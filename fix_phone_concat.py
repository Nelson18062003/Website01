#!/usr/bin/env python3
"""
Fix concatenated phone numbers in pagesjaunes_garages_france.xlsx.

Problem: The scraper's clean_phone() regex was too greedy and captured
multiple phone numbers concatenated without separators, e.g.:
  "04 93 04 34 3404 82 29 17 16"  (2 numbers × 14 chars = 28 chars)
  "04 92 00 26 4004 93 45 21 5704 93 46 86 27"  (3 numbers = 42 chars)

Fix: Extract only the first valid phone number from each anomalous cell,
     then regenerate the international format.
"""

import re
import pandas as pd


INPUT_FILE = "pagesjaunes_garages_france.xlsx"
OUTPUT_FILE = "pagesjaunes_garages_france.xlsx"

# ---------------------------------------------------------------------------
# Phone extraction
# ---------------------------------------------------------------------------

# Ordered by priority – first match wins
PHONE_PATTERNS = [
    # Monaco international: +377 XX XX XX XX  (16 chars)
    r'\+377\s\d{2}\s\d{2}\s\d{2}\s\d{2}',
    # French international: +33 X XX XX XX XX
    r'\+33\s[1-9](?:\s\d{2}){4}',
    # French with spaces: 0X XX XX XX XX  (most common: 14 chars)
    r'0[1-9](?:\s\d{2}){4}',
    # Special SVA numbers with space after 0: "0 810 05 15 15"
    r'0\s8\d{2}\s\d{2}\s\d{2}\s\d{2}',
    # French without separators: 10 consecutive digits starting with 0
    r'0[1-9]\d{8}',
]

COMBINED_PATTERN = re.compile('|'.join(f'({p})' for p in PHONE_PATTERNS))


def extract_first_phone(raw):
    """Return the first valid phone number found in raw string."""
    if not raw or str(raw).strip() in ('', 'nan', 'None'):
        return ''
    text = str(raw).strip()
    match = COMBINED_PATTERN.search(text)
    if match:
        return match.group(0).strip()
    return ''


def format_phone_intl(phone):
    """Convert a cleaned local French phone to +33 international format."""
    if not phone:
        return ''
    p = phone.strip()
    # Already international
    if p.startswith('+33') or p.startswith('+377'):
        return p
    digits = re.sub(r'[^\d]', '', p)
    if digits.startswith('0') and len(digits) == 10:
        return f"+33 {digits[1]} {digits[2:4]} {digits[4:6]} {digits[6:8]} {digits[8:10]}"
    return p


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 65)
    print("  CORRECTION DES NUMÉROS DE TÉLÉPHONE CONCATÉNÉS")
    print("=" * 65)

    df = pd.read_excel(INPUT_FILE)
    print(f"\nFichier chargé : {len(df):,} lignes")

    tel_col  = 'Téléphone'
    intl_col = 'Téléphone (Intl)'

    df['_tel_str'] = df[tel_col].astype(str).str.strip()

    # Identify anomalies: length > 14 chars (normal max for French phones)
    mask = df['_tel_str'].str.len() > 14
    anomaly_count = mask.sum()
    print(f"Anomalies détectées (len > 14) : {anomaly_count:,}")

    fixed = 0
    lost  = 0   # cases where no phone could be extracted

    for idx in df[mask].index:
        raw = df.at[idx, '_tel_str']
        first = extract_first_phone(raw)

        if first:
            df.at[idx, tel_col]  = first
            df.at[idx, intl_col] = format_phone_intl(first)
            fixed += 1
        else:
            # Nothing recognisable – blank it out rather than keep garbage
            df.at[idx, tel_col]  = ''
            df.at[idx, intl_col] = ''
            lost += 1
            print(f"  [NON RÉSOLU] idx={idx} raw=\"{raw}\"")

    df.drop(columns=['_tel_str'], inplace=True)

    print(f"\nRésultats :")
    print(f"  Corrigés   : {fixed:,}")
    print(f"  Vidés      : {lost:,}  (aucun numéro reconnu)")

    # Verify: no more anomalies
    remaining = (df[tel_col].astype(str).str.strip().str.len() > 14).sum()
    print(f"  Anomalies restantes : {remaining:,}")

    df.to_excel(OUTPUT_FILE, index=False)
    print(f"\nFichier sauvegardé : {OUTPUT_FILE}")
    print("Terminé!")


if __name__ == "__main__":
    main()
