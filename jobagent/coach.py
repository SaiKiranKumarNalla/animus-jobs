"""Resume parsing and every AI coaching feature (prompts live here)."""
import io
import json
import re
import time
from collections import Counter

from . import ai, db, scoring
from .config import get_settings


# ---- resume parsing ------------------------------------------------------------

def fix_text(text: str) -> str:
    """Repair PDF font-encoding damage: ligatures (ﬁ ﬂ) and 'ti' glyphs extracted as $ or (."""
    import unicodedata
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"(?<=[A-Za-z])[$(](?=[a-z])", "ti", text)      # Ins$tute, Execu(ng
    text = re.sub(r"(?<=[a-z])\((?=\s|$)", "ti", text, flags=re.M)  # mul( stakeholder
    text = re.sub(r"(?<=\w) -(?=[a-z])", "-", text)                 # Python -based
    return text


def parse_file(filename: str, data: bytes) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader
        return fix_text("\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages).strip())
    if name.endswith(".docx"):
        import docx
        d = docx.Document(io.BytesIO(data))
        parts = [p.text for p in d.paragraphs]
        for t in d.tables:
            for row in t.rows:
                parts.append(" | ".join(c.text for c in row.cells))
        return "\n".join(parts).strip()
    return data.decode("utf-8", errors="ignore").strip()


def _json(text):
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else {}


def build_profile(resume_text: str) -> dict:
    """AI profile extraction with a local fallback."""
    local = {"skills": scoring.extract_skills(resume_text)}
    try:
        out, agent = ai.ask(
            "Read this resume and return ONLY a JSON object with keys: name, headline, "
            "seniority (junior|mid|senior|lead), years_experience (number), "
            "target_roles (5 realistic job titles to search for, most fitting first), "
            "keywords (15 core hard skills), locations (likely job markets, include 'Remote'), "
            "languages (spoken), strengths (3 short), gaps (3 short), summary (2 sentences).\n\n"
            f"RESUME:\n{resume_text[:15000]}", task="profile")
        prof = _json(out)
        prof["skills"] = local["skills"]
        prof["_agent"] = agent
        return prof
    except Exception as e:  # noqa: BLE001
        local["_error"] = str(e)
        local["keywords"] = local["skills"][:20]
        return local


def _kb(query):
    """Relevant notes from the user's optional knowledge base (Obsidian vault); empty if none linked."""
    try:
        from . import kb
        return kb.context(query)
    except Exception:  # noqa: BLE001
        return ""


def profile_brief():
    """Short candidate summary built from THIS user's AI profile + settings (never hardcoded)."""
    from . import packs
    r = db.master_resume() or {}
    prof = json.loads(r.get("profile") or "{}")
    st, pk = get_settings(), packs.active()
    country = st.get("home_country") or pk.get("home_country") or ""
    lines = [f"- Headline: {prof.get('headline', '')}",
             f"- Seniority: {prof.get('seniority', '')}; key skills: {', '.join((prof.get('keywords') or prof.get('skills') or [])[:12])}",
             f"- Field: {pk.get('field', '')}",
             f"- Target roles: {', '.join(st.get('target_roles', [])[:6])}",
             f"- Locations: {', '.join(st.get('locations', [])[:6]) or country}"]
    return "\n".join(l for l in lines if not l.rstrip().endswith(":"))


def home_country():
    from . import packs
    return get_settings().get("home_country") or packs.active().get("home_country") or "the candidate's country"


def resume_text():
    r = db.master_resume()
    if not r:
        raise RuntimeError("Upload your resume first (Resume tab).")
    return r["text"]


def _job(job_id):
    j = db.one("SELECT * FROM jobs WHERE id=?", (job_id,)) if job_id else None
    return j


def _job_block(job=None, jd=""):
    if job:
        return (f"JOB: {job['title']} at {job['company']} ({job['location']})\nURL: {job['url']}\n"
                f"DESCRIPTION:\n{job['description'][:9000]}")
    return f"JOB DESCRIPTION:\n{jd[:9000]}" if jd else "(no specific job – general improvement)"


# ---- features ----------------------------------------------------------------------

def improve_resume(job_id=None, jd="", focus="", agent=None):
    job = _job(job_id)
    prompt = f"""Improve my resume{' for this job' if (job or jd) else ''}.
Deliver, in Markdown:
1. **Verdict** – 3 bullet summary of how a recruiter would see it today.
2. **Top 10 fixes**, ranked by impact (each: what, why, and the rewritten text).
3. **Rewritten summary** (3–4 lines) and **rewritten bullets** for the most relevant roles
   using action verb + what + measurable result. Mark any number I must verify with [verify].
4. **Keywords to add truthfully** for ATS.
5. A complete, ATS-safe **tailored resume** in plain text (single column, standard headings).
{('Extra focus: ' + focus) if focus else ''}

{_job_block(job, jd)}

MY RESUME:
{resume_text()[:15000]}"""
    text, agent = ai.ask(prompt, agent=agent, task="writing")
    db.save_doc("resume", f"Resume rewrite – {job['title'] + ' @ ' + job['company'] if job else 'general'}",
                text, job_id, agent)
    return text, agent


def tailor_resume(job_id=None, jd="", focus="", output_format="markdown", agent=None):
    """Text-based resume modifier: generates an ATS-optimized, tailored resume in Markdown/Plain Text
    strictly using real facts from the candidate's master resume.
    """
    job = _job(job_id)
    prompt = f"""Act as an expert technical resume writer and hiring manager.
Create a complete, polished, ATS-optimized TAILORED RESUME in {output_format.upper()} format.

STRICT INSTRUCTIONS:
- You must ONLY use real facts, roles, degrees, companies, and dates from the candidate's resume below. NEVER invent facts or hallucinate degrees or past employers.
- Tailor the Professional Summary to directly reflect the target role's mission and technical needs.
- In Technical Skills / Core Competencies, surface and prioritize the skills mentioned in the job description that match the candidate's truthful experience (only skills that genuinely appear in the resume).
- For Professional / Research Experience: rewrite each role's bullet points using high-impact action verbs (STAR format) highlighting achievements, technologies used, and metrics that align directly with this opportunity.
- Add an 'ATS Alignment' section at the bottom listing the exact key terms from the job description addressed in this tailored version.
{('Focus on: ' + focus) if focus else ''}

{_job_block(job, jd)}

MY MASTER RESUME:
{resume_text()[:15000]}"""
    text, used = ai.ask(prompt, agent=agent, task="writing")
    title = f"Tailored Resume – {job['title'] + ' @ ' + job['company'] if job else 'Custom Role'}"
    doc_id = db.save_doc("tailored_resume", title, text, job_id, used)

    if job:
        try:
            from .config import ROOT
            from .extras import _slug
            folder = ROOT / "applications" / f"{time.strftime('%Y%m%d')}_{_slug(job['company'])}_{_slug(job['title'])}"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "01_tailored_resume.md").write_text(text.strip() + "\n")
        except Exception:
            pass

    return text, used


def ats_review(jd="", job_id=None, agent=None):
    job = _job(job_id)
    jd_text = job["description"] if job else jd
    rule = scoring.ats_check(resume_text(), jd_text)
    prompt = f"""Act as an ATS (Workday/Greenhouse/Taleo-style) plus a senior recruiter.
A rule-based scan produced: {json.dumps(rule)[:3000]}
Give: estimated ATS match %, parsing risks, hard-skill keywords missing (exact phrasing the ATS
expects), title alignment, and a prioritized edit list to reach 80%+ honestly.

{_job_block(job, jd)}

RESUME:
{resume_text()[:15000]}"""
    try:
        text, agent = ai.ask(prompt, agent=agent, task="writing")
    except Exception as e:  # noqa: BLE001
        text, agent = f"_AI review unavailable: {e}_", None
    return {"rules": rule, "ai": text, "agent": agent}


def cover_letter(job_id=None, jd="", tone="confident, warm, concise", language="English",
                 extra="", agent=None):
    job = _job(job_id)
    prompt = f"""Write a cover letter in {language}. Tone: {tone}. Max 300 words, 3–4 paragraphs.
Hook with something specific about the company/role, map my 2–3 most relevant achievements to
their needs (with numbers from my resume), close with a clear call to action. No clichés
("I am writing to apply…"). After the letter, add 3 bullet tips to personalize it further.
{('Extra context: ' + extra) if extra else ''}

{_job_block(job, jd)}

MY RESUME:
{resume_text()[:12000]}{_kb((job or {}).get("title", "") + " " + (job or {}).get("company", "") + " " + jd[:300])}"""
    text, agent = ai.ask(prompt, agent=agent, task="writing")
    db.save_doc("cover_letter", f"Cover letter – {job['title'] + ' @ ' + job['company'] if job else 'custom'}",
                text, job_id, agent)
    return text, agent


EMAIL_KINDS = {
    "recruiter_outreach": "a cold outreach email/LinkedIn note to a recruiter or hiring manager about this role",
    "referral_request": "a message asking a contact at the company for a referral",
    "follow_up": "a polite follow-up after applying with no response (7–10 days later)",
    "thank_you": "a thank-you email after an interview",
    "networking": "a networking/informational-interview request",
    "negotiation": "a salary/offer negotiation email",
    "withdraw": "a gracious withdrawal from a process",
    "postdoc_inquiry": ("a concise postdoc inquiry to this principal investigator: reference 1–2 of THEIR recent papers "
                        "listed below by title, connect them to my most relevant concrete work from my resume, propose 1–2 joint research ideas, ask about open positions OR co-applying for "
                        "an MSCA Postdoctoral Fellowship / similar with them as host, and offer a short call. Attach-ready: "
                        "also write a 150-word research statement paragraph tailored to their group"),
    "spontaneous": ("a spontaneous (unsolicited) application email to this company: show I understand their product/news, "
                    "pitch the specific role/value I could bring, cite one quantified result, ask for a 20-minute call "
                    "and say a CV is attached"),
}


def draft_email(kind, job_id=None, recipient="", context="", language="English", agent=None):
    job = _job(job_id)
    what = EMAIL_KINDS.get(kind, kind)
    prompt = f"""Draft {what}, in {language}.
Recipient: {recipient or 'unknown – use a placeholder'}
Give: 2 subject line options, the email (under 150 words, specific, human, one clear ask),
and a 300-character LinkedIn connection-note version.
{('Context: ' + context) if context else ''}

{_job_block(job)}

MY RESUME (for facts only):
{resume_text()[:8000]}"""
    text, agent = ai.ask(prompt, agent=agent, task="writing")
    db.save_doc("email", f"Email ({kind}) – {job['company'] if job else recipient or 'general'}",
                text, job_id, agent)
    return text, agent


def skill_gaps(limit=40):
    """Aggregate missing skills across your best-matching jobs (local, instant)."""
    jobs = db.rows("SELECT missing, matched FROM jobs WHERE score>0 ORDER BY score DESC LIMIT ?", (limit,))
    miss, have = Counter(), Counter()
    for j in jobs:
        miss.update(json.loads(j["missing"] or "[]"))
        have.update(json.loads(j["matched"] or "[]"))
    return {"missing": miss.most_common(20), "strong": have.most_common(15), "jobs_analyzed": len(jobs)}


def dev_plan(weeks=8, hours_per_week=8, goal="", agent=None, use_council=False):
    gaps = skill_gaps()
    s = get_settings()
    prompt = f"""Build my personal career development plan for the next {weeks} weeks at
{hours_per_week} h/week. Goal: {goal or 'land one of my target roles: ' + ', '.join(s.get('target_roles', []))}.

Market demand from my best-matching job posts (skill, #posts): missing={gaps['missing']}, strong={gaps['strong']}

Deliver in Markdown:
1. **Skill priority matrix** (skill | why it matters | current→target level | effort).
2. **Week-by-week plan** with concrete tasks, free/cheap resources (official docs, courses, datasets)
   and a portfolio deliverable every 2 weeks (something I can put on GitHub/LinkedIn).
3. **Proof-of-skill projects** (3) tailored to my background that recruiters in my field value.
4. **Certifications** worth it vs. not.
5. **Networking & visibility** weekly habits.
6. **Milestones/KPIs** to track.

MY RESUME:
{resume_text()[:10000]}"""
    if use_council:
        r = ai.council(prompt)
        text, agent = r["synthesis"], f"council→{r['lead']}"
    else:
        text, agent = ai.ask(prompt, agent=agent, task="training")
    db.save_doc("dev_plan", f"Development plan ({weeks} weeks)", text, None, agent)
    return text, agent


def train(skill, mode="quiz", level="intermediate", agent=None):
    modes = {
        "quiz": "a 6-question quiz (mix of multiple-choice and short answer). Put the answer key at the very end under '### Answers'",
        "lesson": "a focused 20-minute lesson: key concepts, a worked example, common pitfalls, and 3 practice exercises",
        "project": "a portfolio mini-project spec (goal, dataset/source, steps, stretch goals, how to present it)",
        "interview": "5 realistic interview questions on this skill with model answers and what interviewers look for",
    }
    prompt = f"Skill training on **{skill}** at {level} level. Create {modes.get(mode, mode)}. " \
             f"Tie examples to my background where useful.\n\nMY RESUME (context):\n{resume_text()[:5000]}"
    text, agent = ai.ask(prompt, agent=agent, task="training")
    db.save_doc("training", f"{mode.title()}: {skill}", text, None, agent)
    return text, agent


def grade(skill, question_set, answers, agent=None):
    prompt = f"Grade my answers for this {skill} exercise. Score each, explain mistakes, and tell me " \
             f"what to study next.\n\nEXERCISE:\n{question_set[:8000]}\n\nMY ANSWERS:\n{answers[:6000]}"
    return ai.ask(prompt, agent=agent, task="training")


def interview_prep(job_id, agent=None):
    job = _job(job_id)
    prompt = f"""Prepare me for interviews for this job. Include: what the company likely cares about,
10 likely questions (behavioral + technical) with STAR answer outlines using MY real experience,
5 smart questions to ask them, and red flags to probe.

{_job_block(job)}

MY RESUME:
{resume_text()[:10000]}"""
    text, agent = ai.ask(prompt, agent=agent, task="writing")
    db.save_doc("interview", f"Interview prep – {job['title']} @ {job['company']}", text, job_id, agent)
    return text, agent


def review_job(job, agent=None):
    """Deep fit review by an agent. Returns dict."""
    s = get_settings()
    r = db.master_resume() or {}
    prof = r.get("profile", "")
    prompt = f"""Evaluate fit between me and this opportunity using my WHOLE profile (resume, AI profile,
preferences, nationality for work-permit questions). Return ONLY JSON:
{{"fit": 0-100, "verdict": "apply|maybe|skip", "why": "2 sentences",
  "angle": "the one story to lead with", "red_flags": ["..."], "missing": ["..."],
  "salary_estimate": "typical gross annual range in local currency for this role/location, or '' if not a job",
  "visa_note": "one line on work-permit needs for me in that country, or ''"}}

{_job_block(job)}

MY PREFERENCES: {s.get('preferences') or '(none stated)'}
MY NATIONALITY: {s.get('nationality') or '(not stated)'}
MY AI PROFILE: {prof[:1500]}
MY RESUME:
{resume_text()[:8000]}"""
    out, agent = ai.ask(prompt, agent=agent, task="review")
    d = _json(out)
    d["agent"] = agent
    return d


def chat(message, agent=None, use_council=False):
    hist = db.rows("SELECT role, content FROM chat ORDER BY id DESC LIMIT 12")[::-1]
    convo = "\n".join(f"{h['role'].upper()}: {h['content'][:2000]}" for h in hist)
    s = get_settings()
    try:
        rt = resume_text()[:6000]
    except RuntimeError:
        rt = "(no resume uploaded yet)"
    pipeline = db.rows("SELECT title, company, status, score FROM jobs WHERE status!='new' "
                       "ORDER BY found_at DESC LIMIT 15")
    prompt = f"""Context – my targets: {s.get('target_roles')}, locations: {s.get('locations')}.
My application pipeline: {pipeline}
MY RESUME: {rt}

Conversation so far:
{convo}

USER: {message}{_kb(message)}"""
    db.execute("INSERT INTO chat (role,content,agent,created) VALUES ('user',?, '', strftime('%s','now'))", (message,))
    if use_council:
        r = ai.council(prompt)
        text, agent = r["synthesis"], f"council→{r['lead']}"
    else:
        text, agent = ai.ask(prompt, agent=agent, task="chat")
    db.execute("INSERT INTO chat (role,content,agent,created) VALUES ('assistant',?,?, strftime('%s','now'))",
               (text, agent))
    return text, agent


def country_brief(country, agent=None):
    """Visa routes, salary ranges, cost of living and relocation tips for one country (cached as a document)."""
    s = get_settings()
    cached = db.one("SELECT * FROM documents WHERE kind='country_brief' AND title=? AND created > strftime('%s','now') - 30*86400 "
                    "ORDER BY id DESC LIMIT 1", (f"Country brief – {country}",))
    if cached:
        return cached["content"], cached["agent"] + " (cached)"
    from . import packs
    field = packs.active().get("field", "my field")
    prompt = f"""Write a practical relocation brief for working in **{country}** for me.
My nationality: {s.get('nationality') or 'not stated – cover both EU and non-EU citizens'}.
My profile: {(db.master_resume() or {}).get('profile', '')[:1200]}
Target roles: {', '.join(s.get('target_roles', []))}; also postdoc, product, analyst and internship options.

Sections (Markdown, concise, with official links):
1. **Work permits / visas** that fit me (e.g. EU Blue Card, researcher/hosting-agreement visa, talent passports, job-seeker visas, intern permits) – eligibility, salary thresholds, processing time.
2. **Salary ranges** (gross/year, local currency) for: postdoc, research scientist, application/product specialist, MedTech analyst, R&D engineer, CTO/CSO at a startup, internship stipend.
3. **Cost of living & net pay feel** in the main hubs for my field.
4. **Language** expectations in industry vs academia.
5. **Ecosystem**: key employers, labs and companies in my field ({field}).
6. **Relocation checklist** (registration, health insurance, tax notes, recognition of diplomas).
Flag anything that may have changed recently and should be verified."""
    try:
        from .opportunities import web_ask
        text, agent = web_ask(prompt)
    except Exception:  # noqa: BLE001
        text, agent = ai.ask(prompt, agent=agent, task="writing")
    db.save_doc("country_brief", f"Country brief – {country}", text, None, agent)
    return text, agent


def weekly_top5(agent=None):
    """The five highest-value moves for this week across all lanes."""
    import time as _t
    pipeline = db.rows("SELECT title,company,status,deadline,next_action,next_date,score,kind FROM jobs "
                       "WHERE status NOT IN ('new','archived','rejected') ORDER BY deadline")
    soon = db.rows("SELECT title,company,kind,deadline,score,url FROM jobs WHERE deadline!='' AND deadline>=date('now') "
                   "AND deadline<=date('now','+21 day') AND status!='archived' ORDER BY score DESC LIMIT 15")
    best = db.rows("SELECT title,company,kind,score,location,url,categories FROM jobs WHERE status='new' AND kind!='intel' "
                   "AND found_at > ? ORDER BY score DESC LIMIT 20", (_t.time() - 8 * 86400,))
    intel = db.rows("SELECT title,company,description FROM jobs WHERE kind='intel' ORDER BY found_at DESC LIMIT 8")
    prompt = f"""You are my career strategist. Pick the **5 highest-value moves for this week** across jobs,
postdoc collaborators, fellowships, funding, hackathons, spontaneous applications and networking.
For each: what to do, why now (deadline/leverage), estimated time, and the exact first step (link). Then add
"⚠ Don't miss" (deadlines ≤ 10 days) and "🧭 One strategic reflection" (2 sentences).

MY PIPELINE: {json.dumps(pipeline)[:3500]}
DEADLINES ≤ 21 DAYS: {json.dumps(soon)[:3000]}
BEST NEW THIS WEEK: {json.dumps(best)[:4500]}
COMPANY INTEL: {json.dumps(intel)[:2500]}
MY PREFERENCES: {get_settings().get('preferences') or '(none)'}
MY PROFILE: {(db.master_resume() or {}).get('profile', '')[:1200]}"""
    text, agent = ai.ask(prompt, agent=agent, task="writing")
    db.save_doc("top5", "Weekly top-5 moves – " + _t.strftime("%d %b %Y"), text, None, agent)
    return text, agent


def interview_cheatsheet(job_id, agent=None):
    """Generates an executive-level interview cheat-sheet & company dossier."""
    job = _job(job_id)
    prompt = f"""You are an elite executive interview coach and technical hiring advisor.
Build a comprehensive, strategic INTERVIEW CHEAT-SHEET & COMPANY DOSSIER for this specific role.

Candidate Profile:
{profile_brief()}

Target Opportunity:
{_job_block(job)}

MY REAL RESUME (Use real projects only; never fabricate facts):
{resume_text()[:12000]}

Format as a high-density, actionable Markdown briefing with these exact sections:

## 1. ⚡ The 30-Second Elevator Pitch
A punchy 3-sentence introduction tailored to this specific team. Hooks with my PhD specialization, connects directly to what this company builds, and states the immediate value I bring on Day 1.

## 2. 🎯 Top 3 STAR Stories (Selected from my Real Experience)
Select the 3 most relevant projects from my resume that prove I can solve their exact challenges:
- **Story 1 (Technical & Computational Challenge)**: Situation, Task, Action (specific algorithms/tools like PyTomography/simulations), and Result (quantified metrics).
- **Story 2 (Clinical / Experimental Validation & Cross-Functional Work)**: Situation, Task, Action (work with PIs/clinicians/hospitals), and Result.
- **Story 3 (Problem-Solving / Discrepancy Resolution)**: When results didn't match expectations or unexpected constraints occurred, and how I diagnosed and solved it.

## 3. 🧠 Top 5 Anticipated Technical & Domain Questions
Provide the 5 toughest technical questions their lead scientist/manager will likely ask, paired with concise model answer bullet points citing my real background.

## 4. 🤝 Top 3 Behavioral & Leadership Questions
Include handling disagreements between clinical staff vs engineering, tight deadlines, and research ambiguity.

## 5. 💡 5 Killer Questions to Ask Them
Strategic questions that demonstrate deep technical maturity and commercial awareness, making them view me as a peer rather than just an applicant.

## 6. 🚩 Red Flags & Critical Clarifications
4 specific things to investigate before accepting an offer (compute infrastructure, clinical dataset access, publication rights, RTT/remote policy, team turnover).
"""
    text, used = ai.ask(prompt, agent=agent, task="writing")
    title = f"Interview Cheat-Sheet – {job['title']} @ {job['company']}"
    db.save_doc("cheatsheet", title, text, job_id, used)
    return text, used


def salary_advisor(job_id=None, offer_details="", agent=None):
    """Provides market compensation benchmarking and counter-offer negotiation scripts for French and European roles."""
    job = _job(job_id) if job_id else None
    prompt = f"""You are a compensation & negotiation expert for this candidate's field and countries.
Analyze and provide a detailed compensation benchmark and negotiation strategy.

Candidate profile:
{profile_brief()}
Home country: {home_country()}

Target Role & Company:
{_job_block(job) if job else 'General market benchmark for my target roles'}

{f'Current Offer / Numbers discussed: {offer_details}' if offer_details else 'No offer yet; calculate target asking ranges for applications and initial recruiter calls.'}

Provide a structured Markdown report:

## 1. 💶 Market Compensation Benchmark Range
- Base salary for this role: 25th percentile, median, 75th percentile (local currency, gross per year), with the source type.
- Geographic adjustments across my target locations.
- Senior / lead / startup-leadership brackets where relevant.

## 2. 📦 Package Anatomy in the Role's Country
Explain the typical package elements and employment norms of the country where the role is based
(contract types, paid leave, profit sharing, health insurance, meal/remote allowances, notice periods) and estimate net take-home.

## 3. 🎯 Negotiation Strategy & Leverage
How to use my strongest, resume-backed differentiators to justify top-bracket compensation.

## 4. ✉ Ready-to-Send Counter-Offer Scripts
- **Script A (English)**: confident, collaborative email asking for +10–12% base or a sign-on bonus.
- **Script B (the role's local language, if not English)**: culturally attuned version of the same email.
"""
    text, used = ai.ask(prompt, agent=agent, task="writing")
    title = f"Salary & Negotiation Dossier – {job['company'] if job else 'Market Guide'}"
    db.save_doc("salary_advisor", title, text, job_id, used)
    return text, used
