#!/usr/bin/env python3
"""
AMELI Health Professionals Directory Scraper
=============================================
Scrapes data from https://annuairesante.ameli.fr/

The site is a Vue.js SPA backed by a JSON API at /ansa-fo-api/.
Authentication requires:
  - A CSRF-TOKEN cookie (self-generated UUID)
  - X-CSRF-TOKEN header matching the cookie
  - sessionID header (UUID)
  - Proper browser-like headers

Working endpoints:
  - /ansa-fo-api/recherche/professions          (list all professions)
  - /ansa-fo-api/recherche/professions-count     (professions with practitioner counts)
  - /ansa-fo-api/recherche/departements-count    (departments with counts per profession)
  - /ansa-fo-api/recherche/communes-count        (communes with counts per profession+dept)
  - /ansa-fo-api/recherche/adresse               (geocoding/address lookup)
  - /ansa-fo-api/recherche/profession             (profession details by ID)
  - /ansa-fo-api/recherche/profession-acte        (profession autocomplete)
  - /ansa-fo-api/recherche/commune                (commune geometry by postal code)
  - /ansa-fo-api/recherche/departement            (department info by number)

Search endpoint (returns individual practitioners):
  - /ansa-fo-api/recherche?nom=&idProfession=ID&centre=LON,LAT&rechercheMode=VILLE&bbox=...
  NOTE: This endpoint returns HTTP 500 as of 2026-04-01 (backend issue on AMELI's side)
"""

import json
import time
import uuid
import urllib.request
import urllib.parse
import ssl
import http.cookiejar
from datetime import datetime
from pathlib import Path


BASE_URL = "https://annuairesante.ameli.fr"
API_BASE = f"{BASE_URL}/ansa-fo-api"
OUTPUT_FILE = Path("/home/user/Website01/data/ameli.json")
DELAY = 2.5  # seconds between requests

# Target professions and their IDs (from the API)
TARGET_PROFESSIONS = {
    "37": "Médecin généraliste",
    "20": "Chirurgien-dentiste",
    "35": "Masseur-kinésithérapeute",
    "34": "Laboratoire",
    "32": "Infirmier",
    "51": "Ophtalmologiste",
    "8":  "Cardiologue",
}

# Target cities with their department codes
TARGET_CITIES = {
    "Paris": {"dept": "75", "postal_prefixes": ["75"]},
    "Marseille": {"dept": "13", "postal_prefixes": ["13"]},
    "Lille": {"dept": "59", "postal_prefixes": ["59"]},
}


class AmeliScraper:
    def __init__(self):
        self.csrf_token = str(uuid.uuid4())
        self.session_id = str(uuid.uuid4())
        self.cookie_jar = http.cookiejar.CookieJar()
        self.ssl_ctx = ssl.create_default_context()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookie_jar)
        )
        self._init_session()

    def _init_session(self):
        """Initialize session by visiting homepage and setting CSRF cookie."""
        req = urllib.request.Request(BASE_URL, headers=self._browser_headers())
        try:
            self.opener.open(req, timeout=15)
        except Exception as e:
            print(f"  [WARN] Homepage fetch: {e}")

        # Add CSRF token cookie
        csrf_cookie = http.cookiejar.Cookie(
            version=0, name="CSRF-TOKEN", value=self.csrf_token,
            port=None, port_specified=False,
            domain="annuairesante.ameli.fr", domain_specified=True, domain_initial_dot=False,
            path="/", path_specified=True,
            secure=True, expires=None, discard=True,
            comment=None, comment_url=None, rest={}, rfc2109=False,
        )
        self.cookie_jar.set_cookie(csrf_cookie)
        print(f"  Session initialized. CSRF: {self.csrf_token[:8]}...")

    def _browser_headers(self):
        return {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Referer": f"{BASE_URL}/",
            "Origin": BASE_URL,
            "X-CSRF-TOKEN": self.csrf_token,
            "sessionID": self.session_id,
            "correlationID": str(uuid.uuid4()),
        }

    def _get(self, url):
        """Make a GET request and return parsed JSON."""
        req = urllib.request.Request(url, headers=self._browser_headers())
        try:
            resp = self.opener.open(req, timeout=20)
            data = json.loads(resp.read().decode("utf-8"))
            return data
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            try:
                return json.loads(body)
            except Exception:
                return {"error": f"HTTP {e.code}", "body": body[:500]}
        except Exception as e:
            return {"error": str(e)}

    def get_professions(self):
        """Fetch full list of professions."""
        print("\n[1/6] Fetching professions list...")
        data = self._get(f"{API_BASE}/recherche/professions")
        if isinstance(data, list):
            print(f"  Found {len(data)} professions")
        return data

    def get_professions_count(self):
        """Fetch professions with practitioner counts."""
        print("\n[2/6] Fetching professions with counts...")
        time.sleep(DELAY)
        data = self._get(f"{API_BASE}/recherche/professions-count")
        if isinstance(data, list):
            print(f"  Found {len(data)} professions with counts")
            total = sum(p.get("count", 0) for p in data)
            print(f"  Total practitioners across France: {total:,}")
        return data

    def get_departments_count(self, profession_id):
        """Fetch department-level counts for a profession."""
        time.sleep(DELAY)
        data = self._get(f"{API_BASE}/recherche/departements-count?profession={profession_id}")
        if isinstance(data, list):
            return data
        return []

    def get_communes_count(self, profession_id, dept_id):
        """Fetch commune-level counts for a profession in a department."""
        time.sleep(DELAY)
        data = self._get(f"{API_BASE}/recherche/communes-count?profession={profession_id}&departement={dept_id}")
        if isinstance(data, list):
            return data
        return []

    def get_address_geometry(self, city_name):
        """Get coordinates for a city."""
        time.sleep(DELAY)
        encoded = urllib.parse.quote(city_name.lower())
        data = self._get(f"{API_BASE}/recherche/adresse?adresse={encoded}")
        if isinstance(data, list) and data:
            return data[0]
        return None

    def search_practitioners(self, profession_id, geometry, profession_type="PROFESSION"):
        """
        Attempt to search for individual practitioners.
        NOTE: As of 2026-04-01, this endpoint returns HTTP 500 on AMELI's backend.
        """
        centre = geometry.get("centre", {}).get("coordinates", [0, 0])
        bbox_coords = geometry.get("bbox", {}).get("coordinates", [[[0, 0]]])

        # Flatten bbox: coordinates[0].flat()
        bbox_flat = []
        for coord in bbox_coords[0]:
            bbox_flat.extend(coord)

        centre_str = f"{centre[0]},{centre[1]}"
        bbox_str = ",".join(str(c) for c in bbox_flat)

        url = (
            f"{API_BASE}/recherche?"
            f"nom=&idProfession={profession_id}"
            f"&centre={centre_str}"
            f"&rechercheMode=VILLE"
            f"&bbox={bbox_str}"
            f"&professionType={profession_type}"
        )

        data = self._get(url)
        return data

    def scrape_all(self):
        """Main scraping routine."""
        results = {
            "metadata": {
                "source": "https://annuairesante.ameli.fr/",
                "scraped_at": datetime.utcnow().isoformat() + "Z",
                "description": "AMELI French Health Insurance - Directory of Health Professionals",
                "note": "The main search API (/ansa-fo-api/recherche) returned HTTP 500 during scraping. "
                        "Individual practitioner listings could not be retrieved. "
                        "All metadata endpoints (professions, departments, communes counts) worked correctly.",
            },
            "professions": [],
            "professions_with_counts": [],
            "cities": {},
            "search_attempts": [],
        }

        # Step 1: Get all professions
        professions = self.get_professions()
        if isinstance(professions, list):
            results["professions"] = professions

        # Step 2: Get professions with counts
        professions_count = self.get_professions_count()
        if isinstance(professions_count, list):
            results["professions_with_counts"] = professions_count

        # Step 3: For each target city, get address geometry
        print("\n[3/6] Fetching city geometries...")
        city_geometries = {}
        for city_name, city_info in TARGET_CITIES.items():
            geo = self.get_address_geometry(city_name)
            if geo:
                city_geometries[city_name] = geo
                print(f"  {city_name}: centre={geo['geometry']['centre']['coordinates']}")

        # Step 4: For each target profession, get department-level counts for target departments
        print("\n[4/6] Fetching department-level counts for target professions...")
        for prof_id, prof_name in TARGET_PROFESSIONS.items():
            print(f"\n  --- {prof_name} (id={prof_id}) ---")
            dept_data = self.get_departments_count(prof_id)

            for city_name, city_info in TARGET_CITIES.items():
                dept_id = city_info["dept"]

                # Find this department in the data
                dept_match = next((d for d in dept_data if d["id"] == dept_id), None)
                if dept_match:
                    print(f"    {city_name} (dept {dept_id}): {dept_match['count']} practitioners")
                else:
                    print(f"    {city_name} (dept {dept_id}): not found")

                if city_name not in results["cities"]:
                    results["cities"][city_name] = {
                        "department": dept_id,
                        "geometry": city_geometries.get(city_name, {}).get("geometry"),
                        "professions": {},
                    }

                results["cities"][city_name]["professions"][prof_name] = {
                    "profession_id": prof_id,
                    "department_count": dept_match["count"] if dept_match else 0,
                    "communes": [],
                }

        # Step 5: For each target profession+city, get commune-level counts
        print("\n[5/6] Fetching commune-level counts...")
        for city_name, city_info in TARGET_CITIES.items():
            dept_id = city_info["dept"]
            for prof_id, prof_name in TARGET_PROFESSIONS.items():
                print(f"  {prof_name} in {city_name}...")
                communes = self.get_communes_count(prof_id, dept_id)

                # Filter to relevant postal codes for the city
                relevant = []
                for commune in communes:
                    cid = commune.get("id", "")
                    # For Paris: 75001-75116, Marseille: 13001-13016, Lille: 59000/59800
                    if any(cid.startswith(p) for p in city_info["postal_prefixes"]):
                        relevant.append(commune)

                results["cities"][city_name]["professions"][prof_name]["communes"] = relevant
                total = sum(c.get("count", 0) for c in relevant)
                print(f"    {len(relevant)} communes, {total} total practitioners")

        # Step 6: Attempt individual practitioner search (known to fail with 500)
        print("\n[6/6] Attempting practitioner search (search API)...")
        search_success = False
        for city_name in TARGET_CITIES:
            geo = city_geometries.get(city_name)
            if not geo:
                continue

            # Try one search per city with GP
            prof_id = "37"  # Médecin généraliste
            print(f"  Searching GPs in {city_name}...")
            time.sleep(DELAY)
            result = self.search_practitioners(prof_id, geo["geometry"])

            attempt = {
                "city": city_name,
                "profession": "Médecin généraliste",
                "profession_id": prof_id,
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }

            if isinstance(result, dict) and "data" in result:
                search_success = True
                attempt["status"] = "success"
                attempt["count"] = len(result["data"])
                attempt["practitioners"] = result["data"]
                print(f"    SUCCESS! Found {len(result['data'])} practitioners")
            else:
                attempt["status"] = "failed"
                attempt["error"] = result
                error_code = ""
                if isinstance(result, dict) and "problems" in result:
                    error_code = result["problems"][0].get("code", "")
                print(f"    FAILED: {error_code or result}")

            results["search_attempts"].append(attempt)

            if not search_success:
                # If first search failed, try a few more professions to confirm it's a global issue
                for alt_prof_id, alt_prof_name in [("20", "Chirurgien-dentiste"), ("32", "Infirmier")]:
                    time.sleep(DELAY)
                    alt_result = self.search_practitioners(alt_prof_id, geo["geometry"])
                    alt_attempt = {
                        "city": city_name,
                        "profession": alt_prof_name,
                        "profession_id": alt_prof_id,
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                    }
                    if isinstance(alt_result, dict) and "data" in alt_result:
                        search_success = True
                        alt_attempt["status"] = "success"
                        alt_attempt["count"] = len(alt_result["data"])
                        alt_attempt["practitioners"] = alt_result["data"]
                        print(f"    {alt_prof_name}: SUCCESS! {len(alt_result['data'])} found")
                    else:
                        alt_attempt["status"] = "failed"
                        alt_attempt["error"] = alt_result
                        print(f"    {alt_prof_name}: FAILED (confirming backend is down)")
                    results["search_attempts"].append(alt_attempt)
                break  # Don't try other cities if search is globally broken

        if not search_success:
            results["metadata"]["search_api_status"] = "HTTP 500 - Backend service unavailable"
        else:
            results["metadata"]["search_api_status"] = "Working"

        return results


def main():
    print("=" * 70)
    print("AMELI Health Professionals Directory Scraper")
    print("=" * 70)
    print(f"Target: {BASE_URL}")
    print(f"Output: {OUTPUT_FILE}")
    print(f"Delay:  {DELAY}s between requests")
    print()

    scraper = AmeliScraper()
    results = scraper.scrape_all()

    # Save results
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 70)
    print("RESULTS SUMMARY")
    print("=" * 70)

    prof_count = len(results.get("professions", []))
    print(f"Professions cataloged: {prof_count}")

    if results.get("professions_with_counts"):
        total = sum(p.get("count", 0) for p in results["professions_with_counts"])
        print(f"Total practitioners in France: {total:,}")

    for city_name, city_data in results.get("cities", {}).items():
        print(f"\n  {city_name} (dept {city_data['department']}):")
        for prof_name, prof_data in city_data.get("professions", {}).items():
            dept_count = prof_data.get("department_count", 0)
            commune_total = sum(c.get("count", 0) for c in prof_data.get("communes", []))
            n_communes = len(prof_data.get("communes", []))
            print(f"    {prof_name}: {dept_count} in dept, {commune_total} in city ({n_communes} communes)")

    search_status = results.get("metadata", {}).get("search_api_status", "unknown")
    print(f"\nSearch API status: {search_status}")

    successes = [a for a in results.get("search_attempts", []) if a.get("status") == "success"]
    if successes:
        total_found = sum(a.get("count", 0) for a in successes)
        print(f"Individual practitioners found: {total_found}")
    else:
        print("Individual practitioners: NOT AVAILABLE (search backend returning HTTP 500)")

    print(f"\nData saved to: {OUTPUT_FILE}")
    print(f"File size: {OUTPUT_FILE.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
