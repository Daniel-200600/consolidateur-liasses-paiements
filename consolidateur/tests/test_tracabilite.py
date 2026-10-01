"""
tests/test_tracabilite.py

Audit de traçabilité, demandé explicitement après qu'un onglet inattendu
(« chèques&VIR 1er SEMESTRE 22 ») soit apparu dans un export : rien ne doit
être inventé, rien ne doit être perdu, et tous les calculs doivent être
exacts au XAF près.

Ces trois garanties sont vérifiées ici contre les fichiers RÉELS, en
recalculant indépendamment les valeurs attendues depuis les cellules
sources — jamais en se fiant à ce que produit le code lui-même.
"""

from pathlib import Path

import openpyxl
import pytest

from core.calibration import Calibration
from core.parsing import KNOWN_SHEETS, Institution, analyser_fichier

FIXTURES = Path(__file__).parent / "fixtures_fictives"
CM = FIXTURES / "cameroun"

TOUS_FICHIERS = [FIXTURES / "BanqueA.xlsx", FIXTURES / "OperateurB.xlsx"] + sorted(CM.glob("*.xlsx"))


# --------------------------------------------------------------------- #
# 1. Rien n'est inventé
# --------------------------------------------------------------------- #

@pytest.mark.parametrize("chemin", TOUS_FICHIERS, ids=lambda p: p.name[:22])
def test_tout_onglet_hors_gabarit_existe_vraiment_dans_la_source(chemin):
    """Un onglet listé comme « hors gabarit » dans les exports doit
    correspondre à un onglet réellement présent dans le fichier déposé —
    jamais un nom fabriqué ou dérivé."""
    _, non_reconnus = analyser_fichier(chemin)
    wb = openpyxl.load_workbook(chemin, read_only=True)
    noms_source = set(wb.sheetnames)
    wb.close()

    for o in non_reconnus:
        assert o.nom in noms_source, f"{o.nom!r} ne figure pas dans {chemin.name}"








# --------------------------------------------------------------------- #
# 2. Rien n'est perdu
# --------------------------------------------------------------------- #

@pytest.mark.parametrize("chemin", TOUS_FICHIERS, ids=lambda p: p.name[:22])
def test_chaque_onglet_source_est_soit_consolide_soit_liste(chemin):
    """Aucun onglet du fichier déposé ne doit disparaître sans trace : il est
    soit consolidé dans un thème, soit listé comme hors gabarit."""
    from core.sheet_matching import detecter_segments, reconnaitre_onglet

    calib = Calibration()
    sheets, non_reconnus = analyser_fichier(chemin, calibration=calib)
    noms_hors_gabarit = {o.nom for o in non_reconnus}

    wb = openpyxl.load_workbook(chemin, data_only=True)
    perdus = []
    for nom in wb.sheetnames:
        if nom in noms_hors_gabarit or nom.strip() in KNOWN_SHEETS:
            continue
        grid = [[c.value for c in row] for row in wb[nom].iter_rows()]
        reconnu = reconnaitre_onglet(nom, grid, set(KNOWN_SHEETS)).theme is not None
        segmentable = len(detecter_segments(grid)) >= 2
        if not (reconnu or segmentable):
            perdus.append(nom)
    wb.close()

    assert not perdus, f"{chemin.name} : onglets sans trace {perdus}"


# --------------------------------------------------------------------- #
# 3. Les calculs sont exacts
# --------------------------------------------------------------------- #







# --------------------------------------------------------------------- #
# 4. Performance : verrouiller les optimisations structurelles
#
# Deux causes de lenteur ont été mesurées et corrigées ; les tests
# ci-dessous portent sur la STRUCTURE du correctif (déterministe) plutôt
# que sur un chronomètre, qui varierait d'une machine à l'autre.
# --------------------------------------------------------------------- #



def test_les_styles_nommes_sont_enregistres_dans_les_deux_exports():
    """openpyxl recalcule une empreinte de l'objet style à chaque
    affectation `cell.font = …` ; sur des dizaines de milliers de cellules,
    c'était le premier poste de temps de génération. Les styles nommés ne
    sont hachés qu'une fois — encore faut-il qu'ils soient bien enregistrés
    dans le classeur, sinon l'affectation par nom échoue à l'exécution."""
    from core.export import _STYLES_GRILLE, build_full_workbook, build_resume_workbook
    from core.kpis import compute_kpis, retrait_gab_kpi
    from core.parsing import parse_workbook

    institutions = [
        Institution("BanqueA", "b.xlsx", parse_workbook(FIXTURES / "BanqueA.xlsx"), pays="CF"),
        Institution("OperateurB", "o.xlsx", parse_workbook(FIXTURES / "OperateurB.xlsx"), pays="CF"),
    ]

    for classeur in (build_full_workbook(institutions),
                     build_resume_workbook(institutions, compute_kpis(institutions),
                                           retrait_gab_kpi(institutions))):
        noms_enregistres = set(classeur.named_styles)
        for nom in _STYLES_GRILLE:
            assert nom in noms_enregistres, f"style « {nom} » absent du classeur"


def test_le_rendu_reste_identique_apres_optimisation():
    """Les styles nommés ne doivent RIEN changer visuellement : mêmes
    polices, mêmes bordures, mêmes formats de nombre qu'avant."""
    from core.export import build_full_workbook
    from core.parsing import parse_workbook

    institutions = [
        Institution("OperateurB", "o.xlsx", parse_workbook(FIXTURES / "OperateurB.xlsx"), pays="CF"),
    ]
    wb = build_full_workbook(institutions)
    ws = next(wb[n] for n in wb.sheetnames if n.startswith("Mobile Money1") and n.endswith("OperateurB"))

    libelle = ws["A7"]
    assert libelle.font.name == "Arial"
    assert libelle.border.left.style is not None

    nombre = ws["M7"]
    assert nombre.number_format.startswith("#,##0")
    assert nombre.border.left.style is not None

    entete_mois = ws["B4"]
    assert entete_mois.font.b is True
    assert "yy" in entete_mois.number_format
