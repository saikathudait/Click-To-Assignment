from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.http import HttpResponse, JsonResponse
from jobs.models import Job
from .models import (JobSummary, JobStructure, GeneratedContent, 
                     References, FullContent, PlagiarismReport, AIReport)
from .services import (generate_job_summary, generate_job_structure,
                       generate_content, generate_references,
                       generate_full_content_with_citations,
                       check_plagiarism, check_ai_content)
from .utils import sync_job_status
from auditlog.utils import log_action, log_job_action
from superadmin.models import ContentAccessSetting

PIPELINE_DONE_STATUSES = {'AI_REPORT', 'APPROVED', 'COMPLETED'}


def superadmin_required(view_func):
    """Decorator to ensure only superadmin can access"""
    def wrapper(request, *args, **kwargs):
        if request.user.role != 'SUPERADMIN':
            messages.error(request, 'Access denied. SuperAdmin only.')
            return redirect('accounts:dashboard_redirect')
        return view_func(request, *args, **kwargs)
    return wrapper


def _marketing_can_view(job, user):
    """Check if a marketing user can see/download generated content."""
    if getattr(user, 'role', '').upper() != 'MARKETING':
        return True
    if job.created_by != user:
        return False
    try:
        ai_report_exists = bool(job.ai_report)
    except Exception:
        ai_report_exists = False
    pipeline_done = (job.status or '').upper() in PIPELINE_DONE_STATUSES or ai_report_exists
    try:
        full_content_obj = job.full_content
    except Exception:
        full_content_obj = None
    access_setting = ContentAccessSetting.for_user(user)
    approval_only = bool(access_setting and access_setting.mode == ContentAccessSetting.MODE_APPROVAL_ONLY)
    release_unlocked = (
        (False if approval_only else bool(getattr(job, 'payment_slip', None)))
        or bool(getattr(full_content_obj, 'is_approved', False))
        or (job.status or '').upper() in {'APPROVED', 'COMPLETED'}
    )
    return pipeline_done and release_unlocked



@login_required
@superadmin_required
def generate_job_summary_view(request, job_id):
    """Generate or regenerate job summary"""
    job = get_object_or_404(Job, id=job_id)
    
    # Check if summary exists (property may return None)
    job_summary = getattr(job, 'summary', None)
    if job_summary:
        if job_summary.regeneration_count >= 3:
            messages.error(request, 'Maximum regeneration limit (3) reached for Job Summary.')
            return redirect('superadmin:new_jobs')
        job_summary.regeneration_count += 1
    else:
        job_summary = JobSummary(job=job)
    

    # Generate summary
    summary_data, error = generate_job_summary(job)

    if error or not summary_data:
        messages.error(request, error or 'Failed to generate Job Summary.')
        return redirect('superadmin:new_jobs')

    # ---- Safely pull values out ----
    topic = summary_data.get('topic') or ''
    reference_style = summary_data.get('reference_style') or 'Harvard'
    writing_style = summary_data.get('writing_style') or 'Academic'
    summary_text = summary_data.get('summary') or ''

    raw_word_count = summary_data.get('word_count', 0)

    # Make sure word_count is always numeric
    try:
        word_count = int(raw_word_count)
    except (TypeError, ValueError):
        # Fallback: compute from summary text or default 0
        word_count = len(summary_text.split()) if summary_text else 0

    # ---- Save summary ----
    job_summary.topic = topic
    job_summary.word_count = word_count
    job_summary.reference_style = reference_style
    job_summary.writing_style = writing_style
    job_summary.summary_text = summary_text
    job_summary.save()

    log_action(
        request.user,
        'GENERATE',
        job_summary,
        f'Generated Job Summary for {job.job_id}',
    )

    messages.success(request, 'Job Summary generated successfully!')
    return redirect('superadmin:new_jobs')


@login_required
@superadmin_required
def approve_job_summary(request, job_id):
    """Approve job summary"""
    job = get_object_or_404(Job, id=job_id)
    job_summary = get_object_or_404(JobSummary, job=job)
    
    job_summary.is_approved = True
    job_summary.approved_by = request.user
    job_summary.approved_at = timezone.now()
    job_summary.save()

    sync_job_status(job)
    
    log_action(request.user, 'APPROVE', job_summary, 
              f'Approved Job Summary for {job.job_id}')
    
    messages.success(request, 'Job Summary approved!')
    return redirect('superadmin:new_jobs')

@login_required
@superadmin_required
def generate_job_structure_view(request, job_id):
    """Generate or regenerate job structure"""
    job = get_object_or_404(Job, id=job_id)
    
    # Must have approved summary first
    try:
        job_summary = job.summary
        if not job_summary.is_approved:
            messages.error(request, 'Please approve Job Summary first.')
            return redirect('superadmin:new_jobs')
    except JobSummary.DoesNotExist:
        messages.error(request, 'Please generate Job Summary first.')
        return redirect('superadmin:new_jobs')
    
    # Check if structure exists
    try:
        job_structure = job.structure
        if job_structure.regeneration_count >= 3:
            messages.error(request, 'Maximum regeneration limit (3) reached for Job Structure.')
            return redirect('superadmin:new_jobs')
        job_structure.regeneration_count += 1
    except JobStructure.DoesNotExist:
        job_structure = JobStructure(job=job)
    
    structure_payload = (
        f"Topic: {job_summary.topic}; "
        f"Word Count: {job_summary.word_count}; "
        f"Reference Style: {job_summary.reference_style}; "
        f"Writing Style: {job_summary.writing_style}; "
        f"Job Summary: {job_summary.summary_text}"
    )
    structure_text, error = generate_job_structure(structure_payload)

    if structure_text and not error:
        job_structure.structure_text = structure_text
        job_structure.total_word_count = job_summary.word_count
        job_structure.save()

        log_action(request.user, 'GENERATE', job_structure, 
                  f'Generated Job Structure for {job.job_id}')

        messages.success(request, 'Job Structure generated successfully!')
    else:
        messages.error(request, error or 'Failed to generate Job Structure.')

    return redirect('superadmin:new_jobs')

@login_required
@superadmin_required
def approve_job_structure(request, job_id):
    """Approve job structure"""
    job = get_object_or_404(Job, id=job_id)
    job_structure = get_object_or_404(JobStructure, job=job)
    
    job_structure.is_approved = True
    job_structure.approved_by = request.user
    job_structure.approved_at = timezone.now()
    job_structure.save()

    sync_job_status(job)
    
    log_action(request.user, 'APPROVE', job_structure, 
              f'Approved Job Structure for {job.job_id}')
    
    messages.success(request, 'Job Structure approved!')
    return redirect('superadmin:new_jobs')

@login_required
@superadmin_required
def generate_content_view(request, job_id):
    """Generate or regenerate content"""
    job = get_object_or_404(Job, id=job_id)
    
    # Must have approved structure first
    try:
        job_structure = job.structure
        if not job_structure.is_approved:
            messages.error(request, 'Please approve Job Structure first.')
            return redirect('superadmin:new_jobs')
    except JobStructure.DoesNotExist:
        messages.error(request, 'Please generate Job Structure first.')
        return redirect('superadmin:new_jobs')
    
    # Check if content exists
    try:
        content = job.content
        if content.regeneration_count >= 3:
            messages.error(request, 'Maximum regeneration limit (3) reached for Content.')
            return redirect('superadmin:new_jobs')
        content.regeneration_count += 1
    except GeneratedContent.DoesNotExist:
        content = GeneratedContent(job=job)
    
    # Generate content
    content_text, error = generate_content(job_structure.structure_text)

    if content_text and not error:
        content.content_text = content_text
        content.save()
        
        log_action(request.user, 'GENERATE', content, 
                  f'Generated Content for {job.job_id}')
        
        messages.success(request, 'Content generated successfully!')
    else:
        messages.error(request, error or 'Failed to generate Content.')

    return redirect('superadmin:new_jobs')

@login_required
@superadmin_required
def approve_content(request, job_id):
    """Approve content"""
    job = get_object_or_404(Job, id=job_id)
    content = get_object_or_404(GeneratedContent, job=job)
    
    content.is_approved = True
    content.approved_by = request.user
    content.approved_at = timezone.now()
    content.save()

    sync_job_status(job)

    job.status = 'CONTENT'
    job.save(update_fields=['status'])
    
    log_action(request.user, 'APPROVE', content, 
              f'Approved Content for {job.job_id}')
    
    messages.success(request, 'Content approved!')
    return redirect('superadmin:new_jobs')

@login_required
@superadmin_required
def generate_references_view(request, job_id):
    """Generate or regenerate references"""
    job = get_object_or_404(Job, id=job_id)
    
    # Must have approved content first
    try:
        content = job.content
        if not content.is_approved:
            messages.error(request, 'Please approve Content first.')
            return redirect('superadmin:new_jobs')
        job_summary = job.summary
    except (GeneratedContent.DoesNotExist, JobSummary.DoesNotExist):
        messages.error(request, 'Please generate required components first.')
        return redirect('superadmin:new_jobs')
    
    # Check if references exist
    try:
        references = job.references
        if references.regeneration_count >= 3:
            messages.error(request, 'Maximum regeneration limit (3) reached for References.')
            return redirect('superadmin:new_jobs')
        references.regeneration_count += 1
    except References.DoesNotExist:
        references = References(job=job)
    
    # Generate references
    ref_data, error = generate_references(
        content.content_text,
        job_summary.reference_style,
        job_summary.word_count
    )
    
    if ref_data and not error:
        references.reference_list = ref_data['reference_list']
        references.citation_list = ref_data['citation_list']
        references.save()
        
        log_action(request.user, 'GENERATE', references, 
                  f'Generated References for {job.job_id}')
        
        messages.success(request, 'References generated successfully!')
    else:
        messages.error(request, error or 'Failed to generate References.')

    return redirect('superadmin:new_jobs')

@login_required
@superadmin_required
def approve_references(request, job_id):
    """Approve references"""
    job = get_object_or_404(Job, id=job_id)
    references = get_object_or_404(References, job=job)
    
    references.is_approved = True
    references.approved_by = request.user
    references.approved_at = timezone.now()
    references.save()

    sync_job_status(job)

    job.status = 'REFERENCES'
    job.save(update_fields=['status'])
    
    log_action(request.user, 'APPROVE', references, 
              f'Approved References for {job.job_id}')
    
    messages.success(request, 'References approved!')
    return redirect('superadmin:new_jobs')

@login_required
@superadmin_required
def generate_full_content_view(request, job_id):
    """Generate or regenerate full content with citations"""
    job = get_object_or_404(Job, id=job_id)
    
    # Must have all previous components approved
    try:
        content = job.content
        references = job.references
        job_summary = job.summary
        
        if not (content.is_approved and references.is_approved):
            messages.error(request, 'Please approve Content and References first.')
            return redirect('superadmin:new_jobs')
    except (GeneratedContent.DoesNotExist, References.DoesNotExist, JobSummary.DoesNotExist):
        messages.error(request, 'Please generate all required components first.')
        return redirect('superadmin:new_jobs')
    
    # Check if full content exists
    try:
        full_content = job.full_content
        if full_content.regeneration_count >= 3:
            messages.error(request, 'Maximum regeneration limit (3) reached for Full Content.')
            return redirect('superadmin:new_jobs')
        full_content.regeneration_count += 1
    except FullContent.DoesNotExist:
        full_content = FullContent(job=job)
    
    # Generate full content with citations
    full_text, error = generate_full_content_with_citations(
        content.content_text,
        references.reference_list,
        references.citation_list,
        job_summary.reference_style
    )
    
    if full_text and not error:
        full_content.content_with_citations = full_text
        full_content.final_word_count = len(full_text.split())
        full_content.save()
        
        log_action(request.user, 'GENERATE', full_content, 
                  f'Generated Full Content for {job.job_id}')
        
        messages.success(request, 'Full Content generated successfully!')
    else:
        messages.error(request, error or 'Failed to generate Full Content.')

    return redirect('superadmin:new_jobs')

@login_required
@superadmin_required
def approve_full_content(request, job_id):
    """Approve full content"""
    job = get_object_or_404(Job, id=job_id)
    full_content = get_object_or_404(FullContent, job=job)
    
    full_content.is_approved = True
    full_content.approved_by = request.user
    full_content.approved_at = timezone.now()
    full_content.save()

    sync_job_status(job)
    
    log_action(request.user, 'APPROVE', full_content, 
              f'Approved Full Content for {job.job_id}')
    
    messages.success(request, 'Full Content approved! Job completed.')
    return redirect('superadmin:new_jobs')

@login_required
@superadmin_required
def generate_plagiarism_report(request, job_id):
    """Generate plagiarism report"""
    job = get_object_or_404(Job, id=job_id)
    
    try:
        full_content = job.full_content
        if not full_content.is_approved:
            messages.error(request, 'Please approve Full Content first.')
            return redirect('superadmin:new_jobs')
    except FullContent.DoesNotExist:
        messages.error(request, 'Please generate Full Content first.')
        return redirect('superadmin:new_jobs')
    
    # Generate or update plagiarism report
    plag_result, error = check_plagiarism(full_content.content_with_citations)

    if not plag_result or error:
        messages.error(request, error or 'Failed to generate plagiarism report.')
        return redirect('superadmin:new_jobs')

    plag_report, created = PlagiarismReport.objects.get_or_create(job=job)
    plag_report.report_data = plag_result['report']
    plag_report.similarity_percentage = plag_result['similarity_percentage']
    plag_report.is_approved = True
    plag_report.generation_count = (plag_report.generation_count or 0) + 1
    plag_report.save()

    sync_job_status(job)
    
    messages.success(request, 'Plagiarism Report generated!')
    return redirect('superadmin:new_jobs')

@login_required
@superadmin_required
def generate_ai_report(request, job_id):
    """Generate AI content report"""
    job = get_object_or_404(Job, id=job_id)
    
    try:
        full_content = job.full_content
        if not full_content.is_approved:
            messages.error(request, 'Please approve Full Content first.')
            return redirect('superadmin:new_jobs')
    except FullContent.DoesNotExist:
        messages.error(request, 'Please generate Full Content first.')
        return redirect('superadmin:new_jobs')
    
    # Generate or update AI report
    ai_result, error = check_ai_content(full_content.content_with_citations)

    if not ai_result or error:
        messages.error(request, error or 'Failed to generate AI report.')
        return redirect('superadmin:new_jobs')

    ai_report, created = AIReport.objects.get_or_create(job=job)
    ai_report.report_data = ai_result['report']
    ai_report.ai_percentage = ai_result['ai_percentage']
    ai_report.is_approved = True
    ai_report.generation_count = (ai_report.generation_count or 0) + 1
    ai_report.save()

    sync_job_status(job)
    
    messages.success(request, 'AI Report generated!')
    return redirect('superadmin:new_jobs')

@login_required
def view_generated_content(request, job_id, content_type):
    """View generated content (AJAX endpoint)"""
    job = get_object_or_404(Job, id=job_id)

    if not _marketing_can_view(job, request.user):
        return JsonResponse(
            {'error': 'Content locked until payment slip is uploaded and AI steps finish.'},
            status=403,
        )
    
    content_data = {}
    
    try:
        if content_type == 'summary':
            obj = job.summary
            content_data = {
                'topic': obj.topic,
                'word_count': obj.word_count,
                'reference_style': obj.reference_style,
                'writing_style': obj.writing_style,
                'content': obj.summary_text,
                'is_approved': obj.is_approved,
                'regeneration_count': obj.regeneration_count
            }
        elif content_type == 'structure':
            obj = job.structure
            content_data = {
                'content': obj.structure_text,
                'is_approved': obj.is_approved,
                'regeneration_count': obj.regeneration_count
            }
        elif content_type == 'content':
            obj = job.content
            content_data = {
                'content': obj.content_text,
                'is_approved': obj.is_approved,
                'regeneration_count': obj.regeneration_count
            }
        elif content_type == 'references':
            obj = job.references
            content_data = {
                'reference_list': obj.reference_list,
                'citation_list': obj.citation_list,
                'is_approved': obj.is_approved,
                'regeneration_count': obj.regeneration_count
            }
        elif content_type == 'full_content':
            obj = job.full_content
            content_data = {
                'content': obj.content_with_citations,
                'is_approved': obj.is_approved,
                'regeneration_count': obj.regeneration_count
            }
        elif content_type == 'plag_report':
            obj = job.plag_report
            content_data = {
                'content': obj.report_data,
                'similarity': obj.similarity_percentage
            }
        elif content_type == 'ai_report':
            obj = job.ai_report
            content_data = {
                'content': obj.report_data,
                'ai_percentage': obj.ai_percentage
            }
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=404)
    
    return JsonResponse(content_data)


@login_required
@superadmin_required
def ai_content_view(request, job_id, content_type):
    """View AI generated content"""
    job = get_object_or_404(Job, job_id=job_id)
    
    content = None
    template_name = 'ai_pipeline/view_content.html'
    
    if content_type == 'summary':
        content = getattr(job, 'job_summary', None)
    elif content_type == 'structure':
        content = getattr(job, 'job_structure', None)
    elif content_type == 'content':
        content = getattr(job, 'generated_content', None)
    elif content_type == 'references':
        content = getattr(job, 'references', None)
    elif content_type == 'plagiarism':
        content = getattr(job, 'plagiarism_report', None)
    elif content_type == 'ai_report':
        content = getattr(job, 'ai_report', None)
    elif content_type == 'full_content':
        content = getattr(job, 'full_content', None)
    
    if not content:
        messages.error(request, f'{content_type.title()} has not been generated yet.')
        return redirect('superadmin:new_jobs')
    
    # Log the action
    log_job_action(
        job_id=job.job_id,
        system_id=job.system_id,
        user=request.user,
        action=f'VIEWED_{content_type.upper()}'
    )
    
    context = {
        'job': job,
        'content': content,
        'content_type': content_type,
    }
    
    return render(request, template_name, context)


@login_required
@superadmin_required
def ai_content_regenerate(request, job_id, content_type):
    """Regenerate AI content using the same logic as the step-by-step views."""
    job = get_object_or_404(Job, job_id=job_id)

    view_map = {
        'summary': generate_job_summary_view,
        'structure': generate_job_structure_view,
        'content': generate_content_view,
        'references': generate_references_view,
        'full_content': generate_full_content_view,
        'plagiarism': generate_plagiarism_report,
        'ai_report': generate_ai_report,
    }

    if content_type not in view_map:
        messages.error(request, 'Invalid content type.')
        return redirect('superadmin:new_jobs')

    return view_map[content_type](request, job.id)


@login_required
@superadmin_required
def ai_content_approve(request, job_id, content_type):
    """Approve AI generated content"""
    job = get_object_or_404(Job, job_id=job_id)
    
    content_map = {
        'summary': 'job_summary',
        'structure': 'job_structure',
        'content': 'generated_content',
        'references': 'references',
        'plagiarism': 'plagiarism_report',
        'ai_report': 'ai_report',
        'full_content': 'full_content',
    }
    
    if content_type not in content_map:
        messages.error(request, 'Invalid content type.')
        return redirect('superadmin:new_jobs')
    
    attr_name = content_map[content_type]
    content_obj = getattr(job, attr_name, None)
    
    if not content_obj:
        messages.error(request, f'{content_type.title()} has not been generated yet.')
        return redirect('superadmin:new_jobs')
    
    if content_obj.is_approved:
        messages.warning(request, f'{content_type.title()} is already approved.')
        return redirect('superadmin:new_jobs')
    
    # Approve content
    content_obj.is_approved = True
    content_obj.approved_by = request.user
    content_obj.approved_at = timezone.now()
    content_obj.save()
    
    # Log the action  âœ… FIXED
    log_action(
        request.user,
        'AI_APPROVAL',
        content_obj,
        f'Approved {content_type} for job {job.job_id}',
    )
    
    log_job_action(
        job_id=job.job_id,
        system_id=job.system_id,
        user=request.user,
        action=f'APPROVED_{content_type.upper()}'
    )
    
    messages.success(request, f'{content_type.title()} approved successfully!')
    
    def _is_approved(attr_name):
        obj = getattr(job, attr_name, None)
        return bool(obj and obj.is_approved)

    # Check if all content is approved, then approve the job
    if all([
        _is_approved('job_summary'),
        _is_approved('job_structure'),
        _is_approved('generated_content'),
        _is_approved('references'),
        _is_approved('plagiarism_report'),
        _is_approved('ai_report'),
        _is_approved('full_content'),
    ]):
        job.is_approved = True
        job.approved_by = request.user
        job.approved_at = timezone.now()
        job.status = 'APPROVED'
        job.save()
        
        messages.success(request, f'All content approved! Job {job.job_id} is now fully approved.')

    sync_job_status(job)

    return redirect('superadmin:new_jobs')


@login_required
@superadmin_required
def generate_all_content(request, job_id):
    """Generate all AI content in sequence"""
    job = get_object_or_404(Job, job_id=job_id)
    
    results = []
    errors = []
    
    # Generate in sequence
    steps = [
        ('Job Summary', generate_job_summary),
        ('Job Structure', generate_job_structure),
        ('Content', generate_content),
        ('References', generate_references),
        ('Full Content', generate_all_content),
        ('Plagiarism Report', generate_plagiarism_report),
        ('AI Report', generate_ai_report),
    ]
    
    for step_name, generate_func in steps:
        try:
            result, error = generate_func(job)
            if result:
                results.append(f'{step_name} generated successfully')
            else:
                errors.append(f'{step_name}: {error}')
                break  # Stop on first error
        except Exception as e:
            errors.append(f'{step_name}: {str(e)}')
            break
    
    # Log the action  âœ… FIXED
    log_action(
        request.user,
        'AI_GENERATION',
        job,
        f'Generated all content for job {job.job_id}. Success: {len(results)}, Errors: {len(errors)}',
    )
    
    if errors:
        messages.error(request, f'Generation stopped with errors: {", ".join(errors)}')
    else:
        messages.success(request, f'All content generated successfully for job {job.job_id}!')
    
    return redirect('superadmin:new_jobs')


@login_required
def download_content(request, job_id, content_type):
    """Download content as file"""
    job = get_object_or_404(Job, job_id=job_id)
    role_upper = (request.user.role or '').upper()
    
    # Check permissions
    if role_upper == 'MARKETING' and job.created_by != request.user:
        messages.error(request, 'Access denied.')
        return redirect('marketing:all_projects')
    if not _marketing_can_view(job, request.user):
        messages.error(request, 'Content locked. Upload a payment slip or wait for approval.')
        return redirect('marketing:all_projects')
    
    content_text = ""
    filename = f"{job.job_id}_{content_type}.txt"
    allow_unapproved = role_upper == 'SUPERADMIN' or _marketing_can_view(job, request.user)
    
    if content_type == 'summary':
        if hasattr(job, 'job_summary') and (job.job_summary.is_approved or allow_unapproved):
            content_text = job.job_summary.summary_text
    elif content_type == 'structure':
        if hasattr(job, 'job_structure') and (job.job_structure.is_approved or allow_unapproved):
            content_text = job.job_structure.structure_text
    elif content_type == 'content':
        if hasattr(job, 'generated_content') and (job.generated_content.is_approved or allow_unapproved):
            content_text = job.generated_content.content_text
    elif content_type == 'references':
        if hasattr(job, 'references') and (job.references.is_approved or allow_unapproved):
            content_text = f"REFERENCE LIST:\n\n{job.references.reference_list}\n\n\nCITATION LIST:\n\n{job.references.citation_list}"
    elif content_type == 'plagiarism':
        if hasattr(job, 'plagiarism_report') and (job.plagiarism_report.is_approved or allow_unapproved):
            content_text = job.plagiarism_report.report_data
    elif content_type == 'ai_report':
        if hasattr(job, 'ai_report') and (job.ai_report.is_approved or allow_unapproved):
            content_text = job.ai_report.report_data
    elif content_type == 'full_content':
        if hasattr(job, 'full_content'):
            content_text = job.full_content.content_with_citations
    
    if not content_text:
        messages.error(request, 'Content not available or not approved yet.')
        return redirect('accounts:dashboard_redirect')
    
    # Create response
    response = HttpResponse(content_text, content_type='text/plain')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    # Log download
    log_job_action(
        job_id=job.job_id,
        system_id=job.system_id,
        user=request.user,
        action=f'DOWNLOADED_{content_type.upper()}'
    )
    
    return response
