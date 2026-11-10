"""Typo-tolerant matching for vehicle names (make / model).

Pure functions, no I/O: the repositories feed candidates in, the service ranks them. Designed for
what people actually mistype on a phone: transposed letters ("kai"), dropped/doubled letters
("nisan", "sentraa"), Spanish phonetic swaps ("vw golf" -> "bolf", "jeta"), accents and spacing
("np 300"), and partially typed words with a typo ("sentr").
"""

import re
import unicodedata
from typing import Iterable, List, NamedTuple, Optional, Sequence, Tuple

MIN_SIMILARITY = 0.62       # per query token
MIN_CANDIDATE_SCORE = 0.66  # average over the query tokens


def fold(text: str) -> str:
    """Lowercase, strip accents and keep only letters and digits ('Citroën C-3' -> 'citroenc3')."""
    decomposed = unicodedata.normalize("NFD", (text or "").lower())
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]", "", stripped)


def tokenize(text: str) -> List[str]:
    """Folded word tokens: 'Nissan X-Trail' -> ['nissan', 'x', 'trail']."""
    decomposed = unicodedata.normalize("NFD", (text or "").lower())
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return [t for t in re.split(r"[^a-z0-9]+", stripped) if t]


def phonetic_key(token: str) -> str:
    """Rough Spanish-sound key so that 'bolkswagen' ~ 'volkswagen' and 'jeta' ~ 'yeta'."""
    s = fold(token)
    s = re.sub(r"(ph)", "f", s)
    s = re.sub(r"qu", "k", s)
    s = re.sub(r"c(?=[eiy])", "s", s)
    s = s.replace("c", "k")
    s = s.replace("v", "b").replace("w", "b")
    s = s.replace("z", "s")
    s = s.replace("ll", "y")
    s = s.replace("h", "")
    s = re.sub(r"(.)\1+", r"\1", s)  # collapse doubled letters
    return s


def damerau_levenshtein(a: str, b: str, max_distance: Optional[int] = None) -> int:
    """Edit distance counting a transposition of neighbours as one edit.

    Stops early and returns max_distance + 1 once the distance cannot be within max_distance.
    """
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if max_distance is not None and abs(la - lb) > max_distance:
        return max_distance + 1
    prev_prev: List[int] = []
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        row_min = cur[0]
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev_prev[j - 2] + 1)
            row_min = min(row_min, cur[j])
        if max_distance is not None and row_min > max_distance:
            return max_distance + 1
        prev_prev, prev = prev, cur
    return prev[lb]


def _allowed_edits(length: int) -> int:
    if length <= 2:
        return 0
    if length <= 5:
        return 1
    return 2


def token_similarity(query: str, candidate: str) -> float:
    """0..1 similarity between a (possibly mistyped or partial) query token and a catalog token."""
    if not query or not candidate:
        return 0.0
    if query == candidate:
        return 1.0

    # Partially typed word: "sent" -> "sentra". Longer prefixes are more convincing.
    if len(query) >= 2 and candidate.startswith(query):
        return 0.9 + 0.1 * min(1.0, len(query) / len(candidate))

    best = 0.0
    allowed = _allowed_edits(len(query))

    if allowed:
        dist = damerau_levenshtein(query, candidate, allowed)
        if dist <= allowed:
            best = max(best, 1.0 - dist / max(len(query), len(candidate)))

        # Partial word that also has a typo: "sentr" vs "sentra" handled above, "setn" vs "sentra".
        if len(query) >= 4 and len(candidate) > len(query):
            head = candidate[: len(query)]
            if damerau_levenshtein(query, head, 1) <= 1:
                best = max(best, 0.8)

    qk, ck = phonetic_key(query), phonetic_key(candidate)
    if qk and qk == ck:
        best = max(best, 0.92)
    elif len(qk) >= 5 and len(ck) >= 5:
        # One sound-key edit is only convincing on longer words; on short ones it matches noise.
        dist = damerau_levenshtein(qk, ck, 1)
        if dist <= 1:
            best = max(best, 0.78)

    return best


class Match(NamedTuple):
    index: int
    score: float


def score_candidate(query_tokens: Sequence[str], candidate_tokens: Sequence[str]) -> float:
    """Average best token similarity; 0 when any query token has no acceptable counterpart."""
    if not query_tokens or not candidate_tokens:
        return 0.0
    total = 0.0
    for q in query_tokens:
        best = max((token_similarity(q, c) for c in candidate_tokens), default=0.0)
        if best < MIN_SIMILARITY:
            return 0.0
        total += best
    return total / len(query_tokens)


def squashed_similarity(query: str, candidate_text: str) -> float:
    """Whole-phrase comparison that ignores spaces: 'np 300' ~ 'np300', 'xtrail' ~ 'X-Trail'."""
    q, c = fold(query), fold(candidate_text)
    if not q or not c:
        return 0.0
    if q == c:
        return 1.0
    if c.startswith(q):
        return 0.9
    allowed = _allowed_edits(len(q))
    if allowed:
        dist = damerau_levenshtein(q, c, allowed)
        if dist <= allowed:
            return 1.0 - dist / max(len(q), len(c))
    return 0.0


def rank_candidates(
    query: str,
    candidates: Iterable[Tuple[str, str]],
    limit: int = 20,
) -> List[Tuple[Tuple[str, str], float]]:
    """Rank (make, model) pairs by closeness to `query`; best first.

    Make-only queries ("nisan") score every model of that make equally, so ties are broken by
    name to keep the order stable.
    """
    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    ranked: List[Tuple[Tuple[str, str], float]] = []
    for make, model in candidates:
        tokens = tokenize(f"{make} {model}")
        score = score_candidate(query_tokens, tokens)
        score = max(score, squashed_similarity(query, f"{make} {model}"), squashed_similarity(query, model))
        if score >= MIN_CANDIDATE_SCORE:
            ranked.append(((make, model), score))

    ranked.sort(key=lambda item: (-item[1], item[0][0].lower(), item[0][1].lower()))
    return ranked[:limit]


def suggestion_label(query: str, make: str, model: str) -> str:
    """What to show as "did you mean": just the make when the query only matches the make."""
    query_tokens = tokenize(query)
    make_score = score_candidate(query_tokens, tokenize(make))
    full_score = score_candidate(query_tokens, tokenize(f"{make} {model}"))
    if make_score > 0 and make_score >= full_score:
        return make
    return f"{make} {model}".strip()
