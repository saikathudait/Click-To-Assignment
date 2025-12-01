import logging
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import User
from customer.models import CustomerProfile


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Remove customer profiles with non-integer PKs and rebuild clean numeric profiles."

    def handle(self, *args, **options):
        fixed = 0
        removed = 0
        kept = 0
        users_processed = 0

        customers = User.objects.filter(role__iexact='CUSTOMER')
        for user in customers:
            users_processed += 1
            profiles = list(CustomerProfile.objects.filter(user=user))
            int_profiles = [p for p in profiles if isinstance(p.pk, int) and not isinstance(p.pk, bool)]
            bad_profiles = [p for p in profiles if p.pk is None or not isinstance(p.pk, int) or isinstance(p.pk, bool)]

            # Keep the newest valid profile and drop duplicates
            if int_profiles:
                int_profiles = sorted(
                    int_profiles,
                    key=lambda p: getattr(p, 'updated_at', p.joined_date),
                    reverse=True,
                )
                keeper = int_profiles[0]
                for extra in int_profiles[1:]:
                    extra.delete()
                    removed += 1
                for bad in bad_profiles:
                    bad.delete()
                    removed += 1
                kept += 1
                continue

            # No valid int profile exists; remove bad ones and rebuild
            for bad in bad_profiles:
                bad.delete()
                removed += 1

            profile = CustomerProfile(
                id=int(timezone.now().timestamp() * 1_000_000),
                user=user,
                full_name=user.get_full_name(),
                phone=getattr(user, 'whatsapp_no', '') or '',
                joined_date=getattr(user, 'date_joined', timezone.now()),
                customer_id=getattr(user, 'customer_code', None) or None,
            )
            if not profile.customer_id:
                profile.customer_id = profile.generate_customer_id()
            profile.save(force_insert=True)
            fixed += 1

        msg = (
            f"Processed customers: {users_processed}; "
            f"kept valid profiles: {kept}; "
            f"rebuilt profiles: {fixed}; "
            f"removed invalid/duplicate profiles: {removed}"
        )
        self.stdout.write(self.style.SUCCESS(msg))
        logger.info(msg)
