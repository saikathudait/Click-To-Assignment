from django.db import models


class FormDefinition(models.Model):
    ROLE_MARKETING = 'MARKETING'
    ROLE_SUPERADMIN = 'SUPERADMIN'
    ROLE_CHOICES = [
        (ROLE_MARKETING, 'Marketing'),
        (ROLE_SUPERADMIN, 'Super Admin'),
    ]

    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    visible_roles = models.CharField(
        max_length=255,
        blank=True,
        help_text='Comma separated roles that can see the form'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'name']

    def __str__(self):
        return self.name

    def visible_roles_list(self):
        if not self.visible_roles:
            return []
        return [role for role in self.visible_roles.split(',') if role]


class FormField(models.Model):
    FIELD_TEXT = 'text'
    FIELD_TEXTAREA = 'textarea'
    FIELD_SELECT = 'select'
    FIELD_NUMBER = 'number'
    FIELD_DATE = 'date'
    FIELD_DATETIME = 'datetime'
    FIELD_CHECKBOX = 'checkbox'
    FIELD_CHOICES = [
        (FIELD_TEXT, 'Text'),
        (FIELD_TEXTAREA, 'Textarea'),
        (FIELD_SELECT, 'Select'),
        (FIELD_NUMBER, 'Number'),
        (FIELD_DATE, 'Date'),
        (FIELD_DATETIME, 'DateTime'),
        (FIELD_CHECKBOX, 'Checkbox'),
    ]

    form = models.ForeignKey(FormDefinition, on_delete=models.CASCADE, related_name='fields')
    label = models.CharField(max_length=255)
    name = models.SlugField(max_length=255)
    field_type = models.CharField(max_length=20, choices=FIELD_CHOICES, default=FIELD_TEXT)
    order = models.PositiveIntegerField(default=0)
    visible_roles = models.CharField(max_length=255, blank=True)
    required_roles = models.CharField(max_length=255, blank=True)
    readonly_roles = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['order', 'label']

    def __str__(self):
        return f'{self.label} ({self.form.name})'

    def _roles_list(self, attr):
        value = getattr(self, attr)
        if not value:
            return []
        return [role for role in value.split(',') if role]

    def visible_roles_list(self):
        return self._roles_list('visible_roles')

    def required_roles_list(self):
        return self._roles_list('required_roles')

    def readonly_roles_list(self):
        return self._roles_list('readonly_roles')
