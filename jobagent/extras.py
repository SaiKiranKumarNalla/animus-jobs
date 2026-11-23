"""Low-token extras: fellowship matchmaker, people finder, feedback learning, application packs,
LinkedIn studio and mock interviews."""
import json
import re
import time
import urllib.parse
from collections import Counter
from pathlib import Path

from . import ai, db, scoring
from .config import ROOT, get_settings

EUROPE_CC = {"FR", "DE", "NL", "BE", "CH", "GB", "IE", "AT", "IT", "ES", "PT", "DK", "SE", "NO", "FI", "PL", "CZ",
             "HU", "GR", "LU", "SI", "HR", "EE", "LT", "LV", "SK", "RO", "IS", "CY", "MT"}
# fellowship programme -> eligible host countries (None = any European host); rule-based, zero tokens
FELLOWSHIP_HOSTS = [  # specific programmes first, generic MSCA/ERC last
    (r"imacs", {"FR", "DE"}), (r"bienven", {"FR"}), (r"humboldt", {"DE"}), (r"dfg|walter benjamin", {"DE"}),
    (r"\bjsps\b|japan", {"JP"}), (r"snsf|swiss national|\beth\b|epfl", {"CH"}),
    (r"royal society|wellcome|ukri|newton", {"GB"}), (r"\bnwo\b|veni", {"NL"}), (r"\bfwo\b", {"BE"}),
    (r"vinnova|vetenskapsr", {"SE"}), (r"embo", EUROPE_CC | {"IL"}), (r"marie|msca|cofund|\berc\b", EUROPE_CC),
]


def _hosts_for(title):
    t = title.lower()
    for pat, ccs in FELLOWSHIP_HOSTS:
        if re.search(pat, t):
            return ccs
    return EUROPE_CC


def _topic_overlap(a, b):
    wa = {w for w in re.findall(r"[a-z][a-z\-]{3,}", a.lower())} - scoring.STOP
    wb = {w for w in re.findall(r"[a-z][a-z\-]{3,}", b.lower())} - scoring.STOP
    return len(wa & wb)


def matchmaker(limit_fellowships=15, hosts_per=5):
    """Pair open fellowships with European PIs who could host you (no AI calls)."""
    fells = db.rows("SELECT id,title,company,deadline,score,url,description FROM jobs WHERE kind='fellowship' "
                    "AND status!='archived' AND (deadline='' OR deadline>=date('now')) ORDER BY score DESC LIMIT ?",
                    (limit_fellowships,))
    pis = db.rows("SELECT id,title,company,country,score,description,extra FROM jobs WHERE kind='collaborator' "
                  "AND status!='archived' ORDER BY score DESC LIMIT 200")
    out = []
    for f in fells:
        hosts = _hosts_for(f["title"] + " " + f["company"])
        cands = []
        for p in pis:
            if p["country"] not in hosts:
                continue
            fit = p["score"] + 3 * _topic_overlap(f["description"][:1500], p["description"][:1500])
            cands.append({"id": p["id"], "name": p["title"], "inst": p["company"], "country": p["country"],
                          "fit": round(min(fit, 99))})
        cands.sort(key=lambda x: -x["fit"])
        out.append({"fellowship": {k: f[k] for k in ("id", "title", "company", "deadline", "url", "score")},
                    "host_countries": sorted(hosts)[:12], "hosts": cands[:hosts_per]})
    return out


def fellowships_for_host(pi_id):
    p = db.one("SELECT country FROM jobs WHERE id=?", (pi_id,))
    if not p:
        return []
    return [m["fellowship"] for m in matchmaker(40, 50) if any(h["id"] == pi_id for h in m["hosts"])
            or p["country"] in m["host_countries"]][:8]


# ---- people finder (search links only) -------------------------------------------------------

def universities():
    s = get_settings()
    if s.get("universities"):
        return s["universities"]
    r = db.master_resume()
    if not r:
        return []
    found = re.findall(r"((?:Universit[éey]|Institut Polytechnique|École|Ecole|IIT|College)[^\n,;|()–-]{3,60})", r["text"])
    return list(dict.fromkeys(x.strip() for x in found))[:6]


def people_links(company, role=""):
    q = lambda s: urllib.parse.quote(s)  # noqa: E731
    g = lambda s: "https://www.google.com/search?q=" + q(s)  # noqa: E731
    c = company.split("(")[0].strip()
    links = [
        {"label": "Recruiters / Talent", "url": f"https://www.linkedin.com/search/results/people/?keywords={q(c + ' recruiter OR talent acquisition')}"},
        {"label": "Hiring manager (team lead)", "url": g(f'site:linkedin.com/in "{c}" ("head of" OR "director" OR "lead") {role}')},
        {"label": "R&D / imaging people", "url": f"https://www.linkedin.com/search/results/people/?keywords={q(c + ' imaging OR R&D OR scientist')}"},
        {"label": "Company page", "url": f"https://www.linkedin.com/search/results/companies/?keywords={q(c)}"},
    ]
    for u in universities():
        links.append({"label": f"Alumni · {u[:28]}", "url": g(f'site:linkedin.com/in "{c}" "{u}"')})
    return links


# ---- learning from 👍 / 👎 -------------------------------------------------------------------------

def feedback_weights():
    """Lane and term weights learned from your feedback: liked items boost similar ones, disliked demote."""
    rows = db.rows("SELECT title, categories, extra FROM jobs WHERE extra LIKE '%\"feedback\": \"%'")
    lanes, terms = Counter(), Counter()
    n = 0
    for r in rows:
        fb = json.loads(r["extra"] or "{}").get("feedback")
        if fb not in ("up", "down"):
            continue
        n += 1
        sign = 1 if fb == "up" else -1
        for c in json.loads(r["categories"] or "[]"):
            lanes[c] += sign
        for w in set(re.findall(r"[a-z][a-z\-]{3,}", r["title"].lower())) - scoring.STOP:
            terms[w] += sign
    return {"n": n, "lanes": dict(lanes), "terms": {w: v for w, v in terms.items() if abs(v) >= 2}}


def learned_bonus(job, cats, weights):
    if not weights["n"]:
        return 0, ""
    b = sum(max(-2, min(2, weights["lanes"].get(c, 0))) * 3 for c in cats)
    words = set(re.findall(r"[a-z][a-z\-]{3,}", job["title"].lower()))
    b += sum(max(-2, min(2, v)) * 2 for w, v in weights["terms"].items() if w in words)
    b = max(-15, min(15, b))
    return b, (f"{'+' if b >= 0 else ''}{b} learned from your 👍/👎" if b else "")


# ---- light application pack (text files, one AI call) ---------------------------------------------

def _slug(s):
    return re.sub(r"[^A-Za-z0-9]+", "_", s)[:50].strip("_")


def application_pack(job_id, agent=None):
    from .coach import resume_text, _job_block
    j = db.one("SELECT * FROM jobs WHERE id=?", (job_id,))
    prompt = f"""Create a LIGHT application pack as plain text. Do NOT rewrite my whole CV. Use these exact
section markers on their own lines:
=== CV_EDITS ===
A checklist of manual edits to my existing CV for this application: which bullets to change (quote old → new),
what to move up, keywords to add truthfully, what to cut. Max 12 items.
=== COVER_LETTER ===
A 200–250 word cover letter.
=== EMAIL ===
Subject line + a 120-word email to the hiring contact.
=== LINKEDIN_NOTE ===
A connection note under 300 characters.
=== CHECKLIST ===
5 short pre-submit checks specific to this application.

{_job_block(j)}

MY RESUME:
{resume_text()[:9000]}"""
    text, used = ai.ask(prompt, agent=agent, task="writing")
    parts = dict(re.findall(r"=== (\w+) ===\s*(.*?)(?=\n=== \w+ ===|\Z)", text, re.S))
    folder = ROOT / "applications" / f"{time.strftime('%Y%m%d')}_{_slug(j['company'])}_{_slug(j['title'])}"
    folder.mkdir(parents=True, exist_ok=True)
    files = {"00_job.txt": f"{j['title']}\n{j['company']} · {j['location']}\n{j['url']}\nDeadline: {j['deadline'] or '-'}\n\n{j['description']}",
             "01_cv_edits.md": parts.get("CV_EDITS", text), "02_cover_letter.txt": parts.get("COVER_LETTER", ""),
             "03_email.txt": parts.get("EMAIL", ""), "04_linkedin_note.txt": parts.get("LINKEDIN_NOTE", ""),
             "05_checklist.md": parts.get("CHECKLIST", "")}
    for name, content in files.items():
        (folder / name).write_text(content.strip() + "\n")
    db.save_doc("pack", f"Application pack – {j['title']} @ {j['company']}", text, job_id, used)
    return {"folder": str(folder), "files": list(files), "agent": used, "text": text}


# ---- LinkedIn studio -------------------------------------------------------------------------------

POST_TYPES = {
    "research_highlight": "a highlight post about one concrete result from my recent work or research, accessible to industry readers",
    "open_to_work": "a tasteful 'open to new opportunities' post naming the roles/lanes I'm targeting and what I bring",
    "news_take": "a thoughtful take on this recent industry news, linking it to my expertise",
    "event": "a post sharing 3 takeaways from a conference/hackathon I attended",
    "lesson": "a 'lessons learned' post from moving between research, start-up and hospital settings",
}


def linkedin_post(kind, context="", language="English", agent=None):
    from .coach import resume_text
    prompt = f"""Write {POST_TYPES.get(kind, kind)} for LinkedIn, in {language}.
Hook in the first line, short paragraphs, one concrete number/result from my real experience, end with a question.
120–220 words, max 3 relevant hashtags, no emojis overload. Then give 2 alternative hooks.
{('Context: ' + context) if context else ''}
MY RESUME (facts only): {resume_text()[:5000]}"""
    text, used = ai.ask(prompt, agent=agent, task="writing")
    db.save_doc("linkedin", f"LinkedIn post – {kind}", text, None, used)
    return text, used


def connection_notes(ids, agent=None):
    """One AI call → personalised <300-char notes for many people/companies."""
    rows = db.rows(f"SELECT id,title,company,kind,description FROM jobs WHERE id IN ({','.join('?' * len(ids))})", ids)
    people = "\n".join(f"[{i}] {r['kind']}: {r['title']} — {r['company']} :: {r['description'][:300]}"
                       for i, r in enumerate(rows))
    prompt = f"""Write one LinkedIn connection note (under 300 characters each) per entry below.
Personal, specific (mention their work/company), no flattery, no ask for a job in the first line.
Format exactly: [index] note
{people}
MY PROFILE: {(db.master_resume() or {}).get('profile', '')[:800]}"""
    text, used = ai.ask(prompt, agent=agent, task="writing")
    notes = dict(re.findall(r"\[(\d+)\]\s*(.+)", text))
    return [{"id": r["id"], "name": r["title"], "company": r["company"], "note": notes.get(str(i), "").strip()[:300]}
            for i, r in enumerate(rows)], used


def linkedin_profile(agent=None):
    from .coach import resume_text
    s = get_settings()
    prompt = f"""Optimise my LinkedIn profile for recruiters and PIs in my target lanes
({', '.join(s.get('target_roles', []))}; also postdoc, product, analyst, founding/CTO).
Give: 3 headline options (<220 chars), an About section (≤1,800 chars), the top 10 skills to list in order,
and 5 Featured-section ideas. Use only facts from my resume.
MY RESUME: {resume_text()[:8000]}"""
    text, used = ai.ask(prompt, agent=agent, task="writing")
    db.save_doc("linkedin", "LinkedIn profile optimisation", text, None, used)
    return text, used


# ---- mock interviews --------------------------------------------------------------------------------

INTERVIEWER = ("You are a realistic interviewer for the role below. Ask ONE question at a time. After each candidate "
               "answer: give a score 1-10, 2 lines of feedback (what was strong, what to improve, STAR structure), "
               "and a stronger model answer outline in 3 bullets, then ask the next question. Use this exact layout:\n"
               "SCORE: n/10\nFEEDBACK: ...\nBETTER: ...\nNEXT QUESTION: ...\n"
               "When told to finish, output a FINAL SCORECARD with an overall score, 3 strengths, 3 priorities, "
               "and the 3 questions to rehearse again.")


def mock_start(job_id, style="mixed", questions=6, language="English", agent=None):
    from .coach import resume_text, _job_block
    j = db.one("SELECT * FROM jobs WHERE id=?", (job_id,)) if job_id else None
    ctx = _job_block(j) if j else "General interview for my target roles."
    prompt = (f"{INTERVIEWER}\n\nInterview style: {style} (behavioral/technical/case/mixed). Language: {language}. "
              f"Planned length: {questions} questions.\n{ctx}\nCANDIDATE RESUME: {resume_text()[:5000]}\n\n"
              "Start: greet in one line, then output 'NEXT QUESTION: <first question>'.")
    text, used = ai.ask(prompt, agent=agent, task="training")
    sid = db.execute("INSERT INTO mock (job_id, style, questions, transcript, created, agent) VALUES (?,?,?,?,?,?)",
                     (job_id, style, questions, json.dumps([{"role": "setup", "content": prompt},
                                                             {"role": "interviewer", "content": text}]),
                      time.time(), used))
    return {"id": sid, "text": text, "agent": used}


def mock_answer(sid, answer, finish=False, agent=None):
    m = db.one("SELECT * FROM mock WHERE id=?", (sid,))
    tr = json.loads(m["transcript"])
    tr.append({"role": "candidate", "content": answer})
    asked = sum(1 for t in tr if t["role"] == "candidate")
    finish = finish or asked >= m["questions"]
    convo = "\n\n".join(f"{t['role'].upper()}: {t['content']}" for t in tr)
    prompt = convo + ("\n\nINTERVIEWER: (score the last answer, then output the FINAL SCORECARD)" if finish else
                      "\n\nINTERVIEWER: (score the last answer, then ask the next question)")
    text, used = ai.ask(prompt, agent=agent or m["agent"], task="training")
    tr.append({"role": "interviewer", "content": text})
    db.execute("UPDATE mock SET transcript=? WHERE id=?", (json.dumps(tr), sid))
    if finish:
        db.save_doc("mock", f"Mock interview #{sid} scorecard", text, m["job_id"], used)
    sc = re.findall(r"SCORE:\s*(\d+)", "\n".join(t["content"] for t in tr if t["role"] == "interviewer"))
    return {"text": text, "agent": used, "done": finish, "asked": asked, "scores": [int(x) for x in sc]}
