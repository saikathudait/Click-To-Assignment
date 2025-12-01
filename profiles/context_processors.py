from django.conf import settings

def user_avatar(request):
    """
    Provide a common `profile_image_url` for all templates.
    Priority: customer profile image -> general profile picture -> fallback ''.
    """
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}

    url = ''
    user = request.user
    try:
        cust_profile = getattr(user, 'customer_profile', None)
        if cust_profile and getattr(cust_profile, 'profile_image', None):
            url = cust_profile.profile_image.url
    except Exception:
        url = ''

    if not url:
        try:
            prof = getattr(user, 'profile', None)
            if prof and getattr(prof, 'profile_picture', None):
                url = prof.profile_picture.url
        except Exception:
            url = ''

    return {'profile_image_url': url}
