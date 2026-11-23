"""Template jobs: postings the user found by hand that show what they want.

• Each template becomes a reference profile (title words + skills + key terms) — no AI needed.
• rescore_all() boosts opportunities that resemble any template (up to +20, "like your template: …").
• gap_plan() asks the AI what the templates have in common, what the CV lacks, and the steps to close the gap.
"""
import json
import re
import time
from collections import Counter

import httpx

from . import ai, db, scoring
from .sources import clean

SCHEMA = """CREATE TABLE IF NOT EXISTS templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, company TEXT, url TEXT, text TEXT,
    job_id TEXT, created REAL, terms TEXT)"""


def setup():
    db.execute(SCHEMA)


def _terms(title, text):
    """Reference profile of a posting: title words (weighted), skills, frequent domain terms."""
    t = scoring.translate_fr(f"{title} {title} {text}")
    words = [w for w in re.findall(r"[a-zà-ü][a-zà-ü+#.\-]{2,}", scoring.norm(title)) if w not in scoring.STOP]
    c = Counter({w: 3 for w in words})
    for sk in scoring.extract_skills(t):
        c[sk] += 2
    for w in scoring.top_terms(t, 25):
        c[w] += 1
    return dict(c.most_common(45))


def fetch_text(url):
    """Best-effort text of a posting the user pasted (their own link). Blocked pages just return ''."""
    try:
        r = httpx.get(url, timeout=15, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
        return clean(r.text)[:12000] if r.status_code == 200 else ""
    except Exception:  # noqa: BLE001
        return ""


def add(title="", company="", url="", text="", job_id=None):
    setup()
    if job_id:
        j = db.one("SELECT title, company, url, description FROM jobs WHERE id=?", (job_id,))
        if j:
            title, company, url, text = title or j["title"], company or j["company"], url or j["url"], text or j["description"]
    if url and len(text) < 200:
        text = (text + "\n" + fetch_text(url)).strip()
    if not (title or text):
        raise ValueError("Give at least a title or the posting text.")
    tid = db.execute("INSERT INTO templates (title, company, url, text, job_id, created, terms) VALUES (?,?,?,?,?,?,?)",
                     (title, company, url, text[:12000], job_id, time.time(), json.dumps(_terms(title, text))))
    return {"id": tid, "title": title, "terms": list(_terms(title, text))[:15]}


def all_templates():
    setup()
    return db.rows("SELECT id, title, company, url, job_id, created, terms FROM templates ORDER BY id DESC")


def delete(tid):
    setup()
    db.execute("DELETE FROM templates WHERE id=?", (tid,))


def _title_words(t):
    return {w for w in re.findall(r"[a-zà-ü&][a-zà-ü&+#.\-]{1,}", scoring.norm(scoring.translate_fr(t or "")))
            if w not in scoring.STOP and len(w) > 2}


def matcher():
    """Return f(job)->(bonus, why): 60% title resemblance + 40% content resemblance to the closest template."""
    temps = [(t["title"], _title_words(t["title"]), json.loads(t["terms"] or "{}")) for t in all_templates()]
    temps = [x for x in temps if x[2]]
    if not temps:
        return lambda job: (0, "")

    def f(job):
        jt = scoring.norm(scoring.translate_fr(f"{job.get('title', '')} {(job.get('description') or '')[:4000]}"))
        jw = _title_words(job.get("title", ""))
        best, best_t = 0.0, ""
        for ti, tw, te in temps:
            tot = sum(te.values())
            content = (sum(w for term, w in te.items() if scoring.has(term, jt)) / tot) if tot else 0
            title = len(jw & tw) / len(tw) if tw else 0
            sim = 0.6 * title + 0.4 * content
            if sim > best:
                best, best_t = sim, ti
        bonus = round(min(20, max(0, (best - 0.25) * 45)))  # below ~0.25 is noise
        return (bonus, f"+{bonus} like your template “{best_t[:40]}”") if bonus else (0, "")
    return f


def gap_plan(agent=None):
    """What the templates want vs. what the CV shows, and concrete steps to close the gap."""
    from .coach import resume_text, profile_brief, _kb
    temps = all_templates()
    if not temps:
        raise ValueError("Add at least one template job first.")
    full = db.rows("SELECT title, company, text FROM templates ORDER BY id DESC LIMIT 8")
    blocks = "\n\n".join(f"### {t['title']} — {t['company']}\n{(t['text'] or '')[:2500]}" for t in full)
    prompt = f"""These are TEMPLATE JOBS the candidate picked as examples of what they want next.
1. **The pattern** – what these roles have in common (level, function, domain, must-have skills, signals employers look for).
2. **Fit today** – which requirements my resume already proves (quote the evidence) and which are missing or weak.
3. **Gap-closing plan** – the 6–10 highest-leverage steps, ordered, each with: what to do, why it matters for these roles,
   time estimate, and proof I can show (project, certificate, publication, talk, open-source, portfolio piece).
4. **Positioning** – a 2-line headline and the 3 resume bullets to rewrite so I read as this kind of candidate.
5. **Search tips** – job titles, keywords (incl. local language) and company types to target more of these roles.
Never invent facts about me.

MY PROFILE:
{profile_brief()}

MY RESUME:
{resume_text()[:8000]}

TEMPLATE JOBS:
{blocks}{_kb(" ".join(t["title"] for t in full))}"""
    text, used = ai.ask(prompt, agent=agent, task="training")
    db.save_doc("template_plan", f"Template-job gap plan ({len(temps)} templates)", text, None, used)
    return text, used
