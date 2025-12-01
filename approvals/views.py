from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from django.core.paginator import Paginator
import secrets
import string

from accounts.models import User
from approvals.models import UserApprovalLog
from profiles.models import ProfileUpdateRequest, Profile  # ensure Profile imported
from auditlog.utils import log_action
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from notifications.utils import notify_user_approval_pending, notify_profile_update_pending, create_notification
from django.urls import reverse_lazy


def _paginate_items(request, items, page_param='page', per_page=20):
    paginator = Paginator(items, per_page)
    page_number = request.GET.get(page_param)
    page_obj = paginator.get_page(page_number)
    params = request.GET.copy()
    if page_param in params:
        params.pop(page_param)
    pagination_query = params.urlencode()
    pagination_base = f'?{pagination_query}&' if pagination_query else '?'
    return page_obj, pagination_base


def superadmin_required(view_func):
    """Decorator to ensure only superadmin can access"""
    def wrapper(request, *args, **kwargs):
        if request.user.role != 'SUPERADMIN':
            messages.error(request, 'Access denied. SuperAdmin only.')
            return redirect('superadmin:dashboard')
        return view_func(request, *args, **kwargs)
    return wrapper


def _generate_random_password(length=12):
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def _derive_names_from_email(email: str):
    local = (email or '').split('@')[0]
    tokens = [t for t in local.replace('.', ' ').replace('_', ' ').replace('-', ' ').split() if t]
    first = tokens[0].title() if tokens else 'New'
    last = tokens[1].title() if len(tokens) > 1 else 'Employee'
    return first, last


@login_required
@superadmin_required
def user_approval_list(request):
    """List all user approval requests (djongo-safe, no boolean filters in SQL)."""
    filter_type = request.GET.get('filter', 'all')

    # 🚫 Avoid boolean filters in SQL like filter(is_approved=True/False)
    # ✅ Get all users once, then filter in Python
    all_users = list(User.objects.all())

    if filter_type == 'pending':
        # active but not approved
        users = [u for u in all_users if u.is_active and not u.is_approved]
    elif filter_type == 'approved':
        # approved (you can decide whether to also require is_active)
        users = [u for u in all_users if u.is_approved]
    elif filter_type == 'rejected':
        # inactive users
        users = [u for u in all_users if not u.is_active]
    elif filter_type == 'superadmin':
        users = [u for u in all_users if getattr(u, 'role', '').upper() == 'SUPERADMIN']
    elif filter_type == 'marketing':
        users = [u for u in all_users if getattr(u, 'role', '').upper() == 'MARKETING']
    elif filter_type == 'customer':
        users = [u for u in all_users if getattr(u, 'role', '').upper() == 'CUSTOMER']
    else:
        users = all_users

    # Statistics (all in Python, no boolean WHERE in DB)
    total_requests = len(all_users)
    total_approved = sum(1 for u in all_users if u.is_approved)
    total_rejected = sum(1 for u in all_users if not u.is_active)
    pending_action = sum(1 for u in all_users if u.is_active and not u.is_approved)
    total_superadmins = sum(1 for u in all_users if getattr(u, 'role', '').upper() == 'SUPERADMIN')
    total_marketing = sum(1 for u in all_users if getattr(u, 'role', '').upper() == 'MARKETING')
    total_customers = sum(1 for u in all_users if getattr(u, 'role', '').upper() == 'CUSTOMER')

    page_obj, pagination_base = _paginate_items(request, users, 'page')
    paginated_users = page_obj.object_list

    context = {
        'users': paginated_users,
        'total_requests': total_requests,
        'total_approved': total_approved,
        'total_rejected': total_rejected,
        'pending_action': pending_action,
        'total_superadmins': total_superadmins,
        'total_marketing': total_marketing,
        'total_customers': total_customers,
        'filter_type': filter_type,
        'page_obj': page_obj,
        'pagination_base': pagination_base,
        'role_choices': User.ROLE_CHOICES,
    }

    return render(request, 'approvals/user_approval_list.html', context)


@login_required
@superadmin_required
def user_detail(request, user_id):
    user = get_object_or_404(User, id=user_id)
    context = {
        'user_obj': user,
    }
    return render(request, 'approvals/user_detail.html', context)


@login_required
@superadmin_required
def user_reset_password(request, user_id):
    user = get_object_or_404(User, id=user_id)
    if request.method != 'POST':
        messages.error(request, 'Invalid request method.')
        return redirect('approvals:user_detail', user_id=user.id)

    new_password = (request.POST.get('password') or '').strip()
    if not new_password:
        new_password = _generate_random_password()
        generated = True
    else:
        generated = False

    user.set_password(new_password)
    user.save(update_fields=['password'])
    log_action(request.user, 'PASSWORD_RESET', user, f'Password reset for {user.email}', str(user.id))

    try:
        send_mail(
            subject='Your password has been reset',
            message=(
                f'Dear {user.first_name},\n\n'
                f'An administrator has reset your password. '
                f'Your new password is: {new_password}\n\n'
                f'Please log in and change it if needed.\n\n'
                f'Thank you.'
            ),
            from_email=settings.EMAIL_HOST_USER,
            recipient_list=[user.email],
            fail_silently=True,
        )
    except Exception:
        pass

    messages.success(request, f"Password reset. New password: {new_password if generated else 'Updated as provided.'}")
    return redirect('approvals:user_detail', user_id=user.id)


@login_required
@superadmin_required
def create_employee(request):
    """Allow superadmin to add a new employee directly from the approval page."""
    if request.method != 'POST':
        messages.error(request, 'Please submit the form to add a new employee.')
        return redirect('approvals:user_approval_list')

    email = (request.POST.get('email') or '').strip().lower()
    role = (request.POST.get('role') or 'MARKETING').upper()
    password = request.POST.get('password') or ''

    if not email:
        messages.error(request, 'Email is required to create an employee.')
        return redirect('approvals:user_approval_list')

    valid_roles = {value for value, _ in User.ROLE_CHOICES}
    if role not in valid_roles:
        role = 'MARKETING'

    if User.objects.filter(email__iexact=email).exists():
        messages.error(request, 'A user with this email already exists.')
        return redirect('approvals:user_approval_list')

    generated_password = False
    if not password:
        password = _generate_random_password()
        generated_password = True

    first_name, last_name = _derive_names_from_email(email)
    now = timezone.now()
    user = User.objects.create_user(
        email=email,
        password=password,
        first_name=first_name,
        last_name=last_name,
        whatsapp_no='',
        whatsapp_country_code='+91',
        last_qualification='',
        role=role,
        is_approved=True,
        is_active=True,
        is_staff=(role == 'SUPERADMIN'),
        is_superuser=(role == 'SUPERADMIN'),
        role_locked=True,
        approved_by=request.user,
        approved_at=now,
    )
    if not getattr(user, 'employee_id', None):
        user.generate_employee_id()
        user.save(update_fields=['employee_id'])

    log_action(request.user, 'CREATE', user, f'Created employee {user.email}', str(user.id))
    messages.success(
        request,
        f"Employee created ({user.email}) with role {user.get_role_display()}. "
        f"Password: {password if generated_password else 'Using provided password.'}"
    )
    return redirect('approvals:user_approval_list')


@login_required
@superadmin_required
def approve_user(request, user_id):
    """Approve a user registration"""
    user = get_object_or_404(User, id=user_id)

    if user.is_approved:
        messages.info(request, 'User is already approved.')
        return redirect('approvals:user_approval_list')

    if request.method != 'POST':
        messages.error(request, 'Invalid request method. Please submit the approval form.')
        return redirect('approvals:user_approval_list')

    selected_role = request.POST.get('role') or 'MARKETING'
    valid_roles = dict(User.ROLE_CHOICES).keys()
    if selected_role not in valid_roles:
        selected_role = 'MARKETING'

    user.role = selected_role
    user.is_staff = selected_role == 'SUPERADMIN'
    user.is_approved = True
    user.approved_by = request.user
    user.approved_at = timezone.now()
    user.role_locked = True
    user.generate_employee_id()
    user.save(update_fields=['role', 'is_staff', 'is_approved', 'approved_by', 'approved_at', 'role_locked', 'employee_id'])
    try:
        create_notification(
            title='User Approved',
            message=f'{user.get_full_name()} approved',
            url=reverse_lazy('approvals:user_approval_list'),
            role_target='SUPERADMIN',
            related_model='User',
            related_object_id=str(user.id),
        )
    except Exception:
        pass

    # Log the approval
    UserApprovalLog.objects.create(
        user=user,
        action='approved',
        approved_by=request.user
    )

    log_action(request.user, 'APPROVE', user, f'Approved user {user.email}', str(user.id))

    # Send email notification
    try:
        send_mail(
            'Account Approved - Click to Assignment',
            (
                f'Dear {user.first_name},\n\n'
                f'Your account has been approved. You can now login with your credentials.\n\n'
                f'Your Employee ID: {user.employee_id}\n\n'
                f'Best regards,\nClick to Assignment Team'
            ),
            settings.EMAIL_HOST_USER,
            [user.email],
            fail_silently=True,
        )
    except Exception:
        pass

    messages.success(
        request,
        f'User {user.get_full_name()} approved successfully! Employee ID: {user.employee_id}'
    )
    return redirect('approvals:user_approval_list')


@login_required
@superadmin_required
def reject_user(request, user_id):
    """Reject a user registration"""
    user = get_object_or_404(User, id=user_id)
    
    if user.is_approved:
        messages.warning(request, 'Cannot reject an already approved user.')
        return redirect('approvals:user_approval_list')

    user.is_active = False
    user.save()
    try:
        create_notification(
            title='User Rejected',
            message=f'{user.get_full_name()} rejected',
            url=reverse_lazy('approvals:user_approval_list'),
            role_target='SUPERADMIN',
            related_model='User',
            related_object_id=str(user.id),
        )
    except Exception:
        pass
    
    # Log the rejection
    UserApprovalLog.objects.create(
        user=user,
        action='rejected',
        approved_by=request.user
    )

    log_action(request.user, 'REJECT', user, f'Rejected user {user.email}', str(user.id))

    # Send email notification
    try:
        send_mail(
            'Account Registration - Click to Assignment',
            (
                f'Dear {user.first_name},\n\n'
                f'We regret to inform you that your account registration has not been approved at this time.\n\n'
                f'If you have any questions, please contact our support team.\n\n'
                f'Best regards,\nClick to Assignment Team'
            ),
            settings.EMAIL_HOST_USER,
            [user.email],
            fail_silently=True,
        )
    except Exception:
        pass

    messages.warning(request, f'User {user.get_full_name()} has been rejected.')
    return redirect('approvals:user_approval_list')


@login_required
@superadmin_required
def profile_update_approval_list(request):
    """List all profile update requests"""
    filter_type = request.GET.get('filter', 'all')

    if filter_type == 'pending':
        requests_qs = ProfileUpdateRequest.objects.filter(status='PENDING')
    elif filter_type == 'approved':
        requests_qs = ProfileUpdateRequest.objects.filter(status='APPROVED')
    elif filter_type == 'rejected':
        requests_qs = ProfileUpdateRequest.objects.filter(status='REJECTED')
    else:
        requests_qs = ProfileUpdateRequest.objects.all()
        
    # Base queryset
    requests = ProfileUpdateRequest.objects.all()

    # Calculate statistics (status is CharField, djongo is OK with this)
    total_requests = ProfileUpdateRequest.objects.count()
    pending_requests = ProfileUpdateRequest.objects.filter(status='PENDING').count()
    total_approved = ProfileUpdateRequest.objects.filter(status='APPROVED').count()
    total_rejected = ProfileUpdateRequest.objects.filter(status='REJECTED').count()

    page_obj, pagination_base = _paginate_items(request, list(requests_qs), 'page')

    context = {
        'requests': page_obj.object_list,
        'total_requests': total_requests,
        'pending_requests': pending_requests,
        'total_approved': total_approved,
        'total_rejected': total_rejected,
        'filter_type': filter_type,
        'page_obj': page_obj,
        'pagination_base': pagination_base,
    }

    return render(request, 'approvals/profile_update_approval.html', context)


@login_required
@superadmin_required
def approve_profile_update(request, request_id):
    """Approve a profile update request and apply the change to User/Profile."""
    import os
    from django.core.files.base import ContentFile
    from django.core.files import File
    from django.utils import timezone as tz
    
    update_request = get_object_or_404(ProfileUpdateRequest, id=request_id)
    
    current_status = str(update_request.status or '').upper()
    if current_status != 'PENDING':
        messages.info(request, 'This request has already been processed.')
        return redirect('approvals:profile_update_list')
    
    user = update_request.user
    profile, _ = Profile.objects.get_or_create(user=user)
    
    request_type = str(update_request.request_type or '').lower()
    updated_value = update_request.updated_value
    new_profile_picture = update_request.new_profile_picture
    
    try:
        if request_type == 'profile_picture':
            if not new_profile_picture:
                messages.error(request, 'No profile picture file found in the request.')
                return redirect('approvals:profile_update_list')
            
            # Delete old profile picture if exists
            if profile.profile_picture:
                try:
                    profile.profile_picture.delete(save=False)
                except Exception:
                    pass
            
            # Generate unique filename with timestamp
            timestamp = tz.now().strftime('%Y%m%d_%H%M%S')
            file_ext = os.path.splitext(new_profile_picture.name)[1].lower()
            if not file_ext:
                file_ext = '.jpg'
            unique_filename = f"profile_{user.id}_{timestamp}{file_ext}"
            
            # Read and save the file
            try:
                # Try to open and read the file
                if hasattr(new_profile_picture, 'open'):
                    new_profile_picture.open('rb')
                elif hasattr(new_profile_picture, 'seek'):
                    new_profile_picture.seek(0)
                
                file_content = new_profile_picture.read()
                
                if len(file_content) == 0:
                    messages.error(request, 'Profile picture file is empty.')
                    return redirect('approvals:profile_update_list')
                
                # Save the file to profile
                profile.profile_picture.save(
                    unique_filename,
                    ContentFile(file_content),
                    save=True
                )
                
                # Close the file if needed
                if hasattr(new_profile_picture, 'close'):
                    new_profile_picture.close()
                
            except Exception as e:
                messages.error(request, f'Error updating profile picture: {str(e)}')
                return redirect('approvals:profile_update_list')
        
        elif request_type == 'first_name':
            user.first_name = updated_value or user.first_name
            user.save()
        
        elif request_type == 'last_name':
            user.last_name = updated_value or user.last_name
            user.save()
        
        elif request_type == 'email':
            user.email = updated_value or user.email
            user.save()
        
        elif request_type == 'whatsapp_number':
            user.whatsapp_no = updated_value or user.whatsapp_no
            user.save()
        
        elif request_type == 'last_qualification':
            user.last_qualification = updated_value or user.last_qualification
            user.save()
    
    except Exception as e:
        messages.error(request, f'Error processing update: {str(e)}')
        return redirect('approvals:profile_update_list')
    
    # Mark request as approved & processed
    update_request.status = 'APPROVED'
    update_request.processed_by = request.user
    update_request.processed_at = timezone.now()
    update_request.save()
    
    # Log the action
    log_action(
        user=request.user,
        action_type='PROFILE_UPDATE_APPROVED',
        target_object=update_request,
        description=f'Profile update approved: {update_request.request_type}',
        request=request,
    )
    try:
        notify_profile_update_pending(update_request)
    except Exception:
        pass
    
    # Send email notification
    try:
        send_mail(
            'Profile Update Approved - Click to Assignment',
            (
                f'Dear {user.first_name},\n\n'
                f'Your profile update request for {update_request.request_type} '
                f'has been approved.\n\n'
                f'Best regards,\nClick to Assignment Team'
            ),
            settings.EMAIL_HOST_USER,
            [user.email],
            fail_silently=True,
        )
    except Exception:
        pass
    
    messages.success(request, f'Profile update request approved for {user.get_full_name()}.')
    return redirect('approvals:profile_update_list')

@login_required
@superadmin_required
def reject_profile_update(request, request_id):
    """Reject a profile update request"""
    update_request = get_object_or_404(ProfileUpdateRequest, id=request_id)

    if update_request.status != 'PENDING':
        messages.info(request, 'This request has already been processed.')
        return redirect('approvals:profile_update_list')
    
    # Get notes if provided
    notes = request.POST.get('notes', '')
    
    # Reject the request
    success = update_request.reject(request.user, notes)

    update_request.status = 'REJECTED'
    update_request.processed_by = request.user
    update_request.processed_at = timezone.now()
    update_request.save()

    log_action(
        request.user,
        'REJECT',
        update_request,
        f'Rejected {update_request.request_type} update for {update_request.user.email}',
    )

    # Send email notification
    try:
        send_mail(
            'Profile Update Request - Click to Assignment',
            (
                f'Dear {update_request.user.first_name},\n\n'
                f'Your profile update request for {update_request.request_type} has not been approved.\n\n'
                f'If you have questions, please contact support.\n\n'
                f'Best regards,\nClick to Assignment Team'
            ),
            settings.EMAIL_HOST_USER,
            [update_request.user.email],
            fail_silently=True,
        )
    except Exception:
        pass

    messages.warning(request, 'Profile update request rejected.')
    return redirect('approvals:profile_update_list')
