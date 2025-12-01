from typing import Iterable, Optional

from django.contrib.auth import get_user_model
from django.db import transaction
from django.urls import reverse

from notifications.models import Notification, NotificationRecipient
from superadmin.models import Announcement
from holidays.models import Holiday

User = get_user_model()


def _create_recipients(notification, users: Iterable[User]):
    recipients = [
        NotificationRecipient(notification=notification, user=user)
        for user in users
    ]
    NotificationRecipient.objects.bulk_create(recipients, ignore_conflicts=True)


@transaction.atomic
def create_notification(*, title: str, message: str = '', url: str = '', role_target: Optional[str] = None,
                        users: Optional[Iterable[User]] = None, related_model: str = '', related_object_id: str = '',
                        user_target: Optional[User] = None):
    notification = Notification.objects.create(
        title=title,
        message=message,
        url=url,
        role_target=role_target,
        user_target=user_target,
        related_model=related_model,
        related_object_id=related_object_id,
    )

    recipient_users = set(users or [])
    if role_target in (Notification.ROLE_MARKETING, Notification.ROLE_SUPERADMIN):
        qs = User.objects.filter(role=role_target)
        recipient_users.update(qs)
    elif role_target == Notification.ROLE_ALL:
        recipient_users.update(User.objects.all())

    if user_target:
        recipient_users.add(user_target)

    _create_recipients(notification, recipient_users)
    return notification


def notify_superadmins_new_job(job):
    message = f'Marketing submitted job {job.job_id}.'
    url = reverse('superadmin:job_detail', args=[job.job_id])
    create_notification(
        title='New Job Submitted',
        message=message,
        url=url,
        role_target=Notification.ROLE_SUPERADMIN,
        related_model='Job',
        related_object_id=str(job.id),
    )


def notify_marketing_job_approved(job):
    if not hasattr(job, 'created_by') or not job.created_by:
        return
    message = f'Your job {job.job_id} was approved.'
    url = reverse('marketing:all_projects')
    create_notification(
        title='Job Approved',
        message=message,
        url=url,
        users=[job.created_by],
        user_target=job.created_by,
        related_model='Job',
        related_object_id=str(job.id),
    )


def notify_marketing_rework_completed(rework):
    job = getattr(rework, 'job', None)
    creator = getattr(job, 'created_by', None) if job else None
    if not creator:
        return
    message = f'Rework completed for {job.job_id}.'
    url = reverse('marketing:job_rework_history', args=[job.job_id])
    create_notification(
        title='Rework Completed',
        message=message,
        url=url,
        users=[creator],
        user_target=creator,
        related_model='JobReworkRequest',
        related_object_id=str(rework.id),
    )


def notify_announcement_created(announcement):
    role_target = (
        Notification.ROLE_ALL if announcement.visibility == Announcement.VISIBILITY_ALL
        else announcement.visibility
    )
    create_notification(
        title=announcement.title,
        message=(getattr(announcement, 'content', '') or announcement.title),
        url=reverse('superadmin:announcement_list'),
        role_target=role_target,
        related_model='Announcement',
        related_object_id=str(announcement.id),
    )


def notify_holiday_created(holiday):
    applies = (holiday.applies_to or '').upper()
    role_target = Notification.ROLE_ALL if applies == 'ALL' else None
    users = None
    if applies and applies != 'ALL':
        users = User.objects.filter(role__in=[role.strip().upper() for role in applies.split(',') if role.strip()])
    create_notification(
        title=f'Holiday: {holiday.title}',
        message=holiday.notes or holiday.title,
        url=reverse('holidays:list'),
        role_target=role_target,
        users=users,
        related_model='Holiday',
        related_object_id=str(holiday.id),
    )


def notify_ticket_created(ticket):
    create_notification(
        title='Ticket Submitted',
        message=f'Ticket {ticket.ticket_id} created',
        url=reverse('tickets:superadmin-ticket-list'),
        role_target=Notification.ROLE_SUPERADMIN,
        related_model='Ticket',
        related_object_id=str(ticket.id),
    )


def notify_user_approval_pending(user):
    create_notification(
        title='User Approval Requested',
        message=f'{user.get_full_name()} pending approval',
        url=reverse('approvals:user_approval_list'),
        role_target=Notification.ROLE_SUPERADMIN,
        related_model='User',
        related_object_id=str(user.id),
    )


def notify_profile_update_pending(profile_request):
    create_notification(
        title='Profile Update Requested',
        message=f'{profile_request.user.get_full_name()} submitted profile update',
        url=reverse('approvals:profile_update_list'),
        role_target=Notification.ROLE_SUPERADMIN,
        related_model='ProfileUpdateRequest',
        related_object_id=str(profile_request.id),
    )
