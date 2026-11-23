# JobAgent: instructions for AI coding agents (Claude Code, Codex, Gemini CLI)

This folder is ANIMUS Jobs (`animus-jobs`), a local-first job-search assistant. Use the `jobagent` CLI (`./bin/jobagent`) to act on it:

- `jobagent status`: agent and email health, job count
- `jobagent scan [--no-email]`: fetch jobs, score, agent-review, and email alerts
- `jobagent jobs -n 20`: top matches with IDs
- `jobagent cover <JOB_ID>`: cover letter for a job
- `jobagent ask "…"` / `jobagent council "…"`: coach / multi-agent answer
- `jobagent plan` / `jobagent weekly`: development plan / emailed weekly plan

Data: `data/jobagent.db` (SQLite: jobs, resumes, documents, chat, runs). Settings: `data/settings.json`.
Code: `jobagent/` (FastAPI server `server.py`, sources `sources.py`, prompts `coach.py`, agents `ai.py`).
Never print or commit `.env` (it holds the Gmail app password and API keys).
Never invent facts about the candidate. Everything must come from the stored resume.

## Mandatory sourcing restriction

Do not run autonomous searches, scans, or radar commands. Do not insert jobs
directly into SQLite or bypass JobAgent's insertion gate. Gemini may draft
proposals only. Proposals must be independently reviewed and approved by
Claude or Codex through `jobagent approve-proposal`; an unavailable reviewer
means the proposal stays pending. Gemini cannot approve its own work.

If `AGENTS.local.md` exists in this folder, read it and follow it as well (private user policies).
