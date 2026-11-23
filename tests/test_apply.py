from pathlib import Path

from jobagent import apply, db, emailer


def _job(jid, desc):
    db.init()
    db.execute("INSERT OR REPLACE INTO jobs (id,title,company,location,url,description,status) VALUES (?,?,?,?,?,?,'new')",
               (jid, "ML Engineer", "Acme", "Paris", "https://example.com/j", desc))


def test_application_email_skips_noreply():
    assert apply.application_email({"description": "Write to noreply@acme.com or jobs@acme.com."}) == "jobs@acme.com"
    assert apply.application_email({"description": "Apply on our site."}) == ""


def test_email_auto_queues_once_and_respects_limit(monkeypatch, tmp_path):
    cv = tmp_path / "cv.pdf"; cv.write_bytes(b"%PDF")
    from jobagent import config
    config.save_settings({"cv_file": str(cv), "apply_daily_limit": 1})
    monkeypatch.setattr(emailer, "configured", lambda: True)
    monkeypatch.setattr(apply, "_letter", lambda j, a=None: ("Application", "Hello", "test"))
    sent = []
    monkeypatch.setattr(emailer, "send_to", lambda to, *a, **k: sent.append(to))
    _job("a1", "Send your CV to hr@acme.com")
    _job("a2", "Send your CV to talent@acme.com")
    first = apply.start("a1", "email_auto")
    again = apply.start("a1", "email_auto")
    assert again["queued"] == first["queued"] and "Already" in again["note"]
    apply.start("a2", "email_auto")
    assert apply.send_due(lambda *_: None)["sent"] == 1  # daily limit 1
    assert sent == ["hr@acme.com"]
    assert db.one("SELECT status FROM jobs WHERE id='a1'")["status"] == "applied"


def test_email_auto_falls_back_when_no_address(monkeypatch):
    monkeypatch.setattr("jobagent.extras.application_pack", lambda jid, a=None: {"folder": "x", "files": [], "agent": "t"})
    _job("a3", "Apply via our careers portal.")
    out = apply.start("a3", "email_auto")
    assert out["mode"] == "assisted" and "queued" not in out
