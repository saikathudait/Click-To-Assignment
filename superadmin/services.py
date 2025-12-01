import csv
import io
import json
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Dict, Iterable, List, Sequence
from xml.sax.saxutils import escape

from django.apps import apps
from django.conf import settings
from django.core.exceptions import FieldDoesNotExist
from django.db import DatabaseError, models
from django.utils import timezone
from django.utils.text import slugify

from .models import Announcement, AnnouncementReceipt

ANNOUNCEMENT_STATUS_LABELS = {
    Announcement.STATUS_ACTIVE: 'Active',
    Announcement.STATUS_SCHEDULED: 'Scheduled',
    Announcement.STATUS_EXPIRED: 'Expired',
    Announcement.STATUS_INACTIVE: 'Inactive',
}

ANNOUNCEMENT_STATUS_BADGES = {
    Announcement.STATUS_ACTIVE: 'bg-success',
    Announcement.STATUS_SCHEDULED: 'bg-info text-dark',
    Announcement.STATUS_EXPIRED: 'bg-secondary',
    Announcement.STATUS_INACTIVE: 'bg-dark',
}

ANNOUNCEMENT_TYPE_BADGES = {
    Announcement.TYPE_INFO: 'bg-primary',
    Announcement.TYPE_WARNING: 'bg-warning text-dark',
    Announcement.TYPE_UPDATE: 'bg-info text-dark',
}


def get_visible_announcements_for_user(user) -> List[Announcement]:
    """
    Return announcements that should be shown to the authenticated user.
    Ensures receipts are marked as seen and filters out dismissed entries.
    """
    if not getattr(user, 'is_authenticated', False):
        return []

    role = getattr(user, 'role', None)
    now = timezone.now()

    try:
        raw_candidates = Announcement.objects.select_related('created_by').order_by('-start_at', '-created_at')
        candidates = []
        for announcement in raw_candidates:
            if not getattr(announcement, 'pk', None):
                continue
            if announcement.is_for_role(role) and announcement.is_visible_now(now):
                candidates.append(announcement)
        if not candidates:
            return []

        announcement_ids = [announcement.pk for announcement in candidates]
        receipts = {
            receipt.announcement_id: receipt
            for receipt in AnnouncementReceipt.objects.filter(
                user=user,
                announcement_id__in=announcement_ids,
            )
        }

        visible_announcements = []
        for announcement in candidates:
            receipt = receipts.get(announcement.pk)
            if receipt and receipt.dismissed_at:
                continue
            if receipt:
                receipt.mark_seen()
            else:
                receipt = AnnouncementReceipt.objects.create(
                    announcement=announcement,
                    user=user,
                    seen_at=now,
                )
            announcement.user_receipt = receipt
            announcement.current_status = announcement.status(now)
            announcement.status_label = ANNOUNCEMENT_STATUS_LABELS.get(
                announcement.current_status,
                announcement.current_status,
            )
            announcement.status_badge_class = ANNOUNCEMENT_STATUS_BADGES.get(
                announcement.current_status,
                'bg-secondary',
            )
            announcement.type_badge_class = ANNOUNCEMENT_TYPE_BADGES.get(
                announcement.type,
                'bg-secondary',
            )
            visible_announcements.append(announcement)
        return visible_announcements
    except DatabaseError:
        return []


# Backup / export helpers
DEFAULT_BACKUP_APPS = getattr(
    settings,
    'BACKUP_EXPORT_APPS',
    [
        'accounts',
        'approvals',
        'ai_pipeline',
        'auditlog',
        'form_management',
        'holidays',
        'jobs',
        'marketing',
        'notifications',
        'permissions',
        'profiles',
        'superadmin',
        'tickets',
    ],
)


@dataclass
class BackupExportResult:
    filename: str
    content_type: str
    content: bytes


class BackupExportError(Exception):
    """Raised when backup/export generation fails."""


def get_exportable_model_metadata():
    """Return metadata for all models allowed in backups."""
    metadata = []
    for model in apps.get_models():
        if model._meta.proxy or model._meta.abstract:
            continue
        app_label = model._meta.app_label
        if DEFAULT_BACKUP_APPS and app_label not in DEFAULT_BACKUP_APPS:
            continue
        key = f'{app_label}.{model.__name__}'
        label = f"{model._meta.verbose_name_plural.title()}"
        try:
            record_count = model.objects.count()
        except Exception:
            record_count = None
        if record_count is None:
            count_label = 'count unavailable'
        else:
            count_label = f'{record_count} records'
        metadata.append({
            'key': key,
            'label': label,
            'app_label': app_label,
            'model': model,
            'count': record_count,
            'choice_label': f"{label} ({count_label})",
        })
    metadata.sort(key=lambda item: (item['app_label'], item['label']))
    return metadata


def generate_backup_export(
    selected_keys: Sequence[str],
    export_format: str,
    metadata_map: Dict[str, dict],
    start_date=None,
    end_date=None,
):
    """Create a CSV/Excel export for the selected models."""
    if not selected_keys:
        raise BackupExportError('No tables selected for export.')

    entries = []
    for key in selected_keys:
        meta = metadata_map.get(key)
        if not meta:
            continue
        model = meta['model']
        field_info = _get_model_fields(model)
        if not field_info:
            continue
        queryset = model.objects.all()
        transform = None
        if meta['app_label'] == 'jobs' and model.__name__ == 'Job':
            queryset = queryset.select_related(
                'created_by',
                'approved_by',
                'jobsummary__approved_by',
            )
            transform = _job_row_transform
        entries.append({
            'key': key,
            'label': meta['label'],
            'model': model,
            'queryset': queryset,
            'fields': field_info,
            'transform': transform,
        })

    if not entries:
        raise BackupExportError('No exportable data found for the selected tables.')

    timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')

    if export_format == 'csv':
        content = _export_tables_to_csv(entries, start_date, end_date)
        return BackupExportResult(
            filename=f'cta_backup_{timestamp}.zip',
            content_type='application/zip',
            content=content,
        )

    if export_format == 'xlsx':
        content = _export_tables_to_excel(entries, start_date, end_date)
        return BackupExportResult(
            filename=f'cta_backup_{timestamp}.xlsx',
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            content=content,
        )

    raise BackupExportError(f'Unsupported export format: {export_format}')


def _export_tables_to_csv(entries, start_date=None, end_date=None):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for entry in entries:
            csv_buffer = io.StringIO()
            writer = csv.DictWriter(csv_buffer, fieldnames=[field.name for field in entry['fields']])
            writer.writeheader()
            for row in _serialize_model_rows(
                entry['model'],
                entry['fields'],
                start_date,
                end_date,
                queryset=entry.get('queryset'),
                transform=entry.get('transform'),
            ):
                writer.writerow(row)
            archive.writestr(f"{_safe_filename(entry['label'])}.csv", csv_buffer.getvalue())
    buffer.seek(0)
    return buffer.read()


def _export_tables_to_excel(entries, start_date=None, end_date=None):
    try:
        from openpyxl import Workbook
    except ImportError:
        return _export_tables_to_excel_inline(entries, start_date, end_date)

    buffer = io.BytesIO()
    wb = Workbook()
    if wb.active:
        wb.remove(wb.active)

    for entry in entries:
        sheet_title = _safe_sheet_title(entry['label'])
        ws = wb.create_sheet(title=sheet_title)
        headers = [field.name for field in entry['fields']]
        ws.append(headers)
        for row in _serialize_model_rows(
            entry['model'],
            entry['fields'],
            start_date,
            end_date,
            queryset=entry.get('queryset'),
            transform=entry.get('transform'),
        ):
            ws.append([row.get(name) for name in headers])

    wb.save(buffer)
    buffer.seek(0)
    return buffer.read()


def _serialize_model_rows(model, fields, start_date=None, end_date=None, queryset=None, transform=None):
    queryset = queryset or model.objects.all()
    date_field = _detect_date_field(model)

    date_filtered_in_python = False
    if date_field and (start_date or end_date):
        queryset = list(queryset)
        date_filtered_in_python = True

    for obj in queryset:
        if date_filtered_in_python and not _matches_date_range(obj, date_field, start_date, end_date):
            continue
        row = {}
        for field in fields:
            value = _get_field_value(obj, field)
            row[field.name] = _normalize_value(value)
        if transform:
            row = transform(row, obj)
        yield row


def _get_model_fields(model):
    fields = []
    for field in model._meta.get_fields():
        if getattr(field, 'many_to_many', False):
            continue
        if getattr(field, 'one_to_many', False):
            continue
        if not getattr(field, 'concrete', False):
            continue
        fields.append(field)
    return fields


def _get_field_value(instance, field):
    if field.is_relation and (field.many_to_one or field.one_to_one):
        return getattr(instance, f'{field.name}_id', None)
    return getattr(instance, field.name, None)


def _normalize_value(value):
    if value is None:
        return ''
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (list, dict)):
        return json.dumps(value, default=str)
    return str(value)


def _safe_filename(label):
    slug = slugify(label) or 'table'
    return slug[:64]


def _safe_sheet_title(label):
    invalid_chars = '[]:*?/\\'
    cleaned = ''.join(ch for ch in label if ch not in invalid_chars)
    cleaned = cleaned.strip() or 'Sheet'
    if len(cleaned) > 28:
        cleaned = cleaned[:28]
    return cleaned


def _detect_date_field(model):
    candidates = [
        'created_at',
        'created',
        'timestamp',
        'updated_at',
        'date',
        'start_at',
        'end_at',
    ]
    for name in candidates:
        try:
            field = model._meta.get_field(name)
        except FieldDoesNotExist:
            continue
        if isinstance(field, (models.DateField, models.DateTimeField)):
            return field
    return None


def _matches_date_range(obj, field, start_date, end_date):
    value = getattr(obj, field.name, None)
    if value is None:
        return False
    if isinstance(field, models.DateTimeField):
        if timezone.is_aware(value):
            value_date = timezone.localtime(value).date()
        else:
            value_date = value.date()
    else:
        value_date = value
    if start_date and value_date < start_date:
        return False
    if end_date and value_date > end_date:
        return False
    return True


def _job_row_transform(row, job):
    row['created_by'] = _format_user(getattr(job, 'created_by', None))
    summary = getattr(job, 'jobsummary', None)
    if summary and summary.is_approved:
        row['is_approved'] = 'True'
        row['approved_at'] = summary.approved_at.isoformat() if summary.approved_at else ''
        row['approved_by'] = _format_user(summary.approved_by)
    else:
        row['is_approved'] = row.get('is_approved', 'False') or 'False'
        row['approved_at'] = ''
        row['approved_by'] = ''
    return row


def _format_user(user):
    if not user:
        return ''
    full_name = ''
    if hasattr(user, 'get_full_name'):
        full_name = user.get_full_name() or ''
    full_name = full_name.strip()
    if full_name:
        return full_name
    return getattr(user, 'email', str(user))


def _export_tables_to_excel_inline(entries, start_date=None, end_date=None):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        sheet_rel_entries = []
        workbook_sheets = []
        for idx, entry in enumerate(entries, start=1):
            sheet_name = _safe_sheet_title(entry['label']) or f'Sheet{idx}'
            sheet_rel_entries.append({
                'Id': f'rId{idx}',
                'Target': f'worksheets/sheet{idx}.xml',
                'Type': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet',
            })
            workbook_sheets.append({
                'name': sheet_name,
                'sheetId': idx,
                'rId': f'rId{idx}',
            })

            headers = [field.name for field in entry['fields']]
            rows = [headers]
            for row in _serialize_model_rows(
                entry['model'],
                entry['fields'],
                start_date,
                end_date,
                queryset=entry.get('queryset'),
                transform=entry.get('transform'),
            ):
                rows.append([row.get(name, '') for name in headers])
            sheet_xml = _build_sheet_xml(rows)
            archive.writestr(f'xl/worksheets/sheet{idx}.xml', sheet_xml)

        archive.writestr('[Content_Types].xml', _build_content_types_xml(len(entries)))
        archive.writestr('_rels/.rels', _build_root_rels_xml())
        archive.writestr('xl/_rels/workbook.xml.rels', _build_workbook_rels_xml(sheet_rel_entries))
        archive.writestr('xl/workbook.xml', _build_workbook_xml(workbook_sheets))
        archive.writestr('xl/styles.xml', _build_styles_xml())

    buffer.seek(0)
    return buffer.read()


def _build_content_types_xml(sheet_count):
    overrides = ''.join(
        f'<Override PartName="/xl/worksheets/sheet{idx}.xml" '
        f'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for idx in range(1, sheet_count + 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        f'{overrides}'
        '</Types>'
    )


def _build_root_rels_xml():
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>'
    )


def _build_workbook_rels_xml(sheet_rel_entries):
    rels = ''.join(
        f'<Relationship Id="{entry["Id"]}" Type="{entry["Type"]}" Target="{entry["Target"]}"/>'
        for entry in sheet_rel_entries
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'{rels}'
        '</Relationships>'
    )


def _build_workbook_xml(sheets):
    sheets_xml = ''.join(
        f'<sheet name="{escape(sheet["name"])}" sheetId="{sheet["sheetId"]}" r:id="{sheet["rId"]}"/>'
        for sheet in sheets
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets>'
        f'{sheets_xml}'
        '</sheets>'
        '</workbook>'
    )


def _build_styles_xml():
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="1"><font><sz val="11"/><color theme="1"/><name val="Calibri"/></font></fonts>'
        '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        '</styleSheet>'
    )


def _build_sheet_xml(rows):
    sheet_rows = []
    for row_idx, row in enumerate(rows, start=1):
        cells = []
        for col_idx, value in enumerate(row, start=1):
            col_ref = f'{_excel_column_name(col_idx)}{row_idx}'
            text = escape(str(value)) if value is not None else ''
            cells.append(
                f'<c r="{col_ref}" t="inlineStr"><is><t>{text}</t></is></c>'
            )
        sheet_rows.append(f'<row r="{row_idx}">{"".join(cells)}</row>')
    sheet_data = ''.join(sheet_rows)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheetData>{sheet_data}</sheetData>'
        '</worksheet>'
    )


def _excel_column_name(index):
    result = []
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        result.append(chr(65 + remainder))
    return ''.join(reversed(result))
