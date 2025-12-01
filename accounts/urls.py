from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('signup/', views.signup_view, name='signup'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('post-login/', views.login_redirect_view, name='post_login'),
    path('dashboard/', views.dashboard_redirect, name='dashboard_redirect'),
    path('wait-approval/', views.wait_approval_view, name='wait_approval'),
]
