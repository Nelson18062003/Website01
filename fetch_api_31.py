#!/usr/bin/env python3
"""
Agent collecte données - API Recherche Entreprises - Département 31 (Haute-Garonne)
Fichier de sortie: /home/user/Website01/agent_out_3_api_31.json
"""

import urllib.request
import urllib.parse
import json
import ssl
import time
import sys
from collections import defaultdict

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASE_URL = "https://recherche-entreprises.api.gouv.fr/search"
OUTPUT_FILE = "/home/user/Website01/agent_out_3_api_31.json"
DEPARTEMENT = "31"
PER_PAGE = 25
MAX_PAGES = 20
DELAY = 1.0          # secondes entre requêtes
RETRY_WAIT = 10      # secondes si HTTP 429
MAX_RETRIES = 5

NAF_CODES = [
    "45.11Z",
    "45.19Z",
    "45.20A",
    "45.20B",
    "45.32Z",
    "45.40Z",
]

SEARCH_TERMS = [
    "garage automobile",
    "concession automobile",
    "carrosserie",
    "moto",
    "",
]

# Désactiver la vérification SSL si nécessaire
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def api_get(params: dict) -> dict | None:
    """Effectue une requête GET avec gestion des retries (HTTP 429)."""
    url = BASE_URL + "?" + urllib.parse.urlencode(params)
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "DataCollectionAgent/1.0"},
            )
            with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print(f"    [429] Rate-limit – attente {RETRY_WAIT}s (tentative {attempt}/{MAX_RETRIES})")
                time.sleep(RETRY_WAIT)
            else:
                print(f"    [HTTP {e.code}] {url}")
                return None
        except Exception as ex:
            print(f"    [ERR] {ex} – {url}")
            return None
    return None


def extract_etablissement(hit: dict) -> dict | None:
    """Extrait les champs voulus d'un résultat brut de l'API."""
    siege = hit.get("siege") or {}

    # ---- Nom ----
    nom = (
        hit.get("nom_complet")
        or hit.get("denomination")
        or siege.get("denomination")
        or ""
    ).strip()

    # ---- SIRET / SIREN ----
    siret = (siege.get("siret") or "").strip()
    siren = (hit.get("siren") or "").strip()

    # ---- Adresse ----
    adresse = (siege.get("adresse") or "").strip()
    if not adresse:
        parts = [
            siege.get("numero_voie") or "",
            siege.get("type_voie") or "",
            siege.get("libelle_voie") or "",
            siege.get("code_postal") or "",
            siege.get("libelle_commune") or "",
        ]
        adresse = " ".join(p for p in parts if p).strip()

    code_postal = (siege.get("code_postal") or "").strip()
    ville = (siege.get("libelle_commune") or "").strip()

    # ---- Code NAF ----
    code_naf = (
        hit.get("activite_principale")
        or siege.get("activite_principale")
        or ""
    ).strip()

    # ---- Date création ----
    date_creation = (hit.get("date_creation") or "").strip()

    # ---- Statut ----
    etat = (
        hit.get("etat_administratif")
        or siege.get("etat_administratif")
        or ""
    ).strip()
    statut = "Actif" if etat == "A" else "Inactif"

    # ---- Effectif ----
    effectif = (
        hit.get("tranche_effectif_salarie")
        or hit.get("categorie_entreprise")
        or ""
    )

    return {
        "nom": nom,
        "siret": siret,
        "siren": siren,
        "adresse": adresse,
        "code_postal": code_postal,
        "ville": ville,
        "code_naf": code_naf,
        "date_creation": date_creation,
        "statut": statut,
        "effectif": effectif,
    }


def is_valid(etab: dict) -> bool:
    """Filtre: actif ET code postal commençant par 31."""
    return (
        etab["statut"] == "Actif"
        and etab["code_postal"].startswith("31")
    )


# ---------------------------------------------------------------------------
# Collecte principale
# ---------------------------------------------------------------------------
def collect():
    all_by_siret: dict[str, dict] = {}
    total_requests = 0
    combos = [(naf, term) for naf in NAF_CODES for term in SEARCH_TERMS]

    print(f"Démarrage – {len(combos)} combinaisons NAF×terme")
    print(f"Département: {DEPARTEMENT} | Max pages: {MAX_PAGES} | Délai: {DELAY}s\n")

    for combo_idx, (naf, term) in enumerate(combos, 1):
        label = f"NAF={naf} | q='{term}'"
        print(f"[{combo_idx:02d}/{len(combos)}] {label}")
        found_this_combo = 0

        for page in range(1, MAX_PAGES + 1):
            params = {
                "activite_principale": naf,
                "departement": DEPARTEMENT,
                "per_page": PER_PAGE,
                "page": page,
            }
            if term:
                params["q"] = term

            data = api_get(params)
            total_requests += 1
            time.sleep(DELAY)

            if data is None:
                print(f"    Page {page}: erreur, on passe à la suite")
                break

            results = data.get("results", [])
            total_found = data.get("total_results", 0)

            if not results:
                break  # Plus de résultats

            new_count = 0
            for hit in results:
                etab = extract_etablissement(hit)
                if etab and is_valid(etab):
                    siret = etab["siret"]
                    if siret and siret not in all_by_siret:
                        all_by_siret[siret] = etab
                        new_count += 1
                        found_this_combo += 1
                    elif not siret:
                        # Pas de SIRET : on tente avec le SIREN comme clé de dédup
                        siren_key = f"siren_{etab['siren']}"
                        if siren_key not in all_by_siret:
                            all_by_siret[siren_key] = etab
                            new_count += 1
                            found_this_combo += 1

            print(f"    Page {page}/{MAX_PAGES} – {len(results)} résultats, {new_count} nouveaux | Total API: {total_found}")

            # Arrêt si on a tout récupéré
            if len(results) < PER_PAGE or page * PER_PAGE >= total_found:
                break

        print(f"  => {found_this_combo} établissements ajoutés pour cette combinaison\n")

    print(f"\nRequêtes API effectuées: {total_requests}")
    return list(all_by_siret.values())


# ---------------------------------------------------------------------------
# Statistiques
# ---------------------------------------------------------------------------
def print_stats(etablissements: list[dict]):
    total = len(etablissements)
    print(f"\n{'='*60}")
    print(f"TOTAL établissements (dédoublonnés): {total}")

    # Répartition par NAF
    naf_count = defaultdict(int)
    for e in etablissements:
        naf_count[e["code_naf"]] += 1
    print(f"\nRépartition par code NAF:")
    for naf, count in sorted(naf_count.items(), key=lambda x: -x[1]):
        print(f"  {naf:10s}: {count:4d}")

    # Top 10 villes
    ville_count = defaultdict(int)
    for e in etablissements:
        ville_count[e["ville"] or "INCONNUE"] += 1
    top10 = sorted(ville_count.items(), key=lambda x: -x[1])[:10]
    print(f"\nTop 10 villes:")
    for ville, count in top10:
        print(f"  {ville:30s}: {count:4d}")
    print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------
def main():
    etablissements = collect()
    print_stats(etablissements)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(etablissements, f, ensure_ascii=False, indent=2)

    print(f"Fichier sauvegardé: {OUTPUT_FILE}")
    print(f"Nombre d'entrées: {len(etablissements)}")


if __name__ == "__main__":
    main()
