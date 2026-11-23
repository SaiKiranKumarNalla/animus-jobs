"""Job sources: free public APIs, company ATS boards and search-engine (X-ray) links."""
import hashlib
import html
import os
import re
import urllib.parse
from datetime import datetime, timezone

import httpx

from . import config  # noqa: F401  (loads .env so API keys are available)

UA = {"User-Agent": "Mozilla/5.0 (JobAgent personal job search; contact via local user)"}


def clean(text):
    text = re.sub(r"<(br|/p|/li|/h\d)[^>]*>", "\n", text or "", flags=re.I)
    text = re.sub(r"<li[^>]*>", "• ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def _id(source, key):
    return f"{source}:{hashlib.sha1(str(key).encode()).hexdigest()[:16]}"


def _job(source, key, title, company, location, url, desc, remote=False, salary="",
         tags=None, posted=""):
    return {"id": _id(source, key), "source": source, "title": (title or "").strip(),
            "company": (company or "").strip(), "location": (location or "").strip(),
            "url": url, "description": clean(desc)[:20000], "remote": remote,
            "salary": salary or "", "tags": tags or [], "posted_at": str(posted or "")}


def _get(url, **kw):
    r = httpx.get(url, headers=UA, timeout=30, follow_redirects=True, **kw)
    r.raise_for_status()
    return r.json()


# ---- sources -----------------------------------------------------------------

def remotive(query):
    d = _get("https://remotive.com/api/remote-jobs", params={"search": query, "limit": 50})
    return [_job("remotive", j["id"], j["title"], j["company_name"],
                 j.get("candidate_required_location", "Remote"), j["url"], j.get("description"),
                 True, j.get("salary"), j.get("tags"), j.get("publication_date"))
            for j in d.get("jobs", [])]


def arbeitnow(query):
    out = []
    for page in (1, 2, 3):
        d = _get("https://www.arbeitnow.com/api/job-board-api", params={"page": page})
        for j in d.get("data", []):
            posted = datetime.fromtimestamp(j.get("created_at", 0), timezone.utc).date()
            out.append(_job("arbeitnow", j["slug"], j["title"], j["company_name"], j.get("location"),
                            j["url"], j.get("description"), j.get("remote"), "", j.get("tags"), posted))
    return out


def remoteok(query):
    tag = urllib.parse.quote(query.split()[0].lower()) if query else ""
    d = _get(f"https://remoteok.com/api?tag={tag}" if tag else "https://remoteok.com/api")
    out = []
    for j in d[1:] if isinstance(d, list) else []:
        sal = f"${j['salary_min']:,}-{j['salary_max']:,}" if j.get("salary_min") else ""
        out.append(_job("remoteok", j.get("id"), j.get("position"), j.get("company"),
                        j.get("location") or "Remote", j.get("url"), j.get("description"), True,
                        sal, j.get("tags"), j.get("date")))
    return out


def jobicy(query):
    d = _get("https://jobicy.com/api/v2/remote-jobs", params={"count": 50, "tag": query})
    return [_job("jobicy", j["id"], j.get("jobTitle"), j.get("companyName"), j.get("jobGeo"),
                 j.get("url"), j.get("jobDescription"), True,
                 str(j.get("annualSalaryMin") or ""), j.get("jobIndustry"), j.get("pubDate"))
            for j in d.get("jobs", [])]


def themuse(query, location=""):
    params = {"page": 0, "descending": "true"}
    if location:
        params["location"] = location
    d = _get("https://www.themuse.com/api/public/jobs", params=params)
    q = query.lower().split()
    out = []
    for j in d.get("results", []):
        if q and not any(w in j.get("name", "").lower() for w in q):
            continue
        out.append(_job("themuse", j["id"], j["name"], j.get("company", {}).get("name"),
                        ", ".join(l["name"] for l in j.get("locations", [])),
                        j.get("refs", {}).get("landing_page"), j.get("contents"),
                        "Remote" in str(j.get("locations")), "", [], j.get("publication_date")))
    return out


def adzuna(query, location="", country="fr"):
    app_id, key = os.environ.get("ADZUNA_APP_ID"), os.environ.get("ADZUNA_APP_KEY")
    if not (app_id and key):
        return []
    params = {"app_id": app_id, "app_key": key, "what": query, "results_per_page": 50,
              "content-type": "application/json"}
    if location and location.lower() not in ("remote", "europe", "eu"):
        params["where"] = location
    d = _get(f"https://api.adzuna.com/v1/api/jobs/{country}/search/1", params=params)
    out = []
    for j in d.get("results", []):
        sal = f"{int(j['salary_min']):,}-{int(j.get('salary_max') or j['salary_min']):,}" \
            if j.get("salary_min") else ""
        out.append(_job(f"adzuna-{country}", j["id"], j.get("title"),
                        j.get("company", {}).get("display_name"),
                        j.get("location", {}).get("display_name"), j.get("redirect_url"),
                        j.get("description"), False, sal, [], j.get("created")))
    return out


# ---- France Travail (official API, free key from francetravail.io) -----------------------------
_FT_TOKEN = {"value": None, "exp": 0}


def _ft_token():
    import time as _t
    cid, sec = os.environ.get("FRANCE_TRAVAIL_CLIENT_ID"), os.environ.get("FRANCE_TRAVAIL_CLIENT_SECRET")
    if not (cid and sec):
        return None
    if _FT_TOKEN["value"] and _t.time() < _FT_TOKEN["exp"] - 60:
        return _FT_TOKEN["value"]
    url = "https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=%2Fpartenaire"
    last = None
    for scope in ("api_offresdemploiv2 o2dsoffre", "api_offresdemploiv2"):  # scope naming differs between docs
        r = httpx.post(url, data={"grant_type": "client_credentials", "client_id": cid, "client_secret": sec,
                                  "scope": scope}, timeout=30)
        if r.status_code == 200:
            d = r.json()
            _FT_TOKEN.update(value=d["access_token"], exp=_t.time() + int(d.get("expires_in", 1400)))
            return _FT_TOKEN["value"]
        last = f"{r.status_code} {r.text[:160]}"
    raise RuntimeError(f"France Travail auth failed: {last}")


def france_travail(query, days=14):
    """Offres d'emploi v2: every job published in France, including partner sites that allow it."""
    tok = _ft_token()
    if not tok:
        return []
    r = httpx.get("https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search",
                  headers={"Authorization": f"Bearer {tok}", "Accept": "application/json"},
                  params={"motsCles": query, "publieeDepuis": days, "range": "0-149"}, timeout=30)
    if r.status_code == 204:
        return []
    if r.status_code not in (200, 206):
        raise RuntimeError(f"{r.status_code} {r.text[:200]}")
    out = []
    for o in r.json().get("resultats", []):
        origin = o.get("origineOffre") or {}
        url = origin.get("urlOrigine") or f"https://candidat.francetravail.fr/offres/recherche/detail/{o['id']}"
        partner = ", ".join(p.get("nom", "") for p in origin.get("partenaires", []) if p.get("nom"))
        sal = (o.get("salaire") or {}).get("libelle", "")
        desc = o.get("description", "")
        if o.get("typeContratLibelle"):
            desc = f"{o['typeContratLibelle']} · {o.get('dureeTravailLibelle', '')}\n\n{desc}"
        if partner:
            desc += f"\n\nAlso published on: {partner}"
        out.append(_job("france-travail", o["id"], o.get("intitule"), (o.get("entreprise") or {}).get("nom", "") or "Entreprise (anonyme)",
                        (o.get("lieuTravail") or {}).get("libelle", "France"), url, desc, False, sal,
                        [o.get("romeLibelle", ""), o.get("typeContrat", "")], o.get("dateCreation")))
    return out


def greenhouse(slug):
    d = _get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", params={"content": "true"})
    return [_job("greenhouse", j["id"], j["title"], slug, j.get("location", {}).get("name"),
                 j["absolute_url"], html.unescape(j.get("content", "")),
                 "remote" in j.get("location", {}).get("name", "").lower(), "", [], j.get("updated_at"))
            for j in d.get("jobs", [])]


def lever(slug):
    d = _get(f"https://api.lever.co/v0/postings/{slug}", params={"mode": "json"})
    return [_job("lever", j["id"], j["text"], slug, j.get("categories", {}).get("location"),
                 j["hostedUrl"], j.get("descriptionPlain", "") + "\n" + j.get("additionalPlain", ""),
                 j.get("workplaceType") == "remote", "", [], j.get("createdAt"))
            for j in d]


def ashby(slug):
    d = _get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    return [_job("ashby", j["id"], j["title"], slug, j.get("location"), j["jobUrl"],
                 j.get("descriptionHtml", ""), j.get("isRemote"), "", [], j.get("publishedAt"))
            for j in d.get("jobs", [])]


BOARDS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby}


GENERIC = {"engineer", "manager", "senior", "junior", "lead", "specialist", "associate", "staff",
           "principal", "head", "of", "and", "the", "i", "ii", "iii", "intern", "consultant", "&", "-"}


EXEC_TITLE = (r"\b(cto|cso|cmo|chief|co-?founder|cofondateur|founding|vp|vice[- ]president|head of|"
              r"directeur|directrice|director|responsable r&d|responsable scientifique|"
              r"entrepreneur[- ]in[- ]residence|entrepreneur en résidence|eir|venture[- ]builder)\b")


def relevant(job, roles, keywords):
    title = job["title"].lower()
    blob = title + " " + " ".join(map(str, job.get("tags") or [])).lower() + " " + job["description"][:1500].lower()
    role_words = {w for r in roles for w in r.lower().split() if w not in GENERIC and len(w) > 2}
    if any(re.search(rf"\b{re.escape(w)}", title) for w in role_words):
        return True
    from .scoring import translate_fr
    blob = translate_fr(blob)
    if any(re.search(rf"\b{re.escape(w)}", translate_fr(title)) for w in role_words):
        return True
    if re.search(EXEC_TITLE, title):
        return any(w in blob for w in ("medtech", "medical", "imaging", "health", "biotech", "nuclear", "radiolog",
                                       "diagnostic", "pharma", "life science", "santé", "médical"))
    hits = sum(1 for k in keywords if re.search(rf"(?<![a-z0-9]){re.escape(k.lower())}(?![a-z0-9])", blob))
    return hits >= 2


def fetch_all(settings, log=print):
    """Run every source for every target role. Returns (jobs, errors)."""
    from .scoring import expand_terms, simple_roles
    roles = simple_roles(settings.get("target_roles")) or settings.get("keywords")[:3] or ["engineer"]
    locs = [l.split(",")[0].split("/")[0].split("(")[0].strip() for l in settings.get("locations") or [""]]
    keywords = expand_terms(settings.get("keywords", []))
    jobs, errors = [], []

    def run(name, fn, *a):
        try:
            got = fn(*a)
            jobs.extend(got)
            log(f"  {name}{a}: {len(got)}")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}{a}: {e}")

    agg_start = len(jobs)
    run("arbeitnow", arbeitnow, "")
    # job APIs work best with short queries: "Research Scientist Medical Imaging" -> "Research Scientist Medical"
    queries = list(dict.fromkeys(" ".join(r.split()[:3]) for r in roles))
    from . import packs
    pk = packs.active()
    lead = pk.get("leadership_queries", [])
    eir = settings.get("eir_queries", [])
    fr = pk.get("local_queries", [])
    # France: France Travail + Adzuna get the French and leadership queries too
    for q in list(dict.fromkeys(fr + lead + eir + queries)):
        run("france-travail", france_travail, q)
    for c in settings.get("adzuna_countries", ["fr"]):
        for q in list(dict.fromkeys(fr + lead + eir)):
            run("adzuna", adzuna, q, "", c)
    for role in list(dict.fromkeys(queries + [q for q in lead if q.isascii()][:4]
                                  + [q for q in eir if q.isascii()])):
        run("remotive", remotive, role)
        run("remoteok", remoteok, role)
        run("jobicy", jobicy, role)
        for c in settings.get("adzuna_countries", ["fr"]):
            for loc in locs[:3]:
                run("adzuna", adzuna, role, loc, c)
    # Search explicit remote categories for imaging / healthtech
    for rq in ["medical imaging", "image analysis", "biomedical", "simulation", "health ai"]:
        run("remotive", remotive, rq)
        run("jobicy", jobicy, rq)
    run("themuse", themuse, " ".join(queries), locs[0] if locs[0] else "")
    # aggregators return lots of noise: keep only postings relevant to the targets
    jobs[agg_start:] = [j for j in jobs[agg_start:] if relevant(j, roles, keywords)]
    for entry in settings.get("watch_companies", []):
        kind, _, slug = entry.partition(":")
        if kind in BOARDS and slug:
            before = len(jobs)
            run(kind, BOARDS[kind], slug)
            jobs[before:] = [j for j in jobs[before:] if relevant(j, roles, keywords)]
    # de-duplicate by (title, company) and clean URL
    seen, uniq = set(), []
    for j in jobs:
        tk = (j["title"].strip().lower(), j["company"].strip().lower())
        uk = re.sub(r"https?://(www\.)?", "", (j.get("url") or "").lower()).split("?")[0].rstrip("/")
        if j["title"] and j["url"] and tk not in seen and (not uk or uk not in seen):
            seen.add(tk)
            if uk and len(uk) > 15:
                seen.add(uk)
            uniq.append(j)
    return uniq, errors


def xray_links(role, location="", skills=None):
    """Search-engine 'X-ray' queries that surface jobs on ATS boards and job sites."""
    q = f'"{role}"'
    loc = f' "{location}"' if location else ""
    sk = " ".join(f'"{s}"' for s in (skills or [])[:2])
    g = lambda s: "https://www.google.com/search?q=" + urllib.parse.quote(s)  # noqa: E731
    enc = urllib.parse.quote
    return [
        {"label": "Greenhouse boards", "url": g(f"site:boards.greenhouse.io OR site:job-boards.greenhouse.io {q}{loc}")},
        {"label": "Lever boards", "url": g(f"site:jobs.lever.co {q}{loc}")},
        {"label": "Ashby boards", "url": g(f"site:jobs.ashbyhq.com {q}{loc}")},
        {"label": "Workday careers", "url": g(f"site:myworkdayjobs.com {q}{loc}")},
        {"label": "Welcome to the Jungle", "url": g(f"site:welcometothejungle.com {q}{loc}")},
        {"label": "HelloWork", "url": g(f"site:hellowork.com/fr-fr/emplois/ {q}{loc}")},
        {"label": "Skill-targeted", "url": g(f"{q} {sk}{loc} (careers OR jobs) -senior")},
        {"label": "Google Jobs", "url": f"https://www.google.com/search?ibp=htl;jobs&q={enc(role + ' ' + location)}"},
        {"label": "LinkedIn (past week)", "url": f"https://www.linkedin.com/jobs/search/?keywords={enc(role)}&location={enc(location)}&f_TPR=r604800"},
        {"label": "Indeed", "url": f"https://www.indeed.com/jobs?q={enc(role)}&l={enc(location)}&fromage=7"},
        {"label": "Indeed France", "url": f"https://fr.indeed.com/jobs?q={enc(role)}&l={enc(location)}&fromage=7"},
        {"label": "Hiring managers on LinkedIn", "url": g(f'site:linkedin.com/in ("hiring" OR "recruiting") {q}{loc}')},
    ]
