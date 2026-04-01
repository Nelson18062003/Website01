#!/usr/bin/env python3
"""Scraper: FINESS (Fichier National des Établissements Sanitaires et Sociaux)"""
import csv
import io
import requests
from scraper_utils import (
    ZONES, setup_logging, save_json, format_phone, format_postal_code, safe_request
)

logger = setup_logging("finess")

# FINESS CSV URLs from data.gouv.fr
FINESS_GEOLOC_URL = "https://static.data.gouv.fr/resources/finess-extraction-du-fichier-des-etablissements/20260312-094547/etalab-cs1100507-stock-20260311-0343.csv"
FINESS_STANDARD_URL = "https://static.data.gouv.fr/resources/finess-extraction-du-fichier-des-etablissements/20260312-094813/etalab-cs1100502-stock-20260311-0344.csv"

# Relevant FINESS category codes for health structures
RELEVANT_CATEGORIES = {
    "101", "106", "109", "114", "122", "128", "129", "131", "141", "146",
    "156", "195", "197", "198", "202", "207", "209", "213", "214", "219",
    "221", "223", "224", "228", "230", "231", "236", "237", "238", "241",
    "246", "249", "252", "253", "255", "262", "265", "286", "289", "292",
    "295", "344", "354", "355", "362", "365", "370", "377", "378", "379",
    "381", "382", "390", "395", "396", "402", "411", "412", "413", "414",
    "415", "418", "422", "427", "430", "432", "433", "437", "440", "441",
    "442", "443", "444", "445", "446", "448", "449", "453", "460", "462",
    "464", "500", "501", "502", "603", "604", "606", "607", "608", "609",
    "610", "611", "614", "620", "623", "624", "627", "628", "629", "630",
    "631", "632", "633", "634", "636", "637", "638", "639", "640", "641",
    "700", "701", "710", "720", "730", "731",
}

# Category code to human-readable category mapping
FINESS_CAT_MAP = {
    # Hospitals
    "101": "Hôpital", "106": "Hôpital", "109": "Hôpital",
    "114": "Hôpital", "122": "Hôpital", "128": "Hôpital",
    "129": "Hôpital", "131": "Hôpital", "141": "Hôpital",
    "146": "Clinique privée", "156": "Clinique privée",
    "195": "Clinique privée", "197": "Clinique privée",
    "198": "Clinique privée",
    # Labs
    "202": "Laboratoire d'analyses médicales",
    "207": "Laboratoire d'analyses médicales",
    "209": "Laboratoire d'analyses médicales",
    # Pharmacies
    "213": "Pharmacie", "214": "Pharmacie",
    # Health centers
    "219": "Centre de santé", "221": "Centre de santé",
    "223": "Centre de santé", "224": "Centre de santé",
    "228": "Centre de santé", "230": "Centre de santé",
    "231": "Centre de santé",
    # Radiology / Imaging
    "236": "Centre de radiologie / Imagerie médicale",
    "237": "Centre de radiologie / Imagerie médicale",
    "238": "Centre de radiologie / Imagerie médicale",
    # Dialysis
    "241": "Centre de dialyse", "246": "Centre de dialyse",
    "249": "Centre de dialyse", "252": "Centre de dialyse",
    "253": "Centre de dialyse", "255": "Centre de dialyse",
    # Other health
    "262": "Centre de santé", "265": "Maison de santé pluridisciplinaire",
    "286": "Autre structure de santé", "289": "Autre structure de santé",
    "292": "Centre de vaccination",
    "295": "Centre de médecine du travail",
    # Medico-social
    "344": "Autre structure de santé", "354": "Autre structure de santé",
    "355": "Autre structure de santé", "362": "Autre structure de santé",
    "365": "Autre structure de santé", "370": "Autre structure de santé",
    "377": "Autre structure de santé", "378": "Autre structure de santé",
    "379": "Autre structure de santé",
    # Default catch-all in processing below
}

TARGET_DEPARTMENTS = {"75", "13", "59"}


def download_finess_csv(url):
    """Download and parse FINESS CSV."""
    logger.info(f"Downloading FINESS CSV from {url[:80]}...")
    try:
        r = requests.get(url, timeout=120, stream=True)
        if r.status_code != 200:
            logger.error(f"FINESS download failed: HTTP {r.status_code}")
            return []

        content = r.content.decode('utf-8', errors='replace')
        logger.info(f"Downloaded {len(content)} bytes")

        reader = csv.DictReader(io.StringIO(content), delimiter=';')
        rows = list(reader)
        logger.info(f"Parsed {len(rows)} rows from FINESS CSV")
        return rows
    except Exception as e:
        logger.error(f"Error downloading FINESS: {e}")
        return []


def process_finess_rows(rows):
    """Process FINESS rows and filter for our target zones."""
    results = []

    for row in rows:
        dept = str(row.get("departement", "") or row.get("dep", "") or "").strip()

        # Try to extract department from postal code if not directly available
        cp = str(row.get("codepostal", "") or row.get("code_postal", "") or row.get("cp", "") or "").strip()
        if not dept and cp and len(cp) >= 2:
            dept = cp[:2]

        if dept not in TARGET_DEPARTMENTS:
            continue

        # Get category
        cat_code = str(row.get("categetab", "") or row.get("cat", "") or row.get("categorie", "") or "").strip()

        # Build address
        addr_parts = []
        for field in ["numvoie", "typvoie", "voie", "lieuditbp", "ligneacheminement"]:
            val = row.get(field, "")
            if val and str(val).strip():
                addr_parts.append(str(val).strip())

        # Get raison sociale
        rs = row.get("rs", "") or row.get("rslongue", "") or row.get("raison_sociale", "") or ""

        record = {
            "raison_sociale": str(rs).strip(),
            "categorie": FINESS_CAT_MAP.get(cat_code, "Structure de santé"),
            "code_naf": "",
            "libelle_naf": "",
            "telephone": format_phone(row.get("telephone", "") or row.get("tel", "")),
            "adresse": " ".join(addr_parts).strip() if addr_parts else "",
            "code_postal": format_postal_code(cp),
            "ville": str(row.get("libcommune", "") or row.get("commune", "") or row.get("ville", "") or "").strip(),
            "siret": "",
            "siren": "",
            "site_web": "",
            "email": "",
            "effectif": "",
            "date_creation": "",
            "finess": str(row.get("nofinesset", "") or row.get("finess", "") or "").strip(),
            "source": "FINESS",
        }

        if record["raison_sociale"]:
            results.append(record)

    return results


def main():
    # Try geolocated version first, then standard
    rows = download_finess_csv(FINESS_GEOLOC_URL)
    if not rows:
        logger.info("Trying standard FINESS CSV...")
        rows = download_finess_csv(FINESS_STANDARD_URL)

    if not rows:
        logger.error("Could not download any FINESS data")
        save_json([], "finess.json")
        return []

    # Log available columns
    if rows:
        logger.info(f"FINESS columns: {list(rows[0].keys())[:20]}")

    results = process_finess_rows(rows)

    # Stats
    by_dept = {}
    for r in results:
        cp = r["code_postal"]
        dept = cp[:2] if cp else "??"
        by_dept[dept] = by_dept.get(dept, 0) + 1

    logger.info(f"FINESS: {len(results)} structures in target zones")
    for dept, count in sorted(by_dept.items()):
        logger.info(f"  Dept {dept}: {count}")

    save_json(results, "finess.json")
    logger.info("Saved to data/finess.json")
    return results


if __name__ == "__main__":
    main()
