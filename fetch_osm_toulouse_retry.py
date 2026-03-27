#!/usr/bin/env python3
"""
Agent OSM - Retry des requetes echouees (concessionnaires_auto + carrosserie)
"""

import json
import time
import sys

try:
    import requests
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "-q"])
    import requests

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OUTPUT_FILE = "/home/user/Website01/agent_out_5_osm_toulouse.json"
BBOX = "43.45,1.20,43.75,1.60"

QUERIES_RETRY = {
    "concessionnaires_auto": f"""[out:json][timeout:60];
(
  node["shop"="car"]({BBOX});
  way["shop"="car"]({BBOX});
  node["shop"="car_dealer"]({BBOX});
  way["shop"="car_dealer"]({BBOX});
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
    tags = element.get("tags", {})
    name = tags.get("name", "").strip()
    if not name:
        return None

    phone = tags.get("phone") or tags.get("contact:phone") or ""
    housenumber = tags.get("addr:housenumber", "").strip()
    street = tags.get("addr:street", "").strip()
    if housenumber and street:
        adresse = f"{housenumber} {street}"
    elif street:
        adresse = street
    else:
        adresse = ""

    return {
        "nom": name,
        "telephone": phone,
        "adresse": adresse,
        "code_postal": tags.get("addr:postcode", ""),
        "ville": tags.get("addr:city", ""),
        "site_web": tags.get("website") or tags.get("contact:website") or "",
        "osm_id": element.get("id"),
        "osm_type": element.get("type", ""),
        "shop_type": tags.get("shop", ""),
        "amenity": tags.get("amenity", ""),
        "categorie_osm": query_type,
        "source": "OpenStreetMap",
    }


def query_overpass_with_retry(query_name, query_body, max_retries=3):
    for attempt in range(1, max_retries + 1):
        wait = 10 * attempt
        print(f"  [{attempt}/{max_retries}] Interrogation: {query_name} ...", end=" ", flush=True)
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
            if attempt < max_retries:
                print(f"    -> Nouvelle tentative dans {wait}s ...")
                time.sleep(wait)
    return []


def main():
    print("=" * 60)
    print("Retry - Concessionnaires auto + Carrosserie")
    print("=" * 60)

    # Load existing output
    with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
        existing = json.load(f)

    # Index existing POIs by osm_id
    all_pois = {poi["osm_id"]: poi for poi in existing["pois"]}
    counts_by_type = existing["metadata"]["counts_by_type"]

    print(f"POI existants charges: {len(all_pois)}")
    print()

    queries_list = list(QUERIES_RETRY.items())
    for i, (query_name, query_body) in enumerate(queries_list):
        elements = query_overpass_with_retry(query_name, query_body)

        extracted = 0
        for element in elements:
            poi = extract_poi(element, query_name)
            if poi is None:
                continue
            osm_id = poi["osm_id"]
            if osm_id not in all_pois:
                all_pois[osm_id] = poi
                extracted += 1

        counts_by_type[query_name] = extracted
        print(f"    -> {extracted} POI nommes retenus pour '{query_name}'")

        if i < len(queries_list) - 1:
            print("    (pause 5s...)")
            time.sleep(5)

    pois_list = list(all_pois.values())

    print()
    print("=" * 60)
    print("RESULTATS FINAUX PAR CATEGORIE:")
    for cat, count in counts_by_type.items():
        print(f"  {cat:30s}: {count:4d} POI")
    print(f"  {'TOTAL (dedoublonne)':30s}: {len(pois_list):4d} POI")
    print("=" * 60)

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

    print(f"\nFichier mis a jour: {OUTPUT_FILE}")
    print(f"Total POI exportes: {len(pois_list)}")


if __name__ == "__main__":
    main()
