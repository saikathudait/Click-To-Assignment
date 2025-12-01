from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone
import re
import random

class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('Email is required')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_approved', True)
        extra_fields.setdefault('role', 'SUPERADMIN')
        return self.create_user(email, password, **extra_fields)

class User(AbstractBaseUser, PermissionsMixin):
    ROLE_CHOICES = [
        ('MARKETING', 'Marketing Team'),
        ('SUPERADMIN', 'Super Admin'),
        ('CUSTOMER', 'Customer'),
    ]
    
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=25)
    last_name = models.CharField(max_length=25)
    whatsapp_no = models.CharField(max_length=20)
    whatsapp_country_code = models.CharField(max_length=5, default='+91')
    last_qualification = models.CharField(max_length=100)
    customer_code = models.CharField(max_length=20, unique=False, null=True, blank=True)
    
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='MARKETING')
    role_locked = models.BooleanField(default=False)
    employee_id = models.CharField(max_length=20, unique=True, null=True, blank=True)
    joining_date = models.DateField(null=True, blank=True)
    
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_approved = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    
    date_joined = models.DateTimeField(default=timezone.now)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_users')
    
    objects = UserManager()
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name']
    
    class Meta:
        db_table = 'users'
    
    def __str__(self):
        return f"{self.get_full_name()} ({self.email})"
    
    def get_full_name(self):
        return f"{self.first_name} {self.last_name}"
    
    def generate_customer_code(self):
        if self.customer_code:
            return self.customer_code
        # Format: F + day + first initial + last initial + random 3 digits
        day = self.date_joined.strftime('%d')
        first_initial = (self.first_name[:1] or 'X').upper()
        last_initial = (self.last_name[:1] or 'X').upper()
        rand_digits = random.randint(100, 999)
        code = f"F{day}{first_initial}{last_initial}{rand_digits}"
        self.customer_code = code
        return code
    
    def generate_employee_id(self):
        """
        Generate Employee ID: First Name Initial + Joining Month + Last Name Initial + Year (YY) + Serial No
        Example: RR1224 (Rahul Roy, December 2024, Serial #1)
        """
        if self.employee_id:
            return self.employee_id

        first_initial = (self.first_name[:1] or 'X').upper()
        last_initial = (self.last_name[:1] or 'X').upper()
        join_month = (self.date_joined or timezone.now()).strftime('%m')
        join_year = (self.date_joined or timezone.now()).strftime('%y')
        
        # Get serial number based on same month/year registrations
        base_id = f"{first_initial}{join_month}{last_initial}{join_year}"
        
        # Find the highest serial number for this base ID
        existing_users = User.objects.filter(
            employee_id__startswith=base_id
        ).order_by('-employee_id')
        
        if existing_users.exists():
            last_id = existing_users.first().employee_id
            # Extract serial number from last employee ID
            serial_match = re.search(r'(\d+)$', last_id)
            if serial_match:
                serial = int(serial_match.group(1)) + 1
            else:
                serial = 1
        else:
            serial = 1
        
        self.employee_id = f"{base_id}{serial}"
        return self.employee_id
    
    def get_whatsapp_full(self):
        """Return full WhatsApp number with country code"""
        return f"{self.whatsapp_country_code}{self.whatsapp_no}"
    
    def can_login(self):
        """Check if user can login"""
        return self.is_approved and self.is_active and not self.is_deleted
    
    def save(self, *args, **kwargs):
        if not self.employee_id and self.is_approved:
            self.generate_employee_id()
        if not self.customer_code and getattr(self, 'role', '').upper() == 'CUSTOMER':
            self.generate_customer_code()
        super().save(*args, **kwargs)
        
class CountryCode(models.Model):
    """Store country codes for WhatsApp numbers"""
    country_name = models.CharField(max_length=100)
    country_code = models.CharField(max_length=5)
    
    class Meta:
        db_table = 'country_codes'
        ordering = ['country_name']
    
    def __str__(self):
        return f"{self.country_name} ({self.country_code})"
    
    
    
