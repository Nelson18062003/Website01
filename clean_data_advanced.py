#!/usr/bin/env python3
"""
Nettoyage avancé et export Excel de qualité pour les fichiers entreprises.
Supprime toutes les erreurs d'enrichissement et produit des fichiers propres.
"""

import json
import re
import os
from collections import defaultdict
from difflib import SequenceMatcher

# ============================================================
# CONFIG
# ============================================================

FILES = [
    "/home/user/Website01/entreprises_auto_moto_lille_lyon_bordeaux_enriched.json",
    "/home/user/Website01/entreprises_auto_moto_evry_toulouse_area.json",
]

# Département → indicatif téléphonique attendu
DEPT_TO_AREA = {
    # +33 1 = Ile-de-France
    "75": "1", "77": "1", "78": "1", "91": "1", "92": "1", "93": "1", "94": "1", "95": "1",
    # +33 2 = Nord-Ouest
    "14": "2", "22": "2", "27": "2", "28": "2", "29": "2", "35": "2", "36": "2", "37": "2",
    "41": "2", "44": "2", "45": "2", "49": "2", "50": "2", "53": "2", "56": "2", "61": "2",
    "72": "2", "76": "2", "85": "2",
    # +33 3 = Nord-Est
    "02": "3", "08": "3", "10": "3", "21": "3", "25": "3", "39": "3", "51": "3", "52": "3",
    "54": "3", "55": "3", "57": "3", "58": "3", "59": "3", "60": "3", "62": "3", "67": "3",
    "68": "3", "70": "3", "71": "3", "80": "3", "88": "3", "89": "3", "90": "3",
    # +33 4 = Sud-Est
    "01": "4", "03": "4", "04": "4", "05": "4", "06": "4", "07": "4", "13": "4", "15": "4",
    "26": "4", "30": "4", "34": "4", "38": "4", "42": "4", "43": "4", "48": "4", "63": "4",
    "66": "4", "69": "4", "73": "4", "74": "4", "83": "4", "84": "4",
    # +33 5 = Sud-Ouest
    "09": "5", "11": "5", "12": "5", "16": "5", "17": "5", "18": "5", "19": "5", "23": "5",
    "24": "5", "31": "5", "32": "5", "33": "5", "40": "5", "46": "5", "47": "5", "64": "5",
    "65": "5", "79": "5", "81": "5", "82": "5", "86": "5", "87": "5",
}

# Faux numéros connus
FAKE_PHONES = {
    "+33 1 23 45 67 89",
    "+33 0 12 34 56 78",
    "+33 1 11 11 11 11",
}

# Placeholder values
PLACEHOLDERS = {"n/a", "na", "null", "undefined", "-", "non trouvé", "non renseigné",
                "none", "inconnu", ".", "...", "//", "http://", "https://"}

SOURCE_RANK = {
    "PagesJaunes": 4,
    "OSM": 3,
    "OpenStreetMap": 3,
    "WebSearch": 2,
    "PagesJaunes/118000.fr": 1,
    "118000.fr": 0,
}


def get_source_rank(company, field_source="source_telephone"):
    src = company.get(field_source, company.get("source", ""))
    for key, rank in SOURCE_RANK.items():
        if key in str(src):
            return rank
    return 0


def get_siren(company):
    siret = str(company.get("siret", "")).replace(" ", "")
    if len(siret) >= 9:
        return siret[:9]
    return None


def get_dept(company):
    cp = str(company.get("code_postal", ""))
    if len(cp) >= 2:
        return cp[:2]
    return None


def is_placeholder(val):
    if not val:
        return True
    return str(val).strip().lower() in PLACEHOLDERS


def is_valid_phone_format(phone):
    """Check +33 X XX XX XX XX format."""
    return bool(re.match(r'^\+33 [1-9] \d{2} \d{2} \d{2} \d{2}$', phone))


def is_premium_number(phone):
    """08xx = numéros surtaxés/service."""
    return bool(re.match(r'^\+33 8', phone))


def phone_matches_region(phone, dept):
    """Check if phone area code matches department region."""
    if not phone or not dept:
        return True  # can't check, assume OK
    m = re.match(r'^\+33 (\d)', phone)
    if not m:
        return True
    area = m.group(1)
    # Mobile numbers (6, 7) and VoIP (9) are not geographic
    if area in ("6", "7", "9"):
        return True
    expected = DEPT_TO_AREA.get(dept)
    if not expected:
        return True
    return area == expected


def fix_phone_semicolon(phone):
    """Split phone;phone and return first valid one."""
    if ";" in phone:
        parts = phone.split(";")
        for p in parts:
            p = p.strip()
            # Try to format
            digits = re.sub(r'[^\d]', '', p)
            if digits.startswith("33") and len(digits) == 11:
                formatted = f"+33 {digits[2]} {digits[3:5]} {digits[5:7]} {digits[7:9]} {digits[9:11]}"
                return formatted
            elif digits.startswith("0") and len(digits) == 10:
                formatted = f"+33 {digits[1]} {digits[2:4]} {digits[4:6]} {digits[6:8]} {digits[8:10]}"
                return formatted
        return ""
    return phone


def deduplicate_field(companies, field, source_field=None):
    """Remove duplicate values for a field across different SIRENs. Keep best source."""
    groups = defaultdict(list)
    for i, c in enumerate(companies):
        val = str(c.get(field, "")).strip()
        if val:
            groups[val].append(i)

    removed = 0
    for val, indices in groups.items():
        if len(indices) <= 1:
            continue

        entries = [(idx, companies[idx]) for idx in indices]

        # Check if all same SIREN
        sirens = set()
        for idx, c in entries:
            s = get_siren(c)
            if s:
                sirens.add(s)
        if len(sirens) <= 1 and None not in sirens:
            continue  # Same company, legit

        # Keep best source
        best_idx = None
        best_score = -1
        for idx, c in entries:
            score = get_source_rank(c, source_field or "source") * 100
            if c.get("id_pagesjaunes"):
                score += 20
            if c.get("email") and field != "email":
                score += 10
            if c.get("site_web") and field != "site_web":
                score += 10
            if c.get("telephone") and field != "telephone":
                score += 10
            if score > best_score:
                best_score = score
                best_idx = idx

        for idx, c in entries:
            if idx != best_idx:
                c[field] = ""
                removed += 1

    return removed


def clean_file(filepath):
    """Full cleaning pipeline for one file."""
    print(f"\n{'═' * 60}")
    print(f"  NETTOYAGE: {os.path.basename(filepath)}")
    print(f"{'═' * 60}")

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    is_dict = isinstance(data, dict)
    if is_dict:
        companies = data.get("entreprises", data.get("results", []))
    else:
        companies = data

    total = len(companies)
    stats = {}

    # --- BEFORE stats ---
    phones_before = sum(1 for c in companies if c.get("telephone", "").strip())
    emails_before = sum(1 for c in companies if c.get("email", "").strip())
    sites_before = sum(1 for c in companies if c.get("site_web", "").strip())

    print(f"Total entreprises: {total}")
    print(f"Avant: {phones_before} tél, {emails_before} emails, {sites_before} sites")

    # 1. Clean placeholders
    placeholder_cleaned = 0
    for c in companies:
        for field in ["telephone", "email", "site_web", "code_postal", "ville", "adresse"]:
            if is_placeholder(c.get(field)):
                if c.get(field):
                    c[field] = ""
                    placeholder_cleaned += 1
    stats["placeholders"] = placeholder_cleaned
    print(f"\n1. Placeholders nettoyés: {placeholder_cleaned}")

    # 2. Fix phone formats (semicolons etc)
    phone_format_fixed = 0
    for c in companies:
        tel = c.get("telephone", "").strip()
        if tel and ";" in tel:
            c["telephone"] = fix_phone_semicolon(tel)
            phone_format_fixed += 1
    stats["phone_format"] = phone_format_fixed
    print(f"2. Téléphones format corrigé: {phone_format_fixed}")

    # 3. Remove fake phone numbers
    fake_removed = 0
    for c in companies:
        tel = c.get("telephone", "").strip()
        if tel in FAKE_PHONES:
            c["telephone"] = ""
            fake_removed += 1
    stats["fake_phones"] = fake_removed
    print(f"3. Faux numéros supprimés: {fake_removed}")

    # 4. Remove premium 08xx numbers
    premium_removed = 0
    for c in companies:
        tel = c.get("telephone", "").strip()
        if tel and is_premium_number(tel):
            c["telephone"] = ""
            premium_removed += 1
    stats["premium"] = premium_removed
    print(f"4. Numéros surtaxés 08xx supprimés: {premium_removed}")

    # 5. Remove phones with wrong geographic area code
    geo_removed = 0
    for c in companies:
        tel = c.get("telephone", "").strip()
        dept = get_dept(c)
        if tel and dept and not phone_matches_region(tel, dept):
            c["telephone"] = ""
            geo_removed += 1
    stats["geo_mismatch"] = geo_removed
    print(f"5. Téléphones zone géo incorrecte supprimés: {geo_removed}")

    # 6. Remove invalid phone formats
    invalid_removed = 0
    for c in companies:
        tel = c.get("telephone", "").strip()
        if tel and not is_valid_phone_format(tel):
            c["telephone"] = ""
            invalid_removed += 1
    stats["invalid_format"] = invalid_removed
    print(f"6. Téléphones format invalide supprimés: {invalid_removed}")

    # 7. Deduplicate phones (different SIRENs with same phone)
    phone_dupes = deduplicate_field(companies, "telephone", "source_telephone")
    stats["phone_dupes"] = phone_dupes
    print(f"7. Téléphones doublons inter-entreprises supprimés: {phone_dupes}")

    # 8. Deduplicate emails
    email_dupes = deduplicate_field(companies, "email", "source")
    stats["email_dupes"] = email_dupes
    print(f"8. Emails doublons inter-entreprises supprimés: {email_dupes}")

    # 9. Deduplicate websites
    site_dupes = deduplicate_field(companies, "site_web", "source")
    stats["site_dupes"] = site_dupes
    print(f"9. Sites web doublons inter-entreprises supprimés: {site_dupes}")

    # 10. Deduplicate by SIRET (keep most complete entry)
    siret_groups = defaultdict(list)
    for i, c in enumerate(companies):
        siret = str(c.get("siret", "")).strip()
        if siret:
            siret_groups[siret].append(i)

    siret_dupes_removed = 0
    indices_to_remove = set()
    for siret, indices in siret_groups.items():
        if len(indices) <= 1:
            continue
        # Keep the most complete entry
        best_idx = None
        best_fields = -1
        for idx in indices:
            c = companies[idx]
            filled = sum(1 for f in ["telephone", "email", "site_web", "id_pagesjaunes"]
                         if c.get(f, "").strip())
            if filled > best_fields:
                best_fields = filled
                best_idx = idx
        for idx in indices:
            if idx != best_idx:
                indices_to_remove.add(idx)
                siret_dupes_removed += 1

    if indices_to_remove:
        companies = [c for i, c in enumerate(companies) if i not in indices_to_remove]
    stats["siret_dupes"] = siret_dupes_removed
    print(f"10. Doublons SIRET supprimés: {siret_dupes_removed}")

    # 11. Clean up effectif field
    for c in companies:
        eff = str(c.get("effectif", "")).strip()
        if eff in ("NN", "Non renseigné", "None", ""):
            c["effectif"] = ""

    # --- AFTER stats ---
    phones_after = sum(1 for c in companies if c.get("telephone", "").strip())
    emails_after = sum(1 for c in companies if c.get("email", "").strip())
    sites_after = sum(1 for c in companies if c.get("site_web", "").strip())

    print(f"\n{'─' * 40}")
    print(f"RÉSULTAT:")
    print(f"  Entreprises: {total} → {len(companies)}")
    print(f"  Téléphones:  {phones_before} → {phones_after}")
    print(f"  Emails:      {emails_before} → {emails_after}")
    print(f"  Sites web:   {sites_before} → {sites_after}")

    # Save JSON
    if is_dict:
        data["entreprises"] = companies
        save_data = data
    else:
        save_data = companies

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(save_data, f, ensure_ascii=False, indent=2)

    return companies, stats


def generate_excel_advanced(companies, xlsx_path, title="Entreprises"):
    """Generate a professional Excel with filters, conditional formatting, and data validation."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side, numbers
    from openpyxl.utils import get_column_letter
    from openpyxl.formatting.rule import CellIsRule

    wb = openpyxl.Workbook()

    # ── Sheet 1: All data ──
    ws = wb.active
    ws.title = title

    headers = [
        "Nom", "SIRET", "SIREN", "Adresse", "Code Postal", "Ville",
        "Activité", "Code NAF", "Type", "Effectif",
        "Téléphone", "Email", "Site Web",
        "Source", "Source Téléphone", "ID PagesJaunes",
        "A Téléphone", "A Email", "A Site Web", "Qualité"
    ]

    # Styles
    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True, size=11, name="Calibri")
    data_font = Font(size=10, name="Calibri")
    thin_border = Border(
        left=Side(style='thin', color='D9D9D9'),
        right=Side(style='thin', color='D9D9D9'),
        top=Side(style='thin', color='D9D9D9'),
        bottom=Side(style='thin', color='D9D9D9')
    )
    green_fill = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")
    yellow_fill = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
    red_fill = PatternFill(start_color="FCE4EC", end_color="FCE4EC", fill_type="solid")

    # Headers
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = thin_border
    ws.row_dimensions[1].height = 30

    # Data
    for row_idx, c in enumerate(companies, 2):
        siret = str(c.get("siret", ""))
        siren = siret[:9] if len(siret) >= 9 else ""
        tel = c.get("telephone", "").strip()
        email = c.get("email", "").strip()
        site = c.get("site_web", "").strip()

        # Quality score
        quality_score = 0
        if tel:
            quality_score += 1
        if email:
            quality_score += 1
        if site:
            quality_score += 1
        quality_labels = {0: "Basique", 1: "Standard", 2: "Bon", 3: "Excellent"}
        quality = quality_labels.get(quality_score, "Basique")

        values = [
            c.get("nom", ""),
            siret,
            siren,
            c.get("adresse", c.get("adresse_complete", "")),
            c.get("code_postal", ""),
            c.get("ville", ""),
            c.get("activite", c.get("activite_principale", c.get("libelle_activite", ""))),
            c.get("naf", c.get("code_naf", "")),
            c.get("type", c.get("categorie", "")),
            c.get("effectif", ""),
            tel,
            email,
            site,
            c.get("source", ""),
            c.get("source_telephone", ""),
            c.get("id_pagesjaunes", ""),
            "Oui" if tel else "Non",
            "Oui" if email else "Non",
            "Oui" if site else "Non",
            quality,
        ]

        for col, val in enumerate(values, 1):
            cell = ws.cell(row=row_idx, column=col, value=str(val) if val else "")
            cell.font = data_font
            cell.border = thin_border
            # SIRET/SIREN as text
            if col in (2, 3):
                cell.number_format = '@'
            # Alignment
            if col in (5, 8, 10, 17, 18, 19, 20):
                cell.alignment = Alignment(horizontal="center")

        # Row color by quality
        row_fill = None
        if quality_score >= 2:
            row_fill = green_fill
        elif quality_score == 1:
            row_fill = yellow_fill

        if row_fill:
            for col in range(1, len(headers) + 1):
                ws.cell(row=row_idx, column=col).fill = row_fill

    # Column widths
    col_widths = {
        1: 35, 2: 18, 3: 14, 4: 40, 5: 10, 6: 20,
        7: 30, 8: 10, 9: 15, 10: 12,
        11: 20, 12: 30, 13: 35,
        14: 20, 15: 20, 16: 16,
        17: 12, 18: 10, 19: 12, 20: 12
    }
    for col, width in col_widths.items():
        ws.column_dimensions[get_column_letter(col)].width = width

    # Freeze & filter
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    # ── Sheet 2: Stats summary ──
    ws2 = wb.create_sheet("Statistiques")
    ws2.sheet_properties.tabColor = "1F4E79"

    stat_header_font = Font(bold=True, size=12, name="Calibri", color="1F4E79")
    stat_font = Font(size=11, name="Calibri")

    # Count stats
    total = len(companies)
    with_tel = sum(1 for c in companies if c.get("telephone", "").strip())
    with_email = sum(1 for c in companies if c.get("email", "").strip())
    with_site = sum(1 for c in companies if c.get("site_web", "").strip())

    # By city
    city_counts = {}
    for c in companies:
        ville = c.get("ville", "Inconnue")
        if ville not in city_counts:
            city_counts[ville] = {"total": 0, "tel": 0, "email": 0, "site": 0}
        city_counts[ville]["total"] += 1
        if c.get("telephone", "").strip():
            city_counts[ville]["tel"] += 1
        if c.get("email", "").strip():
            city_counts[ville]["email"] += 1
        if c.get("site_web", "").strip():
            city_counts[ville]["site"] += 1

    # By type
    type_counts = {}
    for c in companies:
        t = c.get("type", c.get("categorie", "Inconnu"))
        if not t:
            t = "Inconnu"
        if t not in type_counts:
            type_counts[t] = 0
        type_counts[t] += 1

    # Write stats
    row = 1
    ws2.cell(row=row, column=1, value="STATISTIQUES GLOBALES").font = Font(bold=True, size=14, color="1F4E79")
    ws2.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
    row += 2

    stats_data = [
        ("Total entreprises", total),
        ("Avec téléphone", f"{with_tel} ({with_tel/total*100:.1f}%)"),
        ("Avec email", f"{with_email} ({with_email/total*100:.1f}%)"),
        ("Avec site web", f"{with_site} ({with_site/total*100:.1f}%)"),
    ]
    for label, val in stats_data:
        ws2.cell(row=row, column=1, value=label).font = stat_font
        ws2.cell(row=row, column=2, value=str(val)).font = Font(bold=True, size=11)
        row += 1

    row += 2
    ws2.cell(row=row, column=1, value="PAR VILLE").font = stat_header_font
    row += 1
    for h_col, h_val in enumerate(["Ville", "Total", "Téléphone", "Email", "Site Web"], 1):
        ws2.cell(row=row, column=h_col, value=h_val).font = Font(bold=True, size=11)
    row += 1

    for ville in sorted(city_counts.keys(), key=lambda v: -city_counts[v]["total"]):
        if city_counts[ville]["total"] < 3:
            continue
        ws2.cell(row=row, column=1, value=ville).font = stat_font
        ws2.cell(row=row, column=2, value=city_counts[ville]["total"]).font = stat_font
        ws2.cell(row=row, column=3, value=city_counts[ville]["tel"]).font = stat_font
        ws2.cell(row=row, column=4, value=city_counts[ville]["email"]).font = stat_font
        ws2.cell(row=row, column=5, value=city_counts[ville]["site"]).font = stat_font
        row += 1

    row += 2
    ws2.cell(row=row, column=1, value="PAR TYPE D'ACTIVITÉ").font = stat_header_font
    row += 1
    for h_col, h_val in enumerate(["Type", "Nombre"], 1):
        ws2.cell(row=row, column=h_col, value=h_val).font = Font(bold=True, size=11)
    row += 1
    for t in sorted(type_counts.keys(), key=lambda x: -type_counts[x]):
        ws2.cell(row=row, column=1, value=t).font = stat_font
        ws2.cell(row=row, column=2, value=type_counts[t]).font = stat_font
        row += 1

    ws2.column_dimensions['A'].width = 35
    ws2.column_dimensions['B'].width = 15
    ws2.column_dimensions['C'].width = 15
    ws2.column_dimensions['D'].width = 15
    ws2.column_dimensions['E'].width = 15

    # ── Sheet 3: Contacts exploitables (with phone/email/site) ──
    ws3 = wb.create_sheet("Contacts Exploitables")
    ws3.sheet_properties.tabColor = "2E7D32"

    contact_headers = [
        "Nom", "Ville", "Type", "Téléphone", "Email", "Site Web", "SIRET", "Adresse"
    ]
    for col, header in enumerate(contact_headers, 1):
        cell = ws3.cell(row=1, column=col, value=header)
        cell.fill = PatternFill(start_color="2E7D32", end_color="2E7D32", fill_type="solid")
        cell.font = Font(color="FFFFFF", bold=True, size=11, name="Calibri")
        cell.alignment = Alignment(horizontal="center")
        cell.border = thin_border

    contact_row = 2
    for c in companies:
        tel = c.get("telephone", "").strip()
        email = c.get("email", "").strip()
        site = c.get("site_web", "").strip()
        if not tel and not email and not site:
            continue
        values = [
            c.get("nom", ""),
            c.get("ville", ""),
            c.get("type", c.get("categorie", "")),
            tel,
            email,
            site,
            str(c.get("siret", "")),
            c.get("adresse", c.get("adresse_complete", "")),
        ]
        for col, val in enumerate(values, 1):
            cell = ws3.cell(row=contact_row, column=col, value=str(val) if val else "")
            cell.font = data_font
            cell.border = thin_border
            if col == 7:
                cell.number_format = '@'
        contact_row += 1

    ws3.freeze_panes = "A2"
    ws3.auto_filter.ref = ws3.dimensions
    ws3.column_dimensions['A'].width = 35
    ws3.column_dimensions['B'].width = 20
    ws3.column_dimensions['C'].width = 15
    ws3.column_dimensions['D'].width = 20
    ws3.column_dimensions['E'].width = 30
    ws3.column_dimensions['F'].width = 35
    ws3.column_dimensions['G'].width = 18
    ws3.column_dimensions['H'].width = 40

    wb.save(xlsx_path)
    print(f"  Excel sauvegardé: {xlsx_path}")
    print(f"  - Onglet 1: Toutes les entreprises ({len(companies)} lignes)")
    print(f"  - Onglet 2: Statistiques")
    print(f"  - Onglet 3: Contacts exploitables ({contact_row - 2} lignes)")


def verify_no_errors(companies, label):
    """Final verification - ensure no errors remain."""
    from collections import Counter
    print(f"\n  VÉRIFICATION FINALE: {label}")
    issues = 0

    # Check duplicate phones
    phones = [c.get("telephone", "").strip() for c in companies if c.get("telephone", "").strip()]
    phone_counts = Counter(phones)
    dupe_phones = {k: v for k, v in phone_counts.items() if v > 1}
    # Filter: allow same SIREN
    real_dupe_phones = {}
    for phone, count in dupe_phones.items():
        sirens = set()
        for c in companies:
            if c.get("telephone", "").strip() == phone:
                s = get_siren(c)
                if s:
                    sirens.add(s)
        if len(sirens) > 1:
            real_dupe_phones[phone] = count
    if real_dupe_phones:
        print(f"  ⚠ {len(real_dupe_phones)} téléphones encore en double (entreprises différentes)")
        issues += len(real_dupe_phones)
    else:
        print(f"  ✓ 0 téléphone en double")

    # Check duplicate emails
    emails = [c.get("email", "").strip() for c in companies if c.get("email", "").strip()]
    email_counts = Counter(emails)
    dupe_emails = {k: v for k, v in email_counts.items() if v > 1}
    real_dupe_emails = {}
    for email, count in dupe_emails.items():
        sirens = set()
        for c in companies:
            if c.get("email", "").strip() == email:
                s = get_siren(c)
                if s:
                    sirens.add(s)
        if len(sirens) > 1:
            real_dupe_emails[email] = count
    if real_dupe_emails:
        print(f"  ⚠ {len(real_dupe_emails)} emails encore en double")
        issues += len(real_dupe_emails)
    else:
        print(f"  ✓ 0 email en double")

    # Check duplicate sites
    sites = [c.get("site_web", "").strip() for c in companies if c.get("site_web", "").strip()]
    site_counts = Counter(sites)
    dupe_sites = {k: v for k, v in site_counts.items() if v > 1}
    real_dupe_sites = {}
    for site, count in dupe_sites.items():
        sirens = set()
        for c in companies:
            if c.get("site_web", "").strip() == site:
                s = get_siren(c)
                if s:
                    sirens.add(s)
        if len(sirens) > 1:
            real_dupe_sites[site] = count
    if real_dupe_sites:
        print(f"  ⚠ {len(real_dupe_sites)} sites web encore en double")
        issues += len(real_dupe_sites)
    else:
        print(f"  ✓ 0 site web en double")

    # Check fake phones
    fake = sum(1 for c in companies if c.get("telephone", "").strip() in FAKE_PHONES)
    if fake:
        print(f"  ⚠ {fake} faux numéros restants")
        issues += fake
    else:
        print(f"  ✓ 0 faux numéro")

    # Check 08xx
    premium = sum(1 for c in companies if is_premium_number(c.get("telephone", "").strip()))
    if premium:
        print(f"  ⚠ {premium} numéros 08xx restants")
        issues += premium
    else:
        print(f"  ✓ 0 numéro 08xx")

    # Check geo mismatch
    geo_bad = 0
    for c in companies:
        tel = c.get("telephone", "").strip()
        dept = get_dept(c)
        if tel and dept and not phone_matches_region(tel, dept):
            geo_bad += 1
    if geo_bad:
        print(f"  ⚠ {geo_bad} téléphones zone géo incorrecte")
        issues += geo_bad
    else:
        print(f"  ✓ 0 téléphone zone géo incorrecte")

    if issues == 0:
        print(f"  ✓✓✓ FICHIER PROPRE - 0 ERREUR DÉTECTÉE ✓✓✓")
    return issues


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    all_companies = {}

    for filepath in FILES:
        if not os.path.exists(filepath):
            print(f"Fichier non trouvé: {filepath}")
            continue

        companies, stats = clean_file(filepath)
        all_companies[filepath] = companies

        # Verify
        verify_no_errors(companies, os.path.basename(filepath))

        # Excel
        xlsx_path = filepath.replace(".json", "_PROPRE.xlsx")
        print(f"\nGénération Excel avancé...")
        generate_excel_advanced(companies, xlsx_path, "Entreprises")

    # Cross-file SIRET dedup check
    if len(all_companies) == 2:
        files = list(all_companies.keys())
        sirets_1 = {str(c.get("siret", "")) for c in all_companies[files[0]]}
        sirets_2 = {str(c.get("siret", "")) for c in all_companies[files[1]]}
        common = sirets_1 & sirets_2 - {""}
        if common:
            print(f"\n⚠ {len(common)} SIRET en commun entre les 2 fichiers:")
            for s in common:
                for f, comps in all_companies.items():
                    for c in comps:
                        if str(c.get("siret", "")) == s:
                            print(f"  {s} - {c.get('nom', '?')} ({os.path.basename(f)})")

    print(f"\n{'═' * 60}")
    print(f"  TERMINÉ")
    print(f"{'═' * 60}")
