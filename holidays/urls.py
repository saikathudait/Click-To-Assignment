from django.urls import path

from . import views

app_name = 'holidays'

urlpatterns = [
    path('', views.holiday_list_view, name='list'),
    path('<int:pk>/edit/', views.edit_holiday, name='edit'),
    path('<int:pk>/delete/', views.delete_holiday, name='delete'),
    path('<int:pk>/toggle/', views.toggle_holiday_status, name='toggle'),
]
