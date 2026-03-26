#!/usr/bin/env python3
"""
Enrichissement des entreprises automobiles de Bordeaux via 118000.fr
Recherche de numeros de telephone uniquement.
"""

import json
import re
import time
import os
import random
import urllib.parse
import urllib.request
import ssl

INPUT_FILE = "/home/user/Website01/split_bordeaux.json"
OUTPUT_FILE = "/home/user/Website01/enriched_bordeaux_118000.json"
PROGRESS_FILE = "/home/user/Website01/bordeaux_118000_progress.json"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'fr-FR,fr;q=0.9,en;q=0.5',
}

# Disable SSL verification for speed
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE


def format_phone(phone):
    """Format phone number to French standard."""
    if not phone:
        return ""
    phone = phone.replace('+33', '0').replace(' ', '').replace('.', '').replace('-', '')
    phone = re.sub(r'[^\d]', '', phone)
    if phone.startswith('33') and len(phone) == 11:
        phone = '0' + phone[2:]
    if len(phone) == 10 and phone.startswith('0'):
        return f"{phone[0:2]} {phone[2:4]} {phone[4:6]} {phone[6:8]} {phone[8:10]}"
    return ""


def clean_name_for_search(name):
    """Clean company name for better search results."""
    # Remove legal suffixes that hurt search
    cleaned = re.sub(r'\b(SAS|SARL|SA|SNC|EURL|SCI|SASU|SELARL)\b', '', name, flags=re.IGNORECASE)
    # Remove parenthetical content
    cleaned = re.sub(r'\([^)]*\)', '', cleaned)
    # Remove extra whitespace
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned


def search_118000(name, ville="Bordeaux"):
    """Search 118000.fr for a phone number using urllib."""
    try:
        clean = clean_name_for_search(name)
        query = f"{clean} {ville}"
        encoded = urllib.parse.quote(query)
        url = f"https://www.118000.fr/search?who={urllib.parse.quote(clean)}&where={urllib.parse.quote(ville)}"

        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=5, context=SSL_CTX) as response:
            html = response.read().decode('utf-8', errors='ignore')

        # Check for captcha/block
        if 'captcha' in html.lower():
            return "", "captcha"

        # Primary: extract from tel: links (most reliable)
        tel_links = re.findall(r'href="tel:(\d{10})"', html)
        for t in tel_links:
            formatted = format_phone(t)
            if formatted and formatted != "01 23 45 67 89":
                return formatted, "ok"

        # Fallback: extract phone numbers using regex on raw HTML
        phone_pattern = re.compile(r'(?:0[1-9])(?:[\s.\-]?\d{2}){4}')
        phones = phone_pattern.findall(html)

        # Filter out obvious non-phone numbers
        for p in phones:
            formatted = format_phone(p)
            if formatted and formatted != "01 23 45 67 89":
                return formatted, "ok"

        return "", "not_found"

    except urllib.error.HTTPError as e:
        if e.code == 429:
            return "", "rate_limited"
        return "", f"http_{e.code}"
    except Exception as e:
        return "", "error"


def load_progress():
    """Load previous progress."""
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {"processed": {}, "last_index": 0}


def save_progress(progress):
    """Save progress to file."""
    with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
        json.dump(progress, f, ensure_ascii=False)


def save_output(companies):
    """Save enriched data."""
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(companies, f, ensure_ascii=False, indent=2)


def main():
    print("=" * 60)
    print("ENRICHISSEMENT BORDEAUX - 118000.fr")
    print("=" * 60)

    # Load input
    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        companies = json.load(f)
    print(f"Loaded {len(companies)} companies")

    # Initialize fields
    for c in companies:
        if 'telephone' not in c:
            c['telephone'] = ""
        if 'email' not in c:
            c['email'] = ""
        if 'site_web' not in c:
            c['site_web'] = ""

    # Load progress
    progress = load_progress()
    processed = progress.get("processed", {})
    print(f"Already processed: {len(processed)} companies")

    # Apply previous results
    for i, c in enumerate(companies):
        siret = c.get('siret', str(i))
        if siret in processed and processed[siret]:
            c['telephone'] = processed[siret]

    # Count stats
    already_found = sum(1 for v in processed.values() if v)
    print(f"Already found phones: {already_found}")

    # Process companies
    found = already_found
    errors = 0
    captchas = 0
    consecutive_captchas = 0

    for i, company in enumerate(companies):
        siret = company.get('siret', str(i))

        # Skip already processed
        if siret in processed:
            continue

        name = company['nom']
        # Use zone_recherche or ville for the city
        ville = "Bordeaux"

        phone, status = search_118000(name, ville)

        if status == "captcha":
            captchas += 1
            consecutive_captchas += 1
            processed[siret] = ""
            if consecutive_captchas >= 5:
                print(f"\n[!] Too many captchas ({captchas}), pausing 30s...")
                time.sleep(30)
                consecutive_captchas = 0
                # Retry this one
                phone, status = search_118000(name, ville)
                if status == "captcha":
                    print("[!] Still getting captchas, stopping.")
                    break
        elif status == "rate_limited":
            print(f"\n[!] Rate limited at index {i}, pausing 60s...")
            time.sleep(60)
            phone, status = search_118000(name, ville)
            if status == "rate_limited":
                print("[!] Still rate limited, stopping.")
                break
        else:
            consecutive_captchas = 0

        if phone:
            company['telephone'] = phone
            processed[siret] = phone
            found += 1
        else:
            processed[siret] = ""

        # Progress display
        if (i + 1) % 25 == 0 or phone:
            total_processed = len(processed)
            pct = 100 * total_processed / len(companies)
            if phone:
                print(f"  [{total_processed}/{len(companies)} ({pct:.0f}%)] FOUND: {name} -> {phone}")
            else:
                print(f"  [{total_processed}/{len(companies)} ({pct:.0f}%)] Progress... ({found} phones found)")

        # Save progress every 50 companies
        if len(processed) % 50 == 0:
            progress["processed"] = processed
            progress["last_index"] = i
            save_progress(progress)
            save_output(companies)

        # Random delay 0.5-1s
        time.sleep(random.uniform(0.5, 1.0))

    # Final save
    progress["processed"] = processed
    save_progress(progress)
    save_output(companies)

    # Stats
    print("\n" + "=" * 60)
    print("RESULTATS")
    print("=" * 60)
    with_phone = sum(1 for c in companies if c.get('telephone'))
    print(f"  Total entreprises: {len(companies)}")
    print(f"  Avec telephone:    {with_phone} ({100*with_phone/len(companies):.1f}%)")
    print(f"  Captchas:          {captchas}")
    print(f"  Fichier sauvegarde: {OUTPUT_FILE}")
    print("Done!")


if __name__ == '__main__':
    main()
