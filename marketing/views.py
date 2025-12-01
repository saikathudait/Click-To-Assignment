from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Sum, Count
from django.urls import reverse
from django.utils import timezone
import json
from jobs.models import Job, JobReworkRequest
from ai_pipeline.utils import (
    MARKETING_GENERATION_LIMIT,
    get_regeneration_usage,
    run_marketing_pipeline,
    sync_job_status,
)
from jobs.forms import JobDropForm, JobReworkForm
from .utils import collect_marketing_filters, job_matches_marketing_filters
from notifications.utils import notify_superadmins_new_job
from notifications.utils import create_notification, notify_marketing_rework_completed
from auditlog.utils import log_action, log_job_action
from superadmin.models import ContentAccessSetting
from superadmin.models import SystemSettings
from superadmin.services import get_visible_announcements_for_user

def marketing_required(view_func):
    """Decorator to ensure only marketing team can access"""
    def wrapper(request, *args, **kwargs):
        if request.user.role != 'MARKETING':
            messages.error(request, 'Access denied. Marketing Team only.')
            return redirect('accounts:dashboard_redirect')
        return view_func(request, *args, **kwargs)
    return wrapper

@login_required
@marketing_required
def welcome_view(request):
    """Marketing welcome page"""
    context = {
        'user': request.user,
        'announcements': get_visible_announcements_for_user(request.user),
    }
    return render(request, 'marketing/welcome.html', context)

@login_required
@marketing_required
def dashboard_view(request):
    """Marketing dashboard with statistics"""
    # Get user's jobs statistics
    raw_filters, normalized_filters = collect_marketing_filters(request)

    user_jobs_qs = Job.objects.filter(created_by=request.user).prefetch_related('rework_requests')
    user_jobs = [job for job in user_jobs_qs if not job.is_deleted]

    for job in user_jobs:
        job.rework_count = len(list(job.rework_requests.all()))
        sync_job_status(job)
    filtered_jobs = [
        job for job in user_jobs
        if job_matches_marketing_filters(job, normalized_filters)
    ]
    
    total_jobs = len(filtered_jobs)
    pending_jobs = sum(1 for job in filtered_jobs if job.status == 'PENDING')
    # approved_jobs = user_jobs.filter(is_approved=True).count()
    total_amount = sum(job.amount or 0 for job in filtered_jobs)
    
    # Recent jobs
    per_page = 20
    sorted_jobs = sorted(filtered_jobs, key=lambda job: job.created_at, reverse=True)
    paginator = Paginator(sorted_jobs, per_page)
    page_obj = paginator.get_page(request.GET.get('recent_page'))
    recent_jobs = page_obj.object_list
    recent_params = request.GET.copy()
    recent_params.pop('recent_page', None)
    recent_query = recent_params.urlencode()
    
    context = {
        'total_jobs': total_jobs,
        'pending_jobs': pending_jobs,
        #'approved_jobs': approved_jobs,
        'total_amount': total_amount,
        'recent_jobs': recent_jobs,
        'status_choices': Job.STATUS_CHOICES,
        'filter_params': raw_filters,
        'recent_page_obj': page_obj,
        'recent_per_page': per_page,
        'recent_query': recent_query,
    }
    
    return render(request, 'marketing/dashboard.html', context)


@login_required
@marketing_required
def statistics_view(request):
    """Marketing-only statistics built from the requesting user's own jobs."""
    now = timezone.now()

    def _aware(dt):
        if not dt:
            return None
        return timezone.make_aware(dt) if timezone.is_naive(dt) else dt

    def _created_date(job):
        created_at = _aware(getattr(job, 'created_at', None))
        return timezone.localtime(created_at).date() if created_at else None

    user_jobs_qs = Job.objects.filter(created_by=request.user).prefetch_related('rework_requests')
    user_jobs = [job for job in user_jobs_qs if not job.is_deleted]
    for job in user_jobs:
        sync_job_status(job)

    status_counts = {choice[0]: 0 for choice in Job.STATUS_CHOICES}
    created_trend_map = {}
    pending_trend_map = {}
    closed_statuses = {
        'APPROVED',
        'COMPLETED',
        'FULL_CONTENT',
        'PLAGIARISM_REPORT',
        'AI_REPORT',
        'REWORK_COMPLETED',
    }
    pending_like = {'PENDING', 'JOB_SUMMARY', 'JOB_STRUCTURE', 'CONTENT', 'REFERENCES', 'IN_PROGRESS'}

    for job in user_jobs:
        status_key = (job.status or '').upper()
        status_counts[status_key] = status_counts.get(status_key, 0) + 1
        created_date = _created_date(job)
        if created_date:
            created_trend_map[created_date] = created_trend_map.get(created_date, 0) + 1
            if status_key in pending_like:
                pending_trend_map[created_date] = pending_trend_map.get(created_date, 0) + 1

    jobs_created_trend = [
        {'date': d.isoformat(), 'count': c}
        for d, c in sorted(created_trend_map.items())
    ]
    pending_trend = [
        {'date': d.isoformat(), 'count': c}
        for d, c in sorted(pending_trend_map.items())
    ]

    approvals = sum(
        1 for job in user_jobs
        if getattr(job, 'is_approved', False) or (job.status or '').upper() in closed_statuses
    )
    rejections = sum(1 for job in user_jobs if (job.status or '').upper() == 'REJECTED')

    reworks_qs = JobReworkRequest.objects.filter(job__created_by=request.user)
    rework_counts_by_job = {}
    for req in reworks_qs:
        rework_counts_by_job[req.job_id] = rework_counts_by_job.get(req.job_id, 0) + 1

    rework_buckets = {'0': 0, '1': 0, '2': 0, '3+': 0}
    for job in user_jobs:
        count = rework_counts_by_job.get(job.id, 0)
        if count == 0:
            rework_buckets['0'] += 1
        elif count == 1:
            rework_buckets['1'] += 1
        elif count == 2:
            rework_buckets['2'] += 1
        else:
            rework_buckets['3+'] += 1

    rework_trend_map = {}
    for req in reworks_qs:
        dt = _aware(req.created_at)
        if not dt:
            continue
        d = timezone.localtime(dt).date()
        rework_trend_map[d] = rework_trend_map.get(d, 0) + 1
    rework_trend = [
        {'date': d.isoformat(), 'count': c}
        for d, c in sorted(rework_trend_map.items())
    ] or [{'date': '', 'count': 0}]

    on_time = 0
    late = 0
    deadline_buckets = {'Due today': 0, '1-2 days': 0, '3-5 days': 0, '>5 days': 0, 'No deadline': 0}
    for job in user_jobs:
        deadline = _aware(job.strict_deadline)
        completed_at = _aware(job.approved_at or job.updated_at)
        status_key = (job.status or '').upper()
        if (status_key in closed_statuses or getattr(job, 'is_approved', False)) and deadline and completed_at:
            if completed_at <= deadline:
                on_time += 1
            else:
                late += 1

        if deadline:
            if status_key not in closed_statuses:
                delta_days = (deadline - now).total_seconds() / 86400
                if delta_days < 0:
                    bucket = 'Due today'
                elif delta_days <= 2:
                    bucket = '1-2 days'
                elif delta_days <= 5:
                    bucket = '3-5 days'
                else:
                    bucket = '>5 days'
                deadline_buckets[bucket] = deadline_buckets.get(bucket, 0) + 1
        else:
            deadline_buckets['No deadline'] += 1

    context = {
        'status_counts_json': json.dumps(status_counts),
        'created_trend_json': json.dumps(jobs_created_trend),
        'pending_trend_json': json.dumps(pending_trend),
        'approval_json': json.dumps({'approved': approvals, 'rejected': rejections}),
        'rework_trend_json': json.dumps(rework_trend),
        'rework_buckets_json': json.dumps(rework_buckets),
        'deadline_buckets_json': json.dumps(deadline_buckets),
        'on_time_late_json': json.dumps({'on_time': on_time, 'late': late}),
        'total_jobs': len(user_jobs),
        'pending_jobs': sum(1 for job in user_jobs if (job.status or '').upper() in pending_like),
        'rework_total': reworks_qs.count(),
        'overdue_jobs': sum(
            1 for job in user_jobs
            if job.strict_deadline and _aware(job.strict_deadline) < now and (job.status or '').upper() not in closed_statuses
        ),
    }
    return render(request, 'marketing/statistics.html', context)

@login_required
@marketing_required
def all_projects_view(request):
    """List all projects/jobs created by marketing user"""
    raw_filters, normalized_filters = collect_marketing_filters(request)
    filter_type = request.GET.get('filter', 'all')

    access_setting = ContentAccessSetting.for_user(request.user)
    allow_payment_slip = True
    if access_setting and access_setting.mode == ContentAccessSetting.MODE_APPROVAL_ONLY:
        allow_payment_slip = False

    def _safe_related(instance, attr_name):
        try:
            return getattr(instance, attr_name)
        except Exception:
            return None

    pipeline_completed_states = ['AI_REPORT', 'APPROVED', 'COMPLETED']

    user_jobs_qs = Job.objects.filter(created_by=request.user).prefetch_related('rework_requests')
    user_jobs = [job for job in user_jobs_qs if not job.is_deleted]

    total_reworks = 0
    for job in user_jobs:
        sync_job_status(job)
        job.rework_count = len(list(job.rework_requests.all()))
        total_reworks += job.rework_count
        job.can_request_rework = job.status in ('AI_REPORT', 'REWORK_COMPLETED')

        job.pipeline_completed = (job.status or '').upper() in pipeline_completed_states or bool(_safe_related(job, 'ai_report'))
        full_content_obj = _safe_related(job, 'full_content')
        job.release_unlocked = (
            bool(getattr(job, 'payment_slip', None))
            or bool(getattr(full_content_obj, 'is_approved', False))
            or (job.status or '').upper() in {'APPROVED', 'COMPLETED'}
        )
        job.can_view_generated = job.pipeline_completed and job.release_unlocked
        job.generation_used = get_regeneration_usage(job)
        job.generation_limit = MARKETING_GENERATION_LIMIT
        job.generation_remaining = max(0, job.generation_limit - job.generation_used)
        job.can_run_pipeline = (
            (job.status or '').upper() != 'IN_PROGRESS'
            and not job.is_deleted
            and job.generation_used < job.generation_limit
        )
        job.summary_obj = getattr(job, 'summary', None)
        job.structure_obj = getattr(job, 'job_structure', None)
        job.content_obj = getattr(job, 'generated_content', None)
        job.references_obj = _safe_related(job, 'references')
        job.full_content_obj = full_content_obj
        job.plag_report_obj = _safe_related(job, 'plag_report')
        job.ai_report_obj = _safe_related(job, 'ai_report')
        job.allow_payment_slip = allow_payment_slip

    if filter_type == 'pending':
        jobs = [job for job in user_jobs if job.status == 'PENDING']
    elif filter_type == 'approved':
        jobs = [job for job in user_jobs if job.status == 'APPROVED']
    elif filter_type == 'completed':
        jobs = [job for job in user_jobs if job.status in pipeline_completed_states]
    elif filter_type == 'rework':
        jobs = [job for job in user_jobs if job.rework_count > 0]
    else:
        jobs = list(user_jobs)
    
    jobs = [
        job for job in jobs
        if job_matches_marketing_filters(job, normalized_filters)
    ]

    # Calculate statistics
    total_jobs = len(user_jobs)
    pending_jobs = sum(1 for job in user_jobs if job.status == 'PENDING')
    total_amount = sum(job.amount or 0 for job in user_jobs)

    filtered_total = len(jobs)
    per_page = 20
    paginator = Paginator(jobs, per_page)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    paginated_jobs = page_obj.object_list

    params = request.GET.copy()
    params.pop('page', None)
    pagination_query = params.urlencode()
    
    settings_obj = SystemSettings.get_solo()

    context = {
        'jobs': paginated_jobs,
        'total_jobs': total_jobs,
        'pending_jobs': pending_jobs,
        'total_amount': total_amount,
        'filtered_total': filtered_total,
        'filter_type': filter_type,
        'status_choices': Job.STATUS_CHOICES,
        'filter_params': raw_filters,
        'page_obj': page_obj,
        'per_page': per_page,
        'pagination_query': pagination_query,
        'rework_limit': settings_obj.rework_limit,
        'total_reworks': total_reworks,
        'allow_payment_slip': allow_payment_slip,
    }
    
    return render(request, 'marketing/all_projects.html', context)

@login_required
@marketing_required
def create_job_view(request):
    """Create new job"""
    if request.method == 'POST':
        form = JobDropForm(request.POST, request.FILES)
        if form.is_valid():
            from jobs.models import Attachment
            from auditlog.utils import log_action
            from jobs.models import JobMetrics
            
            job = form.save(commit=False)
            job.created_by = request.user
            job.save()
            notify_superadmins_new_job(job)
            
            # Handle file attachments
            from jobs.models import Attachment
            import os
            
            # Handle multiple file uploads
            files = request.FILES.getlist('attachments')
            for file in files:
                Attachment.objects.create(
                    job=job,
                    file=file,
                    filename=file.name,
                    file_type=file.name.split('.')[-1].lower(),
                    file_size=file.size
                )
            
            from auditlog.utils import log_action, log_job_action
            
            # Log action  ✅ pass `request` instead of `request.user`
            log_action(
                user=request.user,
                action_type='CREATE',
                target_object=job,
                description=f'Created job {job.job_id} (System ID: {job.system_id})',
                request=request,
            )
            
            log_job_action(
                job_id=job.job_id,
                system_id=job.system_id,
                user=request.user,
                action='JOB_CREATED'
            )
            from jobs.models import JobMetrics
            # Update metrics
            JobMetrics.update_metrics()
            
            messages.success(request, f'Job {job.job_id} created successfully!')
            return redirect('marketing:all_projects')
        else:
            if form.errors.get('expected_deadline') or form.errors.get('strict_deadline'):
                messages.error(
                    request,
                    'You cannot set Expected or Strict deadlines on Sundays or holidays. Please choose different dates.'
                )
    else:
        form = JobDropForm()
    
    return render(
        request,
        'marketing/create_job.html',
        {
            'form': form,
            'is_edit': False,
            'form_title': 'Job Drop Form',
            'submit_label': 'Submit Job',
            'cancel_url': reverse('marketing:all_projects'),
            'show_attachments': True,
        },
    )


@login_required
@marketing_required
def profile_view(request):
    """Marketing user profile"""
    return render(request, 'marketing/profile.html', {'user': request.user})


@login_required
@marketing_required
def run_pipeline(request, job_id):
    """Run the full AI pipeline sequentially for a marketing-owned job."""
    job = get_object_or_404(Job.objects.filter(job_id=job_id, created_by=request.user))

    if job.is_deleted:
        messages.error(request, 'Job is archived and cannot run the pipeline.')
        return redirect('marketing:all_projects')

    if request.method != 'POST':
        messages.error(request, 'Invalid request method.')
        return redirect('marketing:all_projects')

    if get_regeneration_usage(job) >= MARKETING_GENERATION_LIMIT:
        messages.error(
            request,
            f'Generation limit reached for {job.job_id}. You can regenerate up to {MARKETING_GENERATION_LIMIT} times.',
        )
        return redirect('marketing:all_projects')

    try:
        job.status = 'IN_PROGRESS'
        job.save(update_fields=['status'])
        result = run_marketing_pipeline(job, request.user)
        if result.get('success'):
            messages.success(
                request,
                'AI pipeline completed: ' + '; '.join(result.get('results', [])),
            )
        else:
            job.status = 'PENDING'
            job.save(update_fields=['status'])
            messages.error(request, result.get('error') or 'Pipeline failed.')
    except Exception as exc:  # pragma: no cover - defensive
        messages.error(request, f'Pipeline failed: {exc}')
    finally:
        sync_job_status(job)
        log_job_action(
            job_id=job.job_id,
            system_id=job.system_id,
            user=request.user,
            action='PIPELINE_RUN',
        )

    return redirect('marketing:all_projects')


@login_required
@marketing_required
def upload_payment_slip(request, job_id):
    """Upload a payment slip screenshot to unlock content downloads early."""
    job = get_object_or_404(Job.objects.filter(job_id=job_id, created_by=request.user))

    if job.is_deleted:
        messages.error(request, 'Job is archived and cannot accept uploads.')
        return redirect('marketing:all_projects')

    if request.method != 'POST':
        messages.error(request, 'Invalid request method.')
        return redirect('marketing:all_projects')

    access_setting = ContentAccessSetting.for_user(request.user)
    if access_setting and access_setting.mode == ContentAccessSetting.MODE_APPROVAL_ONLY:
        messages.error(request, 'Payment slip uploads are disabled for your account by Super Admin.')
        return redirect('marketing:all_projects')

    slip = request.FILES.get('payment_slip')
    if not slip:
        messages.error(request, 'Please select a payment slip to upload.')
        return redirect('marketing:all_projects')

    job.payment_slip = slip
    job.save(update_fields=['payment_slip'])
    log_action(
        request.user,
        'UPLOAD_PAYMENT_SLIP',
        job,
        f'Uploaded payment slip for {job.job_id}',
        request=request,
    )
    log_job_action(
        job_id=job.job_id,
        system_id=job.system_id,
        user=request.user,
        action='PAYMENT_SLIP_UPLOADED',
    )
    messages.success(request, 'Payment slip uploaded. Content will unlock after generation.')
    return redirect('marketing:all_projects')


@login_required
@marketing_required
def request_rework(request, job_id):
    """Allow marketing to request a rework for their job."""
    job = get_object_or_404(Job.objects.filter(job_id=job_id, created_by=request.user))
    if job.is_deleted:
        messages.error(request, 'Job is archived and cannot be reworked.')
        return redirect(request.META.get('HTTP_REFERER') or reverse('marketing:all_projects'))

    if job.status not in ('AI_REPORT', 'REWORK_COMPLETED'):
        messages.error(request, 'Rework is only available when AI Report is ready.')
        return redirect(request.META.get('HTTP_REFERER') or reverse('marketing:all_projects'))
    settings_obj = SystemSettings.get_solo()
    limit = settings_obj.rework_limit
    current_reworks = job.rework_requests.count()

    if current_reworks >= limit:
        messages.error(
            request,
            f'Rework limit reached for {job.job_id}. You can request up to {limit} reworks.',
        )
        return redirect(request.META.get('HTTP_REFERER') or reverse('marketing:all_projects'))

    if request.method != 'POST':
        messages.error(request, 'Invalid request method.')
        return redirect(request.META.get('HTTP_REFERER') or reverse('marketing:dashboard'))

    form = JobReworkForm(request.POST, request.FILES)
    if form.is_valid():
        rework = form.save(commit=False)
        rework.job = job
        rework.requested_by = request.user
        # Assign stable rework ID (system_id R1, R2, ...)
        try:
            count = job.rework_requests.count() + 1
        except Exception:
            count = 1
        rework.rework_id = f"{job.system_id} R{count}"
        rework.save()
        job.status = 'REWORK'
        job.save(update_fields=['status'])
        log_action(
            request.user,
            'REWORK_REQUEST',
            job,
            f'Rework requested for {job.job_id}: {rework.reason[:120]}',
            request=request,
        )
        create_notification(
            title='Rework Requested',
            message=f'Rework requested for {job.job_id}',
            url=reverse('superadmin:rework_detail', args=[rework.id]),
            role_target='SUPERADMIN',
            related_model='JobReworkRequest',
            related_object_id=str(rework.id),
        )
        messages.success(request, f'Rework requested for {job.job_id}. Super Admin will review it.')
    else:
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
    return redirect(request.META.get('HTTP_REFERER') or reverse('marketing:all_projects'))


@login_required
@marketing_required
def job_rework_history(request, job_id):
    job = get_object_or_404(Job.objects.filter(job_id=job_id, created_by=request.user))
    reworks = list(
        JobReworkRequest.objects.filter(job=job)
        .select_related('generation', 'handled_by')
        .order_by('-created_at')
    )
    context = {
        'job': job,
        'reworks': reworks,
    }
    return render(request, 'marketing/rework_history.html', context)
