from datetime import datetime

from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from accounts.forms import COUNTRY_CODES
from accounts.models import User
from accounts.validators import validate_whatsapp_number
from superadmin.models import Announcement, PricingPlan, SystemSettings, GoogleAuthConfig


class UserCreateForm(forms.ModelForm):
    auto_generate_password = forms.BooleanField(
        required=False,
        initial=True,
        label='Auto-generate password'
    )
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Enter a password'}),
        label='Password'
    )

    joining_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        label='Joining date'
    )

    class Meta:
        model = User
        fields = [
            'first_name',
            'last_name',
            'email',
            'whatsapp_country_code',
            'whatsapp_no',
            'last_qualification',
            'role',
            'is_active',
            'joining_date',
        ]
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'First name'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Last name'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Email address'}),
            'whatsapp_country_code': forms.Select(attrs={'class': 'form-select'}, choices=COUNTRY_CODES),
            'whatsapp_no': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'WhatsApp number'}),
            'last_qualification': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Last qualification'}),
            'role': forms.Select(attrs={'class': 'form-select'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        labels = {
            'is_active': 'Active Status',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['whatsapp_country_code'].choices = COUNTRY_CODES
        if not self.instance or not self.instance.pk:
            self.fields['is_active'].initial = True

    def clean_whatsapp_no(self):
        number = self.cleaned_data.get('whatsapp_no', '')
        validate_whatsapp_number(number)
        return number

    def clean(self):
        cleaned = super().clean()
        auto = cleaned.get('auto_generate_password')
        password = cleaned.get('password')
        if not auto and not password:
            self.add_error('password', _('Enter a password or enable auto-generation.'))
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        auto = self.cleaned_data.get('auto_generate_password')
        password = self.cleaned_data.get('password')
        if auto or not password:
            password = User.objects.make_random_password()
            self.generated_password = password
        else:
            self.generated_password = None
        user.set_password(password)
        self.plaintext_password = password
        user.is_approved = True
        user.is_staff = user.role == 'SUPERADMIN'
        if commit:
            user.save()
        return user


class UserUpdateForm(forms.ModelForm):
    reset_password = forms.BooleanField(
        required=False,
        label='Reset password'
    )
    new_password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'New password'}),
        label='New password'
    )
    joining_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        label='Joining date'
    )

    class Meta:
        model = User
        fields = [
            'first_name',
            'last_name',
            'email',
            'whatsapp_country_code',
            'whatsapp_no',
            'last_qualification',
            'role',
            'is_active',
            'joining_date',
        ]
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'whatsapp_country_code': forms.Select(attrs={'class': 'form-select'}, choices=COUNTRY_CODES),
            'whatsapp_no': forms.TextInput(attrs={'class': 'form-control'}),
            'last_qualification': forms.TextInput(attrs={'class': 'form-control'}),
            'role': forms.Select(attrs={'class': 'form-select'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        labels = {'is_active': 'Active Status'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['whatsapp_country_code'].choices = COUNTRY_CODES

    def clean_whatsapp_no(self):
        number = self.cleaned_data.get('whatsapp_no', '')
        validate_whatsapp_number(number)
        return number

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_staff = user.role == 'SUPERADMIN'
        user.is_approved = True
        self.generated_password = None
        new_password = None
        self.plaintext_password = None
        if self.cleaned_data.get('reset_password'):
            new_password = self.cleaned_data.get('new_password') or User.objects.make_random_password()
            self.generated_password = new_password
            self.plaintext_password = new_password
            user.set_password(new_password)
        if commit:
            user.save()
        return user


class SystemSettingsForm(forms.ModelForm):
    class Meta:
        model = SystemSettings
        fields = [
            'default_turnaround_days',
            'max_upload_size_mb',
            'allowed_file_types',
            'rework_limit',
            'auto_close_days',
        ]
        widgets = {
            'default_turnaround_days': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'max_upload_size_mb': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'allowed_file_types': forms.TextInput(attrs={'class': 'form-control'}),
            'rework_limit': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'auto_close_days': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
        }

    def clean_allowed_file_types(self):
        value = self.cleaned_data.get('allowed_file_types', '')
        cleaned = ",".join(
            sorted({part.strip().lower().strip('.')
                    for part in value.split(',') if part.strip()})
        )
        if not cleaned:
            raise forms.ValidationError('Provide at least one file extension.')
        return cleaned


class PricingPlanForm(forms.ModelForm):
    class Meta:
        model = PricingPlan
        fields = [
            'name',
            'short_description',
            'coin_amount',
            'price',
            'currency',
            'validity_days',
            'plan_type',
            'benefits',
            'limit_job_checks_per_day',
            'limit_structures_per_day',
            'limit_contents_per_day',
            'limit_job_checks_per_month',
            'limit_structures_per_month',
            'limit_contents_per_month',
            'special_conditions',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Starter / Pro / Enterprise'}),
            'short_description': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Short summary for customers'}),
            'coin_amount': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'price': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'step': '0.01'}),
            'currency': forms.TextInput(attrs={'class': 'form-control', 'maxlength': 10}),
            'validity_days': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'placeholder': 'Leave blank for no expiry'}),
            'plan_type': forms.Select(attrs={'class': 'form-select'}),
            'benefits': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Benefit 1\\nBenefit 2'}),
            'limit_job_checks_per_day': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'limit_structures_per_day': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'limit_contents_per_day': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'limit_job_checks_per_month': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'limit_structures_per_month': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'limit_contents_per_month': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'special_conditions': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Special conditions e.g., No expiry on coins'}),
        }
        labels = {
            'coin_amount': 'Coins included',
            'validity_days': 'Validity (days)',
        }

    def clean_coin_amount(self):
        coins = self.cleaned_data.get('coin_amount') or 0
        if coins < 0:
            raise forms.ValidationError('Coins must be zero or a positive number.')
        return coins

    def clean_price(self):
        price = self.cleaned_data.get('price') or 0
        if price < 0:
            raise forms.ValidationError('Price cannot be negative.')
        return price

    def clean_validity_days(self):
        days = self.cleaned_data.get('validity_days')
        if days is not None and days <= 0:
            return None
        return days


class AnnouncementForm(forms.ModelForm):
    remove_attachment = forms.BooleanField(
        required=False,
        initial=False,
        label='Remove attachment',
    )

    datetime_format = '%Y-%m-%dT%H:%M'

    start_at = forms.DateTimeField(
        widget=forms.DateTimeInput(
            attrs={'class': 'form-control', 'type': 'datetime-local'},
            format=datetime_format,
        ),
        input_formats=[datetime_format],
    )
    end_at = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(
            attrs={'class': 'form-control', 'type': 'datetime-local'},
            format=datetime_format,
        ),
        input_formats=[datetime_format],
    )

    class Meta:
        model = Announcement
        fields = [
            'title',
            'body',
            'type',
            'visibility',
            'attachment',
            'link_url',
            'start_at',
            'end_at',
            'is_active',
        ]
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Announcement title'}),
            'body': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Write the message'}),
            'type': forms.Select(attrs={'class': 'form-select'}),
            'visibility': forms.Select(attrs={'class': 'form-select'}),
            'attachment': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'link_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'Optional link'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        labels = {
            'is_active': 'Active',
            'link_url': 'Optional link/URL',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Format datetime defaults for HTML datetime-local inputs
        tz = timezone.get_current_timezone()
        for field_name in ('start_at', 'end_at'):
            value = self.initial.get(field_name) or getattr(self.instance, field_name, None)
            if isinstance(value, datetime):
                localized = timezone.localtime(value, tz)
                self.initial[field_name] = localized.strftime(self.datetime_format)

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('start_at')
        end = cleaned.get('end_at')
        if start and end and end <= start:
            self.add_error('end_at', _('End time must be after the start time.'))
        return cleaned

    def save(self, commit=True):
        announcement = super().save(commit=False)
        remove_attachment = self.cleaned_data.get('remove_attachment')
        if remove_attachment and announcement.attachment:
            announcement.attachment.delete(save=False)
            announcement.attachment = None
        if commit:
            announcement.save()
            self.save_m2m()
        return announcement


class GoogleAuthConfigForm(forms.ModelForm):
    class Meta:
        model = GoogleAuthConfig
        fields = [
            'enabled',
            'allow_signup',
            'mode',
            'allowed_domains',
            'allow_customer',
            'allow_marketing',
            'allow_superadmin',
            'client_id',
            'client_secret',
            'redirect_url',
            'show_health_warning',
        ]
        widgets = {
            'allowed_domains': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'example.com, partner.edu'}),
            'client_id': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Google OAuth Client ID'}),
            'client_secret': forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Google OAuth Client Secret', 'render_value': True}),
            'redirect_url': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. http://127.0.0.1:8000/accounts/social/google/login/callback/'}),
            'mode': forms.Select(attrs={'class': 'form-select'}),
        }
        labels = {
            'allow_signup': 'Allow Google-based signup',
            'allow_customer': 'Allow Customers',
            'allow_marketing': 'Allow Marketing',
            'allow_superadmin': 'Allow Super Admin',
            'show_health_warning': 'Show warning banner if misconfigured',
        }

    def clean_allowed_domains(self):
        data = self.cleaned_data.get('allowed_domains', '')
        parts = [p.strip().lower() for p in data.split(',') if p.strip()]
        return ','.join(parts)


class BackupExportForm(forms.Form):
    FORMAT_CHOICES = [
        ('xlsx', 'Excel (.xlsx, multi-sheet)'),
        ('csv', 'CSV (.zip, one file per table)'),
    ]

    export_format = forms.ChoiceField(
        choices=FORMAT_CHOICES,
        label='Export format',
        widget=forms.RadioSelect,
    )
    include_all = forms.BooleanField(
        required=False,
        initial=False,
        label='Include every table in the backup',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
    )
    status = forms.ChoiceField(
        required=False,
        label='Module (Status)',
        choices=[],
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    tables = forms.MultipleChoiceField(
        required=False,
        label='Sub Status (Tables)',
        widget=forms.CheckboxSelectMultiple,
    )
    start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        label='Start date',
    )
    end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        label='End date',
    )

    def __init__(self, *args, table_metadata=None, **kwargs):
        self.table_metadata = table_metadata or []
        super().__init__(*args, **kwargs)
        app_labels = sorted({item['app_label'] for item in self.table_metadata})
        self.fields['status'].choices = [('', 'All modules')] + [
            (label, label.replace('_', ' ').title()) for label in app_labels
        ]
        selected_status = self.data.get(self.add_prefix('status')) or self.initial.get('status')
        self.selected_status = selected_status
        table_choices = [
            (item['key'], item['choice_label']) for item in self.table_metadata
        ]
        self.fields['tables'].choices = table_choices

    def clean(self):
        cleaned = super().clean()
        include_all = cleaned.get('include_all')
        tables = cleaned.get('tables') or []
        status = cleaned.get('status') or self.selected_status
        if not include_all and not tables and not status:
            self.add_error(
                'tables',
                _('Select at least one table or enable "Include every table".'),
            )
        start = cleaned.get('start_date')
        end = cleaned.get('end_date')
        if start and end and start > end:
            self.add_error('end_date', _('End date must be after the start date.'))
        return cleaned
