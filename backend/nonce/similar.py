"""Find past questions that look like a new one: TF-IDF cosine over lightly stemmed words.

Cautious mode uses this to pick what the detector compares a new request against: the closest
past questions plus the most recent ones (what you've been up to lately).
"""

import math
import re
from collections import Counter

STOP = set(
    """a about after all also am an and any are as at be been before but by can could did do does
    for from get got had has have how i if in into is it its just last let like me my need next
    of on or our out please show so some than that the their them then there these they this to
    up us was we were what when where which who why will with would you your""".split()
)


def stem(w: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if len(w) > len(suffix) + 2 and w.endswith(suffix):
            return w[: -len(suffix)]
    return w


def terms(text: str) -> list[str]:
    return [stem(w) for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP and len(w) > 1]


def rank(query: str, past: list[str], k: int = 5) -> list[tuple[str, float]]:
    """Past questions most like `query`, best first, with cosine scores in [0, 1]."""
    docs = [Counter(terms(p)) for p in past]
    q = Counter(terms(query))
    if not q or not docs:
        return []
    df = Counter(t for d in docs for t in d)
    n = len(docs)

    def weights(tf: Counter) -> dict[str, float]:
        return {t: (1 + math.log(c)) * math.log(1 + n / (1 + df[t])) for t, c in tf.items()}

    def cosine(a: dict[str, float], b: dict[str, float]) -> float:
        dot = sum(v * b.get(t, 0.0) for t, v in a.items())
        na, nb = math.sqrt(sum(v * v for v in a.values())), math.sqrt(sum(v * v for v in b.values()))
        return dot / (na * nb) if na and nb else 0.0

    qw = weights(q)
    scored = [(past[i], cosine(qw, weights(d))) for i, d in enumerate(docs)]
    return sorted((s for s in scored if s[1] > 0), key=lambda s: s[1], reverse=True)[:k]


def compare_set(query: str, past_recent_first: list[str], *, closest: int = 5, recent: int = 5) -> tuple[list[str], tuple[str, float] | None]:
    """What the detector should compare against (closest + most recent, no duplicates), and the single best match."""
    unique = list(dict.fromkeys(past_recent_first))
    best = rank(query, unique, closest)
    picked = list(dict.fromkeys([p for p, _ in best] + unique[:recent]))
    return picked, (best[0] if best else None)
