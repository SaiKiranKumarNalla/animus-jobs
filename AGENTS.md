# JobAgent: instructions for AI coding agents (Claude Code, Codex, Gemini CLI)

This folder is ANIMUS Jobs (`animus-jobs`), a local-first job-search assistant. Use the `jobagent` CLI (`./bin/jobagent`) to act on it:

- `jobagent status`: agent and email health, job count
- `jobagent scan [--no-email]`: fetch jobs, score, agent-review, and email alerts
- `jobagent jobs -n 20`: top matches with IDs
- `jobagent cover <JOB_ID>`: cover letter for a job
- `jobagent ask "…"` / `jobagent council "…"`: coach / multi-agent answer
- `jobagent plan` / `jobagent weekly`: development plan / emailed weekly plan

Data lives in the user's app folder (`~/.jobagent`, `%APPDATA%\JobAgent`, or `JOBAGENT_HOME`; legacy installs use `./data`): SQLite `data/jobagent.db`, settings `data/settings.json`.
Code: `jobagent/` (FastAPI server `server.py`, sources `sources.py`, prompts `coach.py`, agents `ai.py`).
Never print or commit `.env` (it holds the email app password and API keys).
Never invent facts about the candidate. Everything must come from the stored resume.

## Sourcing rules (all installs)

- Gemini must not add opportunities directly: its proposals go through `job_proposals` and must be approved by
  Claude or Codex (`jobagent approve-proposal DIGEST --agent codex|claude_cli`). Never bypass this.
- Never scrape sites whose terms forbid it; use official APIs, the user's own alert emails, or AI web search.
- Archive confirmed broken/closed/generic links; keep blocked pages as unverified. Preserve saved/applied records and notes.

## Private instructions
If `AGENTS.local.md` exists in this folder, read it and follow it as well. It holds this user's private policies.
