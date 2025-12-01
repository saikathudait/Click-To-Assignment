from djongo import models
from django.conf import settings
from django.utils import timezone


class UserApprovalLog(models.Model):
    """Log of user approval/rejection actions"""
    
    ACTION_CHOICES = [
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='approval_logs'
    )
    
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='user_approvals_made'
    )
    
    notes = models.TextField(blank=True)
    timestamp = models.DateTimeField(default=timezone.now)
    
    class Meta:
        db_table = 'user_approval_logs'
        ordering = ['-timestamp']
    
    def __str__(self):
        return f"{self.user.email} - {self.action} - {self.timestamp}"


class ApprovalStatistics(models.Model):
    """Daily statistics for approvals"""
    
    date = models.DateField(default=timezone.now, unique=True)
    
    total_user_requests = models.IntegerField(default=0)
    approved_users = models.IntegerField(default=0)
    rejected_users = models.IntegerField(default=0)
    pending_users = models.IntegerField(default=0)
    
    total_profile_requests = models.IntegerField(default=0)
    approved_profile_requests = models.IntegerField(default=0)
    rejected_profile_requests = models.IntegerField(default=0)
    pending_profile_requests = models.IntegerField(default=0)
    
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'approval_statistics'
        ordering = ['-date']
        verbose_name_plural = 'Approval Statistics'
    
    def __str__(self):
        return f"Approval Stats for {self.date}"