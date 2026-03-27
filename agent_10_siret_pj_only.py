#!/usr/bin/env python3
"""
Agent 10 - SIRET enrichment for PJ-only establishments.
Finds establishments present in Pages Jaunes but not in the main API database,
then searches for their SIRET via the Recherche Entreprises API.
"""

import json
import random
import re
import subprocess
import time
import urllib.parse
import urllib.request
from difflib import SequenceMatcher

# ─── CONFIG ────────────────────────────────────────────────────────────────────
BASE_DB_PATH     = "/home/user/Website01/entreprises_auto_moto_evry_toulouse_area.json"
PJ_SOURCES = [
    ("/home/user/Website01/pj_results_toulouse.json",  "Toulouse",  "list"),
    ("/home/user/Website01/pj_results_evry.json",      "Evry",      "list"),
    ("/home/user/Website01/pj_results_blagnac.json",   "Blagnac",   "list"),
    ("/home/user/Website01/pj_results_colomiers.json", "Colomiers", "list"),
    ("/home/user/Website01/pj_results_muret.json",     "Muret",     "list"),
    ("/home/user/Website01/pj_cache_toulouse.json",    "Toulouse",  "dict"),
    ("/home/user/Website01/pj_cache_evry.json",        "Evry",      "dict"),
]
OUT_PATH         = "/home/user/Website01/agent_out_10_siret_pj_only.json"
SIMILARITY_THRESH = 0.70
MAX_PJ_ONLY      = 500
API_DELAY        = 1.5   # 1.5s base delay between calls
RETRY_DELAY      = 6.0   # fallback if no retry-after header


# ─── HELPERS ───────────────────────────────────────────────────────────────────
def normalize_name(name: str) -> str:
    if not name:
        return ""
    name = name.upper()
    name = re.sub(r'\b(SARL|SAS|SA|EURL|SCI|SASU|SNC|ETS|ETABLISSEMENTS?)\b', '', name)
    name = re.sub(r'[^A-Z0-9\s]', ' ', name)
    return re.sub(r'\s+', ' ', name).strip()


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def normalize_cp(cp) -> str:
    if cp is None:
        return ""
    return str(cp).strip().zfill(5)


# ─── LOAD MAIN DB ──────────────────────────────────────────────────────────────
print("Loading main database...")
with open(BASE_DB_PATH, encoding="utf-8") as f:
    main_db = json.load(f)

# Build index: (normalized_name, code_postal) → entry
# Also keep a set of (norm_name, cp) for fast lookup
main_index = {}   # key → list of entries
for entry in main_db:
    n  = normalize_name(entry.get("nom", ""))
    cp = normalize_cp(entry.get("code_postal", ""))
    key = (n, cp)
    main_index.setdefault(key, []).append(entry)

print(f"  Main DB: {len(main_db)} entries, {len(main_index)} unique (name+CP) keys")


# ─── LOAD ALL PJ ENTRIES ───────────────────────────────────────────────────────
print("\nLoading PJ sources...")
pj_all = []   # list of dicts with unified fields
seen_pj = set()  # dedup by (nom, cp)

def add_pj_entry(entry: dict, zone: str):
    nom = entry.get("nom_pj") or entry.get("nom") or ""
    cp  = normalize_cp(entry.get("code_postal_pj") or entry.get("code_postal") or "")
    key = (nom.upper(), cp)
    if key in seen_pj:
        return
    seen_pj.add(key)
    pj_all.append({
        "nom":          nom,
        "adresse":      entry.get("adresse_pj") or entry.get("adresse") or "",
        "code_postal":  cp,
        "ville":        entry.get("ville_pj") or entry.get("ville") or "",
        "telephone":    entry.get("telephone") or "",
        "site_web":     entry.get("site_web") or "",
        "zone_recherche": zone,
        "_raw": entry,
    })

for path, zone, kind in PJ_SOURCES:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if kind == "list":
        for e in data:
            add_pj_entry(e, zone)
    else:  # dict of lists
        for _cat, entries in data.items():
            if isinstance(entries, list):
                for e in entries:
                    add_pj_entry(e, zone)
            elif isinstance(entries, dict):
                add_pj_entry(entries, zone)

print(f"  Total unique PJ entries: {len(pj_all)}")


# ─── FIND PJ-ONLY ENTRIES ──────────────────────────────────────────────────────
print("\nIdentifying PJ-only entries (not in main DB)...")

def is_in_main_db(nom: str, cp: str) -> bool:
    norm = normalize_name(nom)
    if not norm:
        return False
    # Exact match first
    if (norm, cp) in main_index:
        return True
    # Fuzzy match: compare against all entries with same CP
    for (db_name, db_cp), _ in main_index.items():
        if db_cp != cp:
            continue
        if similarity(norm, db_name) > SIMILARITY_THRESH:
            return True
    return False

pj_only = []
for entry in pj_all:
    nom = entry["nom"]
    cp  = entry["code_postal"]
    if not is_in_main_db(nom, cp):
        pj_only.append(entry)

print(f"  PJ-only entries: {len(pj_only)} (out of {len(pj_all)} total PJ)")


# ─── PRIORITIZE: entries with phone AND address ─────────────────────────────────
def has_phone(e):  return bool(e.get("telephone", "").strip())
def has_addr(e):   return bool(e.get("adresse", "").strip())

priority = [e for e in pj_only if has_phone(e) and has_addr(e)]
rest     = [e for e in pj_only if not (has_phone(e) and has_addr(e))]
candidates = (priority + rest)[:MAX_PJ_ONLY]
print(f"  With phone+address: {len(priority)}")
print(f"  Processing (max {MAX_PJ_ONLY}): {len(candidates)}")


# ─── API SEARCH ────────────────────────────────────────────────────────────────
API_BASE = "https://recherche-entreprises.api.gouv.fr/search"

def fetch_url(url: str, max_retries: int = 8) -> dict | None:
    """Fetch URL using curl subprocess, handles 429 with retry-after."""
    for attempt in range(max_retries):
        try:
            result = subprocess.run(
                ["curl", "-s", "-w", "\n%{http_code}", "--max-time", "15", url],
                capture_output=True, text=True, timeout=20
            )
            output = result.stdout.strip()
            if not output:
                return None
            lines = output.rsplit("\n", 1)
            http_code = int(lines[-1]) if len(lines) > 1 else 0
            body = lines[0] if len(lines) > 1 else output

            if http_code == 200:
                return json.loads(body)
            elif http_code == 429:
                # Parse retry-after from body if available
                wait = RETRY_DELAY + random.uniform(1, 3)
                try:
                    err_data = json.loads(body)
                    wait = float(err_data.get("retry-after", wait))
                except Exception:
                    pass
                wait = max(wait, RETRY_DELAY)
                print(f"    429 (attempt {attempt+1}), sleeping {wait:.1f}s...")
                time.sleep(wait)
                continue
            else:
                print(f"    HTTP {http_code} for URL: {url[:80]}")
                return None
        except subprocess.TimeoutExpired:
            print(f"    Timeout on attempt {attempt+1}")
            time.sleep(RETRY_DELAY)
            continue
        except Exception as exc:
            print(f"    Error: {exc}")
            return None
    print(f"    Max retries exceeded")
    return None


def search_siret(nom: str, cp: str) -> dict | None:
    """Search the API and return best matching result dict, or None."""
    query = urllib.parse.quote(nom)
    url   = f"{API_BASE}?q={query}&per_page=5"
    data  = fetch_url(url)
    if data is None:
        return None

    results = data.get("results", [])
    norm_query = normalize_name(nom)

    for r in results:
        # Get first matching etablissement
        etabs = r.get("matching_etablissements") or r.get("siege") and [r["siege"]] or []
        if not etabs and r.get("siege"):
            etabs = [r["siege"]]

        nom_api = r.get("nom_complet") or r.get("nom_raison_sociale") or ""
        norm_api = normalize_name(nom_api)
        sim = similarity(norm_query, norm_api)

        if sim < SIMILARITY_THRESH:
            continue

        # Find etablissement matching CP
        matched_etab = None
        for etab in etabs:
            etab_cp = normalize_cp(etab.get("code_postal") or "")
            if etab_cp == cp:
                matched_etab = etab
                break

        # Also check siege CP
        if not matched_etab:
            siege = r.get("siege") or {}
            siege_cp = normalize_cp(siege.get("code_postal") or "")
            if siege_cp == cp:
                matched_etab = siege

        if not matched_etab:
            continue

        # Build result
        siret = matched_etab.get("siret") or ""
        siren = r.get("siren") or siret[:9] if siret else ""
        adresse_parts = [
            matched_etab.get("numero_voie") or "",
            matched_etab.get("type_voie") or "",
            matched_etab.get("libelle_voie") or "",
            matched_etab.get("code_postal") or "",
            matched_etab.get("libelle_commune") or "",
        ]
        adresse = " ".join(p for p in adresse_parts if p).strip()

        return {
            "siret":     siret,
            "siren":     siren,
            "adresse":   adresse or matched_etab.get("adresse") or "",
            "code_postal": normalize_cp(matched_etab.get("code_postal") or cp),
            "ville":     matched_etab.get("libelle_commune") or "",
            "code_naf":  matched_etab.get("activite_principale") or r.get("activite_principale") or "",
        }

    return None


# ─── ENRICH LOOP ───────────────────────────────────────────────────────────────
print("\nEnriching PJ-only entries with SIRET...")
enriched = []
not_found = 0

for i, entry in enumerate(candidates, 1):
    nom = entry["nom"]
    cp  = entry["code_postal"]

    if i % 50 == 0:
        print(f"  Progress: {i}/{len(candidates)} | enriched={len(enriched)}, not_found={not_found}")

    result = search_siret(nom, cp)
    time.sleep(API_DELAY + random.uniform(0, 1.0))

    if result and result.get("siret"):
        enriched.append({
            "nom":           nom,
            "siret":         result["siret"],
            "siren":         result["siren"],
            "adresse":       result.get("adresse") or entry.get("adresse") or "",
            "code_postal":   result.get("code_postal") or cp,
            "ville":         result.get("ville") or entry.get("ville") or "",
            "code_naf":      result.get("code_naf") or "",
            "telephone":     entry.get("telephone") or "",
            "site_web":      entry.get("site_web") or "",
            "source":        "PagesJaunes+API",
            "zone_recherche": entry.get("zone_recherche") or "",
        })
    else:
        not_found += 1


# ─── SAVE ──────────────────────────────────────────────────────────────────────
print(f"\nSaving {len(enriched)} enriched entries to {OUT_PATH}...")
with open(OUT_PATH, "w", encoding="utf-8") as f:
    json.dump(enriched, f, ensure_ascii=False, indent=2)

# ─── SUMMARY ───────────────────────────────────────────────────────────────────
print("\n" + "="*60)
print("SUMMARY")
print("="*60)
print(f"  PJ entries analysed  : {len(pj_all)}")
print(f"  PJ-only found        : {len(pj_only)}")
print(f"  Candidates processed : {len(candidates)}")
print(f"  SIRET enriched       : {len(enriched)}")
print(f"  Not found            : {not_found}")
print(f"  Output file          : {OUT_PATH}")
print("="*60)
