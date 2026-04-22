from __future__ import annotations

from ..models import Item

# Unicode ranges that strongly indicate non-Latin-script text.
_NON_LATIN_RANGES: tuple[tuple[int, int], ...] = (
    (0x0400, 0x052F),  # Cyrillic + Cyrillic Supplement
    (0x0590, 0x05FF),  # Hebrew
    (0x0600, 0x06FF),  # Arabic
    (0x0700, 0x074F),  # Syriac
    (0x0900, 0x097F),  # Devanagari
    (0x0E00, 0x0E7F),  # Thai
    (0x3040, 0x30FF),  # Hiragana + Katakana
    (0x3400, 0x4DBF),  # CJK Extension A
    (0x4E00, 0x9FFF),  # CJK Unified Ideographs
    (0xAC00, 0xD7AF),  # Hangul Syllables
)

# Very common English function words. Presence of these is a strong English signal.
_ENGLISH_STOPWORDS = frozenset(
    [
        "the", "a", "an", "and", "to", "of", "in", "on", "for", "with", "at",
        "by", "from", "into", "about", "as", "is", "are", "was", "were", "be",
        "been", "being", "has", "have", "had", "do", "does", "did", "will",
        "would", "can", "could", "should", "may", "might", "must", "not",
        "but", "or", "if", "then", "than", "this", "that", "these", "those",
        "it", "its", "i", "you", "your", "we", "our", "they", "their", "he",
        "she", "his", "her", "them", "just", "more", "most", "new", "now",
        "how", "what", "why", "when", "where", "who", "which",
    ]
)

# Common function words in Romance + German languages — presence counts
# against "this is English". Any overlap with English (e.g. "a", "no") is
# intentionally left out so we don't penalize English.
_NON_ENGLISH_STOPWORDS = frozenset(
    [
        # Portuguese
        "que", "não", "uma", "para", "como", "mais", "muito", "ser", "foi",
        "você", "são", "está", "também", "isso", "pelo", "pela", "dos", "das",
        "sem", "porque", "entre", "sobre", "ainda", "quando", "pois",
        # Spanish (many overlap with PT)
        "qué", "sin", "sí", "pero", "porqué", "también", "cómo", "están",
        "estoy", "soy", "eres", "somos", "nosotros", "vosotros", "ellos",
        "esto", "eso", "aquí", "allí", "ahora", "siempre", "nunca",
        # French
        "avec", "pour", "dans", "sur", "sous", "vers", "entre", "cette",
        "ces", "leur", "leurs", "vous", "nous", "je", "tu", "il", "elle",
        "ils", "elles", "mais", "ou", "donc", "car", "ni", "très", "bien",
        "trop", "pas", "plus", "moins", "être", "était", "comme", "quand",
        "parce", "après", "avant", "toujours", "jamais",
        # German
        "und", "der", "die", "das", "den", "dem", "des", "ein", "eine",
        "einen", "einem", "einer", "eines", "ist", "sind", "war", "waren",
        "wird", "werden", "wurde", "wurden", "nicht", "kein", "keine",
        "auch", "aber", "oder", "wenn", "doch", "nur", "noch", "schon",
        "mit", "bei", "nach", "vor", "über", "unter", "zwischen", "durch",
        "ich", "du", "er", "sie", "es", "wir", "ihr", "mich", "dich", "sich",
        "mein", "dein", "sein", "ihr", "unser", "euer",
        # Italian
        "che", "gli", "nel", "nella", "nei", "nelle", "sul", "sulla", "dei",
        "delle", "degli", "dalla", "dallo", "sono", "era", "stato", "anche",
        "più", "molto", "questo", "quello", "quella", "questa",
    ]
)


def looks_english(text: str) -> bool:
    """Return True if `text` is probably English.

    Strategy:
      1. Reject if any chars fall inside non-Latin script ranges.
      2. Tokenize and count matches against English vs. non-English function
         words. If non-English clearly wins, reject. Otherwise keep — we
         prefer false positives (keeping a non-English item) over false
         negatives (dropping a short English item with no stopwords).
    """
    if not text:
        return True

    sample = text[:800]

    for ch in sample:
        code = ord(ch)
        for start, end in _NON_LATIN_RANGES:
            if start <= code <= end:
                return False

    words = [
        w.strip(".,!?;:()[]{}\"'`—–-…*_#/\\")
        for w in sample.lower().split()
    ]

    en_hits = sum(1 for w in words if w in _ENGLISH_STOPWORDS)
    non_hits = sum(1 for w in words if w in _NON_ENGLISH_STOPWORDS)

    if non_hits >= 2 and non_hits > en_hits:
        return False
    return True


def filter_english(items: list[Item]) -> list[Item]:
    return [i for i in items if looks_english(f"{i.title}\n{i.summary}")]
