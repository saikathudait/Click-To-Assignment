from django.contrib import admin
from .models import Job, Attachment, JobMetrics


class AttachmentInline(admin.TabularInline):
    model = Attachment
    extra = 0
    readonly_fields = ['file_size', 'file_type', 'uploaded_at']  # removed original_filename
    can_delete = False


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = [
        'sl_no', 'job_id', 'system_id', 'created_by', 'amount',
        'status', 'is_approved', 'expected_deadline', 'strict_deadline', 'created_at'
    ]
    list_filter = ['status', 'is_approved', 'created_at', 'expected_deadline']
    search_fields = ['job_id', 'system_id', 'instruction']
    readonly_fields = ['system_id', 'sl_no', 'created_at', 'updated_at', 'approved_at']
    inlines = [AttachmentInline]

    fieldsets = (
        ('Job Information', {
            'fields': ('job_id', 'system_id', 'sl_no', 'instruction')
        }),
        ('Financial', {
            'fields': ('amount',)
        }),
        ('Deadlines', {
            'fields': ('expected_deadline', 'strict_deadline')
        }),
        ('Status', {
            'fields': ('status', 'is_approved', 'approved_by', 'approved_at')
        }),
        ('Tracking', {
            'fields': ('created_by', 'created_at', 'updated_at')
        }),
    )

    def get_readonly_fields(self, request, obj=None):
        if obj:  # Editing an existing object
            return self.readonly_fields + ['job_id', 'created_by']
        return self.readonly_fields


@admin.register(Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    list_display = ['job', 'file', 'file_type', 'file_size', 'uploaded_at']  # removed original_filename
    list_filter = ['file_type', 'uploaded_at']
    search_fields = ['job__job_id']  # removed original_filename
    readonly_fields = ['uploaded_at']


@admin.register(JobMetrics)
class JobMetricsAdmin(admin.ModelAdmin):
    list_display = [
        'date', 'total_jobs', 'pending_jobs', 'approved_jobs',
        'completed_jobs', 'total_amount', 'updated_at'
    ]
    list_filter = ['date']
    readonly_fields = ['updated_at']
    ordering = ['-date']
