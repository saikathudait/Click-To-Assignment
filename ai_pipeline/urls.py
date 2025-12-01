# ai_pipeline/urls.py
from django.urls import path
from . import views

app_name = 'ai_pipeline'

urlpatterns = [
    # STEP-BY-STEP GENERATION & APPROVAL (by Job PK: id)
    path('generate-summary/<int:job_id>/', views.generate_job_summary_view, name='generate_summary'),
    path('approve-summary/<int:job_id>/', views.approve_job_summary, name='approve_summary'),

    path('generate-structure/<int:job_id>/', views.generate_job_structure_view, name='generate_structure'),
    path('approve-structure/<int:job_id>/', views.approve_job_structure, name='approve_structure'),

    path('generate-content/<int:job_id>/', views.generate_content_view, name='generate_content'),
    path('approve-content/<int:job_id>/', views.approve_content, name='approve_content'),

    path('generate-references/<int:job_id>/', views.generate_references_view, name='generate_references'),
    path('approve-references/<int:job_id>/', views.approve_references, name='approve_references'),

    path('generate-full-content/<int:job_id>/', views.generate_full_content_view, name='generate_full_content'),
    path('approve-full-content/<int:job_id>/', views.approve_full_content, name='approve_full_content'),

    path('generate-plagiarism/<int:job_id>/', views.generate_plagiarism_report, name='generate_plagiarism'),
    path('generate-ai-report/<int:job_id>/', views.generate_ai_report, name='generate_ai_report'),

    # JSON / AJAX view (by Job PK: id)
    path('view-content/<int:job_id>/<str:content_type>/', views.view_generated_content, name='view_content'),

    # FULL-PAGE VIEW / REGENERATE / APPROVE (by external job_id string)
    # used by ai_pipeline/view_content.html and job_detail buttons
    path(
        'content/<str:job_id>/<str:content_type>/',
        views.ai_content_view,
        name='ai_content_view',
    ),
    path(
        'content/<str:job_id>/<str:content_type>/regenerate/',
        views.ai_content_regenerate,
        name='ai_content_regenerate',
    ),
    path(
        'content/<str:job_id>/<str:content_type>/approve/',
        views.ai_content_approve,
        name='ai_content_approve',
    ),

    # ONE-CLICK "GENERATE ALL" (by external job_id string)
    # this is what your template calls in new_jobs.html
    # {% url 'ai_pipeline:generate_all_content' item.job.job_id %}
    path(
        'generate-all/<str:job_id>/',
        views.generate_all_content,
        name='generate_all_content',
    ),

    # DOWNLOAD CONTENT (by external job_id string)
    path(
        'download/<str:job_id>/<str:content_type>/',
        views.download_content,
        name='download_content',
    ),
]
