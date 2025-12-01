from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.models import SocialAccount
from allauth.exceptions import ImmediateHttpResponse
from django.shortcuts import redirect
from django.contrib import messages
from django.contrib.auth import get_user_model
from superadmin.models import GoogleAuthConfig, GoogleLoginLog

User = get_user_model()


class CustomerSocialAccountAdapter(DefaultSocialAccountAdapter):
    """Force social signups to be active/approved customers."""

    def _log(self, user, email, status, reason, request):
        try:
            GoogleLoginLog.objects.create(
                user=user if user and user.pk else None,
                email=email or '',
                status=status,
                reason=reason or '',
                ip_address=request.META.get('REMOTE_ADDR', ''),
            )
        except Exception:
            pass

    def pre_social_login(self, request, sociallogin):
        """
        If a user with the same email already exists, link the social account to it
        instead of trying to create a duplicate.
        """
        config = GoogleAuthConfig.get_solo()
        email = (sociallogin.user.email or '').strip().lower()

        # Config checks
        if not config.enabled:
            self._log(None, email, GoogleLoginLog.STATUS_FAILURE, 'Google login disabled', request)
            raise ImmediateHttpResponse(redirect('accounts:login'))

        provider = getattr(sociallogin.account, 'provider', None)
        uid = getattr(sociallogin.account, 'uid', None)

        def deny(reason):
            self._log(None, email, GoogleLoginLog.STATUS_FAILURE, reason, request)
            messages.error(request, reason)
            raise ImmediateHttpResponse(redirect('accounts:login'))

        # Domain rule
        if email and not config.domain_allowed(email):
            deny('This email domain is not allowed for Google login.')
        # Role allow rule (we always assign CUSTOMER)
        if not config.is_role_allowed('CUSTOMER'):
            deny('Google login for Customers is disabled by admin.')

        provider = getattr(sociallogin.account, 'provider', None)
        uid = getattr(sociallogin.account, 'uid', None)

        # Clean up or reconnect orphaned social accounts (uid exists but user missing)
        if provider and uid:
            try:
                existing_account = SocialAccount.objects.filter(provider=provider, uid=uid).select_related('user').first()
            except Exception:
                existing_account = None
            if existing_account:
                if not existing_account.user_id:
                    # Orphaned social account; remove it so we can recreate
                    existing_account.delete()
                else:
                    try:
                        linked_user = existing_account.user
                    except User.DoesNotExist:
                        existing_account.delete()
                    else:
                        # Ensure flags/ids and connect
                        linked_user.role = 'CUSTOMER'
                        linked_user.is_active = True
                        linked_user.is_approved = True
                        if not getattr(linked_user, 'employee_id', None):
                            try:
                                linked_user.generate_employee_id()
                            except Exception:
                                pass
                        if getattr(linked_user, 'role', '').upper() == 'CUSTOMER' and not getattr(linked_user, 'customer_code', None):
                            try:
                                linked_user.generate_customer_code()
                            except Exception:
                                pass
                        linked_user.save()
                        sociallogin.user = linked_user
                        sociallogin.account.user = linked_user
                        return

        if sociallogin.is_existing:
            # Ensure role flags on existing user
            user = sociallogin.user
            user.role = 'CUSTOMER'
            user.is_active = True
            user.is_approved = True
            if not getattr(user, 'employee_id', None):
                try:
                    user.generate_employee_id()
                except Exception:
                    pass
            if getattr(user, 'role', '').upper() == 'CUSTOMER' and not getattr(user, 'customer_code', None):
                try:
                    user.generate_customer_code()
                except Exception:
                    pass
            user.save()
            return
        email = (sociallogin.user.email or '').strip().lower()
        if not email:
            return
        try:
            existing_user = User.objects.filter(email__iexact=email).first()
        except Exception:
            existing_user = None
        if existing_user:
            # Ensure baseline flags and IDs
            existing_user.role = 'CUSTOMER'
            existing_user.is_active = True
            existing_user.is_approved = True
            if not getattr(existing_user, 'employee_id', None):
                try:
                    existing_user.generate_employee_id()
                except Exception:
                    pass
            if getattr(existing_user, 'role', '').upper() == 'CUSTOMER' and not getattr(existing_user, 'customer_code', None):
                try:
                    existing_user.generate_customer_code()
                except Exception:
                    pass
            existing_user.save()
            sociallogin.connect(request, existing_user)
            sociallogin.user = existing_user
            return
        else:
            # New signup
            if not config.allow_signup or config.mode == GoogleAuthConfig.MODE_LOGIN_ONLY:
                deny('Google signup is disabled. Please use normal signup or contact admin.')

    def save_user(self, request, sociallogin, form=None):
        user = super().save_user(request, sociallogin, form)
        # Force customer role and approval
        user.role = 'CUSTOMER'
        user.is_approved = True
        user.is_active = True

        # Generate IDs if missing
        if not getattr(user, 'employee_id', None):
            try:
                user.generate_employee_id()
            except Exception:
                pass
        if getattr(user, 'role', '').upper() == 'CUSTOMER' and not getattr(user, 'customer_code', None):
            try:
                user.generate_customer_code()
            except Exception:
                pass

        # Persist changes
        user.save()
        # Log success
        self._log(user, user.email, GoogleLoginLog.STATUS_SUCCESS, '', request)
        return user
