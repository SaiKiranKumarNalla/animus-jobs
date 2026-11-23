"""Fill a throwaway data folder with fictional opportunities, to try the dashboard or take screenshots.

Usage:
    JOBAGENT_HOME=/tmp/animus-demo python scripts/demo_seed.py
    JOBAGENT_HOME=/tmp/animus-demo jobagent serve

Every company, URL and posting below is invented. Nothing touches your real data folder.
"""
import os
import sys
import time
from pathlib import Path

if not os.environ.get("JOBAGENT_HOME"):
    sys.exit("Set JOBAGENT_HOME to an empty demo folder first (your real data is never used).")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jobagent import db  # noqa: E402

DEMO = [
    # title, company, location, remote, score, status, tags, salary, matched, missing
    ("Research Scientist, Quantitative PET", "Northwind Imaging", "Paris, France", 0, 92, "saved",
     "imaging,pet,research", "55-65k EUR", "PET physics, image reconstruction, Python", "regulatory exposure"),
    ("AI Engineer, LLM Agents for Clinical Workflows", "Contoso Health", "Lyon, France", 1, 88, "new",
     "ai,llm,agents", "50-60k EUR", "Python, agentic workflows, healthcare data", "production MLOps"),
    ("Postdoc, Physics-Informed Neural Networks", "Fabrikam Institute", "Grenoble, France", 0, 85, "new",
     "research,pinn,simulation", "", "PDEs, simulation, PyTorch", "JAX"),
    ("Medical Imaging Software Engineer", "Tailspin Medical", "Toulouse, France", 1, 81, "applied",
     "imaging,software", "48-58k EUR", "DICOM, 3D processing, C++/Python", ""),
    ("Computer Vision Engineer, 3D Reconstruction", "Wide World Robotics", "Remote (EU)", 1, 76, "new",
     "cv,3d", "", "3D geometry, PyTorch", "SLAM"),
    ("Data Scientist, Medical Devices", "Adventure Works Medtech", "Bordeaux, France", 0, 71, "new",
     "data,medtech", "45-52k EUR", "statistics, Python", "SQL at scale"),
    ("Simulation Engineer, CFD Surrogates", "Litware Marine", "Brest, France", 0, 68, "later",
     "cfd,surrogates", "", "OpenFOAM, surrogate models", "marine hydrodynamics"),
    ("Marie Curie Postdoctoral Fellowship (call)", "EU Research Programme", "Europe", 0, 83, "new",
     "fellowship,academia", "", "PhD, publications, mobility", "host PI not chosen"),
]


def main():
    db.init()
    now = time.time()
    added = 0
    for i, (title, company, loc, remote, score, status, tags, salary, matched, missing) in enumerate(DEMO):
        jid = f"demo:{i:03d}"
        ok = db.upsert_job({
            "id": jid, "source": "demo", "title": title, "company": company, "location": loc,
            "remote": remote, "url": f"https://example.org/demo/jobs/{i:03d}-{company.split()[0].lower()}",
            "description": f"Fictional demo posting at {company}.", "salary": salary, "tags": tags,
            "posted_at": time.strftime("%Y-%m-%d", time.localtime(now - i * 86400)),
            "found_at": now - i * 3600, "score": score, "matched": matched, "missing": missing,
        })
        if ok:
            db.execute("UPDATE jobs SET score=?, status=? WHERE id=?", (score, status, jid))
            added += 1
    print(f"Demo data ready: {added} fictional opportunities in {os.environ['JOBAGENT_HOME']}")


if __name__ == "__main__":
    main()
