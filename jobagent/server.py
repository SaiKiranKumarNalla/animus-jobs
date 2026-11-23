"""FastAPI dashboard backend + built-in interval scheduler."""
import hashlib
from pathlib import Path
import json
import threading
import time
from datetime import datetime

from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from datetime import date, timedelta

from fastapi.responses import Response

from . import agent, ai, categories, coach, db, emailer, extras, geo, opportunities, scoring, sources, tracker, verifier
from .config import ROOT, get_settings, save_settings

from fastapi.staticfiles import StaticFiles

app = FastAPI(title="JobAgent")
STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def no_cache_ui(request, call_next):
    """Always serve the latest UI after an update (local app, so caching buys nothing)."""
    resp = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp
db.init()


def ok(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e)) from e


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/classic")
def classic():
    return FileResponse(STATIC / "classic.html")


@app.get("/api/state")
def state():
    r = db.master_resume()
    excl, eargs = db.country_filter()
    counts = {x["status"]: x["n"] for x in db.rows("SELECT status, COUNT(*) n FROM jobs WHERE 1=1" + excl +
                                                   " GROUP BY status", eargs)}
    return {
        "settings": get_settings(),
        "agents": ai.status(),
        "email": emailer.configured(),
        "resume": {"name": r["name"], "chars": len(r["text"]), "profile": json.loads(r["profile"] or "{}"),
                   "created": r["created"]} if r else None,
        "counts": counts,
        "total": sum(counts.values()),
        "top": db.one("SELECT COUNT(*) n FROM jobs WHERE score>=?" + excl, (get_settings()["min_score"], *eargs))["n"],
        "runs": db.rows("SELECT * FROM runs ORDER BY id DESC LIMIT 8"),
        "scan": {"running": agent.STATE["running"],
                 "last": agent.STATE["last"] or (db.one("SELECT summary FROM runs WHERE kind='scan' ORDER BY id DESC LIMIT 1") or {}).get("summary")},
        "next_scan": SCHED.get("next"),
    }


@app.post("/api/settings")
def settings(body: dict = Body(...)):
    s = save_settings(body)
    threading.Thread(target=agent.rescore_all, daemon=True).start()
    return s


def _store_resume(name, text):
    if len(text) < 200:
        raise HTTPException(400, "Could not read enough text from this resume.")
    prof = coach.build_profile(text)
    db.execute("UPDATE resumes SET is_master=0")
    db.execute("INSERT INTO resumes (name,text,profile,created,is_master) VALUES (?,?,?,?,1)",
               (name, text, json.dumps(prof), time.time()))
    s = get_settings()
    upd = {}
    for k in ("target_roles", "keywords", "locations"):
        if not s.get(k) and prof.get(k):
            upd[k] = prof[k]
    if not s.get("name") and prof.get("name"):
        upd["name"] = prof["name"]
    if upd:
        save_settings(upd)
    agent.rescore_all()
    return {"profile": prof, "settings_updated": list(upd)}


@app.post("/api/resume")
async def upload_resume(file: UploadFile = File(...)):
    data = await file.read()
    text = ok(coach.parse_file, file.filename, data)
    from .config import DATA
    cvdir = DATA / "cv"
    cvdir.mkdir(exist_ok=True)
    keep = cvdir / Path(file.filename).name  # original file, attached by the email apply mode
    keep.write_bytes(data)
    save_settings({"cv_file": str(keep)})
    return ok(_store_resume, file.filename, text)


@app.post("/api/resume/text")
def resume_text(body: dict = Body(...)):
    return ok(_store_resume, body.get("name", "pasted"), body.get("text", ""))


@app.post("/api/resume/reprofile")
def reprofile(body: dict = Body(default={})):
    """Re-run the AI profile on the current resume; optionally overwrite targeting settings."""
    r = db.master_resume()
    if not r:
        raise HTTPException(400, "Upload a resume first.")
    prof = coach.build_profile(r["text"])
    if prof.get("_error"):
        raise HTTPException(400, prof["_error"])
    db.execute("UPDATE resumes SET profile=? WHERE id=?", (json.dumps(prof), r["id"]))
    upd = {k: prof[k] for k in ("target_roles", "keywords", "locations") if prof.get(k)}
    if prof.get("name"):
        upd["name"] = prof["name"]
    save_settings(upd)
    agent.rescore_all()
    return {"profile": prof, "settings_updated": list(upd)}


@app.get("/api/resume")
def get_resume():
    r = db.master_resume()
    return r or {}


@app.get("/api/jobs")
def jobs(q: str = "", status: str = "", min_score: float = 0, limit: int = 200, category: str = "",
         kind: str = "", section: str = "", sort: str = "score"):
    excl, eargs = db.country_filter()
    sql, args = "SELECT * FROM jobs WHERE score>=?" + excl, [min_score, *eargs]
    if section in db.SECTIONS:
        sql += f" AND {db.SECTIONS[section]}"
    if category:
        sql += " AND categories LIKE ?"
        args.append(f'%"{category}"%')
    if kind:
        sql += " AND kind=?"
        args.append(kind)
    if status:
        sql += " AND status=?"
        args.append(status)
    else:
        sql += " AND status NOT IN ('archived','rejected')"  # archived only when explicitly asked for
    if q:
        sql += " AND (title LIKE ? OR company LIKE ? OR description LIKE ? OR location LIKE ?)"
        args += [f"%{q}%"] * 4
    sql += (" ORDER BY CASE WHEN deadline='' THEN 1 ELSE 0 END, deadline, score DESC LIMIT ?" if sort == "deadline"
            else " ORDER BY found_at DESC LIMIT ?" if sort == "new" else " ORDER BY score DESC, found_at DESC LIMIT ?")
    args.append(limit)
    out = db.rows(sql, args)
    for j in out:
        j["description"] = j["description"][:300]   # list rows only need a snippet; details load on open
        x = json.loads(j.get("extra") or "{}")
        lc = x.get("link_check") or {}
        vf = x.get("verified") or {}
        j["extra"] = json.dumps({k: v for k, v in {"gem": x.get("gem"), "star": x.get("star"), "found_by": x.get("found_by"),
                                 "fit": x.get("fit"), "rarity": x.get("rarity"),
                                 "verified": {"status": vf.get("status"), "by": vf.get("by"), "on": vf.get("on")} if vf else None,
                                 "link_check": {"valid": lc.get("valid"), "status": lc.get("status"), "reason": lc.get("reason")} if lc else None}.items() if v})
        v = json.loads(j.get("ai_verdict") or "null")
        j["ai_verdict"] = json.dumps({"verdict": v.get("verdict"), "fit": v.get("fit"), "why": (v.get("why") or "")[:200]}) if v else None
        for k in ("matched", "missing", "tags", "notes", "reminded"):
            j.pop(k, None)
    return out


@app.get("/api/job")
def job(id: str):
    j = db.one("SELECT * FROM jobs WHERE id=?", (id,))
    if not j:
        raise HTTPException(404, "not found")
    j["docs"] = db.rows("SELECT id,kind,title,agent,created FROM documents WHERE job_id=? ORDER BY id DESC", (id,))
    return j


@app.post("/api/job/update")
def job_update(body: dict = Body(...)):
    fields = {k: body[k] for k in ("status", "notes", "deadline", "next_action", "next_date") if k in body}
    if body.get("status") in ("applied", "interview", "offer"):
        cur = db.one("SELECT applied_at FROM jobs WHERE id=?", (body["id"],))
        if cur and not cur["applied_at"]:
            fields["applied_at"] = date.today().isoformat()
    for k, v in fields.items():
        db.execute(f"UPDATE jobs SET {k}=? WHERE id=?", (v, body["id"]))
    return {"ok": True}


@app.delete("/api/job")
def job_delete_param(id: str):
    db.delete_job(id)
    return {"ok": True, "deleted": id}


@app.post("/api/job/delete")
def job_delete(body: dict = Body(...)):
    if "ids" in body and isinstance(body["ids"], list):
        n = db.delete_jobs(body["ids"])
        return {"ok": True, "deleted_count": n}
    job_id = body.get("id")
    if not job_id:
        raise HTTPException(400, "Missing job id")
    db.delete_job(job_id)
    return {"ok": True, "deleted": job_id}


@app.post("/api/jobs/cleanup")
def jobs_cleanup(body: dict = Body(default={})):
    max_days_rej = int(body.get("max_days_rejected", 30))
    min_sc = float(body.get("min_score_new", 30))
    max_days_new = int(body.get("max_days_new", 60))
    res = db.cleanup_jobs(max_days_rejected=max_days_rej, min_score_new=min_sc, max_days_new=max_days_new)
    return res


@app.post("/api/jobs/dedup")
def jobs_dedup():
    res = db.deduplicate_jobs()
    agent.rescore_all()
    return res


@app.post("/api/jobs/verify")
def jobs_verify(body: dict = Body(default={})):
    prune = bool(body.get("prune", False))
    limit = int(body.get("limit", 250))
    max_days = int(body.get("max_days", 60))
    jobs = db.rows("SELECT * FROM jobs WHERE status!='archived' ORDER BY score DESC LIMIT ?", (limit,))
    res = verifier.verify_jobs_batch(jobs, prune=prune, max_days=max_days, log=agent._log)
    if prune and res.get("pruned"):
        agent.rescore_all()
    return res


@app.get("/api/job/verify")
def job_verify_single(id: str):
    j = db.one("SELECT * FROM jobs WHERE id=?", (id,))
    if not j:
        raise HTTPException(404, "Job not found")
    res = verifier.verify_job(j, check_live=True)
    extra = json.loads(j.get("extra") or "{}")
    extra["link_check"] = {"ts": time.time(), **res}
    db.execute("UPDATE jobs SET extra=? WHERE id=?", (json.dumps(extra), id))
    return res


@app.post("/api/job/add")
def job_add(body: dict = Body(...)):
    j = sources._job("manual", body.get("url") or body.get("title") + str(time.time()),
                     body.get("title", "Untitled"), body.get("company", ""), body.get("location", ""),
                     body.get("url", ""), body.get("description", ""))
    db.upsert_job(j)
    agent.rescore_all()
    return j


@app.post("/api/job/review")
def job_review(body: dict = Body(...)):
    j = db.one("SELECT * FROM jobs WHERE id=?", (body["id"],))
    v = ok(coach.review_job, j, body.get("agent"))
    db.execute("UPDATE jobs SET ai_verdict=? WHERE id=?", (json.dumps(v), j["id"]))
    agent.rescore_all()
    return v


@app.post("/api/job/feedback")
def job_feedback(body: dict = Body(...)):
    """👍 / 👎 / clear — feeds straight into the score."""
    j = db.one("SELECT extra FROM jobs WHERE id=?", (body["id"],))
    extra = json.loads(j["extra"] or "{}")
    extra["feedback"] = body.get("value") or None
    db.execute("UPDATE jobs SET extra=? WHERE id=?", (json.dumps(extra), body["id"]))
    agent.rescore_all()
    return {"ok": True}


@app.get("/api/matchmaker")
def matchmaker():
    return extras.matchmaker()


@app.get("/api/job/related")
def job_related(id: str):
    """Zero-token extras for the drawer: people-finder links, and fellowships for a PI host."""
    j = db.one("SELECT title, company, kind FROM jobs WHERE id=?", (id,))
    out = {"people": [], "fellowships": [], "universities": extras.universities()}
    if j and j["kind"] not in ("collaborator", "intel", "hackathon", "conference", "funding"):
        out["people"] = extras.people_links(j["company"], j["title"])
    if j and j["kind"] == "collaborator":
        out["fellowships"] = extras.fellowships_for_host(id)
    return out


@app.post("/api/pack")
def pack(body: dict = Body(...)):
    return ok(extras.application_pack, body["job_id"], body.get("agent"))


@app.post("/api/reveal")
def reveal(body: dict = Body(...)):
    import subprocess
    path = Path(body["path"]).resolve()
    if ROOT / "applications" not in path.parents and path != ROOT / "applications":
        raise HTTPException(400, "Only application folders can be revealed.")
    subprocess.run(["open", str(path)])
    return {"ok": True}


@app.post("/api/linkedin/post")
def li_post(body: dict = Body(...)):
    text, used = ok(extras.linkedin_post, body.get("kind", "research_highlight"), body.get("context", ""),
                    body.get("language") or "English", body.get("agent"))
    return {"text": text, "agent": used}


@app.post("/api/linkedin/notes")
def li_notes(body: dict = Body(...)):
    notes, used = ok(extras.connection_notes, body["ids"][:15], body.get("agent"))
    return {"notes": notes, "agent": used}


@app.post("/api/linkedin/profile")
def li_profile(body: dict = Body(default={})):
    text, used = ok(extras.linkedin_profile, body.get("agent"))
    return {"text": text, "agent": used}


@app.post("/api/mock/start")
def mock_start(body: dict = Body(...)):
    return ok(extras.mock_start, body.get("job_id"), body.get("style", "mixed"), int(body.get("questions", 6)),
              body.get("language") or "English", body.get("agent"))


@app.post("/api/mock/answer")
def mock_answer(body: dict = Body(...)):
    return ok(extras.mock_answer, int(body["id"]), body["answer"], bool(body.get("finish")), body.get("agent"))


@app.get("/api/feedback/weights")
def fb_weights():
    return extras.feedback_weights()


@app.post("/api/country_brief")
def country_brief(body: dict = Body(...)):
    text, used = ok(coach.country_brief, body["country"], body.get("agent"))
    return {"text": text, "agent": used}


@app.post("/api/top5")
def top5(body: dict = Body(default={})):
    if body.get("email"):
        threading.Thread(target=agent.weekly_top5_email, daemon=True).start()
        return {"started": True}
    text, used = ok(coach.weekly_top5, body.get("agent"))
    return {"text": text, "agent": used}


@app.post("/api/scan")
def scan(body: dict = Body(default={})):
    if agent.STATE["running"]:
        return {"started": False, "msg": "already running"}
    threading.Thread(target=agent.scan, kwargs={"send_email": body.get("email", True)}, daemon=True).start()
    return {"started": True}


@app.get("/api/scan/log")
def scan_log():
    return {"running": agent.STATE["running"], "log": agent.STATE["log"][-80:]}


FEATURES = {
    "improve_resume": lambda b: coach.improve_resume(b.get("job_id"), b.get("jd", ""), b.get("focus", ""), b.get("agent")),
    "cover_letter": lambda b: coach.cover_letter(b.get("job_id"), b.get("jd", ""), b.get("tone") or "confident, warm, concise",
                                                 b.get("language") or "English", b.get("extra", ""), b.get("agent")),
    "email": lambda b: coach.draft_email(b.get("kind", "recruiter_outreach"), b.get("job_id"), b.get("recipient", ""),
                                         b.get("context", ""), b.get("language") or "English", b.get("agent")),
    "dev_plan": lambda b: coach.dev_plan(int(b.get("weeks", 8)), int(b.get("hours", 8)), b.get("goal", ""),
                                         b.get("agent"), bool(b.get("council"))),
    "train": lambda b: coach.train(b["skill"], b.get("mode", "quiz"), b.get("level", "intermediate"), b.get("agent")),
    "grade": lambda b: coach.grade(b["skill"], b["exercise"], b["answers"], b.get("agent")),
    "interview": lambda b: coach.interview_prep(b["job_id"], b.get("agent")),
    "tailor_resume": lambda b: coach.tailor_resume(b.get("job_id"), b.get("jd", ""), b.get("focus", ""),
                                                   b.get("format") or "markdown", b.get("agent")),
    "cheatsheet": lambda b: coach.interview_cheatsheet(b.get("job_id"), b.get("agent")),
    "salary_advisor": lambda b: coach.salary_advisor(b.get("job_id"), b.get("offer", ""), b.get("agent")),
}


@app.post("/api/ai/{feature}")
def ai_feature(feature: str, body: dict = Body(...)):
    if feature == "ats":
        return ok(coach.ats_review, body.get("jd", ""), body.get("job_id"), body.get("agent"))
    if feature not in FEATURES:
        raise HTTPException(404, "unknown feature")
    text, used = ok(FEATURES[feature], body)
    return {"text": text, "agent": used}


@app.get("/api/resume/export")
def resume_export(id: int = None, template: str = "industry"):
    from fastapi.responses import HTMLResponse
    from . import exporter
    if id:
        doc = db.one("SELECT * FROM documents WHERE id=?", (id,))
        if not doc:
            raise HTTPException(404, "Document not found")
        content = doc["content"]
        title = doc["title"]
    else:
        r = db.master_resume()
        if not r:
            raise HTTPException(400, "No master resume found")
        content = r["text"]
        title = "Master Resume"
    html_page = exporter.render_html_resume(content, template=template, title=title)
    return HTMLResponse(content=html_page)


@app.get("/api/tracker/status")
def tracker_status():
    return {"configured": tracker.configured()}


@app.get("/api/tracker/stalled")
def tracker_stalled(days: int = 7):
    return tracker.stalled_applications(days_threshold=days)


@app.post("/api/tracker/followup")
def tracker_followup(body: dict = Body(...)):
    text, used = ok(tracker.draft_followup, body["job_id"], body.get("language") or "English", body.get("agent"))
    return {"text": text, "agent": used}


@app.post("/api/tracker/sync")
def tracker_sync(body: dict = Body(default={})):
    days = int(body.get("days", 14))
    limit = int(body.get("limit", 50))
    dry_run = bool(body.get("dry_run", False))
    agent_pref = body.get("agent")
    return ok(tracker.sync_inbox, days=days, limit=limit, dry_run=dry_run, agent=agent_pref)


@app.post("/api/ats/quick")
def ats_quick(body: dict = Body(...)):
    r = db.master_resume()
    return scoring.ats_check(body.get("resume") or (r["text"] if r else ""), body.get("jd", ""))


@app.post("/api/agents/probe")
def agents_probe():
    st = ai.status()
    return {k: (ai.probe(k) if (v["ready"] or "needs login" in v["detail"]) else {"ok": False, "error": v["detail"]})
            for k, v in st.items()}


@app.post("/api/council")
def council(body: dict = Body(...)):
    return ok(ai.council, body["prompt"])


@app.get("/api/chat")
def chat_hist():
    return db.rows("SELECT * FROM chat ORDER BY id DESC LIMIT 60")[::-1]


@app.post("/api/chat")
def chat(body: dict = Body(...)):
    text, used = ok(coach.chat, body["message"], body.get("agent"), bool(body.get("council")))
    return {"text": text, "agent": used}


@app.delete("/api/chat")
def chat_clear():
    db.execute("DELETE FROM chat")
    return {"ok": True}


@app.get("/api/docs")
def docs(kind: str = ""):
    if kind:
        return db.rows("SELECT id,kind,title,agent,created,job_id FROM documents WHERE kind=? ORDER BY id DESC", (kind,))
    return db.rows("SELECT id,kind,title,agent,created,job_id FROM documents ORDER BY id DESC LIMIT 200")


@app.get("/api/doc")
def doc(id: int):
    return db.one("SELECT * FROM documents WHERE id=?", (id,))


@app.delete("/api/doc")
def doc_delete(id: int):
    db.execute("DELETE FROM documents WHERE id=?", (id,))
    return {"ok": True}


@app.get("/api/gaps")
def gaps():
    return coach.skill_gaps()


@app.get("/api/xray")
def xray():
    s = get_settings()
    roles = s.get("target_roles") or ["engineer"]
    locs = s.get("locations") or [""]
    loc = next((l for l in locs if l.lower() != "remote"), "")
    return [{"role": r, "links": sources.xray_links(r, loc, s.get("keywords"))} for r in roles[:5]]


@app.post("/api/email/test")
def email_test():
    to = ok(emailer.send, "✅ JobAgent email test", "<p>Your JobAgent alerts are working.</p>")
    return {"sent_to": to}


@app.post("/api/weekly")
def weekly():
    threading.Thread(target=agent.weekly_coaching_email, daemon=True).start()
    return {"started": True}


# ---- categories, tracker, calendar, skills, map -----------------------------------------

@app.get("/api/categories")
def cats():
    out = []
    excl, eargs = db.country_filter()
    for c in categories.all_categories():
        if c["id"] in ("collab", "hackathon", "fellowship", "conference", "trends", "research", "indiv_funding"):
            continue  # these live in their own sections
        r = db.one("SELECT COUNT(*) n, MAX(score) top, SUM(CASE WHEN found_at > ? THEN 1 ELSE 0 END) fresh "
                   f"FROM jobs WHERE categories LIKE ? AND status!='archived' AND {db.SECTIONS['jobs']}" + excl,
                   (time.time() - 86400 * 2, f'%"{c["id"]}"%', *eargs))
        out.append({**{k: c[k] for k in ("id", "label", "glyph")}, "count": r["n"], "top": r["top"] or 0,
                    "fresh": r["fresh"] or 0})
    return out


# ---- first-run setup ------------------------------------------------------------------------------
@app.get("/api/setup/status")
def setup_status():
    from . import setup
    return setup.status()


@app.post("/api/setup/pack")
def setup_pack(body: dict = Body(...)):
    """Pick a built-in field pack, or let the AI write one from the CV."""
    from . import packs
    if body.get("builtin"):
        if not packs.builtin(body["builtin"]):
            raise HTTPException(404, "unknown pack")
        save_settings({"pack": body["builtin"]})
    else:
        r = db.master_resume()
        if not r:
            raise HTTPException(400, "Upload your CV first.")
        pk = ok(packs.generate_pack, r["text"], get_settings().get("preferences", ""), body.get("agent"))
        if not pk.get("lanes"):
            raise HTTPException(400, "The AI could not build field lanes from this CV; pick a built-in pack.")
        save_settings({"pack": pk})
    threading.Thread(target=agent.rescore_all, daemon=True).start()
    p = packs.active()
    return {"name": p.get("name"), "field": p.get("field"), "lanes": [l["label"] for l in p.get("lanes", [])],
            "companies": p.get("intel_companies", [])[:12]}


@app.post("/api/setup/email")
def setup_email(body: dict = Body(...)):
    from . import setup
    return ok(setup.connect_email, body.get("provider", "gmail"), body["address"], body["password"],
              body.get("alerts_to", ""), body.get("smtp_host", ""), body.get("smtp_port", 0), body.get("imap_host", ""))


@app.post("/api/setup/key")
def setup_key(body: dict = Body(...)):
    """Optional API keys (Gemini, Anthropic, Adzuna, France Travail) written to the user's private .env."""
    from . import setup
    allowed = {"GEMINI_API_KEY", "ANTHROPIC_API_KEY", "ADZUNA_APP_ID", "ADZUNA_APP_KEY", "APIFY_TOKEN",
               "FRANCE_TRAVAIL_CLIENT_ID", "FRANCE_TRAVAIL_CLIENT_SECRET"}
    upd = {k: v for k, v in body.items() if k in allowed and v}
    setup.write_env(upd)
    return {"saved": sorted(upd)}


@app.post("/api/setup/finish")
def setup_finish(body: dict = Body(default={})):
    keep = {k: body[k] for k in ("apply_mode", "modules", "home_country", "locations", "excluded_countries", "preferences",
                                  "scan_interval_hours") if k in body}
    save_settings({**keep, "setup_done": True})
    if body.get("scan"):
        threading.Thread(target=agent.scan, kwargs={"send_email": False}, daemon=True).start()
    return {"ok": True}


# ---- swipe deck ---------------------------------------------------------------------------------
DECK_SCOPES = {
    "jobs": ["jobs"], "academia": ["postdocs", "fellowships", "grants", "contacts"],
    "community": ["hackathons", "events"], "all": ["jobs", "postdocs", "fellowships", "grants", "hackathons", "events"],
}
_rescore_timer = {"t": None}


def _rescore_soon(delay=20):
    """Debounced rescore so a burst of swipes trains the scoring once, not per swipe."""
    if _rescore_timer["t"]:
        _rescore_timer["t"].cancel()
    _rescore_timer["t"] = threading.Timer(delay, agent.rescore_all)
    _rescore_timer["t"].daemon = True
    _rescore_timer["t"].start()


@app.get("/api/deck")
def deck(scope: str = "all", n: int = 30):
    """Cards to swipe: ~55% best matches, ~30% 💎 priority-lane gems (whatever their score), ~15% exploration."""
    import random
    secs = DECK_SCOPES.get(scope, [scope] if scope in db.SECTIONS else DECK_SCOPES["all"])
    excl, eargs = db.country_filter()
    cond = " OR ".join(f"({db.SECTIONS[x]})" for x in secs)
    now = time.time()
    where = (f"status='new' AND ({cond}){excl} "
             "AND (json_extract(extra,'$.swipe') IS NULL OR (json_extract(extra,'$.swipe')='later' "
             "AND COALESCE(json_extract(extra,'$.snooze_until'),0) < ?)) "
             "AND COALESCE(json_extract(extra,'$.link_check.status'),'') NOT IN ('broken','generic','expired') "
             "AND COALESCE(json_extract(extra,'$.verified.status'),'') NOT IN ('closed','not_found','mismatch') "
             "AND NOT (COALESCE(json_extract(extra,'$.found_by'),'') LIKE 'gemini%' "
             "AND COALESCE(json_extract(extra,'$.verified.status'),'') != 'open')")
    total = db.one(f"SELECT COUNT(*) n FROM jobs WHERE {where}", (*eargs, now))["n"]
    pool = db.rows(f"SELECT * FROM jobs WHERE {where} ORDER BY score DESC LIMIT 600", (*eargs, now))
    gems = [j for j in pool if '"gem": true' in (j["extra"] or "")]
    top = [j for j in pool if j not in gems]
    mid = [j for j in top[len(top) // 3:] if 35 <= (j["score"] or 0) < 65]
    random.shuffle(mid)
    n_g, n_x = round(n * .30), round(n * .15)
    picks, seen = [], set()
    pattern = ["top", "top", "gem", "top", "explore", "gem"]
    src = {"top": iter(top), "gem": iter(gems), "explore": iter(mid)}
    quota = {"top": n - n_g - n_x, "gem": n_g, "explore": n_x}
    while len(picks) < n and any(quota.values()):
        progressed = False
        for kind in pattern:
            if len(picks) >= n or quota[kind] <= 0:
                continue
            for j in src[kind]:
                if j["id"] not in seen:
                    seen.add(j["id"]); j["_why_card"] = kind; picks.append(j); quota[kind] -= 1; progressed = True
                    break
            else:
                quota["top"] += quota[kind]; quota[kind] = 0  # pool ran dry → refill with best matches
        if not progressed:
            break
    for j in picks:
        j["description"] = (j["description"] or "")[:700]
    return {"cards": picks, "remaining": total}


@app.post("/api/swipe")
def swipe(body: dict = Body(...)):
    """right=like→saved · left=nope→archived · up=super→saved+starred · down=later→snoozed 3 days."""
    j = db.one("SELECT status, extra FROM jobs WHERE id=?", (body["id"],))
    if not j:
        raise HTTPException(404, "not found")
    act = body["action"]
    x = json.loads(j["extra"] or "{}")
    x["swipe_prev"] = {"status": j["status"], "feedback": x.get("feedback"), "swipe": x.get("swipe")}
    x["swipe"], x["swiped_at"] = act, time.time()
    status = j["status"]
    if act in ("like", "super"):
        status, x["feedback"] = "saved", "up"
        x["star"] = act == "super"
    elif act == "nope":
        status, x["feedback"], x["archived_reason"] = "archived", "down", "swiped left"
    elif act == "later":
        x["snooze_until"] = time.time() + 3 * 86400
    db.execute("UPDATE jobs SET status=?, extra=? WHERE id=?", (status, json.dumps(x), body["id"]))
    if act in ("like", "super", "nope"):
        _rescore_soon()
    return {"ok": True, "status": status}


@app.post("/api/swipe/undo")
def swipe_undo(body: dict = Body(...)):
    j = db.one("SELECT extra FROM jobs WHERE id=?", (body["id"],))
    x = json.loads(j["extra"] or "{}")
    prev = x.pop("swipe_prev", None) or {"status": "new"}
    for k in ("swipe", "swiped_at", "snooze_until", "star", "archived_reason"):
        x.pop(k, None)
    x["feedback"] = prev.get("feedback")
    db.execute("UPDATE jobs SET status=?, extra=? WHERE id=?", (prev.get("status") or "new", json.dumps(x), body["id"]))
    _rescore_soon()
    return {"ok": True}


@app.post("/api/autofilter")
def autofilter_now(body: dict = Body(default={})):
    from . import autofilter
    return autofilter.run(agent._log, dry=bool(body.get("dry")))


@app.get("/api/apify/status")
def apify_status():
    from . import apify
    if not apify.token():
        return {"token": False}
    try:
        b = apify.budget()
    except Exception as e:  # noqa: BLE001
        return {"token": True, "error": str(e)[:200]}
    led = json.loads(apify.LEDGER.read_text())[-8:] if apify.LEDGER.exists() else []
    return {"token": True, "budget": b, "recent": led[::-1], "queries": apify.plan_queries(),
            "sources": {k: v["label"] for k, v in apify.ACTORS.items()}}


@app.post("/api/apify/scan")
def apify_scan(body: dict = Body(default={})):
    """Manual, budget-guarded Apify scan. dry=true returns the plan and live budget without spending anything."""
    from . import apify
    s = get_settings()
    kw = dict(sources=tuple(body.get("sources") or apify.ACTORS), queries=body.get("queries") or None,
              items_per_run=int(body.get("items_per_run") or s.get("apify_items_per_run", 20)),
              cap_per_run=float(body.get("cap_per_run") or s.get("apify_cap_per_run_usd", 0.15)), agent=body.get("agent"))
    if body.get("dry", True):
        return ok(apify.scan, dry=True, **kw)

    def go():
        agent._log("Apify scan started")
        try:
            apify.scan(log=agent._log, **kw)
            agent.rescore_all()
        except Exception as e:  # noqa: BLE001
            agent._log(f"Apify scan stopped: {str(e)[:200]}")
        agent._log("Apify done")
    threading.Thread(target=go, daemon=True).start()
    return {"started": True}


@app.post("/api/apply")
def apply_start(body: dict = Body(...)):
    from . import apply
    return ok(apply.start, body["id"], body.get("mode"), body.get("agent"), body.get("to"))


@app.post("/api/cv/latex")
def cv_latex(body: dict = Body(default={})):
    from . import latex_cv
    return ok(latex_cv.build, body.get("job_id"), body.get("language", "auto"), body.get("agent"))


@app.get("/api/apply/queue")
def apply_queue():
    from . import apply
    return {"queue": apply.queue(), "sent_today": apply.sent_today(), "limit": get_settings().get("apply_daily_limit", 5),
            "mode": get_settings().get("apply_mode")}


@app.post("/api/apply/cancel")
def apply_cancel(body: dict = Body(...)):
    from . import apply
    apply.cancel(int(body["id"]))
    return {"ok": True}


@app.post("/api/apply/send")
def apply_send(body: dict = Body(default={})):
    from . import apply
    return ok(apply.send_due, agent._log)


@app.get("/api/game")
def game_state():
    from . import game
    return game.state()


@app.get("/api/kb/status")
def kb_status():
    from . import kb
    return kb.status()


@app.post("/api/kb/export")
def kb_export(body: dict = Body(...)):
    from . import kb
    d = db.one("SELECT title, content, kind FROM documents WHERE id=?", (int(body["doc_id"]),))
    if not d:
        raise HTTPException(404, "document not found")
    return {"path": ok(kb.export_doc, d["title"], d["content"], d["kind"] or "note")}


@app.get("/api/templates")
def templates_list():
    from . import templates
    return templates.all_templates()


@app.post("/api/templates")
def templates_add(body: dict = Body(...)):
    from . import templates
    r = ok(templates.add, body.get("title", ""), body.get("company", ""), body.get("url", ""), body.get("text", ""),
           body.get("job_id"))
    threading.Thread(target=agent.rescore_all, daemon=True).start()
    return r


@app.delete("/api/templates")
def templates_delete(id: int):
    from . import templates
    templates.delete(id)
    threading.Thread(target=agent.rescore_all, daemon=True).start()
    return {"ok": True}


@app.post("/api/templates/plan")
def templates_plan(body: dict = Body(default={})):
    from . import templates
    text, used = ok(templates.gap_plan, body.get("agent"))
    return {"text": text, "agent": used}


@app.post("/api/verify/web")
def verify_web(body: dict = Body(...)):
    """Have Claude/Codex open the page(s) and confirm the posting; records who verified and when."""
    from . import verifier
    jobs = [db.one("SELECT * FROM jobs WHERE id=?", (i,)) for i in body.get("ids", [])[:10]]
    jobs = [j for j in jobs if j]
    counts = verifier.web_verify_batch(jobs, agent=body.get("agent"), log=agent._log)
    return {"counts": counts, "results": [json.loads(db.one("SELECT extra FROM jobs WHERE id=?", (j["id"],))["extra"]).get("verified") for j in jobs]}


@app.get("/api/sections")
def sections():
    """Counts, best score, fresh items and next deadline per section (for the sidebar and Command)."""
    excl, eargs = db.country_filter()
    out = {}
    for name, cond in db.SECTIONS.items():
        r = db.one(f"SELECT COUNT(*) n, MAX(score) top, SUM(CASE WHEN found_at > ? THEN 1 ELSE 0 END) fresh, "
                   f"MIN(CASE WHEN deadline >= date('now') THEN deadline END) nextdl FROM jobs "
                   f"WHERE status!='archived' AND {cond}" + excl, (time.time() - 2 * 86400, *eargs))
        out[name] = {"count": r["n"], "top": r["top"] or 0, "fresh": r["fresh"] or 0, "next_deadline": r["nextdl"] or ""}
    return out


@app.get("/api/tracker")
def api_tracker():
    return db.rows("SELECT id,title,company,location,status,score,kind,categories,deadline,applied_at,next_action,"
                   "next_date,url FROM jobs WHERE status NOT IN ('new','archived') ORDER BY "
                   "CASE WHEN deadline='' THEN 1 ELSE 0 END, deadline, score DESC")


@app.get("/api/calendar")
def calendar(start: str, end: str):
    items = []
    for j in db.rows("SELECT id,title,company,kind,status,score,deadline,next_date,next_action,applied_at,url "
                     "FROM jobs WHERE status!='archived' AND ((deadline BETWEEN ? AND ?) OR (next_date BETWEEN ? AND ?) "
                     "OR (applied_at BETWEEN ? AND ?))", (start, end) * 3):
        if j["deadline"] and start <= j["deadline"] <= end:
            items.append({"date": j["deadline"], "type": "deadline", "title": j["title"], "sub": j["company"],
                          "job_id": j["id"], "kind": j["kind"], "status": j["status"], "score": j["score"]})
        if j["next_date"] and start <= j["next_date"] <= end:
            items.append({"date": j["next_date"], "type": "next", "title": j["next_action"] or "Next step",
                          "sub": f"{j['title']} · {j['company']}", "job_id": j["id"], "kind": j["kind"]})
        if j["applied_at"] and start <= j["applied_at"] <= end:
            items.append({"date": j["applied_at"], "type": "applied", "title": "Applied: " + j["title"],
                          "sub": j["company"], "job_id": j["id"], "kind": j["kind"]})
    for e in db.rows("SELECT * FROM events WHERE date BETWEEN ? AND ?", (start, end)):
        items.append({"date": e["date"], "type": e["kind"], "title": e["title"], "sub": e["notes"],
                      "time": e["time"], "event_id": e["id"], "done": e["done"], "job_id": e["job_id"]})
    return sorted(items, key=lambda x: (x["date"], x.get("time") or ""))


@app.post("/api/events")
def add_event(body: dict = Body(...)):
    eid = db.execute("INSERT INTO events (title,date,time,kind,job_id,notes) VALUES (?,?,?,?,?,?)",
                     (body["title"], body["date"], body.get("time", ""), body.get("kind", "event"),
                      body.get("job_id"), body.get("notes", "")))
    return {"id": eid}


@app.post("/api/events/done")
def event_done(body: dict = Body(...)):
    db.execute("UPDATE events SET done=? WHERE id=?", (int(body.get("done", 1)), body["id"]))
    return {"ok": True}


@app.delete("/api/events")
def del_event(id: int):
    db.execute("DELETE FROM events WHERE id=?", (id,))
    return {"ok": True}


@app.get("/api/calendar.ics")
def ics():
    today = date.today().isoformat()
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//JobAgent//EN", "X-WR-CALNAME:JobAgent"]
    for it in calendar(today, (date.today() + timedelta(days=400)).isoformat()):
        d = it["date"].replace("-", "")
        nxt = (date.fromisoformat(it["date"]) + timedelta(days=1)).isoformat().replace("-", "")
        summ = f"[{it['type'].upper()}] {it['title']}".replace(",", "\\,")
        lines += ["BEGIN:VEVENT", f"UID:{hashlib.sha1((it['date'] + it['title'] + it['type']).encode()).hexdigest()[:20]}@jobagent",
                  f"DTSTAMP:{date.today().strftime('%Y%m%d')}T000000Z", f"DTSTART;VALUE=DATE:{d}",
                  f"DTEND;VALUE=DATE:{nxt}", f"SUMMARY:{summ}", f"DESCRIPTION:{(it.get('sub') or '')[:200]}",
                  "BEGIN:VALARM", "TRIGGER:-P2D", "ACTION:DISPLAY", "DESCRIPTION:JobAgent deadline", "END:VALARM",
                  "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return Response("\r\n".join(lines), media_type="text/calendar",
                    headers={"Content-Disposition": "attachment; filename=jobagent.ics"})


@app.get("/api/skills")
def skills():
    """Rank skills by market demand (weighted by match score) against your self-rated level."""
    s = get_settings()
    r = db.master_resume()
    rtext = scoring.norm(r["text"]) if r else ""
    demand = {}
    rows_ = db.rows("SELECT title, description, score FROM jobs WHERE status!='archived' AND kind IN ('job','research','fellowship')"
                    " AND categories != '[]' AND categories IS NOT NULL AND score >= 50" + db.country_filter()[0] +
                    " ORDER BY score DESC LIMIT 200", db.country_filter()[1])
    soft = {"english", "french", "spanish", "german", "communication", "leadership", "presentation", "teaching",
            "mentoring", "research", "publications", "strategy", "consulting", "phd", "postdoc", "biology", "physics",
            "hardware", "electronics", "validation", "quality control", "cad"}
    vocab = (set(scoring.expand_terms(s.get("keywords", []))) | set(scoring.PHRASES) | scoring.SINGLES) - soft
    for j in rows_:
        text = scoring.norm(j["title"] + " " + j["description"][:5000])
        w = ((j["score"] or 0) / 100) ** 2  # strong matches dominate the demand signal
        for term in vocab:
            if len(term) > 2 and scoring.has(term, text):
                demand[term] = demand.get(term, 0) + w
    mine = {x["name"]: x for x in db.rows("SELECT * FROM skills")}
    top = max(demand.values(), default=1)
    out = []
    for name, d in sorted(demand.items(), key=lambda kv: -kv[1])[:40]:
        have = scoring.has(name, rtext)
        m = mine.get(name, {})
        level = m.get("level") if m.get("level") is not None and name in mine else (3 if have else 0)
        target = m.get("target") or 4
        dem = round(100 * d / top)
        out.append({"name": name, "demand": dem, "level": level, "target": target, "in_resume": have,
                    "priority": round(dem * max(target - level, 0) / 4),
                    "history": db.rows("SELECT level, ts FROM skill_history WHERE name=? ORDER BY ts", (name,))})
    for name, m in mine.items():
        if name not in demand:
            out.append({"name": name, "demand": 0, "level": m["level"], "target": m["target"], "in_resume": True,
                        "priority": 0, "history": []})
    return sorted(out, key=lambda x: -x["priority"])


@app.post("/api/skills")
def skill_set(body: dict = Body(...)):
    name = body["name"].lower().strip()
    lvl, tgt = int(body.get("level", 0)), int(body.get("target", 4))
    db.execute("INSERT INTO skills (name,level,target,updated) VALUES (?,?,?,?) ON CONFLICT(name) DO UPDATE SET "
               "level=excluded.level, target=excluded.target, updated=excluded.updated", (name, lvl, tgt, time.time()))
    db.execute("INSERT INTO skill_history (name,level,ts) VALUES (?,?,?)", (name, lvl, time.time()))
    return {"ok": True}


@app.get("/api/map")
def world_map(category: str = "", min_score: float = 0, section: str = ""):
    excl, eargs = db.country_filter()
    sql, args = "SELECT id,title,company,location,kind,score,categories,deadline,status,extra FROM jobs " \
                "WHERE status!='archived' AND score>=?" + excl, [min_score, *eargs]
    if section in db.SECTIONS:
        sql += f" AND {db.SECTIONS[section]}"
    if category:
        sql += " AND categories LIKE ?"
        args.append(f'%"{category}"%')
    points, virtual = {}, []
    for j in db.rows(sql + " ORDER BY score DESC LIMIT 1500", args):
        loc = j["location"]
        if j["kind"] == "collaborator":
            cc = json.loads(j["extra"] or "{}").get("country", "") or loc
            loc = geo.ISO2.get(cc.upper(), cc)
        g = geo.locate(loc)
        item = {k: j[k] for k in ("id", "title", "company", "kind", "score", "deadline", "status")}
        item["categories"] = json.loads(j["categories"] or "[]")
        if not g or g["virtual"]:
            virtual.append(item)
            continue
        key = (g["lat"], g["lon"])
        p = points.setdefault(key, {"lat": g["lat"], "lon": g["lon"], "place": g["place"], "items": []})
        p["items"].append(item)
    pts = sorted(points.values(), key=lambda p: -len(p["items"]))
    return {"points": pts, "virtual": virtual[:200], "virtual_count": len(virtual)}


@app.post("/api/contacts/refresh")
def contacts_refresh():
    """Re-pull European PIs from OpenAlex (no AI tokens)."""
    new = 0
    from . import packs
    for t in packs.active().get("collab_topics", []):
        try:
            new += sum(db.upsert_job(x) for x in opportunities.collaborators(t))
        except Exception as e:  # noqa: BLE001
            agent._log(f"contacts {t}: {e}")
    agent.rescore_all()
    return {"new": new}


@app.post("/api/radar")
def radar_now(body: dict = Body(default={})):
    """Run the AI web radar now for one category (or the next ones in rotation)."""
    def go():
        agent_pref = body.get("agent")
        agent._log(f"Radar started (agent: {agent_pref or 'auto'})")
        prof = (db.master_resume() or {}).get("profile", "")
        cats = body.get("categories") or ([body["category"]] if body.get("category") else [])
        s = get_settings()
        picks = [x for x in opportunities.lanes() if x[0] in cats] or \
            opportunities.radar_next(s.get("radar_per_scan", 0), s.get("radar_pinned", []))
        got, _ = opportunities.run_radar(picks, s, agent._log, agent_pref=agent_pref)
        new = sum(db.upsert_job(o) for o in got)
        agent._log(f"  radar total: {len(got)} found, {new} new")
        agent.rescore_all()
        agent._log("Radar done")
    threading.Thread(target=go, daemon=True).start()
    return {"started": True}


# ---- built-in scheduler -------------------------------------------------------------
SCHED = {"next": None}


def _scheduler():
    # resume from the database so restarts don't re-trigger runs
    r = db.one("SELECT MAX(started) t FROM runs WHERE kind='scan'")
    last_scan = (r and r["t"]) or 0.0
    r = db.one("SELECT MAX(started) t FROM runs WHERE kind='weekly_plan'")
    last_weekly = datetime.fromtimestamp(r["t"]).strftime("%G-%V") if r and r["t"] else ""
    time.sleep(20)
    while True:
        s = get_settings()
        interval = max(1, float(s.get("scan_interval_hours", 6))) * 3600
        SCHED["next"] = last_scan + interval if last_scan else time.time()
        if time.time() >= SCHED["next"] and db.master_resume():
            last_scan = time.time()
            try:
                agent.scan()
            except Exception as e:  # noqa: BLE001
                print("scheduled scan failed:", e)
        now = datetime.now()
        wk = now.strftime("%G-%V")
        if now.weekday() == 0 and now.hour >= s.get("daily_digest_hour", 8) and wk != last_weekly \
                and db.master_resume():
            last_weekly = wk
            for job in (agent.weekly_top5_email, agent.weekly_coaching_email):
                try:
                    job()
                except Exception as e:  # noqa: BLE001
                    print("weekly job failed:", job.__name__, e)
        time.sleep(60)


@app.on_event("startup")
def start_scheduler():
    threading.Thread(target=_scheduler, daemon=True).start()
