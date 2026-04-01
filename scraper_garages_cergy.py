#!/usr/bin/env python3
"""
Scraper complet — Garages, Concessions, Carrossiers, Motos à Cergy (95)
Sources: API Recherche Entreprises + Pages Jaunes (curl_cffi) + OpenStreetMap
"""
import json
import os
import random
import re
import time

import pandas as pd
import requests
from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests

from scraper_utils import (
    DATA_DIR, setup_logging, save_json, normalize_name,
    format_phone, format_postal_code, safe_request
)

logger = setup_logging("garages_cergy")

# ── Configuration ──────────────────────────────────────────────────────────

AUTO_NAF_CODES = {
    "45.11Z": "Commerce de voitures et de véhicules automobiles légers",
    "45.19Z": "Commerce d'autres véhicules automobiles",
    "45.20A": "Entretien et réparation de véhicules automobiles légers",
    "45.20B": "Entretien et réparation d'autres véhicules automobiles",
    "45.31Z": "Commerce de gros d'équipements automobiles",
    "45.32Z": "Commerce de détail d'équipements automobiles",
    "45.40Z": "Commerce de motocycles",
}

POSTAL_CODES = ["95000", "95800"]

PJ_CATEGORIES = [
    ("garage-automobile",       "Garage automobile",       "45.20A"),
    ("concession-automobile",   "Concession automobile",   "45.11Z"),
    ("carrosserie-automobile",  "Carrosserie",             "45.20A"),
    ("garage-moto",             "Garage moto",             "45.40Z"),
    ("concession-moto",         "Concession moto",         "45.40Z"),
    ("reparation-automobile",   "Garage automobile",       "45.20A"),
    ("carrossier",              "Carrosserie",             "45.20A"),
    ("peinture-automobile",     "Carrosserie / Peinture",  "45.20A"),
]

PJ_LOCATION = "cergy-95"
PJ_MAX_PAGES = 10

# Cergy bounding box (south, west, north, east) — generous to catch edges
CERGY_BBOX = (49.01, 1.98, 49.08, 2.10)

COLUMNS = [
    "raison_sociale", "categorie", "code_naf", "libelle_naf",
    "telephone", "adresse", "code_postal", "departement", "ville",
    "siret", "siren", "site_web", "email",
    "effectif", "date_creation", "source",
]

OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "garages-cergy.xlsx")

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
API_URL = "https://recherche-entreprises.api.gouv.fr/search"


# ── Catégorisation auto ────────────────────────────────────────────────────

def categorize_auto(naf_code, name):
    """Assign precise automotive category from NAF code + business name."""
    n = (name or "").upper()

    if naf_code in ("45.20A", "4520A"):
        if "CARROSSERIE" in n or "CARROSSIER" in n or "PEINTURE" in n:
            return "Carrosserie"
        if "MOTO" in n or "SCOOTER" in n:
            return "Garage moto"
        return "Garage automobile"

    if naf_code in ("45.20B", "4520B"):
        if "POIDS LOURD" in n or "CAMION" in n:
            return "Garage poids lourds"
        return "Garage automobile"

    if naf_code in ("45.11Z", "4511Z"):
        if any(w in n for w in ["MOTO", "HARLEY", "YAMAHA", "KAWASAKI", "DUCATI", "TRIUMPH", "BMW MOTO"]):
            return "Concession moto"
        return "Concession automobile"

    if naf_code in ("45.19Z", "4519Z"):
        return "Concession automobile"

    if naf_code in ("45.40Z", "4540Z"):
        return "Concession moto"

    if naf_code in ("45.31Z", "4531Z"):
        return "Équipements automobiles (gros)"

    if naf_code in ("45.32Z", "4532Z"):
        return "Équipements automobiles (détail)"

    # Fallback by keywords
    if "CARROSSERIE" in n or "CARROSSIER" in n:
        return "Carrosserie"
    if "CONCESSION" in n:
        return "Concession automobile"
    if "MOTO" in n or "SCOOTER" in n:
        return "Concession moto"
    return "Garage automobile"


# ── Source 1: API Recherche Entreprises ─────────────────────────────────────

def scrape_api_entreprises():
    """Fetch all automotive businesses in Cergy from the government API."""
    all_records = []

    for naf_code, naf_label in AUTO_NAF_CODES.items():
        for cp in POSTAL_CODES:
            page = 1
            while True:
                params = {
                    "activite_principale": naf_code,
                    "code_postal": cp,
                    "etat_administratif": "A",
                    "page": page,
                    "per_page": 25,
                }
                r = safe_request(API_URL, params=params, timeout=30, retries=3, delay=1.0)
                if r is None or r.status_code != 200:
                    break

                data = r.json()
                entreprises = data.get("results", [])
                if not entreprises:
                    break

                for ent in entreprises:
                    siege = ent.get("siege", {})
                    record = {
                        "raison_sociale": ent.get("nom_complet", "") or ent.get("nom_raison_sociale", ""),
                        "code_naf": naf_code,
                        "libelle_naf": naf_label,
                        "siren": ent.get("siren", ""),
                        "siret": siege.get("siret", ""),
                        "adresse": " ".join(filter(None, [
                            siege.get("numero_voie", ""),
                            siege.get("type_voie", ""),
                            siege.get("libelle_voie", ""),
                            siege.get("complement_adresse", ""),
                        ])).strip(),
                        "code_postal": format_postal_code(siege.get("code_postal", cp)),
                        "departement": "95",
                        "ville": siege.get("libelle_commune", ""),
                        "effectif": siege.get("tranche_effectif_salarie", "") or ent.get("tranche_effectif_salarie", ""),
                        "date_creation": ent.get("date_creation", ""),
                        "telephone": "",
                        "email": "",
                        "site_web": "",
                        "source": "API Recherche Entreprises",
                    }

                    # Use matching_etablissements for the correct local address
                    for etab in ent.get("matching_etablissements", []):
                        etab_cp = format_postal_code(etab.get("code_postal", ""))
                        if etab_cp == format_postal_code(cp):
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

                    record["categorie"] = categorize_auto(naf_code, record["raison_sociale"])
                    all_records.append(record)

                total = data.get("total_results", 0)
                if page * 25 >= total:
                    break
                page += 1
                time.sleep(0.3)

            logger.info(f"API: {naf_code} / {cp} => {len([r for r in all_records if r['code_naf'] == naf_code and r['code_postal'] == format_postal_code(cp)])} records")

    logger.info(f"API Entreprises total: {len(all_records)} records")
    return all_records


# ── Source 2: Pages Jaunes ─────────────────────────────────────────────────

def parse_pj_listing(article):
    """Parse a single listing from a PJ result page."""
    record = {c: "" for c in COLUMNS}
    record["source"] = "Pages Jaunes"
    record["departement"] = "95"

    # Business name
    name_el = article.find(attrs={"data-denomination": True})
    if name_el:
        record["raison_sociale"] = name_el.get("data-denomination", "").strip()
    if not record["raison_sociale"]:
        for sel in [".bi-denomination a", "h3 a", ".bi-header-title a"]:
            el = article.select_one(sel)
            if el:
                record["raison_sociale"] = el.get_text(strip=True)
                break
    if not record["raison_sociale"]:
        h3 = article.find("h3")
        if h3:
            record["raison_sociale"] = h3.get_text(strip=True)

    if not record["raison_sociale"]:
        return None

    record["raison_sociale"] = re.sub(r'\s+', ' ', record["raison_sociale"]).strip()

    # Phone — fantomas div (PRIMARY method for PJ)
    phone = None
    fantomas = article.select_one("[id*=fantomas]")
    if fantomas:
        text = fantomas.get_text(" ", strip=True)
        m = re.search(r'(\d{2}[\s\.]*\d{2}[\s\.]*\d{2}[\s\.]*\d{2}[\s\.]*\d{2})', text)
        if m:
            phone = m.group(1)
    # Fallback: data-href tel:
    if not phone:
        for el in article.find_all(attrs={"data-href": True}):
            if "tel:" in el.get("data-href", ""):
                phone = el["data-href"].replace("tel:", "").strip()
                break
    # Fallback: a href tel:
    if not phone:
        for el in article.find_all("a", href=True):
            if el["href"].startswith("tel:"):
                phone = el["href"].replace("tel:", "").strip()
                break
    if phone:
        record["telephone"] = format_phone(phone)

    # Address
    addr_el = article.select_one(".bi-address, .address, .bi-adresse")
    if addr_el:
        addr_text = addr_el.get_text(strip=True)
        cp_match = re.search(r'(\d{5})\s*(.+?)(?:Voir le plan)?$', addr_text)
        if cp_match:
            record["code_postal"] = format_postal_code(cp_match.group(1))
            record["ville"] = cp_match.group(2).strip()
            record["adresse"] = addr_text[:cp_match.start()].strip().rstrip(',')
        else:
            record["adresse"] = addr_text

    # Website link
    for a in article.find_all("a", href=True):
        href = a.get("href", "")
        if "site-internet" in href or (a.get("class") and any("website" in c for c in a.get("class", []))):
            record["site_web"] = href
            break

    # SIRET (sometimes visible)
    siret_match = re.search(r'(\d{14})', str(article))
    if siret_match:
        record["siret"] = siret_match.group(1)
        record["siren"] = siret_match.group(1)[:9]

    return record


def scrape_pages_jaunes():
    """Scrape all automotive categories from Pages Jaunes for Cergy."""
    all_records = []
    seen = set()

    for query, category, naf_code in PJ_CATEGORIES:
        logger.info(f"PJ: {query} in {PJ_LOCATION}...")
        category_count = 0

        for page in range(1, PJ_MAX_PAGES + 1):
            url = f"https://www.pagesjaunes.fr/annuaire/chercherlespros?quoiqui={query}&ou={PJ_LOCATION}&page={page}"

            try:
                r = cffi_requests.get(url, impersonate="chrome116", timeout=30)

                if r.status_code == 403:
                    logger.warning(f"PJ 403 for {query}/{PJ_LOCATION} page {page}")
                    break
                if r.status_code != 200:
                    break

                soup = BeautifulSoup(r.text, 'lxml')

                if "challenge" in r.text.lower() and "enable javascript" in r.text.lower():
                    logger.warning(f"PJ Cloudflare challenge for {query}")
                    break

                articles = soup.select("li.bi")
                if not articles:
                    break

                new_count = 0
                for article in articles:
                    rec = parse_pj_listing(article)
                    if not rec:
                        continue

                    rec["categorie"] = rec["categorie"] or category
                    rec["code_naf"] = rec["code_naf"] or naf_code
                    rec["code_postal"] = rec["code_postal"] or "95000"
                    rec["ville"] = rec["ville"] or "CERGY"

                    dedup_key = rec["raison_sociale"].upper()[:30] + "_" + rec["code_postal"]
                    if dedup_key not in seen:
                        seen.add(dedup_key)
                        all_records.append(rec)
                        new_count += 1

                category_count += new_count
                if new_count > 0:
                    logger.info(f"  PJ: {query} page {page}: {new_count} new ({len(articles)} raw)")

                has_next = len(articles) >= 15 or bool(soup.select(".pagination-next a, a.next"))
                if not has_next:
                    break

                time.sleep(random.uniform(2.5, 5.0))

            except Exception as e:
                logger.error(f"PJ error: {query} page {page}: {e}")
                break

        if category_count > 0:
            logger.info(f"  => {category_count} records for {query}")
        time.sleep(random.uniform(3, 6))

    logger.info(f"Pages Jaunes total: {len(all_records)} records")
    return all_records


# ── Source 3: OpenStreetMap Overpass ────────────────────────────────────────

OSM_TYPES = {
    "car_repair": "Garage automobile",
    "car": "Concession automobile",
    "motorcycle": "Concession moto",
    "car_body_repair": "Carrosserie",
    "car_rental": "Location automobile",
    "car_parts": "Équipements automobiles (détail)",
}

def scrape_osm():
    """Query Overpass API for automotive POIs in Cergy area."""
    south, west, north, east = CERGY_BBOX

    shop_filters = "".join(
        f'node["shop"="{t}"]({south},{west},{north},{east});'
        f'way["shop"="{t}"]({south},{west},{north},{east});'
        for t in ["car_repair", "car", "motorcycle", "car_parts"]
    )
    craft_filters = (
        f'node["craft"="car_body_repair"]({south},{west},{north},{east});'
        f'way["craft"="car_body_repair"]({south},{west},{north},{east});'
    )
    amenity_filters = (
        f'node["amenity"="car_rental"]({south},{west},{north},{east});'
        f'way["amenity"="car_rental"]({south},{west},{north},{east});'
    )

    query = f"""
    [out:json][timeout:60];
    ({shop_filters}{craft_filters}{amenity_filters});
    out center body;
    """

    try:
        r = requests.post(OVERPASS_URL, data={"data": query}, timeout=90)
        if r.status_code != 200:
            logger.warning(f"OSM Overpass HTTP {r.status_code}")
            return []

        elements = r.json().get("elements", [])
        records = []

        for el in elements:
            tags = el.get("tags", {})
            name = tags.get("name", "")
            if not name:
                continue

            # Determine category
            cat = "Garage automobile"
            for tag_key in ["shop", "craft", "amenity"]:
                val = tags.get(tag_key, "")
                if val in OSM_TYPES:
                    cat = OSM_TYPES[val]
                    break

            records.append({
                "raison_sociale": name,
                "categorie": cat,
                "code_naf": "",
                "libelle_naf": "",
                "telephone": format_phone(tags.get("phone", "") or tags.get("contact:phone", "")),
                "adresse": " ".join(filter(None, [
                    tags.get("addr:housenumber", ""),
                    tags.get("addr:street", ""),
                ])).strip(),
                "code_postal": format_postal_code(tags.get("addr:postcode", "95000")),
                "departement": "95",
                "ville": tags.get("addr:city", "Cergy").upper(),
                "siret": "",
                "siren": "",
                "site_web": tags.get("website", "") or tags.get("contact:website", ""),
                "email": tags.get("email", "") or tags.get("contact:email", ""),
                "effectif": "",
                "date_creation": "",
                "source": "OpenStreetMap",
            })

        logger.info(f"OSM Overpass: {len(records)} automotive POIs")
        return records

    except Exception as e:
        logger.error(f"OSM error: {e}")
        return []


# ── Merge & Deduplicate ────────────────────────────────────────────────────

def merge_and_deduplicate(api_records, pj_records, osm_records):
    """Merge all sources and deduplicate."""
    all_records = api_records + pj_records + osm_records
    if not all_records:
        return pd.DataFrame(columns=COLUMNS)

    df = pd.DataFrame(all_records)
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df = df.fillna("")
    for col in df.columns:
        df[col] = df[col].astype(str)

    # Clean SIRET
    df["siret"] = df["siret"].apply(lambda x: re.sub(r'[^\d]', '', x))
    df["siret"] = df["siret"].apply(lambda x: x if len(x) == 14 else "")
    df["siren"] = df.apply(lambda r: r["siret"][:9] if len(r["siret"]) == 14 and not r["siren"] else r["siren"], axis=1)

    # Normalize for dedup
    df["_norm"] = df["raison_sociale"].apply(normalize_name)
    df["_cp"] = df["code_postal"].apply(format_postal_code)

    # Score by completeness
    def score(row):
        s = 0
        if row["siret"]: s += 5
        if row["telephone"]: s += 3
        if row["adresse"]: s += 2
        if row["email"]: s += 2
        if row["site_web"]: s += 1
        if row["code_naf"]: s += 2
        if row["effectif"]: s += 1
        return s

    df["_score"] = df.apply(score, axis=1)
    df = df.sort_values("_score", ascending=False)

    # Deduplicate
    seen_sirets = {}
    seen_names = {}
    keep_indices = []

    for idx, row in df.iterrows():
        siret = row["siret"]
        norm_key = f"{row['_norm']}_{row['_cp']}"

        if siret and siret in seen_sirets:
            existing = seen_sirets[siret]
            for col in COLUMNS:
                if col == "source":
                    if row["source"] and row["source"] not in df.at[existing, "source"]:
                        df.at[existing, "source"] = f"{df.at[existing, 'source']}; {row['source']}"
                elif not df.at[existing, col] and row[col]:
                    df.at[existing, col] = row[col]
            continue

        if norm_key and norm_key in seen_names and not siret:
            existing = seen_names[norm_key]
            for col in COLUMNS:
                if col == "source":
                    if row["source"] and row["source"] not in df.at[existing, "source"]:
                        df.at[existing, "source"] = f"{df.at[existing, 'source']}; {row['source']}"
                elif not df.at[existing, col] and row[col]:
                    df.at[existing, col] = row[col]
            continue

        keep_indices.append(idx)
        if siret:
            seen_sirets[siret] = idx
        if norm_key:
            seen_names[norm_key] = idx

    df = df.loc[keep_indices].drop(columns=["_norm", "_cp", "_score"], errors='ignore')
    logger.info(f"After dedup: {len(df)} unique records")
    return df


# ── SIRET Enrichment ───────────────────────────────────────────────────────

def enrich_missing_sirets(df, max_enrichments=150):
    """Enrich missing SIRETs via API Recherche Entreprises."""
    missing = df[df["siret"] == ""]
    if len(missing) == 0:
        return df

    logger.info(f"Enriching SIRETs for {min(len(missing), max_enrichments)} records...")
    enriched = 0

    for idx, row in missing.head(max_enrichments).iterrows():
        name = row["raison_sociale"]
        cp = row["code_postal"]
        if not name or not cp:
            continue

        try:
            r = requests.get(API_URL, params={
                "q": name, "code_postal": cp,
                "etat_administratif": "A", "page": 1, "per_page": 1,
            }, timeout=15)
            if r.status_code == 200:
                results = r.json().get("results", [])
                if results:
                    ent = results[0]
                    siege = ent.get("siege", {})
                    siret = re.sub(r'[^\d]', '', siege.get("siret", ""))
                    if len(siret) == 14:
                        df.at[idx, "siret"] = siret
                        df.at[idx, "siren"] = siret[:9]
                        if not df.at[idx, "code_naf"]:
                            df.at[idx, "code_naf"] = siege.get("activite_principale", "")
                        if not df.at[idx, "effectif"]:
                            df.at[idx, "effectif"] = siege.get("tranche_effectif_salarie", "") or ent.get("tranche_effectif_salarie", "")
                        if not df.at[idx, "date_creation"]:
                            df.at[idx, "date_creation"] = ent.get("date_creation", "")
                        enriched += 1
            time.sleep(0.5)
        except Exception:
            continue

    logger.info(f"SIRET enrichment: {enriched} records enriched")
    return df


# ── Cleanup ────────────────────────────────────────────────────────────────

def cleanup(df):
    """Clean and standardize the dataframe."""
    df["telephone"] = df["telephone"].apply(format_phone)
    df["code_postal"] = df["code_postal"].apply(format_postal_code)

    # Fix NAF format
    def fix_naf(naf):
        naf = str(naf).strip()
        if len(naf) == 5 and naf[2] != '.':
            return naf[:2] + '.' + naf[2:]
        return naf

    df["code_naf"] = df["code_naf"].apply(fix_naf)

    # Fill libelle_naf
    for idx, row in df.iterrows():
        if not row["libelle_naf"] and row["code_naf"] in AUTO_NAF_CODES:
            df.at[idx, "libelle_naf"] = AUTO_NAF_CODES[row["code_naf"]]

    # Re-categorize if needed
    for idx, row in df.iterrows():
        if not row["categorie"]:
            df.at[idx, "categorie"] = categorize_auto(row["code_naf"], row["raison_sociale"])

    df["ville"] = df["ville"].str.upper()
    df = df[df["raison_sociale"].str.strip() != ""]
    for col in df.columns:
        df[col] = df[col].replace('nan', '')
    df = df[[c for c in COLUMNS if c in df.columns]]

    return df


# ── Export XLSX ────────────────────────────────────────────────────────────

def export_xlsx(df):
    """Export to formatted XLSX with xlsxwriter."""
    logger.info(f"Exporting {len(df)} records to {OUTPUT_FILE}")

    df_all = df.sort_values(["categorie", "raison_sociale"])
    df_phone = df[df["telephone"] != ""].sort_values(["categorie", "raison_sociale"])

    with pd.ExcelWriter(OUTPUT_FILE, engine='xlsxwriter') as writer:
        wb = writer.book
        hdr = wb.add_format({
            'bold': True, 'font_color': 'white', 'bg_color': '#2E75B6',
            'text_wrap': True, 'align': 'center', 'valign': 'vcenter',
            'border': 1, 'font_size': 11,
        })
        section_fmt = wb.add_format({'bold': True, 'font_size': 12, 'font_color': '#2E75B6'})

        for sheet_name, sheet_df in [
            ("Tous les établissements", df_all),
            ("Avec téléphone", df_phone),
        ]:
            sheet_df.to_excel(writer, sheet_name=sheet_name, index=False)
            ws = writer.sheets[sheet_name]
            for ci, cn in enumerate(sheet_df.columns):
                ws.write(0, ci, cn, hdr)
            for ci, cn in enumerate(sheet_df.columns):
                max_len = max(len(cn), *(min(len(str(v)), 50) for v in sheet_df.iloc[:100, ci]) if len(sheet_df) > 0 else [10])
                ws.set_column(ci, ci, max(max_len + 3, 12))
            if len(sheet_df) > 0:
                ws.autofilter(0, 0, len(sheet_df), len(sheet_df.columns) - 1)
            ws.freeze_panes(1, 0)

        # Statistics sheet
        stats = build_statistics(df_all, df_phone)
        stats.to_excel(writer, sheet_name="Statistiques", index=False)
        ws = writer.sheets["Statistiques"]
        for ci, cn in enumerate(stats.columns):
            ws.write(0, ci, cn, hdr)
        ws.set_column(0, 0, 55)
        ws.set_column(1, 1, 20)
        for ri, val in enumerate(stats["Statistique"]):
            if isinstance(val, str) and val.isupper() and val:
                ws.write(ri + 1, 0, val, section_fmt)
        ws.freeze_panes(1, 0)

    logger.info(f"Excel saved: {OUTPUT_FILE}")


def build_statistics(df_all, df_phone):
    """Build statistics DataFrame."""
    rows = []
    total = len(df_all)
    t = max(total, 1)

    rows.append({"Statistique": "RÉSUMÉ GÉNÉRAL", "Valeur": ""})
    rows.append({"Statistique": "Total établissements", "Valeur": total})
    rows.append({"Statistique": "Avec téléphone", "Valeur": len(df_phone)})
    rows.append({"Statistique": "", "Valeur": ""})

    rows.append({"Statistique": "RÉPARTITION PAR CATÉGORIE", "Valeur": ""})
    for cat, count in df_all["categorie"].value_counts().items():
        if cat:
            rows.append({"Statistique": f"  {cat}", "Valeur": count})
    rows.append({"Statistique": "", "Valeur": ""})

    rows.append({"Statistique": "RÉPARTITION PAR CODE NAF", "Valeur": ""})
    for naf, count in df_all["code_naf"].value_counts().items():
        if naf:
            label = AUTO_NAF_CODES.get(naf, "")
            rows.append({"Statistique": f"  {naf} — {label}", "Valeur": count})
    rows.append({"Statistique": "", "Valeur": ""})

    rows.append({"Statistique": "RÉPARTITION PAR CODE POSTAL", "Valeur": ""})
    for cp, count in df_all["code_postal"].value_counts().items():
        if cp:
            rows.append({"Statistique": f"  {cp}", "Valeur": count})
    rows.append({"Statistique": "", "Valeur": ""})

    rows.append({"Statistique": "TAUX DE COMPLÉTUDE", "Valeur": ""})
    rows.append({"Statistique": "  SIRET", "Valeur": f"{len(df_all[df_all['siret'] != '']) / t * 100:.1f}%"})
    rows.append({"Statistique": "  Téléphone", "Valeur": f"{len(df_all[df_all['telephone'] != '']) / t * 100:.1f}%"})
    rows.append({"Statistique": "  Email", "Valeur": f"{len(df_all[df_all['email'] != '']) / t * 100:.1f}%"})
    rows.append({"Statistique": "  Site web", "Valeur": f"{len(df_all[df_all['site_web'] != '']) / t * 100:.1f}%"})
    rows.append({"Statistique": "  Adresse", "Valeur": f"{len(df_all[df_all['adresse'] != '']) / t * 100:.1f}%"})
    rows.append({"Statistique": "", "Valeur": ""})

    rows.append({"Statistique": "SOURCES UTILISÉES", "Valeur": ""})
    src_counts = {}
    for src in df_all["source"]:
        primary = str(src).split(";")[0].strip()
        src_counts[primary] = src_counts.get(primary, 0) + 1
    for src, count in sorted(src_counts.items(), key=lambda x: -x[1]):
        if src:
            rows.append({"Statistique": f"  {src}", "Valeur": count})

    return pd.DataFrame(rows)


# ── Summary ────────────────────────────────────────────────────────────────

def print_summary(df):
    """Print terminal summary."""
    total = len(df)
    t = max(total, 1)

    print("\n" + "=" * 60)
    print("  GARAGES / CONCESSIONS / CARROSSIERS — CERGY (95)")
    print("=" * 60)
    print(f"\n  Total : {total}")
    print(f"  Avec téléphone : {len(df[df['telephone'] != ''])}")
    print(f"  Avec SIRET : {len(df[df['siret'] != ''])}")

    print("\n  Par catégorie :")
    for cat, count in df["categorie"].value_counts().items():
        if cat:
            print(f"    {cat:45s} : {count:>4}")

    print("\n  Par code NAF :")
    for naf, count in df["code_naf"].value_counts().head(10).items():
        if naf:
            label = AUTO_NAF_CODES.get(naf, "")
            print(f"    {naf} — {label:45s} : {count:>4}")

    print(f"\n  Complétude :")
    print(f"    SIRET      : {len(df[df['siret'] != '']) / t * 100:.1f}%")
    print(f"    Téléphone  : {len(df[df['telephone'] != '']) / t * 100:.1f}%")
    print(f"    Adresse    : {len(df[df['adresse'] != '']) / t * 100:.1f}%")

    print(f"\n  Sources :")
    src_counts = {}
    for src in df["source"]:
        primary = str(src).split(";")[0].strip()
        src_counts[primary] = src_counts.get(primary, 0) + 1
    for src, count in sorted(src_counts.items(), key=lambda x: -x[1]):
        if src:
            print(f"    {src:40s} : {count:>4}")

    print("\n" + "=" * 60)
    print(f"  Fichier : garages-cergy.xlsx")
    print("=" * 60 + "\n")


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    logger.info("=== Scraper Garages Cergy — START ===")

    # Source 1: API Entreprises
    api_records = scrape_api_entreprises()
    save_json(api_records, "garages_cergy_api.json")

    # Source 2: Pages Jaunes
    pj_records = scrape_pages_jaunes()
    save_json(pj_records, "garages_cergy_pj.json")

    # Source 3: OSM
    osm_records = scrape_osm()
    save_json(osm_records, "garages_cergy_osm.json")

    # Merge + dedup
    df = merge_and_deduplicate(api_records, pj_records, osm_records)

    # Enrich missing SIRETs
    df = enrich_missing_sirets(df)

    # Cleanup
    df = cleanup(df)

    # Export
    export_xlsx(df)

    # Summary
    print_summary(df)

    logger.info("=== Scraper Garages Cergy — DONE ===")


if __name__ == "__main__":
    main()
