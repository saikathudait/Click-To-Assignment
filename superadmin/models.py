import random

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.urls import NoReverseMatch, reverse
from accounts.models import User
from django.core.validators import validate_email
from django.core.exceptions import ValidationError


class ErrorLog(models.Model):
    code = models.CharField(max_length=20)
    message = models.TextField(blank=True, default='')
    path = models.CharField(max_length=512, blank=True, default='')
    method = models.CharField(max_length=10, blank=True, default='')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    role = models.CharField(max_length=50, blank=True, default='')
    meta = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        db_table = 'error_logs'

    def __str__(self):
        return f"{self.code} @ {self.created_at}"


class SystemSettings(models.Model):
    """
    Singleton-style model that stores global configuration used
    throughout the platform. Only one record is expected.
    """
    DEFAULTS = {
        'default_turnaround_days': 5,
        'max_upload_size_mb': 25,
        'allowed_file_types': 'pdf,docx,txt',
        'rework_limit': 3,
        'auto_close_days': 7,
        'admin_coin_balance': 0,
        'admin_coin_total_created': 0,
        'coin_rule_note': '',
        'pricing_plan_doc': '',
    }

    default_turnaround_days = models.PositiveIntegerField(default=DEFAULTS['default_turnaround_days'])
    max_upload_size_mb = models.PositiveIntegerField(default=DEFAULTS['max_upload_size_mb'])
    allowed_file_types = models.CharField(
        max_length=255,
        help_text='Comma separated list of extensions (e.g. pdf,docx,txt)',
        default=DEFAULTS['allowed_file_types'],
    )
    rework_limit = models.PositiveIntegerField(default=DEFAULTS['rework_limit'])
    auto_close_days = models.PositiveIntegerField(default=DEFAULTS['auto_close_days'])
    admin_coin_balance = models.IntegerField(default=DEFAULTS['admin_coin_balance'])
    admin_coin_total_created = models.IntegerField(default=DEFAULTS['admin_coin_total_created'])
    coin_rule_note = models.TextField(blank=True, default=DEFAULTS['coin_rule_note'])
    pricing_plan_doc = models.TextField(blank=True, default=DEFAULTS['pricing_plan_doc'])
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'System Setting'
        verbose_name_plural = 'System Settings'

    def __str__(self):
        return 'Global System Settings'

    @classmethod
    def get_solo(cls):
        obj, created = cls.objects.get_or_create(pk=1, defaults=cls.DEFAULTS)
        # Ensure missing fields fall back to defaults
        changed = False
        for field, value in cls.DEFAULTS.items():
            if getattr(obj, field) in (None, ''):
                setattr(obj, field, value)
                changed = True
        if changed:
            obj.save()
        return obj


def _generate_bigint_id():
    """
    Djongo does not auto-increment numeric IDs reliably, so we generate
    a timestamp-based unique integer that fits into BigAutoField.
    """
    base = int(timezone.now().timestamp() * 1_000_000)  # microseconds
    return base * 100 + random.randint(10, 99)


class AdminWallet(models.Model):
    """
    Singleton admin wallet to hold platform coin reserves.
    """
    id = models.BigAutoField(primary_key=True)
    balance = models.IntegerField(default=0)
    total_created = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'admin_wallet'

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1, defaults={'balance': 0, 'total_created': 0})
        return obj


class CoinWallet(models.Model):
    STATUS_ACTIVE = 'ACTIVE'
    STATUS_FROZEN = 'FROZEN'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_FROZEN, 'Frozen'),
    ]
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='coin_wallet')
    balance = models.IntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    last_updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'coin_wallets'
        unique_together = [('user',)]

    def __str__(self):
        return f"Wallet {self.pk} for {self.user.email}"


class CoinTransaction(models.Model):
    TYPE_CREDIT = 'CREDIT'
    TYPE_DEBIT = 'DEBIT'
    TYPE_REFUND = 'REFUND'
    TYPE_EXPIRY = 'EXPIRY'
    TYPE_ADJUST = 'ADJUST'
    TYPE_CHOICES = [
        (TYPE_CREDIT, 'Credit'),
        (TYPE_DEBIT, 'Debit'),
        (TYPE_REFUND, 'Refund'),
        (TYPE_EXPIRY, 'Expiry'),
        (TYPE_ADJUST, 'Adjust'),
    ]
    SOURCE_PURCHASE = 'PURCHASE'
    SOURCE_JOB = 'JOB_CHECK'
    SOURCE_STRUCTURE = 'STRUCTURE'
    SOURCE_CONTENT = 'CONTENT'
    SOURCE_ADMIN = 'ADMIN'
    SOURCE_SYSTEM = 'SYSTEM'
    SOURCE_CHOICES = [
        (SOURCE_PURCHASE, 'Purchase'),
        (SOURCE_JOB, 'Job Checking'),
        (SOURCE_STRUCTURE, 'Structure'),
        (SOURCE_CONTENT, 'Content'),
        (SOURCE_ADMIN, 'Admin'),
        (SOURCE_SYSTEM, 'System'),
    ]

    id = models.BigAutoField(primary_key=True)
    txn_id = models.CharField(max_length=50, unique=True)
    wallet = models.ForeignKey(CoinWallet, on_delete=models.CASCADE, related_name='transactions')
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='coin_transactions')
    txn_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    amount = models.IntegerField()
    before_balance = models.IntegerField()
    after_balance = models.IntegerField()
    source = models.CharField(max_length=30, choices=SOURCE_CHOICES, default=SOURCE_SYSTEM)
    related_object_type = models.CharField(max_length=30, null=True, blank=True)
    related_object_id = models.CharField(max_length=50, null=True, blank=True)
    reason = models.TextField(null=True, blank=True)
    expiry_date = models.DateTimeField(null=True, blank=True)
    created_by_role = models.CharField(max_length=20, default='SUPERADMIN')
    created_by_id = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_coin_transactions')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'coin_transactions'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.txn_id} {self.txn_type} {self.amount}"


class CoinRule(models.Model):
    id = models.BigAutoField(primary_key=True)
    service_name = models.CharField(max_length=30, unique=True)
    coin_cost = models.IntegerField(default=0)
    min_balance_required = models.IntegerField(default=0)
    expiry_enabled = models.BooleanField(default=False)
    expiry_days = models.IntegerField(null=True, blank=True)
    refund_enabled = models.BooleanField(default=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='updated_coin_rules')
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'coin_rules'

    def __str__(self):
        return self.service_name


class PricingPlan(models.Model):
    STATUS_DRAFT = 'DRAFT'
    STATUS_PUBLISHED = 'PUBLISHED'
    STATUS_UNPUBLISHED = 'UNPUBLISHED'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_PUBLISHED, 'Published'),
        (STATUS_UNPUBLISHED, 'Unpublished'),
    ]

    TYPE_ONE_TIME = 'ONE_TIME'
    TYPE_SUBSCRIPTION = 'SUBSCRIPTION'
    PLAN_TYPE_CHOICES = [
        (TYPE_ONE_TIME, 'One-time'),
        (TYPE_SUBSCRIPTION, 'Subscription'),
    ]

    id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=150)
    short_description = models.CharField(max_length=255, blank=True, default='')
    coin_amount = models.PositiveIntegerField(default=0)
    price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=10, default='USD')
    validity_days = models.PositiveIntegerField(null=True, blank=True)
    plan_type = models.CharField(max_length=20, choices=PLAN_TYPE_CHOICES, default=TYPE_ONE_TIME)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    benefits = models.TextField(blank=True, default='')
    limit_job_checks_per_day = models.PositiveIntegerField(default=0)
    limit_structures_per_day = models.PositiveIntegerField(default=0)
    limit_contents_per_day = models.PositiveIntegerField(default=0)
    limit_job_checks_per_month = models.PositiveIntegerField(default=0)
    limit_structures_per_month = models.PositiveIntegerField(default=0)
    limit_contents_per_month = models.PositiveIntegerField(default=0)
    special_conditions = models.TextField(blank=True, default='')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pricing_plans_created',
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pricing_plans_updated',
    )
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'pricing_plans'
        ordering = ['-updated_at', '-created_at']

    def __str__(self):
        return self.name


class GoogleAuthConfig(models.Model):
    MODE_LOGIN_ONLY = 'LOGIN_ONLY'
    MODE_LOGIN_SIGNUP = 'LOGIN_SIGNUP'
    MODE_CHOICES = [
        (MODE_LOGIN_ONLY, 'Login Only'),
        (MODE_LOGIN_SIGNUP, 'Login + Signup'),
    ]

    id = models.BigAutoField(primary_key=True)
    enabled = models.BooleanField(default=True)
    allow_signup = models.BooleanField(default=True)
    mode = models.CharField(max_length=20, choices=MODE_CHOICES, default=MODE_LOGIN_SIGNUP)
    allowed_domains = models.TextField(blank=True, default='', help_text='Comma-separated domains (e.g. example.com,partner.edu). Leave blank to allow all.')
    allow_customer = models.BooleanField(default=True)
    allow_marketing = models.BooleanField(default=False)
    allow_superadmin = models.BooleanField(default=False)
    client_id = models.CharField(max_length=255, blank=True, default='')
    client_secret = models.CharField(max_length=255, blank=True, default='')
    redirect_url = models.CharField(max_length=512, blank=True, default='')
    show_health_warning = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='google_auth_updates')

    class Meta:
        db_table = 'google_auth_config'

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def domain_allowed(self, email: str) -> bool:
        domains = [d.strip().lower() for d in (self.allowed_domains or '').split(',') if d.strip()]
        if not domains:
            return True
        try:
            validate_email(email)
        except ValidationError:
            return False
        domain = (email.split('@')[-1] or '').lower()
        return domain in domains

    def is_role_allowed(self, role: str) -> bool:
        role = (role or '').upper()
        if role == 'CUSTOMER':
            return self.allow_customer
        if role == 'MARKETING':
            return self.allow_marketing
        if role == 'SUPERADMIN':
            return self.allow_superadmin
        return False


class GoogleLoginLog(models.Model):
    STATUS_SUCCESS = 'SUCCESS'
    STATUS_FAILURE = 'FAILURE'
    STATUS_CHOICES = [
        (STATUS_SUCCESS, 'Success'),
        (STATUS_FAILURE, 'Failure'),
    ]

    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='google_login_logs')
    email = models.CharField(max_length=255, blank=True, default='')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_SUCCESS)
    reason = models.TextField(blank=True, default='')
    ip_address = models.CharField(max_length=50, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'google_login_logs'
        ordering = ['-created_at']

    def is_active_for_customers(self):
        return self.status == self.STATUS_PUBLISHED

    def validity_label(self):
        if self.validity_days:
            return f"{self.validity_days} days"
        return "No expiry"


class PricingPlanPurchase(models.Model):
    STATUS_ACTIVE = 'ACTIVE'
    STATUS_EXPIRED = 'EXPIRED'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_EXPIRED, 'Expired'),
    ]

    id = models.BigAutoField(primary_key=True)
    plan = models.ForeignKey(
        PricingPlan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='purchases',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='pricing_plan_purchases',
    )
    wallet = models.ForeignKey(
        CoinWallet,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='plan_purchases',
    )
    transaction = models.ForeignKey(
        CoinTransaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='plan_purchases',
    )
    plan_name = models.CharField(max_length=150)
    plan_snapshot = models.TextField(blank=True, default='')
    price_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=10, default='USD')
    coins_granted = models.IntegerField(default=0)
    validity_days = models.PositiveIntegerField(null=True, blank=True)
    purchased_at = models.DateTimeField(auto_now_add=True)
    valid_until = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    notes = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'pricing_plan_purchases'
        ordering = ['-purchased_at']

    def __str__(self):
        return f"{self.plan_name} for {self.user.email}"

    def is_expired(self):
        return bool(self.valid_until and timezone.now() > self.valid_until)

    def computed_status(self):
        return self.STATUS_EXPIRED if self.is_expired() else self.status


class AIRequestLog(models.Model):
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ai_request_logs',
    )
    customer_id = models.CharField(max_length=50, blank=True, default='')
    customer_name = models.CharField(max_length=255, blank=True, default='')
    service = models.CharField(max_length=100)
    coins = models.IntegerField(default=0)
    status = models.CharField(max_length=50, default='PENDING')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'ai_request_logs'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.customer_name or self.customer_id} - {self.service}"


class JobCheckingSubmission(models.Model):
    STATUS_PENDING = 'PENDING'
    STATUS_SUCCESS = 'SUCCESS'
    STATUS_FAILED = 'FAILED'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_SUCCESS, 'Success'),
        (STATUS_FAILED, 'Failed'),
    ]

    id = models.BigAutoField(primary_key=True)
    submission_id = models.CharField(max_length=30, unique=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='job_checking_submissions',
    )
    service = models.CharField(max_length=50, default='JOB_CHECK')
    customer_id = models.CharField(max_length=50, blank=True, default='')
    customer_name = models.CharField(max_length=255, blank=True, default='')
    instruction = models.TextField(blank=True, default='')
    attachment = models.FileField(upload_to='job_checking/', null=True, blank=True)
    extracted_text = models.TextField(blank=True, default='')
    ai_prompt = models.TextField(blank=True, default='')
    ai_summary = models.TextField(blank=True, default='')
    job_reference = models.CharField(max_length=100, blank=True, default='')
    coins_spent = models.IntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    error_message = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'job_checking_submissions'
        ordering = ['-created_at']

    def __str__(self):
        return self.submission_id

    def generate_submission_id(self):
        if self.submission_id:
            return self.submission_id
        base = timezone.now().strftime('JCS%Y%m%d%H%M%S')
        suffix = random.randint(100, 999)
        self.submission_id = f"{base}{suffix}"
        return self.submission_id

    def save(self, *args, **kwargs):
        if not self.submission_id:
            self.generate_submission_id()
        if not self.customer_id and self.user:
            self.customer_id = getattr(self.user, 'customer_code', None) or getattr(self.user, 'employee_id', None) or ''
        if not self.customer_name and self.user:
            self.customer_name = self.user.get_full_name()
        super().save(*args, **kwargs)


class StructureGenerationSubmission(models.Model):
    STATUS_PENDING = 'PENDING'
    STATUS_SUCCESS = 'SUCCESS'
    STATUS_FAILED = 'FAILED'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_SUCCESS, 'Success'),
        (STATUS_FAILED, 'Failed'),
    ]

    id = models.BigAutoField(primary_key=True)
    submission_id = models.CharField(max_length=30, unique=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='structure_generation_submissions',
    )
    customer_id = models.CharField(max_length=50, blank=True, default='')
    customer_name = models.CharField(max_length=255, blank=True, default='')
    topic = models.CharField(max_length=500, blank=True, default='')
    word_count = models.IntegerField(default=0)
    referencing_style = models.CharField(max_length=100, blank=True, default='')
    academic_style = models.CharField(max_length=100, blank=True, default='')
    academic_level = models.CharField(max_length=100, blank=True, default='')
    summary = models.TextField(blank=True, default='')
    marking_criteria = models.TextField(blank=True, default='')
    merit_criteria = models.TextField(blank=True, default='')
    subject_field = models.CharField(max_length=150, blank=True, default='')
    ai_prompt = models.TextField(blank=True, default='')
    ai_structure = models.TextField(blank=True, default='')
    coins_spent = models.IntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    error_message = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'structure_generation_submissions'
        ordering = ['-created_at']

    def __str__(self):
        return self.submission_id

    def generate_submission_id(self):
        if self.submission_id:
            return self.submission_id
        base = timezone.now().strftime('SGS%Y%m%d%H%M%S')
        suffix = random.randint(100, 999)
        self.submission_id = f"{base}{suffix}"
        return self.submission_id

    def save(self, *args, **kwargs):
        if not self.submission_id:
            self.generate_submission_id()
        if not self.customer_id and self.user:
            self.customer_id = getattr(self.user, 'customer_code', None) or getattr(self.user, 'employee_id', None) or ''
        if not self.customer_name and self.user:
            self.customer_name = self.user.get_full_name()
        super().save(*args, **kwargs)


class ContentGenerationSubmission(models.Model):
    STATUS_PENDING = 'PENDING'
    STATUS_SUCCESS = 'SUCCESS'
    STATUS_FAILED = 'FAILED'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_SUCCESS, 'Success'),
        (STATUS_FAILED, 'Failed'),
    ]

    id = models.BigAutoField(primary_key=True)
    submission_id = models.CharField(max_length=30, unique=True, db_index=True)
    base_submission_id = models.CharField(max_length=30, db_index=True)
    version_number = models.IntegerField(default=1)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='content_generation_submissions',
    )
    customer_id = models.CharField(max_length=50, blank=True, default='')
    customer_name = models.CharField(max_length=255, blank=True, default='')
    topic = models.CharField(max_length=500, blank=True, default='')
    word_count = models.IntegerField(default=0)
    referencing_style = models.CharField(max_length=100, blank=True, default='')
    writing_style = models.CharField(max_length=100, blank=True, default='')
    writing_tone = models.CharField(max_length=100, blank=True, default='')
    structure_guidelines = models.TextField(blank=True, default='')
    subject_field = models.CharField(max_length=150, blank=True, default='')
    academic_level = models.CharField(max_length=100, blank=True, default='')
    generated_content = models.TextField(blank=True, default='')
    references_text = models.TextField(blank=True, default='')
    citations_text = models.TextField(blank=True, default='')
    final_content = models.TextField(blank=True, default='')
    coins_spent = models.IntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    error_message = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'content_generation_submissions'
        ordering = ['-created_at']

    def __str__(self):
        return self.submission_id

    def generate_submission_ids(self):
        if not self.submission_id:
            base = timezone.now().strftime('CGS%Y%m%d%H%M%S')
            suffix = random.randint(100, 999)
            self.submission_id = f"{base}{suffix}"
        if not self.base_submission_id:
            self.base_submission_id = self.submission_id
        return self.submission_id

    def save(self, *args, **kwargs):
        self.generate_submission_ids()
        if not self.customer_id and self.user:
            self.customer_id = getattr(self.user, 'customer_code', None) or getattr(self.user, 'employee_id', None) or ''
        if not self.customer_name and self.user:
            self.customer_name = self.user.get_full_name()
        super().save(*args, **kwargs)
class Announcement(models.Model):
    TYPE_INFO = 'INFO'
    TYPE_WARNING = 'WARNING'
    TYPE_UPDATE = 'UPDATE'
    TYPE_CHOICES = [
        (TYPE_INFO, 'Info'),
        (TYPE_WARNING, 'Warning'),
        (TYPE_UPDATE, 'Update'),
    ]

    VISIBILITY_MARKETING = 'MARKETING'
    VISIBILITY_SUPERADMIN = 'SUPERADMIN'
    VISIBILITY_ALL = 'ALL'
    VISIBILITY_CHOICES = [
        (VISIBILITY_MARKETING, 'Marketing'),
        (VISIBILITY_SUPERADMIN, 'Super Admin'),
        (VISIBILITY_ALL, 'All Roles'),
    ]

    STATUS_SCHEDULED = 'SCHEDULED'
    STATUS_ACTIVE = 'ACTIVE'
    STATUS_EXPIRED = 'EXPIRED'
    STATUS_INACTIVE = 'INACTIVE'

    title = models.CharField(max_length=255)
    body = models.TextField()
    type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        default=TYPE_INFO,
    )
    visibility = models.CharField(
        max_length=20,
        choices=VISIBILITY_CHOICES,
        default=VISIBILITY_ALL,
    )
    attachment = models.FileField(
        upload_to='attachments/notices/',
        blank=True,
        null=True,
    )
    link_url = models.URLField(blank=True)
    start_at = models.DateTimeField(default=timezone.now)
    end_at = models.DateTimeField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='announcements_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-start_at', '-created_at']

    def __str__(self):
        return self.title

    def status(self, reference_time=None):
        """Return computed status string for UI/state."""
        if not self.is_active:
            return self.STATUS_INACTIVE
        reference_time = reference_time or timezone.now()
        if self.start_at and self.start_at > reference_time:
            return self.STATUS_SCHEDULED
        if self.end_at and self.end_at < reference_time:
            return self.STATUS_EXPIRED
        return self.STATUS_ACTIVE

    def is_for_role(self, role):
        if self.visibility == self.VISIBILITY_ALL:
            return True
        return self.visibility == role

    def is_visible_now(self, reference_time=None):
        """Return True if announcement should be shown right now."""
        reference_time = reference_time or timezone.now()
        if not self.is_active:
            return False
        if self.start_at and reference_time < self.start_at:
            return False
        if self.end_at and reference_time > self.end_at:
            return False
        return True

    def save(self, *args, **kwargs):
        if not self.pk:
            self.pk = _generate_bigint_id()
        super().save(*args, **kwargs)


class ContentAccessSetting(models.Model):
    MODE_APPROVAL_ONLY = 'APPROVAL_ONLY'
    MODE_APPROVAL_OR_SLIP = 'APPROVAL_OR_SLIP'
    MODE_CHOICES = [
        (MODE_APPROVAL_ONLY, 'Super Admin Approval Only'),
        (MODE_APPROVAL_OR_SLIP, 'Approval or Payment Slip'),
    ]

    marketing_user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='content_access_setting',
    )
    mode = models.CharField(
        max_length=30,
        choices=MODE_CHOICES,
        default=MODE_APPROVAL_OR_SLIP,
    )

    class Meta:
        db_table = 'content_access_settings'

    def __str__(self):
        return f"{self.marketing_user.email} - {self.mode}"

    @classmethod
    def for_user(cls, user):
        if not user or getattr(user, 'role', '').upper() != 'MARKETING':
            return None
        try:
            obj, _ = cls.objects.get_or_create(
                marketing_user=user,
                defaults={'mode': cls.MODE_APPROVAL_OR_SLIP},
            )
            return obj
        except Exception:
            return None


class AnnouncementReceipt(models.Model):
    announcement = models.ForeignKey(
        Announcement,
        on_delete=models.CASCADE,
        related_name='receipts',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='announcement_receipts',
    )
    seen_at = models.DateTimeField(blank=True, null=True)
    dismissed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        unique_together = ('announcement', 'user')
        ordering = ['-announcement__start_at']

    def mark_seen(self, timestamp=None, save=True):
        if self.seen_at:
            return False
        self.seen_at = timestamp or timezone.now()
        if save:
            self.save(update_fields=['seen_at'])
        return True

    def mark_dismissed(self, timestamp=None, save=True):
        self.dismissed_at = timestamp or timezone.now()
        fields = ['dismissed_at']
        if not self.seen_at:
            self.seen_at = self.dismissed_at
            fields.append('seen_at')
        if save:
            self.save(update_fields=fields)
        return True

    def save(self, *args, **kwargs):
        if not self.pk:
            self.pk = _generate_bigint_id()
        super().save(*args, **kwargs)


class MenuItem(models.Model):
    ROLE_SUPERADMIN = 'SUPERADMIN'
    ROLE_MARKETING = 'MARKETING'
    ROLE_CHOICES = [
        (ROLE_SUPERADMIN, 'Super Admin'),
        (ROLE_MARKETING, 'Marketing'),
    ]

    label = models.CharField(max_length=100)
    url_name = models.CharField(max_length=200)
    icon_class = models.CharField(max_length=100, default='fas fa-circle')
    position = models.PositiveIntegerField(default=0)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_SUPERADMIN)
    is_active = models.BooleanField(default=True)
    is_fixed = models.BooleanField(default=False)

    class Meta:
        db_table = 'menu_items'
        ordering = ['role', 'position', 'label']
        unique_together = ('role', 'url_name')

    def __str__(self):
        return f"{self.role} - {self.label}"

    @classmethod
    def _default_menu(cls):
        return {
            cls.ROLE_SUPERADMIN: [
                ('Welcome', 'superadmin:welcome', 'fas fa-home', 0, True),
                ('Dashboard', 'superadmin:dashboard', 'fas fa-chart-bar', 1, False),
                ('Statistics', 'superadmin:statistics', 'fas fa-chart-pie', 2, False),
                ('All Jobs', 'superadmin:all_jobs', 'fas fa-briefcase', 3, False),
                ('New Jobs', 'superadmin:new_jobs', 'fas fa-bell', 4, False),
                ('Tickets', 'tickets:superadmin-ticket-list', 'fas fa-ticket-alt', 5, False),
                ('Holiday Management', 'holidays:list', 'fas fa-umbrella-beach', 6, False),
                ('User Management', 'superadmin:user_management', 'fas fa-users-cog', 7, False),
                ('Form Management', 'superadmin:form_management', 'fas fa-clipboard-list', 8, False),
                ('Permission Management', 'superadmin:permission_management', 'fas fa-user-shield', 9, False),
                ('Notice Management', 'superadmin:announcement_list', 'fas fa-bullhorn', 10, False),
                ('Menu Management', 'superadmin:menu_management', 'fas fa-list', 11, False),
                ('Content Management', 'superadmin:content_management', 'fas fa-lock-open', 12, False),
                ('Settings', 'superadmin:settings', 'fas fa-sliders-h', 13, False),
                ('Activity Tracking', 'superadmin:activity_tracking', 'fas fa-stream', 14, False),
                ('User Time-on-Page', 'superadmin:activity_analytics', 'fas fa-chart-line', 15, False),
                ('Error Management', 'superadmin:error_management', 'fas fa-bug', 16, False),
                ('Backup', 'superadmin:backup_center', 'fas fa-database', 17, False),
                ('User Approval', 'approvals:user_approval_list', 'fas fa-user-check', 18, False),
                ('Profile Updates', 'approvals:profile_update_list', 'fas fa-edit', 19, False),
                ('Customer Management System', 'superadmin:customer_management', 'fas fa-user-tie', 20, False),
                ('Customer Account Management', 'superadmin:customer_accounts', 'fas fa-id-card', 21, False),
                ('Coin / Wallet Management', 'superadmin:customer_wallets', 'fas fa-wallet', 22, False),
                ('Pricing Plan Management', 'superadmin:customer_pricing', 'fas fa-tags', 23, False),
                ('AI Service Configuration', 'superadmin:customer_ai_config', 'fas fa-microchip', 24, False),
                ('AI Request Log', 'superadmin:customer_ai_logs', 'fas fa-clipboard-list', 25, False),
                ('Job Checking Submissions', 'superadmin:customer_job_checks', 'fas fa-file-alt', 26, False),
                ('Structure Generation Management', 'superadmin:customer_structures', 'fas fa-sitemap', 27, False),
                ('Content Generation Management', 'superadmin:customer_contents', 'fas fa-file-signature', 28, False),
                ('Customer Ticket Management', 'superadmin:customer_tickets', 'fas fa-ticket-alt', 29, False),
                ('Meeting Management', 'superadmin:customer_meetings', 'fas fa-handshake', 30, False),
                ('Booking Management', 'superadmin:customer_bookings', 'fas fa-calendar-check', 31, False),
                ('Customer Analytics Dashboard', 'superadmin:customer_analytics', 'fas fa-chart-pie', 32, False),
            ],
            cls.ROLE_MARKETING: [
                ('Welcome', 'marketing:welcome', 'fas fa-home', 0, True),
                ('Dashboard', 'marketing:dashboard', 'fas fa-chart-line', 1, False),
                ('Statistics', 'marketing:statistics', 'fas fa-chart-pie', 2, False),
                ('All Projects', 'marketing:all_projects', 'fas fa-folder-open', 3, False),
                ('Create Job', 'marketing:create_job', 'fas fa-plus-circle', 4, False),
                ('My Tickets', 'tickets:marketing-ticket-list', 'fas fa-ticket-alt', 5, False),
                ('Create Ticket', 'tickets:marketing-ticket-create', 'fas fa-plus-square', 6, False),
                ('Holiday Calendar', 'holidays:list', 'fas fa-umbrella-beach', 7, False),
            ],
        }

    @classmethod
    def ensure_defaults(cls, role):
        defaults = cls._default_menu().get(role, [])
        for label, url_name, icon, position, is_fixed in defaults:
            cls.objects.get_or_create(
                role=role,
                url_name=url_name,
                defaults={
                    'label': label,
                    'icon_class': icon,
                    'position': position,
                    'is_fixed': is_fixed,
                    'is_active': True,
                },
            )

    @classmethod
    def ordered_for_role(cls, role):
        try:
            cls.ensure_defaults(role)
            qs = cls.objects.filter(role=role, is_active=True).order_by('position', 'label')

            valid_items = []
            for item in qs:
                try:
                    reverse(item.url_name)
                    valid_items.append(item)
                except NoReverseMatch:
                    continue
            return valid_items
        except Exception:
            # If the menu collection/table is missing or another DB issue occurs,
            # fail soft and return an empty menu.
            return []
