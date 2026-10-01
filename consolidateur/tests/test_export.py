"""
tests/test_export.py

Phase 7 : les deux exports doivent (1) contenir les valeurs exactes de
reference et (2) s'ouvrir sans aucune erreur de formule (#REF!, #VALUE!...),
verifie par un recalcul LibreOffice reel - c'est le critere obligatoire du
Cahier des charges, section 5.6.
"""

from pathlib import Path

import openpyxl
import pytest

from core.export import build_full_workbook, build_resume_workbook, sanitize_sheet_name
from core.kpis import compute_kpis, retrait_gab_kpi
from core.parsing import Institution, parse_workbook
from libreoffice_recalc import recalculer

FIXTURES = Path(__file__).parent / "fixtures_fictives"


@pytest.fixture
def institutions():
    banque_a = Institution(name="BanqueA", file_name="BanqueA.xlsx", sheets=parse_workbook(FIXTURES / "BanqueA.xlsx"))
    operateur_b = Institution(name="OperateurB", file_name="OperateurB.xlsx", sheets=parse_workbook(FIXTURES / "OperateurB.xlsx"))
    return [banque_a, operateur_b]


def _recalc_check(path: Path) -> dict:
    """Recalcule le fichier avec LibreOffice et renvoie le rapport d'erreurs."""
    return recalculer(path)


# --------------------------------------------------------------------------- #
# Export "Résumé"
# --------------------------------------------------------------------------- #

def _index_labels(ws) -> dict:
    """Repère les lignes par leur libellé plutôt que par une position fixe :
    le résumé comporte désormais plusieurs blocs, et un ajout de bloc ne doit
    pas casser les tests."""
    return {ws.cell(row=r, column=1).value: r for r in range(1, ws.max_row + 1)}


def test_resume_workbook_values(institutions, tmp_path):
    kpis = compute_kpis(institutions)
    gab = retrait_gab_kpi(institutions)
    wb = build_resume_workbook(institutions, kpis, gab)

    out = tmp_path / "resume.xlsx"
    wb.save(out)

    report = _recalc_check(out)
    assert report["status"] == "success", report

    wb2 = openpyxl.load_workbook(out, data_only=True)
    ws = wb2["Résumé"]
    rows = _index_labels(ws)

    def total_kpi(label):
        # Bloc 1 : Indicateur | BanqueA | OperateurB | Total marché
        return ws.cell(row=rows[label], column=4).value

    assert total_kpi("Porteurs Mobile Money (total cumulé)") == 1232671
    assert total_kpi("Clients porteurs de cartes") == 11386
    assert total_kpi("Retraits GAB - valeur (XAF)") == 14942539230


def test_resume_contains_the_four_blocks(institutions, tmp_path):
    wb = build_resume_workbook(institutions, compute_kpis(institutions), retrait_gab_kpi(institutions))
    out = tmp_path / "blocs.xlsx"
    wb.save(out)
    _recalc_check(out)
    ws = openpyxl.load_workbook(out, data_only=True)["Résumé"]
    titres = [ws.cell(row=r, column=1).value for r in range(1, ws.max_row + 1)]
    titres = [t for t in titres if isinstance(t, str)]
    assert any(t.startswith("1 · INDICATEURS") for t in titres)
    assert any(t.startswith("2 · RÉCAPITULATIF PAR FEUILLE") for t in titres)
    assert any(t.startswith("3 · DÉTAIL DE TOUTES LES LIGNES") for t in titres)
    assert any(t.startswith("4 · POINTS DE VIGILANCE") for t in titres)


def test_resume_coverage_block_counts_every_sheet(institutions, tmp_path):
    """Le récapitulatif doit couvrir chaque feuille renseignée du gabarit et
    totaliser exactement les 249 lignes détectées, dont 45 renseignées."""
    wb = build_resume_workbook(institutions, compute_kpis(institutions), retrait_gab_kpi(institutions))
    out = tmp_path / "couverture.xlsx"
    wb.save(out)
    report = _recalc_check(out)
    assert report["status"] == "success", report

    ws = openpyxl.load_workbook(out, data_only=True)["Résumé"]
    rows = _index_labels(ws)

    for sheet in ("Mobile Money1", "MobileMoney2", "MobileMoney3", "Cartes1", "Cartes 2", "Cartes 5"):
        assert sheet in rows, f"{sheet} absent du récapitulatif"

    total_row = rows["TOTAL"]
    assert ws.cell(row=total_row, column=2).value == 280   # lignes prévues
    assert ws.cell(row=total_row, column=3).value == 45    # lignes renseignées
    # Le taux de remplissage est une formule, pas une valeur figée.
    taux = ws.cell(row=total_row, column=6).value
    assert taux is not None and 0 < taux < 1


def test_resume_detail_block_lists_filled_indicators(institutions, tmp_path):
    wb = build_resume_workbook(institutions, compute_kpis(institutions), retrait_gab_kpi(institutions))
    out = tmp_path / "detail.xlsx"
    wb.save(out)
    _recalc_check(out)
    ws = openpyxl.load_workbook(out, data_only=True)["Résumé"]

    # Le détail sectoriel Mobile Money doit apparaître nommément.
    libelles = [ws.cell(row=r, column=3).value for r in range(1, ws.max_row + 1)]
    libelles = [str(v) for v in libelles if v]
    assert any("Electricité" in v for v in libelles)
    assert any("Retrait GAB" in v for v in libelles)

    # Chaque ligne de détail porte le tableau d'origine.
    tableaux = [ws.cell(row=r, column=2).value for r in range(1, ws.max_row + 1)]
    assert any(isinstance(t, str) and "TRANSACTIONS DE VOS PORTEURS" in t for t in tableaux)


def test_resume_workbook_with_single_institution(tmp_path):
    operateur_b = Institution(name="OperateurB", file_name="OperateurB.xlsx", sheets=parse_workbook(FIXTURES / "OperateurB.xlsx"))
    kpis = compute_kpis([operateur_b])
    gab = retrait_gab_kpi([operateur_b])
    wb = build_resume_workbook([operateur_b], kpis, gab)
    out = tmp_path / "resume_single.xlsx"
    wb.save(out)
    report = _recalc_check(out)
    assert report["status"] == "success", report


def test_resume_workbook_with_no_institutions():
    wb = build_resume_workbook([], [], {"per_inst": [], "total": {"nombre": 0, "valeur": 0}})
    ws = wb["Résumé"]
    assert ws["A1"].value == "SYNTHÈSE MARCHÉ DES PAIEMENTS"


# --------------------------------------------------------------------------- #
# Export "Complet"
# --------------------------------------------------------------------------- #

def test_full_workbook_no_formula_errors(institutions, tmp_path):
    wb = build_full_workbook(institutions)
    out = tmp_path / "full.xlsx"
    wb.save(out)

    report = _recalc_check(out)
    assert report["status"] == "success", report
    assert report["total_errors"] == 0
    assert report["total_formulas"] > 1000  # cf. version validée précédemment (~1426)


def test_full_workbook_sheet_count(institutions):
    wb = build_full_workbook(institutions)
    # 11 onglets x (2 établissements + 1 Total) = 33, plus le Sommaire et le
    # Tableau de bord.
    assert len(wb.sheetnames) == 35
    assert "Sommaire" in wb.sheetnames


def test_row_numbers_match_the_source_file(institutions):
    """La mise en forme ne doit décaler aucune ligne.

    Un bandeau de titre inséré au-dessus de la grille décalerait les données
    de deux lignes alors que les formules des onglets Total référencent les
    adresses d'origine : les totaux deviendraient faux SANS qu'aucune erreur
    de formule ne soit signalée — le recalcul resterait vert. Ce test compare
    donc les positions exportées à celles du fichier source.
    """
    wb = build_full_workbook(institutions)
    operateur_b = next(i for i in institutions if i.name == "OperateurB")
    src = operateur_b.sheets["Mobile Money1"].grid
    sheet = next(n for n in wb.sheetnames if n.startswith("Mobile Money1") and n.endswith("OperateurB"))
    ws = wb[sheet]
    # Ligne 7 / colonne M du fichier source = grid[6][12]
    assert ws["M7"].value == src[6][12] == 1232671

    total = next(n for n in wb.sheetnames if n.startswith("Mobile Money1") and n.endswith("Total"))
    assert "M7" in wb[total]["M7"].value  # la formule vise bien la même ligne


def test_full_workbook_totals_match_reference(institutions, tmp_path):
    wb = build_full_workbook(institutions)
    out = tmp_path / "full2.xlsx"
    wb.save(out)
    _recalc_check(out)  # force le recalcul avant relecture

    wb2 = openpyxl.load_workbook(out, data_only=True)
    mm1_total = next(n for n in wb2.sheetnames if n.startswith("Mobile Money1") and n.endswith("Total"))
    cartes1_total = next(n for n in wb2.sheetnames if n.startswith("Cartes1") and n.endswith("Total"))

    assert wb2[mm1_total]["M7"].value == 1232671
    assert wb2[cartes1_total]["B3"].value == 11386


def test_full_workbook_source_error_is_not_reinjected_as_formula(institutions, tmp_path):
    # La cellule d'erreur source (MobileMoney2 AB13 chez OperateurB) doit devenir
    # un texte explicite, jamais une formule "=#VALUE!" recopiée telle quelle.
    wb = build_full_workbook(institutions)
    operateur_b_mm2 = next(n for n in wb.sheetnames if n.startswith("MobileMoney2") and n.endswith("OperateurB"))
    ws = wb[operateur_b_mm2]
    assert ws["AB13"].value == "Erreur de formule dans le fichier source (OperateurB)"
    assert not str(ws["AB13"].value).startswith("=")


def test_sanitize_sheet_name_handles_duplicates():
    used = set()
    n1 = sanitize_sheet_name("Transfert d'argent-Banque Régionale du Centre", used)
    n2 = sanitize_sheet_name("Transfert d'argent-Banque Régionale du Congo", used)
    assert len(n1) <= 31
    assert len(n2) <= 31
    assert n1 != n2  # la déduplication doit s'activer si la troncature crée un doublon


def test_full_workbook_with_three_institutions(tmp_path):
    operateur_b1 = Institution(name="OperateurB1", file_name="o.xlsx", sheets=parse_workbook(FIXTURES / "OperateurB.xlsx"))
    operateur_b2 = Institution(name="OperateurB2", file_name="o.xlsx", sheets=parse_workbook(FIXTURES / "OperateurB.xlsx"))
    banque_a = Institution(name="BanqueA", file_name="b.xlsx", sheets=parse_workbook(FIXTURES / "BanqueA.xlsx"))
    wb = build_full_workbook([operateur_b1, operateur_b2, banque_a])
    out = tmp_path / "full3.xlsx"
    wb.save(out)
    report = _recalc_check(out)
    assert report["status"] == "success", report

    wb2 = openpyxl.load_workbook(out, data_only=True)
    mm1_total = next(n for n in wb2.sheetnames if n.startswith("Mobile Money1") and n.endswith("Total"))
    assert wb2[mm1_total]["M7"].value == 1232671 * 2


def test_chaque_feuille_a_un_lien_vers_le_sommaire(institutions):
    """Navigation : avec plus de trente onglets, chaque feuille doit offrir
    un retour direct au sommaire."""
    wb = build_full_workbook(institutions)
    sans_lien = []
    for nom in wb.sheetnames:
        if nom == "Sommaire":
            continue
        ws = wb[nom]
        trouve = any(
            cell.hyperlink and "Sommaire" in str(cell.hyperlink.location)
            for row in ws.iter_rows() for cell in row
        )
        if not trouve:
            sans_lien.append(nom)
    assert not sans_lien, f"Feuilles sans lien de retour : {sans_lien}"


def test_le_lien_de_retour_ne_decale_aucune_ligne(institutions):
    """Le lien est posé dans une cellule libre de la première ligne, jamais
    par insertion : sans quoi les formules des onglets Total viseraient des
    lignes décalées et les totaux deviendraient faux en silence."""
    wb = build_full_workbook(institutions)
    operateur_b = next(i for i in institutions if i.name == "OperateurB")
    src = operateur_b.sheets["Mobile Money1"].grid

    feuille = next(n for n in wb.sheetnames
                   if n.startswith("Mobile Money1") and n.endswith("OperateurB"))
    ws = wb[feuille]
    assert ws["A1"].value == src[0][0]        # titre du gabarit conservé
    assert ws["M7"].value == src[6][12] == 1232671   # aucune ligne décalée


def test_le_lien_de_retour_necrase_aucune_donnee(institutions):
    """La cellule retenue doit avoir été vide dans le fichier source."""
    wb = build_full_workbook(institutions)
    for inst in institutions:
        for onglet, sd in inst.sheets.items():
            feuille = next((n for n in wb.sheetnames
                            if n.startswith(onglet[:20]) and n.endswith(inst.name)), None)
            if feuille is None or not sd.grid:
                continue
            ws = wb[feuille]
            for c in range(2, 6):
                cell = ws.cell(row=1, column=c)
                if cell.hyperlink:
                    source = sd.grid[0][c - 1] if c - 1 < len(sd.grid[0]) else None
                    assert source in (None, ""), (
                        f"{feuille} : le lien écrase « {source} » en ligne 1")
                    break


def _cible_du_lien(cellule) -> str:
    """Nom d'onglet visé par un lien interne, analysé COMME EXCEL.

    L'analyse doit être stricte : à l'intérieur des apostrophes délimitantes,
    une apostrophe littérale s'écrit doublée. Un analyseur permissif
    accepterait « 'Transfert d'argent-Total'!A1 » alors qu'Excel le rejette —
    et le test ne protégerait alors de rien.

    Renvoie "" si la référence est invalide.
    """
    emplacement = cellule.hyperlink.location or ""
    if not emplacement.startswith("'"):
        return emplacement.rsplit("!", 1)[0]

    nom = []
    i = 1
    while i < len(emplacement):
        car = emplacement[i]
        if car == "'":
            if i + 1 < len(emplacement) and emplacement[i + 1] == "'":
                nom.append("'")      # apostrophe littérale, correctement doublée
                i += 2
                continue
            i += 1
            break                     # fin du nom délimité
        nom.append(car)
        i += 1
    else:
        return ""                     # apostrophe fermante absente

    if not emplacement[i:].startswith("!"):
        return ""                     # ce qui suit le nom n'est pas une cellule
    return "".join(nom)


def test_tous_les_liens_visent_un_onglet_existant(institutions):
    """Un lien dont l'apostrophe n'est pas doublée fait afficher à Excel
    « La référence n'est pas valide » : « Transfert d'argent-Total » ferme la
    chaîne au mauvais endroit. Le contrôle porte donc sur la RÉSOLUTION du
    lien, pas sur la simple présence d'un mot dans son adresse."""
    wb = build_full_workbook(institutions)
    onglets = set(wb.sheetnames)
    casses = []
    for nom in wb.sheetnames:
        ws = wb[nom]
        for ligne in ws.iter_rows():
            for cellule in ligne:
                if cellule.hyperlink and cellule.hyperlink.location:
                    cible = _cible_du_lien(cellule)
                    if cible not in onglets:
                        casses.append((nom, cellule.coordinate, cellule.hyperlink.location))
    assert not casses, f"Liens vers un onglet inexistant : {casses[:5]}"


def test_apostrophe_du_nom_donglet_est_doublee(institutions):
    """Cas concret : l'onglet « Transfert d'argent-Total »."""
    wb = build_full_workbook(institutions)
    sommaire = wb["Sommaire"]
    liens = [c for ligne in sommaire.iter_rows() for c in ligne
             if c.hyperlink and "argent" in str(c.hyperlink.location)]
    assert liens, "Le lien vers Transfert d'argent est introuvable"
    assert "d''argent" in liens[0].hyperlink.location


def test_liens_valides_avec_des_noms_detablissement_longs():
    """Des noms longs sont tronqués à 31 caractères et suffixés en cas de
    doublon : les liens doivent rester résolvables après ces transformations."""
    institutions = [
        Institution(name="Liasse Stats Paiements 2025 (2) vf", file_name="a.xlsx",
                    sheets=parse_workbook(FIXTURES / "BanqueA.xlsx")),
        Institution(name="Liasse Stats Paiements 2026", file_name="b.xlsx",
                    sheets=parse_workbook(FIXTURES / "OperateurB.xlsx")),
    ]
    wb = build_full_workbook(institutions)
    onglets = set(wb.sheetnames)
    for nom in wb.sheetnames:
        for ligne in wb[nom].iter_rows():
            for cellule in ligne:
                if cellule.hyperlink and cellule.hyperlink.location:
                    assert _cible_du_lien(cellule) in onglets, (
                        f"{nom}!{cellule.coordinate} -> {cellule.hyperlink.location}")
