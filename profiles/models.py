from django.db import models
from accounts.models import User
from django.utils import timezone
from django.conf import settings


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    profile_picture = models.ImageField(upload_to='profile_pictures/approved/', null=True, blank=True)
    bio = models.TextField(max_length=500, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    address = models.TextField(max_length=500, blank=True)
    
    # Social links
    linkedin_url = models.URLField(max_length=200, blank=True)
    github_url = models.URLField(max_length=200, blank=True)
    
    # Statistics
    total_jobs_completed = models.IntegerField(default=0)
    total_earnings = models.FloatField(default=0.0)
    
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)
    
    class Meta:
        db_table = 'profiles'
    
    def __str__(self):
        return f"Profile of {self.user.get_full_name()}"


class ProfileUpdateRequest(models.Model):
    REQUEST_TYPE_CHOICES = [
        ('profile_picture', 'Profile Picture'),
        ('first_name', 'First Name'),
        ('last_name', 'Last Name'),
        ('email', 'Email'),
        ('whatsapp_number', 'WhatsApp Number'),
        ('last_qualification', 'Last Qualification'),
    ]
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
    ]
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='update_requests'
    )
    request_type = models.CharField(
        max_length=30,
        choices=REQUEST_TYPE_CHOICES
    )
    current_value = models.TextField()
    updated_value = models.TextField()
    new_profile_picture = models.ImageField(
        upload_to='profile_pictures/pending/',
        null=True,
        blank=True
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='PENDING'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    processed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='processed_requests'
    )
    notes = models.TextField(blank=True)
    
    class Meta:
        db_table = 'profile_update_requests'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['user', 'created_at']),
        ]
    
    def __str__(self):
        return f"{self.user.get_full_name()} - {self.get_request_type_display()} - {self.status}"
    
    def approve(self, admin_user, notes=''):
        """Approve the request and update user profile"""
        if self.status != 'PENDING':
            return False
        
        user = self.user
        
        if self.request_type == 'profile_picture':
            if self.new_profile_picture:
                # Get or create profile
                profile, _ = Profile.objects.get_or_create(user=user)
                profile.profile_picture = self.new_profile_picture
                profile.save()
        elif self.request_type == 'first_name':
            user.first_name = self.updated_value
            user.save()
        elif self.request_type == 'last_name':
            user.last_name = self.updated_value
            user.save()
        elif self.request_type == 'email':
            user.email = self.updated_value
            user.save()
        elif self.request_type == 'whatsapp_number':
            user.whatsapp_no = self.updated_value
            user.save()
        elif self.request_type == 'last_qualification':
            user.last_qualification = self.updated_value
            user.save()
        
        # Update request status
        self.status = 'APPROVED'
        self.processed_by = admin_user
        self.processed_at = timezone.now()
        self.notes = notes
        self.save()
        
        return True
    
    def reject(self, admin_user, notes=''):
        """Reject the request"""
        if self.status != 'PENDING':
            return False
        
        self.status = 'REJECTED'
        self.processed_by = admin_user
        self.processed_at = timezone.now()
        self.notes = notes
        self.save()
        
        return True