#!/usr/bin/env python3
"""
Build a comprehensive list of medical centers (centres médicaux) across ALL of France.

Data sources:
1. FINESS (data.gouv.fr) - Official French healthcare establishments database
   → Provides: name, address, phone, SIRET, FINESS number, category
2. recherche-entreprises.api.gouv.fr - French government enterprise API
   → Enriches with: SIREN, SIRET (when missing from FINESS)

Output: Excel file with all medical centers in France.
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

# Department number → (Department name, Region)
DEPARTMENTS = {
    "01": ("Ain", "Auvergne-Rhône-Alpes"),
    "02": ("Aisne", "Hauts-de-France"),
    "03": ("Allier", "Auvergne-Rhône-Alpes"),
    "04": ("Alpes-de-Haute-Provence", "Provence-Alpes-Côte d'Azur"),
    "05": ("Hautes-Alpes", "Provence-Alpes-Côte d'Azur"),
    "06": ("Alpes-Maritimes", "Provence-Alpes-Côte d'Azur"),
    "07": ("Ardèche", "Auvergne-Rhône-Alpes"),
    "08": ("Ardennes", "Grand Est"),
    "09": ("Ariège", "Occitanie"),
    "10": ("Aube", "Grand Est"),
    "11": ("Aude", "Occitanie"),
    "12": ("Aveyron", "Occitanie"),
    "13": ("Bouches-du-Rhône", "Provence-Alpes-Côte d'Azur"),
    "14": ("Calvados", "Normandie"),
    "15": ("Cantal", "Auvergne-Rhône-Alpes"),
    "16": ("Charente", "Nouvelle-Aquitaine"),
    "17": ("Charente-Maritime", "Nouvelle-Aquitaine"),
    "18": ("Cher", "Centre-Val de Loire"),
    "19": ("Corrèze", "Nouvelle-Aquitaine"),
    "2A": ("Corse-du-Sud", "Corse"),
    "2B": ("Haute-Corse", "Corse"),
    "21": ("Côte-d'Or", "Bourgogne-Franche-Comté"),
    "22": ("Côtes-d'Armor", "Bretagne"),
    "23": ("Creuse", "Nouvelle-Aquitaine"),
    "24": ("Dordogne", "Nouvelle-Aquitaine"),
    "25": ("Doubs", "Bourgogne-Franche-Comté"),
    "26": ("Drôme", "Auvergne-Rhône-Alpes"),
    "27": ("Eure", "Normandie"),
    "28": ("Eure-et-Loir", "Centre-Val de Loire"),
    "29": ("Finistère", "Bretagne"),
    "30": ("Gard", "Occitanie"),
    "31": ("Haute-Garonne", "Occitanie"),
    "32": ("Gers", "Occitanie"),
    "33": ("Gironde", "Nouvelle-Aquitaine"),
    "34": ("Hérault", "Occitanie"),
    "35": ("Ille-et-Vilaine", "Bretagne"),
    "36": ("Indre", "Centre-Val de Loire"),
    "37": ("Indre-et-Loire", "Centre-Val de Loire"),
    "38": ("Isère", "Auvergne-Rhône-Alpes"),
    "39": ("Jura", "Bourgogne-Franche-Comté"),
    "40": ("Landes", "Nouvelle-Aquitaine"),
    "41": ("Loir-et-Cher", "Centre-Val de Loire"),
    "42": ("Loire", "Auvergne-Rhône-Alpes"),
    "43": ("Haute-Loire", "Auvergne-Rhône-Alpes"),
    "44": ("Loire-Atlantique", "Pays de la Loire"),
    "45": ("Loiret", "Centre-Val de Loire"),
    "46": ("Lot", "Occitanie"),
    "47": ("Lot-et-Garonne", "Nouvelle-Aquitaine"),
    "48": ("Lozère", "Occitanie"),
    "49": ("Maine-et-Loire", "Pays de la Loire"),
    "50": ("Manche", "Normandie"),
    "51": ("Marne", "Grand Est"),
    "52": ("Haute-Marne", "Grand Est"),
    "53": ("Mayenne", "Pays de la Loire"),
    "54": ("Meurthe-et-Moselle", "Grand Est"),
    "55": ("Meuse", "Grand Est"),
    "56": ("Morbihan", "Bretagne"),
    "57": ("Moselle", "Grand Est"),
    "58": ("Nièvre", "Bourgogne-Franche-Comté"),
    "59": ("Nord", "Hauts-de-France"),
    "60": ("Oise", "Hauts-de-France"),
    "61": ("Orne", "Normandie"),
    "62": ("Pas-de-Calais", "Hauts-de-France"),
    "63": ("Puy-de-Dôme", "Auvergne-Rhône-Alpes"),
    "64": ("Pyrénées-Atlantiques", "Nouvelle-Aquitaine"),
    "65": ("Hautes-Pyrénées", "Occitanie"),
    "66": ("Pyrénées-Orientales", "Occitanie"),
    "67": ("Bas-Rhin", "Grand Est"),
    "68": ("Haut-Rhin", "Grand Est"),
    "69": ("Rhône", "Auvergne-Rhône-Alpes"),
    "70": ("Haute-Saône", "Bourgogne-Franche-Comté"),
    "71": ("Saône-et-Loire", "Bourgogne-Franche-Comté"),
    "72": ("Sarthe", "Pays de la Loire"),
    "73": ("Savoie", "Auvergne-Rhône-Alpes"),
    "74": ("Haute-Savoie", "Auvergne-Rhône-Alpes"),
    "75": ("Paris", "Île-de-France"),
    "76": ("Seine-Maritime", "Normandie"),
    "77": ("Seine-et-Marne", "Île-de-France"),
    "78": ("Yvelines", "Île-de-France"),
    "79": ("Deux-Sèvres", "Nouvelle-Aquitaine"),
    "80": ("Somme", "Hauts-de-France"),
    "81": ("Tarn", "Occitanie"),
    "82": ("Tarn-et-Garonne", "Occitanie"),
    "83": ("Var", "Provence-Alpes-Côte d'Azur"),
    "84": ("Vaucluse", "Provence-Alpes-Côte d'Azur"),
    "85": ("Vendée", "Pays de la Loire"),
    "86": ("Vienne", "Nouvelle-Aquitaine"),
    "87": ("Haute-Vienne", "Nouvelle-Aquitaine"),
    "88": ("Vosges", "Grand Est"),
    "89": ("Yonne", "Bourgogne-Franche-Comté"),
    "90": ("Territoire de Belfort", "Bourgogne-Franche-Comté"),
    "91": ("Essonne", "Île-de-France"),
    "92": ("Hauts-de-Seine", "Île-de-France"),
    "93": ("Seine-Saint-Denis", "Île-de-France"),
    "94": ("Val-de-Marne", "Île-de-France"),
    "95": ("Val-d'Oise", "Île-de-France"),
    # DOM-TOM
    "971": ("Guadeloupe", "Guadeloupe"),
    "972": ("Martinique", "Martinique"),
    "973": ("Guyane", "Guyane"),
    "974": ("La Réunion", "La Réunion"),
    "976": ("Mayotte", "Mayotte"),
}

# FINESS establishment category codes for medical centers
MEDICAL_CATEGORIES = {
    # Centres de santé
    "122": "Centre de santé médical",
    "123": "Centre de santé médical spécialisé",
    "124": "Centre de santé polyvalent",
    "125": "Centre de santé dentaire",
    "126": "Centre de santé infirmier",
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

# Keywords to match in establishment names
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

CACHE_FILE = "centres_medicaux_france_cache.json"
OUTPUT_FILE = "centres_medicaux_France_complet.xlsx"


# =============================================================================
# Helpers
# =============================================================================

def get_dept_name(dept_num):
    """Get department name from number."""
    info = DEPARTMENTS.get(dept_num)
    return info[0] if info else ""


def get_region(dept_num):
    """Get region name from department number."""
    info = DEPARTMENTS.get(dept_num)
    return info[1] if info else ""


def format_phone_international(phone):
    """Convert French phone number to international format +33 X XX XX XX XX."""
    if not phone:
        return ""
    digits = re.sub(r"[^\d]", "", str(phone).strip())
    if not digits:
        return ""
    if digits.startswith("33"):
        digits = "0" + digits[2:]
    if digits.startswith("0") and len(digits) == 10:
        return f"+33 {digits[1]} {digits[2:4]} {digits[4:6]} {digits[6:8]} {digits[8:10]}"
    elif len(digits) == 9 and not digits.startswith("0"):
        return f"+33 {digits[0]} {digits[1:3]} {digits[3:5]} {digits[5:7]} {digits[7:9]}"
    return str(phone).strip()


# =============================================================================
# FINESS Data Download & Parsing
# =============================================================================

def find_finess_download_urls():
    """Find FINESS establishments download URLs from data.gouv.fr."""
    print("Searching for FINESS dataset on data.gouv.fr...")
    dataset_slug = "finess-extraction-du-fichier-des-etablissements"
    url = f"{DATA_GOUV_API}/datasets/{dataset_slug}/"
    try:
        resp = requests.get(url, timeout=30)
        if resp.status_code != 200:
            print(f"  [WARNING] HTTP {resp.status_code}")
            return []
        data = resp.json()
        resources = data.get("resources", [])
        csv_candidates = []
        csv_geoloc = []
        for resource in resources:
            title = resource.get("title", "")
            title_l = title.lower()
            fmt = (resource.get("format") or "").lower()
            url_r = resource.get("url", "")
            url_l = url_r.lower()
            info = {
                "title": title,
                "url": url_r,
                "format": fmt,
                "filesize": resource.get("filesize", 0) or 0,
            }
            if "historique" in title_l:
                continue
            is_etab = any(kw in title_l or kw in url_l for kw in [
                "structet", "etablissement", "etalab-cs", "finess-cs", "geoloc", "extraction"
            ])
            is_geoloc = "géoloc" in title_l or "geoloc" in title_l or "geoloc" in url_l
            if is_etab and (fmt == "csv" or url_l.endswith(".csv") or ".csv" in url_l):
                if is_geoloc:
                    csv_geoloc.append(info)
                else:
                    csv_candidates.append(info)
        all_candidates = csv_candidates + csv_geoloc
        print(f"  Found {len(csv_candidates)} CSV (non-geo), {len(csv_geoloc)} CSV (geo)")
        for c in all_candidates[:3]:
            print(f"  Candidate: {c['title']} ({c['filesize']} bytes)")
        return all_candidates
    except Exception as e:
        print(f"  [ERROR] {e}")
        return []


def download_finess_data(url):
    """Download FINESS data (CSV or ZIP containing CSV)."""
    print(f"Downloading FINESS data...")
    try:
        resp = requests.get(url, timeout=180)
        if resp.status_code != 200:
            print(f"  [ERROR] HTTP {resp.status_code}")
            return None
        content = resp.content
        print(f"  Downloaded {len(content):,} bytes")
        if content[:4] == b"PK\x03\x04" or url.lower().endswith(".zip"):
            print("  Extracting ZIP...")
            zf = zipfile.ZipFile(io.BytesIO(content))
            csv_files = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            target = None
            for cf in csv_files:
                if any(kw in cf.lower() for kw in ["structet", "etablissement", "etalab"]):
                    target = cf
                    break
            if not target and csv_files:
                target = csv_files[0]
            if not target:
                return None
            content = zf.read(target)
        for encoding in ["utf-8", "latin-1", "cp1252"]:
            try:
                text = content.decode(encoding)
                if ";" in text[:2000]:
                    print(f"  Decoded OK (encoding: {encoding})")
                    return text, encoding
            except UnicodeDecodeError:
                continue
        return None
    except Exception as e:
        print(f"  [ERROR] {e}")
        return None


def parse_finess_csv(text):
    """Parse FINESS CSV and extract ALL French medical centers.

    FINESS positional columns (;-separated, no header row):
    0: record_type   1: nofinesset    2: nofinessej   3: rs (short name)
    4: rslongue      5: complrs       6: compldistrib  7: numvoie
    8: typvoie       9: voie         10: compvoie     11: lieuditbp
    12: commune_code 13: departement  14: libdepartement
    15: ligneacheminement (postal code + city)
    16: telephone    17: telecopie    18: categetab    19: libcategetab
    20: categagretab 21: libcategagretab  22: siret    23: codeape
    24: codemft      25: libmft
    """
    print("Parsing FINESS data for all of France...")
    lines = text.split("\n")
    print(f"  Total lines: {len(lines):,}")

    if lines and lines[0].startswith("finess;"):
        lines = lines[1:]

    centers = []
    total_rows = 0
    matched_rows = 0
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

        display_name = name_long if name_long else name_short

        # Filter: is this a medical center?
        is_medical_by_category = cat_code in MEDICAL_CATEGORIES
        is_medical_by_name = False
        if not is_medical_by_category:
            name_lower = display_name.lower()
            for kw in NAME_KEYWORDS:
                if kw in name_lower:
                    is_medical_by_name = True
                    break

        if not is_medical_by_category and not is_medical_by_name:
            continue

        matched_rows += 1

        # Build address
        addr_parts = [p for p in [num_street, type_street, street, street_comp] if p]
        address = " ".join(addr_parts)

        # Postal code and city
        postal_code = ""
        city = ""
        if routing_line and len(routing_line) >= 5:
            parts = routing_line.split(" ", 1)
            if parts[0].isdigit():
                postal_code = parts[0]
            if len(parts) >= 2:
                city = parts[1].strip()

        siren = siret[:9] if siret and len(siret) >= 9 else ""
        dept_name = get_dept_name(dept_num) or dept_name_raw
        region = get_region(dept_num)

        if not cat_label and cat_code in MEDICAL_CATEGORIES:
            cat_label = MEDICAL_CATEGORIES[cat_code]

        centers.append({
            "name": display_name,
            "address": address,
            "postal_code": postal_code,
            "city": city,
            "department_num": dept_num,
            "department_name": dept_name,
            "region": region,
            "phone": phone,
            "phone_international": format_phone_international(phone),
            "fax": fax,
            "email": "",
            "siret": siret,
            "siren": siren,
            "finess": finess_et,
            "category_code": cat_code,
            "category_label": cat_label,
            "source": "FINESS",
        })

    print(f"  Total data rows: {total_rows:,}")
    print(f"  Parse errors: {parse_errors:,}")
    print(f"  Medical centers found: {matched_rows:,}")
    return centers


# =============================================================================
# Enterprise API
# =============================================================================

def search_enterprise_api(name, postal_code, city):
    """Search for a company SIRET via the government API."""
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
            results = resp.json().get("results", [])
            if results:
                best = results[0]
                return {
                    "siren": best.get("siren", ""),
                    "siret": best.get("siege", {}).get("siret", ""),
                }, ""
        # Fallback with city
        if city and str(city).strip() not in ("None", ""):
            params2 = {"q": f"{name} {city}", "per_page": 5}
            resp2 = requests.get(ENTERPRISE_API_URL, params=params2, timeout=15)
            if resp2.status_code == 200:
                results2 = resp2.json().get("results", [])
                if results2:
                    best = results2[0]
                    return {
                        "siren": best.get("siren", ""),
                        "siret": best.get("siege", {}).get("siret", ""),
                    }, ""
    except Exception as e:
        return {}, str(e)
    return {}, ""


def search_medical_centers_api(department):
    """Search for medical centers in a department via the enterprise API."""
    all_results = []
    seen_sirens = set()
    search_terms = ["centre medical", "centre de sante", "maison de sante", "centre medico"]

    for term in search_terms:
        page = 1
        while page <= 50:
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
                    siren = r.get("siren", "")
                    if siren in seen_sirens:
                        continue
                    seen_sirens.add(siren)

                    siege = r.get("siege", {})
                    siret = siege.get("siret", "")
                    name = r.get("nom_complet", "")
                    addr = siege.get("adresse", "")
                    cp = str(siege.get("code_postal", "") or "")
                    city = siege.get("libelle_commune", "")

                    # Determine actual department from postal code
                    actual_dept = cp[:2] if len(cp) >= 2 else ""
                    if cp[:3] in ("971", "972", "973", "974", "976"):
                        actual_dept = cp[:3]

                    # If siege not in target department, try matching_etablissements
                    if actual_dept != department:
                        found = False
                        for etab in r.get("matching_etablissements", []):
                            etab_cp = str(etab.get("code_postal", "") or "")
                            etab_dept = etab_cp[:2] if len(etab_cp) >= 2 else ""
                            if etab_cp[:3] in ("971", "972", "973", "974", "976"):
                                etab_dept = etab_cp[:3]
                            if etab_dept == department:
                                addr = etab.get("adresse", "") or addr
                                cp = etab_cp
                                city = etab.get("libelle_commune", "") or city
                                actual_dept = etab_dept
                                siret = etab.get("siret", "") or siret
                                found = True
                                break
                        if not found:
                            continue

                    # Clean address
                    if addr and cp and city:
                        suffix = f"{cp} {city}"
                        if addr.endswith(suffix):
                            addr = addr[:-len(suffix)].strip().rstrip(",")
                        elif addr.endswith(cp):
                            addr = addr[:-len(cp)].strip().rstrip(",")

                    all_results.append({
                        "name": name,
                        "address": addr,
                        "postal_code": cp,
                        "city": city,
                        "department_num": actual_dept,
                        "department_name": get_dept_name(actual_dept),
                        "region": get_region(actual_dept),
                        "phone": "",
                        "phone_international": "",
                        "fax": "",
                        "email": "",
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
                time.sleep(0.12)
            except Exception as e:
                print(f"      [ERROR] {e}")
                break
    return all_results


# =============================================================================
# Cache
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
        keys = []
        if c.get("siret"):
            keys.append(f"siret:{c['siret']}")
        if c.get("finess"):
            keys.append(f"finess:{c['finess']}")
        if c.get("name") and c.get("postal_code"):
            name_norm = re.sub(r"[^a-z0-9]", "", c["name"].lower())
            keys.append(f"name_cp:{name_norm}:{c['postal_code']}")
        if not keys:
            unique.append(c)
            continue
        is_dup = any(k in seen for k in keys)
        if not is_dup:
            unique.append(c)
            seen.update(keys)
    return unique


# =============================================================================
# Excel Output
# =============================================================================

def write_excel(centers, filename):
    """Write centers to a formatted Excel file."""
    print(f"\nWriting {len(centers):,} centers to {filename}...")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Centres Médicaux France"

    headers = [
        ("N°", 7),
        ("Nom de l'établissement", 45),
        ("Adresse", 40),
        ("Code Postal", 12),
        ("Ville", 25),
        ("Département N°", 14),
        ("Département", 24),
        ("Région", 28),
        ("Téléphone (International)", 28),
        ("Téléphone (Original)", 20),
        ("Fax", 18),
        ("Email", 30),
        ("SIREN", 15),
        ("SIRET", 18),
        ("N° FINESS", 15),
        ("Catégorie", 40),
        ("Source", 18),
    ]

    # Styles
    header_font = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color="1A5276", end_color="1A5276", fill_type="solid")
    header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )
    data_font = Font(name="Calibri", size=10)
    data_alignment = Alignment(vertical="center", wrap_text=False)

    for col, (header_text, width) in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header_text)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border
        ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = width

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{openpyxl.utils.get_column_letter(len(headers))}1"

    # Sort by region, department, city, name
    centers.sort(key=lambda x: (
        x.get("region") or "",
        x.get("department_num") or "",
        x.get("city") or "",
        x.get("name") or "",
    ))

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
            center.get("region", ""),
            center.get("phone_international", ""),
            center.get("phone", ""),
            center.get("fax", ""),
            center.get("email", ""),
            center.get("siren", ""),
            center.get("siret", ""),
            center.get("finess", ""),
            center.get("category_label", ""),
            center.get("source", ""),
        ]
        row_fill = PatternFill(start_color="EBF5FB", end_color="EBF5FB", fill_type="solid") if idx % 2 == 0 else PatternFill(fill_type=None)
        for col, val in enumerate(values, 1):
            cell = ws.cell(row=row, column=col, value=val)
            cell.font = data_font
            cell.alignment = data_alignment
            cell.border = thin_border
            cell.fill = row_fill

    # ---- Summary sheet ----
    ws_s = wb.create_sheet("Résumé")
    ws_s.column_dimensions["A"].width = 40
    ws_s.column_dimensions["B"].width = 15

    summary = [
        ("=== STATISTIQUES GÉNÉRALES ===", ""),
        ("Total centres médicaux", len(centers)),
        ("Avec téléphone", sum(1 for c in centers if c.get("phone_international"))),
        ("Avec SIRET", sum(1 for c in centers if c.get("siret"))),
        ("Avec SIREN", sum(1 for c in centers if c.get("siren"))),
        ("Avec N° FINESS", sum(1 for c in centers if c.get("finess"))),
        ("", ""),
    ]

    # By region
    summary.append(("=== PAR RÉGION ===", ""))
    region_counts = {}
    for c in centers:
        r = c.get("region") or "Inconnu"
        region_counts[r] = region_counts.get(r, 0) + 1
    for r, count in sorted(region_counts.items()):
        summary.append((f"  {r}", count))

    summary.extend([("", ""), ("=== PAR DÉPARTEMENT (top 20) ===", "")])
    dept_counts = {}
    for c in centers:
        d = f"{c.get('department_num', '??')} - {c.get('department_name', '??')}"
        dept_counts[d] = dept_counts.get(d, 0) + 1
    for d, count in sorted(dept_counts.items(), key=lambda x: -x[1])[:20]:
        summary.append((f"  {d}", count))

    summary.extend([("", ""), ("=== PAR SOURCE ===", "")])
    source_counts = {}
    for c in centers:
        s = c.get("source", "?")
        source_counts[s] = source_counts.get(s, 0) + 1
    for s, count in sorted(source_counts.items()):
        summary.append((f"  {s}", count))

    for row_idx, (label, value) in enumerate(summary, 1):
        cell_a = ws_s.cell(row=row_idx, column=1, value=label)
        cell_a.font = Font(name="Calibri", bold=("===" in str(label)), size=11)
        if value != "":
            ws_s.cell(row=row_idx, column=2, value=value).font = Font(name="Calibri", size=11)

    wb.save(filename)
    print(f"  Saved to {filename}")


# =============================================================================
# Main
# =============================================================================

def main():
    print("=" * 70)
    print("  CENTRES MÉDICAUX DE FRANCE - Construction de la liste complète")
    print("=" * 70)
    print()

    all_centers = []

    # -----------------------------------------------------------------
    # Phase 1: FINESS (all of France)
    # -----------------------------------------------------------------
    print("PHASE 1: Téléchargement des données FINESS (toute la France)")
    print("-" * 55)

    finess_urls = find_finess_download_urls()
    finess_centers = []

    for candidate in finess_urls:
        result = download_finess_data(candidate["url"])
        if result:
            text, enc = result
            finess_centers = parse_finess_csv(text)
            if finess_centers:
                all_centers.extend(finess_centers)
                print(f"  → {len(finess_centers):,} centres médicaux trouvés dans FINESS")
                break
        print(f"  [WARNING] Trying next resource...")

    if not finess_centers:
        print("  [WARNING] Could not load FINESS data")
    print()

    # -----------------------------------------------------------------
    # Phase 2: Enterprise API (all departments)
    # -----------------------------------------------------------------
    print("PHASE 2: Recherche complémentaire via l'API Entreprises")
    print("-" * 55)

    api_centers = []
    dept_list = sorted(DEPARTMENTS.keys(), key=lambda x: x.zfill(3))
    total_depts = len(dept_list)

    for i, dept in enumerate(dept_list, 1):
        dept_name, region = DEPARTMENTS[dept]
        print(f"  [{i:3d}/{total_depts}] {dept} - {dept_name} ({region})...", end=" ", flush=True)
        results = search_medical_centers_api(dept)
        api_centers.extend(results)
        print(f"{len(results)} résultats")
        time.sleep(0.2)

    all_centers.extend(api_centers)
    print(f"\n  → {len(api_centers):,} centres trouvés via l'API Entreprises")
    print()

    # -----------------------------------------------------------------
    # Phase 3: Deduplication
    # -----------------------------------------------------------------
    print("PHASE 3: Déduplication")
    print("-" * 55)
    print(f"  Total avant: {len(all_centers):,}")
    all_centers = deduplicate_centers(all_centers)
    print(f"  Total après: {len(all_centers):,}")
    print()

    # -----------------------------------------------------------------
    # Phase 4: SIRET enrichment
    # -----------------------------------------------------------------
    print("PHASE 4: Enrichissement SIRET pour les entrées manquantes")
    print("-" * 55)

    cache = load_cache()
    missing = [c for c in all_centers if not c.get("siret")]
    print(f"  {len(missing):,} centres sans SIRET")

    enriched = 0
    for i, center in enumerate(missing):
        name = center.get("name", "")
        cp = center.get("postal_code", "")
        city = center.get("city", "")
        cache_key = f"{name}|{cp}|{city}"

        if cache_key in cache:
            result = cache[cache_key]
        else:
            result, _ = search_enterprise_api(name, cp, city)
            cache[cache_key] = result
            time.sleep(0.12)

        if result and result.get("siret"):
            center["siret"] = result["siret"]
            center["siren"] = result.get("siren", "")
            enriched += 1

        if (i + 1) % 100 == 0:
            pct = (i + 1) / len(missing) * 100
            print(f"    {i+1:,}/{len(missing):,} ({pct:.0f}%) | SIRET trouvés: {enriched}")
            save_cache(cache)

    save_cache(cache)
    print(f"  → {enriched} SIRET supplémentaires trouvés")
    print()

    # -----------------------------------------------------------------
    # Phase 5: Output
    # -----------------------------------------------------------------
    print("PHASE 5: Génération du fichier Excel")
    print("-" * 55)
    write_excel(all_centers, OUTPUT_FILE)

    # Summary
    print()
    print("=" * 70)
    print("  RÉSUMÉ FINAL")
    print("=" * 70)
    print(f"  Total centres médicaux : {len(all_centers):,}")
    print(f"  Avec téléphone         : {sum(1 for c in all_centers if c.get('phone_international')):,}")
    print(f"  Avec SIRET             : {sum(1 for c in all_centers if c.get('siret')):,}")
    print(f"  Avec N° FINESS         : {sum(1 for c in all_centers if c.get('finess')):,}")
    print()

    # Top regions
    print("  Par région:")
    region_counts = {}
    for c in all_centers:
        r = c.get("region") or "Inconnu"
        region_counts[r] = region_counts.get(r, 0) + 1
    for r, count in sorted(region_counts.items(), key=lambda x: -x[1]):
        print(f"    {r}: {count:,}")

    print()
    print(f"  Fichier: {OUTPUT_FILE}")
    print("=" * 70)

    # Cleanup
    if os.path.exists(CACHE_FILE):
        os.remove(CACHE_FILE)


if __name__ == "__main__":
    main()
