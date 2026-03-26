#!/usr/bin/env python3
"""
Post-traitement et fusion des enrichissements PJ pour Lille.
Fusionne les resultats des deux scripts, nettoie les telephones, et produit enriched_lille_pj.json.
"""

import json
import re

FILE_V1 = "/home/user/Website01/enriched_lille_pj.json"
FILE_V2 = "/home/user/Website01/enriched_lille_pj_final.json"
OUTPUT = "/home/user/Website01/enriched_lille_pj.json"


def clean_phone(phone_str):
    """Nettoie un numero de telephone."""
    if not phone_str:
        return ""
    # Extraire le premier numero valide (0X XX XX XX XX)
    m = re.search(r'(0[1-9][\s.]?\d{2}[\s.]?\d{2}[\s.]?\d{2}[\s.]?\d{2})', phone_str)
    if m:
        phone = m.group(1)
        # Formater en 0X XX XX XX XX
        digits = re.sub(r'[\s.]', '', phone)
        if len(digits) == 10:
            return f"{digits[0:2]} {digits[2:4]} {digits[4:6]} {digits[6:8]} {digits[8:10]}"
    return ""


def main():
    # Charger les deux versions
    with open(FILE_V1, "r", encoding="utf-8") as f:
        data_v1 = json.load(f)
    with open(FILE_V2, "r", encoding="utf-8") as f:
        data_v2 = json.load(f)

    # Indexer v2 par SIRET
    v2_by_siret = {}
    for e in data_v2:
        siret = e.get("siret", "")
        if siret:
            v2_by_siret[siret] = e

    # Fusionner : prendre v1 comme base, enrichir avec v2 si manquant
    for e in data_v1:
        siret = e.get("siret", "")

        # Nettoyer le telephone
        e["pj_telephone"] = clean_phone(e.get("pj_telephone", ""))

        # Si pas de match dans v1 mais match dans v2, prendre v2
        v2 = v2_by_siret.get(siret)
        if v2 and v2.get("enrichi"):
            if not e.get("pj_telephone") and v2.get("telephone"):
                e["pj_telephone"] = clean_phone(v2["telephone"])
                e["pj_nom_trouve"] = e.get("pj_nom_trouve") or v2.get("nom_pj", "")
                e["pj_adresse_pj"] = e.get("pj_adresse_pj") or v2.get("adresse_pj", "")
                e["pj_match_score"] = max(e.get("pj_match_score", 0), v2.get("match_score", 0) * 100)

            if not e.get("pj_site_web") and v2.get("site_web"):
                e["pj_site_web"] = v2["site_web"]

            if not e.get("pj_detail_url") and v2.get("url_pj"):
                e["pj_detail_url"] = v2["url_pj"]

        # S'assurer que tous les champs enrichissement existent
        for field in ["pj_match_score", "pj_nom_trouve", "pj_telephone", "pj_site_web", "pj_adresse_pj", "pj_detail_url"]:
            if field not in e:
                e[field] = "" if field != "pj_match_score" else 0

    # Stats
    total = len(data_v1)
    with_phone = sum(1 for e in data_v1 if e.get("pj_telephone"))
    with_web = sum(1 for e in data_v1 if e.get("pj_site_web"))
    high_match = sum(1 for e in data_v1 if e.get("pj_match_score", 0) >= 60)

    print(f"Total: {total}")
    print(f"Avec match (>=60): {high_match} ({high_match*100//total}%)")
    print(f"Avec telephone: {with_phone} ({with_phone*100//total}%)")
    print(f"Avec site web: {with_web} ({with_web*100//total}%)")

    # Sauvegarder
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(data_v1, f, ensure_ascii=False, indent=2)
    print(f"\nSauvegarde: {OUTPUT}")


if __name__ == "__main__":
    main()
