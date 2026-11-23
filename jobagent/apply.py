"""Application modes.

assisted   — build the application pack, open the posting, move the job to 'applying'. The user submits.
email_auto — when the posting gives an application email, a tailored email + the user's CV file is queued and sent
             from the user's own account by the scheduler, at most `apply_daily_limit` per day. Queued sends can be
             cancelled until they go out.
web_assist — (the safe replacement for form bots) pack + posting opened with answers ready to copy. JobAgent never
             fills or submits third-party web forms automatically.
"""
import json
import re
import time
from datetime import date
from pathlib import Path

from . import ai, db, emailer
from .config import get_settings

SCHEMA = """CREATE TABLE IF NOT EXISTS apply_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT, to_addr TEXT, subject TEXT, body TEXT,
    attachment TEXT, status TEXT DEFAULT 'queued', created REAL, sent_at REAL, error TEXT)"""
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
SKIP = ("noreply", "no-reply", "donotreply", "privacy", "rgpd", "gdpr", "dpo@", "support@", "info@linkedin", "jobs-noreply")


def setup():
    db.execute(SCHEMA)


def application_email(job):
    """An application address explicitly given in the posting (never guessed)."""
    for m in EMAIL_RE.findall(job.get("description") or ""):
        m = m.strip(".")
        if not any(x in m.lower() for x in SKIP) and not m.lower().endswith((".png", ".jpg")):
            return m
    return ""


def _letter(job, agent=None):
    from .coach import resume_text, profile_brief
    lang = get_settings().get("apply_language", "auto")
    prompt = f"""Write a job APPLICATION EMAIL for this posting{'' if lang == 'auto' else ' in ' + lang}
(if 'auto': use the language the posting is written in). Return ONLY JSON:
{{"subject": "...", "body": "plain-text email, 150-220 words, ends with my name and says my CV is attached"}}
Use only facts from my resume; no invented numbers; no salary or work-authorisation claims.

POSTING: {job['title']} — {job['company']} ({job['location']})
{(job.get('description') or '')[:4000]}

MY PROFILE:
{profile_brief()}
MY RESUME:
{resume_text()[:6000]}"""
    out, used = ai.ask(prompt, agent=agent, task="writing")
    d = json.loads(re.search(r"\{.*\}", out, re.S).group(0))
    return d["subject"].strip(), d["body"].strip(), used


def start(job_id, mode=None, agent=None, to=None):
    """Run the configured (or given) mode for one job. Returns what happened."""
    from . import extras
    setup()
    s = get_settings()
    mode = mode or s.get("apply_mode", "assisted")
    if mode == "web_auto":
        mode = "web_assist"
    j = db.one("SELECT * FROM jobs WHERE id=?", (job_id,))
    if not j:
        raise ValueError("unknown job")
    out = {"mode": mode, "url": j["url"]}
    if mode in ("assisted", "web_assist"):
        pack = extras.application_pack(job_id, agent)
        out.update(pack_folder=pack["folder"], files=pack["files"], agent=pack["agent"])
        db.execute("UPDATE jobs SET status='applying' WHERE id=? AND status IN ('new','saved')", (job_id,))
        return out
    # email_auto
    addr = to or application_email(j)
    if not addr:
        out.update(mode="assisted", note="No application email in this posting, so it was prepared for you to submit instead.")
        return {**out, **start(job_id, "assisted", agent)}
    cv = s.get("cv_file")
    if not cv or not Path(cv).exists():
        raise ValueError("Upload your CV file (Resume tab) so it can be attached.")
    if not emailer.configured():
        raise ValueError("Connect your email first (Setup → Email).")
    dup = db.one("SELECT id FROM apply_queue WHERE job_id=? AND status IN ('queued','sent')", (job_id,))
    if dup:
        return {**out, "queued": dup["id"], "note": "Already queued or sent for this job, so nothing new was queued."}
    subject, body, used = _letter(j, agent)
    qid = db.execute("INSERT INTO apply_queue (job_id,to_addr,subject,body,attachment,created) VALUES (?,?,?,?,?,?)",
                     (job_id, addr, subject, body, cv, time.time()))
    db.execute("UPDATE jobs SET status='applying' WHERE id=? AND status IN ('new','saved')", (job_id,))
    out.update(queued=qid, to=addr, subject=subject, agent=used,
               note=f"Queued. Sends automatically (max {s.get('apply_daily_limit', 5)}/day) unless you cancel it.")
    return out


def sent_today():
    setup()
    start_of_day = time.mktime(date.today().timetuple())
    return db.one("SELECT COUNT(*) n FROM apply_queue WHERE status='sent' AND sent_at >= ?", (start_of_day,))["n"]


def send_due(log=print):
    """Send queued application emails within today's limit (called by the scheduler and the 'Send now' button)."""
    setup()
    s = get_settings()
    room = max(0, int(s.get("apply_daily_limit", 5)) - sent_today())
    sent = 0
    for q in db.rows("SELECT * FROM apply_queue WHERE status='queued' ORDER BY id LIMIT ?", (room,)):
        try:
            emailer.send_to(q["to_addr"], q["subject"], q["body"], [q["attachment"]])
            db.execute("UPDATE apply_queue SET status='sent', sent_at=? WHERE id=?", (time.time(), q["id"]))
            db.execute("UPDATE jobs SET status='applied', applied_at=? WHERE id=?", (date.today().isoformat(), q["job_id"]))
            sent += 1
            log(f"  application sent → {q['to_addr']}")
        except Exception as e:  # noqa: BLE001
            db.execute("UPDATE apply_queue SET status='error', error=? WHERE id=?", (str(e)[:300], q["id"]))
    return {"sent": sent, "left_today": room - sent}


def queue():
    setup()
    return db.rows("SELECT q.*, j.title, j.company FROM apply_queue q LEFT JOIN jobs j ON j.id=q.job_id ORDER BY q.id DESC LIMIT 50")


def cancel(qid):
    setup()
    db.execute("UPDATE apply_queue SET status='cancelled' WHERE id=? AND status='queued'", (qid,))
