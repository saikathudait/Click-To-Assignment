def user_role(request):
    """Add user role and color to template context"""
    context = {}
    if request.user.is_authenticated:
        context['user_role'] = request.user.role
        if request.user.role == 'superadmin':
            context['role_color'] = '#A4F4CF'
        else:
            context['role_color'] = '#CAD5E2'
    return context