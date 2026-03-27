#!/usr/bin/env python3
"""
Scrape PagesJaunes for Toulouse and Évry using curl (bypasses Cloudflare).
Categories: garage automobile, concession automobile, carrosserie automobile, garage moto, concession moto
"""

import json
import re
import time
import os
import sys
import subprocess

try:
    from bs4 import BeautifulSoup
except ImportError:
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'beautifulsoup4', 'lxml'])
    from bs4 import BeautifulSoup

BASE_DIR = "/home/user/Website01"
OUTPUT_TOULOUSE = os.path.join(BASE_DIR, "agent_out_playwright_toulouse.json")
OUTPUT_EVRY = os.path.join(BASE_DIR, "agent_out_playwright_evry.json")
CACHE_TOULOUSE = os.path.join(BASE_DIR, "cache_curl_toulouse.json")
CACHE_EVRY = os.path.join(BASE_DIR, "cache_curl_evry.json")

CATEGORIES = [
    "garage+automobile",
    "concession+automobile",
    "carrosserie+automobile",
    "garage+moto",
    "concession+moto",
]

TOULOUSE_LOCATIONS = ["toulouse+31"]
EVRY_LOCATIONS = [
    "evry+91",
    "corbeil-essonnes+91",
    "ris-orangis+91",
    "lisses+91",
    "bondoufle+91",
]

MAX_PAGES = 50

PROXY = (
    os.environ.get('https_proxy')
    or os.environ.get('HTTPS_PROXY')
    or os.environ.get('http_proxy')
    or os.environ.get('HTTP_PROXY')
    or ''
)

HEADERS = [
    '-H', 'Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    '-H', 'Accept-Language: fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7',
    '-H', 'Accept-Encoding: identity',
    '-H', 'Connection: keep-alive',
    '-H', 'Upgrade-Insecure-Requests: 1',
    '-H', 'Cache-Control: no-cache',
]

USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'

# Cookie jar path
COOKIE_JAR = os.path.join(BASE_DIR, 'pj_cookies.txt')


def fetch_url(url, use_cookies=True):
    """Fetch URL via curl with proxy and cookies."""
    cmd = [
        'curl', '-s',
        '-A', USER_AGENT,
        '--insecure',
        '--max-time', '45',
        '--retry', '2',
        '--retry-delay', '3',
    ] + HEADERS

    if PROXY:
        cmd += ['--proxy', PROXY]

    if use_cookies:
        cmd += ['-b', COOKIE_JAR, '-c', COOKIE_JAR]

    cmd.append(url)

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=60)
        if result.returncode != 0:
            print(f"    curl error code {result.returncode}: {result.stderr.decode()[:200]}")
            return None
        return result.stdout.decode('utf-8', errors='replace')
    except subprocess.TimeoutExpired:
        print("    curl timeout")
        return None
    except Exception as e:
        print(f"    curl exception: {e}")
        return None


def init_cookies():
    """Visit homepage to get cookies."""
    print("Initializing cookies from homepage...")
    # Create empty cookie jar if it doesn't exist
    if not os.path.exists(COOKIE_JAR):
        open(COOKIE_JAR, 'w').close()

    html = fetch_url("https://www.pagesjaunes.fr", use_cookies=True)
    if html and len(html) > 1000:
        print(f"  Homepage fetched ({len(html)} bytes)")
        if 'instant' in html.lower()[:500]:
            print("  Warning: Got Cloudflare challenge on homepage")
        else:
            print("  Homepage OK")
    else:
        print("  Warning: Homepage fetch returned little/no content")
    time.sleep(3)


def extract_listings(soup):
    """Extract listings from BeautifulSoup object."""
    items = soup.select('li[id^="bi-"]')
    if not items:
        items = soup.select('.bi-generic')

    results = []
    for item in items:
        entry = {}

        # Name - get from h3/h2 inside .bi-denomination
        denom_el = item.select_one('.bi-denomination, .bi-header-title a')
        if denom_el:
            h_el = denom_el.select_one('h3, h2')
            if h_el:
                entry['nom_pj'] = h_el.get_text(strip=True)
            else:
                # Get text while ignoring tooltip children
                name_parts = []
                for child in denom_el.children:
                    if hasattr(child, 'name'):
                        if child.name in ('h3', 'h2', 'span') and not child.get('class'):
                            name_parts.append(child.get_text(strip=True))
                    else:
                        t = str(child).strip()
                        if t:
                            name_parts.append(t)
                entry['nom_pj'] = ' '.join(name_parts).strip()

        if not entry.get('nom_pj'):
            continue

        # Address
        addr_el = item.select_one('.bi-address')
        if addr_el:
            addr_text = addr_el.get_text(' ', strip=True)
            addr_text = re.sub(r'\s*Voir le plan\s*', ' ', addr_text)
            addr_text = re.sub(r'\s+', ' ', addr_text).strip()
            if addr_text:
                entry['adresse_pj'] = addr_text

        # Phone from text
        text = item.get_text()
        phones = re.findall(r'0[1-9](?:[\s\.\-]?[0-9]{2}){4}', text)
        if phones:
            entry['telephone'] = re.sub(r'[\s\.\-]', '', phones[0])

        # PJ internal ID
        bi_id = item.get('id', '').replace('bi-', '')
        if bi_id:
            entry['pj_id'] = bi_id

        results.append(entry)

    return results


def get_total_pages(soup):
    """Extract total page count from pagination."""
    pag = soup.select_one('.pagination-compteur')
    if pag:
        text = pag.get_text(strip=True)
        m = re.search(r'/\s*(\d+)', text)
        if m:
            return int(m.group(1))

    # Try page links
    max_page = 1
    for a in soup.select('.pagination a, a.link_pagination'):
        n_text = a.get_text(strip=True)
        try:
            n = int(n_text)
            if n > max_page:
                max_page = n
        except ValueError:
            pass

    return max_page


def normalize_name(name):
    if not name:
        return ""
    name = name.upper()
    name = re.sub(r'\b(SARL|SAS|SA|EURL|SCI|SNC|AUTO|AUTOMOBILES?|GARAGE|CARROSSERIE)\b', '', name)
    name = re.sub(r'\(.*?\)', '', name)
    name = re.sub(r'[^A-Z0-9\s]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def extract_postal_city(address):
    """Extract postal code and city from address string."""
    if not address:
        return None, None
    m = re.search(r'(\d{5})\s+(.+?)(?:\s+Voir le plan)?$', address)
    if m:
        return m.group(1), m.group(2).strip()
    return None, None


def is_cloudflare_challenge(html):
    """Detect Cloudflare challenge page."""
    if not html or len(html) > 30000:
        return False
    indicators = [
        'challenge-platform',
        'cf-turnstile',
        'Sécurité\nAfin de nous aider',
        'veuillez compléter le',
        'Enable JavaScript and cookies to continue',
    ]
    for ind in indicators:
        if ind in html:
            return True
    if len(html) < 15000 and ('Un instant' in html[:3000] or 'Trouvez plus que des coord' in html[:3000]):
        return True
    return False


def scrape_category_location(category, location, cache):
    """Scrape all pages for a given category+location combo."""
    cache_key = f"{category}_{location}"
    if cache_key in cache:
        print(f"  [CACHE] {category} @ {location}: {len(cache[cache_key])} results")
        return cache[cache_key]

    all_results = []
    base_url = "https://www.pagesjaunes.fr/annuaire/chercherlespros"

    print(f"\n  Scraping: {category} @ {location}")

    total_pages = None
    cf_retries = 0
    MAX_CF_RETRIES = 3

    page_num = 1
    while page_num <= MAX_PAGES:
        url = f"{base_url}?quoiqui={category}&ou={location}&page={page_num}"
        print(f"    Page {page_num}/{total_pages or '?'}: ", end='', flush=True)

        html = fetch_url(url)

        if not html:
            print("fetch failed")
            if page_num == 1:
                break
            break

        print(f"{len(html)} bytes", end='')

        # Check for Cloudflare challenge
        if is_cloudflare_challenge(html):
            cf_retries += 1
            print(f" [CLOUDFLARE CF#{cf_retries}]")
            if cf_retries <= MAX_CF_RETRIES:
                wait_time = 15 * cf_retries
                print(f"    Waiting {wait_time}s before retry...")
                time.sleep(wait_time)
                continue  # retry same page
            else:
                print(f"    Max CF retries reached, stopping this combo")
                break
        else:
            cf_retries = 0  # reset on success

        soup = BeautifulSoup(html, 'lxml')

        # Check for no results
        page_text = soup.get_text()
        if any(x in page_text for x in ["Aucun résultat", "aucun résultat", "0 résultat"]):
            print(" [NO RESULTS]")
            break

        if page_num == 1:
            total_pages = get_total_pages(soup)
            print(f" (total pages: {total_pages})")
        else:
            print()

        listings = extract_listings(soup)
        print(f"      Found {len(listings)} listings")

        if not listings:
            if page_num == 1:
                # Save debug
                with open(os.path.join(BASE_DIR, f"debug_nolisting_{category}_{location}.html"), 'w') as f:
                    f.write(html)
                print("    No listings on page 1, stopping (debug saved)")
            break

        # Enrich with metadata
        for r in listings:
            r["categorie"] = category.replace("+", " ")
            r["location_query"] = location
            cp, ville = extract_postal_city(r.get("adresse_pj", ""))
            if cp:
                r["code_postal"] = cp
            if ville:
                r["ville"] = ville

        all_results.extend(listings)
        print(f"      Cumulative: {len(all_results)}")

        if total_pages and page_num >= total_pages:
            break

        page_num += 1
        time.sleep(3)

    print(f"    Total for {category} @ {location}: {len(all_results)}")
    cache[cache_key] = all_results
    return all_results


def deduplicate(results):
    """Remove duplicates by normalized name."""
    seen = set()
    unique = []
    for r in results:
        key = normalize_name(r.get("nom_pj", ""))
        if key and key not in seen:
            seen.add(key)
            unique.append(r)
        elif not key:
            unique.append(r)
    return unique


def print_summary(label, results):
    """Print summary statistics."""
    from collections import Counter
    print(f"\n{'='*60}")
    print(f"SUMMARY: {label}")
    print(f"{'='*60}")
    print(f"Total entries: {len(results)}")
    print(f"With telephone: {sum(1 for r in results if r.get('telephone'))}")
    print(f"With adresse: {sum(1 for r in results if r.get('adresse_pj'))}")

    by_cat = Counter(r.get("categorie", "unknown") for r in results)
    print("\nBy category:")
    for cat, count in sorted(by_cat.items()):
        print(f"  {cat}: {count}")

    by_loc = Counter(r.get("location_query", "unknown") for r in results)
    print("\nBy location:")
    for loc, count in sorted(by_loc.items()):
        print(f"  {loc}: {count}")


def load_cache(cache_file):
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_cache(cache, cache_file):
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def run_scraping(categories, locations, cache, cache_file):
    """Run scraping for all category/location combos."""
    all_results = []
    for location in locations:
        for category in categories:
            results = scrape_category_location(category, location, cache)
            all_results.extend(results)
            save_cache(cache, cache_file)
            time.sleep(4)
    return all_results


def main():
    print("Starting PagesJaunes curl scraper for Toulouse and Évry...")
    print(f"Proxy: {PROXY[:60]}..." if PROXY else "No proxy configured")

    # Initialize cookies
    init_cookies()

    # Load caches
    cache_toulouse = load_cache(CACHE_TOULOUSE)
    cache_evry = load_cache(CACHE_EVRY)

    # ─── TOULOUSE ───
    print("\n" + "="*60)
    print("ZONE 1: TOULOUSE")
    print("="*60)

    toulouse_raw = run_scraping(CATEGORIES, TOULOUSE_LOCATIONS, cache_toulouse, CACHE_TOULOUSE)
    toulouse_unique = deduplicate(toulouse_raw)

    with open(OUTPUT_TOULOUSE, "w", encoding="utf-8") as f:
        json.dump(toulouse_unique, f, ensure_ascii=False, indent=2)
    print(f"\nSaved {len(toulouse_unique)} entries to {OUTPUT_TOULOUSE}")
    print_summary("TOULOUSE", toulouse_unique)

    time.sleep(5)

    # ─── ÉVRY ───
    print("\n" + "="*60)
    print("ZONE 2: ÉVRY ET BANLIEUE")
    print("="*60)

    evry_raw = run_scraping(CATEGORIES, EVRY_LOCATIONS, cache_evry, CACHE_EVRY)
    evry_unique = deduplicate(evry_raw)

    with open(OUTPUT_EVRY, "w", encoding="utf-8") as f:
        json.dump(evry_unique, f, ensure_ascii=False, indent=2)
    print(f"\nSaved {len(evry_unique)} entries to {OUTPUT_EVRY}")
    print_summary("ÉVRY ET BANLIEUE", evry_unique)

    print("\n" + "="*60)
    print("DONE")
    print(f"Toulouse: {OUTPUT_TOULOUSE}")
    print(f"Évry:     {OUTPUT_EVRY}")


if __name__ == "__main__":
    main()
