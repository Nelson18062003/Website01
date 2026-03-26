#!/usr/bin/env python3
"""
Consolidation finale : fusionne les données API gouv + enrichissement PagesJaunes
"""
import json
import os
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

os.chdir('/home/user/Website01')

# 1. Charger les données de base
with open('entreprises_auto_moto_lille_lyon_bordeaux.json') as f:
    base = json.load(f)

print(f"Base: {len(base)} entreprises actives")

# Indexer par SIRET
by_siret = {}
for e in base:
    siret = e.get('siret', '').strip()
    if siret:
        by_siret[siret] = e
        # Init contact fields
        e['telephone'] = ''
        e['site_web'] = ''
        e['email'] = ''

# 2. Enrichir avec PJ Bordeaux (meilleure source)
with open('enriched_bordeaux_pj.json') as f:
    bordeaux_pj = json.load(f)

pj_enriched = 0
for e in bordeaux_pj:
    siret = e.get('siret', '').strip()
    tel = e.get('telephone', '').strip()
    site = e.get('site_web', '').strip()
    if siret in by_siret:
        if tel:
            by_siret[siret]['telephone'] = tel
            pj_enriched += 1
        if site:
            by_siret[siret]['site_web'] = site
print(f"PJ Bordeaux: {pj_enriched} entreprises enrichies avec téléphone")

# 3. Enrichir avec PJ Lille
with open('enriched_lille_pj.json') as f:
    lille_pj = json.load(f)

lille_enriched = 0
for e in lille_pj:
    siret = e.get('siret', '').strip()
    tel = e.get('pj_telephone', '').strip() if e.get('pj_telephone') else ''
    site = e.get('pj_site_web', '').strip() if e.get('pj_site_web') else ''
    if siret in by_siret:
        if tel:
            by_siret[siret]['telephone'] = tel
            lille_enriched += 1
        if site:
            by_siret[siret]['site_web'] = site
print(f"PJ Lille: {lille_enriched} entreprises enrichies avec téléphone")

# 4. Enrichir avec PJ Lyon  
try:
    with open('enriched_lyon_pj.json') as f:
        lyon_pj = json.load(f)
    lyon_enriched = 0
    for e in lyon_pj:
        siret = e.get('siret', '').strip()
        tel = e.get('telephone', '') or e.get('pj_telephone', '')
        site = e.get('site_web', '') or e.get('pj_site_web', '')
        tel = tel.strip() if tel else ''
        site = site.strip() if site else ''
        if siret in by_siret:
            if tel:
                by_siret[siret]['telephone'] = tel
                lyon_enriched += 1
            if site:
                by_siret[siret]['site_web'] = site
    print(f"PJ Lyon: {lyon_enriched} entreprises enrichies avec téléphone")
except Exception as ex:
    print(f"PJ Lyon: erreur - {ex}")

# 5. Enrichir avec les petits fichiers enriched_bordeaux/lyon.json (test 5 entreprises)
for fname in ['enriched_bordeaux.json', 'enriched_lyon.json']:
    try:
        with open(fname) as f:
            data = json.load(f)
        if isinstance(data, list):
            for e in data:
                siret = e.get('siret', '').strip()
                tel = e.get('telephone', '').strip() if e.get('telephone') else ''
                site = (e.get('site_web', '') or e.get('site_internet', '')).strip()
                if siret in by_siret:
                    if tel and not by_siret[siret]['telephone']:
                        by_siret[siret]['telephone'] = tel
                    if site and not by_siret[siret]['site_web']:
                        by_siret[siret]['site_web'] = site
    except:
        pass

# 6. Enrichir avec PJ results Bordeaux brut (853 résultats PJ)
try:
    with open('pj_results_bordeaux.json') as f:
        pj_raw = json.load(f)
    pj_extra = 0
    # Match by name similarity with base companies in Bordeaux
    bordeaux_base = {e['siret']: e for e in base if e.get('zone_recherche') == 'Bordeaux'}
    name_to_siret = {}
    for siret, e in bordeaux_base.items():
        nom = e.get('nom', '').upper().strip()
        if nom:
            name_to_siret[nom] = siret
    
    for pj in pj_raw:
        pj_nom = (pj.get('nom') or '').upper().strip()
        pj_tel = (pj.get('telephone') or pj.get('tel') or '').strip()
        pj_site = (pj.get('site_web') or pj.get('website') or '').strip()
        
        if pj_nom in name_to_siret:
            siret = name_to_siret[pj_nom]
            if siret in by_siret:
                if pj_tel and not by_siret[siret]['telephone']:
                    by_siret[siret]['telephone'] = pj_tel
                    pj_extra += 1
                if pj_site and not by_siret[siret]['site_web']:
                    by_siret[siret]['site_web'] = pj_site
    print(f"PJ Bordeaux brut extra: {pj_extra} matches par nom")
except Exception as ex:
    print(f"PJ brut: {ex}")

# 7. Formater les téléphones en +33
def format_phone(tel):
    if not tel:
        return ''
    tel = tel.strip().replace(' ', '').replace('.', '').replace('-', '')
    if tel.startswith('0') and len(tel) == 10:
        tel = '+33' + tel[1:]
    elif tel.startswith('33') and len(tel) == 11:
        tel = '+' + tel
    elif not tel.startswith('+'):
        tel = '+33' + tel if len(tel) == 9 else tel
    # Format lisible
    if tel.startswith('+33') and len(tel) == 12:
        tel = f'+33 {tel[3]} {tel[4:6]} {tel[6:8]} {tel[8:10]} {tel[10:12]}'
    return tel

for e in base:
    e['telephone'] = format_phone(e.get('telephone', ''))

# Stats finales
total = len(base)
with_tel = sum(1 for e in base if e['telephone'])
with_site = sum(1 for e in base if e['site_web'])
print(f"\n=== STATS FINALES ===")
print(f"Total entreprises: {total}")
print(f"Avec téléphone: {with_tel} ({100*with_tel//total}%)")
print(f"Avec site web: {with_site} ({100*with_site//total}%)")

from collections import Counter
print("\nPar ville:")
for ville in ['Lille', 'Lyon', 'Bordeaux']:
    ville_data = [e for e in base if e.get('zone_recherche') == ville]
    t = sum(1 for e in ville_data if e['telephone'])
    s = sum(1 for e in ville_data if e['site_web'])
    print(f"  {ville}: {len(ville_data)} total | {t} tél | {s} sites")

print("\nPar catégorie:")
for cat, count in Counter(e['categorie'] for e in base).most_common():
    t = sum(1 for e in base if e['categorie'] == cat and e['telephone'])
    print(f"  {cat}: {count} total | {t} tél")

# 8. Export JSON
with open('entreprises_auto_moto_lille_lyon_bordeaux_enriched.json', 'w', encoding='utf-8') as f:
    json.dump(base, f, ensure_ascii=False, indent=2)

# 9. Export Excel
wb = Workbook()
ws = wb.active
ws.title = "Entreprises Auto-Moto"

headers = ['Nom', 'SIRET', 'SIREN', 'Adresse', 'Code Postal', 'Ville',
           'Téléphone', 'Site Web', 'Email',
           'Code NAF', 'Activité', 'Date Création', 'Statut', 'Effectif',
           'Catégorie', 'Zone Recherche']

header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
header_font = Font(color="FFFFFF", bold=True, size=11)
thin_border = Border(
    left=Side(style='thin'), right=Side(style='thin'),
    top=Side(style='thin'), bottom=Side(style='thin')
)

for col, h in enumerate(headers, 1):
    cell = ws.cell(row=1, column=col, value=h)
    cell.fill = header_fill
    cell.font = header_font
    cell.alignment = Alignment(horizontal='center')
    cell.border = thin_border

keys = ['nom', 'siret', 'siren', 'adresse', 'code_postal', 'ville',
        'telephone', 'site_web', 'email',
        'code_naf', 'libelle_activite', 'date_creation', 'statut', 'effectif',
        'categorie', 'zone_recherche']

for row_idx, e in enumerate(base, 2):
    for col_idx, key in enumerate(keys, 1):
        val = e.get(key, '')
        cell = ws.cell(row=row_idx, column=col_idx, value=val)
        cell.border = thin_border
        if key in ('siret', 'siren', 'code_postal'):
            cell.number_format = '@'

for col in ws.columns:
    max_length = 0
    for cell in col:
        if cell.value:
            max_length = max(max_length, len(str(cell.value)))
    ws.column_dimensions[col[0].column_letter].width = min(max_length + 2, 50)

ws.freeze_panes = 'A2'
ws.auto_filter.ref = ws.dimensions

wb.save('entreprises_auto_moto_lille_lyon_bordeaux_enriched.xlsx')
print(f"\nExport terminé:")
print(f"  - entreprises_auto_moto_lille_lyon_bordeaux_enriched.json")
print(f"  - entreprises_auto_moto_lille_lyon_bordeaux_enriched.xlsx")
