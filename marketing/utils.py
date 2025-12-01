from datetime import datetime
from django.utils import timezone


def parse_date_param(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def collect_marketing_filters(request):
    raw = {
        "search": (request.GET.get("search") or "").strip(),
        "status": (request.GET.get("status") or "").strip().upper(),
        "subcategory": (request.GET.get("subcategory") or "").strip(),
        "date_field": (request.GET.get("date_field") or "expected").strip().lower(),
        "date_from": (request.GET.get("date_from") or "").strip(),
        "date_to": (request.GET.get("date_to") or "").strip(),
    }
    if raw["date_field"] not in ("expected", "strict"):
        raw["date_field"] = "expected"

    normalized = {
        "search": raw["search"].lower(),
        "status": raw["status"],
        "subcategory": raw["subcategory"].lower(),
        "date_field": raw["date_field"],
        "date_from": parse_date_param(raw["date_from"]),
        "date_to": parse_date_param(raw["date_to"]),
    }
    return raw, normalized


def job_matches_marketing_filters(job, filters):
    summary = getattr(job, "summary", None)

    def contains(value, needle):
        return needle in (value or "").lower()

    if filters["search"]:
        search_fields = [
            job.job_id,
            job.system_id,
            getattr(job, "instruction", ""),
            getattr(summary, "topic", None),
            getattr(summary, "summary_text", None),
        ]
        if not any(contains(field, filters["search"]) for field in search_fields):
            return False

    if filters["subcategory"]:
        sub_fields = [
            getattr(job, "instruction", ""),
            getattr(summary, "summary_text", None),
            getattr(summary, "writing_style", None),
        ]
        if not any(contains(field, filters["subcategory"]) for field in sub_fields):
            return False

    if filters["status"] and (job.status or "").upper() != filters["status"]:
        return False

    date_from = filters["date_from"]
    date_to = filters["date_to"]
    if date_from or date_to:
        deadline = job.expected_deadline if filters["date_field"] == "expected" else job.strict_deadline
        if not deadline:
            return False
        deadline_date = timezone.localtime(deadline).date() if timezone.is_aware(deadline) else deadline.date()
        if date_from and deadline_date < date_from:
            return False
        if date_to and deadline_date > date_to:
            return False

    return True

