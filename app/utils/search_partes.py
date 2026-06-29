import re
from typing import List, Tuple

PREPOSICIONES = frozenset([
    "el", "la", "las", "lo", "los", "a", "ante", "bajo", "cabe", "con", "contra",
    "de", "del", "desde", "durante", "en", "entre", "hacia", "hasta", "mediante",
    "mi", "para", "por", "según", "sin", "so", "sobre", "tras", "versus", "vía"
])

SPELLING_PAIRS: List[Tuple[str, str]] = [
    ("v", "b"), ("b", "v"), ("mb", "nv"), ("nv", "mb"), ("s", "sc"), ("c", "s"),
    ("c", "k"), ("k", "c"), ("mp", "np"), ("np", "mp"), ("z", "s"), ("z", "c"),
    ("s", "z"), ("ll", "y"), ("y", "ll"), ("r", "rr"), ("rr", "r"), ("g", "j"),
    ("j", "g"), ("k", "qu"), ("qu", "k"), ("h", "j"),
]

TILDE_MAP = {
    "a": "[aàâáä]+",
    "e": "[eèêéë]+",
    "i": "[iìîíï]+",
    "o": "[oòôóö]+",
    "u": "[uùûúü]+",
    "n": "[nñ]+",
    "ñ": "[nñ]+",
}


def _clean(s: str) -> str:
    s = s.strip()
    s = re.sub(r"\s\s+", " ", s)
    return s


def _stem_plural(token: str) -> str:
    m = re.match(r"([a-záéíóúñ]+?)(s\b|es\b|as\b|os\b)\b", token, re.IGNORECASE)
    if m:
        return m.group(1).lower()
    return token.lower()


def _add_tilde_rule(criteria: str) -> str:
    result = []
    for c in criteria:
        result.append(TILDE_MAP.get(c.lower(), re.escape(c)))
    return "".join(result)


def _add_criteria_alternative(
    search_value: str, replace_value: str, criteria: str, lst: List[str]
) -> None:
    replaced = criteria.replace(search_value, replace_value)
    if replaced and replaced != criteria:
        pattern = _add_tilde_rule(replaced)
        if pattern and pattern not in lst:
            lst.append(pattern)


def _spelling_variant_words(stemmed: str) -> List[str]:
    """Return stemmed word plus all single-substitution spelling variants (no regex)."""
    out = {stemmed}
    for search_val, replace_val in SPELLING_PAIRS:
        for w in list(out):
            if search_val in w:
                out.add(w.replace(search_val, replace_val, 1))
    return list(out)


def prepare_fulltext_variant_groups(criterio: str) -> List[List[str]]:
    """
    For FULLTEXT with spelling variants: clean, tokenize, drop stopwords, stem,
    then for each token produce a list of variant words (original + Spanish spelling alternatives).
    Returns one list of variant words per token, e.g. [["filtro", "filtbo"], ["aceite", "aseite"]].
    Accent-insensitivity is left to DB collation.
    """
    cleaned = _clean(criterio)
    if not cleaned:
        return []
    query_lower = cleaned.lower()
    tokens = query_lower.split()
    groups: List[List[str]] = []
    for token in tokens:
        if token in PREPOSICIONES:
            continue
        stemmed = _stem_plural(token)
        if not stemmed:
            continue
        variants = _spelling_variant_words(stemmed)
        if variants:
            groups.append(variants)
    if not groups:
        for token in tokens:
            if token in PREPOSICIONES:
                continue
            stemmed = _stem_plural(token)
            if stemmed:
                groups.append(_spelling_variant_words(stemmed))
    if not groups:
        groups.append(_spelling_variant_words(query_lower))
    return groups


def build_search_regex(criterio: str) -> str:
    cleaned = _clean(criterio)
    if not cleaned:
        return ""
    query_lower = cleaned.lower()
    tokens = query_lower.split()
    lst_criterias: List[str] = []
    for token in tokens:
        if token in PREPOSICIONES:
            continue
        stemmed = _stem_plural(token)
        if not stemmed:
            continue
        lst_criterias.append(_add_tilde_rule(stemmed))
        for search_val, replace_val in SPELLING_PAIRS:
            if search_val in stemmed:
                _add_criteria_alternative(search_val, replace_val, stemmed, lst_criterias)
    if not lst_criterias:
        for token in tokens:
            if token in PREPOSICIONES:
                continue
            stemmed = _stem_plural(token)
            if stemmed:
                lst_criterias.append(_add_tilde_rule(stemmed))
    if not lst_criterias:
        lst_criterias.append(_add_tilde_rule(query_lower))
    seen = set()
    unique = []
    for p in lst_criterias:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return "|".join(unique)
