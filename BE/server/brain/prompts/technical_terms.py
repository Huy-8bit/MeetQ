from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Pattern


PROTECTED_TECH_TERMS: tuple[str, ...] = (
    "software engineer",
    "frontend engineer",
    "backend engineer",
    "DevOps engineer",
    "full-stack engineer",
    "QA engineer",
    "product manager",
    "project manager",
    "button",
    "dropdown",
    "input",
    "screen",
    "layout",
    "backend",
    "frontend",
    "API",
    "Python",
    "Golang",
    "Docker",
    "Redis",
    "MongoDB",
    "PostgreSQL",
    "Node.js",
    "React",
    "Next.js",
    "TypeScript",
    "JavaScript",
    "LiveKit",
    "OpenAI",
    "BRSE",
    "Ho Chi Minh",
    "Saigon",
    # DevOps / infrastructure terms — commonly mis-translated
    "k8s",
    "Kubernetes",
    "kubectl",
    "deploy",
    "deployment",
    "pipeline",
    "CI/CD",
    "git",
    "Helm",
    "pod",
    "container",
    "microservice",
    "cluster",
    "namespace",
    "ingress",
    "Dockerfile",
    "docker-compose",
    "merge",
    "pull request",
    "PR",
    "branch",
    "commit",
    "staging",
    "production",
    "rollback",
    "hotfix",
    "release",
)

_TECH_CONTEXT_WORDS = (
    "button",
    "dropdown",
    "input",
    "screen",
    "layout",
    "frontend",
    "backend",
    "api",
    "docker",
    "redis",
    "mongodb",
    "golang",
    "python",
    "react",
    "livekit",
    "ui",
    "dev",
    "code",
    "server",
    "client",
    "deploy",
    "deployment",
    "database",
    "engineer",
    "product",
    "k8s",
    "kubernetes",
    "kubectl",
    "helm",
    "pod",
    "container",
    "pipeline",
    "git",
    "merge",
    "commit",
    "microservice",
    "cluster",
    "staging",
    "production",
    "rollback",
    "branch",
    "release",
    "sửa",
    "bấm",
    "nhấn",
    "click",
    "màn hình",
    "giao diện",
)

_TECH_CONTEXT_RE = re.compile(
    r"\b(?:"
    + "|".join(re.escape(term) for term in _TECH_CONTEXT_WORDS)
    + r")\b",
    re.IGNORECASE,
)

_TERM_HIT_RES: tuple[tuple[str, Pattern[str]], ...] = tuple(
    (term, re.compile(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", re.IGNORECASE))
    for term in PROTECTED_TECH_TERMS
)

_CANONICAL_REPLACEMENTS: tuple[tuple[str, Pattern[str], str], ...] = (
    ("job_title", re.compile(r"\bsoftware\s+engineer\b", re.IGNORECASE), "software engineer"),
    ("job_title", re.compile(r"\bfront[\s-]*end\s+engineer\b", re.IGNORECASE), "frontend engineer"),
    ("job_title", re.compile(r"\bback[\s-]*end\s+engineer\b", re.IGNORECASE), "backend engineer"),
    ("job_title", re.compile(r"\bdev[\s-]*ops\s+engineer\b", re.IGNORECASE), "DevOps engineer"),
    ("job_title", re.compile(r"\bfull[\s-]*stack\s+engineer\b", re.IGNORECASE), "full-stack engineer"),
    ("job_title", re.compile(r"\bq\s*a\s+engineer\b", re.IGNORECASE), "QA engineer"),
    ("tech_term", re.compile(r"\bfront[\s-]*end\b", re.IGNORECASE), "frontend"),
    ("tech_term", re.compile(r"\bback[\s-]*end\b", re.IGNORECASE), "backend"),
    ("tech_term", re.compile(r"\bdev[\s-]*ops\b", re.IGNORECASE), "DevOps"),
    ("ui_term", re.compile(r"\bdrop[\s-]*down\b", re.IGNORECASE), "dropdown"),
    ("tech_stack", re.compile(r"\bgo\s+lang\b", re.IGNORECASE), "Golang"),
    ("tech_stack", re.compile(r"\bgolang\b", re.IGNORECASE), "Golang"),
    ("tech_stack", re.compile(r"\bdocker\b", re.IGNORECASE), "Docker"),
    ("tech_stack", re.compile(r"\bredis\b", re.IGNORECASE), "Redis"),
    ("tech_stack", re.compile(r"\bmongo\s*db\b", re.IGNORECASE), "MongoDB"),
    ("tech_stack", re.compile(r"\blive\s*kit\b", re.IGNORECASE), "LiveKit"),
    ("tech_stack", re.compile(r"\bnode\s*\.?\s*js\b", re.IGNORECASE), "Node.js"),
    ("tech_stack", re.compile(r"\bnext\s*\.?\s*js\b", re.IGNORECASE), "Next.js"),
    ("tech_stack", re.compile(r"\btype\s*script\b", re.IGNORECASE), "TypeScript"),
    ("tech_stack", re.compile(r"\bjava\s*script\b", re.IGNORECASE), "JavaScript"),
    ("tech_stack", re.compile(r"\bpostgre\s*sql\b", re.IGNORECASE), "PostgreSQL"),
    ("place_name", re.compile(r"\bh(?:o|ồ)\s+ch[ií]\s+minh\b", re.IGNORECASE), "Ho Chi Minh"),
    ("place_name", re.compile(r"\bhcmc\b", re.IGNORECASE), "Ho Chi Minh"),
    ("place_name", re.compile(r"\bs(?:ai|ài)\s+g(?:o|ò)n\b", re.IGNORECASE), "Saigon"),
    # DevOps / infra normalization — k8s variants commonly misrecognized by ASR
    ("infra_term", re.compile(r"\bk\s*8\s*s\b", re.IGNORECASE), "k8s"),
    ("infra_term", re.compile(r"\bkubernetes\b", re.IGNORECASE), "Kubernetes"),
    ("infra_term", re.compile(r"\bkubectl\b", re.IGNORECASE), "kubectl"),
    ("infra_term", re.compile(r"\bci\s*/\s*cd\b", re.IGNORECASE), "CI/CD"),
    ("infra_term", re.compile(r"\bdocker[\s-]*compose\b", re.IGNORECASE), "docker-compose"),
    ("infra_term", re.compile(r"\bdocker\s*file\b", re.IGNORECASE), "Dockerfile"),
    ("infra_term", re.compile(r"\bmicro[\s-]*service\b", re.IGNORECASE), "microservice"),
    ("infra_term", re.compile(r"\bpull[\s-]*request\b", re.IGNORECASE), "pull request"),
    ("infra_term", re.compile(r"\bhot[\s-]*fix\b", re.IGNORECASE), "hotfix"),
    ("infra_term", re.compile(r"\bkey\s*eight\s*s\b", re.IGNORECASE), "k8s"),
    ("infra_term", re.compile(r"\bk\s+eight\s+s\b", re.IGNORECASE), "k8s"),
    ("tech_stack", re.compile(r"\bred\s*dis\b", re.IGNORECASE), "Redis"),
    ("tech_stack", re.compile(r"\bdock\s+er\b", re.IGNORECASE), "Docker"),
    ("tech_stack", re.compile(r"\bsoftware\s+in\s+geneer\b", re.IGNORECASE), "software engineer"),
)

_CONTEXTUAL_ASR_CORRECTIONS: tuple[tuple[str, Pattern[str], str], ...] = (
    (
        "ui_button_asr_context",
        re.compile(
            r"\b((?:cái|nút|bấm|click|sửa|ấn|chọn|nhấn|tap|press|select)\s+)(?:bg|b\s+g|btn)\b",
            re.IGNORECASE,
        ),
        r"\1button",
    ),
    (
        "ui_button_asr_phonetic_context",
        re.compile(
            r"\b((?:cái|nút|bấm|click|sửa|ấn|chọn|nhấn|tap)\s+)(?:bờ|bớt|bật)\s+t(?:ần|ân|on)\b",
            re.IGNORECASE,
        ),
        r"\1button",
    ),
)

_AMBIGUOUS_TECH_FRAGMENT_RE = re.compile(r"(?<![A-Za-z0-9])(?:bg|b\s+g|bt|b\s+t)(?![A-Za-z0-9])", re.IGNORECASE)


@dataclass(frozen=True)
class TechnicalTermNormalizationResult:
    text: str
    protected_terms: tuple[str, ...] = ()
    corrections: tuple[str, ...] = ()
    ambiguous_fragments: tuple[str, ...] = ()
    source_changed: bool = False

    def as_signal(self) -> dict[str, object]:
        return {
            "protected_terms": list(self.protected_terms),
            "corrections": list(self.corrections),
            "ambiguous_fragments": list(self.ambiguous_fragments),
            "source_changed": self.source_changed,
        }


def build_technical_transcription_prompt() -> str:
    # ASR-only hint. Interpreter/relay policies live in session_config and
    # per-turn term injection; do not grow this into a translation policy.
    return (
        "ASR hint for live BRSE meetings: transcribe speech as heard before translation. "
        "Speakers may mix Vietnamese with English IT/product/UI/DevOps terms in one utterance; "
        "keep that code-switching instead of forcing one language. "
        "Preserve technical terms, proper nouns, company/person/place names, natural casing, "
        "and shorthand such as k8s, CI/CD, API, Docker, Redis, Kubernetes, LiveKit, OpenAI, "
        "BRSE, Ho Chi Minh, button, deploy, and software engineer. "
        "If unclear, write the closest heard words and do not invent a technical term."
    )


def build_technical_translation_policy() -> str:
    # This is the base session-level policy. Per-turn specific term preservation
    # is injected dynamically by interpreter_client using term_detector.detect_terms().
    # Keep this short and principle-based to reduce instruction noise.
    return (
        "Technical-term policy: meeting speech often mixes Vietnamese with English technical terms, "
        "product names, tool names, job titles, and code terms. "
        "Preserve English technical tokens in their natural form when that is the speaker's intent. "
        "Do not invent translations for unclear short tokens. "
        "For job titles, preserve the technical role accurately. "
        "Specific terms that must be preserved in this turn will be listed in the request. "
    )


def normalize_technical_terms(text: str) -> TechnicalTermNormalizationResult:
    current = text or ""
    corrections: list[str] = []

    for reason, pattern, replacement in _CONTEXTUAL_ASR_CORRECTIONS:
        next_text, count = pattern.subn(replacement, current)
        if count:
            corrections.append(reason)
            current = next_text

    for reason, pattern, replacement in _CANONICAL_REPLACEMENTS:
        next_text, count = pattern.subn(replacement, current)
        if count:
            corrections.append(reason)
            current = next_text

    protected_terms = _find_protected_terms(current)
    ambiguous_fragments = _find_ambiguous_fragments(text or "", corrections)
    return TechnicalTermNormalizationResult(
        text=current,
        protected_terms=tuple(protected_terms),
        corrections=tuple(corrections),
        ambiguous_fragments=tuple(ambiguous_fragments),
        source_changed=current != (text or ""),
    )


def text_has_technical_context(text: str) -> bool:
    return bool(_TECH_CONTEXT_RE.search(text or ""))


def _find_protected_terms(text: str) -> list[str]:
    result: list[str] = []
    for term, pattern in _TERM_HIT_RES:
        if pattern.search(text):
            result.append(term)
    return result


def _find_ambiguous_fragments(text: str, corrections: list[str]) -> list[str]:
    if corrections:
        return []
    fragments = {
        " ".join(match.group(0).lower().split())
        for match in _AMBIGUOUS_TECH_FRAGMENT_RE.finditer(text)
    }
    if not fragments:
        return []
    return sorted(fragments)
