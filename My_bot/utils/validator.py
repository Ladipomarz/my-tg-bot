import re
import datetime
import difflib

# Allows letters plus space, apostrophe, hyphen (no dots, no random symbols)
_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z'\- ]*[A-Za-z]$")


def is_valid_dob(dob_str: str) -> bool:
    """
    Validates DOB format: YYYY/MM/DD and checks if it's a real date.
    Example valid: 1995/12/31
    """
    dob_str = (dob_str or "").strip()
    if not re.match(r"^\d{4}/\d{2}/\d{2}$", dob_str):
        return False

    year_str, month_str, day_str = dob_str.split("/")
    try:
        datetime.date(int(year_str), int(month_str), int(day_str))
    except ValueError:
        return False

    return True


def is_valid_name(name: str) -> bool:
    """
    Name validation:
    - 2+ chars
    - letters only, plus: space, apostrophe, hyphen
    - no leading/trailing spaces, no dots or other symbols
    Examples valid: John, Mary-Jane, O'Neil, De La Cruz
    """
    name = (name or "").strip()

    if len(name) < 2:
        return False

    # Normalize multiple spaces
    name = re.sub(r"\s+", " ", name)

    # Must match allowed pattern
    if not _NAME_RE.match(name):
        return False

    return True


def is_valid_zip(zip_str: str) -> bool:
    """
    US ZIP validation:
    - 5 digits (e.g. 90210)
    - optionally ZIP+4 (e.g. 90210-1234)
    """
    zip_str = (zip_str or "").strip()
    return bool(re.match(r"^\d{5}(-\d{4})?$", zip_str))


# 50 states (full names only)
US_STATE_NAMES = [
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado", "Connecticut",
    "Delaware", "Florida", "Georgia", "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa",
    "Kansas", "Kentucky", "Louisiana", "Maine", "Maryland", "Massachusetts", "Michigan",
    "Minnesota", "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada",
    "New Hampshire", "New Jersey", "New Mexico", "New York", "North Carolina",
    "North Dakota", "Ohio", "Oklahoma", "Oregon", "Pennsylvania", "Rhode Island",
    "South Carolina", "South Dakota", "Tennessee", "Texas", "Utah", "Vermont",
    "Virginia", "Washington", "West Virginia", "Wisconsin", "Wyoming",
]

# normalized -> canonicall
_US_STATE_NORM_TO_CANON = {s.lower(): s for s in US_STATE_NAMES}


def _norm_spaces(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def normalize_us_state_full_name(state_str: str) -> tuple[bool, str | None]:
    """
    Full-name only. Returns (ok, canonical_full_name).
    Accepts case-insensitive input and extra spaces.
    Examples:
      "texas" -> (True, "Texas")
      " new   york " -> (True, "New York")
      "TX" -> (False, None)
    """
    s = _norm_spaces(state_str)
    if not s:
        return (False, None)

    canon = _US_STATE_NORM_TO_CANON.get(s)
    if canon:
        return (True, canon)

    return (False, None)


def suggest_us_states_full_name(state_str: str, n: int = 3) -> list[str]:
    """
    Returns up to n close matches of full state names.
    """
    s = _norm_spaces(state_str)
    if not s:
        return []

    candidates = list(_US_STATE_NORM_TO_CANON.keys())
    close = difflib.get_close_matches(s, candidates, n=n, cutoff=0.55)
    return [_US_STATE_NORM_TO_CANON[c] for c in close]


def is_valid_email(email: str) -> bool:
    email = (email or "").strip()
    # simple + safe (good enough for checkout)
    return bool(re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$", email))



# ==========================================
# GLOBAL COUNTRIES VALIDATOR
# ==========================================

GLOBAL_COUNTRY_NAMES = [
    "Afghanistan", "Albania", "Algeria", "Andorra", "Angola", "Antigua and Barbuda", "Argentina", "Armenia", "Australia", 
    "Austria", "Azerbaijan", "Bahamas", "Bahrain", "Bangladesh", "Barbados", "Belarus", "Belgium", "Belize", "Benin", 
    "Bhutan", "Bolivia", "Bosnia and Herzegovina", "Botswana", "Brazil", "Brunei", "Bulgaria", "Burkina Faso", "Burundi", 
    "Cabo Verde", "Cambodia", "Cameroon", "Canada", "Central African Republic", "Chad", "Chile", "China", "Colombia", 
    "Comoros", "Congo", "Costa Rica", "Croatia", "Cuba", "Cyprus", "Czech Republic", "Denmark", "Djibouti", "Dominica", 
    "Dominican Republic", "Ecuador", "Egypt", "El Salvador", "Equatorial Guinea", "Eritrea", "Estonia", "Eswatini", 
    "Ethiopia", "Fiji", "Finland", "France", "Gabon", "Gambia", "Georgia", "Germany", "Ghana", "Greece", "Grenada", 
    "Guatemala", "Guinea", "Guinea-Bissau", "Guyana", "Haiti", "Honduras", "Hungary", "Iceland", "India", "Indonesia", 
    "Iran", "Iraq", "Ireland", "Israel", "Italy", "Jamaica", "Japan", "Jordan", "Kazakhstan", "Kenya", "Kiribati", 
    "Kuwait", "Kyrgyzstan", "Laos", "Latvia", "Lebanon", "Lesotho", "Liberia", "Libya", "Liechtenstein", "Lithuania", 
    "Luxembourg", "Madagascar", "Malawi", "Malaysia", "Maldives", "Mali", "Malta", "Marshall Islands", "Mauritania", 
    "Mauritius", "Mexico", "Micronesia", "Moldova", "Monaco", "Mongolia", "Montenegro", "Morocco", "Mozambique", 
    "Myanmar", "Namibia", "Nauru", "Nepal", "Netherlands", "New Zealand", "Nicaragua", "Niger", "Nigeria", "North Korea", 
    "North Macedonia", "Norway", "Oman", "Pakistan", "Palau", "Palestine", "Panama", "Papua New Guinea", "Paraguay", 
    "Peru", "Philippines", "Poland", "Portugal", "Qatar", "Romania", "Russia", "Rwanda", "Saint Kitts and Nevis", 
    "Saint Lucia", "Saint Vincent", "Samoa", "San Marino", "Sao Tome and Principe", "Saudi Arabia", "Senegal", 
    "Serbia", "Seychelles", "Sierra Leone", "Singapore", "Slovakia", "Slovenia", "Solomon Islands", "Somalia", 
    "South Africa", "South Korea", "South Sudan", "Spain", "Sri Lanka", "Sudan", "Suriname", "Sweden", "Switzerland", 
    "Syria", "Taiwan", "Tajikistan", "Tanzania", "Thailand", "Timor-Leste", "Togo", "Tonga", "Trinidad and Tobago", 
    "Tunisia", "Turkey", "Turkmenistan", "Tuvalu", "Uganda", "Ukraine", "United Arab Emirates", "United Kingdom", 
    "United States", "Uruguay", "Uzbekistan", "Vanuatu", "Vatican City", "Venezuela", "Vietnam", "Yemen", "Zambia", "Zimbabwe"
]

# Create a fast lookup dictionary (lowercase)
_GLOBAL_NORM_TO_CANON = {c.lower(): c for c in GLOBAL_COUNTRY_NAMES}

# Inject the smart aliases into the lookup
_GLOBAL_NORM_TO_CANON.update({
    "uk": "United Kingdom",
    "england": "United Kingdom",
    "gb": "United Kingdom",
    "us": "United States",
    "usa": "United States",
    "uae": "United Arab Emirates",
    "dubai": "United Arab Emirates",
    "sa": "South Africa",
    "rsa": "South Africa",
    "nz": "New Zealand",
    "aus": "Australia",
})

def normalize_global_country_name(country_str: str) -> tuple[bool, str | None]:
    """
    Checks if the typed country exists in the 195 list or alias map.
    Uses difflib to autocorrect minor typos (like Brazill -> Brazil).
    """
    s = _norm_spaces(country_str)
    if not s:
        return (False, None)

    # 1. Exact match or alias (e.g., 'uk' -> 'United Kingdom')
    if s in _GLOBAL_NORM_TO_CANON:
        return (True, _GLOBAL_NORM_TO_CANON[s])

    # 2. Fuzzy match for typos (e.g., 'Brazill' -> 'Brazil')
    candidates = list(_GLOBAL_NORM_TO_CANON.keys())
    close = difflib.get_close_matches(s, candidates, n=1, cutoff=0.7)
    
    if close:
        matched_canon = _GLOBAL_NORM_TO_CANON[close[0]]
        return (True, matched_canon)

    # 3. Complete garbage (e.g., 'ik') -> Reject
    return (False, None)