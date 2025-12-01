from django import forms

from .models import Holiday


class HolidayForm(forms.ModelForm):
    applies_to = forms.MultipleChoiceField(
        choices=Holiday.TEAM_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text='Select the teams the holiday applies to (leave empty for all).'
    )

    start_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    end_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))

    class Meta:
        model = Holiday
        fields = ['title', 'holiday_type', 'start_date', 'end_date', 'applies_to', 'notes']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Holiday title'}),
            'holiday_type': forms.Select(attrs={'class': 'form-select'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Optional notes'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            if self.instance.applies_to and self.instance.applies_to != Holiday.TEAM_ALL:
                self.initial['applies_to'] = self.instance.applies_to.split(',')

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get('start_date')
        end = cleaned_data.get('end_date')
        holiday_type = cleaned_data.get('holiday_type')

        if start and end:
            if holiday_type == Holiday.HOLIDAY_TYPE_SINGLE:
                cleaned_data['end_date'] = start
            elif end < start:
                self.add_error('end_date', 'End date cannot be before start date.')

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        selected_teams = self.cleaned_data.get('applies_to')
        if selected_teams:
            instance.applies_to = ','.join(selected_teams)
        else:
            instance.applies_to = Holiday.TEAM_ALL
        if commit:
            instance.save()
        return instance
