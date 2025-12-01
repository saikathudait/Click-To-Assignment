from django.conf import settings
from django.db import models
from django.utils import timezone


class Notification(models.Model):
    ROLE_MARKETING = 'MARKETING'
    ROLE_SUPERADMIN = 'SUPERADMIN'
    ROLE_ALL = 'ALL'
    ROLE_CHOICES = [
        (ROLE_MARKETING, 'Marketing'),
        (ROLE_SUPERADMIN, 'Super Admin'),
        (ROLE_ALL, 'All Users'),
    ]

    title = models.CharField(max_length=255)
    message = models.TextField(blank=True)
    url = models.CharField(max_length=500, blank=True)
    role_target = models.CharField(max_length=20, choices=ROLE_CHOICES, blank=True, null=True)
    user_target = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='direct_notifications',
        blank=True,
        null=True,
    )
    related_model = models.CharField(max_length=100, blank=True)
    related_object_id = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title


class NotificationRecipient(models.Model):
    notification = models.ForeignKey(
        Notification,
        on_delete=models.CASCADE,
        related_name='recipients',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notification_receipts',
    )
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        unique_together = ('notification', 'user')
        ordering = ['-notification__created_at']

    def mark_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at'])

    def __str__(self):
        return f'{self.user} -> {self.notification}'
