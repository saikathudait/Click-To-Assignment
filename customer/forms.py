from django import forms
from django.contrib.auth.forms import PasswordChangeForm
from accounts.models import User
from accounts.validators import validate_whatsapp_number, validate_name_length


class CustomerProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'whatsapp_country_code', 'whatsapp_no', 'last_qualification']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'First name'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Last name'}),
            'whatsapp_country_code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+91'}),
            'whatsapp_no': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '10 digit number', 'maxlength': '10', 'pattern': '\\d{10}', 'inputmode': 'numeric'}),
            'last_qualification': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Last qualification'}),
        }

    def clean_first_name(self):
        value = self.cleaned_data.get('first_name', '')
        validate_name_length(value, 'First Name')
        return value

    def clean_last_name(self):
        value = self.cleaned_data.get('last_name', '')
        validate_name_length(value, 'Last Name')
        return value

    def clean_whatsapp_no(self):
        number = self.cleaned_data.get('whatsapp_no', '')
        validate_whatsapp_number(number)
        return number


class CustomerPasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})
