from django.contrib import admin
from .models import (
    JobSummary, JobStructure, GeneratedContent,
    References, FullContent, PlagiarismReport, AIReport
)


@admin.register(JobSummary)
class JobSummaryAdmin(admin.ModelAdmin):
    list_display = ['job', 'topic', 'word_count', 'is_approved', 'regeneration_count', 'generated_at']
    list_filter = ['is_approved', 'generated_at', 'created_at']
    search_fields = ['job__job_id', 'topic']
    # removed generation_count
    readonly_fields = ['created_at', 'updated_at', 'approved_at']


@admin.register(JobStructure)
class JobStructureAdmin(admin.ModelAdmin):
    list_display = ['job', 'total_word_count', 'is_approved', 'regeneration_count', 'generated_at']
    list_filter = ['is_approved', 'generated_at', 'created_at']
    search_fields = ['job__job_id']
    readonly_fields = ['created_at', 'updated_at', 'approved_at']


@admin.register(GeneratedContent)
class GeneratedContentAdmin(admin.ModelAdmin):
    list_display = ['job', 'is_approved', 'regeneration_count', 'generated_at']
    list_filter = ['is_approved', 'generated_at', 'created_at']
    search_fields = ['job__job_id']
    readonly_fields = ['created_at', 'updated_at', 'approved_at']


@admin.register(References)
class ReferencesAdmin(admin.ModelAdmin):
    list_display = ['job', 'is_approved', 'regeneration_count', 'generated_at']
    list_filter = ['is_approved', 'generated_at', 'created_at']
    search_fields = ['job__job_id']
    readonly_fields = ['created_at', 'updated_at', 'approved_at']


@admin.register(FullContent)
class FullContentAdmin(admin.ModelAdmin):
    list_display = ['job', 'is_approved', 'regeneration_count', 'generated_at']
    list_filter = ['is_approved', 'generated_at', 'created_at']
    search_fields = ['job__job_id']
    readonly_fields = ['created_at', 'updated_at', 'approved_at']


@admin.register(PlagiarismReport)
class PlagiarismReportAdmin(admin.ModelAdmin):
    list_display = ['job', 'similarity_percentage', 'is_approved', 'generated_at']
    list_filter = ['is_approved', 'generated_at', 'created_at']
    search_fields = ['job__job_id']
    readonly_fields = ['created_at', 'updated_at', 'approved_at']


@admin.register(AIReport)
class AIReportAdmin(admin.ModelAdmin):
    list_display = ['job', 'ai_percentage', 'is_approved', 'generated_at']
    list_filter = ['is_approved', 'generated_at', 'created_at']
    search_fields = ['job__job_id']
    readonly_fields = ['created_at', 'updated_at', 'approved_at']


