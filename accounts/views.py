from django.shortcuts import render, redirect
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .forms import SignUpForm, LoginForm
from .models import User
from django.conf import settings
from auditlog.utils import log_action
from django.core.mail import send_mail


def signup_view(request):
    if request.user.is_authenticated:
        return redirect_after_login(request.user)
    
    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            # New signups are customers and auto-approved
            user.is_approved = True
            user.role = 'CUSTOMER'
            user.save()
            
            
            # Log the action
            log_action(
                user=None,
                action_type='USER_REGISTRATION',
                target_object=user,
                description=f'New user registered: {user.email}'
            )
            
            # Send welcome email (no approval needed)
            send_mail(
                subject='Registration Successful',
                message=f'Dear {user.first_name},\n\nYour registration was successful. You can now log in using your credentials.\n\nThank you.',
                from_email=settings.EMAIL_HOST_USER,
                recipient_list=[user.email],
                fail_silently=True,
            )

            messages.success(request, 'Registration successful! You can now log in.')
            return redirect('accounts:login')
        
        
    else:
        form = SignUpForm()
    
    return render(request, 'accounts/signup.html', {'form': form})

def login_view(request):
    if request.user.is_authenticated:
        if request.user.role == 'SUPERADMIN':
            return redirect('superadmin:welcome')
        elif request.user.role == 'CUSTOMER':
            return redirect('customer:welcome')
        else:
            return redirect('marketing:welcome')
    
    if request.method == 'POST':
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            email = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(request, username=email, password=password)
            
            if user is not None:
                if not user.is_approved:
                    messages.error(request, 'Your account is pending approval.')
                    return redirect('accounts:wait_approval')
                
                login(request, user)
                
                # Redirect based on role
                if user.role == 'SUPERADMIN':
                    return redirect('superadmin:welcome')
                elif user.role == 'CUSTOMER':
                    return redirect('customer:welcome')
                else:
                    return redirect('marketing:welcome')
            else:
                messages.error(request, 'Invalid email or password.')
    else:
        form = LoginForm()
    
    return render(request, 'accounts/login.html', {'form': form})

def redirect_after_login(user):
    """Send user to correct dashboard based on role."""
    if user.role == 'SUPERADMIN':
        return redirect('superadmin:welcome')
    if user.role == 'CUSTOMER':
        return redirect('customer:welcome')
    else:
        return redirect('marketing:welcome')


@login_required
def logout_view(request):
    """User logout view"""
    user_name = request.user.first_name
    
    # Log the action
    log_action(
    request.user,          # user
    'USER_LOGOUT',         # action_type
    None,                  # obj (no specific object here)
    'User logged out',     # description
    request=request,       # request (optional)
    )
    
    logout(request)
    messages.success(request, f'Goodbye, {user_name}! You have been logged out.')
    return redirect('accounts:login')


@login_required
def login_redirect_view(request):
    """Used by LOGIN_REDIRECT_URL to send user to their role dashboard."""
    return redirect_after_login(request.user)

def wait_approval_view(request):
    return render(request, 'accounts/wait_for_approval.html')

@login_required
def dashboard_redirect(request):
    """Redirect to appropriate dashboard based on user role"""
    return redirect_after_login(request.user)
