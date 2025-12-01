from django.urls import path
from . import views

app_name = 'profiles'

urlpatterns = [
    path('', views.profile_view, name='profile'),
    path('update-request/', views.request_profile_update, name='update_request'),
    path('change-password/', views.change_password_view, name='change_password'),
    path('superadmin-update/', views.superadmin_profile_update, name='superadmin_profile_update'),
]