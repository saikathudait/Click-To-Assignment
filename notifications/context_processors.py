from django.db import DatabaseError

from notifications.models import NotificationRecipient


def notifications_data(request):
    """
    Provide a lightweight unread count for the notification bell.
    Djongo struggles with boolean filters inside aggregation/count queries,
    so we keep the query simple (filter only by user) and calculate the
    unread total in Python. Any database failure simply returns zero so
    regular pages keep loading.
    """
    if not request.user.is_authenticated:
        return {}

    unread = 0
    try:
        # Pull only the is_read column to minimize payload, then count locally.
        flags = NotificationRecipient.objects.filter(
            user=request.user
        ).values_list('is_read', flat=True)
        unread = sum(1 for is_read in flags if not is_read)
    except DatabaseError:
        unread = 0

    return {
        'notification_unread_count': unread,
    }
