"""The scheduled job-hunting cycle: fetch -> score -> agent review -> email."""
import itertools
import json
import time

from datetime import date, timedelta

from . import ai, categories, coach, db, emailer, extras, geo, opportunities, scoring, sources, verifier
from .config import get_settings

STATE = {"running": False, "last": None, "log": []}


def _log(msg):
    line = time.strftime("%H:%M:%S ") + str(msg)
    print(line, flush=True)
    STATE["log"] = (STATE["log"] + [line])[-200:]


def _core():
    from . import packs
    return packs.core_lanes()
CAREER_TRACKS = {"medtech", "product", "analyst", "exec", "founding", "vc", "research", "internship"}
EUROPE = {"FR", "DE", "NL", "BE", "CH", "GB", "IE", "AT", "IT", "ES", "PT", "DK", "SE", "NO", "FI", "PL", "CZ",
          "HU", "GR", "LU", "SI", "HR", "EE", "LT", "LV", "SK", "RO", "IS", "CY", "MT", "EU"}
SENIOR_TITLE = r"\b(senior|sr\.?|principal|staff|lead|director|head|vp)\b"


def profile_text(s, r):
    """Everything we know about you, not just the resume: AI profile, preferences, rated skills."""
    prof = json.loads(r.get("profile") or "{}")
    skills = [x["name"] for x in db.rows("SELECT name FROM skills WHERE level>=3")]
    parts = [r["text"], prof.get("headline", ""), prof.get("summary", ""), " ".join(prof.get("strengths", [])),
             " ".join(prof.get("keywords", [])), " ".join(s.get("target_roles", [])), s.get("preferences", ""),
             " ".join(skills)]
    return "\n".join(p for p in parts if p), prof


def rescore_all():
    """Score = profile match (resume + AI profile + preferences + rated skills) + lane/location fit,
    blended with the agents' fit verdict when one exists, adjusted by your 👍/👎 feedback."""
    import re as _re
    import hashlib
    s = get_settings()
    r = db.master_resume()
    if not r:
        return 0
    ptext, prof = profile_text(s, r)
    seniority = (prof.get("seniority") or "mid").lower()
    pref = scoring.norm(s.get("preferences", ""))
    jobs = db.rows("SELECT id,title,company,description,location,remote,tags,kind,extra,ai_verdict FROM jobs")
    kw = scoring.expand_terms(s.get("keywords", []) + prof.get("keywords", []))
    learned = extras.feedback_weights()
    CORE_TRACKS = _core()
    from . import templates
    like_template = templates.matcher()
    with db.db() as con:
        for j in jobs:
            j["tags"] = json.loads(j["tags"] or "[]")
            extra = json.loads(j.get("extra") or "{}")
            cats = categories.tag(j)
            cset = set(cats)
            why = []
            loc = j["location"]
            if j["kind"] == "collaborator":
                cc = extra.get("country", "")
                loc = geo.ISO2.get(cc.upper(), cc) if cc else loc
            g = geo.locate(loc) or {}
            cc = g.get("cc", "")
            if j["kind"] in ("job", "internship"):
                score, m, miss = scoring.match(ptext, j, s)
                why.append(f"profile match {score:.0f}")
                core = len(cset & CORE_TRACKS)
                if core:
                    score += min(16, 8 * core)
                    why.append(f"+{min(16, 8 * core)} core field")
                if cset & CAREER_TRACKS:
                    score += 6
                    why.append("+6 target lane")
                if not (cset & (CORE_TRACKS | CAREER_TRACKS)):
                    score *= 0.7
                    why.append("×0.7 outside your field")
                if seniority in ("junior", "mid") and _re.search(SENIOR_TITLE, j["title"].lower()) \
                        and not (cset & {"exec", "founding"}):
                    score -= 10
                    why.append("-10 seniority above profile")
            else:
                text = scoring.norm(j["title"] + " " + j["description"])
                m = [k for k in kw if scoring.has(k, text)][:12]
                miss = []
                score = 35 + 8 * len(cset & CORE_TRACKS) + 4 * len(cats) + 5 * len(m) + (10 if extra.get("radar") else 0)
                if j["kind"] == "collaborator":
                    score = 45 + 6 * min(extra.get("papers", 0), 6)
                if j["kind"] == "intel":
                    score = 50
                if j["kind"] == "trend":
                    score = 50
                if j["kind"] in ("conference", "event"):
                    score = 45 + 10 * len(cset & CORE_TRACKS)
                why.append(f"relevance {score:.0f}")
            if cc in EUROPE or g.get("virtual"):
                score += 5
                why.append("+5 Europe/remote")
            if pref and any(w in pref for w in (cc.lower(), (g.get("place") or "").lower()) if w):
                score += 5
                why.append("+5 matches your preferences")
            v = json.loads(j.get("ai_verdict") or "{}")
            if isinstance(v.get("fit"), (int, float)):
                score = 0.35 * score + 0.65 * v["fit"]
                why.append(f"blended with {v.get('agent', 'agent')} fit {v['fit']}")
            fit = round(max(0, min(score, 100)))   # honest fit: profile match (+ agent verdict); boosts below only rank
            extra["fit"] = fit
            gem = bool(cset & set(s.get("priority_lanes", [])))
            if gem and j["kind"] in ("job", "internship"):
                score += s.get("priority_boost", 18)
                why.append(f"+{s.get('priority_boost', 18)} 💎 priority lane")
            tb, twhy = like_template(j) if j["kind"] in ("job", "internship", "research") else (0, "")
            if tb:
                score += tb
                why.append(twhy)
                gem = gem or tb >= 10  # resembles a template you gave → surfaces in the 💎 slots too
            extra["like_template"] = twhy or None
            extra["gem"] = gem
            lb, lwhy = extras.learned_bonus(j, cats, learned)
            if lb and not extra.get("feedback"):
                score += lb
                why.append(lwhy)
            reviewed = extra.get("fit_review", {})
            if (reviewed.get("reviewer") in ("codex", "claude_cli")
                    and reviewed.get("resume_sha256") == hashlib.sha256(r["text"].encode()).hexdigest()
                    and isinstance(reviewed.get("score"), (int, float))
                    and reviewed.get("source_evidence")):
                score = reviewed["score"]
                why = [f"resume-based {reviewed['reviewer']} review: {score}"]
            fb = extra.get("feedback")
            if fb == "up":
                score += 15
                why.append("+15 you liked it")
            elif fb == "down":
                score -= 30
                why.append("-30 you disliked it")
            score = round(max(0, min(score, 140)), 1)   # ranking value (fit + boosts); the UI shows `fit`
            extra["rarity"] = ("legendary" if score >= 100 or (gem and fit >= 75) else "epic" if score >= 85
                               else "rare" if score >= 70 else "uncommon" if score >= 55 else "common")
            extra["score_why"] = why
            con.execute("UPDATE jobs SET score=?, matched=?, missing=?, categories=?, country=?, extra=? WHERE id=?",
                        (score, json.dumps(m), json.dumps(miss), json.dumps(cats), cc, json.dumps(extra), j["id"]))
    return len(jobs)


def scan(send_email=True, review=True):
    """One full cycle. Safe to call from the scheduler or the dashboard."""
    if STATE["running"]:
        return {"error": "scan already running"}
    STATE["running"] = True
    started = time.time()
    s = get_settings()
    try:
        _log("Scan started")
        jobs, errors = sources.fetch_all(s, _log)
        new = sum(db.upsert_job(j) for j in jobs)
        _log(f"Fetched {len(jobs)} jobs, {new} new. Source errors: {len(errors)}")
        for e in errors[:8]:
            _log("  ! " + e[:200])
        if s.get("email_alerts", True):
            try:
                from . import alerts
                ajobs, astats = alerts.fetch(days=10)
                anew = sum(db.upsert_job(j) for j in ajobs)
                jobs = jobs + ajobs
                _log(f"Job-alert emails: {', '.join(f'{k} {v['jobs']}' for k, v in astats.items() if v['emails'])} → {anew} new")
            except Exception as e:  # noqa: BLE001
                errors.append(f"email alerts: {e}")
        opps, oerr = opportunities.fetch_all(s, _log, radar_n=s.get("radar_per_scan", 0))
        onew = sum(db.upsert_job(o) for o in opps)
        errors += oerr
        _log(f"Opportunities: {len(opps)} found, {onew} new")
        rescore_all()
        from . import autofilter
        autofilter.run(_log)  # archive expired / stale / generic / duplicates (engaged items untouched)
        n_ver = int(s.get("model_verify_per_scan", 6) or 0)
        if n_ver:  # AI-found links can be invented: a trusted model opens the page before it reaches you
            unver = db.rows("SELECT * FROM jobs WHERE status='new' AND kind IN ('job','internship','research') "
                            "AND (source='radar' OR json_extract(extra,'$.found_by') IS NOT NULL) "
                            "AND json_extract(extra,'$.verified') IS NULL ORDER BY score DESC LIMIT ?", (n_ver,))
            if unver:
                _log(f"Model-verifying {len(unver)} AI-found link(s)")
                verifier.web_verify_batch(unver, log=_log)

        excl, eargs = db.country_filter()
        cands = db.rows("SELECT * FROM jobs WHERE alerted=0 AND score>=? AND status='new' AND kind NOT IN ('collaborator','intel','trend') "
                        "AND NOT (COALESCE(json_extract(extra,'$.found_by'),'') LIKE 'gemini%' "
                        "AND COALESCE(json_extract(extra,'$.verified.status'),'') != 'open') "
                        f"{excl} ORDER BY score DESC LIMIT 30", (s["min_score"], *eargs))
        _log(f"{len(cands)} un-alerted jobs at or above {s['min_score']}")

        if cands:
            v_res = verifier.verify_jobs_batch(cands, prune=True, max_days=int(s.get("max_job_age_days", 60)), log=_log)
            if v_res.get("pruned"):
                _log(f"Link check: pruned {v_res['pruned']} broken/expired candidates")
            invalid_ids = {d["id"] for d in v_res["details"]}
            cands = [c for c in cands if c["id"] not in invalid_ids]

        # rotate the agents so Claude, Codex/Astra and Gemini each review jobs
        if review and cands and db.master_resume():
            st = ai.status()
            avail = [a for a in ["claude_cli", "codex", "gemini", "anthropic_api"] if st[a]["ready"]]
            fam_seen, rot = set(), []
            fixed = ai.route("review")  # routes.review = an agent name pins reviews to it; "rotate" spreads them
            if fixed:
                avail = [fixed] if fixed in avail else avail[:1]
            for a in avail:  # one agent per family
                fam = "claude" if a in ("claude_cli", "anthropic_api") else a
                if fam not in fam_seen:
                    fam_seen.add(fam)
                    rot.append(a)
            cycle = itertools.cycle(rot or [None])
            for j in cands[: s["ai_review_top_n"]]:
                agent = next(cycle)
                if not agent or not ai.status()[agent]["ready"]:
                    continue
                try:
                    v = coach.review_job(j, agent=agent)
                    if v.get("agent") != agent:
                        _log(f"  ({agent} unavailable, {v.get('agent')} stepped in)")
                    db.execute("UPDATE jobs SET ai_verdict=? WHERE id=?", (json.dumps(v), j["id"]))
                    j["ai_verdict"] = json.dumps(v)
                    _log(f"  {agent} reviewed: {j['title']} @ {j['company']} -> {v.get('verdict')} {v.get('fit')}")
                except Exception as e:  # noqa: BLE001
                    _log(f"  {agent} review failed: {str(e)[:160]}")

        rescore_all()  # blend in the fresh agent verdicts
        emailed = 0
        if send_email and cands and emailer.configured():
            for j in cands:
                j["ai"] = json.loads(j.get("ai_verdict") or "{}")
                j["matched_list"] = json.loads(j.get("matched") or "[]")
                j["missing_list"] = json.loads(j.get("missing") or "[]")
            cands.sort(key=lambda j: (j["ai"].get("verdict") == "skip", -(j["ai"].get("fit") or j["score"])))
            try:
                to = emailer.send(f"🎯 {len(cands)} new job matches for you",
                                  emailer.jobs_html(cands, f"{len(cands)} new roles matched your profile."))
                db.execute(f"UPDATE jobs SET alerted=1 WHERE id IN ({','.join('?'*len(cands))})",
                           [j["id"] for j in cands])
                emailed = len(cands)
                _log(f"Emailed {emailed} matches to {to}")
            except Exception as e:  # noqa: BLE001
                _log(f"Email failed: {e}")
        elif send_email and not emailer.configured():
            _log("Email not configured – skipping alert (set SMTP_USER/SMTP_PASSWORD in .env)")

        if send_email:
            deadline_reminders()
        if s.get("apply_mode") == "email_auto":
            from . import apply
            apply.send_due(_log)  # queued application emails, within the daily limit
        summary = f"{len(jobs)} jobs + {len(opps)} opportunities fetched, {new} new, {len(cands)} matches, {emailed} emailed"
        db.log_run("scan", summary, True, started)
        STATE["last"] = summary
        _log("Done: " + summary)
        return {"fetched": len(jobs), "new": new, "matches": len(cands), "emailed": emailed,
                "errors": errors}
    except Exception as e:  # noqa: BLE001
        db.log_run("scan", str(e), False, started)
        _log(f"Scan failed: {e}")
        raise
    finally:
        STATE["running"] = False


def deadline_reminders():
    """Email items you're tracking whose deadline/next step is 7 or 1 days away (once each)."""
    if not emailer.configured():
        return 0
    today = date.today()
    due = []
    rows = db.rows("SELECT * FROM jobs WHERE (deadline!='' OR next_date!='') AND status NOT IN ('rejected','archived')"
                   " AND (status!='new' OR score>=70)")
    for j in rows:
        for field, label in (("deadline", "Deadline"), ("next_date", j.get("next_action") or "Next step")):
            d = j.get(field)
            if not d:
                continue
            try:
                days = (date.fromisoformat(d) - today).days
            except ValueError:
                continue
            tag = f"{field}:{d}:{'1' if days <= 1 else '7'}"
            if 0 <= days <= 7 and tag not in (j.get("reminded") or ""):
                due.append((days, label, j, tag))
    for e in db.rows("SELECT * FROM events WHERE done=0"):
        try:
            days = (date.fromisoformat(e["date"]) - today).days
        except ValueError:
            continue
        if days in (0, 1, 7):
            due.append((days, e["kind"].title(), {"title": e["title"], "company": e["notes"], "url": "", "id": None}, None))
    if not due:
        return 0
    due.sort(key=lambda x: x[0])
    rows_html = "".join(
        f"<tr><td style='padding:8px;border-bottom:1px solid #eee'><b style='color:{'#b91c1c' if d <= 1 else '#b45309'}'>"
        f"{'TODAY' if d == 0 else f'in {d} day' + ('s' if d > 1 else '')}</b></td><td style='padding:8px;border-bottom:1px solid #eee'>"
        f"{emailer._e(label)}: <a href='{emailer._e(j.get('url'))}'>{emailer._e(j['title'])}</a> · {emailer._e(j.get('company'))}</td></tr>"
        for d, label, j, _ in due)
    emailer.send(f"⏰ {len(due)} deadline(s) coming up",
                 f"<div style='font-family:-apple-system,Arial'><h2>⏰ Upcoming deadlines</h2><table>{rows_html}</table></div>")
    for _, _, j, tag in due:
        if tag and j.get("id"):
            db.execute("UPDATE jobs SET reminded = reminded || ? WHERE id=?", (tag + ";", j["id"]))
    _log(f"Sent {len(due)} deadline reminders")
    return len(due)


def weekly_top5_email():
    text, agent = coach.weekly_top5()
    if emailer.configured():
        emailer.send("🎯 Your top 5 moves this week", emailer.md_html("Top 5 moves this week", text), text)
    db.log_run("weekly_top5", f"by {agent}")
    return text


def weekly_coaching_email():
    """Weekly: skill-gap analysis + council development plan, emailed."""
    text, agent = coach.dev_plan(weeks=4, use_council=True)
    if emailer.configured():
        emailer.send("📈 Your weekly career development plan", emailer.md_html("Weekly plan", text), text)
    db.log_run("weekly_plan", f"plan by {agent}")
    return text
