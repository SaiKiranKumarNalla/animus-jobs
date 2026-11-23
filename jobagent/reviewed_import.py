"""Import a locally reviewed, evidence-backed job shortlist (no network or email)."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import db
from .config import get_settings


def import_file(path):
    payload = json.loads(Path(path).read_text())
    resume = db.master_resume()
    if not resume:
        raise ValueError("Stored master resume required")
    resume_hash = hashlib.sha256(resume["text"].encode()).hexdigest()
    if payload.get("resume_sha256") != resume_hash:
        raise ValueError("Review does not match the current stored resume")
    now = datetime.now(timezone.utc)
    results = []
    for job in payload["jobs"]:
        review = job.get("extra", {}).get("fit_review", {})
        score = review.get("score", 0)
        posted = datetime.fromisoformat(job["posted_at"].replace("Z", "+00:00"))
        if posted.tzinfo is None:
            posted = posted.replace(tzinfo=timezone.utc)
        if (review.get("reviewer") not in ("codex", "claude_cli")
                or not get_settings()["apify_import_min_fit"] < score <= 100
                or not review.get("reason") or not review.get("source_evidence")
                or not now - timedelta(days=7) <= posted <= now):
            raise ValueError(f"Invalid or stale review: {job['id']}")
        review["resume_sha256"] = resume_hash
        inserted = db.upsert_job(job)
        if inserted:
            db.execute("UPDATE jobs SET score=?,ai_verdict=? WHERE id=?",
                       (score, json.dumps({"fit": score, "agent": review["reviewer"],
                                          "reason": review["reason"],
                                          "gaps": review.get("gaps", [])}), job["id"]))
        results.append({"id": job["id"], "inserted": inserted, "fit": score})
    return results
