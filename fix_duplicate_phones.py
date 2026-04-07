#!/usr/bin/env python3
"""
Fix duplicate phone numbers in enriched company files.

Strategy:
1. Remove known fake numbers (+33 1 23 45 67 89)
2. For each duplicate phone, keep it only on the company with the best match:
   - If same SIREN (first 9 digits of SIRET) -> keep all (same company, multiple locations)
   - Otherwise, keep the one with best source quality (PagesJaunes > OSM > 118000.fr)
   - Among same source quality, keep the one where phone was likely the real match
3. Clear the phone from all other entries
"""

import json
import re
import os
from collections import Counter, defaultdict
from difflib import SequenceMatcher

# Known fake/test numbers to always remove
FAKE_NUMBERS = {
    "+33 1 23 45 67 89",
    "+33 0 12 34 56 78",
    "+33 1 11 11 11 11",
}

# Source quality ranking (higher = more trustworthy)
SOURCE_RANK = {
    "PagesJaunes": 4,
    "OSM": 3,
    "OpenStreetMap": 3,
    "WebSearch": 2,
    "PagesJaunes/118000.fr": 1,
    "118000.fr": 0,
}


def get_source_rank(company):
    """Get source quality rank for a company's phone."""
    src = company.get("source_telephone", company.get("source", ""))
    for key, rank in SOURCE_RANK.items():
        if key in src:
            return rank
    return 0


def get_siren(company):
    """Extract SIREN (first 9 digits) from SIRET."""
    siret = str(company.get("siret", "")).replace(" ", "")
    if len(siret) >= 9:
        return siret[:9]
    return None


def name_similarity(name, phone_owner_name):
    """How similar are two company names."""
    if not name or not phone_owner_name:
        return 0
    return SequenceMatcher(None, name.lower(), phone_owner_name.lower()).ratio()


def fix_duplicates(companies):
    """Fix duplicate phone numbers in a list of companies."""
    # Index phones
    phone_groups = defaultdict(list)
    for i, c in enumerate(companies):
        tel = c.get("telephone", "").strip()
        if tel:
            phone_groups[tel].append(i)

    stats = {
        "fake_removed": 0,
        "duplicates_removed": 0,
        "kept_same_siren": 0,
        "phones_before": sum(1 for c in companies if c.get("telephone", "").strip()),
    }

    # Remove fake numbers
    for fake in FAKE_NUMBERS:
        if fake in phone_groups:
            for idx in phone_groups[fake]:
                companies[idx]["telephone"] = ""
                stats["fake_removed"] += 1
            del phone_groups[fake]

    # Process each duplicate group
    for phone, indices in phone_groups.items():
        if len(indices) <= 1:
            continue

        entries = [(idx, companies[idx]) for idx in indices]

        # Check if all from same SIREN (legit multi-location)
        sirens = set()
        for idx, c in entries:
            s = get_siren(c)
            if s:
                sirens.add(s)

        if len(sirens) == 1 and sirens != {None}:
            # Same company, multiple locations - keep all
            stats["kept_same_siren"] += len(entries)
            continue

        # Group by SIREN - keep phone for each unique SIREN group's best entry
        siren_groups = defaultdict(list)
        for idx, c in entries:
            s = get_siren(c) or f"unknown_{idx}"
            siren_groups[s].append((idx, c))

        # If multiple SIRENs share the same phone, it's contamination
        # Keep only the one with the best source quality
        best_idx = None
        best_score = -1

        for idx, c in entries:
            score = get_source_rank(c) * 100
            # Bonus: if company has other data (email, website) it's more likely legit
            if c.get("email"):
                score += 10
            if c.get("site_web"):
                score += 10
            # Bonus: if it has a PJ ID, the phone likely came from a real PJ listing
            if c.get("id_pagesjaunes"):
                score += 20

            if score > best_score:
                best_score = score
                best_idx = idx

        # Clear phone from all except the best match
        for idx, c in entries:
            if idx != best_idx:
                c["telephone"] = ""
                c["source_telephone"] = c.get("source_telephone", "").replace(
                    "supprimé (doublon)", ""
                )
                if c.get("source_telephone"):
                    c["source_telephone"] += " | supprimé (doublon)"
                else:
                    c["source_telephone"] = "supprimé (doublon)"
                stats["duplicates_removed"] += 1

    stats["phones_after"] = sum(1 for c in companies if c.get("telephone", "").strip())
    return companies, stats


def process_file(filepath):
    """Process a single JSON file."""
    print(f"\n{'='*60}")
    print(f"Traitement: {os.path.basename(filepath)}")
    print(f"{'='*60}")

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Handle dict or list structure
    is_dict = isinstance(data, dict)
    if is_dict:
        companies = data.get("entreprises", data.get("results", []))
    else:
        companies = data

    print(f"Total entreprises: {len(companies)}")

    companies, stats = fix_duplicates(companies)

    print(f"Telephones avant:       {stats['phones_before']}")
    print(f"Faux numeros supprimes: {stats['fake_removed']}")
    print(f"Doublons supprimes:     {stats['duplicates_removed']}")
    print(f"Gardes (meme SIREN):    {stats['kept_same_siren']}")
    print(f"Telephones apres:       {stats['phones_after']}")

    # Save
    if is_dict:
        data["entreprises"] = companies
        save_data = data
    else:
        save_data = companies

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(save_data, f, ensure_ascii=False, indent=2)

    print(f"Sauvegarde: {filepath}")
    return stats


def generate_excel(json_path, xlsx_path):
    """Generate Excel from JSON."""
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    except ImportError:
        print(f"  openpyxl non disponible, Excel non genere pour {xlsx_path}")
        return

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict):
        companies = data.get("entreprises", data.get("results", []))
    else:
        companies = data

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Entreprises"

    # Headers
    headers = [
        "Nom", "SIRET", "SIREN", "Adresse", "Code Postal", "Ville",
        "Activite", "NAF", "Type", "Telephone", "Email", "Site Web",
        "Source", "Source Telephone", "ID PagesJaunes"
    ]
    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True, size=11)
    thin_border = Border(
        left=Side(style='thin'), right=Side(style='thin'),
        top=Side(style='thin'), bottom=Side(style='thin')
    )

    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")
        cell.border = thin_border

    # Data rows
    for row_idx, c in enumerate(companies, 2):
        siret = str(c.get("siret", ""))
        siren = siret[:9] if len(siret) >= 9 else ""
        values = [
            c.get("nom", ""),
            siret,
            siren,
            c.get("adresse", c.get("adresse_complete", "")),
            c.get("code_postal", ""),
            c.get("ville", ""),
            c.get("activite", c.get("activite_principale", "")),
            c.get("naf", c.get("code_naf", "")),
            c.get("type", c.get("categorie", "")),
            c.get("telephone", ""),
            c.get("email", ""),
            c.get("site_web", ""),
            c.get("source", ""),
            c.get("source_telephone", ""),
            c.get("id_pagesjaunes", ""),
        ]
        for col, val in enumerate(values, 1):
            cell = ws.cell(row=row_idx, column=col, value=str(val) if val else "")
            cell.border = thin_border
            # SIRET/SIREN as text
            if col in (2, 3):
                cell.number_format = '@'

    # Auto-width
    for col in range(1, len(headers) + 1):
        max_len = len(str(ws.cell(row=1, column=col).value))
        for row in range(2, min(102, ws.max_row + 1)):
            val = ws.cell(row=row, column=col).value
            if val:
                max_len = max(max_len, min(len(str(val)), 50))
        ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = max_len + 3

    # Freeze header
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    wb.save(xlsx_path)
    print(f"Excel genere: {xlsx_path}")


if __name__ == "__main__":
    files = [
        "/home/user/Website01/entreprises_auto_moto_lille_lyon_bordeaux_enriched.json",
        "/home/user/Website01/entreprises_auto_moto_evry_toulouse_area.json",
    ]

    for filepath in files:
        if os.path.exists(filepath):
            process_file(filepath)

    # Regenerate Excel
    print("\n" + "=" * 60)
    print("REGENERATION EXCEL")
    print("=" * 60)

    for json_path in files:
        if os.path.exists(json_path):
            xlsx_path = json_path.replace(".json", ".xlsx")
            generate_excel(json_path, xlsx_path)

    print("\nTermine!")
