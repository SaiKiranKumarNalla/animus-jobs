"""Fast local matching: resume <-> job keyword overlap and a rule-based ATS check."""
import re
from collections import Counter

# Broad skill lexicon (tech, data, research, biomedical, business). Extend freely.
LEXICON = """
python r matlab c c++ c# java javascript typescript sql nosql bash julia scala go rust swift kotlin
pandas numpy scipy scikit-learn sklearn pytorch tensorflow keras jax xgboost lightgbm opencv
machine learning deep learning computer vision nlp natural language processing llm llms
generative ai rag transformers reinforcement learning statistics biostatistics bayesian
data analysis data science data engineering data visualization etl spark hadoop airflow dbt
tableau power bi excel looker matplotlib seaborn plotly ggplot jupyter
aws azure gcp google cloud docker kubernetes terraform ci/cd git github linux mlops
fastapi flask django react node.js rest api graphql microservices
medical imaging image processing image segmentation segmentation registration mri ct pet
ultrasound dicom nifti itk simpleitk 3d slicer slicer custusx vtk monai nnu-net u-net
radiology neuroimaging fmri dti spectroscopy mrs dmi biomedical engineering signal processing
medical devices iso 13485 iec 62304 fda mdr regulatory clinical trials gcp clinical research
bioinformatics genomics biology neuroscience physics electronics hardware embedded
unity c# unreal augmented reality virtual reality surgical navigation robotics
research publications phd postdoc latex scientific writing grant writing
project management agile scrum jira stakeholder management product management
consulting strategy venture capital due diligence market research financial modeling
leadership mentoring teaching communication presentation french english spanish german
""".split("\n")
# multi-word phrases are matched first, then single tokens
PHRASES = \
    ["machine learning", "deep learning", "computer vision", "natural language processing",
     "generative ai", "reinforcement learning", "data analysis", "data science", "data engineering",
     "data visualization", "google cloud", "power bi", "rest api", "medical imaging",
     "image processing", "image segmentation", "3d slicer", "biomedical engineering",
     "signal processing", "medical devices", "iso 13485", "iec 62304", "clinical trials",
     "clinical research", "augmented reality", "virtual reality", "surgical navigation",
     "scientific writing", "grant writing", "project management", "stakeholder management",
     "product management", "venture capital", "due diligence", "market research",
     "financial modeling", "scikit-learn", "nnu-net", "u-net", "ci/cd", "node.js"]
# single words that only make sense inside a phrase ("machine", "medical") are dropped
_FRAGMENTS = {w for p in PHRASES for w in p.split()} - {"segmentation", "slicer", "research"}
SINGLES = set(" ".join(LEXICON).split()) - _FRAGMENTS - {"c", "r", "go"}
STOP = set("""a an the and or of to in for on with at by from as is are be this that we you your our
will can our their they it its into about over under more most other such than then also using
work working team teams role roles experience years year job jobs company including strong
ability skills skill knowledge required preferred plus etc new world help join who what how""".split())


def expand_terms(items):
    """'Image Segmentation (3D Slicer, ITK-SNAP)' -> ['image segmentation', '3d slicer', 'itk-snap']."""
    out = []
    for it in items or []:
        it = it.lower()
        inner = re.findall(r"\(([^)]*)\)", it)
        core = re.sub(r"\([^)]*\)", " ", it)
        for part in re.split(r"[,/&]| and | – | - ", core + "," + ",".join(inner)):
            part = part.strip(" .")
            if 1 < len(part) <= 40:
                out.append(part)
    return list(dict.fromkeys(out))


def simple_roles(roles):
    """'Research Scientist – Medical Imaging (PET/CT)' -> 'Research Scientist Medical Imaging'."""
    return [re.sub(r"\s+", " ", re.sub(r"\([^)]*\)|[–—-]| / ", " ", r)).strip() for r in roles or []]


# French -> English equivalents, appended to text so French postings match English profiles and lanes
FR_EN = {
    "tep": "pet", "tep-tdm": "pet/ct", "tep/tdm": "pet/ct", "tdm": "ct", "scanner": "ct", "irm": "mri",
    "imagerie médicale": "medical imaging", "imagerie": "imaging", "médecine nucléaire": "nuclear medicine",
    "radiopharmaceutique": "radiopharmaceutical", "dosimétrie": "dosimetry", "physicien médical": "medical physicist",
    "physique médicale": "medical physics", "dispositif médical": "medical device", "dispositifs médicaux": "medical devices",
    "ingénieur": "engineer", "ingénieure": "engineer", "chercheur": "researcher", "chercheuse": "researcher",
    "chargé de recherche": "research scientist", "post-doctorat": "postdoc", "postdoctorat": "postdoc",
    "docteur": "phd", "doctorat": "phd", "thèse": "phd", "apprentissage automatique": "machine learning",
    "apprentissage profond": "deep learning", "intelligence artificielle": "artificial intelligence ai",
    "traitement d'images": "image processing", "segmentation d'images": "image segmentation",
    "simulation numérique": "simulation", "jumeau numérique": "digital twin", "modélisation": "modeling",
    "directeur scientifique": "chief scientific officer cso", "directrice scientifique": "chief scientific officer cso",
    "directeur technique": "chief technology officer cto", "directrice technique": "chief technology officer cto",
    "directeur r&d": "head of r&d", "responsable r&d": "head of r&d", "cofondateur": "co-founder",
    "chef de produit": "product manager", "spécialiste produit": "product specialist",
    "ingénieur d'application": "application specialist", "spécialiste d'application": "application specialist",
    "analyste": "analyst", "stage": "internship", "stagiaire": "intern", "alternance": "internship apprenticeship",
    "santé": "health", "médical": "medical", "réglementaire": "regulatory", "essais cliniques": "clinical trials",
}


def translate_fr(text):
    t = (text or "").lower()
    extra = [en for fr, en in FR_EN.items() if re.search(r"(?<![a-zà-ü])" + re.escape(fr) + r"(?![a-zà-ü])", t)]
    return t + (" " + " ".join(extra) if extra else "")


def norm(text):
    return re.sub(r"\s+", " ", (text or "").lower())


def has(term, text):
    return re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", text) is not None


def extract_skills(text):
    t = norm(text)
    found = [p for p in PHRASES if has(p, t)]
    found += [s for s in SINGLES if has(s, t)]
    if re.search(r"(?:^|[ ,(/])r(?:[ ,)/]|$)", t) and re.search(r"\b(rstudio|tidyverse|ggplot|cran)\b|[ ,(/]r[,/)]", t):
        found.append("r")
    return sorted(set(found))


def top_terms(text, n=25):
    """Frequent meaningful words in a job description (catches domain terms not in lexicon)."""
    words = re.findall(r"[a-z][a-z+#.\-]{2,}", norm(text))
    c = Counter(w for w in words if w not in STOP)
    return [w for w, _ in c.most_common(n)]


def match(resume_text, job, settings):
    """Score 0-100: skill overlap, title fit, location fit, exclusions."""
    r = norm(resume_text)
    jd = norm(translate_fr(job.get("title", "") + " " + job.get("description", "") + " " + " ".join(job.get("tags", []) if isinstance(job.get("tags"), list) else [])))
    title = norm(translate_fr(job.get("title", "")))
    job_sk = extract_skills(jd)
    kw = expand_terms(settings.get("keywords", []))
    res_sk = set(extract_skills(r)) | set(kw)
    matched = [s for s in job_sk if s in res_sk]
    missing = [s for s in job_sk if s not in res_sk]
    skill = len(matched) / max(len(job_sk), 4)
    roles = [x.lower() for x in simple_roles(settings.get("target_roles", []))]
    role_hits = max((sum(w in title for w in rl.split()) / len(rl.split()) for rl in roles if rl.split()), default=0.3)
    kw_fit = sum(has(k, jd) for k in kw) / max(len(kw), 1) if kw else skill
    locs = [l for l in expand_terms(settings.get("locations", [])) if l not in ("remote", "europe")]
    loc_text = norm(job.get("location", ""))
    loc_fit = 1.0 if not locs else (1.0 if any(l in loc_text for l in locs) else
                                    (0.8 if job.get("remote") and settings.get("remote_ok") else 0.3))
    score = 100 * (0.4 * skill + 0.3 * role_hits + 0.15 * kw_fit + 0.15 * loc_fit)
    leadership = re.search(r"\b(cto|cso|chief|co-?founder|founding|vp|vice president|head of|director)\b", title)
    if any(x.strip() and re.search(r"(?<![a-z])" + re.escape(x.strip().lower()) + r"(?![a-z])", title)
           for x in settings.get("exclude_keywords", [])) and not leadership:
        score *= 0.4  # exclusions never hit the leadership roles you target
    return round(min(score, 100), 1), matched, missing


SECTIONS = ["experience", "education", "skills", "summary|profile|about", "projects",
            "publications|research", "certifications|certificates", "languages"]


def ats_check(resume_text, jd_text=""):
    """Rule-based ATS report (no AI needed)."""
    r = resume_text or ""
    rn = norm(r)
    report = {"checks": [], "score": 0}

    def chk(name, ok, tip, weight=1):
        report["checks"].append({"name": name, "ok": bool(ok), "tip": tip, "weight": weight})

    words = len(r.split())
    chk("Length", 350 <= words <= 1100, f"{words} words. Aim for 400-900 (1-2 pages).")
    chk("Email present", re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", r), "Add a professional email in the header.", 2)
    chk("Phone present", re.search(r"\+?\d[\d\s().-]{7,}", r), "Add a phone number with country code.")
    chk("LinkedIn / portfolio", "linkedin" in rn or "github" in rn, "Add LinkedIn and GitHub/portfolio URLs.")
    for s in ["experience", "education", "skills"]:
        chk(f"'{s.title()}' section", re.search(rf"\b({s})\b", rn), f"Use a standard '{s.title()}' heading.", 2)
    bullets = len(re.findall(r"^\s*[•\-\*▪●]", r, re.M))
    chk("Bulleted achievements", bullets >= 6, f"{bullets} bullets found. Use 3-6 bullets per role.")
    nums = len(re.findall(r"\d+\s?%|\d+[kKmM]\b|\$\s?\d|€\s?\d|\b\d{2,}\b", r))
    chk("Quantified impact", nums >= 5, f"{nums} numbers found. Quantify results (%, time saved, scale).", 2)
    verbs = ["led", "built", "developed", "designed", "implemented", "improved", "reduced",
             "increased", "launched", "managed", "created", "analyzed", "optimized", "delivered"]
    vcount = sum(has(v, rn) for v in verbs)
    chk("Strong action verbs", vcount >= 5, f"{vcount} distinct action verbs. Start bullets with verbs.")
    weak = [w for w in ["responsible for", "duties included", "helped with", "worked on"] if w in rn]
    chk("No weak phrasing", not weak, "Replace: " + ", ".join(weak) if weak else "Good.")
    chk("No tables/columns artifacts", r.count("\t") < 15 and r.count("|") < 10,
        "Avoid tables, text boxes and multi-column layouts; ATS parsers scramble them.")
    if jd_text:
        jd_sk = extract_skills(jd_text)
        res_sk = set(extract_skills(r))
        matched = [s for s in jd_sk if s in res_sk]
        missing = [s for s in jd_sk if s not in res_sk]
        terms = [t for t in top_terms(jd_text, 30) if t not in rn][:12]
        cov = len(matched) / max(len(jd_sk), 1)
        report.update({"matched": matched, "missing": missing, "jd_terms_missing": terms,
                       "keyword_coverage": round(100 * cov)})
        chk("Keyword coverage ≥ 70%", cov >= 0.7,
            f"{round(100*cov)}% of the job's skills appear. Add the truthful ones: " + ", ".join(missing[:10]), 4)
    tot = sum(c["weight"] for c in report["checks"])
    got = sum(c["weight"] for c in report["checks"] if c["ok"])
    report["score"] = round(100 * got / tot)
    return report
