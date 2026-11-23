"""First-run setup helpers: detect AI CLIs, connect email, write the user's private .env."""
import imaplib
import json
import os
import platform
import smtplib
import subprocess

from . import ai, config

OS = {"Darwin": "macos", "Linux": "linux", "Windows": "windows"}.get(platform.system(), "linux")

# How to install and log in to each subscription CLI (copy-paste commands shown in the wizard).
AGENT_HELP = {
    "claude_cli": {
        "name": "Claude (Pro/Max subscription)",
        "install": {"macos": "curl -fsSL https://claude.ai/install.sh | bash",
                    "linux": "curl -fsSL https://claude.ai/install.sh | bash",
                    "windows": "irm https://claude.ai/install.ps1 | iex"},
        "login": "claude auth login",
    },
    "codex": {
        "name": "Codex (ChatGPT subscription)",
        "install": {"macos": "npm install -g @openai/codex", "linux": "npm install -g @openai/codex",
                    "windows": "npm install -g @openai/codex"},
        "login": "codex login",
    },
    "gemini": {
        "name": "Gemini (free AI Studio key, optional)",
        "install": {"macos": "Get a key at https://aistudio.google.com/apikey", "linux": "Get a key at https://aistudio.google.com/apikey",
                    "windows": "Get a key at https://aistudio.google.com/apikey"},
        "login": "Paste the key below as GEMINI_API_KEY",
    },
}

EMAIL_PRESETS = {
    "gmail": {"smtp_host": "smtp.gmail.com", "smtp_port": 465, "imap_host": "imap.gmail.com",
              "help": "Create an app password at https://myaccount.google.com/apppasswords (needs 2-Step Verification)."},
    "outlook": {"smtp_host": "smtp-mail.outlook.com", "smtp_port": 587, "imap_host": "outlook.office365.com",
                "help": "Use an app password from https://account.microsoft.com/security (Advanced security options)."},
    "icloud": {"smtp_host": "smtp.mail.me.com", "smtp_port": 587, "imap_host": "imap.mail.me.com",
               "help": "Create an app-specific password at https://appleid.apple.com."},
    "other": {"smtp_host": "", "smtp_port": 465, "imap_host": "", "help": "Use your provider's SMTP/IMAP hosts and an app password."},
}


def agents():
    """Installed / ready state for each agent plus the exact commands for this OS."""
    st = ai.status()
    out = {}
    for name, h in AGENT_HELP.items():
        v = st.get(name, {})
        out[name] = {"name": h["name"], "ready": v.get("ready", False), "state": v.get("state", "offline"),
                     "detail": v.get("detail", ""), "install": h["install"][OS], "login": h["login"]}
    return out


def account_email():
    """Email of the logged-in Claude account (official `claude auth status`), used as the default alert address."""
    b = ai.claude_bin()
    if not b:
        return ""
    try:
        r = subprocess.run([b, "auth", "status"], capture_output=True, text=True, timeout=20)
        return json.loads(r.stdout or "{}").get("email", "") or ""
    except Exception:  # noqa: BLE001
        return ""


def write_env(updates: dict):
    """Merge KEY=value pairs into the user's private .env (chmod 600) and the running process."""
    path = config.ENV_PATH
    lines = path.read_text().splitlines() if path.exists() else []
    keys = {k for k in updates}
    kept = [l for l in lines if not any(l.startswith(k + "=") for k in keys)]
    for k, v in updates.items():
        if v is None:
            continue
        v = str(v).replace("\n", "").strip()
        kept.append(f"{k}={v}")
        os.environ[k] = v
    path.write_text("\n".join(kept) + "\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def test_email(address, password, smtp_host, smtp_port, imap_host):
    """Log in to SMTP (sending alerts) and IMAP (reading job-alert emails). Returns {smtp, imap, error}."""
    res = {"smtp": False, "imap": False, "error": ""}
    pw = password.replace(" ", "")
    try:
        if int(smtp_port) == 465:
            with smtplib.SMTP_SSL(smtp_host, 465, timeout=20) as s:
                s.login(address, pw)
        else:
            with smtplib.SMTP(smtp_host, int(smtp_port), timeout=20) as s:
                s.starttls()
                s.login(address, pw)
        res["smtp"] = True
    except Exception as e:  # noqa: BLE001
        res["error"] = f"SMTP: {str(e)[:160]}"
    if imap_host:
        try:
            m = imaplib.IMAP4_SSL(imap_host)
            m.login(address, pw)
            m.logout()
            res["imap"] = True
        except Exception as e:  # noqa: BLE001
            res["error"] += f" IMAP: {str(e)[:160]}"
    return res


def connect_email(provider, address, password, alerts_to="", smtp_host="", smtp_port=0, imap_host=""):
    pre = EMAIL_PRESETS.get(provider, EMAIL_PRESETS["other"])
    smtp_host, imap_host = smtp_host or pre["smtp_host"], imap_host or pre["imap_host"]
    smtp_port = int(smtp_port or pre["smtp_port"])
    res = test_email(address, password, smtp_host, smtp_port, imap_host)
    if res["smtp"]:
        write_env({"SMTP_USER": address, "SMTP_PASSWORD": password.replace(" ", ""), "SMTP_HOST": smtp_host,
                   "SMTP_PORT": smtp_port, "IMAP_HOST": imap_host, "ALERT_EMAIL_TO": alerts_to or address})
        config.save_settings({"email_to": alerts_to or address, "email_alerts": res["imap"]})
    return res


def status():
    s = config.get_settings()
    from . import db, emailer, packs
    return {"os": OS, "setup_done": s.get("setup_done"), "resume": bool(db.master_resume()),
            "pack": (s.get("pack") if isinstance(s.get("pack"), str) else (s.get("pack") or {}).get("name", "custom")),
            "builtin_packs": packs.builtins(), "agents": agents(), "email": emailer.configured(),
            "email_presets": {k: v["help"] for k, v in EMAIL_PRESETS.items()}, "default_email": account_email(),
            "apply_mode": s.get("apply_mode"), "home_country": s.get("home_country"), "app_home": str(config.APP_HOME)}
