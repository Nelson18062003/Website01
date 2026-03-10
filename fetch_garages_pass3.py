#!/usr/bin/env python3
"""Third pass - fetch remaining data that was rate-limited."""

import json
import time
import urllib.request
import urllib.parse
import ssl

OUTPUT_FILE = "/home/user/Website01/scrape_environs_legal.json"

with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
    existing = json.load(f)

all_enterprises = {e["siren"]: e for e in existing}
print(f"Loaded {len(all_enterprises)} existing enterprises")

# Still missing queries
QUERIES = [
    # Dept 54 garage 45.11Z page 3
    ("garage", "45.11Z", "54", 3),
    # Dept 93 garage 45.20A pages 1, 2, 5 and beyond
    ("garage", "45.20A", "93", 1),
    ("garage", "45.20A", "93", 2),
    ("garage", "45.20A", "93", 5),
    ("garage", "45.20A", "93", 6),
    # Dept 93 45.11Z pages 4-6+
    ("garage", "45.11Z", "93", 4),
    ("garage", "45.11Z", "93", 5),
    ("garage", "45.11Z", "93", 6),
    # Réparation automobile searches
    ("réparation automobile", "45.20A", "93", 1),
    ("réparation automobile", "45.20B", "54", 1),
    ("réparation automobile", "45.20B", "93", 1),
    # Additional NAF-specific searches
    ("auto", "45.20A", "54", 1),
    ("auto", "45.20A", "54", 2),
    ("auto", "45.20A", "54", 3),
    ("auto", "45.20A", "93", 1),
    ("auto", "45.20A", "93", 2),
    ("auto", "45.20A", "93", 3),
    ("auto", "45.20A", "93", 4),
    ("auto", "45.20A", "93", 5),
    ("auto", "45.20A", "93", 6),
    # More searches
    ("automobile", "45.20A", "54", 1),
    ("automobile", "45.20A", "54", 2),
    ("automobile", "45.20A", "93", 1),
    ("automobile", "45.20A", "93", 2),
    ("automobile", "45.20A", "93", 3),
    ("automobile", "45.11Z", "54", 1),
    ("automobile", "45.11Z", "54", 2),
    ("automobile", "45.11Z", "93", 1),
    ("automobile", "45.11Z", "93", 2),
    ("automobile", "45.11Z", "93", 3),
]


def fetch_url(url, max_retries=4):
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 10 * (attempt + 1)
                print(f"  Rate limited (attempt {attempt+1}), waiting {wait}s...")
                time.sleep(wait)
                continue
            print(f"  HTTP Error {e.code}: {e.reason}")
            return None
        except Exception as e:
            print(f"  Error: {e}")
            time.sleep(8)
            continue
    print(f"  Max retries exceeded")
    return None


def extract_enterprises(data):
    results = []
    if not data or "results" not in data:
        return results
    for ent in data["results"]:
        siege = ent.get("siege", {})
        dirigeants = ent.get("dirigeants", [])
        director_parts = []
        for d in dirigeants:
            nom = d.get("nom", "")
            prenom = d.get("prenom", "")
            qualite = d.get("qualite", "")
            if nom:
                name = f"{prenom} {nom}".strip()
                if qualite:
                    name += f" ({qualite})"
                director_parts.append(name)
        director = "; ".join(director_parts) if director_parts else ""
        adresse = siege.get("adresse", "") or ""
        code_postal = siege.get("code_postal", "") or ""
        commune = siege.get("libelle_commune", "") or siege.get("commune", "") or ""
        etat = ent.get("etat_administratif", "")
        status = "Active" if etat == "A" else "Radiée" if etat == "C" else etat
        effectif = ent.get("tranche_effectif_salarie", "") or siege.get("tranche_effectif_salarie", "") or ""
        record = {
            "name": ent.get("nom_complet", "") or ent.get("nom_raison_sociale", ""),
            "siren": ent.get("siren", ""),
            "siret": siege.get("siret", ""),
            "address": adresse,
            "postal_code": code_postal,
            "city": commune,
            "naf_code": ent.get("activite_principale", "") or siege.get("activite_principale", ""),
            "director": director,
            "creation_date": ent.get("date_creation", ""),
            "status": status,
            "employees": effectif,
            "source": "API Gouv"
        }
        results.append(record)
    return results


def main():
    global all_enterprises
    new_count = 0

    for q, naf, dept, page in QUERIES:
        encoded_q = urllib.parse.quote(q)
        url = f"https://recherche-entreprises.api.gouv.fr/search?q={encoded_q}&activite_principale={naf}&departement={dept}&page={page}&per_page=25"
        print(f"Fetching: q={q}, naf={naf}, dept={dept}, page={page}")
        data = fetch_url(url)
        if data:
            enterprises = extract_enterprises(data)
            added = 0
            for ent in enterprises:
                siren = ent["siren"]
                if siren and siren not in all_enterprises:
                    all_enterprises[siren] = ent
                    added += 1
                    new_count += 1
            total = data.get("total_results", 0)
            print(f"  Got {len(enterprises)} results, {added} new (total API: {total})")
        time.sleep(5)

    result_list = list(all_enterprises.values())
    result_list.sort(key=lambda x: (x.get("postal_code", ""), x.get("name", "")))

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result_list, f, ensure_ascii=False, indent=2)

    print(f"\n=== DONE (Pass 3) ===")
    print(f"New enterprises added: {new_count}")
    print(f"Total unique enterprises saved: {len(result_list)}")
    dept54 = [e for e in result_list if e.get("postal_code", "").startswith("54")]
    dept93 = [e for e in result_list if e.get("postal_code", "").startswith("93")]
    other = [e for e in result_list if not e.get("postal_code", "").startswith(("54", "93"))]
    print(f"  Dept 54: {len(dept54)}")
    print(f"  Dept 93: {len(dept93)}")
    if other:
        print(f"  Other: {len(other)}")


if __name__ == "__main__":
    main()
