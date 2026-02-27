#!/usr/bin/env python3
"""Parallel SIRET enrichment worker. Processes a slice of companies."""
import json, os, sys, time, requests

API_URL = "https://recherche-entreprises.api.gouv.fr/search"
API_DELAY = 0.12


def search_siret(company_name, postal_code, city):
    if not company_name:
        return "", "", "", ""
    query = str(company_name).strip()
    params = {"q": query, "per_page": 5}
    if postal_code:
        pc = str(postal_code).strip()
        if pc and pc != "None":
            params["code_postal"] = pc
    try:
        resp = requests.get(API_URL, params=params, timeout=15)
        if resp.status_code == 429:
            time.sleep(3)
            resp = requests.get(API_URL, params=params, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            results = data.get("results", [])
            if results:
                best = results[0]
                siren = best.get("siren", "")
                siege = best.get("siege", {})
                siret = siege.get("siret", "")
                matched_name = best.get("nom_complet", "")
                naf = best.get("activite_principale", "")
                return siren, siret, matched_name, naf
        if city and str(city).strip() != "None":
            params2 = {"q": f"{query} {city}", "per_page": 5}
            resp2 = requests.get(API_URL, params=params2, timeout=15)
            if resp2.status_code == 200:
                data2 = resp2.json()
                results2 = data2.get("results", [])
                if results2:
                    best = results2[0]
                    siren = best.get("siren", "")
                    siege = best.get("siege", {})
                    siret = siege.get("siret", "")
                    matched_name = best.get("nom_complet", "")
                    naf = best.get("activite_principale", "")
                    return siren, siret, matched_name, naf
    except requests.exceptions.RequestException:
        pass
    return "", "", "", ""


def main():
    worker_id = int(sys.argv[1])
    total_workers = int(sys.argv[2])
    output_file = f"siret_worker_{worker_id}.json"

    # Load existing SIRET cache
    main_cache_file = "electriciens_siret_cache.json"
    existing_cache = {}
    if os.path.exists(main_cache_file):
        with open(main_cache_file, "r", encoding="utf-8") as f:
            existing_cache = json.load(f)

    # Load all company data
    sys.path.insert(0, os.path.dirname(__file__))
    from build_electriciens import load_all_data
    companies = load_all_data()
    total = len(companies)

    # Split work
    chunk_size = total // total_workers
    start = worker_id * chunk_size
    end = start + chunk_size if worker_id < total_workers - 1 else total
    my_companies = companies[start:end]

    # Count how many are already cached
    cached_count = sum(1 for c in my_companies
                       if f"{c.get('name','')}|{c.get('postal_code','')}|{c.get('city','')}" in existing_cache)
    to_fetch = len(my_companies) - cached_count

    print(f"[W{worker_id}] {len(my_companies)} companies (idx {start}-{end}), {cached_count} cached, {to_fetch} to fetch", flush=True)

    results = {}
    found = 0
    not_found = 0

    for i, company in enumerate(my_companies):
        name = company.get("name", "")
        postal_code = company.get("postal_code", "")
        city = company.get("city", "")
        cache_key = f"{name}|{postal_code}|{city}"

        if cache_key in existing_cache:
            siren, siret, matched_name, naf = existing_cache[cache_key]
        else:
            siren, siret, matched_name, naf = search_siret(name, postal_code, city)
            time.sleep(API_DELAY)

        results[cache_key] = [siren, siret, matched_name, naf]

        if siren:
            found += 1
        else:
            not_found += 1

        current = i + 1
        if current % 50 == 0 or current == len(my_companies):
            print(f"[W{worker_id}] {current}/{len(my_companies)} | SIRET:{found} miss:{not_found}", flush=True)
            # Save partial results
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False)

    print(f"[W{worker_id}] DONE {found}/{len(my_companies)} -> {output_file}", flush=True)


if __name__ == "__main__":
    main()
