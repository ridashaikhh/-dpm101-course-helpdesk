"""Question normalisation, FAQ-intent matching and follow-up detection.

Caching is deliberately conservative:

1. Exact layer  - same text after light normalisation (case, punctuation,
   whitespace, thousands separators, "dpm-101" spelling).
2. FAQ layer    - a question matches a known FAQ intent only if
   (a) it contains the intent's required concepts AND
   (b) EVERY remaining content word is inside that intent's vocabulary.
   Any number, date, unit or condition word that the intent doesn't expect
   ("1 day late", "50%", "if I drop in week 2") breaks the match, so questions
   with materially different details are never merged.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


def normalize(question: str) -> str:
    s = unicodedata.normalize("NFKC", question).casefold()
    s = s.replace("\u2019", "'").replace("\u2018", "'")
    s = re.sub(r"(?<=\d),(?=\d)", "", s)                  # 1,500 -> 1500
    s = re.sub(r"[^\w\s\-.%]", " ", s)                    # drop punctuation (keep - . %)
    s = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", s)             # periods only inside numbers
    s = re.sub(r"(?<!\w)-|-(?!\w)", " ", s)               # stray hyphens
    s = re.sub(r"\bdpm[\s\-]*101\b", "dpm101", s)
    return " ".join(s.split())


STOPWORDS = frozenset(
    """a an the is are am was were be been do does did i me my we our you your to of in on at for
    and or what whats how much many can could should would will shall get got tell please pls
    know about there any with by it its that this from as s t m ll d re ve have has had need needs
    needed required require must am""".split()
)

# Words that signal "this refers to something said earlier".
ANAPHORA = frozenset(
    "it its that this those these them they he she there then same also too another above "
    "previous earlier former latter one".split()
)
FOLLOWUP_PREFIXES = ("and ", "what about", "how about", "why ", "so ", "but ", "ok ", "okay ")


def content_tokens(norm: str) -> list[str]:
    return [t for t in norm.split() if t not in STOPWORDS]


def is_context_dependent(norm: str, has_history: bool) -> bool:
    """A follow-up may only make sense with the previous turns -> never cache it."""
    if not has_history:
        return False
    words = norm.split()
    if len(words) < 4:
        return True
    if norm.startswith(FOLLOWUP_PREFIXES):
        return True
    return bool(ANAPHORA.intersection(words))


@dataclass(frozen=True)
class FaqIntent:
    id: str
    canonical: str                       # the question actually sent to Gemini for this intent
    required: tuple[frozenset, ...]      # each group must be hit by >=1 token
    vocab: frozenset                     # every content token must be inside vocab


def _fs(words: str) -> frozenset:
    return frozenset(words.split())


_COMMON = "course dpm101 verified certificate"

FAQ_INTENTS: tuple[FaqIntent, ...] = (
    FaqIntent(
        "pass_score",
        "What is the minimum score needed to pass DPM-101 and earn the Verified Certificate?",
        (_fs("score scores marks percentage percent threshold cutoff cut-off"),
         _fs("pass passing passed certificate qualify")),
        _fs(f"{_COMMON} score scores marks percentage percent threshold cutoff cut-off pass passing "
            "passed minimum least overall total weighted earn receive qualify"),
    ),
    FaqIntent(
        "capstone_deadline",
        "When is the Capstone Product Case due?",
        (_fs("capstone"), _fs("due deadline date submission submit last")),
        _fs("capstone product case project due deadline date submission submit when last"),
    ),
    FaqIntent(
        "exam_format",
        "Is the final exam open-book or closed-book, and when is it scheduled?",
        (_fs("exam test"),
         _fs("open-book closed-book open closed book openbook closedbook")),
        _fs("exam final proctored test open-book closed-book open closed book openbook closedbook "
            "date schedule scheduled when time"),
    ),
    FaqIntent(
        "exam_date",
        "When is the proctored final exam scheduled (date, time slots and duration)?",
        (_fs("exam test"), _fs("date scheduled schedule when time slot slots")),
        _fs("exam final proctored test date scheduled schedule when time slot slots"),
    ),
    FaqIntent(
        "exam_device",
        "Can I take the proctored final exam on a mobile phone or tablet (such as an iPad)?",
        (_fs("exam test"),
         _fs("ipad tablet tablets phone phones mobile smartphone iphone android device devices "
             "laptop desktop computer")),
        _fs("exam final proctored test take taking attempt use ipad tablet tablets phone phones mobile "
            "smartphone iphone android device devices laptop desktop computer"),
    ),
    FaqIntent(
        "verified_fee",
        "How much does the Verified Certificate track cost?",
        (_fs("cost costs fee fees price pay paid charge rs rupees inr"),
         _fs("verified certificate certification track")),
        _fs(f"{_COMMON} track cost costs fee fees price pay paid charge rs rupees inr certification"),
    ),
    FaqIntent(
        "quiz_count",
        "How many weekly quizzes are there, and what happens if I miss one?",
        (_fs("quiz quizzes"),),
        _fs(f"{_COMMON} quiz quizzes weekly total number count miss missed missing if happens happen one"),
    ),
    FaqIntent(
        "late_policy",
        "Are late submissions allowed for the capstone or the weekly quizzes?",
        (_fs("late delay delayed"),),
        _fs("late delay delayed submission submissions submit submitting allowed allow accept accepted "
            "permitted penalty policy capstone quiz quizzes assignment assignments if happens happen "
            f"{_COMMON}"),
    ),
)


def match_faq(norm: str) -> FaqIntent | None:
    tokens = set(content_tokens(norm))
    if not tokens:
        return None
    for intent in FAQ_INTENTS:
        if tokens <= intent.vocab and all(tokens & group for group in intent.required):
            return intent
    return None
