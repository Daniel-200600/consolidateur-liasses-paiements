"""
tests/test_history.py

Phase 9 : régles de cadrage validées ici -
- la période est bien déduite du dernier mois Mobile Money commun ;
- l'enregistrement automatique met à jour la ligne existante d'une période
  déjà connue plutôt que de la dupliquer (indispensable puisque Streamlit
  relance le script à chaque interaction) ;
- l'historique accumule correctement plusieurs périodes distinctes ;
- les variations période à période sont justes.
"""

import datetime
from pathlib import Path

import pytest

from core.history import (
    build_snapshot_row, compute_deltas, determine_period, load_history, save_snapshot,
)
from core.kpis import compute_kpis, retrait_gab_kpi
from core.parsing import Institution, parse_workbook

FIXTURES = Path(__file__).parent / "fixtures_fictives"


@pytest.fixture
def institutions():
    banque_a = Institution(name="BanqueA", file_name="BanqueA.xlsx", sheets=parse_workbook(FIXTURES / "BanqueA.xlsx"))
    operateur_b = Institution(name="OperateurB", file_name="OperateurB.xlsx", sheets=parse_workbook(FIXTURES / "OperateurB.xlsx"))
    return [banque_a, operateur_b]


def test_determine_period_from_mobile_money_data(institutions):
    kpis = compute_kpis(institutions)
    period = determine_period(institutions, kpis)
    assert period == datetime.date(2025, 12, 1)  # dernier mois commun = déc-2025 (cf. CDC section 9)


def test_determine_period_falls_back_to_today_without_mobile_money():
    banque_a = Institution(name="BanqueA", file_name="BanqueA.xlsx", sheets=parse_workbook(FIXTURES / "BanqueA.xlsx"))
    kpis = compute_kpis([banque_a])  # BanqueA seul : aucune donnée Mobile Money réelle
    period = determine_period([banque_a], kpis)
    today = datetime.date.today()
    assert period == datetime.date(today.year, today.month, 1)


def test_build_snapshot_row_values(institutions):
    kpis = compute_kpis(institutions)
    gab = retrait_gab_kpi(institutions)
    row = build_snapshot_row(institutions, kpis, gab)
    assert row["periode"] == "déc-25"
    assert row["porteurs_mm_actifs"] == 359593
    assert row["cartes_debit"] == 21298
    assert row["gab_valeur"] == 14942539230
    assert "BanqueA" in row["etablissements"] and "OperateurB" in row["etablissements"]


def test_save_and_reload_snapshot(institutions, tmp_path):
    path = tmp_path / "historique.csv"
    kpis = compute_kpis(institutions)
    gab = retrait_gab_kpi(institutions)
    row = build_snapshot_row(institutions, kpis, gab)

    save_snapshot(row, path)
    df = load_history(path)

    assert len(df) == 1
    assert df.loc[0, "porteurs_mm_actifs"] == 359593


def test_rerun_on_same_period_updates_instead_of_duplicating(institutions, tmp_path):
    # Simule ce qui se passe réellement : Streamlit relance le script à
    # chaque interaction, donc save_snapshot est appelée plusieurs fois de
    # suite pour la MÊME période. Elle ne doit jamais créer de doublon.
    path = tmp_path / "historique.csv"
    kpis = compute_kpis(institutions)
    gab = retrait_gab_kpi(institutions)
    row = build_snapshot_row(institutions, kpis, gab)

    save_snapshot(row, path)
    save_snapshot(row, path)
    save_snapshot(row, path)
    df = load_history(path)

    assert len(df) == 1


def test_history_accumulates_distinct_periods(tmp_path):
    path = tmp_path / "historique.csv"
    row_nov = {
        "periode_date": "2025-11-01", "periode": "nov-25", "date_enregistrement": "2025-11-30T10:00:00",
        "etablissements": "BanqueA, OperateurB", "porteurs_mm_total": 700000, "porteurs_mm_actifs": 300000,
        "encours_me": 9000000000, "clients_cartes": 9000, "comptes_cartes": 25000, "cartes_debit": 15000,
        "gab_nombre": 85000, "gab_valeur": 11000000000,
    }
    row_dec = {
        "periode_date": "2025-12-01", "periode": "déc-25", "date_enregistrement": "2025-12-31T10:00:00",
        "etablissements": "BanqueA, OperateurB", "porteurs_mm_total": 1232671, "porteurs_mm_actifs": 359593,
        "encours_me": 14621281997, "clients_cartes": 11386, "comptes_cartes": 29374, "cartes_debit": 21298,
        "gab_nombre": 142872, "gab_valeur": 14942539230,
    }
    save_snapshot(row_nov, path)
    save_snapshot(row_dec, path)
    df = load_history(path)

    assert len(df) == 2
    assert list(df["periode"]) == ["nov-25", "déc-25"]  # ordre chronologique, pas alphabétique


def test_compute_deltas_between_consecutive_periods(tmp_path):
    path = tmp_path / "historique.csv"
    row_nov = {
        "periode_date": "2025-11-01", "periode": "nov-25", "date_enregistrement": "x",
        "etablissements": "BanqueA, OperateurB", "porteurs_mm_total": 700000, "porteurs_mm_actifs": 300000,
        "encours_me": 9000000000, "clients_cartes": 9000, "comptes_cartes": 25000, "cartes_debit": 15000,
        "gab_nombre": 85000, "gab_valeur": 11000000000,
    }
    row_dec = {
        "periode_date": "2025-12-01", "periode": "déc-25", "date_enregistrement": "y",
        "etablissements": "BanqueA, OperateurB", "porteurs_mm_total": 1232671, "porteurs_mm_actifs": 359593,
        "encours_me": 14621281997, "clients_cartes": 11386, "comptes_cartes": 29374, "cartes_debit": 21298,
        "gab_nombre": 142872, "gab_valeur": 14942539230,
    }
    save_snapshot(row_nov, path)
    df = save_snapshot(row_dec, path)

    deltas = compute_deltas(df, "2025-12-01")
    assert deltas["porteurs_mm_actifs"] == pytest.approx(359593 - 300000)
    assert deltas["cartes_debit"] == pytest.approx(21298 - 15000)

    # Pas de période antérieure pour novembre : delta = None pour tous les indicateurs.
    deltas_first = compute_deltas(df, "2025-11-01")
    assert all(v is None for v in deltas_first.values())


def test_compute_deltas_on_empty_history():
    import pandas as pd
    from core.history import HISTORY_COLUMNS
    empty = pd.DataFrame(columns=HISTORY_COLUMNS)
    deltas = compute_deltas(empty, "2025-12-01")
    assert all(v is None for v in deltas.values())
