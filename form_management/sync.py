import inspect
from importlib import import_module

from django import forms as django_forms
from django.conf import settings
from django.utils.text import slugify

from form_management.models import FormDefinition, FormField


def _field_type(field):
    mapping = {
        'charfield': 'text',
        'textfield': 'text',
        'integerfield': 'number',
        'floatfield': 'number',
        'decimalfield': 'number',
        'datefield': 'date',
        'datetimefield': 'datetime',
        'timefield': 'text',
        'choicefield': 'select',
        'multiplechoicefield': 'select',
        'typedchoicefield': 'select',
        'booleanfield': 'checkbox',
    }
    name = field.__class__.__name__.lower()
    return mapping.get(name, 'text')


def sync_forms_from_modules():
    module_paths = getattr(settings, 'FORM_MANAGEMENT_FORM_MODULES', [])
    if not module_paths:
        return

    for module_path in module_paths:
        try:
            module = import_module(module_path)
        except ModuleNotFoundError:
            continue

        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if not inspect.isclass(attr):
                continue
            if not issubclass(attr, django_forms.BaseForm):
                continue
            if attr in (django_forms.BaseForm, django_forms.Form, django_forms.ModelForm):
                continue

            if attr.base_fields is None:
                continue

            slug = slugify(f'{module_path}-{attr_name}')
            visible_roles = 'SUPERADMIN,MARKETING'
            form_obj, _ = FormDefinition.objects.get_or_create(
                slug=slug,
                defaults={
                    'name': attr_name.replace('_', ' '),
                    'description': f'Auto-detected from {module_path}',
                    'visible_roles': visible_roles,
                    'order': FormDefinition.objects.count() + 1,
                    'is_active': True,
                },
            )

            existing_names = []
            for order, (name, field) in enumerate(attr.base_fields.items(), start=1):
                existing_names.append(name)
                FormField.objects.update_or_create(
                    form=form_obj,
                    name=name,
                    defaults={
                        'label': getattr(field, 'label', name.title()),
                        'field_type': _field_type(field),
                        'order': order,
                        'visible_roles': visible_roles,
                        'required_roles': visible_roles if field.required else '',
                        'readonly_roles': '',
                        'is_active': True,
                    },
                )
            FormField.objects.filter(form=form_obj).exclude(name__in=existing_names).delete()
