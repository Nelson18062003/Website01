#!/usr/bin/env python3
"""
Enrichit les entreprises automobiles d'Evry-Courcouronnes avec des données OpenStreetMap (Overpass API).
Fait du fuzzy matching entre les résultats OSM et le fichier api_evry.json.
"""

import json
import re
import requests
from difflib import SequenceMatcher

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
INPUT_FILE = "/home/user/Website01/api_evry.json"
OUTPUT_FILE = "/home/user/Website01/osm_evry.json"

# Requête bbox autour d'Evry-Courcouronnes (lat ~48.63, lon ~2.43, rayon ~5km)
OVERPASS_QUERY = """
[out:json][timeout:60];
(
  node["shop"="car_repair"](48.60,2.38,48.66,2.48);
  node["shop"="car"](48.60,2.38,48.66,2.48);
  node["shop"="motorcycle"](48.60,2.38,48.66,2.48);
  way["shop"="car_repair"](48.60,2.38,48.66,2.48);
  way["shop"="car"](48.60,2.38,48.66,2.48);
  way["shop"="motorcycle"](48.60,2.38,48.66,2.48);
  node["craft"="coachbuilder"](48.60,2.38,48.66,2.48);
  way["craft"="coachbuilder"](48.60,2.38,48.66,2.48);
  node["amenity"="car_rental"](48.60,2.38,48.66,2.48);
  way["amenity"="car_rental"](48.60,2.38,48.66,2.48);
);
out body;
"""


def normalize(name):
    """Normalise un nom pour le matching : minuscules, sans ponctuation."""
    if not name:
        return ""
    name = name.lower()
    # Supprimer les formes juridiques courantes
    for term in ["sarl", "sas", "sa", "eurl", "auto", "garage", "carrosserie",
                 "concession", "atelier", "ets", "etablissements", "exploitation"]:
        name = re.sub(r'\b' + term + r'\b', '', name)
    name = re.sub(r'[^a-z0-9\s]', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def fuzzy_score(a, b):
    """Score de similarité entre deux noms normalisés."""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def query_overpass():
    """Interroge l'Overpass API et retourne les éléments."""
    print("Requete Overpass API en cours...")
    resp = requests.post(OVERPASS_URL, data={"data": OVERPASS_QUERY}, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    elements = data.get("elements", [])
    print(f"  -> {len(elements)} resultats OSM recus")
    return elements


def extract_osm_info(element):
    """Extrait les infos utiles d'un élément OSM."""
    tags = element.get("tags", {})
    return {
        "osm_id": element.get("id"),
        "osm_type": element.get("type"),
        "osm_name": tags.get("name", ""),
        "osm_phone": tags.get("phone", tags.get("contact:phone", "")),
        "osm_website": tags.get("website", tags.get("contact:website", "")),
        "osm_email": tags.get("email", tags.get("contact:email", "")),
        "osm_opening_hours": tags.get("opening_hours", ""),
        "osm_brand": tags.get("brand", ""),
        "osm_operator": tags.get("operator", ""),
        "osm_addr_street": tags.get("addr:street", ""),
        "osm_addr_housenumber": tags.get("addr:housenumber", ""),
        "osm_addr_postcode": tags.get("addr:postcode", ""),
        "osm_shop": tags.get("shop", ""),
        "osm_craft": tags.get("craft", ""),
        "osm_amenity": tags.get("amenity", ""),
        "osm_lat": element.get("lat"),
        "osm_lon": element.get("lon"),
    }


def match_enterprises(enterprises, osm_elements):
    """Match les éléments OSM avec les entreprises par fuzzy matching sur le nom."""
    osm_data = []
    for el in osm_elements:
        info = extract_osm_info(el)
        if info["osm_name"]:
            info["_norm"] = normalize(info["osm_name"])
            osm_data.append(info)

    print(f"  -> {len(osm_data)} resultats OSM avec un nom exploitable")

    # Pre-normaliser les noms d'entreprises
    for ent in enterprises:
        ent["_norm"] = normalize(ent.get("nom", ""))

    matched_count = 0
    enriched = []

    for ent in enterprises:
        ent_norm = ent["_norm"]
        best_score = 0
        best_osm = None

        for osm in osm_data:
            score = fuzzy_score(ent_norm, osm["_norm"])
            if score > best_score:
                best_score = score
                best_osm = osm

        result = {k: v for k, v in ent.items() if k != "_norm"}

        if best_score >= 0.55 and best_osm:
            matched_count += 1
            osm_clean = {k: v for k, v in best_osm.items() if k != "_norm"}
            result["osm_match_score"] = round(best_score, 3)
            result.update(osm_clean)
        else:
            result["osm_match_score"] = 0
            result["osm_id"] = None
            result["osm_name"] = ""
            result["osm_phone"] = ""
            result["osm_website"] = ""
            result["osm_email"] = ""
            result["osm_opening_hours"] = ""

        enriched.append(result)

    print(f"  -> {matched_count} entreprises matchees avec OSM (seuil >= 0.55)")
    return enriched


def main():
    # Charger les entreprises
    print(f"Chargement de {INPUT_FILE}...")
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        enterprises = json.load(f)
    print(f"  -> {len(enterprises)} entreprises chargees")

    # Requete Overpass
    osm_elements = query_overpass()

    # Matching
    print("Matching fuzzy en cours...")
    enriched = match_enterprises(enterprises, osm_elements)

    # Sauvegarde
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(enriched, f, ensure_ascii=False, indent=2)
    print(f"Resultat sauvegarde dans {OUTPUT_FILE}")

    # Stats
    with_data = sum(1 for e in enriched if e.get("osm_match_score", 0) > 0)
    with_phone = sum(1 for e in enriched if e.get("osm_phone"))
    with_web = sum(1 for e in enriched if e.get("osm_website"))
    with_email = sum(1 for e in enriched if e.get("osm_email"))
    with_hours = sum(1 for e in enriched if e.get("osm_opening_hours"))
    print(f"\nStatistiques:")
    print(f"  Entreprises totales : {len(enriched)}")
    print(f"  Matchees OSM        : {with_data}")
    print(f"  Avec telephone      : {with_phone}")
    print(f"  Avec site web       : {with_web}")
    print(f"  Avec email          : {with_email}")
    print(f"  Avec horaires       : {with_hours}")


if __name__ == "__main__":
    main()
