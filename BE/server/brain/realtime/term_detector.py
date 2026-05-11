"""
BE/server/brain/realtime/term_detector.py

Rule-based technical term and mixed-language token detector.

Replaces the static-list approach of technical_terms.PROTECTED_TECH_TERMS as the
PRIMARY detection mechanism. Works on ASR transcript text to identify tokens that
need special handling during relay without relying on an ever-growing flat list.

technical_terms.py retains its role for:
- canonical normalization (go lang → Golang, k 8 s → k8s, bg → button in UI context)
- context-aware ASR corrections
- curated brand/product overrides that shape rules cannot detect reliably

Detection layers (applied in order of confidence):
1. Multi-word job title patterns (regex — highest confidence)
2. Alphanumeric-with-digit tokens (shape rule: k8s, gpt4, oauth2, v1)
3. CamelCase identifiers (shape rule: Docker, MongoDB, TypeScript, LiveKit)
4. ALL-CAPS acronyms filtered against non-tech exclusion set (API, CI, CD, URL)
5. Dotted tech names (Node.js, Next.js, v1.2)
6. Slash abbreviations (CI/CD, A/B)
7. English code-switches in Vietnamese context (rule + small vocabulary)
8. Curated single-word tool/framework names (small explicit list)
9. Ambiguous short fragments in tech context (flag for gating, not preserve)

Integration point: interpreter_client._send_relay_response calls detect_terms()
and appends TermAnalysis.build_preserve_instruction() to the per-turn response.create
instructions. This gives the model per-utterance guidance instead of relying on a
static system-level list.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Vietnamese context marker
# ---------------------------------------------------------------------------

_VI_DIACRITIC_RE = re.compile(
    r"[àáảãạăắằẳẵặâấầẩẫậđèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵ"
    r"ÀÁẢÃẠĂẮẰẲẴẶÂẤẦẨẪẬĐÈÉẺẼẸÊẾỀỂỄỆÌÍỈĨỊÒÓỎÕỌÔỐỒỔỖỘƠỚỜỞỠỢÙÚỦŨỤƯỨỪỬỮỰỲÝỶỸỴ]"
)
_VI_CONTEXT_WORD_RE = re.compile(
    r"\b(?:"
    r"tôi|toi|em|anh|chị|chi|mình|minh|bọn|bon|bên|ben|cái|cai|này|nay|đó|"
    r"sửa|sua|dùng|dung|lên|len|với|voi|ở|đang|dang|cho|cần|muốn|muon"
    r")\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Shape-rule patterns
# ---------------------------------------------------------------------------

# Alphanumeric tokens with embedded digits: k8s, gpt4, oauth2, v1, h264
# Must have at least one letter and at least one digit, may have hyphens
_ALPHANUM_DIGIT_RE = re.compile(
    r"\b(?:[A-Za-z]+\d+[A-Za-z0-9\-]*|\d+[A-Za-z]+[A-Za-z0-9\-]*)\b"
)

# CamelCase: at least two humps (Upper+lower + Upper+lower)
# Catches Docker, MongoDB, TypeScript, LiveKit, OpenAI, DevOps
_CAMEL_CASE_RE = re.compile(r"\b[A-Z][a-z]+(?:[A-Z][a-z0-9]+)+\b")

# ALL-CAPS acronyms 2-6 chars: API, URL, HTTP, SQL, CI, CD, UI, UX, AWS, GCP
_ACRONYM_RE = re.compile(r"\b[A-Z]{2,6}\b")

# Dotted tech names: Node.js, Next.js, React.js, v1.2
_DOTTED_TECH_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9]+\.[a-z]{1,4}\b")

# Slash abbreviations: CI/CD, A/B
_SLASH_ABBREV_RE = re.compile(r"\b[A-Z]{1,5}/[A-Z]{1,5}\b")
_TITLE_CASE_SEQUENCE_RE = re.compile(
    r"\b[A-Z][a-z]{1,}(?:\s+[A-Z][a-z]{1,}){1,3}\b"
)

# Plain English words (for code-switch detection in Vietnamese context)
_ENGLISH_WORD_RE = re.compile(r"\b[A-Za-z]{2,}\b")

# ---------------------------------------------------------------------------
# Vocabulary sets (intentionally SMALL — rules handle most cases)
# ---------------------------------------------------------------------------

# Acronyms that are NOT technical terms — filter these out
_ACRONYM_EXCLUSION: frozenset[str] = frozenset([
    "I", "A", "IS", "OR", "AT", "AN", "AS", "NO", "DO", "GO", "IT", "IN",
    "OF", "ON", "TO", "UP", "US", "WE", "OK", "HI", "VS", "IF", "BY", "MY",
    "AM", "BE", "SO", "HE", "ME", "THE", "AND", "FOR", "NOT", "BUT",
])

# Known single-word tool / framework / service names (curated fallback).
# These are proper names where the CamelCase rule doesn't fire (lowercase or short).
_CURATED_TOOL_NAMES: frozenset[str] = frozenset([
    # Infrastructure & DevOps
    "docker", "redis", "mongodb", "postgres", "postgresql", "mysql", "kafka",
    "nginx", "apache", "jenkins", "grafana", "prometheus", "terraform", "ansible",
    "kubernetes", "kubectl", "helm", "k8s", "git", "github", "gitlab",
    # Cloud
    "aws", "gcp", "azure", "vercel", "netlify", "cloudflare",
    # Frameworks / languages
    "python", "golang", "rust", "kotlin", "swift", "php",
    "react", "vue", "angular", "svelte",
    # Platform-specific
    "livekit", "openai", "anthropic", "brse",
    # Issue trackers / tools
    "jira", "slack", "notion", "figma", "postman", "swagger",
])

# English words frequently code-switched into Vietnamese tech speech.
# These indicate technical usage even in a Vietnamese sentence.
_VI_CODESWITCH_VOCAB: frozenset[str] = frozenset([
    # Dev workflow
    "deploy", "deployment", "build", "test", "debug", "fix", "update", "release",
    "merge", "commit", "push", "pull", "branch", "tag", "rollback", "hotfix",
    "staging", "production", "environment", "pipeline", "workflow",
    # Architecture
    "backend", "frontend", "server", "client", "database", "cache", "queue",
    "microservice", "service", "container", "cluster", "namespace", "pod", "ingress",
    # Dev process / team
    "feature", "ticket", "sprint", "standup", "review", "meeting", "deadline",
    # UI / Product
    "button", "input", "screen", "layout", "dropdown", "modal", "sidebar", "dashboard",
    "popup", "tooltip", "header", "footer", "sidebar",
    # Infra / config
    "config", "variable", "secret", "token", "key", "endpoint", "payload",
    # Generic code terms
    "code", "data", "model", "schema", "api", "sdk", "cli", "log", "error",
])

# Place names and multi-word proper nouns that rules won't catch
_CURATED_PROPER_NOUNS: tuple[re.Pattern[str], str] = (
    (re.compile(r"\bh(?:o|ồ)\s+ch[ií]\s+minh\b", re.IGNORECASE), "Ho Chi Minh"),
    (re.compile(r"\bhcmc\b", re.IGNORECASE), "Ho Chi Minh"),
    (re.compile(r"\bs(?:ai|ài)\s+g(?:o|ò)n\b", re.IGNORECASE), "Saigon"),
)
_TITLE_CASE_EXCLUSION = frozenset(
    {
        "The",
        "This",
        "That",
        "When",
        "Where",
        "Because",
        "Please",
        "Thank You",
        "All Right",
        "Good Morning",
        "Good Afternoon",
        "Good Evening",
    }
)

# ---------------------------------------------------------------------------
# Job title patterns (multi-word, high confidence)
# ---------------------------------------------------------------------------

_JOB_TITLE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"\b(?:software|frontend|back[\s-]?end|backend|full[\s\-]?stack|devops|"
            r"qa|product|project|data|ml|ai|technical|tech)\s+"
            r"(?:engineer|developer|manager|lead|director|head|architect|analyst)\b",
            re.IGNORECASE,
        ),
        "job_title",
    ),
    (re.compile(r"\bengineering\s+manager\b", re.IGNORECASE), "job_title"),
    (re.compile(r"\btech(?:nical)?\s+lead\b", re.IGNORECASE), "job_title"),
    (re.compile(r"\bteam\s+lead\b", re.IGNORECASE), "job_title"),
    (re.compile(r"\bproduct\s+owner\b", re.IGNORECASE), "job_title"),
    (re.compile(r"\bscrum\s+master\b", re.IGNORECASE), "job_title"),
]

# ---------------------------------------------------------------------------
# Ambiguous short fragment detection (possible ASR errors)
# ---------------------------------------------------------------------------

# Short tokens that look technical but can't be confirmed — flag for gating
_AMBIGUOUS_FRAGMENT_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"bg|b\s+g|bt|b\s+t|"         # Known Vietnamese ASR artifacts for "button"
    r"[a-z][0-9][a-z]|"            # 3-char mixed like a2b, b3g (but NOT k8s — that's caught by alphanum)
    r"[a-z]{1,2}[0-9]{1,2}(?![A-Za-z0-9])"  # short alpha+digit like 'v1' 'k8' without suffix
    r")(?![A-Za-z0-9])",
    re.IGNORECASE,
)

# Tech context keywords — used to decide if an ambiguous fragment is in a tech sentence
_TECH_CONTEXT_FAST_CHECK = frozenset([
    "button", "deploy", "backend", "frontend", "server", "api", "docker",
    "redis", "database", "screen", "code", "sửa", "bấm", "click", "update",
    "kubernetes", "k8s", "git", "service", "container", "pod", "build",
    "deploy", "debug", "fix", "test", "release", "production", "staging",
])


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class TermAnalysis:
    """
    Result of analyzing a source transcript for technical/mixed-language tokens.

    preserve_tokens : tokens that must appear unchanged in the relay
    conservative_tokens : phrases with technical meaning (job titles, roles)
    ambiguous_tokens : possibly garbled ASR — used for source gating, not relay
    is_mixed_language : True when Vietnamese + English code-switching is detected
    source_has_vietnamese : True when Vietnamese diacritics present
    """

    preserve_tokens: list[str] = field(default_factory=list)
    conservative_tokens: list[str] = field(default_factory=list)
    ambiguous_tokens: list[str] = field(default_factory=list)
    is_mixed_language: bool = False
    source_has_vietnamese: bool = False

    @property
    def has_technical_content(self) -> bool:
        return bool(self.preserve_tokens or self.conservative_tokens)

    @property
    def has_unresolved_ambiguity(self) -> bool:
        """Ambiguous tech-looking fragments exist with no confirmed technical terms."""
        return bool(self.ambiguous_tokens) and not self.preserve_tokens

    @property
    def is_clean(self) -> bool:
        """No technical content and no ambiguous fragments — plain speech."""
        return not self.ambiguous_tokens and not self.preserve_tokens and not self.conservative_tokens

    def build_preserve_instruction(self) -> str:
        """
        Build a concise per-turn instruction for model injection in response.create.

        This is the key integration: inject specific terms from THIS utterance so
        the model knows exactly what to preserve, rather than relying on a static list.
        """
        parts: list[str] = []
        if self.preserve_tokens:
            # Cap at 12 terms to keep instructions concise
            terms = ", ".join(self.preserve_tokens[:12])
            parts.append(
                f"These terms appear in the source — keep them exactly as written: {terms}."
            )
        if self.conservative_tokens:
            terms = ", ".join(self.conservative_tokens[:6])
            parts.append(
                f"These terms have specific technical meaning — translate accurately and preserve the role: {terms}."
            )
        if self.is_mixed_language and not parts:
            parts.append(
                "This source mixes Vietnamese and English technical vocabulary. "
                "Keep English technical terms in their natural form."
            )
        return " ".join(parts)

    def as_signal(self) -> dict[str, object]:
        return {
            "preserve": list(self.preserve_tokens),
            "conservative": list(self.conservative_tokens),
            "ambiguous": list(self.ambiguous_tokens),
            "is_mixed_language": self.is_mixed_language,
            "source_has_vietnamese": self.source_has_vietnamese,
        }


# ---------------------------------------------------------------------------
# Core detection function
# ---------------------------------------------------------------------------

def detect_terms(text: str) -> TermAnalysis:
    """
    Analyze a source transcript for technical/mixed-language tokens.

    Uses shape rules + vocabulary sets + Vietnamese context detection to identify
    tokens without relying on a static protected-terms list.

    Args:
        text: ASR transcript (already normalized/corrected by technical_terms.py)

    Returns:
        TermAnalysis with detected tokens and a ready-to-use preserve instruction.
    """
    if not text or not text.strip():
        return TermAnalysis()

    source_has_vi = bool(_VI_DIACRITIC_RE.search(text) or _VI_CONTEXT_WORD_RE.search(text))
    preserve: list[str] = []
    conservative: list[str] = []
    seen_preserve: set[str] = set()
    seen_conservative: set[str] = set()
    # Track character spans covered by multi-word matches to avoid re-tokenizing
    covered_spans: list[tuple[int, int]] = []

    def _add_preserve(token: str) -> None:
        t = token.strip()
        if t and t not in seen_preserve:
            preserve.append(t)
            seen_preserve.add(t)

    def _add_conservative(phrase: str) -> None:
        p = phrase.strip()
        if p and p not in seen_conservative and p not in seen_preserve:
            conservative.append(p)
            seen_conservative.add(p)

    def _span_is_covered(start: int, end: int) -> bool:
        return any(cs <= start and end <= ce for cs, ce in covered_spans)

    # --- Layer 1: Multi-word job title patterns (highest confidence) ---
    for pattern, _ in _JOB_TITLE_PATTERNS:
        for m in pattern.finditer(text):
            if not _span_is_covered(m.start(), m.end()):
                _add_conservative(m.group(0))
                covered_spans.append((m.start(), m.end()))

    # --- Layer 1b: Curated proper noun patterns ---
    for pattern, canonical in _CURATED_PROPER_NOUNS:
        for m in pattern.finditer(text):
            if not _span_is_covered(m.start(), m.end()):
                _add_preserve(canonical)
                covered_spans.append((m.start(), m.end()))

    # --- Layer 1c: Multi-word proper nouns in mixed Vietnamese context ---
    # Conservative by design: only multi-token Title Case sequences, and mostly
    # useful when Vietnamese function words indicate code-switching/name usage.
    if source_has_vi:
        for m in _TITLE_CASE_SEQUENCE_RE.finditer(text):
            if _span_is_covered(m.start(), m.end()):
                continue
            phrase = m.group(0).strip()
            if phrase not in _TITLE_CASE_EXCLUSION:
                _add_preserve(phrase)
                covered_spans.append((m.start(), m.end()))

    # --- Layer 2: Shape rules on individual tokens ---

    # 2a. Alphanumeric-with-digit (k8s, gpt4, oauth2, v1beta)
    # Exclude common time/unit formats: 10h30, 5km, 2px — these are NOT tech identifiers
    _TIME_UNIT_RE = re.compile(r"^\d+[hHmMsS]\d*$|^\d+(?:km|cm|mm|px|pt|em|rem|ms|gb|mb|kb)$", re.IGNORECASE)
    for m in _ALPHANUM_DIGIT_RE.finditer(text):
        if _span_is_covered(m.start(), m.end()):
            continue
        token = m.group(0)
        if not token.isdigit() and len(token) >= 2 and not _TIME_UNIT_RE.match(token):
            _add_preserve(token)

    # 2b. CamelCase identifiers (Docker, MongoDB, TypeScript, LiveKit)
    for m in _CAMEL_CASE_RE.finditer(text):
        if _span_is_covered(m.start(), m.end()):
            continue
        token = m.group(0)
        if len(token) >= 4:
            _add_preserve(token)

    # 2c. Dotted tech names (Node.js, Next.js)
    for m in _DOTTED_TECH_RE.finditer(text):
        if _span_is_covered(m.start(), m.end()):
            continue
        _add_preserve(m.group(0))

    # 2d. Slash abbreviations (CI/CD)
    for m in _SLASH_ABBREV_RE.finditer(text):
        if _span_is_covered(m.start(), m.end()):
            continue
        full_abbrev = m.group(0)
        _add_preserve(full_abbrev)
        # Prevent individual parts from being re-detected by the ACRONYM rule
        for part in full_abbrev.split("/"):
            seen_preserve.add(part)

    # 2e. ALL-CAPS acronyms (filtered)
    for m in _ACRONYM_RE.finditer(text):
        if _span_is_covered(m.start(), m.end()):
            continue
        token = m.group(0)
        if token not in _ACRONYM_EXCLUSION:
            _add_preserve(token)

    # --- Layer 3: Known tool names + English code-switches ---
    for m in _ENGLISH_WORD_RE.finditer(text):
        if _span_is_covered(m.start(), m.end()):
            continue
        token = m.group(0)
        lower = token.lower()
        if token in seen_preserve or token in seen_conservative:
            continue
        if lower in seen_preserve:
            continue
        # Always detect curated tool/framework names regardless of language context
        if lower in _CURATED_TOOL_NAMES:
            _add_preserve(token)
        # Code-switch vocabulary only relevant in Vietnamese context
        elif source_has_vi and lower in _VI_CODESWITCH_VOCAB:
            _add_preserve(token)

    # --- Layer 4: Ambiguous fragments (for gating, not relay) ---
    ambiguous: list[str] = []
    seen_ambiguous: set[str] = set()
    for m in _AMBIGUOUS_FRAGMENT_RE.finditer(text):
        fragment = m.group(0).strip()
        if not fragment or fragment in seen_preserve or fragment in seen_ambiguous:
            continue
        # Only flag if surrounded by tech context
        ctx_start = max(0, m.start() - 40)
        ctx_end = min(len(text), m.end() + 40)
        context_snippet = text[ctx_start:ctx_end].lower()
        if any(kw in context_snippet for kw in _TECH_CONTEXT_FAST_CHECK):
            ambiguous.append(fragment)
            seen_ambiguous.add(fragment)

    is_mixed = source_has_vi and bool(preserve or conservative)

    return TermAnalysis(
        preserve_tokens=preserve,
        conservative_tokens=conservative,
        ambiguous_tokens=ambiguous,
        is_mixed_language=is_mixed,
        source_has_vietnamese=source_has_vi,
    )


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

def has_high_confidence_technical_content(analysis: TermAnalysis) -> bool:
    """True when detection found confirmed technical tokens (good for source gating)."""
    return bool(analysis.preserve_tokens)


def is_short_but_valid_technical(text: str, analysis: TermAnalysis) -> bool:
    """
    Returns True when the text is short by character count but contains
    confirmed technical terms — used to bypass length-based source rejection.
    """
    return bool(analysis.preserve_tokens) and not analysis.ambiguous_tokens
