"""Shared utilities for medical structure scrapers."""
import json
import logging
import os
import re
import time
import requests

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
os.makedirs(DATA_DIR, exist_ok=True)

NAF_CODES = {
    "86.21Z": "Activité des médecins généralistes",
    "86.22A": "Activités de radiodiagnostic et de radiothérapie",
    "86.22C": "Autres activités des médecins spécialistes",
    "86.23Z": "Pratique dentaire",
    "86.10Z": "Activités hospitalières",
    "86.90B": "Laboratoires d'analyses médicales",
    "86.90E": "Activités des professionnels de la rééducation",
    "86.90F": "Activités de santé humaine non classées ailleurs",
}

NAF_CATEGORY_MAP = {
    "86.21Z": "Cabinet médical / Médecin généraliste",
    "86.22A": "Centre de radiologie / Imagerie médicale",
    "86.22C": "Cabinet de médecin spécialiste",
    "86.23Z": "Cabinet dentaire",
    "86.10Z": "Hôpital / Clinique",
    "86.90B": "Laboratoire d'analyses médicales",
    "86.90E": "Cabinet de kinésithérapie / Rééducation",
    "86.90F": "Autre structure de santé",
}

ZONES = {
    "paris": {
        "postal_codes": [f"750{i:02d}" for i in range(1, 21)],
        "department": "75",
    },
    "marseille": {
        "postal_codes": [f"130{i:02d}" for i in range(1, 17)],
        "department": "13",
    },
    "lille": {
        "postal_codes": ["59000", "59800", "59100", "59200", "59491", "59130", "59110"],
        "department": "59",
    },
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}


def setup_logging(name):
    """Setup logging for a scraper module."""
    log_file = os.path.join(os.path.dirname(__file__), 'scraper-medical.log')
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        fh = logging.FileHandler(log_file, encoding='utf-8')
        fh.setLevel(logging.INFO)
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        fmt = logging.Formatter('%(asctime)s [%(name)s] %(levelname)s: %(message)s')
        fh.setFormatter(fmt)
        ch.setFormatter(fmt)
        logger.addHandler(fh)
        logger.addHandler(ch)
    return logger


def normalize_name(name):
    """Normalize a business name for deduplication."""
    if not name:
        return ""
    name = name.upper().strip()
    name = re.sub(r'[^A-Z0-9\s]', '', name)
    name = re.sub(r'\s+', ' ', name)
    for w in ['SAS', 'SARL', 'SA', 'SCI', 'EURL', 'EI', 'SELARL', 'SCM', 'SCP', 'DR', 'DOCTEUR', 'CABINET', 'CENTRE', 'CLINIQUE']:
        name = re.sub(rf'\b{w}\b', '', name)
    return name.strip()


def format_phone(phone):
    """Format phone number to 0X XX XX XX XX."""
    if not phone:
        return ""
    digits = re.sub(r'[^\d]', '', str(phone))
    if digits.startswith('33') and len(digits) == 11:
        digits = '0' + digits[2:]
    if digits.startswith('+33'):
        digits = '0' + digits[3:]
    if len(digits) == 10 and digits.startswith('0'):
        return f"{digits[0:2]} {digits[2:4]} {digits[4:6]} {digits[6:8]} {digits[8:10]}"
    return phone


def format_postal_code(cp):
    """Ensure postal code is 5 digits."""
    if not cp:
        return ""
    cp = str(cp).strip()
    digits = re.sub(r'[^\d]', '', cp)
    if len(digits) <= 5:
        return digits.zfill(5)
    return digits[:5]


def save_json(data, filename):
    """Save data to JSON file in data directory."""
    filepath = os.path.join(DATA_DIR, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return filepath


def load_json(filename):
    """Load data from JSON file in data directory."""
    filepath = os.path.join(DATA_DIR, filename)
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []


def safe_request(url, params=None, headers=None, timeout=30, retries=3, delay=1.5):
    """Make a request with retries and delay."""
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=headers or HEADERS, timeout=timeout)
            if r.status_code == 200:
                return r
            if r.status_code == 429:
                wait = (attempt + 1) * 5
                time.sleep(wait)
                continue
            if r.status_code >= 500:
                time.sleep(delay * (attempt + 1))
                continue
            return r
        except (requests.RequestException, Exception) as e:
            if attempt < retries - 1:
                time.sleep(delay * (attempt + 1))
            else:
                return None
    return None


def categorize_by_naf_and_name(naf_code, name=""):
    """Assign a precise category based on NAF code and business name."""
    name_upper = (name or "").upper()

    if naf_code == "86.10Z" or naf_code == "8610Z":
        if any(w in name_upper for w in ["CLINIQUE", "POLYCLINIQUE"]):
            return "Clinique privée"
        if any(w in name_upper for w in ["DIALYSE", "NEPHROLOG"]):
            return "Centre de dialyse"
        if any(w in name_upper for w in ["MUTUALISTE", "MUTUELLE"]):
            return "Centre mutualiste"
        return "Hôpital"

    if naf_code in ("86.22C", "8622C"):
        if any(w in name_upper for w in ["OPHTALMOL", "OPHTALMO", "OEIL", "VISION"]):
            return "Cabinet d'ophtalmologie"
        if any(w in name_upper for w in ["DERMATOL", "DERMATO", "PEAU"]):
            return "Cabinet de dermatologie"
        if any(w in name_upper for w in ["CARDIOLOG", "CARDIO", "COEUR"]):
            return "Cabinet de cardiologie"
        if any(w in name_upper for w in ["GYNECOL", "GYNÉCO", "OBSTETRI"]):
            return "Cabinet de gynécologie"
        if any(w in name_upper for w in ["TRAVAIL", "SANTE AU TRAVAIL", "SIST", "SSTI"]):
            return "Centre de médecine du travail"
        return "Cabinet de médecin spécialiste"

    if naf_code in ("86.21Z", "8621Z"):
        if any(w in name_upper for w in ["MAISON DE SANTE", "MSP", "PLURIDISCIPL", "PLURIPROFESS"]):
            return "Maison de santé pluridisciplinaire"
        if any(w in name_upper for w in ["CENTRE DE SANTE", "CDS", "MUNICIPAL"]):
            return "Centre de santé"
        if any(w in name_upper for w in ["UNIVERSITAIRE", "UNIVERSITE"]):
            return "Centre de santé universitaire"
        return "Cabinet médical / Médecin généraliste"

    if naf_code in ("86.22A", "8622A"):
        if any(w in name_upper for w in ["RADIOTHERAP"]):
            return "Centre de radiothérapie"
        return "Centre de radiologie / Imagerie médicale"

    if naf_code in ("86.23Z", "8623Z"):
        return "Cabinet dentaire"

    if naf_code in ("86.90B", "8690B"):
        return "Laboratoire d'analyses médicales"

    if naf_code in ("86.90E", "8690E"):
        return "Cabinet de kinésithérapie / Rééducation"

    if naf_code in ("86.90F", "8690F"):
        if any(w in name_upper for w in ["VACCIN"]):
            return "Centre de vaccination"
        return "Autre structure de santé"

    return "Structure médicale"
