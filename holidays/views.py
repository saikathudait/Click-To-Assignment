from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from holidays.forms import HolidayForm
from holidays.models import Holiday
from notifications.utils import notify_holiday_created

from superadmin.views import superadmin_required


def _get_upcoming_holidays():
    today = timezone.localdate()
    return Holiday.objects.filter(end_date__gte=today).order_by('start_date')


@login_required
def holiday_list_view(request):
    if getattr(request.user, 'role', '').upper() == 'CUSTOMER':
        return HttpResponseForbidden('Not authorized')

    holidays_qs = _get_upcoming_holidays()

    if request.user.role == 'SUPERADMIN':
        form = HolidayForm(request.POST or None)
        if request.method == 'POST' and form.is_valid():
            holiday = form.save(commit=False)
            holiday.created_by = request.user
            holiday.save()
            try:
                notify_holiday_created(holiday)
            except Exception:
                pass
            messages.success(request, 'Holiday added successfully!')
            return redirect('holidays:list')
    else:
        form = None

    per_page = 20
    holidays = holidays_qs
    paginator = Paginator(holidays, per_page)
    page_obj = paginator.get_page(request.GET.get('page'))

    holiday_ranges = [
        {
            'start': h.start_date.isoformat(),
            'end': h.end_date.isoformat(),
        }
        for h in holidays_qs
        if getattr(h, 'is_active', True)
    ]

    context = {
        'form': form,
        'holidays': page_obj.object_list,
        'editing_holiday': None,
        'page_obj': page_obj,
        'per_page': per_page,
        'calendar_holidays': holiday_ranges,
    }
    return render(request, 'holidays/manage.html', context)


@login_required
@superadmin_required
def edit_holiday(request, pk):
    holiday = get_object_or_404(Holiday, pk=pk)
    holidays = _get_upcoming_holidays()

    if request.method == 'POST':
        form = HolidayForm(request.POST, instance=holiday)
        if form.is_valid():
            form.save()
            messages.success(request, 'Holiday updated successfully.')
            return redirect('holidays:list')
    else:
        form = HolidayForm(instance=holiday)

    holiday_ranges = [
        {
            'start': h.start_date.isoformat(),
            'end': h.end_date.isoformat(),
        }
        for h in holidays
        if getattr(h, 'is_active', True)
    ]

    context = {
        'form': form,
        'holidays': holidays,
        'editing_holiday': holiday,
        'calendar_holidays': holiday_ranges,
    }
    return render(request, 'holidays/manage.html', context)


@login_required
@superadmin_required
@require_POST
def delete_holiday(request, pk):
    holiday = get_object_or_404(Holiday, pk=pk)
    holiday.delete()
    messages.success(request, 'Holiday deleted successfully.')
    return redirect('holidays:list')


@login_required
@superadmin_required
@require_POST
def toggle_holiday_status(request, pk):
    holiday = get_object_or_404(Holiday, pk=pk)
    holiday.is_active = not holiday.is_active
    holiday.save(update_fields=['is_active'])
    state = 'activated' if holiday.is_active else 'marked as inactive'
    messages.success(request, f'Holiday {state}.')
    return redirect('holidays:list')
