#!/usr/bin/env python3
"""
Enrichissement des entreprises automobiles de Bordeaux.
Recherche telephone, email, site_web via societe.com, pappers.fr, DuckDuckGo.

Usage:
    python3 enrich_bordeaux.py --test     # Teste sur 5 entreprises
    python3 enrich_bordeaux.py            # Traite les 727 entreprises
"""

import json
import re
import time
import urllib.request
import urllib.parse
import urllib.error
import ssl
import sys
import os
import random

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
INPUT_FILE = "/home/user/Website01/split_bordeaux.json"
OUTPUT_FILE = "/home/user/Website01/enriched_bordeaux.json"
PROGRESS_FILE = "/home/user/Website01/enrichment_progress_bdx.json"
BATCH_SAVE = 10
DELAY_MIN = 1.2
DELAY_MAX = 2.8

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
]


def get_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.5",
    }


def fetch_url(url, timeout=15):
    """Recupere le contenu d'une URL. Retourne '' en cas d'erreur."""
    try:
        req = urllib.request.Request(url, headers=get_headers())
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read()
            for enc in ["utf-8", "latin-1", "iso-8859-1"]:
                try:
                    return raw.decode(enc)
                except UnicodeDecodeError:
                    continue
            return raw.decode("utf-8", errors="replace")
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

def clean_phone(phone):
    """Nettoie et valide un numero de telephone francais."""
    phone = re.sub(r'[^\d+]', '', phone)
    if phone.startswith('+33'):
        phone = '0' + phone[3:]
    if phone.startswith('33') and len(phone) == 11:
        phone = '0' + phone[2:]
    if len(phone) == 10 and phone.startswith('0'):
        return f"{phone[0:2]} {phone[2:4]} {phone[4:6]} {phone[6:8]} {phone[8:10]}"
    return ""


def is_valid_phone(phone):
    """Verifie qu'un telephone n'est pas un numero generique/faux."""
    if not phone:
        return False
    digits = re.sub(r'\s', '', phone)
    # Rejeter les numeros suspects (memes chiffres repetes, etc.)
    if len(set(digits[2:])) <= 2:
        return False
    # Rejeter les numeros de service connus (pappers, societe.com, etc.)
    if digits.startswith("0234"):
        return False
    # 08 86 = numeros surtaxes/service
    if digits.startswith("0886"):
        return False
    # Rejeter les numeros premium/surtaxes 08 9X
    if digits.startswith("089"):
        return False
    # Numeros connus de societe.com / annuaires (apparaissent sur toutes les pages)
    known_bad = [
        "0615135432", "0234115156", "0178908080", "0899196596",
        "0891150414", "0178901010", "0492315713", "0100235578",
    ]
    if digits in known_bad:
        return False
    return True


def strip_html_noise(html):
    """Remove SVG paths, style blocks, script blocks, and other noise before extraction."""
    # Remove SVG content
    html = re.sub(r'<svg[^>]*>.*?</svg>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    # Remove path d="" attributes
    html = re.sub(r'\bd="[^"]*"', ' ', html)
    # Remove style blocks
    html = re.sub(r'<style[^>]*>.*?</style>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    # Remove script blocks
    html = re.sub(r'<script[^>]*>.*?</script>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    return html


def extract_phones(html):
    """Extrait les numeros de telephone d'une page HTML."""
    phones = []

    # First: high-confidence extraction from href="tel:" links (before stripping)
    for match in re.finditer(r'href="tel:((?:0|\+33|33)[\s.-]*[1-9](?:[\s.-]*\d{2}){4})"', html, re.IGNORECASE):
        cleaned = clean_phone(match.group(1))
        if cleaned and is_valid_phone(cleaned) and cleaned not in phones:
            phones.append(cleaned)

    # Strip noise for pattern-based extraction
    clean_html = strip_html_noise(html)

    patterns = [
        r'(?:tel|phone|telephone|téléphone|tél)["\s:=]*[+]?[\s]*((?:0|\+33|33)[\s.-]*[1-9](?:[\s.-]*\d{2}){4})',
        r'(?<!\d)(0[1-9][\s.-]?\d{2}[\s.-]?\d{2}[\s.-]?\d{2}[\s.-]?\d{2})(?!\d)',
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, clean_html, re.IGNORECASE):
            cleaned = clean_phone(match.group(1) if match.lastindex else match.group(0))
            if cleaned and is_valid_phone(cleaned) and cleaned not in phones:
                phones.append(cleaned)
    return phones


def extract_emails(html):
    """Extrait les adresses email d'une page HTML."""
    emails = []
    pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    skip = ['example.com', 'sentry.io', 'wixpress.com', 'google.com',
            'facebook.com', 'twitter.com', 'w3.org', '.png', '.jpg',
            '.gif', '.svg', 'webpack', 'babel', 'eslint', 'jquery',
            'bootstrap', 'noreply', 'no-reply', 'placeholder',
            'pappers.fr', 'societe.com', 'pagesjaunes', 'cloudflare',
            'schema.org', 'cookie', 'privacy', 'unsubscribe',
            'email@email', 'test@test', 'info@info',
            'duckduckgo.com', 'bing.com', 'yahoo.com', 'outlook.com',
            'hotmail.com', 'live.com', 'msn.com']
    for match in re.finditer(pattern, html):
        email = match.group(0).lower()
        # Rejeter les emails obfusques (hash longs)
        local = email.split('@')[0]
        if len(local) > 30:
            continue
        if not any(s in email for s in skip):
            if email not in emails:
                emails.append(email)
    return emails


def is_company_website(url):
    """Verifie qu'une URL est bien un site d'entreprise, pas un ad/service."""
    url_lower = url.lower()

    # Reject URLs with tracking/partner patterns
    reject_path_patterns = [
        'partenaire', 'utm_', 'affiliate', 'partner', 'sponsor',
        'lp-partenaire', 'campaign', 'promo', 'ad/', 'ads/',
        'click', 'track', 'redirect'
    ]
    if any(p in url_lower for p in reject_path_patterns):
        return False

    # Domain blacklist (comprehensive)
    skip_domains = [
        'societe.com', 'annuaire.com', 'pagesjaunes.fr', 'google.',
        'facebook.com', 'twitter.com', 'linkedin.com', 'instagram.com',
        'youtube.com', 'apple.com', 'microsoft.com', 'wikipedia.org',
        'gouv.fr', 'infogreffe.fr', 'bodacc.fr', 'annuaire-entreprises',
        'verif.com', 'pappers.fr', 'manageo.fr', 'insee.fr',
        'bing.com', 'yahoo.com', 'duckduckgo.com', 'amazon.',
        'creditsafe', 'score3.fr', 'ellisphere', 'cloudflare',
        'w3.org', 'schema.org', 'gstatic.com', 'googleapis.com',
        'gravatar.com', 'wp.com', 'cdn.', 'jquery', 'bootstrap',
        'fontawesome', 'recaptcha', 'analytics', 'privacy-center.org',
        'onetrust.com', 'cookielaw.org', 'consent.', 'cookie',
        'didomi.io', 'axeptio.eu', 'trustcommander', 'evidon.com',
        'sourcepoint.com', 'quantcast.com', 'hotjar.com', 'hubspot.',
        'doubleclick.net', 'adsrvr.org', 'taboola.com', 'outbrain.com',
        'cdn-cgi', 'unpkg.com', 'cdnjs.', 'maxcdn.', 'jsdelivr.',
        'tiktok.com', 'snapchat.com', 'pinterest.',
        'reddit.com', 'trustpilot.com', 'glassdoor.', 'indeed.',
        'pole-emploi.fr', 'leboncoin.fr', 'lafourchette.com',
        'swapn.fr', 'qwant.com', 'ecosia.org', 'startpage.com',
        'dnb.com', 'kompass.com', 'europages.', 'societeinfo.com',
        'data.gouv.fr', 'sirene.fr', 'inpi.fr', 'tribunal-commerce',
        'greffe-tc', 'dfrancais.fr', 'figaro.fr', 'lemonde.fr',
        'l-expert-comptable.com', 'expert-comptable', 'legalstart',
        'legalplace', 'captaincontrat', 'shine.fr', 'blank.app',
        'qonto.com', 'pennylane.', 'tiime.fr', 'numbr.co',
        'getbunq.app', 'bunq.', 'revolut.', 'n26.com', 'sumup.',
        'paypal.', 'stripe.', 'mollie.', 'gocardless.',
        'sendinblue.', 'brevo.com', 'mailchimp.', 'mailjet.',
        'typeform.', 'jotform.', 'calendly.', 'docusign.',
        'impayes.com', 'creancier.', 'recouvrement-amiable.',
        'infolegale.fr', 'altares.com', 'coface.', 'creditorwatch.',
        'bilans.net', 'bilans-gratuits', 'comptedesresultats.',
        'avis-situation-sirene', 'boamp.fr', 'marches-publics.',
    ]
    domain = urllib.parse.urlparse(url).netloc.lower()
    if any(d in domain for d in skip_domains):
        return False

    return True


def extract_websites(html, nom_entreprise=""):
    """Extrait les sites web d'une page HTML. Privilegia les sources fiables."""
    sites = []

    # Priority 1: JSON-LD structured data (most reliable)
    for m in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL | re.IGNORECASE):
        try:
            content = m.group(1).replace('//<![CDATA[', '').replace('//]]>', '').strip()
            data = json.loads(content)
            # Look for company URL in schema.org data
            if isinstance(data, dict):
                org_url = data.get("url", "")
                if org_url and data.get("@type") in ("LocalBusiness", "AutoRepair", "AutoDealer", "Organization", "Store"):
                    # This is likely the company's own URL
                    if is_company_website(org_url):
                        if org_url not in sites:
                            sites.append(org_url)
        except (json.JSONDecodeError, ValueError):
            pass

    # Priority 2: Explicit "site web" labels
    patterns_labeled = [
        r'(?:site[_ ]?web|site[_ ]?internet|website)["\s:=]*(?:<[^>]*href=")?(?:https?://)?((?:www\.)?[a-zA-Z0-9][\w.-]*\.[a-zA-Z]{2,}(?:/[^\s"<]*)?)',
        r'href="(https?://(?:www\.)?[a-zA-Z0-9][\w.-]*\.[a-zA-Z]{2,}(?:/[^\s"<]*)?)"[^>]*>(?:[^<]*(?:site|web|visit))',
    ]
    for pattern in patterns_labeled:
        for match in re.finditer(pattern, html, re.IGNORECASE):
            site = match.group(1)
            if not site.startswith("http"):
                site = "https://" + site
            if is_company_website(site) and site not in sites:
                sites.append(site)

    return sites


def extract_websites_from_search(html):
    """Extract websites from search engine results (DuckDuckGo/Bing).
    More permissive than extract_websites since search results contain company links."""
    sites = []

    # DuckDuckGo result links
    for match in re.finditer(r'class="result__url"[^>]*href="(https?://[^"]+)"', html):
        site = match.group(1)
        if is_company_website(site) and site not in sites:
            sites.append(site)

    # DuckDuckGo result snippets with URLs
    for match in re.finditer(r'class="result__a"[^>]*href="(https?://[^"]+)"', html):
        site = match.group(1)
        # Clean DuckDuckGo redirect
        if 'duckduckgo.com' in site:
            m = re.search(r'[?&]uddg=(https?://[^&]+)', site)
            if m:
                site = urllib.parse.unquote(m.group(1))
        if is_company_website(site) and site not in sites:
            sites.append(site)

    # Bing result links
    for match in re.finditer(r'<cite[^>]*>(https?://[^<]+)</cite>', html):
        site = match.group(1).strip()
        if is_company_website(site) and site not in sites:
            sites.append(site)

    # Generic href links as fallback for search results
    for match in re.finditer(r'href="(https?://(?:www\.)?[a-zA-Z0-9][\w.-]+\.[a-zA-Z]{2,}/?)"', html):
        site = match.group(1)
        if is_company_website(site) and site not in sites:
            sites.append(site)

    return sites


# ---------------------------------------------------------------------------
# Data sources
# ---------------------------------------------------------------------------

def search_annuaire_entreprises_api(siren):
    """API publique annuaire-entreprises.data.gouv.fr."""
    result = {"telephone": "", "email": "", "site_web": ""}
    if not siren:
        return result
    url = f"https://recherche-entreprises.api.gouv.fr/search?q={siren}&page=1&per_page=1"
    try:
        req = urllib.request.Request(url, headers={
            "Accept": "application/json",
            "User-Agent": random.choice(USER_AGENTS)
        })
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("results"):
                r = data["results"][0]
                complements = r.get("complements", {})
                ct = complements.get("collectivite_territoriale", {})
                if ct:
                    tel = ct.get("telephone", "")
                    if tel:
                        cleaned = clean_phone(tel)
                        if is_valid_phone(cleaned):
                            result["telephone"] = cleaned
    except Exception:
        pass
    return result


def search_societe_com(siren):
    """Recherche sur societe.com par SIREN.
    Only extracts from JSON-LD / explicit 'site web' labels (not generic links)."""
    result = {"telephone": "", "email": "", "site_web": ""}
    if not siren:
        return result

    url = f"https://www.societe.com/cgi-bin/search?champs={siren}"
    html = fetch_url(url)
    if not html:
        return result

    phones = extract_phones(html)
    if phones:
        result["telephone"] = phones[0]

    emails = extract_emails(html)
    if emails:
        result["email"] = emails[0]

    # Only use structured/labeled extraction for societe.com (too many ads)
    sites = extract_websites(html)
    if sites:
        result["site_web"] = sites[0]

    return result


def search_pappers(siren):
    """Recherche sur pappers.fr (attention: emails/phones souvent obfusques)."""
    result = {"telephone": "", "email": "", "site_web": ""}
    if not siren:
        return result

    url = f"https://www.pappers.fr/entreprise/{siren}"
    html = fetch_url(url)
    if not html:
        return result

    # Pappers phones are often their own service number, so validate extra
    phones = extract_phones(html)
    if phones:
        result["telephone"] = phones[0]

    # Pappers emails are obfuscated hashes -- skip them
    # Only take emails that look real
    emails = extract_emails(html)
    if emails:
        result["email"] = emails[0]

    sites = extract_websites(html)
    if sites:
        result["site_web"] = sites[0]

    return result


def search_duckduckgo(nom, ville):
    """Recherche DuckDuckGo HTML pour telephone et site web."""
    result = {"telephone": "", "email": "", "site_web": ""}
    query = urllib.parse.quote_plus(f"{nom} {ville} telephone")
    url = f"https://html.duckduckgo.com/html/?q={query}"
    html = fetch_url(url, timeout=15)
    if not html:
        return result

    phones = extract_phones(html)
    if phones:
        result["telephone"] = phones[0]

    emails = extract_emails(html)
    if emails:
        result["email"] = emails[0]

    # Use search-specific extraction for DDG
    sites = extract_websites_from_search(html)
    if sites:
        result["site_web"] = sites[0]

    return result


def search_bing(nom, ville):
    """Recherche Bing."""
    result = {"telephone": "", "email": "", "site_web": ""}
    query = urllib.parse.quote(f"{nom} {ville} téléphone site web")
    url = f"https://www.bing.com/search?q={query}&setlang=fr"
    html = fetch_url(url)
    if not html:
        return result

    phones = extract_phones(html)
    if phones:
        result["telephone"] = phones[0]

    emails = extract_emails(html)
    if emails:
        result["email"] = emails[0]

    # Use search-specific extraction for Bing
    sites = extract_websites_from_search(html)
    if sites:
        result["site_web"] = sites[0]

    return result


# ---------------------------------------------------------------------------
# Enrichissement principal
# ---------------------------------------------------------------------------

def merge_result(current, new_data):
    """Fusionne les nouvelles donnees dans le resultat courant."""
    for key in ["telephone", "email", "site_web"]:
        if not current.get(key) and new_data.get(key):
            current[key] = new_data[key]


def enrich_entreprise(entreprise, index, total):
    """Enrichit une entreprise avec telephone, email, site_web."""
    nom = entreprise.get("nom", "")
    siren = entreprise.get("siren", "")
    ville = entreprise.get("ville", "")

    result = {"telephone": "", "email": "", "site_web": ""}

    print(f"[{index+1}/{total}] {nom} (SIREN: {siren})...", end=" ", flush=True)

    # 1) API annuaire-entreprises (rapide, gratuit)
    try:
        r = search_annuaire_entreprises_api(siren)
        merge_result(result, r)
    except Exception:
        pass

    # 2) societe.com
    if not result["telephone"] or not result["site_web"]:
        time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
        try:
            r = search_societe_com(siren)
            merge_result(result, r)
        except Exception:
            pass

    # 3) pappers.fr
    if not result["telephone"] or not result["site_web"]:
        time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
        try:
            r = search_pappers(siren)
            merge_result(result, r)
        except Exception:
            pass

    # 4) DuckDuckGo
    if not result["telephone"] or not result["site_web"]:
        time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
        try:
            r = search_duckduckgo(nom, ville)
            merge_result(result, r)
        except Exception:
            pass

    # 5) Bing (dernier recours)
    if not result["telephone"] or not result["site_web"]:
        time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
        try:
            r = search_bing(nom, ville)
            merge_result(result, r)
        except Exception:
            pass

    status_parts = []
    if result["telephone"]:
        status_parts.append(f"tel={result['telephone']}")
    if result["email"]:
        status_parts.append(f"email={result['email']}")
    if result["site_web"]:
        status_parts.append(f"web={result['site_web'][:50]}")
    print(" | ".join(status_parts) if status_parts else "rien trouve")

    entreprise["telephone"] = result["telephone"]
    entreprise["email"] = result["email"]
    entreprise["site_web"] = result["site_web"]

    return entreprise


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    test_mode = "--test" in sys.argv
    test_count = 5

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        entreprises = json.load(f)

    total_all = len(entreprises)
    print(f"Fichier charge: {total_all} entreprises")

    enriched = []
    start_index = 0

    if os.path.exists(PROGRESS_FILE) and not test_mode:
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                enriched = json.load(f)
            start_index = len(enriched)
            print(f"Reprise depuis l'index {start_index} ({start_index} deja traites)")
        except Exception:
            enriched = []
            start_index = 0

    if test_mode:
        entreprises = entreprises[:test_count]
        total = test_count
        enriched = []
        start_index = 0
        print(f"=== MODE TEST: {test_count} entreprises ===")
    else:
        total = total_all

    for i in range(start_index, len(entreprises)):
        ent = entreprises[i]
        try:
            enriched_ent = enrich_entreprise(ent, i, total)
            enriched.append(enriched_ent)
        except Exception as e:
            print(f"  ERREUR: {e}")
            ent["telephone"] = ""
            ent["email"] = ""
            ent["site_web"] = ""
            enriched.append(ent)

        # Sauvegarder la progression regulierement
        if (i + 1) % BATCH_SAVE == 0 or i == len(entreprises) - 1:
            if not test_mode:
                with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
                    json.dump(enriched, f, ensure_ascii=False, indent=2)
                print(f"  [Progression sauvegardee: {len(enriched)}/{total}]")

    # Sauvegarder le resultat final
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(enriched, f, ensure_ascii=False, indent=2)

    # Nettoyer le fichier de progression
    if os.path.exists(PROGRESS_FILE) and not test_mode:
        os.remove(PROGRESS_FILE)

    # Stats
    n = len(enriched)
    with_phone = sum(1 for e in enriched if e.get("telephone"))
    with_email = sum(1 for e in enriched if e.get("email"))
    with_web = sum(1 for e in enriched if e.get("site_web"))
    print(f"\n=== RESULTATS ===")
    print(f"Total: {n} entreprises")
    print(f"Avec telephone: {with_phone} ({100*with_phone/n:.1f}%)")
    print(f"Avec email: {with_email} ({100*with_email/n:.1f}%)")
    print(f"Avec site web: {with_web} ({100*with_web/n:.1f}%)")
    print(f"Fichier sauvegarde: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
