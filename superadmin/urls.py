# superadmin/urls.py
from django.urls import path

from form_management import views as form_views
from permissions import views as permission_views

from . import views

app_name = 'superadmin'

urlpatterns = [
    # Dashboard / welcome
    path('', views.dashboard_view, name='dashboard'),
    path('welcome/', views.welcome_view, name='welcome'),
    path('statistics/', views.statistics_view, name='statistics'),
    path('users/', views.user_management, name='user_management'),
    path('users/<int:pk>/toggle-status/', views.user_toggle_status, name='user_toggle_status'),
    path('users/<int:pk>/toggle-role/', views.user_toggle_role, name='user_toggle_role'),
    path('users/<int:pk>/delete/', views.user_soft_delete, name='user_soft_delete'),
    path('forms/', form_views.form_list_view, name='form_management'),
    path('forms/<slug:slug>/', form_views.form_detail_view, name='form_management_edit'),
    path('forms/<slug:slug>/toggle/', form_views.toggle_form_status, name='form_management_toggle'),
    path('permissions/', permission_views.permission_management_view, name='permission_management'),
    path('notices/', views.announcement_list_view, name='announcement_list'),
    path('notices/<int:pk>/edit/', views.announcement_edit_view, name='announcement_edit'),
    path('notices/<int:pk>/toggle/', views.announcement_toggle_view, name='announcement_toggle'),
    path('notices/<int:pk>/delete/', views.announcement_delete_view, name='announcement_delete'),
    path('notices/<int:pk>/dismiss/', views.announcement_dismiss_view, name='announcement_dismiss'),
    path('backup/', views.backup_center_view, name='backup_center'),
    path('settings/', views.settings_view, name='settings'),
    path('content-management/', views.content_management_view, name='content_management'),
    path('activity-tracking/', views.activity_tracking_view, name='activity_tracking'),
    path('activity-analytics/', views.activity_analytics_view, name='activity_analytics'),
    path('error-management/', views.error_management_view, name='error_management'),
    path('menu-management/', views.menu_management_view, name='menu_management'),
    path('reworks/', views.rework_list_view, name='rework_list'),
    path('reworks/<int:pk>/', views.rework_detail_view, name='rework_detail'),
    path('reworks/<int:pk>/api/summary/generate/', views.api_generate_rework_summary, name='rework_generate_summary'),
    path('reworks/<int:pk>/api/rework/generate/', views.api_generate_rework_content, name='rework_generate_rework'),
    path('reworks/<int:pk>/api/summary/approve/', views.api_approve_rework_summary, name='rework_approve_summary'),
    path('reworks/<int:pk>/api/rework/approve/', views.api_approve_rework_content, name='rework_approve_rework'),

    # Jobs
    path('all-jobs/', views.all_jobs_view, name='all_jobs'),
    path('new-jobs/', views.new_jobs_view, name='new_jobs'),

    # Job detail uses external job_id string (e.g. "2000")
    path('job/<str:job_id>/', views.job_detail, name='job_detail'),

    # Approve a single job (approve_job uses Job.pk: id=job_id)
    path('job/<int:job_id>/approve/', views.approve_job, name='approve_job'),

    # Approve all AI content for a job (approve_all_job_content uses job_id=job_id)
    path(
        'job/<str:job_id>/approve-all-content/',
        views.approve_all_job_content,
        name='approve_all_job_content',
    ),

    # User approvals page (redirects to approvals app)
    path('user-approval/', views.user_approvals, name='user_approval'),

    # Profile update requests page (redirects to approvals app)
    path(
        'profile-update-requests/',
        views.profile_update_requests,
        name='profile_update_requests',
    ),

    # SuperAdmin profile (the editable profile_view)
    path('profile/', views.profile_view, name='profile'),
    # Customer management (SuperAdmin)
    path('customers/', views.customer_management, name='customer_management'),
    path('customers/accounts/', views.customer_accounts, name='customer_accounts'),
    path('customers/wallets/', views.customer_wallets, name='customer_wallets'),
    path('customers/pricing/', views.customer_pricing, name='customer_pricing'),
    path('customers/ai-config/', views.customer_ai_config, name='customer_ai_config'),
    path('customers/ai-logs/', views.customer_ai_logs, name='customer_ai_logs'),
    path('customers/job-checks/', views.customer_job_checks, name='customer_job_checks'),
    path('customers/job-checks/<str:submission_id>/', views.customer_job_check_detail, name='customer_job_check_detail'),
    path('customers/structures/', views.customer_structures, name='customer_structures'),
    path('customers/structures/<str:submission_id>/', views.customer_structure_detail, name='customer_structure_detail'),
    path('customers/contents/', views.customer_contents, name='customer_contents'),
    path('customers/tickets/', views.customer_tickets, name='customer_tickets'),
    path('customers/tickets/<str:ticket_id>/', views.customer_ticket_detail, name='customer_ticket_detail'),
    path('customers/meetings/', views.customer_meetings, name='customer_meetings'),
    path('customers/bookings/', views.customer_bookings, name='customer_bookings'),
    path('customers/analytics/', views.customer_analytics, name='customer_analytics'),
    path('customers/contents/<str:submission_id>/', views.customer_content_detail, name='customer_content_detail'),

    # Google Login management (Super Admin only)
    path('google-login/', views.google_login_settings_view, name='google_login_settings'),
    path('google-login/unlink/<int:account_id>/', views.google_login_unlink_view, name='google_login_unlink'),
]
