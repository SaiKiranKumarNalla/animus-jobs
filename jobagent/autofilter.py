"""Automatic filtering: keeps the feed small and current.

Every rule ARCHIVES (never deletes) and records why in extra.archived_reason, so nothing is lost and
archived IDs are never re-imported. Anything you engaged with — saved/applied/interview/offer, notes,
an applied date, a 👍 or a right-swipe — is never touched.
"""
import json
import re
import time
from datetime import date

from . import db
from .config import get_settings

ENGAGED_STATUSES = ("saved", "applying", "applied", "interview", "offer")
GENDER = r"\(?\b(h/f|f/h|m/f|f/m|m/f/d|w/m/d|m/w/d|x/f/m|f/m/x|m/f/x|all genders|hf|fh)\b\)?"
LEGAL = r"\b(gmbh|sas|sasu|sa|sarl|inc|ltd|llc|bv|ag|plc|s\.a\.|co\.|corp|limited|group|groupe)\b\.?"


def engaged(j, extra=None):
    extra = extra if extra is not None else json.loads(j.get("extra") or "{}")
    return (j.get("status") in ENGAGED_STATUSES or bool((j.get("notes") or "").strip())
            or bool(j.get("applied_at")) or extra.get("feedback") == "up"
            or extra.get("swipe") in ("like", "super"))


def norm_title(t, company=""):
    t = (t or "").lower()
    t = re.sub(GENDER, " ", t)
    t = re.sub(r"\([^)]*\)", " ", t)                       # (Paris), (x/f/m), (CDI)…
    toks = set(re.sub(r"[^a-z0-9à-ü ]+", " ", t).split())   # years stay: events differ by year
    comp = set(re.sub(r"[^a-z0-9à-ü ]+", " ", (company or "").lower()).split())
    rest = toks - comp                                       # "Barco – Internship X" → "internship x"
    return frozenset(rest if len(rest) >= 3 else toks)       # never reduce a title to "congress 2027"


def norm_company(c):
    c = (c or "").lower()
    c = re.sub(r"\([^)]*\)", " ", c)
    c = re.sub(LEGAL, " ", c)
    return re.sub(r"[^a-z0-9]+", "", c)


def norm_url(u):
    u = (u or "").lower()
    u = re.sub(r"https?://(www\.)?", "", u).split("#")[0]
    u = re.sub(r"[?&](utm_[^=&]+|ref|refid|trk|trackingid|source|src)=[^&]*", "", u)
    return u.split("?")[0].rstrip("/")


def _similar(ta, tb):
    if ta == tb:
        return bool(ta)
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) >= 0.85


def _priority(j, extra):
    p = 1000 if engaged(j, extra) else 0
    p += 300 if j.get("ai_verdict") else 0
    p += 100 if (extra.get("link_check") or {}).get("valid") else 0
    return p + (j.get("score") or 0)


def merge_duplicates(rows, log=print, dry=False):
    """Near-duplicate merge within the same organisation (or same canonical URL; events by title+year)."""
    archived = []
    groups = {}
    for j in rows:
        extra = json.loads(j.get("extra") or "{}")
        j["_x"] = extra
        key = norm_company(j["company"]) if j["kind"] not in ("event", "conference", "hackathon", "trend") else "_ev"
        groups.setdefault(key, []).append(j)
    by_url = {}
    for key, items in groups.items():
        items.sort(key=lambda j: -_priority(j, j["_x"]))
        kept = []
        for j in items:
            nt = norm_title(j["title"], "" if key == "_ev" else j["company"])
            nu = norm_url(j["url"])
            dup_of = None
            if nu and len(nu) > 20 and nu in by_url:
                dup_of = by_url[nu]
            else:
                # title matching only within a known organisation (or among events, by title + year)
                dup_of = next((k for k in kept if key and _similar(nt, k["_nt"])), None)
            if dup_of is not None and not engaged(j, j["_x"]):
                dx = dup_of["_x"]
                also = dx.setdefault("also_on", [])
                if j["url"] not in also and j["url"] != dup_of["url"]:
                    also.append(j["url"])
                dup_of["_dirty"] = True
                archived.append((j["id"], f"duplicate of {dup_of['id']}", j["_x"]))
            else:
                j["_nt"] = nt
                kept.append(j)
                if nu:
                    by_url.setdefault(nu, j)
    if dry:
        return archived
    with db.db() as con:
        for items in groups.values():
            for j in items:
                if j.get("_dirty"):
                    con.execute("UPDATE jobs SET extra=? WHERE id=?", (json.dumps(j["_x"]), j["id"]))
    return archived


def run(log=print, check_links=False, dry=False):
    """Apply every rule. Returns counts per reason."""
    from . import verifier
    s = get_settings()
    now, today = time.time(), date.today().isoformat()
    rows = db.rows("SELECT id,title,company,url,kind,status,notes,applied_at,deadline,found_at,score,"
                   "ai_verdict,extra,categories FROM jobs WHERE status NOT IN ('archived','rejected')")
    out = []  # (id, reason, extra)
    keep_days = {"trend": s.get("keep_trends_days", 10), "intel": s.get("keep_intel_days", 21)}
    max_age = s.get("max_job_age_days", 45)
    low = s.get("auto_archive_below", 30)
    gems = set(s.get("priority_lanes", []))
    for j in rows:
        x = json.loads(j["extra"] or "{}")
        if engaged(j, x):
            continue
        age = (now - (j["found_at"] or now)) / 86400
        cats = set(json.loads(j["categories"] or "[]"))
        dl = (j["deadline"] or "")[:10]
        if dl and dl < today:
            out.append((j["id"], "deadline/event date passed", x))
        elif j["kind"] in keep_days and age > keep_days[j["kind"]]:
            out.append((j["id"], f"{j['kind']} older than {keep_days[j['kind']]} days", x))
        elif j["status"] == "new" and age > max_age and j["kind"] not in ("collaborator",):
            out.append((j["id"], f"untouched for {max_age}+ days", x))
        elif j["status"] == "new" and (j["score"] or 0) < low and age > 7 and not (cats & gems):
            out.append((j["id"], f"score below {low} after a week", x))
        elif x.get("swipe") == "nope":
            out.append((j["id"], "swiped left", x))
        else:
            gen, why = verifier.generic_for_kind(j["url"], j["kind"])
            if gen:
                out.append((j["id"], f"generic link: {why}", x))
    done = {i for i, _, _ in out}
    remaining = [j for j in rows if j["id"] not in done]
    out += merge_duplicates(remaining, log, dry)
    counts = {}
    for _, reason, _ in out:
        k = reason.split(":")[0].split(" of ")[0]
        counts[k] = counts.get(k, 0) + 1
    if dry:
        return {"archived": 0, "would_archive": len(out), "by_reason": counts}
    with db.db() as con:
        for jid, reason, x in out:
            x["archived_reason"], x["archived_at"] = reason, now
            con.execute("UPDATE jobs SET status='archived', extra=? WHERE id=?", (json.dumps(x), jid))
    if check_links:
        fresh = db.rows("SELECT * FROM jobs WHERE status='new' AND found_at > ? AND extra NOT LIKE '%link_check%'",
                        (now - 3 * 86400,))
        if fresh:
            r = verifier.verify_jobs_batch(fresh, prune=True, max_days=max_age, log=log)
            counts["broken link"] = counts.get("broken link", 0) + r.get("pruned", 0)
    total = sum(counts.values())
    if total:
        log(f"Auto-filter archived {total}: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    return {"archived": total, "by_reason": counts}
