"""PII scrubber for text that comes from outside (news titles and snippets, model output).

Only patterns that can be validated are redacted: CPF and CNPJ must have correct check digits,
so ordinary numbers (case counts, years) are left alone.
"""

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

_CNPJ = re.compile(r"(?<!\d)\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}(?!\d)")
_CPF = re.compile(r"(?<!\d)\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?!\d)")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONES = (
    re.compile(r"(?<!\d)(?:\+?55[\s-]?)?\(?\d{2}\)?[\s-]?9\d{4}[\s-]?\d{4}(?!\d)"),  # mobile
    re.compile(r"(?<!\d)\(\d{2}\)\s?\d{4}[\s-]?\d{4}(?!\d)"),  # landline with area code in parens
    re.compile(r"(?<![\d-])\d{4,5}-\d{4}(?![\d-])"),  # local number with a dash
)


def _digits(value: str) -> list[int]:
    return [int(char) for char in value if char.isdigit()]


def valid_cpf(value: str) -> bool:
    """Check the two CPF verification digits (and reject repeated-digit sequences)."""
    digits = _digits(value)
    if len(digits) != 11 or len(set(digits)) == 1:  # noqa: PLR2004
        return False
    for length in (9, 10):
        total = sum(
            digit * weight for digit, weight in zip(digits, range(length + 1, 1, -1), strict=False)
        )
        if (total * 10 % 11) % 10 != digits[length]:
            return False
    return True


def valid_cnpj(value: str) -> bool:
    """Check the two CNPJ verification digits (and reject repeated-digit sequences)."""
    digits = _digits(value)
    if len(digits) != 14 or len(set(digits)) == 1:  # noqa: PLR2004
        return False
    for length, weights in (
        (12, (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)),
        (13, (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)),
    ):
        total = sum(digit * weight for digit, weight in zip(digits, weights, strict=False))
        remainder = total % 11
        if (0 if remainder < 2 else 11 - remainder) != digits[length]:  # noqa: PLR2004
            return False
    return True


@dataclass(frozen=True)
class ScrubResult:
    """Text with PII replaced by placeholders, and how many of each kind were found."""

    text: str
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def redactions(self) -> int:
        """Total number of redactions."""
        return sum(self.counts.values())


def scrub(text: str) -> ScrubResult:
    """Redact CPF, CNPJ, e-mail addresses and Brazilian phone numbers."""
    found: Counter[str] = Counter()

    def validated(
        pattern: re.Pattern[str], label: str, check: Callable[[str], bool], current: str
    ) -> str:
        def replace(match: re.Match[str]) -> str:
            if check(match.group(0)):
                found[label] += 1
                return f"[{label}]"
            return match.group(0)

        return pattern.sub(replace, current)

    result = validated(_CNPJ, "CNPJ", valid_cnpj, text)
    result = validated(_CPF, "CPF", valid_cpf, result)
    result, emails = _EMAIL.subn("[EMAIL]", result)
    if emails:
        found["EMAIL"] += emails
    for pattern in _PHONES:
        result, phones = pattern.subn("[TELEFONE]", result)
        if phones:
            found["TELEFONE"] += phones
    return ScrubResult(result, dict(found))
