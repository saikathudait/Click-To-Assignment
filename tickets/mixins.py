# common/mixins.py
from django.contrib.auth.mixins import UserPassesTestMixin

class SuperAdminRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        user = self.request.user
        return user.is_authenticated and user.role == 'SUPERADMIN'


class MarketingRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        user = self.request.user
        return user.is_authenticated and user.role == 'MARKETING'
