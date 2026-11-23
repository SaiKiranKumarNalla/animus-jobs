"""Auto-email tracker for job applications.

Connects to IMAP (e.g. Gmail) using SMTP_USER / SMTP_PASSWORD or dedicated IMAP credentials,
scans recent incoming recruiter/ATS emails, identifies the target application,
classifies the status (applied / interview / rejected / offer), and updates the pipeline.
"""
from datetime import date, datetime, timedelta, timezone
from email import policy
from email.header import decode_header
from email.parser import BytesParser
import imaplib
import json
import os
import re
import time

from . import ai, db
from .config import DATA, get_settings


def configured():
    """True if IMAP credentials can be derived from .env or settings."""
    user = os.environ.get("IMAP_USER") or os.environ.get("SMTP_USER")
    pw = os.environ.get("IMAP_PASSWORD") or os.environ.get("SMTP_PASSWORD")
    return bool(user and pw)


def _get_imap_config():
    host = os.environ.get("IMAP_HOST") or "imap.gmail.com"
    port = int(os.environ.get("IMAP_PORT") or 993)
    user = os.environ.get("IMAP_USER") or os.environ.get("SMTP_USER")
    pw = os.environ.get("IMAP_PASSWORD") or os.environ.get("SMTP_PASSWORD")
    return host, port, user, pw


def connect_imap():
    host, port, user, pw = _get_imap_config()
    if not (user and pw):
        raise RuntimeError("IMAP credentials not configured. Set SMTP_USER / SMTP_PASSWORD or IMAP_USER / IMAP_PASSWORD in .env")
    mail = imaplib.IMAP4_SSL(host, port, timeout=30)
    mail.login(user, pw)
    return mail


def _decode_hdr(val):
    if not val:
        return ""
    parts = []
    for text, enc in decode_header(val):
        if isinstance(text, bytes):
            parts.append(text.decode(enc or "utf-8", errors="replace"))
        else:
            parts.append(str(text))
    return " ".join(parts).strip()


def _extract_body(msg):
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            cdisp = str(part.get("Content-Disposition", ""))
            if ctype == "text/plain" and "attachment" not in cdisp:
                payload = part.get_payload(decode=True)
                if payload:
                    body += payload.decode("utf-8", errors="replace") + "\n"
        if not body:  # fallback to html
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    payload = part.get_payload(decode=True)
                    if payload:
                        raw = payload.decode("utf-8", errors="replace")
                        body += re.sub(r"<[^>]+>", " ", raw) + "\n"
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            body = payload.decode("utf-8", errors="replace")
    return re.sub(r"\s+", " ", body).strip()


REJECTION_PATTERNS = [
    r"\bunfortunately\b",
    r"\bafter careful consideration\b",
    r"\bnot moving forward\b",
    r"\bother candidates\b",
    r"\bdecided to pursue\b",
    r"\bregret to inform\b",
    r"\bwill not be moving forward\b",
    r"\bwill not be progressing\b",
    r"\bunable to offer\b",
    r"\bnot selected\b",
    r"\bposition has been filled\b",
]

INTERVIEW_PATTERNS = [
    r"\binvitation to interview\b",
    r"\bschedule (?:a|an|our) (?:call|chat|interview|conversation)\b",
    r"\binterview (?:invitation|confirmation|details|scheduled)\b",
    r"\bscreening (?:call|interview)\b",
    r"\bcalendly\.com\b",
    r"\bavailability for (?:a|an) (?:interview|call|chat)\b",
    r"\bwould like to speak with you\b",
    r"\bnext step in our process\b",
    r"\btechnical interview\b",
    r"\bround of interviews\b",
]

OFFER_PATTERNS = [
    r"\boffer of employment\b",
    r"\bjob offer\b",
    r"\bpleased to offer\b",
    r"\bdelighted to offer\b",
    r"\bcongratulations on your offer\b",
]

CONFIRMATION_PATTERNS = [
    r"\breceived your application\b",
    r"\bthank you for applying\b",
    r"\bapplication (?:has been )?submitted\b",
    r"\bapplication received\b",
    r"\bwe have received your resume\b",
]


def classify_text(subject, body, agent=None):
    """Classifies application status from subject + body.
    Returns (status, confidence, reason) where status is one of:
    'interview', 'rejected', 'offer', 'applied', or None.
    """
    combined = f"{subject}\n{body}".lower()

    # Rule-based fast check
    for pat in OFFER_PATTERNS:
        if re.search(pat, combined, re.I):
            return "offer", 0.95, f"Matched offer pattern: {pat}"

    for pat in INTERVIEW_PATTERNS:
        if re.search(pat, combined, re.I):
            return "interview", 0.90, f"Matched interview pattern: {pat}"

    for pat in REJECTION_PATTERNS:
        if re.search(pat, combined, re.I):
            return "rejected", 0.90, f"Matched rejection pattern: {pat}"

    for pat in CONFIRMATION_PATTERNS:
        if re.search(pat, combined, re.I):
            return "applied", 0.85, f"Matched confirmation pattern: {pat}"

    # If ambiguous and an AI agent is available, use lightweight classification
    if agent or ai.status().get("gemini", {}).get("ready") or ai.status().get("claude_cli", {}).get("ready"):
        prompt = f"""Classify this recruitment email into exactly one status:
[interview, rejected, offer, applied, unrelated]

SUBJECT: {subject[:200]}
BODY: {body[:1500]}

Respond ONLY in JSON format:
{{"status": "interview|rejected|offer|applied|unrelated", "reason": "short explanation"}}
"""
        try:
            res_text, _ = ai.ask(prompt, agent=agent or "gemini", task="coach")
            m = re.search(r"\{.*\}", res_text, re.S)
            if m:
                data = json.loads(m.group(0))
                st = data.get("status")
                if st in ("interview", "rejected", "offer", "applied"):
                    return st, 0.85, data.get("reason", "AI classification")
        except Exception:
            pass

    return None, 0.0, "No clear recruitment intent"


def _clean_str(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def find_matching_job(subject, sender, body, active_jobs):
    """Finds which tracked job this email refers to."""
    sender_clean = sender.lower()
    subject_clean = subject.lower()
    body_clean = body.lower()

    best_match = None
    best_score = 0

    for j in active_jobs:
        company = (j["company"] or "").strip()
        title = (j["title"] or "").strip()
        if not company or len(company) < 3:
            continue

        c_clean = company.lower()
        score = 0

        # Exact company name in sender domain or display name
        if c_clean in sender_clean:
            score += 6
        # Company name in subject
        if re.search(rf"\b{re.escape(c_clean)}\b", subject_clean, re.I):
            score += 5
        # Company name in body
        elif re.search(rf"\b{re.escape(c_clean)}\b", body_clean, re.I):
            score += 3

        # Title keywords in subject or body
        title_words = [w for w in re.findall(r"\w{4,}", title.lower()) if w not in ("engineer", "scientist", "senior", "lead", "staff")]
        title_matches = sum(1 for w in title_words if w in subject_clean or w in body_clean)
        score += min(3, title_matches)

        if score > best_score and score >= 4:
            best_score = score
            best_match = j

    return best_match, best_score


def sync_inbox(days=14, limit=50, dry_run=False, agent=None):
    """Scans IMAP mailbox for recent application updates, classifies them,
    and updates jobs and calendar events in the database.
    """
    if not configured():
        return {"ok": False, "error": "Email credentials not configured in .env (SMTP_USER / SMTP_PASSWORD)"}

    # Retrieve all active or recent jobs from SQLite
    jobs = db.rows("SELECT id, title, company, status, deadline, applied_at, next_action FROM jobs WHERE kind='job'")
    if not jobs:
        return {"ok": True, "checked": 0, "matched": 0, "updates": []}

    mail = connect_imap()
    mail.select("INBOX", readonly=True)

    since_date = (date.today() - timedelta(days=days)).strftime("%d-%b-%Y")
    status_code, data = mail.search(None, f'(SINCE "{since_date}")')
    if status_code != "OK" or not data or not data[0]:
        mail.close()
        mail.logout()
        return {"ok": True, "checked": 0, "matched": 0, "updates": []}

    msg_ids = data[0].split()
    msg_ids = msg_ids[-limit:]  # most recent

    checked = 0
    updates = []

    parser = BytesParser(policy=policy.default)

    for mid in reversed(msg_ids):
        res, msg_data = mail.fetch(mid, "(RFC822)")
        if res != "OK" or not msg_data or not msg_data[0]:
            continue

        raw = msg_data[0][1]
        msg = parser.parsebytes(raw)
        checked += 1

        subject = _decode_hdr(msg.get("Subject", ""))
        sender = _decode_hdr(msg.get("From", ""))
        date_hdr = msg.get("Date", "")
        body = _extract_body(msg)

        if not subject or not body:
            continue

        # Check if email is relevant to an application
        matched_job, match_score = find_matching_job(subject, sender, body, jobs)
        if not matched_job:
            continue

        status, confidence, reason = classify_text(subject, body, agent=agent)
        if not status:
            continue

        item_update = {
            "job_id": matched_job["id"],
            "title": matched_job["title"],
            "company": matched_job["company"],
            "previous_status": matched_job["status"],
            "new_status": status,
            "confidence": confidence,
            "reason": reason,
            "subject": subject,
            "from": sender,
            "date": date_hdr,
        }

        # Don't downgrade interview or offer to applied
        if matched_job["status"] in ("interview", "offer") and status == "applied":
            continue

        updates.append(item_update)

        if not dry_run:
            today_str = date.today().isoformat()
            # Update job status
            if status == "interview":
                db.execute(
                    "UPDATE jobs SET status=?, next_action=?, next_date=? WHERE id=?",
                    ("interview", f"Interview invitation from {matched_job['company']}", today_str, matched_job["id"])
                )
                db.execute(
                    "INSERT INTO events (title, date, kind, job_id, notes) VALUES (?,?,?,?,?)",
                    (f"Interview: {matched_job['company']} ({matched_job['title']})", today_str, "interview", matched_job["id"], f"From: {sender}\nSubject: {subject}")
                )
            elif status == "rejected":
                db.execute("UPDATE jobs SET status=?, next_action=? WHERE id=?", ("rejected", "Closed (rejected)", matched_job["id"]))
            elif status == "offer":
                db.execute("UPDATE jobs SET status=?, next_action=? WHERE id=?", ("offer", f"Offer received from {matched_job['company']}", matched_job["id"]))
                db.execute(
                    "INSERT INTO events (title, date, kind, job_id, notes) VALUES (?,?,?,?,?)",
                    (f"Offer Received: {matched_job['company']}", today_str, "offer", matched_job["id"], f"From: {sender}\nSubject: {subject}")
                )
            elif status == "applied" and matched_job["status"] == "new":
                db.execute("UPDATE jobs SET status='applied', applied_at=? WHERE id=?", (today_str, matched_job["id"]))

    try:
        mail.close()
        mail.logout()
    except Exception:
        pass

    return {
        "ok": True,
        "checked": checked,
        "matched": len(updates),
        "updates": updates,
    }


def stalled_applications(days_threshold=7):
    """Finds active applications that have had no response or update for >= days_threshold."""
    from datetime import date
    today_dt = date.today()
    rows = db.rows(
        "SELECT id, title, company, status, applied_at, next_action, next_date, score, url "
        "FROM jobs WHERE status IN ('applied', 'applying', 'interview') ORDER BY applied_at DESC"
    )
    stalled = []
    for r in rows:
        app_date_str = r.get("applied_at") or ""
        days_stalled = None
        if app_date_str:
            try:
                ad = date.fromisoformat(app_date_str[:10])
                days_stalled = (today_dt - ad).days
            except Exception:
                pass

        # If next_date is set in the future, it is not stalled
        next_dt_str = r.get("next_date") or ""
        if next_dt_str:
            try:
                nd = date.fromisoformat(next_dt_str[:10])
                if nd >= today_dt:
                    continue
            except Exception:
                pass

        if days_stalled is not None and days_stalled >= days_threshold:
            stalled.append({
                "id": r["id"],
                "title": r["title"],
                "company": r["company"],
                "status": r["status"],
                "applied_at": app_date_str,
                "days_stalled": days_stalled,
                "score": r["score"],
                "url": r["url"],
                "recommendation": (
                    f"Applied {days_stalled} days ago. Perfect time to send a polite 3-sentence check-in."
                    if r["status"] == "applied"
                    else f"Interview follow-up: {days_stalled} days since activity."
                ),
            })
        elif not app_date_str and r["status"] in ("applied", "applying"):
            stalled.append({
                "id": r["id"],
                "title": r["title"],
                "company": r["company"],
                "status": r["status"],
                "applied_at": "unknown",
                "days_stalled": days_threshold,
                "score": r["score"],
                "url": r["url"],
                "recommendation": "Marked applied without date. Check status or follow up.",
            })

    return stalled


def draft_followup(job_id, language="English", agent=None):
    """Drafts a high-impact, polite follow-up email for a stalled application."""
    from . import coach
    return coach.draft_email(
        kind="follow_up",
        job_id=job_id,
        context="It has been over a week since applying. Reiterate genuine enthusiasm for their team, cite our PhD fit in medical imaging/PET, and ask about their recruitment timeline.",
        language=language,
        agent=agent,
    )
