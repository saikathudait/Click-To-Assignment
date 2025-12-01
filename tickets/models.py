# tickets/models.py
from django.db import models
from django.conf import settings

User = settings.AUTH_USER_MODEL

class Ticket(models.Model):
    PRIORITY_CHOICES = (
        ('LOW', 'Low'),
        ('MEDIUM', 'Medium'),
        ('HIGH', 'High'),
        ('URGENT', 'Urgent'),
    )

    STATUS_CHOICES = (
        ('NEW', 'New'),                 # Created by Marketing
        ('UNDER_REVIEW', 'Under Review by SuperAdmin'),
        ('APPROVED', 'Approved'),
        ('IN_PROGRESS', 'In Progress'),
        ('REWORK', 'Rework Requested'),
        ('COMPLETED', 'Completed'),
        ('CLOSED', 'Closed'),
    )

    job_id = models.CharField(max_length=50, unique=True)  # From your system
    ticket_id = models.CharField(max_length=50, unique=True, blank=True)  # Unique Ticket ID
    title = models.CharField(max_length=255)
    description = models.TextField()

    topic = models.CharField(max_length=255, blank=True, null=True)
    word_count = models.PositiveIntegerField(blank=True, null=True)
    referencing_style = models.CharField(max_length=100, blank=True, null=True)

    priority = models.CharField(
        max_length=10,
        choices=PRIORITY_CHOICES,
        default='MEDIUM'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='NEW'
    )

    # Who created the ticket (always Marketing)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_tickets'
    )

    deadline = models.DateTimeField(blank=True, null=True)

    question_file = models.FileField(
        upload_to='tickets/question_files/',
        blank=True,
        null=True
    )
    final_file = models.FileField(
        upload_to='tickets/final_files/',
        blank=True,
        null=True
    )

    marketing_notes = models.TextField(blank=True, null=True)
    superadmin_notes = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.ticket_id:
            from django.utils.crypto import get_random_string
            unique = False
            while not unique:
                candidate = f"TKT-{get_random_string(8).upper()}"
                if not Ticket.objects.filter(ticket_id=candidate).exists():
                    unique = True
                    self.ticket_id = candidate
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.ticket_id} - {self.job_id} - {self.title}"


class CustomerTicket(models.Model):
    PRIORITY_CHOICES = (
        ('LOW', 'Low'),
        ('MEDIUM', 'Medium'),
        ('HIGH', 'High'),
        ('CRITICAL', 'Critical'),
    )
    STATUS_CHOICES = (
        ('OPEN', 'Open'),
        ('IN_PROGRESS', 'In Progress'),
        ('RESOLVED', 'Resolved'),
        ('CLOSED', 'Closed'),
    )
    id = models.BigAutoField(primary_key=True)
    ticket_id = models.CharField(max_length=30, unique=True, db_index=True)
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='customer_tickets',
    )
    customer_id = models.CharField(max_length=50, blank=True, default='')
    customer_name = models.CharField(max_length=255, blank=True, default='')
    subject = models.CharField(max_length=255)
    category = models.CharField(max_length=100, blank=True, default='')
    description = models.TextField()
    attachment = models.FileField(upload_to='tickets/customer_attachments/', null=True, blank=True)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='MEDIUM')
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='OPEN')
    admin_notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'customer_tickets'
        ordering = ['-created_at']

    def __str__(self):
        return self.ticket_id

    def save(self, *args, **kwargs):
        if not self.ticket_id:
            from django.utils.crypto import get_random_string
            self.ticket_id = f"CT-{get_random_string(8).upper()}"
        if self.user:
            if not self.customer_id:
                self.customer_id = getattr(self.user, 'customer_code', None) or getattr(self.user, 'employee_id', None) or ''
            if not self.customer_name:
                self.customer_name = self.user.get_full_name()
        super().save(*args, **kwargs)
