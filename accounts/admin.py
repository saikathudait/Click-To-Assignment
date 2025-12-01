# accounts/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, CountryCode


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ['email', 'employee_id', 'first_name', 'last_name', 'role', 'is_approved', 'is_active']
    list_filter = ['role', 'is_approved', 'is_active', 'date_joined']
    search_fields = ['email', 'first_name', 'last_name', 'employee_id']
    ordering = ['-date_joined']

    fieldsets = (
        (None, {
            'fields': ('email', 'password')
        }),
        ('Personal Info', {
            'fields': (
                'first_name',
                'last_name',
                'whatsapp_no',
                'whatsapp_country_code',
                'profile_picture',
                'last_qualification',
            )
        }),
        ('Permissions', {
            'fields': (
                'is_active',
                'is_staff',
                'is_superuser',
                'groups',
                'user_permissions',
            )
        }),
        ('Role & Status', {
            'fields': (
                'role',
                'employee_id',
                'is_approved',
                'approved_by',
                'approved_at',
            )
        }),
        ('Important Dates', {
            'fields': (
                'last_login',
                'date_joined',
            )
        }),
    )

    readonly_fields = ['employee_id', 'approved_at']

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': (
                'email',
                'first_name',
                'last_name',
                'password1',
                'password2',
                'role',
            ),
        }),
    )


@admin.register(CountryCode)
class CountryCodeAdmin(admin.ModelAdmin):
    list_display = ['country_name', 'country_code']
    search_fields = ['country_name', 'country_code']
    ordering = ['country_name']
