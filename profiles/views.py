from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.core.mail import send_mail
from django.conf import settings
from accounts.models import User
from .models import Profile, ProfileUpdateRequest
from .forms import ProfileUpdateRequestForm, CustomPasswordChangeForm, SuperAdminProfileUpdateForm
from auditlog.utils import log_action

@login_required
def profile_view(request):
    """View user profile"""
    user = request.user
    
    # Create profile if doesn't exist
    profile, created = Profile.objects.get_or_create(user=user)
    
    context = {
        'user': user,
        'profile': profile,
    }
    
    return render(request, 'profiles/profile.html', context)

@login_required
def request_profile_update(request):
    """Submit profile update request"""
    # ✅ ensure we have a Profile object (where profile_picture actually lives)
    profile, _ = Profile.objects.get_or_create(user=request.user)
    
    # role check (keep your marketing restriction, but robust)
    if str(getattr(request.user, 'role', '')).upper() != 'MARKETING':
        messages.error(request, 'This feature is only available for marketing team.')
        return redirect('profiles:profile')
    
    if request.method == 'POST':
        form = ProfileUpdateRequestForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            request_type = form.cleaned_data['request_type']
            
            print(f"=== PROFILE UPDATE REQUEST DEBUG ===")
            print(f"Request Type: {request_type}")
            print(f"Files in request: {request.FILES}")
            
            # Get current value
            if request_type == 'profile_picture':
                # ✅ use profile.profile_picture instead of request.user.profile_picture
                current_value = (
                    str(profile.profile_picture)
                    if getattr(profile, 'profile_picture', None)
                    else 'No picture'
                )
                updated_value = 'New picture uploaded'
                new_picture = form.cleaned_data.get('new_profile_picture')
                
                print(f"New picture from form: {new_picture}")
                print(f"New picture name: {new_picture.name if new_picture else 'None'}")
                print(f"New picture size: {new_picture.size if new_picture else 'None'}")
                
                if not new_picture:
                    messages.error(request, 'Please select a profile picture to upload.')
                    return redirect('profiles:update_request')
            
            elif request_type == 'whatsapp_number':
                current_value = request.user.get_whatsapp_full()
                country_code = form.cleaned_data['whatsapp_country_code']
                number = form.cleaned_data['whatsapp_number']
                updated_value = f"{country_code.country_code}{number}"
                new_picture = None
            
            else:
                current_value = getattr(request.user, request_type)
                updated_value = form.cleaned_data['updated_value']
                new_picture = None
            
            # Create update request
            update_request = ProfileUpdateRequest.objects.create(
                user=request.user,
                request_type=request_type,
                current_value=current_value,
                updated_value=updated_value,
                new_profile_picture=new_picture,
            )
            
            print(f"Created update request ID: {update_request.id}")
            if request_type == 'profile_picture':
                print(f"Saved picture path: {update_request.new_profile_picture}")
                print(f"Picture URL: {update_request.new_profile_picture.url if update_request.new_profile_picture else 'None'}")
            
            # Log the action (matches log_action signature)
            log_action(
                user=request.user,
                action_type='PROFILE_UPDATE_REQUEST',
                target_object=update_request,
                description=f'Profile update requested: {request_type}',
                request=request,
            )
            
            # Djongo-safe superadmin query (no is_active=True in DB filter)
            admins_qs = User.objects.filter(role='SUPERADMIN')
            superadmins = [admin for admin in admins_qs if admin.is_active]
            
            # Notify super admin
            for admin in superadmins:
                try:
                    send_mail(
                        subject='New Profile Update Request',
                        message=(
                            f'{request.user.get_full_name()} has requested to update '
                            f'their {request_type}.\n\nPlease review and approve/reject.'
                        ),
                        from_email=settings.EMAIL_HOST_USER,
                        recipient_list=[admin.email],
                        fail_silently=True,
                    )
                except Exception as e:
                    print(f"Error sending email: {e}")
            
            messages.success(
                request,
                'Profile update request submitted successfully. '
                'Please wait for admin approval.'
            )
            return redirect('profiles:profile')
        else:
            messages.error(request, 'Please correct the errors below.')
            print(f"Form errors: {form.errors}")
    else:
        form = ProfileUpdateRequestForm(user=request.user)
    
    # Get pending requests
    pending_requests = ProfileUpdateRequest.objects.filter(
        user=request.user,
        status='PENDING'
    ).order_by('-created_at')
    
    context = {
        'form': form,
        'pending_requests': pending_requests,
        'profile': profile,
    }
    
    return render(request, 'profiles/profile_update_request.html', context)



@login_required
def change_password_view(request):
    """Allow users to change their own password"""
    if request.method == 'POST':
        form = CustomPasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)  # Keep user logged in
            
            # Log the action
            log_action(
                user=request.user,
                action_type='PASSWORD_CHANGE',
                description='User changed password',
                target_model='User',
                target_id=str(request.user.id)
            )
            
            messages.success(request, 'Your password was successfully updated!')
            return redirect('profiles:profile')

        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = CustomPasswordChangeForm(request.user)
    
    return render(request, 'profiles/change_password.html', {'form': form})


@login_required
def superadmin_profile_update(request):
    """SuperAdmin profile update (can update directly with notes for email/WhatsApp)"""
    if request.user.role != 'superadmin':
        messages.error(request, 'Access denied.')
        return redirect('profiles:profile')
    
    if request.method == 'POST':
        form = SuperAdminProfileUpdateForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            email_notes = form.cleaned_data.get('email_notes')
            whatsapp_notes = form.cleaned_data.get('whatsapp_notes')
            
            user = form.save()
            
            # Log the action with notes
            notes_log = []
            if email_notes:
                notes_log.append(f"Email changed. Reason: {email_notes}")
            if whatsapp_notes:
                notes_log.append(f"WhatsApp changed. Reason: {whatsapp_notes}")
            
            description = 'SuperAdmin updated profile'
            if notes_log:
                description += '. ' + ' | '.join(notes_log)
            
            log_action(
                user=request.user,
                action_type='PROFILE_UPDATE_APPROVED',
                description=description,
                target_model='User',
                target_id=str(request.user.id)
            )
            
            messages.success(request, 'Profile updated successfully!')
            return redirect('profiles:profile')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = SuperAdminProfileUpdateForm(instance=request.user)
    
    return render(request, 'profiles/superadmin_profile_update.html', {'form': form})