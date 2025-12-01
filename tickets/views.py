# tickets/views.py
from django.views.generic import CreateView, ListView, DetailView, UpdateView
from django.urls import reverse_lazy
from django.shortcuts import get_object_or_404
from .models import Ticket
from .forms import MarketingTicketForm, SuperAdminTicketForm
from tickets.mixins import MarketingRequiredMixin, SuperAdminRequiredMixin
from notifications.utils import notify_ticket_created

class MarketingTicketCreateView(MarketingRequiredMixin, CreateView):
    model = Ticket
    form_class = MarketingTicketForm
    template_name = 'tickets/marketing_ticket_create.html'
    success_url = reverse_lazy('tickets:marketing-ticket-list')

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        # status stays 'NEW' by default
        response = super().form_valid(form)
        try:
            notify_ticket_created(self.object)
        except Exception:
            pass
        return response


class MarketingTicketListView(MarketingRequiredMixin, ListView):
    model = Ticket
    template_name = 'tickets/marketing_ticket_list.html'
    context_object_name = 'tickets'
    paginate_by = 20

    def get_queryset(self):
        # Only tickets created by that marketing user
        return Ticket.objects.filter(created_by=self.request.user).order_by('-created_at')




class SuperAdminTicketListView(SuperAdminRequiredMixin, ListView):
    model = Ticket
    template_name = 'tickets/superadmin_ticket_list.html'
    context_object_name = 'tickets'
    paginate_by = 20

    def get_queryset(self):
        qs = Ticket.objects.all().order_by('-created_at')
        status = self.request.GET.get('status')
        if status:
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET.copy()
        params.pop('page', None)
        query = params.urlencode()
        context['pagination_base'] = f'?{query}&' if query else '?'
        return context


class SuperAdminTicketUpdateView(SuperAdminRequiredMixin, UpdateView):
    model = Ticket
    form_class = SuperAdminTicketForm
    template_name = 'tickets/superadmin_ticket_update.html'
    success_url = reverse_lazy('tickets:superadmin-ticket-list')



from tickets.models import Ticket

def superadmin_counts(request):
    pending_jobs = ...  # your existing logic
    pending_users = ...
    pending_profile_updates = ...

    pending_tickets = Ticket.objects.filter(
        status__in=['NEW', 'UNDER_REVIEW', 'REWORK']
    ).count()

    return {
        'pending_jobs': pending_jobs,
        'pending_users': pending_users,
        'pending_profile_updates': pending_profile_updates,
        'pending_tickets': pending_tickets,
    }


