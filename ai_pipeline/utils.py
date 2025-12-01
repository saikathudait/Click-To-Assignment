"""
Helpers shared across the AI pipeline.

Historically this module only re-exported functions from ``ai_pipeline.services``.
It now also provides utility helpers (e.g., status synchronisation) that are used
by multiple views.
"""

from django.utils import timezone

from auditlog.utils import log_action

from .models import (
    AIReport,
    FullContent,
    GeneratedContent,
    JobStructure,
    JobSummary,
    PlagiarismReport,
    References,
)
from .services import (  # noqa: F401
    check_ai_content,
    check_plagiarism,
    generate_content,
    generate_full_content_with_citations,
    generate_job_structure,
    generate_job_summary,
    generate_references,
)

MARKETING_GENERATION_LIMIT = 3

PIPELINE_STATUS_ORDER = [
    ("summary", "JOB_SUMMARY"),
    ("structure", "JOB_STRUCTURE"),
    ("content", "CONTENT"),
    ("references", "REFERENCES"),
    ("full_content", "FULL_CONTENT"),
    ("plag_report", "PLAGIARISM_REPORT"),
    ("ai_report", "AI_REPORT"),
]

# Keep the status sequence monotonic so we never move a job backwards.
STATUS_SEQUENCE = [
    "PENDING",
    "IN_PROGRESS",
    "JOB_SUMMARY",
    "JOB_STRUCTURE",
    "CONTENT",
    "REFERENCES",
    "FULL_CONTENT",
    "PLAGIARISM_REPORT",
    "AI_REPORT",
    "REWORK",
    "REWORK_COMPLETED",
    "COMPLETED",
    "APPROVED",
]

STATUS_RANK = {name: idx for idx, name in enumerate(STATUS_SEQUENCE)}
TERMINAL_STATUSES = {"REJECTED"}


def _max_status(current: str, candidate: str) -> str:
    """Return the furthest-progress status between two values."""
    current_rank = STATUS_RANK.get((current or "").upper(), -1)
    candidate_rank = STATUS_RANK.get((candidate or "").upper(), -1)
    return candidate if candidate_rank > current_rank else current


def sync_job_status(job, save=True):
    """
    Ensure the ``job.status`` field reflects the furthest approved AI component.

    This keeps legacy jobs (generated before status tracking was extended) in
    sync with the new workflow and guarantees future operations stay consistent.
    """
    status_upper = (job.status or "PENDING").upper()

    if status_upper in TERMINAL_STATUSES:
        return job.status

    # Start from the current status so we never downgrade progress.
    new_status = status_upper if status_upper in STATUS_RANK else "PENDING"

    # Advance based on approved artifacts.
    for attr_name, status in PIPELINE_STATUS_ORDER:
        obj = getattr(job, attr_name, None)
        if obj and getattr(obj, "is_approved", False):
            new_status = _max_status(new_status, status)

    if getattr(job, "is_approved", False):
        new_status = "APPROVED"

    if job.status != new_status:
        job.status = new_status
        if save:
            job.save(update_fields=["status"])

    return new_status


def get_regeneration_usage(job):
    """
    Return the highest regeneration/generation count across pipeline artifacts.
    This is used to enforce the marketing-side regeneration cap.
    """
    counts = []
    for attr_name in (
        "summary",
        "job_structure",
        "generated_content",
        "references",
        "full_content",
        "plagiarism_report",
        "ai_report",
    ):
        try:
            obj = getattr(job, attr_name)
        except Exception:
            obj = None
        if not obj:
            continue
        count = getattr(obj, "regeneration_count", getattr(obj, "generation_count", 0)) or 0
        counts.append(count)
    return max(counts) if counts else 0


def run_marketing_pipeline(job, actor):
    """
    Sequentially generate all AI artifacts for a job on behalf of Marketing.

    Intermediate steps are auto-approved so the pipeline can continue without
    SuperAdmin intervention. The final Full Content remains unapproved so it
    can be reviewed/approved by SuperAdmin.
    """
    results = []

    def _fail(message):
        return {"success": False, "results": results, "error": message}

    def _set_status(status_value):
        job.status = status_value
        job.save(update_fields=["status"])

    if get_regeneration_usage(job) >= MARKETING_GENERATION_LIMIT:
        return _fail(f"Generation limit reached ({MARKETING_GENERATION_LIMIT} regenerations used).")

    # --- Job Summary ---
    job_summary = getattr(job, "summary", None)
    if job_summary:
        if not job_summary.can_regenerate():
            return _fail("Generation limit reached for Job Summary.")
        job_summary.regeneration_count = (job_summary.regeneration_count or 0) + 1
    else:
        job_summary = JobSummary(job=job)

    summary_data, error = generate_job_summary(job)
    if error or not summary_data:
        return _fail(error or "Failed to generate Job Summary.")

    summary_text = summary_data.get("summary") or ""
    raw_word_count = summary_data.get("word_count", 0)
    try:
        word_count = int(raw_word_count)
    except (TypeError, ValueError):
        word_count = len(summary_text.split()) if summary_text else 0

    job_summary.topic = summary_data.get("topic") or ""
    job_summary.word_count = word_count
    job_summary.reference_style = summary_data.get("reference_style") or "Harvard"
    job_summary.writing_style = summary_data.get("writing_style") or "Academic"
    job_summary.summary_text = summary_text
    job_summary.is_approved = True
    job_summary.approved_by = actor
    job_summary.approved_at = timezone.now()
    job_summary.save()
    log_action(actor, "GENERATE", job_summary, f"Generated Job Summary for {job.job_id}")
    _set_status("JOB_SUMMARY")
    results.append("Job Summary generated")

    # --- Job Structure ---
    structure_payload = (
        f"Topic: {job_summary.topic}; "
        f"Word Count: {job_summary.word_count}; "
        f"Reference Style: {job_summary.reference_style}; "
        f"Writing Style: {job_summary.writing_style}; "
        f"Job Summary: {job_summary.summary_text}"
    )
    job_structure = getattr(job, "job_structure", None)
    if job_structure:
        if not job_structure.can_regenerate():
            return _fail("Generation limit reached for Job Structure.")
        job_structure.regeneration_count = (job_structure.regeneration_count or 0) + 1
    else:
        job_structure = JobStructure(job=job)

    structure_text, error = generate_job_structure(structure_payload)
    if error or not structure_text:
        return _fail(error or "Failed to generate Job Structure.")

    job_structure.structure_text = structure_text
    job_structure.total_word_count = job_summary.word_count
    job_structure.is_approved = True
    job_structure.approved_by = actor
    job_structure.approved_at = timezone.now()
    job_structure.save()
    log_action(actor, "GENERATE", job_structure, f"Generated Job Structure for {job.job_id}")
    _set_status("JOB_STRUCTURE")
    results.append("Job Structure generated")

    # --- Content ---
    content_obj = getattr(job, "generated_content", None)
    if content_obj:
        if not content_obj.can_regenerate():
            return _fail("Generation limit reached for Content.")
        content_obj.regeneration_count = (content_obj.regeneration_count or 0) + 1
    else:
        content_obj = GeneratedContent(job=job)

    content_text, error = generate_content(job_structure.structure_text)
    if error or not content_text:
        return _fail(error or "Failed to generate Content.")

    content_obj.content_text = content_text
    content_obj.is_approved = True
    content_obj.approved_by = actor
    content_obj.approved_at = timezone.now()
    content_obj.save()
    log_action(actor, "GENERATE", content_obj, f"Generated Content for {job.job_id}")
    _set_status("CONTENT")
    results.append("Content generated")

    # --- References ---
    try:
        references_obj = job.references
        if references_obj:
            if not references_obj.can_regenerate():
                return _fail("Generation limit reached for References.")
            references_obj.regeneration_count = (references_obj.regeneration_count or 0) + 1
    except Exception:
        references_obj = References(job=job)

    ref_data, error = generate_references(
        content_obj.content_text,
        job_summary.reference_style,
        job_summary.word_count,
    )
    if error or not ref_data:
        return _fail(error or "Failed to generate References.")

    references_obj.reference_list = ref_data.get("reference_list", "")
    references_obj.citation_list = ref_data.get("citation_list", "")
    references_obj.is_approved = True
    references_obj.approved_by = actor
    references_obj.approved_at = timezone.now()
    references_obj.save()
    log_action(actor, "GENERATE", references_obj, f"Generated References for {job.job_id}")
    _set_status("REFERENCES")
    results.append("References generated")

    # --- Full Content (awaits SuperAdmin approval) ---
    try:
        full_content_obj = job.full_content
        if full_content_obj:
            if not full_content_obj.can_regenerate():
                return _fail("Generation limit reached for Full Content.")
            full_content_obj.regeneration_count = (full_content_obj.regeneration_count or 0) + 1
    except Exception:
        full_content_obj = FullContent(job=job)

    full_text, error = generate_full_content_with_citations(
        content_obj.content_text,
        references_obj.reference_list,
        references_obj.citation_list,
        job_summary.reference_style,
    )
    if error or not full_text:
        return _fail(error or "Failed to generate Full Content.")

    full_content_obj.content_with_citations = full_text
    full_content_obj.final_word_count = len(full_text.split())
    full_content_obj.save()
    log_action(actor, "GENERATE", full_content_obj, f"Generated Full Content for {job.job_id}")
    _set_status("FULL_CONTENT")
    results.append("Full Content generated")

    # --- Plagiarism Report ---
    try:
        plag_report_obj = job.plag_report
        if not plag_report_obj.can_regenerate():
            return _fail("Generation limit reached for Plagiarism Report.")
        plag_report_obj.generation_count = (plag_report_obj.generation_count or 0) + 1
    except Exception:
        plag_report_obj = PlagiarismReport(job=job)

    plag_result, error = check_plagiarism(full_content_obj.content_with_citations)
    if error or not plag_result:
        return _fail(error or "Failed to generate Plagiarism Report.")

    plag_report_obj.report_data = plag_result.get("report", "")
    plag_report_obj.similarity_percentage = plag_result.get("similarity_percentage", 0.0)
    plag_report_obj.is_approved = True
    plag_report_obj.approved_by = actor
    plag_report_obj.approved_at = timezone.now()
    plag_report_obj.save()
    log_action(actor, "GENERATE", plag_report_obj, f"Generated Plagiarism Report for {job.job_id}")
    _set_status("PLAGIARISM_REPORT")
    results.append("Plagiarism report generated")

    # --- AI Report ---
    try:
        ai_report_obj = job.ai_report
        if not ai_report_obj.can_regenerate():
            return _fail("Generation limit reached for AI Report.")
        ai_report_obj.generation_count = (ai_report_obj.generation_count or 0) + 1
    except Exception:
        ai_report_obj = AIReport(job=job)

    ai_result, error = check_ai_content(full_content_obj.content_with_citations)
    if error or not ai_result:
        return _fail(error or "Failed to generate AI Report.")

    ai_report_obj.report_data = ai_result.get("report", "")
    ai_report_obj.ai_percentage = ai_result.get("ai_percentage", 0.0)
    ai_report_obj.is_approved = True
    ai_report_obj.approved_by = actor
    ai_report_obj.approved_at = timezone.now()
    ai_report_obj.save()
    log_action(actor, "GENERATE", ai_report_obj, f"Generated AI Report for {job.job_id}")
    _set_status("AI_REPORT")
    results.append("AI report generated")

    sync_job_status(job)
    return {"success": True, "results": results, "error": None}


__all__ = [
    "generate_job_summary",
    "generate_job_structure",
    "generate_content",
    "generate_references",
    "generate_full_content_with_citations",
    "check_plagiarism",
    "check_ai_content",
    "sync_job_status",
    "run_marketing_pipeline",
    "get_regeneration_usage",
    "MARKETING_GENERATION_LIMIT",
]
