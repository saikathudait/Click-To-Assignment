from django.db import models
from django.utils import timezone
from accounts.models import User
import uuid
from datetime import datetime, timedelta, time
from django.conf import settings


class ReworkGeneration(models.Model):
    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('GENERATED', 'Generated'),
        ('APPROVED', 'Approved'),
    ]

    rework = models.OneToOneField('JobReworkRequest', on_delete=models.CASCADE, related_name='generation')
    summary_text = models.TextField(blank=True, default='')
    rework_text = models.TextField(blank=True, default='')
    summary_regen_count = models.IntegerField(default=0)
    rework_regen_count = models.IntegerField(default=0)
    summary_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')
    rework_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'rework_generations'

    def __str__(self):
        return f"Generation for rework {self.rework_id}"


def generate_system_id():
    """Generate unique System ID: JN-timestamp(milliseconds)"""
    timestamp = timezone.now().strftime('%Y%m%d%H%M%S%f')[:-3]
    return f"JN-{timestamp}"

class Job(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('JOB_SUMMARY', 'Job Summary Approved'),
        ('JOB_STRUCTURE', 'Job Structure Approved'),
        ('CONTENT', 'Content Approved'),
        ('REFERENCES', 'References Approved'),
        ('FULL_CONTENT', 'Full Content Approved'),
        ('PLAGIARISM_REPORT', 'Plagiarism Report Ready'),
        ('AI_REPORT', 'AI Report Ready'),
        ('IN_PROGRESS', 'In Progress'),
        ('REWORK', 'Rework'),
        ('REWORK_COMPLETED', 'Rework Completed'),
        ('COMPLETED', 'Completed'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
    ]
    
    # Auto-generated fields
    sl_no = models.IntegerField(editable=False, null=True, blank=True)
    system_id = models.CharField(max_length=50, unique=True, default=generate_system_id, editable=False)
    
    # From Job Drop Form
    job_id = models.CharField(max_length=100, unique=True, help_text="Job ID from Customer")
    instruction = models.TextField(max_length=10000)
    amount = models.FloatField(help_text="Amount in INR")
    expected_deadline = models.DateTimeField()
    strict_deadline = models.DateTimeField()
    payment_slip = models.FileField(upload_to='payment_slips/%Y/%m/%d/', null=True, blank=True)
    
    # Metadata
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_jobs')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')

    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='deleted_jobs'
    )
    
    # Approval tracking
    is_approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_jobs'
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_jobs')
    
    class Meta:
        db_table = 'jobs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['job_id']),
            models.Index(fields=['system_id']),
            models.Index(fields=['status']),
            models.Index(fields=['-created_at']),
        ]
    
    def __str__(self):
        return f"{self.job_id} - {self.system_id}"
    
    # Update the save method in Job model
    def save(self, *args, **kwargs):
    # Generate SL NO if not exists - use update_or_create to prevent race conditions
        if not self.sl_no:
            from django.db import transaction
            with transaction.atomic():
                last_job = Job.objects.select_for_update().order_by('-sl_no').first()
                self.sl_no = (last_job.sl_no + 1) if last_job and last_job.sl_no else 1
    
    # Validate strict deadline is at least 24 hours after expected deadline
        if self.strict_deadline and self.expected_deadline:
            time_diff = self.strict_deadline - self.expected_deadline
            if time_diff < timedelta(hours=24):
                from django.core.exceptions import ValidationError
                raise ValidationError('Strict deadline must be at least 24 hours after expected deadline.')
    
        super().save(*args, **kwargs)
        
    def get_time_remaining(self):
        """Calculate time remaining until strict deadline"""
        if self.strict_deadline:
            now = timezone.now()
            diff = self.strict_deadline - now
            if diff.total_seconds() > 0:
                days = diff.days
                hours = diff.seconds // 3600
                return f"{days} days, {hours} hours"
            else:
                return "Overdue"
        return "N/A"
    
    def is_overdue(self):
        """Check if job is overdue"""
        if self.strict_deadline:
            return timezone.now() > self.strict_deadline
        return False

    # --- Compatibility helpers for AI pipeline relations ---
    @property
    def summary(self):
        """Alias for JobSummary relation (historically named jobsummary)."""
        return getattr(self, 'jobsummary', None)

    @property
    def job_summary(self):
        """Alias used in some legacy views."""
        return self.summary

    @property
    def job_structure(self):
        """Alias for JobStructure relation (related_name='structure')."""
        return getattr(self, 'structure', None)

    @property
    def generated_content(self):
        """Alias for GeneratedContent relation (related_name='content')."""
        return getattr(self, 'content', None)

    @property
    def plagiarism_report(self):
        """Alias for PlagiarismReport relation (related_name='plag_report')."""
        return getattr(self, 'plag_report', None)

class Attachment(models.Model):
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name='attachments')
    file = models.FileField(upload_to='attachments/%Y/%m/%d/')
    filename = models.CharField(max_length=255)
    file_type = models.CharField(max_length=10)
    file_size = models.IntegerField(help_text="File size in bytes")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'attachments'
        ordering = ['uploaded_at']
    
    def __str__(self):
        return f"{self.filename} - {self.job.job_id}"
    
    def get_file_extension(self):
        return self.filename.split('.')[-1].lower()
    
    def get_file_size_display(self):
        """Return human-readable file size"""
        size = self.file_size
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} TB"


class JobReworkRequest(models.Model):
    STATUS_PENDING = 'PENDING'
    STATUS_APPROVED = 'APPROVED'
    STATUS_REJECTED = 'REJECTED'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_APPROVED, 'Completed'),
        (STATUS_REJECTED, 'Rejected'),
    ]

    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name='rework_requests')
    requested_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='job_rework_requests')
    rework_id = models.CharField(max_length=150, blank=True, default='')
    reason = models.TextField(default='')
    expected_deadline = models.DateTimeField(null=True, blank=True)
    attachment = models.FileField(upload_to='rework/%Y/%m/%d/', blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='handled_rework_requests'
    )
    handled_at = models.DateTimeField(null=True, blank=True)
    response_notes = models.TextField(blank=True)

    class Meta:
        db_table = 'job_rework_requests'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['job', '-created_at']),
        ]

    def __str__(self):
        return f"Rework for {self.job.job_id} by {self.requested_by}"

    def assign_rework_id(self, force=False):
        """Ensure a stable rework identifier, e.g., JN-000 R1, R2, ..."""
        if self.rework_id and not force:
            return self.rework_id
        if not self.job_id:
            return self.rework_id
        try:
            siblings = (
                JobReworkRequest.objects
                .filter(job=self.job)
                .order_by('created_at', 'pk')
                .values_list('pk', flat=True)
            )
            idx = list(siblings).index(self.pk) + 1 if self.pk in siblings else siblings.count() + 1
        except Exception:
            idx = 1
        self.rework_id = f"{self.job.system_id} R{idx}"
        return self.rework_id

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # After the initial save we have a PK; ensure rework_id is set.
        if not self.rework_id:
            self.assign_rework_id(force=True)
            super().save(update_fields=['rework_id'])

class JobMetrics(models.Model):
    """Track job statistics for cards/dashboard"""
    date = models.DateField(unique=True)
    total_jobs = models.IntegerField(default=0)
    pending_jobs = models.IntegerField(default=0)
    approved_jobs = models.IntegerField(default=0)
    total_amount = models.FloatField(default=0)
    completed_jobs = models.IntegerField(default=0)
    pending_amount = models.FloatField(default=0.0)
    approved_amount = models.FloatField(default=0.0)
    completed_amount = models.FloatField(default=0.0)
    
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'job_metrics'
        ordering = ['-date']
        
    def __str__(self):
        return f"Metrics for {self.date}"
    
    @classmethod
    def update_metrics(cls, date=None):
        """Update metrics for a given date"""
        # Use local date if not provided
        if not date:
            date = timezone.localdate()
        
        metrics, created = cls.objects.get_or_create(date=date)
        
        # Build start and end of the day (timezone-aware)
        tz = timezone.get_current_timezone()
        start_dt = timezone.make_aware(datetime.combine(date, time.min), tz)
        end_dt = timezone.make_aware(
            datetime.combine(date + timedelta(days=1), time.min),
            tz
        )
        
        # Single DB query for all jobs created that day
        qs = Job.objects.filter(
            created_at__gte=start_dt,
            created_at__lt=end_dt
        )
        jobs_today = list(qs)  # evaluate once, then work in Python
        
        # Helper for safe amount (in case amount can be None)
        def safe_amount(job):
            return job.amount or 0
        
        # ---- Totals (all Python-side, no extra SQL / no boolean WHERE) ----
        metrics.total_jobs = len(jobs_today)
        metrics.pending_jobs = sum(1 for job in jobs_today if job.status == 'pending')
        metrics.completed_jobs = sum(1 for job in jobs_today if job.status == 'completed')
        metrics.approved_jobs = sum(1 for job in jobs_today if getattr(job, 'is_approved', False))
        
        # ---- Amounts ----
        metrics.total_amount = sum(safe_amount(job) for job in jobs_today)
        metrics.pending_amount = sum(
            safe_amount(job) for job in jobs_today if job.status == 'pending'
        )
        metrics.completed_amount = sum(
            safe_amount(job) for job in jobs_today if job.status == 'completed'
        )
        metrics.approved_amount = sum(
            safe_amount(job) for job in jobs_today if getattr(job, 'is_approved', False)
        )
        
        metrics.save()
        return metrics
