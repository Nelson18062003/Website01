#!/usr/bin/env python3
"""
Enrichissement des entreprises automobiles de Lille via Pages Jaunes.

Strategie :
1. Scrape les pages de resultats PJ par categorie (garage, concession, carrossier, moto)
2. Collecte nom, adresse, telephone, site web, email pour chaque listing
3. Matche par fuzzy matching avec les entreprises du fichier source
4. Sauvegarde le resultat enrichi dans enriched_lille_pj.json

Utilise curl_cffi pour contourner Cloudflare.
"""

import json
import re
import time
import os
import sys
import unicodedata
from urllib.parse import quote, urlencode
from bs4 import BeautifulSoup
from curl_cffi import requests
from rapidfuzz import fuzz

# --- Configuration ---
SOURCE_FILE = "/home/user/Website01/split_lille.json"
OUTPUT_FILE = "/home/user/Website01/enriched_lille_pj.json"
PROGRESS_FILE = "/home/user/Website01/_pj_scrape_progress.json"
DELAY_MIN = 1.5
DELAY_MAX = 2.5
MAX_PAGES_PER_CATEGORY = 50

# Mapping categorie source -> terme de recherche PJ
CATEGORY_SEARCH = {
    "garage": "garage automobile",
    "concession": "concessionnaire automobile",
    "carrossier": "carrosserie automobile",
    "moto": "moto",
}

BASE_URL = "https://www.pagesjaunes.fr"


def normalize(text):
    """Normalise un texte pour la comparaison : minuscules, sans accents, sans ponctuation."""
    if not text:
        return ""
    text = text.lower().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_phone(fantomas_div):
    """Extrait le numero de telephone depuis le div bi-fantomas."""
    if not fantomas_div:
        return ""
    nc = fantomas_div.select_one(".number-contact")
    if nc:
        text = nc.get_text(strip=True)
        text = re.sub(r"^T[ée]l\s*:\s*", "", text, flags=re.IGNORECASE)
        return text.strip()
    return ""


def extract_listing_data(li_element):
    """Extrait les donnees d'un listing PJ (element li.bi)."""
    data = {
        "pj_nom": "",
        "pj_adresse": "",
        "pj_telephone": "",
        "pj_site_web": "",
        "pj_detail_url": "",
    }

    # Nom
    denom = li_element.select_one(".bi-denomination")
    if denom:
        data["pj_nom"] = denom.get_text(strip=True)
        # URL detail
        pjlb = denom.get("data-pjlb", "")
        if pjlb:
            try:
                import base64
                pjlb_data = json.loads(pjlb)
                decoded = base64.b64decode(pjlb_data["url"]).decode()
                data["pj_detail_url"] = decoded
            except Exception:
                pass

    # Adresse
    addr_el = li_element.select_one(".bi-address")
    if addr_el:
        data["pj_adresse"] = addr_el.get_text(strip=True).replace("Voir le plan", "").strip()

    # Telephone
    fantomas = li_element.select_one(".bi-fantomas")
    data["pj_telephone"] = extract_phone(fantomas)

    # Site web - chercher dans les liens du listing
    li_html = str(li_element)
    urls = re.findall(
        r'https?://(?:www\.)?[a-zA-Z0-9._-]+\.[a-zA-Z]{2,}(?:/[^\s"<>\']*)?',
        li_html,
    )
    excluded = ["pagesjaunes.fr", "at-internet", "weborama", "google", "facebook.com/tr"]
    for url in urls:
        if not any(ex in url for ex in excluded):
            data["pj_site_web"] = url
            break

    return data


def fetch_page(session, url, retries=3):
    """Fetch une page avec retry et delay."""
    for attempt in range(retries):
        try:
            r = session.get(url, timeout=20)
            if r.status_code == 200:
                return r.text
            elif r.status_code == 403:
                print(f"  [WARN] 403 sur {url[:80]}, retry {attempt+1}/{retries}")
                time.sleep(5 + attempt * 3)
            else:
                print(f"  [WARN] Status {r.status_code} sur {url[:80]}")
                time.sleep(3)
        except Exception as e:
            print(f"  [ERR] {e}, retry {attempt+1}/{retries}")
            time.sleep(5)
    return None


def scrape_category(session, search_term, max_pages=MAX_PAGES_PER_CATEGORY):
    """Scrape toutes les pages de resultats pour une categorie."""
    all_listings = []

    first_url = f"{BASE_URL}/recherche/lille-59/{quote(search_term)}"
    print(f"\n{'='*60}")
    print(f"Scraping: {search_term}")
    print(f"URL: {first_url}")
    print(f"{'='*60}")

    html = fetch_page(session, first_url)
    if not html:
        print(f"  [ERR] Impossible de charger la premiere page")
        return all_listings

    soup = BeautifulSoup(html, "html.parser")

    # Nombre total de pages
    compteur = soup.select_one(".pagination-compteur")
    total_pages = 1
    if compteur:
        m = re.search(r"(\d+)\s*/\s*(\d+)", compteur.get_text())
        if m:
            total_pages = int(m.group(2))
    print(f"  Pages totales: {total_pages}")
    total_pages = min(total_pages, max_pages)

    # Parse page 1
    listings = soup.select("li.bi")
    for li in listings:
        data = extract_listing_data(li)
        if data["pj_nom"]:
            all_listings.append(data)
    print(f"  Page 1: {len(listings)} listings ({len(all_listings)} total)")

    # Pages suivantes
    for page_num in range(2, total_pages + 1):
        import random
        delay = random.uniform(DELAY_MIN, DELAY_MAX)
        time.sleep(delay)

        # Trouver l'URL de la page suivante
        next_link = soup.select_one("a.next")
        next_url = None
        if next_link and next_link.get("data-pjlb"):
            try:
                import base64
                pjlb = json.loads(next_link["data-pjlb"])
                path = base64.b64decode(pjlb["url"]).decode()
                next_url = f"{BASE_URL}{path}"
            except Exception:
                pass

        if not next_url:
            # Construire l'URL manuellement
            next_url = f"{BASE_URL}/recherche/lille-59/{quote(search_term)}?page={page_num}"

        html = fetch_page(session, next_url)
        if not html:
            print(f"  [WARN] Arret a la page {page_num}")
            break

        soup = BeautifulSoup(html, "html.parser")
        listings = soup.select("li.bi")
        if not listings:
            print(f"  Page {page_num}: 0 listings - arret")
            break

        for li in listings:
            data = extract_listing_data(li)
            if data["pj_nom"]:
                all_listings.append(data)

        print(f"  Page {page_num}/{total_pages}: {len(listings)} listings ({len(all_listings)} total)")

    return all_listings


def fetch_detail_page(session, detail_path):
    """Fetch une page de detail pour recuperer site web et email."""
    if not detail_path:
        return {}

    url = f"{BASE_URL}{detail_path}"
    html = fetch_page(session, url)
    if not html:
        return {}

    soup = BeautifulSoup(html, "html.parser")
    result = {}

    # Site web
    site_links = soup.select('a[href*="http"]')
    excluded = ["pagesjaunes.fr", "at-internet", "weborama", "google", "facebook.com/tr",
                "airship", "cookielaw", "onetrust"]
    for a in site_links:
        href = a.get("href", "")
        text = a.get_text(strip=True).lower()
        stats = a.get("data-pjstats", "")
        # Check if it's a "voir le site" type link
        is_site_link = False
        if stats:
            try:
                tag = json.loads(stats).get("idTag", "")
                if "SITE" in tag.upper():
                    is_site_link = True
            except:
                pass
        if "site" in text or "web" in text or is_site_link:
            if href.startswith("http") and not any(ex in href for ex in excluded):
                result["site_web"] = href
                break

    # Si pas trouve via data-pjstats, chercher dans le HTML brut
    if "site_web" not in result:
        html_text = str(soup)
        urls = re.findall(
            r'https?://(?:www\.)?[a-zA-Z0-9._-]+\.[a-zA-Z]{2,}(?:/[^\s"<>\']*)?',
            html_text,
        )
        for url in urls:
            if not any(ex in url for ex in excluded):
                result["site_web"] = url
                break

    # Email
    emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', str(soup))
    excluded_emails = ["pagesjaunes", "solocal", "onetrust", "cookielaw"]
    for email in emails:
        if not any(ex in email.lower() for ex in excluded_emails):
            result["email"] = email
            break

    return result


def match_enterprises(source_data, pj_data):
    """Match les entreprises source avec les donnees PJ par fuzzy matching."""
    print(f"\n{'='*60}")
    print(f"Matching {len(source_data)} entreprises source avec {len(pj_data)} listings PJ")
    print(f"{'='*60}")

    matched = 0
    for ent in source_data:
        ent_name = normalize(ent.get("nom", ""))
        ent_addr = normalize(ent.get("adresse", ""))
        ent_cp = ent.get("code_postal", "")

        best_score = 0
        best_match = None

        for pj in pj_data:
            pj_name = normalize(pj.get("pj_nom", ""))
            pj_addr = normalize(pj.get("pj_adresse", ""))

            # Score base sur le nom
            name_score = fuzz.token_set_ratio(ent_name, pj_name)

            # Bonus si l'adresse matche aussi
            addr_score = fuzz.token_set_ratio(ent_addr, pj_addr) if ent_addr and pj_addr else 0

            # Bonus si le code postal est dans l'adresse PJ
            cp_bonus = 10 if ent_cp and ent_cp in pj.get("pj_adresse", "") else 0

            # Score combine
            combined = name_score * 0.7 + addr_score * 0.2 + cp_bonus

            if combined > best_score:
                best_score = combined
                best_match = pj

        # Seuil de matching
        MATCH_THRESHOLD = 60
        if best_score >= MATCH_THRESHOLD and best_match:
            ent["pj_match_score"] = round(best_score, 1)
            ent["pj_nom_trouve"] = best_match.get("pj_nom", "")
            ent["pj_telephone"] = best_match.get("pj_telephone", "")
            ent["pj_site_web"] = best_match.get("pj_site_web", "")
            ent["pj_adresse_pj"] = best_match.get("pj_adresse", "")
            ent["pj_detail_url"] = best_match.get("pj_detail_url", "")
            matched += 1
        else:
            ent["pj_match_score"] = round(best_score, 1) if best_match else 0
            ent["pj_nom_trouve"] = ""
            ent["pj_telephone"] = ""
            ent["pj_site_web"] = ""
            ent["pj_adresse_pj"] = ""
            ent["pj_detail_url"] = ""

    print(f"  Matches trouves: {matched}/{len(source_data)} ({matched*100//len(source_data)}%)")
    return source_data


def enrich_with_detail_pages(session, enriched_data, limit=None):
    """Pour les entreprises matchees sans site web, tente de recuperer via page detail."""
    import random

    candidates = [
        e for e in enriched_data
        if e.get("pj_detail_url") and not e.get("pj_site_web") and e.get("pj_match_score", 0) >= 55
    ]

    if limit:
        candidates = candidates[:limit]

    print(f"\nRecuperation des details pour {len(candidates)} entreprises sans site web...")

    for i, ent in enumerate(candidates):
        detail = fetch_detail_page(session, ent["pj_detail_url"])
        if detail.get("site_web"):
            ent["pj_site_web"] = detail["site_web"]
        if detail.get("email"):
            ent["pj_email"] = detail["email"]

        if (i + 1) % 10 == 0:
            print(f"  Detail {i+1}/{len(candidates)}")
            save_progress(enriched_data, OUTPUT_FILE)

        time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

    return enriched_data


def save_progress(data, filepath):
    """Sauvegarde la progression."""
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  [SAVE] {filepath} ({len(data)} entreprises)")


def load_progress():
    """Charge la progression precedente si elle existe."""
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def main():
    import random

    # Charger les donnees source
    with open(SOURCE_FILE, "r", encoding="utf-8") as f:
        source_data = json.load(f)
    print(f"Entreprises source: {len(source_data)}")

    # Mode test ?
    test_mode = "--test" in sys.argv
    if test_mode:
        print("\n*** MODE TEST : 1 page par categorie ***\n")

    # Creer la session curl_cffi
    session = requests.Session(impersonate="chrome")
    session.headers.update({
        "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    })

    # Verifier si progression existe
    progress = load_progress()
    if progress and not test_mode:
        print(f"Progression precedente trouvee: {len(progress)} listings PJ")
        pj_all_listings = progress
    else:
        # Scraper par categorie
        pj_all_listings = []
        categories_done = set()

        for cat, search_term in CATEGORY_SEARCH.items():
            max_pages = 2 if test_mode else MAX_PAGES_PER_CATEGORY
            listings = scrape_category(session, search_term, max_pages=max_pages)
            pj_all_listings.extend(listings)
            categories_done.add(cat)

            # Sauvegarder la progression
            with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
                json.dump(pj_all_listings, f, ensure_ascii=False, indent=2)
            print(f"  [PROGRESS] {len(pj_all_listings)} listings PJ total")

            # Delai entre categories
            time.sleep(random.uniform(2, 4))

    print(f"\nTotal listings PJ collectes: {len(pj_all_listings)}")

    # Deduplication par nom + adresse
    seen = set()
    unique_listings = []
    for l in pj_all_listings:
        key = normalize(l["pj_nom"]) + "|" + normalize(l["pj_adresse"])
        if key not in seen:
            seen.add(key)
            unique_listings.append(l)
    print(f"Listings uniques apres dedup: {len(unique_listings)}")

    # Matcher avec les entreprises source
    enriched = match_enterprises(source_data, unique_listings)

    # Sauvegarder le resultat
    save_progress(enriched, OUTPUT_FILE)

    # Recherche directe par nom pour les non-matches
    unmatched = [e for e in enriched if e.get("pj_match_score", 0) < 60]
    print(f"\nRecherche directe PJ pour {len(unmatched)} entreprises non matchees...")
    direct_found = 0
    for idx, ent in enumerate(unmatched):
        import random
        time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

        search_name = ent["nom"].split("(")[0].strip()  # Enlever les parentheses
        search_url = f"{BASE_URL}/recherche/lille-59/{quote(search_name)}"
        html = fetch_page(session, search_url)
        if not html:
            continue

        soup = BeautifulSoup(html, "html.parser")
        listings = soup.select("li.bi")

        ent_name = normalize(ent.get("nom", ""))
        ent_addr = normalize(ent.get("adresse", ""))
        ent_cp = ent.get("code_postal", "")

        for li in listings:
            data = extract_listing_data(li)
            pj_name = normalize(data.get("pj_nom", ""))
            pj_addr = normalize(data.get("pj_adresse", ""))
            name_score = fuzz.token_set_ratio(ent_name, pj_name)
            addr_score = fuzz.token_set_ratio(ent_addr, pj_addr) if ent_addr and pj_addr else 0
            cp_bonus = 10 if ent_cp and ent_cp in data.get("pj_adresse", "") else 0
            combined = name_score * 0.7 + addr_score * 0.2 + cp_bonus

            if combined >= 60:
                ent["pj_match_score"] = round(combined, 1)
                ent["pj_nom_trouve"] = data.get("pj_nom", "")
                ent["pj_telephone"] = data.get("pj_telephone", "")
                ent["pj_site_web"] = data.get("pj_site_web", "")
                ent["pj_adresse_pj"] = data.get("pj_adresse", "")
                ent["pj_detail_url"] = data.get("pj_detail_url", "")
                direct_found += 1
                break

        if (idx + 1) % 20 == 0:
            print(f"  Recherche directe {idx+1}/{len(unmatched)} (+{direct_found} trouves)")
            save_progress(enriched, OUTPUT_FILE)

        if test_mode and idx >= 4:
            break

    print(f"  Recherche directe: +{direct_found} entreprises matchees")
    save_progress(enriched, OUTPUT_FILE)

    # Enrichir avec les pages detail (sites web)
    if not test_mode:
        enriched = enrich_with_detail_pages(session, enriched)
        save_progress(enriched, OUTPUT_FILE)

    # Stats finales
    total = len(enriched)
    with_phone = sum(1 for e in enriched if e.get("pj_telephone"))
    with_web = sum(1 for e in enriched if e.get("pj_site_web"))
    with_email = sum(1 for e in enriched if e.get("pj_email"))
    high_match = sum(1 for e in enriched if e.get("pj_match_score", 0) >= 55)

    print(f"\n{'='*60}")
    print(f"RESULTATS FINAUX")
    print(f"{'='*60}")
    print(f"Total entreprises: {total}")
    print(f"Matchees (score >= 55): {high_match} ({high_match*100//total}%)")
    print(f"Avec telephone: {with_phone} ({with_phone*100//total}%)")
    print(f"Avec site web: {with_web} ({with_web*100//total}%)")
    print(f"Avec email: {with_email} ({with_email*100//total}%)")
    print(f"\nFichier sauvegarde: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
