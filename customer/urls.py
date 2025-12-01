from django.urls import path
from . import views

app_name = 'customer'

urlpatterns = [
    path('', views.welcome_view, name='welcome'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('remove-ai/', views.remove_ai_view, name='remove_ai'),
    path('job-checking/', views.job_checking_view, name='job_checking'),
    path('job-checking/<str:submission_id>/', views.job_check_detail_view, name='job_check_detail'),
    path('structure-generate/', views.structure_generate_view, name='structure_generate'),
    path('structure-generate/<str:submission_id>/', views.structure_detail_view, name='structure_detail'),
    path('create-content/', views.create_content_view, name='create_content'),
    path('create-content/<str:submission_id>/', views.content_detail_view, name='content_detail'),
    path('coins/', views.coin_history_view, name='coin_history'),
    path('pricing/', views.pricing_plan_view, name='pricing'),
    path('tickets/submit/', views.submit_ticket_view, name='submit_ticket'),
    path('tickets/', views.my_tickets_view, name='my_tickets'),
    path('tickets/<str:ticket_id>/', views.ticket_detail_view, name='ticket_detail'),
    path('meetings/', views.meetings_view, name='meetings'),
    path('bookings/', views.bookings_view, name='bookings'),
    path('profile/', views.profile_view, name='profile'),
    path('profile/edit/', views.profile_edit_view, name='profile_edit'),
    path('profile/change-password/', views.password_change_view, name='password_change'),
]
