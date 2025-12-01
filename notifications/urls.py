from django.urls import path

from notifications import views

app_name = 'notifications'

urlpatterns = [
    path('list/', views.list_notifications, name='list'),
    path('read/<int:pk>/', views.mark_notification_read, name='mark_read'),
    path('read-all/', views.mark_all_notifications_read, name='mark_all'),
]
