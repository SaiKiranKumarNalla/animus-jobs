"""Game layer: XP, levels, daily quests, streaks and achievements — all *derived* from real job-search actions
already stored in the database (swipes, saves, applications, verifications, documents, practice), so nothing can
drift out of sync and there is nothing to farm except actual progress."""
import json
import math
import time
from datetime import date, datetime, timedelta

from . import ai, db

XP = {"swipe": 2, "like": 5, "super": 8, "applied": 50, "interview": 150, "offer": 500, "verified": 3,
      "template": 10, "document": 5, "mock_answer": 10, "skill": 15}
RANKS = ["Recruit", "Scout", "Tracker", "Operative", "Specialist", "Strategist", "Vanguard", "Master", "Legend"]


def _day(ts):
    return datetime.fromtimestamp(ts).date().isoformat() if ts else ""


def _events():
    """[(date, kind)] for every XP-earning action."""
    ev = []
    for r in db.rows("SELECT status, applied_at, extra FROM jobs WHERE extra LIKE '%swiped_at%' OR extra LIKE '%verified%' "
                     "OR status IN ('applied','interview','offer') OR applied_at != ''"):
        x = json.loads(r["extra"] or "{}")
        if x.get("swiped_at"):
            d = _day(x["swiped_at"])
            ev.append((d, "swipe"))
            if x.get("swipe") in ("like", "super"):
                ev.append((d, x["swipe"]))
        v = x.get("verified") or {}
        if v.get("ts"):
            ev.append((_day(v["ts"]), "verified"))
        if r["applied_at"]:
            ev.append((r["applied_at"][:10], "applied"))
        if r["status"] in ("interview", "offer"):
            ev.append((r["applied_at"][:10] or date.today().isoformat(), r["status"]))
    for r in db.rows("SELECT created FROM documents"):
        ev.append((_day(r["created"]), "document"))
    try:
        for r in db.rows("SELECT created FROM templates"):
            ev.append((_day(r["created"]), "template"))
    except Exception:  # noqa: BLE001 — table appears on first template
        pass
    for r in db.rows("SELECT transcript, created FROM mock"):
        n = sum(1 for t in json.loads(r["transcript"] or "[]") if t.get("role") == "candidate")
        ev += [(_day(r["created"]), "mock_answer")] * n
    for r in db.rows("SELECT ts FROM skill_history"):
        ev.append((_day(r["ts"]), "skill"))
    return [e for e in ev if e[0]]


def _level(xp):
    lvl = int((math.sqrt(1 + 8 * xp / 100) - 1) / 2) + 1          # 100, 300, 600, 1000 … XP per level
    lo, hi = 100 * (lvl - 1) * lvl // 2, 100 * lvl * (lvl + 1) // 2
    return lvl, lo, hi


def quests(ev, today):
    c = {}
    for d, k in ev:
        if d == today:
            c[k] = c.get(k, 0) + 1
    q = [("Triage", "Swipe 20 cards", c.get("swipe", 0), 20, 40),
         ("Collector", "Save or star 3 opportunities", c.get("like", 0) + c.get("super", 0), 3, 30),
         ("Trust but verify", "Verify 2 links with AI", c.get("verified", 0), 2, 20),
         ("Strike", "Apply to 1 opportunity", c.get("applied", 0), 1, 60),
         ("Train", "Answer 3 mock-interview questions or rate a skill", c.get("mock_answer", 0) + c.get("skill", 0), 3, 30)]
    return [{"name": n, "goal": g, "progress": min(p, t), "target": t, "xp": x, "done": p >= t} for n, g, p, t, x in q]


def streak(ev, today):
    days = {d for d, _ in ev}
    cur, n = date.fromisoformat(today), 0
    if today not in days:
        cur -= timedelta(days=1)  # streak survives until the end of today
    while cur.isoformat() in days:
        n += 1
        cur -= timedelta(days=1)
    return n


def achievements(ev, counts):
    tot = {}
    for _, k in ev:
        tot[k] = tot.get(k, 0) + 1
    A = [("First contact", "Make your first swipe", tot.get("swipe", 0) >= 1),
         ("Centurion", "Swipe 100 cards", tot.get("swipe", 0) >= 100),
         ("First strike", "Send your first application", tot.get("applied", 0) >= 1),
         ("Through the gate", "Land an interview", tot.get("interview", 0) >= 1),
         ("Endgame", "Receive an offer", tot.get("offer", 0) >= 1),
         ("Truth seeker", "Verify 10 links", tot.get("verified", 0) >= 10),
         ("Cartographer", "Add 3 template jobs", tot.get("template", 0) >= 3),
         ("Sparring partner", "Answer 10 mock-interview questions", tot.get("mock_answer", 0) >= 10),
         ("Legendary find", "Save a legendary opportunity", counts.get("legendary_saved", 0) >= 1),
         ("Week warrior", "Keep a 7-day streak", counts.get("streak", 0) >= 7)]
    return [{"name": n, "desc": d, "unlocked": bool(u)} for n, d, u in A]


def energy():
    """Remaining AI 'energy' per agent: daily budget left (or 'unlimited'), cooldowns shown as empty."""
    out = {}
    for k, v in ai.status().items():
        if k == "anthropic_api" and not v.get("ready"):
            continue
        used, budget = (v.get("usage") or {}).get("calls", 0), v.get("budget") or 0
        pct = 0 if not v.get("ready") else (100 if not budget else max(0, round(100 * (1 - used / budget))))
        out[k] = {"pct": pct, "used": used, "budget": budget, "state": v.get("state"), "detail": v.get("detail", "")[:120]}
    return out


def state():
    ev = _events()
    today = date.today().isoformat()
    xp = sum(XP.get(k, 0) for _, k in ev)
    q = quests(ev, today)
    xp += sum(x["xp"] for x in q if x["done"])
    lvl, lo, hi = _level(xp)
    st = streak(ev, today)
    leg = db.one("SELECT COUNT(*) n FROM jobs WHERE status IN ('saved','applying','applied','interview','offer') "
                 "AND json_extract(extra,'$.rarity')='legendary'")["n"]
    return {"xp": xp, "level": lvl, "rank": RANKS[min(lvl - 1, len(RANKS) - 1)], "level_from": lo, "level_to": hi,
            "today_xp": sum(XP.get(k, 0) for d, k in ev if d == today) + sum(x["xp"] for x in q if x["done"]),
            "quests": q, "streak": st, "achievements": achievements(ev, {"legendary_saved": leg, "streak": st}),
            "energy": energy(), "ts": time.time()}
