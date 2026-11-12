import pytest

from app.normalizer import is_context_dependent, match_faq, normalize


def test_exact_normalization():
    a = normalize("What is the minimum score needed to pass the course?")
    assert a == normalize("  what IS the minimum score needed to pass the course ")
    assert normalize("Pay Rs. 1,500 fee?") == "pay rs 1500 fee"
    assert normalize("DPM 101") == normalize("dpm-101") == "dpm101"


@pytest.mark.parametrize("q,intent", [
    ("What is the minimum score needed to pass the course and get a Verified Certificate?", "pass_score"),
    ("how much do i need to score to pass dpm-101?", "pass_score"),
    ("When is the Capstone Product Case due?", "capstone_deadline"),
    ("Is the final exam open-book or closed-book, and when is it scheduled?", "exam_format"),
    ("Can I take the proctored final exam on my iPad or mobile phone?", "exam_device"),
    ("How much does the Verified Certificate track cost?", "verified_fee"),
    ("How many weekly quizzes are there, and what if I miss one?", "quiz_count"),
    ("Are late submissions allowed?", "late_policy"),
])
def test_known_faqs_match(q, intent):
    assert match_faq(normalize(q)).id == intent


@pytest.mark.parametrize("q", [
    "What happens if I submit my Capstone project 1 day late?",   # specific duration
    "Is 50% enough to pass?",                                      # different number
    "what score do I need to pass the final exam separately?",     # different condition
    "What is the minimum score for Pass with Distinction?",
    "If I pay the Rs. 1,500 fee and drop the course in Week 2, how do I get a refund?",
    "What if I miss two quizzes?",
    "Does this course teach SQL database indexing and Kubernetes deployment?",
    "Who won the cricket match last night?",
    "Can I take the exam on my laptop with Firefox?",
])
def test_materially_different_questions_never_merge(q):
    assert match_faq(normalize(q)) is None


def test_context_dependence():
    assert not is_context_dependent("what is the minimum score to pass", False)
    assert is_context_dependent(normalize("What about the capstone?"), True)
    assert is_context_dependent(normalize("And when is that due?"), True)
    assert not is_context_dependent(normalize("When is the Capstone Product Case due?"), True)
