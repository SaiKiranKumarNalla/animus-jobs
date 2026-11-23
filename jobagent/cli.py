"""Command line: lets you (or Claude Code / Codex / Gemini sessions) drive JobAgent.

  jobagent serve                 start dashboard + scheduler (http://127.0.0.1:8765)
  jobagent scan [--no-email]     run one job-hunting cycle now
  jobagent status                agents, email, counts
  jobagent jobs [-n 15]          top matches
  jobagent ask "question"        ask the best agent (career coach)
  jobagent council "question"    ask Claude + Codex + Gemini and merge
  jobagent cover JOB_ID          cover letter for a tracked job
  jobagent plan                  development plan
  jobagent weekly                build + email the weekly plan
"""
import argparse
import json
import sys

from . import agent, ai, coach, db, emailer, tracker


def main(argv=None):
    p = argparse.ArgumentParser(prog="jobagent", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=8765)
    sc = sub.add_parser("scan")
    sc.add_argument("--no-email", action="store_true")
    sub.add_parser("status")
    sub.add_parser("proposals")
    imp = sub.add_parser("import-reviewed")
    imp.add_argument("path", help="Resume-bound JSON shortlist reviewed by Codex/Claude")
    ap = sub.add_parser("approve-proposal")
    ap.add_argument("digest")
    ap.add_argument("--agent", required=True, choices=["claude_cli", "codex"])
    j = sub.add_parser("jobs")
    j.add_argument("-n", type=int, default=15)
    for name in ("ask", "council"):
        a = sub.add_parser(name)
        a.add_argument("text", nargs="+")
        a.add_argument("--agent", default=None)
    c = sub.add_parser("cover")
    c.add_argument("job_id")
    c.add_argument("--agent", default=None)
    tl = sub.add_parser("tailor")
    tl.add_argument("job_id")
    tl.add_argument("--agent", default=None)
    del_p = sub.add_parser("delete")
    del_p.add_argument("job_ids", nargs="+")
    cl_p = sub.add_parser("cleanup")
    cl_p.add_argument("--days", type=int, default=30)
    cl_p.add_argument("--min-score", type=float, default=30)
    sub.add_parser("dedup")
    tr_p = sub.add_parser("tracker")
    tr_p.add_argument("--days", type=int, default=14)
    tr_p.add_argument("--limit", type=int, default=50)
    tr_p.add_argument("--dry-run", action="store_true")
    tr_p.add_argument("--agent", default=None)
    rd_p = sub.add_parser("radar")
    rd_p.add_argument("categories", nargs="*")
    rd_p.add_argument("--agent", default=None)
    vr_p = sub.add_parser("verify")
    vr_p.add_argument("--prune", action="store_true")
    vr_p.add_argument("--limit", type=int, default=200)
    vr_p.add_argument("--days", type=int, default=60)
    vr_p.add_argument("--source-agent", choices=["gemini"])
    vr_p.add_argument("--report")
    vr_p.add_argument("--generic-only", action="store_true")
    ch_p = sub.add_parser("cheatsheet")
    ch_p.add_argument("job_id")
    ch_p.add_argument("--agent", default=None)
    sal_p = sub.add_parser("salary")
    sal_p.add_argument("job_id", nargs="?", default=None)
    sal_p.add_argument("--offer", default="")
    sal_p.add_argument("--agent", default=None)
    st_p = sub.add_parser("stalled")
    st_p.add_argument("--days", type=int, default=7)
    exp_p = sub.add_parser("export")
    exp_p.add_argument("--id", type=int, default=None)
    exp_p.add_argument("--out", default=None)
    sub.add_parser("plan")
    sub.add_parser("weekly")
    sub.add_parser("setup", help="interactive first-run setup (CV, field pack, AI logins, email)")
    vw = sub.add_parser("verify-web", help="have Claude/Codex open postings and confirm they are real and open")
    vw.add_argument("--company", default="")
    vw.add_argument("--limit", type=int, default=10)
    vw.add_argument("--agent", choices=["claude_cli", "codex"], default=None)
    apf = sub.add_parser("apify", help="budget-guarded Apify scan (LinkedIn, WTTJ, HelloWork, APEC); --dry shows the plan only")
    apf.add_argument("--dry", action="store_true")
    apf.add_argument("--sources", nargs="*", default=None)
    apf.add_argument("--queries", nargs="*", default=None)
    apf.add_argument("--items", type=int, default=20)
    apf.add_argument("--cap", type=float, default=0.15, help="max USD per actor run")
    apf.add_argument("--agent", choices=["codex", "claude_cli"], default=None)
    apl = sub.add_parser("apply", help="apply to a job using your apply mode (assisted / email_auto / web_assist)")
    apl.add_argument("id"); apl.add_argument("--mode", choices=["assisted", "email_auto", "web_assist"])
    apl.add_argument("--to", help="application email to use instead of the one in the posting")
    apl.add_argument("--agent")
    sub.add_parser("apply-queue", help="list queued/sent application emails")
    sub.add_parser("apply-send", help="send queued application emails now (within the daily limit)")
    apc = sub.add_parser("apply-cancel", help="cancel a queued application email"); apc.add_argument("qid", type=int)
    lx = sub.add_parser("cv-latex", help="build a LaTeX CV (and PDF if LaTeX is installed), optionally tailored to a job")
    lx.add_argument("job_id", nargs="?"); lx.add_argument("--language", default="auto"); lx.add_argument("--agent")
    lx.add_argument("--no-pdf", action="store_true")
    op = sub.add_parser("open", help="start the server if needed and open the dashboard")
    op.add_argument("--port", type=int, default=8765)
    args = p.parse_args(argv)
    db.init()

    if args.cmd == "setup":
        return _setup_wizard()
    if args.cmd == "open":
        return _open(args.port)
    if args.cmd == "cv-latex":
        from . import latex_cv
        print(json.dumps(latex_cv.build(args.job_id, args.language, args.agent, compile=not args.no_pdf), indent=1))
        return
    if args.cmd.startswith("apply"):
        from . import apply
        if args.cmd == "apply":
            res = apply.start(args.id, args.mode, args.agent, args.to)
        elif args.cmd == "apply-queue":
            res = {"sent_today": apply.sent_today(), "queue": [{k: q[k] for k in ("id", "status", "to_addr", "subject", "title", "company", "error")} for q in apply.queue()]}
        elif args.cmd == "apply-send":
            res = apply.send_due()
        else:
            apply.cancel(args.qid); res = {"cancelled": args.qid}
        print(json.dumps(res, indent=1, default=str))
        return
    if args.cmd == "apify":
        from . import apify
        print(json.dumps(apify.scan(sources=tuple(args.sources or apify.ACTORS), queries=args.queries, items_per_run=args.items,
                                    cap_per_run=args.cap, agent=args.agent, dry=args.dry), indent=1, default=str))
        return
    if args.cmd == "verify-web":
        from . import verifier
        jobs = db.rows("SELECT * FROM jobs WHERE status NOT IN ('archived','rejected') AND kind IN ('job','internship','research') "
                       "AND lower(company) LIKE ? AND json_extract(extra,'$.verified') IS NULL ORDER BY score DESC LIMIT ?",
                       (f"%{args.company.lower()}%", args.limit))
        print(json.dumps(verifier.web_verify_batch(jobs, agent=args.agent), indent=1))
        return
    if args.cmd == "import-reviewed":
        from .reviewed_import import import_file
        print(json.dumps(import_file(args.path), indent=2))
    elif args.cmd == "proposals":
        from . import governance
        governance.setup()
        print(json.dumps(db.rows("SELECT digest,status,reviewer FROM job_proposals"), indent=2))
    elif args.cmd == "approve-proposal":
        from . import governance
        print(json.dumps(governance.review_proposal(args.digest, args.agent), indent=2))
    elif args.cmd == "serve":
        import uvicorn
        uvicorn.run("jobagent.server:app", host="127.0.0.1", port=args.port, log_level="warning")
    elif args.cmd == "scan":
        print(json.dumps(agent.scan(send_email=not args.no_email), indent=2))
    elif args.cmd == "status":
        print(json.dumps({"agents": ai.status(), "email": emailer.configured(),
                          "tracker": tracker.configured(),
                          "jobs": db.one("SELECT COUNT(*) n FROM jobs")["n"],
                          "resume": bool(db.master_resume())}, indent=2))
    elif args.cmd == "jobs":
        for r in db.rows("SELECT id,score,title,company,location,status FROM jobs ORDER BY score DESC LIMIT ?", (args.n,)):
            print(f"{r['score']:5.1f}  {r['title'][:50]:50}  {r['company'][:22]:22}  {r['status']:9} {r['id']}")
    elif args.cmd == "ask":
        text, used = coach.chat(" ".join(args.text), agent=args.agent)
        print(text + f"\n\n— {used}")
    elif args.cmd == "council":
        r = ai.council(" ".join(args.text))
        print(r["synthesis"] + f"\n\n— merged by {r['lead']} from " +
              ", ".join(f"{a['family']}={'ok' if a['agent'] else 'n/a'}" for a in r["answers"]))
    elif args.cmd == "cover":
        print(coach.cover_letter(args.job_id, agent=args.agent)[0])
    elif args.cmd == "tailor":
        text, used = coach.tailor_resume(args.job_id, agent=args.agent)
        print(text + f"\n\n— tailored by {used}")
    elif args.cmd == "delete":
        n = db.delete_jobs(args.job_ids)
        print(f"Deleted {n} job(s).")
    elif args.cmd == "cleanup":
        res = db.cleanup_jobs(max_days_rejected=args.days, min_score_new=args.min_score)
        print(f"Cleanup finished: {json.dumps(res, indent=2)}")
    elif args.cmd == "dedup":
        res = db.deduplicate_jobs()
        print(f"Deduplication finished: {json.dumps(res, indent=2)}")
    elif args.cmd == "tracker":
        res = tracker.sync_inbox(days=args.days, limit=args.limit, dry_run=args.dry_run, agent=args.agent)
        print(json.dumps(res, indent=2))
    elif args.cmd == "radar":
        from . import config, opportunities
        s = config.get_settings()
        picks = [x for x in opportunities.lanes() if x[0] in args.categories] if args.categories else opportunities.radar_next(s.get("radar_per_scan", 0), s.get("radar_pinned", []))
        got, errs = opportunities.run_radar(picks, s, print, agent_pref=args.agent)
        new = sum(db.upsert_job(o) for o in got)
        agent.rescore_all()
        print(f"Radar complete: {len(got)} found, {new} new. Errors: {len(errs)}")
    elif args.cmd == "verify":
        from . import verifier
        jobs = db.rows("SELECT * FROM jobs WHERE status!='archived' ORDER BY score DESC LIMIT ?", (args.limit,))
        if args.source_agent:
            from .governance import is_gemini
            jobs = [j for j in jobs if is_gemini(j)]
        if args.generic_only:
            jobs = [j for j in jobs if j.get("kind") in ("job", "internship", "research")
                    and verifier.is_generic_job_url(j["url"])[0]]
        res = verifier.verify_jobs_batch(jobs, prune=args.prune, max_days=args.days, log=print)
        if args.report:
            from pathlib import Path
            Path(args.report).write_text(json.dumps(res, indent=2))
        print(f"\nVerification summary: Scanned {res['scanned']} | Valid: {res['valid']} | Broken: {res['broken']} | Expired: {res['expired']} | Generic: {res['generic']} | Stale: {res['stale']} | Pruned: {res['pruned']}")
        for d in res["details"][:15]:
            print(f"  [{d['status']}] {d['title'][:40]} ({d['company'][:20]}) -> {d['reason']}")
        if res.get("pruned"):
            agent.rescore_all()
    elif args.cmd == "cheatsheet":
        text, used = coach.interview_cheatsheet(args.job_id, agent=args.agent)
        print(text + f"\n\n— generated by {used}")
    elif args.cmd == "salary":
        text, used = coach.salary_advisor(args.job_id, offer_details=args.offer, agent=args.agent)
        print(text + f"\n\n— generated by {used}")
    elif args.cmd == "stalled":
        items = tracker.stalled_applications(days_threshold=args.days)
        print(f"Stalled applications (>={args.days} days): {len(items)}")
        for it in items:
            print(f"  • {it['title']} @ {it['company']} (applied: {it['applied_at']}, {it['days_stalled']}d) -> {it['recommendation']}")
    elif args.cmd == "export":
        from pathlib import Path
        import time as _time
        from . import exporter
        if args.id:
            doc = db.one("SELECT * FROM documents WHERE id=?", (args.id,))
            content, title = doc["content"], doc["title"]
        else:
            r = db.master_resume()
            content, title = r["text"], "Master Resume"
        html_out = exporter.render_html_resume(content, title=title)
        out_path = args.out or f"resume_export_{int(_time.time())}.html"
        Path(out_path).write_text(html_out)
        print(f"Exported printable HTML resume to: {out_path}")
    elif args.cmd == "plan":
        print(coach.dev_plan()[0])
    elif args.cmd == "weekly":
        print(agent.weekly_coaching_email())


if __name__ == "__main__":
    sys.exit(main())


def _setup_wizard():
    """Terminal version of the web wizard (the web one at http://127.0.0.1:8765 does the same)."""
    import getpass
    from pathlib import Path
    from . import config, packs, setup
    from .server import _store_resume
    from .coach import parse_file
    print("JobAgent setup — data folder:", config.APP_HOME)
    if not db.master_resume():
        path = input("Path to your CV (PDF/DOCX/TXT): ").strip().strip("'\"")
        p = Path(path).expanduser()
        print("Reading CV and building your profile…")
        print(json.dumps(_store_resume(p.name, parse_file(p.name, p.read_bytes())).get("settings_updated"), indent=1))
    print("\nAI agents (use your existing subscriptions):")
    for k, a in setup.agents().items():
        print(f"  {'✓' if a['ready'] else '✗'} {a['name']}" + ("" if a["ready"] else f"\n      install: {a['install']}\n      log in:  {a['login']}"))
    built = packs.builtins()
    print("\nField pack:  0) generate from my CV with AI" + "".join(f"\n             {i}) {b['name']}" for i, b in enumerate(built, 1)))
    ch = input("Choose [0]: ").strip() or "0"
    if ch == "0":
        r = db.master_resume()
        config.save_settings({"pack": packs.generate_pack(r["text"])})
    else:
        config.save_settings({"pack": built[int(ch) - 1]["id"]})
    print("Pack:", packs.active().get("name"), "| lanes:", [l["label"] for l in packs.field_lanes()])
    if input("\nConnect an email account for alerts? [y/N] ").lower().startswith("y"):
        prov = input("Provider (gmail/outlook/icloud/other) [gmail]: ").strip() or "gmail"
        print(setup.EMAIL_PRESETS.get(prov, setup.EMAIL_PRESETS["other"])["help"])
        addr = input(f"Email address [{setup.account_email()}]: ").strip() or setup.account_email()
        pw = getpass.getpass("App password (not your normal password): ")
        print(setup.connect_email(prov, addr, pw))
    mode = input("\nApplying mode — assisted / email_auto / web_auto [assisted]: ").strip() or "assisted"
    country = input("Home country (e.g. France): ").strip()
    config.save_settings({"apply_mode": mode, "home_country": country, "setup_done": True})
    print("\nDone. Open http://127.0.0.1:8765 or run `jobagent scan`.")


def _open(port=8765):
    """Cross-platform launcher: start the server in the background if it isn't running, then open the browser."""
    import subprocess
    import time
    import urllib.request
    import webbrowser
    url = f"http://127.0.0.1:{port}"

    def up():
        try:
            urllib.request.urlopen(url + "/api/sections", timeout=1)
            return True
        except Exception:  # noqa: BLE001
            return False
    if not up():
        flags = 0x00000008 if sys.platform == "win32" else 0  # DETACHED_PROCESS on Windows
        subprocess.Popen([sys.executable, "-m", "jobagent.cli", "serve", "--port", str(port)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=sys.platform != "win32",
                         creationflags=flags)
        for _ in range(40):
            if up():
                break
            time.sleep(0.25)
    webbrowser.open(url)
