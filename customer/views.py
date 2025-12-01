from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.shortcuts import render, redirect, get_object_or_404
from django.core.paginator import Paginator
from django.conf import settings
from profiles.models import Profile
from django.utils import timezone
from datetime import timedelta
from django.db.models import Max
import os
import logging
import re
import base64
from pathlib import Path

from .forms import CustomerProfileForm, CustomerPasswordChangeForm
from .models import CustomerProfile
from auditlog.utils import log_action
from superadmin.models import (
    AIRequestLog,
    AdminWallet,
    CoinRule,
    CoinTransaction,
    CoinWallet,
    ContentGenerationSubmission,
    JobCheckingSubmission,
    PricingPlan,
    PricingPlanPurchase,
    StructureGenerationSubmission,
    _generate_bigint_id,
    SystemSettings,
)
from tickets.models import CustomerTicket
from ai_pipeline.services import (
    _get_openai_client,
    extract_text_from_pdf,
    extract_text_from_docx,
    extract_text_from_pptx,
    extract_text_from_csv,
    extract_text_from_excel,
    extract_text_from_plain,
)
from notifications.utils import create_notification

logger = logging.getLogger(__name__)

THEME_COLOR = '#FEEBE7'


def _get_rule(service_name: str):
    return CoinRule.objects.filter(service_name=service_name).first()


def _debit_wallet(user, amount: int, source: str, related_type: str = '', related_id: str = '', reason: str = ''):
    """
    Deduct coins from the customer's wallet and record a transaction.
    """
    wallet, _ = CoinWallet.objects.get_or_create(user=user, defaults={'balance': 0})
    amount = int(amount or 0)
    if amount < 0:
        amount = 0
    if amount > 0 and (wallet.balance or 0) < amount:
        return False, wallet, None

    before_balance = wallet.balance or 0
    if amount > 0:
        wallet.balance = before_balance - amount
        wallet.save(update_fields=['balance', 'last_updated_at'])
        # Credit the SuperAdmin wallet with the same amount
        try:
            admin_wallet = AdminWallet.get_solo()
            admin_wallet.balance = (admin_wallet.balance or 0) + amount
            admin_wallet.save(update_fields=['balance', 'updated_at'])
            settings_obj = SystemSettings.get_solo()
            settings_obj.admin_coin_balance = (settings_obj.admin_coin_balance or 0) + amount
            settings_obj.save(update_fields=['admin_coin_balance', 'updated_at'])
        except Exception:
            logger.warning("Failed to credit AdminWallet for debit of %s coins", amount)
        txn = CoinTransaction.objects.create(
            txn_id=f"TXN{_generate_bigint_id()}",
            wallet=wallet,
            customer=user,
            txn_type=CoinTransaction.TYPE_DEBIT,
            amount=amount,
            before_balance=before_balance,
            after_balance=wallet.balance,
            source=source,
            related_object_type=related_type,
            related_object_id=str(related_id) if related_id else '',
            reason=reason,
            created_by_role=getattr(user, 'role', 'CUSTOMER'),
            created_by_id=user,
        )
        # Notify customer of deduction
        try:
            create_notification(
                title="Coins deducted",
                message=f"{amount} coins deducted. Balance: {wallet.balance}",
                user_target=user,
                users=[user],
                related_model='CoinTransaction',
                related_object_id=str(txn.pk),
            )
        except Exception:
            logger.warning("Failed to send deduction notification for txn %s", getattr(txn, 'pk', None))
    else:
        txn = None

    return True, wallet, txn


def _credit_wallet(user, amount: int, source: str, related_type: str = '', related_id: str = '', reason: str = ''):
    """
    Credit coins to the customer's wallet and record a transaction.
    """
    wallet, _ = CoinWallet.objects.get_or_create(user=user, defaults={'balance': 0})
    amount = int(amount or 0)
    if amount <= 0:
        return wallet, None
    before_balance = wallet.balance or 0
    wallet.balance = before_balance + amount
    wallet.save(update_fields=['balance', 'last_updated_at'])
    txn = CoinTransaction.objects.create(
        txn_id=f"TXN{_generate_bigint_id()}",
        wallet=wallet,
        customer=user,
        txn_type=CoinTransaction.TYPE_CREDIT,
        amount=amount,
        before_balance=before_balance,
        after_balance=wallet.balance,
        source=source,
        related_object_type=related_type,
        related_object_id=str(related_id) if related_id else '',
        reason=reason,
        created_by_role=getattr(user, 'role', 'CUSTOMER'),
        created_by_id=user,
    )
    # Notify customer of credit
    try:
        create_notification(
            title="Coins added",
            message=f"{amount} coins added. Balance: {wallet.balance}",
            user_target=user,
            users=[user],
            related_model='CoinTransaction',
            related_object_id=str(txn.pk),
        )
    except Exception:
        logger.warning("Failed to send credit notification for txn %s", getattr(txn, 'pk', None))
    return wallet, txn


def _ensure_profile(user):
    """
    Make sure a CustomerProfile exists and is hydrated with sensible defaults.
    """
    if not user or getattr(user, 'role', '').upper() != 'CUSTOMER':
        return None
    def _next_int_id():
        return int(timezone.now().timestamp() * 1_000_000)
    def _is_int_pk(val):
        return isinstance(val, int) and not isinstance(val, bool)

    # Load existing profiles
    try:
        profiles = list(CustomerProfile.objects.filter(user=user))
    except Exception as exc:
        logger.warning(
            "Customer profile lookup failed for user %s (%s); rebuilding profile. %s",
            getattr(user, 'email', user),
            getattr(user, 'pk', None),
            exc,
        )
        return _rebuild_profile(user)
    # If any non-integer PKs exist, purge and start fresh
    if any((p.pk is None) or (not _is_int_pk(p.pk)) for p in profiles):
        CustomerProfile.objects.filter(user=user).delete()
        profiles = []

    profile = None
    if profiles:
        profiles = sorted(
            profiles,
            key=lambda p: getattr(p, 'updated_at', timezone.now()),
            reverse=True,
        )
        profile = profiles[0]
        # delete extras
        extra_ids = [p.pk for p in profiles[1:] if p.pk]
        if extra_ids:
            CustomerProfile.objects.filter(pk__in=extra_ids).delete()
        if profile and not _is_int_pk(profile.pk):
            profile = _rebuild_profile(user)

    if not profile:
        new_id = _next_int_id()
        profile = CustomerProfile(
            id=new_id,
            user=user,
            full_name=user.get_full_name(),
            phone=getattr(user, 'whatsapp_no', '') or '',
            joined_date=getattr(user, 'date_joined', timezone.now()),
        )
        profile.customer_id = getattr(user, 'customer_code', None) or profile.generate_customer_id()
        profile.save(force_insert=True)
        # Djongo may return an ObjectId pk on the in-memory instance; re-fetch to ensure int pk
        try:
            profile = CustomerProfile.objects.get(pk=new_id)
        except Exception:
            try:
                profile.refresh_from_db()
            except Exception:
                pass

    # Ensure required fields
    updated = False
    if getattr(user, 'customer_code', None) and profile.customer_id != user.customer_code:
        profile.customer_id = user.customer_code
        updated = True
    elif not profile.customer_id:
        profile.customer_id = getattr(user, 'customer_code', None) or profile.generate_customer_id()
        updated = True
    if not profile.full_name:
        profile.full_name = user.get_full_name()
        updated = True
    if not profile.phone:
        profile.phone = getattr(user, 'whatsapp_no', '') or profile.phone
        updated = True
    if updated:
        try:
            profile.save()
        except Exception as exc:
            logger.warning(
                "Customer profile save failed for %s (pk=%s); rebuilding profile. %s",
                getattr(user, 'email', user),
                getattr(profile, 'pk', None),
                exc,
            )
            profile = _rebuild_profile(user)
    return profile


def _rebuild_profile(user, image=None):
    """
    Hard reset the customer's profile to a fresh numeric ID row, optionally with a new image.
    """
    if not user or getattr(user, 'role', '').upper() != 'CUSTOMER':
        return None
    try:
        CustomerProfile.objects.filter(user=user).delete()
    except Exception:
        pass
    new_id = int(timezone.now().timestamp() * 1_000_000)
    new_profile = CustomerProfile(
        id=new_id,
        user=user,
        full_name=user.get_full_name(),
        phone=getattr(user, 'whatsapp_no', '') or '',
        joined_date=getattr(user, 'date_joined', timezone.now()),
        customer_id=getattr(user, 'customer_code', None) or '',
    )
    if not new_profile.customer_id:
        new_profile.customer_id = new_profile.generate_customer_id()
    if image:
        new_profile.profile_image = image
    new_profile.save(force_insert=True)
    # Re-fetch to ensure pk is the stored integer, not an ObjectId on the in-memory instance
    try:
        new_profile = CustomerProfile.objects.get(pk=new_id)
    except Exception:
        try:
            new_profile.refresh_from_db()
        except Exception:
            pass
    return new_profile


def _base_context(request):
    profile = _ensure_profile(request.user)
    if profile and profile.pk:
        try:
            profile.refresh_from_db()
        except Exception:
            pass
    wallet, _ = CoinWallet.objects.get_or_create(user=request.user, defaults={'balance': getattr(profile, 'coin_balance', 0) or 0})
    coins = wallet.balance if wallet else 0
    # Coin rule shortcuts for customer display
    rule_defs = ['REMOVE_AI', 'JOB_CHECK', 'STRUCTURE', 'CREATE_CONTENT']
    rule_map = {r.service_name: r for r in CoinRule.objects.filter(service_name__in=rule_defs)}
    remove_ai_cost = getattr(rule_map.get('REMOVE_AI'), 'coin_cost', 0) if rule_map.get('REMOVE_AI') else 0
    job_check_cost = getattr(rule_map.get('JOB_CHECK'), 'coin_cost', 0) if rule_map.get('JOB_CHECK') else 0
    structure_cost = getattr(rule_map.get('STRUCTURE'), 'coin_cost', 0) if rule_map.get('STRUCTURE') else 0
    content_cost = getattr(rule_map.get('CREATE_CONTENT'), 'coin_cost', 0) if rule_map.get('CREATE_CONTENT') else 0
    img_url = ''
    if profile and getattr(profile, 'profile_image', None):
        try:
            img_url = profile.profile_image.url
        except Exception:
            name = getattr(profile.profile_image, 'name', '')
            img_url = settings.MEDIA_URL + name if name else ''
    elif hasattr(request.user, 'profile'):
        try:
            prof = Profile.objects.filter(user=request.user).first()
            if prof and prof.profile_picture:
                img_url = prof.profile_picture.url
        except Exception:
            pass
    return {
        'theme_color': THEME_COLOR,
        'coin_balance': coins or 0,
        'customer_profile': profile,
        'customer_wallet': wallet,
        'remove_ai_cost': remove_ai_cost,
        'job_check_cost': job_check_cost,
        'structure_cost': structure_cost,
        'content_cost': content_cost,
        'profile_image_url': img_url,
    }


def _generate_job_check_summary(submission):
    """
    Build a structured summary using OpenAI (with heuristic fallback).
    """
    instruction = submission.instruction or ''
    extracted = submission.extracted_text or ''

    def _extract_attachment_text(sub):
        if not sub.attachment:
            return ''
        try:
            file_path = sub.attachment.path
        except Exception:
            return ''
        ext = os.path.splitext(file_path.lower())[1]
        try:
            if ext in {'.png', '.jpg', '.jpeg'}:
                try:
                    raw = Path(file_path).read_bytes()
                    mime = "image/png" if ext == ".png" else "image/jpeg"
                    b64 = base64.b64encode(raw).decode("utf-8")
                    content = [
                        {"type": "input_text", "text": "Extract all readable text from this image. Return only the text."},
                        {"type": "input_image", "image_url": f"data:{mime};base64,{b64}"},
                    ]
                    client = _get_openai_client()
                    resp = client.chat.completions.create(
                        model=getattr(settings, 'OPENAI_MODEL_SUMMARY', 'gpt-5.1'),
                        messages=[
                            {"role": "system", "content": "You extract plain text from images."},
                            {"role": "user", "content": content},
                        ],
                        temperature=0,
                        max_completion_tokens=2000,
                    )
                    return (resp.choices[0].message.content or '').strip()
                except Exception as exc_img:
                    logger.warning("Image OCR via OpenAI failed for %s: %s", file_path, exc_img)
                    return ''
            if ext == '.pdf':
                return extract_text_from_pdf(file_path)
            if ext in {'.docx', '.doc'}:
                return extract_text_from_docx(file_path)
            if ext in {'.pptx'}:
                return extract_text_from_pptx(file_path)
            if ext == '.csv':
                return extract_text_from_csv(file_path)
            if ext in {'.xlsx', '.xls', '.xlx'}:
                return extract_text_from_excel(file_path)
            return extract_text_from_plain(file_path)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Attachment extract failed for %s: %s", file_path, exc)
            try:
                raw = Path(file_path).read_bytes()
                return raw.decode('utf-8', errors='ignore') or ''
            except Exception:
                return ''

    if not extracted:
        extracted = _extract_attachment_text(submission) or ''
        submission.extracted_text = extracted
        submission.save(update_fields=['extracted_text', 'updated_at'])

    def _extract_word_count_hint(text: str):
        """
        Look for explicit word count or ranges in the provided text.
        Returns a string (e.g., "2500-3000" or "2000") or None.
        """
        text = text or ''
        # normalize commas in numbers, e.g., 2,500 -> 2500
        text = re.sub(r'(?<=\d),(?=\d)', '', text)
        # Word count forms
        patterns = [
            r'(\d{2,5})\s*-\s*(\d{2,5})\s*words?',
            r'(\d{2,5})\s*[–—\-to]{1,3}\s*(\d{2,5})\s*words?',
            r'(\d{2,5})\s*words?\b',
            r'words?\s*[:\-]?\s*(\d{2,5})',
            r'word\s*count\s*[:\-]?\s*(\d{2,5})',
            r'\bwc\s*[:\-]?\s*(\d{2,5})\b',
            r'word\s*limit\s*(?:of\s*)?[:\-]?\s*(\d{2,5})(?:\s*[–—\-to]{1,3}\s*(\d{2,5}))?',
        ]
        for pat in patterns:
            for m in re.finditer(pat, text, flags=re.IGNORECASE):
                if m.lastindex and m.lastindex >= 2:
                    return f"{m.group(1)}-{m.group(2)}"
                if m.lastindex and m.group(1):
                    return m.group(1)
        # Page-based hints (convert pages to words ~275 per page)
        page_pat = re.compile(r'(\d{1,3})(?:\s*[–—\-to]{1,3}\s*(\d{1,3}))?\s*pages?', re.IGNORECASE)
        for m in page_pat.finditer(text):
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else None
            if end:
                return f"{start*275}-{end*275}"
            return str(start * 275)
        return None

    def _extract_ref_style(text: str):
        style_map = {
            'APA7': 'APA',
            'APA 7': 'APA7',
            'APA 7TH': 'APA7',
            'APA': 'APA',
            'MLA': 'MLA',
            'HARVARD': 'Harvard',
            'Harvard': 'Harvard',
            'CHICAGO': 'CHICAGO',
            'IEEE': 'IEEE',
            'VANCOUVER': 'VANCOUVER',
            'OSCOLA': 'OSCOLA',
            'TURABIAN': 'TURABIAN',
            'REFERENCING STYLE APA': 'APA',
            'REFERENCING STYLE HARVARD': 'Harvard',
            'APA system' : 'APA',
            'harvard':'Harvard',
            'apa': 'APA',
            'apa7': 'APA',
            'ieee': 'IEEE',
            'Ieee':'IEEE',
            'Harvard Notation' : 'Harvard',
            'Harvard convention' : 'Harvard',
        }
        upper_text = (text or '').upper()
        for key, val in style_map.items():
            if key in upper_text:
                return val
        return None

    def _limit_job_summary(summary_text: str, max_words: int = 200, override_word_count: str = None, override_ref_style: str = None) -> str:
        """
        Ensure the 'Job Summary' line is capped to a target word budget.
        Also lets us override the Word Count / Referencing Style lines if we detected specific values.
        """
        lines = (summary_text or '').splitlines()
        out_lines = []
        for line in lines:
            lower_line = line.strip().lower()
            if lower_line.startswith('job summary'):
                # Split on first hyphen to preserve label
                parts = line.split('-', 1)
                if len(parts) == 2:
                    label, content = parts[0], parts[1]
                    words = content.strip().split()
                    if len(words) > max_words:
                        content = ' '.join(words[:max_words]) + ' ...'
                    line = f"{label.strip()} - {content.strip()}"
            if lower_line.startswith('word count') and override_word_count:
                line = f"Word Count - {override_word_count}"
            if lower_line.startswith('referencing style') and override_ref_style:
                line = f"Referencing Style - {override_ref_style}"
            out_lines.append(line)
        return "\n".join(out_lines)

    prompt_text = """
Attachedment Read Very care fully and All instrcution and all informtion read care fully step by step in details.
You are an AI assistant specialized in understanding writing tasks and producing a structured Job Summary, not the full content itself. Read the user's instructions and any extracted text from attachments (e.g., PDFs, DOCX) to identify what needs to be written, including topic, word count or length, reference style (APA, MLA, Harvard, etc.), and writing style or document type (essay, report, PPT, proposal, article, dissertation, thesis, etc.). If a detail is not explicitly given but can be reasonably inferred, infer it; if it cannot be inferred confidently, mark it as "Not specified." Always respond in this exact format, each on its own line and using a hyphen after the label: Topic - <short topic or title>; Word Count - <number of words or If word count is not mentioned in the Job card, then by default print "1500">; Referencing Style - <style or If Reference Style is not mentioned in the Job card, then by default print "Harvard">; Academic Style - <type or "Report">; Academic Level - Undergraduate/Masters/PhD; Summary - <What needs to be written>; Marking Criteria - <Assessment requirements>; Merit Criteria - <Excellence indicators>; Subject Field - <Discipline/area of study>; Job Summary - <10-20 sentences clearly describing what needs to be written, the main themes to cover, target audience or level if known, and any important constraints such as tone or structure>. Do not add extra sections, do not explain your reasoning, and do not write the actual assignment-only provide a clear, concise, implementation-ready Job Summary that another writer or AI could directly follow.
""".strip()
    prompt_text += " The Job Summary must stay concise, target around 180-200 words, and never exceed 210 words. If the instructions specify a word count or range, use that value; only default to 1500 when nothing is provided."

    user_payload = f"Instructions:\n{instruction or 'N/A'}\n\nExtracted Text:\n{extracted or 'N/A'}"
    combined = f"{instruction}\n{extracted}"
    wc_hint_source = _extract_word_count_hint(combined) or _extract_word_count_hint(extracted)
    ref_hint_source = _extract_ref_style(combined) or _extract_ref_style(extracted)
    if wc_hint_source:
        user_payload += f"\n\nDetected Word Count: {wc_hint_source}"
    if ref_hint_source:
        user_payload += f"\nDetected Referencing Style: {ref_hint_source}"

    model = getattr(settings, 'OPENAI_MODEL_SUMMARY', 'gpt-5.1')
    try:
        client = _get_openai_client()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": prompt_text},
                {"role": "user", "content": user_payload},
            ],
            temperature=0.2,
            max_completion_tokens=2000,
        )
        ai_summary = (response.choices[0].message.content or '').strip()
        wc_hint_ai = _extract_word_count_hint(ai_summary)
        ref_hint_ai = _extract_ref_style(ai_summary)
        # Prefer hints from source (instruction/extracted) over AI defaults
        wc_final = wc_hint_source or wc_hint_ai
        ref_final = ref_hint_source or ref_hint_ai
        ai_summary = _limit_job_summary(ai_summary, max_words=200, override_word_count=wc_final, override_ref_style=ref_final)
        submission.ai_prompt = prompt_text
        submission.ai_summary = ai_summary
        submission.status = JobCheckingSubmission.STATUS_SUCCESS
        submission.error_message = ''
        submission.save(update_fields=['ai_prompt', 'ai_summary', 'status', 'error_message', 'updated_at'])
        return
    except Exception as exc:
        logger.warning("OpenAI job checking failed: %s", exc)
        submission.error_message = str(exc)[:500]
        # Fallback heuristic
        text_for_parse = f"{instruction} {extracted}"
        topic = (instruction.strip().splitlines()[0] if instruction.strip() else 'Not specified')[:120]
        word_count = 1500
        ref_style = ref_hint_source or 'Harvard'
        wc_hint_fallback = wc_hint_source
        writing_style = 'Report'
        academic_level = 'Not specified'
        subject_field = 'Not specified'
        marking_criteria = 'Assessment requirements'
        merit_criteria = 'Excellence indicators'

        m_wc = wc_hint_fallback or None
        if not m_wc:
            m_wc_re = re.search(r'(\d{2,5})\s*words?', text_for_parse, re.IGNORECASE)
            if m_wc_re:
                try:
                    m_wc = m_wc_re.group(1)
                except Exception:
                    m_wc = None
        if m_wc:
            try:
                word_count = int(str(m_wc).split('-')[0])
            except Exception:
                word_count = 1500

        for style in ['APA', 'MLA', 'Harvard', 'Chicago', 'IEEE']:
            if re.search(style, text_for_parse, re.IGNORECASE):
                ref_style = style if style == 'Harvard' else style.upper()
                break

        for ws in ['essay', 'report', 'proposal', 'ppt', 'article', 'dissertation', 'thesis']:
            if re.search(ws, text_for_parse, re.IGNORECASE):
                writing_style = ws.title()
                break

        for level in ['Undergraduate', 'Masters', 'PhD', 'UG', 'PG']:
            if re.search(level, text_for_parse, re.IGNORECASE):
                if level.lower() in ['pg', 'masters']:
                    academic_level = 'Masters'
                elif level.lower() == 'ug':
                    academic_level = 'Undergraduate'
                else:
                    academic_level = level
                break

        job_summary_text = instruction or extracted or "Not specified"
        wc_display = wc_hint_fallback or word_count
        summary_lines = [
            f"Topic - {topic if topic else 'Not specified'}",
            f"Word Count - {wc_display}",
            f"Referencing Style - {ref_style}",
            f"Academic Style - {writing_style}",
            f"Academic Level - {academic_level}",
            f"Summary - {job_summary_text}",
            f"Marking Criteria - {marking_criteria}",
            f"Merit Criteria - {merit_criteria}",
            f"Subject Field - {subject_field}",
        ]
        submission.ai_prompt = prompt_text
        submission.ai_summary = _limit_job_summary("\n".join(summary_lines), max_words=200, override_word_count=str(wc_display), override_ref_style=ref_style)
        submission.status = JobCheckingSubmission.STATUS_SUCCESS
        submission.save(update_fields=['ai_prompt', 'ai_summary', 'status', 'error_message', 'updated_at'])


def _generate_structure_outline(submission):
    """
    Generate an academic structure outline using OpenAI for the structure request.
    """
    def _align_structure_total(text: str, expected_total: int = None) -> str:
        """
        Enforce hierarchical word-count consistency:
        - Exclude Cover/AI Disclaimer/References from totals.
        - Subsection counts sum to their parent.
        - Main sections sum to the target total (if provided) or to the natural sum.
        """
        if not text:
            return text

        ignore_keys = ['cover', 'cover page', 'ai disclaimer', 'disclaimer', 'references', 'reference', 'bibliography']

        def _is_ignored(line: str) -> bool:
            low = (line or '').lower()
            return any(k in low for k in ignore_keys)

        def _find_count(line: str):
            m = re.search(r'(\d{1,6})\s*words?', line, flags=re.IGNORECASE)
            return int(m.group(1)) if m else None

        try:
            target_total = int(expected_total) if expected_total not in (None, '', 'Not specified') else None
        except Exception:
            target_total = None

        lines = text.splitlines()
        total_idx = next((i for i, ln in enumerate(lines) if 'total word count' in ln.lower()), None)

        heading_re = re.compile(r'^\s*(\d+)\.\s')
        subheading_re = re.compile(r'^\s*(\d+)\.(\d+)\s')

        mains = []       # (idx, num, count)
        subs = {}        # num -> list[(idx, subnum, count)]

        for idx, line in enumerate(lines):
            if idx == total_idx:
                continue
            count = _find_count(line)
            if count is None or _is_ignored(line):
                continue
            m_sub = subheading_re.match(line)
            if m_sub:
                pnum = int(m_sub.group(1))
                subs.setdefault(pnum, []).append((idx, int(m_sub.group(2)), count))
                continue
            m_main = heading_re.match(line)
            if m_main:
                mains.append((idx, int(m_main.group(1)), count))

        if not mains:
            return text

        # Make parent counts equal to sum of subs (if subs exist)
        main_counts = {}
        for idx, num, count in mains:
            if num in subs:
                subtotal = sum(c[2] for c in subs[num])
                main_counts[num] = subtotal if subtotal > 0 else count
            else:
                main_counts[num] = count

        main_sum = sum(main_counts.values())
        if main_sum <= 0:
            return text

        # Rescale mains to target_total if provided
        if target_total:
            scale = target_total / main_sum
            scaled = {k: max(1, round(v * scale)) for k, v in main_counts.items()}
            drift = target_total - sum(scaled.values())
            if drift != 0:
                largest = max(scaled, key=scaled.get)
                scaled[largest] = max(1, scaled[largest] + drift)
            main_counts = scaled

        # Rescale subs proportionally to their parent
        for pnum, items in subs.items():
            parent_target = main_counts.get(pnum)
            orig = sum(c[2] for c in items)
            if not parent_target or orig <= 0:
                continue
            factor = parent_target / orig
            new_counts = [max(1, round(c[2] * factor)) for c in items]
            drift = parent_target - sum(new_counts)
            if drift != 0:
                adjust_idx = max(range(len(new_counts)), key=lambda i: new_counts[i])
                new_counts[adjust_idx] = max(1, new_counts[adjust_idx] + drift)
            for (idx_line, _, _), new_val in zip(items, new_counts):
                lines[idx_line] = re.sub(r'(\d{1,6})(\s*words?)', fr"{new_val}\2", lines[idx_line], count=1, flags=re.IGNORECASE)

        # Write main counts back
        for idx_line, num, _ in mains:
            new_val = main_counts.get(num)
            if new_val is not None:
                lines[idx_line] = re.sub(r'(\d{1,6})(\s*words?)', fr"{new_val}\2", lines[idx_line], count=1, flags=re.IGNORECASE)

        final_total = sum(main_counts.values())
        if total_idx is not None:
            lines[total_idx] = re.sub(r'(Total\s*Word\s*Count\s*[:\-]?\s*)(\d{1,6})',
                                      fr"\1{final_total}", lines[total_idx], count=1, flags=re.IGNORECASE)
        else:
            lines.insert(1, f"Total Word Count: {final_total}")

        return "\n".join(lines)

    # Build prompt
    prompt_text = """
You are an AI assistant specialized in creating academic writing structures (detailed outlines) for writing tasks. Your input is: Topic, Word Count, Reference Style, Writing Style, Academic Level, Marking Criteria, Merit Criteria, Subject Field and Job Summary (and may also include extra instructions). Your job is to design a clear, logically ordered, academically appropriate structure with word counts for each section and subsection, so that another writer or AI could directly draft the final document. Strictly follow all instructions and requirements from the Job Summary and ensure that every key theme, focus area, or constraint is reflected in the structure. Use academic writing conventions that match the Writing Style (e.g., essays with introduction/body/conclusion; reports with sections such as introduction, methodology, analysis, conclusion; dissertations/thesis with chapters such as introduction, literature review, methodology, results, discussion, conclusion; PPTs as slide-based academic sections, etc.). Handle Word Count as follows: always use only word counts and never pages, lines, slides, or any other length unit; if a specific word count is given, treat it as the target total and allocate section word counts so they sum to approximately that total (with minor acceptable variation); if a range is given, internally pick a reasonable midpoint and allocate based on that; if the word count is described in pages or similar, internally convert to an approximate word count and output only word counts; if Word Count is "Not specified," infer a reasonable total based on the Writing Style and academic context, then allocate accordingly. Respect the Reference Style by including a final "References" or "Bibliography" section with an appropriate word count whenever references are expected for that type of task. Ensure a coherent hierarchy with numbered sections and, where useful, subsections, each with a clear academic-style heading and an explicit word count (e.g., "Section Title - X words"). Begin by stating the title (using the Topic) and the total word count, then list the sections in order. Do not write any actual content of the sections, only the structure and word counts. Do not explain your reasoning, do not add extra metadata fields, and do not mention any unit other than words.Do not write any actual content of the sections, only the structure and word counts. Do not explain your reasoning, do not add extra metadata fields, and do not mention any unit other than words. Sub points must show word counts and the sum of sub point word counts must match the parent section total; the sum of all main sections must equal the total word count. If any subsection has its own child subsections, their word counts must sum exactly to that subsection total.Look, Total Words count is Sum of all Main Section, and then Main Section is Sum of Sub Section, and Sub Section is Sum of Sub Section of Sub Section,like
Total words count is Sum of Main Section. and Main Section look like, 1., 2., 3., 4., .......
then Main Section is sum of Sub Section and Sub Section look like, 1.1., 1.2., 1.3., 1.4., ........
and Sub Section is sum of Sub Section of Sub Section and Sub Section of Sub Section look like 1.1.1., 1.1.2., 1.1.3., 1.1.4., ........,
 You must allocate Introduction and Conclusion to ~10% each of the total word count (within ±2%). Keep other sections proportional to remaining words.
 Do not use bold or markdown emphasis in headings; plain text only.
""".strip()

    user_payload = f"""
Topic: {submission.topic or 'N/A'}
Word Count: {submission.word_count or 'Not specified'}
Reference Style: {submission.referencing_style or 'Not specified'}
Writing Style: {submission.academic_style or 'Not specified'}
Academic Level: {submission.academic_level or 'Not specified'}
Subject Field: {submission.subject_field or 'Not specified'}
Marking Criteria: {submission.marking_criteria or 'Not specified'}
Merit Criteria: {submission.merit_criteria or 'Not specified'}
Job Summary / Instructions: {submission.summary or 'Not specified'}
""".strip()

    model = getattr(settings, 'OPENAI_MODEL_STRUCTURE', 'gpt-5.1')
    try:
        client = _get_openai_client()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": prompt_text},
                {"role": "user", "content": user_payload},
            ],
            temperature=0.2,
            max_completion_tokens=2000,
        )
        ai_structure_raw = (response.choices[0].message.content or '').strip()
        ai_structure = _align_structure_total(ai_structure_raw, expected_total=submission.word_count)
        submission.ai_prompt = prompt_text
        submission.ai_structure = ai_structure
        submission.status = StructureGenerationSubmission.STATUS_SUCCESS
        submission.error_message = ''
        submission.save(update_fields=['ai_prompt', 'ai_structure', 'status', 'error_message', 'updated_at'])
    except Exception as exc:
        logger.warning("OpenAI structure generation failed: %s", exc)
        submission.error_message = str(exc)[:500]
        submission.status = StructureGenerationSubmission.STATUS_FAILED
        submission.save(update_fields=['error_message', 'status', 'updated_at'])


def _generate_content_text(submission):
    """
    Generate full academic content (with references/citations) using OpenAI.
    """
    prompt_text = """
You are an AI assistant specialized in academic content writing. Your input is Content Topic, Target Word Count, Referencing Style, Writing Style, Writing tone, Structure & Guidelines. You must:
- Use the provided headings/structure exactly. If none is given, create a sensible academic structure (Introduction, 3?5 body sections, Conclusion) with headings/subheadings.
- Allocate word counts per section/subsection that sum to the target word count (stay within ?5% of the target total). Reflect these allocations directly in the written content (do not output a separate plan).
- Maintain formal academic tone, consistent voice/tense, and logical flow.
- Do NOT invent or remove headings beyond the structure (unless creating the minimal structure above).
- After writing the content, create an original, verifiable Reference List (real sources, 2022+ only) in the given reference style, ~7 references per 1000 words (rounded reasonably). Then provide a Citation List showing correct in-text formats (Harvard/APA: Author, Year; IEEE: [1], etc.).
- Insert in-text citations throughout the content (but NOT in Introduction, Conclusion, Abstract/Executive Summary). Every reference must be cited at least once; no fake sources.
- Append the full reference list at the end. Output only the final content with in-text citations inserted and the complete reference list appended. No explanations or extra notes.
Always obey the target total word count first, keeping your final response within ±10% of the user’s specified total (if the target is T, your answer must be between 0.9T and 1.1T words), and then strictly follow the exact section and subsection structure (headings and hierarchy) provided by the user, using the same titles and not adding any new sections. If the user also gives approximate word counts per section, treat those as guidelines while ensuring the total word count stays within the allowed range. Be concise, avoid repetition, and prioritize clarity and relevance when space is limited instead of adding extra detail. Do not mention word counts, calculations, rules, or reasoning in your output, and do not restate or reference these instructions. Your entire response should only consist of the content requested by the user, formatted using the exact structure they provided, while keeping the total word count strictly within the ±10% range.
""".strip()

    user_payload = f"""
Content Topic: {submission.topic or 'N/A'}
Target Word Count: {submission.word_count or 'Not specified'}
Referencing Style: {submission.referencing_style or 'Not specified'}
Writing Style: {submission.writing_style or 'Not specified'}
Writing Tone: {submission.writing_tone or 'Not specified'}
Structure & Guidelines: {submission.structure_guidelines or 'Not specified'}
Academic Level: {submission.academic_level or 'Not specified'}
Subject Field: {submission.subject_field or 'Not specified'}
""".strip()

    model = getattr(settings, 'OPENAI_MODEL_CONTENT', 'gpt-5.1')
    try:
        client = _get_openai_client()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": prompt_text},
                {"role": "user", "content": user_payload},
            ],
            temperature=0.2,
            max_completion_tokens=10000,
        )
        content_text = (response.choices[0].message.content or '').strip()
        submission.generated_content = content_text
        submission.references_text = content_text
        submission.final_content = content_text
        submission.status = ContentGenerationSubmission.STATUS_SUCCESS
        submission.error_message = ''
        submission.save(update_fields=['generated_content', 'references_text', 'final_content', 'status', 'error_message', 'updated_at'])
    except Exception as exc:
        logger.warning("OpenAI content generation failed: %s", exc)
        submission.error_message = str(exc)[:500]
        submission.status = ContentGenerationSubmission.STATUS_FAILED
        submission.save(update_fields=['error_message', 'status', 'updated_at'])


@login_required
def welcome_view(request):
    ctx = _base_context(request)
    user = request.user
    # Compute counts
    ai_ops = (
        JobCheckingSubmission.objects.filter(user=user).count()
        + StructureGenerationSubmission.objects.filter(user=user).count()
        + ContentGenerationSubmission.objects.filter(user=user).count()
    )
    from tickets.models import CustomerTicket
    open_tickets = CustomerTicket.objects.filter(user=user, status__in=['OPEN', 'IN_PROGRESS']).count()
    ctx.update({
        'ai_operations': ai_ops,
        'open_tickets': open_tickets,
    })
    return render(request, 'customer/welcome.html', ctx)


@login_required
def dashboard_view(request):
    ctx = _base_context(request)
    user = request.user
    # Coins and wallet
    coins_balance = ctx.get('coin_balance', 0)
    # Recent activities from submissions and requests
    activities = []
    # Coin transactions (top-ups/spends) for visibility, not counted as tasks
    coin_txns = CoinTransaction.objects.filter(customer=user).order_by('-created_at')[:20]
    for tx in coin_txns:
        activities.append({
            'type': f"Coin {tx.txn_type.title()}",
            'primary_id': tx.txn_id,
            'topic': tx.reason or '',
            'coins': tx.amount if tx.txn_type == CoinTransaction.TYPE_CREDIT else -tx.amount,
            'status': tx.source,
            'created_at': tx.created_at,
            'submission_id': tx.txn_id,
            'is_task': False,
        })
    for src, label, coins_field, topic_field in [
        (JobCheckingSubmission.objects.filter(user=user).order_by('-created_at')[:20], 'Job Checking', 'coins_spent', 'instruction'),
        (StructureGenerationSubmission.objects.filter(user=user).order_by('-created_at')[:20], 'Structure Generate', 'coins_spent', 'topic'),
        (ContentGenerationSubmission.objects.filter(user=user).order_by('-created_at')[:20], 'Content Creation', 'coins_spent', 'topic'),
    ]:
        for item in src:
            activities.append({
                'type': label,
                'primary_id': getattr(item, 'submission_id', '') or '',
                'topic': (getattr(item, topic_field, '') or '')[:80],
                'coins': getattr(item, coins_field, 0),
                'status': getattr(item, 'status', ''),
                'created_at': getattr(item, 'created_at', None),
                'submission_id': getattr(item, 'submission_id', '') or '',
                'is_task': True,
            })
    # Tickets as additional activities (no coins)
    from tickets.models import CustomerTicket  # local import to avoid circulars
    for t in CustomerTicket.objects.filter(user=user).order_by('-updated_at')[:20]:
        activities.append({
            'type': 'Ticket',
            'primary_id': t.ticket_id,
            'topic': t.subject,
            'coins': 0,
            'status': t.status,
            'created_at': t.updated_at or t.created_at,
            'submission_id': t.ticket_id,
            'is_task': False,
        })
    activities = sorted(activities, key=lambda a: a.get('created_at') or 0, reverse=True)

    # Totals should be computed on the full task list, not the trimmed display list
    task_entries_all = [a for a in activities if a.get('is_task')]
    total_ops = len(task_entries_all)
    total_spend = sum(a['coins'] for a in task_entries_all if a['coins'] > 0)

    # Paginate activities (5 per page)
    paginator = Paginator(activities, 5)
    page_number = request.GET.get('page') or 1
    page_obj = paginator.get_page(page_number)
    paged_activities = list(page_obj.object_list)

    # Page coins still reflect visible items
    page_coins = sum(a['coins'] for a in paged_activities)

    stats = {
        'coins': coins_balance,
        'operations': total_ops,
        'spend': total_spend,
    }
    ctx.update({
        'stats': stats,
        'activities': paged_activities,
        'activity_page_obj': page_obj,
        'activity_page_coins': page_coins,
        'activity_total_rows': paginator.count,
    })
    return render(request, 'customer/dashboard.html', ctx)


@login_required
def remove_ai_view(request):
    return render(request, 'customer/remove_ai.html', _base_context(request))


@login_required
def job_checking_view(request):
    if getattr(request.user, 'role', '').upper() != 'CUSTOMER':
        messages.error(request, 'Only customers can use Job Checking.')
        return redirect('customer:welcome')

    ctx = _base_context(request)
    if request.method == 'POST':
        instruction = (request.POST.get('instruction') or '').strip()
        attachment = request.FILES.get('attachment')
        rule = _get_rule('JOB_CHECK')
        cost = getattr(rule, 'coin_cost', 0) if rule else 0
        min_balance = getattr(rule, 'min_balance_required', cost) if rule else cost
        wallet, _ = CoinWallet.objects.get_or_create(user=request.user, defaults={'balance': ctx.get('coin_balance', 0) or 0})
        if (wallet.balance or 0) < max(cost, min_balance):
            messages.error(request, f'Insufficient coins. Required at least {max(cost, min_balance)}.')
            return redirect('customer:job_checking')
        try:
            submission = JobCheckingSubmission.objects.create(
                user=request.user,
                instruction=instruction,
                attachment=attachment,
                status=JobCheckingSubmission.STATUS_PENDING,
                coins_spent=cost,
                service='JOB_CHECK',
            )
            log = AIRequestLog.objects.create(
                user=request.user,
                customer_id=submission.customer_id,
                customer_name=submission.customer_name,
                service='JOB_CHECK',
                coins=cost,
                status='PENDING',
            )
            ok, wallet, txn = _debit_wallet(
                request.user,
                cost,
                CoinTransaction.SOURCE_JOB,
                related_type='JobCheckingSubmission',
                related_id=submission.submission_id,
                reason=f"Job Checking {submission.submission_id}",
            )
            if not ok:
                submission.delete()
                messages.error(request, 'Could not deduct coins. Please try again.')
                return redirect('customer:job_checking')
            _generate_job_check_summary(submission)
            submission.coins_spent = cost
            submission.save(update_fields=['coins_spent'])
            log.status = 'SUCCESS'
            log.save(update_fields=['status'])
            ctx['coin_balance'] = wallet.balance
            messages.success(request, f"Submission received. ID: {submission.submission_id}")
        except Exception:
            messages.error(request, 'Could not save submission. Please try again.')
        return redirect('customer:job_checking')

    recent_checks = JobCheckingSubmission.objects.filter(user=request.user).order_by('-created_at')[:10]
    checks_paginator = Paginator(JobCheckingSubmission.objects.filter(user=request.user).order_by('-created_at'), 5)
    checks_page_number = request.GET.get('rc_page') or 1
    checks_page_obj = checks_paginator.get_page(checks_page_number)
    ctx.update({
        'recent_checks': list(checks_page_obj.object_list),
        'recent_checks_page_obj': checks_page_obj,
    })
    job_cost = ctx.get('job_check_cost', 0)
    ctx.update({
        'wallet_balance': ctx.get('coin_balance', 0),
        'job_check_cost': job_cost,
    })
    return render(request, 'customer/job_checking.html', ctx)


@login_required
def job_check_detail_view(request, submission_id):
    submission = get_object_or_404(JobCheckingSubmission, submission_id=submission_id, user=request.user)
    ctx = {**_base_context(request), 'submission': submission}
    return render(request, 'customer/job_check_detail.html', ctx)


@login_required
def structure_generate_view(request):
    if getattr(request.user, 'role', '').upper() != 'CUSTOMER':
        messages.error(request, 'Only customers can use Structure Generate.')
        return redirect('customer:welcome')

    ctx = _base_context(request)
    if request.method == 'POST':
        rule = _get_rule('STRUCTURE')
        cost = getattr(rule, 'coin_cost', 0) if rule else 0
        min_balance = getattr(rule, 'min_balance_required', cost) if rule else cost
        wallet, _ = CoinWallet.objects.get_or_create(user=request.user, defaults={'balance': ctx.get('coin_balance', 0) or 0})
        if (wallet.balance or 0) < max(cost, min_balance):
            messages.error(request, f'Insufficient coins. Required at least {max(cost, min_balance)}.')
            return redirect('customer:structure_generate')
        topic = (request.POST.get('topic') or '').strip()
        word_count = request.POST.get('word_count') or 0
        ref_style = (request.POST.get('ref_style') or '').strip()
        academic_style = (request.POST.get('academic_style') or '').strip()
        summary = (request.POST.get('summary') or '').strip()
        academic_level = (request.POST.get('academic_level') or '').strip()
        subject_field = (request.POST.get('subject_field') or '').strip()
        marking_criteria = (request.POST.get('marking_criteria') or '').strip()
        merit_criteria = (request.POST.get('merit_criteria') or '').strip()
        try:
            submission = StructureGenerationSubmission.objects.create(
                user=request.user,
                topic=topic,
                word_count=int(word_count or 0),
                referencing_style=ref_style,
                academic_style=academic_style,
                academic_level=academic_level,
                summary=summary,
                subject_field=subject_field,
                marking_criteria=marking_criteria,
                merit_criteria=merit_criteria,
                status=StructureGenerationSubmission.STATUS_PENDING,
                coins_spent=cost,
            )
            ok, wallet, _ = _debit_wallet(
                request.user,
                cost,
                CoinTransaction.SOURCE_STRUCTURE,
                related_type='StructureGenerationSubmission',
                related_id=submission.submission_id,
                reason=f"Structure Generate {submission.submission_id}",
            )
            if not ok:
                submission.delete()
                messages.error(request, 'Could not deduct coins. Please try again.')
                return redirect('customer:structure_generate')
            _generate_structure_outline(submission)
            ctx['coin_balance'] = wallet.balance
            messages.success(request, f"Structure submission received. ID: {submission.submission_id}")
        except Exception:
            messages.error(request, 'Could not save structure submission. Please try again.')
        return redirect('customer:structure_generate')

    # Recent submissions with pagination
    structures_qs = StructureGenerationSubmission.objects.filter(user=request.user).order_by('-created_at')
    struct_page = Paginator(structures_qs, 5).get_page(request.GET.get('sg_page') or 1)
    structure_cost = ctx.get('structure_cost', 0)
    ctx.update({
        'wallet_balance': ctx.get('coin_balance', 0),
        'structure_cost': structure_cost,
        'structures': list(struct_page.object_list),
        'structures_page_obj': struct_page,
    })
    return render(request, 'customer/structure_generate.html', ctx)


@login_required
def structure_detail_view(request, submission_id):
    submission = get_object_or_404(StructureGenerationSubmission, submission_id=submission_id, user=request.user)
    ctx = {**_base_context(request), 'submission': submission}
    return render(request, 'customer/structure_detail.html', ctx)


@login_required
def create_content_view(request):
    if getattr(request.user, 'role', '').upper() != 'CUSTOMER':
        messages.error(request, 'Only customers can use Create Content.')
        return redirect('customer:welcome')

    ctx = _base_context(request)

    def _count_words(text: str) -> int:
        return len(re.findall(r'\w+', text or ''))

    if request.method == 'POST':
        rule = _get_rule('CREATE_CONTENT')
        base_cost = getattr(rule, 'coin_cost', 0) if rule else 0
        per_block = 250
        try:
            wc = int(request.POST.get('word_count') or 0)
        except Exception:
            wc = 0
        blocks = (wc + (per_block - 1)) // per_block if wc > 0 else 1
        cost = blocks * base_cost
        min_balance = getattr(rule, 'min_balance_required', cost) if rule else cost
        wallet, _ = CoinWallet.objects.get_or_create(user=request.user, defaults={'balance': ctx.get('coin_balance', 0) or 0})
        if (wallet.balance or 0) < max(cost, min_balance):
            messages.error(request, f'Insufficient coins. Required at least {max(cost, min_balance)}.')
            return redirect('customer:create_content')
        topic = (request.POST.get('topic') or '').strip()
        word_count = request.POST.get('word_count') or 0
        referencing_style = (request.POST.get('referencing_style') or '').strip()
        writing_style = (request.POST.get('writing_style') or '').strip()
        writing_tone = (request.POST.get('writing_tone') or '').strip()
        structure_guidelines = (request.POST.get('structure_guidelines') or '').strip()
        subject_field = (request.POST.get('subject_field') or '').strip()
        academic_level = (request.POST.get('academic_level') or '').strip()
        try:
            submission = ContentGenerationSubmission.objects.create(
                user=request.user,
                topic=topic,
                word_count=int(word_count or 0),
                referencing_style=referencing_style,
                writing_style=writing_style,
                writing_tone=writing_tone,
                structure_guidelines=structure_guidelines,
                subject_field=subject_field,
                academic_level=academic_level,
                status=ContentGenerationSubmission.STATUS_PENDING,
                coins_spent=cost,
                version_number=1,
            )
            ok, wallet, _ = _debit_wallet(
                request.user,
                cost,
                CoinTransaction.SOURCE_CONTENT,
                related_type='ContentGenerationSubmission',
                related_id=submission.submission_id,
                reason=f"Content Generation {submission.submission_id}",
            )
            if not ok:
                submission.delete()
                messages.error(request, 'Could not deduct coins. Please try again.')
                return redirect('customer:create_content')
            _generate_content_text(submission)
            # Recalculate cost based on actual output words
            submission.refresh_from_db()
            output_words = _count_words(getattr(submission, 'final_content', '') or getattr(submission, 'generated_content', '') or '')
            if output_words <= 0:
                try:
                    output_words = int(word_count or 0)
                except Exception:
                    output_words = 0
            out_blocks = (output_words + (per_block - 1)) // per_block if output_words > 0 else 1
            actual_cost = out_blocks * base_cost
            if actual_cost != cost:
                diff = actual_cost - cost
                if diff > 0:
                    ok_extra, wallet, _ = _debit_wallet(
                        request.user,
                        diff,
                        CoinTransaction.SOURCE_CONTENT,
                        related_type='ContentGenerationSubmission',
                        related_id=submission.submission_id,
                        reason=f"Additional content cost for {submission.submission_id} (output {output_words} words)",
                    )
                    if ok_extra:
                        submission.coins_spent = actual_cost
                        submission.save(update_fields=['coins_spent', 'updated_at'])
                        ctx['coin_balance'] = wallet.balance
                    else:
                        messages.warning(request, f"Content generated but unable to deduct extra {diff} coins for actual word count ({output_words}).")
                else:
                    refund = abs(diff)
                    wallet, _ = _credit_wallet(
                        request.user,
                        refund,
                        CoinTransaction.SOURCE_CONTENT,
                        related_type='ContentGenerationSubmission',
                        related_id=submission.submission_id,
                        reason=f"Refund for lower output words on {submission.submission_id}",
                    )
                    submission.coins_spent = actual_cost
                    submission.save(update_fields=['coins_spent', 'updated_at'])
                    ctx['coin_balance'] = wallet.balance
                    messages.info(request, f"Refunded {refund} coins based on actual output word count ({output_words}).")
            else:
                ctx['coin_balance'] = wallet.balance
            messages.success(request, f"Content submission received. ID: {submission.submission_id}")
        except Exception:
            messages.error(request, 'Could not save content submission. Please try again.')
        return redirect('customer:create_content')

    contents_qs = ContentGenerationSubmission.objects.filter(user=request.user).order_by('-created_at')
    contents_page = Paginator(contents_qs, 5).get_page(request.GET.get('cc_page') or 1)
    contents = []
    for c in contents_page.object_list:
        c.output_words_count = _count_words(getattr(c, 'final_content', '') or getattr(c, 'generated_content', '') or '')
        contents.append(c)
    ctx.update({
        'contents': contents,
        'contents_page_obj': contents_page,
    })
    return render(request, 'customer/create_content.html', ctx)


@login_required
def content_detail_view(request, submission_id):
    submission = get_object_or_404(ContentGenerationSubmission, submission_id=submission_id, user=request.user)
    ctx = {**_base_context(request), 'submission': submission}
    return render(request, 'customer/content_detail.html', ctx)


@login_required
def coin_history_view(request):
    ctx = _base_context(request)
    transactions_qs = CoinTransaction.objects.filter(customer=request.user).order_by('-created_at')
    page = Paginator(transactions_qs, 10).get_page(request.GET.get('page') or 1)
    ctx.update({
        'transactions': list(page.object_list),
        'transactions_page_obj': page,
    })
    return render(request, 'customer/coin_history.html', ctx)


@login_required
def pricing_plan_view(request):
    ctx = _base_context(request)
    plans = list(PricingPlan.objects.filter(status=PricingPlan.STATUS_PUBLISHED).order_by('price', 'name'))
    purchases = list(PricingPlanPurchase.objects.filter(user=request.user).order_by('-purchased_at')[:20])

    # Refresh purchase status for expiry
    now = timezone.now()
    for purchase in purchases:
        if purchase.valid_until and purchase.valid_until < now and purchase.status != PricingPlanPurchase.STATUS_EXPIRED:
            purchase.status = PricingPlanPurchase.STATUS_EXPIRED
            purchase.save(update_fields=['status'])

    if request.method == 'POST':
        if getattr(request.user, 'role', '').upper() != 'CUSTOMER':
            messages.error(request, 'Only customers can purchase plans.')
            return redirect('customer:pricing')
        plan_id = request.POST.get('plan_id')
        plan = PricingPlan.objects.filter(pk=plan_id, status=PricingPlan.STATUS_PUBLISHED).first()
        if not plan:
            messages.error(request, 'Plan not found or no longer available.')
        else:
            wallet, _ = CoinWallet.objects.get_or_create(user=request.user, defaults={'balance': ctx.get('coin_balance', 0)})
            before_balance = wallet.balance
            wallet.balance = (before_balance or 0) + plan.coin_amount
            wallet.save(update_fields=['balance', 'last_updated_at'])

            txn = CoinTransaction.objects.create(
                txn_id=f"TXN{_generate_bigint_id()}",
                wallet=wallet,
                customer=request.user,
                txn_type=CoinTransaction.TYPE_CREDIT,
                amount=plan.coin_amount,
                before_balance=before_balance or 0,
                after_balance=wallet.balance,
                source=CoinTransaction.SOURCE_PURCHASE,
                related_object_type='PricingPlan',
                related_object_id=str(plan.pk),
                reason=f"Purchase of plan {plan.name}",
                created_by_role=getattr(request.user, 'role', 'CUSTOMER'),
                created_by_id=request.user,
            )

            valid_until = now + timedelta(days=plan.validity_days) if plan.validity_days else None
            PricingPlanPurchase.objects.create(
                plan=plan,
                user=request.user,
                wallet=wallet,
                transaction=txn,
                plan_name=plan.name,
                plan_snapshot=plan.short_description or plan.benefits,
                price_paid=plan.price,
                currency=plan.currency,
                coins_granted=plan.coin_amount,
                validity_days=plan.validity_days,
                valid_until=valid_until,
            )

            ctx['coin_balance'] = wallet.balance
            ctx['customer_wallet'] = wallet
            log_action(request.user, 'PURCHASE', plan, f'Purchased pricing plan {plan.name}')
            messages.success(request, f"Purchased {plan.name}. {plan.coin_amount} coins added to your wallet.")
            return redirect('customer:pricing')

    active_purchase_count = len([p for p in purchases if p.computed_status() != PricingPlanPurchase.STATUS_EXPIRED])

    # Rule cards
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

    settings_obj = SystemSettings.get_solo()

    ctx.update({
        'plans': plans,
        'purchases': purchases,
        'active_purchase_count': active_purchase_count,
        'available_plan_count': len(plans),
        'rule_cards': rule_cards,
        'content_word_block': 250,
        'pricing_plan_doc': getattr(settings_obj, 'pricing_plan_doc', '') or '',
    })
    return render(request, 'customer/pricing_plan.html', ctx)


@login_required
def submit_ticket_view(request):
    if getattr(request.user, 'role', '').upper() != 'CUSTOMER':
        messages.error(request, 'Only customers can submit tickets.')
        return redirect('customer:welcome')
    ctx = _base_context(request)
    if request.method == 'POST':
        subject = (request.POST.get('subject') or '').strip()
        category = (request.POST.get('category') or '').strip()
        description = (request.POST.get('description') or '').strip()
        priority = (request.POST.get('priority') or 'MEDIUM').upper()
        attachment = request.FILES.get('attachment')
        if not subject or not description:
            messages.error(request, 'Subject and description are required.')
            return redirect('customer:submit_ticket')
        try:
            CustomerTicket.objects.create(
                user=request.user,
                subject=subject,
                category=category,
                description=description,
                priority=priority if priority in ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL') else 'MEDIUM',
                status='OPEN',
                attachment=attachment,
            )
            messages.success(request, 'Ticket submitted successfully.')
            return redirect('customer:my_tickets')
        except Exception:
            messages.error(request, 'Could not submit ticket. Please try again.')
            return redirect('customer:submit_ticket')
    return render(request, 'customer/submit_ticket.html', ctx)


@login_required
def my_tickets_view(request):
    if getattr(request.user, 'role', '').upper() != 'CUSTOMER':
        messages.error(request, 'Only customers can view their tickets.')
        return redirect('customer:welcome')
    qs = CustomerTicket.objects.filter(user=request.user).order_by('-updated_at')
    rows = []
    for t in qs:
        rows.append({
            'pk': t.pk,
            'ticket_id': t.ticket_id,
            'subject': t.subject,
            'status': t.status,
            'priority': t.priority,
            'updated': t.updated_at,
            'created': t.created_at,
        })
    ctx = {**_base_context(request), 'tickets': rows}
    return render(request, 'customer/my_tickets.html', ctx)


@login_required
def ticket_detail_view(request, ticket_id):
    ticket = get_object_or_404(CustomerTicket, ticket_id=ticket_id, user=request.user)
    ctx = {**_base_context(request), 'ticket': ticket}
    return render(request, 'customer/ticket_detail.html', ctx)


@login_required
def meetings_view(request):
    return render(request, 'customer/meetings.html', _base_context(request))


@login_required
def bookings_view(request):
    return render(request, 'customer/bookings.html', _base_context(request))


@login_required
def profile_view(request):
    return render(request, 'customer/profile.html', _base_context(request))


@login_required
def profile_edit_view(request):
    form = CustomerProfileForm(request.POST or None, instance=request.user)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        image = request.FILES.get('profile_image')
        _rebuild_profile(user, image=image)
        messages.success(request, 'Profile updated successfully.')
        return redirect('customer:profile')
    ctx = {**_base_context(request), 'form': form}
    return render(request, 'customer/profile_edit.html', ctx)


@login_required
def password_change_view(request):
    form = CustomerPasswordChangeForm(request.user, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        messages.success(request, 'Password changed successfully.')
        return redirect('customer:profile')
    ctx = {**_base_context(request), 'form': form}
    return render(request, 'customer/password_change.html', ctx)
