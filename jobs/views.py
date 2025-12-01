from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Count, Q
from django.urls import reverse
from django.utils import timezone
from .models import Job, Attachment, JobMetrics
from .forms import JobDropForm, JobFilterForm
from auditlog.utils import log_action, log_job_action

@login_required
def create_job_view(request):
    """Marketing Team: Create new job"""
    if request.user.role != 'MARKETING':
        messages.error(request, 'Access denied.')
        return redirect('superadmin:dashboard')  # or some valid URL

    if request.method == 'POST':
        form = JobDropForm(request.POST, request.FILES)
        if form.is_valid():
            job = form.save(commit=False)
            job.created_by = request.user
            job.save()

            # ✅ Use cleaned_data from MultiFileField
            files = form.cleaned_data.get('attachments', [])
            for file in files:
                Attachment.objects.create(
                    job=job,
                    file=file,
                    filename=file.name,
                    file_type=file.name.split('.')[-1].lower(),
                    file_size=file.size
                )
                Attachment.save()

            log_action(request.user, 'CREATE', job, str(job.id), f'Created job {job.job_id} (System ID: {job.system_id})')
            log_job_action(
                job_id=job.job_id,
                system_id=job.system_id,
                user=request.user,
                action='JOB_CREATED'
            )
            JobMetrics.update_metrics()

            messages.success(request, f'Job {job.job_id} created successfully!')
            return redirect('marketing:all_projects')
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
def edit_job_view(request, pk):
    job = get_object_or_404(Job, pk=pk)

    if job.is_deleted:
        messages.error(request, 'This job has been deleted. Restore it before editing.')
        return redirect('superadmin:new_jobs' if request.user.role == 'SUPERADMIN' else 'marketing:all_projects')

    if request.user.role == 'MARKETING':
        if job.created_by != request.user:
            messages.error(request, 'You can only edit jobs you created.')
            return redirect('marketing:all_projects')
        if job.status != 'PENDING':
            messages.error(request, 'You can only edit jobs that are still pending.')
            return redirect('marketing:all_projects')
    elif request.user.role != 'SUPERADMIN':
        messages.error(request, 'Access denied.')
        return redirect('accounts:dashboard_redirect')

    if request.method == 'POST':
        form = JobDropForm(request.POST, request.FILES, instance=job)
        if form.is_valid():
            form.save()

            files = form.cleaned_data.get('attachments', [])
            for file in files:
                Attachment.objects.create(
                    job=job,
                    file=file,
                    filename=file.name,
                    file_type=file.name.split('.')[-1].lower(),
                    file_size=file.size,
                )

            log_action(request.user, 'UPDATE', job, f'Updated job {job.job_id}')
            messages.success(request, f'Job {job.job_id} updated successfully!')
            target = 'superadmin:new_jobs' if request.user.role == 'SUPERADMIN' else 'marketing:all_projects'
            return redirect(target)
        else:
            if form.errors.get('expected_deadline') or form.errors.get('strict_deadline'):
                messages.error(
                    request,
                    'You cannot set Expected or Strict deadlines on Sundays or holidays. Please choose different dates.'
                )
    else:
        form = JobDropForm(instance=job)

    cancel_target = 'superadmin:new_jobs' if request.user.role == 'SUPERADMIN' else 'marketing:all_projects'

    return render(
        request,
        'marketing/create_job.html',
        {
            'form': form,
            'is_edit': True,
            'form_title': 'Edit Job',
            'submit_label': 'Update Job',
            'cancel_url': reverse(cancel_target),
            'show_attachments': True,
        },
    )


@login_required
def delete_job_view(request, pk):
    job = get_object_or_404(Job, pk=pk)

    if job.is_deleted:
        messages.error(request, 'Job is already deleted.')
        target = 'superadmin:new_jobs' if request.user.role == 'SUPERADMIN' else 'marketing:all_projects'
        return redirect(target)

    if request.user.role == 'MARKETING':
        if job.created_by != request.user:
            messages.error(request, 'You can only delete jobs you created.')
            return redirect('marketing:all_projects')
        if job.status != 'PENDING':
            messages.error(request, 'You can only delete jobs that are still pending.')
            return redirect('marketing:all_projects')
    elif request.user.role != 'SUPERADMIN':
        messages.error(request, 'Access denied.')
        return redirect('accounts:dashboard_redirect')

    if job.is_deleted:
        messages.error(request, 'This job has been deleted. Restore it before editing.')
        target = 'superadmin:new_jobs' if request.user.role == 'SUPERADMIN' else 'marketing:all_projects'
        return redirect(target)

    if request.method == 'POST':
        job.is_deleted = True
        job.deleted_at = timezone.now()
        job.deleted_by = request.user
        job.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])
        log_action(request.user, 'DELETE', job, f'Deleted job {job.job_id}')
        messages.success(request, f'Job {job.job_id} deleted successfully.')

    target = 'superadmin:new_jobs' if request.user.role == 'SUPERADMIN' else 'marketing:all_projects'
    return redirect(target)


@login_required
def restore_job_view(request, pk):
    if request.user.role != 'SUPERADMIN':
        messages.error(request, 'Access denied.')
        return redirect('marketing:dashboard')

    job = get_object_or_404(Job, pk=pk)

    if not job.is_deleted:
        messages.info(request, 'Job is already active.')
        return redirect('superadmin:new_jobs')

    if request.method == 'POST':
        job.is_deleted = False
        job.deleted_at = None
        job.deleted_by = None
        job.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])
        log_action(request.user, 'RESTORE', job, f'Restored job {job.job_id}')
        messages.success(request, f'Job {job.job_id} restored successfully!')

    return redirect('superadmin:new_jobs')


@login_required
def job_list(request):
    """List all jobs with filters"""
    form = JobFilterForm(request.GET)
    jobs = Job.objects.all()
    
    # Apply filters
    if form.is_valid():
        status = form.cleaned_data.get('status')
        date_from = form.cleaned_data.get('date_from')
        date_to = form.cleaned_data.get('date_to')
        search = form.cleaned_data.get('search')
        
        if status:
            jobs = jobs.filter(status=status)
        
        if date_from:
            jobs = jobs.filter(created_at__date__gte=date_from)
        
        if date_to:
            jobs = jobs.filter(created_at__date__lte=date_to)
        
        if search:
            jobs = jobs.filter(
                Q(job_id__icontains=search) | Q(system_id__icontains=search)
            )
    
    # Calculate statistics
    total_jobs = jobs.count()
    pending_jobs = jobs.filter(status='pending').count()
    total_amount = jobs.aggregate(Sum('amount'))['amount__sum'] or 0
    
    # Filter by card click
    card_filter = request.GET.get('filter')
    if card_filter == 'pending':
        jobs = jobs.filter(status='pending', is_approved=False)
    elif card_filter == 'total':
        pass  # Show all
    elif card_filter == 'amount':
        pass  # Show all but sorted by amount
        jobs = jobs.order_by('-amount')
    
    context = {
        'jobs': jobs,
        'form': form,
        'total_jobs': total_jobs,
        'pending_jobs': pending_jobs,
        'total_amount': total_amount,
    }
    
    return render(request, 'jobs/job_list.html', context)

@login_required
def job_detail_view(request, job_id):
    """View complete job details"""
    job = get_object_or_404(Job, id=job_id)
    attachments = job.attachments.all()
    
    # Check permissions
    if request.user.role == 'MARKETING' and job.created_by != request.user:
        messages.error(request, 'You can only view your own jobs.')
        return redirect('marketing:all_projects')
    
    # Log the action – pass the job object, no target_model/target_id kwargs
    log_action(
        request.user,
        'JOB_VIEWED',
        job,
        f'Job viewed: {job.job_id}',
        request=request,
    )
    
    log_job_action(
        job_id=job.job_id,
        system_id=job.system_id,
        user=request.user,
        action='JOB_VIEWED',
    )
    
    context = {
        'job': job,
        'attachments': attachments,
    }
    return render(request, 'jobs/job_detail.html', context)



@login_required
def marketing_all_projects(request):
    """Marketing team's all projects page"""
    if request.user.role != 'marketing':
        messages.error(request, 'Access denied.')
        return redirect('accounts:dashboard_redirect')
    
    # Get jobs created by this user
    jobs_qs = Job.objects.filter(created_by=request.user)
    jobs = [job for job in jobs_qs if not job.is_deleted]
    
    # Calculate statistics
    total_jobs = len(jobs)
    pending_jobs = sum(1 for job in jobs if not job.is_approved)
    total_amount = sum(job.amount or 0 for job in jobs)
    
    # Filter by card click
    card_filter = request.GET.get('filter')
    if card_filter == 'pending':
        jobs = [job for job in jobs if not job.is_approved]
    elif card_filter == 'amount':
        jobs = sorted(jobs, key=lambda j: j.amount or 0, reverse=True)
    
    context = {
        'jobs': jobs,
        'total_jobs': total_jobs,
        'pending_jobs': pending_jobs,
        'total_amount': total_amount,
    }
    
    return render(request, 'jobs/marketing_all_projects.html', context)

def get_job_statistics():
    """Helper function to get job statistics"""
    total_jobs = Job.objects.count()
    pending_jobs = Job.objects.filter(status='pending', is_approved=False).count()
    approved_jobs = Job.objects.filter(is_approved=True).count()
    completed_jobs = Job.objects.filter(status='completed').count()
    
    total_amount = Job.objects.aggregate(Sum('amount'))['amount__sum'] or 0
    pending_amount = Job.objects.filter(status='pending').aggregate(Sum('amount'))['amount__sum'] or 0
    
    return {
        'total_jobs': total_jobs,
        'pending_jobs': pending_jobs,
        'approved_jobs': approved_jobs,
        'completed_jobs': completed_jobs,
        'total_amount': total_amount,
        'pending_amount': pending_amount,
    }
