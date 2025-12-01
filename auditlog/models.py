from django.db import models
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from accounts.models import User
from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

class ActionLog(models.Model):
    ACTION_TYPES = [
        ('CREATE', 'Create'),
        ('UPDATE', 'Update'),
        ('DELETE', 'Delete'),
        ('APPROVE', 'Approve'),
        ('REJECT', 'Reject'),
        ('LOGIN', 'Login'),
        ('LOGOUT', 'Logout'),
        ('VIEW', 'View'),
        ('GENERATE', 'Generate'),
        ('USER_REGISTRATION', 'User Registration'),
        ('USER_LOGIN', 'User Login'),
        ('USER_LOGOUT', 'User Logout'),
        ('USER_APPROVAL', 'User Approval'),
        ('USER_REJECTION', 'User Rejection'),
        ('JOB_CREATED', 'Job Created'),
        ('JOB_VIEWED', 'Job Viewed'),
        ('JOB_UPDATED', 'Job Updated'),
        ('AI_GENERATION', 'AI Content Generation'),
        ('AI_REGENERATION', 'AI Content Regeneration'),
        ('AI_APPROVAL', 'AI Content Approval'),
        ('PROFILE_UPDATE_REQUEST', 'Profile Update Request'),
        ('PROFILE_UPDATE_APPROVED', 'Profile Update Approved'),
        ('PROFILE_UPDATE_REJECTED', 'Profile Update Rejected'),
        ('PASSWORD_CHANGE', 'Password Change'),
        ('REWORK_REQUEST', 'Rework Requested'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='actions')
    user_email = models.EmailField(max_length=255, blank=True, default='')  # Store email even if user deleted
    user_name = models.CharField(max_length=100, blank=True, default='')
    action_type = models.CharField(max_length=50, choices=ACTION_TYPES)
    timestamp = models.DateTimeField(auto_now_add=True)
    
    target_model = models.CharField(max_length=50, null=True, blank=True)
    target_id = models.CharField(max_length=100, null=True, blank=True)
    
    # Generic foreign key to any model
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, null=True, blank=True)
    object_id = models.CharField(max_length=255, null=True, blank=True)
    content_object = GenericForeignKey('content_type', 'object_id')
    
    description = models.TextField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    
    class Meta:
        db_table = 'action_logs'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['-timestamp']),
            models.Index(fields=['user', '-timestamp']),
            models.Index(fields=['action_type', '-timestamp']),
        ]
    
    def __str__(self):
        return f"{self.user} - {self.action_type} - {self.timestamp}"


class PageVisit(models.Model):
    """Track per-page active + idle time for authenticated users."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='page_visits',
    )
    session_id = models.CharField(max_length=64)
    page_path = models.CharField(max_length=512)
    page_name = models.CharField(max_length=255, blank=True, default='')
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField()
    active_seconds = models.PositiveIntegerField(default=0)
    idle_seconds = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'page_visits'
        ordering = ['-started_at']
        verbose_name = _('Page Visit')
        verbose_name_plural = _('Page Visits')

    def __str__(self):
        user_label = self.user.email if self.user else 'Anonymous'
        return f"{user_label} @ {self.page_path} ({self.active_seconds}s)"

    @property
    def total_seconds(self):
        return (self.active_seconds or 0) + (self.idle_seconds or 0)


class JobActionLog(models.Model):
    """Specific log for job-related actions"""
    
    job_id = models.CharField(max_length=100, db_index=True)
    system_id = models.CharField(max_length=100, db_index=True)
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    user_email = models.EmailField(max_length=255)
    
    action = models.CharField(max_length=100)
    field_changed = models.CharField(max_length=100, null=True, blank=True)
    old_value = models.TextField(null=True, blank=True)
    new_value = models.TextField(null=True, blank=True)
    
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    
    class Meta:
        db_table = 'job_action_logs'
        ordering = ['-timestamp']
    
    def __str__(self):
        return f"Job {self.job_id} - {self.action} - {self.timestamp}"
    
    
