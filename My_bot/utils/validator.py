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
