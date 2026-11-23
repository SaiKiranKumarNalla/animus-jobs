# 🎯 JobAgent: your personal AI job-search assistant

A local app that runs in the background on your Mac. It hunts for jobs, ranks them against your resume, has
**Claude Opus, Codex (Astra) and Gemini** review the best ones on a schedule, emails you alerts, and coaches you.

**Open it:** double-click **JobAgent** on your Desktop, or go to <http://127.0.0.1:8765>.

## What it does
| Area | Features |
|---|---|
| 💼 Jobs | Pulls from Remotive, Arbeitnow (EU), RemoteOK, Jobicy, The Muse, Adzuna (optional key), plus company boards you watch (Greenhouse / Lever / Ashby). Relevance filter, match score 0-100, matched/missing skills, pipeline tracking (saved → applied → interview → offer). |
| 🔎 Search-engine hunting | Generates Google "X-ray" queries for Greenhouse/Lever/Ashby/Workday/Welcome to the Jungle, LinkedIn, Indeed and hiring managers. |
| 📄 Resume & ATS | Upload PDF/DOCX; the agent builds your profile and auto-fills targets. Instant rule-based ATS scan plus an AI recruiter review; resume rewrite and tailoring per job. |
| ✉️ Writing | Cover letters (EN/FR/ES/DE, tone presets) and emails: recruiter outreach, referral ask, follow-up, thank-you, networking, negotiation. |
| 🧠 Skills | Skill-gap analysis across your best-matching jobs, an N-week development plan, a trainer (quiz / lesson / project / interview questions) with grading. |
| 💬 Coach | Chat that knows your resume and pipeline. Council mode asks all agents at once. |
| 🤖 Agents | Every scan, the top jobs are reviewed round-robin by Claude, Codex and Gemini. The council merges answers from all three. |
| 📬 Alerts | Email of new matches after every scan (default every 6 h). A weekly development plan every Monday. |

## v2: ANIMUS HUD
- **14 tracks:** PET/CT, Nuclear Medicine, Medical Imaging, AI in Imaging, MedTech Innovation, MedTech VC, CTO/CEO,
  Research, Collaborators, Hackathons, Individual Funding, Computational Modelling, Fellowships, Startup Funding.
- **Sources beyond jobs:** Devpost hackathons, EU Funding & Tenders calls (incl. MSCA and EIC), OpenAlex collaborators
  (authors publishing in your topics), and the **AI radar**: Claude searches the web for 2 tracks per scan, in rotation.
- **World map**, **kanban tracker** (drag between columns), **deadline calendar** (.ics export plus email reminders
  7 days and 1 day ahead), **skill ranker** (market demand × your self-rated gap, with history).
- The old interface is still at `/classic`.

## v3: lanes, intel, scoring
- **20 lanes**, adding Postdoc Collaborators (European PIs), online-only Hackathons, MedTech Analyst, Product Roles,
  CSO/CTO/CEO, Founding Engineer/Scientist, Internships (Europe), Spontaneous Targets and Company Intelligence.
- **Web radar** uses Claude, with automatic fallback to Codex (`codex --search`) when Claude is offline, limited
  or over budget. It covers 3 lanes per scan, in rotation, and respects excluded countries.
- **Scoring** uses your whole profile: resume, AI profile, Config → "What I want", skills rated 3+, lane fit,
  Europe preference, the agents' fit verdict (65% weight once reviewed), and your 👍/👎. Each score lists why.
- **Writers:** postdoc inquiry to a PI (cites their papers), spontaneous application, country brief (visa routes,
  salaries, cost of living, relocation), salary estimate and visa note on each review, weekly top-5 moves (emailed Mondays).

## One-time setup
1. **Upload your resume** in *Resume & ATS*. This auto-fills target roles, skills and locations; adjust them in *Settings*.
2. **Email alerts:** create a Gmail app password at <https://myaccount.google.com/apppasswords>, paste it as
   `SMTP_PASSWORD=` in `~/Jobagent/.env`, then run `launchctl kickstart -k gui/$(id -u)/com.jobagent.server`
   and press *Send test email* in Settings.
3. **Connect the agents** (any subset works; check them with *Agents Council → Test agent connections*):
   - **Claude Opus:** install the Claude Code CLI (`curl -fsSL https://claude.ai/install.sh | bash`) and run `claude` once to log in,
     **or** put `ANTHROPIC_API_KEY=` in `.env`.
   - **Codex (Astra):** `brew install node && npm i -g @openai/codex && codex login`
   - **Gemini:** `npm i -g @google/gemini-cli && gemini` (log in once), **or** set `GEMINI_API_KEY=` in `.env`.
   - After installing, restart the service: `launchctl kickstart -k gui/$(id -u)/com.jobagent.server`
4. Optional: free Adzuna keys (<https://developer.adzuna.com>) add France, UK, US and other national job boards.

## CLI
```
jobagent status | scan | jobs | ask "…" | council "…" | cover JOB_ID | plan | weekly
```
`AGENTS.md` / `CLAUDE.md` / `GEMINI.md` tell Claude Code, Codex and Gemini CLI how to drive JobAgent when they're opened in this folder.

## Service
- Runs as `~/Library/LaunchAgents/com.jobagent.server.plist`: starts at login, restarts if it crashes, and holds the scheduler.
- Logs: `logs/server.log`, `logs/server.err`. Data: `data/` (stays on your Mac).
- Stop: `launchctl bootout gui/$(id -u)/com.jobagent.server` · Reinstall/update: `./scripts/install.sh`

## v4: extras
- **Fellowship Match** (no AI usage): open fellowships paired with eligible European PIs, with a one-click joint-application email.
- **People finder** (no AI usage): recruiter, hiring-manager and alumni search links on every job or target.
- **Learning from 👍/👎** (no AI usage): lanes and title terms you like or dislike shift future scores by up to ±15.
- **Conferences & Abstracts** radar lane (EANM, SNMMI, MICCAI, IEEE MIC…), with deadlines on the calendar.
- **Light application pack**: one AI call writes `applications/<date>_<company>_<role>/` containing a CV-edits checklist,
  cover letter, email, LinkedIn note and pre-submit checklist as text files.
- **LinkedIn Studio**: post drafts, batch connection notes (one AI call) and profile optimisation. Drafts only; nothing is posted.
- **Mock Interview**: typed or spoken (Chrome speech), one question at a time, scored, with a final scorecard.
- Usage-limit cooldowns follow the agent's own reset time (e.g. "resets 6:10pm").

## v5: sections
- Sidebar groups: **Industry** (Jobs · Tracks), **Academia** (Postdocs, Fellowships, Research Grants,
  Fellowship Match, PI Contacts), **Community** (Hackathons, Events · Fairs), **Tools**.
- Tracks are industry-only. Postdocs, fellowships, grants, PI contacts, hackathons and events never appear there,
  and alert emails group items by section.
- **Events · Fairs**: webinars, job fairs, career days, meetups and conferences found by the radar, on the calendar.
- **What's hot** (LinkedIn Studio): trending topics in your field from web search, each with "draft a post on this".
- Gemini via Antigravity: Antigravity's `agentapi` needs an internal project ID and session token, so it isn't wired up.
  Use a free AI Studio key (`GEMINI_API_KEY` in `.env`) instead.

## v6: cleaner feed and swipe
- **Discover:** a swipe deck (→ save, ← dismiss, ↑ star, ↓ later, Z undo) next to the lists. Each deck is about 55% best
  matches, 30% 💎 priority-lane gems and 15% exploration. Every swipe trains the scoring.
- **💎 Priority lanes** (Config `priority_lanes`: CSO/CTO, founding, Innovation & EIR, VC) get +18 and are never
  auto-dropped for a low score, so leadership roles with weaker CV matches still surface.
- **Auto-filter** (every scan, archive-only, engaged items untouched): past deadlines and events, trends older than 10 days and intel
  older than 21 days, items untouched for 45+ days, scores under 30 after a week, generic or listing links, swiped-left items,
  and near-duplicate merging (same organisation and 85% title overlap; the kept card lists the others under `also_on`).
- Kind-aware generic-link checks (contact pages, event directories, grant aggregators, awesome-lists).
- Simpler UI: compact rows, page descriptions moved into title tooltips, a shorter Command screen, a collapsible "More" menu.
