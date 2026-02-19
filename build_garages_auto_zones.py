#!/usr/bin/env python3
"""
Build a comprehensive list of auto garages in specific French departments,
categorized by "Top Zone" and "Middle Zone".

Data sources:
1. recherche-entreprises.api.gouv.fr - French government enterprise API
   → Provides: name, address, SIREN, SIRET, NAF code
2. annuaire-entreprises.data.gouv.fr - Enrichment API
   → Provides: phone numbers (when available)

Output: Excel file with all garages sorted by zone, department, city.
"""

import requests
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

ENTERPRISE_API_URL = "https://recherche-entreprises.api.gouv.fr/search"
ANNUAIRE_API_URL = "https://annuaire-entreprises.data.gouv.fr/api/rne/v1/full"

CACHE_FILE = "garages_auto_cache.json"
PHONE_CACHE_FILE = "garages_phone_cache.json"
OUTPUT_FILE = "garages_auto_zones_france.xlsx"

# NAF codes for auto garages
NAF_CODES = {
    "45.20A": "Entretien et réparation de véhicules automobiles légers",
    "45.20B": "Entretien et réparation d'autres véhicules automobiles",
}

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
    "971": ("Guadeloupe", "Guadeloupe"),
    "972": ("Martinique", "Martinique"),
    "973": ("Guyane", "Guyane"),
    "974": ("La Réunion", "La Réunion"),
    "976": ("Mayotte", "Mayotte"),
}

# Zone definitions
TOP_ZONE_DEPTS = ["06", "59", "60", "77", "78", "88", "91", "93", "95"]

MIDDLE_ZONE_DEPTS = [
    "17", "24", "27", "28", "30", "31", "33", "35", "38", "40", "41", "42",
    "44", "45", "46", "57", "62", "67", "72", "73", "76", "79", "80", "83",
    "86", "971", "973",
]


# =============================================================================
# Helper functions
# =============================================================================

def get_dept_name(dept_num):
    """Get department name from department number."""
    info = DEPARTMENTS.get(dept_num)
    return info[0] if info else dept_num


def get_region(dept_num):
    """Get region name from department number."""
    info = DEPARTMENTS.get(dept_num)
    return info[1] if info else ""


def get_zone(dept_num):
    """Get zone label for a department."""
    if dept_num in TOP_ZONE_DEPTS:
        return "Top Zone"
    elif dept_num in MIDDLE_ZONE_DEPTS:
        return "Middle Zone"
    return ""


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


def get_dept_from_postal(postal_code):
    """Extract department number from a postal code."""
    cp = str(postal_code or "").strip()
    if not cp:
        return ""
    if cp[:3] in ("971", "972", "973", "974", "976"):
        return cp[:3]
    if len(cp) >= 2:
        return cp[:2]
    return ""


# =============================================================================
# Cache functions
# =============================================================================

def load_cache(filepath):
    """Load cache from JSON file."""
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def save_cache(cache, filepath):
    """Save cache to JSON file."""
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)


# =============================================================================
# API Functions
# =============================================================================

def search_garages_by_department(department):
    """Fetch ALL garages for a department using NAF code filter."""
    all_results = []
    seen_sirets = set()
    page = 1
    max_pages = 500  # Safety limit

    while page <= max_pages:
        params = {
            "activite_principale": "45.20A,45.20B",
            "departement": department,
            "etat_administratif": "A",
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

            total = data.get("total_results", 0)

            for r in results:
                garage = extract_garage_data(r, department)
                if garage:
                    siret = garage.get("siret", "")
                    siren = garage.get("siren", "")
                    dedup_key = siret if siret else siren
                    if dedup_key and dedup_key in seen_sirets:
                        continue
                    if dedup_key:
                        seen_sirets.add(dedup_key)
                    all_results.append(garage)

            if page * 25 >= total:
                break
            page += 1
            time.sleep(0.15)  # Rate limiting: ~6.7 req/s

        except requests.exceptions.Timeout:
            print(f"      [TIMEOUT] page {page}, retrying...")
            time.sleep(2)
            continue
        except Exception as e:
            print(f"      [ERROR] page {page}: {e}")
            break

    return all_results


def extract_garage_data(result, target_department):
    """Extract garage data from an API result."""
    siren = result.get("siren", "")
    nom = result.get("nom_complet", "")
    naf_code = result.get("activite_principale", "")
    naf_label = NAF_CODES.get(naf_code, naf_code)
    nombre_etablissements = result.get("nombre_etablissements", 1)

    siege = result.get("siege", {})
    siret = siege.get("siret", "")
    addr = siege.get("adresse", "")
    cp = str(siege.get("code_postal", "") or "")
    city = siege.get("libelle_commune", "")

    # Determine actual department from siege
    actual_dept = get_dept_from_postal(cp)

    # If siege not in target department, look at matching_etablissements
    if actual_dept != target_department:
        found = False
        for etab in result.get("matching_etablissements", []):
            etab_cp = str(etab.get("code_postal", "") or "")
            etab_dept = get_dept_from_postal(etab_cp)
            if etab_dept == target_department:
                addr = etab.get("adresse", "") or addr
                cp = etab_cp
                city = etab.get("libelle_commune", "") or city
                siret = etab.get("siret", "") or siret
                actual_dept = etab_dept
                found = True
                break
        if not found:
            return None  # Not actually in target department

    # Clean address: remove trailing postal code + city
    if addr and cp and city:
        suffix = f"{cp} {city}"
        if addr.endswith(suffix):
            addr = addr[:-len(suffix)].strip().rstrip(",")
        elif addr.endswith(cp):
            addr = addr[:-len(cp)].strip().rstrip(",")

    zone = get_zone(actual_dept)

    return {
        "name": nom,
        "address": addr,
        "postal_code": cp,
        "city": city,
        "department_num": actual_dept,
        "department_name": get_dept_name(actual_dept),
        "region": get_region(actual_dept),
        "zone": zone,
        "phone": "",
        "phone_international": "",
        "email": "",
        "siren": siren,
        "siret": siret,
        "naf_code": naf_code,
        "naf_label": naf_label,
        "nombre_etablissements": nombre_etablissements,
        "source": "API Entreprises",
    }


# =============================================================================
# Phone Enrichment
# =============================================================================

def enrich_phone_for_siren(siren, phone_cache):
    """Try to get phone number from annuaire-entreprises API for a SIREN."""
    if not siren:
        return "", ""

    # Check cache
    if siren in phone_cache:
        cached = phone_cache[siren]
        return cached.get("phone", ""), cached.get("email", "")

    url = f"{ANNUAIRE_API_URL}/{siren}"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            # Try to extract phone from RNE data
            phone = ""
            email = ""

            # The RNE data may contain contact info in various fields
            complements = data.get("complements", {})
            if isinstance(complements, dict):
                phone = complements.get("telephone", "") or ""
                email = complements.get("email", "") or ""

            # Also check in dirigeants/beneficiaires for phone
            if not phone:
                identite = data.get("identite", {})
                if isinstance(identite, dict):
                    phone = identite.get("telephone", "") or ""
                    if not email:
                        email = identite.get("email", "") or ""

            phone_cache[siren] = {"phone": phone, "email": email}
            return phone, email

        elif resp.status_code == 404:
            phone_cache[siren] = {"phone": "", "email": ""}
            return "", ""
        elif resp.status_code == 429:
            time.sleep(3)
            return enrich_phone_for_siren(siren, phone_cache)
        else:
            phone_cache[siren] = {"phone": "", "email": ""}
            return "", ""

    except requests.exceptions.Timeout:
        return "", ""
    except Exception:
        phone_cache[siren] = {"phone": "", "email": ""}
        return "", ""


def enrich_garages_with_phones(garages):
    """Enrich garages with phone numbers from annuaire-entreprises."""
    print(f"\nPHASE 2: Enrichissement téléphonique ({len(garages):,} garages)")
    print("-" * 55)

    phone_cache = load_cache(PHONE_CACHE_FILE)
    enriched_count = 0
    cached_count = 0
    total = len(garages)
    save_interval = 100

    for i, garage in enumerate(garages):
        siren = garage.get("siren", "")
        if not siren:
            continue

        was_cached = siren in phone_cache
        phone, email = enrich_phone_for_siren(siren, phone_cache)

        if phone:
            garage["phone"] = phone
            garage["phone_international"] = format_phone_international(phone)
            enriched_count += 1
        if email:
            garage["email"] = email

        if was_cached:
            cached_count += 1
        else:
            time.sleep(0.2)  # Rate limit for new API calls

        # Progress display
        if (i + 1) % 500 == 0 or (i + 1) == total:
            pct = (i + 1) / total * 100
            print(f"  [{i + 1:,}/{total:,}] ({pct:.1f}%) "
                  f"- {enriched_count:,} téléphones trouvés "
                  f"- {cached_count:,} en cache")

        # Save cache periodically
        if (i + 1) % save_interval == 0:
            save_cache(phone_cache, PHONE_CACHE_FILE)

    save_cache(phone_cache, PHONE_CACHE_FILE)
    print(f"\n  Résultat enrichissement:")
    print(f"    Téléphones trouvés: {enriched_count:,} / {total:,}")
    print(f"    Emails trouvés: {sum(1 for g in garages if g.get('email')):,}")

    return garages


# =============================================================================
# Deduplication
# =============================================================================

def deduplicate_garages(garages):
    """Remove duplicates based on SIRET or SIREN + name."""
    seen = set()
    unique = []
    for g in garages:
        keys = []
        if g.get("siret"):
            keys.append(f"siret:{g['siret']}")
        if g.get("siren"):
            keys.append(f"siren:{g['siren']}")
        if g.get("name") and g.get("postal_code"):
            name_norm = re.sub(r"[^a-z0-9]", "", g["name"].lower())
            keys.append(f"name_cp:{name_norm}:{g['postal_code']}")
        if not keys:
            unique.append(g)
            continue
        is_dup = any(k in seen for k in keys)
        if not is_dup:
            unique.append(g)
            seen.update(keys)
    return unique


# =============================================================================
# Excel Output
# =============================================================================

def write_excel(garages, filename):
    """Write garages to a formatted Excel file."""
    print(f"\nÉcriture de {len(garages):,} garages dans {filename}...")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Garages Auto par Zones"

    headers = [
        ("N°", 7),
        ("Nom de l'établissement", 45),
        ("Adresse", 40),
        ("Code Postal", 12),
        ("Ville", 25),
        ("Département N°", 14),
        ("Département", 24),
        ("Région", 28),
        ("Zone", 15),
        ("Téléphone (International)", 28),
        ("Téléphone (Original)", 20),
        ("Email", 30),
        ("SIREN", 15),
        ("SIRET", 18),
        ("Code NAF", 12),
        ("Activité", 50),
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

    # Write headers
    for col, (header_text, width) in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header_text)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border
        ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = width

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{openpyxl.utils.get_column_letter(len(headers))}1"

    # Sort: Zone (Top first) → Department → City → Name
    garages.sort(key=lambda x: (
        0 if x.get("zone") == "Top Zone" else 1,
        x.get("department_num", "").zfill(3),
        x.get("city") or "",
        x.get("name") or "",
    ))

    # Zone color fills
    top_zone_fill = PatternFill(start_color="E8F8F5", end_color="E8F8F5", fill_type="solid")
    mid_zone_fill = PatternFill(start_color="EBF5FB", end_color="EBF5FB", fill_type="solid")

    for idx, garage in enumerate(garages, 1):
        row = idx + 1
        values = [
            idx,
            garage.get("name", ""),
            garage.get("address", ""),
            garage.get("postal_code", ""),
            garage.get("city", ""),
            garage.get("department_num", ""),
            garage.get("department_name", ""),
            garage.get("region", ""),
            garage.get("zone", ""),
            garage.get("phone_international", ""),
            garage.get("phone", ""),
            garage.get("email", ""),
            garage.get("siren", ""),
            garage.get("siret", ""),
            garage.get("naf_code", ""),
            garage.get("naf_label", ""),
            garage.get("source", ""),
        ]

        # Alternate fill by zone
        zone = garage.get("zone", "")
        if zone == "Top Zone":
            row_fill = top_zone_fill if idx % 2 == 0 else PatternFill(fill_type=None)
        else:
            row_fill = mid_zone_fill if idx % 2 == 0 else PatternFill(fill_type=None)

        for col, val in enumerate(values, 1):
            cell = ws.cell(row=row, column=col, value=val)
            cell.font = data_font
            cell.alignment = data_alignment
            cell.border = thin_border
            cell.fill = row_fill

    # ---- Summary sheet ----
    ws_s = wb.create_sheet("Résumé")
    ws_s.column_dimensions["A"].width = 45
    ws_s.column_dimensions["B"].width = 15

    summary = [
        ("=== STATISTIQUES GÉNÉRALES ===", ""),
        ("Total garages automobiles", len(garages)),
        ("Avec téléphone", sum(1 for g in garages if g.get("phone_international"))),
        ("Avec email", sum(1 for g in garages if g.get("email"))),
        ("Avec SIRET", sum(1 for g in garages if g.get("siret"))),
        ("Avec SIREN", sum(1 for g in garages if g.get("siren"))),
        ("", ""),
        ("=== PAR ZONE ===", ""),
    ]

    # By zone
    top_count = sum(1 for g in garages if g.get("zone") == "Top Zone")
    mid_count = sum(1 for g in garages if g.get("zone") == "Middle Zone")
    summary.append(("  Top Zone", top_count))
    summary.append(("  Middle Zone", mid_count))

    # By NAF code
    summary.extend([("", ""), ("=== PAR CODE NAF ===", "")])
    naf_counts = {}
    for g in garages:
        naf = g.get("naf_code", "?")
        label = g.get("naf_label", "")
        key = f"{naf} - {label}" if label else naf
        naf_counts[key] = naf_counts.get(key, 0) + 1
    for naf, count in sorted(naf_counts.items()):
        summary.append((f"  {naf}", count))

    # By region
    summary.extend([("", ""), ("=== PAR RÉGION ===", "")])
    region_counts = {}
    for g in garages:
        r = g.get("region") or "Inconnu"
        region_counts[r] = region_counts.get(r, 0) + 1
    for r, count in sorted(region_counts.items()):
        summary.append((f"  {r}", count))

    # By department (all)
    summary.extend([("", ""), ("=== PAR DÉPARTEMENT ===", "")])
    dept_counts = {}
    for g in garages:
        d = f"{g.get('department_num', '??')} - {g.get('department_name', '??')}"
        dept_counts[d] = dept_counts.get(d, 0) + 1
    for d, count in sorted(dept_counts.items(), key=lambda x: -x[1]):
        summary.append((f"  {d}", count))

    # Write summary
    summary_header_font = Font(name="Calibri", bold=True, size=12, color="1A5276")
    summary_data_font = Font(name="Calibri", size=11)

    for row_idx, (label, value) in enumerate(summary, 1):
        cell_a = ws_s.cell(row=row_idx, column=1, value=label)
        if "===" in str(label):
            cell_a.font = summary_header_font
        else:
            cell_a.font = summary_data_font
        if value != "":
            cell_b = ws_s.cell(row=row_idx, column=2, value=value)
            cell_b.font = summary_data_font
            cell_b.alignment = Alignment(horizontal="right")

    wb.save(filename)
    print(f"  Fichier sauvegardé: {filename}")


# =============================================================================
# Main
# =============================================================================

def main():
    print("=" * 70)
    print("  GARAGES AUTOMOBILES PAR ZONES - France")
    print("  NAF 45.20A + 45.20B")
    print("=" * 70)
    print()

    # Build ordered department list
    all_depts = []
    for d in TOP_ZONE_DEPTS:
        all_depts.append((d, "Top Zone"))
    for d in MIDDLE_ZONE_DEPTS:
        all_depts.append((d, "Middle Zone"))

    # Sort by department number for consistent ordering
    all_depts.sort(key=lambda x: x[0].zfill(3))

    all_garages = []
    cache = load_cache(CACHE_FILE)
    total_depts = len(all_depts)

    # -----------------------------------------------------------------
    # Phase 1: Fetch garages from API
    # -----------------------------------------------------------------
    print("PHASE 1: Collecte des garages via l'API Entreprises")
    print("-" * 55)

    for i, (dept, zone) in enumerate(all_depts, 1):
        dept_name = get_dept_name(dept)
        print(f"  [{i:2d}/{total_depts}] {dept} - {dept_name} ({zone})...", end=" ", flush=True)

        if dept in cache:
            garages = cache[dept]
            print(f"{len(garages):,} garages (en cache)")
        else:
            garages = search_garages_by_department(dept)
            cache[dept] = garages
            save_cache(cache, CACHE_FILE)
            print(f"{len(garages):,} garages")

        all_garages.extend(garages)

    print(f"\n  Total brut: {len(all_garages):,} garages")

    # -----------------------------------------------------------------
    # Phase 1b: Deduplication
    # -----------------------------------------------------------------
    print("\n  Déduplication...")
    before = len(all_garages)
    all_garages = deduplicate_garages(all_garages)
    after = len(all_garages)
    print(f"  {before:,} → {after:,} (supprimé {before - after:,} doublons)")

    # -----------------------------------------------------------------
    # Phase 2: Phone enrichment (skipped - API does not provide phone data)
    # -----------------------------------------------------------------
    # Note: The annuaire-entreprises.data.gouv.fr RNE API was tested but
    # does not return phone numbers for garage businesses.
    # all_garages = enrich_garages_with_phones(all_garages)
    print("\nPHASE 2: Enrichissement téléphonique (ignoré)")
    print("-" * 55)
    print("  L'API annuaire-entreprises ne contient pas de données")
    print("  téléphoniques pour les garages automobiles.")

    # -----------------------------------------------------------------
    # Phase 3: Excel generation
    # -----------------------------------------------------------------
    print("\nPHASE 3: Génération du fichier Excel")
    print("-" * 55)
    write_excel(all_garages, OUTPUT_FILE)

    # -----------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  RÉSUMÉ FINAL")
    print("=" * 70)

    top_count = sum(1 for g in all_garages if g.get("zone") == "Top Zone")
    mid_count = sum(1 for g in all_garages if g.get("zone") == "Middle Zone")
    phone_count = sum(1 for g in all_garages if g.get("phone_international"))
    siret_count = sum(1 for g in all_garages if g.get("siret"))

    print(f"  Total garages: {len(all_garages):,}")
    print(f"    Top Zone:    {top_count:,}")
    print(f"    Middle Zone: {mid_count:,}")
    print(f"  Avec téléphone: {phone_count:,}")
    print(f"  Avec SIRET:     {siret_count:,}")
    print(f"\n  Fichier: {OUTPUT_FILE}")

    # Cleanup caches
    for cache_file in [CACHE_FILE, PHONE_CACHE_FILE]:
        if os.path.exists(cache_file):
            os.remove(cache_file)
            print(f"  Cache supprimé: {cache_file}")

    print("\nTerminé!")


if __name__ == "__main__":
    main()
