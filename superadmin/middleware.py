import json

from django.utils.deprecation import MiddlewareMixin

from .models import ErrorLog


ERROR_MESSAGES = {
    'EFR-001': "Please write a short description of the issue.",
    'EFR-002': "File type not supported. Upload PNG/JPG/PDF only.",
    'EFR-003': "File too large. Max allowed size is X MB.",
    'EFR-004': "Only one attachment is allowed.",
    'EFR-005': "Something went wrong while sending report. Try again.",
    'EFR-006': "You already reported this issue recently.",
    'EFR-007': "Session expired. Please login again.",
    'EFR-101': "You don’t have permission to access this page.",
    'EFR-102': "Your role cannot report issues here.",
    'EFR-201': "Issue not found.",
    'EFR-202': "Invalid status change.",
    'EFR-203': "This issue is already resolved.",
    'EFR-204': "Comment cannot be empty.",
    'EFR-901': "Could not submit report. Please try again.",
    'EFR-902': "Attachment upload failed. Submit without file or try again.",
    'EFR-903': "Issue created, but notify failed.",
    'EFR-904': "Too many reports. Please wait and try again.",
}


class ErrorCodeLoggingMiddleware(MiddlewareMixin):
    """
    Logs known EFR error codes (via ?error_code=EFR-XXX) for audit/visibility.
    """

    def process_view(self, request, view_func, view_args, view_kwargs):
        code = request.GET.get('error_code')
        if not code or code not in ERROR_MESSAGES:
            return None
        try:
            ErrorLog.objects.create(
                code=code,
                message=ERROR_MESSAGES.get(code, ''),
                path=request.path[:512],
                method=request.method,
                user=request.user if getattr(request, 'user', None) and request.user.is_authenticated else None,
                role=(getattr(request, 'user', None).role if getattr(request, 'user', None) else ''),
                meta=json.dumps({
                    'remote_addr': request.META.get('REMOTE_ADDR'),
                    'user_agent': request.META.get('HTTP_USER_AGENT', '')[:255],
                }),
            )
        except Exception:
            # Avoid breaking the request cycle due to logging failures.
            return None
        return None
