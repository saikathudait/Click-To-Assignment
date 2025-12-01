from django.utils.deprecation import MiddlewareMixin
from .utils import log_action

class AuditLogMiddleware(MiddlewareMixin):
    """Middleware to automatically log certain user actions"""

    def __init__(self, get_response=None):
        super().__init__(get_response)

    def process_response(self, request, response):
        if hasattr(request, 'user') and request.user.is_authenticated:
            if request.method == 'POST':
                path = request.path
            if request.path.endswith('/login/') and response.status_code == 302:
                log_action(request.user, 'LOGIN', description='User logged in', request=request)
            elif request.path.endswith('/logout/') and response.status_code == 302:
                log_action(request.user, 'LOGOUT', description='User logged out', request=request)

        return response
    
    
    
def get_client_ip(request):
    """Get client IP address from request"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip