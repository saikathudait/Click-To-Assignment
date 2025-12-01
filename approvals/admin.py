from django.contrib import admin
from .models import UserApprovalLog, ApprovalStatistics


@admin.register(UserApprovalLog)
class UserApprovalLogAdmin(admin.ModelAdmin):
    list_display = ['user', 'action', 'approved_by', 'timestamp']
    list_filter = ['action', 'timestamp']
    search_fields = ['user__email', 'user__first_name', 'user__last_name']
    readonly_fields = ['user', 'action', 'approved_by', 'timestamp']
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False


@admin.register(ApprovalStatistics)
class ApprovalStatisticsAdmin(admin.ModelAdmin):
    list_display = ['date', 'pending_users', 'approved_users', 'rejected_users', 
                   'pending_profile_requests', 'approved_profile_requests', 'updated_at']
    list_filter = ['date']
    readonly_fields = ['updated_at']
    ordering = ['-date']