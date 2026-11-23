"""Multi-agent AI layer.

Agents:
  claude_cli    - Claude Code CLI (`claude -p`, Opus), uses your Claude login
  anthropic_api - Anthropic API (ANTHROPIC_API_KEY), model claude-opus-5-5
  codex         - OpenAI Codex CLI (`codex exec`)  ("Astra")
  gemini        - Google Gemini CLI (`gemini -p`), or GEMINI_API_KEY via REST
"""
import glob
import os
import shutil
import json
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from .config import DATA, get_settings

WORKDIR = DATA / "agent_ws"
WORKDIR.mkdir(exist_ok=True)
TIMEOUT = int(os.environ.get("AGENT_TIMEOUT", "300"))
CLAUDE_MODEL = "claude-opus-5-5"

SYSTEM = (
    "You are JobAgent, a sharp, warm, honest career coach and job-search assistant. "
    "You help one person land a great job: tailoring resumes, beating ATS filters, writing "
    "outreach emails and cover letters, planning skill development and preparing interviews. "
    "Be specific and actionable, use the candidate's real experience, never invent facts "
    "about their background, and flag anything they should verify. Use Markdown."
)


def _which(*names):
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def claude_bin():
    p = os.environ.get("CLAUDE_BIN") or _which("claude")
    if p:
        return p
    for cand in [os.path.expanduser("~/.claude/local/claude"), "/opt/homebrew/bin/claude",
                 "/usr/local/bin/claude"]:
        if os.path.exists(cand):
            return cand
    hits = sorted(glob.glob(os.path.expanduser(
        "~/Library/Application Support/Claude/claude-code/*/*/claude.app/Contents/MacOS/claude")))
    return hits[-1] if hits else None


def codex_bin():
    return os.environ.get("CODEX_BIN") or _which("codex")


def gemini_bin():
    return os.environ.get("GEMINI_BIN") or _which("gemini")


def _env():
    env = dict(os.environ)
    env["PATH"] = env.get("PATH", "") + ":/opt/homebrew/bin:/usr/local/bin:" + \
        os.path.expanduser("~/.local/bin") + ":" + os.path.expanduser("~/.npm-global/bin")
    return env


WEB_TIMEOUT = int(os.environ.get("AGENT_WEB_TIMEOUT", "900"))  # multi-search web lanes take longer


def _run(cmd, stdin_text=None, timeout=None):
    r = subprocess.run(cmd, input=stdin_text, capture_output=True, text=True,
                       timeout=timeout or TIMEOUT, cwd=WORKDIR, env=_env())
    out = (r.stdout or "").strip()
    if r.returncode != 0 or not out:
        raise RuntimeError((r.stderr or out or f"exit {r.returncode}").strip()[-600:])
    low = out.lower()
    if "not logged in" in low or "please run /login" in low:
        raise RuntimeError(out)
    return out


# ---- individual agents -------------------------------------------------------

def ask_claude_cli(prompt, system=SYSTEM):
    b = claude_bin()
    if not b:
        raise RuntimeError("Claude CLI not found")
    return _run([b, "-p", "--model", "opus", "--no-session-persistence",
                 "--append-system-prompt", system], prompt)


def ask_claude_web(prompt, system=SYSTEM):
    """Claude CLI with web search/fetch enabled (subscription) – used by the opportunity radar."""
    b = claude_bin()
    if not b:
        raise RuntimeError("Claude CLI not found")
    return _run([b, "-p", "--model", "opus", "--no-session-persistence",
                 "--allowedTools", "WebSearch", "WebFetch", "--append-system-prompt", system], prompt,
                timeout=WEB_TIMEOUT)


def _search_web_snippets(query, max_results=8):
    """Direct fast web search without external dependencies, returns list of formatted snippets."""
    import urllib.parse
    UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    try:
        r = httpx.post("https://html.duckduckgo.com/html/", data={"q": query[:120]}, headers=UA, timeout=15)
        matches = re.findall(r'<a class="result__url"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?<a class="result__snippet[^"]*"[^>]*>(.*?)</a>', r.text, re.S)
        results = []
        seen = set()
        for u, disp, snip in matches[:max_results]:
            if "uddg=" in u:
                m = re.search(r"uddg=([^&]+)", u)
                if m:
                    u = urllib.parse.unquote(m.group(1))
            if u.startswith("http") and u not in seen:
                seen.add(u)
                clean_snip = re.sub(r"<[^>]+>", "", snip).strip()
                results.append(f"URL: {u}\nSNIPPET: {clean_snip}")
        return results
    except Exception:
        return []


def ask_gemini_web(prompt, system=SYSTEM):
    """Disabled: Gemini proposals require independent Claude/Codex approval."""
    raise RuntimeError("Gemini web search disabled by user policy; use Claude or Codex.")


def ask_codex_web(prompt, system=SYSTEM):
    """Codex CLI with live web search (ChatGPT subscription) or web snippets fallback."""
    b = codex_bin()
    if b:
        try:
            return _run([b, "--search", "exec", "--skip-git-repo-check", f"{system}\n\n{prompt}"], timeout=WEB_TIMEOUT)
        except Exception:
            pass
    # Fallback using live search snippets
    m_what = re.search(r"find up to \d+ (.*?)\.", prompt, re.I | re.S)
    q = m_what.group(1).strip().split("\n")[0][:80] if m_what else prompt.split("\n")[0][:80]
    snippets = _search_web_snippets(q, max_results=8)
    context = "\n---\n".join(snippets) if snippets else ""
    return ask_codex(f"LIVE WEB RESULTS:\n{context}\n\n{prompt}", system=system)


def ask_anthropic_api(prompt, system=SYSTEM):
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    import anthropic
    client = anthropic.Anthropic()
    with client.beta.messages.stream(
        model=CLAUDE_MODEL,
        max_tokens=32000,
        system=system,
        thinking={"type": "adaptive"},
        output_config={"effort": "medium"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        msg = stream.get_final_message()
    if msg.stop_reason == "refusal":
        raise RuntimeError("Request declined by the model")
    return "".join(b.text for b in msg.content if b.type == "text").strip()


def ask_codex(prompt, system=SYSTEM):
    b = codex_bin()
    if not b:
        raise RuntimeError("Codex CLI not installed (npm i -g @openai/codex)")
    return _run([b, "exec", "--skip-git-repo-check", f"{system}\n\n{prompt}"])


def ask_gemini(prompt, system=SYSTEM):
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        configured_model = os.environ.get("GEMINI_MODEL")
        candidate_models = []
        if configured_model:
            candidate_models.append(configured_model)
        for m in ["gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.8-flash"]:
            if m not in candidate_models:
                candidate_models.append(m)
        last_err = None
        for model in candidate_models:
            if not model:
                continue
            try:
                r = httpx.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
                    headers={"Content-Type": "application/json"},
                    json={"systemInstruction": {"parts": [{"text": system}]},
                          "contents": [{"role": "user", "parts": [{"text": prompt}]}]},
                    timeout=TIMEOUT,
                )
                r.raise_for_status()
                data = r.json()
                candidates = data.get("candidates", [])
                if candidates and "content" in candidates[0]:
                    parts = candidates[0]["content"].get("parts", [])
                    text = "".join(p.get("text", "") for p in parts if "text" in p).strip()
                    if text:
                        return text
            except Exception as e:  # noqa: BLE001
                last_err = e
                continue
        if not gemini_bin():
            raise RuntimeError(f"Gemini API request failed: {last_err}")
    b = gemini_bin()
    if b:
        return _run([b, "-p", f"{system}\n\n{prompt}"])
    raise RuntimeError("Gemini CLI not installed and no valid GEMINI_API_KEY")


AGENTS = {
    "claude_cli": ("Claude Opus (CLI)", ask_claude_cli),
    "anthropic_api": ("Claude Opus (API)", ask_anthropic_api),
    "codex": ("Codex / Astra", ask_codex),
    "gemini": ("Gemini", ask_gemini),
}
# ---- health, limits, usage & routing -------------------------------------------------------
# HEALTH[name] = (since, message, kind, until)   kind: "auth" (needs login) | "limit" (usage cap, cooling down)
HEALTH = {}
AUTH_WORDS = ("not logged", "please run /login", "log in", "unauthorized", "401", "credential", "api key",
              "api_key", "no longer supported", "migrate to", "authentication")
LIMIT_WORDS = ("usage limit", "limit reached", "rate limit", "rate_limit", "429", "quota", "too many requests",
               "resource_exhausted", "overloaded", "capacity", "hit your", "out of credits", "exceeded")
HEALTH_FILE = DATA / "agent_health.json"
USAGE_FILE = DATA / "agent_usage.json"
_lock = threading.Lock()


def _load(path, default):
    try:
        return json.loads(path.read_text())
    except Exception:  # noqa: BLE001
        return default


HEALTH.update({k: tuple(v) if len(v) >= 4 else (v[0], v[1], "auth", v[0] + 6 * 3600)
               for k, v in _load(HEALTH_FILE, {}).items()})


def _save_health():
    try:
        HEALTH_FILE.write_text(json.dumps(HEALTH))
    except Exception:  # noqa: BLE001
        pass


def _mark(name, err):
    msg = str(err).lower()
    now = time.time()
    if any(w in msg for w in LIMIT_WORDS) or "session limit" in msg:
        until = now + get_settings().get("limit_cooldown_min", 60) * 60
        m = re.search(r"resets?\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", msg)
        if m:  # e.g. "resets 6:10pm" -> rest until exactly then
            import datetime as _dt
            h, mi = int(m.group(1)), int(m.group(2) or 0)
            if m.group(3) == "pm" and h < 12:
                h += 12
            if m.group(3) == "am" and h == 12:
                h = 0
            t = _dt.datetime.now().replace(hour=h % 24, minute=mi, second=0, microsecond=0)
            if t.timestamp() <= now:
                t += _dt.timedelta(days=1)
            until = t.timestamp() + 60
        HEALTH[name] = (now, str(err)[:200], "limit", until)
    elif any(w in msg for w in AUTH_WORDS):
        HEALTH[name] = (now, str(err)[:200], "auth", now + 6 * 3600)
    else:
        return
    _save_health()


def _blocked(name):
    h = HEALTH.get(name)
    return h if h and time.time() < h[3] else None


def _usage():
    u = _load(USAGE_FILE, {})
    day = time.strftime("%Y-%m-%d")
    if u.get("day") != day:
        u = {"day": day, "agents": {}}
    return u


def _record(name, prompt, out, ok, secs):
    with _lock:
        u = _usage()
        a = u["agents"].setdefault(name, {"calls": 0, "fails": 0, "tokens_in": 0, "tokens_out": 0, "secs": 0})
        a["calls"] += 1
        a["fails"] += 0 if ok else 1
        a["tokens_in"] += len(prompt) // 4          # ~4 chars per token estimate
        a["tokens_out"] += len(out or "") // 4
        a["secs"] = round(a["secs"] + secs, 1)
        USAGE_FILE.write_text(json.dumps(u))


def over_budget(name):
    budget = int(get_settings().get("agent_budgets", {}).get(name, 0) or 0)
    used = _usage()["agents"].get(name, {}).get("calls", 0)
    return budget and used >= budget


def call(name, prompt, system=SYSTEM, fn=None):
    """Single agent call with usage accounting and limit/auth detection."""
    t0 = time.time()
    try:
        out = (fn or AGENTS[name][1])(prompt, system)
        _record(name, prompt, out, True, time.time() - t0)
        return out
    except Exception as e:  # noqa: BLE001
        _record(name, prompt, "", False, time.time() - t0)
        _mark(name, e)
        raise


# council names -> concrete agents
FAMILY = {"claude": ["claude_cli", "anthropic_api"], "codex": ["codex"], "gemini": ["gemini"]}


def status():
    """Availability without calling the models: installed + not blocked + under today's budget."""
    st = _status()
    u = _usage()["agents"]
    budgets = get_settings().get("agent_budgets", {})
    for name, v in st.items():
        v["usage"] = u.get(name, {"calls": 0, "tokens_in": 0, "tokens_out": 0, "fails": 0})
        v["budget"] = int(budgets.get(name, 0) or 0)
        h = _blocked(name)
        if v["ready"] and h:
            v["ready"] = False
            v["state"] = h[2]
            v["detail"] = ("cooling down until " + time.strftime("%H:%M", time.localtime(h[3])) + " (usage limit): "
                           if h[2] == "limit" else "needs login: ") + h[1]
        elif v["ready"] and over_budget(name):
            v["ready"], v["state"], v["detail"] = False, "budget", f"daily budget of {v['budget']} calls used"
        else:
            v["state"] = "ready" if v["ready"] else "offline"
    return st


def _status():
    return {
        "claude_cli": {"label": AGENTS["claude_cli"][0], "ready": bool(claude_bin()),
                       "detail": claude_bin() or "not found"},
        "anthropic_api": {"label": AGENTS["anthropic_api"][0],
                          "ready": bool(os.environ.get("ANTHROPIC_API_KEY")),
                          "detail": "key set" if os.environ.get("ANTHROPIC_API_KEY") else "no ANTHROPIC_API_KEY"},
        "codex": {"label": AGENTS["codex"][0], "ready": bool(codex_bin()),
                  "detail": codex_bin() or "not installed"},
        "gemini": {"label": AGENTS["gemini"][0],
                   "ready": bool(gemini_bin() or os.environ.get("GEMINI_API_KEY")),
                   "detail": gemini_bin() or ("API key" if os.environ.get("GEMINI_API_KEY") else "not installed")},
    }


def _order(preferred=None):
    s = get_settings()
    order = list(s.get("agent_order") or ["claude_cli", "codex", "gemini", "anthropic_api"])
    for a in ["claude_cli", "codex", "gemini", "anthropic_api"]:
        if a not in order:
            order.append(a)
    pref = preferred if preferred in AGENTS else s.get("ai_primary", "auto")
    if pref in AGENTS:
        order.remove(pref)
        order.insert(0, pref)
    return order


def route(task):
    """Preferred agent for a task type (Config → routing); 'auto' means the fallback order."""
    r = (get_settings().get("routes") or {}).get(task, "auto")
    return r if r in AGENTS else None


def ask(prompt, system=SYSTEM, agent=None, task=None, strict=False):
    """Ask the routed/preferred agent; on usage limits, auth errors or budget, fall through to the next.
    strict=True only tries the named agent. Returns (text, agent)."""
    errors = []
    st = status()
    first = agent if agent in AGENTS else route(task)
    names = [first] if strict and first else _order(first)
    for name in names:
        if not st[name]["ready"]:
            errors.append(f"{name}: {st[name]['detail']}")
            continue
        try:
            return call(name, prompt, system), name
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {e}")
    raise RuntimeError("No AI agent could answer.\n" + "\n".join(errors))


def _ask_family(fam, prompt, system):
    st = status()
    last = "unknown agent"
    for name in FAMILY.get(fam, []):
        if st[name]["ready"]:
            try:
                return fam, name, call(name, prompt, system)
            except Exception as e:  # noqa: BLE001
                last = str(e)
                continue
        last = st[name]["detail"]
    return fam, None, f"_unavailable: {last}_"


def council(prompt, system=SYSTEM, families=None, synthesize=True):
    """Ask Claude, Codex and Gemini in parallel, then have the lead agent merge."""
    fams = families or get_settings().get("council_agents", ["claude", "codex", "gemini"])
    with ThreadPoolExecutor(max_workers=len(fams)) as ex:
        results = list(ex.map(lambda f: _ask_family(f, prompt, system), fams))
    answered = [r for r in results if r[1]]
    out = {"answers": [{"family": f, "agent": a, "text": t} for f, a, t in results]}
    if synthesize and len(answered) > 1:
        merged = "\n\n".join(f"### {f} ({a})\n{t}" for f, a, t in answered)
        out["synthesis"], out["lead"] = ask(
            "Several AI advisors answered the same request. Merge them into one best answer: "
            "keep the strongest specific points, resolve disagreements explicitly, drop fluff.\n\n"
            f"## Original request\n{prompt}\n\n## Advisor answers\n{merged}", system)
    elif answered:
        out["synthesis"], out["lead"] = answered[0][2], answered[0][1]
    else:
        out["synthesis"], out["lead"] = "No agents available.", None
    return out


def probe(name):
    """Actually call an agent with a tiny prompt (clears/sets its health)."""
    HEALTH.pop(name, None)
    _save_health()
    try:
        out = call(name, "Reply with exactly: OK", "You are a health check.")
        return {"ok": True, "reply": out[:80]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:300]}
