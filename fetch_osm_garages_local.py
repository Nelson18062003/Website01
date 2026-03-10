#!/usr/bin/env python3
"""
Fetch garage/auto repair data from OpenStreetMap Overpass API
for Nancy (dept 54) and Saint-Denis (dept 93) areas.
Enrich with French government reverse geocoding API.
"""

import json
import time
import requests

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
REVERSE_GEOCODE_URL = "https://api-adresse.data.gouv.fr/reverse/"

AREAS = {
    "Nancy (54)": {"south": 48.557, "west": 5.979, "north": 48.827, "east": 6.389},
    "Saint-Denis (93)": {"south": 48.801, "west": 2.151, "north": 49.071, "east": 2.563},
}

TAG_FILTERS = [
    '["shop"="car_repair"]',
    '["shop"="car"]',
    '["craft"="car_repair"]',
    '["amenity"="car_wash"]',
    '["shop"="tyres"]',
]


def build_overpass_query(bbox):
    """Build an Overpass QL query for all tag filters in the given bounding box."""
    s, w, n, e = bbox["south"], bbox["west"], bbox["north"], bbox["east"]
    bb = f"{s},{w},{n},{e}"
    parts = []
    for tag_filter in TAG_FILTERS:
        parts.append(f"  node{tag_filter}({bb});")
        parts.append(f"  way{tag_filter}({bb});")
    query = "[out:json][timeout:60];\n(\n" + "\n".join(parts) + "\n);\nout center body;"
    return query


def fetch_overpass(query):
    """Send a query to Overpass API and return the elements."""
    print(f"  Sending Overpass query ({len(query)} chars)...")
    resp = requests.post(OVERPASS_URL, data={"data": query}, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    return data.get("elements", [])


def extract_entry(element):
    """Extract a normalized entry dict from an Overpass element."""
    tags = element.get("tags", {})

    # Get coordinates: for nodes use lat/lon directly, for ways use center
    if element["type"] == "node":
        lat = element.get("lat")
        lon = element.get("lon")
    else:
        center = element.get("center", {})
        lat = center.get("lat")
        lon = center.get("lon")

    if lat is None or lon is None:
        return None

    housenumber = tags.get("addr:housenumber", "")
    street = tags.get("addr:street", "")
    address_parts = []
    if housenumber:
        address_parts.append(housenumber)
    if street:
        address_parts.append(street)
    address = " ".join(address_parts)

    return {
        "name": tags.get("name", ""),
        "phone": tags.get("phone", tags.get("contact:phone", "")),
        "address": address,
        "postal_code": tags.get("addr:postcode", ""),
        "city": tags.get("addr:city", ""),
        "lat": lat,
        "lon": lon,
        "website": tags.get("website", tags.get("contact:website", "")),
        "opening_hours": tags.get("opening_hours", ""),
        "source": "OpenStreetMap",
        "osm_id": element.get("id"),
        "osm_type": element.get("type"),
        "tags": tags,
    }


def reverse_geocode(lat, lon):
    """Use the French government reverse geocoding API to get postal_code and city."""
    try:
        resp = requests.get(
            REVERSE_GEOCODE_URL,
            params={"lat": lat, "lon": lon},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        features = data.get("features", [])
        if features:
            props = features[0].get("properties", {})
            return props.get("postcode", ""), props.get("city", "")
    except Exception as e:
        print(f"    Reverse geocode error for ({lat}, {lon}): {e}")
    return "", ""


def enrich_entries(entries):
    """Fill in missing postal_code and city via reverse geocoding."""
    need_geocode = [e for e in entries if not e["postal_code"] or not e["city"]]
    total = len(need_geocode)
    if total == 0:
        print("  All entries already have postal code and city.")
        return

    print(f"  Reverse geocoding {total} entries missing postal_code/city...")
    for i, entry in enumerate(need_geocode):
        postcode, city = reverse_geocode(entry["lat"], entry["lon"])
        if not entry["postal_code"] and postcode:
            entry["postal_code"] = postcode
        if not entry["city"] and city:
            entry["city"] = city
        # Be polite to the API
        if (i + 1) % 20 == 0:
            print(f"    Geocoded {i + 1}/{total}...")
            time.sleep(1)
        else:
            time.sleep(0.15)
    print(f"    Geocoded {total}/{total} done.")


def main():
    all_entries = []
    area_counts = {}

    for area_name, bbox in AREAS.items():
        print(f"\n--- Fetching: {area_name} ---")
        query = build_overpass_query(bbox)
        elements = fetch_overpass(query)
        print(f"  Got {len(elements)} raw elements from Overpass.")

        # Deduplicate by osm_type + osm_id
        seen = set()
        entries = []
        for el in elements:
            key = (el.get("type"), el.get("id"))
            if key in seen:
                continue
            seen.add(key)
            entry = extract_entry(el)
            if entry:
                entry["area"] = area_name
                entries.append(entry)

        print(f"  {len(entries)} unique entries after dedup.")
        area_counts[area_name] = len(entries)

        # Enrich missing addresses
        enrich_entries(entries)
        all_entries.extend(entries)

    # Build final output (remove internal fields)
    output = []
    for e in all_entries:
        output.append({
            "name": e["name"],
            "phone": e["phone"],
            "address": e["address"],
            "postal_code": e["postal_code"],
            "city": e["city"],
            "lat": e["lat"],
            "lon": e["lon"],
            "website": e["website"],
            "opening_hours": e["opening_hours"],
            "source": e["source"],
            "area": e["area"],
        })

    output_path = "/home/user/Website01/osm_garages_nancy_stdenis.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nSaved {len(output)} entries to {output_path}")

    # Stats
    print("\n=== STATS ===")
    print(f"Total entries: {len(output)}")
    for area_name, count in area_counts.items():
        print(f"  {area_name}: {count}")
    with_phone = sum(1 for e in output if e["phone"])
    print(f"Entries with phone number: {with_phone}")
    with_website = sum(1 for e in output if e["website"])
    print(f"Entries with website: {with_website}")
    with_name = sum(1 for e in output if e["name"])
    print(f"Entries with name: {with_name}")


if __name__ == "__main__":
    main()
