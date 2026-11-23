"""SQLite storage for jobs, resume versions, documents, chat and agent runs."""
import json
import sqlite3
import time
from contextlib import contextmanager

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    source TEXT, title TEXT, company TEXT, location TEXT, remote INTEGER,
    url TEXT, description TEXT, salary TEXT, tags TEXT, posted_at TEXT,
    found_at REAL, score REAL DEFAULT 0, matched TEXT, missing TEXT,
    ai_verdict TEXT, status TEXT DEFAULT 'new', notes TEXT DEFAULT '',
    alerted INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS jobs_score ON jobs(score DESC);
CREATE TABLE IF NOT EXISTS resumes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, text TEXT,
    profile TEXT, created REAL, is_master INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, title TEXT,
    content TEXT, job_id TEXT, agent TEXT, created REAL
);
CREATE TABLE IF NOT EXISTS chat (
    id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT, content TEXT,
    agent TEXT, created REAL
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, started REAL,
    finished REAL, summary TEXT, ok INTEGER
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, date TEXT, time TEXT DEFAULT '',
    kind TEXT DEFAULT 'event', job_id TEXT, notes TEXT DEFAULT '', done INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS mock (
    id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT, style TEXT, questions INTEGER,
    transcript TEXT, created REAL, agent TEXT
);
CREATE TABLE IF NOT EXISTS skill_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, level INTEGER, ts REAL
);
CREATE TABLE IF NOT EXISTS skills (
    name TEXT PRIMARY KEY, level INTEGER DEFAULT 0, target INTEGER DEFAULT 3,
    demand INTEGER DEFAULT 0, plan TEXT DEFAULT '', updated REAL
);
"""


def connect():
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    return con


@contextmanager
def db():
    con = connect()
    try:
        yield con
        con.commit()
    finally:
        con.close()


# columns added after v1 (kept as migrations so existing databases upgrade in place)
JOB_COLUMNS = {
    "kind": "TEXT DEFAULT 'job'",        # job | research | collaborator | hackathon | funding | fellowship
    "categories": "TEXT DEFAULT '[]'",
    "deadline": "TEXT DEFAULT ''",       # YYYY-MM-DD
    "applied_at": "TEXT DEFAULT ''",
    "next_action": "TEXT DEFAULT ''",
    "next_date": "TEXT DEFAULT ''",
    "extra": "TEXT DEFAULT '{}'",
    "reminded": "TEXT DEFAULT ''",
    "country": "TEXT DEFAULT ''",          # ISO-2 code derived from location (for country filters)
}


def init():
    with db() as con:
        con.executescript(SCHEMA)
        have = {r[1] for r in con.execute("PRAGMA table_info(jobs)")}
        for col, ddl in JOB_COLUMNS.items():
            if col not in have:
                con.execute(f"ALTER TABLE jobs ADD COLUMN {col} {ddl}")


def rows(sql, args=()):
    with db() as con:
        return [dict(r) for r in con.execute(sql, args).fetchall()]


def one(sql, args=()):
    r = rows(sql, args)
    return r[0] if r else None


def execute(sql, args=()):
    with db() as con:
        cur = con.execute(sql, args)
        return cur.lastrowid


def upsert_job(j: dict) -> bool:
    """Insert a job if new. Returns True when it was new.
    Prevents cross-source duplicates by checking ID, URL, and title+company.
    """
    if not j.get("id") or not j.get("title"):
        return False
    from .governance import is_gemini, has_approval, queue_proposal
    if is_gemini(j) and not has_approval(j):
        queue_proposal(j)
        return False
    with db() as con:
        if con.execute("SELECT 1 FROM jobs WHERE id=?", (j["id"],)).fetchone():
            return False
        url = (j.get("url") or "").strip()
        if not url:
            return False
        from datetime import date
        dl = str(j.get("deadline") or "").strip()
        if dl and len(dl) >= 10 and dl[:10] < date.today().isoformat():
            return False
        from . import verifier
        checker = verifier.is_generic_job_url if j.get("kind", "job") in (
            "job", "internship", "research") else verifier.is_generic_url
        if checker(url)[0]:
            return False
        if len(url) > 12 and con.execute("SELECT 1 FROM jobs WHERE url=?", (url,)).fetchone():
            return False
        t_clean = (j.get("title") or "").strip().lower()
        c_clean = (j.get("company") or "").strip().lower()
        if t_clean and c_clean and len(c_clean) > 2:
            if con.execute("SELECT 1 FROM jobs WHERE lower(title)=? AND lower(company)=? AND lower(location)=?",
                           (t_clean, c_clean, (j.get("location") or "").strip().lower())).fetchone():
                return False
        con.execute(
            """INSERT INTO jobs (id, source, title, company, location, remote, url,
               description, salary, tags, posted_at, found_at, kind, deadline, extra)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (j["id"], j["source"], j["title"], j["company"], j["location"],
             int(bool(j.get("remote"))), j["url"], j["description"], j.get("salary", ""),
             json.dumps(j.get("tags", [])), j.get("posted_at", ""), time.time(),
             j.get("kind", "job"), j.get("deadline", ""), json.dumps(j.get("extra", {}))),
        )
        return True


def deduplicate_jobs() -> dict:
    """Scans all jobs in the database and cleans up duplicates (title+company or identical URLs).
    Preserves user interactions (applied, saved, interview, notes, reviews) and highest scores.
    """
    import re
    all_jobs = rows("SELECT id, title, company, location, url, score, status, notes, ai_verdict, kind, found_at FROM jobs "
                    "ORDER BY score DESC, found_at DESC")
    seen_tc = {}
    seen_url = {}
    to_delete = []

    def norm_s(s):
        return re.sub(r"[^a-z0-9]", "", (s or "").lower())

    def norm_u(u):
        if not u:
            return ""
        return re.sub(r"https?://(www\.)?", "", u.lower()).split("?")[0].split("#")[0].rstrip("/")

    for r in all_jobs:
        tc = (norm_s(r["title"])[:35], norm_s(r["company"])[:25],
              norm_s(r.get("location", "")))
        uk = norm_u(r["url"])

        # Interaction priority
        prio = 0
        if r["status"] in ("applied", "interview", "offer", "saved"):
            prio += 1000
        if r["notes"]:
            prio += 500
        if r["ai_verdict"]:
            prio += 250
        prio += (r["score"] or 0)

        match = None
        if tc[0] and tc[1] and tc in seen_tc:
            match = seen_tc[tc]
        elif uk and len(uk) > 15 and uk in seen_url:
            match = seen_url[uk]

        if match:
            orig, orig_prio = match
            if prio > orig_prio:
                to_delete.append(orig["id"])
                seen_tc[tc] = (r, prio)
                if uk:
                    seen_url[uk] = (r, prio)
            else:
                to_delete.append(r["id"])
        else:
            if tc[0] and tc[1]:
                seen_tc[tc] = (r, prio)
            if uk:
                seen_url[uk] = (r, prio)

    if to_delete:
        delete_jobs(to_delete)

    return {"scanned": len(all_jobs), "deleted_duplicates": len(to_delete), "unique_remaining": len(all_jobs) - len(to_delete)}


def master_resume():
    return one("SELECT * FROM resumes WHERE is_master=1 ORDER BY id DESC LIMIT 1") or \
        one("SELECT * FROM resumes ORDER BY id DESC LIMIT 1")


def save_doc(kind, title, content, job_id=None, agent=""):
    return execute(
        "INSERT INTO documents (kind,title,content,job_id,agent,created) VALUES (?,?,?,?,?,?)",
        (kind, title, content, job_id, agent, time.time()),
    )


def log_run(kind, summary, ok=True, started=None):
    execute(
        "INSERT INTO runs (kind,started,finished,summary,ok) VALUES (?,?,?,?,?)",
        (kind, started or time.time(), time.time(), summary, int(ok)),
    )


def country_filter():
    """SQL fragment hiding excluded countries (Config → excluded_countries, e.g. the US toggle)."""
    from .config import get_settings
    ex = [c.upper() for c in get_settings().get("excluded_countries", []) if c]
    if not ex:
        return "", []
    return f" AND country NOT IN ({','.join('?' * len(ex))})", ex


# Separate sections: these never appear in Tracks (jobs) and have their own views/alerts.
_POSTDOC = ("(kind='research' OR lower(title) LIKE '%postdoc%' OR lower(title) LIKE '%post-doc%' "
            "OR lower(title) LIKE '%postdoctoral%' OR lower(title) LIKE '%post-doctoral%')")
SECTIONS = {
    "postdocs": f"({_POSTDOC} AND kind NOT IN ('fellowship','collaborator','hackathon'))",
    "fellowships": "kind='fellowship' OR lower(title) LIKE '%fellowship%'",
    "hackathons": "kind='hackathon' OR lower(title) LIKE '%hackathon%'",
    "contacts": "kind='collaborator'",
    "grants": "kind IN ('funding', 'startup_funding') OR lower(title) LIKE '%funding call%' OR lower(title) LIKE '%subvention%'",
    "events": "kind IN ('conference','event') OR lower(title) LIKE '%webinar%' OR lower(title) LIKE '%job fair%'",
    "trends": "kind='trend'",
    "intel": "kind IN ('intel', 'target')",
}
SECTIONS["jobs"] = "kind IN ('job','internship') AND NOT (" + " OR ".join(f"({v})" for k, v in SECTIONS.items() if k != "jobs") + ")"


def section_of(job):
    t = (job.get("title") or "").lower()
    k = job.get("kind") or "job"
    if k == "fellowship" or "fellowship" in t:
        return "fellowships"
    if k == "hackathon" or "hackathon" in t:
        return "hackathons"
    if k == "collaborator":
        return "contacts"
    if k in ("funding", "startup_funding") or "funding" in t or "grant" in t or "subvention" in t:
        return "grants"
    if k in ("conference", "event") or "conference" in t or "webinar" in t or "job fair" in t:
        return "events"
    if k == "trend":
        return "trends"
    if k in ("intel", "target"):
        return "intel"
    if k == "research" or any(w in t for w in ("postdoc", "post-doc", "postdoctoral", "post-doctoral")):
        return "postdocs"
    return "jobs"


def delete_job(job_id: str) -> bool:
    if not job_id:
        return False
    with db() as con:
        con.execute("DELETE FROM jobs WHERE id=?", (job_id,))
        con.execute("DELETE FROM documents WHERE job_id=?", (job_id,))
        con.execute("DELETE FROM events WHERE job_id=?", (job_id,))
    return True


def delete_jobs(job_ids: list) -> int:
    if not job_ids:
        return 0
    with db() as con:
        placeholders = ",".join("?" * len(job_ids))
        con.execute(f"DELETE FROM jobs WHERE id IN ({placeholders})", job_ids)
        con.execute(f"DELETE FROM documents WHERE job_id IN ({placeholders})", job_ids)
        con.execute(f"DELETE FROM events WHERE job_id IN ({placeholders})", job_ids)
    return len(job_ids)


def cleanup_jobs(max_days_rejected=30, min_score_new=30, max_days_new=60) -> dict:
    """Automatic cleanup:
    1. Status 'rejected' older than max_days_rejected days
    2. Status 'new' with score < min_score_new older than max_days_new days
    3. Past deadlines older than 30 days with status 'new'
    """
    from datetime import date, timedelta
    now = time.time()
    day_sec = 86400
    rejected_cutoff = now - (max_days_rejected * day_sec)
    new_cutoff = now - (max_days_new * day_sec)
    today_str = date.today().isoformat()
    old_applied = (date.today() - timedelta(days=max_days_rejected)).isoformat()

    deleted = {"rejected": 0, "low_score": 0, "expired_deadline": 0, "total": 0}
    with db() as con:
        r1 = con.execute(
            "SELECT id FROM jobs WHERE status='rejected' AND (found_at < ? OR (applied_at != '' AND applied_at < ?))",
            (rejected_cutoff, old_applied)
        ).fetchall()
        ids1 = [r[0] for r in r1]
        deleted["rejected"] = len(ids1)

        r2 = con.execute(
            "SELECT id FROM jobs WHERE status='new' AND score < ? AND found_at < ?",
            (min_score_new, new_cutoff)
        ).fetchall()
        ids2 = [r[0] for r in r2 if r[0] not in ids1]
        deleted["low_score"] = len(ids2)

        r3 = con.execute(
            "SELECT id FROM jobs WHERE status='new' AND deadline != '' AND deadline < ?",
            (today_str,)
        ).fetchall()
        ids3 = [r[0] for r in r3 if r[0] not in ids1 and r[0] not in ids2]
        deleted["expired_deadline"] = len(ids3)

        all_ids = ids1 + ids2 + ids3
        if all_ids:
            placeholders = ",".join("?" * len(all_ids))
            con.execute(f"DELETE FROM jobs WHERE id IN ({placeholders})", all_ids)
            con.execute(f"DELETE FROM documents WHERE job_id IN ({placeholders})", all_ids)
            con.execute(f"DELETE FROM events WHERE job_id IN ({placeholders})", all_ids)
        deleted["total"] = len(all_ids)
    return deleted
