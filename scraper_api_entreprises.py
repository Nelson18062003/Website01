#!/usr/bin/env python3
"""Scraper: API Recherche Entreprises (recherche-entreprises.api.gouv.fr)"""
import time
import sys
from scraper_utils import (
    NAF_CODES, ZONES, setup_logging, save_json, categorize_by_naf_and_name,
    format_postal_code, safe_request
)

API_URL = "https://recherche-entreprises.api.gouv.fr/search"
PER_PAGE = 25
logger = setup_logging("api_entreprises")


def fetch_naf_postal(naf_code, postal_code):
    """Fetch all results for a NAF code + postal code combination."""
    results = []
    page = 1
    while True:
        params = {
            "activite_principale": naf_code,
            "code_postal": postal_code,
            "etat_administratif": "A",  # Active only
            "page": page,
            "per_page": PER_PAGE,
        }
        r = safe_request(API_URL, params=params, timeout=30, retries=3, delay=1.0)
        if r is None or r.status_code != 200:
            logger.warning(f"Failed: NAF={naf_code} CP={postal_code} page={page}")
            break

        data = r.json()
        total = data.get("total_results", 0)
        entreprises = data.get("results", [])

        if not entreprises:
            break

        for ent in entreprises:
            siege = ent.get("siege", {})
            # Get the matching establishment (siege or matching etablissement)
            record = {
                "raison_sociale": ent.get("nom_complet", "") or ent.get("nom_raison_sociale", ""),
                "code_naf": naf_code,
                "libelle_naf": NAF_CODES.get(naf_code, ""),
                "siren": ent.get("siren", ""),
                "siret": siege.get("siret", ""),
                "adresse": " ".join(filter(None, [
                    siege.get("numero_voie", ""),
                    siege.get("type_voie", ""),
                    siege.get("libelle_voie", ""),
                    siege.get("complement_adresse", ""),
                ])).strip(),
                "code_postal": format_postal_code(siege.get("code_postal", postal_code)),
                "ville": siege.get("libelle_commune", ""),
                "effectif": siege.get("tranche_effectif_salarie", "") or ent.get("tranche_effectif_salarie", ""),
                "date_creation": ent.get("date_creation", ""),
                "telephone": "",
                "email": "",
                "site_web": "",
                "source": "API Recherche Entreprises",
            }

            # Also check matching_etablissements for the specific postal code
            matching = ent.get("matching_etablissements", [])
            for etab in matching:
                etab_cp = format_postal_code(etab.get("code_postal", ""))
                if etab_cp == format_postal_code(postal_code):
                    record["siret"] = etab.get("siret", record["siret"])
                    record["adresse"] = " ".join(filter(None, [
                        etab.get("numero_voie", ""),
                        etab.get("type_voie", ""),
                        etab.get("libelle_voie", ""),
                        etab.get("complement_adresse", ""),
                    ])).strip() or record["adresse"]
                    record["code_postal"] = etab_cp or record["code_postal"]
                    record["ville"] = etab.get("libelle_commune", "") or record["ville"]
                    record["effectif"] = etab.get("tranche_effectif_salarie", "") or record["effectif"]
                    break

            record["categorie"] = categorize_by_naf_and_name(naf_code, record["raison_sociale"])
            results.append(record)

        # Check if more pages
        if page * PER_PAGE >= total or page * PER_PAGE >= 10000:
            break
        page += 1
        time.sleep(0.3)  # Light rate limiting

    return results


def main():
    all_results = []
    total_combos = sum(len(zone["postal_codes"]) for zone in ZONES.values()) * len(NAF_CODES)
    done = 0

    for zone_name, zone_info in ZONES.items():
        zone_count = 0
        for naf_code in NAF_CODES:
            for postal_code in zone_info["postal_codes"]:
                results = fetch_naf_postal(naf_code, postal_code)
                all_results.extend(results)
                zone_count += len(results)
                done += 1
                if results:
                    logger.info(f"[{done}/{total_combos}] {zone_name} NAF={naf_code} CP={postal_code}: {len(results)} results")
                time.sleep(0.2)

        logger.info(f"=== {zone_name.upper()}: {zone_count} total results ===")

    logger.info(f"API Recherche Entreprises: {len(all_results)} total raw results")
    save_json(all_results, "api_entreprises.json")
    logger.info("Saved to data/api_entreprises.json")
    return all_results


if __name__ == "__main__":
    main()
