from django.urls import path

from form_management import views

app_name = 'form_management'

urlpatterns = [
    path('', views.form_list_view, name='list'),
    path('<slug:slug>/', views.form_detail_view, name='detail'),
    path('<slug:slug>/toggle/', views.toggle_form_status, name='toggle'),
]
