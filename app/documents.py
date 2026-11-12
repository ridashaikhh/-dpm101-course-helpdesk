"""Course document loading and pre-processing.

All quirks in the supplied documents are handled here, in code. The .txt files
are only ever read, never modified.

* Superseded documents: a document that says it supersedes/replaces another
  file by name (and is newer) marks that file as superseded; superseded files
  are excluded from the knowledge sent to the model.
* Untrusted content: sections that are unmoderated student forum exports are
  cut off and never reach the model. They are scanned for prompt-injection
  patterns only so we can report/log them.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("helpdesk.documents")

PROMPT_VERSION = "v1"  # bump when prompts.py changes so cached answers are invalidated

HEADER_RE = re.compile(r"^(COURSE|DOCUMENT|LAST UPDATED|STATUS):\s*(.*)$")
UNTRUSTED_HEADER_RE = re.compile(
    r"^\s*(?:\d+[.)]\s*)?[A-Z][^\n]*\b(UNMODERATED|STUDENT DISCUSSION|FORUM COMMENTS|RAW EXPORT)\b",
)
SUPERSEDES_RE = re.compile(r"supersedes\s+[\"“']?([\w.\-]+\.txt)", re.IGNORECASE)
INJECTION_RE = re.compile(
    r"(ignore|disregard|forget)\s+(all\s+|any\s+|the\s+|previous\s+|above\s+|section\s+\d+)"
    r"|for\s+ai\s+assistants|system\s+(update|prompt|instruction)|new\s+instructions"
    r"|you\s+are\s+now|override\s+(the\s+)?(policy|rules|instructions)",
    re.IGNORECASE,
)


@dataclass
class ExcludedSection:
    reason: str
    text: str
    injection_attempts: int


@dataclass
class Document:
    filename: str
    title: str
    last_updated: str
    status_line: str
    official_text: str                       # text that is safe to use as knowledge
    excluded: list[ExcludedSection] = field(default_factory=list)
    superseded_by: str | None = None

    @property
    def active(self) -> bool:
        return self.superseded_by is None

    @property
    def last_updated_date(self) -> datetime | None:
        try:
            return datetime.strptime(self.last_updated, "%d %B %Y")
        except ValueError:
            return None


@dataclass
class DocumentSet:
    documents: list[Document]
    version: str                             # hash of active content + prompt version

    @property
    def active(self) -> list[Document]:
        return [d for d in self.documents if d.active]

    @property
    def active_filenames(self) -> set[str]:
        return {d.filename for d in self.active}

    def title_for(self, filename: str) -> str:
        for d in self.documents:
            if d.filename == filename:
                return d.title
        return filename

    def knowledge_block(self) -> str:
        parts = []
        for d in self.active:
            status = d.status_line or "Official Course Document"
            parts.append(
                f'<document name="{d.filename}" last_updated="{d.last_updated}" status="{status}">\n'
                f"{d.official_text.strip()}\n</document>"
            )
        return "\n\n".join(parts)

    def summary(self) -> list[dict]:
        out = []
        for d in self.documents:
            out.append(
                {
                    "file": d.filename,
                    "title": d.title,
                    "last_updated": d.last_updated,
                    "used_as_knowledge": d.active,
                    "superseded_by": d.superseded_by,
                    "excluded_untrusted_sections": len(d.excluded),
                    "injection_attempts_detected": sum(e.injection_attempts for e in d.excluded),
                }
            )
        return out


def _split_untrusted(text: str) -> tuple[str, list[ExcludedSection]]:
    """Cut everything from the first untrusted-section header onwards."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if UNTRUSTED_HEADER_RE.match(line):
            official = "\n".join(lines[:i]).rstrip() + "\n"
            rest = "\n".join(lines[i:])
            attempts = len(INJECTION_RE.findall(rest))
            if attempts:
                logger.warning("Prompt-injection pattern(s) found in untrusted section; excluded.")
            return official, [ExcludedSection("unmoderated student content", rest, attempts)]
    return text, []


def parse_document(path: Path) -> Document:
    raw = path.read_text(encoding="utf-8")
    header: dict[str, str] = {}
    for line in raw.splitlines()[:8]:
        m = HEADER_RE.match(line.strip())
        if m:
            header[m.group(1)] = m.group(2).strip()
    official, excluded = _split_untrusted(raw)
    return Document(
        filename=path.name,
        title=header.get("DOCUMENT", path.stem),
        last_updated=header.get("LAST UPDATED", ""),
        status_line=header.get("STATUS", ""),
        official_text=official,
        excluded=excluded,
    )


def _resolve_supersession(docs: list[Document]) -> None:
    by_name = {d.filename: d for d in docs}
    for d in docs:
        for target_name in SUPERSEDES_RE.findall(d.official_text):
            target = by_name.get(target_name)
            if not target or target is d:
                continue
            # Only trust the claim when the claimant is actually newer.
            d_date, t_date = d.last_updated_date, target.last_updated_date
            if d_date and t_date and d_date > t_date:
                target.superseded_by = d.filename


def load_documents(docs_dir: str | Path) -> DocumentSet:
    paths = sorted(Path(docs_dir).glob("*.txt"))
    if not paths:
        raise RuntimeError(f"No course documents found in {docs_dir}")
    docs = [parse_document(p) for p in paths]
    _resolve_supersession(docs)
    digest = hashlib.sha256(PROMPT_VERSION.encode())
    for d in docs:
        if d.active:
            digest.update(d.filename.encode())
            digest.update(d.official_text.encode())
    return DocumentSet(documents=docs, version=digest.hexdigest()[:16])
