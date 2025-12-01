from django.urls import path
from . import views

app_name = 'marketing'

urlpatterns = [
    path('welcome/', views.welcome_view, name='welcome'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('statistics/', views.statistics_view, name='statistics'),
    path('all-projects/', views.all_projects_view, name='all_projects'),
    path('create-job/', views.create_job_view, name='create_job'),
    path('profile/', views.profile_view, name='profile'),
    path('jobs/<str:job_id>/run-pipeline/', views.run_pipeline, name='run_pipeline'),
    path('jobs/<str:job_id>/payment-slip/', views.upload_payment_slip, name='upload_payment_slip'),
    path('jobs/<str:job_id>/rework/', views.request_rework, name='request_rework'),
    path('jobs/<str:job_id>/reworks/', views.job_rework_history, name='job_rework_history'),
]
