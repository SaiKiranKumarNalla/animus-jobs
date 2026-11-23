"""Non-job opportunities: hackathons, funding calls, fellowships, collaborators, and the AI radar."""
import json
import re
import time
from collections import defaultdict
from datetime import date, datetime

import httpx

from . import ai, db, verifier
from .config import DATA
from .sources import UA, _job, clean

TODAY = lambda: date.today().isoformat()  # noqa: E731


def _date(s):
    """Best-effort date parse -> YYYY-MM-DD ('' if unknown)."""
    if not s:
        return ""
    s = str(s)
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return m.group(0)
    for fmt in ("%b %d, %Y", "%d %B %Y", "%B %d, %Y", "%d %b %Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date().isoformat()
        except ValueError:
            pass
    return ""


# ---- Devpost hackathons ------------------------------------------------------------

def devpost(query):
    d = httpx.get("https://devpost.com/api/hackathons", headers=UA, timeout=30,
                  params={"search": query, "status[]": ["upcoming", "open"], "order_by": "deadline"}).json()
    out = []
    for h in d.get("hackathons", []):
        if (h.get("displayed_location") or {}).get("location", "Online") != "Online":
            continue  # online only
        period = h.get("submission_period_dates", "")
        end = ""
        m = re.search(r"-\s*([A-Za-z]{3} \d{1,2}),? (\d{4})", period)
        if m:
            end = _date(f"{m.group(1)}, {m.group(2)}")
        prize = re.sub(r"<[^>]+>", "", h.get("prize_amount", ""))
        themes = [t["name"] for t in h.get("themes", [])]
        j = _job("devpost", h["id"], h["title"].strip(), h.get("organization_name") or "Devpost",
                 h.get("displayed_location", {}).get("location", "Online"), h["url"],
                 f"Hackathon. Themes: {', '.join(themes)}. Prizes: {prize}. Submission: {period}. "
                 f"{h.get('time_left_to_submission', '')}", h.get("displayed_location", {}).get("location") == "Online",
                 prize, themes, period)
        j.update(kind="hackathon", deadline=end)
        out.append(j)
    return out


# ---- EU Funding & Tenders portal -------------------------------------------------------

EU_STATUS_OPEN, EU_STATUS_FORTHCOMING = "31094501", "31094502"


def eu_funding(text, kind="funding"):
    r = httpx.post(
        "https://api.tech.ec.europa.eu/search-api/prod/rest/search",
        params={"apiKey": "SEDIA", "text": text, "pageSize": 30, "pageNumber": 1},
        headers=UA, timeout=40,
        files={"query": ("blob", json.dumps({"bool": {"must": [
            {"terms": {"type": ["1", "2", "8"]}},
            {"terms": {"status": [EU_STATUS_OPEN, EU_STATUS_FORTHCOMING]}}]}}), "application/json"),
            "languages": ("blob", json.dumps(["en"]), "application/json")})
    r.raise_for_status()
    out = []
    for x in r.json().get("results", []):
        m = x.get("metadata", {})
        first = lambda k: (m.get(k) or [""])[0]  # noqa: E731
        title = first("title") or x.get("summary", "")[:120]
        ident = first("identifier")
        deadline = _date(first("deadlineDate"))
        if deadline and deadline < TODAY():
            continue
        action = first("typesOfAction")
        k = kind
        if "MSCA" in ident or "fellowship" in title.lower():
            k = "fellowship"
        elif "EIC" in ident or "accelerator" in title.lower():
            k = "startup_funding"
        j = _job("eu-funding", ident or x.get("reference"), f"{title}", "European Commission",
                 "Europe", x.get("url"), f"{ident} · {action} · Call: {first('callTitle')}\n\n{clean(x.get('content') or x.get('summary') or '')[:4000]}",
                 False, "", [action], first("startDate"))
        j.update(kind=k, deadline=deadline, extra={"identifier": ident, "status": first("status")})
        out.append(j)
    return out


# ---- OpenAlex: postdoc collaborators (senior authors at European institutions) -------------

EUROPE = ["FR", "DE", "NL", "BE", "CH", "GB", "IE", "AT", "IT", "ES", "PT", "DK", "SE", "NO", "FI", "PL", "CZ",
          "HU", "GR", "LU", "SI", "HR", "EE", "LT", "LV", "SK", "RO", "IS", "CY", "MT"]


def collaborators(topic, since="2023-06-01", top=12, countries=None):
    countries = countries or EUROPE
    d = httpx.get("https://api.openalex.org/works", timeout=40, params={
        "search": topic, "per-page": 100,
        "filter": f"from_publication_date:{since},institutions.country_code:{'|'.join(c.lower() for c in countries)}",
        "select": "title,authorships,publication_year,doi,cited_by_count,id"}).json()
    people = defaultdict(lambda: {"papers": [], "cites": 0, "inst": "", "country": "", "orcid": "", "id": "",
                                  "senior": 0})
    for w in d.get("results", []):
        for a in w.get("authorships", []):
            au = a.get("author", {})
            insts = a.get("institutions") or []
            cc = (insts[0].get("country_code") or "") if insts else ""
            if not au.get("id") or cc.upper() not in countries:
                continue
            senior = a.get("author_position") == "last" or a.get("is_corresponding")
            if not senior:
                continue  # postdoc hosts are usually last/corresponding authors (PIs)
            p = people[au["display_name"]]
            p["papers"].append(f"{w['title']} ({w.get('publication_year')})" + (f" doi:{w['doi']}" if w.get("doi") else ""))
            p["cites"] += w.get("cited_by_count", 0)
            p["senior"] += 1
            p["id"], p["orcid"] = au["id"], au.get("orcid") or ""
            p["inst"], p["country"] = insts[0].get("display_name", ""), cc.upper()
    ranked = sorted(people.items(), key=lambda kv: (kv[1]["senior"], kv[1]["cites"]), reverse=True)[:top]
    out = []
    for name, p in ranked:
        j = _job("openalex", p["id"], name, p["inst"] or "Independent", p["country"],
                 p["orcid"] or p["id"].replace("https://openalex.org/", "https://openalex.org/authors/"),
                 f"Potential postdoc host / collaborator (senior author) on '{topic}' at {p['inst']}. "
                 f"{len(p['papers'])} recent papers as PI, {p['cites']} citations.\n\nRecent papers:\n"
                 + "\n".join("• " + t for t in p["papers"][:6]), False, "", [topic])
        j.update(kind="collaborator", extra={"topic": topic, "papers": len(p["papers"]), "country": p["country"],
                                             "paper_titles": p["papers"][:4]})
        out.append(j)
    return out


# ---- AI radar: Claude (or Codex as fallback) searches the web for what no API covers ----------

# (category, kind, what to search for)
ACADEMIC_LANES = {"collab", "fellowship", "indiv_funding", "conference"}
COMMUNITY_LANES = {"hackathon", "events"}


def lanes():
    """Radar lanes for the active field pack, minus disabled modules (academia / community)."""
    from . import packs
    from .config import get_settings
    mods = get_settings().get("modules") or {}
    off = (set() if mods.get("academia") else ACADEMIC_LANES) | (set() if mods.get("community") else COMMUNITY_LANES)
    return [l for l in packs.radar_lanes() if l[0] not in off]


RADAR_STATE = DATA / "radar_state.json"


def radar_next(n=2, pinned=()):
    """Pinned lanes run every scan; the remaining lanes rotate n at a time (n <= 0 means every lane)."""
    if n <= 0:
        return lanes()
    st = json.loads(RADAR_STATE.read_text()) if RADAR_STATE.exists() else {"i": 0}
    all_lanes = lanes()
    fixed = [r for r in all_lanes if r[0] in pinned]
    rest = [r for r in all_lanes if r[0] not in pinned]
    picks = [rest[(st["i"] + k) % len(rest)] for k in range(min(n, len(rest)))] if rest else []
    st["i"] = (st["i"] + n) % max(len(rest), 1)
    RADAR_STATE.write_text(json.dumps(st))
    return fixed + picks


WEB_AGENTS = ["claude_cli", "codex"]


def _web_fn(name):
    if name == "gemini":
        return ai.ask_gemini_web
    if name == "claude_cli":
        return ai.ask_claude_web
    if name == "codex":
        return ai.ask_codex_web
    return None


def web_ask(prompt, prefer=None):
    """Only trusted reviewers may perform autonomous opportunity searches."""
    if prefer == "gemini":
        raise RuntimeError("Gemini autonomous search is disabled; use Claude or Codex.")
    order = [a for a in WEB_AGENTS if a in ai.AGENTS]
    pref = prefer or ai.route("radar")
    if pref in order:
        order.remove(pref)
        order.insert(0, pref)
    errors = []
    st = ai.status()
    for name in order:
        if not st[name]["ready"]:
            errors.append(f"{name}: {st[name]['detail'][:120]}")
            continue
        try:
            fn = _web_fn(name)
            if not fn:
                continue
            return ai.call(name, prompt, fn=fn), name
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {str(e)[:160]}")
    raise RuntimeError("No web-capable agent available: " + " | ".join(errors))


def radar(cat_id, kind, what, profile="", settings=None, prefer=None):
    settings = settings or {}
    n_items = int(settings.get("radar_max_items", 20))
    from . import packs
    what = what.replace("{companies}", ", ".join(packs.active().get("intel_companies", [])))
    if kind == "trend":
        schema = '{"title": "trending topic", "org": "who is driving it", "location": "Online", "url": "source", ' \
                 '"date": "YYYY-MM-DD", "summary": "why it is hot (2 lines)", "angle": "post angle for me"}'
    elif kind == "event":
        schema = '{"title": "event name", "org": "organiser", "location": "Online or city, country", "url": "registration page", ' \
                 '"deadline": "event date YYYY-MM-DD", "summary": "type (webinar/job fair/meetup/conference), time, why attend", ' \
                 '"eligibility": "registration / cost", "amount": ""}'
    elif kind == "intel":
        schema = '{"title": "headline", "org": "company", "location": "city, country", "url": "source article", ' \
                 '"date": "YYYY-MM-DD", "summary": "two lines", "hiring_signal": "what it means for job seekers"}'
    elif kind == "target":
        schema = '{"title": "Company – suggested role to pitch", "org": "...", "location": "city, country", ' \
                 '"url": "careers or contact page", "summary": "why they fit + recent news", ' \
                 '"eligibility": "who to contact (role)", "amount": ""}'
    else:
        schema = '{"title": "...", "org": "...", "location": "city, country or Online", "url": "https://...", ' \
                 '"deadline": "YYYY-MM-DD or empty if rolling", "amount": "funding/salary if known", ' \
                 '"eligibility": "one line", "summary": "two lines on why it fits"}'
    excl = ", ".join(settings.get("excluded_countries", []))
    where = ("Location rule: prioritise Europe and fully-remote items open to candidates based in France"
             + (f"; EXCLUDE anything located in: {excl}" if excl else "") + ".") if kind not in ("intel", "trend") else ""
    prompt = f"""Today is {TODAY()}. Use web search to find up to {n_items} {what}.
Run several different searches (different sites and phrasings) to reach that number; never pad with weak matches.
{where}
Candidate profile: {profile[:700]}
Candidate preferences: {settings.get('preferences', '')[:400]}
CRITICAL LINK & FRESHNESS RULES:
1. ONLY include current, active items (open or posted within the last 30 days). Exclude anything from past years or closed deadlines.
2. The URL MUST point directly to the specific job or call page. NEVER return search query pages (no /jobs/search, no /q-), directory roots, or bare homepages.
3. Every URL will be verified live via HTTP; broken or generic links will be discarded.
Return ONLY a JSON array of objects: {schema}"""
    text, agent_used = web_ask(prompt, prefer)
    m = re.search(r"\[.*\]", text, re.S)
    items = json.loads(m.group(0)) if m else []
    out = []
    max_days = int(settings.get("max_job_age_days", 45))
    for it in items:
        if not it.get("url") or not it.get("title"):
            continue
        dl = _date(it.get("deadline"))
        if dl and dl < TODAY():
            continue
        # Verify URL is live, not a generic search/homepage, and not a dead posting
        check = verifier.verify_job(it, check_live=True, max_days=max_days)
        if not check["valid"]:
            continue
        loc = str(it.get("location", ""))
        desc = f"{it.get('summary', '')}"
        if it.get("angle"):
            desc += f"\n\nPost angle: {it['angle']}"
        if it.get("hiring_signal"):
            desc += f"\n\nHiring signal: {it['hiring_signal']}"
        if it.get("eligibility"):
            desc += f"\n\n{'Contact' if kind == 'target' else 'Eligibility'}: {it['eligibility']}"
        if it.get("amount"):
            desc += f"\nAmount: {it['amount']}"
        j = _job("radar", it["url"] + it["title"][:40], it["title"], it.get("org", ""), loc, it["url"], desc,
                 any(w in loc.lower() for w in ("online", "remote")), it.get("amount", ""), [cat_id],
                 it.get("date", ""))
        j.update(kind=kind, deadline=dl, extra={"radar": cat_id, "found_by": agent_used + "+web"})
        out.append(j)
    return out


def run_radar(picks, settings, log=print, agent_pref=None):
    """Run radar lanes in parallel across trusted web-capable agents (Claude, Codex).
    Each agent gets `radar_workers_per_agent` concurrent searches; failures fall back to other agents."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    prof = (db.master_resume() or {}).get("profile", "")
    st = ai.status()
    pref = agent_pref or settings.get("radar_agent") or ai.route("radar")
    if pref and pref in WEB_AGENTS and st.get(pref, {}).get("ready"):
        agents = [pref]
    else:
        agents = [a for a in WEB_AGENTS if st.get(a, {}).get("ready")] or WEB_AGENTS
        if pref and pref in agents:
            agents.remove(pref)
            agents.insert(0, pref)
    per = max(1, int(settings.get("radar_workers_per_agent", 2)))
    items, errors = [], []
    with ThreadPoolExecutor(max_workers=per * len(agents)) as ex:
        futs = {ex.submit(radar, cat_id, kind, what, prof, settings, agents[i % len(agents)]): (cat_id, agents[i % len(agents)])
                for i, (cat_id, kind, what) in enumerate(picks)}
        for f in as_completed(futs):
            cat_id, assigned = futs[f]
            try:
                got = f.result()
                items.extend(got)
                by = {j["extra"].get("found_by", "?") for j in got} or {assigned}
                log(f"  radar {cat_id} [{', '.join(sorted(by))}]: {len(got)}")
            except Exception as e:  # noqa: BLE001
                errors.append(f"radar {cat_id}: {str(e)[:160]}")
                log(f"  radar {cat_id} failed: {str(e)[:120]}")
    return items, errors


def fetch_all(settings, log=print, radar_n=2):
    items, errors = [], []

    def run(name, fn, *a):
        try:
            got = fn(*a)
            items.extend(got)
            log(f"  {name}{a[:1]}: {len(got)}")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}{a[:1]}: {str(e)[:160]}")

    from . import packs
    pk = packs.active()
    mods = settings.get("modules") or {}
    for q in (pk.get("hackathon_queries", []) if mods.get("community") else []):
        run("devpost", devpost, q)
    for q, k in [x for x in pk.get("funding_queries", []) if mods.get("academia") or x[1] == "startup_funding"]:
        run("eu-funding", eu_funding, q, k)
    for topic in (pk.get("collab_topics", []) if mods.get("academia") else []):
        run("openalex", collaborators, topic)
    if radar_n is not None:
        picks = radar_next(radar_n, settings.get("radar_pinned", []))
        got, rerr = run_radar(picks, settings, log, agent_pref=settings.get("radar_agent"))
        items.extend(got)
        errors.extend(rerr)
    # de-duplicate
    seen, uniq = set(), []
    for j in items:
        if j["id"] not in seen:
            seen.add(j["id"])
            uniq.append(j)
    return uniq, errors
