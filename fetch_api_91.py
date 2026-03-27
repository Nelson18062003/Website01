#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agent de collecte - API Recherche Entreprises - Département 91 (Essonne)
Codes NAF: 45.11Z, 45.19Z, 45.20A, 45.20B, 45.32Z, 45.40Z
"""

import urllib.request
import urllib.parse
import json
import ssl
import time
import sys

OUTPUT_FILE = "/home/user/Website01/agent_out_4_api_91.json"

API_URL = "https://recherche-entreprises.api.gouv.fr/search"

NAF_CODES = [
    "45.11Z",
    "45.19Z",
    "45.20A",
    "45.20B",
    "45.32Z",
    "45.40Z",
]

TERMES = ["garage", "concession", "carrosserie", "moto", ""]

TARGET_CP = {
    "91000", "91080",   # Évry-Courcouronnes
    "91100",            # Corbeil-Essonnes
    "91130",            # Ris-Orangis
    "91090",            # Lisses
    "91070",            # Bondoufle
    "91600",            # Savigny-sur-Orge
    "91160",            # Longjumeau
    "91300",            # Massy
}

DELAY        = 0.3   # secondes entre requêtes
MAX_PAGES    = 20
PER_PAGE     = 25
MAX_RETRIES  = 5
RETRY_DELAY  = 5     # secondes sur 429

# SSL context (désactive la vérification si nécessaire)
ssl_ctx = ssl.create_default_context()

def api_get(params: dict) -> dict | None:
    """Effectue une requête GET vers l'API avec retry sur 429."""
    url = API_URL + "?" + urllib.parse.urlencode(params)
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; data-collector/1.0)"}
            )
            with urllib.request.urlopen(req, context=ssl_ctx, timeout=30) as resp:
                raw = resp.read()
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print(f"    [429] Rate limited. Attente {RETRY_DELAY}s (essai {attempt}/{MAX_RETRIES})…")
                time.sleep(RETRY_DELAY)
            else:
                print(f"    [HTTP {e.code}] {url}")
                return None
        except Exception as ex:
            print(f"    [ERR] {ex} (essai {attempt}/{MAX_RETRIES})")
            time.sleep(2)
    return None


def extract_etablissements(data: dict) -> list[dict]:
    """Extrait les établissements pertinents depuis une réponse API."""
    results = []
    for ent in data.get("results", []):
        # Données au niveau entreprise
        siren         = ent.get("siren", "")
        nom_entreprise = (
            ent.get("nom_complet") or
            ent.get("nom_raison_sociale") or
            ent.get("nom") or ""
        )
        # Parcourir les établissements (matching_etablissements en priorité, sinon siege)
        etabs = ent.get("matching_etablissements") or []
        if not etabs:
            siege = ent.get("siege")
            if siege:
                etabs = [siege]

        for etab in etabs:
            siret = etab.get("siret", "")
            if not siret:
                continue

            # Statut
            etat = (etab.get("etat_administratif") or "").strip()
            if etat.upper() not in ("A", "ACTIF"):
                # Certaines API renvoient "A" pour Actif
                # On accepte aussi "" (indéfini) pour ne rien rater
                if etat != "":
                    continue

            # Adresse
            adresse = etab.get("adresse", "") or ""
            if not adresse:
                # Reconstituer depuis champs atomiques
                parts = []
                for k in ("numero_voie", "type_voie", "libelle_voie", "complement_adresse"):
                    v = etab.get(k, "")
                    if v:
                        parts.append(str(v))
                adresse = " ".join(parts).strip()

            cp    = str(etab.get("code_postal", "") or "").strip()
            ville = (etab.get("libelle_commune") or etab.get("commune") or "").strip()

            # Filtrer département 91
            if not cp.startswith("91"):
                continue

            # Code NAF de l'établissement
            code_naf = (
                etab.get("activite_principale") or
                ent.get("activite_principale") or ""
            ).strip()

            # Effectif
            effectif = (
                etab.get("tranche_effectif_salarie") or
                ent.get("tranche_effectifs") or
                etab.get("libelle_tranche_effectif") or ""
            )

            # Date création
            date_creation = (
                etab.get("date_creation") or
                ent.get("date_creation") or ""
            )

            # Statut lisible
            statut_map = {"A": "Actif", "F": "Fermé", "": "Inconnu"}
            statut = statut_map.get(etat.upper(), etat) if etat else "Actif"

            results.append({
                "nom":           nom_entreprise,
                "siret":         siret,
                "siren":         siren,
                "adresse":       adresse,
                "code_postal":   cp,
                "ville":         ville,
                "code_naf":      code_naf,
                "date_creation": date_creation,
                "statut":        statut,
                "effectif":      str(effectif),
            })
    return results


def run():
    seen_sirets: set[str] = set()
    all_results: list[dict] = []

    total_requests  = 0
    total_combos    = len(NAF_CODES) * len(TERMES)
    combo_idx       = 0

    print(f"=== Collecte API Recherche Entreprises - Dép. 91 ===")
    print(f"Codes NAF : {NAF_CODES}")
    print(f"Termes    : {TERMES}")
    print(f"Combos    : {total_combos}")
    print()

    for naf in NAF_CODES:
        for terme in TERMES:
            combo_idx += 1
            label = f"[{combo_idx}/{total_combos}] NAF={naf} terme='{terme}'"
            print(f"{label}")

            page = 1
            combo_count = 0

            while page <= MAX_PAGES:
                params = {
                    "activite_principale": naf,
                    "departement": "91",
                    "per_page": PER_PAGE,
                    "page": page,
                }
                if terme:
                    params["q"] = terme

                time.sleep(DELAY)
                data = api_get(params)
                total_requests += 1

                if data is None:
                    print(f"  Page {page}: erreur, on passe.")
                    break

                # Pagination
                total_api    = data.get("total_results", 0)
                nb_resultats = len(data.get("results", []))

                if nb_resultats == 0:
                    break

                etabs = extract_etablissements(data)
                new_this_page = 0
                for e in etabs:
                    sid = e["siret"]
                    if sid not in seen_sirets:
                        seen_sirets.add(sid)
                        all_results.append(e)
                        new_this_page += 1
                        combo_count += 1

                print(f"  Page {page}/{min(MAX_PAGES, (total_api // PER_PAGE) + 1)}: "
                      f"{nb_resultats} résultats API, {len(etabs)} en 91, {new_this_page} nouveaux "
                      f"(total API annoncé: {total_api})")

                # Conditions de sortie
                if nb_resultats < PER_PAGE:
                    break
                if page * PER_PAGE >= total_api:
                    break

                page += 1

            print(f"  => {combo_count} établissements uniques ajoutés pour cette combinaison")

    # --- Rapport ---
    print()
    print(f"=== RÉSULTATS FINAUX ===")
    print(f"Requêtes API effectuées : {total_requests}")
    print(f"Total établissements uniques (dept 91, Actifs) : {len(all_results)}")
    print()

    # Répartition par ville / code postal
    from collections import Counter
    cp_counter   = Counter()
    ville_counter = Counter()
    for e in all_results:
        cp_counter[e["code_postal"]] += 1
        ville_counter[e["ville"].upper()] += 1

    print("Répartition par code postal (top 30):")
    for cp, cnt in sorted(cp_counter.items(), key=lambda x: -x[1])[:30]:
        marker = " <-- cible" if cp in TARGET_CP else ""
        print(f"  {cp}: {cnt}{marker}")

    print()
    print("Répartition par ville (top 30):")
    for ville, cnt in sorted(ville_counter.items(), key=lambda x: -x[1])[:30]:
        print(f"  {ville}: {cnt}")

    # Villes cibles
    print()
    print("Établissements dans les villes cibles:")
    target_total = sum(cp_counter.get(cp, 0) for cp in TARGET_CP)
    print(f"  Total villes cibles : {target_total}")
    print(f"  Reste département 91 : {len(all_results) - target_total}")

    # Répartition par NAF
    naf_counter = Counter(e["code_naf"] for e in all_results)
    print()
    print("Répartition par code NAF:")
    for naf, cnt in sorted(naf_counter.items(), key=lambda x: -x[1]):
        print(f"  {naf}: {cnt}")

    # Sauvegarde
    output = {
        "meta": {
            "source":        "recherche-entreprises.api.gouv.fr",
            "departement":   "91",
            "codes_naf":     NAF_CODES,
            "termes":        TERMES,
            "total":         len(all_results),
            "requetes_api":  total_requests,
            "date_collecte": "2026-03-27",
        },
        "etablissements": all_results,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print()
    print(f"Fichier sauvegardé : {OUTPUT_FILE}")
    print(f"Taille : {len(all_results)} établissements")


if __name__ == "__main__":
    run()
