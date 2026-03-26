#!/usr/bin/env python3
"""
Pass 2: Improve enrichment with OSM, cleanup, and additional sources.
"""

import json
import re
import time
import urllib.parse
from difflib import SequenceMatcher
import requests
from bs4 import BeautifulSoup

INPUT_FILE = "/home/user/Website01/enriched_lille.json"
OUTPUT_FILE = "/home/user/Website01/enriched_lille.json"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'fr-FR,fr;q=0.9',
}


def normalize_name(name):
    name = name.upper()
    for suffix in ['SAS', 'SARL', 'SA', 'SNC', 'EURL', 'SCI', 'AUTO', 'GARAGE', 'FRANCE']:
        name = re.sub(r'\b' + suffix + r'\b', '', name)
    name = re.sub(r'\([^)]*\)', '', name)
    name = re.sub(r'[^A-Z0-9\s]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def similarity(a, b):
    return SequenceMatcher(None, normalize_name(a), normalize_name(b)).ratio()


def format_phone(phone):
    if not phone:
        return ""
    phone = phone.replace('+33', '0').replace(' ', '').replace('.', '').replace('-', '')
    phone = re.sub(r'[^\d]', '', phone)
    if phone.startswith('33') and len(phone) == 11:
        phone = '0' + phone[2:]
    if len(phone) == 10 and phone.startswith('0'):
        return f"{phone[0:2]} {phone[2:4]} {phone[4:6]} {phone[6:8]} {phone[8:10]}"
    return phone


def is_local_phone(phone):
    """Check if phone is from Nord-Pas-de-Calais area (03.20, 03.28, 03.21, etc.)"""
    if not phone:
        return False
    digits = re.sub(r'[^\d]', '', phone)
    # 03 is Nord region, 06/07 are mobiles (OK), 09 is VoIP (OK)
    return digits.startswith('03') or digits.startswith('06') or digits.startswith('07') or digits.startswith('09')


def fetch_osm_data():
    """Fetch from OSM with smaller area and retry."""
    print("Fetching OSM data...")
    overpass_url = "https://overpass-api.de/api/interpreter"

    # Split into smaller queries
    queries = [
        # Car repair/garages
        """[out:json][timeout:60];
        (
          node["shop"~"car_repair|car_parts"](50.58,2.95,50.68,3.15);
          way["shop"~"car_repair|car_parts"](50.58,2.95,50.68,3.15);
          node["craft"~"car_repair"](50.58,2.95,50.68,3.15);
          way["craft"~"car_repair"](50.58,2.95,50.68,3.15);
        );
        out body;""",
        # Car shops/dealers
        """[out:json][timeout:60];
        (
          node["shop"="car"](50.58,2.95,50.68,3.15);
          way["shop"="car"](50.58,2.95,50.68,3.15);
          node["shop"="motorcycle"](50.58,2.95,50.68,3.15);
          way["shop"="motorcycle"](50.58,2.95,50.68,3.15);
          node["shop"="tyres"](50.58,2.95,50.68,3.15);
          way["shop"="tyres"](50.58,2.95,50.68,3.15);
        );
        out body;""",
        # Car wash, rental, fuel
        """[out:json][timeout:60];
        (
          node["amenity"~"car_wash|car_rental"](50.58,2.95,50.68,3.15);
          way["amenity"~"car_wash|car_rental"](50.58,2.95,50.68,3.15);
        );
        out body;""",
    ]

    all_elements = []
    for i, query in enumerate(queries):
        try:
            r = requests.post(overpass_url, data={"data": query}, timeout=90)
            if r.status_code == 200:
                data = r.json()
                elements = data.get('elements', [])
                all_elements.extend(elements)
                print(f"  Query {i+1}: {len(elements)} elements")
            else:
                print(f"  Query {i+1} failed: {r.status_code}")
            time.sleep(2)
        except Exception as e:
            print(f"  Query {i+1} error: {e}")

    print(f"  Total OSM elements: {len(all_elements)}")
    return all_elements


def match_osm(companies, osm_elements):
    """Match OSM data to companies."""
    osm_data = []
    for el in osm_elements:
        tags = el.get('tags', {})
        name = tags.get('name', '')
        brand = tags.get('brand', '')
        if name or brand:
            osm_data.append({
                'name': name,
                'brand': brand,
                'phone': tags.get('phone', '') or tags.get('contact:phone', ''),
                'website': tags.get('website', '') or tags.get('contact:website', ''),
                'email': tags.get('email', '') or tags.get('contact:email', ''),
            })

    matched_phone = 0
    matched_web = 0
    matched_email = 0

    for company in companies:
        comp_name = company['nom']
        best_match = None
        best_score = 0

        for osm in osm_data:
            for candidate in [osm['name'], osm['brand']]:
                if not candidate:
                    continue
                score = similarity(comp_name, candidate)
                if score > best_score and score >= 0.45:
                    best_score = score
                    best_match = osm

        if best_match:
            if best_match['phone'] and not company.get('telephone'):
                company['telephone'] = format_phone(best_match['phone'])
                matched_phone += 1
            if best_match['website'] and not company.get('site_web'):
                company['site_web'] = best_match['website']
                matched_web += 1
            if best_match['email'] and not company.get('email'):
                company['email'] = best_match['email']
                matched_email += 1

    print(f"  OSM matches: {matched_phone} phones, {matched_web} websites, {matched_email} emails")


def try_118000_detailed(name, adresse, ville="Lille"):
    """More detailed 118000 search using address."""
    try:
        # Try with address for more precision
        search_who = urllib.parse.quote(name)
        search_where = urllib.parse.quote(f"{ville} {adresse.split()[-2] if len(adresse.split()) > 2 else ville}")
        url = f"https://www.118000.fr/search?who={search_who}&where={search_where}"
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code == 200 and 'captcha' not in r.text.lower():
            soup = BeautifulSoup(r.text, 'lxml')
            text = soup.get_text()

            # Phone
            phone_pattern = re.compile(r'(?:0[1-9])[\s.-]?\d{2}[\s.-]?\d{2}[\s.-]?\d{2}[\s.-]?\d{2}')
            phones = phone_pattern.findall(text)
            result = {}

            # Filter for local phones
            local_phones = [p for p in phones if re.sub(r'[^\d]', '', p).startswith(('03', '06', '07', '09'))]
            if local_phones:
                result['telephone'] = format_phone(local_phones[0])
            elif phones:
                result['telephone'] = format_phone(phones[0])

            # Website - look for links
            for a in soup.find_all('a', href=True):
                href = a.get('href', '')
                if 'http' in href and '118000' not in href and 'google' not in href:
                    if any(ext in href for ext in ['.fr', '.com', '.net', '.eu']):
                        result['site_web'] = href
                        break

            return result
    except Exception:
        pass
    return {}


def cleanup_phones(companies):
    """Flag suspicious phone numbers (not local to Lille area)."""
    suspicious = 0
    for company in companies:
        phone = company.get('telephone', '')
        if phone:
            digits = re.sub(r'[^\d]', '', phone)
            # 01 numbers are Paris - likely HQ, not local establishment
            if digits.startswith('01') or digits.startswith('04') or digits.startswith('05'):
                # Mark as potentially HQ number
                company['telephone_note'] = "siege_possible"
                suspicious += 1
    print(f"  Flagged {suspicious} potentially non-local phone numbers")


def try_geneanet_free_api(siren):
    """Try getting website from various free data sources."""
    # Try the French company search API
    try:
        url = f"https://recherche-entreprises.api.gouv.fr/search?q={siren}&per_page=1"
        r = requests.get(url, timeout=8)
        if r.status_code == 200:
            data = r.json()
            results = data.get('results', [])
            if results:
                result = results[0]
                # Check matching_etablissements for the right one
                complements = result.get('complements', {})
                collectivite = complements.get('collectivite_territoriale', {})
                # Sometimes website info is in complements
                return {}
    except Exception:
        pass
    return {}


def main():
    print("=" * 60)
    print("ENRICHISSEMENT PASS 2 - OSM + Nettoyage + Compléments")
    print("=" * 60)

    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        companies = json.load(f)
    print(f"Loaded {len(companies)} companies")

    # Stats before
    phone_before = sum(1 for c in companies if c.get('telephone'))
    print(f"  With phone before: {phone_before}")

    # Step 1: OSM
    print("\n--- STEP 1: OSM enrichment ---")
    osm_elements = fetch_osm_data()
    if osm_elements:
        match_osm(companies, osm_elements)

    # Step 2: Cleanup suspicious phones
    print("\n--- STEP 2: Cleanup ---")
    cleanup_phones(companies)

    # Step 3: Re-try 118000 for companies still without phone, with more precise search
    print("\n--- STEP 3: 118000 retry for missing phones ---")
    no_phone = [c for c in companies if not c.get('telephone')]
    print(f"  {len(no_phone)} companies still without phone")
    found = 0
    blocked = False
    for i, company in enumerate(no_phone):
        if blocked:
            break
        result = try_118000_detailed(company['nom'], company.get('adresse', ''), company.get('ville', 'Lille'))
        if result.get('telephone'):
            company['telephone'] = result['telephone']
            found += 1
        if result.get('site_web'):
            company['site_web'] = result['site_web']

        if i % 50 == 0 and i > 0:
            print(f"  Progress: {i}/{len(no_phone)} ({found} found)")

        time.sleep(0.5)

        # Check if blocked
        if i >= 20 and found == 0:
            print("  Appears blocked, stopping...")
            blocked = True

    print(f"  Found {found} additional phones")

    # Final stats
    print("\n" + "=" * 60)
    print("FINAL ENRICHMENT RESULTS")
    print("=" * 60)
    with_phone = sum(1 for c in companies if c.get('telephone'))
    with_email = sum(1 for c in companies if c.get('email'))
    with_web = sum(1 for c in companies if c.get('site_web'))
    print(f"  Total companies: {len(companies)}")
    print(f"  With telephone:  {with_phone} ({100*with_phone/len(companies):.1f}%)")
    print(f"  With email:      {with_email} ({100*with_email/len(companies):.1f}%)")
    print(f"  With site_web:   {with_web} ({100*with_web/len(companies):.1f}%)")

    # Save
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(companies, f, ensure_ascii=False, indent=2)
    print(f"\nSaved to {OUTPUT_FILE}")


if __name__ == '__main__':
    main()
