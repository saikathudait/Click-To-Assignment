from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import redirect, render

from auditlog.utils import log_action
from permissions.models import Permission, RolePermission
from permissions.utils import ensure_default_permissions
from superadmin.views import superadmin_required


def _get_role_toggle_name(perm_id, role):
    return f'perm_{perm_id}_{role}'


@login_required
@superadmin_required
def permission_management_view(request):
    ensure_default_permissions()
    filter_type = request.GET.get('filter', '').lower()

    permissions_qs = list(Permission.objects.prefetch_related('role_permissions').all())
    role_choices = list(RolePermission.ROLE_CHOICES)
    role_map = {role: label for role, label in role_choices}
    role_order = [role for role, _ in role_choices]

    marketing_permissions = [rp for rp in RolePermission.objects.filter(role=RolePermission.ROLE_MARKETING)]
    marketing_active = sum(1 for rp in marketing_permissions if rp.is_allowed)
    marketing_inactive = sum(1 for rp in marketing_permissions if not rp.is_allowed)

    if request.method == 'POST':
        updated = 0
        for perm in permissions_qs:
            rp_map = {rp.role: rp for rp in perm.role_permissions.all()}
            for role in role_map.keys():
                rp = rp_map.get(role)
                if not rp:
                    continue
                if role == RolePermission.ROLE_SUPERADMIN:
                    if not rp.is_allowed:
                        rp.is_allowed = True
                        rp.save(update_fields=['is_allowed'])
                        updated += 1
                    continue

                field = _get_role_toggle_name(perm.id, role)
                is_on = field in request.POST
                if rp.is_allowed != is_on:
                    rp.is_allowed = is_on
                    rp.save(update_fields=['is_allowed'])
                    updated += 1
        if updated:
            log_action(
                request.user,
                'PERMISSION_UPDATE',
                None,
                f'Updated {updated} permission toggles.',
            )
            messages.success(request, f'Permissions updated ({updated} changes).')
        else:
            messages.info(request, 'No permission changes detected.')
        return redirect('superadmin:permission_management')

    per_page = 20
    page_number = request.GET.get('page')
    paginator = Paginator(permissions_qs, per_page)
    page_obj = paginator.get_page(page_number)

    permissions = []
    for perm in page_obj.object_list:
        role_permissions = {rp.role: rp.is_allowed for rp in perm.role_permissions.all()}
        if filter_type == 'marketing_active' and not role_permissions.get(RolePermission.ROLE_MARKETING):
            continue
        if filter_type == 'marketing_inactive' and role_permissions.get(RolePermission.ROLE_MARKETING):
            continue
        role_entries = [
            {
                'role': role,
                'label': role_map[role],
                'allowed': role_permissions.get(role, role == RolePermission.ROLE_SUPERADMIN),
            }
            for role in role_order
        ]
        permissions.append(
            {
                'perm': perm,
                'role_entries': role_entries,
            }
        )

    total_permissions = len(permissions_qs)
    filter_query = ''
    if filter_type:
        filter_query = f'filter={filter_type}'

    context = {
        'permissions': permissions,
        'role_choices': role_choices,
        'filter_type': filter_type,
        'total_permissions': total_permissions,
        'marketing_active': marketing_active,
        'marketing_inactive': marketing_inactive,
        'filter_query': filter_query,
        'page_obj': page_obj,
        'per_page': per_page,
    }
    return render(request, 'permissions/manage.html', context)
