#!/usr/bin/env python3
"""
Agent de collecte OSM - Garages, concessionnaires et ateliers moto Toulouse
"""

import json
import time
import sys

# Auto-install requests if needed
try:
    import requests
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "-q"])
    import requests

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OUTPUT_FILE = "/home/user/Website01/agent_out_5_osm_toulouse.json"
BBOX = "43.45,1.20,43.75,1.60"
DELAY = 3  # seconds between queries

QUERIES = {
    "garages_auto": f"""[out:json][timeout:60];
(
  node["shop"="car_repair"]({BBOX});
  way["shop"="car_repair"]({BBOX});
  node["amenity"="car_repair"]({BBOX});
  way["amenity"="car_repair"]({BBOX});
);
out body;""",

    "concessionnaires_auto": f"""[out:json][timeout:60];
(
  node["shop"="car"]({BBOX});
  way["shop"="car"]({BBOX});
  node["shop"="car_dealer"]({BBOX});
  way["shop"="car_dealer"]({BBOX});
);
out body;""",

    "moto": f"""[out:json][timeout:60];
(
  node["shop"="motorcycle"]({BBOX});
  way["shop"="motorcycle"]({BBOX});
  node["shop"="motorcycle_repair"]({BBOX});
  way["shop"="motorcycle_repair"]({BBOX});
);
out body;""",

    "carrosserie": f"""[out:json][timeout:60];
(
  node["shop"="car_bodywork"]({BBOX});
  way["shop"="car_bodywork"]({BBOX});
);
out body;""",
}


def extract_poi(element, query_type):
    """Extract relevant fields from an OSM element."""
    tags = element.get("tags", {})

    name = tags.get("name", "").strip()
    if not name:
        return None  # Filter: only keep named POIs

    phone = tags.get("phone") or tags.get("contact:phone") or ""
    housenumber = tags.get("addr:housenumber", "").strip()
    street = tags.get("addr:street", "").strip()
    if housenumber and street:
        adresse = f"{housenumber} {street}"
    elif street:
        adresse = street
    else:
        adresse = ""

    code_postal = tags.get("addr:postcode", "")
    ville = tags.get("addr:city", "")
    site_web = tags.get("website") or tags.get("contact:website") or ""
    osm_id = element.get("id")
    osm_type = element.get("type", "")
    shop_type = tags.get("shop", "")
    amenity = tags.get("amenity", "")

    return {
        "nom": name,
        "telephone": phone,
        "adresse": adresse,
        "code_postal": code_postal,
        "ville": ville,
        "site_web": site_web,
        "osm_id": osm_id,
        "osm_type": osm_type,
        "shop_type": shop_type,
        "amenity": amenity,
        "categorie_osm": query_type,
        "source": "OpenStreetMap",
    }


def query_overpass(query_name, query_body):
    """Send a query to the Overpass API and return elements."""
    print(f"  Interrogation: {query_name} ...", end=" ", flush=True)
    try:
        response = requests.post(
            OVERPASS_URL,
            data={"data": query_body},
            timeout=90,
            headers={"User-Agent": "ToulouseGaragesCollector/1.0"},
        )
        response.raise_for_status()
        data = response.json()
        elements = data.get("elements", [])
        print(f"{len(elements)} elements bruts recus.")
        return elements
    except requests.exceptions.RequestException as e:
        print(f"ERREUR: {e}")
        return []
    except json.JSONDecodeError as e:
        print(f"ERREUR JSON: {e}")
        return []


def main():
    print("=" * 60)
    print("Agent OSM - Garages / Concessionnaires / Moto - Toulouse")
    print("=" * 60)
    print(f"Bounding box: {BBOX}")
    print(f"Fichier de sortie: {OUTPUT_FILE}")
    print()

    all_pois = {}  # deduplicate by osm_id
    counts_by_type = {}

    queries_list = list(QUERIES.items())
    for i, (query_name, query_body) in enumerate(queries_list):
        elements = query_overpass(query_name, query_body)

        extracted = 0
        for element in elements:
            poi = extract_poi(element, query_name)
            if poi is None:
                continue
            osm_id = poi["osm_id"]
            if osm_id not in all_pois:
                all_pois[osm_id] = poi
                extracted += 1
            # else: duplicate, skip

        counts_by_type[query_name] = extracted
        print(f"    -> {extracted} POI nommes retenus pour '{query_name}'")

        # Wait between queries (except after the last one)
        if i < len(queries_list) - 1:
            print(f"    (pause {DELAY}s...)")
            time.sleep(DELAY)

    # Final deduplicated list
    pois_list = list(all_pois.values())

    print()
    print("=" * 60)
    print("RESULTATS PAR CATEGORIE:")
    for cat, count in counts_by_type.items():
        print(f"  {cat:30s}: {count:4d} POI")
    print(f"  {'TOTAL (dedoublonne)':30s}: {len(pois_list):4d} POI")
    print("=" * 60)

    # Build output structure
    output = {
        "metadata": {
            "source": "OpenStreetMap via Overpass API",
            "region": "Toulouse elargie",
            "bbox": BBOX,
            "date_collecte": "2026-03-27",
            "total_pois": len(pois_list),
            "counts_by_type": counts_by_type,
        },
        "pois": pois_list,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nFichier sauvegarde: {OUTPUT_FILE}")
    print(f"Total POI exportes: {len(pois_list)}")


if __name__ == "__main__":
    main()
