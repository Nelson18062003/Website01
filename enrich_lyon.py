#!/usr/bin/env python3
"""
Enrichit les entreprises de split_lyon.json avec telephone, email, site_web
en interrogeant societe.com via le SIREN.
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

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
INPUT_FILE  = "/home/user/Website01/split_lyon.json"
OUTPUT_FILE = "/home/user/Website01/enriched_lyon.json"
PROGRESS_FILE = "/home/user/Website01/enriched_lyon_progress.json"
BATCH_SAVE  = 25          # save progress every N companies
DELAY_MIN   = 1.0         # min delay between requests (seconds)
DELAY_MAX   = 2.5         # max delay
TEST_MODE   = False       # set True to only process 5 entries
MAX_RETRIES = 2

# SSL context that doesn't verify (some sites have cert issues)
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.5",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fetch_url(url, timeout=15):
    """Fetch URL content as string, return None on failure."""
    req = urllib.request.Request(url, headers=HEADERS)
    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                raw = resp.read()
                # try utf-8 first, fallback latin-1
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
    """Normalize a French phone number."""
    if not raw:
        return ""
    digits = re.sub(r"[^\d+]", "", raw)
    # French numbers: 10 digits starting with 0
    if re.match(r"^0[1-9]\d{8}$", digits):
        return " ".join([digits[i:i+2] for i in range(0, 10, 2)])
    if re.match(r"^\+33\d{9}$", digits):
        local = "0" + digits[3:]
        return " ".join([local[i:i+2] for i in range(0, 10, 2)])
    if len(digits) >= 10:
        # try to extract last 10 digits
        m = re.search(r"(0[1-9]\d{8})", digits)
        if m:
            d = m.group(1)
            return " ".join([d[i:i+2] for i in range(0, 10, 2)])
    return ""


def extract_from_societe_com(siren, nom):
    """
    Try societe.com page for a SIREN to get phone, email, website.
    """
    phone, email, website = "", "", ""
    url = f"https://www.societe.com/societe/{siren}.html"
    html = fetch_url(url)
    if not html:
        return phone, email, website

    # Phone: look for patterns like 0X XX XX XX XX in the page
    # societe.com often has phone in a specific section
    phone_patterns = [
        r'itemprop="telephone"[^>]*>([^<]+)<',
        r'tel:(\+?[\d\s.\-]+)',
        r'class="[^"]*phone[^"]*"[^>]*>([^<]+)<',
        r'(?:T(?:é|e)l(?:é|e)?(?:phone)?|Phone)\s*(?::|\s)\s*(0[1-9][\s.\-]?\d{2}[\s.\-]?\d{2}[\s.\-]?\d{2}[\s.\-]?\d{2})',
    ]
    for pat in phone_patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            candidate = clean_phone(m.group(1))
            if candidate:
                phone = candidate
                break

    # Email
    email_patterns = [
        r'itemprop="email"[^>]*>([^<]+)<',
        r'mailto:([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)',
        r'([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.(?:fr|com|net|org|eu))',
    ]
    for pat in email_patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            candidate = m.group(1).strip()
            # filter out generic/noreply
            if "@" in candidate and "societe.com" not in candidate.lower():
                email = candidate
                break

    # Website
    site_patterns = [
        r'itemprop="url"[^>]*>([^<]+)<',
        r'Site\s*(?:web|internet)\s*(?::|\s)\s*(?:<[^>]*>)?\s*((?:https?://)?(?:www\.)?[a-zA-Z0-9.-]+\.[a-z]{2,}[^\s<"]*)',
        r'href="(https?://(?:www\.)?[^"]*)"[^>]*>\s*(?:Site|Visiter)',
    ]
    for pat in site_patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            candidate = m.group(1).strip()
            if "societe.com" not in candidate.lower() and "." in candidate:
                if not candidate.startswith("http"):
                    candidate = "https://" + candidate
                website = candidate
                break

    return phone, email, website


def extract_from_annuaire(nom, ville):
    """
    Search annuaire.com / pagesjaunes-style for phone + website.
    """
    phone, email, website = "", "", ""
    # Clean company name for search
    search_name = re.sub(r'\([^)]*\)', '', nom).strip()
    query = urllib.parse.quote(f"{search_name} {ville}")
    url = f"https://www.google.com/search?q={query}+telephone+site"
    html = fetch_url(url)
    if not html:
        return phone, email, website

    # Phone numbers in search results
    phone_re = r'(?<!\d)(0[1-9][\s.\-]?\d{2}[\s.\-]?\d{2}[\s.\-]?\d{2}[\s.\-]?\d{2})(?!\d)'
    phones_found = re.findall(phone_re, html)
    for p in phones_found:
        candidate = clean_phone(p)
        if candidate:
            phone = candidate
            break

    # Website: look for company-related URLs in results
    # Skip known aggregators
    skip_domains = {"google.", "societe.com", "pagesjaunes.", "annuaire.",
                    "wikipedia.", "facebook.com", "linkedin.com", "twitter.com",
                    "youtube.com", "instagram.com", "yelp.", "tripadvisor."}
    url_re = r'href="(https?://[^"]+)"'
    for m in re.finditer(url_re, html):
        u = m.group(1)
        if any(skip in u.lower() for skip in skip_domains):
            continue
        # Check if the URL could be the company's site
        name_words = re.sub(r'[^a-zA-Z\s]', '', search_name.lower()).split()
        u_lower = u.lower()
        if any(w in u_lower for w in name_words if len(w) > 3):
            website = u.split("&")[0].split("?sa=")[0]
            break

    # Email from search snippet
    em = re.search(r'([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.(?:fr|com|net|org|eu))', html)
    if em:
        candidate = em.group(1)
        if "google" not in candidate.lower():
            email = candidate

    return phone, email, website


def extract_from_pappers(siren):
    """Try pappers.fr for company info."""
    phone, email, website = "", "", ""
    url = f"https://www.pappers.fr/entreprise/{siren}"
    html = fetch_url(url)
    if not html:
        return phone, email, website

    # Phone
    m = re.search(r'(?:telephone|phone)["\s:]*[>]?\s*(0[1-9][\s.\-]?\d{2}[\s.\-]?\d{2}[\s.\-]?\d{2}[\s.\-]?\d{2})', html, re.I)
    if m:
        phone = clean_phone(m.group(1))

    # Website
    m = re.search(r'(?:Site\s*(?:web|internet)|website)\s*(?::|\s)?\s*(?:<[^>]*>)?\s*((?:https?://)?(?:www\.)?[a-zA-Z0-9][-a-zA-Z0-9.]*\.[a-z]{2,}[^\s<"]*)', html, re.I)
    if m:
        candidate = m.group(1).strip()
        if "pappers" not in candidate.lower():
            if not candidate.startswith("http"):
                candidate = "https://" + candidate
            website = candidate

    # Email
    em = re.search(r'([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.(?:fr|com|net|org|eu))', html)
    if em and "pappers" not in em.group(1).lower():
        email = em.group(1)

    return phone, email, website


def enrich_company(company):
    """Enrich a single company with phone, email, site_web."""
    siren = company.get("siren", "")
    nom = company.get("nom", "")
    ville = company.get("ville", "")

    phone, email, website = "", "", ""

    # Source 1: societe.com (via SIREN)
    if siren:
        p, e, w = extract_from_societe_com(siren, nom)
        phone = phone or p
        email = email or e
        website = website or w
        time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

    # Source 2: pappers.fr
    if siren and (not phone or not website):
        p, e, w = extract_from_pappers(siren)
        phone = phone or p
        email = email or e
        website = website or w
        time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

    # Source 3: Google search (as last resort if we still miss data)
    if not phone or not website:
        p, e, w = extract_from_annuaire(nom, ville)
        phone = phone or p
        email = email or e
        website = website or w
        time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

    return phone, email, website


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    # Load input
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        companies = json.load(f)

    total = len(companies)
    print(f"Loaded {total} companies from {INPUT_FILE}")

    if TEST_MODE:
        companies = companies[:5]
        total = 5
        print("TEST MODE: processing only 5 companies")

    # Load progress if exists
    start_idx = 0
    if os.path.exists(PROGRESS_FILE) and not TEST_MODE:
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                progress_data = json.load(f)
            # progress_data contains already-enriched entries
            if len(progress_data) > 0 and len(progress_data) <= total:
                start_idx = len(progress_data)
                # Apply saved enrichment to companies
                for i, pd in enumerate(progress_data):
                    companies[i]["telephone"] = pd.get("telephone", "")
                    companies[i]["email"] = pd.get("email", "")
                    companies[i]["site_web"] = pd.get("site_web", "")
                print(f"Resuming from index {start_idx} ({start_idx}/{total} already done)")
        except Exception:
            start_idx = 0

    # Initialize fields for all companies
    for i, c in enumerate(companies):
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
            if website: status.append(f"site={website[:40]}")
            print(" | ".join(status) if status else "(rien trouvé)")

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
    print(f"Terminé! {total} entreprises traitées.")
    print(f"Téléphones trouvés : {found_phone}/{total}")
    print(f"Emails trouvés     : {found_email}/{total}")
    print(f"Sites web trouvés  : {found_site}/{total}")
    print(f"Résultat sauvegardé dans {OUTPUT_FILE}")


if __name__ == "__main__":
    # Allow passing --test from command line
    if "--test" in sys.argv:
        TEST_MODE = True
    main()
