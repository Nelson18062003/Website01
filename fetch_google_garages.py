#!/usr/bin/env python3
"""
Fetch garages/auto repair shops in Nancy (54) and Saint-Denis (93)
using freely available sources (Nominatim + local OSM data).
"""

import json
import time
import urllib.request
import urllib.parse
import ssl

OUTPUT_FILE = "/home/user/Website01/nominatim_garages_nancy_stdenis.json"
OSM_FILE = "/home/user/Website01/osm_garages_phones.json"

USER_AGENT = "GarageFinderScript/1.0 (research project; contact@example.com)"

# Bounding boxes
AREAS = {
    "Nancy": {"lat_min": 48.55, "lat_max": 48.80, "lon_min": 5.95, "lon_max": 6.35},
    "Saint-Denis": {"lat_min": 48.88, "lat_max": 48.97, "lon_min": 2.30, "lon_max": 2.42},
}

# Nominatim search queries
NOMINATIM_QUERIES = [
    "garage automobile Nancy France",
    "réparation automobile Nancy France",
    "garage automobile Saint-Denis France",
    "réparation automobile Saint-Denis France",
    "garage auto Nancy 54 France",
    "garage auto Saint-Denis 93 France",
    "carrosserie Nancy France",
    "carrosserie Saint-Denis France",
    "mécanicien automobile Nancy France",
    "mécanicien automobile Saint-Denis France",
]

# SSL context to avoid certificate issues
ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE


def fetch_url(url, description=""):
    """Fetch a URL with proper headers and error handling."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, context=ssl_ctx, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data
    except Exception as e:
        print(f"  [WARN] Failed to fetch {description or url}: {e}")
        return None


def nominatim_search(query, limit=50):
    """Search Nominatim for a query string."""
    params = urllib.parse.urlencode({
        "q": query,
        "format": "json",
        "addressdetails": "1",
        "limit": str(limit),
    })
    url = f"https://nominatim.openstreetmap.org/search?{params}"
    return fetch_url(url, description=f"Nominatim: {query}")


def reverse_geocode_gouv(lat, lon):
    """Use api-adresse.data.gouv.fr to reverse geocode a point."""
    url = f"https://api-adresse.data.gouv.fr/reverse/?lon={lon}&lat={lat}"
    return fetch_url(url, description=f"reverse({lat},{lon})")


def in_area(lat, lon, area):
    """Check if a point falls within a bounding box."""
    return (area["lat_min"] <= lat <= area["lat_max"] and
            area["lon_min"] <= lon <= area["lon_max"])


def detect_area(lat, lon):
    """Return area name if point is in a known area."""
    for name, bbox in AREAS.items():
        if in_area(lat, lon, bbox):
            return name
    return None


def parse_nominatim_result(r):
    """Parse a single Nominatim search result into our standard format."""
    addr = r.get("address", {})
    entry = {
        "name": r.get("name") or r.get("display_name", "").split(",")[0],
        "phone": "",
        "address": r.get("display_name", ""),
        "postal_code": addr.get("postcode", ""),
        "city": addr.get("city") or addr.get("town") or addr.get("village") or addr.get("municipality", ""),
        "lat": float(r.get("lat", 0)),
        "lon": float(r.get("lon", 0)),
        "website": "",
        "source": "Nominatim",
    }
    return entry


def parse_osm_entry(entry):
    """Parse an entry from the local OSM JSON file."""
    tags = entry.get("tags", {})

    # Build address from components
    parts = []
    if tags.get("addr:housenumber"):
        parts.append(tags["addr:housenumber"])
    if tags.get("addr:street"):
        parts.append(tags["addr:street"])
    if tags.get("addr:postcode"):
        parts.append(tags["addr:postcode"])
    if tags.get("addr:city"):
        parts.append(tags["addr:city"])
    address = ", ".join(parts) if parts else ""

    return {
        "name": tags.get("name", ""),
        "phone": tags.get("phone") or tags.get("contact:phone", ""),
        "address": address,
        "postal_code": tags.get("addr:postcode", ""),
        "city": tags.get("addr:city", ""),
        "lat": entry.get("lat", 0),
        "lon": entry.get("lon", 0),
        "website": tags.get("website") or tags.get("contact:website", ""),
        "source": "OSM",
    }


def deduplicate(results):
    """Remove duplicates based on name+city or lat/lon proximity."""
    seen = {}
    deduped = []
    for r in results:
        # Key by lowercase name + postal code, or by rounded coordinates
        name_key = (r["name"].lower().strip(), r["postal_code"])
        coord_key = (round(r["lat"], 5), round(r["lon"], 5))

        if name_key in seen and name_key[0]:
            # Merge: keep the one with more info, update missing fields
            idx = seen[name_key]
            existing = deduped[idx]
            for field in ["phone", "address", "postal_code", "city", "website"]:
                if not existing[field] and r[field]:
                    existing[field] = r[field]
            if existing["source"] != r["source"]:
                existing["source"] = "Nominatim/OSM"
            continue
        if coord_key in seen:
            idx = seen[coord_key]
            existing = deduped[idx]
            for field in ["phone", "address", "postal_code", "city", "website", "name"]:
                if not existing[field] and r[field]:
                    existing[field] = r[field]
            if existing["source"] != r["source"]:
                existing["source"] = "Nominatim/OSM"
            continue

        idx = len(deduped)
        if r["name"].strip():
            seen[name_key] = idx
        seen[coord_key] = idx
        deduped.append(r)

    return deduped


def main():
    all_results = []

    # ── Approach 1: Nominatim search ──
    print("=" * 60)
    print("APPROACH 1: Nominatim search")
    print("=" * 60)

    nominatim_count = 0
    for query in NOMINATIM_QUERIES:
        print(f"  Searching: {query}")
        results = nominatim_search(query)
        if results:
            for r in results:
                lat = float(r.get("lat", 0))
                lon = float(r.get("lon", 0))
                area = detect_area(lat, lon)
                if area:
                    entry = parse_nominatim_result(r)
                    all_results.append(entry)
                    nominatim_count += 1
            print(f"    -> {len(results)} results, {nominatim_count} total in target areas")
        time.sleep(1.1)  # Nominatim rate limit

    print(f"\nNominatim total in target areas: {nominatim_count}")

    # ── Approach 2: Filter local OSM data ──
    print("\n" + "=" * 60)
    print("APPROACH 2: Local OSM data filtering")
    print("=" * 60)

    try:
        with open(OSM_FILE, "r", encoding="utf-8") as f:
            osm_data = json.load(f)
        print(f"  Loaded {len(osm_data)} garages from {OSM_FILE}")
    except Exception as e:
        print(f"  [ERROR] Could not load OSM file: {e}")
        osm_data = []

    osm_matches = []
    for entry in osm_data:
        lat = entry.get("lat", 0)
        lon = entry.get("lon", 0)
        area = detect_area(lat, lon)
        if area:
            parsed = parse_osm_entry(entry)
            osm_matches.append(parsed)

    print(f"  Found {len(osm_matches)} garages in target areas")

    # Reverse geocode entries missing postal_code or city
    need_geocode = [e for e in osm_matches if not e["postal_code"] or not e["city"]]
    print(f"  {len(need_geocode)} entries need reverse geocoding")

    geocoded = 0
    for entry in need_geocode:
        result = reverse_geocode_gouv(entry["lat"], entry["lon"])
        if result and result.get("features"):
            props = result["features"][0].get("properties", {})
            if not entry["postal_code"]:
                entry["postal_code"] = props.get("postcode", "")
            if not entry["city"]:
                entry["city"] = props.get("city", "")
            if not entry["address"]:
                entry["address"] = props.get("label", "")
            geocoded += 1
        time.sleep(0.15)  # Be polite to the API

    print(f"  Reverse geocoded {geocoded} entries")

    all_results.extend(osm_matches)

    # ── Deduplicate ──
    print("\n" + "=" * 60)
    print("DEDUPLICATION")
    print("=" * 60)
    print(f"  Before dedup: {len(all_results)}")
    all_results = deduplicate(all_results)
    print(f"  After dedup:  {len(all_results)}")

    # Update source field for all
    for r in all_results:
        if r["source"] not in ("Nominatim/OSM",):
            r["source"] = "Nominatim/OSM"

    # ── Save ──
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"\nSaved to {OUTPUT_FILE}")

    # ── Stats ──
    print("\n" + "=" * 60)
    print("STATS")
    print("=" * 60)

    nancy = [r for r in all_results if detect_area(r["lat"], r["lon"]) == "Nancy"]
    stdenis = [r for r in all_results if detect_area(r["lat"], r["lon"]) == "Saint-Denis"]
    with_phone = [r for r in all_results if r["phone"]]
    with_address = [r for r in all_results if r["address"]]
    with_website = [r for r in all_results if r["website"]]

    print(f"  Total garages:       {len(all_results)}")
    print(f"  Nancy area:          {len(nancy)}")
    print(f"  Saint-Denis area:    {len(stdenis)}")
    print(f"  With phone:          {len(with_phone)}")
    print(f"  With address:        {len(with_address)}")
    print(f"  With website:        {len(with_website)}")

    # Show a few samples
    print("\n── Sample entries (Nancy) ──")
    for r in nancy[:3]:
        print(f"  {r['name']} | {r['phone']} | {r['city']} {r['postal_code']}")

    print("\n── Sample entries (Saint-Denis) ──")
    for r in stdenis[:3]:
        print(f"  {r['name']} | {r['phone']} | {r['city']} {r['postal_code']}")


if __name__ == "__main__":
    main()
