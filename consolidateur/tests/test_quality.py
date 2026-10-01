"""
tests/test_quality.py

Phase 5 : le contrôle qualité doit retrouver exactement les anomalies déjà
identifiées manuellement dans les fichiers de référence (cf. CDC section 9
et rapport de contrôle qualité initial) :
- 3 cellules en erreur de formule chez OperateurB (MobileMoney2, AB13/17/25) ;
- BanqueA n'a saisi de données réelles que sur 4 onglets (Cartes1, Cartes 2,
  Cartes 3, Cartes 5) -> 7 onglets vides ;
- OperateurB n'a saisi de données réelles que sur 3 onglets (Mobile Money1,
  MobileMoney2, MobileMoney3) -> 8 onglets vides.
"""

from pathlib import Path

import pytest

from core.parsing import Institution, parse_workbook
from core.quality import check_empty_sheets, check_formula_errors, run_quality_checks

FIXTURES = Path(__file__).parent / "fixtures_fictives"


@pytest.fixture
def institutions():
    banque_a = Institution(name="BanqueA", file_name="BanqueA.xlsx", sheets=parse_workbook(FIXTURES / "BanqueA.xlsx"))
    operateur_b = Institution(name="OperateurB", file_name="OperateurB.xlsx", sheets=parse_workbook(FIXTURES / "OperateurB.xlsx"))
    return [banque_a, operateur_b]


def test_formula_errors_detected_only_for_operateur_b(institutions):
    flags = check_formula_errors(institutions)
    assert len(flags) == 1
    assert flags[0].institution == "OperateurB"
    assert flags[0].sheet == "MobileMoney2"
    assert len(flags[0].details) == 3
    addrs = {e["addr"] for e in flags[0].details}
    assert addrs == {"AB13", "AB17", "AB25"}


def test_empty_sheets_banque_a(institutions):
    flags = check_empty_sheets(institutions)
    banque_a_flag = next(f for f in flags if f.institution == "BanqueA")
    assert len(banque_a_flag.details) == 7
    assert "Mobile Money1" in banque_a_flag.details
    assert "Cartes1" not in banque_a_flag.details  # BanqueA a bien des données ici


def test_empty_sheets_operateur_b(institutions):
    flags = check_empty_sheets(institutions)
    operateur_b_flag = next(f for f in flags if f.institution == "OperateurB")
    assert len(operateur_b_flag.details) == 8
    assert "Cartes1" in operateur_b_flag.details
    assert "Mobile Money1" not in operateur_b_flag.details  # OperateurB a bien des données ici


def test_run_quality_checks_combines_both(institutions):
    flags = run_quality_checks(institutions)
    kinds = {f.kind for f in flags}
    # S'ajoute aux deux contrôles historiques : les nombres saisis en texte
    # (récupérés automatiquement mais à corriger à la source).
    assert kinds == {"erreur_formule", "onglet_vide", "nombre_en_texte"}
    assert len([f for f in flags if f.kind == "erreur_formule"]) == 1
    assert len([f for f in flags if f.kind == "onglet_vide"]) == 2


def test_no_institutions_returns_no_flags():
    assert run_quality_checks([]) == []


def test_quality_checks_never_raise(institutions):
    # Les anomalies sont informatives : la fonction ne doit jamais lever
    # d'exception, quel que soit l'état des données (cf. CDC section 5.4).
    try:
        run_quality_checks(institutions)
    except Exception as exc:  # pragma: no cover
        pytest.fail(f"run_quality_checks a levé une exception : {exc}")
