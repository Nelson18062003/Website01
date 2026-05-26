#!/usr/bin/env python3
"""Scraper: OpenStreetMap Overpass API for medical facilities."""
import time
import requests
from scraper_utils import (
    setup_logging, save_json, format_phone, format_postal_code
)

logger = setup_logging("osm")

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Bounding boxes: south, west, north, east
BBOXES = {
    "paris": (48.815, 2.225, 48.902, 2.420),
    "marseille": (43.20, 5.30, 43.38, 5.50),
    "lille": (50.58, 2.95, 50.70, 3.18),
}

# OSM amenity types for medical facilities
AMENITY_TYPES = [
    "hospital", "clinic", "dentist", "doctors", "laboratory",
]
HEALTHCARE_TYPES = [
    "hospital", "clinic", "dentist", "doctor", "laboratory",
    "physiotherapist", "optometrist", "centre", "dialysis",
    "radiologist", "gynaecologist", "cardiologist",
]

OSM_CATEGORY_MAP = {
    "hospital": "Hôpital",
    "clinic": "Clinique privée",
    "dentist": "Cabinet dentaire",
    "doctors": "Cabinet médical / Médecin généraliste",
    "doctor": "Cabinet médical / Médecin généraliste",
    "laboratory": "Laboratoire d'analyses médicales",
    "physiotherapist": "Cabinet de kinésithérapie / Rééducation",
    "optometrist": "Cabinet d'ophtalmologie",
    "centre": "Centre de santé",
    "dialysis": "Centre de dialyse",
    "radiologist": "Centre de radiologie / Imagerie médicale",
    "gynaecologist": "Cabinet de gynécologie",
    "cardiologist": "Cabinet de cardiologie",
}


def query_overpass(zone_name, bbox):
    """Query Overpass API for medical facilities in a bounding box."""
    south, west, north, east = bbox

    # Build Overpass QL query for amenity and healthcare tags
    amenity_filters = "".join(f'node["amenity"="{a}"]({south},{west},{north},{east});way["amenity"="{a}"]({south},{west},{north},{east});' for a in AMENITY_TYPES)
    healthcare_filters = "".join(f'node["healthcare"="{h}"]({south},{west},{north},{east});way["healthcare"="{h}"]({south},{west},{north},{east});' for h in HEALTHCARE_TYPES)

    query = f"""
    [out:json][timeout:120];
    (
      {amenity_filters}
      {healthcare_filters}
    );
    out center body;
    """

    logger.info(f"Querying Overpass for {zone_name}...")
    try:
        r = requests.post(OVERPASS_URL, data={"data": query}, timeout=180)
        if r.status_code != 200:
            logger.error(f"Overpass error for {zone_name}: HTTP {r.status_code}")
            return []

        data = r.json()
        elements = data.get("elements", [])
        logger.info(f"Overpass {zone_name}: {len(elements)} elements")
        return elements
    except Exception as e:
        logger.error(f"Overpass error for {zone_name}: {e}")
        return []


def process_elements(elements, zone_name):
    """Process Overpass elements into our standard record format."""
    results = []
    seen_names = set()

    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name", "").strip()
        if not name:
            name = tags.get("official_name", "").strip()
        if not name:
            continue

        # Deduplicate within OSM results
        dedup_key = f"{name.upper()}_{tags.get('addr:postcode', '')}"
        if dedup_key in seen_names:
            continue
        seen_names.add(dedup_key)

        # Determine category
        amenity = tags.get("amenity", "")
        healthcare = tags.get("healthcare", "")
        cat_key = healthcare or amenity
        category = OSM_CATEGORY_MAP.get(cat_key, "Structure médicale")

        # Build address
        addr_parts = []
        if tags.get("addr:housenumber"):
            addr_parts.append(tags["addr:housenumber"])
        if tags.get("addr:street"):
            addr_parts.append(tags["addr:street"])

        record = {
            "raison_sociale": name,
            "categorie": category,
            "code_naf": "",
            "libelle_naf": "",
            "telephone": format_phone(tags.get("phone", "") or tags.get("contact:phone", "")),
            "adresse": " ".join(addr_parts),
            "code_postal": format_postal_code(tags.get("addr:postcode", "")),
            "ville": tags.get("addr:city", "") or zone_name.capitalize(),
            "siret": "",
            "siren": "",
            "site_web": tags.get("website", "") or tags.get("contact:website", ""),
            "email": tags.get("email", "") or tags.get("contact:email", ""),
            "effectif": "",
            "date_creation": "",
            "source": "OpenStreetMap",
        }
        results.append(record)

    return results


def main():
    all_results = []

    for zone_name, bbox in BBOXES.items():
        elements = query_overpass(zone_name, bbox)
        results = process_elements(elements, zone_name)
        all_results.extend(results)
        logger.info(f"OSM {zone_name}: {len(results)} usable records")
        time.sleep(5)  # Be nice to Overpass

    logger.info(f"OSM total: {len(all_results)} records")
    save_json(all_results, "osm.json")
    logger.info("Saved to data/osm.json")
    return all_results


if __name__ == "__main__":
    main()
