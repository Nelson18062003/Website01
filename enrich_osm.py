#!/usr/bin/env python3
"""
Enrichit les entreprises automobiles de Colomiers, Blagnac et Muret
avec des donnees OpenStreetMap via Overpass API.
"""

import json
import requests
import time
import re
from difflib import SequenceMatcher

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

VILLES = [
    {"nom": "Colomiers", "fichier_api": "api_colomiers.json", "fichier_osm": "osm_colomiers.json"},
    {"nom": "Blagnac",   "fichier_api": "api_blagnac.json",   "fichier_osm": "osm_blagnac.json"},
    {"nom": "Muret",     "fichier_api": "api_muret.json",     "fichier_osm": "osm_muret.json"},
]

BASE_DIR = "/home/user/Website01/"


def query_overpass(ville_nom, max_retries=3):
    """Interroge Overpass API pour une ville donnee, avec retry."""
    query = f"""
[out:json][timeout:90];
area["name"="{ville_nom}"]->.a;
(
  node["shop"="car_repair"](area.a);
  node["shop"="car"](area.a);
  node["shop"="motorcycle"](area.a);
  node["craft"="coachbuilder"](area.a);
);
out body;
"""
    for attempt in range(max_retries):
        try:
            print(f"  Requete Overpass pour {ville_nom} (tentative {attempt+1})...")
            resp = requests.get(OVERPASS_URL, params={"data": query}, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            elements = data.get("elements", [])
            print(f"  -> {len(elements)} resultats OSM trouves")
            return elements
        except (requests.exceptions.HTTPError, requests.exceptions.Timeout) as e:
            print(f"  Erreur: {e}")
            if attempt < max_retries - 1:
                wait = 15 * (attempt + 1)
                print(f"  Nouvelle tentative dans {wait}s...")
                time.sleep(wait)
            else:
                print(f"  Echec apres {max_retries} tentatives, retour liste vide")
                return []


def extract_osm_info(element):
    """Extrait les infos utiles d'un element OSM."""
    tags = element.get("tags", {})
    return {
        "osm_id": element.get("id"),
        "osm_name": tags.get("name", ""),
        "osm_phone": tags.get("phone", tags.get("contact:phone", "")),
        "osm_website": tags.get("website", tags.get("contact:website", "")),
        "osm_email": tags.get("email", tags.get("contact:email", "")),
        "osm_shop": tags.get("shop", tags.get("craft", "")),
        "osm_lat": element.get("lat"),
        "osm_lon": element.get("lon"),
    }


def normalize(name):
    """Normalise un nom pour le matching."""
    name = name.upper()
    # Supprime les formes juridiques courantes
    for term in ["SARL ", "SAS ", "EURL ", "SA ", "SCI ", "AUTO ", "GARAGE ",
                 "CARROSSERIE ", "ETS ", "ETABLISSEMENTS "]:
        name = name.replace(term, "")
    # Supprime ponctuation
    name = re.sub(r"[^A-Z0-9 ]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def match_score(api_name, osm_name):
    """Calcule un score de similarite entre deux noms."""
    if not osm_name:
        return 0
    n1 = normalize(api_name)
    n2 = normalize(osm_name)
    if not n1 or not n2:
        return 0

    # Correspondance exacte apres normalisation
    if n1 == n2:
        return 1.0

    # Un nom contenu dans l'autre
    if n1 in n2 or n2 in n1:
        return 0.85

    # Mots en commun
    words1 = set(n1.split())
    words2 = set(n2.split())
    common = words1 & words2
    if common and len(common) >= 1:
        word_score = len(common) / max(len(words1), len(words2))
        if word_score >= 0.5:
            return 0.7 + word_score * 0.2

    # Similarite de sequence
    return SequenceMatcher(None, n1, n2).ratio()


def process_ville(ville_config):
    """Traite une ville : requete OSM, matching, sauvegarde."""
    ville_nom = ville_config["nom"]
    print(f"\n=== Traitement de {ville_nom} ===")

    # Charger le fichier API
    with open(BASE_DIR + ville_config["fichier_api"], "r", encoding="utf-8") as f:
        api_data = json.load(f)
    print(f"  {len(api_data)} entreprises dans le fichier API")

    # Requete Overpass
    osm_elements = query_overpass(ville_nom)
    osm_infos = [extract_osm_info(e) for e in osm_elements]

    # Matching
    enriched = []
    matched_count = 0

    for entreprise in api_data:
        entry = dict(entreprise)  # copie
        best_score = 0
        best_osm = None

        for osm in osm_infos:
            score = match_score(entreprise["nom"], osm["osm_name"])
            if score > best_score:
                best_score = score
                best_osm = osm

        if best_score >= 0.55 and best_osm:
            entry["osm_match_score"] = round(best_score, 2)
            entry["osm_name"] = best_osm["osm_name"]
            entry["osm_phone"] = best_osm["osm_phone"]
            entry["osm_website"] = best_osm["osm_website"]
            entry["osm_email"] = best_osm["osm_email"]
            entry["osm_lat"] = best_osm["osm_lat"]
            entry["osm_lon"] = best_osm["osm_lon"]
            entry["osm_id"] = best_osm["osm_id"]
            matched_count += 1
        else:
            entry["osm_match_score"] = 0
            entry["osm_name"] = ""
            entry["osm_phone"] = ""
            entry["osm_website"] = ""
            entry["osm_email"] = ""
            entry["osm_lat"] = None
            entry["osm_lon"] = None
            entry["osm_id"] = None

        enriched.append(entry)

    print(f"  {matched_count} entreprises matchees sur {len(api_data)}")

    # Ajouter les elements OSM non-matches
    matched_osm_ids = {e["osm_id"] for e in enriched if e.get("osm_id")}
    unmatched_osm = [osm for osm in osm_infos if osm["osm_id"] not in matched_osm_ids and osm["osm_name"]]
    if unmatched_osm:
        print(f"  {len(unmatched_osm)} elements OSM non-matches (ajoutes en supplement)")
        for osm in unmatched_osm:
            enriched.append({
                "nom": osm["osm_name"],
                "siret": "",
                "siren": "",
                "adresse": "",
                "code_postal": "",
                "ville": ville_nom.upper(),
                "code_naf": "",
                "libelle_activite": "",
                "categorie": osm["osm_shop"],
                "date_creation": "",
                "statut": "",
                "effectif": "",
                "zone_recherche": ville_nom,
                "osm_match_score": 0,
                "osm_name": osm["osm_name"],
                "osm_phone": osm["osm_phone"],
                "osm_website": osm["osm_website"],
                "osm_email": osm["osm_email"],
                "osm_lat": osm["osm_lat"],
                "osm_lon": osm["osm_lon"],
                "osm_id": osm["osm_id"],
                "source": "osm_only"
            })

    # Sauvegarde
    output_path = BASE_DIR + ville_config["fichier_osm"]
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(enriched, f, ensure_ascii=False, indent=2)
    print(f"  Sauvegarde dans {output_path} ({len(enriched)} entrees)")


def main():
    print("Enrichissement des entreprises automobiles avec OpenStreetMap")
    for i, ville in enumerate(VILLES):
        process_ville(ville)
        if i < len(VILLES) - 1:
            print("  Pause de 5s entre les requetes...")
            time.sleep(5)
    print("\nTermine !")


if __name__ == "__main__":
    main()
