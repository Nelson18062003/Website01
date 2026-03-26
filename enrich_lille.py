import json
import re

# Load the original data
with open('/home/user/Website01/split_lille.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# PagesJaunes data collected via web searches
# Format: (search_key_words, telephone, site_web)
# search_key_words are used to match against the "nom" field in split_lille.json
pj_data = [
    # GARAGES
    {"keys": ["GARAGE D'ESQUERMES", "GARAGE DESQUERMES"], "telephone": "03 20 93 49 15", "site_web": ""},
    {"keys": ["LETAILLEUR", "GARAGE ASLOUN"], "telephone": "03 20 56 40 83", "site_web": "https://garageasloun.fr/"},
    {"keys": ["AUTOWORKS TD"], "telephone": "03 66 19 18 74", "site_web": "https://www.autoworks.fr/"},
    {"keys": ["CARROSSERIE ALEXANDRE"], "telephone": "", "site_web": ""},
    {"keys": ["E.B CARROSSERIE", "EB CARROSSERIE"], "telephone": "", "site_web": ""},
    {"keys": ["GARAGE GAMBETTA SECO"], "telephone": "03 20 57 29 67", "site_web": ""},
    {"keys": ["MIDAS FRANCE"], "telephone": "03 20 54 99 25", "site_web": "https://www.midas.fr/"},
    {"keys": ["VALAUTO LOMME"], "telephone": "03 20 92 06 63", "site_web": "https://www.valauto.fr/"},
    {"keys": ["VALAUTO LAMBERSART"], "telephone": "03 20 08 17 17", "site_web": "https://www.valauto.fr/"},
    {"keys": ["VALAUTO METROPOLE"], "telephone": "03 20 17 26 97", "site_web": "https://www.valauto.fr/"},
    {"keys": ["PALINSKI"], "telephone": "03 20 04 35 05", "site_web": ""},
    {"keys": ["CARROSSERIE LESPINEUX"], "telephone": "03 20 55 03 88", "site_web": "http://www.carlespineux.free.fr/"},
    {"keys": ["GARAGE LICTEVOUT"], "telephone": "03 20 22 02 02", "site_web": ""},
    {"keys": ["GARAGE BIENVENUE"], "telephone": "03 20 47 66 37", "site_web": ""},
    {"keys": ["GARAGE DELMAERE"], "telephone": "03 20 52 53 17", "site_web": "https://www.garagedelmaere.fr/"},
    {"keys": ["GARAGE LEMAIRE"], "telephone": "03 20 56 04 86", "site_web": ""},
    {"keys": ["GARAGE DESCAMPS"], "telephone": "03 20 92 19 02", "site_web": ""},
    {"keys": ["GARAGE STAELS", "GARAGE SMS"], "telephone": "03 20 93 19 10", "site_web": ""},
    {"keys": ["GARAGE RIGAUT"], "telephone": "03 20 56 19 09", "site_web": ""},
    {"keys": ["SINEO LILLE"], "telephone": "03 20 15 07 85", "site_web": "https://www.sineo.fr/"},
    {"keys": ["SARL PLANETE V.S.P", "PLANETE VSP"], "telephone": "03 20 00 06 36", "site_web": "https://www.planetevsp.fr/"},
    {"keys": ["GARAGE REPUBLIQUE", "FLAMENT", "CARROSSERIE FLAMENT"], "telephone": "03 20 09 11 60", "site_web": ""},
    {"keys": ["ETABLISSEMENTS MARANDIN"], "telephone": "03 20 09 34 44", "site_web": ""},
    {"keys": ["GRAND LILLE AUTO"], "telephone": "03 20 50 94 94", "site_web": "https://www.grandlilleauto.fr/"},
    {"keys": ["LAVANCE EXPLOITATION"], "telephone": "03 20 16 05 44", "site_web": "https://www.norauto.fr/"},
    {"keys": ["EUROMASTER"], "telephone": "03 20 00 17 20", "site_web": "https://www.euromaster.fr/"},

    # CONCESSIONS
    {"keys": ["STELLANTIS"], "telephone": "03 20 08 54 54", "site_web": "https://www.stellantisandyou.com/"},
    {"keys": ["RENAULT RETAIL GROUP"], "telephone": "03 20 88 59 59", "site_web": "https://www.renault-retail-group.fr/"},
    {"keys": ["GGPC"], "telephone": "03 20 88 59 59", "site_web": "https://www.ggpauto.fr/"},
    {"keys": ["GGPE"], "telephone": "03 20 88 59 59", "site_web": "https://www.ggpauto.fr/"},
    {"keys": ["GGP FIRST"], "telephone": "03 20 88 59 59", "site_web": "https://www.ggpauto.fr/"},
    {"keys": ["GGP LOCATION"], "telephone": "03 20 88 59 59", "site_web": "https://www.ggpauto.fr/"},
    {"keys": ["SAGA NORD"], "telephone": "", "site_web": "https://www.myrcm.eu/fr/saga-mercedes-benz"},
    {"keys": ["NECKER AUTOMOBILE"], "telephone": "", "site_web": ""},
    {"keys": ["VERBAERE AUTOMOBILES", "D.VERBAERE"], "telephone": "03 20 90 52 52", "site_web": "https://www.verbaereauto.com/"},
    {"keys": ["ARAMISAUTO", "WKDA FRANCE"], "telephone": "03 66 33 06 70", "site_web": "https://www.aramisauto.com/"},
    {"keys": ["QARSON"], "telephone": "", "site_web": "https://www.qarson.fr/"},
    {"keys": ["FRAIKIN FRANCE"], "telephone": "", "site_web": "https://www.fraikin.fr/"},
    {"keys": ["AUTOMOBILES PEUGEOT"], "telephone": "", "site_web": "https://www.peugeot.fr/"},
    {"keys": ["CARROSSERIE LILLOISE"], "telephone": "", "site_web": ""},
    {"keys": ["SOCIETE NOUVELLE LAURENT"], "telephone": "", "site_web": ""},

    # MOTOS
    {"keys": ["BOXER EVASION"], "telephone": "03 28 77 77 28", "site_web": "https://bmw-motorrad-boxerevasion.fr/"},
    {"keys": ["MT MOTO"], "telephone": "03 66 19 15 60", "site_web": "https://www.mt-moto.fr/"},
    {"keys": ["AVENIR MOTO", "TRIUMPH LILLE"], "telephone": "03 28 77 77 20", "site_web": "https://www.triumphlille.fr/"},
    {"keys": ["DAFY MOTO", "SA DAFY MOTO"], "telephone": "03 20 97 77 24", "site_web": "https://www.dafy-moto.com/"},
    {"keys": ["ROXAD"], "telephone": "03 27 23 84 76", "site_web": "https://www.roxad-motors.com/"},
    {"keys": ["DE DONCKER"], "telephone": "03 20 06 63 53", "site_web": "https://dedoncker.com/"},
    {"keys": ["LYS MOTO"], "telephone": "03 20 65 30 30", "site_web": "https://www.lys-moto.fr/"},
    {"keys": ["MOTOLAND", "ACCESS LAND"], "telephone": "03 20 54 88 08", "site_web": "https://motoland.eu/"},
    {"keys": ["MOTO 3000"], "telephone": "", "site_web": ""},
    {"keys": ["LEON CYCLE"], "telephone": "", "site_web": "https://leoncycle.fr/"},
    {"keys": ["ETABLISSEMENTS LECOLIER"], "telephone": "", "site_web": "https://cycleslecolier.fr/"},
    {"keys": ["ECYCLUM"], "telephone": "", "site_web": ""},
    {"keys": ["BRH MOTOS"], "telephone": "", "site_web": ""},
    {"keys": ["DARK SIDE"], "telephone": "", "site_web": ""},
    {"keys": ["ON TRAKC", "ON TRACK"], "telephone": "", "site_web": ""},
    {"keys": ["NORTH PROJECT"], "telephone": "", "site_web": ""},
    {"keys": ["ROBLIN"], "telephone": "", "site_web": ""},
    {"keys": ["MOTO LINE"], "telephone": "", "site_web": ""},
    {"keys": ["TOP MOBILITE", "TOM MOBILITY", "MOBILITYURBAN"], "telephone": "", "site_web": ""},

    # CARROSSIERS
    {"keys": ["SOCIETE DE DIFFUSION ET D APPLICATIONS TECHNIQUES AUTOMOBILES"], "telephone": "", "site_web": ""},
    {"keys": ["SEBASTIEN LEGRIS", "KIX NET"], "telephone": "", "site_web": ""},
    
    # Additional garages/concessions found
    {"keys": ["STA LILLE"], "telephone": "03 20 53 03 33", "site_web": "http://garage-sta-lille.com/"},
    {"keys": ["PREMIUM AUTO LILLE"], "telephone": "03 20 91 20 71", "site_web": "https://premiumautolille.fr/"},
    {"keys": ["ROND POINT AUTO"], "telephone": "03 20 44 09 44", "site_web": ""},
    {"keys": ["QUAD STATION"], "telephone": "03 20 29 13 66", "site_web": "https://www.quadstation.com/"},
    {"keys": ["ETS MICHEL GUSMINI", "GARAGE GUSMINI", "ETS GUSMINI"], "telephone": "03 20 93 83 42", "site_web": ""},
    {"keys": ["VALAUTO PROFESSIONNELS"], "telephone": "03 20 08 17 17", "site_web": "https://www.valauto.fr/"},
    {"keys": ["L ATELIER DU 71"], "telephone": "06 26 70 89 02", "site_web": "https://www.atelierdu71.com/"},
    {"keys": ["BERNARD AUTO SERVICE"], "telephone": "", "site_web": "https://www.bernardautoservice.com/"},
    {"keys": ["CARROSSERIE LILLOISE"], "telephone": "", "site_web": "https://www.ad.fr/garage/ad-carroserie-lilloise"},
    {"keys": ["AUTOSPHERE"], "telephone": "", "site_web": "https://www.autosphere.fr/"},
    {"keys": ["NYXO LILLE"], "telephone": "", "site_web": "https://www.autosphere.fr/"},
    {"keys": ["KEOS NIEPPE"], "telephone": "", "site_web": "https://www.autosphere.fr/"},
    {"keys": ["KEOS ENGLOS"], "telephone": "", "site_web": "https://www.autosphere.fr/"},
    {"keys": ["KEOS LAON"], "telephone": "", "site_web": "https://www.autosphere.fr/"},
    {"keys": ["BAYERN LILLE"], "telephone": "", "site_web": ""},
    {"keys": ["GARAGE DU MARAIS"], "telephone": "", "site_web": ""},
]

def normalize(s):
    """Normalize a string for fuzzy matching"""
    s = s.upper()
    s = re.sub(r'[^A-Z0-9 ]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def match_entry(nom, pj_entry):
    """Check if a business name matches any of the PJ entry keys"""
    nom_norm = normalize(nom)
    for key in pj_entry["keys"]:
        key_norm = normalize(key)
        # Check if key is contained in nom or nom contains key
        if key_norm in nom_norm or nom_norm in key_norm:
            return True
        # Also check individual words match
        key_words = key_norm.split()
        if len(key_words) >= 2:
            # All key words present in nom
            if all(w in nom_norm for w in key_words):
                return True
    return False

# Enrich the data
matched_count = 0
for entry in data:
    # Add empty telephone and site_web fields if not present
    if "telephone" not in entry:
        entry["telephone"] = ""
    if "site_web" not in entry:
        entry["site_web"] = ""
    
    nom = entry.get("nom", "")
    for pj in pj_data:
        if match_entry(nom, pj):
            if pj["telephone"] and not entry["telephone"]:
                entry["telephone"] = pj["telephone"]
                matched_count += 1
            if pj["site_web"] and not entry["site_web"]:
                entry["site_web"] = pj["site_web"]
            break  # Only match first PJ entry

# Save enriched data
with open('/home/user/Website01/enriched_lille_final.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

# Report
total = len(data)
with_tel = sum(1 for d in data if d.get("telephone"))
with_site = sum(1 for d in data if d.get("site_web"))
print(f"Total entries: {total}")
print(f"Entries with telephone: {with_tel}")
print(f"Entries with site_web: {with_site}")
print(f"Matched in this run: {matched_count}")

# Show some matched entries
print("\n--- Sample matched entries ---")
for entry in data:
    if entry.get("telephone"):
        print(f"  {entry['nom']}: tel={entry['telephone']}, web={entry.get('site_web','')}")
