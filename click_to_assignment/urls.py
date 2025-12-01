"""
URL configuration for click_to_assignment project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.shortcuts import redirect

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', lambda request: redirect('accounts:login')),
    path('accounts/', include('accounts.urls')),
    path('accounts/social/', include('allauth.urls')),
    path('jobs/', include('jobs.urls')),
    path('profiles/', include('profiles.urls', namespace='profiles')),
    path('approvals/', include('approvals.urls')),
    path('ai/', include('ai_pipeline.urls')),
    path('marketing/', include(('marketing.urls', 'marketing'), namespace='marketing')),
    path('customer/', include(('customer.urls', 'customer'), namespace='customer')),
    path('superadmin/', include(('superadmin.urls', 'superadmin'), namespace='superadmin')),
    path('tickets/', include(('tickets.urls'), namespace='tickets')),
    path('holidays/', include(('holidays.urls', 'holidays'), namespace='holidays')),
    path('notifications/', include(('notifications.urls', 'notifications'), namespace='notifications')),
    path('activity/', include(('auditlog.urls', 'auditlog'), namespace='auditlog')),

]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
else:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    
    
# Admin site customization
admin.site.site_header = "Click to Assignment Administration"
admin.site.site_title = "Click to Assignment Admin"
admin.site.index_title = "Welcome to Click to Assignment Administration"

