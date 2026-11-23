"""Field packs: everything domain-specific (field lanes, web-radar briefs, search queries, companies).

The code is field-agnostic. A pack says *what* to look for:
  • built-in packs live in jobagent/packs/*.json (e.g. medical_imaging.json),
  • `generate_pack()` asks the AI to write one from the user's CV during setup,
  • the active pack is stored in settings["pack"]; anything missing falls back to GENERIC.
"""
import json
import re
from functools import lru_cache
from pathlib import Path

from .config import get_settings

PACK_DIR = Path(__file__).parent / "packs"

# Universal radar lanes. Placeholders are filled from the active pack + settings.
UNIVERSAL_RADAR = [
    ("collab", "research", "open POSTDOC and research-fellow positions in {region} in {field}: EURAXESS, university and hospital lab pages, Nature Careers, jobs.ac.uk, academicpositions.eu"),
    ("fellowship", "fellowship", "open fellowships (MSCA postdoctoral & COFUND, EMBO, Humboldt, foundation or industry fellowships) for someone with this profile in {field}, in {region}"),
    ("indiv_funding", "funding", "grants, microgrants and prizes an INDIVIDUAL can apply for without an institutional affiliation (Experiment.com, independent-researcher grants, travel grants, foundation grants) in {field}"),
    ("hackathon", "hackathon", "upcoming ONLINE / remote hackathons, datathons and challenges in {field}, plus online AI 'vibe coding' / AI-agent build hackathons (lablab.ai, MLH, Devpost, Kaggle, Hugging Face) – remote participation only"),
    ("local_leadership", "job", "leadership roles in {home_country}, advertised in {local_language} where relevant: co-founder, technical/scientific partner, CTO, CSO, R&D director, head of R&D, first engineer, at startups and SMEs in {field}. Search national job boards, Welcome to the Jungle, LinkedIn public job pages, incubators and founders' co-founder posts. Keep original titles"),
    ("analyst", "job", "open analyst roles related to {field}: market or competitive-intelligence analyst, equity-research or investment analyst, consulting analyst, technology scouting – {region} or remote"),
    ("product", "job", "open product roles in {field}: product specialist, application specialist/scientist, product manager, product owner – {region} or remote, at companies like {companies}"),
    ("exec", "job", "open CSO, CTO, Chief Scientific/Technical Officer, VP R&D or Head of R&D roles at startups and scale-ups in {field} ({region} or remote)"),
    ("founding", "job", "startups recruiting a FOUNDING engineer, founding scientist or technical co-founder in {field} (YC Work at a Startup, Wellfound, Welcome to the Jungle, EU-Startups, founder posts)"),
    ("eir", "job", "Entrepreneur in Residence / EIR / venture builder / venture scientist / founder-in-residence roles in {field} ({region} or remote)"),
    ("internship", "internship", "open INTERNSHIPS, research stays and traineeships in {region} in {field}, including industry R&D internships and EU traineeships"),
    ("vc", "job", "open jobs in venture capital focused on {field} (analyst, associate, venture partner, scout, EIR) in {region} or remote"),
    ("startup_funding", "startup_funding", "startup and innovation funding calls for an early-stage venture in {field} in {home_country} or the EU (national innovation agencies, EIC Accelerator/Pathfinder, accelerators, incubators)"),
    ("field_jobs", "job", "open industry jobs in {field} matching this profile, at companies like {companies}, in {region} or remote"),
    ("local_jobs", "job", "job vacancies in {home_country} written in {local_language} for this profile in {field}; prefer the national job boards; keep original titles"),
    ("remote_jobs", "job", "FULLY REMOTE or hybrid jobs open to candidates based in {home_country} in {field}"),
    ("targets", "target", "SPONTANEOUS-APPLICATION TARGETS: companies, startups and labs in {region} (no matching job posted) where this candidate's skills in {field} would be valuable – recently funded or expanding. Give the careers/contact URL"),
    ("conference", "conference", "upcoming CONFERENCES in the next 12 months in {field}, with their ABSTRACT SUBMISSION deadlines ({conferences}). Put the abstract deadline in 'deadline' and the event dates + city in 'summary'"),
    ("events", "event", "upcoming EVENTS in the next 60 days useful to a job seeker in {field} in {region}: free webinars, virtual and in-person job fairs, career days, meetups and networking events. Put the EVENT date in 'deadline' and the type + online/city in 'summary'"),
    ("trends", "trend", "WHAT'S HOT this week on LinkedIn and in industry news for {field}: trending discussions, announcements, debates, regulations, big papers. For each give the topic, why it is trending, a source URL and a suggested post angle"),
    ("intel", "intel", "COMPANY INTELLIGENCE from the last 30 days: funding rounds, acquisitions, new sites, product launches, approvals and hiring announcements at: {companies}. Report hiring signals"),
]

GENERIC = {
    "id": "generic", "name": "Generic (fill from your CV)", "field": "your field", "home_country": "your country",
    "region": "Europe", "local_language": "English", "lanes": [], "core_lanes": [], "labels": {}, "domain_words": [],
    "radar": {}, "radar_order": [lid for lid, _, _ in UNIVERSAL_RADAR], "hackathon_queries": ["AI agents", "vibe coding"],
    "funding_queries": [["MSCA postdoctoral fellowships", "fellowship"], ["EIC Accelerator", "startup_funding"]],
    "collab_topics": [], "local_queries": [], "leadership_queries": ["CTO", "chief technology officer", "head of R&D", "VP engineering", "co-founder"],
    "intel_companies": [], "conferences": [],
}


@lru_cache(maxsize=None)
def builtin(pack_id):
    p = PACK_DIR / f"{pack_id}.json"
    return json.loads(p.read_text()) if p.exists() else None


def builtins():
    return [{"id": p.stem, "name": json.loads(p.read_text()).get("name", p.stem)} for p in sorted(PACK_DIR.glob("*.json"))]


def active():
    """The current user's pack: settings["pack"] (a dict, or the id of a built-in) over GENERIC."""
    s = get_settings()
    raw = s.get("pack") or {}
    if isinstance(raw, str):
        raw = builtin(raw) or {}
    pack = {**GENERIC, **raw}
    # per-user overrides saved in Config win over the pack
    for k in ("local_queries", "leadership_queries", "intel_companies"):
        legacy = {"local_queries": "french_queries"}.get(k, k)
        if s.get(legacy):
            pack[k] = s[legacy]
    return pack


def _ctx(pack):
    return {"field": pack.get("field", "your field"), "home_country": pack.get("home_country", ""),
            "region": pack.get("region", "Europe"), "local_language": pack.get("local_language", "English"),
            "companies": ", ".join(pack.get("intel_companies", [])[:12]) or "leading companies in the field",
            "conferences": ", ".join(pack.get("conferences", [])[:12]) or "the main conferences of the field"}


def radar_lanes(pack=None):
    """[(lane_id, kind, brief)] for the active pack: pack-specific briefs win, universal templates fill the rest."""
    pack = pack or active()
    ctx = _ctx(pack)
    kinds = {lid: k for lid, k, _ in UNIVERSAL_RADAR}
    kinds.update(pack.get("radar_kinds", {}))
    templ = {lid: t for lid, _, t in UNIVERSAL_RADAR}
    out = []
    for lid in pack.get("radar_order") or list(templ):
        brief = pack.get("radar", {}).get(lid) or templ.get(lid)
        if not brief:
            continue
        for k, v in ctx.items():   # plain replace: briefs may legitimately contain other braces
            brief = brief.replace("{" + k + "}", v)
        out.append((lid, kinds.get(lid, "job"), brief))
    return out


def field_lanes(pack=None):
    return (pack or active()).get("lanes", [])


def core_lanes(pack=None):
    pack = pack or active()
    return set(pack.get("core_lanes") or [l["id"] for l in pack.get("lanes", [])])


def label(cat_id, default, pack=None):
    return (pack or active()).get("labels", {}).get(cat_id, default)


PACK_SCHEMA_HINT = """{
 "name": "short pack name", "field": "the candidate's field in a few words",
 "home_country": "...", "region": "e.g. Europe", "local_language": "e.g. French",
 "lanes": [{"id": "snake_case", "label": "Lane label", "glyph": "one symbol", "terms": ["8-15 lowercase keywords incl. local-language terms"]}],
 "domain_words": ["10-20 lowercase words that signal the field (used to keep leadership roles on-topic)"],
 "collab_topics": ["4-6 research topics for finding potential PIs / collaborators"],
 "hackathon_queries": ["4-6 short queries"], "funding_queries": [["query", "funding|fellowship|startup_funding"]],
 "local_queries": ["8-12 search queries in the local language"], "leadership_queries": ["6-10 leadership-title queries"],
 "intel_companies": ["10-18 companies to watch"], "conferences": ["6-12 main conferences"]
}"""


def generate_pack(resume_text, prefs="", agent=None):
    """Ask the AI to build a field pack from a CV (3–6 field lanes, queries, companies, conferences)."""
    from . import ai
    prompt = f"""Build a job-search FIELD PACK for this candidate. Return ONLY JSON matching:
{PACK_SCHEMA_HINT}
Rules: 3–6 lanes specific to the candidate's field (universal lanes like CTO/founding/internships already exist –
do not add them). Use real, well-known companies and conferences. No invented facts about the candidate.
Candidate preferences: {prefs or '(none)'}
CV:
{resume_text[:9000]}"""
    text, used = ai.ask(prompt, agent=agent, task="profile")
    m = re.search(r"\{.*\}", text, re.S)
    data = json.loads(m.group(0)) if m else {}
    lanes = []
    for l in data.get("lanes", [])[:6]:
        lid = re.sub(r"[^a-z0-9_]", "_", str(l.get("id", "")).lower())[:24] or None
        if lid and l.get("terms"):
            lanes.append({"id": lid, "label": str(l.get("label", lid))[:40], "glyph": str(l.get("glyph", "◆"))[:2],
                          "terms": [str(t).lower() for t in l["terms"]][:20]})
    data["lanes"] = lanes
    data["id"], data["_generated_by"] = "custom", used
    data["core_lanes"] = [l["id"] for l in lanes]
    return {k: v for k, v in data.items() if k in GENERIC or k in ("id", "_generated_by")}
