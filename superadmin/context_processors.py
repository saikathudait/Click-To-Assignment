from accounts.models import User
from profiles.models import ProfileUpdateRequest
from jobs.models import Job


def notification_counts(request):
    """Add notification counts to template context"""
    context = {}
    
    if request.user.is_authenticated and request.user.role == 'superadmin':
        # Count pending user approvals
        context['pending_user_approvals'] = User.objects.filter(
            role='marketing',
            is_approved=False,
            is_active=True
        ).count()
        
        # Count pending profile update requests
        context['pending_profile_updates'] = ProfileUpdateRequest.objects.filter(
            status='pending'
        ).count()
        
        # Count new jobs (pending approval)
        context['new_jobs_count'] = Job.objects.filter(
            is_approved=False
        ).count()
    
    return context