#!/usr/bin/env python3
"""
Script d'enrichissement des entreprises automobiles de Lille
avec telephone, email et site_web.

Sources utilisees:
1. OpenStreetMap (Overpass API) - données ouvertes avec phone/website
2. API recherche-entreprises.data.gouv.fr - données légales
3. Scraping léger de sources accessibles
"""

import json
import re
import time
import sys
import os
import urllib.parse
from difflib import SequenceMatcher
import requests
from bs4 import BeautifulSoup

INPUT_FILE = "/home/user/Website01/split_lille.json"
OUTPUT_FILE = "/home/user/Website01/enriched_lille.json"
PROGRESS_FILE = "/home/user/Website01/enrichment_progress.json"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'fr-FR,fr;q=0.9,en;q=0.5',
}


def normalize_name(name):
    """Normalize company name for matching."""
    name = name.upper()
    # Remove common suffixes
    for suffix in ['SAS', 'SARL', 'SA', 'SNC', 'EURL', 'SCI', 'AUTO', 'GARAGE']:
        name = re.sub(r'\b' + suffix + r'\b', '', name)
    # Remove parenthetical content
    name = re.sub(r'\([^)]*\)', '', name)
    # Remove special chars
    name = re.sub(r'[^A-Z0-9\s]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def similarity(a, b):
    """Calculate similarity between two strings."""
    return SequenceMatcher(None, normalize_name(a), normalize_name(b)).ratio()


def format_phone(phone):
    """Format phone number to French standard."""
    if not phone:
        return ""
    # Remove +33 prefix
    phone = phone.replace('+33', '0').replace(' ', '').replace('.', '').replace('-', '')
    # Remove non-digit chars
    phone = re.sub(r'[^\d]', '', phone)
    if phone.startswith('33') and len(phone) == 11:
        phone = '0' + phone[2:]
    if len(phone) == 10 and phone.startswith('0'):
        return f"{phone[0:2]} {phone[2:4]} {phone[4:6]} {phone[6:8]} {phone[8:10]}"
    return phone


def fetch_osm_data():
    """Fetch car-related businesses from OSM in wider Lille area."""
    print("Fetching OSM data for Lille metropolitan area...")
    overpass_url = "https://overpass-api.de/api/interpreter"

    # Wider Lille metro area bbox
    query = """
    [out:json][timeout:120];
    (
      node["shop"~"car|car_repair|car_parts|motorcycle"](50.55,2.90,50.72,3.20);
      way["shop"~"car|car_repair|car_parts|motorcycle"](50.55,2.90,50.72,3.20);
      node["craft"~"car_repair|motorcycle_repair"](50.55,2.90,50.72,3.20);
      way["craft"~"car_repair|motorcycle_repair"](50.55,2.90,50.72,3.20);
      node["amenity"~"car_wash|car_rental|fuel"](50.55,2.90,50.72,3.20);
      way["amenity"~"car_wash|car_rental|fuel"](50.55,2.90,50.72,3.20);
      node["shop"="tyres"](50.55,2.90,50.72,3.20);
      way["shop"="tyres"](50.55,2.90,50.72,3.20);
      node["service"~"vehicle"](50.55,2.90,50.72,3.20);
    );
    out body;
    """

    try:
        r = requests.post(overpass_url, data={"data": query}, timeout=120)
        if r.status_code == 200:
            data = r.json()
            elements = data.get('elements', [])
            print(f"  Found {len(elements)} OSM elements")
            return elements
        else:
            print(f"  OSM query failed: {r.status_code}")
            return []
    except Exception as e:
        print(f"  OSM error: {e}")
        return []


def match_osm_to_companies(companies, osm_elements):
    """Match OSM data to companies by name similarity."""
    matched = 0
    osm_by_name = {}

    for el in osm_elements:
        tags = el.get('tags', {})
        name = tags.get('name', '')
        if name:
            osm_by_name[name] = tags

    for company in companies:
        comp_name = company['nom']
        best_match = None
        best_score = 0

        for osm_name, tags in osm_by_name.items():
            score = similarity(comp_name, osm_name)
            if score > best_score and score >= 0.5:
                best_score = score
                best_match = tags

        if best_match:
            phone = best_match.get('phone', '') or best_match.get('contact:phone', '')
            website = best_match.get('website', '') or best_match.get('contact:website', '')
            email = best_match.get('email', '') or best_match.get('contact:email', '')

            if phone and not company.get('telephone'):
                company['telephone'] = format_phone(phone)
                matched += 1
            if website and not company.get('site_web'):
                company['site_web'] = website
            if email and not company.get('email'):
                company['email'] = email

    print(f"  Matched {matched} companies from OSM data")
    return companies


def try_118000(name, ville="Lille"):
    """Try 118000.fr for phone number lookup."""
    try:
        search_name = urllib.parse.quote(name)
        search_ville = urllib.parse.quote(ville)
        url = f"https://www.118000.fr/search?who={search_name}&where={search_ville}"
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code == 200 and 'captcha' not in r.text.lower():
            soup = BeautifulSoup(r.text, 'lxml')
            # Look for phone numbers in the page
            phone_pattern = re.compile(r'(?:0[1-9])(?:[\s.-]?\d{2}){4}')
            phones = phone_pattern.findall(soup.get_text())
            if phones:
                return format_phone(phones[0])
    except Exception:
        pass
    return ""


def try_infogreffe(siren):
    """Try data.infogreffe.fr API."""
    try:
        url = f"https://opendata.datainfogreffe.fr/api/records/1.0/search/?dataset=chiffres-cles-2023&q=siren:{siren}"
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data.get('records'):
                fields = data['records'][0].get('fields', {})
                return {
                    'telephone': fields.get('telephone', ''),
                    'email': fields.get('email', ''),
                    'site_web': fields.get('site_internet', ''),
                }
    except Exception:
        pass
    return {}


def try_sirene_api(siren):
    """Try official SIRENE API for basic info."""
    try:
        url = f"https://recherche-entreprises.api.gouv.fr/search?q={siren}&page=1&per_page=1"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            results = data.get('results', [])
            if results:
                complements = results[0].get('complements', {})
                return {
                    'site_web': complements.get('site_web', '') or '',
                }
    except Exception:
        pass
    return {}


def try_cylex(name, ville="Lille"):
    """Try cylex-locale.fr for business info."""
    try:
        search_name = urllib.parse.quote(f"{name} {ville}")
        url = f"https://www.cylex-locale.fr/recherche.aspx?search={search_name}&loc={ville}"
        r = requests.get(url, headers=HEADERS, timeout=10, allow_redirects=True)
        if r.status_code == 200 and 'captcha' not in r.text.lower():
            soup = BeautifulSoup(r.text, 'lxml')
            phone_pattern = re.compile(r'(?:0[1-9])(?:[\s.-]?\d{2}){4}')
            phones = phone_pattern.findall(soup.get_text())
            if phones:
                return {'telephone': format_phone(phones[0])}
    except Exception:
        pass
    return {}


def try_google_places_free(name, ville="Lille"):
    """Extract info from freely accessible sources."""
    results = {}

    # Try vroomly.com (car repair aggregator)
    try:
        search_name = name.lower().replace(' ', '-').replace("'", '')
        search_name = re.sub(r'[^a-z0-9-]', '', search_name)
        url = f"https://www.vroomly.com/garages/{search_name}-{ville.lower()}/"
        r = requests.get(url, headers=HEADERS, timeout=8, allow_redirects=True)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'lxml')
            phone_el = soup.find('a', href=re.compile(r'^tel:'))
            if phone_el:
                phone = phone_el.get('href', '').replace('tel:', '')
                results['telephone'] = format_phone(phone)
    except Exception:
        pass

    return results


def enrich_batch_web(companies, start_idx=0, batch_size=50):
    """Enrich companies using web scraping in batches."""
    enriched_count = 0

    for i in range(start_idx, min(start_idx + batch_size, len(companies))):
        company = companies[i]
        name = company['nom']
        siren = company.get('siren', '')

        # Skip if already has phone
        if company.get('telephone'):
            continue

        # Try SIRENE API first (most reliable, has site_web sometimes)
        if siren and not company.get('site_web'):
            sirene_data = try_sirene_api(siren)
            if sirene_data.get('site_web'):
                company['site_web'] = sirene_data['site_web']

        # Rate limiting
        time.sleep(0.3)

        if i % 50 == 0 and i > 0:
            print(f"  Progress: {i}/{len(companies)} ({enriched_count} enriched so far)")

    return enriched_count


def load_progress():
    """Load previous enrichment progress."""
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_progress(data):
    """Save enrichment progress."""
    with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    print("=" * 60)
    print("ENRICHISSEMENT DES ENTREPRISES AUTOMOBILES - LILLE")
    print("=" * 60)

    # Load input data
    print(f"\nLoading {INPUT_FILE}...")
    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        companies = json.load(f)
    print(f"  Loaded {len(companies)} companies")

    # Initialize enrichment fields
    for company in companies:
        if 'telephone' not in company:
            company['telephone'] = ""
        if 'email' not in company:
            company['email'] = ""
        if 'site_web' not in company:
            company['site_web'] = ""

    # Step 1: OSM enrichment
    print("\n--- STEP 1: OpenStreetMap enrichment ---")
    osm_elements = fetch_osm_data()
    if osm_elements:
        companies = match_osm_to_companies(companies, osm_elements)

    # Step 2: SIRENE API enrichment (for site_web)
    print("\n--- STEP 2: SIRENE API enrichment ---")
    sirene_enriched = 0
    for i, company in enumerate(companies):
        siren = company.get('siren', '')
        if siren and not company.get('site_web'):
            data = try_sirene_api(siren)
            if data.get('site_web'):
                company['site_web'] = data['site_web']
                sirene_enriched += 1
        if i % 100 == 0:
            print(f"  Progress: {i}/{len(companies)}")
        time.sleep(0.15)  # Rate limiting
    print(f"  Enriched {sirene_enriched} companies with SIRENE API")

    # Step 3: Try 118000.fr for phone numbers (for companies without phone)
    print("\n--- STEP 3: 118000.fr phone lookup ---")
    phone_enriched = 0
    no_phone = [c for c in companies if not c.get('telephone')]
    print(f"  {len(no_phone)} companies without phone number")

    for i, company in enumerate(no_phone):
        result = try_118000(company['nom'], company.get('ville', 'Lille'))
        if result:
            company['telephone'] = result
            phone_enriched += 1
        if i % 50 == 0 and i > 0:
            print(f"  Progress: {i}/{len(no_phone)} ({phone_enriched} found)")
        time.sleep(0.5)  # Be respectful

        # Stop if getting blocked
        if i >= 10 and phone_enriched == 0:
            print("  118000.fr appears to be blocking requests, skipping...")
            break

    print(f"  Found {phone_enriched} phone numbers via 118000.fr")

    # Final stats
    print("\n" + "=" * 60)
    print("ENRICHMENT RESULTS")
    print("=" * 60)
    with_phone = sum(1 for c in companies if c.get('telephone'))
    with_email = sum(1 for c in companies if c.get('email'))
    with_web = sum(1 for c in companies if c.get('site_web'))
    print(f"  Total companies: {len(companies)}")
    print(f"  With telephone:  {with_phone} ({100*with_phone/len(companies):.1f}%)")
    print(f"  With email:      {with_email} ({100*with_email/len(companies):.1f}%)")
    print(f"  With site_web:   {with_web} ({100*with_web/len(companies):.1f}%)")

    # Save output
    print(f"\nSaving to {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(companies, f, ensure_ascii=False, indent=2)
    print("Done!")

    return companies


if __name__ == '__main__':
    main()
