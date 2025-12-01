from permissions.utils import get_role_permissions


def role_permissions(request):
    if not request.user.is_authenticated:
        return {}
    try:
        perms = get_role_permissions(request.user.role)
    except Exception:
        perms = {}
    return {'role_permissions': perms}
