"""
tests/test_missing_labels.py

Garde-fou contre l'évolution silencieuse du gabarit BEAC.

Scénario testé : la BEAC (ou une saisie non conforme) modifie le libellé
d'une ligne. Avant ce garde-fou, l'indicateur correspondant retombait à 0
sans aucune alerte, et ce 0 se propageait jusqu'au Total marché puis dans
les exports réglementaires. On vérifie ici que l'anomalie est bien détectée
et remontée, et qu'aucune fausse alerte n'est levée sur des fichiers sains.
"""

import shutil
from pathlib import Path

import openpyxl
import pytest

from core.kpis import compute_kpis, retrait_gab_kpi
from core.parsing import Institution, parse_workbook
from core.quality import check_missing_labels, run_quality_checks

FIXTURES = Path(__file__).parent / "fixtures_fictives"


@pytest.fixture
def institutions():
    banque_a = Institution(name="BanqueA", file_name="BanqueA.xlsx", sheets=parse_workbook(FIXTURES / "BanqueA.xlsx"))
    operateur_b = Institution(name="OperateurB", file_name="OperateurB.xlsx", sheets=parse_workbook(FIXTURES / "OperateurB.xlsx"))
    return [banque_a, operateur_b]


def _make_renamed_label_file(tmp_path: Path, sheet: str, cell: str, new_label: str, source="OperateurB.xlsx") -> Path:
    """Copie un fichier de référence en renommant un libellé, pour simuler
    une évolution du gabarit."""
    dest = tmp_path / f"modifie_{source}"
    shutil.copy(FIXTURES / source, dest)
    wb = openpyxl.load_workbook(dest)
    wb[sheet][cell] = new_label
    wb.save(dest)
    return dest


# --------------------------------------------------------------------------- #
# Pas de fausse alerte sur les fichiers de référence sains
# --------------------------------------------------------------------------- #

def test_no_false_positive_on_reference_files(institutions):
    kpis = compute_kpis(institutions)
    gab = retrait_gab_kpi(institutions)

    for k in kpis:
        assert k.missing_label_for == [], f"Fausse alerte sur {k.key} : {k.missing_label_for}"
    assert gab["missing_label_for"] == []
    assert check_missing_labels(kpis, gab) == []


def test_empty_sheet_is_not_flagged_as_missing_label(institutions):
    # BanqueA ne renseigne pas Mobile Money : c'est un cas NORMAL (déjà signalé
    # comme "onglet vide"), surtout pas une alerte de libellé introuvable.
    kpis = compute_kpis(institutions)
    porteurs = next(k for k in kpis if k.key == "porteurs_mm_actifs")
    assert "BanqueA" not in porteurs.missing_label_for


# --------------------------------------------------------------------------- #
# Détection réelle d'un libellé modifié
# --------------------------------------------------------------------------- #

def test_renamed_mobile_money_label_is_detected(tmp_path):
    # Ligne 8 de Mobile Money1 = "Nombre de porteurs de Mobile Money actifs".
    path = _make_renamed_label_file(
        tmp_path, "Mobile Money1", "A8", "Usagers actifs du portefeuille électronique",
    )
    inst = Institution(name="OperateurB", file_name=path.name, sheets=parse_workbook(path))
    kpis = compute_kpis([inst])

    porteurs = next(k for k in kpis if k.key == "porteurs_mm_actifs")
    assert porteurs.total == 0                      # la valeur retombe bien à 0...
    assert porteurs.missing_label_for == ["OperateurB"]  # ...mais l'anomalie est signalée

    flags = check_missing_labels(kpis)
    assert len(flags) == 1
    assert flags[0].kind == "libelle_introuvable"
    assert "Porteurs Mobile Money actifs" in flags[0].message
    assert "Mobile Money1" in flags[0].message


def test_renamed_cartes_label_is_detected(tmp_path):
    # Ligne 10 de Cartes1 = "Cartes de débit".
    path = _make_renamed_label_file(tmp_path, "Cartes1", "A10", "Cartes bancaires classiques", source="BanqueA.xlsx")
    inst = Institution(name="BanqueA", file_name=path.name, sheets=parse_workbook(path))
    kpis = compute_kpis([inst])

    cartes = next(k for k in kpis if k.key == "cartes_debit")
    assert cartes.total == 0
    assert cartes.missing_label_for == ["BanqueA"]


def test_renamed_retrait_gab_section_is_detected(tmp_path):
    # On casse le titre de la section "TRANSACTIONS DE VOS PORTEURS" (A10 de
    # Cartes 5), dont dépend la lecture contextuelle du Retrait GAB.
    path = _make_renamed_label_file(
        tmp_path, "Cartes 5", "A10", "OPERATIONS DE NOS CLIENTS", source="BanqueA.xlsx",
    )
    inst = Institution(name="BanqueA", file_name=path.name, sheets=parse_workbook(path))
    gab = retrait_gab_kpi([inst])

    assert gab["total"]["nombre"] == 0
    assert gab["missing_label_for"] == ["BanqueA"]

    flags = check_missing_labels([], gab)
    assert len(flags) == 1
    assert "Retrait GAB" in flags[0].message


def test_anomaly_surfaces_in_run_quality_checks(tmp_path):
    path = _make_renamed_label_file(
        tmp_path, "Mobile Money1", "A8", "Usagers actifs du portefeuille électronique",
    )
    inst = Institution(name="OperateurB", file_name=path.name, sheets=parse_workbook(path))
    kpis = compute_kpis([inst])
    gab = retrait_gab_kpi([inst])

    flags = run_quality_checks([inst], kpis, gab)
    kinds = {f.kind for f in flags}
    assert "libelle_introuvable" in kinds


def test_run_quality_checks_still_works_without_kpis(institutions):
    # Compatibilité ascendante : l'appel sans KPI reste valide.
    flags = run_quality_checks(institutions)
    assert all(f.kind != "libelle_introuvable" for f in flags)
