from django.conf import settings
from django.db import models
from django.utils import timezone
import random


class CustomerProfile(models.Model):
    STATUS_ACTIVE = 'ACTIVE'
    STATUS_INACTIVE = 'INACTIVE'
    STATUS_BLOCKED = 'BLOCKED'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_INACTIVE, 'Inactive'),
        (STATUS_BLOCKED, 'Blocked'),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='customer_profile')
    customer_id = models.CharField(max_length=30, db_index=True, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    is_blocked = models.BooleanField(default=False)
    blocked_reason = models.TextField(null=True, blank=True)
    blocked_at = models.DateTimeField(null=True, blank=True)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    full_name = models.CharField(max_length=200, blank=True, default='')
    phone = models.CharField(max_length=20, blank=True, default='')
    profile_image = models.ImageField(upload_to='profile_pictures/customer/', null=True, blank=True)
    joined_date = models.DateTimeField(default=timezone.now)
    last_login_at = models.DateTimeField(null=True, blank=True)
    last_activity_at = models.DateTimeField(null=True, blank=True)
    coin_balance = models.IntegerField(default=0)
    total_coins_added = models.IntegerField(default=0)
    total_coins_spent = models.IntegerField(default=0)
    total_operations = models.IntegerField(default=0)
    total_tickets = models.IntegerField(default=0)
    total_meetings = models.IntegerField(default=0)
    total_bookings = models.IntegerField(default=0)
    notes_internal = models.TextField(null=True, blank=True)
    theme_preference = models.CharField(max_length=10, default='light')
    preferred_language = models.CharField(max_length=20, null=True, blank=True)
    timezone = models.CharField(max_length=50, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'customer_profiles'
        ordering = ['-joined_date']

    def __str__(self):
        return self.customer_id or f"Customer {self.pk}"

    def generate_customer_id(self):
        if self.customer_id:
            return self.customer_id
        base = "CUST"
        suffix = f"{int(timezone.now().timestamp())}{random.randint(100,999)}"
        self.customer_id = f"{base}{suffix}"
        return self.customer_id
