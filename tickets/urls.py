# F:\...\tickets\urls.py
from django.urls import path
from .views import (
    MarketingTicketCreateView,
    MarketingTicketListView,
    SuperAdminTicketListView,
    SuperAdminTicketUpdateView,
)

app_name = "tickets"  

urlpatterns = [
    # Marketing
    path('marketing/tickets/', MarketingTicketListView.as_view(), name='marketing-ticket-list'),
    path('marketing/tickets/create/', MarketingTicketCreateView.as_view(), name='marketing-ticket-create'),

    # SuperAdmin
    path('superadmin/tickets/', SuperAdminTicketListView.as_view(), name='superadmin-ticket-list'),
    path('superadmin/tickets/<int:pk>/edit/', SuperAdminTicketUpdateView.as_view(), name='superadmin-ticket-update'),
]
