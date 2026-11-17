import pytest

from srag_sentinel.guardrails.pii import scrub, valid_cnpj, valid_cpf

VALID_CPF = "529.982.247-25"
VALID_CNPJ = "11.222.333/0001-81"


@pytest.mark.parametrize(
    ("text", "label", "secret"),
    [
        (f"Paciente CPF {VALID_CPF} internado", "CPF", "529.982"),
        ("CPF 52998224725 sem máscara", "CPF", "52998224725"),
        (f"CNPJ {VALID_CNPJ} do hospital", "CNPJ", "11.222.333"),
        ("CNPJ 11222333000181 sem máscara", "CNPJ", "11222333000181"),
        ("contato maria.silva+saude@exemplo.com.br urgente", "EMAIL", "maria.silva"),
        ("ligue (11) 91234-5678 hoje", "TELEFONE", "91234"),
        ("whats +55 11 91234 5678", "TELEFONE", "91234"),
        ("fixo (21) 2345-6789", "TELEFONE", "2345-6789"),
        ("telefone 98765-4321", "TELEFONE", "98765"),
        ("11912345678 é o celular", "TELEFONE", "912345678"),
    ],
)
def test_validated_pii_is_replaced_by_a_placeholder(text: str, label: str, secret: str) -> None:
    result = scrub(text)

    assert f"[{label}]" in result.text
    assert secret not in result.text
    assert result.counts.get(label, 0) >= 1


@pytest.mark.parametrize(
    "text",
    [
        "Foram notificados 11111111111 casos",  # repeated digits are not a CPF
        "Código 12345678901 sem sentido",  # 11 digits with wrong check digits
        "14 221 casos de SRAG em 2026",
        "A taxa foi de 29,2% e 15655 casos",
        "Data 2026-11-15 e semana 46",
        "Texto comum sem dados pessoais",
    ],
)
def test_ordinary_numbers_and_text_are_left_alone(text: str) -> None:
    result = scrub(text)

    assert result.text == text
    assert result.redactions == 0


def test_every_kind_is_counted_separately() -> None:
    text = f"{VALID_CPF}; {VALID_CNPJ}; a@b.com; c@d.org; (11) 91234-5678"

    result = scrub(text)

    assert result.counts == {"CPF": 1, "CNPJ": 1, "EMAIL": 2, "TELEFONE": 1}
    assert result.redactions == 5


def test_checksums() -> None:
    assert valid_cpf(VALID_CPF)
    assert not valid_cpf("529.982.247-24")
    assert not valid_cpf("000.000.000-00")
    assert valid_cnpj(VALID_CNPJ)
    assert not valid_cnpj("11.222.333/0001-80")
    assert not valid_cnpj("00.000.000/0000-00")


def test_scrubbing_is_idempotent() -> None:
    once = scrub(f"CPF {VALID_CPF} e a@b.com").text

    assert scrub(once).text == once


@pytest.mark.parametrize(
    ("text", "label", "secret"),
    [
        ("documento RG 12.345.678-9 do paciente", "RG", "12.345.678"),
        ("RG: 123456789", "RG", "123456789"),
        ("endereço CEP 01310-100, Paulista", "CEP", "01310-100"),
        ("cartão 4539 1488 0343 6467 usado", "CARTAO", "4539 1488"),
        ("cartão 4539-1488-0343-6467", "CARTAO", "0343"),
        ("o paciente Maria da Silva foi internado", "NOME", "Maria da Silva"),
        ("Sr. João Pereira Santos relatou", "NOME", "João Pereira"),
        ("a internada Ana Souza segue estável", "NOME", "Ana Souza"),
    ],
)
def test_extended_pii_is_replaced_by_a_placeholder(text: str, label: str, secret: str) -> None:
    result = scrub(text)

    assert f"[{label}]" in result.text
    assert secret not in result.text
    assert result.counts.get(label, 0) >= 1


@pytest.mark.parametrize(
    "text",
    [
        "4539 1488 0343 6468",  # fails Luhn
        "1111111111111111",
        "12.345.678-9 sem a pista",  # RG needs its cue
        "1234567-890",
        "paciente Covid-19 internado",
        "paciente SRAG grave",
        "o paciente chegou ao hospital",  # no capitalised word after the cue
    ],
)
def test_ordinary_text_is_left_alone(text: str) -> None:
    result = scrub(text)

    assert result.counts == {}
    assert result.text == text


def test_a_bare_name_without_a_cue_is_out_of_reach() -> None:
    assert scrub("Maria da Silva disse que os casos caíram").redactions == 0
