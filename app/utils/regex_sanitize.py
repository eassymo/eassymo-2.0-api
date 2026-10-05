"""Escape user input for safe use in regex patterns."""

import re

MAX_SEARCH_LENGTH = 100


def sanitize_search_term(search_argument: str) -> str:
    term = (search_argument or "").strip()
    if len(term) > MAX_SEARCH_LENGTH:
        term = term[:MAX_SEARCH_LENGTH]
    return re.escape(term)
