"""Job-alert email reader: turns LinkedIn / APEC / Indeed / Glassdoor / Welcome to the Jungle alert emails
into jobs. Read-only IMAP (BODY.PEEK, mailbox opened read-only), and only messages from these senders."""
import email
import imaplib
import json
import os
import re
import time
from email.header import decode_header
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlparse

from . import config  # noqa: F401  (loads .env)
from .config import DATA
from .sources import _job

STATE = DATA / "alerts_state.json"

# sender domain -> (source label, regex for job links)
SENDERS = {
    "linkedin.com": ("linkedin", r"linkedin\.com/(comm/)?jobs/view/(\d+)"),
    "apec.fr": ("apec", r"apec\.fr/.*(detail-offre|offres-emploi-cadres)"),
    "indeed.com": ("indeed", r"indeed\.[a-z.]+/(rc/clk|viewjob|pagead/clk|m/viewjob)|jk=[0-9a-f]{8,}|cts\.indeed\.com/v3/"),
    "indeed.fr": ("indeed", r"indeed\.[a-z.]+/(rc/clk|viewjob|pagead/clk|m/viewjob)|jk=[0-9a-f]{8,}|cts\.indeed\.com/v3/"),
    "glassdoor": ("glassdoor", r"glassdoor\.[a-z.]+/(job-listing|partner/joblisting|Job/|GD_JOB)"),
    "welcometothejungle.com": ("wttj", r"welcometothejungle\.com/.*/jobs/"),
}
NOISE = re.compile(r"^(view job|voir l'offre|apply|postuler|see all jobs|voir toutes|unsubscribe|se désabonner|"
                   r"manage alerts?|gérer|easy apply|candidature simplifiée|new|nouveau|promoted|sponsorisé|"
                   r"actively recruiting|\d+ (applicants|candidats)|be an early applicant|voir l'emploi|"
                   r"ne correspond pas|en savoir plus|modifier le profil|suspendre ces emails|centre d'aide|"
                   r"politique de confidentialité|conditions d'utilisation|help cent(er|re)|privacy policy|"
                   r"terms|edit (profile|alert)|not interested|view similar jobs|voir les offres similaires)$", re.I)


class _Links(HTMLParser):
    """Collects (href, anchor text) plus the plain-text stream so we can read lines after each link."""

    def __init__(self):
        super().__init__()
        self.items, self._href, self._buf, self.stream = [], None, [], []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href, self._buf = dict(attrs).get("href", ""), []

    def handle_data(self, data):
        t = " ".join(data.split())
        if t:
            self.stream.append(t)
            if self._href is not None:
                self._buf.append(t)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.items.append((self._href, " ".join(self._buf).strip(), len(self.stream)))
            self._href = None


def _decode(s):
    out = ""
    for part, enc in decode_header(s or ""):
        out += part.decode(enc or "utf-8", errors="ignore") if isinstance(part, bytes) else part
    return out


def _clean_url(u):
    """Unwrap tracking redirects and drop tracking params where possible."""
    q = parse_qs(urlparse(u).query)
    for key in ("url", "u", "dest", "redirect", "target"):
        if key in q and q[key][0].startswith("http"):
            u = unquote(q[key][0])
    m = re.search(r"(https://[a-z.]*linkedin\.com/(?:comm/)?jobs/view/\d+)", u)
    return m.group(1).replace("/comm/", "/") if m else u


def parse_alert(html, source, pattern, subject=""):
    p = _Links()
    p.feed(html)
    jobs, seen = [], set()
    for href, text, pos in p.items:
        if not re.search(pattern, href, re.I) or not text or NOISE.match(text) or len(text) < 4 \
                or text.lower() in ("indeed", "linkedin", "apec", "glassdoor", "welcome to the jungle"):
            continue
        url = _clean_url(href)
        key = re.sub(r"[?#].*", "", url) if source != "indeed" else f"{text}|{subject}"
        if key in seen:
            continue
        seen.add(key)
        after = [t for t in p.stream[pos:pos + 6] if not NOISE.match(t) and t != text][:3]
        company = after[0] if after else ""
        location = after[1] if len(after) > 1 else ""
        # single-job alerts (Indeed "match" emails): subject is "Title – Company"
        if subject and " – " in subject and text.lower() in subject.lower():
            company = subject.rsplit(" – ", 1)[1].strip()
            location = next((t for t in after if t != company), "")
        jobs.append({"title": text[:160], "company": company[:100], "location": location[:100], "url": url, "key": key})
    return jobs


def fetch(days=7, max_msgs=60, dry=False):
    """Read recent alert emails (read-only). Returns (jobs, stats)."""
    user, pw = os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASSWORD")
    if not (user and pw):
        raise RuntimeError("Gmail not configured (SMTP_USER / SMTP_PASSWORD)")
    state = json.loads(STATE.read_text()) if STATE.exists() else {"seen": []}
    seen_ids = set(state["seen"])
    since = time.strftime("%d-%b-%Y", time.localtime(time.time() - days * 86400))
    imap = imaplib.IMAP4_SSL(os.environ.get("IMAP_HOST") or "imap.gmail.com")
    imap.login(user, pw.replace(" ", ""))
    imap.select("INBOX", readonly=True)  # read-only: nothing is marked read or changed
    out, stats = [], {}
    try:
        for domain, (source, pattern) in SENDERS.items():
            typ, data = imap.search(None, "SINCE", since, "FROM", domain)
            ids = (data[0].split() if typ == "OK" else [])[-max_msgs:]
            stats.setdefault(source, {"emails": 0, "jobs": 0})
            for mid in ids:
                typ, msg_data = imap.fetch(mid, "(BODY.PEEK[])")
                if typ != "OK" or not msg_data or not msg_data[0]:
                    continue
                msg = email.message_from_bytes(msg_data[0][1])
                msgid = msg.get("Message-ID", "") or f"{domain}:{mid.decode()}"
                stats[source]["emails"] += 1
                if msgid in seen_ids:
                    continue
                html = ""
                for part in msg.walk():
                    if part.get_content_type() == "text/html":
                        html += part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="ignore")
                if not html:
                    continue
                subject = _decode(msg.get("Subject", ""))
                for j in parse_alert(html, source, pattern, subject):
                    job = _job(f"alert-{source}", j["key"], j["title"], j["company"], j["location"], j["url"],
                               f"From your {source.title()} job alert: “{subject}”.\n\n{j['title']} · {j['company']} · {j['location']}",
                               "remote" in j["location"].lower() or "télétravail" in j["location"].lower())
                    job["extra"] = {"alert": source, "subject": subject[:200]}
                    out.append(job)
                    stats[source]["jobs"] += 1
                seen_ids.add(msgid)
    finally:
        try:
            imap.logout()
        except Exception:  # noqa: BLE001
            pass
    if not dry:
        state["seen"] = list(seen_ids)[-3000:]
        STATE.write_text(json.dumps(state))
    return out, stats
