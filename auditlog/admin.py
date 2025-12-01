from django.contrib import admin
from .models import ActionLog, JobActionLog


@admin.register(ActionLog)
class ActionLogAdmin(admin.ModelAdmin):
    list_display = ['user_name', 'user_email', 'action_type', 'target_model', 'timestamp']
    list_filter = ['action_type', 'timestamp', 'target_model']
    search_fields = ['user_email', 'user_name', 'description', 'target_id']
    readonly_fields = ['user', 'user_email', 'user_name', 'action_type', 'description', 
                      'target_model', 'target_id', 'ip_address', 'user_agent', 'timestamp']
    ordering = ['-timestamp']
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(JobActionLog)
class JobActionLogAdmin(admin.ModelAdmin):
    list_display = ['job_id', 'system_id', 'user_email', 'action', 'field_changed', 'timestamp']
    list_filter = ['action', 'timestamp']
    search_fields = ['job_id', 'system_id', 'user_email']
    readonly_fields = ['job_id', 'system_id', 'user', 'user_email', 'action', 
                      'field_changed', 'old_value', 'new_value', 'timestamp']
    ordering = ['-timestamp']
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser