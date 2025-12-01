from django.contrib.auth.decorators import login_required
from django.db import DatabaseError
from django.http import JsonResponse
from django.utils import timezone

from django.db.models import Q

from notifications.models import NotificationRecipient, Notification
from notifications.utils import create_notification
from django.contrib.auth import get_user_model

User = get_user_model()


@login_required
def list_notifications(request):
    """
    Return the latest notifications plus a safe unread counter.
    Avoid boolean filters in queries that Djongo would translate
    into problematic NOT clauses by counting unread items in Python.
    """
    notifications_payload = []
    unread_count = 0

    try:
        user_role = (getattr(request.user, 'role', '') or '').upper()

        # Ensure recipients exist for role/ALL/user-targeted notifications
        try:
            candidate_notifs = Notification.objects.filter(
                Q(role_target=Notification.ROLE_ALL)
                | Q(role_target=user_role)
                | Q(user_target=request.user)
            )
            missing = []
            existing_ids = set(
                NotificationRecipient.objects.filter(user=request.user)
                .values_list('notification_id', flat=True)
            )
            for notif in candidate_notifs:
                if notif.id not in existing_ids:
                    missing.append(
                        NotificationRecipient(notification=notif, user=request.user)
                    )
            if missing:
                NotificationRecipient.objects.bulk_create(missing, ignore_conflicts=True)
        except DatabaseError:
            pass

        recipients_qs = NotificationRecipient.objects.filter(user=request.user)\
            .exclude(notification__title='Welcome')\
            .select_related('notification')\
            .order_by('-notification__created_at', '-id')

        # Customers should only see coin transaction notifications
        if user_role == 'CUSTOMER':
            recipients_qs = recipients_qs.filter(notification__related_model='CoinTransaction')

        recipients = list(recipients_qs[:20])
        unread_flags = recipients_qs.values_list('is_read', flat=True)
        unread_count = sum(1 for flag in unread_flags if not flag)
    except DatabaseError:
        recipients = []
        unread_count = 0

    for receipt in recipients:
        notif = receipt.notification
        ts = notif.created_at
        try:
            ts = timezone.localtime(ts)
        except Exception:
            pass
        notifications_payload.append({
            'id': receipt.id,
            'title': notif.title,
            'message': notif.message,
            'url': notif.url,
            'created_at': ts.strftime('%b %d, %H:%M') if ts else '',
            'is_read': receipt.is_read,
        })
    return JsonResponse({'notifications': notifications_payload, 'unread_count': unread_count})


@login_required
def mark_notification_read(request, pk):
    if request.method != 'POST':
        return JsonResponse({'status': 'error'}, status=405)
    try:
        receipt = NotificationRecipient.objects.get(pk=pk, user=request.user)
    except NotificationRecipient.DoesNotExist:
        return JsonResponse({'status': 'error'}, status=404)

    if not receipt.is_read:
        receipt.is_read = True
        receipt.read_at = timezone.now()
        receipt.save(update_fields=['is_read', 'read_at'])
    return JsonResponse({'status': 'ok'})


@login_required
def mark_all_notifications_read(request):
    if request.method != 'POST':
        return JsonResponse({'status': 'error'}, status=405)
    # Djongo cannot translate the NOT boolean filter inside an UPDATE statement,
    # so we fall back to updating row-by-row in Python.
    recipients = list(NotificationRecipient.objects.filter(user=request.user))
    for receipt in recipients:
        if receipt.is_read:
            continue
        receipt.is_read = True
        receipt.read_at = timezone.now()
        receipt.save(update_fields=['is_read', 'read_at'])
    return JsonResponse({'status': 'ok'})
