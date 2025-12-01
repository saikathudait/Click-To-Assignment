from django.urls import path
from . import views

app_name = 'jobs'

urlpatterns = [
    path('create/', views.create_job_view, name='create_job'),
    path('detail/<int:job_id>/', views.job_detail_view, name='job_detail'),
    path('list/', views.job_list, name='job_list'),
    path('marketing/all-projects/', views.marketing_all_projects, name='marketing_all_projects'),
    path('<int:pk>/edit/', views.edit_job_view, name='edit_job'),
    path('<int:pk>/delete/', views.delete_job_view, name='delete_job'),
    path('<int:pk>/restore/', views.restore_job_view, name='restore_job'),
]
