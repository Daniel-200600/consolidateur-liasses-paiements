"""
tests/test_consolidation.py

Phase 3 : le moteur de consolidation doit retrouver exactement les valeurs de
référence validées manuellement (cf. Cahier des charges, section 9) à partir
des deux fichiers BanqueA + OperateurB.
"""

from pathlib import Path

import pytest

from core.consolidation import consolidate_all
from core.parsing import Institution, parse_workbook

FIXTURES = Path(__file__).parent / "fixtures_fictives"


@pytest.fixture
def institutions():
    banque_a = Institution(name="BanqueA", file_name="BanqueA.xlsx", sheets=parse_workbook(FIXTURES / "BanqueA.xlsx"))
    operateur_b = Institution(name="OperateurB", file_name="OperateurB.xlsx", sheets=parse_workbook(FIXTURES / "OperateurB.xlsx"))
    return [banque_a, operateur_b]


def test_all_11_sheets_consolidated(institutions):
    totals = consolidate_all(institutions)
    assert len(totals) == 11


def test_mobile_money_totals(institutions):
    totals = consolidate_all(institutions)
    grid = totals["Mobile Money1"].grid
    # Ligne 7 (index 6) = porteurs totaux ; colonne M (index 12, déc-2025).
    assert grid[6][12] == 1232671  # BanqueA=0 (onglet non renseigné) + OperateurB=1232671
    assert grid[7][12] == 359593  # porteurs actifs
    # Colonne S (index 18, juin-2026) = encours de monnaie électronique.
    assert grid[5][18] == 14621281997


def test_cartes_totals(institutions):
    totals = consolidate_all(institutions)
    grid = totals["Cartes1"].grid
    assert grid[2][1] == 11386    # clients : BanqueA=11386 + OperateurB=0 (onglet non renseigné)
    assert grid[3][1] == 29374   # comptes
    assert grid[9][1] == 21298   # cartes de débit


def test_cartes5_retrait_gab(institutions):
    totals = consolidate_all(institutions)
    grid = totals["Cartes 5"].grid
    # Section "TRANSACTIONS DE VOS PORTEURS", ligne "Retrait GAB" = ligne 11
    # (index 10) ; colonnes B (nombre, index 1) et C (valeur, index 2).
    assert grid[10][1] == 142872
    assert grid[10][2] == 14942539230


def test_empty_sheets_have_no_real_totals(institutions):
    # chèques&VIR, Transfert d'argent et PrêtsCredits ne sont renseignés par
    # aucun des deux établissements : le total doit rester à 0/None partout,
    # jamais planter.
    totals = consolidate_all(institutions)
    grid = totals["chèques&VIR"].grid
    numeric_values = {v for row in grid for v in row if isinstance(v, (int, float))}
    assert numeric_values <= {0}


def test_labels_are_preserved(institutions):
    totals = consolidate_all(institutions)
    grid = totals["Cartes1"].grid
    assert "client" in str(grid[2][0]).lower()


def test_single_institution_still_works():
    # La consolidation doit aussi fonctionner avec un seul établissement
    # chargé (cas d'usage réel : les remises arrivent progressivement).
    operateur_b = Institution(name="OperateurB", file_name="OperateurB.xlsx", sheets=parse_workbook(FIXTURES / "OperateurB.xlsx"))
    totals = consolidate_all([operateur_b])
    assert totals["Mobile Money1"].grid[6][12] == 1232671


def test_three_institutions_sum_correctly():
    # Vérifie que la somme se comporte correctement au-delà de 2 établissements
    # (OperateurB chargé deux fois = doublement du total, cas synthétique de contrôle).
    operateur_b1 = Institution(name="OperateurB1", file_name="OperateurB.xlsx", sheets=parse_workbook(FIXTURES / "OperateurB.xlsx"))
    operateur_b2 = Institution(name="OperateurB2", file_name="OperateurB.xlsx", sheets=parse_workbook(FIXTURES / "OperateurB.xlsx"))
    banque_a = Institution(name="BanqueA", file_name="BanqueA.xlsx", sheets=parse_workbook(FIXTURES / "BanqueA.xlsx"))
    totals = consolidate_all([operateur_b1, operateur_b2, banque_a])
    assert totals["Mobile Money1"].grid[6][12] == 1232671 * 2
    assert totals["Cartes1"].grid[2][1] == 11386
