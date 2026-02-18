#!/usr/bin/env python3
"""
Build a comprehensive list of medical centers (centres médicaux) in Île-de-France.

Data sources:
1. FINESS (data.gouv.fr) - Official French healthcare establishments database
   → Provides: name, address, phone, SIRET, FINESS number, category
2. recherche-entreprises.api.gouv.fr - French government enterprise API
   → Enriches with: SIREN, SIRET (when missing from FINESS)

Output: Excel file with all medical centers in IDF.
"""

import requests
import csv
import io
import zipfile
import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
import time
import json
import os
import re
import sys

# =============================================================================
# Configuration
# =============================================================================

IDF_DEPARTMENTS = {
    "75": "Paris",
    "77": "Seine-et-Marne",
    "78": "Yvelines",
    "91": "Essonne",
    "92": "Hauts-de-Seine",
    "93": "Seine-Saint-Denis",
    "94": "Val-de-Marne",
    "95": "Val-d'Oise",
}

# FINESS establishment category codes for medical centers
# See: https://www.data.gouv.fr/fr/datasets/finess-extraction-du-fichier-des-etablissements/
MEDICAL_CATEGORIES = {
    # Centres de santé
    "122": "Centre de santé médical",
    "123": "Centre de santé médical spécialisé",
    "124": "Centre de santé polyvalent",
    "127": "Centre de santé médical et dentaire",
    "128": "Centre de santé médical et infirmier",
    "129": "Centre de santé médical, dentaire et infirmier",
    # Centres hospitaliers
    "101": "Centre hospitalier (CH)",
    "106": "Centre hospitalier spécialisé - lutte maladies mentales",
    "114": "Hôpital des armées",
    "292": "Centre de PMI",
    "355": "Centre de lutte contre le cancer",
    "365": "Centre hospitalier universitaire (CHU)",
    # Cliniques
    "354": "Clinique",
    # Maisons de santé
    "603": "Maison de santé pluriprofessionnelle",
    # Centres de soins
    "219": "Autre centre de soins médicaux",
    "221": "Centre de dialyse",
    "228": "Centre d'action médico-sociale précoce (CAMSP)",
    "233": "Centre de médecine préventive",
    # Centres médicaux divers
    "160": "Centre médico-psychologique",
    "162": "Centre de postcure psychiatrique",
    "166": "Centre de crise",
}

# Additional keywords to match in establishment names (broader capture)
NAME_KEYWORDS = [
    "centre medical",
    "centre médical",
    "centre de sante",
    "centre de santé",
    "maison de sante",
    "maison de santé",
    "centre medico",
    "centre médico",
    "polyclinique",
    "centre de soins",
    "centre paramédical",
    "centre paramedical",
]

ENTERPRISE_API_URL = "https://recherche-entreprises.api.gouv.fr/search"
DATA_GOUV_API = "https://www.data.gouv.fr/api/1"

CACHE_FILE = "centres_medicaux_cache.json"
OUTPUT_FILE = "centres_medicaux_IDF_complet.xlsx"


# =============================================================================
# Phone formatting
# =============================================================================

def format_phone_international(phone):
    """Convert French phone number to international format +33 X XX XX XX XX."""
    if not phone:
        return ""

    # Clean the phone number - keep only digits
    digits = re.sub(r"[^\d]", "", str(phone).strip())

    if not digits:
        return ""

    # Handle French numbers
    if digits.startswith("33"):
        digits = "0" + digits[2:]

    if digits.startswith("0") and len(digits) == 10:
        # Standard French number: 0X XX XX XX XX -> +33 X XX XX XX XX
        formatted = f"+33 {digits[1]} {digits[2:4]} {digits[4:6]} {digits[6:8]} {digits[8:10]}"
        return formatted
    elif len(digits) == 9 and not digits.startswith("0"):
        # Missing leading 0
        formatted = f"+33 {digits[0]} {digits[1:3]} {digits[3:5]} {digits[5:7]} {digits[7:9]}"
        return formatted

    # Return as-is if format not recognized
    return str(phone).strip()


# =============================================================================
# FINESS Data Download
# =============================================================================

def find_finess_download_urls():
    """Find the FINESS establishments download URLs from data.gouv.fr."""
    print("Searching for FINESS dataset on data.gouv.fr...")

    dataset_slug = "finess-extraction-du-fichier-des-etablissements"
    url = f"{DATA_GOUV_API}/datasets/{dataset_slug}/"

    try:
        resp = requests.get(url, timeout=30)
        if resp.status_code != 200:
            print(f"  [WARNING] Could not fetch dataset metadata (HTTP {resp.status_code})")
            return []

        data = resp.json()
        resources = data.get("resources", [])

        # Categorize resources
        csv_candidates = []
        csv_geoloc = []
        zip_candidates = []

        for resource in resources:
            title = resource.get("title", "")
            title_l = title.lower()
            fmt = (resource.get("format") or "").lower()
            url_r = resource.get("url", "")
            url_l = url_r.lower()
            filesize = resource.get("filesize", 0) or 0

            info = {
                "title": title,
                "url": url_r,
                "format": fmt,
                "filesize": filesize,
                "last_modified": resource.get("last_modified", ""),
            }

            # Skip historical/archive files (very large)
            if "historique" in title_l:
                continue

            # Prefer CSV files with establishment data
            is_etab = any(kw in title_l or kw in url_l for kw in [
                "structet", "etablissement", "etalab-cs", "finess-cs",
                "geoloc", "extraction"
            ])
            is_geoloc = "géoloc" in title_l or "geoloc" in title_l or "geoloc" in url_l

            if is_etab:
                if fmt == "csv" or url_l.endswith(".csv"):
                    if is_geoloc:
                        csv_geoloc.append(info)
                    else:
                        csv_candidates.append(info)
                elif fmt == "zip" or url_l.endswith(".zip"):
                    zip_candidates.append(info)
                elif fmt in ("", "unknown"):
                    if ".csv" in url_l:
                        if is_geoloc:
                            csv_geoloc.append(info)
                        else:
                            csv_candidates.append(info)
                    elif ".zip" in url_l:
                        zip_candidates.append(info)
                    else:
                        csv_candidates.append(info)

        # Print what we found
        print(f"  Found {len(csv_candidates)} CSV (non-geo), {len(csv_geoloc)} CSV (geo), {len(zip_candidates)} ZIP")

        # Prefer non-geolocated CSV (simpler format), then geoloc, then ZIP
        all_candidates = csv_candidates + csv_geoloc + zip_candidates

        if not all_candidates:
            # Fallback: list all resources for debugging
            print("  [WARNING] No suitable resource found. Available resources:")
            for r in resources[:15]:
                print(f"    - {r.get('title')} ({r.get('format')}) [{r.get('filesize', 0)} bytes]")
                print(f"      URL: {r.get('url', '')[:100]}")

        for c in all_candidates[:5]:
            print(f"  Candidate: {c['title']} ({c['format']}, {c['filesize']} bytes)")

        return all_candidates

    except Exception as e:
        print(f"  [ERROR] Failed to query data.gouv.fr: {e}")
        return []


def download_finess_data(url):
    """Download FINESS data (CSV or ZIP containing CSV)."""
    print(f"Downloading FINESS data from: {url[:80]}...")
    try:
        resp = requests.get(url, timeout=120)
        if resp.status_code != 200:
            print(f"  [ERROR] Download failed (HTTP {resp.status_code})")
            return None

        content = resp.content
        print(f"  Downloaded {len(content)} bytes")

        # Check if it's a ZIP file
        if content[:4] == b"PK\x03\x04" or url.lower().endswith(".zip"):
            print("  File is a ZIP archive, extracting...")
            try:
                zf = zipfile.ZipFile(io.BytesIO(content))
                csv_files = [n for n in zf.namelist()
                             if n.lower().endswith(".csv")]
                # Prefer files with "structet" or "etablissement" in name
                target = None
                for cf in csv_files:
                    cfl = cf.lower()
                    if any(kw in cfl for kw in ["structet", "etablissement", "etalab"]):
                        target = cf
                        break
                if not target and csv_files:
                    # Just take the first/largest CSV
                    target = csv_files[0]

                if not target:
                    print(f"  [ERROR] No CSV found in ZIP. Contents: {zf.namelist()[:10]}")
                    return None

                print(f"  Extracting: {target}")
                csv_bytes = zf.read(target)
                content = csv_bytes
            except zipfile.BadZipFile:
                print("  Not a valid ZIP, treating as raw CSV")

        # Try different encodings
        for encoding in ["utf-8", "latin-1", "cp1252", "iso-8859-1"]:
            try:
                text = content.decode(encoding)
                # Verify it looks like CSV
                first_chunk = text[:2000]
                if ";" in first_chunk or "," in first_chunk or "\t" in first_chunk:
                    print(f"  Decoded successfully (encoding: {encoding})")
                    return text, encoding
            except (UnicodeDecodeError, UnicodeError):
                continue

        print("  [ERROR] Could not decode file with any known encoding")
        return None

    except Exception as e:
        print(f"  [ERROR] Download failed: {e}")
        return None


def parse_finess_csv(text, encoding="utf-8"):
    """Parse FINESS CSV and extract IDF medical centers.

    FINESS CSV format (no column headers):
    Line 1: metadata (finess;etalab;106;date)
    Line 2+: data rows with ; delimiter

    Positional columns (0-indexed):
    0:  record_type (structureet)
    1:  nofinesset (FINESS ET)
    2:  nofinessej (FINESS EJ)
    3:  rs (raison sociale - short name)
    4:  rslongue (full name)
    5:  complrs
    6:  compldistrib
    7:  numvoie (street number)
    8:  typvoie (street type: R, AV, BD, etc.)
    9:  voie (street name)
    10: compvoie (street complement)
    11: lieuditbp
    12: commune_code (INSEE code)
    13: departement (department number)
    14: libdepartement (department name)
    15: ligneacheminement (postal code + city)
    16: telephone
    17: telecopie (fax)
    18: categetab (category code)
    19: libcategetab (category label)
    20: categagretab
    21: libcategagretab
    22: siret
    23: codeape (NAF)
    24: codemft
    25: libmft
    (+ possibly more columns for geolocated version)
    """
    print("Parsing FINESS data...")

    lines = text.split("\n")
    print(f"  Total lines: {len(lines)}")

    # Skip the first metadata line
    if lines and lines[0].startswith("finess;"):
        lines = lines[1:]
        print("  Skipped metadata header line")

    centers = []
    total_rows = 0
    idf_rows = 0
    parse_errors = 0

    for line in lines:
        line = line.strip()
        if not line:
            continue

        total_rows += 1
        fields = line.split(";")

        if len(fields) < 23:
            parse_errors += 1
            continue

        # Extract fields by position
        record_type = fields[0].strip()
        finess_et = fields[1].strip()
        name_short = fields[3].strip()
        name_long = fields[4].strip()
        num_street = fields[7].strip()
        type_street = fields[8].strip()
        street = fields[9].strip()
        street_comp = fields[10].strip()
        dept_num = fields[13].strip()
        dept_name_raw = fields[14].strip()
        routing_line = fields[15].strip()
        phone = fields[16].strip()
        fax = fields[17].strip()
        cat_code = fields[18].strip()
        cat_label = fields[19].strip()
        siret = fields[22].strip() if len(fields) > 22 else ""
        naf_code = fields[23].strip() if len(fields) > 23 else ""

        # Filter for IDF departments
        if dept_num not in IDF_DEPARTMENTS:
            continue

        idf_rows += 1

        # Use full name if available
        display_name = name_long if name_long else name_short

        # Check if this is a medical center (by category or by name keyword)
        is_medical_by_category = cat_code in MEDICAL_CATEGORIES
        is_medical_by_name = False
        name_lower = display_name.lower()
        for kw in NAME_KEYWORDS:
            if kw in name_lower:
                is_medical_by_name = True
                break

        if not is_medical_by_category and not is_medical_by_name:
            continue

        # Build address
        addr_parts = []
        if num_street:
            addr_parts.append(num_street)
        if type_street:
            addr_parts.append(type_street)
        if street:
            addr_parts.append(street)
        if street_comp:
            addr_parts.append(street_comp)
        address = " ".join(addr_parts)

        # Extract postal code and city from routing line
        postal_code = ""
        city = ""
        if routing_line and len(routing_line) >= 5:
            parts = routing_line.split(" ", 1)
            if parts[0].isdigit():
                postal_code = parts[0]
            if len(parts) >= 2:
                city = parts[1].strip()

        # Derive SIREN from SIRET
        siren = siret[:9] if siret and len(siret) >= 9 else ""

        dept_name = IDF_DEPARTMENTS.get(dept_num, dept_name_raw)

        # Get category label from our mapping if not in data
        if not cat_label and cat_code in MEDICAL_CATEGORIES:
            cat_label = MEDICAL_CATEGORIES[cat_code]

        centers.append({
            "name": display_name,
            "address": address,
            "postal_code": postal_code,
            "city": city,
            "department_num": dept_num,
            "department_name": dept_name,
            "region": "Île-de-France",
            "phone": phone,
            "phone_international": format_phone_international(phone),
            "fax": fax,
            "siret": siret,
            "siren": siren,
            "finess": finess_et,
            "category_code": cat_code,
            "category_label": cat_label,
            "source": "FINESS",
        })

    print(f"  Total data rows: {total_rows}")
    print(f"  Parse errors (short lines): {parse_errors}")
    print(f"  IDF establishments: {idf_rows}")
    print(f"  Medical centers found: {len(centers)}")

    return centers


# =============================================================================
# Enterprise API Enrichment
# =============================================================================

def search_enterprise_api(name, postal_code, city):
    """Search for a company using the government enterprise API."""
    if not name:
        return {}, ""

    params = {"q": str(name).strip(), "per_page": 5}

    if postal_code:
        pc = str(postal_code).strip()
        if pc and pc != "None" and len(pc) >= 2:
            params["code_postal"] = pc

    try:
        resp = requests.get(ENTERPRISE_API_URL, params=params, timeout=15)
        if resp.status_code == 429:
            time.sleep(2)
            resp = requests.get(ENTERPRISE_API_URL, params=params, timeout=15)

        if resp.status_code == 200:
            data = resp.json()
            results = data.get("results", [])
            if results:
                best = results[0]
                return {
                    "siren": best.get("siren", ""),
                    "siret": best.get("siege", {}).get("siret", ""),
                    "matched_name": best.get("nom_complet", ""),
                }, ""

        # Fallback: search with city in query
        if city and str(city).strip() not in ("None", ""):
            params2 = {"q": f"{name} {city}", "per_page": 5}
            resp2 = requests.get(ENTERPRISE_API_URL, params=params2, timeout=15)
            if resp2.status_code == 200:
                data2 = resp2.json()
                results2 = data2.get("results", [])
                if results2:
                    best = results2[0]
                    return {
                        "siren": best.get("siren", ""),
                        "siret": best.get("siege", {}).get("siret", ""),
                        "matched_name": best.get("nom_complet", ""),
                    }, ""

    except Exception as e:
        return {}, str(e)

    return {}, ""


def search_medical_centers_api(department):
    """Search for medical centers in a department using the enterprise API."""
    all_results = []
    search_terms = [
        "centre medical",
        "centre de sante",
        "maison de sante",
        "centre medico",
    ]

    for term in search_terms:
        page = 1
        while page <= 100:  # Safety limit
            params = {
                "q": term,
                "departement": department,
                "per_page": 25,
                "page": page,
            }
            try:
                resp = requests.get(ENTERPRISE_API_URL, params=params, timeout=15)
                if resp.status_code == 429:
                    time.sleep(2)
                    resp = requests.get(ENTERPRISE_API_URL, params=params, timeout=15)

                if resp.status_code != 200:
                    break

                data = resp.json()
                results = data.get("results", [])
                if not results:
                    break

                for r in results:
                    siege = r.get("siege", {})
                    siren = r.get("siren", "")
                    siret = siege.get("siret", "")
                    name = r.get("nom_complet", "")
                    addr = siege.get("adresse", "")
                    cp = str(siege.get("code_postal", "") or "")
                    city = siege.get("libelle_commune", "")

                    # Verify the establishment is actually in IDF
                    # Check postal code starts with an IDF department
                    actual_dept = cp[:2] if len(cp) >= 2 else ""
                    if actual_dept not in IDF_DEPARTMENTS:
                        # Try matching establishments instead of siege
                        found_idf = False
                        for etab in r.get("matching_etablissements", []):
                            etab_cp = str(etab.get("code_postal", "") or "")
                            etab_dept = etab_cp[:2] if len(etab_cp) >= 2 else ""
                            if etab_dept in IDF_DEPARTMENTS:
                                addr = etab.get("adresse", "") or addr
                                cp = etab_cp
                                city = etab.get("libelle_commune", "") or city
                                actual_dept = etab_dept
                                siret = etab.get("siret", "") or siret
                                found_idf = True
                                break
                        if not found_idf:
                            continue  # Skip non-IDF entries

                    # Clean address: remove trailing postal code + city
                    if addr and cp and city:
                        suffix = f"{cp} {city}"
                        if addr.endswith(suffix):
                            addr = addr[:-len(suffix)].strip().rstrip(",")
                        # Also try just postal code
                        elif addr.endswith(cp):
                            addr = addr[:-len(cp)].strip().rstrip(",")

                    all_results.append({
                        "name": name,
                        "address": addr,
                        "postal_code": cp,
                        "city": city,
                        "department_num": actual_dept,
                        "department_name": IDF_DEPARTMENTS.get(actual_dept, ""),
                        "region": "Île-de-France",
                        "phone": "",
                        "phone_international": "",
                        "fax": "",
                        "siret": siret,
                        "siren": siren,
                        "finess": "",
                        "category_code": "",
                        "category_label": r.get("activite_principale", ""),
                        "source": "API Entreprises",
                    })

                total = data.get("total_results", 0)
                if page * 25 >= total:
                    break
                page += 1
                time.sleep(0.15)

            except Exception as e:
                print(f"    [ERROR] API search failed: {e}")
                break

    return all_results


# =============================================================================
# Cache management
# =============================================================================

def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)


# =============================================================================
# Deduplication
# =============================================================================

def deduplicate_centers(centers):
    """Remove duplicates based on SIRET, FINESS, or name+postal_code."""
    seen = set()
    unique = []

    for c in centers:
        # Create dedup keys
        keys = []
        if c.get("siret"):
            keys.append(f"siret:{c['siret']}")
        if c.get("finess"):
            keys.append(f"finess:{c['finess']}")
        if c.get("name") and c.get("postal_code"):
            name_norm = re.sub(r"[^a-z0-9]", "", c["name"].lower())
            keys.append(f"name_cp:{name_norm}:{c['postal_code']}")

        if not keys:
            # No dedup key, include anyway
            unique.append(c)
            continue

        is_dup = False
        for k in keys:
            if k in seen:
                is_dup = True
                break

        if not is_dup:
            unique.append(c)
            for k in keys:
                seen.add(k)

    return unique


# =============================================================================
# Excel Output
# =============================================================================

def write_excel(centers, filename):
    """Write centers to a formatted Excel file."""
    print(f"\nWriting {len(centers)} centers to {filename}...")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Centres Médicaux IDF"

    # Headers
    headers = [
        ("N°", 5),
        ("Nom de l'établissement", 45),
        ("Adresse", 40),
        ("Code Postal", 12),
        ("Ville", 25),
        ("Département N°", 15),
        ("Département", 22),
        ("Région", 18),
        ("Téléphone (International)", 28),
        ("Téléphone (Original)", 20),
        ("Fax", 18),
        ("SIREN", 15),
        ("SIRET", 18),
        ("N° FINESS", 15),
        ("Catégorie", 40),
        ("Source", 18),
    ]

    # Style for headers
    header_font = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color="2E86C1", end_color="2E86C1", fill_type="solid")
    header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin_border = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )

    # Write headers
    for col, (header_text, width) in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header_text)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border
        ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = width

    # Freeze top row
    ws.freeze_panes = "A2"

    # Auto-filter
    ws.auto_filter.ref = f"A1:{openpyxl.utils.get_column_letter(len(headers))}1"

    # Data font
    data_font = Font(name="Calibri", size=10)
    data_alignment = Alignment(vertical="center", wrap_text=False)

    # Sort centers by department, then city, then name
    centers.sort(key=lambda x: (
        x.get("department_num") or "",
        x.get("city") or "",
        x.get("name") or "",
    ))

    # Write data
    for idx, center in enumerate(centers, 1):
        row = idx + 1
        values = [
            idx,
            center.get("name", ""),
            center.get("address", ""),
            center.get("postal_code", ""),
            center.get("city", ""),
            center.get("department_num", ""),
            center.get("department_name", ""),
            center.get("region", "Île-de-France"),
            center.get("phone_international", ""),
            center.get("phone", ""),
            center.get("fax", ""),
            center.get("siren", ""),
            center.get("siret", ""),
            center.get("finess", ""),
            center.get("category_label", ""),
            center.get("source", ""),
        ]

        # Alternate row colors
        if idx % 2 == 0:
            row_fill = PatternFill(start_color="EBF5FB", end_color="EBF5FB", fill_type="solid")
        else:
            row_fill = PatternFill(fill_type=None)

        for col, val in enumerate(values, 1):
            cell = ws.cell(row=row, column=col, value=val)
            cell.font = data_font
            cell.alignment = data_alignment
            cell.border = thin_border
            cell.fill = row_fill

    # Add summary sheet
    ws_summary = wb.create_sheet("Résumé")
    ws_summary.column_dimensions["A"].width = 30
    ws_summary.column_dimensions["B"].width = 20

    summary_data = [
        ("Statistiques", ""),
        ("Total centres médicaux", len(centers)),
        ("", ""),
        ("Par département:", ""),
    ]

    # Count by department
    dept_counts = {}
    for c in centers:
        dept = f"{c.get('department_num', '??')} - {c.get('department_name', '??')}"
        dept_counts[dept] = dept_counts.get(dept, 0) + 1

    for dept, count in sorted(dept_counts.items()):
        summary_data.append((f"  {dept}", count))

    summary_data.extend([
        ("", ""),
        ("Avec téléphone", sum(1 for c in centers if c.get("phone_international"))),
        ("Avec SIRET", sum(1 for c in centers if c.get("siret"))),
        ("Avec SIREN", sum(1 for c in centers if c.get("siren"))),
        ("Avec N° FINESS", sum(1 for c in centers if c.get("finess"))),
        ("", ""),
        ("Par source:", ""),
    ])

    source_counts = {}
    for c in centers:
        src = c.get("source", "Inconnu")
        source_counts[src] = source_counts.get(src, 0) + 1
    for src, count in sorted(source_counts.items()):
        summary_data.append((f"  {src}", count))

    for row_idx, (label, value) in enumerate(summary_data, 1):
        ws_summary.cell(row=row_idx, column=1, value=label).font = Font(
            name="Calibri", bold=(row_idx <= 1 or ":" in str(label)), size=11
        )
        if value != "":
            ws_summary.cell(row=row_idx, column=2, value=value).font = Font(
                name="Calibri", size=11
            )

    wb.save(filename)
    print(f"  Saved to {filename}")


# =============================================================================
# Main
# =============================================================================

def main():
    print("=" * 70)
    print("  Construction de la liste des centres médicaux en Île-de-France")
    print("=" * 70)
    print()

    all_centers = []

    # -------------------------------------------------------------------------
    # Phase 1: Download and parse FINESS data
    # -------------------------------------------------------------------------
    print("PHASE 1: Téléchargement des données FINESS")
    print("-" * 50)

    finess_urls = find_finess_download_urls()
    finess_centers = []

    for candidate in finess_urls:
        result = download_finess_data(candidate["url"])
        if result:
            text, encoding = result
            finess_centers = parse_finess_csv(text, encoding)
            if finess_centers:
                all_centers.extend(finess_centers)
                print(f"  → {len(finess_centers)} centres médicaux trouvés dans FINESS")
                break
            else:
                print(f"  [INFO] No medical centers found in this file, trying next...")
        else:
            print(f"  [WARNING] Could not download {candidate['title']}, trying next...")

    if not finess_centers:
        print("  [WARNING] Could not load FINESS data from any source")

    print()

    # -------------------------------------------------------------------------
    # Phase 2: Search via Enterprise API (complementary)
    # -------------------------------------------------------------------------
    print("PHASE 2: Recherche complémentaire via l'API Entreprises")
    print("-" * 50)

    api_centers = []
    for dept, dept_name in sorted(IDF_DEPARTMENTS.items()):
        print(f"  Searching in {dept} - {dept_name}...")
        results = search_medical_centers_api(dept)
        api_centers.extend(results)
        print(f"    Found {len(results)} results")
        time.sleep(0.3)

    all_centers.extend(api_centers)
    print(f"  → {len(api_centers)} centres trouvés via l'API Entreprises")
    print()

    # -------------------------------------------------------------------------
    # Phase 3: Deduplicate
    # -------------------------------------------------------------------------
    print("PHASE 3: Déduplication")
    print("-" * 50)
    print(f"  Total avant déduplication: {len(all_centers)}")
    all_centers = deduplicate_centers(all_centers)
    print(f"  Total après déduplication: {len(all_centers)}")
    print()

    # -------------------------------------------------------------------------
    # Phase 4: Enrich missing SIRET via API
    # -------------------------------------------------------------------------
    print("PHASE 4: Enrichissement SIRET pour les entrées manquantes")
    print("-" * 50)

    cache = load_cache()
    missing_siret = [c for c in all_centers if not c.get("siret")]
    print(f"  {len(missing_siret)} centres sans SIRET à enrichir")

    enriched_count = 0
    for i, center in enumerate(missing_siret):
        name = center.get("name", "")
        cp = center.get("postal_code", "")
        city = center.get("city", "")

        cache_key = f"{name}|{cp}|{city}"

        if cache_key in cache:
            result = cache[cache_key]
        else:
            result, err = search_enterprise_api(name, cp, city)
            cache[cache_key] = result
            time.sleep(0.15)

        if result and result.get("siret"):
            center["siret"] = result["siret"]
            center["siren"] = result.get("siren", "")
            enriched_count += 1

        if (i + 1) % 50 == 0:
            print(f"    Progress: {i + 1}/{len(missing_siret)} | Enriched: {enriched_count}")
            save_cache(cache)

    save_cache(cache)
    print(f"  → {enriched_count} SIRET supplémentaires trouvés")
    print()

    # -------------------------------------------------------------------------
    # Phase 5: Output
    # -------------------------------------------------------------------------
    print("PHASE 5: Génération du fichier Excel")
    print("-" * 50)

    write_excel(all_centers, OUTPUT_FILE)

    # Print summary
    print()
    print("=" * 70)
    print("  RÉSUMÉ")
    print("=" * 70)
    print(f"  Total centres médicaux: {len(all_centers)}")
    print(f"  Avec téléphone: {sum(1 for c in all_centers if c.get('phone_international'))}")
    print(f"  Avec SIRET: {sum(1 for c in all_centers if c.get('siret'))}")
    print(f"  Avec SIREN: {sum(1 for c in all_centers if c.get('siren'))}")
    print(f"  Avec N° FINESS: {sum(1 for c in all_centers if c.get('finess'))}")
    print()

    # By department
    print("  Par département:")
    dept_counts = {}
    for c in all_centers:
        dept = c.get("department_num", "??")
        dept_counts[dept] = dept_counts.get(dept, 0) + 1
    for dept in sorted(dept_counts.keys()):
        name = IDF_DEPARTMENTS.get(dept, "?")
        print(f"    {dept} - {name}: {dept_counts[dept]}")

    print()
    print(f"  Fichier de sortie: {OUTPUT_FILE}")
    print("=" * 70)

    # Cleanup cache
    if os.path.exists(CACHE_FILE):
        os.remove(CACHE_FILE)


if __name__ == "__main__":
    main()
