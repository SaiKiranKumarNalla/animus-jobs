"""Printable HTML/PDF resume exporter with clean typography and ATS compliance.
Renders master resume or tailored resume into print-optimized HTML.
"""
import html
import json
import re
from pathlib import Path

from . import db
from .config import get_settings


def _parse_resume_sections(text: str) -> dict:
    """Extract standard sections from markdown or plain text resume."""
    sections = {
        "name": "",
        "contact": "",
        "summary": "",
        "skills": [],
        "experience": [],
        "education": [],
        "publications": [],
        "projects": [],
        "raw": text,
    }

    lines = [l.strip() for l in text.split("\n")]
    if not lines:
        return sections

    # First non-empty header usually has the name
    for l in lines[:5]:
        if l.startswith("# "):
            sections["name"] = l.lstrip("# ").strip()
            break
        elif not sections["name"] and len(l) > 3 and not l.startswith(("-", "*", "•", "http", "@")):
            sections["name"] = l
            break

    # Look for contact line (email, phone, linkedin, location)
    for l in lines[:10]:
        if "@" in l or "linkedin" in l.lower() or "github" in l.lower():
            sections["contact"] = l.lstrip("•-*# ").strip()
            break

    # Split into sections by H2 / H3 headers
    current_sec = "summary"
    sec_content = {current_sec: []}

    for l in lines:
        if re.match(r"^#{1,3}\s+", l):
            header = re.sub(r"^#{1,3}\s+", "", l).lower().strip()
            if any(k in header for k in ("skill", "competenc", "technolog")):
                current_sec = "skills"
            elif any(k in header for k in ("experience", "work", "employment", "career", "recherche")):
                current_sec = "experience"
            elif any(k in header for k in ("education", "degree", "formation", "academic")):
                current_sec = "education"
            elif any(k in header for k in ("publication", "paper", "article", "conference")):
                current_sec = "publications"
            elif any(k in header for k in ("project", "projet", "portfolio")):
                current_sec = "projects"
            elif any(k in header for k in ("summary", "profile", "about", "profil")):
                current_sec = "summary"
            else:
                current_sec = header
            sec_content.setdefault(current_sec, [])
        else:
            sec_content[current_sec].append(l)

    sections["sec_content"] = {k: "\n".join(v).strip() for k, v in sec_content.items() if v}
    return sections


def render_html_resume(resume_text: str, template: str = "industry", title: str = "Resume") -> str:
    """Renders a standalone, elegant HTML page optimized for screen preview and print (Save as PDF)."""
    try:
        import markdown
        body_html = markdown.markdown(resume_text, extensions=["extra", "tables"])
    except Exception:
        escaped = html.escape(resume_text)
        escaped = re.sub(r"^### (.*?)$", r"<h3>\1</h3>", escaped, flags=re.MULTILINE)
        escaped = re.sub(r"^## (.*?)$", r"<h2>\1</h2>", escaped, flags=re.MULTILINE)
        escaped = re.sub(r"^# (.*?)$", r"<h1>\1</h1>", escaped, flags=re.MULTILINE)
        escaped = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", escaped)
        escaped = re.sub(r"\*(.*?)\*", r"<em>\1</em>", escaped)
        escaped = re.sub(r"^- (.*?)$", r"<li>\1</li>", escaped, flags=re.MULTILINE)
        body_html = f"<div style='white-space:pre-wrap'>{escaped}</div>"
    s = get_settings()
    user_name = s.get("name") or "Your Name"

    css = """
    :root {
      --primary: #0f172a;
      --secondary: #334155;
      --accent: #0284c7;
      --bg: #ffffff;
      --text: #1e293b;
      --border: #e2e8f0;
      --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: #f1f5f9;
      color: var(--text);
      font-family: var(--font-sans);
      font-size: 10.5pt;
      line-height: 1.5;
      padding: 20px;
    }
    .page-container {
      max-width: 850px;
      margin: 0 auto;
      background: #ffffff;
      padding: 40px 50px;
      box-shadow: 0 4px 20px rgba(0,0,0,0.08);
      border-radius: 4px;
    }
    .toolbar {
      max-width: 850px;
      margin: 0 auto 16px auto;
      display: flex;
      justify-content: space-between;
      align-items: center;
      background: #0f172a;
      color: #ffffff;
      padding: 10px 18px;
      border-radius: 6px;
    }
    .toolbar button {
      background: #0284c7;
      color: #fff;
      border: none;
      padding: 7px 14px;
      font-weight: 600;
      font-size: 13px;
      border-radius: 4px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .toolbar button:hover { background: #0369a1; }
    .toolbar a { color: #94a3b8; text-decoration: none; font-size: 13px; }
    .toolbar a:hover { color: #ffffff; }

    /* Resume typography */
    h1 {
      font-size: 22pt;
      font-weight: 700;
      color: var(--primary);
      letter-spacing: -0.02em;
      margin-bottom: 4px;
      border-bottom: 2px solid var(--accent);
      padding-bottom: 6px;
    }
    h2 {
      font-size: 12.5pt;
      font-weight: 700;
      color: var(--primary);
      text-transform: uppercase;
      letter-spacing: 0.05em;
      margin-top: 18px;
      margin-bottom: 8px;
      border-bottom: 1px solid var(--border);
      padding-bottom: 4px;
    }
    h3 {
      font-size: 11pt;
      font-weight: 600;
      color: var(--secondary);
      margin-top: 10px;
      margin-bottom: 3px;
    }
    p { margin-bottom: 8px; }
    ul { margin-left: 20px; margin-bottom: 10px; }
    li { margin-bottom: 3.5px; }
    strong { color: var(--primary); font-weight: 600; }
    em { color: var(--secondary); }
    a { color: var(--accent); text-decoration: none; }
    table { width: 100%; border-collapse: collapse; margin-bottom: 12px; }
    th, td { padding: 6px 10px; border: 1px solid var(--border); text-align: left; }
    th { background: #f8fafc; font-weight: 600; }

    /* Print styles */
    @media print {
      body { background: #fff; padding: 0; font-size: 10pt; line-height: 1.45; }
      .toolbar { display: none !important; }
      .page-container {
        padding: 0;
        box-shadow: none;
        max-width: 100%;
      }
      h2 { page-break-after: avoid; break-after: avoid; margin-top: 14px; }
      h3 { page-break-after: avoid; break-after: avoid; }
      ul, p, table { page-break-inside: auto; }
      li { page-break-inside: avoid; break-inside: avoid; }
      @page {
        margin: 1.5cm 1.5cm 1.5cm 1.5cm;
      }
    }
    """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{html.escape(title)} — {html.escape(user_name)}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>{css}</style>
</head>
<body>
  <div class="toolbar">
    <div><b>JobAgent Exporter</b> · <span style="color:#38bdf8">{html.escape(title)}</span></div>
    <div style="display:flex;gap:12px;align-items:center">
      <button onclick="window.print()">🖨 Print / Save as PDF</button>
      <a href="javascript:window.close()">✕ Close</a>
    </div>
  </div>
  <div class="page-container">
    {body_html}
  </div>
</body>
</html>"""
