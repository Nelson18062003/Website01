#!/usr/bin/env python3
"""Scrape garages automobiles in Nancy (54) and Saint-Denis (93) with SIRET enrichment."""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(__file__))

from build_electriciens import (
    parse_listings, _new_session, search_siret,
    DELAY_BETWEEN_PAGES
)


def scrape_city(query, ou_param, label):
    session = _new_session()
    all_results = []
    page = 1
    empty_pages = 0
    consecutive_errors = 0

    while page <= 50:
        url = "https://www.pagesjaunes.fr/annuaire/chercherlespros"
        params = {"quoiqui": query, "ou": ou_param, "page": str(page)}

        try:
            resp = session.get(url, params=params, timeout=20)
            if resp.status_code == 403:
                consecutive_errors += 1
                if consecutive_errors >= 5:
                    break
                wait = 5 * (2 ** (consecutive_errors - 1))
                print(f"  [{label}] 403 page {page}, wait {wait}s", flush=True)
                time.sleep(wait)
                session = _new_session()
                continue
            if resp.status_code != 200:
                break

            consecutive_errors = 0
            listings = parse_listings(resp.text)
            if not listings:
                empty_pages += 1
                if empty_pages >= 2:
                    break
                page += 1
                time.sleep(DELAY_BETWEEN_PAGES)
                continue

            empty_pages = 0
            all_results.extend(listings)
            print(f"  [{label}] Page {page}: +{len(listings)} (total: {len(all_results)})", flush=True)
            page += 1
            time.sleep(DELAY_BETWEEN_PAGES)

        except Exception as e:
            print(f"  [{label}] ERROR page {page}: {e}", flush=True)
            break

    return all_results


def main():
    cities = [
        ("garages automobiles", "Nancy (54)", "Nancy (54)"),
        ("garages automobiles", "Saint-Denis (93)", "Saint-Denis (93)"),
    ]

    all_data = {}
    for query, ou, label in cities:
        print(f"\n=== Scraping {label} ===", flush=True)
        results = scrape_city(query, ou, label)
        all_data[label] = results
        time.sleep(5)

    # SIRET enrichment
    print(f"\n=== Enrichissement SIRET ===", flush=True)
    for label, companies in all_data.items():
        found = 0
        for i, c in enumerate(companies):
            siren, siret, matched, naf = search_siret(
                c.get("name", ""), c.get("postal_code", ""), c.get("city", "")
            )
            c["siren"] = siren
            c["siret"] = siret
            if siret:
                found += 1
            if (i + 1) % 50 == 0 or (i + 1) == len(companies):
                print(f"  [{label}] {i+1}/{len(companies)} | SIRET: {found}", flush=True)
            time.sleep(0.12)

    # Stats
    print(f"\n{'='*60}", flush=True)
    print(f"  RÉSULTATS FINAUX", flush=True)
    print(f"{'='*60}", flush=True)

    grand_total = 0
    grand_phone = 0
    grand_siret = 0
    grand_both = 0

    for label, companies in all_data.items():
        total = len(companies)
        with_phone = sum(1 for c in companies if c.get("phone"))
        with_siret = sum(1 for c in companies if c.get("siret"))
        with_both = sum(1 for c in companies if c.get("phone") and c.get("siret"))

        grand_total += total
        grand_phone += with_phone
        grand_siret += with_siret
        grand_both += with_both

        print(f"\n  {label}:", flush=True)
        print(f"    Total garages:            {total}", flush=True)
        if total:
            print(f"    Avec téléphone:           {with_phone:>4} ({100*with_phone/total:.1f}%)", flush=True)
            print(f"    Avec SIRET:               {with_siret:>4} ({100*with_siret/total:.1f}%)", flush=True)
            print(f"    Avec téléphone ET SIRET:  {with_both:>4} ({100*with_both/total:.1f}%)", flush=True)

    if grand_total:
        print(f"\n  TOTAL (2 villes):", flush=True)
        print(f"    Total garages:            {grand_total}", flush=True)
        print(f"    Avec téléphone:           {grand_phone:>4} ({100*grand_phone/grand_total:.1f}%)", flush=True)
        print(f"    Avec SIRET:               {grand_siret:>4} ({100*grand_siret/grand_total:.1f}%)", flush=True)
        print(f"    Avec téléphone ET SIRET:  {grand_both:>4} ({100*grand_both/grand_total:.1f}%)", flush=True)

    with open("garages_nancy_saintdenis.json", "w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)
    print(f"\n  Données sauvegardées: garages_nancy_saintdenis.json", flush=True)


if __name__ == "__main__":
    main()
