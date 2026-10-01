"""
tests/test_kpis.py

Phase 4 : les 8 indicateurs doivent retrouver exactement les valeurs de
référence validées (cf. Cahier des charges, section 9).
"""

from pathlib import Path

import pytest

from core.kpis import compute_kpis, retrait_gab_kpi
from core.parsing import Institution, parse_workbook

FIXTURES = Path(__file__).parent / "fixtures_fictives"

REFERENCE = {
    "porteurs_mm_total": 1232671,
    "porteurs_mm_actifs": 359593,
    "encours_me": 14621281997,
    "clients_cartes": 11386,
    "comptes_cartes": 29374,
    "cartes_debit": 21298,
}


@pytest.fixture
def institutions():
    banque_a = Institution(name="BanqueA", file_name="BanqueA.xlsx", sheets=parse_workbook(FIXTURES / "BanqueA.xlsx"))
    operateur_b = Institution(name="OperateurB", file_name="OperateurB.xlsx", sheets=parse_workbook(FIXTURES / "OperateurB.xlsx"))
    return [banque_a, operateur_b]


def test_all_six_kpis_match_reference(institutions):
    kpis = compute_kpis(institutions)
    assert len(kpis) == 6
    for k in kpis:
        assert k.total == REFERENCE[k.key], f"{k.key}: attendu {REFERENCE[k.key]}, obtenu {k.total}"


def test_kpi_split_by_institution(institutions):
    kpis = compute_kpis(institutions)
    porteurs = next(k for k in kpis if k.key == "porteurs_mm_total")
    per_inst = dict(porteurs.per_inst)
    assert per_inst["BanqueA"] == 0
    assert per_inst["OperateurB"] == 1232671

    cartes = next(k for k in kpis if k.key == "cartes_debit")
    per_inst2 = dict(cartes.per_inst)
    assert per_inst2["BanqueA"] == 21298
    assert per_inst2["OperateurB"] == 0


def test_retrait_gab(institutions):
    gab = retrait_gab_kpi(institutions)
    assert gab["total"]["nombre"] == 142872
    assert gab["total"]["valeur"] == 14942539230
    per_inst = {p["name"]: p for p in gab["per_inst"]}
    assert per_inst["BanqueA"]["nombre"] == 142872
    assert per_inst["OperateurB"]["nombre"] == 0


def test_cartes_debit_does_not_match_debit_differe(institutions):
    # Garde-fou : "Cartes de débit différé" ne doit jamais être confondue
    # avec "Cartes de débit" (cf. CDC section 6).
    kpis = compute_kpis(institutions)
    cartes_debit = next(k for k in kpis if k.key == "cartes_debit")
    assert cartes_debit.total == 21298  # et non une valeur incluant le différé


def test_kpis_work_with_single_institution():
    operateur_b = Institution(name="OperateurB", file_name="OperateurB.xlsx", sheets=parse_workbook(FIXTURES / "OperateurB.xlsx"))
    kpis = compute_kpis([operateur_b])
    porteurs = next(k for k in kpis if k.key == "porteurs_mm_total")
    assert porteurs.total == 1232671


def test_kpis_work_with_no_institutions():
    kpis = compute_kpis([])
    assert all(k.total == 0 for k in kpis)
