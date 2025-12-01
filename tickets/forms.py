# tickets/forms.py
from django import forms
from .models import Ticket

class MarketingTicketForm(forms.ModelForm):
    class Meta:
        model = Ticket
        fields = [
            'job_id', 'title', 'description',
            'topic', 'word_count', 'referencing_style',
            'priority', 'deadline', 'question_file',
            'marketing_notes',
        ]
        widgets = {
            'job_id': forms.TextInput(attrs={'class': 'form-control'}),
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'topic': forms.TextInput(attrs={'class': 'form-control'}),
            'word_count': forms.NumberInput(attrs={'class': 'form-control'}),
            'referencing_style': forms.TextInput(attrs={'class': 'form-control'}),
            'priority': forms.Select(attrs={'class': 'form-select'}),
            'deadline': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'question_file': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'marketing_notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class SuperAdminTicketForm(forms.ModelForm):
    class Meta:
        model = Ticket
        fields = [
            'priority', 'status', 'final_file',
            'superadmin_notes',
        ]
        widgets = {
            'priority': forms.Select(attrs={'class': 'form-select'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'final_file': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'superadmin_notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }
