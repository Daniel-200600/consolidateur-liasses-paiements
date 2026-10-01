"""
tests/test_generalisation.py

Le système ne doit jamais être figé sur les fichiers déjà rencontrés
(BanqueA, OperateurB, et les 8 fichiers du Cameroun) : ces tests le vérifient
contre des fichiers **entièrement synthétiques**, construits ici même,
avec des noms d'onglet, d'établissement et de libellés jamais vus
ailleurs dans le code ou les fixtures.

Trois garanties attendues :
- une structure inédite mais conforme à l'esprit du gabarit est reconnue
  (avec la prudence attendue — piste faible, pas un forçage) ;
- un contenu réellement étranger au gabarit n'est jamais consolidé à tort,
  mais reste visible ;
- rien ne plante sur des cas limites (0 établissement, établissement vide,
  mélange hétéroclite de sources).
"""

from pathlib import Path

import openpyxl
import pytest

from core.calibration import Calibration
from core.export import build_full_workbook, build_resume_workbook
from core.kpis import compute_kpis, retrait_gab_kpi
from core.montant_total import montant_total_argent
from core.parsing import Institution, analyser_fichier


@pytest.fixture(scope="module")
def fichier_carte_inedit(tmp_path_factory):
    """Un établissement, des noms d'onglet et des libellés jamais vus nulle
    part ailleurs dans le code — seule la STRUCTURE (succession de lignes)
    ressemble au thème Cartes1 du gabarit officiel."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("CARTE_1")
    ws["A1"] = "RAPPORT CARTES BANCAIRES - BANQUE TEST FICTIVE SA"
    ws["A2"] = "Nom de la banque : BANQUE TEST FICTIVE SA"
    ws["A3"], ws["B3"] = "Nombre de clients :", 55555
    ws["A4"], ws["B4"] = "Nombre de comptes :", 66666
    ws["A6"], ws["B6"] = "Type de cartes", "Nombre de cartes"
    ws["A7"], ws["B7"] = "Cartes de crédit", 100
    ws["A8"], ws["B8"] = "Cartes de débit différé", 200
    ws["A9"], ws["B9"] = "Cartes de débit", 12345
    ws["A10"], ws["B10"] = "Cartes prépayées", 0
    ws["A11"], ws["B11"] = "TOTAL", 12645

    chemin = tmp_path_factory.mktemp("generalisation") / "fichier_inedit.xlsx"
    wb.save(chemin)
    return chemin


@pytest.fixture(scope="module")
def fichier_theme_etranger(tmp_path_factory):
    """Un contenu qui n'a RIEN à voir avec le gabarit BEAC — aucun thème
    ne doit jamais s'y accrocher, quel que soit le seuil de confiance."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("Assurance emprunteur")
    ws["A1"] = "STATISTIQUES ASSURANCE EMPRUNTEUR 2025"
    ws["A2"], ws["B2"] = "Nombre de contrats souscrits", 4200
    ws["A3"], ws["B3"] = "Primes collectées (XAF)", 89000000

    chemin = tmp_path_factory.mktemp("generalisation") / "fichier_etranger.xlsx"
    wb.save(chemin)
    return chemin


# --------------------------------------------------------------------- #
# Une structure inédite mais conforme à l'esprit du gabarit est reconnue,
# avec la prudence attendue.
# --------------------------------------------------------------------- #

def test_structure_inedite_recoit_une_piste_pas_un_forcage(fichier_carte_inedit):
    """Aucun nom connu (ni établissement, ni onglet) : seule la structure
    doit guider la reconnaissance, et rester une PROPOSITION vérifiable —
    jamais une consolidation automatique sur un cas jamais vu."""
    sheets, non_reconnus = analyser_fichier(fichier_carte_inedit)
    assert sheets == {}  # rien consolidé sans validation
    assert len(non_reconnus) == 1
    o = non_reconnus[0]
    assert o.suggestion == "Cartes1"
    assert 0 < o.taux_suggestion < 0.8  # une piste, pas une certitude


def test_extraction_exacte_sur_structure_jamais_vue(fichier_carte_inedit):
    """Une fois la piste validée, les valeurs extraites de cette structure
    100% inédite doivent être exactes au chiffre près — la généralisation
    ne vaut que si les calculs qui en découlent sont fiables."""
    calib = Calibration()
    calib.valider("CARTE_1", "Cartes1")
    sheets, _ = analyser_fichier(fichier_carte_inedit, calibration=calib)
    grid = sheets["Cartes1"].grid

    assert grid[2][1] == 55555   # clients
    assert grid[3][1] == 66666   # comptes
    assert grid[7][1] == 100     # crédit
    assert grid[8][1] == 200     # débit différé
    assert grid[9][1] == 12345   # débit
    assert grid[10][1] == 0      # prépayées
    assert grid[11][1] == 12645  # TOTAL


# --------------------------------------------------------------------- #
# Un contenu réellement étranger n'est jamais consolidé à tort.
# --------------------------------------------------------------------- #

def test_theme_etranger_nest_jamais_rattache(fichier_theme_etranger):
    sheets, non_reconnus = analyser_fichier(fichier_theme_etranger)
    assert sheets == {}
    assert len(non_reconnus) == 1
    o = non_reconnus[0]
    assert o.theme_propose is None
    assert o.suggestion is None  # aucune ressemblance, même faible


def test_theme_etranger_reste_visible_dans_les_deux_exports(fichier_theme_etranger):
    """Rien à voir avec le gabarit ne veut pas dire invisible : l'onglet
    doit tout de même apparaître dans le fichier complet et dans le résumé."""
    s, nr = analyser_fichier(fichier_theme_etranger)
    inst = Institution("AssureurTest", "fichier_etranger.xlsx", s, nr, pays="GA")

    wb = build_full_workbook([inst])
    assert any("Assurance emprunteur" in n for n in wb.sheetnames)

    ws_resume = build_resume_workbook([inst], compute_kpis([inst]), retrait_gab_kpi([inst]))["Résumé"]
    textes = {str(c.value) for row in ws_resume.iter_rows() for c in row if c.value}
    assert any("Assurance emprunteur" in t for t in textes)


# --------------------------------------------------------------------- #
# Rien ne plante sur des cas limites ou des mélanges hétéroclites.
# --------------------------------------------------------------------- #

def test_zero_etablissement_ne_plante_jamais():
    assert montant_total_argent([]) == 0
    wb = build_full_workbook([])
    assert wb.sheetnames == ["Sommaire"]


def test_etablissement_sans_aucun_onglet_reconnu_ne_plante_jamais():
    inst = Institution("Vide", "vide.xlsx", {})
    assert montant_total_argent([inst]) == 0
    assert len(compute_kpis([inst])) > 0  # ne plante pas, renvoie des zéros


def test_melange_heteroclite_fichier_reel_et_fichiers_synthetiques(
        fichier_carte_inedit, fichier_theme_etranger):
    """Le cas le plus exigeant : un vrai fichier BEAC, un fichier
    synthétique partiellement reconnaissable, et un fichier totalement
    étranger, consolidés ensemble sans qu'aucun ne perturbe les autres."""
    from core.parsing import parse_workbook
    FIXTURES = Path(__file__).parent / "fixtures_fictives"

    s_carte, nr_carte = analyser_fichier(fichier_carte_inedit)
    s_etranger, nr_etranger = analyser_fichier(fichier_theme_etranger)

    insts = [
        Institution("BanqueA", "BanqueA_CA.xlsx", parse_workbook(FIXTURES / "BanqueA.xlsx"), pays="CF"),
        Institution("BanqueTest", "fichier_inedit.xlsx", s_carte, nr_carte, pays="TD"),
        Institution("AssureurTest", "fichier_etranger.xlsx", s_etranger, nr_etranger, pays="GA"),
    ]

    wb = build_full_workbook(insts)
    assert "Sommaire" in wb.sheetnames
    assert any("Assurance emprunteur" in n for n in wb.sheetnames)

    montant = montant_total_argent(insts)
    assert montant > 0  # BanqueA seul contribue déjà un montant réel
    # Les valeurs de BanqueA, garanties par tout le reste de la suite, ne
    # doivent pas être perturbées par la présence des fichiers synthétiques.
    from core.kpis import compute_kpis as ck
    clients = next(k.total for k in ck(insts) if k.key == "clients_cartes")
    assert clients >= 11386  # BanqueA seul + éventuellement BanqueTest (55555)
