from bson import ObjectId
from django.db import models


def _generate_id():
    return str(ObjectId())


class Permission(models.Model):
    id = models.CharField(primary_key=True, max_length=24, default=_generate_id, editable=False)
    code = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ['code']

    def __str__(self):
        return f'{self.code}'


class RolePermission(models.Model):
    id = models.CharField(primary_key=True, max_length=24, default=_generate_id, editable=False)
    ROLE_MARKETING = 'MARKETING'
    ROLE_SUPERADMIN = 'SUPERADMIN'
    ROLE_CHOICES = [
        (ROLE_MARKETING, 'Marketing'),
        (ROLE_SUPERADMIN, 'Super Admin'),
    ]

    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE, related_name='role_permissions')
    is_allowed = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('role', 'permission')
        ordering = ['permission__code', 'role']

    def __str__(self):
        return f'{self.role}:{self.permission.code}'
