# profiles/admin.py
from django.contrib import admin
from .models import Profile, ProfileUpdateRequest


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'total_jobs_completed', 'total_earnings', 'created_at']
    search_fields = ['user__email', 'user__first_name', 'user__last_name']
    readonly_fields = ['created_at', 'updated_at']

    fieldsets = (
        ('User', {
            'fields': ('user',)
        }),
        ('Personal Information', {
            'fields': ('bio', 'date_of_birth', 'address')
        }),
        ('Social Links', {
            'fields': ('linkedin_url', 'github_url')
        }),
        ('Statistics', {
            'fields': ('total_jobs_completed', 'total_earnings')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )


@admin.register(ProfileUpdateRequest)
class ProfileUpdateRequestAdmin(admin.ModelAdmin):
    list_display = [
        'user',
        'request_type',
        'status',
        'created_at',
        'processed_by',
        'processed_at',
    ]
    list_filter = ['status', 'request_type', 'created_at']
    search_fields = ['user__email', 'user__first_name', 'user__last_name']

    readonly_fields = [
        'user',
        'request_type',
        'current_value',
        'updated_value',
        'new_profile_picture',
        'status',
        'created_at',
        'processed_by',
        'processed_at',
    ]

    fieldsets = (
        ('Request Information', {
            'fields': ('user', 'request_type', 'status')
        }),
        ('Values', {
            'fields': ('current_value', 'updated_value', 'new_profile_picture')
        }),
        ('Processing', {
            'fields': ('processed_by', 'processed_at', 'notes')
        }),
        ('Timestamps', {
            'fields': ('created_at',)
        }),
    )

