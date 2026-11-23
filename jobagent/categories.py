"""Opportunity categories ("tracks") and the rules that tag each item."""
import re

# id, label, glyph, rule. A rule matches on kind, title regex, or term hits in title+description.
# Universal lanes (any field). Field-specific lanes come from the active pack — see all_categories().
CATEGORIES = [
    {"id": "vc", "label": "Venture Capital", "glyph": "◆",
     "title": r"\b(venture|investment|investor|vc|principal|associate)\b",
     "terms": ["venture capital", "life sciences fund", "healthcare fund", "due diligence", "deal flow", "portfolio companies"]},
    {"id": "exec", "label": "CSO / CTO / CEO", "glyph": "♛", "exec": True,
     "title": r"\b(cto|cso|cmo|chief (scientific|technology|technical|medical|science|innovation|executive) officer|"
              r"co-?founder|cofondat(eur|rice)|associ[ée]e? (technique|scientifique)|"
              r"vp (of )?(r&d|research|engineering|science|imaging|technology)|vice president,? (r&d|research|engineering|science)|"
              r"head of (r&d|research|science|imaging|engineering|technology|innovation|physics)|"
              r"(director|directeur|directrice) (of )?(r&d|research|science|scientifique|technique|technical|engineering|imaging|innovation|r & d)|"
              r"(scientific|technical|r&d|research) director|responsable (r&d|scientifique|technique)|chief scientist)\b"},
    {"id": "innovation", "label": "Innovation & EIR", "glyph": "✶",
     "title": r"\b(innovation (manager|lead|officer|director|project|program|programme|strategist|scout)|"
              r"head of innovation|chief innovation|charg[ée]e? (de mission )?(d'|de l')?innovation|"
              r"responsable innovation|directeur (de l')?innovation|technology transfer|transfert de technologie|"
              r"valorisation|licensing (manager|officer)|venture (builder|architect|partner)|"
              r"entrepreneur[- ]in[- ]residence|\beir\b|intrapreneur|open innovation|tech scout)\b"},
    {"id": "founding", "label": "Founding Engineer / Scientist", "glyph": "⚑",
     "title": r"\b(founding|first (engineer|scientist|hire)|technical co-?founder|employee #?1)\b",
     "terms": ["founding engineer", "founding scientist", "founding team", "technical co-founder", "first engineering hire"]},
    {"id": "analyst", "label": "Analyst Roles", "glyph": "◬",
     "title": r"\b(analyst|analytics consultant|market intelligence|competitive intelligence|equity research|investment associate)\b"},
    {"id": "product", "label": "Product Roles", "glyph": "▲",
     "title": r"\b(product (specialist|manager|owner|lead|scientist|marketing)|application specialist|clinical specialist|application scientist|clinical application|solutions? (specialist|engineer|scientist))\b"},
    {"id": "internship", "label": "Internships (Europe)", "glyph": "◇", "kinds": ["internship"],
     "title": r"\b(intern|internship|stage|stagiaire|alternance|apprenti|praktikum|praktikant|werkstudent|trainee|placement)\b"},
    {"id": "research", "label": "Research Opportunities", "glyph": "⌬",
     "kinds": ["research"],
     "title": r"\b(postdoc|post-doc|post-doctoral|postdoctoral|research scientist|researcher|research fellow|research engineer|phd|scientist)\b"},
    {"id": "collab", "label": "Postdoc Collaborators (EU)", "glyph": "⚭", "kinds": ["collaborator"]},
    {"id": "targets", "label": "Spontaneous Targets", "glyph": "➶", "kinds": ["target"]},
    {"id": "intel", "label": "Company Intelligence", "glyph": "◉", "kinds": ["intel"]},
    {"id": "conference", "label": "Events & Conferences", "glyph": "✺", "kinds": ["conference", "event"]},
    {"id": "trends", "label": "What's Hot", "glyph": "🔥", "kinds": ["trend"]},
    {"id": "hackathon", "label": "Hackathons (online)", "glyph": "⚡", "kinds": ["hackathon"],
     "terms": ["hackathon", "datathon", "challenge"]},
    {"id": "indiv_funding", "label": "Individual Researcher Funding", "glyph": "✦",
     "kinds": ["funding"], "need_terms": ["individual", "independent", "researcher", "personal grant", "unaffiliated",
                                          "fellowship", "msca", "erc", "starting grant", "travel grant", "microgrant", "experiment.com"]},
    {"id": "fellowship", "label": "Fellowships", "glyph": "✧", "kinds": ["fellowship"],
     "terms": ["fellowship", "msca", "marie skłodowska", "marie curie", "fellow program"]},
    {"id": "startup_funding", "label": "Startup / Innovation Funding", "glyph": "⬢",
     "kinds": ["startup_funding"],
     "terms": ["eic accelerator", "eic pathfinder", "eic transition", "accelerator", "incubator", "bpifrance",
               "i-nov", "innovation grant", "seed funding", "startup grant", "sme instrument", "proof of concept"]},
    {"id": "remote_jobs", "label": "Remote Roles (EU/Global)", "glyph": "🌐",
     "terms": ["remote", "fully remote", "télétravail", "home office", "anywhere in europe", "remote in europe"]},
]
def all_categories():
    """Field lanes from the active pack first, then the universal lanes (with pack label overrides)."""
    from . import packs
    pack = packs.active()
    out = [dict(l) for l in pack.get("lanes", [])]
    ids = {l["id"] for l in out}
    for c in CATEGORIES:
        if c["id"] not in ids:
            out.append({**c, "label": packs.label(c["id"], c["label"], pack)})
    return out


class _ById(dict):
    def __missing__(self, key):
        return {c["id"]: c for c in all_categories()}[key]


BY_ID = _ById()


def _hit(term, text):
    return re.search(r"(?<![a-z0-9])" + re.escape(term.strip()) + r"(?![a-z0-9])", text) is not None \
        if term.strip() == term else term in text


def tag(job: dict) -> list:
    from .scoring import translate_fr
    title = translate_fr(job.get("title") or "")
    text = f" {title} {(job.get('company') or '').lower()} {translate_fr((job.get('description') or '')[:6000])} "
    kind = job.get("kind") or "job"
    from . import packs
    pack = packs.active()
    domain, core = pack.get("domain_words") or [], packs.core_lanes(pack)
    out = []
    for c in all_categories():
        ok = False
        if kind in c.get("kinds", []):
            ok = True if not c.get("need_terms") else any(_hit(t, text) for t in c["need_terms"])
        if not ok and c.get("title") and re.search(c["title"], title):
            ok = True
        if not ok and c.get("terms"):
            ok = sum(_hit(t, text) for t in c["terms"]) >= (1 if any(_hit(t, title) for t in c["terms"]) else 2)
        if not ok and c.get("all_of"):
            ok = all(any(t in text for t in group) for group in c["all_of"])
        if c["id"] in ("exec", "founding", "analyst", "product", "innovation") and kind not in ("job", "internship"):
            ok = False
        if ok and c.get("exec") and domain and not any(w in text for w in domain):
            ok = False  # leadership lane = technical/scientific leadership in the user's field, not any "director"
        if c["id"] == "internship" and kind not in ("job", "internship", "research"):
            ok = False
        if kind in ("intel", "target", "conference", "event", "trend") and c["id"] not in ("intel", "targets", "conference", "trends") \
                and not (kind in ("conference", "event") and c["id"] in core):
            ok = False
        if ok:
            out.append(c["id"])
    return out
