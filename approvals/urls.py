from django.urls import path
from . import views

app_name = 'approvals'

urlpatterns = [
    # User Approval
    path('users/', views.user_approval_list, name='user_approval_list'),
    path('users/<int:user_id>/', views.user_detail, name='user_detail'),
    path('users/<int:user_id>/reset-password/', views.user_reset_password, name='user_reset_password'),
    path('users/create/', views.create_employee, name='create_employee'),
    path('users/<int:user_id>/approve/', views.approve_user, name='approve_user'),
    path('users/<int:user_id>/reject/', views.reject_user, name='reject_user'),
    
    # Profile Update Approval
    path('profile-updates/', views.profile_update_approval_list, name='profile_update_list'),
    path('profile-updates/<int:request_id>/approve/', views.approve_profile_update, name='approve_profile_update'),
    path('profile-updates/<int:request_id>/reject/', views.reject_profile_update, name='reject_profile_update'),
]
