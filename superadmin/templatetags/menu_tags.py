from django import template

from superadmin.models import MenuItem

register = template.Library()


@register.simple_tag
def role_menu(role):
    """
    Return ordered, active menu items for the given role.
    Welcome is always seeded and fixed at position 0 by defaults.
    """
    try:
        return MenuItem.ordered_for_role(role)
    except Exception:
        return []


@register.simple_tag
def user_menu(user):
    """Shortcut to fetch menu for the current user role."""
    role = getattr(user, "role", None)
    if not role:
        return []
    try:
        return MenuItem.ordered_for_role(role)
    except Exception:
        return []


@register.filter
def get_item(mapping, key):
    """Template helper to get dict item by key safely."""
    if not isinstance(mapping, dict):
        return None
    return mapping.get(key)
