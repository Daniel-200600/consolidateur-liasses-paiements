"""
tests/test_charts.py

Phase 6 : vérifie les données préparées pour les deux graphiques du tableau
de bord, à partir des fichiers de référence.
"""

from pathlib import Path

import pytest

from core.charts import build_market_share_data, build_monthly_series
from core.kpis import KPI_DEFS, compute_kpis, retrait_gab_kpi
from core.parsing import Institution, parse_workbook

FIXTURES = Path(__file__).parent / "fixtures_fictives"


@pytest.fixture
def institutions():
    banque_a = Institution(name="BanqueA", file_name="BanqueA.xlsx", sheets=parse_workbook(FIXTURES / "BanqueA.xlsx"))
    operateur_b = Institution(name="OperateurB", file_name="OperateurB.xlsx", sheets=parse_workbook(FIXTURES / "OperateurB.xlsx"))
    return [banque_a, operateur_b]


def test_market_share_sums_to_100_when_total_nonzero(institutions):
    kpis = compute_kpis(institutions)
    gab = retrait_gab_kpi(institutions)
    df = build_market_share_data(kpis, gab, ["BanqueA", "OperateurB"])
    for _, row in df.iterrows():
        total_pct = row["BanqueA"] + row["OperateurB"]
        assert total_pct in (0.0, 100.0)  # 0 % si l'indicateur est nul partout, sinon 100 %


def test_market_share_operateur_b_monopoly_on_mobile_money(institutions):
    kpis = compute_kpis(institutions)
    gab = retrait_gab_kpi(institutions)
    df = build_market_share_data(kpis, gab, ["BanqueA", "OperateurB"])
    assert df.loc["Porteurs Mobile Money actifs", "OperateurB"] == 100.0
    assert df.loc["Porteurs Mobile Money actifs", "BanqueA"] == 0.0


def test_market_share_banque_a_monopoly_on_cartes(institutions):
    kpis = compute_kpis(institutions)
    gab = retrait_gab_kpi(institutions)
    df = build_market_share_data(kpis, gab, ["BanqueA", "OperateurB"])
    assert df.loc["Cartes de débit émises", "BanqueA"] == 100.0
    assert df.loc["Retraits GAB - nombre", "BanqueA"] == 100.0


def test_monthly_series_porteurs_actifs(institutions):
    matcher = KPI_DEFS[1]["matcher"]  # "porteurs de Mobile Money actifs"
    df = build_monthly_series(institutions, "Mobile Money1", matcher)
    assert len(df) >= 12  # au moins les 12 mois de 2025
    # décembre 2025 doit valoir 359 593 (référence CDC section 9)
    assert df.loc["déc-25", "OperateurB"] == 359593
    assert df.loc["déc-25", "BanqueA"] == 0
    # la série est bien triée chronologiquement (janvier avant décembre)
    assert list(df.index).index("janv-25") < list(df.index).index("déc-25")


def test_monthly_series_empty_when_no_dates():
    operateur_b = Institution(name="OperateurB", file_name="OperateurB.xlsx", sheets=parse_workbook(FIXTURES / "OperateurB.xlsx"))
    df = build_monthly_series([operateur_b], "Cartes1", lambda l: "client" in l)
    assert df.empty  # Cartes1 n'a pas d'en-têtes de mois
