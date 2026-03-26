#!/usr/bin/env python3
"""
Enrichissement des entreprises automobiles de Bordeaux.
Recherche telephone, email, site_web via societe.com et annuaire-entreprises.
"""

import json
import re
import time
import urllib.request
import urllib.parse
import urllib.error
import ssl
import sys
import os
import random

# Ignorer les erreurs SSL pour les requetes simples
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

INPUT_FILE = "/home/user/Website01/split_bordeaux.json"
OUTPUT_FILE = "/home/user/Website01/enriched_bordeaux.json"
PROGRESS_FILE = "/home/user/Website01/enrichment_progress.json"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]


def get_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.5",
    }


def fetch_url(url, timeout=15):
    """Recupere le contenu d'une URL."""
    try:
        req = urllib.request.Request(url, headers=get_headers())
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read()
            # Essayer plusieurs encodages
            for enc in ["utf-8", "latin-1", "iso-8859-1"]:
                try:
                    return raw.decode(enc)
                except UnicodeDecodeError:
                    continue
            return raw.decode("utf-8", errors="replace")
    except Exception as e:
        return ""


def clean_phone(phone):
    """Nettoie et valide un numero de telephone francais."""
    phone = re.sub(r'[^\d+]', '', phone)
    # Format francais : 0X XX XX XX XX (10 chiffres)
    if phone.startswith('+33'):
        phone = '0' + phone[3:]
    if phone.startswith('33') and len(phone) == 11:
        phone = '0' + phone[2:]
    if len(phone) == 10 and phone.startswith('0'):
        # Formater joliment
        return f"{phone[0:2]} {phone[2:4]} {phone[4:6]} {phone[6:8]} {phone[8:10]}"
    return ""


def extract_phones(html):
    """Extrait les numeros de telephone d'une page HTML."""
    phones = set()
    # Patterns courants pour les telephones francais
    patterns = [
        r'(?:tel|phone|telephone|téléphone|tél)["\s:=]*[+]?[\s]*((?:0|\+33|33)[\s.-]*[1-9](?:[\s.-]*\d{2}){4})',
        r'href="tel:((?:0|\+33|33)[\s.-]*[1-9](?:[\s.-]*\d{2}){4})"',
        r'(?<!\d)(0[1-9][\s.-]?\d{2}[\s.-]?\d{2}[\s.-]?\d{2}[\s.-]?\d{2})(?!\d)',
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, html, re.IGNORECASE):
            cleaned = clean_phone(match.group(1) if match.lastindex else match.group(0))
            if cleaned:
                phones.add(cleaned)
    return list(phones)


def extract_emails(html):
    """Extrait les adresses email d'une page HTML."""
    emails = set()
    pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    for match in re.finditer(pattern, html):
        email = match.group(0).lower()
        # Filtrer les faux positifs
        skip = ['example.com', 'sentry.io', 'wixpress.com', 'google.com',
                'facebook.com', 'twitter.com', 'w3.org', '.png', '.jpg',
                '.gif', '.svg', 'webpack', 'babel', 'eslint', 'jquery',
                'bootstrap', 'noreply', 'no-reply', 'placeholder']
        if not any(s in email for s in skip):
            emails.add(email)
    return list(emails)


def extract_website(html, nom_entreprise=""):
    """Extrait le site web d'une page HTML (source annuaire/societe)."""
    sites = set()
    # Chercher des liens explicitement marques comme site web
    patterns = [
        r'(?:site[_ ]?web|site[_ ]?internet|website|url)["\s:=]*(?:<[^>]*href=")?(?:https?://)?([a-zA-Z0-9][\w.-]*\.[a-zA-Z]{2,}(?:/[^\s"<]*)?)',
        r'href="(https?://(?:www\.)?[a-zA-Z0-9][\w.-]*\.[a-zA-Z]{2,}(?:/[^\s"<]*)?)"[^>]*>(?:[^<]*(?:site|web|visit))',
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, html, re.IGNORECASE):
            site = match.group(1)
            if not site.startswith("http"):
                site = "https://" + site
            # Filtrer les sites d'annuaires eux-memes
            skip_domains = ['societe.com', 'annuaire.com', 'pagesjaunes.fr',
                          'google.com', 'facebook.com', 'twitter.com',
                          'linkedin.com', 'instagram.com', 'youtube.com',
                          'apple.com', 'microsoft.com', 'wikipedia.org',
                          'gouv.fr', 'infogreffe.fr', 'bodacc.fr',
                          'annuaire-entreprises', 'verif.com', 'pappers.fr',
                          'manageo.fr', 'insee.fr']
            if not any(d in site.lower() for d in skip_domains):
                sites.add(site)
    return list(sites)


def search_annuaire_entreprises(siren):
    """Recherche sur annuaire-entreprises.data.gouv.fr (API publique)."""
    result = {"telephone": "", "email": "", "site_web": ""}
    if not siren:
        return result
    url = f"https://recherche-entreprises.api.gouv.fr/search?q={siren}&page=1&per_page=1"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": random.choice(USER_AGENTS)})
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("results"):
                # L'API ne fournit pas toujours telephone/email, mais tentons
                r = data["results"][0]
                # Complements may have phone info in some cases
                complements = r.get("complements", {})
                if complements.get("collectivite_territoriale"):
                    tel = complements["collectivite_territoriale"].get("telephone", "")
                    if tel:
                        result["telephone"] = clean_phone(tel)
    except Exception:
        pass
    return result


def search_societe_com(siren):
    """Recherche sur societe.com pour trouver telephone/site_web."""
    result = {"telephone": "", "email": "", "site_web": ""}
    if not siren:
        return result

    url = f"https://www.societe.com/cgi-bin/search?champs={siren}"
    html = fetch_url(url)
    if not html:
        return result

    phones = extract_phones(html)
    if phones:
        result["telephone"] = phones[0]

    emails = extract_emails(html)
    if emails:
        result["email"] = emails[0]

    sites = extract_website(html)
    if sites:
        result["site_web"] = sites[0]

    return result


def search_pappers(siren):
    """Recherche sur pappers.fr."""
    result = {"telephone": "", "email": "", "site_web": ""}
    if not siren:
        return result

    url = f"https://www.pappers.fr/entreprise/{siren}"
    html = fetch_url(url)
    if not html:
        return result

    phones = extract_phones(html)
    if phones:
        result["telephone"] = phones[0]

    emails = extract_emails(html)
    if emails:
        result["email"] = emails[0]

    sites = extract_website(html)
    if sites:
        result["site_web"] = sites[0]

    return result


def search_google(nom, ville):
    """Recherche Google pour trouver telephone et site web."""
    result = {"telephone": "", "email": "", "site_web": ""}
    query = urllib.parse.quote(f"{nom} {ville} telephone site web")
    url = f"https://www.google.com/search?q={query}&hl=fr&num=5"
    html = fetch_url(url)
    if not html:
        return result

    phones = extract_phones(html)
    if phones:
        result["telephone"] = phones[0]

    emails = extract_emails(html)
    if emails:
        result["email"] = emails[0]

    sites = extract_website(html, nom)
    if sites:
        result["site_web"] = sites[0]

    return result


def search_bing(nom, ville):
    """Recherche Bing comme alternative."""
    result = {"telephone": "", "email": "", "site_web": ""}
    query = urllib.parse.quote(f"{nom} {ville} téléphone")
    url = f"https://www.bing.com/search?q={query}&setlang=fr"
    html = fetch_url(url)
    if not html:
        return result

    phones = extract_phones(html)
    if phones:
        result["telephone"] = phones[0]

    emails = extract_emails(html)
    if emails:
        result["email"] = emails[0]

    sites = extract_website(html, nom)
    if sites:
        result["site_web"] = sites[0]

    return result


def enrich_entreprise(entreprise, index, total):
    """Enrichit une entreprise avec telephone, email, site_web."""
    nom = entreprise.get("nom", "")
    siren = entreprise.get("siren", "")
    ville = entreprise.get("ville", "")

    telephone = ""
    email = ""
    site_web = ""

    print(f"[{index+1}/{total}] {nom} (SIREN: {siren})...", end=" ", flush=True)

    # 1) API annuaire-entreprises (rapide, gratuit, fiable)
    try:
        r = search_annuaire_entreprises(siren)
        if r["telephone"]:
            telephone = r["telephone"]
        if r["email"]:
            email = r["email"]
        if r["site_web"]:
            site_web = r["site_web"]
    except Exception:
        pass

    # 2) Pappers
    if not telephone or not site_web:
        time.sleep(random.uniform(1.0, 2.5))
        try:
            r = search_pappers(siren)
            if not telephone and r["telephone"]:
                telephone = r["telephone"]
            if not email and r["email"]:
                email = r["email"]
            if not site_web and r["site_web"]:
                site_web = r["site_web"]
        except Exception:
            pass

    # 3) societe.com
    if not telephone or not site_web:
        time.sleep(random.uniform(1.0, 2.5))
        try:
            r = search_societe_com(siren)
            if not telephone and r["telephone"]:
                telephone = r["telephone"]
            if not email and r["email"]:
                email = r["email"]
            if not site_web and r["site_web"]:
                site_web = r["site_web"]
        except Exception:
            pass

    # 4) Recherche Bing
    if not telephone or not site_web:
        time.sleep(random.uniform(1.5, 3.0))
        try:
            r = search_bing(nom, ville)
            if not telephone and r["telephone"]:
                telephone = r["telephone"]
            if not email and r["email"]:
                email = r["email"]
            if not site_web and r["site_web"]:
                site_web = r["site_web"]
        except Exception:
            pass

    status = []
    if telephone:
        status.append(f"tel={telephone}")
    if email:
        status.append(f"email={email}")
    if site_web:
        status.append(f"web={site_web}")
    print(" | ".join(status) if status else "rien trouvé")

    entreprise["telephone"] = telephone
    entreprise["email"] = email
    entreprise["site_web"] = site_web

    return entreprise


def main():
    # Mode test: seulement les N premieres entreprises
    test_mode = "--test" in sys.argv
    test_count = 5

    # Charger les donnees source
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        entreprises = json.load(f)

    total = len(entreprises)
    print(f"Fichier charge: {total} entreprises")

    # Charger la progression si elle existe
    enriched = []
    start_index = 0
    if os.path.exists(PROGRESS_FILE) and not test_mode:
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            enriched = json.load(f)
        start_index = len(enriched)
        print(f"Reprise depuis l'index {start_index} ({start_index} deja traites)")

    if test_mode:
        entreprises = entreprises[:test_count]
        total = test_count
        enriched = []
        start_index = 0
        print(f"=== MODE TEST: {test_count} entreprises ===")

    # Traiter chaque entreprise
    for i in range(start_index, len(entreprises)):
        ent = entreprises[i]
        try:
            enriched_ent = enrich_entreprise(ent, i, total)
            enriched.append(enriched_ent)
        except Exception as e:
            print(f"  ERREUR: {e}")
            ent["telephone"] = ""
            ent["email"] = ""
            ent["site_web"] = ""
            enriched.append(ent)

        # Sauvegarder la progression regulierement (toutes les 10 entreprises)
        if (i + 1) % 10 == 0 or i == len(entreprises) - 1:
            if not test_mode:
                with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
                    json.dump(enriched, f, ensure_ascii=False, indent=2)
                print(f"  [Progression sauvegardee: {len(enriched)}/{total}]")

    # Sauvegarder le resultat final
    output = OUTPUT_FILE
    with open(output, "w", encoding="utf-8") as f:
        json.dump(enriched, f, ensure_ascii=False, indent=2)

    # Stats
    with_phone = sum(1 for e in enriched if e.get("telephone"))
    with_email = sum(1 for e in enriched if e.get("email"))
    with_web = sum(1 for e in enriched if e.get("site_web"))
    print(f"\n=== RESULTATS ===")
    print(f"Total: {len(enriched)} entreprises")
    print(f"Avec telephone: {with_phone} ({100*with_phone/len(enriched):.1f}%)")
    print(f"Avec email: {with_email} ({100*with_email/len(enriched):.1f}%)")
    print(f"Avec site web: {with_web} ({100*with_web/len(enriched):.1f}%)")
    print(f"Fichier sauvegarde: {output}")


if __name__ == "__main__":
    main()
