#!/usr/bin/env python3
"""
Agent de collecte OSM - Garages, concessionnaires et ateliers moto
Région d'Évry et communes limitrophes
"""

import json
import time
import requests

OUTPUT_FILE = "/home/user/Website01/agent_out_6_osm_evry.json"
API_URL = "https://overpass-api.de/api/interpreter"
BBOX = "48.55,2.30,48.75,2.55"
DELAY = 10       # secondes entre chaque requête
MAX_RETRIES = 4  # tentatives max par requête
RETRY_WAIT = 20  # secondes d'attente entre les retries

QUERIES = {
    "garages": f"""[out:json][timeout:60];
(
  node["shop"="car_repair"]({BBOX});
  way["shop"="car_repair"]({BBOX});
  node["amenity"="car_repair"]({BBOX});
  way["amenity"="car_repair"]({BBOX});
);
out body;""",

    "concessionnaires": f"""[out:json][timeout:60];
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
out body;"""
}


def extract_poi(element, category):
    tags = element.get("tags", {})
    name = tags.get("name", "").strip()
    if not name:
        return None

    # Téléphone
    telephone = tags.get("phone") or tags.get("contact:phone") or ""

    # Adresse
    housenumber = tags.get("addr:housenumber", "").strip()
    street = tags.get("addr:street", "").strip()
    adresse = f"{housenumber} {street}".strip() if housenumber or street else ""

    # Localisation
    code_postal = tags.get("addr:postcode", "")
    ville = tags.get("addr:city", "")

    # Site web
    site_web = tags.get("website") or tags.get("contact:website") or ""

    # Type de shop
    shop_type = tags.get("shop") or tags.get("amenity") or ""

    return {
        "osm_id": element.get("id"),
        "nom": name,
        "telephone": telephone,
        "adresse": adresse,
        "code_postal": code_postal,
        "ville": ville,
        "site_web": site_web,
        "shop_type": shop_type,
        "categorie": category,
        "source": "OpenStreetMap"
    }


def query_overpass(query_name, query_text):
    for attempt in range(1, MAX_RETRIES + 1):
        print(f"  Requête '{query_name}' (tentative {attempt}/{MAX_RETRIES})...", end=" ", flush=True)
        try:
            response = requests.post(
                API_URL,
                data={"data": query_text},
                timeout=120,
                headers={"User-Agent": "OSM-Evry-Collector/1.0"}
            )
            if response.status_code == 429:
                wait = RETRY_WAIT * attempt
                print(f"429 Too Many Requests. Attente {wait}s avant retry...")
                time.sleep(wait)
                continue
            if response.status_code in (502, 503, 504):
                wait = RETRY_WAIT * attempt
                print(f"{response.status_code} erreur serveur. Attente {wait}s avant retry...")
                time.sleep(wait)
                continue
            response.raise_for_status()
            data = response.json()
            elements = data.get("elements", [])
            print(f"{len(elements)} éléments bruts reçus.")
            return elements
        except requests.exceptions.Timeout:
            wait = RETRY_WAIT * attempt
            print(f"Timeout. Attente {wait}s avant retry...")
            time.sleep(wait)
        except requests.exceptions.RequestException as e:
            print(f"ERREUR: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_WAIT)
        except json.JSONDecodeError as e:
            print(f"ERREUR JSON: {e}")
            break

    print(f"  ECHEC définitif pour '{query_name}' après {MAX_RETRIES} tentatives.")
    return []


def main():
    print("=" * 60)
    print("Collecte OSM - Garages / Moto - Région Évry")
    print(f"Bounding box: {BBOX}")
    print("=" * 60)

    all_pois = {}  # clé = osm_id pour dédoublonnage
    counts_by_category = {}

    for i, (category, query_text) in enumerate(QUERIES.items()):
        if i > 0:
            print(f"  Attente {DELAY}s avant prochaine requête...")
            time.sleep(DELAY)

        elements = query_overpass(category, query_text)

        added = 0
        for element in elements:
            poi = extract_poi(element, category)
            if poi is None:
                continue
            osm_id = poi["osm_id"]
            if osm_id not in all_pois:
                all_pois[osm_id] = poi
                added += 1

        counts_by_category[category] = added
        print(f"  -> {added} POI valides ajoutés pour '{category}'.")

    # Résultats finaux
    final_list = list(all_pois.values())

    print("\n" + "=" * 60)
    print("RÉSUMÉ PAR TYPE:")
    for cat, count in counts_by_category.items():
        print(f"  {cat:20s}: {count} POI")
    print(f"  {'TOTAL (dédoublonné)':20s}: {len(final_list)} POI")
    print("=" * 60)

    # Sauvegarde
    output = {
        "meta": {
            "source": "OpenStreetMap via Overpass API",
            "region": "Évry et communes limitrophes",
            "bbox": BBOX,
            "communes": ["Évry-Courcouronnes", "Corbeil-Essonnes", "Ris-Orangis", "Lisses", "Bondoufle", "Courcouronnes"],
            "total": len(final_list),
            "par_categorie": counts_by_category,
            "date_collecte": "2026-03-27"
        },
        "pois": final_list
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nFichier sauvegardé: {OUTPUT_FILE}")
    print(f"Total POI: {len(final_list)}")


if __name__ == "__main__":
    main()
