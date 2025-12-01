from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect

from permissions.defaults import DEFAULT_PERMISSIONS, ROLE_DEFAULTS
from permissions.models import Permission, RolePermission


def ensure_default_permissions():
    for code, name, desc in DEFAULT_PERMISSIONS:
        permission, _ = Permission.objects.update_or_create(
            code=code,
            defaults={'name': name, 'description': desc},
        )
        for role, _ in RolePermission.ROLE_CHOICES:
            default_matrix = ROLE_DEFAULTS.get(role)
            if default_matrix == 'ALL':
                RolePermission.objects.update_or_create(
                    permission=permission,
                    role=role,
                    defaults={'is_allowed': True},
                )
            elif isinstance(default_matrix, set):
                should_allow = code in default_matrix
                RolePermission.objects.update_or_create(
                    permission=permission,
                    role=role,
                    defaults={'is_allowed': should_allow},
                )
            else:
                RolePermission.objects.get_or_create(
                    permission=permission,
                    role=role,
                )

    RolePermission.objects.filter(role=RolePermission.ROLE_SUPERADMIN).update(is_allowed=True)


def get_role_permissions(role):
    ensure_default_permissions()
    return {
        rp.permission.code: rp.is_allowed
        for rp in RolePermission.objects.filter(role=role).select_related('permission')
    }


def role_has_permission(role, code):
    ensure_default_permissions()
    try:
        rp = RolePermission.objects.select_related('permission').get(
            role=role, permission__code=code
        )
        return rp.is_allowed
    except RolePermission.DoesNotExist:
        return False


def permission_required(permission_code, redirect_url='marketing:dashboard'):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if request.user.role == RolePermission.ROLE_SUPERADMIN:
                return view_func(request, *args, **kwargs)
            if not role_has_permission(request.user.role, permission_code):
                messages.error(request, 'Access denied. Missing permission.')
                return redirect(redirect_url)
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator
