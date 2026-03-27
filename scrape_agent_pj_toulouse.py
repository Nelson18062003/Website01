#!/usr/bin/env python3
"""
Agent scraper - Pages Jaunes Toulouse - toutes catégories auto/moto
Output: /home/user/Website01/agent_out_1_pj_toulouse.json
"""

import json
import re
import time
import base64
import unicodedata
import sys
import os
import subprocess

# ── Auto-install deps ──────────────────────────────────────────────────────────
def pip_install(*pkgs):
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", *pkgs])

try:
    from curl_cffi import requests as cffi_requests
    print("[OK] curl_cffi disponible")
except ImportError:
    print("[..] Installation curl_cffi...")
    pip_install("curl_cffi")
    from curl_cffi import requests as cffi_requests

try:
    from bs4 import BeautifulSoup
    print("[OK] beautifulsoup4 disponible")
except ImportError:
    print("[..] Installation beautifulsoup4 + lxml...")
    pip_install("beautifulsoup4", "lxml")
    from bs4 import BeautifulSoup

# ── Config ─────────────────────────────────────────────────────────────────────
BASE_DIR        = "/home/user/Website01"
CACHE_FILE      = os.path.join(BASE_DIR, "pj_cache_toulouse.json")
OUTPUT_FILE     = os.path.join(BASE_DIR, "agent_out_1_pj_toulouse.json")

CATEGORIES = [
    ("garage+automobile",     "toulouse+31", "garage automobile"),
    ("concession+automobile", "toulouse+31", "concession automobile"),
    ("carrosserie+automobile","toulouse+31", "carrosserie automobile"),
    ("garage+moto",           "toulouse+31", "garage moto"),
    ("concession+moto",       "toulouse+31", "concession moto"),
]

MAX_PAGES   = 50
DELAY_SEC   = 2
CACHE_KEY_PREFIX = "cat_"

HEADERS = {
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Referer": "https://www.pagesjaunes.fr/",
}

PJ_URL = "https://www.pagesjaunes.fr/annuaire/chercherlespros?quoiqui={quoi}&ou={ou}&page={page}"

TEL_RE = re.compile(r'0[1-9][\s.]?\d{2}[\s.]?\d{2}[\s.]?\d{2}[\s.]?\d{2}')
PAGE_COUNT_RE = re.compile(r'(\d+)\s*$')

# ── Helpers ────────────────────────────────────────────────────────────────────
def decode_pjlb_url(s: str) -> str:
    try:
        d = json.loads(s)
        u = d.get('url', '')
        if u:
            pad = 4 - len(u) % 4
            if pad != 4:
                u += '=' * pad
            return base64.b64decode(u).decode('utf-8', 'ignore')
    except Exception:
        pass
    return ''


def normalize_name(name: str) -> str:
    """Normalise pour déduplication : minuscules, sans accents, sans ponctuation."""
    s = unicodedata.normalize('NFD', name.lower())
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = re.sub(r'[^a-z0-9\s]', '', s)
    return re.sub(r'\s+', ' ', s).strip()


def load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"[WARN] Cache illisible : {e}")
    return {}


def save_cache(cache: dict):
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def get_page(session, quoi: str, ou: str, page: int) -> str | None:
    url = PJ_URL.format(quoi=quoi, ou=ou, page=page)
    try:
        resp = session.get(url, headers=HEADERS, timeout=30, impersonate="chrome")
        if resp.status_code == 200:
            return resp.text
        else:
            print(f"  [WARN] HTTP {resp.status_code} pour {url}")
            return None
    except Exception as e:
        print(f"  [ERR] {e} pour {url}")
        return None


def parse_total_pages(html: str) -> int:
    """Extrait le nombre total de pages depuis le compteur de pagination."""
    # ex : « 1-20 / 1000 résultats » → plusieurs pages
    # .pagination-compteur contient souvent "Page X sur Y"
    soup = BeautifulSoup(html, 'lxml')

    # Essai 1 : pagination-compteur
    counter = soup.select_one('.pagination-compteur')
    if counter:
        text = counter.get_text()
        m = PAGE_COUNT_RE.search(text)
        if m:
            return int(m.group(1))

    # Essai 2 : dernier numéro de page dans les liens de pagination
    page_links = soup.select('a[href*="page="]')
    max_p = 1
    for a in page_links:
        href = a.get('href', '')
        m = re.search(r'page=(\d+)', href)
        if m:
            max_p = max(max_p, int(m.group(1)))
    if max_p > 1:
        return max_p

    # Essai 3 : data-nb-pages
    elem = soup.find(attrs={"data-nb-pages": True})
    if elem:
        try:
            return int(elem['data-nb-pages'])
        except Exception:
            pass

    return 1


def parse_listings(html: str, category_label: str) -> list[dict]:
    """Parse une page HTML PJ et retourne les annonces trouvées."""
    soup = BeautifulSoup(html, 'lxml')
    results = []

    listings = soup.select('li.bi')
    if not listings:
        # Fallback : chercher d'autres conteneurs
        listings = soup.select('[class*="bi-content"]')

    for li in listings:
        # Nom
        nom_el = li.select_one('.bi-denomination')
        if not nom_el:
            nom_el = li.select_one('[class*="denomination"]')
        nom = nom_el.get_text(strip=True) if nom_el else ''
        if not nom:
            continue

        # Adresse
        addr_el = li.select_one('a.bi-address') or li.select_one('[class*="bi-address"]')
        adresse = ''
        code_postal = ''
        ville = ''
        if addr_el:
            adresse = addr_el.get_text(strip=True)
            # Extraction CP + ville
            m_cp = re.search(r'(\d{5})\s+(.+)$', adresse)
            if m_cp:
                code_postal = m_cp.group(1)
                ville = m_cp.group(2).strip()

        # Téléphone (regex dans le HTML brut du li)
        li_html = str(li)
        tel_match = TEL_RE.search(li_html)
        telephone = tel_match.group(0) if tel_match else ''

        # Site web (data-pjlb base64)
        website = ''
        web_el = li.select_one('a.bi-website[data-pjlb]')
        if web_el:
            website = decode_pjlb_url(web_el.get('data-pjlb', ''))
        if not website:
            # Fallback : href direct s'il commence par http
            if web_el and web_el.get('href', '').startswith('http'):
                website = web_el['href']

        # URL PJ
        url_pj = ''
        detail_el = li.select_one('a.bi-denomination') or li.select_one('a[href*="/pros/"]')
        if detail_el:
            href = detail_el.get('href', '')
            if href.startswith('http'):
                url_pj = href
            elif href.startswith('/'):
                url_pj = 'https://www.pagesjaunes.fr' + href

        results.append({
            "nom":          nom,
            "adresse":      adresse,
            "code_postal":  code_postal,
            "ville":        ville,
            "telephone":    telephone,
            "site_web":     website,
            "url_pj":       url_pj,
            "categorie":    category_label,
        })

    return results


# ── Scraping d'une catégorie ───────────────────────────────────────────────────
def scrape_category(session, quoi: str, ou: str, label: str) -> list[dict]:
    all_items: list[dict] = []
    print(f"\n[CAT] {label} ({quoi} / {ou})")

    # Page 1
    html1 = get_page(session, quoi, ou, 1)
    if not html1:
        print("  [FAIL] Impossible d'accéder à la page 1")
        return []

    total_pages = min(parse_total_pages(html1), MAX_PAGES)
    page1_items = parse_listings(html1, label)
    all_items.extend(page1_items)
    print(f"  Page 1/{total_pages} → {len(page1_items)} annonces")

    for page in range(2, total_pages + 1):
        time.sleep(DELAY_SEC)
        html = get_page(session, quoi, ou, page)
        if not html:
            print(f"  [SKIP] Page {page} non disponible")
            continue
        items = parse_listings(html, label)
        all_items.extend(items)
        print(f"  Page {page}/{total_pages} → {len(items)} annonces (total: {len(all_items)})")
        if not items:
            print("  [STOP] Aucun résultat, arrêt pagination")
            break

    print(f"  => Total catégorie '{label}': {len(all_items)} annonces")
    return all_items


# ── Conversion cache → format de sortie ───────────────────────────────────────
def convert_cache_entry(entry: dict, label: str) -> dict:
    """Convertit une entrée de cache ancien format vers le format de sortie."""
    nom = entry.get('nom_pj') or entry.get('nom', '')
    adresse = entry.get('adresse_pj') or entry.get('adresse', '')
    cp = entry.get('code_postal_pj') or entry.get('code_postal', '')
    ville = entry.get('ville_pj') or entry.get('ville', '')
    tel = entry.get('telephone', '')
    site = entry.get('site_web', '')
    url = entry.get('url_pj', '')
    cat = entry.get('search_category') or entry.get('categorie', label)

    # Extraire CP/ville depuis adresse si absent
    if adresse and not cp:
        m = re.search(r'(\d{5})\s+(.+)$', adresse)
        if m:
            cp = m.group(1)
            ville = m.group(2).strip()

    return {
        "nom":         nom,
        "adresse":     adresse,
        "code_postal": cp,
        "ville":       ville,
        "telephone":   tel,
        "site_web":    site,
        "url_pj":      url,
        "categorie":   cat,
    }


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("SCRAPER PAGES JAUNES - TOULOUSE - Auto/Moto")
    print("=" * 60)

    cache = load_cache()
    all_results: list[dict] = []
    stats: dict[str, int] = {}

    # Créer une session curl_cffi
    session = cffi_requests.Session()

    for quoi, ou, label in CATEGORIES:
        cache_key = CACHE_KEY_PREFIX + label
        fresh_data = None

        # Tentative de scraping live
        try:
            fresh_data = scrape_category(session, quoi, ou, label)
        except Exception as e:
            print(f"  [ERR] Scraping live échoué : {e}")
            fresh_data = None

        if fresh_data and len(fresh_data) > 0:
            # Utiliser les données fraîches
            print(f"  [OK] Données fraîches utilisées : {len(fresh_data)} entrées")
            # Mettre à jour le cache dans le nouveau format
            cache[cache_key] = fresh_data
            save_cache(cache)
            category_items = fresh_data
        elif cache_key in cache and cache[cache_key]:
            # Fallback cache
            raw_cache = cache[cache_key]
            print(f"  [CACHE] Utilisation cache : {len(raw_cache)} entrées pour '{label}'")
            # Normaliser le format si besoin
            category_items = []
            for entry in raw_cache:
                if 'nom' in entry and 'categorie' in entry:
                    # Déjà au bon format
                    category_items.append(entry)
                else:
                    category_items.append(convert_cache_entry(entry, label))
        else:
            print(f"  [WARN] Aucune donnée pour '{label}'")
            category_items = []

        stats[label] = len(category_items)
        all_results.extend(category_items)

    # ── Déduplication ──────────────────────────────────────────────────────────
    print("\n[DEDUP] Déduplication par nom normalisé...")
    seen: set[str] = set()
    unique_results: list[dict] = []
    for item in all_results:
        key = normalize_name(item.get('nom', ''))
        if key and key not in seen:
            seen.add(key)
            unique_results.append(item)

    # ── Sauvegarde ─────────────────────────────────────────────────────────────
    output = {
        "meta": {
            "source":     "Pages Jaunes",
            "zone":       "Toulouse (31)",
            "categories": list(stats.keys()),
            "total_brut": len(all_results),
            "total_unique": len(unique_results),
            "stats_par_categorie": stats,
            "date_extraction": time.strftime("%Y-%m-%dT%H:%M:%S"),
        },
        "etablissements": unique_results,
    }

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # ── Résumé ─────────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("RÉSUMÉ")
    print("=" * 60)
    for label, count in stats.items():
        print(f"  {label:<30} : {count:>5} entrées")
    print(f"  {'TOTAL BRUT':<30} : {len(all_results):>5} entrées")
    print(f"  {'TOTAL UNIQUE (dédoublonné)':<30} : {len(unique_results):>5} entrées")
    print(f"\n  Fichier de sortie : {OUTPUT_FILE}")
    print("=" * 60)


if __name__ == "__main__":
    main()
