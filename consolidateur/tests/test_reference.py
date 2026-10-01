"""
tests/test_reference.py

Jeu de test de référence (Cahier des charges, section 9) : les fichiers BanqueA
et OperateurB RCA déjà validés servent de fixtures pour tout le développement.

Phase 2 : on vérifie uniquement que le parsing est correct (onglets reconnus,
structure des grilles, détection des erreurs de formule connues). Les
assertions sur les indicateurs eux-mêmes arriveront en Phase 4.
"""

from pathlib import Path

import pytest

from core.parsing import KNOWN_SHEETS, parse_workbook

FIXTURES = Path(__file__).parent / "fixtures_fictives"


@pytest.fixture
def banque_a_sheets():
    return parse_workbook(FIXTURES / "BanqueA.xlsx", "BanqueA.xlsx")


@pytest.fixture
def operateur_b_sheets():
    return parse_workbook(FIXTURES / "OperateurB.xlsx", "OperateurB.xlsx")


def test_all_known_sheets_found(banque_a_sheets, operateur_b_sheets):
    # Le gabarit BEAC est strictement identique d'un établissement à l'autre :
    # les 11 onglets connus doivent être présents dans les deux fichiers.
    assert set(banque_a_sheets.keys()) == set(KNOWN_SHEETS)
    assert set(operateur_b_sheets.keys()) == set(KNOWN_SHEETS)


def test_grid_is_non_empty(banque_a_sheets):
    for name in KNOWN_SHEETS:
        assert len(banque_a_sheets[name].grid) > 0, f"Onglet {name} vide côté BanqueA"


def test_known_banque_a_values(banque_a_sheets):
    # Valeurs connues (cf. CDC section 9) : Cartes1, ligne 3 = "Nobre de
    # clients", colonne B (index 1) = 11 386.
    grid = banque_a_sheets["Cartes1"].grid
    assert grid[2][1] == 11386
    assert grid[3][1] == 29374  # Nombre de comptes
    assert grid[9][1] == 21298  # Cartes de débit


def test_known_operateur_b_values(operateur_b_sheets):
    # Mobile Money1, ligne 7 (index 6) = porteurs totaux, colonne M (index 12,
    # décembre 2025) = 1 232 671 (cf. CDC section 9).
    grid = operateur_b_sheets["Mobile Money1"].grid
    assert grid[6][12] == 1232671
    assert grid[7][12] == 359593  # porteurs actifs


def test_known_formula_errors_detected(operateur_b_sheets):
    # 3 cellules en erreur de formule connues dans MobileMoney2 (CDC section 6
    # / rapport de contrôle qualité, colonne AB, lignes 13/17/25).
    errors = operateur_b_sheets["MobileMoney2"].errors
    error_addrs = {e["addr"] for e in errors}
    assert {"AB13", "AB17", "AB25"}.issubset(error_addrs)
    assert len(errors) == 3


def test_unreadable_file_does_not_crash(tmp_path):
    bad_file = tmp_path / "not_an_xlsx.xlsx"
    bad_file.write_text("ceci n'est pas un classeur Excel")
    with pytest.raises(Exception):
        parse_workbook(bad_file, "not_an_xlsx.xlsx")
    # Le test documente que parse_workbook lève une exception normale
    # (et non un crash silencieux) : c'est app.py qui l'intercepte (cf. app.py
    # `_add_files`) pour ne jamais interrompre l'application.
