"""Optional knowledge base: an Obsidian vault (or any folder of Markdown notes).

Read-only by default: notes are indexed and the most relevant ones are added as context to the coach,
the template gap plan and letters. Export writes ONLY inside <vault>/JobAgent/ and only when asked.
"""
import re
import time
from pathlib import Path

from .config import get_settings

_CACHE = {"path": None, "ts": 0, "notes": []}
SKIP_DIRS = {".obsidian", ".trash", ".git", "node_modules"}
STOP = set("the and for with that this from have are was were will your you our not but can all any into about "
           "les des une pour avec dans sur pas que qui est sont".split())


def vault():
    p = (get_settings().get("kb_path") or "").strip()
    return Path(p).expanduser() if p else None


def _words(t):
    return [w for w in re.findall(r"[a-zà-ü0-9][a-zà-ü0-9+#\-]{2,}", t.lower()) if w not in STOP]


def index(force=False, max_notes=4000):
    v = vault()
    if not v or not v.is_dir():
        return []
    if not force and _CACHE["path"] == str(v) and time.time() - _CACHE["ts"] < 600:
        return _CACHE["notes"]
    notes = []
    for f in v.rglob("*.md"):
        if any(part in SKIP_DIRS for part in f.relative_to(v).parts) or (f.relative_to(v).parts[:1] == ("JobAgent",)):
            continue
        try:
            text = f.read_text(errors="ignore")[:20000]
        except OSError:
            continue
        tags = set(re.findall(r"(?<!\w)#([\w/-]+)", text))
        notes.append({"path": str(f.relative_to(v)), "title": f.stem, "tags": sorted(tags)[:12], "text": text,
                      "words": set(_words(f.stem + " " + text))})
        if len(notes) >= max_notes:
            break
    _CACHE.update(path=str(v), ts=time.time(), notes=notes)
    return notes


def search(query, k=4):
    q = set(_words(query))
    if not q:
        return []
    scored = []
    for n in index():
        hit = len(q & n["words"])
        if hit:
            scored.append((hit + 2 * len(q & set(_words(n["title"]))), n))
    scored.sort(key=lambda x: -x[0])
    return [{"path": n["path"], "title": n["title"], "tags": n["tags"], "excerpt": n["text"][:1500]} for _, n in scored[:k]]


def context(query, k=3, chars=3500):
    """A compact 'MY NOTES' block for prompts (empty when no vault is linked)."""
    hits = search(query, k)
    if not hits:
        return ""
    body = "\n\n".join(f"### {h['title']} ({h['path']})\n{h['excerpt']}" for h in hits)
    return "\n\nMY NOTES (from my knowledge base — use only if relevant, never contradict my resume):\n" + body[:chars]


def status():
    v = vault()
    if not v:
        return {"linked": False}
    if not v.is_dir():
        return {"linked": False, "error": f"folder not found: {v}"}
    notes = index(force=True)
    return {"linked": True, "path": str(v), "notes": len(notes), "is_obsidian": (v / ".obsidian").is_dir()}


def export_doc(title, content, kind="note"):
    """Write a generated document into <vault>/JobAgent/<kind>/ (the only place JobAgent ever writes)."""
    v = vault()
    if not v or not v.is_dir():
        raise ValueError("No knowledge-base folder linked (Config → Knowledge base).")
    folder = v / "JobAgent" / re.sub(r"[^\w-]+", "_", kind)
    folder.mkdir(parents=True, exist_ok=True)
    name = re.sub(r'[\\/:*?"<>|#^\[\]]+', " ", title).strip()[:90] or "note"
    path = folder / f"{name}.md"
    path.write_text(f"---\nsource: JobAgent\nkind: {kind}\ncreated: {time.strftime('%Y-%m-%d %H:%M')}\ntags: [jobagent, {kind}]\n---\n\n{content}\n")
    return str(path.relative_to(v))
