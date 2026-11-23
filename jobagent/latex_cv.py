"""LaTeX CV builder.

The AI only returns structured JSON taken from the stored resume (no invented facts); Python escapes every
string and renders a single-column A4 template that needs only standard packages (geometry, enumitem;
links use pdfTeX primitives, so no hyperref). If pdflatex/xelatex/latexmk is installed the .tex is compiled to PDF (shell-escape disabled),
otherwise only the .tex is written so it can be compiled anywhere (e.g. Overleaf).
"""
import json
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from . import ai, db

_ESC = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
        "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}


def esc(s):
    return "".join(_ESC.get(c, c) for c in str(s or ""))


def _url(u):
    u = str(u or "").strip()
    return u.replace("\\", "").replace("{", "").replace("}", "").replace("(", "%28").replace(")", "%29").replace("%", r"\%").replace("#", r"\#")


PREAMBLE = r"""\documentclass[10.5pt,a4paper]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage[margin=1.6cm]{geometry}
\usepackage{enumitem}
\ifdefined\pdfstartlink
  \newcommand{\href}[2]{\pdfstartlink attr{/Border[0 0 0]} user{/Subtype/Link/A<</S/URI/URI(#1)>>}#2\pdfendlink}
\else\newcommand{\href}[2]{#2}\fi
\setlist[itemize]{leftmargin=1.2em,itemsep=1pt,topsep=2pt}
\pagestyle{empty}
\setlength{\parindent}{0pt}
\newcommand{\cvsection}[1]{\vspace{8pt}{\large\bfseries\uppercase{#1}}\par\vspace{-4pt}\rule{\linewidth}{0.4pt}\par\vspace{2pt}}
\begin{document}
"""


def render(cv):
    """cv: {name, headline, contact: [str|{text,url}], summary, sections: [{title, entries: [{heading, org,
    place, dates, bullets: []}]}], skills: [{group, items: []}]} → LaTeX source."""
    out = [PREAMBLE, r"{\LARGE\bfseries " + esc(cv.get("name")) + r"}\par"]
    if cv.get("headline"):
        out.append(r"\vspace{2pt}{\large " + esc(cv["headline"]) + r"}\par")
    contact = []
    for c in cv.get("contact") or []:
        if isinstance(c, dict) and c.get("url"):
            contact.append(r"\href{" + _url(c["url"]) + "}{" + esc(c.get("text") or c["url"]) + "}")
        else:
            contact.append(esc(c if not isinstance(c, dict) else c.get("text")))
    if contact:
        out.append(r"\vspace{3pt}{\small " + r" \textbar{} ".join(contact) + r"}\par")
    if cv.get("summary"):
        out += [r"\cvsection{" + esc(cv.get("summary_title") or "Profile") + "}", esc(cv["summary"]) + r"\par"]
    for sec in cv.get("sections") or []:
        out.append(r"\cvsection{" + esc(sec.get("title")) + "}")
        for e in sec.get("entries") or []:
            left = r"\textbf{" + esc(e.get("heading")) + "}" + (", " + esc(e["org"]) if e.get("org") else "")
            right = ", ".join(esc(x) for x in (e.get("place"), e.get("dates")) if x)
            out.append(left + (r"\hspace{1em}\hfill\mbox{" + right + "}" if right else "") + r"\par")
            bullets = [b for b in e.get("bullets") or [] if str(b).strip()]
            if bullets:
                out.append(r"\begin{itemize}" + "".join(r"\item " + esc(b) for b in bullets) + r"\end{itemize}")
            out.append(r"\vspace{3pt}")
    if cv.get("skills"):
        out.append(r"\cvsection{" + esc(cv.get("skills_title") or "Skills") + "}")
        for g in cv["skills"]:
            out.append(r"\textbf{" + esc(g.get("group")) + r":} " + esc(", ".join(g.get("items") or [])) + r"\par")
    out.append(r"\end{document}" + "\n")
    return "\n".join(out)


def compiler():
    for c in ("pdflatex", "xelatex", "latexmk"):
        if shutil.which(c):
            return c
    return None


def compile_pdf(tex_path):
    """Compile next to the .tex; returns the PDF path or None. Never enables shell-escape."""
    c = compiler()
    if not c:
        return None
    tex_path = Path(tex_path).resolve()
    with tempfile.TemporaryDirectory() as tmp:
        if c == "latexmk":
            cmd = ["latexmk", "-pdf", "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape", f"-outdir={tmp}", str(tex_path)]
        else:
            cmd = [c, "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape", f"-output-directory={tmp}", str(tex_path)]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=tmp, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            raise RuntimeError("LaTeX compile timed out (a missing package may need installing, e.g. via the MiKTeX console).")
        pdf = Path(tmp) / (tex_path.stem + ".pdf")
        if r.returncode != 0 or not pdf.exists():
            log = Path(tmp) / (tex_path.stem + ".log")
            tail = log.read_text(errors="ignore")[-1500:] if log.exists() else r.stdout[-1500:]
            raise RuntimeError("LaTeX compile failed:\n" + tail)
        dest = tex_path.with_suffix(".pdf")
        shutil.copy(pdf, dest)
        return dest


def _structure(job=None, language="auto", agent=None):
    from .coach import resume_text, _job_block
    prompt = f"""Convert my resume into JSON for a one-to-two page CV{'' if language == 'auto' else ' written in ' + language}
{'tailored to the posting below (reorder and select bullets, surface matching skills that truly appear in my resume)' if job else ''}.
STRICT: use ONLY facts, roles, employers, degrees, dates, numbers and links that appear in my resume. Never invent anything.
Return ONLY JSON with this shape:
{{"name": "", "headline": "", "contact": ["city", {{"text": "email", "url": "mailto:..."}}, {{"text": "linkedin", "url": "https://..."}}],
 "summary_title": "Profile", "summary": "2-3 sentences",
 "sections": [{{"title": "Experience", "entries": [{{"heading": "role or degree", "org": "", "place": "", "dates": "", "bullets": [""]}}]}}],
 "skills_title": "Skills", "skills": [{{"group": "", "items": [""]}}]}}
{_job_block(job) if job else ''}
MY RESUME:
{resume_text()[:15000]}"""
    out, used = ai.ask(prompt, agent=agent, task="writing")
    return json.loads(re.search(r"\{.*\}", out, re.S).group(0)), used


def build(job_id=None, language="auto", agent=None, compile=True):
    from .config import ROOT
    from .extras import _slug
    job = db.one("SELECT * FROM jobs WHERE id=?", (job_id,)) if job_id else None
    if job_id and not job:
        raise ValueError("unknown job")
    cv, used = _structure(job, language, agent)
    name = f"{time.strftime('%Y%m%d')}_{_slug(job['company'])}_{_slug(job['title'])}" if job else f"{time.strftime('%Y%m%d')}_master"
    folder = ROOT / "applications" / name
    folder.mkdir(parents=True, exist_ok=True)
    tex = folder / "06_cv.tex"
    tex.write_text(render(cv))
    (folder / "06_cv.json").write_text(json.dumps(cv, indent=1, ensure_ascii=False))
    out = {"tex": str(tex), "agent": used, "pdf": None}
    if compile:
        try:
            pdf = compile_pdf(tex)
            out["pdf"] = str(pdf) if pdf else None
            if not pdf:
                out["note"] = "No LaTeX compiler found; compile the .tex (e.g. Overleaf) or install TeX Live / MacTeX."
        except Exception as e:  # noqa: BLE001
            out["error"] = str(e)
    db.save_doc("latex_cv", f"LaTeX CV – {job['title'] + ' @ ' + job['company'] if job else 'master'}", out["tex"], job_id, used)
    return out
