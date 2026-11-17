"""PII scrubber for text that comes from outside (news titles and snippets, model output).

Only patterns that can be validated are redacted: CPF, CNPJ and card numbers must pass their check
digits, an RG needs the "RG" cue, a CEP the dash, and a name a cue such as "paciente" or "Sr.", so
ordinary numbers (case counts, years) are left alone. A bare name stays out of reach (spec 09 §4).
"""

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

_CNPJ = re.compile(r"(?<!\d)\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}(?!\d)")
_CPF = re.compile(r"(?<!\d)\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?!\d)")
# RG has no national check digit, so it is only redacted after the "RG" cue.
_RG = re.compile(r"(?i:\brg\b)[\s:.nº°-]*\d{1,2}\.?\d{3}\.?\d{3}-?[\dxX]\b")
_CEP = re.compile(r"(?<![\d-])\d{5}-\d{3}(?![\d-])")
_CARD = re.compile(r"(?<![\d-])\d(?:[ -]?\d){12,18}(?![\d-])")
# A name is only recognised after a cue ("paciente", "Sr.", "internada"); a bare one is not.
_NAME_CUE = (
    r"(?i:(?:\b(?:paciente(?:\s+de\s+nome)?|senhora?|internad[oa]|v[ií]tima)\b|\bsra?\.)[\s:,]+)"
)
_NAME_WORD = r"[A-ZÀ-ÝÇ][a-zà-ÿç']+"
_NAME = re.compile(rf"({_NAME_CUE})({_NAME_WORD}(?:\s+(?:d[aeo]s?\s+)?{_NAME_WORD}){{0,3}})")
# Words that follow a cue but are not a person (diseases, places in a headline).
_NOT_A_NAME = frozenset({"covid", "srag", "influenza", "gripe", "vsr", "sars", "brasil", "uti"})
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


def valid_card(value: str) -> bool:
    """Luhn check for a 13 to 19 digit card number (and reject repeated-digit sequences)."""
    digits = _digits(value)
    if not 13 <= len(digits) <= 19 or len(set(digits)) == 1:  # noqa: PLR2004
        return False
    total = 0
    for index, digit in enumerate(reversed(digits)):
        if index % 2:
            digit *= 2  # noqa: PLW2901
            if digit > 9:  # noqa: PLR2004
                digit -= 9  # noqa: PLW2901
        total += digit
    return total % 10 == 0


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
    """Redact card (Luhn), CPF, CNPJ, RG and CEP, names after a cue, e-mail and Brazilian phones."""
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

    def named(match: re.Match[str]) -> str:
        if match.group(2).split()[0].lower() in _NOT_A_NAME:
            return match.group(0)
        found["NOME"] += 1
        return f"{match.group(1)}[NOME]"

    result = validated(_CARD, "CARTAO", valid_card, text)
    result = validated(_CNPJ, "CNPJ", valid_cnpj, result)
    result = validated(_CPF, "CPF", valid_cpf, result)
    result = validated(_RG, "RG", lambda _: True, result)
    result = validated(_CEP, "CEP", lambda _: True, result)
    result = _NAME.sub(named, result)
    result, emails = _EMAIL.subn("[EMAIL]", result)
    if emails:
        found["EMAIL"] += emails
    for pattern in _PHONES:
        result, phones = pattern.subn("[TELEFONE]", result)
        if phones:
            found["TELEFONE"] += phones
    return ScrubResult(result, dict(found))
