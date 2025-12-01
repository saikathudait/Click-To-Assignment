from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from .models import ActionLog, JobActionLog

def log_action(user, action_type, target_object=None, description='', request=None):
    """
    Log an action performed by a user
    
    Args:
        user: User who performed the action
        action_type: Type of action (CREATE, UPDATE, DELETE, etc.)
        target_object: The object affected by the action
        description: Description of the action
        request: HTTP request object (optional, for IP and user agent)
    """
    actor_name = ''
    actor_email = ''
    if user:
        actor_email = getattr(user, 'email', '') or ''
        full_name = getattr(user, 'get_full_name', lambda: '')()
        actor_name = full_name or getattr(user, 'username', '') or actor_email

    log_data = {
        'user': user,
        'user_email': actor_email,
        'user_name': actor_name,
        'action_type': action_type,
        'description': description,
    }

    if target_object:
        content_type = ContentType.objects.get_for_model(target_object)
        log_data['content_type'] = content_type
        log_data['object_id'] = str(target_object.pk)
        log_data['target_model'] = target_object.__class__.__name__
        log_data['target_id'] = str(target_object.pk)

    if request and hasattr(request, 'META'):
        log_data['ip_address'] = get_client_ip(request)
        log_data['user_agent'] = request.META.get('HTTP_USER_AGENT', '')[:500]
    
    ActionLog.objects.create(**log_data)

def get_client_ip(request):
    """Get client IP address from request"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def log_job_action(job_id, system_id, user, action, field_changed=None, old_value=None, new_value=None):
    """
    Utility function to log job-specific actions
    """
    try:
        JobActionLog.objects.create(
            job_id=job_id,
            system_id=system_id,
            user=user,
            user_email=user.email if user else 'system@clicktoassignment.com',
            action=action,
            field_changed=field_changed,
            old_value=old_value,
            new_value=new_value,
            timestamp=timezone.now()
        )
    except Exception as e:
        print(f"Failed to log job action: {e}")
        
        
def get_user_actions(user, limit=50):
    """Get recent actions by a user"""
    return ActionLog.objects.filter(user=user).order_by('-timestamp')[:limit]


def get_job_history(job_id):
    """Get complete history of a job"""
    return JobActionLog.objects.filter(job_id=job_id).order_by('-timestamp')


def get_recent_actions(limit=100):
    """Get recent actions across all users"""
    return ActionLog.objects.all().order_by('-timestamp')[:limit]


