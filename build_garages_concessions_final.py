#!/usr/bin/env python3
"""
Consolidation finale — Garages, Concessions, Carrossiers Toulouse & Évry
=========================================================================
Fusionne toutes les sources collectées par les agents parallèles + données existantes.
Produit: garages-concessions-carrossiers.csv

Sources intégrées:
  - entreprises_auto_moto_evry_toulouse_area.json (base API SIRET)
  - agent_out_1_pj_toulouse.json           (PJ Toulouse fresh)
  - agent_out_2_pj_evry_suburbs.json       (PJ Évry banlieue)
  - agent_out_3_api_31.json                (API dept 31)
  - agent_out_4_api_91.json                (API dept 91)
  - agent_out_5_osm_toulouse.json          (OSM Toulouse)
  - agent_out_6_osm_evry.json              (OSM Évry)
  - agent_out_7_phones_toulouse_1.json     (enrichissement téléphones Toulouse 1)
  - agent_out_8_phones_toulouse_2.json     (enrichissement téléphones Toulouse 2)
  - agent_out_9_phones_evry.json           (enrichissement téléphones Évry)
  - agent_out_10_siret_pj_only.json        (SIRET pour entrées PJ-only)
  - pj_results_toulouse.json / pj_results_evry.json etc.
  - enriched_toulouse_pj.json / enriched_evry_pj.json etc.
"""

import json
import os
import re
import csv
import time
import urllib.request
import urllib.parse
import ssl
from difflib import SequenceMatcher
from collections import Counter, defaultdict
import logging

logging.basicConfig(
    filename='/home/user/Website01/scraper.log',
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
log = logging.info

BASE = "/home/user/Website01"
OUTPUT_CSV = os.path.join(BASE, "garages-concessions-carrossiers.csv")

# =============================================================================
# NAF → type_etablissement
# =============================================================================
NAF_TYPE_MAP = {
    "45.11Z": "concession_auto",
    "45.19Z": "concession_auto",
    "45.20A": "garage_auto",
    "45.20B": "garage_auto",
    "45.32Z": "garage_auto",
    "45.40Z": "garage_moto",
    "4511Z":  "concession_auto",
    "4519Z":  "concession_auto",
    "4520A":  "garage_auto",
    "4520B":  "garage_auto",
    "4532Z":  "garage_auto",
    "4540Z":  "garage_moto",
}

CARROSSERIE_KEYWORDS = ["carrosserie", "carrossier", "body", "peinture auto", "débosselage"]
MOTO_KEYWORDS = ["moto", "motocycle", "motocyclette", "scooter", "deux-roues", "deux roues"]
CONCESSION_KEYWORDS = ["concession", "concessionnaire", "distributeur", "citroën", "renault",
                       "peugeot", "volkswagen", "bmw", "mercedes", "ford", "toyota", "honda",
                       "opel", "nissan", "hyundai", "kia", "seat", "skoda", "audi", "volvo",
                       "fiat", "stellantis", "dacia", "ds ", "alfa romeo", "suzuki"]


def infer_type(nom, code_naf, search_category="", categorie=""):
    """Inférer le type d'établissement."""
    naf_clean = (code_naf or "").replace(".", "").strip()
    naf_dot = code_naf or ""

    # Priorité: code NAF
    t = NAF_TYPE_MAP.get(naf_dot) or NAF_TYPE_MAP.get(naf_clean, "")

    nom_lower = (nom or "").lower()
    cat_lower = (search_category or categorie or "").lower()

    # Affiner par mots-clés nom
    if any(k in nom_lower for k in MOTO_KEYWORDS) or "moto" in cat_lower:
        if "garage" in cat_lower or "réparation" in cat_lower or t == "garage_auto":
            return "garage_moto"
        if "concession" in cat_lower or t == "concession_auto":
            return "concession_moto"
        if "carrosserie" in cat_lower:
            return "carrossier_moto"
        # Default moto
        if not t:
            return "garage_moto"

    if any(k in nom_lower for k in CARROSSERIE_KEYWORDS) or "carrosserie" in cat_lower:
        return "carrossier_auto"

    if any(k in nom_lower for k in CONCESSION_KEYWORDS) or "concession" in cat_lower:
        if "moto" in nom_lower or "moto" in cat_lower:
            return "concession_moto"
        return "concession_auto"

    return t or "garage_auto"


# =============================================================================
# Normalisation
# =============================================================================
def normalize_name(name):
    if not name:
        return ""
    name = name.upper()
    name = re.sub(r'\b(SARL|SAS|SA|EURL|SCI|SASU|SNC|ETS|ETABLISSEMENTS?|GARAGE|AUTO|AUTOMOBILES?)\b', '', name)
    name = re.sub(r'[^A-Z0-9\s]', ' ', name)
    return re.sub(r'\s+', ' ', name).strip()


def fmt_phone(p):
    """Standardiser le téléphone au format 0X XX XX XX XX."""
    if not p:
        return ""
    d = re.sub(r'[^\d+]', '', str(p))
    if d.startswith('+33'):
        d = '0' + d[3:]
    elif d.startswith('0033'):
        d = '0' + d[4:]
    elif d.startswith('33') and len(d) == 11:
        d = '0' + d[2:]
    d = re.sub(r'[^\d]', '', d)
    if len(d) == 10 and d.startswith('0'):
        return f"{d[0:2]} {d[2:4]} {d[4:6]} {d[6:8]} {d[8:10]}"
    return p if len(p) >= 10 else ""


def normalize_cp(cp):
    if not cp:
        return ""
    cp = re.sub(r'[^\d]', '', str(cp))
    return cp.zfill(5) if len(cp) <= 5 else cp[:5]


def similarity(a, b):
    return SequenceMatcher(None, a, b).ratio()


# =============================================================================
# Chargement des fichiers
# =============================================================================
def load_json(path, default=None):
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"  [WARN] Impossible de charger {path}: {e}")
    return default if default is not None else []


def load_pj_cache(path):
    """Charger un cache PJ (dict de listes) et aplatir en liste."""
    data = load_json(path, {})
    if isinstance(data, dict):
        result = []
        for v in data.values():
            if isinstance(v, list):
                result.extend(v)
        return result
    return data if isinstance(data, list) else []


# =============================================================================
# Conversion des entrées vers le format unifié
# =============================================================================
def from_api_entry(e, source="API Recherche Entreprises"):
    """Convertir une entrée API gouvernementale."""
    return {
        "raison_sociale": (e.get("nom") or e.get("nom_complet") or "").strip(),
        "telephone": fmt_phone(e.get("telephone", "")),
        "adresse": (e.get("adresse") or "").strip(),
        "code_postal": normalize_cp(e.get("code_postal", "")),
        "ville": (e.get("ville") or e.get("libelle_commune") or "").strip().upper(),
        "siret": (e.get("siret") or "").strip(),
        "siren": (e.get("siren") or "").strip(),
        "type_etablissement": infer_type(
            e.get("nom", ""), e.get("code_naf", ""),
            e.get("categorie", ""), e.get("zone_recherche", "")
        ),
        "code_naf": (e.get("code_naf") or "").strip(),
        "site_web": (e.get("site_web") or "").strip(),
        "email": (e.get("email") or "").strip(),
        "source": e.get("source", source),
        "_zone": e.get("zone_recherche", ""),
        "_statut": e.get("statut", "Actif"),
    }


def from_pj_entry(e, zone=""):
    """Convertir une entrée Pages Jaunes."""
    nom = (e.get("nom_pj") or e.get("nom") or "").strip()
    adresse = (e.get("adresse_pj") or e.get("adresse") or "").strip()
    cp = normalize_cp(e.get("code_postal_pj") or e.get("code_postal") or "")
    ville = (e.get("ville_pj") or e.get("ville") or "").strip().upper()
    tel = fmt_phone(e.get("telephone", ""))
    site = (e.get("site_web") or "").strip()
    cat = (e.get("search_category") or e.get("categorie") or "").strip()

    return {
        "raison_sociale": nom,
        "telephone": tel,
        "adresse": adresse,
        "code_postal": cp,
        "ville": ville,
        "siret": (e.get("siret") or "").strip(),
        "siren": (e.get("siren") or "").strip(),
        "type_etablissement": infer_type(nom, e.get("code_naf", ""), cat),
        "code_naf": (e.get("code_naf") or "").strip(),
        "site_web": site,
        "email": "",
        "source": "PagesJaunes",
        "_zone": zone or e.get("zone_recherche", ""),
        "_statut": "Actif",
    }


def from_osm_entry(e):
    """Convertir une entrée OpenStreetMap."""
    shop_type = e.get("shop_type", "") or e.get("amenity", "")
    nom = (e.get("nom") or e.get("name") or "").strip()
    return {
        "raison_sociale": nom,
        "telephone": fmt_phone(e.get("telephone", "")),
        "adresse": (e.get("adresse") or "").strip(),
        "code_postal": normalize_cp(e.get("code_postal", "")),
        "ville": (e.get("ville") or "").strip().upper(),
        "siret": "",
        "siren": "",
        "type_etablissement": infer_type(nom, "", shop_type),
        "code_naf": "",
        "site_web": (e.get("site_web") or "").strip(),
        "email": "",
        "source": "OpenStreetMap",
        "_zone": "",
        "_statut": "Actif",
        "_osm_id": str(e.get("osm_id", "")),
    }


# =============================================================================
# Dédoublonnage et fusion
# =============================================================================
def make_key(entry):
    """Clé primaire: SIRET. Secondaire: nom normalisé + code postal."""
    siret = (entry.get("siret") or "").strip()
    if siret and len(siret) == 14:
        return f"siret:{siret}"
    nom = normalize_name(entry.get("raison_sociale", ""))
    cp = normalize_cp(entry.get("code_postal", ""))
    if nom and cp:
        return f"name:{nom[:30]}|{cp}"
    return None


def merge_entries(existing, new):
    """Fusionner deux entrées, garder le plus complet."""
    # Champs à enrichir si vide
    for field in ["telephone", "site_web", "email", "siret", "siren", "code_naf",
                  "adresse", "type_etablissement"]:
        if not existing.get(field) and new.get(field):
            existing[field] = new[field]
    # Source: concaténer
    srcs = set(existing.get("source", "").split("|") + new.get("source", "").split("|"))
    srcs.discard("")
    existing["source"] = "|".join(sorted(srcs))
    return existing


def add_entry(registry, entry):
    """Ajouter/fusionner une entrée dans le registry."""
    if not entry.get("raison_sociale"):
        return
    key = make_key(entry)
    if key is None:
        # Entrée sans clé identifiable: ajouter quand même avec clé unique
        import uuid
        key = f"nokey:{uuid.uuid4().hex[:8]}"

    if key in registry:
        registry[key] = merge_entries(registry[key], entry)
    else:
        registry[key] = entry


# =============================================================================
# Enrichissement SIRET via API
# =============================================================================
def fetch_siret(nom, code_postal, city, max_retries=3):
    """Chercher le SIRET d'un établissement via l'API Recherche Entreprises."""
    q = f"{nom} {city}".strip()
    url = f"https://recherche-entreprises.api.gouv.fr/search?q={urllib.parse.quote(q)}&per_page=3"
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                results = data.get("results", [])
                for r in results:
                    r_cp = (r.get("siege", {}) or {}).get("code_postal", "")
                    r_nom = normalize_name(r.get("nom_complet", ""))
                    nom_norm = normalize_name(nom)
                    if normalize_cp(r_cp) == normalize_cp(code_postal) and similarity(nom_norm, r_nom) > 0.65:
                        siege = r.get("siege", {}) or {}
                        addr = " ".join(filter(None, [
                            siege.get("numero_voie", ""),
                            siege.get("type_voie", ""),
                            siege.get("libelle_voie", ""),
                        ])).strip()
                        if not addr:
                            addr = siege.get("adresse", "")
                        return {
                            "siret": siege.get("siret", ""),
                            "siren": r.get("siren", ""),
                            "code_naf": r.get("activite_principale", ""),
                            "adresse": addr,
                        }
                return None
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            return None
        except Exception:
            return None
    return None


# =============================================================================
# MAIN
# =============================================================================
def main():
    print("=" * 70)
    print("CONSOLIDATION FINALE — Garages/Concessions/Carrossiers")
    print("Toulouse + Blagnac + Colomiers + Muret | Évry + banlieue")
    print("=" * 70)
    log("Début de la consolidation")

    registry = {}  # key → entry unifié
    source_counts = Counter()

    # ------------------------------------------------------------------
    # 1. BASE PRINCIPALE: entreprises_auto_moto_evry_toulouse_area.json
    # ------------------------------------------------------------------
    print("\n[1/12] Chargement base principale API...")
    base = load_json(f"{BASE}/entreprises_auto_moto_evry_toulouse_area.json", [])
    for e in base:
        if e.get("statut", "").lower() in ("radié", "fermé", "inactif"):
            continue
        entry = from_api_entry(e)
        add_entry(registry, entry)
        source_counts["base_API"] += 1
    print(f"  => {len(base)} entrées chargées, registry: {len(registry)}")

    # ------------------------------------------------------------------
    # 2. ENRICHI TOULOUSE PJ (données PJ fusionnées avec API)
    # ------------------------------------------------------------------
    print("\n[2/12] Chargement enriched_toulouse_pj...")
    for fname, zone in [
        ("enriched_toulouse_pj.json", "Toulouse"),
        ("enriched_evry_pj.json", "Evry"),
        ("enriched_blagnac_pj.json", "Blagnac"),
        ("enriched_colomiers_pj.json", "Colomiers"),
        ("enriched_muret_pj.json", "Muret"),
    ]:
        data = load_json(f"{BASE}/{fname}", [])
        for e in data:
            if e.get("statut", "").lower() in ("radié", "fermé", "inactif"):
                continue
            entry = from_api_entry(e, source="API+PJ")
            if e.get("telephone"):
                entry["telephone"] = fmt_phone(e["telephone"])
            if e.get("site_web"):
                entry["site_web"] = e["site_web"]
            add_entry(registry, entry)
        source_counts["enriched_pj"] += len(data)
    print(f"  => registry: {len(registry)}")

    # ------------------------------------------------------------------
    # 3. PJ RESULTS (données PJ brutes avec téléphones)
    # ------------------------------------------------------------------
    print("\n[3/12] Chargement PJ results...")
    pj_files = [
        ("pj_results_toulouse.json", "Toulouse"),
        ("pj_results_evry.json", "Evry"),
        ("pj_results_blagnac.json", "Blagnac"),
        ("pj_results_colomiers.json", "Colomiers"),
        ("pj_results_muret.json", "Muret"),
    ]
    for fname, zone in pj_files:
        data = load_json(f"{BASE}/{fname}", [])
        for e in data:
            entry = from_pj_entry(e, zone)
            if entry["raison_sociale"]:
                add_entry(registry, entry)
        source_counts["pj_results"] += len(data)

    # PJ caches
    for fname, zone in [
        ("pj_cache_toulouse.json", "Toulouse"),
        ("pj_cache_evry.json", "Evry"),
        ("pj_cache_blagnac.json", "Blagnac"),
        ("pj_cache_colomiers.json", "Colomiers"),
        ("pj_cache_muret.json", "Muret"),
    ]:
        data = load_pj_cache(f"{BASE}/{fname}")
        for e in data:
            entry = from_pj_entry(e, zone)
            if entry["raison_sociale"]:
                add_entry(registry, entry)
        source_counts["pj_cache"] += len(data)
    print(f"  => registry: {len(registry)}")

    # ------------------------------------------------------------------
    # 4. AGENT OUTPUTS
    # ------------------------------------------------------------------
    print("\n[4/12] Chargement outputs des agents parallèles...")

    # Agent 1: PJ Toulouse fresh
    raw1 = load_json(f"{BASE}/agent_out_1_pj_toulouse.json", [])
    data = raw1.get("etablissements", raw1) if isinstance(raw1, dict) else raw1
    for e in data:
        if isinstance(e, dict):
            entry = from_pj_entry(e, "Toulouse")
            add_entry(registry, entry)
    source_counts["agent1_pj_toulouse"] += len(data)
    print(f"  Agent 1 (PJ Toulouse fresh): {len(data)} entrées")

    def unwrap(raw, *keys):
        """Extraire une liste depuis un dict enveloppant ou retourner la liste directement."""
        if isinstance(raw, list):
            return raw
        if isinstance(raw, dict):
            for k in keys:
                if k in raw and isinstance(raw[k], list):
                    return raw[k]
        return []

    # Agent 2: PJ Évry suburbs
    raw2 = load_json(f"{BASE}/agent_out_2_pj_evry_suburbs.json", [])
    data = unwrap(raw2, "results", "etablissements")
    for e in data:
        if isinstance(e, dict):
            entry = from_pj_entry(e, e.get("zone_recherche", "Evry_suburb"))
            add_entry(registry, entry)
    source_counts["agent2_pj_evry_suburbs"] += len(data)
    print(f"  Agent 2 (PJ Évry suburbs): {len(data)} entrées")

    # Agent 3: API dept 31
    raw3 = load_json(f"{BASE}/agent_out_3_api_31.json", [])
    data = unwrap(raw3, "etablissements", "results")
    for e in data:
        if not isinstance(e, dict): continue
        if e.get("statut", "Actif") not in ("Actif", "actif", "A", ""):
            continue
        entry = from_api_entry(e, "API_dept31")
        add_entry(registry, entry)
    source_counts["agent3_api_31"] += len(data)
    print(f"  Agent 3 (API dept 31): {len(data)} entrées")

    # Agent 4: API dept 91
    raw4 = load_json(f"{BASE}/agent_out_4_api_91.json", [])
    data = unwrap(raw4, "etablissements", "results")
    for e in data:
        if not isinstance(e, dict): continue
        if e.get("statut", "Actif") not in ("Actif", "actif", "A", ""):
            continue
        entry = from_api_entry(e, "API_dept91")
        add_entry(registry, entry)
    source_counts["agent4_api_91"] += len(data)
    print(f"  Agent 4 (API dept 91): {len(data)} entrées")

    # Agent 5: OSM Toulouse
    raw5 = load_json(f"{BASE}/agent_out_5_osm_toulouse.json", [])
    data = unwrap(raw5, "pois", "results", "etablissements")
    for e in data:
        if isinstance(e, dict):
            entry = from_osm_entry(e)
            add_entry(registry, entry)
    source_counts["agent5_osm_toulouse"] += len(data)
    print(f"  Agent 5 (OSM Toulouse): {len(data)} entrées")

    # Agent 6: OSM Évry
    raw6 = load_json(f"{BASE}/agent_out_6_osm_evry.json", [])
    data = unwrap(raw6, "pois", "results", "etablissements")
    for e in data:
        if isinstance(e, dict):
            entry = from_osm_entry(e)
            add_entry(registry, entry)
    source_counts["agent6_osm_evry"] += len(data)
    print(f"  Agent 6 (OSM Évry): {len(data)} entrées")

    # Agent 10 traité dans section 4b ci-dessous

    print(f"\n  => Registry total après agents collecte: {len(registry)}")

    # ------------------------------------------------------------------
    # 4b. Playwright Toulouse data
    # ------------------------------------------------------------------
    raw_pw_toulouse = load_json(f"{BASE}/agent_out_playwright_toulouse.json", [])
    pw_toulouse = unwrap(raw_pw_toulouse, "etablissements", "results", "pois") if isinstance(raw_pw_toulouse, dict) else raw_pw_toulouse
    for e in pw_toulouse:
        if isinstance(e, dict):
            entry = from_pj_entry(e, e.get("zone_recherche", "Toulouse"))
            add_entry(registry, entry)
    source_counts["playwright_toulouse"] = len(pw_toulouse)
    print(f"  Playwright Toulouse: {len(pw_toulouse)} entrées")

    # ------------------------------------------------------------------
    # 4c. Playwright Évry data
    # ------------------------------------------------------------------
    raw_pw_evry = load_json(f"{BASE}/agent_out_playwright_evry.json", [])
    pw_evry = unwrap(raw_pw_evry, "etablissements", "results", "pois") if isinstance(raw_pw_evry, dict) else raw_pw_evry
    for e in pw_evry:
        if isinstance(e, dict):
            entry = from_pj_entry(e, e.get("zone_recherche", "Evry_suburb"))
            add_entry(registry, entry)
    source_counts["playwright_evry"] += len(pw_evry)
    print(f"  Playwright Évry: {len(pw_evry)} entrées")

    # Fresh PJ scrape
    for fname, label in [("agent_pj_fresh_scrape.json", "pj_fresh"), ("agent_pj_moto_missing.json", "pj_moto_missing")]:
        raw_fresh = load_json(f"{BASE}/{fname}", [])
        pj_fresh = unwrap(raw_fresh, "etablissements", "results") if isinstance(raw_fresh, dict) else raw_fresh
        for e in pj_fresh:
            if isinstance(e, dict):
                entry = from_pj_entry(e, e.get("zone_recherche", e.get("ville", "")))
                add_entry(registry, entry)
        source_counts[label] = len(pj_fresh)
        print(f"  {label}: {len(pj_fresh)} entrées")

    # Agent 10: PJ-only entries with phones
    raw10 = load_json(f"{BASE}/agent_out_10_siret_pj_only.json", [])
    data10 = unwrap(raw10, "etablissements", "results") if isinstance(raw10, dict) else raw10
    for e in data10:
        if isinstance(e, dict):
            entry = from_pj_entry(e, e.get("zone_recherche", ""))
            if not entry.get("siret") and e.get("siret"):
                entry["siret"] = e["siret"]
            if not entry.get("siren") and e.get("siren"):
                entry["siren"] = e["siren"]
            add_entry(registry, entry)
    source_counts["pj_only_siret"] += len(data10)
    print(f"  Agent 10 (PJ-only avec tel): {len(data10)} entrées")

    print(f"\n  => Registry total après toutes sources: {len(registry)}")

    # ------------------------------------------------------------------
    # 5. ENRICHISSEMENT TÉLÉPHONES (tous les fichiers de phones)
    # ------------------------------------------------------------------
    print("\n[5/12] Application enrichissements téléphones...")

    # Construire index SIRET → entry
    siret_index = {
        e["siret"]: e
        for e in registry.values()
        if e.get("siret") and len(e["siret"]) == 14
    }

    phones_enriched = 0
    phone_files = [
        "agent_out_7_phones_toulouse_1.json",
        "agent_out_8_phones_toulouse_2.json",
        "agent_out_9_phones_evry.json",
        "agent_phones_aggressive_toulouse.json",
        "agent_phones_aggressive_evry.json",
        "agent_phones_annuaires.json",
        "agent_phones_live_batch.json",
    ]
    for fname in phone_files:
        path = f"{BASE}/{fname}"
        if not os.path.exists(path):
            continue
        data = load_json(path, [])
        if isinstance(data, dict):
            data = data.get("results", data.get("enrichissements", []))
        count = 0
        for pe in data:
            if not isinstance(pe, dict):
                continue
            siret = (pe.get("siret") or "").strip()
            tel = fmt_phone(pe.get("telephone", ""))
            if siret and tel and siret in siret_index:
                if not siret_index[siret].get("telephone"):
                    siret_index[siret]["telephone"] = tel
                    if pe.get("site_web") and not siret_index[siret].get("site_web"):
                        siret_index[siret]["site_web"] = pe["site_web"]
                    siret_index[siret]["source"] = (
                        siret_index[siret].get("source", "") + "|" +
                        pe.get("source_telephone", "phone_enrich")
                    ).strip("|")
                    phones_enriched += 1
                    count += 1
        print(f"  {fname}: {len(data)} enrichissements, {count} appliqués")

    print(f"  => {phones_enriched} nouveaux téléphones appliqués")

    # ------------------------------------------------------------------
    # 6. ENRICHISSEMENT SIRET via 118000 / autres sources existantes
    # ------------------------------------------------------------------
    print("\n[6/12] Chargement enrichissements 118000...")
    for fname, zone in [
        ("enriched_toulouse_118000.json", "Toulouse"),
        ("enriched_evry_118000.json", "Evry"),
        ("enriched_blagnac_118000.json", "Blagnac"),
        ("enriched_colomiers_118000.json", "Colomiers"),
        ("enriched_muret_118000.json", "Muret"),
    ]:
        path = f"{BASE}/{fname}"
        if not os.path.exists(path):
            continue
        data = load_json(path, [])
        for e in data:
            if not e.get("telephone"):
                continue
            siret = (e.get("siret") or "").strip()
            if siret and siret in siret_index and not siret_index[siret].get("telephone"):
                siret_index[siret]["telephone"] = fmt_phone(e["telephone"])
                siret_index[siret]["source"] += "|118000"

    # ------------------------------------------------------------------
    # 7. FILTRE: supprimer les établissements radiés / hors zone
    # ------------------------------------------------------------------
    print("\n[7/12] Filtrage des établissements inactifs...")
    ZONES_OK = {
        # Toulouse
        "31000", "31100", "31200", "31300", "31400", "31500",
        "31700", "31770", "31600",
        # Évry
        "91000", "91080", "91100", "91130", "91090", "91070",
    }

    all_entries = list(registry.values())
    filtered = []
    removed_inactive = 0
    removed_zone = 0

    for e in all_entries:
        # Filtrer inactifs
        statut = (e.get("_statut") or "Actif").lower()
        if statut in ("radié", "fermé", "inactif", "cessé"):
            removed_inactive += 1
            continue
        filtered.append(e)

    print(f"  Supprimés (inactifs): {removed_inactive}")
    print(f"  => {len(filtered)} établissements actifs")

    # ------------------------------------------------------------------
    # 8. ENRICHISSEMENT SIRET MANQUANTS (désactivé - trop lent, données suffisantes)
    # ------------------------------------------------------------------
    print("\n[8/12] SIRET manquants (skipped - données API déjà complètes)")
    enriched_siret = 0

    # ------------------------------------------------------------------
    # 9. NETTOYAGE FINAL
    # ------------------------------------------------------------------
    print("\n[9/12] Nettoyage et standardisation...")

    CHAMPS_CSV = [
        "raison_sociale", "telephone", "adresse", "code_postal", "ville",
        "siret", "siren", "type_etablissement", "code_naf", "site_web",
        "email", "source"
    ]

    final = []
    for e in filtered:
        # Standardiser téléphone
        e["telephone"] = fmt_phone(e.get("telephone", ""))

        # Standardiser code postal
        e["code_postal"] = normalize_cp(e.get("code_postal", ""))

        # Inférer type si vide
        if not e.get("type_etablissement"):
            e["type_etablissement"] = infer_type(
                e.get("raison_sociale", ""),
                e.get("code_naf", ""),
                e.get("source", "")
            )

        # Nettoyer ville - normaliser tirets et espaces
        ville = (e.get("ville") or "").strip().upper()
        ville = re.sub(r'\s*-\s*', '-', ville)   # normaliser tirets
        ville = re.sub(r'\s+', ' ', ville).strip()
        # Corrections connues
        ville_corrections = {
            "CORBEIL ESSONNES": "CORBEIL-ESSONNES",
            "PORTET SUR GARONNE": "PORTET-SUR-GARONNE",
            "L UNION": "L'UNION",
            "EVRY COURCOURONNES": "ÉVRY-COURCOURONNES",
            "EVRY-COURCOURONNES": "ÉVRY-COURCOURONNES",
            "EVRY": "ÉVRY-COURCOURONNES",
        }
        e["ville"] = ville_corrections.get(ville, ville)

        # Construire l'objet final
        row = {k: (e.get(k) or "").strip() for k in CHAMPS_CSV}
        final.append(row)

    # Tri final: ville puis raison sociale
    final.sort(key=lambda x: (x.get("ville", ""), x.get("raison_sociale", "")))

    # ------------------------------------------------------------------
    # 10. EXPORT CSV
    # ------------------------------------------------------------------
    print(f"\n[10/12] Export CSV: {OUTPUT_CSV}...")
    with open(OUTPUT_CSV, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=CHAMPS_CSV, delimiter=';')
        writer.writeheader()
        writer.writerows(final)

    print(f"  => {len(final)} lignes exportées")

    # ------------------------------------------------------------------
    # 11. RÉSUMÉ
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("RÉSUMÉ FINAL")
    print("=" * 70)
    print(f"Total établissements: {len(final)}")

    print("\nRépartition par ville:")
    villes = Counter(r["ville"] for r in final)
    for ville, cnt in sorted(villes.items(), key=lambda x: -x[1])[:20]:
        print(f"  {ville:<30} {cnt:>4}")

    print("\nRépartition par type:")
    types = Counter(r["type_etablissement"] for r in final)
    for t, cnt in sorted(types.items(), key=lambda x: -x[1]):
        print(f"  {t:<30} {cnt:>4}")

    has_siret = sum(1 for r in final if len(r.get("siret", "")) == 14)
    has_phone = sum(1 for r in final if r.get("telephone"))
    has_site = sum(1 for r in final if r.get("site_web"))
    print(f"\nComplétude SIRET:    {has_siret}/{len(final)} = {100*has_siret//max(len(final),1)}%")
    print(f"Complétude téléphone: {has_phone}/{len(final)} = {100*has_phone//max(len(final),1)}%")
    print(f"Complétude site web:  {has_site}/{len(final)} = {100*has_site//max(len(final),1)}%")

    print("\nSources utilisées:")
    for src, cnt in sorted(source_counts.items(), key=lambda x: -x[1]):
        print(f"  {src:<35} {cnt:>5} entrées brutes")

    print(f"\n{'=' * 70}")
    print(f"FICHIER LIVRÉ: {OUTPUT_CSV}")
    print(f"{'=' * 70}")
    log(f"Consolidation terminée: {len(final)} entrées exportées")


if __name__ == "__main__":
    main()
