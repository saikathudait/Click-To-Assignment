import json
from datetime import datetime

from django.http import JsonResponse
from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import PageVisit


def _parse_iso_dt(value):
    """Parse ISO datetime safely with timezone awareness."""
    if not value:
        return None
    if isinstance(value, (int, float)):
        try:
            return timezone.make_aware(datetime.fromtimestamp(value / 1000.0))
        except Exception:
            return None
    try:
        dt = parse_datetime(value)
        if dt is None:
            dt = datetime.fromisoformat(value)
    except Exception:
        return None
    if timezone.is_naive(dt):
        try:
            dt = timezone.make_aware(dt, timezone.get_default_timezone())
        except Exception:
            pass
    return dt


@csrf_exempt
@never_cache
@require_POST
def track_page_visit(request):
    """Record active/idle time for a single page visit."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)

    # Derive session key without mutating session to avoid forced-update errors
    try:
        sess_key = request.session.session_key
        session_exists = bool(sess_key and request.session.exists(sess_key))
    except Exception:
        sess_key, session_exists = None, False

    # Prevent SessionMiddleware from saving on this endpoint
    try:
        request.session.modified = False
        request.session.accessed = False
        request.session.save = lambda *args, **kwargs: None  # type: ignore
    except Exception:
        pass

    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except Exception:
        payload = {}

    session_id = (payload.get('session_id') or '').strip()
    page_path = (payload.get('page_path') or '').strip()
    page_name = (payload.get('page_name') or '').strip()
    started_at = _parse_iso_dt(payload.get('started_at'))
    ended_at = _parse_iso_dt(payload.get('ended_at'))

    def _clean_seconds(value):
        try:
            return max(0, int(round(float(value or 0))))
        except Exception:
            return 0

    active_seconds = _clean_seconds(payload.get('active_seconds'))
    idle_seconds = _clean_seconds(payload.get('idle_seconds'))

    if not session_id:
        session_id = sess_key if session_exists else (request.COOKIES.get(settings.SESSION_COOKIE_NAME, '') or f"anon-{int(timezone.now().timestamp() * 1000)}")
    if not page_path:
        page_path = request.META.get('HTTP_REFERER', '') or '/'
    now_ts = timezone.now()
    started_at = started_at or now_ts
    ended_at = ended_at or now_ts
    if ended_at < started_at:
        ended_at = started_at

    try:
        PageVisit.objects.create(
            user=request.user,
            session_id=session_id[:64],
            page_path=page_path[:512],
            page_name=page_name[:255],
            started_at=started_at,
            ended_at=ended_at,
            active_seconds=active_seconds,
            idle_seconds=idle_seconds,
        )
    except Exception as exc:
        return JsonResponse({'error': f'Could not record visit: {exc}'}, status=500)

    return JsonResponse({'success': True})
