#!/usr/bin/env python3
"""
Interroge l'Overpass API avec des bbox précis pour Colomiers, Blagnac et Muret.
Extrait nom, phone, website, email de chaque résultat OSM.
Matche avec les fichiers api_*.json existants.
Sauvegarde dans osm_*_v2.json.
"""

import json
import time
import requests
from difflib import SequenceMatcher
import unicodedata
import re

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

CITIES = {
    "colomiers": {
        "query": """[out:json];(
            node["shop"="car_repair"](43.58,1.30,43.64,1.38);
            node["shop"="car"](43.58,1.30,43.64,1.38);
            way["shop"="car_repair"](43.58,1.30,43.64,1.38);
            way["shop"="car"](43.58,1.30,43.64,1.38);
            node["craft"="car_repair"](43.58,1.30,43.64,1.38);
            way["craft"="car_repair"](43.58,1.30,43.64,1.38);
            node["amenity"="car_wash"](43.58,1.30,43.64,1.38);
            way["amenity"="car_wash"](43.58,1.30,43.64,1.38);
            node["shop"="tyres"](43.58,1.30,43.64,1.38);
            way["shop"="tyres"](43.58,1.30,43.64,1.38);
            node["shop"="car_parts"](43.58,1.30,43.64,1.38);
            way["shop"="car_parts"](43.58,1.30,43.64,1.38);
        );out body center;""",
        "api_file": "api_colomiers.json",
        "output_file": "osm_colomiers_v2.json",
    },
    "blagnac": {
        "query": """[out:json];(
            node["shop"="car_repair"](43.61,1.35,43.67,1.43);
            node["shop"="car"](43.61,1.35,43.67,1.43);
            way["shop"="car_repair"](43.61,1.35,43.67,1.43);
            way["shop"="car"](43.61,1.35,43.67,1.43);
            node["craft"="car_repair"](43.61,1.35,43.67,1.43);
            way["craft"="car_repair"](43.61,1.35,43.67,1.43);
            node["amenity"="car_wash"](43.61,1.35,43.67,1.43);
            way["amenity"="car_wash"](43.61,1.35,43.67,1.43);
            node["shop"="tyres"](43.61,1.35,43.67,1.43);
            way["shop"="tyres"](43.61,1.35,43.67,1.43);
            node["shop"="car_parts"](43.61,1.35,43.67,1.43);
            way["shop"="car_parts"](43.61,1.35,43.67,1.43);
        );out body center;""",
        "api_file": "api_blagnac.json",
        "output_file": "osm_blagnac_v2.json",
    },
    "muret": {
        "query": """[out:json];(
            node["shop"="car_repair"](43.43,1.29,43.49,1.37);
            node["shop"="car"](43.43,1.29,43.49,1.37);
            way["shop"="car_repair"](43.43,1.29,43.49,1.37);
            way["shop"="car"](43.43,1.29,43.49,1.37);
            node["craft"="car_repair"](43.43,1.29,43.49,1.37);
            way["craft"="car_repair"](43.43,1.29,43.49,1.37);
            node["amenity"="car_wash"](43.43,1.29,43.49,1.37);
            way["amenity"="car_wash"](43.43,1.29,43.49,1.37);
            node["shop"="tyres"](43.43,1.29,43.49,1.37);
            way["shop"="tyres"](43.43,1.29,43.49,1.37);
            node["shop"="car_parts"](43.43,1.29,43.49,1.37);
            way["shop"="car_parts"](43.43,1.29,43.49,1.37);
        );out body center;""",
        "api_file": "api_muret.json",
        "output_file": "osm_muret_v2.json",
    },
}

BASE_DIR = "/home/user/Website01"


def normalize(text):
    """Normalise un texte pour la comparaison : minuscules, sans accents, sans ponctuation."""
    if not text:
        return ""
    text = text.lower().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def match_score(api_name, osm_name):
    """Calcule un score de similarité entre un nom API et un nom OSM."""
    n1 = normalize(api_name)
    n2 = normalize(osm_name)
    if not n1 or not n2:
        return 0.0

    # Exact match
    if n1 == n2:
        return 1.0

    # Check if one contains the other
    if n1 in n2 or n2 in n1:
        return 0.85

    # Check token overlap
    tokens1 = set(n1.split())
    tokens2 = set(n2.split())
    if tokens1 and tokens2:
        common = tokens1 & tokens2
        # Remove trivial words
        trivial = {"de", "la", "le", "les", "du", "des", "et", "l", "d", "en", "au", "aux",
                    "sarl", "sas", "eurl", "sa", "auto", "garage", "carrosserie"}
        meaningful_common = common - trivial
        if meaningful_common:
            token_score = len(meaningful_common) / max(len(tokens1 - trivial), len(tokens2 - trivial), 1)
            if token_score >= 0.5:
                return max(0.7, token_score)

    # SequenceMatcher
    return SequenceMatcher(None, n1, n2).ratio()


def query_overpass(query):
    """Interroge l'Overpass API et retourne les éléments."""
    print(f"  Envoi requête Overpass API...")
    resp = requests.post(OVERPASS_URL, data={"data": query}, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    elements = data.get("elements", [])
    print(f"  -> {len(elements)} éléments trouvés")
    return elements


def extract_osm_info(element):
    """Extrait les infos utiles d'un élément OSM."""
    tags = element.get("tags", {})
    lat = element.get("lat") or element.get("center", {}).get("lat")
    lon = element.get("lon") or element.get("center", {}).get("lon")
    return {
        "osm_id": element.get("id"),
        "osm_type": element.get("type"),
        "osm_name": tags.get("name", ""),
        "osm_phone": tags.get("phone", tags.get("contact:phone", "")),
        "osm_website": tags.get("website", tags.get("contact:website", "")),
        "osm_email": tags.get("email", tags.get("contact:email", "")),
        "osm_shop": tags.get("shop", tags.get("craft", tags.get("amenity", ""))),
        "osm_brand": tags.get("brand", ""),
        "osm_operator": tags.get("operator", ""),
        "osm_addr_street": tags.get("addr:street", ""),
        "osm_addr_housenumber": tags.get("addr:housenumber", ""),
        "osm_addr_city": tags.get("addr:city", ""),
        "osm_opening_hours": tags.get("opening_hours", ""),
        "osm_lat": lat,
        "osm_lon": lon,
    }


def find_best_match(api_entry, osm_entries):
    """Trouve le meilleur match OSM pour une entrée API."""
    api_name = api_entry.get("nom", "")
    best_score = 0
    best_osm = None

    for osm in osm_entries:
        # Compare with osm name, brand, and operator
        for field in ["osm_name", "osm_brand", "osm_operator"]:
            score = match_score(api_name, osm.get(field, ""))
            if score > best_score:
                best_score = score
                best_osm = osm

    return best_osm, best_score


def process_city(city_name, config):
    """Traite une ville complète."""
    print(f"\n{'='*60}")
    print(f"Traitement de {city_name.upper()}")
    print(f"{'='*60}")

    # Charger les données API
    api_path = f"{BASE_DIR}/{config['api_file']}"
    with open(api_path, "r", encoding="utf-8") as f:
        api_data = json.load(f)
    print(f"  {len(api_data)} entrées dans {config['api_file']}")

    # Requête Overpass
    osm_elements = query_overpass(config["query"])

    # Extraire les infos OSM
    osm_entries = [extract_osm_info(el) for el in osm_elements]

    # Log des résultats OSM
    print(f"\n  Résultats OSM trouvés :")
    for osm in osm_entries:
        name = osm["osm_name"] or "(sans nom)"
        phone = osm["osm_phone"] or "-"
        website = osm["osm_website"] or "-"
        email = osm["osm_email"] or "-"
        print(f"    - {name} | tel:{phone} | web:{website} | email:{email}")

    # Matcher avec les données API
    matched_count = 0
    results = []
    for api_entry in api_data:
        entry = dict(api_entry)  # copie
        best_osm, score = find_best_match(api_entry, osm_entries)

        if best_osm and score >= 0.45:
            matched_count += 1
            entry["osm_match_score"] = round(score, 2)
            entry["osm_name"] = best_osm["osm_name"]
            entry["osm_phone"] = best_osm["osm_phone"]
            entry["osm_website"] = best_osm["osm_website"]
            entry["osm_email"] = best_osm["osm_email"]
            entry["osm_lat"] = best_osm["osm_lat"]
            entry["osm_lon"] = best_osm["osm_lon"]
            entry["osm_id"] = best_osm["osm_id"]
            entry["osm_opening_hours"] = best_osm["osm_opening_hours"]
            entry["osm_addr_street"] = best_osm["osm_addr_street"]
            print(f"  MATCH ({score:.2f}): {api_entry['nom']} <-> {best_osm['osm_name']}")
        else:
            entry["osm_match_score"] = 0
            entry["osm_name"] = ""
            entry["osm_phone"] = ""
            entry["osm_website"] = ""
            entry["osm_email"] = ""
            entry["osm_lat"] = None
            entry["osm_lon"] = None
            entry["osm_id"] = None
            entry["osm_opening_hours"] = ""
            entry["osm_addr_street"] = ""

        results.append(entry)

    # Sauvegarder
    output_path = f"{BASE_DIR}/{config['output_file']}"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n  Résumé {city_name}: {matched_count}/{len(api_data)} matchés")
    print(f"  Sauvegardé dans {output_path}")

    # Aussi sauvegarder les données brutes OSM pour référence
    raw_path = f"{BASE_DIR}/osm_raw_{city_name}.json"
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(osm_entries, f, ensure_ascii=False, indent=2)
    print(f"  Données OSM brutes dans {raw_path}")

    return matched_count, len(api_data), len(osm_entries)


def main():
    total_matched = 0
    total_api = 0
    total_osm = 0

    for city_name, config in CITIES.items():
        matched, api_count, osm_count = process_city(city_name, config)
        total_matched += matched
        total_api += api_count
        total_osm += osm_count
        # Pause entre requêtes pour respecter les limites de l'API
        time.sleep(2)

    print(f"\n{'='*60}")
    print(f"TOTAL: {total_matched}/{total_api} matchés, {total_osm} éléments OSM trouvés")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
