import re
import datetime


def is_valid_dob(dob_str: str) -> bool:
    """
    Validates DOB format: YYYY/MM/DD and checks if it's a real date.
    Example valid: 1995/12/31
    """
    if not re.match(r"^\d{4}/\d{2}/\d{2}$", dob_str):
        return False

    year_str, month_str, day_str = dob_str.split("/")
    year = int(year_str)
    month = int(month_str)
    day = int(day_str)

    try:
        datetime.date(year, month, day)
    except ValueError:
        return False

    return True


def is_valid_name(name: str) -> bool:
    """
    Simple name validation:
    - strip spaces
    - at least 2 characters
    - no digits
    """
    name = name.strip()
    if len(name) < 2:
        return False

    if any(ch.isdigit() for ch in name):
        return False

    return True
