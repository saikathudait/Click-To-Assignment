from django.apps import AppConfig
from django.db.models.signals import post_migrate
from django.contrib.auth.management import create_permissions
from django.conf import settings


class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'accounts'

    def ready(self):
        """
        Workaround for djongo SQLDecodeError:
        Disable Django's automatic permission creation, which uses SQL
        that djongo can't translate properly.
        """
        try:
            post_migrate.disconnect(
                create_permissions,
                dispatch_uid="django.contrib.auth.management.create_permissions",
            )
        except Exception:
            # If it's already disconnected or not connected, just ignore
            pass

        # Auto-create Google SocialApp if env vars are present
        try:
            from allauth.socialaccount.models import SocialApp
            from django.contrib.sites.models import Site

            providers = getattr(settings, 'SOCIALACCOUNT_PROVIDERS', {})
            google_app = providers.get('google', {}).get('APP', {})
            client_id = google_app.get('client_id')
            secret = google_app.get('secret')
            if client_id and secret:
                site, _ = Site.objects.get_or_create(
                    id=getattr(settings, 'SITE_ID', 1),
                    defaults={'domain': 'localhost', 'name': 'localhost'}
                )
                app, created = SocialApp.objects.get_or_create(provider='google', defaults={
                    'name': 'Google',
                    'client_id': client_id,
                    'secret': secret,
                })
                # Update in case env vars change
                updated = False
                if app.client_id != client_id:
                    app.client_id = client_id
                    updated = True
                if app.secret != secret:
                    app.secret = secret
                    updated = True
                if updated:
                    app.save(update_fields=['client_id', 'secret'])
                if site not in app.sites.all():
                    app.sites.add(site)
        except Exception:
            # Avoid startup crashes if migrations not applied yet
            pass

