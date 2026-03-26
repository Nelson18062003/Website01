#!/usr/bin/env python3
"""
Scrape PagesJaunes by category for Lyon using Playwright to bypass Cloudflare.
Then fuzzy-match with split_lyon.json to enrich company records.
"""

import json
import re
import time
import os
import sys
from difflib import SequenceMatcher
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

BASE_DIR = "/home/user/Website01"
SOURCE_FILE = os.path.join(BASE_DIR, "split_lyon.json")
OUTPUT_FILE = os.path.join(BASE_DIR, "enriched_lyon_pj.json")
PJ_CACHE_FILE = os.path.join(BASE_DIR, "pj_results_cache.json")

CATEGORIES = [
    ("garage automobile", "garage-automobile"),
    ("concession automobile", "concession-automobile"),
    ("carrosserie automobile", "carrosserie-automobile"),
    ("concession moto", "concession-moto"),
    ("garage moto", "garage-moto"),
]

DELAY = 2


def extract_listings(page):
    """Extract listings from current PagesJaunes page using JS evaluation."""
    # Wait for results to load
    try:
        page.wait_for_selector(".bi-generic, .bi-bloc, [data-pjid], .bi-header-title, .bi-denomination", timeout=10000)
    except PlaywrightTimeout:
        print("    No listing elements found on page")
        return []

    results = page.evaluate("""() => {
        const listings = [];
        // Try multiple selector strategies
        const items = document.querySelectorAll('li[id^="bi-"]') ||
                      document.querySelectorAll('.bi-generic') ||
                      document.querySelectorAll('[data-pjid]');

        if (items.length === 0) {
            // Fallback: try broader selector
            const items2 = document.querySelectorAll('.bi-content-wrapper, .bi-bloc');
            items2.forEach(item => {
                const nameEl = item.querySelector('.bi-denomination a, .bi-header-title a, h3 a, h2 a, .denomination-links a');
                if (!nameEl) return;
                const entry = { pj_nom: nameEl.textContent.trim() };

                const addrEl = item.querySelector('.bi-address, .bi-adresse, .address');
                if (addrEl) entry.pj_adresse = addrEl.textContent.replace(/\\s+/g, ' ').trim();

                const phoneEl = item.querySelector('.bi-phone-number, .click_phone_number, a[href^="tel:"]');
                if (phoneEl) {
                    entry.pj_telephone = (phoneEl.getAttribute('href') || phoneEl.textContent || '').replace('tel:', '').trim();
                }

                const webEl = item.querySelector('a.bi-website, a[data-pjlabel="site_internet"], a.pj-link--website');
                if (webEl) entry.pj_site_web = webEl.getAttribute('href') || webEl.textContent.trim();

                const emailEl = item.querySelector('a[href^="mailto:"]');
                if (emailEl) entry.pj_email = emailEl.getAttribute('href').replace('mailto:', '').trim();

                listings.push(entry);
            });
            return listings;
        }

        items.forEach(item => {
            const nameEl = item.querySelector('.bi-denomination a, .bi-header-title a, h3 a, h2 a, .denomination-links a');
            if (!nameEl) return;
            const entry = { pj_nom: nameEl.textContent.trim() };

            const addrEl = item.querySelector('.bi-address, .bi-adresse, .address');
            if (addrEl) entry.pj_adresse = addrEl.textContent.replace(/\\s+/g, ' ').trim();

            const phoneEl = item.querySelector('.bi-phone-number, .click_phone_number, a[href^="tel:"]');
            if (phoneEl) {
                entry.pj_telephone = (phoneEl.getAttribute('href') || phoneEl.textContent || '').replace('tel:', '').trim();
            }

            const webEl = item.querySelector('a.bi-website, a[data-pjlabel="site_internet"], a.pj-link--website');
            if (webEl) entry.pj_site_web = webEl.getAttribute('href') || webEl.textContent.trim();

            const emailEl = item.querySelector('a[href^="mailto:"]');
            if (emailEl) entry.pj_email = emailEl.getAttribute('href').replace('mailto:', '').trim();

            listings.push(entry);
        });
        return listings;
    }""")
    return results


def get_pagination_info(page):
    """Get pagination info from page."""
    return page.evaluate("""() => {
        const nextBtn = document.querySelector('a#pagination-next, a.next, a[title="Page suivante"], a.pagination-next');
        const pageLinks = document.querySelectorAll('.pagination a, a.link_pagination');
        let maxPage = 1;
        pageLinks.forEach(a => {
            const n = parseInt(a.textContent.trim());
            if (!isNaN(n) && n > maxPage) maxPage = n;
        });
        return {
            hasNext: !!nextBtn,
            nextHref: nextBtn ? nextBtn.getAttribute('href') : null,
            maxPage: maxPage
        };
    }""")


def scrape_category(browser_page, cat_name, cat_slug):
    """Scrape all pages for a category."""
    all_results = []
    page_num = 1
    base_url = f"https://www.pagesjaunes.fr/annuaire/lyon-69/{cat_slug}"

    print(f"\n{'='*60}")
    print(f"Scraping: {cat_name}")
    print(f"{'='*60}")

    while True:
        url = base_url if page_num == 1 else f"{base_url}/page-{page_num}"
        print(f"  Page {page_num}: {url}")

        try:
            browser_page.goto(url, wait_until="domcontentloaded", timeout=30000)
            # Wait a bit for dynamic content
            time.sleep(3)

            # Check if we're on a Cloudflare challenge page
            title = browser_page.title()
            print(f"    Title: {title}")
            if "moment" in title.lower() or "challenge" in title.lower():
                print("    Cloudflare challenge detected, waiting 10s...")
                time.sleep(10)
                title = browser_page.title()
                print(f"    Title after wait: {title}")
                if "moment" in title.lower():
                    print("    Still blocked by Cloudflare, saving screenshot...")
                    browser_page.screenshot(path=os.path.join(BASE_DIR, f"cf_block_{cat_slug}.png"))
                    break

            # Check for 404 or no results
            content = browser_page.content()
            if "Aucun résultat" in content or "aucun résultat" in content:
                print("    No results found")
                break

            listings = extract_listings(browser_page)
            print(f"    Found {len(listings)} listings")

            if not listings:
                # Save debug screenshot
                browser_page.screenshot(path=os.path.join(BASE_DIR, f"debug_{cat_slug}_p{page_num}.png"))
                # Save HTML for debugging
                with open(os.path.join(BASE_DIR, f"debug_{cat_slug}_p{page_num}.html"), "w") as f:
                    f.write(content)
                if page_num == 1:
                    print("    No listings on page 1, stopping")
                    break
                else:
                    break

            all_results.extend(listings)

            # Check pagination
            pag = get_pagination_info(browser_page)
            print(f"    Pagination: hasNext={pag['hasNext']}, maxPage={pag['maxPage']}")

            if pag['hasNext'] or page_num < pag['maxPage']:
                page_num += 1
                time.sleep(DELAY)
            else:
                break

        except Exception as e:
            print(f"    Error: {e}")
            browser_page.screenshot(path=os.path.join(BASE_DIR, f"error_{cat_slug}_p{page_num}.png"))
            break

    print(f"  Total for '{cat_name}': {len(all_results)}")
    return all_results


def normalize_name(name):
    if not name:
        return ""
    name = name.upper()
    name = re.sub(r'\b(SARL|SAS|SA|EURL|SCI|SNC|AUTO|AUTOMOBILES?|GARAGE|CARROSSERIE)\b', '', name)
    name = re.sub(r'\(.*?\)', '', name)
    name = re.sub(r'[^A-Z0-9\s]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def normalize_address(addr):
    if not addr:
        return ""
    addr = addr.upper()
    addr = re.sub(r'[^A-Z0-9\s]', '', addr)
    addr = re.sub(r'\s+', ' ', addr).strip()
    return addr


def fuzzy_match(name1, name2):
    n1 = normalize_name(name1)
    n2 = normalize_name(name2)
    if not n1 or not n2:
        return 0.0
    return SequenceMatcher(None, n1, n2).ratio()


def address_match(addr1, addr2):
    a1 = normalize_address(addr1)
    a2 = normalize_address(addr2)
    if not a1 or not a2:
        return 0.0
    return SequenceMatcher(None, a1, a2).ratio()


def match_pj_to_source(pj_results, source_data):
    matches = {}
    for pj in pj_results:
        pj_name = pj.get("pj_nom", "")
        pj_addr = pj.get("pj_adresse", "")
        best_score = 0
        best_idx = None

        for idx, src in enumerate(source_data):
            src_name = src.get("nom", "")
            src_addr = src.get("adresse", "")

            name_score = fuzzy_match(pj_name, src_name)
            addr_score = address_match(pj_addr, src_addr)
            combined = name_score * 0.65 + addr_score * 0.35

            if name_score > 0.5 and addr_score > 0.5:
                combined += 0.1

            pj_words = set(normalize_name(pj_name).split())
            src_words = set(normalize_name(src_name).split())
            if pj_words and src_words:
                common = pj_words & src_words
                if len(common) >= 2:
                    combined += 0.1
                elif len(common) >= 1 and len(min(pj_words, src_words, key=len)) <= 2:
                    combined += 0.05

            if combined > best_score and combined > 0.45:
                best_score = combined
                best_idx = idx

        if best_idx is not None:
            if best_idx not in matches or matches[best_idx][1] < best_score:
                matches[best_idx] = (pj, best_score)

    return matches


def main():
    print("Loading source data...")
    with open(SOURCE_FILE, "r", encoding="utf-8") as f:
        source_data = json.load(f)
    print(f"Loaded {len(source_data)} companies")

    # Check cache
    all_pj_results = []
    if os.path.exists(PJ_CACHE_FILE):
        with open(PJ_CACHE_FILE, "r", encoding="utf-8") as f:
            cached = json.load(f)
        if cached:
            print(f"Found {len(cached)} cached results, using those")
            all_pj_results = cached

    if not all_pj_results:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                ]
            )
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                locale="fr-FR",
                timezone_id="Europe/Paris",
            )

            # Add stealth scripts
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => false });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                Object.defineProperty(navigator, 'languages', { get: () => ['fr-FR', 'fr', 'en-US', 'en'] });
                window.chrome = { runtime: {} };
            """)

            page = context.new_page()

            # Visit homepage first to get cookies
            print("Visiting PagesJaunes homepage...")
            page.goto("https://www.pagesjaunes.fr", wait_until="domcontentloaded", timeout=30000)
            time.sleep(5)

            # Handle cookie consent
            try:
                consent = page.query_selector('button[id*="accept"], button[id*="consent"], #didomi-notice-agree-button, .didomi-button')
                if consent:
                    consent.click()
                    print("Accepted cookies")
                    time.sleep(2)
            except:
                pass

            title = page.title()
            print(f"Homepage title: {title}")

            for cat_name, cat_slug in CATEGORIES:
                results = scrape_category(page, cat_name, cat_slug)
                all_pj_results.extend(results)

                # Save cache after each category
                with open(PJ_CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump(all_pj_results, f, ensure_ascii=False, indent=2)
                print(f"  Cached {len(all_pj_results)} total results")

                time.sleep(3)

            browser.close()

    print(f"\nTotal PJ results: {len(all_pj_results)}")

    # Deduplicate
    seen = set()
    unique_pj = []
    for r in all_pj_results:
        key = normalize_name(r.get("pj_nom", ""))
        if key and key not in seen:
            seen.add(key)
            unique_pj.append(r)
    print(f"Unique after dedup: {len(unique_pj)}")

    # Match
    print("\nMatching...")
    matches = match_pj_to_source(unique_pj, source_data)
    print(f"Found {len(matches)} matches")

    # Enrich
    enriched = []
    matched_count = 0
    for idx, company in enumerate(source_data):
        entry = dict(company)
        if idx in matches:
            pj_data, score = matches[idx]
            entry["pj_telephone"] = pj_data.get("pj_telephone", "")
            entry["pj_site_web"] = pj_data.get("pj_site_web", "")
            entry["pj_email"] = pj_data.get("pj_email", "")
            entry["pj_adresse_pj"] = pj_data.get("pj_adresse", "")
            entry["pj_nom_match"] = pj_data.get("pj_nom", "")
            entry["pj_match_score"] = round(score, 3)
            entry["pj_enriched"] = True
            matched_count += 1
        else:
            entry["pj_telephone"] = ""
            entry["pj_site_web"] = ""
            entry["pj_email"] = ""
            entry["pj_adresse_pj"] = ""
            entry["pj_nom_match"] = ""
            entry["pj_match_score"] = 0
            entry["pj_enriched"] = False
        enriched.append(entry)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(enriched, f, ensure_ascii=False, indent=2)

    print(f"\nDone! Enriched {matched_count}/{len(source_data)} companies")
    print(f"Saved to {OUTPUT_FILE}")

    if matched_count > 0:
        scores = [matches[i][1] for i in matches]
        print(f"Scores: min={min(scores):.3f}, max={max(scores):.3f}, avg={sum(scores)/len(scores):.3f}")
        print("\nSample matches:")
        for idx in list(matches.keys())[:10]:
            pj, score = matches[idx]
            src = source_data[idx]
            print(f"  {src['nom'][:40]:40s} <-> {pj['pj_nom'][:40]:40s} ({score:.3f})")


if __name__ == "__main__":
    main()
