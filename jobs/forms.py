# jobs/forms.py

from datetime import timedelta
from django.utils import timezone
from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
import os
from .models import Job, Attachment, JobReworkRequest
from holidays.models import Holiday



class MultiFileInput(forms.ClearableFileInput):
    """
    Widget that allows selecting multiple files in a single input.
    """
    allow_multiple_selected = True


class MultiFileField(forms.Field):
    """
    Custom field that accepts multiple uploaded files.
    The cleaned value is always a list (possibly empty).
    """
    widget = MultiFileInput
    default_error_messages = {
        "required": "Please upload at least one file.",
        "invalid": "Invalid file upload.",
    }

    def to_python(self, data):
        """
        Normalize the incoming data into a list of files.
        """
        if not data:
            return []

        # If Django already gives us a list/tuple of files
        if isinstance(data, (list, tuple)):
            return list(data)

        # Single file → wrap in list
        return [data]

    def validate(self, value):
        """
        Run the parent `validate` to handle 'required' logic.
        `value` is a list (possibly empty).
        """
        super().validate(value)
        # No extra required checks here; custom validation is in the form's clean()


class JobDropForm(forms.ModelForm):
    """
    Form for dropping/creating a job with multiple attachments.
    """
    attachments = MultiFileField(
        required=False,
        widget=MultiFileInput(
            attrs={
                "multiple": True,
                "class": "form-control",
                "accept": ".doc,.docx,.pdf,.png,.jpg,.jpeg,.pptx,.csv,.xlsx,.xls",
            }
        ),
        help_text=(
            "Upload multiple files (DOC, DOCX, PDF, PNG, JPG, JPEG, "
            "PPTX, CSV, XLSX, XLS)"
        ),
    )

    class Meta:
        model = Job
        fields = [
            "job_id",
            "instruction",
            "amount",
            "expected_deadline",
            "strict_deadline",
        ]
        widgets = {
            "job_id": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Enter unique Job ID from customer",
                }
            ),
            "instruction": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 6,
                    "maxlength": 10000,
                    "placeholder": "Enter job instructions (max 10000 characters)",
                }
            ),
            "amount": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.01",
                    "min": "0",
                    "placeholder": "Enter amount in INR",
                }
            ),
            "expected_deadline": forms.DateTimeInput(
                attrs={
                    "class": "form-control",
                    "type": "datetime-local",
                }
            ),
            "strict_deadline": forms.DateTimeInput(
                attrs={
                    "class": "form-control",
                    "type": "datetime-local",
                }
            ),
        }
        labels = {
            'job_id': 'Job ID (From Customer)',
            'instruction': 'Instructions',
            'amount': 'Amount (INR)',
            'expected_deadline': 'Expected Deadline (Date and Time IST)',
            'strict_deadline': 'Strict Deadline (Date and Time IST)',
        }

    def clean_job_id(self):
        job_id = self.cleaned_data.get("job_id")
        if not job_id:
            return job_id
        qs = Job.objects.filter(job_id=job_id)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("This Job ID already exists. Please use a unique Job ID.")
        return job_id
    
    def clean_instruction(self):
        instruction = self.cleaned_data.get('instruction')
        if len(instruction) > 10000:
            raise ValidationError('Instructions cannot exceed 10000 characters.')
        return instruction
    
    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        if amount < 0:
            raise ValidationError('Amount cannot be negative.')
        return amount
    

    def clean(self):
        cleaned_data = super().clean()
        expected_deadline = cleaned_data.get("expected_deadline")
        strict_deadline = cleaned_data.get("strict_deadline")

        # Validate deadline relationship
        if expected_deadline and strict_deadline:
            min_strict_deadline = expected_deadline + timedelta(hours=24)
            if strict_deadline < min_strict_deadline:
                raise ValidationError(
                    {
                        "strict_deadline": (
                            "Strict deadline must be at least 24 hours "
                            "after the expected deadline."
                        )
                    }
                )

        def _blocked_reason(dt):
            if not dt:
                return None
            if timezone.is_aware(dt):
                date_value = timezone.localtime(dt).date()
            else:
                date_value = dt.date()

            if date_value.weekday() == 6:  # Sunday
                return "Sundays cannot be selected as deadlines. Please choose another day."

            holidays = Holiday.objects.filter(
                start_date__lte=date_value,
                end_date__gte=date_value,
            )
            for holiday in holidays:
                applies = holiday.applies_to or Holiday.TEAM_ALL
                if applies == Holiday.TEAM_ALL:
                    return f"{holiday.title} is a holiday. Please choose another day."
                teams = [item.strip() for item in applies.split(',') if item.strip()]
                if Holiday.TEAM_MARKETING in teams:
                    return f"{holiday.title} is a holiday for Marketing. Please choose another day."
            return None

        expected_reason = _blocked_reason(expected_deadline)
        strict_reason = _blocked_reason(strict_deadline)
        if expected_reason:
            self.add_error('expected_deadline', expected_reason)
        if strict_reason:
            self.add_error('strict_deadline', strict_reason)

        # Validate attachments (size and extension)
        files = cleaned_data.get("attachments") or []

        for file in files:
            # Size check
            if file.size > settings.MAX_UPLOAD_SIZE:
                raise ValidationError(
                    f"File {file.name} exceeds maximum size of 50MB."
                )

            # Extension check
            ext = file.name.split(".")[-1].lower()
            if ext not in settings.ALLOWED_UPLOAD_EXTENSIONS:
                raise ValidationError(f"File type .{ext} is not allowed.")

        return cleaned_data
    
    def clean_attachments(self):
        """Validate uploaded files"""
        files = self.files.getlist('attachments')
        
        allowed_extensions = [
            'doc', 'docx', 'pdf', 'png', 'jpg', 'jpeg', 
            'pptx', 'csv', 'xlsx', 'xls'
        ]
        
        max_file_size = 10 * 1024 * 1024  # 10MB
        
        for file in files:
            # Check file extension
            ext = os.path.splitext(file.name)[1][1:].lower()
            if ext not in allowed_extensions:
                raise ValidationError(
                    f'File type "{ext}" is not allowed. Allowed types: {", ".join(allowed_extensions)}'
                )
            
            # Check file size
            if file.size > max_file_size:
                raise ValidationError(
                    f'File "{file.name}" is too large. Maximum size is 10MB.'
                )
        
        return files
    
    
class JobFilterForm(forms.Form):
    """Form for filtering jobs"""
    
    STATUS_CHOICES = [
        ('', 'All Status'),
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('rejected', 'Rejected'),
    ]
    
    status = forms.ChoiceField(
        choices=STATUS_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        })
    )


class JobReworkForm(forms.ModelForm):
    class Meta:
        model = JobReworkRequest
        fields = ['reason', 'expected_deadline', 'attachment']
        widgets = {
            'reason': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Explain what needs to be fixed.',
                'maxlength': 1000,
                'required': True,
            }),
            'expected_deadline': forms.DateTimeInput(attrs={
                'class': 'form-control',
                'type': 'datetime-local',
            }),
            'attachment': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': '.doc,.docx,.pdf,.png,.jpg,.jpeg,.pptx,.csv,.xlsx,.xls'
            }),
        }
        labels = {
            'reason': 'Comment',
            'expected_deadline': 'Expected Deadline',
            'attachment': 'Attachment',
        }

    def clean_reason(self):
        comment = (self.cleaned_data.get('reason') or '').strip()
        if not comment:
            raise ValidationError('Comment is required.')
        return comment

    def clean_attachment(self):
        file = self.cleaned_data.get('attachment')
        if not file:
            return file
        max_size = settings.MAX_UPLOAD_SIZE
        allowed_ext = settings.ALLOWED_UPLOAD_EXTENSIONS
        if file.size > max_size:
            raise ValidationError('Attachment exceeds maximum allowed size.')
        ext = file.name.split('.')[-1].lower()
        if ext not in allowed_ext:
            raise ValidationError(f'.{ext} files are not allowed.')
        return file

    def clean_expected_deadline(self):
        deadline = self.cleaned_data.get('expected_deadline')
        if not deadline:
            raise ValidationError('Expected deadline is required.')
        return deadline
    
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        })
    )
    
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search by Job ID or System ID'
        })
    )
