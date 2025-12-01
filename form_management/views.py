from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from form_management.models import FormDefinition, FormField
from form_management.sync import sync_forms_from_modules
from superadmin.views import superadmin_required


def _card_state(params, **overrides):
    result = params.copy()
    for key, value in overrides.items():
        if value:
            result[key] = value
        else:
            result.pop(key, None)
    return result


def _build_query(params):
    query = params.urlencode()
    return f'?{query}' if query else '?'


@login_required
@superadmin_required
def form_list_view(request):
    sync_forms_from_modules()
    status_filter = (request.GET.get('status') or '').upper()

    all_forms = list(FormDefinition.objects.all())
    stats = {
        'total': len(all_forms),
        'active': sum(1 for form in all_forms if form.is_active),
        'inactive': sum(1 for form in all_forms if not form.is_active),
    }

    filtered_forms = all_forms
    if status_filter == 'ACTIVE':
        filtered_forms = [form for form in filtered_forms if form.is_active]
    elif status_filter == 'INACTIVE':
        filtered_forms = [form for form in filtered_forms if not form.is_active]

    per_page = max(len(filtered_forms), 1)  # show all forms on one page
    paginator = Paginator(filtered_forms, per_page)
    page_obj = paginator.get_page(request.GET.get('page'))

    params = request.GET.copy()
    params.pop('page', None)
    filter_query = params.urlencode()
    pagination_base = f'?{filter_query}&' if filter_query else '?'

    base_params = request.GET.copy()
    base_params.pop('page', None)
    base_params.pop('edit', None)
    card_urls = {
        'total': _build_query(_card_state(base_params, status=None)),
        'active': _build_query(_card_state(base_params, status='ACTIVE')),
        'inactive': _build_query(_card_state(base_params, status='INACTIVE')),
    }

    card_active = {
        'total': status_filter not in ('ACTIVE', 'INACTIVE'),
        'active': status_filter == 'ACTIVE',
        'inactive': status_filter == 'INACTIVE',
    }

    context = {
        'stats': stats,
        'page_obj': page_obj,
        'pagination_base': pagination_base,
        'per_page': per_page,
        'filter_query': filter_query,
        'card_urls': card_urls,
        'card_active': card_active,
    }
    return render(request, 'form_management/list.html', context)


@login_required
@superadmin_required
def form_detail_view(request, slug):
    sync_forms_from_modules()
    form_obj = get_object_or_404(FormDefinition, slug=slug)
    fields = list(form_obj.fields.all())
    role_choices = FormDefinition.ROLE_CHOICES

    if request.method == 'POST':
        for field in fields:
            prefix = f'field_{field.pk}'
            field.field_type = request.POST.get(f'{prefix}_type', field.field_type)
            order_value = request.POST.get(f'{prefix}_order')
            try:
                field.order = int(order_value)
            except (TypeError, ValueError):
                pass
            for attr in ('visible', 'required', 'readonly'):
                selected = request.POST.getlist(f'{prefix}_{attr}')
                setattr(field, f'{attr}_roles', ','.join(selected))
            field.is_active = request.POST.get(f'{prefix}_active') == 'on'

        FormField.objects.bulk_update(
            fields,
            ['field_type', 'order', 'visible_roles', 'required_roles', 'readonly_roles', 'is_active'],
        )
        messages.success(request, 'Form configuration updated.')
        return redirect('superadmin:form_management_edit', slug=form_obj.slug)

    context = {
        'form_obj': form_obj,
        'fields': fields,
        'role_choices': role_choices,
        'per_page': 20,
    }
    return render(request, 'form_management/detail.html', context)


@login_required
@superadmin_required
@require_POST
def toggle_form_status(request, slug):
    form_obj = get_object_or_404(FormDefinition, slug=slug)
    target_state = request.POST.get('state')
    if target_state == 'active':
        form_obj.is_active = True
    elif target_state == 'inactive':
        form_obj.is_active = False
    else:
        form_obj.is_active = not form_obj.is_active
    form_obj.save(update_fields=['is_active'])
    state = 'activated' if form_obj.is_active else 'marked inactive'
    messages.success(request, f'{form_obj.name} {state}.')
    return redirect('superadmin:form_management')
