"""
tests/test_display.py

Point 3 : l'aperçu des onglets déclenchait un avertissement de
sérialisation Arrow à chaque affichage (colonnes mélangeant libellés,
nombres et dates). On vérifie ici que toutes les grilles des fichiers de
référence sont désormais sérialisables sans erreur, et que le formatage
reste fidèle aux valeurs d'origine.
"""

import datetime
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pytest

from core.consolidation import consolidate_all
from core.display import format_cell, grid_to_display_df
from core.parsing import Institution, parse_workbook

FIXTURES = Path(__file__).parent / "fixtures_fictives"


@pytest.fixture
def institutions():
    banque_a = Institution(name="BanqueA", file_name="BanqueA.xlsx", sheets=parse_workbook(FIXTURES / "BanqueA.xlsx"))
    operateur_b = Institution(name="OperateurB", file_name="OperateurB.xlsx", sheets=parse_workbook(FIXTURES / "OperateurB.xlsx"))
    return [banque_a, operateur_b]


def test_all_reference_sheets_are_arrow_serializable(institutions):
    """Le test qui compte : AUCUNE grille des fichiers de référence ne doit
    déclencher d'erreur de sérialisation une fois formatée."""
    for inst in institutions:
        for sheet_name, sd in inst.sheets.items():
            df = grid_to_display_df(sd.grid)
            try:
                pa.Table.from_pandas(df)
            except Exception as exc:  # pragma: no cover
                pytest.fail(f"Sérialisation Arrow échouée pour {inst.name}/{sheet_name} : {exc}")


def test_consolidated_totals_are_arrow_serializable(institutions):
    totals = consolidate_all(institutions)
    for sheet_name, cs in totals.items():
        df = grid_to_display_df(cs.grid)
        try:
            pa.Table.from_pandas(df)
        except Exception as exc:  # pragma: no cover
            pytest.fail(f"Sérialisation Arrow échouée pour Total/{sheet_name} : {exc}")


def test_raw_grid_would_have_failed(institutions):
    """Contrôle que le problème existait bien : au moins une grille brute
    non formatée échoue effectivement à la sérialisation (sinon ce
    correctif n'aurait plus d'objet)."""
    failures = 0
    for inst in institutions:
        for sd in inst.sheets.values():
            try:
                pa.Table.from_pandas(pd.DataFrame(sd.grid))
            except Exception:
                failures += 1
    assert failures > 0


def test_format_cell_values():
    assert format_cell(None) == ""
    assert format_cell(1232671) == "1 232 671"
    assert format_cell(14942539230) == "14 942 539 230"
    assert format_cell("Cartes de débit") == "Cartes de débit"
    assert format_cell(datetime.datetime(2025, 12, 1)) == "déc-25"
    assert format_cell(0) == "0"
    assert format_cell(12.5) == "12,50"


def test_display_df_uses_excel_coordinates(institutions):
    """Les en-têtes doivent reprendre les lettres de colonnes Excel pour que
    l'utilisateur puisse relier une alerte qualité (ex. AB13) à l'aperçu."""
    sd = institutions[1].sheets["MobileMoney2"]
    df = grid_to_display_df(sd.grid)
    assert list(df.columns)[:3] == ["A", "B", "C"]
    assert "AB" in df.columns
    assert df.index[0] == "1"


def test_display_df_preserves_values(institutions):
    sd = institutions[0].sheets["Cartes1"]
    df = grid_to_display_df(sd.grid)
    # Cartes1 B3 = 11 386 clients (référence CDC section 9)
    assert df.loc["3", "B"] == "11 386"


def test_empty_grid_returns_empty_df():
    assert grid_to_display_df([]).empty
