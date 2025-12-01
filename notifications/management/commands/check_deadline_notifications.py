from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from holidays.models import Holiday
from jobs.models import Job
from notifications.models import Notification
from notifications.utils import create_notification


def _holiday_dates_between(start, end):
    holidays = Holiday.objects.filter(is_active=True, start_date__lte=end, end_date__gte=start)
    dates = set()
    for holiday in holidays:
        current = holiday.start_date
        while current <= holiday.end_date:
            dates.add(current)
            current += timedelta(days=1)
    return dates


def working_days_until(target_date, holidays):
    today = timezone.localdate()
    if target_date <= today:
        return 0
    days = 0
    current = today
    while current < target_date:
        current += timedelta(days=1)
        if current.weekday() >= 5:
            continue
        if current in holidays:
            continue
        days += 1
    return days


class Command(BaseCommand):
    help = 'Generate notifications for jobs nearing deadlines (excluding holidays).'

    def handle(self, *args, **options):
        today = timezone.localdate()
        upcoming = Job.objects.filter(expected_deadline__isnull=False).exclude(status__in=['COMPLETED', 'APPROVED'])
        for job in upcoming:
            deadline = timezone.localtime(job.expected_deadline).date()
            if deadline < today:
                continue
            holidays = _holiday_dates_between(today, deadline)
            working_days = working_days_until(deadline, holidays)
            if working_days > 1:
                continue
            existing = Notification.objects.filter(
                related_model='JobDeadline',
                related_object_id=str(job.id),
            ).exists()
            if existing:
                continue

            message = f'Deadline approaching for job {job.job_id} on {deadline.strftime(\"%b %d\")} (working days left: {working_days}).'
            url = ''
            if job.created_by_id:
                create_notification(
                    title='Deadline Reminder',
                    message=message,
                    url=url,
                    users=[job.created_by],
                    related_model='JobDeadline',
                    related_object_id=str(job.id),
                )
            create_notification(
                title='Deadline Reminder',
                message=message,
                url=url,
                role_target=Notification.ROLE_SUPERADMIN,
                related_model='JobDeadline',
                related_object_id=str(job.id),
            )
        self.stdout.write(self.style.SUCCESS('Deadline notifications checked.'))
