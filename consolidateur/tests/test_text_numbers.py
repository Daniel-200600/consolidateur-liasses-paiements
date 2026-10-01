"""
tests/test_text_numbers.py

Nombres saisis en TEXTE dans les fichiers sources.

Les liasses reçues contiennent des cellules où le nombre a été saisi comme du
texte (« 25310 », « 15 300 000 000,00 »). Excel ne les additionne pas : sans
traitement, elles seraient comptées comme zéro et fausseraient les totaux de
plusieurs milliards de XAF. L'outil les récupère et les signale.

Ces tests verrouillent deux exigences opposées :
- la récupération doit être effective (sinon totaux sous-évalués) ;
- elle ne doit modifier AUCUNE des valeurs de référence déjà validées
  (cf. Cahier des charges, section 9).
"""

from pathlib import Path

import pytest

from core.kpis import compute_kpis, retrait_gab_kpi
from core.parsing import Institution, _parse_numeric_text, parse_workbook
from core.quality import check_text_numbers

FIXTURES = Path(__file__).parent / "fixtures_fictives"


@pytest.fixture
def institutions():
    return [
        Institution(name="BanqueA", file_name="BanqueA.xlsx", sheets=parse_workbook(FIXTURES / "BanqueA.xlsx")),
        Institution(name="OperateurB", file_name="OperateurB.xlsx", sheets=parse_workbook(FIXTURES / "OperateurB.xlsx")),
    ]


# --------------------------------------------------------------------- #
# Conversion elle-même
# --------------------------------------------------------------------- #

@pytest.mark.parametrize("raw, expected", [
    ("25310", 25310),
    ("15\u00a0300\u00a0000\u00a0000,00", 15300000000),
    ("1 234", 1234),
    ("3,5", 3.5),
    ("-42", -42),
])
def test_numeric_text_is_parsed(raw, expected):
    assert _parse_numeric_text(raw) == expected


@pytest.mark.parametrize("raw", [
    "", "   ", "Retrait GAB", "(1)", "12A", "1.2.3", None, 42, "N/A", "7,9%",
])
def test_non_numeric_text_is_left_alone(raw):
    assert _parse_numeric_text(raw) is None


# --------------------------------------------------------------------- #
# Effet sur les fichiers de référence
# --------------------------------------------------------------------- #

def test_text_numbers_are_recovered(institutions):
    total_cells = sum(len(sd.text_numbers) for i in institutions for sd in i.sheets.values())
    assert total_cells == 33


def test_recovered_amounts_are_material(institutions):
    operateur_b = institutions[1]
    mm1 = operateur_b.sheets["Mobile Money1"].text_numbers
    assert len(mm1) == 1
    assert mm1[0]["parsed"] == 19144002809  # encours d'un mois, sinon compté 0


def test_labels_are_never_converted(institutions):
    """La colonne des libellés (colonne 0) ne doit jamais être convertie,
    sous peine de transformer un intitulé en donnée."""
    for inst in institutions:
        for sd in inst.sheets.values():
            assert all(t["col"] > 0 for t in sd.text_numbers)


def test_reference_values_are_unchanged(institutions):
    """Garde-fou central : la récupération ne doit rien changer aux valeurs
    validées manuellement."""
    expected = {
        "porteurs_mm_total": 1232671,
        "porteurs_mm_actifs": 359593,
        "encours_me": 14621281997,
        "clients_cartes": 11386,
        "comptes_cartes": 29374,
        "cartes_debit": 21298,
    }
    for k in compute_kpis(institutions):
        assert k.total == expected[k.key], f"{k.key} a changé : {k.total}"
    gab = retrait_gab_kpi(institutions)
    assert gab["total"]["nombre"] == 142872
    assert gab["total"]["valeur"] == 14942539230


# --------------------------------------------------------------------- #
# Signalement
# --------------------------------------------------------------------- #

def test_quality_flag_is_raised(institutions):
    flags = check_text_numbers(institutions)
    assert len(flags) == 2  # Mobile Money1 et MobileMoney2, côté OperateurB
    assert all(f.institution == "OperateurB" for f in flags)
    assert {f.sheet for f in flags} == {"Mobile Money1", "MobileMoney2"}
    assert all("corriger à la source" in f.message for f in flags)


def test_flag_details_allow_locating_each_cell(institutions):
    flags = check_text_numbers(institutions)
    mm1 = next(f for f in flags if f.sheet == "Mobile Money1")
    detail = mm1.details[0]
    assert detail["addr"]                      # ex. "N6" : repérable dans Excel
    assert detail["original"] != detail["parsed"]


def test_clean_file_raises_no_flag(institutions):
    banque_a = institutions[0]
    assert check_text_numbers([banque_a]) == []
