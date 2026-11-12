import hashlib
from pathlib import Path

from app.documents import load_documents
from conftest import DOCS_DIR


def _hashes():
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(DOCS_DIR).glob("*.txt")}


def test_latest_policy_supersedes_older(docs):
    by = {d.filename: d for d in docs.documents}
    assert by["02_grading_policy_v1.txt"].superseded_by == "03_grading_policy_v2.txt"
    assert by["03_grading_policy_v2.txt"].active
    assert "02_grading_policy_v1.txt" not in docs.active_filenames


def test_forum_section_excluded_and_injection_flagged(docs):
    d = {x.filename: x for x in docs.documents}["04_exam_rules_and_faq.txt"]
    assert "OFFICIAL PROCTORED FINAL EXAM RULES" in d.official_text
    assert "TECHNICAL REQUIREMENTS" in d.official_text
    assert "Learner_819" not in d.official_text and "OPEN-BOOK" not in d.official_text
    assert len(d.excluded) == 1 and d.excluded[0].injection_attempts >= 1


def test_knowledge_block_has_no_untrusted_or_superseded_text(docs):
    k = docs.knowledge_block()
    assert "30 December" not in k and "Learner_" not in k
    assert '<document name="02_grading_policy_v1.txt"' not in k
    assert "JANUARY 2026 COHORT" not in k and "up to 2 late submissions" not in k
    assert "15 November 2026" in k and "at least 60%" in k


def test_original_files_not_modified():
    before = _hashes()
    load_documents(DOCS_DIR)
    assert _hashes() == before
