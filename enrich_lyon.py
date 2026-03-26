#!/usr/bin/env python3
"""
Enrichit les entreprises de split_lyon.json avec telephone, email, site_web.
Sources: societe.com (via recherche SIREN), DuckDuckGo, Google.
Usage: python3 enrich_lyon.py [--test]
"""

import json
import re
import time
import urllib.request
import urllib.parse
import urllib.error
import ssl
import os
import sys
import random
import html as html_mod

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
INPUT_FILE  = "/home/user/Website01/split_lyon.json"
OUTPUT_FILE = "/home/user/Website01/enriched_lyon.json"
PROGRESS_FILE = "/home/user/Website01/enriched_lyon_progress.json"
BATCH_SAVE  = 20          # save progress every N companies
DELAY_MIN   = 1.2         # min delay between requests (seconds)
DELAY_MAX   = 2.8         # max delay
TEST_MODE   = False       # set True to only process 5 entries
MAX_RETRIES = 2

# SSL context that doesn't verify (some sites have cert issues)
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

UA_LIST = [
    "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:123.0) Gecko/20100101 Firefox/123.0",
]

def get_headers():
    return {
        "User-Agent": random.choice(UA_LIST),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.5",
    }

# Domains to skip when looking for company websites
SKIP_DOMAINS = {
    "google.", "gstatic.", "googleapis.", "societe.com", "pagesjaunes.",
    "annuaire.", "wikipedia.", "facebook.com", "linkedin.com", "twitter.com",
    "youtube.com", "instagram.com", "yelp.", "tripadvisor.", "pappers.fr",
    "verif.com", "manageo.fr", "infogreffe.", "bodacc.", "duckduckgo.com",
    "bing.com", "kompass.", "europages.", "mappy.", "tiktok.com",
    "data.gouv.fr", "score3.fr", "118000.", "118712.", "horaires.lefigaro.",
    "apple.com/maps", "pinterest.", "reddit.com", "annuairefrancais.fr",
    "annuaire-inverse", "justacote.", "starofservice.", "cylex.",
    "hoodspot.", "infoisinfo.", "hotfrog.", "fr.kompass.", "telephone.city",
    "local.infobel.", "pratique.fr", "allopneus.", "encontre-se.",
    "dnb.com", "yellowpages.", "net1901.org", "dataprospects.fr",
    "auto-selection.com", "soundcloud.com", "lyon.fr/lieu",
    "entreprises.lefigaro.fr", "app.dataprospects.", "geneanet.",
    "zipcodestogo.", "garage-fr.com", "lesgarages.fr", "118218.",
    "societeinfo.com", "sirene.fr", "near-place.com", "placeslocales.",
    "endroit-ede.", "cylex-locale.", "localfr.", "ville-data.com",
    "contact-infos.", "annuairepro.", "infonet.fr", "tel.fr",
    "horairesdouverture24.", "horairesdouverture.", "ouvert-le-dimanche.",
    "openingtimes.", "cybo.", "foursquare.", "pagesjaunes.ca",
    "whitepages.", "automobile.e-pro.", "e-pro.fr", "linternaute.com",
    "lagazettefrance.", "lagazette.", "pages-blanches.", "pagesblanches.",
    "copainsdavant.", "trombi.", "kelest.", "annuaire-mairie.",
    "gralon.", "commune-mairie.", "habitatpresto.", "travaux.com",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fetch_url(url, timeout=15):
    """Fetch URL content as string, return None on failure."""
    req = urllib.request.Request(url, headers=get_headers())
    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                raw = resp.read()
                try:
                    return raw.decode("utf-8")
                except UnicodeDecodeError:
                    return raw.decode("latin-1")
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(2)
            else:
                return None
    return None


def clean_phone(raw):
    """Normalize a French phone number to XX XX XX XX XX format."""
    if not raw:
        return ""
    digits = re.sub(r"[^\d+]", "", raw)
    # +33 format
    if digits.startswith("+33") or digits.startswith("33"):
        digits = digits.replace("+", "")
        if digits.startswith("33"):
            digits = "0" + digits[2:]
    # Extract 10-digit French number
    m = re.search(r"(0[1-9]\d{8})", digits)
    if m:
        d = m.group(1)
        return " ".join([d[i:i+2] for i in range(0, 10, 2)])
    return ""


def is_valid_phone(phone_str):
    """Check phone is a plausible French landline/mobile for Lyon area."""
    digits = re.sub(r"\s", "", phone_str)
    if len(digits) != 10:
        return False
    # Exclude premium/special numbers
    if digits[:2] in ("08", "09"):
        # 09 can be valid (box internet), 08 is premium
        if digits[:2] == "08":
            return False
    return True


def extract_phones_from_text(text, siren="", siret=""):
    """Extract all French phone numbers from text, avoiding SVG/path false positives."""
    # First, strip out SVG elements and path data to avoid false positives
    text_clean = re.sub(r'<svg[^>]*>.*?</svg>', ' ', text, flags=re.S|re.I)
    text_clean = re.sub(r'\bd="[^"]*"', ' ', text_clean)
    text_clean = re.sub(r'<path[^>]*>', ' ', text_clean, flags=re.I)
    # Also strip numeric sequences that look like coordinates (digits.digits)
    text_clean = re.sub(r'\d+\.\d+\s+\d+\.\d+', ' ', text_clean)

    # Pattern: phone must have at least one separator (space, dot, dash) between groups
    # OR be in a tel: link, OR preceded by known labels
    patterns = [
        # Phone with separators: 04 78 83 24 81 or 04.78.83.24.81
        r'(?<!\d)(?:\+33\s?[\s.\-]?)?0[1-9][\s.\-]\d{2}[\s.\-]\d{2}[\s.\-]\d{2}[\s.\-]\d{2}(?!\d)',
        # tel: link
        r'tel:[\s]*((?:\+33|0)[1-9][\d\s.\-]{8,})',
    ]
    raw_phones = []
    for pattern in patterns:
        raw_phones.extend(re.findall(pattern, text_clean))

    # Deduplicate and validate
    seen = set()
    cleaned = []
    # Build set of numbers to exclude (SIREN, SIRET digits)
    exclude_digits = set()
    if siren:
        exclude_digits.add(siren)
    if siret:
        exclude_digits.add(siret)

    for p in raw_phones:
        c = clean_phone(p)
        if not c or not is_valid_phone(c):
            continue
        digits = re.sub(r"\s", "", c)
        if digits in exclude_digits:
            continue
        if digits in seen:
            continue
        seen.add(digits)
        cleaned.append(c)
    return cleaned


def extract_emails_from_text(text):
    """Extract emails, filtering out noise."""
    pattern = r'[a-zA-Z0-9_.+\-]+@[a-zA-Z0-9.\-]+\.(?:fr|com|net|org|eu|io|biz|info)'
    found = re.findall(pattern, text, re.I)
    filtered = []
    noise = ["societe.com", "google", "example", "noreply", "pappers",
             "duckduckgo", "pagesjaunes", "gstatic", "schema.org",
             "microsoft", "w3.org", "mozilla", "apple.com"]
    for e in found:
        if not any(n in e.lower() for n in noise):
            filtered.append(e)
    return filtered


def extract_websites_from_text(text, company_name=""):
    """Extract plausible company websites from HTML text.

    Only returns sites that have at least one company name word in the domain,
    or are short domains (likely the company's own site).
    """
    urls = re.findall(r'href="(https?://[^"]+)"', text)
    name_words = set(re.sub(r'[^a-zA-Z\s]', '', company_name.lower()).split())
    # Filter meaningful words (>3 chars)
    name_words = {w for w in name_words if len(w) > 3}

    candidates = []
    for u in urls:
        u_clean = u.split("&")[0].split("?sa=")[0].rstrip("/")
        u_lower = u_clean.lower()
        if any(skip in u_lower for skip in SKIP_DOMAINS):
            continue
        # Extract just the domain for checking
        try:
            parsed = urllib.parse.urlparse(u_clean)
            domain = parsed.netloc.lower().replace("www.", "")
        except Exception:
            continue
        if not domain:
            continue

        # Skip if the path is too deep (likely an annuaire page about the company)
        path = parsed.path.rstrip("/")
        path_depth = len([p for p in path.split("/") if p])

        # Score: company name words in domain (much more valuable than in path)
        domain_score = sum(2 for w in name_words if w in domain)
        # Only count path matches if domain also partially matches
        path_score = sum(1 for w in name_words if w in path.lower()) if domain_score > 0 else 0
        score = domain_score + path_score

        # Accept if: name word in domain, OR domain is short and path is shallow
        if score > 0:
            candidates.append((score, u_clean))
        elif path_depth <= 1 and len(domain) < 30:
            # Could be a company site with a non-matching name
            candidates.append((0, u_clean))

    # Sort by score descending
    candidates.sort(key=lambda x: -x[0])
    # Only return sites with score > 0 (name match) if available
    high_score = [c[1] for c in candidates if c[0] > 0]
    if high_score:
        return high_score
    return [c[1] for c in candidates[:1]]  # at most one fallback


# ---------------------------------------------------------------------------
# Source 1: societe.com via search
# ---------------------------------------------------------------------------
def extract_from_societe_com(siren, nom, siret=""):
    """Search societe.com via SIREN to find company page, extract data."""
    phone, email, website = "", "", ""
    if not siren:
        return phone, email, website

    url = f"https://www.societe.com/cgi-bin/search?champs={siren}"
    page = fetch_url(url)
    if not page:
        return phone, email, website

    # Decode entities
    page = html_mod.unescape(page)

    # Phone - societe.com often obfuscates, but sometimes visible
    phones = extract_phones_from_text(page, siren=siren, siret=siret)
    if phones:
        phone = phones[0]

    # Email
    emails = extract_emails_from_text(page)
    if emails:
        email = emails[0]

    # Website - look for itemprop or "Site internet" sections
    site_patterns = [
        r'itemprop="url"[^>]*>([^<]+)<',
        r'(?:Site\s*(?:web|internet|officiel))\s*:?\s*(?:<[^>]*>)*\s*((?:https?://)?(?:www\.)?[a-zA-Z0-9][-a-zA-Z0-9.]*\.[a-z]{2,}[^\s<"]*)',
        r'href="(https?://(?:www\.)?[^"]*)"[^>]*>\s*(?:Site|Visiter|Voir le site)',
    ]
    for pat in site_patterns:
        m = re.search(pat, page, re.I)
        if m:
            candidate = m.group(1).strip()
            if not any(skip in candidate.lower() for skip in SKIP_DOMAINS):
                if not candidate.startswith("http"):
                    candidate = "https://" + candidate
                website = candidate
                break

    return phone, email, website


# ---------------------------------------------------------------------------
# Source 2: DuckDuckGo HTML search
# ---------------------------------------------------------------------------
def extract_from_duckduckgo(nom, ville):
    """Search DuckDuckGo for phone, email, website."""
    phone, email, website = "", "", ""
    search_name = re.sub(r'\([^)]*\)', '', nom).strip()
    query = f"{search_name} {ville} telephone"
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    page = fetch_url(url)
    if not page:
        return phone, email, website

    page = html_mod.unescape(page)

    # Phone
    phones = extract_phones_from_text(page)
    if phones:
        phone = phones[0]

    # Email
    emails = extract_emails_from_text(page)
    if emails:
        email = emails[0]

    # Website
    sites = extract_websites_from_text(page, search_name)
    if sites:
        website = sites[0]

    return phone, email, website


# ---------------------------------------------------------------------------
# Source 3: Google search (fallback)
# ---------------------------------------------------------------------------
def extract_from_google(nom, ville):
    """Search Google for phone, email, website."""
    phone, email, website = "", "", ""
    search_name = re.sub(r'\([^)]*\)', '', nom).strip()
    query = f"{search_name} {ville} telephone site"
    url = "https://www.google.com/search?" + urllib.parse.urlencode({"q": query, "hl": "fr", "num": "10"})
    page = fetch_url(url)
    if not page:
        return phone, email, website

    page = html_mod.unescape(page)

    # Phone
    phones = extract_phones_from_text(page)
    if phones:
        phone = phones[0]

    # Email
    emails = extract_emails_from_text(page)
    if emails:
        email = emails[0]

    # Website
    sites = extract_websites_from_text(page, search_name)
    if sites:
        website = sites[0]

    return phone, email, website


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
def enrich_company(company):
    """Enrich a single company with phone, email, site_web using multiple sources."""
    siren = company.get("siren", "")
    siret = company.get("siret", "")
    nom = company.get("nom", "")
    ville = company.get("ville", "")

    phone, email, website = "", "", ""

    # Source 1: DuckDuckGo (most reliable, no captcha)
    p, e, w = extract_from_duckduckgo(nom, ville)
    phone = phone or p
    email = email or e
    website = website or w
    time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

    # Source 2: societe.com (via SIREN search)
    if not phone or not website:
        p, e, w = extract_from_societe_com(siren, nom, siret)
        phone = phone or p
        email = email or e
        website = website or w
        time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

    # Source 3: Google (as last resort, may get captcha after many requests)
    if not phone and not website:
        p, e, w = extract_from_google(nom, ville)
        phone = phone or p
        email = email or e
        website = website or w
        time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

    return phone, email, website


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    global TEST_MODE

    # Allow passing --test from command line
    if "--test" in sys.argv:
        TEST_MODE = True

    # Load input
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        companies = json.load(f)

    total = len(companies)
    print(f"Loaded {total} companies from {INPUT_FILE}")

    if TEST_MODE:
        companies = companies[:5]
        total = 5
        print("TEST MODE: processing only 5 companies")

    # Load progress if exists (for resume)
    start_idx = 0
    if os.path.exists(PROGRESS_FILE) and not TEST_MODE:
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                progress_data = json.load(f)
            if len(progress_data) > 0 and len(progress_data) <= total:
                start_idx = len(progress_data)
                for i, pd in enumerate(progress_data):
                    companies[i]["telephone"] = pd.get("telephone", "")
                    companies[i]["email"] = pd.get("email", "")
                    companies[i]["site_web"] = pd.get("site_web", "")
                print(f"Resuming from index {start_idx} ({start_idx}/{total} already done)")
        except Exception:
            start_idx = 0

    # Initialize fields for all companies
    for c in companies:
        if "telephone" not in c:
            c["telephone"] = ""
        if "email" not in c:
            c["email"] = ""
        if "site_web" not in c:
            c["site_web"] = ""

    # Process
    found_phone = sum(1 for c in companies[:start_idx] if c.get("telephone"))
    found_email = sum(1 for c in companies[:start_idx] if c.get("email"))
    found_site = sum(1 for c in companies[:start_idx] if c.get("site_web"))

    for i in range(start_idx, total):
        c = companies[i]
        nom = c.get("nom", "?")
        siren = c.get("siren", "?")
        print(f"[{i+1}/{total}] {nom} (SIREN: {siren}) ...", end=" ", flush=True)

        try:
            phone, email, website = enrich_company(c)
            c["telephone"] = phone
            c["email"] = email
            c["site_web"] = website

            if phone: found_phone += 1
            if email: found_email += 1
            if website: found_site += 1

            status = []
            if phone: status.append(f"tel={phone}")
            if email: status.append(f"email={email}")
            if website: status.append(f"site={website[:50]}")
            print(" | ".join(status) if status else "(rien trouve)")

        except Exception as ex:
            print(f"ERREUR: {ex}")
            c["telephone"] = ""
            c["email"] = ""
            c["site_web"] = ""

        # Save progress periodically
        if (i + 1) % BATCH_SAVE == 0 or i == total - 1:
            with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
                json.dump(companies[:i+1], f, ensure_ascii=False, indent=2)

    # Final save
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(companies, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"Termine! {total} entreprises traitees.")
    print(f"Telephones trouves : {found_phone}/{total}")
    print(f"Emails trouves     : {found_email}/{total}")
    print(f"Sites web trouves  : {found_site}/{total}")
    print(f"Resultat sauvegarde dans {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
