from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.core.exceptions import ValidationError
from .models import User
from .validators import validate_whatsapp_number, validate_name_length

COUNTRY_CODES = [
    ('+1', 'USA/Canada (+1)'),
    ('+44', 'UK (+44)'),
    ('+91', 'India (+91)'),
    ('+61', 'Australia (+61)'),
    ('+86', 'China (+86)'),
    ('+81', 'Japan (+81)'),
    ('+82', 'South Korea (+82)'),
    ('+971', 'UAE (+971)'),
    ('+65', 'Singapore (+65)'),
]

class SignUpForm(UserCreationForm):
    first_name = forms.CharField(
        max_length=25,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter first name (min 25 characters)'
        }),
        error_messages={
            'max_length': 'First Name cannot be longer than 25 characters.',
        },
    )
    last_name = forms.CharField(
        max_length=25,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter last name (min 25 characters)'
        }),
        error_messages={
            'max_length': 'Last Name cannot be longer than 25 characters.',
        },
    )
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter email address'
        })
    )
    whatsapp_country_code = forms.ChoiceField(
        choices=COUNTRY_CODES,
        initial='+91',
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    whatsapp_no = forms.CharField(
        max_length=10,
        required=True,
        validators=[validate_whatsapp_number],
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter 10 digit WhatsApp number',
            'maxlength': '10',
            'pattern': '\\d{10}',
            'inputmode': 'numeric',
            'title': 'Enter exactly 10 digits'
        })
    )
    last_qualification = forms.CharField(
        max_length=100,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter last qualification (max 100 characters)'
        })
    )
    password1 = forms.CharField(
        label='Create Password',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Minimum 8 characters (letters, numbers, symbols)'
        })
    )
    password2 = forms.CharField(
        label='Confirm Password',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Re-enter password'
        })
    )
    
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'whatsapp_country_code', 
                  'whatsapp_no', 'last_qualification', 'password1', 'password2']
    
    def clean_first_name(self):
        first_name = self.cleaned_data.get('first_name')
        validate_name_length(first_name, 'First Name')
        return first_name
    
    def clean_last_name(self):
        last_name = self.cleaned_data.get('last_name')
        validate_name_length(last_name, 'Last Name')
        return last_name
    
    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise ValidationError('This email is already registered.')
        return email
    
    def clean_whatsapp_no(self):
        number = self.cleaned_data.get('whatsapp_no')
        if not number.isdigit():
            raise ValidationError('WhatsApp number must contain only digits.')
        if len(number) != 10:
            raise ValidationError('WhatsApp number must be exactly 10 digits.')
        return number
    
    def clean_last_qualification(self):
        qualification = self.cleaned_data.get('last_qualification')
        if len(qualification) > 100:
            raise ValidationError('Qualification cannot exceed 100 characters.')
        return qualification
    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = 'marketing'  # Default role
        country_code = self.cleaned_data.get('whatsapp_country_code')
        user.whatsapp_country_code = country_code
        
        if commit:
            user.save()
        return user

class LoginForm(AuthenticationForm):
    username = forms.EmailField(
        label='Email',
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your email'
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your password'
        })
    )
    def confirm_login_allowed(self, user):
        if not user.is_active:
            raise ValidationError(
                'This account is inactive.',
                code='inactive',
            )
        if not user.is_approved:
            raise ValidationError(
                'Your account is pending approval. Please wait for admin verification.',
                code='not_approved',
            )
