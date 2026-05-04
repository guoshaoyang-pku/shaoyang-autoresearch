"""Literature review helpers: verify .bib against Semantic Scholar + must-cite ideas.

Integration invokes ``LitReview.run_full()``; persistence is
``state/lit_review/<worker>/<run_id>.json`` plus Markdown summary (wiring in mgr).

See ``docs/sub_agents_contract.md`` § MODULE B.

Usage::

    from pathlib import Path
    from lib.lit_review import LitReview, StubLitReview, SemanticScholarClient

    report = LitReview().run_full(Path("refs.bib"), keywords=["transformer", "BERT"])
    path.write_text(json.dumps(report.to_dict(), indent=2))
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_pkg_root = Path(__file__).resolve().parent.parent
if __package__ is None:
    sys.path.insert(0, str(_pkg_root))

try:
    from .state import expand
except ImportError:
    from lib.state import expand

USER_AGENT = "cursor_manager/lit_review (shaoyang-autoresearch autoresearch)"
DEFAULT_TIMEOUT_SEC = 10
SS_BASE = "https://api.semanticscholar.org/graph/v1"


@dataclass
class CitationCheckEntry:
    bib_key: str
    title: str | None
    found: bool
    semantic_scholar_id: str | None
    matched_title: str | None
    year: int | None
    issue: str | None  # not_found | year_mismatch | title_mismatch | api_error | malformed_bib | ...

    def to_dict(self) -> dict[str, Any]:
        return {
            "bib_key": self.bib_key,
            "title": self.title,
            "found": self.found,
            "semantic_scholar_id": self.semantic_scholar_id,
            "matched_title": self.matched_title,
            "year": self.year,
            "issue": self.issue,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CitationCheckEntry:
        return cls(
            bib_key=str(d.get("bib_key", "")),
            title=d.get("title"),
            found=bool(d.get("found", False)),
            semantic_scholar_id=d.get("semantic_scholar_id"),
            matched_title=d.get("matched_title"),
            year=d.get("year") if d.get("year") is not None else None,
            issue=d.get("issue"),
        )


@dataclass
class MustCiteSuggestion:
    title: str
    authors: list[str]
    year: int
    venue: str
    semantic_scholar_id: str
    citation_count: int
    relevance_reason: str
    bib_entry: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "authors": list(self.authors),
            "year": self.year,
            "venue": self.venue,
            "semantic_scholar_id": self.semantic_scholar_id,
            "citation_count": self.citation_count,
            "relevance_reason": self.relevance_reason,
            "bib_entry": self.bib_entry,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> MustCiteSuggestion:
        authors = d.get("authors") or []
        return cls(
            title=str(d.get("title", "")),
            authors=[str(a) for a in authors],
            year=int(d.get("year", 0)),
            venue=str(d.get("venue", "")),
            semantic_scholar_id=str(d.get("semantic_scholar_id", "")),
            citation_count=int(d.get("citation_count", 0)),
            relevance_reason=str(d.get("relevance_reason", "")),
            bib_entry=str(d.get("bib_entry", "")),
        )


@dataclass
class LitReviewReport:
    bib_path: str
    n_entries_total: int
    n_verified: int
    n_unverified: int
    citation_checks: list[CitationCheckEntry]
    must_cite_suggestions: list[MustCiteSuggestion]
    keywords_searched: list[str]
    generated_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "bib_path": self.bib_path,
            "n_entries_total": self.n_entries_total,
            "n_verified": self.n_verified,
            "n_unverified": self.n_unverified,
            "citation_checks": [c.to_dict() for c in self.citation_checks],
            "must_cite_suggestions": [m.to_dict() for m in self.must_cite_suggestions],
            "keywords_searched": list(self.keywords_searched),
            "generated_at": self.generated_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> LitReviewReport:
        return cls(
            bib_path=str(d.get("bib_path", "")),
            n_entries_total=int(d.get("n_entries_total", 0)),
            n_verified=int(d.get("n_verified", 0)),
            n_unverified=int(d.get("n_unverified", 0)),
            citation_checks=[
                CitationCheckEntry.from_dict(x) for x in (d.get("citation_checks") or [])
            ],
            must_cite_suggestions=[
                MustCiteSuggestion.from_dict(x) for x in (d.get("must_cite_suggestions") or [])
            ],
            keywords_searched=[str(k) for k in (d.get("keywords_searched") or [])],
            generated_at=float(d.get("generated_at", 0.0)),
        )

    def to_markdown_summary(self) -> str:
        lines = [
            "# Literature review summary",
            "",
            f"- **Bib file**: `{self.bib_path}`",
            f"- **Entries**: {self.n_entries_total} total — {self.n_verified} verified, "
            f"{self.n_unverified} not verified",
            f"- **Keywords searched**: {', '.join(self.keywords_searched) if self.keywords_searched else '(none)'}",
            f"- **Must-cite suggestions**: {len(self.must_cite_suggestions)}",
            f"- **Generated at (unix)**: {self.generated_at}",
            "",
            "## Citation checks",
        ]
        for c in self.citation_checks:
            st = "OK" if c.found else "MISS"
            extra = f" — `{c.issue}`" if c.issue else ""
            t = c.title or "(no title)"
            mid = c.semantic_scholar_id or "—"
            lines.append(f"- **{c.bib_key}** [{st}]{extra}: _{t}_ → SS `{mid}`")
        lines.extend(["", "## Must-cite suggestions"])
        for m in self.must_cite_suggestions:
            auth = ", ".join(m.authors[:3]) + (" et al." if len(m.authors) > 3 else "")
            lines.append(
                f"- **{m.title}** ({m.year}, {m.citation_count} cites) — {m.relevance_reason}; "
                f"venue: {m.venue or '—'}; id: `{m.semantic_scholar_id}`"
            )
            lines.append(f"  - Authors: {auth}")
        return "\n".join(lines) + "\n"


def _warn(msg: str) -> None:
    print(msg, file=sys.stderr)


def _norm_title(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = s.lower().strip()
    s = re.sub(r"\s+", " ", s)
    # drop common punctuation noise for loose matching
    s = re.sub(r"[^\w\s]", "", s, flags=re.UNICODE)
    return s


def _titles_match(bib_title: str, ss_title: str | None) -> bool:
    if not ss_title:
        return False
    a = _norm_title(bib_title)
    b = _norm_title(ss_title)
    if not a or not b:
        return False
    if a == b:
        return True
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) >= 10 and short in long:
        return True
    return False


def _extract_year(val: str | None) -> int | None:
    if not val:
        return None
    m = re.search(r"(\d{4})", val)
    if m:
        y = int(m.group(1))
        if 1000 <= y <= 2100:
            return y
    return None


def _strip_tex_outer(s: str) -> str:
    s = s.strip()
    if (s.startswith("{") and s.endswith("}")) or (s.startswith('"') and s.endswith('"')):
        return s[1:-1].strip()
    return s


def _extract_field(body: str, name: str) -> str | None:
    """Best-effort bib field extraction (tolerant, nested braces for one level)."""
    pat = re.compile(rf"(?im)^\s*{re.escape(name)}\s*=\s*")
    m = pat.search(body)
    if not m:
        return None
    i = m.end()
    while i < len(body) and body[i] in " \t":
        i += 1
    if i >= len(body):
        return None
    if body[i] == "{":
        depth = 0
        j = i
        while j < len(body):
            if body[j] == "{":
                depth += 1
            elif body[j] == "}":
                depth -= 1
                if depth == 0:
                    return _strip_tex_outer(body[i : j + 1])
            j += 1
        return None
    if body[i] == '"':
        end = body.find('"', i + 1)
        if end < 0:
            return None
        return body[i + 1 : end]
    # bare token until comma or newline at depth 0
    m2 = re.match(r"([^,\n]+)", body[i:])
    return _strip_tex_outer(m2.group(1).strip()) if m2 else None


@dataclass
class _ParsedBibEntry:
    bib_key: str
    entry_type: str
    title: str | None
    year: int | None
    raw_body: str
    parse_issue: str | None = None


def parse_bib_text(text: str) -> list[_ParsedBibEntry]:
    """Parse .bib text with stdlib only; skip @comment/@string/@preamble."""

    def next_at_entry(start: int) -> tuple[str, str, int, bool] | None:
        m = re.search(r"@(\w+)\s*\{", text[start:], flags=re.IGNORECASE)
        if not m:
            return None
        typ = m.group(1)
        brace_open = start + m.end() - 1
        depth = 0
        j = brace_open
        while j < len(text):
            c = text[j]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    inner = text[brace_open + 1 : j]
                    return typ, inner, j + 1, True
            j += 1
        inner = text[brace_open + 1 :]
        return typ, inner, len(text), False

    out: list[_ParsedBibEntry] = []
    pos = 0
    while pos < len(text):
        nxt = next_at_entry(pos)
        if not nxt:
            break
        typ, inner, new_pos, closed = nxt
        pos = new_pos
        tlow = typ.lower()
        if tlow in {"comment", "string", "preamble"}:
            continue

        # key = segment before first ',' at brace depth 0 within inner
        depth = 0
        split_at = -1
        for k, ch in enumerate(inner):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            elif ch == "," and depth == 0:
                split_at = k
                break
        if split_at < 0:
            key = inner.strip() or "?"
            body = ""
            issue: str | None = "malformed_bib"
            if not closed:
                issue = "malformed_bib"
        else:
            key = inner[:split_at].strip()
            body = inner[split_at + 1 :]
            issue = "malformed_bib" if not closed else None

        title = _extract_field(body, "title")
        year_s = _extract_field(body, "year")
        yr = _extract_year(year_s)

        if issue is None and not closed:
            issue = "malformed_bib"

        out.append(
            _ParsedBibEntry(
                bib_key=key,
                entry_type=typ,
                title=title,
                year=yr,
                raw_body=body,
                parse_issue=issue,
            )
        )
    return out


class SemanticScholarClient:
    """Thin wrapper around Semantic Scholar Graph API v1."""

    BASE_URL = SS_BASE

    def __init__(self, api_key: str | None = None, rate_limit_rps: float = 1.0):
        self.api_key = api_key
        self.rate_limit_rps = max(0.0, float(rate_limit_rps))
        self._last_call_ts: float = 0.0

    def _sleep_rate_limit(self) -> None:
        if self.rate_limit_rps <= 0:
            return
        gap = 1.0 / self.rate_limit_rps
        now = time.monotonic()
        wait = gap - (now - self._last_call_ts)
        if wait > 0:
            time.sleep(wait)

    def _paper_search_raw(
        self, query: str, limit: int, fields: list[str]
    ) -> tuple[list[dict] | None, bool]:
        """Return (papers, api_ok). ``papers is None`` and ``api_ok False`` => transport/API failure."""

        data = self._request_json(
            "/paper/search",
            {"query": query, "limit": str(limit), "fields": ",".join(fields)},
        )
        if data is None:
            return None, False
        arr = data.get("data")
        if not isinstance(arr, list):
            return None, False
        out: list[dict] = []
        for item in arr:
            if isinstance(item, dict):
                out.append(item)
        return out, True

    def _request_json(
        self,
        path: str,
        query: dict[str, Any] | None = None,
        *,
        max_429_retries: int = 3,
    ) -> Any | None:
        q = urllib.parse.urlencode({k: str(v) for k, v in (query or {}).items() if v is not None})
        url = f"{self.BASE_URL}{path}"
        if q:
            url = f"{url}?{q}"

        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if self.api_key:
            headers["x-api-key"] = self.api_key

        last_exc: BaseException | None = None
        for attempt in range(max_429_retries + 1):
            self._sleep_rate_limit()
            try:
                req = urllib.request.Request(url, headers=headers, method="GET")
                with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT_SEC) as resp:
                    body = resp.read().decode("utf-8", errors="replace")
                    self._last_call_ts = time.monotonic()
                    return json.loads(body)
            except urllib.error.HTTPError as e:
                self._last_call_ts = time.monotonic()
                code = getattr(e, "code", None)
                if code == 429 and attempt < max_429_retries:
                    _warn(f"Semantic Scholar 429 for {path}; sleeping 5s (attempt {attempt + 1})")
                    time.sleep(5.0)
                    continue
                if code is not None and 500 <= code < 600:
                    _warn(f"Semantic Scholar HTTP {code} for {path}: failing soft")
                    return None
                _warn(f"Semantic Scholar HTTP error {code} for {path}: {e}")
                return None
            except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, OSError) as e:
                last_exc = e
                self._last_call_ts = time.monotonic()
                _warn(f"Semantic Scholar request failed for {path}: {e}")
                return None
        if last_exc:
            _warn(f"Semantic Scholar gave up after retries: {last_exc}")
        return None

    def search_by_title(self, title: str, *, fields: list[str] | None = None) -> dict | None:
        flist = fields or ["paperId", "title", "year", "authors", "venue", "citationCount"]
        papers, ok = self._paper_search_raw(title, 5, flist)
        if not ok or not papers:
            return None
        return papers[0]

    def search_by_keyword(
        self,
        keyword: str,
        limit: int = 10,
        *,
        fields: list[str] | None = None,
    ) -> list[dict]:
        flist = fields or ["paperId", "title", "year", "authors", "venue", "citationCount"]
        lim = max(1, min(int(limit), 100))
        papers, ok = self._paper_search_raw(keyword, lim, flist)
        if not ok:
            return []
        return papers or []

    def get_paper(self, paper_id: str, *, fields: list[str] | None = None) -> dict | None:
        flist = fields or ["paperId", "title", "year", "authors", "venue", "citationCount"]
        enc = urllib.parse.quote(paper_id, safe=":/.-_+")
        data = self._request_json(f"/paper/{enc}", {"fields": ",".join(flist)})
        return data if isinstance(data, dict) else None


def _authors_to_strings(authors: Any) -> list[str]:
    if not isinstance(authors, list):
        return []
    out: list[str] = []
    for a in authors:
        if isinstance(a, dict) and a.get("name"):
            out.append(str(a["name"]))
        elif isinstance(a, str):
            out.append(a)
    return out


def _paper_year(p: dict) -> int | None:
    y = p.get("year")
    if isinstance(y, int):
        return y
    if isinstance(y, str) and y.isdigit():
        return int(y)
    return None


def _suggestion_bib_key(authors: list[str], year: int, title: str, used: set[str]) -> str:
    last = "unknown"
    if authors:
        parts = re.split(r"[\s,]+", authors[0].strip())
        last = re.sub(r"[^a-z0-9]", "", parts[-1].lower()) or "unknown"
    w = re.sub(r"[^a-z0-9]+", "", _norm_title(title).split(" ")[0] if title else "paper")[:12]
    base = f"{last}{year}{w}".lower() or f"paper{year}"
    cand = base
    n = 0
    while cand in used:
        n += 1
        cand = f"{base}{n}"
    used.add(cand)
    return cand


def _format_bib_entry(
    entry_type: str,
    bib_key: str,
    title: str,
    authors: list[str],
    year: int,
    venue: str,
) -> str:
    auth = " and ".join(authors) if authors else "Unknown"
    ven = venue or ""
    return (
        f"@{entry_type}{{{bib_key},\n"
        f"  title={{{title}}},\n"
        f"  author={{{auth}}},\n"
        f"  year={{{year}}},\n"
        f"  booktitle={{{ven}}},\n"
        f"}}"
    )


class LitReview:
    def __init__(self, client: SemanticScholarClient | None = None):
        self.client = client or SemanticScholarClient()

    def _verify_entry(self, e: _ParsedBibEntry) -> CitationCheckEntry:
        if e.parse_issue:
            return CitationCheckEntry(
                bib_key=e.bib_key,
                title=e.title,
                found=False,
                semantic_scholar_id=None,
                matched_title=None,
                year=e.year,
                issue=e.parse_issue,
            )
        if not e.title or not str(e.title).strip():
            return CitationCheckEntry(
                bib_key=e.bib_key,
                title=None,
                found=False,
                semantic_scholar_id=None,
                matched_title=None,
                year=e.year,
                issue="not_found",
            )

        flist = ["paperId", "title", "year", "authors", "venue", "citationCount"]
        papers, ok = self.client._paper_search_raw(e.title, 5, flist)
        if not ok:
            return CitationCheckEntry(
                bib_key=e.bib_key,
                title=e.title,
                found=False,
                semantic_scholar_id=None,
                matched_title=None,
                year=e.year,
                issue="api_error",
            )
        if not papers:
            return CitationCheckEntry(
                bib_key=e.bib_key,
                title=e.title,
                found=False,
                semantic_scholar_id=None,
                matched_title=None,
                year=e.year,
                issue="not_found",
            )
        paper = papers[0]

        pid = paper.get("paperId")
        ss_title = paper.get("title")
        ss_y = _paper_year(paper)

        title_ok = _titles_match(e.title, ss_title if isinstance(ss_title, str) else None)
        if not title_ok:
            return CitationCheckEntry(
                bib_key=e.bib_key,
                title=e.title,
                found=False,
                semantic_scholar_id=str(pid) if pid else None,
                matched_title=str(ss_title) if ss_title else None,
                year=e.year,
                issue="title_mismatch",
            )

        issue: str | None = None
        if e.year is not None and ss_y is not None and e.year != ss_y:
            issue = "year_mismatch"

        return CitationCheckEntry(
            bib_key=e.bib_key,
            title=e.title,
            found=True,
            semantic_scholar_id=str(pid) if pid else None,
            matched_title=str(ss_title) if ss_title else None,
            year=e.year,
            issue=issue,
        )

    def check_bib(self, bib_path: str | Path) -> list[CitationCheckEntry]:
        p = expand(bib_path)
        text = p.read_text(encoding="utf-8", errors="replace")
        parsed = parse_bib_text(text)
        return [self._verify_entry(e) for e in parsed]

    def suggest_must_cites(
        self,
        keywords: list[str],
        existing_bib_keys: set[str],
        *,
        max_suggestions: int = 20,
        min_citations: int = 30,
    ) -> list[MustCiteSuggestion]:
        max_suggestions = max(0, int(max_suggestions))
        min_citations = int(min_citations)
        suggestions: list[MustCiteSuggestion] = []
        seen_ids: set[str] = set()
        used_keys: set[str] = set(existing_bib_keys)

        for kw in keywords:
            if len(suggestions) >= max_suggestions:
                break
            papers = self.client.search_by_keyword(kw, limit=20)
            for p in papers:
                if len(suggestions) >= max_suggestions:
                    break
                pid = p.get("paperId")
                if not pid or pid in seen_ids:
                    continue
                cites = int(p.get("citationCount") or 0)
                if cites < min_citations:
                    continue
                title = str(p.get("title") or "")
                if not title:
                    continue
                auths = _authors_to_strings(p.get("authors"))
                yr = _paper_year(p) or 0
                venue = str(p.get("venue") or "")
                entry_type = "inproceedings" if venue else "article"
                bkey = _suggestion_bib_key(auths, yr, title, used_keys)
                if bkey in existing_bib_keys:
                    continue
                seen_ids.add(str(pid))
                be = _format_bib_entry(entry_type, bkey, title, auths, yr, venue)
                suggestions.append(
                    MustCiteSuggestion(
                        title=title,
                        authors=auths,
                        year=yr,
                        venue=venue,
                        semantic_scholar_id=str(pid),
                        citation_count=cites,
                        relevance_reason=f"matches keyword '{kw}'",
                        bib_entry=be,
                    )
                )

        return suggestions[:max_suggestions]

    def run_full(
        self,
        bib_path: str | Path,
        keywords: list[str] | None = None,
    ) -> LitReviewReport:
        p = expand(bib_path)
        text = p.read_text(encoding="utf-8", errors="replace")
        parsed = parse_bib_text(text)
        existing_keys = {e.bib_key for e in parsed}
        checks = [self._verify_entry(e) for e in parsed]
        kws = list(keywords or [])
        sug = self.suggest_must_cites(kws, existing_keys) if kws else []

        verified = sum(1 for c in checks if c.found)
        unverified = len(checks) - verified
        return LitReviewReport(
            bib_path=str(p),
            n_entries_total=len(checks),
            n_verified=verified,
            n_unverified=unverified,
            citation_checks=checks,
            must_cite_suggestions=sug,
            keywords_searched=kws,
            generated_at=time.time(),
        )


class StubLitReview:
    """Offline fallback: deterministic dummy report (no network)."""

    def run_full(self, bib_path: str | Path, keywords: list[str] | None = None) -> LitReviewReport:
        p = expand(bib_path)
        kws = list(keywords or ["stub-topic"])
        ts = 1700000000.0  # deterministic
        bcites = [
            CitationCheckEntry(
                bib_key="stub2024good",
                title="A Stub Paper Title",
                found=True,
                semantic_scholar_id="stub-paper-id-1",
                matched_title="A Stub Paper Title",
                year=2024,
                issue=None,
            ),
            CitationCheckEntry(
                bib_key="stub2023bad",
                title="Unknown Missing Title",
                found=False,
                semantic_scholar_id=None,
                matched_title=None,
                year=2023,
                issue="not_found",
            ),
        ]
        ms = [
            MustCiteSuggestion(
                title="Attention Is All You Need",
                authors=["Ashish Vaswani", "Noam Shazeer", "Niki Parmar"],
                year=2017,
                venue="NeurIPS",
                semantic_scholar_id="stub-attention-id",
                citation_count=90000,
                relevance_reason="matches keyword 'transformer'",
                bib_entry=(
                    "@inproceedings{vaswani2017attention,\n"
                    "  title={Attention Is All You Need},\n"
                    "  author={Vaswani and Shazeer and Parmar},\n"
                    "  year={2017},\n"
                    "  booktitle={NeurIPS},\n"
                    "}"
                ),
            )
        ]
        return LitReviewReport(
            bib_path=str(p),
            n_entries_total=len(bcites),
            n_verified=1,
            n_unverified=1,
            citation_checks=bcites,
            must_cite_suggestions=ms,
            keywords_searched=kws,
            generated_at=ts,
        )


def _self_test(network: bool = False) -> int:
    def ok(msg: str) -> None:
        print(f"OK: {msg}")

    def fail(reason: str) -> int:
        print(f"FAIL: {reason}", file=sys.stderr)
        return 1

    # 1) Parse synthetic .bib (3 entries: title / year-only / malformed-unclosed)
    synthetic = r"""
@article{hasTitle,
  title = {Example Paper About AI},
  year = {2021},
}

@article{yearOnlyEntry,
  year = {2018},
}

@article{brokenEntry,
  title = {This brace never closes
"""

    parsed = parse_bib_text(synthetic)
    if len(parsed) != 3:
        return fail(f"expected 3 parsed bib entries, got {len(parsed)}")

    mal: _ParsedBibEntry | None = None
    for e in parsed:
        if e.bib_key == "brokenEntry" or "broken" in e.bib_key.lower():
            mal = e
    if mal is None:
        mal = parsed[-1]
    if not mal.parse_issue:
        # third entry should be malformed (unclosed outer brace)
        return fail("malformed bib entry should have parse_issue set")
    lit0 = LitReview(client=SemanticScholarClient(rate_limit_rps=0.0))
    mal_check = lit0._verify_entry(parsed[-1])
    if mal_check.issue != "malformed_bib" or mal_check.found:
        return fail(
            "malformed CitationCheckEntry should have issue='malformed_bib' and found=False"
        )
    ok("parsed dummy bib (3 entries)")

    # 2) StubLitReview deterministic report
    stub_path = Path("/tmp/stub_lit_review.bib")
    stub_path.write_text("@article{x, title={y}, year={2020},}\n", encoding="utf-8")
    rep_stub1 = StubLitReview().run_full(stub_path, keywords=["kw"])
    rep_stub2 = StubLitReview().run_full(stub_path, keywords=["kw"])
    if rep_stub1.to_dict() != rep_stub2.to_dict():
        return fail("StubLitReview reports not deterministic")
    d_stub = rep_stub1.to_dict()
    for key in (
        "bib_path",
        "n_entries_total",
        "n_verified",
        "n_unverified",
        "citation_checks",
        "must_cite_suggestions",
        "keywords_searched",
        "generated_at",
    ):
        if key not in d_stub:
            return fail(f"stub report dict missing {key}")
    if not d_stub["citation_checks"] or not d_stub["must_cite_suggestions"]:
        return fail("stub report must populate citation_checks and must_cite_suggestions")
    ok("StubLitReview returns deterministic report")

    # 3) Client instantiates without network
    SemanticScholarClient(rate_limit_rps=1.0)
    ok("SemanticScholarClient instantiates")

    # 4) Markdown + JSON
    md = rep_stub1.to_markdown_summary()
    if not md or not md.strip():
        return fail("to_markdown_summary empty")
    try:
        json.dumps(rep_stub1.to_dict())
    except TypeError as e:
        return fail(f"to_dict not JSON-serializable: {e}")
    ok("LitReviewReport markdown + JSON roundtrip basics")

    # 5) Optional network
    if network:
        cli = SemanticScholarClient(rate_limit_rps=1.0)
        pap = cli.search_by_title("Attention Is All You Need")
        if not pap:
            return fail("network search returned no paper for 'Attention Is All You Need'")
        ok("network: found 'Attention Is All You Need' on Semantic Scholar")
    else:
        ok("skipped network self-test (pass --network to enable)")

    print("OK: all checks passed")
    return 0


def _main() -> int:
    ap = argparse.ArgumentParser(description="Literature review (Semantic Scholar) helpers")
    ap.add_argument("--self-test", action="store_true", help="Run offline self-test")
    ap.add_argument("--network", action="store_true", help="With --self-test, hit Semantic Scholar API once")
    args = ap.parse_args()
    if args.self_test:
        return _self_test(network=args.network)
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
