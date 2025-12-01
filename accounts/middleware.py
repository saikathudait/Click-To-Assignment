from django.utils.deprecation import MiddlewareMixin
from allauth.socialaccount.models import SocialAccount
from accounts.models import User


class CleanOrphanSocialAccountsMiddleware(MiddlewareMixin):
    """
    Remove SocialAccount rows whose user record no longer exists.
    This prevents allauth lookup errors (DoesNotExist) when a social account
    points to a deleted or missing user.
    """

    def process_request(self, request):
        try:
            orphan_ids = []
            for sa in SocialAccount.objects.all().only('id', 'user_id'):
                if not User.objects.filter(id=sa.user_id).exists():
                    orphan_ids.append(sa.id)
            if orphan_ids:
                SocialAccount.objects.filter(id__in=orphan_ids).delete()
        except Exception:
            # Avoid blocking requests if cleanup fails
            pass
        return None
