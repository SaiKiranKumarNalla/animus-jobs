# ANIMUS Jobs (`animus-jobs`)

**A local-first AI career agent.** It finds jobs, postdocs, fellowships, grants, hackathons and events, ranks them
against *your* profile, verifies links, and helps you apply. It runs on your own computer, using the AI
subscriptions you already pay for (Claude, ChatGPT/Codex, Gemini). No API bills, and your CV never leaves your
machine except in prompts to your own AI accounts.

> Status: early public version (0.6). macOS and Linux are tested; Windows support is new, so please report issues.

## What it does
- **Discover:** swipe through opportunities (→ save, ← dismiss, ↑ star, ↓ later). Every swipe trains your ranking.
- **Field packs:** lanes, searches, companies and conferences for *your* field, generated from your CV or picked from
  built-ins (software, data/AI, biotech, medical imaging).
- **Many sources:** free job APIs, company boards (Greenhouse, Lever, Ashby), France Travail, Adzuna, EU funding calls,
  OpenAlex (potential PIs), Devpost, your job-alert emails (LinkedIn, Indeed, APEC, Welcome to the Jungle, read-only),
  and an **AI web radar** (Claude/Codex search the web, lane by lane).
- **Trust:** links are checked automatically. Claude or Codex can **open the page and confirm the posting**, and every item
  shows *who added it* and *who verified it, and when*. Dead, duplicate and expired items are archived automatically.
- **Template jobs:** paste postings you found yourself. Similar ones get boosted, and a gap plan tells you how to become that candidate.
- **Academia:** postdocs, fellowships, grants, and a Fellowship Match that pairs open calls with eligible host PIs.
- **Writing:** tailored CVs, cover letters, outreach and postdoc emails, LinkedIn drafts, mock interviews, salary and visa briefs.
- **Game layer:** XP and levels earned from real progress (triage, verification, applications, practice), daily
  quests, streaks and achievements. Opportunities come in rarity tiers (common → legendary), and agent energy bars show
  how much of your AI subscriptions is left today.
- **Plan:** kanban tracker, deadline calendar (.ics), world map, skill ranker, weekly top-5 email.
- **Optional:** email alerts (Gmail, Outlook, iCloud, any IMAP/SMTP), Obsidian / Markdown knowledge base.

## Install
Requires **Python 3.10+**. Then install at least one AI command-line tool and log in once (the setup wizard shows how):
[Claude Code](https://claude.com/claude-code) (Claude Pro/Max) and/or [Codex](https://github.com/openai/codex) (ChatGPT).

**macOS / Linux**
```bash
git clone https://github.com/<you>/animus-jobs && cd animus-jobs
./scripts/install.sh
```
**Windows (PowerShell)**
```powershell
git clone https://github.com/<you>/animus-jobs; cd animus-jobs
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
```
Then open **http://127.0.0.1:8765** (or run `jobagent open`). The **setup wizard** walks you through:
1. CV upload → AI profile
2. Field pack (generated from your CV, or a built-in one)
3. Connecting Claude / Codex / Gemini
4. Optional email
5. How applying should work: assisted, auto-send email applications, or (risky) full auto-apply

Prefer the terminal? `jobagent setup`.

## Where your data lives
`~/.jobagent` (Windows: `%APPDATA%\JobAgent`). Override it with `JOBAGENT_HOME`. It holds the SQLite database,
settings, logs and your private `.env` (email app password, optional API keys, `chmod 600`). Nothing personal is ever
written inside the repo.

## CLI
```
jobagent open | setup | scan | status | jobs | radar [lanes…] | verify-web --company X
jobagent ask "…" | council "…" | cover JOB_ID | tailor JOB_ID | plan | weekly
```

## Applying modes and their limits
The mode is chosen in setup. Today JobAgent prepares the material: tailored CV, letter, email and answers, plus a
text "application pack". The automatic modes are on the roadmap.
- **Assisted (default):** JobAgent prepares everything; you press Submit.
- **Auto-send email applications (planned):** sent from your own account within the daily limits you set.
- **Full auto-apply to web forms (planned, opt-in):** off by default. Automated submissions break the terms of LinkedIn, Indeed and
  most applicant-tracking systems, and can get accounts banned. JobAgent never scrapes sites that forbid it; it uses
  official APIs, your own alert emails, or AI web search instead.

## Contributing
Field packs are plain JSON in `jobagent/packs/`; new packs for other fields are very welcome. Run tests with `pytest`.

## License
MIT. See [LICENSE](LICENSE).
