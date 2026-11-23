"""Paths, .env loading and user settings."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _app_home() -> Path:
    """Where a user's data lives (never inside the git repo for new installs).
    JOBAGENT_HOME wins; an existing checkout with data/ keeps working in place; otherwise a per-OS user folder."""
    if os.environ.get("JOBAGENT_HOME"):
        return Path(os.environ["JOBAGENT_HOME"]).expanduser()
    if (ROOT / "data" / "jobagent.db").exists():
        return ROOT  # legacy single-user install
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "JobAgent"
    xdg = os.environ.get("XDG_DATA_HOME")
    return (Path(xdg) / "jobagent") if xdg else Path.home() / ".jobagent"


APP_HOME = _app_home()
DATA = APP_HOME / "data"
LOGS = APP_HOME / "logs"
ENV_PATH = APP_HOME / ".env"
DB_PATH = DATA / "jobagent.db"
SETTINGS_PATH = DATA / "settings.json"
DATA.mkdir(parents=True, exist_ok=True)
LOGS.mkdir(parents=True, exist_ok=True)


def load_env():
    env = ENV_PATH
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()

DEFAULT_SETTINGS = {
    "pack": "",                   # field pack: built-in id (e.g. "medical_imaging") or a generated dict
    "setup_done": False,
    "modules": {"academia": False, "community": False},  # industry jobs always on; these are opt-in
    "apply_mode": "assisted",
    "apply_daily_limit": 5,       # email_auto: max application emails sent per day
    "apply_language": "auto",     # auto = the posting's language
    "cv_file": "",                # original CV file (set on upload) — attached to email applications     # assisted | email_auto | web_auto (see Config → Applying)
    "home_country": "",
    "apify_monthly_budget_usd": 5.0,
    "apify_import_min_fit": 50,
    "apify_reserve_usd": 0.3,
    "allow_ai_gigs": False,
    "apify_plan": {},   # per-source queries for the ⚡ Apify panel, e.g. {"linkedin": [...], "hellowork": [...]}             # hourly AI-training / data-labelling 'researcher' gigs are filtered out           # kept free for API/storage charges
    "apify_default_unknown_cap_usd": 1.0,  # assumed cost of a running run whose cap can't be read
    "apify_cap_per_run_usd": 0.15, "apify_items_per_run": 20,
    "name": "",
    "email_to": os.environ.get("ALERT_EMAIL_TO", ""),
    "target_roles": [],          # e.g. ["Medical Imaging Engineer", "Data Scientist"]
    "eir_queries": ["entrepreneur in residence healthcare", "entrepreneur-in-residence medtech",
                    "EIR healthcare", "EIR medtech", "venture builder healthcare",
                    "venture builder medtech", "entrepreneur en résidence santé"],
    "keywords": [],              # skills / terms to match
    "exclude_keywords": ["senior director", "vp ", "principal"],
    "locations": [],             # e.g. ["France", "Paris", "Remote", "Europe"]
    "remote_ok": True,
    "min_score": 55,             # only alert on jobs scoring >= this
    "scan_interval_hours": 6,
    "ai_primary": "claude_cli",        # auto | claude_cli | anthropic_api | codex | gemini
    "council_agents": ["claude", "codex", "gemini"],
    "ai_review_top_n": 5,        # jobs per scan that the agents review in depth
    "daily_digest_hour": 8,
    # ATS boards to watch directly, e.g. ["greenhouse:doctolib", "lever:mistral"]
    "watch_companies": [],
    "adzuna_countries": ["fr"],
    "excluded_countries": ["US"],  # hidden everywhere (toggle in the top bar)
    "radar_per_scan": 3,
    # feed hygiene & balance -----------------------------------------------------------
    "kb_path": "",                # optional knowledge base: an Obsidian vault / Markdown folder (read-only)
    "model_verify_per_scan": 6,   # AI-found job links Claude/Codex verify each scan (0 = off)
    "priority_lanes": ["exec", "founding", "innovation", "vc"],  # 💎 hidden gems: boosted, never auto-dropped for low score
    "priority_boost": 18,
    "keep_trends_days": 10, "keep_intel_days": 21,
    "max_job_age_days": 45,       # untouched items older than this are archived
    "auto_archive_below": 30,     # untouched items still under this score after a week are archived
    "radar_max_items": 20,        # results requested per radar lane
    "radar_workers_per_agent": 2, # parallel web searches per agent (Claude + Codex → 4 at once)
    "radar_pinned": ["fr_leadership", "exec"],   # lanes searched every scan (others rotate)          # AI web-radar lanes researched per scan (Claude, Codex fallback)
    "intel_companies": [],        # override the pack's companies (empty = use pack)
    "preferences": "",            # free text: what you want (used in scoring + AI reviews)
    "nationality": "",            # for visa briefs
    "universities": [],
    "email_alerts": True,         # read LinkedIn/APEC/Indeed/Glassdoor/WTTJ alert emails (read-only) each scan
    # bilingual / leadership search terms sent to France Travail, Adzuna and the job feeds
    "french_queries": [],         # local-language search terms (empty = use pack)
    "leadership_queries": [],     # leadership search terms (empty = use pack)
    # model switching ---------------------------------------------------------------
    "agent_order": ["claude_cli", "codex", "gemini", "anthropic_api"],   # fallback order
    "routes": {"writing": "claude_cli", "review": "rotate", "radar": "claude_cli", "chat": "auto",
               "training": "auto", "profile": "auto"},                     # task -> agent | auto | rotate
    "agent_budgets": {"claude_cli": 0, "codex": 0, "gemini": 0, "anthropic_api": 20},  # calls/day, 0 = unlimited
    "limit_cooldown_min": 60,     # after a usage-limit error, skip that agent for this long
}


def get_settings() -> dict:
    s = dict(DEFAULT_SETTINGS)
    if SETTINGS_PATH.exists():
        try:
            saved = json.loads(SETTINGS_PATH.read_text())
            if "pack" not in saved:  # one-time migration: installs from before packs were medical-imaging
                saved.update(pack="medical_imaging", setup_done=True)
            if "modules" not in saved and saved.get("setup_done"):
                saved["modules"] = {"academia": True, "community": True}
                SETTINGS_PATH.write_text(json.dumps(saved, indent=2))
            s.update(saved)
        except Exception:
            pass
    return s


def save_settings(new: dict) -> dict:
    s = get_settings()
    s.update({k: v for k, v in new.items() if k in DEFAULT_SETTINGS})
    SETTINGS_PATH.write_text(json.dumps(s, indent=2))
    return s
