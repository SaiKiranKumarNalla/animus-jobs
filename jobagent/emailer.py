"""Gmail (SMTP) alerts. Configure SMTP_USER / SMTP_PASSWORD (Gmail app password) in .env."""
import html
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .config import get_settings


def configured():
    return bool(os.environ.get("SMTP_USER") and os.environ.get("SMTP_PASSWORD"))


def send(subject, html_body, text_body=""):
    if not configured():
        raise RuntimeError("Email not configured: set SMTP_USER and SMTP_PASSWORD in .env")
    to = get_settings().get("email_to") or os.environ.get("ALERT_EMAIL_TO") or os.environ["SMTP_USER"]
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, os.environ["SMTP_USER"], to
    msg.attach(MIMEText(text_body or subject, "plain"))
    msg.attach(MIMEText(html_body, "html"))
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    smtp = smtplib.SMTP_SSL(host, port, timeout=30) if port == 465 else smtplib.SMTP(host, port, timeout=30)
    with smtp as s:
        if port != 465:
            s.starttls()
        s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        s.sendmail(os.environ["SMTP_USER"], [a.strip() for a in to.split(",")], msg.as_string())
    return to


def _e(x):
    return html.escape(str(x or ""))


SECTION_TITLES = {"jobs": "💼 Jobs (industry)", "postdocs": "🎓 Academia · Postdoc positions",
                  "fellowships": "🎓 Academia · Fellowships", "grants": "🎓 Academia · Research grants",
                  "hackathons": "⚡ Hackathons", "events": "✺ Events, webinars & job fairs", "contacts": "⚭ Contacts"}


def jobs_html(jobs, intro=""):
    from .db import section_of
    rows = []
    groups = {}
    for j in jobs:
        groups.setdefault(section_of(j), []).append(j)
    ordered = []
    for sec in SECTION_TITLES:
        for k, j in enumerate(groups.get(sec, [])):
            j["_hdr"] = SECTION_TITLES[sec] + f" ({len(groups[sec])})" if k == 0 else ""
            ordered.append(j)
    for j in ordered:
        if j.get("_hdr"):
            rows.append(f"<tr><td style='padding:18px 0 4px;font-size:18px;font-weight:700;color:#111'>{_e(j['_hdr'])}</td></tr>")
        v = j.get("ai") or {}
        badge = f"<b style='color:#0a7d4f'>{_e(v.get('verdict','').upper())} {_e(v.get('fit',''))}</b> · " if v else ""
        rows.append(f"""
<tr><td style="padding:12px 0;border-bottom:1px solid #eee">
  <div style="font-size:16px"><a href="{_e(j['url'])}" style="color:#1a56db;text-decoration:none"><b>{_e(j['title'])}</b></a></div>
  <div style="color:#555">{('<b>' + _e(j.get('kind','job')).upper() + '</b> · ') if j.get('kind','job')!='job' else ''}{_e(j['company'])} · {_e(j['location'])} · <i>{_e(j['source'])}</i>{(' · <b style="color:#b91c1c">deadline ' + _e(j['deadline']) + '</b>') if j.get('deadline') else ''}</div>
  <div style="margin-top:4px">{badge}Match <b>{j['score']:.0f}</b>/100
  {(' · matched: ' + _e(', '.join(j.get('matched_list', [])[:6]))) if j.get('matched_list') else ''}</div>
  {f"<div style='color:#333;margin-top:4px'>{_e(v.get('why'))}<br><i>Angle:</i> {_e(v.get('angle'))}</div>" if v.get('why') else ''}
  {f"<div style='color:#b45309'>Gaps: {_e(', '.join(j.get('missing_list', [])[:6]))}</div>" if j.get('missing_list') else ''}
</td></tr>""")
    return f"""<div style="font-family:-apple-system,Segoe UI,Arial,sans-serif;max-width:680px;margin:auto">
<h2 style="margin-bottom:4px">🎯 JobAgent</h2><p style="color:#444">{intro}</p>
<table style="width:100%;border-collapse:collapse">{''.join(rows)}</table>
<p style="color:#888;font-size:12px">Open your dashboard: http://127.0.0.1:8765 to draft cover letters, emails and tailor your resume for any of these.</p></div>"""


def md_html(title, md):
    body = _e(md).replace("\n", "<br>")
    return f"<div style='font-family:-apple-system,Arial,sans-serif;max-width:720px;margin:auto'><h2>{_e(title)}</h2><div>{body}</div></div>"


def send_to(to, subject, text_body, attachments=(), reply_to=None):
    """Send a plain-text email from the user's own account to someone else (application emails), with files."""
    from email.mime.application import MIMEApplication
    from pathlib import Path
    if not configured():
        raise RuntimeError("Email not configured")
    msg = MIMEMultipart()
    msg["Subject"], msg["From"], msg["To"] = subject, os.environ["SMTP_USER"], to
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    for f in attachments:
        part = MIMEApplication(Path(f).read_bytes(), Name=Path(f).name)
        part["Content-Disposition"] = f'attachment; filename="{Path(f).name}"'
        msg.attach(part)
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    smtp = smtplib.SMTP_SSL(host, port, timeout=30) if port == 465 else smtplib.SMTP(host, port, timeout=30)
    with smtp as s:
        if port != 465:
            s.starttls()
        s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        s.sendmail(os.environ["SMTP_USER"], [to], msg.as_string())
    return to
