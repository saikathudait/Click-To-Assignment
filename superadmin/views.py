import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from ai_pipeline.models import FullContent, GeneratedContent, JobStructure, JobSummary, References
from ai_pipeline.utils import sync_job_status
from datetime import datetime, timedelta
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from jobs.models import Job, JobReworkRequest, ReworkGeneration
from form_management.models import FormDefinition
from tickets.models import Ticket, CustomerTicket
from accounts.models import User
from customer.models import CustomerProfile
from profiles.models import Profile, ProfileUpdateRequest
from approvals.models import UserApprovalLog
from auditlog.models import ActionLog, PageVisit
from auditlog.utils import log_action
from django.urls import reverse_lazy
from notifications.utils import notify_marketing_job_approved
from notifications.utils import notify_marketing_rework_completed
from notifications.utils import notify_announcement_created
from superadmin.forms import (
    AnnouncementForm,
    BackupExportForm,
    PricingPlanForm,
    SystemSettingsForm,
    UserCreateForm,
    UserUpdateForm,
    GoogleAuthConfigForm,
)
from superadmin.models import (
    Announcement,
    AnnouncementReceipt,
    AIRequestLog,
    CoinWallet,
    CoinRule,
    CoinTransaction,
    ContentAccessSetting,
    MenuItem,
    PricingPlan,
    PricingPlanPurchase,
    StructureGenerationSubmission,
    ContentGenerationSubmission,
    JobCheckingSubmission,
    SystemSettings,
    GoogleAuthConfig,
    GoogleLoginLog,
)
from allauth.socialaccount.models import SocialAccount
from django.conf import settings
from superadmin.services import (
    ANNOUNCEMENT_STATUS_BADGES,
    ANNOUNCEMENT_STATUS_LABELS,
    ANNOUNCEMENT_TYPE_BADGES,
    BackupExportError,
    generate_backup_export,
    get_exportable_model_metadata,
    get_visible_announcements_for_user,
)

REWORK_SUMMARY_PROMPT = r"""
Rework Job Summary
You are an AI assistant specialized in analysing writing tasks and producing a precise Job Summary for rework, not the full content itself. Your role is to read the user’s instructions and any extracted text from attachments (such as PDFs, DOCX files, or pasted content) and convert them into a clear, concise, implementation-ready Job Summary that another writer or AI can directly follow. The Job Summary must specify exactly what the task is, what needs to be rewritten or corrected, the required word count or length, tone, structure, formatting, referencing style, number of sources, academic level, and any constraints such as AI-free tone, plagiarism-free requirements, or specific style rules. Do not write any actual assignment content, do not add new sections, do not explain your reasoning, and do not expand beyond the user’s instructions. Only provide a clean, structured Job Summary focused strictly on what needs to be changed or produced. Your output must be direct, actionable, and aligned fully with the user’s requirements, describing only what needs to be done for the rework.
""".strip()

MAKE_REWORK_PROMPT = r"""
You are an AI assistant designed to perform precise, instruction-based rework of full documents. You must only make changes that the user explicitly instructs through a professional comment, rework note, or correction request. Never change or rewrite anything unless the user’s comment or rework summary clearly states what needs revision. All rework must strictly follow the user’s provided notes, such as correcting mistakes, rewriting unclear sections, expanding content, removing content, adjusting tone, restructuring, adding references, correcting citations, reducing AI-like writing, or redoing entire sections. You must not guess, assume, or make changes on your own—every edit must be grounded in a specific, user-provided rework comment or instruction.

When rewriting or expanding content, match the existing tone, style, academic level, and formatting. When removing content, maintain coherence. When correcting mistakes, follow the user’s note exactly. When rewriting a section, preserve the meaning unless the user requests a conceptual change.

If the user requests reference generation or reference additions, follow this rule exactly:
“Your task is to create an original, topic-related reference list that strictly follows the given reference style and is based on the themes, concepts, and topics present in the content. All references must be real, credible, verifiable, and published from 2022 onward. Generate approximately 7 references per 1000 words of content. Present a properly formatted Reference List in A–Z order, followed by a separate Citation List with correct in-text citation formats according to the chosen referencing style. Do not include explanations or analysis—only the formatted lists.”

After executing the rework, you must always output the FULL final content, including both unchanged and changed parts, merged into one clean output. Do not output explanations, reasoning, or comments—only the final revised document (and the Reference List + Citation List if required).
""".strip()


def _parse_date_param(value):
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


def _collect_filter_values(request):
    raw = {
        'search': (request.GET.get('search') or '').strip(),
        'status': (request.GET.get('status') or '').strip().upper(),
        'subcategory': (request.GET.get('subcategory') or '').strip(),
        'date_field': (request.GET.get('date_field') or 'expected').strip().lower(),
        'date_from': (request.GET.get('date_from') or '').strip(),
        'date_to': (request.GET.get('date_to') or '').strip(),
    }
    if raw['date_field'] not in ('expected', 'strict'):
        raw['date_field'] = 'expected'

    normalized = {
        'search': raw['search'].lower(),
        'status': raw['status'],
        'subcategory': raw['subcategory'].lower(),
        'date_field': raw['date_field'],
        'date_from': _parse_date_param(raw['date_from']),
        'date_to': _parse_date_param(raw['date_to']),
    }
    return raw, normalized


def _job_matches_filters(job, filters):
    summary = getattr(job, 'summary', None)

    def _contains(value, needle):
        return needle in (value or '').lower()

    search = filters['search']
    if search:
        search_fields = [
            job.job_id,
            job.system_id,
            getattr(job, 'instruction', ''),
            getattr(summary, 'topic', None),
            getattr(summary, 'summary_text', None),
        ]
        if not any(_contains(field, search) for field in search_fields):
            return False

    subcat = filters['subcategory']
    if subcat:
        subcat_fields = [
            getattr(job, 'instruction', ''),
            getattr(summary, 'summary_text', None),
            getattr(summary, 'writing_style', None),
        ]
        if not any(_contains(field, subcat) for field in subcat_fields):
            return False

    status_filter = filters['status']
    if status_filter and (job.status or '').upper() != status_filter:
        return False

    date_from = filters['date_from']
    date_to = filters['date_to']
    if date_from or date_to:
        deadline = job.expected_deadline if filters['date_field'] == 'expected' else job.strict_deadline
        if not deadline:
            return False
        if timezone.is_naive(deadline):
            deadline_date = deadline.date()
        else:
            deadline_date = timezone.localtime(deadline).date()
        if date_from and deadline_date < date_from:
            return False
        if date_to and deadline_date > date_to:
            return False

    return True


def _paginate_items(request, items, page_param='page', per_page=20):
    paginator = Paginator(items, per_page)
    page_number = request.GET.get(page_param)
    page_obj = paginator.get_page(page_number)
    params = request.GET.copy()
    if page_param in params:
        params.pop(page_param)
    pagination_query = params.urlencode()
    pagination_base = f'?{pagination_query}&' if pagination_query else '?'
    return page_obj, pagination_base


def _format_duration(seconds):
    seconds = int(seconds or 0)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if not parts:
        parts.append(f"{secs}s")
    return " ".join(parts)


def _convert_seconds(seconds, unit):
    seconds = float(seconds or 0)
    if unit == 'hours':
        return round(seconds / 3600.0, 2)
    if unit == 'minutes':
        return round(seconds / 60.0, 1)
    return int(round(seconds))


def _seconds_to_hours(seconds):
    return round(float(seconds or 0) / 3600.0, 2)


def _has_active_superadmin(exclude_user=None):
    """Ensure at least one active super admin remains."""
    exclude_id = getattr(exclude_user, 'pk', exclude_user) if exclude_user else None
    users = User.objects.all()
    for user in users:
        if exclude_id and user.pk == exclude_id:
            continue
        if user.role == 'SUPERADMIN' and user.is_active and not user.is_deleted:
            return True
    return False


def _build_announcement_status_data(announcements, reference_time=None):
    """Return status map + counts for announcement queryset."""
    reference_time = reference_time or timezone.now()
    status_counts = {
        Announcement.STATUS_ACTIVE: 0,
        Announcement.STATUS_SCHEDULED: 0,
        Announcement.STATUS_EXPIRED: 0,
        Announcement.STATUS_INACTIVE: 0,
    }
    status_map = {}
    for announcement in announcements:
        status = announcement.status(reference_time)
        status_map[announcement.pk] = status
        status_counts[status] = status_counts.get(status, 0) + 1
    return status_map, status_counts, reference_time


def _announcement_visibility_values():
    return [choice[0] for choice in Announcement.VISIBILITY_CHOICES]


def superadmin_required(view_func):
    """Decorator to ensure only superadmin can access"""
    def wrapper(request, *args, **kwargs):
        if request.user.role != 'SUPERADMIN':
            messages.error(request, 'Access denied. SuperAdmin only.')
            return redirect('marketing:dashboard')
        return view_func(request, *args, **kwargs)
    return wrapper


@login_required
@superadmin_required
def announcement_list_view(request):
    """List + create announcements (Notice Management)."""
    announcements = [
        announcement for announcement in
        Announcement.objects.select_related('created_by').order_by('-start_at', '-created_at')
        if getattr(announcement, 'pk', None)
    ]
    status_map, status_counts, ref_time = _build_announcement_status_data(announcements)

    status_filter = (request.GET.get('status') or '').upper()
    if status_filter not in status_counts:
        status_filter = ''

    visibility_filter = (request.GET.get('visibility') or '').upper()
    if visibility_filter not in _announcement_visibility_values():
        visibility_filter = ''

    filtered_announcements = announcements
    status_labels = ANNOUNCEMENT_STATUS_LABELS
    status_badges = ANNOUNCEMENT_STATUS_BADGES
    type_badges = ANNOUNCEMENT_TYPE_BADGES

    if status_filter:
        filtered_announcements = [
            announcement for announcement in filtered_announcements
            if status_map.get(announcement.pk) == status_filter
        ]
    if visibility_filter:
        filtered_announcements = [
            announcement for announcement in filtered_announcements
            if announcement.visibility == visibility_filter
        ]
    for announcement in filtered_announcements:
        status = status_map.get(announcement.pk)
        announcement.calculated_status = status
        announcement.status_label = status_labels.get(status, status)
        announcement.status_badge_class = status_badges.get(status, 'bg-secondary')
        announcement.type_badge_class = type_badges.get(announcement.type, 'bg-secondary')

    if request.method == 'POST':
        form = AnnouncementForm(request.POST, request.FILES)
        if form.is_valid():
            announcement = form.save(commit=False)
            announcement.created_by = request.user
            announcement.save()
            try:
                notify_announcement_created(announcement)
            except Exception:
                pass
            log_action(
                request.user,
                'CREATE',
                target_object=announcement,
                description=f'Created announcement "{announcement.title}"',
                request=request,
            )
            messages.success(request, 'Announcement created successfully.')
            return redirect('superadmin:announcement_list')
    else:
        initial_start = timezone.localtime(ref_time)
        form = AnnouncementForm(initial={'start_at': initial_start})

    status_summaries = [
        {
            'key': key,
            'label': status_labels[key],
            'count': status_counts.get(key, 0),
        }
        for key in status_labels.keys()
    ]

    context = {
        'announcements': filtered_announcements,
        'status_filter': status_filter,
        'visibility_filter': visibility_filter,
        'form': form,
        'Announcement': Announcement,
        'total_announcements': len(announcements),
        'ref_time': ref_time,
        'status_summaries': status_summaries,
        'visibility_choices': Announcement.VISIBILITY_CHOICES,
        'active_count': status_counts.get(Announcement.STATUS_ACTIVE, 0),
        'status_labels': status_labels,
    }
    return render(request, 'superadmin/notice_management.html', context)


@login_required
@superadmin_required
def announcement_edit_view(request, pk):
    announcement = get_object_or_404(Announcement, pk=pk)
    if request.method == 'POST':
        form = AnnouncementForm(request.POST, request.FILES, instance=announcement)
        if form.is_valid():
            form.save()
            log_action(
                request.user,
                'UPDATE',
                target_object=announcement,
                description=f'Updated announcement "{announcement.title}"',
                request=request,
            )
            messages.success(request, 'Announcement updated successfully.')
            return redirect('superadmin:announcement_list')
    else:
        form = AnnouncementForm(instance=announcement)

    context = {
        'form': form,
        'announcement': announcement,
    }
    return render(request, 'superadmin/announcement_form.html', context)


@login_required
@superadmin_required
@require_POST
def announcement_toggle_view(request, pk):
    announcement = get_object_or_404(Announcement, pk=pk)
    announcement.is_active = not announcement.is_active
    announcement.save(update_fields=['is_active'])
    state = 'activated' if announcement.is_active else 'deactivated'
    log_action(
        request.user,
        'UPDATE',
        target_object=announcement,
        description=f'{state.capitalize()} announcement "{announcement.title}"',
        request=request,
    )
    messages.success(request, f'Announcement {state}.')
    return redirect('superadmin:announcement_list')


@login_required
@superadmin_required
@require_POST
def announcement_delete_view(request, pk):
    announcement = get_object_or_404(Announcement, pk=pk)
    log_action(
        request.user,
        'DELETE',
        target_object=announcement,
        description=f'Deleted announcement "{announcement.title}"',
        request=request,
    )
    announcement.delete()
    messages.success(request, 'Announcement deleted.')
    return redirect('superadmin:announcement_list')


@login_required
@require_POST
def announcement_dismiss_view(request, pk):
    announcement = get_object_or_404(Announcement, pk=pk)
    user = request.user
    if not announcement.is_for_role(user.role):
        return JsonResponse({'error': 'Not allowed'}, status=403)

    receipt, _ = AnnouncementReceipt.objects.get_or_create(
        announcement=announcement,
        user=user,
        defaults={'seen_at': timezone.now()},
    )
    receipt.mark_dismissed()
    return JsonResponse({'success': True})


@login_required
@superadmin_required
def backup_center_view(request):
    metadata = get_exportable_model_metadata()
    metadata_map = {item['key']: item for item in metadata}
    form = BackupExportForm(request.POST or None, table_metadata=metadata)
    total_records = sum(item['count'] or 0 for item in metadata)

    if request.method == 'POST' and form.is_valid():
        selected_keys = form.cleaned_data.get('tables') or []
        if not selected_keys and form.cleaned_data.get('status'):
            selected_keys = [
                item['key'] for item in metadata
                if item['app_label'] == form.cleaned_data['status']
            ]
        if form.cleaned_data.get('include_all') or not selected_keys:
            selected_keys = list(metadata_map.keys())
        try:
            result = generate_backup_export(
                selected_keys,
                form.cleaned_data['export_format'],
                metadata_map,
                start_date=form.cleaned_data.get('start_date'),
                end_date=form.cleaned_data.get('end_date'),
            )
        except BackupExportError as exc:
            messages.error(request, str(exc))
        else:
            log_action(
                request.user,
                'GENERATE',
                description=f'Exported backup (format={form.cleaned_data["export_format"]}, tables={len(selected_keys)})',
                request=request,
            )
            response = HttpResponse(result.content, content_type=result.content_type)
            response['Content-Disposition'] = f'attachment; filename="{result.filename}"'
            return response

    status_filter = getattr(form, 'selected_status', None)
    filtered_metadata = [
        item for item in metadata if not status_filter or item['app_label'] == status_filter
    ]

    context = {
        'form': form,
        'table_metadata': filtered_metadata,
        'available_table_count': len(metadata),
        'total_record_count': total_records,
        'now': timezone.now(),
        'status_filter': status_filter,
        'table_app_map_json': json.dumps({item['key']: item['app_label'] for item in metadata}),
    }
    return render(request, 'superadmin/backup_center.html', context)


@login_required
@superadmin_required
def welcome_view(request):
    """SuperAdmin welcome page"""
    announcements = get_visible_announcements_for_user(request.user)
    context = {
        'user': request.user,
        'announcements': announcements,
    }
    return render(request, 'superadmin/welcome.html', context)
@login_required
@superadmin_required
def dashboard_view(request):
    """SuperAdmin dashboard with statistics"""
    all_jobs = list(Job.objects.all())
    active_jobs = [job for job in all_jobs if not job.is_deleted]

    total_jobs = len(active_jobs)
    pending_jobs = sum(1 for job in active_jobs if job.status == 'PENDING')
    approved_jobs = sum(1 for job in active_jobs if job.status == 'APPROVED')
    completed_jobs = sum(
        1 for job in active_jobs if job.status in {
            'FULL_CONTENT',
            'PLAGIARISM_REPORT',
            'AI_REPORT',
            'APPROVED',
            'COMPLETED',
        }
    )

    total_amount = sum((job.amount or 0) for job in active_jobs)
    # 🚫 Do NOT filter on booleans in SQL (djongo breaks on WHERE "is_active")
    # users_qs = User.objects.filter(is_active=True)
    # ✅ Safe: get all users, then calculate in Python
    users = list(User.objects.all())
    # Active + approved stats
    total_users = sum(1 for u in users if u.is_active and u.is_approved)
    pending_users = sum(1 for u in users if u.is_active and not u.is_approved)
    marketing_users = User.objects.filter(role='marketing')
    approved_users = sum(1 for u in marketing_users if u.is_approved)
    # Profile update requests (status is probably a CharField, safe)
    pending_profile_updates = ProfileUpdateRequest.objects.filter(
        status='PENDING'
    ).count()
    per_page = 3
    sorted_recent_jobs = sorted(active_jobs, key=lambda job: job.created_at, reverse=True)
    recent_paginator = Paginator(sorted_recent_jobs, per_page)
    recent_page_obj = recent_paginator.get_page(request.GET.get('recent_page'))
    recent_jobs = recent_page_obj.object_list
    recent_params = request.GET.copy()
    recent_params.pop('recent_page', None)
    recent_query = recent_params.urlencode()
    recent_users = User.objects.filter(role='marketing', is_approved=True).order_by('-approved_at')[:5]
    context = {
        'total_jobs': total_jobs,
        'pending_jobs': pending_jobs,
        'approved_jobs': approved_jobs,
        'completed_jobs': completed_jobs,
        'total_amount': total_amount,
        'pending_users': pending_users,
        'total_users': total_users,
        'pending_profile_updates': pending_profile_updates,
        'recent_jobs': recent_jobs,
        'recent_page_obj': recent_page_obj,
        'recent_per_page': per_page,
        'recent_query': recent_query,
        'approved_users': approved_users,
        'recent_users': recent_users,
    }
    return render(request, 'superadmin/dashboard.html', context)


@login_required
@superadmin_required
def statistics_view(request):
    """SuperAdmin-only reporting hub with aggregated performance metrics."""
    now = timezone.now()
    date_from = _parse_date_param(request.GET.get('date_from'))
    date_to = _parse_date_param(request.GET.get('date_to'))
    status_filter = (request.GET.get('status') or '').strip().upper()
    user_filter = (request.GET.get('user') or '').strip()
    try:
        deadline_window_hours = max(1, int(request.GET.get('deadline_window') or 48))
    except (TypeError, ValueError):
        deadline_window_hours = 48

    def _aware(dt):
        if not dt:
            return None
        if timezone.is_naive(dt):
            return timezone.make_aware(dt)
        return dt

    def _created_date(job):
        created_at = job.created_at
        if not created_at:
            return None
        created_at = _aware(created_at)
        return timezone.localtime(created_at).date()

    raw_jobs = Job.objects.select_related('created_by').all().order_by('-created_at')
    all_jobs = [job for job in raw_jobs if not job.is_deleted]
    global_pending_jobs = sum(1 for job in all_jobs if job.status == 'PENDING')

    def _matches_filters(job):
        created_date = _created_date(job)
        if date_from and created_date and created_date < date_from:
            return False
        if date_to and created_date and created_date > date_to:
            return False
        if status_filter and (job.status or '').upper() != status_filter:
            return False
        if user_filter:
            try:
                if str(job.created_by_id) != str(int(user_filter)):
                    return False
            except (TypeError, ValueError):
                if str(job.created_by_id) != user_filter:
                    return False
        return True

    filtered_jobs = [job for job in all_jobs if _matches_filters(job)]
    job_ids = [job.id for job in filtered_jobs]

    status_counts = {choice[0]: 0 for choice in Job.STATUS_CHOICES}
    for job in filtered_jobs:
        status_key = (job.status or '').upper()
        status_counts[status_key] = status_counts.get(status_key, 0) + 1

    job_approvals = sum(
        1 for job in filtered_jobs
        if getattr(job, 'is_approved', False) or (job.status or '').upper() == 'APPROVED'
    )
    job_rejections = sum(1 for job in filtered_jobs if (job.status or '').upper() == 'REJECTED')
    total_jobs = len(filtered_jobs)
    pending_jobs_count = status_counts.get('PENDING', 0)

    reworks_qs = JobReworkRequest.objects.filter(job_id__in=job_ids)
    rework_counts = {
        'total': reworks_qs.count(),
        'pending': reworks_qs.filter(status=JobReworkRequest.STATUS_PENDING).count(),
        'approved': reworks_qs.filter(status=JobReworkRequest.STATUS_APPROVED).count(),
        'rejected': reworks_qs.filter(status=JobReworkRequest.STATUS_REJECTED).count(),
    }
    rework_rate = (rework_counts['total'] / total_jobs * 100) if total_jobs else 0

    def _turnaround_hours(job):
        if not job.approved_at or not job.created_at:
            return None
        approved = timezone.localtime(_aware(job.approved_at))
        created = timezone.localtime(_aware(job.created_at))
        delta = approved - created
        return delta.total_seconds() / 3600 if delta else None

    turnaround_hours = [hrs for hrs in (_turnaround_hours(job) for job in filtered_jobs) if hrs is not None]
    average_turnaround_hours = sum(turnaround_hours) / len(turnaround_hours) if turnaround_hours else 0

    near_deadline_cutoff = now + timedelta(hours=deadline_window_hours)
    nearing_deadline = [
        job for job in filtered_jobs
        if job.strict_deadline
        and _aware(job.strict_deadline) >= now
        and _aware(job.strict_deadline) <= near_deadline_cutoff
        and job.status not in {'APPROVED', 'COMPLETED'}
    ]
    overdue_jobs = [
        job for job in filtered_jobs
        if job.strict_deadline
        and _aware(job.strict_deadline) < now
        and job.status not in {'APPROVED', 'COMPLETED'}
    ]
    at_risk_jobs = (nearing_deadline + overdue_jobs)[:5]

    closed_statuses = {'COMPLETED', 'APPROVED'}
    closed_jobs_count = sum(1 for job in filtered_jobs if job.status in closed_statuses)

    users = list(User.objects.all())
    user_stats = {
        'active': sum(1 for u in users if u.is_active and not u.is_deleted),
        'inactive': sum(1 for u in users if not u.is_active and not u.is_deleted),
        'approved': sum(1 for u in users if u.is_approved and u.is_active and not u.is_deleted),
        'pending': sum(1 for u in users if not u.is_approved and u.is_active and not u.is_deleted),
    }
    # User approval outcomes (fallback to model state if no logs)
    user_approval_logs = list(UserApprovalLog.objects.all())
    log_approved = sum(1 for log in user_approval_logs if (log.action or '').lower() == 'approved')
    log_rejected = sum(1 for log in user_approval_logs if (log.action or '').lower() == 'rejected')
    user_approved_total = log_approved or sum(1 for u in users if u.is_approved)
    user_rejected_total = log_rejected or sum(1 for u in users if not u.is_active and not u.is_approved)

    form_objects = list(FormDefinition.objects.all())
    form_stats = {
        'active': sum(1 for f in form_objects if getattr(f, 'is_active', False)),
        'inactive': sum(1 for f in form_objects if not getattr(f, 'is_active', False)),
        'total': len(form_objects),
    }

    tickets_pending = Ticket.objects.filter(status__in=['NEW', 'UNDER_REVIEW', 'REWORK']).count()
    pending_profile_updates = ProfileUpdateRequest.objects.filter(status='PENDING').count()

    trend_map = {}
    completion_trend_map = {}
    backlog_trend_map = {}
    week_approval_map = {}
    pending_statuses = {
        'PENDING',
        'JOB_SUMMARY',
        'JOB_STRUCTURE',
        'CONTENT',
        'REFERENCES',
        'FULL_CONTENT',
        'PLAGIARISM_REPORT',
        'AI_REPORT',
        'IN_PROGRESS',
        'REWORK',
        'REWORK_COMPLETED',
    }
    closed_statuses = {
        'APPROVED',
        'COMPLETED',
        'FULL_CONTENT',
        'PLAGIARISM_REPORT',
        'AI_REPORT',
        'REWORK_COMPLETED',
    }
    job_created_by_date = {}

    for job in filtered_jobs:
        created_date = _created_date(job)
        normalized_status = (job.status or '').upper()
        if created_date:
            trend_map[created_date] = trend_map.get(created_date, 0) + 1
            job_created_by_date[created_date] = job_created_by_date.get(created_date, 0) + 1
            if normalized_status in pending_statuses:
                backlog_trend_map[created_date] = backlog_trend_map.get(created_date, 0) + 1

        if normalized_status in closed_statuses or getattr(job, 'is_approved', False):
            completion_date = job.approved_at or job.updated_at or job.created_at
            completion_date = _aware(completion_date)
            if completion_date:
                completion_date = timezone.localtime(completion_date).date()
                completion_trend_map[completion_date] = completion_trend_map.get(completion_date, 0) + 1

        # Weekly approval/rejection stacking (include is_approved flag)
        if normalized_status in {'APPROVED', 'REJECTED'} or getattr(job, 'is_approved', False):
            dt = _aware(job.approved_at or job.updated_at or job.created_at)
            if dt:
                local_dt = timezone.localtime(dt)
                year, week, _ = local_dt.isocalendar()
                key = f'{year}-W{week:02d}'
                entry = week_approval_map.get(key, {'approved': 0, 'rejected': 0})
                if normalized_status == 'REJECTED':
                    entry['rejected'] += 1
                else:
                    entry['approved'] += 1
                week_approval_map[key] = entry

    profile_requests = list(ProfileUpdateRequest.objects.all())
    profile_approved_total = sum(1 for req in profile_requests if (req.status or '').upper() == 'APPROVED')
    profile_rejected_total = sum(1 for req in profile_requests if (req.status or '').upper() == 'REJECTED')
    for req in profile_requests:
        status = (req.status or '').upper()
        if status not in {'APPROVED', 'REJECTED'}:
            continue
        dt = req.processed_at or req.created_at
        dt = _aware(dt)
        if not dt:
            continue
        local_dt = timezone.localtime(dt)
        year, week, _ = local_dt.isocalendar()
        key = f'{year}-W{week:02d}'
        entry = week_approval_map.get(key, {'approved': 0, 'rejected': 0})
        if status == 'REJECTED':
            entry['rejected'] += 1
        else:
            entry['approved'] += 1
        week_approval_map[key] = entry

    for log in user_approval_logs:
        dt = _aware(getattr(log, 'timestamp', None))
        if not dt:
            continue
        local_dt = timezone.localtime(dt)
        year, week, _ = local_dt.isocalendar()
        key = f'{year}-W{week:02d}'
        entry = week_approval_map.get(key, {'approved': 0, 'rejected': 0})
        action = (log.action or '').lower()
        if action == 'rejected':
            entry['rejected'] += 1
        elif action == 'approved':
            entry['approved'] += 1
        week_approval_map[key] = entry

    trend_data = [
        {'date': date.isoformat(), 'count': count}
        for date, count in sorted(trend_map.items())
    ]
    completion_trend = [
        {'date': date.isoformat(), 'count': count}
        for date, count in sorted(completion_trend_map.items())
    ]
    backlog_trend = [
        {'date': date.isoformat(), 'count': count}
        for date, count in sorted(backlog_trend_map.items())
    ]

    approvals = job_approvals + profile_approved_total + user_approved_total
    rejections = job_rejections + profile_rejected_total + user_rejected_total

    approval_trend_map = {
        'approved': approvals,
        'rejected': rejections,
        'rework_rate': round(rework_rate, 2),
        'weekly': [
            {'week': key, 'approved': val['approved'], 'rejected': val['rejected']}
            for key, val in sorted(week_approval_map.items())
        ],
    }

    # Rework analytics
    rework_counts_by_job = {}
    for req in reworks_qs:
        rework_counts_by_job[req.job_id] = rework_counts_by_job.get(req.job_id, 0) + 1

    rework_buckets = {'0': 0, '1': 0, '2': 0, '3+': 0}
    rework_status_mix = {}
    for job in filtered_jobs:
        count = rework_counts_by_job.get(job.id, 0)
        if count == 0:
            rework_buckets['0'] += 1
        elif count == 1:
            rework_buckets['1'] += 1
        elif count == 2:
            rework_buckets['2'] += 1
        else:
            rework_buckets['3+'] += 1

        if count > 0:
            normalized_status = (job.status or '').upper()
            rework_status_mix[normalized_status] = rework_status_mix.get(normalized_status, 0) + 1

    rework_rate_trend = []
    rework_per_date = {}
    for req in reworks_qs:
        if not req.created_at:
            continue
        dt = _aware(req.created_at)
        if not dt:
            continue
        d = timezone.localtime(dt).date()
        rework_per_date[d] = rework_per_date.get(d, 0) + 1

    for date, rework_count in sorted(rework_per_date.items()):
        job_count = job_created_by_date.get(date, 0)
        rate = (rework_count / job_count * 100) if job_count else 0
        rework_rate_trend.append({'date': date.isoformat(), 'rate': rate})

    # Turnaround over time (weekly)
    turnaround_week_map = {}
    for job in filtered_jobs:
        hrs = _turnaround_hours(job)
        if hrs is None:
            continue
        dt = _aware(job.approved_at or job.updated_at or job.created_at)
        if not dt:
            continue
        local_dt = timezone.localtime(dt)
        year, week, _ = local_dt.isocalendar()
        key = f'{year}-W{week:02d}'
        arr = turnaround_week_map.get(key, [])
        arr.append(hrs)
        turnaround_week_map[key] = arr

    turnaround_trend = [
        {'week': key, 'hours': (sum(vals) / len(vals)) if vals else 0}
        for key, vals in sorted(turnaround_week_map.items())
    ]

    # Deadline + timeliness
    on_time = 0
    late = 0
    overdue_trend_map = {}
    deadline_buckets = {'Due today': 0, '1-2 days': 0, '3-5 days': 0, '>5 days': 0, 'No deadline': 0}
    for job in filtered_jobs:
        deadline = _aware(job.strict_deadline)
        completed_at = _aware(job.approved_at or job.updated_at)

        normalized_status = (job.status or '').upper()
        if (normalized_status in closed_statuses or getattr(job, 'is_approved', False)) and deadline and completed_at:
            if completed_at <= deadline:
                on_time += 1
            else:
                late += 1

        if deadline:
            deadline_date = timezone.localtime(deadline).date()
            # overdue trend keyed on deadline date for overdue items
            if deadline < now and job.status not in closed_statuses:
                overdue_trend_map[deadline_date] = overdue_trend_map.get(deadline_date, 0) + 1

            if job.status not in closed_statuses:
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

    overdue_trend = [
        {'date': date.isoformat(), 'count': count}
        for date, count in sorted(overdue_trend_map.items())
    ]

    # Marketing productivity
    marketing_users = [u for u in users if (u.role or '').upper() == 'MARKETING' and not u.is_deleted]
    productivity = []
    for m_user in marketing_users:
        user_jobs = [job for job in filtered_jobs if getattr(job, 'created_by_id', None) == m_user.id]
        productivity.append({
            'name': m_user.get_full_name(),
            'created': len(user_jobs),
            'closed': sum(1 for job in user_jobs if job.status in closed_statuses),
        })
    productivity = sorted(productivity, key=lambda item: item['created'], reverse=True)[:8]

    # Form usage placeholder (until actual usage events exist)
    forms_usage = [
        {'name': getattr(form, 'name', 'Form'), 'count': getattr(form, 'order', 0) or 0}
        for form in form_objects
    ]

    recent_actions = ActionLog.objects.all()[:5]

    creator_breakdown = {}
    for job in filtered_jobs:
        creator_name = job.created_by.get_full_name() if getattr(job, 'created_by', None) else 'Unknown'
        creator_breakdown[creator_name] = creator_breakdown.get(creator_name, 0) + 1
    top_creators = sorted(
        [{'name': name, 'count': count} for name, count in creator_breakdown.items()],
        key=lambda item: item['count'],
        reverse=True,
    )[:5]

    context = {
        'filters': {
            'date_from': date_from,
            'date_to': date_to,
            'status': status_filter,
            'user': user_filter,
            'deadline_window_hours': deadline_window_hours,
        },
        'status_labels': dict(Job.STATUS_CHOICES),
        'status_counts': status_counts,
        'total_jobs': total_jobs,
        'approvals': approvals,
        'rejections': rejections,
        'pending_jobs': global_pending_jobs,
        'filtered_pending_jobs': pending_jobs_count,
        'rework_counts': rework_counts,
        'rework_rate': rework_rate,
        'average_turnaround_hours': average_turnaround_hours,
        'nearing_deadline_jobs': nearing_deadline,
        'overdue_jobs': overdue_jobs,
        'at_risk_jobs': at_risk_jobs,
        'closed_jobs_count': closed_jobs_count,
        'user_stats': user_stats,
        'form_stats': form_stats,
        'trend_data_json': json.dumps(trend_data),
        'completion_trend_json': json.dumps(completion_trend),
        'backlog_trend_json': json.dumps(backlog_trend),
        'approval_trend_json': json.dumps(approval_trend_map),
        'top_creators': top_creators,
        'recent_actions': recent_actions,
        'rework_buckets_json': json.dumps(rework_buckets),
        'rework_status_mix_json': json.dumps(rework_status_mix),
        'rework_rate_trend_json': json.dumps(rework_rate_trend),
        'turnaround_trend_json': json.dumps(turnaround_trend),
        'on_time_late_json': json.dumps({'on_time': on_time, 'late': late}),
        'overdue_trend_json': json.dumps(overdue_trend),
        'deadline_buckets_json': json.dumps(deadline_buckets),
        'productivity_json': json.dumps(productivity),
        'forms_usage_json': json.dumps(forms_usage),
        'has_any_data': any([
            total_jobs,
            approvals,
            rejections,
            rework_counts['total'],
            len(trend_data),
            len(completion_trend),
            len(backlog_trend),
            sum(deadline_buckets.values()),
        ]),
        'pending_users': user_stats['pending'],
        'pending_profile_updates': pending_profile_updates,
        'pending_tickets': tickets_pending,
    }
    return render(request, 'superadmin/statistics.html', context)
from django.db.models import Q, Sum
from jobs.models import Job
from ai_pipeline.models import (
    JobSummary,
    JobStructure,
    GeneratedContent,
    References,
    FullContent,
)
from ai_pipeline.services import _get_openai_client
@login_required
@superadmin_required
def all_jobs_view(request):
    """All Jobs Page - shows all jobs with filter cards (djongo-safe)."""
    filter_type = request.GET.get('filter', 'all')
    raw_filters, normalized_filters = _collect_filter_values(request)

    # 1. Load everything with simple queries
    jobs_qs = Job.objects.all().order_by('-created_at')
    jobs = [job for job in jobs_qs if not job.is_deleted]  # materialize

    for job in jobs:
        sync_job_status(job)
    summaries = list(JobSummary.objects.all())
    # Build lookup: job_id -> JobSummary
    summary_by_job_id = {s.job_id: s for s in summaries}
    # 2. Stats in Python
    total_jobs = len(jobs)
    total_amount = sum((job.amount or 0) for job in jobs)
    pending_job_ids = []
    for job in jobs:
        s = summary_by_job_id.get(job.id)
        # Pending if no summary OR summary not approved
        if s is None or not s.is_approved:
            pending_job_ids.append(job.id)
    total_pending_jobs = len(pending_job_ids)
    # 3. Apply filter (for the table)
    if filter_type == 'pending':
        filtered_jobs = [job for job in jobs if job.id in pending_job_ids]
    elif filter_type == 'amount':
        filtered_jobs = sorted(jobs, key=lambda j: (j.amount or 0), reverse=True)
    else:
        filtered_jobs = jobs

    filtered_jobs = [
        job for job in filtered_jobs
        if _job_matches_filters(job, normalized_filters)
    ]
    page_obj, pagination_base = _paginate_items(request, filtered_jobs, 'page')
    paginated_jobs = page_obj.object_list

    jobs_data = []
    for job in paginated_jobs:
        job_summary = summary_by_job_id.get(job.id)
        job_structure = JobStructure.objects.filter(job=job).first()
        content = GeneratedContent.objects.filter(job=job).first()
        references = References.objects.filter(job=job).first()
        full_content = FullContent.objects.filter(job=job).first()
        jobs_data.append({
            'job': job,
            'job_summary': job_summary,
            'job_structure': job_structure,
            'content': content,
            'references': references,
            'plag_report': None,
            'ai_report': None,
            'full_content': full_content,
        })
    context = {
        'total_jobs': total_jobs,
        'total_pending_jobs': total_pending_jobs,
        'total_amount': total_amount,
        'active_filter': filter_type,
        'jobs': paginated_jobs,
        'pending_jobs': total_pending_jobs,
        'jobs_data': jobs_data,
        'status_choices': Job.STATUS_CHOICES,
        'filter_params': raw_filters,
        'page_obj': page_obj,
        'pagination_base': pagination_base,
    }
    return render(request, 'superadmin/all_jobs.html', context)
@login_required
@superadmin_required
def new_jobs_view(request):
    """New jobs page - jobs pending approval"""
    # ✅ Small helper, no logic change – just makes count safe
    def get_generation_count(obj):
        if not obj:
            return 0
        # Prefer regeneration_count, fall back to generation_count if it exists
        return getattr(obj, 'regeneration_count', getattr(obj, 'generation_count', 0))
    raw_filters, normalized_filters = _collect_filter_values(request)
    card_filter = request.GET.get('filter')
    # Base queryset: let DB only handle ordering
    if card_filter == 'amount':
        jobs_qs = Job.objects.all().order_by('-amount')
    else:
        jobs_qs = Job.objects.all().order_by('-created_at')
    jobs = [j for j in jobs_qs if not j.is_deleted and not j.is_approved]

    for job in jobs:
        sync_job_status(job)
    jobs_with_status = []
    total_amount = 0
    for job in jobs:
        # Summary is accessed as job.summary in your generate view
        summary_obj = getattr(job, 'summary', None)
        structure_obj = getattr(job, 'job_structure', None)
        content_obj = getattr(job, 'generated_content', None)
        references_obj = getattr(job, 'references', None)
        plagiarism_obj = getattr(job, 'plagiarism_report', None)
        ai_report_obj = getattr(job, 'ai_report', None)
        full_content_obj = getattr(job, 'full_content', None)
        job_data = {
            'job': job,
            # Job Summary
            'has_summary': summary_obj is not None,
            'summary_approved': summary_obj.is_approved if summary_obj else False,
            'summary_can_regenerate': summary_obj.can_regenerate() if summary_obj else True,
            'summary_count': get_generation_count(summary_obj),
            # Job Structure
            'has_structure': structure_obj is not None,
            'structure_approved': structure_obj.is_approved if structure_obj else False,
            'structure_can_regenerate': structure_obj.can_regenerate() if structure_obj else True,
            'structure_count': get_generation_count(structure_obj),
            # Content
            'has_content': content_obj is not None,
            'content_approved': content_obj.is_approved if content_obj else False,
            'content_can_regenerate': content_obj.can_regenerate() if content_obj else True,
            'content_count': get_generation_count(content_obj),
            # References
            'has_references': references_obj is not None,
            'references_approved': references_obj.is_approved if references_obj else False,
            'references_can_regenerate': references_obj.can_regenerate() if references_obj else True,
            'references_count': get_generation_count(references_obj),
            # Plagiarism Report
            'has_plagiarism': plagiarism_obj is not None,
            'plagiarism_approved': plagiarism_obj.is_approved if plagiarism_obj else False,
            'plagiarism_can_regenerate': plagiarism_obj.can_regenerate() if plagiarism_obj else True,
            'plagiarism_count': get_generation_count(plagiarism_obj),
            # AI Report
            'has_ai_report': ai_report_obj is not None,
            'ai_report_approved': ai_report_obj.is_approved if ai_report_obj else False,
            'ai_report_can_regenerate': ai_report_obj.can_regenerate() if ai_report_obj else True,
            'ai_report_count': get_generation_count(ai_report_obj),
            # Full Content
            'has_full_content': full_content_obj is not None,
            'full_content_approved': full_content_obj.is_approved if full_content_obj else False,
            'full_content_can_regenerate': full_content_obj.can_regenerate() if full_content_obj else True,
            'full_content_count': get_generation_count(full_content_obj),
        }
        job_data['all_components_ready'] = all([
            job_data['summary_approved'],
            job_data['structure_approved'],
            job_data['content_approved'],
            job_data['references_approved'],
            job_data['plagiarism_approved'],
            job_data['ai_report_approved'],
            job_data['full_content_approved'],
        ])
        if job_data['all_components_ready']:
            continue

        if not _job_matches_filters(job, normalized_filters):
            continue

        total_amount += job.amount or 0
        jobs_with_status.append(job_data)
    total_new_jobs = len(jobs_with_status)

    page_obj, pagination_base = _paginate_items(request, jobs_with_status, 'page')
    paginated_jobs = page_obj.object_list

    deleted_jobs = sorted(
        [job for job in Job.objects.all() if job.is_deleted],
        key=lambda job: job.deleted_at or job.created_at,
        reverse=True,
    )
    deleted_page_obj, deleted_pagination_base = _paginate_items(request, deleted_jobs, 'deleted_page')
    paginated_deleted_jobs = deleted_page_obj.object_list

    context = {
        'jobs_with_status': paginated_jobs,
        'total_new_jobs': total_new_jobs,
        'total_amount': total_amount,
        'status_choices': Job.STATUS_CHOICES,
        'filter_params': raw_filters,
        'deleted_jobs': paginated_deleted_jobs,
        'page_obj': page_obj,
        'pagination_base': pagination_base,
        'deleted_page_obj': deleted_page_obj,
        'deleted_pagination_base': deleted_pagination_base,
    }
    return render(request, 'superadmin/new_jobs.html', context)


@login_required
@superadmin_required
def user_management(request):
    """User management dashboard for Super Admins."""
    search_query = (request.GET.get('search') or '').strip()
    role_filter = (request.GET.get('role') or '').strip().upper()
    status_filter = (request.GET.get('status') or '').strip().upper()
    show_deleted = request.GET.get('show_deleted') == '1'

    valid_roles = dict(User.ROLE_CHOICES)
    per_page = 20
    all_users = list(User.objects.all())
    visible_users = [u for u in all_users if not u.is_deleted]
    stats = {
        'total': len(visible_users),
        'active': sum(1 for u in visible_users if u.is_active),
        'inactive': sum(1 for u in visible_users if not u.is_active),
        'marketing': sum(1 for u in visible_users if u.role == 'MARKETING'),
        'superadmin': sum(1 for u in visible_users if u.role == 'SUPERADMIN'),
        'customer': sum(1 for u in visible_users if u.role == 'CUSTOMER'),
    }

    users_list = list(all_users)

    if not show_deleted:
        users_list = [u for u in users_list if not u.is_deleted]

    if role_filter in valid_roles:
        users_list = [u for u in users_list if u.role == role_filter]

    if status_filter == 'ACTIVE':
        users_list = [u for u in users_list if u.is_active]
    elif status_filter == 'INACTIVE':
        users_list = [u for u in users_list if not u.is_active]

    if search_query:
        lowered = search_query.lower()
        def matches(user):
            values = [
                user.first_name or '',
                user.last_name or '',
                user.email or '',
                user.employee_id or '',
            ]
            return any(lowered in (value.lower()) for value in values if value)
        users_list = [u for u in users_list if matches(u)]

    users_list.sort(key=lambda u: u.date_joined or timezone.now(), reverse=True)

    paginator = Paginator(users_list, per_page)
    page_obj = paginator.get_page(request.GET.get('page'))
    params = request.GET.copy()
    if 'page' in params:
        params.pop('page')
    pagination_query = params.urlencode()
    pagination_base = f'?{pagination_query}&' if pagination_query else '?'
    filter_query_params = request.GET.copy()
    for key in ['page', 'edit']:
        filter_query_params.pop(key, None)
    filter_query = filter_query_params.urlencode()

    def build_card_url(**overrides):
        card_params = filter_query_params.copy()
        card_params.pop('role', None)
        card_params.pop('status', None)
        for key, value in overrides.items():
            if value:
                card_params[key] = value
            else:
                card_params.pop(key, None)
        query = card_params.urlencode()
        return f'?{query}' if query else '?'

    card_urls = {
        'total': build_card_url(),
        'active': build_card_url(status='ACTIVE'),
        'inactive': build_card_url(status='INACTIVE'),
        'marketing': build_card_url(role='MARKETING'),
        'superadmin': build_card_url(role='SUPERADMIN'),
        'customer': build_card_url(role='CUSTOMER'),
    }
    card_active = {
        'total': not role_filter and not status_filter,
        'active': status_filter == 'ACTIVE',
        'inactive': status_filter == 'INACTIVE',
        'marketing': role_filter == 'MARKETING',
        'superadmin': role_filter == 'SUPERADMIN',
        'customer': role_filter == 'CUSTOMER',
    }

    create_form = UserCreateForm()
    edit_form = None
    editing_user = None
    show_create_modal = False
    show_edit_modal = False
    if request.method != 'POST':
        edit_id = request.GET.get('edit')
        if edit_id:
            editing_user = get_object_or_404(User, pk=edit_id)
            edit_form = UserUpdateForm(instance=editing_user)
            show_edit_modal = True

    if request.method == 'POST':
        form_type = request.POST.get('form_type', 'create')
        if form_type == 'create':
            create_form = UserCreateForm(request.POST)
            if create_form.is_valid():
                new_user = create_form.save()
                new_user.approved_by = request.user
                new_user.approved_at = timezone.now()
                new_user.save()
                password_value = create_form.plaintext_password
                messages.success(
                    request,
                    f'User {new_user.get_full_name()} created successfully. '
                    f'Temporary password: {password_value}'
                )
                return redirect('superadmin:user_management')
            show_create_modal = True
        elif form_type == 'update':
            user_id = request.POST.get('user_id')
            editing_user = get_object_or_404(User, pk=user_id)
            edit_form = UserUpdateForm(request.POST, instance=editing_user)
            if edit_form.is_valid():
                desired_role = edit_form.cleaned_data.get('role')
                desired_active = edit_form.cleaned_data.get('is_active')
                if editing_user.role == 'SUPERADMIN' and (desired_role != 'SUPERADMIN' or not desired_active):
                    if not _has_active_superadmin(exclude_user=editing_user):
                        edit_form.add_error(
                            None,
                            'At least one active Super Admin must remain.'
                        )
                if not edit_form.errors:
                    updated_user = edit_form.save()
                    password_note = ''
                    if edit_form.cleaned_data.get('reset_password'):
                        password_note = f' New password: {edit_form.plaintext_password}'
                    messages.success(
                        request,
                        f'User {updated_user.get_full_name()} updated successfully.{password_note}'
                    )
                    return redirect('superadmin:user_management')
            show_edit_modal = True

    context = {
        'create_form': create_form,
        'edit_form': edit_form,
        'editing_user': editing_user,
        'filters': {
            'search': search_query,
            'role': role_filter,
            'status': status_filter,
            'show_deleted': show_deleted,
        },
        'page_obj': page_obj,
        'pagination_base': pagination_base,
        'total_users': len(users_list),
        'stats': stats,
        'per_page': per_page,
        'show_create_modal': show_create_modal,
        'show_edit_modal': show_edit_modal,
        'filter_query': filter_query,
        'card_urls': card_urls,
        'card_active': card_active,
        'role_choices': User.ROLE_CHOICES,
    }
    return render(request, 'superadmin/user_management.html', context)


@login_required
@superadmin_required
@require_POST
def user_toggle_status(request, pk):
    """Activate or deactivate a user."""
    user = get_object_or_404(User, pk=pk)
    if user.is_deleted:
        messages.error(request, 'Cannot change status of a deleted user.')
        return redirect('superadmin:user_management')
    if user.role == 'SUPERADMIN' and user.is_active:
        if not _has_active_superadmin(exclude_user=user):
            messages.error(request, 'At least one active Super Admin must remain.')
            return redirect('superadmin:user_management')
    user.is_active = not user.is_active
    user.save(update_fields=['is_active'])
    state = 'activated' if user.is_active else 'deactivated'
    messages.success(request, f'User {user.get_full_name()} {state}.')
    return redirect('superadmin:user_management')


@login_required
@superadmin_required
@require_POST
def user_toggle_role(request, pk):
    """Toggle or update a user's role."""
    user = get_object_or_404(User, pk=pk)
    if user.is_deleted:
        messages.error(request, 'Cannot change role of a deleted user.')
        return redirect('superadmin:user_management')
    if getattr(user, 'role_locked', False):
        messages.error(request, 'Role is locked after approval and cannot be changed.')
        return redirect('superadmin:user_management')
    target_role = request.POST.get('target_role')
    valid_roles = dict(User.ROLE_CHOICES).keys()
    if target_role not in valid_roles:
        target_role = 'SUPERADMIN' if user.role == 'MARKETING' else 'MARKETING'
    if user.role == 'SUPERADMIN' and target_role != 'SUPERADMIN':
        if not _has_active_superadmin(exclude_user=user):
            messages.error(request, 'At least one active Super Admin must remain.')
            return redirect('superadmin:user_management')
    user.role = target_role
    user.is_staff = target_role == 'SUPERADMIN'
    user.save(update_fields=['role', 'is_staff'])
    messages.success(request, f'{user.get_full_name()} is now {user.get_role_display()}.')
    return redirect('superadmin:user_management')


@login_required
@superadmin_required
@require_POST
def user_soft_delete(request, pk):
    """Soft delete a user instead of hard deleting."""
    user = get_object_or_404(User, pk=pk)
    if user.is_deleted:
        messages.info(request, 'User is already archived.')
        return redirect('superadmin:user_management')
    if user.role == 'SUPERADMIN':
        if not _has_active_superadmin(exclude_user=user):
            messages.error(request, 'At least one active Super Admin must remain.')
            return redirect('superadmin:user_management')
    user.is_deleted = True
    user.is_active = False
    user.save(update_fields=['is_deleted', 'is_active'])
    messages.success(request, f'User {user.get_full_name()} has been archived.')
    return redirect('superadmin:user_management')
@login_required
@superadmin_required
def profile_view(request):
    """SuperAdmin profile with editable fields"""
    if request.method == 'POST':
        user = request.user
        profile, _ = Profile.objects.get_or_create(user=user)

        # SuperAdmin can update their own details directly
        user.first_name = request.POST.get('first_name', user.first_name)
        user.last_name = request.POST.get('last_name', user.last_name)
        upload = request.FILES.get('profile_picture')
        if upload:
            profile.profile_picture = upload
            profile.save()

        # For email and WhatsApp, require notes
        new_email = request.POST.get('email')
        new_whatsapp = request.POST.get('whatsapp_no')
        notes = request.POST.get('notes', '')

        if new_email and new_email != user.email:
            if not notes:
                messages.error(request, 'Notes are required for email change.')
            else:
                user.email = new_email
                log_action(request.user, 'UPDATE', user, 
                          f'Changed email to {new_email}. Notes: {notes}')

        if new_whatsapp and new_whatsapp != user.whatsapp_no:
            if not notes:
                messages.error(request, 'Notes are required for WhatsApp number change.')
            else:
                user.whatsapp_no = new_whatsapp
                log_action(request.user, 'UPDATE', user, 
                          f'Changed WhatsApp to {new_whatsapp}. Notes: {notes}')

        user.last_qualification = request.POST.get('last_qualification', user.last_qualification)
        user.save()

        messages.success(request, 'Profile updated successfully!')
        return redirect('superadmin:profile')

    return render(request, 'superadmin/profile.html', {'user': request.user})
@login_required
@superadmin_required
def approve_job(request, job_id):
    """Approve a job (after all AI content is approved)"""
    job = get_object_or_404(Job, id=job_id)

    # Check if all required components are approved
    checks = []
    try:
        if not job.full_content.is_approved:
            checks.append('Full Content')
    except:
        checks.append('Full Content (not generated)')

    if checks:
        messages.error(request, f'Cannot approve job. Missing: {", ".join(checks)}')
        return redirect('superadmin:new_jobs')

    job.status = 'APPROVED'
    job.approved_by = request.user
    job.approved_at = timezone.now()
    job.save()
    notify_marketing_job_approved(job)

    log_action(request.user, 'APPROVE', job, f'Approved job {job.job_id}')

    messages.success(request, f'Job {job.job_id} approved successfully!')
    return redirect('superadmin:new_jobs')
@login_required
@superadmin_required
def user_approvals(request):
    """User approval page - redirects to approvals app"""
    return redirect('approvals:user_approval_list')
@login_required
@superadmin_required
def profile_update_requests(request):
    """Profile update requests page - redirects to approvals app"""
    return redirect('approvals:profile_update_approval_list')
@login_required
@superadmin_required
def profile(request):
    """SuperAdmin profile page"""
    return redirect('profiles:profile_view')
@login_required
@superadmin_required
def job_detail(request, job_id):
    """View detailed job information"""
    job = get_object_or_404(Job, job_id=job_id)
 # Changed from job_id=job_id to id=job_id
    attachments = job.attachments.all()

    # Get all AI content
    ai_content = {
        'summary': getattr(job, 'summary', None),
        'structure': getattr(job, 'structure', None),  # Changed from 'job_structure'
        'content': getattr(job, 'content', None),  # Changed from 'generated_content'
        'references': getattr(job, 'references', None),
        'plagiarism': getattr(job, 'plag_report', None),  # Changed from 'plagiarism_report'
        'ai_report': getattr(job, 'ai_report', None),
        'full_content': getattr(job, 'full_content', None),
    }

    # Check what exists and is approved
    has_summary = ai_content['summary'] is not None
    has_structure = ai_content['structure'] is not None
    has_content = ai_content['content'] is not None
    has_references = ai_content['references'] is not None
    has_full_content = ai_content['full_content'] is not None
    has_plag_report = ai_content['plagiarism'] is not None
    has_ai_report = ai_content['ai_report'] is not None

    summary_approved = ai_content['summary'].is_approved if has_summary else False
    structure_approved = ai_content['structure'].is_approved if has_structure else False
    content_approved = ai_content['content'].is_approved if has_content else False
    references_approved = ai_content['references'].is_approved if has_references else False
    full_content_approved = ai_content['full_content'].is_approved if has_full_content else False

    # Log the action
    log_action(
        request.user,
        'VIEW',
        job,
        f'SuperAdmin viewed job: {job.job_id}',
        request=request,
    )

    reworks = list(JobReworkRequest.objects.filter(job=job).select_related('requested_by', 'handled_by').order_by('-created_at'))

    context = {
        'job': job,
        'ai_content': ai_content,
        'attachments': attachments,
        'has_summary': has_summary,
        'has_structure': has_structure,
        'has_content': has_content,
        'has_references': has_references,
        'has_full_content': has_full_content,
        'has_plag_report': has_plag_report,
        'has_ai_report': has_ai_report,
        'summary_approved': summary_approved,
        'structure_approved': structure_approved,
        'content_approved': content_approved,
        'references_approved': references_approved,
        'full_content_approved': full_content_approved,
        'reworks': reworks,
    }

    return render(request, 'superadmin/job_detail.html', context)
@login_required
@superadmin_required
def approve_all_job_content(request, job_id):
    """Approve all AI content for a job at once"""
    job = get_object_or_404(Job, job_id=job_id)

    approved_count = 0
    content_types = [
        ('job_summary', 'Job Summary'),
        ('job_structure', 'Job Structure'),
        ('generated_content', 'Generated Content'),
        ('references', 'References'),
        ('plagiarism_report', 'Plagiarism Report'),
        ('ai_report', 'AI Report'),
        ('full_content', 'Full Content'),
    ]

    for attr_name, display_name in content_types:
        if hasattr(job, attr_name):
            content_obj = getattr(job, attr_name)
            if not content_obj.is_approved:
                content_obj.is_approved = True
                content_obj.approved_by = request.user
                content_obj.approved_at = timezone.now()
                content_obj.save()
                approved_count += 1

    # Approve the job itself
    if not job.is_approved:
        job.is_approved = True
        job.approved_by = request.user
        job.approved_at = timezone.now()
        job.status = 'APPROVED'
        job.save()

    # Log the action
    log_action(
        user=request.user,
        action_type='AI_APPROVAL',
        description=f'Approved all content for job {job.job_id} ({approved_count} items)',
        target_model='Job',
        target_id=str(job.id)
    )

    messages.success(request, f'Approved {approved_count} content items for job {job.job_id}!')
    return redirect('superadmin:new_jobs')


@login_required
@superadmin_required
def settings_view(request):
    """Control panel for global defaults managed only by Super Admin."""
    settings_obj = SystemSettings.get_solo()
    form = SystemSettingsForm(instance=settings_obj)
    updated_fields = []

    if request.method == 'POST':
        form = SystemSettingsForm(request.POST, instance=settings_obj)
        if form.is_valid():
            before = {field: getattr(settings_obj, field) for field in form.fields}
            settings_obj = form.save()
            for field in form.fields:
                old = before[field]
                new = getattr(settings_obj, field)
                if old != new:
                    updated_fields.append(f'{field.replace("_", " ").title()}: {old} → {new}')
            if updated_fields:
                log_action(
                    request.user,
                    'UPDATE',
                    settings_obj,
                    f'Updated settings: {"; ".join(updated_fields)}',
                    request=request,
                )
            messages.success(request, 'Settings updated successfully.')
            return redirect('superadmin:settings')

    context = {
        'form': form,
        'settings_obj': settings_obj,
    }
    return render(request, 'superadmin/settings.html', context)


@login_required
@superadmin_required
def content_management_view(request):
    """Manage content access mode per marketing user."""
    marketing_users = []
    try:
        marketing_users = list(
            User.objects.filter(role__iexact='MARKETING', is_deleted=False).order_by('first_name', 'last_name')
        )
    except Exception:
        try:
            # Fallback: pull all users and filter in Python to avoid Djongo SQL issues
            marketing_users = [u for u in User.objects.all() if getattr(u, 'role', '').upper() == 'MARKETING' and not getattr(u, 'is_deleted', False)]
        except Exception:
            marketing_users = []

    if request.method == 'POST':
        target_id = request.POST.get('user_id')
        mode = request.POST.get('mode')
        valid_modes = dict(ContentAccessSetting.MODE_CHOICES).keys()
        if mode not in valid_modes:
            messages.error(request, 'Invalid mode selected.')
            return redirect('superadmin:content_management')
        user = None
        if marketing_users:
            user = next((u for u in marketing_users if str(u.pk) == str(target_id)), None)
        if not user:
            try:
                user = User.objects.filter(pk=target_id).first()
                if user and getattr(user, 'role', '').upper() != 'MARKETING':
                    user = None
            except Exception:
                user = None
        if not user:
            messages.error(request, 'User not found or unavailable.')
            return redirect('superadmin:content_management')
        try:
            setting = ContentAccessSetting.objects.filter(marketing_user=user).first()
            if not setting:
                setting = ContentAccessSetting(marketing_user=user, mode=mode)
                setting.save()
            else:
                setting.mode = mode
                setting.save(update_fields=['mode'])
            messages.success(request, f'Content access updated for {user.get_full_name()}')
        except Exception:
            messages.error(request, 'Database error while updating content access. Please ensure migrations are applied.')
        return redirect('superadmin:content_management')

    rows = []
    for m_user in marketing_users:
        setting = ContentAccessSetting.for_user(m_user)
        rows.append({
            'user': m_user,
            'setting': setting,
        })

    context = {
        'rows': rows,
        'mode_choices': ContentAccessSetting.MODE_CHOICES,
    }
    return render(request, 'superadmin/content_management.html', context)


@login_required
@superadmin_required
def menu_management_view(request):
    """
    Manage sidebar menu ordering per role.
    Welcome is fixed at position 0 for every role.
    """
    roles = [
        (MenuItem.ROLE_SUPERADMIN, "Super Admin"),
        (MenuItem.ROLE_MARKETING, "Marketing"),
    ]

    for role, _ in roles:
        MenuItem.ensure_defaults(role)

    if request.method == 'POST':
        role = request.POST.get('role')
        if role not in dict(roles):
            messages.error(request, 'Invalid role selected.')
            return redirect('superadmin:menu_management')

        items = MenuItem.objects.filter(role=role)
        for item in items:
            pos_key = f'pos_{item.id}'
            active_key = f'active_{item.id}'
            if item.is_fixed:
                item.position = 0
                item.is_active = True
                item.save(update_fields=['position', 'is_active'])
                continue

            try:
                new_pos = int(request.POST.get(pos_key, item.position))
            except (TypeError, ValueError):
                new_pos = item.position
            item.position = max(1, new_pos)
            item.is_active = bool(request.POST.get(active_key))
            item.save(update_fields=['position', 'is_active'])

        messages.success(request, f'Menu updated for {role.title()}.')
        return redirect('superadmin:menu_management')

    items_by_role = {
        role: MenuItem.objects.filter(role=role).order_by('position', 'label')
        for role, _ in roles
    }

    context = {
        'roles': roles,
        'items_by_role': items_by_role,
    }
    return render(request, 'superadmin/menu_management.html', context)


@login_required
@superadmin_required
def activity_tracking_view(request):
    """Detailed audit trail for super admin oversight."""
    raw_filters = {
        'search': (request.GET.get('search') or '').strip(),
        'role': (request.GET.get('role') or '').strip().upper(),
        'action_type': (request.GET.get('action_type') or '').strip().upper(),
        'target_type': (request.GET.get('target_type') or '').strip().lower(),
        'target_id': (request.GET.get('target_id') or '').strip(),
        'user_query': (request.GET.get('user') or '').strip(),
        'date_from': (request.GET.get('date_from') or '').strip(),
        'date_to': (request.GET.get('date_to') or '').strip(),
        'card': (request.GET.get('card') or '').strip(),
    }
    filters = {
        'search': raw_filters['search'].lower(),
        'role': raw_filters['role'],
        'action_type': raw_filters['action_type'],
        'target_type': raw_filters['target_type'],
        'target_id': raw_filters['target_id'].lower(),
        'user_query': raw_filters['user_query'].lower(),
        'date_from': _parse_date_param(raw_filters['date_from']),
        'date_to': _parse_date_param(raw_filters['date_to']),
    }

    logs_qs = ActionLog.objects.select_related('user').order_by('-timestamp')
    logs = list(logs_qs)
    role_labels = {code: label for code, label in User.ROLE_CHOICES}

    action_counts = {}
    target_types = set()
    processed_logs = []

    for log in logs:
        action_counts[log.action_type] = action_counts.get(log.action_type, 0) + 1
        raw_target = log.target_model or (log.content_type.model if log.content_type else '')
        target_slug = (raw_target or '').replace('_', ' ').strip()
        target_label = target_slug.title() if target_slug else ''
        if target_label:
            target_types.add(target_label)
        role_code = getattr(log.user, 'role', '') or ''
        role_display = role_labels.get(role_code, role_code.title()) if role_code else 'System'
        if not role_code and log.user_email:
            role_display = 'External'
        actor_name = log.user_name or (log.user.get_full_name() if log.user else '') or log.user_email or 'System'
        target_identifier = log.target_id or log.object_id or ''
        timestamp = log.timestamp
        if timezone.is_naive(timestamp):
            timestamp_local = timestamp
        else:
            timestamp_local = timezone.localtime(timestamp)
        processed_logs.append({
            'instance': log,
            'action_code': log.action_type,
            'action_label': log.get_action_type_display(),
            'actor': actor_name,
            'role_code': role_code.upper(),
            'role_label': role_display,
            'target_label': target_label or 'General',
            'target_key': (target_label or '').lower(),
            'target_id': target_identifier,
            'description': log.description,
            'ip_address': log.ip_address or '',
            'user_agent': log.user_agent or '',
            'timestamp': timestamp_local,
            'timestamp_str': timestamp_local.strftime('%b %d, %Y %H:%M'),
        })

    def _matches_filters(entry):
        if filters['role'] and entry['role_code'] != filters['role']:
            return False
        if filters['action_type'] and entry['action_code'] != filters['action_type']:
            return False
        if filters['target_type'] and entry['target_key'] != filters['target_type']:
            return False
        if filters['target_id']:
            if filters['target_id'] not in (entry['target_id'] or '').lower():
                return False
        if filters['user_query']:
            actor_blob = f"{entry['actor']} {entry['role_label']}".lower()
            if filters['user_query'] not in actor_blob:
                return False
        if filters['search']:
            haystack = " ".join([
                entry['actor'],
                entry['role_label'],
                entry['action_label'],
                entry['target_label'],
                entry['target_id'] or '',
                entry['description'] or '',
            ]).lower()
            if filters['search'] not in haystack:
                return False
        log_date = entry['timestamp'].date()
        if filters['date_from'] and log_date < filters['date_from']:
            return False
        if filters['date_to'] and log_date > filters['date_to']:
            return False
        return True

    filtered_logs = [entry for entry in processed_logs if _matches_filters(entry)]
    page_obj, pagination_base = _paginate_items(request, filtered_logs, per_page=20)

    base_params = request.GET.copy()
    base_params.pop('page', None)

    def build_card_url(card_key, action_type):
        params = base_params.copy()
        params.pop('card', None)
        if action_type:
            params['action_type'] = action_type
            params['card'] = card_key
        else:
            params.pop('action_type', None)
        query = params.urlencode()
        return f'?{query}' if query else '?'

    card_definitions = [
        ('total', 'Total Activities', None, len(logs)),
        ('create', 'Creations', 'CREATE', action_counts.get('CREATE', 0)),
        ('update', 'Updates', 'UPDATE', action_counts.get('UPDATE', 0)),
        ('approve', 'Approvals', 'APPROVE', action_counts.get('APPROVE', 0)),
        ('reject', 'Rejections', 'REJECT', action_counts.get('REJECT', 0)),
    ]
    active_card = raw_filters['card']
    card_stats = []
    for key, label, action_type, count in card_definitions:
        url = build_card_url(key, action_type)
        is_active = active_card == key
        if key == 'total' and (not active_card) and not filters['action_type']:
            is_active = True
        card_stats.append({
            'key': key,
            'label': label,
            'count': count,
            'url': url,
            'active': is_active,
        })

    target_choices = sorted(
        [{'value': label.lower(), 'label': label} for label in target_types],
        key=lambda item: item['label']
    )

    context = {
        'filters': raw_filters,
        'page_obj': page_obj,
        'pagination_base': pagination_base,
        'logs': page_obj.object_list,
        'action_choices': ActionLog.ACTION_TYPES,
        'role_choices': User.ROLE_CHOICES,
        'target_choices': target_choices,
        'card_stats': card_stats,
        'total_filtered': len(filtered_logs),
        'total_all': len(logs),
        'per_page': 20,
    }
    return render(request, 'superadmin/activity_tracking.html', context)


@login_required
@superadmin_required
def activity_analytics_view(request):
    """
    Aggregate active/idle viewing time captured from the JS tracker.
    Super Admin only.
    """
    raw_filters = {
        'user': (request.GET.get('user') or '').strip(),
        'path': (request.GET.get('path') or '').strip(),
        'session': (request.GET.get('session') or '').strip(),
        'date_from': (request.GET.get('date_from') or '').strip(),
        'date_to': (request.GET.get('date_to') or '').strip(),
        'unit': (request.GET.get('unit') or 'minutes').strip().lower(),
    }
    date_from = _parse_date_param(raw_filters['date_from'])
    date_to = _parse_date_param(raw_filters['date_to'])
    unit = raw_filters['unit'] if raw_filters['unit'] in ('seconds', 'minutes', 'hours') else 'minutes'
    unit_label = unit

    visits_qs = PageVisit.objects.select_related('user').order_by('-started_at')
    visits = list(visits_qs)
    filtered = []

    def _match_user(visit):
        if not raw_filters['user']:
            return True
        query = raw_filters['user'].lower()
        user = visit.user
        name_blob = ''
        email = ''
        user_id = ''
        if user:
            name_blob = f"{user.get_full_name()} {getattr(user, 'role', '')}".lower()
            email = (user.email or '').lower()
            user_id = str(user.pk)
        return any(
            query in needle
            for needle in [name_blob, email, user_id]
        )

    for visit in visits:
        start_local = visit.started_at
        end_local = visit.ended_at
        if start_local and timezone.is_aware(start_local):
            start_local = timezone.localtime(start_local)
        if end_local and timezone.is_aware(end_local):
            end_local = timezone.localtime(end_local)
        visit.start_local = start_local
        visit.end_local = end_local
        visit_date = (start_local or visit.started_at or timezone.now()).date()

        if date_from and visit_date < date_from:
            continue
        if date_to and visit_date > date_to:
            continue
        if raw_filters['path'] and raw_filters['path'].lower() not in (visit.page_path or '').lower():
            continue
        if raw_filters['session'] and raw_filters['session'] not in (visit.session_id or ''):
            continue
        if not _match_user(visit):
            continue
        filtered.append(visit)

    total_active = sum(getattr(v, 'active_seconds', 0) or 0 for v in filtered)
    total_idle = sum(getattr(v, 'idle_seconds', 0) or 0 for v in filtered)
    visit_count = len(filtered)
    avg_active = total_active / visit_count if visit_count else 0
    avg_idle = total_idle / visit_count if visit_count else 0
    total_time = total_active + total_idle
    idle_ratio = (total_idle / total_time * 100) if total_time else 0
    active_ratio = 100 - idle_ratio if total_time else 0

    per_user = {}
    per_page = {}
    per_day = {}

    visit_rows = []
    for visit in filtered:
        user_key = visit.user_id or 'anonymous'
        user_obj = visit.user
        user_record = per_user.setdefault(user_key, {
            'user': user_obj,
            'name': user_obj.get_full_name() if user_obj else 'Deleted User',
            'email': getattr(user_obj, 'email', ''),
            'active': 0,
            'idle': 0,
            'visits': 0,
        })
        user_record['active'] += visit.active_seconds or 0
        user_record['idle'] += visit.idle_seconds or 0
        user_record['visits'] += 1

        page_key = visit.page_path or 'Unknown'
        page_record = per_page.setdefault(page_key, {
            'path': page_key,
            'name': visit.page_name or '',
            'active': 0,
            'idle': 0,
            'visits': 0,
        })
        page_record['active'] += visit.active_seconds or 0
        page_record['idle'] += visit.idle_seconds or 0
        page_record['visits'] += 1

        day_key = visit_date = visit.start_local.date() if visit.start_local else (visit.started_at.date() if visit.started_at else timezone.now().date())
        day_record = per_day.setdefault(day_key, {'active': 0, 'idle': 0, 'visits': 0})
        day_record['active'] += visit.active_seconds or 0
        day_record['idle'] += visit.idle_seconds or 0
        day_record['visits'] += 1

        visit_rows.append({
            'user_name': user_record['name'],
            'user_email': user_record['email'],
            'path': page_key,
            'page_name': visit.page_name or '',
            'active_seconds': visit.active_seconds or 0,
            'idle_seconds': visit.idle_seconds or 0,
            'active_display': _convert_seconds(visit.active_seconds or 0, unit_label),
            'idle_display': _convert_seconds(visit.idle_seconds or 0, unit_label),
            'active_human': _format_duration(visit.active_seconds or 0),
            'idle_human': _format_duration(visit.idle_seconds or 0),
            'started_at': visit.start_local or visit.started_at,
            'ended_at': visit.end_local or visit.ended_at,
        })

    visit_rows_sorted = sorted(visit_rows, key=lambda x: x['started_at'] or timezone.now(), reverse=True)
    visit_page_obj, visit_pagination_base = _paginate_items(
        request,
        visit_rows_sorted,
        page_param='visits_page',
        per_page=20,
    )

    user_rows_all = sorted(per_user.values(), key=lambda x: x['active'], reverse=True)
    page_rows_all = sorted(per_page.values(), key=lambda x: x['active'], reverse=True)
    top_pages = page_rows_all[:10]
    daily_rows_all = sorted(per_day.items(), key=lambda item: item[0])

    user_page_obj, user_pagination_base = _paginate_items(
        request,
        user_rows_all,
        page_param='users_page',
        per_page=10,
    )
    page_page_obj, page_pagination_base = _paginate_items(
        request,
        page_rows_all,
        page_param='pages_page',
        per_page=10,
    )
    daily_page_obj, daily_pagination_base = _paginate_items(
        request,
        [
            {
                'date': day.isoformat(),
                'active': values['active'],
                'idle': values['idle'],
                'visits': values['visits'],
                'active_display': _convert_seconds(values['active'], unit_label),
                'idle_display': _convert_seconds(values['idle'], unit_label),
            }
            for day, values in daily_rows_all
        ],
        page_param='days_page',
        per_page=10,
    )

    # Chart data (based on filtered visits)
    chart_visits = filtered
    marketing_only = chart_visits  # include all roles to surface complete database activity
    user_totals = {}
    page_totals = {}
    day_totals = {}
    page_visit_counts = {}
    session_lengths = []
    user_day_totals = {}
    heatmap_map = {}

    def _user_label(user):
        if not user:
            return 'Deleted User'
        name = user.get_full_name() or (user.email or 'Unknown')
        email = user.email or ''
        return f"{name}".strip() or email or 'Unknown'

    for visit in marketing_only:
        ulabel = _user_label(visit.user)
        page_label = visit.page_path or 'Unknown'
        start_dt = visit.start_local or visit.started_at or timezone.now()
        if timezone.is_aware(start_dt):
            start_dt = timezone.localtime(start_dt)
        day_key = start_dt.date()
        hour_key = start_dt.hour
        active = visit.active_seconds or 0
        idle = visit.idle_seconds or 0
        total = active + idle
        session_lengths.append(total)

        user_tot = user_totals.setdefault(ulabel, {'active': 0, 'idle': 0})
        user_tot['active'] += active
        user_tot['idle'] += idle

        page_tot = page_totals.setdefault(page_label, {'active': 0, 'idle': 0, 'visits': 0, 'name': visit.page_name or ''})
        page_tot['active'] += active
        page_tot['idle'] += idle
        page_tot['visits'] += 1

        day_tot = day_totals.setdefault(day_key, 0)
        day_totals[day_key] = day_tot + active

        page_visit_counts[page_label] = page_visit_counts.get(page_label, 0) + 1

        user_day = user_day_totals.setdefault(ulabel, {})
        user_day[day_key] = user_day.get(day_key, 0) + active

        heat_page = heatmap_map.setdefault(page_label, [0] * 24)
        if 0 <= hour_key < 24:
            heat_page[hour_key] += active

    user_total_labels = list(user_totals.keys())
    user_total_values = [_seconds_to_hours(user_totals[u]['active']) for u in user_total_labels]
    user_idle_values = [_seconds_to_hours(user_totals[u]['idle']) for u in user_total_labels]

    page_total_items = sorted(page_totals.items(), key=lambda kv: kv[1]['active'], reverse=True)
    page_total_labels = [k for k, _ in page_total_items]
    page_total_values = [_seconds_to_hours(v['active']) for _, v in page_total_items]
    page_total_top10_labels = page_total_labels[:10]
    page_total_top10_values = page_total_values[:10]

    day_items = sorted(day_totals.items(), key=lambda kv: kv[0])
    day_labels = [d.isoformat() for d, _ in day_items]
    day_values = [_seconds_to_hours(v) for _, v in day_items]

    user_trend_labels = day_labels
    user_trend_datasets = []
    for ulabel, daymap in user_day_totals.items():
        data = []
        for d in user_trend_labels:
            date_obj = datetime.fromisoformat(d).date()
            data.append(_seconds_to_hours(daymap.get(date_obj, 0)))
        user_trend_datasets.append({
            'label': ulabel,
            'data': data,
        })

    avg_time_labels = []
    avg_time_values = []
    visit_count_labels = []
    visit_count_values = []
    for page_label, data in page_totals.items():
        if data['visits']:
            avg_time_labels.append(page_label)
            avg_time_values.append(round((data['active'] / data['visits']) / 60.0, 2))
        visit_count_labels.append(page_label)
        visit_count_values.append(data['visits'])

    heatmap_pages_sorted = sorted(page_totals.items(), key=lambda kv: kv[1]['active'], reverse=True)[:8]
    heatmap_pages = [k for k, _ in heatmap_pages_sorted]
    heatmap_matrix = [heatmap_map.get(page, [0] * 24) for page in heatmap_pages]
    heatmap_hours = list(range(24))

    buckets = [
        (0, 60, '0-1 min'),
        (60, 300, '1-5 min'),
        (300, 900, '5-15 min'),
        (900, 1800, '15-30 min'),
        (1800, 3600, '30-60 min'),
        (3600, 7200, '1-2 hrs'),
        (7200, None, '2 hrs+'),
    ]
    bucket_labels = [b[2] for b in buckets]
    bucket_counts = [0] * len(buckets)
    for length in session_lengths:
        for idx, (low, high, _) in enumerate(buckets):
            if length >= low and (high is None or length < high):
                bucket_counts[idx] += 1
                break

    chart_data = {
        'user_total': {'labels': user_total_labels, 'active_hours': user_total_values},
        'page_total': {'labels': page_total_labels, 'active_hours': page_total_values},
        'page_total_top10': {'labels': page_total_top10_labels, 'active_hours': page_total_top10_values},
        'daily_trend': {'labels': day_labels, 'active_hours': day_values},
        'user_trend': {'labels': user_trend_labels, 'datasets': user_trend_datasets},
        'avg_time': {'labels': avg_time_labels, 'avg_minutes': avg_time_values},
        'visit_counts': {'labels': visit_count_labels, 'counts': visit_count_values},
        'active_idle_user': {'labels': user_total_labels, 'active_hours': user_total_values, 'idle_hours': user_idle_values},
        'heatmap': {'pages': heatmap_pages, 'hours': heatmap_hours, 'matrix': heatmap_matrix},
        'session_hist': {'labels': bucket_labels, 'counts': bucket_counts},
    }

    context = {
        'filters': raw_filters,
        'unit': unit_label,
        'total_active': total_active,
        'total_idle': total_idle,
        'total_active_display': _convert_seconds(total_active, unit_label),
        'total_idle_display': _convert_seconds(total_idle, unit_label),
        'avg_active_display': _convert_seconds(avg_active, unit_label),
        'avg_idle_display': _convert_seconds(avg_idle, unit_label),
        'active_ratio': round(active_ratio, 1),
        'idle_ratio': round(idle_ratio, 1),
        'visit_count': visit_count,
        'user_page_obj': user_page_obj,
        'user_pagination_base': user_pagination_base,
        'user_total': len(user_rows_all),
        'user_rows': [
            {**row,
             'active_display': _convert_seconds(row['active'], unit_label),
             'idle_display': _convert_seconds(row['idle'], unit_label),
             'active_human': _format_duration(row['active']),
             'idle_human': _format_duration(row['idle']),
            }
            for row in user_page_obj.object_list
        ],
        'page_page_obj': page_page_obj,
        'page_pagination_base': page_pagination_base,
        'page_total': len(page_rows_all),
        'page_rows': [
            {**row,
             'active_display': _convert_seconds(row['active'], unit_label),
             'idle_display': _convert_seconds(row['idle'], unit_label),
             'avg_active_display': _convert_seconds(row['active'] / row['visits'], unit_label) if row['visits'] else 0,
             'active_human': _format_duration(row['active']),
            }
            for row in page_page_obj.object_list
        ],
        'top_pages': [
            {**row,
             'active_display': _convert_seconds(row['active'], unit_label),
             'active_human': _format_duration(row['active']),
            }
            for row in top_pages
        ],
        'daily_page_obj': daily_page_obj,
        'daily_pagination_base': daily_pagination_base,
        'daily_total': len(daily_rows_all),
        'unit_suffix': unit_label,
        'has_data': bool(filtered),
        'visit_page_obj': visit_page_obj,
        'visit_pagination_base': visit_pagination_base,
        'visit_total': len(visit_rows_sorted),
        'chart_data_json': json.dumps(chart_data),
    }
    return render(request, 'superadmin/activity_analytics.html', context)


@login_required
@superadmin_required
def error_management_view(request):
    """
    SuperAdmin-only Error Management hub (stub implementation).
    Designed to surface marketing-reported issues with page context, attachments, and status controls.
    """
    from .models import ErrorLog
    logs = ErrorLog.objects.all()[:50]
    return render(request, 'superadmin/error_management.html', {'logs': logs})


@login_required
@superadmin_required
def rework_list_view(request):
    status_filter = (request.GET.get('status') or '').upper()
    reworks = list(
        JobReworkRequest.objects.select_related('job', 'requested_by').order_by('-created_at')
    )
    total_count = len(reworks)
    completed_count = sum(1 for r in reworks if r.status == JobReworkRequest.STATUS_APPROVED)

    if status_filter:
        filtered = [r for r in reworks if r.status == status_filter]
    else:
        filtered = reworks

    page_obj, pagination_base = _paginate_items(request, filtered, per_page=20)

    params = request.GET.copy()
    params.pop('page', None)

    def build_card_url(target_status, card_key):
        card_params = params.copy()
        if target_status:
            card_params['status'] = target_status
            card_params['card'] = card_key
        else:
            card_params.pop('status', None)
            card_params.pop('card', None)
        query = card_params.urlencode()
        return f'?{query}' if query else '?'

    cards = [
        {
            'label': 'Total Reworks',
            'value': total_count,
            'url': build_card_url(None, 'all'),
            'active': not status_filter,
        },
        {
            'label': 'Completed Reworks',
            'value': completed_count,
            'url': build_card_url(JobReworkRequest.STATUS_APPROVED, 'completed'),
            'active': status_filter == JobReworkRequest.STATUS_APPROVED,
        },
    ]

    context = {
        'page_obj': page_obj,
        'pagination_base': pagination_base,
        'card_stats': cards,
        'total_count': total_count,
    }
    return render(request, 'superadmin/reworks.html', context)


@login_required
@superadmin_required
def rework_detail_view(request, pk):
    rework = get_object_or_404(
        JobReworkRequest.objects.select_related('job', 'requested_by', 'handled_by'),
        pk=pk,
    )
    generation, _ = ReworkGeneration.objects.get_or_create(rework=rework)
    job_full_content = getattr(rework.job, 'full_content', None)
    if not job_full_content:
        job_full_content = FullContent.objects.filter(job=rework.job).first()
    if request.method == 'POST' and request.POST.get('action') == 'complete':
        rework.status = JobReworkRequest.STATUS_APPROVED
        rework.handled_by = request.user
        rework.handled_at = timezone.now()
        provided_notes = (request.POST.get('response_notes') or '').strip()
        if provided_notes:
            rework.response_notes = provided_notes
        elif generation.rework_text:
            rework.response_notes = generation.rework_text
        rework.save()
        job = rework.job
        job.status = 'REWORK_COMPLETED'
        job.save(update_fields=['status'])
        notify_marketing_rework_completed(rework)
        log_action(
            request.user,
            'UPDATE',
            job,
            f'Marked rework complete for {job.job_id}',
            request=request,
        )
        messages.success(request, f'Rework for {job.job_id} marked as completed.')
        return redirect('superadmin:rework_list')

    return render(
        request,
        'superadmin/rework_detail.html',
        {
            'rework': rework,
            'full_content': job_full_content,
            'generation': generation,
            'rework_generation_json': json.dumps({
                'summary_text': generation.summary_text,
                'rework_text': generation.rework_text,
                'summary_status': generation.summary_status,
                'rework_status': generation.rework_status,
                'summary_regen_count': generation.summary_regen_count,
                'rework_regen_count': generation.rework_regen_count,
                'summary_limit': 3,
                'rework_limit': 3,
            }),
        },
    )


def _openai_generate(developer_prompt, user_payload):
    client = _get_openai_client()
    model = getattr(settings, 'OPENAI_REWORK_MODEL', 'gpt-4.1-mini')
    resp = client.responses.create(
        model=model,
        input=[
            {"role": "developer", "content": developer_prompt},
            {"role": "user", "content": user_payload},
        ],
        max_output_tokens=2000,
    )
    return getattr(resp, 'output_text', '') or ''


def _rework_payload_summary(rework):
    note = rework.reason or ''
    job = rework.job
    instructions = getattr(job, 'instruction', '')
    attachments = []
    for att in job.attachments.all():
        attachments.append(f"File: {att.filename} ({att.file_type}), size={att.file_size}")
    attachment_block = "\n".join(attachments) or "No attachments listed."
    return f"""
USER NOTE / INSTRUCTIONS:
{note}

JOB INSTRUCTION:
{instructions}

ATTACHMENTS (metadata only):
{attachment_block}
"""


def _rework_payload_content(rework, generation, full_content_text):
    return f"""
REWORK-JOB-SUMMARY:
{generation.summary_text or '[No summary generated yet]'}

FULL CONTENT TO REWORK:
{full_content_text or '[No full content available]'}
"""


def _get_generation_or_404(pk):
    rework = get_object_or_404(
        JobReworkRequest.objects.select_related('job', 'requested_by', 'handled_by'),
        pk=pk,
    )
    generation, _ = ReworkGeneration.objects.get_or_create(rework=rework)
    return rework, generation


@login_required
@superadmin_required
@require_POST
def api_generate_rework_summary(request, pk):
    rework, generation = _get_generation_or_404(pk)
    if generation.summary_regen_count >= 3:
        return JsonResponse({'error': 'Regeneration limit reached (3).'}, status=400)
    payload = _rework_payload_summary(rework)
    try:
        text = _openai_generate(REWORK_SUMMARY_PROMPT, payload)
    except Exception as exc:  # pragma: no cover - external
        return JsonResponse({'error': f'OpenAI error: {exc}'}, status=500)
    generation.summary_text = text or generation.summary_text
    generation.summary_status = 'GENERATED'
    generation.summary_regen_count = generation.summary_regen_count + 1
    generation.save()
    return JsonResponse({
        'summary_text': generation.summary_text,
        'summary_status': generation.summary_status,
        'summary_regen_count': generation.summary_regen_count,
    })


@login_required
@superadmin_required
@require_POST
def api_generate_rework_content(request, pk):
    rework, generation = _get_generation_or_404(pk)
    if generation.rework_regen_count >= 3:
        return JsonResponse({'error': 'Regeneration limit reached (3).'}, status=400)
    full_content = getattr(rework.job, 'full_content', None)
    full_text = getattr(full_content, 'content_with_citations', '') if full_content else ''
    payload = _rework_payload_content(rework, generation, full_text)
    try:
        text = _openai_generate(MAKE_REWORK_PROMPT, payload)
    except Exception as exc:  # pragma: no cover
        return JsonResponse({'error': f'OpenAI error: {exc}'}, status=500)
    generation.rework_text = text or generation.rework_text
    generation.rework_status = 'GENERATED'
    generation.rework_regen_count = generation.rework_regen_count + 1
    generation.save()
    return JsonResponse({
        'rework_text': generation.rework_text,
        'rework_status': generation.rework_status,
        'rework_regen_count': generation.rework_regen_count,
    })


@login_required
@superadmin_required
@require_POST
def api_approve_rework_summary(request, pk):
    _, generation = _get_generation_or_404(pk)
    generation.summary_status = 'APPROVED'
    generation.save(update_fields=['summary_status', 'updated_at'])
    return JsonResponse({'summary_status': generation.summary_status})


@login_required
@superadmin_required
@require_POST
def api_approve_rework_content(request, pk):
    rework, generation = _get_generation_or_404(pk)
    generation.rework_status = 'APPROVED'
    generation.save(update_fields=['rework_status', 'updated_at'])
    return JsonResponse({'rework_status': generation.rework_status})


# Customer management (SuperAdmin) - stub pages
@login_required
@superadmin_required
def customer_management(request):
    return render(request, 'superadmin/customers/management.html', {})


@login_required
@superadmin_required
def customer_accounts(request):
    customers = []
    try:
        customers = User.objects.filter(role='CUSTOMER')
    except Exception:
        try:
            customers = [u for u in User.objects.all() if getattr(u, 'role', '').upper() == 'CUSTOMER']
        except Exception:
            customers = []
    # ensure profiles
    for user in customers:
        prof = CustomerProfile.objects.filter(user=user).first()
        desired_code = getattr(user, 'customer_code', None)
        if not prof:
            try:
                prof = CustomerProfile(
                    user=user,
                    full_name=user.get_full_name(),
                    phone=getattr(user, 'whatsapp_no', '') or '',
                    customer_id=desired_code or None,
                )
                prof.joined_date = getattr(user, 'date_joined', timezone.now())
                if not prof.customer_id:
                    prof.generate_customer_id()
                prof.save()
            except Exception:
                pass
        if prof and not prof.customer_id:
            try:
                prof.customer_id = desired_code or prof.generate_customer_id()
                prof.save(update_fields=['customer_id'])
            except Exception:
                pass
        elif prof and desired_code and prof.customer_id != desired_code:
            try:
                prof.customer_id = desired_code
                prof.save(update_fields=['customer_id'])
            except Exception:
                pass
        if getattr(user, 'is_approved', False) and not getattr(user, 'employee_id', None):
            try:
                user.generate_employee_id()
                user.save(update_fields=['employee_id'])
            except Exception:
                pass

    # Filters
    status_filter = (request.GET.get('status') or '').lower()
    search = (request.GET.get('search') or '').strip().lower()
    date_from = _parse_date_param(request.GET.get('date_from'))
    date_to = _parse_date_param(request.GET.get('date_to'))

    # Ensure customer codes exist
    for c in customers:
        if getattr(c, 'role', '').upper() == 'CUSTOMER' and not getattr(c, 'customer_code', None):
            try:
                c.generate_customer_code()
                c.save(update_fields=['customer_code'])
            except Exception:
                pass

    total_customers = len(customers)

    def _status_counts(user_list):
        active = inactive = blocked = 0
        for user in user_list:
            prof = CustomerProfile.objects.filter(user=user).first()
            if prof and prof.status == CustomerProfile.STATUS_BLOCKED:
                blocked += 1
            elif prof and prof.status == CustomerProfile.STATUS_INACTIVE:
                inactive += 1
            elif getattr(user, 'is_active', False):
                active += 1
            else:
                inactive += 1
        return active, inactive, blocked

    total_active, total_inactive, total_blocked = _status_counts(customers)

    if status_filter == 'active':
        customers = [c for c in customers if CustomerProfile.objects.filter(user=c, status=CustomerProfile.STATUS_ACTIVE).exists() or (getattr(c, 'is_active', False) and not getattr(c, 'is_deleted', False))]
    elif status_filter == 'inactive':
        customers = [c for c in customers if CustomerProfile.objects.filter(user=c, status=CustomerProfile.STATUS_INACTIVE).exists() or (not getattr(c, 'is_active', False) and not getattr(c, 'is_deleted', False))]
    elif status_filter == 'blocked':
        customers = [c for c in customers if CustomerProfile.objects.filter(user=c, status=CustomerProfile.STATUS_BLOCKED).exists()]

    if search:
        customers = [
            c for c in customers
            if search in (getattr(c, 'employee_id', '') or '').lower()
            or search in (getattr(c, 'customer_code', '') or '').lower()
            or search in (getattr(getattr(c, 'customer_profile', None), 'customer_id', '') or '').lower()
            or search in (getattr(c, 'email', '') or '').lower()
            or search in (c.get_full_name() or '').lower()
        ]

    def _within_date(user):
        joined = getattr(user, 'date_joined', None)
        if not joined:
            return False
        joined_date = joined.date()
        if date_from and joined_date < date_from:
            return False
        if date_to and joined_date > date_to:
            return False
        return True
    if date_from or date_to:
        customers = [c for c in customers if _within_date(c)]
    # paginate
    rows = []
    user_ids = [u.id for u in customers]
    for user in customers:
        prof = CustomerProfile.objects.filter(user=user).first()
        wallet = CoinWallet.objects.filter(user=user).first()
        uid = user.id
        # Per-user aggregation for reliability (avoids Djongo group issues)
        try:
            txs = list(CoinTransaction.objects.filter(customer=user).values('txn_type', 'amount'))
        except Exception:
            txs = []
        total_credit = sum((t.get('amount') or 0) for t in txs if t.get('txn_type') == CoinTransaction.TYPE_CREDIT)
        total_debit = sum((t.get('amount') or 0) for t in txs if t.get('txn_type') == CoinTransaction.TYPE_DEBIT)
        txn_count = len(txs)
        try:
            ops_count = (
                JobCheckingSubmission.objects.filter(user=user).count()
                + StructureGenerationSubmission.objects.filter(user=user).count()
                + ContentGenerationSubmission.objects.filter(user=user).count()
            )
        except Exception:
            ops_count = 0
        try:
            ticket_count = CustomerTicket.objects.filter(user=user).count()
        except Exception:
            ticket_count = 0
        rows.append({
            'user': user,
            'profile': prof,
            'wallet': wallet,
            'agg_total_added': total_credit,
            'agg_total_spent': total_debit,
            'agg_total_ops': txn_count,
            'agg_ops': ops_count,
            'agg_tickets': ticket_count,
        })
    page_obj, pagination_base = _paginate_items(request, rows, page_param='page', per_page=20)

    action = request.GET.get('action')
    target_id = request.GET.get('user_id')
    if action in ('activate', 'deactivate', 'block', 'unblock') and target_id:
        for user in customers:
            if str(user.id) == str(target_id):
                prof = CustomerProfile.objects.filter(user=user).first()
                if action in ('activate', 'deactivate'):
                    user.is_active = (action == 'activate')
                    if prof:
                        prof.status = CustomerProfile.STATUS_ACTIVE if user.is_active else CustomerProfile.STATUS_INACTIVE
                else:
                    user.is_active = False if action == 'block' else True
                    if prof:
                        prof.is_blocked = (action == 'block')
                        prof.status = CustomerProfile.STATUS_BLOCKED if prof.is_blocked else CustomerProfile.STATUS_ACTIVE
                        prof.blocked_at = timezone.now() if prof.is_blocked else None
                try:
                    user.save(update_fields=['is_active'])
                    if prof:
                        prof.save()
                    msg = f'User {user.email} set to {action}.'
                    messages.success(request, msg)
                except Exception:
                    messages.error(request, 'Could not update user status. Please try again.')
                break

    context = {
        'page_obj': page_obj,
        'pagination_base': pagination_base,
        'customers': page_obj.object_list,
        'total_customers': total_customers,
        'total_active': total_active,
        'total_inactive': total_inactive,
        'total_blocked': total_blocked,
        'status_filter': status_filter,
        'search': search,
        'date_from': date_from,
        'date_to': date_to,
    }
    return render(request, 'superadmin/customers/accounts.html', context)


@login_required
@superadmin_required
def customer_wallets(request):
    success_message = None
    error_message = None
    from superadmin.models import SystemSettings, AdminWallet, CoinWallet, CoinTransaction, _generate_bigint_id
    settings_obj = SystemSettings.get_solo()
    admin_wallet = AdminWallet.get_solo()
    # Keep settings counters in sync with AdminWallet singleton and reconcile against customer balances
    try:
        # Ensure admin totals mirror the singleton
        settings_obj.admin_coin_balance = admin_wallet.balance or 0
        settings_obj.admin_coin_total_created = admin_wallet.total_created or 0

        # Reconcile admin balance as: total created minus total customer balances (no negative)
        customer_total_balance = sum(CoinWallet.objects.all().values_list('balance', flat=True)) or 0
        reconciled_balance = max(0, (settings_obj.admin_coin_total_created or 0) - customer_total_balance)
        if reconciled_balance != settings_obj.admin_coin_balance:
            settings_obj.admin_coin_balance = reconciled_balance
            admin_wallet.balance = reconciled_balance
            admin_wallet.save(update_fields=['balance', 'updated_at'])
        settings_obj.save(update_fields=['admin_coin_balance', 'admin_coin_total_created', 'updated_at'])
    except Exception:
        pass
    if request.method == 'POST':
        if request.POST.get('form_type') == 'create_coin':
            create_amount_raw = request.POST.get('create_amount')
            try:
                create_amount = int(create_amount_raw)
                if create_amount <= 0:
                    raise ValueError
            except Exception:
                create_amount = None
            if create_amount is None:
                error_message = 'Enter a positive amount to create coins.'
            else:
                settings_obj.admin_coin_total_created += create_amount
                settings_obj.admin_coin_balance += create_amount
                admin_wallet.total_created += create_amount
                admin_wallet.balance += create_amount
                admin_wallet.save(update_fields=['total_created', 'balance', 'updated_at'])
                settings_obj.save(update_fields=['admin_coin_total_created', 'admin_coin_balance', 'updated_at'])
                success_message = f"Created {create_amount} coins. Admin balance is now {settings_obj.admin_coin_balance}."
        else:
            cust_id_raw = request.POST.get('customer_profile_id')
            action = request.POST.get('action')
            amount = request.POST.get('amount')
            note = request.POST.get('note', '').strip()
            try:
                amount_val = int(amount)
                if amount_val <= 0:
                    raise ValueError
            except Exception:
                amount_val = None
            cust_id = cust_id_raw if cust_id_raw not in (None, '', 'None') else None
            if not cust_id or not action or amount_val is None or (isinstance(cust_id, str) and not cust_id.isdigit()):
                error_message = 'Please select a customer, action, and a positive amount.'
            else:
                user_wallet = None
                if str(cust_id).isdigit():
                    user_wallet = CoinWallet.objects.filter(pk=int(cust_id)).select_related('user').first()
                if not user_wallet:
                    error_message = 'Customer wallet not found.'
                else:
                    # Apply balance change directly to profile (simple implementation).
                    new_balance = user_wallet.balance
                    customer_user = user_wallet.user
                    # ensure admin_balance sufficient
                    if action == 'CREDIT':
                        if amount_val > admin_wallet.balance:
                            error_message = 'Insufficient admin coin balance to transfer.'
                        else:
                            admin_wallet.balance -= amount_val
                            settings_obj.admin_coin_balance -= amount_val
                            new_balance += amount_val
                    else:
                        if amount_val > user_wallet.balance:
                            error_message = 'Insufficient balance to deduct that amount.'
                        else:
                            new_balance -= amount_val
                            admin_wallet.balance += amount_val
                            settings_obj.admin_coin_balance += amount_val
                    if not error_message:
                        before_balance = user_wallet.balance
                        user_wallet.balance = new_balance
                        user_wallet.status = CoinWallet.STATUS_ACTIVE if new_balance >= 0 else CoinWallet.STATUS_FROZEN
                        user_wallet.save()
                        admin_wallet.save(update_fields=['balance', 'total_created', 'updated_at'])
                        settings_obj.save(update_fields=['admin_coin_balance', 'admin_coin_total_created', 'updated_at'])
                        # compute expiry one year from now
                        from datetime import timedelta
                        expiry_dt = timezone.now() + timedelta(days=365)
                        # log transaction
                        CoinTransaction.objects.create(
                            txn_id=f"TXN{_generate_bigint_id()}",
                            wallet=user_wallet,
                            customer=customer_user,
                            txn_type=CoinTransaction.TYPE_CREDIT if action == 'CREDIT' else CoinTransaction.TYPE_DEBIT,
                            amount=amount_val,
                            before_balance=before_balance,
                            after_balance=new_balance,
                            source=CoinTransaction.SOURCE_ADMIN,
                            related_object_type=None,
                            related_object_id=None,
                            reason=note or '',
                            expiry_date=expiry_dt,
                            created_by_role='SUPERADMIN',
                            created_by_id=request.user,
                        )
                        success_message = f"{'Credited' if action == 'CREDIT' else 'Debited'} {amount_val} coins for {getattr(customer_user, 'employee_id', '') or customer_user.email}. New balance: {new_balance}."

    # Ensure each customer has a wallet
    customer_users = list(User.objects.filter(role='CUSTOMER'))
    for u in customer_users:
        if not CoinWallet.objects.filter(user=u).exists():
            CoinWallet.objects.create(user=u, balance=0)

    wallets = list(CoinWallet.objects.select_related('user').all())

    search = (request.GET.get('search') or '').strip().lower()
    status_filter = (request.GET.get('status') or '').strip().upper()
    min_balance = request.GET.get('min_balance')
    max_balance = request.GET.get('max_balance')

    def _match(wallet):
        user = wallet.user
        if status_filter:
            if status_filter == 'ACTIVE' and wallet.status != CoinWallet.STATUS_ACTIVE:
                return False
            if status_filter == 'INACTIVE' and wallet.status == CoinWallet.STATUS_ACTIVE:
                return False
        if min_balance:
            try:
                if wallet.balance < int(min_balance):
                    return False
            except ValueError:
                pass
        if max_balance:
            try:
                if wallet.balance > int(max_balance):
                    return False
            except ValueError:
                pass
        if search:
            blob = ' '.join([
                getattr(user, 'employee_id', '') or '',
                user.get_full_name() or '',
                getattr(user, 'email', '') or '',
            ]).lower()
            if search not in blob:
                return False
        return True

    filtered = [w for w in wallets if _match(w)]

    # Deduplicate by user to avoid duplicate rows
    unique_profiles = []
    seen_users = set()
    for w in filtered:
        key = f"{w.user_id}"
        if key in seen_users:
            continue
        seen_users.add(key)
        unique_profiles.append(w)

    rows = []
    for w in unique_profiles:
        u = w.user
        rows.append({
            'wallet': w,
            'user': u,
            'employee_id': getattr(u, 'employee_id', '') or 'N/A',
            'name': u.get_full_name() if u else '',
            'email': getattr(u, 'email', ''),
            'status': w.status,
            'balance': w.balance,
            'updated_at': w.last_updated_at,
            'created_at': w.created_at,
        })

    page_obj, pagination_base = _paginate_items(request, rows, page_param='page', per_page=20)

    txn_qs = CoinTransaction.objects.select_related('wallet', 'customer', 'created_by_id').order_by('-created_at')
    txn_page_obj, txn_pagination_base = _paginate_items(request, txn_qs, page_param='tx_page', per_page=10)

    context = {
        'rows': page_obj.object_list,
        'page_obj': page_obj,
        'pagination_base': pagination_base,
        'txn_page_obj': txn_page_obj,
        'txn_pagination_base': txn_pagination_base,
        'search': search,
        'status_filter': status_filter,
        'min_balance': min_balance or '',
        'max_balance': max_balance or '',
        'total_customers': len(unique_profiles),
        'total_balance': sum(w.balance for w in unique_profiles),
        'total_added': 0,
        'total_spent': 0,
        'success_message': success_message,
        'error_message': error_message,
        'admin_coin_balance': settings_obj.admin_coin_balance,
        'admin_coin_total_created': settings_obj.admin_coin_total_created,
        'coin_rules': list(CoinRule.objects.select_related('updated_by').all()),
    }
    return render(request, 'superadmin/customers/wallets.html', context)


@login_required
@superadmin_required
def customer_pricing(request):
    settings_obj = SystemSettings.get_solo()
    edit_mode = (request.GET.get('edit') == '1')

    # Show current coin rules for key customer-facing tasks
    rule_defs = [
        ('REMOVE_AI', 'Remove-AI'),
        ('JOB_CHECK', 'Job Checking'),
        ('STRUCTURE', 'Structure Generate'),
        ('CREATE_CONTENT', 'Create Content (per 250 words)'),
    ]
    rule_qs = {r.service_name: r for r in CoinRule.objects.filter(service_name__in=[r[0] for r in rule_defs])}

    def _ensure_rule(key, label):
        rule = rule_qs.get(key)
        if not rule:
            rule = CoinRule.objects.create(
                service_name=key,
                coin_cost=0,
                min_balance_required=0,
                expiry_enabled=False,
                refund_enabled=True,
                updated_by=request.user,
            )
        return rule

    rule_rows = []
    for key, label in rule_defs:
        rule = _ensure_rule(key, label)
        rule_rows.append({
            'key': key,
            'label': label,
            'coin_cost': rule.coin_cost,
        })

    if request.method == 'POST':
        doc_text = (request.POST.get('pricing_plan_doc') or '').strip()
        settings_obj.pricing_plan_doc = doc_text
        settings_obj.save(update_fields=['pricing_plan_doc', 'updated_at'])
        log_action(request.user, 'UPDATE', settings_obj, 'Updated pricing plan document')
        messages.success(request, 'Pricing plan notes saved.')
        return redirect('superadmin:customer_pricing')

    context = {
        'pricing_plan_doc': settings_obj.pricing_plan_doc or '',
        'last_updated': settings_obj.updated_at,
        'edit_mode': edit_mode,
        'pricing_rules': rule_rows,
        'content_word_block': 250,
    }
    return render(request, 'superadmin/customers/pricing.html', context)


@login_required
@superadmin_required
def customer_ai_config(request):
    settings_obj = SystemSettings.get_solo()
    rule_defs = [
        ('REMOVE_AI', 'Remove-AI'),
        ('JOB_CHECK', 'Job Checking'),
        ('STRUCTURE', 'Structure Generate'),
        ('CREATE_CONTENT', 'Create Content (per 250 words)'),
    ]
    rules = {r.service_name: r for r in CoinRule.objects.filter(service_name__in=[r[0] for r in rule_defs])}

    def _get_or_create_rule(key, label):
        rule = rules.get(key)
        if not rule:
            rule = CoinRule.objects.create(
                service_name=key,
                coin_cost=0,
                min_balance_required=0,
                expiry_enabled=False,
                refund_enabled=True,
                updated_by=request.user,
            )
        return rule

    if request.method == 'POST':
        updated_any = False
        for key, label in rule_defs:
            val_raw = request.POST.get(f"coins_{key.lower()}", '0').strip()
            try:
                coins_val = int(val_raw)
                if coins_val < 0:
                    raise ValueError
            except Exception:
                coins_val = 0
            rule = _get_or_create_rule(key, label)
            if rule.coin_cost != coins_val or rule.min_balance_required != coins_val:
                rule.coin_cost = coins_val
                rule.min_balance_required = coins_val
                rule.updated_by = request.user
                rule.save()
                updated_any = True
        note_text = request.POST.get('coin_rule_note', '').strip()
        if note_text != (settings_obj.coin_rule_note or ''):
            settings_obj.coin_rule_note = note_text
            settings_obj.save(update_fields=['coin_rule_note', 'updated_at'])
            updated_any = True
        if updated_any:
            log_action(request.user, 'UPDATE', settings_obj, 'Updated coin deduction rules')
            messages.success(request, 'Coin deduction rules saved.')
        else:
            messages.info(request, 'No changes detected.')
        return redirect('superadmin:customer_ai_config')

    rows = []
    for key, label in rule_defs:
        rule = _get_or_create_rule(key, label)
        rows.append({
            'key': key,
            'label': label,
            'coin_cost': rule.coin_cost,
            'min_balance_required': rule.min_balance_required,
        })
    context = {
        'rules': rows,
        'coin_rule_note': settings_obj.coin_rule_note or '',
        'content_word_block': 250,
    }
    return render(request, 'superadmin/customers/ai_config.html', context)


@login_required
@superadmin_required
@login_required
@superadmin_required
def customer_ai_logs(request):
    logs = AIRequestLog.objects.select_related('user').all()
    paginator = Paginator(logs, 20)
    page_number = request.GET.get('page') or 1
    page_obj = paginator.get_page(page_number)
    qs = request.GET.copy()
    qs.pop('page', None)
    base_query = qs.urlencode()
    pagination_base = '?' + base_query + '&' if base_query else '?'

    def _customer_id(log):
        if getattr(log, 'customer_id', None):
            return log.customer_id
        user = getattr(log, 'user', None)
        return getattr(user, 'customer_code', None) or getattr(user, 'employee_id', None) or ''

    def _customer_name(log):
        if getattr(log, 'customer_name', None):
            return log.customer_name
        user = getattr(log, 'user', None)
        return user.get_full_name() if user else ''

    rows = []
    for idx, log in enumerate(page_obj.object_list, start=page_obj.start_index()):
        rows.append({
            'sl_no': idx,
            'customer_id': _customer_id(log),
            'customer_name': _customer_name(log),
            'service': log.service,
            'coins': log.coins,
            'status': log.status,
            'time': log.created_at,
        })

    context = {
        'logs': rows,
        'page_obj': page_obj,
        'pagination_base': pagination_base,
    }
    return render(request, 'superadmin/customers/ai_logs.html', context)


@login_required
@superadmin_required
def customer_job_checks(request):
    submissions = JobCheckingSubmission.objects.select_related('user').all()
    rule_defs = [
        ('REMOVE_AI', 'Remove-AI'),
        ('JOB_CHECK', 'Job Checking'),
        ('STRUCTURE', 'Structure Generate'),
        ('CREATE_CONTENT', 'Create Content (per 250 words)'),
    ]
    rule_map = {r.service_name: r for r in CoinRule.objects.filter(service_name__in=[r[0] for r in rule_defs])}
    rule_cards = []
    for key, label in rule_defs:
        rule = rule_map.get(key)
        coin_cost = getattr(rule, 'coin_cost', 0) if rule else 0
        rule_cards.append({'label': label, 'coins': coin_cost})
    search = (request.GET.get('search') or '').strip().lower()
    status_filter = (request.GET.get('status') or '').strip().upper()
    date_from = _parse_date_param(request.GET.get('date_from'))
    date_to = _parse_date_param(request.GET.get('date_to'))

    if search:
        submissions = [
            s for s in submissions
            if search in s.submission_id.lower()
            or search in (getattr(s.user, 'email', '') or '').lower()
            or search in (getattr(s.user, 'customer_code', '') or '').lower()
            or search in (getattr(s.user, 'employee_id', '') or '').lower()
        ]

    if status_filter in (JobCheckingSubmission.STATUS_PENDING, JobCheckingSubmission.STATUS_SUCCESS, JobCheckingSubmission.STATUS_FAILED):
        submissions = [s for s in submissions if getattr(s, 'status', '').upper() == status_filter]

    if date_from or date_to:
        filtered = []
        for s in submissions:
            dt = getattr(s, 'created_at', None)
            if not dt:
                continue
            d = dt.date()
            if date_from and d < date_from:
                continue
            if date_to and d > date_to:
                continue
            filtered.append(s)
        submissions = filtered

    paginator = Paginator(submissions, 20)
    page_number = request.GET.get('page') or 1
    page_obj = paginator.get_page(page_number)
    qs = request.GET.copy()
    qs.pop('page', None)
    base_query = qs.urlencode()
    pagination_base = '?' + base_query + '&' if base_query else '?'

    rows = []
    for idx, sub in enumerate(page_obj.object_list, start=page_obj.start_index()):
        rows.append({
            'sl_no': idx,
            'submission_id': sub.submission_id,
            'customer_id': sub.customer_id,
            'customer_name': sub.customer_name,
            'status': sub.status,
            'coins_spent': sub.coins_spent,
            'created_at': sub.created_at,
            'service': sub.service,
        })

    context = {
        'rows': rows,
        'page_obj': page_obj,
        'pagination_base': pagination_base,
        'search': search,
        'status_filter': status_filter,
        'date_from': date_from,
        'date_to': date_to,
        'rule_cards': rule_cards,
        'content_word_block': 250,
    }
    return render(request, 'superadmin/customers/job_checks.html', context)


@login_required
@superadmin_required
def customer_job_check_detail(request, submission_id):
    submission = get_object_or_404(JobCheckingSubmission, submission_id=submission_id)
    context = {
        'submission': submission,
    }
    return render(request, 'superadmin/customers/job_check_detail.html', context)


@login_required
@superadmin_required
def customer_structures(request):
    submissions = StructureGenerationSubmission.objects.select_related('user').all()
    search = (request.GET.get('search') or '').strip().lower()
    status_filter = (request.GET.get('status') or '').strip().upper()
    date_from = _parse_date_param(request.GET.get('date_from'))
    date_to = _parse_date_param(request.GET.get('date_to'))
    subject_filter = (request.GET.get('subject_field') or '').strip().lower()
    level_filter = (request.GET.get('academic_level') or '').strip().lower()

    if search:
        submissions = [
            s for s in submissions
            if search in (s.submission_id or '').lower()
            or search in (s.topic or '').lower()
            or search in (getattr(s.user, 'email', '') or '').lower()
        ]

    if status_filter in (StructureGenerationSubmission.STATUS_SUCCESS, StructureGenerationSubmission.STATUS_FAILED, StructureGenerationSubmission.STATUS_PENDING):
        submissions = [s for s in submissions if getattr(s, 'status', '').upper() == status_filter]

    if subject_filter:
        submissions = [s for s in submissions if subject_filter in (s.subject_field or '').lower()]

    if level_filter:
        submissions = [s for s in submissions if level_filter in (s.academic_level or '').lower()]

    if date_from or date_to:
        filtered = []
        for s in submissions:
            dt = getattr(s, 'created_at', None)
            if not dt:
                continue
            d = dt.date()
            if date_from and d < date_from:
                continue
            if date_to and d > date_to:
                continue
            filtered.append(s)
        submissions = filtered

    paginator = Paginator(submissions, 20)
    page_number = request.GET.get('page') or 1
    page_obj = paginator.get_page(page_number)
    qs = request.GET.copy()
    qs.pop('page', None)
    base_query = qs.urlencode()
    pagination_base = '?' + base_query + '&' if base_query else '?'

    rows = []
    for idx, sub in enumerate(page_obj.object_list, start=page_obj.start_index()):
        rows.append({
            'sl_no': idx,
            'submission_id': sub.submission_id,
            'customer_id': sub.customer_id,
            'customer_name': sub.customer_name,
            'topic': sub.topic,
            'status': sub.status,
            'coins_spent': sub.coins_spent,
            'created_at': sub.created_at,
        })

    # Coin rule cards
    rule_defs = [
        ('REMOVE_AI', 'Remove-AI'),
        ('JOB_CHECK', 'Job Checking'),
        ('STRUCTURE', 'Structure Generate'),
        ('CREATE_CONTENT', 'Create Content (per 250 words)'),
    ]
    rule_map = {r.service_name: r for r in CoinRule.objects.filter(service_name__in=[r[0] for r in rule_defs])}
    rule_cards = []
    for key, label in rule_defs:
        rule = rule_map.get(key)
        coin_cost = getattr(rule, 'coin_cost', 0) if rule else 0
        rule_cards.append({'label': label, 'coins': coin_cost})

    context = {
        'rows': rows,
        'page_obj': page_obj,
        'pagination_base': pagination_base,
        'search': search,
        'status_filter': status_filter,
        'date_from': date_from,
        'date_to': date_to,
        'subject_filter': subject_filter,
        'level_filter': level_filter,
        'rule_cards': rule_cards,
        'content_word_block': 250,
    }
    return render(request, 'superadmin/customers/structures.html', context)


@login_required
@superadmin_required
def customer_structure_detail(request, submission_id):
    submission = get_object_or_404(StructureGenerationSubmission, submission_id=submission_id)
    context = {'submission': submission}
    return render(request, 'superadmin/customers/structure_detail.html', context)


@login_required
@superadmin_required
def customer_contents(request):
    submissions = ContentGenerationSubmission.objects.select_related('user').all()
    search = (request.GET.get('search') or '').strip().lower()
    status_filter = (request.GET.get('status') or '').strip().upper()
    date_from = _parse_date_param(request.GET.get('date_from'))
    date_to = _parse_date_param(request.GET.get('date_to'))
    subject_filter = (request.GET.get('subject_field') or '').strip().lower()
    level_filter = (request.GET.get('academic_level') or '').strip().lower()
    min_wc = request.GET.get('min_wc')
    max_wc = request.GET.get('max_wc')

    if search:
        submissions = [
            s for s in submissions
            if search in (s.submission_id or '').lower()
            or search in (s.topic or '').lower()
            or search in (getattr(s.user, 'email', '') or '').lower()
        ]

    if status_filter in (ContentGenerationSubmission.STATUS_SUCCESS, ContentGenerationSubmission.STATUS_FAILED, ContentGenerationSubmission.STATUS_PENDING):
        submissions = [s for s in submissions if getattr(s, 'status', '').upper() == status_filter]

    if subject_filter:
        submissions = [s for s in submissions if subject_filter in (s.subject_field or '').lower()]

    if level_filter:
        submissions = [s for s in submissions if level_filter in (s.academic_level or '').lower()]

    def _wc(val):
        try:
            return int(val)
        except Exception:
            return None
    min_wc_val = _wc(min_wc)
    max_wc_val = _wc(max_wc)
    if min_wc_val is not None or max_wc_val is not None:
        filtered_wc = []
        for s in submissions:
            wc = getattr(s, 'word_count', 0) or 0
            if min_wc_val is not None and wc < min_wc_val:
                continue
            if max_wc_val is not None and wc > max_wc_val:
                continue
            filtered_wc.append(s)
        submissions = filtered_wc

    if date_from or date_to:
        filtered = []
        for s in submissions:
            dt = getattr(s, 'created_at', None)
            if not dt:
                continue
            d = dt.date()
            if date_from and d < date_from:
                continue
            if date_to and d > date_to:
                continue
            filtered.append(s)
        submissions = filtered

    paginator = Paginator(submissions, 20)
    page_number = request.GET.get('page') or 1
    page_obj = paginator.get_page(page_number)
    qs = request.GET.copy()
    qs.pop('page', None)
    base_query = qs.urlencode()
    pagination_base = '?' + base_query + '&' if base_query else '?'

    rows = []
    for idx, sub in enumerate(page_obj.object_list, start=page_obj.start_index()):
        version_count = ContentGenerationSubmission.objects.filter(base_submission_id=sub.base_submission_id).count()
        rows.append({
            'sl_no': idx,
            'submission_id': sub.submission_id,
            'base_submission_id': sub.base_submission_id,
            'version_number': sub.version_number,
            'version_count': version_count,
            'customer_id': sub.customer_id,
            'customer_name': sub.customer_name,
            'topic': sub.topic,
            'status': sub.status,
            'coins_spent': sub.coins_spent,
            'word_count': sub.word_count,
            'created_at': sub.created_at,
        })

    rule_defs = [
        ('REMOVE_AI', 'Remove-AI'),
        ('JOB_CHECK', 'Job Checking'),
        ('STRUCTURE', 'Structure Generate'),
        ('CREATE_CONTENT', 'Create Content (per 250 words)'),
    ]
    rule_map = {r.service_name: r for r in CoinRule.objects.filter(service_name__in=[r[0] for r in rule_defs])}
    rule_cards = []
    for key, label in rule_defs:
        rule = rule_map.get(key)
        coin_cost = getattr(rule, 'coin_cost', 0) if rule else 0
        rule_cards.append({'label': label, 'coins': coin_cost})

    context = {
        'rows': rows,
        'page_obj': page_obj,
        'pagination_base': pagination_base,
        'search': search,
        'status_filter': status_filter,
        'date_from': date_from,
        'date_to': date_to,
        'subject_filter': subject_filter,
        'level_filter': level_filter,
        'min_wc': min_wc or '',
        'max_wc': max_wc or '',
        'rule_cards': rule_cards,
        'content_word_block': 250,
    }
    return render(request, 'superadmin/customers/contents.html', context)


@login_required
@superadmin_required
def customer_content_detail(request, submission_id):
    submission = get_object_or_404(ContentGenerationSubmission, submission_id=submission_id)
    versions = ContentGenerationSubmission.objects.filter(base_submission_id=submission.base_submission_id).order_by('version_number')
    context = {
        'submission': submission,
        'versions': versions,
    }
    return render(request, 'superadmin/customers/content_detail.html', context)


@login_required
@superadmin_required
def customer_tickets(request):
    tickets = CustomerTicket.objects.select_related('user').all()
    search = (request.GET.get('search') or '').strip().lower()
    status_filter = (request.GET.get('status') or '').strip().upper()
    priority_filter = (request.GET.get('priority') or '').strip().upper()
    date_from = _parse_date_param(request.GET.get('date_from'))
    date_to = _parse_date_param(request.GET.get('date_to'))
    category_filter = (request.GET.get('category') or '').strip().lower()

    if search:
        tickets = [
            t for t in tickets
            if search in (t.ticket_id or '').lower()
            or search in (t.subject or '').lower()
            or search in (getattr(t.user, 'email', '') or '').lower()
            or search in (t.customer_id or '').lower()
        ]

    if status_filter in ('OPEN', 'IN_PROGRESS', 'RESOLVED', 'CLOSED'):
        tickets = [t for t in tickets if getattr(t, 'status', '').upper() == status_filter]

    if priority_filter in ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL'):
        tickets = [t for t in tickets if getattr(t, 'priority', '').upper() == priority_filter]

    if category_filter:
        tickets = [t for t in tickets if category_filter in (t.category or '').lower()]

    if date_from or date_to:
        filtered = []
        for t in tickets:
            dt = getattr(t, 'created_at', None)
            if not dt:
                continue
            d = dt.date()
            if date_from and d < date_from:
                continue
            if date_to and d > date_to:
                continue
            filtered.append(t)
        tickets = filtered

    paginator = Paginator(tickets, 20)
    page_number = request.GET.get('page') or 1
    page_obj = paginator.get_page(page_number)
    qs = request.GET.copy()
    qs.pop('page', None)
    base_query = qs.urlencode()
    pagination_base = '?' + base_query + '&' if base_query else '?'

    rows = []
    for idx, t in enumerate(page_obj.object_list, start=page_obj.start_index()):
        rows.append({
            'sl_no': idx,
            'ticket_id': t.ticket_id,
            'customer_id': t.customer_id,
            'customer_name': t.customer_name,
            'subject': t.subject,
            'category': t.category,
            'status': t.status,
            'priority': t.priority,
            'created_at': t.created_at,
            'updated_at': t.updated_at,
        })

    rule_defs = [
        ('REMOVE_AI', 'Remove-AI'),
        ('JOB_CHECK', 'Job Checking'),
        ('STRUCTURE', 'Structure Generate'),
        ('CREATE_CONTENT', 'Create Content (per 250 words)'),
    ]
    rule_map = {r.service_name: r for r in CoinRule.objects.filter(service_name__in=[r[0] for r in rule_defs])}
    rule_cards = []
    for key, label in rule_defs:
        rule = rule_map.get(key)
        coin_cost = getattr(rule, 'coin_cost', 0) if rule else 0
        rule_cards.append({'label': label, 'coins': coin_cost})

    context = {
        'rows': rows,
        'page_obj': page_obj,
        'pagination_base': pagination_base,
        'search': search,
        'status_filter': status_filter,
        'priority_filter': priority_filter,
        'date_from': date_from,
        'date_to': date_to,
        'category_filter': category_filter,
        'rule_cards': rule_cards,
        'content_word_block': 250,
    }
    return render(request, 'superadmin/customers/tickets.html', context)


@login_required
@superadmin_required
def customer_ticket_detail(request, ticket_id):
    ticket = get_object_or_404(CustomerTicket, ticket_id=ticket_id)
    edit_mode = (request.GET.get('edit') == '1')

    if request.method == 'POST':
        new_status = (request.POST.get('status') or ticket.status).upper()
        new_priority = (request.POST.get('priority') or ticket.priority).upper()
        admin_note = (request.POST.get('admin_note') or '').strip()
        changed_fields = []
        if new_status != ticket.status:
            ticket.status = new_status
            changed_fields.append('status')
        if new_priority != ticket.priority:
            ticket.priority = new_priority
            changed_fields.append('priority')
        if admin_note != (ticket.admin_notes or ''):
            ticket.admin_notes = admin_note
            changed_fields.append('admin_notes')
        if changed_fields:
            changed_fields.append('updated_at')
            ticket.save(update_fields=changed_fields)
            log_action(request.user, 'UPDATE', ticket, f'Updated ticket {ticket.ticket_id}')
            messages.success(request, 'Ticket updated.')
        else:
            messages.info(request, 'No changes made.')
        return redirect('superadmin:customer_ticket_detail', ticket_id=ticket.ticket_id)

    context = {
        'ticket': ticket,
        'priority_choices': CustomerTicket.PRIORITY_CHOICES,
        'status_choices': CustomerTicket.STATUS_CHOICES,
        'admin_note': ticket.admin_notes or '',
        'edit_mode': edit_mode,
    }
    return render(request, 'superadmin/customers/ticket_detail.html', context)


@login_required
@superadmin_required
def customer_meetings(request):
    return render(request, 'superadmin/customers/meetings.html', {})


@login_required
@superadmin_required
def customer_bookings(request):
    return render(request, 'superadmin/customers/bookings.html', {})


@login_required
@superadmin_required
def customer_analytics(request):
    # Date filters
    date_from = _parse_date_param(request.GET.get('date_from'))
    date_to = _parse_date_param(request.GET.get('date_to'))

    def _in_range(dt):
        if not dt:
            return False
        d = dt.date()
        if date_from and d < date_from:
            return False
        if date_to and d > date_to:
            return False
        return True if (date_from or date_to) else True

    customers = list(User.objects.filter(role='CUSTOMER'))
    wallet_map = {w.user_id: w for w in CoinWallet.objects.select_related('user').all()}

    # Collect AI operations
    ai_logs = AIRequestLog.objects.all()
    if date_from or date_to:
        ai_logs = [l for l in ai_logs if _in_range(l.created_at)]

    job_checks = JobCheckingSubmission.objects.all()
    if date_from or date_to:
        job_checks = [j for j in job_checks if _in_range(j.created_at)]

    structures = StructureGenerationSubmission.objects.all()
    if date_from or date_to:
        structures = [s for s in structures if _in_range(s.created_at)]

    contents = ContentGenerationSubmission.objects.all()
    if date_from or date_to:
        contents = [c for c in contents if _in_range(c.created_at)]

    tickets = CustomerTicket.objects.all()
    if date_from or date_to:
        tickets = [t for t in tickets if _in_range(t.created_at)]

    total_wallet_balance = sum(getattr(wallet_map.get(u.id), 'balance', 0) for u in customers)
    total_coins_spent = sum(getattr(log, 'coins', 0) for log in ai_logs)
    total_operations = len(ai_logs) + len(job_checks) + len(structures) + len(contents)

    job_check_count = len(job_checks)
    structure_count = len(structures)
    content_count = len(contents)
    other_ops = len(ai_logs) - job_check_count - structure_count - content_count
    if other_ops < 0:
        other_ops = 0
    service_usage = [
        {'label': 'Job Checking', 'count': job_check_count},
        {'label': 'Structure Generate', 'count': structure_count},
        {'label': 'Content Creation', 'count': content_count},
        {'label': 'Other AI Ops', 'count': other_ops},
    ]
    total_usage = sum(item['count'] for item in service_usage) or 1
    for item in service_usage:
        item['pct'] = round((item['count'] / total_usage) * 100, 1)

    # Per-customer aggregation
    customer_rows = []
    for idx, user in enumerate(customers, start=1):
        wallet = wallet_map.get(user.id)
        user_ai_logs = [l for l in ai_logs if getattr(l, 'user_id', None) == user.id]
        user_job_checks = [j for j in job_checks if getattr(j, 'user_id', None) == user.id]
        user_structures = [s for s in structures if getattr(s, 'user_id', None) == user.id]
        user_contents = [c for c in contents if getattr(c, 'user_id', None) == user.id]
        user_tickets = [t for t in tickets if getattr(t, 'user_id', None) == user.id]
        coins_spent = sum(getattr(l, 'coins', 0) for l in user_ai_logs)
        ops_count = len(user_ai_logs) + len(user_job_checks) + len(user_structures) + len(user_contents)
        customer_rows.append({
            'sl_no': idx,
            'customer_id': getattr(user, 'customer_code', None) or getattr(user, 'employee_id', None) or '',
            'customer_name': user.get_full_name(),
            'email': user.email,
            'wallet_balance': getattr(wallet, 'balance', 0) if wallet else 0,
            'coins_spent': coins_spent,
            'operations': ops_count,
            'tickets': len(user_tickets),
        })

    # Simple top customers by operations
    top_customers = sorted(customer_rows, key=lambda r: r['operations'], reverse=True)[:5]

    # Coin rule cards for quick reference
    rule_defs = [
        ('REMOVE_AI', 'Remove-AI'),
        ('JOB_CHECK', 'Job Checking'),
        ('STRUCTURE', 'Structure Generate'),
        ('CREATE_CONTENT', 'Create Content (per 250 words)'),
    ]
    rule_map = {r.service_name: r for r in CoinRule.objects.filter(service_name__in=[r[0] for r in rule_defs])}
    rule_cards = []
    for key, label in rule_defs:
        rule = rule_map.get(key)
        coin_cost = getattr(rule, 'coin_cost', 0) if rule else 0
        rule_cards.append({'label': label, 'coins': coin_cost})

    context = {
        'date_from': date_from,
        'date_to': date_to,
        'total_wallet_balance': total_wallet_balance,
        'total_coins_spent': total_coins_spent,
        'total_operations': total_operations,
        'total_customers': len(customers),
        'customer_rows': customer_rows,
        'top_customers': top_customers,
        'service_usage': service_usage,
        'job_check_count': job_check_count,
        'structure_count': structure_count,
        'content_count': content_count,
        'rule_cards': rule_cards,
        'content_word_block': 250,
    }
    return render(request, 'superadmin/customers/analytics.html', context)


# ---------------- Google Login / Social Auth Management (SuperAdmin only) ----------------
@login_required
@superadmin_required
def google_login_settings_view(request):
    config = GoogleAuthConfig.get_solo()
    edit_mode = request.GET.get('edit') == '1'
    if request.method == 'POST':
        form = GoogleAuthConfigForm(request.POST, instance=config)
        if form.is_valid():
            cfg = form.save(commit=False)
            cfg.updated_by = request.user
            cfg.save()
            log_action(request.user, 'UPDATE', cfg, 'Updated Google auth config')
            messages.success(request, 'Google Login settings updated.')
            return redirect('superadmin:google_login_settings')
        else:
            edit_mode = True
    else:
        form = GoogleAuthConfigForm(instance=config)

    warnings = []
    if config.enabled and (not config.client_id or not config.client_secret):
        warnings.append('Google login is enabled but Client ID/Secret are not set.')
    if config.enabled and not config.redirect_url:
        warnings.append('Redirect URL is empty; ensure it matches the Google OAuth console.')

    linked_accounts = SocialAccount.objects.filter(provider='google').select_related('user')
    logs = list(GoogleLoginLog.objects.all()[:50])
    if not logs and linked_accounts:
        # Fallback: surface linked accounts as "linked" entries so the table shows existing DB data
        for acc in linked_accounts:
            logs.append(type('LogRow', (), {
                'created_at': getattr(acc, 'last_login', None) or getattr(acc.user, 'date_joined', timezone.now()) if acc.user else timezone.now(),
                'user': acc.user,
                'email': acc.extra_data.get('email') or acc.uid,
                'status': GoogleLoginLog.STATUS_SUCCESS,
                'reason': 'Linked (no log entry)',
                'ip_address': '',
            })())

    return render(request, 'superadmin/google_login_settings.html', {
        'form': form,
        'edit_mode': edit_mode,
        'config': config,
        'warnings': warnings,
        'linked_accounts': linked_accounts,
        'logs': logs,
        'masked_secret': (config.client_secret[:4] + '...' + config.client_secret[-4:]) if config.client_secret else '',
    })


@login_required
@superadmin_required
def google_login_unlink_view(request, account_id):
    acc = get_object_or_404(SocialAccount, id=account_id, provider='google')
    email = acc.extra_data.get('email') or acc.uid
    try:
        acc.delete()
        log_action(request.user, 'UNLINK', acc, f'Unlinked Google account {email}')
        messages.success(request, f'Google account {email} unlinked.')
    except Exception as exc:
        messages.error(request, f'Could not unlink: {exc}')
    return redirect('superadmin:google_login_settings')


