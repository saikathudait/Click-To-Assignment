from django import forms
from django.contrib.auth.forms import PasswordChangeForm
from .models import ProfileUpdateRequest
from accounts.models import User, CountryCode



class ProfileUpdateRequestForm(forms.Form):
    """Form for requesting profile updates"""
    
    REQUEST_TYPE_CHOICES = [
        ('', 'Select field to update'),
        ('profile_picture', 'Profile Picture'),
        ('first_name', 'First Name'),
        ('last_name', 'Last Name'),
        ('email', 'Email ID'),
        ('whatsapp_number', 'WhatsApp Number'),
        ('last_qualification', 'Last Qualification'),
    ]
    
    request_type = forms.ChoiceField(
        choices=REQUEST_TYPE_CHOICES,
        required=True,
        widget=forms.Select(attrs={'class': 'form-control', 'id': 'request_type'})
    )
    
    # Profile Picture
    new_profile_picture = forms.ImageField(
        required=False,
        widget=forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'})
    )
    
    # Text fields
    updated_value = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter new value'})
    )
    
    # WhatsApp specific
    whatsapp_country_code = forms.ModelChoiceField(
        queryset=CountryCode.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    whatsapp_number = forms.CharField(
        required=False,
        max_length=15,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter 10 digit number'})
    )
    
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
    
    def clean(self):
        cleaned_data = super().clean()
        request_type = cleaned_data.get('request_type')
        
        if not request_type:
            raise forms.ValidationError('Please select a field to update.')
        
        if request_type == 'profile_picture':
            if not cleaned_data.get('new_profile_picture'):
                raise forms.ValidationError('Please upload a profile picture.')
        elif request_type == 'whatsapp_number':
            if not cleaned_data.get('whatsapp_country_code') or not cleaned_data.get('whatsapp_number'):
                raise forms.ValidationError('Please provide both country code and WhatsApp number.')
            
            number = cleaned_data.get('whatsapp_number')
            if not number.isdigit() or len(number) != 10:
                raise forms.ValidationError('WhatsApp number must be exactly 10 digits.')
        else:
            if not cleaned_data.get('updated_value'):
                raise forms.ValidationError('Please provide the updated value.')
            
            # Validate based on type
            if request_type == 'email':
                from django.core.validators import validate_email
                from django.core.exceptions import ValidationError as DjangoValidationError
                try:
                    validate_email(cleaned_data.get('updated_value'))
                except DjangoValidationError:
                    raise forms.ValidationError('Please enter a valid email address.')
                
                # Check if email already exists
                if User.objects.filter(email=cleaned_data.get('updated_value')).exclude(id=self.user.id).exists():
                    raise forms.ValidationError('This email is already registered.')
            
            elif request_type in ['first_name', 'last_name']:
                if len(cleaned_data.get('updated_value')) > 25:
                    raise forms.ValidationError(f'{request_type.replace("_", " ").title()} cannot exceed 25 characters.')
            
            elif request_type == 'last_qualification':
                if len(cleaned_data.get('updated_value')) > 100:
                    raise forms.ValidationError('Last Qualification cannot exceed 100 characters.')
        
        return cleaned_data

class CustomPasswordChangeForm(PasswordChangeForm):
    old_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Current Password'})
    )
    new_password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'New Password'})
    )
    new_password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Confirm New Password'})
    )
    
    
class SuperAdminProfileUpdateForm(forms.ModelForm):
    """Form for SuperAdmin to update their own profile"""
    
    # Extra (non-model) fields
    profile_picture = forms.ImageField(
        required=False,
        widget=forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
        label='Profile Picture'
    )

    whatsapp_country_code = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
        label='WhatsApp Country Code'
    )

    whatsapp_number = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
        label='WhatsApp Number'
    )
    
    last_qualification = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
        label='Last Qualification'
    )

    
    email_notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Enter reason for email change (mandatory if changing email)'
        }),
        label='Email Change Notes'
    )
    
    whatsapp_notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Enter reason for WhatsApp number change (mandatory if changing number)'
        }),
        label='WhatsApp Change Notes'
    )
    
    class Meta:
        model = User
        fields = ['profile_picture', 'first_name', 'last_name', 'email', 
                 'whatsapp_country_code', 'whatsapp_number', 'last_qualification']
        widgets = {
            'profile_picture': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'whatsapp_country_code': forms.TextInput(attrs={'class': 'form-control'}),
            'whatsapp_number': forms.TextInput(attrs={'class': 'form-control'}),
            'last_qualification': forms.TextInput(attrs={'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial_email = self.instance.email
        self.initial_whatsapp = self.instance.whatsapp_number
    
    def clean(self):
        cleaned_data = super().clean()
        email = cleaned_data.get('email')
        whatsapp_number = cleaned_data.get('whatsapp_number')
        email_notes = cleaned_data.get('email_notes')
        whatsapp_notes = cleaned_data.get('whatsapp_notes')
        
        # Check if email changed and notes provided
        if email != self.initial_email and not email_notes:
            raise forms.ValidationError('Email change notes are mandatory when changing email address.')
        
        # Check if WhatsApp changed and notes provided
        if whatsapp_number != self.initial_whatsapp and not whatsapp_notes:
            raise forms.ValidationError('WhatsApp change notes are mandatory when changing WhatsApp number.')
        
        return cleaned_data