#!/usr/bin/env python3
"""
Scrape PagesJaunes for Toulouse and Évry (banlieue) using Playwright stealth.
Categories: garage automobile, concession automobile, carrosserie automobile, garage moto, concession moto
"""

import json
import re
import time
import os
import sys
import subprocess
import urllib.parse

# Install playwright if needed
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
except ImportError:
    print("Installing playwright...")
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'playwright'])
    subprocess.check_call([sys.executable, '-m', 'playwright', 'install', 'chromium'])
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

BASE_DIR = "/home/user/Website01"
OUTPUT_TOULOUSE = os.path.join(BASE_DIR, "agent_out_playwright_toulouse.json")
OUTPUT_EVRY = os.path.join(BASE_DIR, "agent_out_playwright_evry.json")
CACHE_TOULOUSE = os.path.join(BASE_DIR, "cache_toulouse.json")
CACHE_EVRY = os.path.join(BASE_DIR, "cache_evry.json")

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


def extract_listings(page):
    """Extract listings from current PagesJaunes page using JS evaluation."""
    try:
        page.wait_for_selector(
            "li[id^='bi-'], .bi-generic, .bi-content-wrapper, .bi-denomination, .bi-header-title",
            timeout=10000
        )
    except PlaywrightTimeout:
        print("    No listing elements found on page")
        return []

    results = page.evaluate("""() => {
        const listings = [];

        // Strategy 1: li[id^="bi-"]
        let items = document.querySelectorAll('li[id^="bi-"]');

        // Strategy 2: .bi-generic
        if (items.length === 0) {
            items = document.querySelectorAll('.bi-generic');
        }

        // Strategy 3: .bi-content-wrapper
        if (items.length === 0) {
            items = document.querySelectorAll('.bi-content-wrapper, .bi-bloc');
        }

        items.forEach(item => {
            const nameEl = item.querySelector(
                '.bi-denomination a, .bi-header-title a, h3 a, h2 a, .denomination-links a, .bi-denomination, .bi-header-title'
            );
            if (!nameEl) return;
            const entry = { nom_pj: nameEl.textContent.trim() };

            const addrEl = item.querySelector('.bi-address, .bi-adresse, .address, [class*="address"]');
            if (addrEl) entry.adresse_pj = addrEl.textContent.replace(/\\s+/g, ' ').trim();

            const phoneEl = item.querySelector('a[href^="tel:"], .bi-phone-number, .click_phone_number');
            if (phoneEl) {
                entry.telephone = (phoneEl.getAttribute('href') || phoneEl.textContent || '')
                    .replace('tel:', '').trim();
            }

            const webEl = item.querySelector(
                'a.bi-website, a[data-pjlabel="site_internet"], a.pj-link--website, a[class*="website"]'
            );
            if (webEl) entry.site_web = webEl.getAttribute('href') || webEl.textContent.trim();

            const emailEl = item.querySelector('a[href^="mailto:"]');
            if (emailEl) entry.email = emailEl.getAttribute('href').replace('mailto:', '').trim();

            listings.push(entry);
        });
        return listings;
    }""")
    return results or []


def get_pagination_info(page):
    """Get total pages from pagination."""
    return page.evaluate("""() => {
        // Try pagination counter text
        const counter = document.querySelector('.pagination-compteur, .pagination-info, .nb-results');
        let totalPages = 1;

        if (counter) {
            const text = counter.innerText || counter.textContent;
            const m = text.match(/(\\d+)\\s*$/) || text.match(/sur\\s+(\\d+)/i);
            if (m) totalPages = Math.ceil(parseInt(m[1]) / 20);
        }

        // Try explicit page links
        const pageLinks = document.querySelectorAll('.pagination a, a.link_pagination, a[aria-label*="Page "]');
        pageLinks.forEach(a => {
            const n = parseInt(a.textContent.trim());
            if (!isNaN(n) && n > totalPages) totalPages = n;
        });

        // Check for next button
        const nextBtn = document.querySelector(
            'a#pagination-next, a.next, a[title="Page suivante"], a.pagination-next, a[aria-label*="suivant"], a[aria-label*="next"]'
        );

        return {
            hasNext: !!nextBtn,
            totalPages: totalPages
        };
    }""")


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
    m = re.search(r'(\d{5})\s+(.+)$', address)
    if m:
        return m.group(1), m.group(2).strip()
    return None, None


def scrape_category_location(browser_page, category, location, cache):
    """Scrape all pages for a given category+location combo."""
    cache_key = f"{category}_{location}"
    if cache_key in cache:
        print(f"  [CACHE] {category} @ {location}: {len(cache[cache_key])} results")
        return cache[cache_key]

    all_results = []
    base_url = "https://www.pagesjaunes.fr/annuaire/chercherlespros"

    print(f"\n  Scraping: {category} @ {location}")

    for page_num in range(1, MAX_PAGES + 1):
        url = f"{base_url}?quoiqui={category}&ou={location}&page={page_num}"
        print(f"    Page {page_num}: {url}")

        try:
            browser_page.goto(url, wait_until="domcontentloaded", timeout=45000)
            time.sleep(3)

            title = browser_page.title()
            print(f"      Title: {title}")

            # Check for Cloudflare challenge
            if any(x in title.lower() for x in ["moment", "just a", "challenge", "captcha", "attention required"]):
                print("      Cloudflare challenge detected, waiting 15s...")
                time.sleep(15)
                title = browser_page.title()
                print(f"      Title after wait: {title}")
                if any(x in title.lower() for x in ["moment", "just a", "challenge"]):
                    print("      Still blocked, taking screenshot and skipping")
                    browser_page.screenshot(
                        path=os.path.join(BASE_DIR, f"cf_block_{category}_{location}_p{page_num}.png")
                    )
                    break

            content = browser_page.content()

            # Check for no results
            if any(x in content for x in ["Aucun résultat", "aucun résultat", "0 résultat", "Aucune entreprise"]):
                print("      No results found")
                break

            # Check for page beyond results
            if page_num > 1 and "page introuvable" in content.lower():
                print("      Page not found, stopping")
                break

            listings = extract_listings(browser_page)
            print(f"      Found {len(listings)} listings")

            if not listings:
                browser_page.screenshot(
                    path=os.path.join(BASE_DIR, f"debug_{category}_{location}_p{page_num}.png")
                )
                if page_num == 1:
                    print("      No listings on page 1, stopping")
                    break
                else:
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

            # Pagination check
            pag = get_pagination_info(browser_page)
            print(f"      Pagination: hasNext={pag['hasNext']}, totalPages={pag['totalPages']}")

            if not pag['hasNext'] and page_num >= pag['totalPages']:
                break

            time.sleep(3)

        except PlaywrightTimeout as e:
            print(f"      Timeout: {e}")
            break
        except Exception as e:
            print(f"      Error: {e}")
            try:
                browser_page.screenshot(
                    path=os.path.join(BASE_DIR, f"error_{category}_{location}_p{page_num}.png")
                )
            except Exception:
                pass
            break

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
    print(f"\n{'='*60}")
    print(f"SUMMARY: {label}")
    print(f"{'='*60}")
    print(f"Total entries: {len(results)}")
    print(f"With telephone: {sum(1 for r in results if r.get('telephone'))}")
    print(f"With site web: {sum(1 for r in results if r.get('site_web'))}")
    print(f"With email: {sum(1 for r in results if r.get('email'))}")

    # By category
    from collections import Counter
    by_cat = Counter(r.get("categorie", "unknown") for r in results)
    print("\nBy category:")
    for cat, count in sorted(by_cat.items()):
        print(f"  {cat}: {count}")

    # By location
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


def run_scraping(browser_page, categories, locations, cache, cache_file):
    """Run scraping for all category/location combos."""
    all_results = []
    for location in locations:
        for category in categories:
            results = scrape_category_location(browser_page, category, location, cache)
            all_results.extend(results)
            # Save cache after each combo
            save_cache(cache, cache_file)
            time.sleep(5)
    return all_results


def main():
    print("Starting PagesJaunes scraper for Toulouse and Évry...")

    # Load caches
    cache_toulouse = load_cache(CACHE_TOULOUSE)
    cache_evry = load_cache(CACHE_EVRY)

    # Build proxy config from environment
    proxy_config = None
    proxy_env = os.environ.get('https_proxy') or os.environ.get('HTTPS_PROXY') or \
                os.environ.get('http_proxy') or os.environ.get('HTTP_PROXY')
    if proxy_env:
        m = re.match(r'http://([^:]+):(.+)@(.+)', proxy_env)
        if m:
            proxy_config = {
                'server': f'http://{m.group(3)}',
                'username': m.group(1),
                'password': m.group(2),
            }
            print(f"Using proxy: {proxy_config['server']}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--window-size=1920,1080',
                '--ignore-certificate-errors',
            ],
            proxy=proxy_config,
        )
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="fr-FR",
            timezone_id="Europe/Paris",
            ignore_https_errors=True,
        )

        # Stealth: mask webdriver detection
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => false });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['fr-FR', 'fr', 'en-US', 'en'] });
            window.chrome = { runtime: {} };
        """)

        page = context.new_page()

        # Visit homepage first to get cookies
        print("\nVisiting PagesJaunes homepage to get cookies...")
        page.goto("https://www.pagesjaunes.fr", wait_until="domcontentloaded", timeout=30000)
        time.sleep(5)

        # Accept cookies
        try:
            consent = page.query_selector(
                '#didomi-notice-agree-button, button[id*="accept"], button[id*="consent"], .didomi-button'
            )
            if consent:
                consent.click()
                print("Accepted cookies")
                time.sleep(2)
        except Exception:
            pass

        title = page.title()
        print(f"Homepage title: {title}")

        # ─── TOULOUSE ───
        print("\n" + "="*60)
        print("ZONE 1: TOULOUSE")
        print("="*60)

        toulouse_raw = run_scraping(page, CATEGORIES, TOULOUSE_LOCATIONS, cache_toulouse, CACHE_TOULOUSE)
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

        evry_raw = run_scraping(page, CATEGORIES, EVRY_LOCATIONS, cache_evry, CACHE_EVRY)
        evry_unique = deduplicate(evry_raw)

        with open(OUTPUT_EVRY, "w", encoding="utf-8") as f:
            json.dump(evry_unique, f, ensure_ascii=False, indent=2)
        print(f"\nSaved {len(evry_unique)} entries to {OUTPUT_EVRY}")
        print_summary("ÉVRY ET BANLIEUE", evry_unique)

        browser.close()

    print("\n" + "="*60)
    print("DONE")
    print(f"Toulouse: {OUTPUT_TOULOUSE}")
    print(f"Évry:     {OUTPUT_EVRY}")


if __name__ == "__main__":
    main()
