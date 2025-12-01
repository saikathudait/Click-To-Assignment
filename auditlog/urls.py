from django.urls import path

from . import views

app_name = 'auditlog'

urlpatterns = [
    path('track-visit/', views.track_page_visit, name='track_visit'),
]
