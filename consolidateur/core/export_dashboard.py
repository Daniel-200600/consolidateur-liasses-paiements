"""
core/export_dashboard.py

Feuille « Tableau de bord » du fichier complet : synthèse visuelle couvrant
TOUS les indicateurs détectés, sans sélection ni omission.

Principe directeur, identique au reste de l'export : le tableau de bord ne
recopie AUCUNE valeur. Chaque chiffre est une FORMULE qui pointe vers la
cellule correspondante d'un onglet « …-Total ». Si une donnée source change,
le tableau de bord se recalcule avec le reste du classeur.

Un premier essai retenait 8 indicateurs et 5 volumes choisis à la main.
Retenu à tort : le choix était arbitraire, et tout ce qui n'y figurait pas
restait invisible malgré une consolidation par ailleurs correcte. La feuille
reprend maintenant EXACTEMENT la même liste d'indicateurs que la section
« Tous les indicateurs » de l'application et que le bloc 3 du résumé —
y compris la cartographie validée par l'utilisateur, si elle existe, pour
qu'une ligne requalifiée en titre par le modèle local n'apparaisse pas ici
comme une donnée.
"""

from __future__ import annotations

import datetime

from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.hyperlink import Hyperlink

from core.export_style import (
    ALIGN_ENTETE, ALIGN_LIBELLE, ALIGN_NOMBRE, B_ENTETE, B_GRILLE, B_TOTAL,
    EMERAUDE, EMERAUDE_FONCE, FILL_ENTETE, FILL_RUBRIQUE, FILL_SOUS_SECTION,
    FILL_TOTAL, FMT_NOMBRE, F_DONNEE, F_ENTETE, F_LIBELLE, F_NOTE, F_RUBRIQUE,
    F_SOUS_SECTION, F_SOUS_TITRE, F_TITRE, F_TOTAL, couleur_onglet,
)
from core.indicators import analyze_layout, discover_indicators
from core.parsing import Institution, KNOWN_SHEETS

F_COMPTEUR_TITRE = Font(name="Arial", size=9, bold=True, color=EMERAUDE_FONCE)
F_COMPTEUR_VALEUR = Font(name="Arial", size=20, bold=True, color=EMERAUDE)
FILL_COMPTEUR = PatternFill("solid", fgColor="F3FAF6")


def _adresse_total(institutions: list[Institution], sheet: str, row: int,
                   mesure: str) -> str | None:
    """Adresse (ex. « S7 ») d'un indicateur dans l'onglet …-Total.

    L'onglet Total reproduit exactement la grille source : l'adresse y est
    donc la même que dans les fichiers d'origine. Pour un indicateur
    mensuel, on vise la dernière période où l'un des établissements a saisi
    une valeur, cohérent avec le reste de l'application ; à défaut de toute
    saisie, la dernière période du calendrier est retenue pour que la
    formule reste valide (et affiche 0).
    """
    presents = [i for i in institutions if sheet in i.sheets]
    if not presents:
        return None
    ref_grid = presents[0].sheets[sheet].grid
    if row >= len(ref_grid):
        return None
    layout = analyze_layout(ref_grid)

    if layout.is_monthly:
        derniere_col = None
        for _periode, mesures in layout.periods:
            col = mesures.get(mesure)
            if col is None:
                continue
            for inst in presents:
                grid = inst.sheets[sheet].grid
                if row < len(grid) and col < len(grid[row]):
                    v = grid[row][col]
                    if isinstance(v, (int, float)) and not isinstance(v, bool) and v != 0:
                        derniere_col = col
                        break
        if derniere_col is None and layout.periods:
            derniere_col = layout.periods[-1][1].get(mesure)
        if derniere_col is None:
            return None
        return f"{get_column_letter(derniere_col + 1)}{row + 1}"

    col = layout.row_measures.get(row, {}).get(mesure)
    if col is None:
        return None
    return f"{get_column_letter(col + 1)}{row + 1}"


def _formule_vers_total(total_name: str, adresse: str) -> str:
    from core.export import _escape_sheet_ref
    return f"=N('{_escape_sheet_ref(total_name)}'!{adresse})"


def ajouter_tableau_de_bord(wb, institutions: list[Institution],
                            noms_total: dict[str, str], cartographie=None,
                            indicateurs=None) -> None:
    """Ajoute la feuille de tableau de bord.

    `noms_total` associe chaque feuille du gabarit au nom de son onglet Total
    dans le classeur. `indicateurs`, si fourni, évite de relancer la
    découverte (déjà faite ailleurs dans build_full_workbook).
    """
    ws = wb.create_sheet("Tableau de bord", 0)
    ws.sheet_view.showGridLines = False

    ws.merge_cells("A1:F1")
    titre = ws.cell(row=1, column=1, value="TABLEAU DE BORD — MARCHÉ DES PAIEMENTS")
    titre.font, titre.fill, titre.alignment = F_TITRE, FILL_ENTETE, ALIGN_LIBELLE
    ws.row_dimensions[1].height = 26

    ws.merge_cells("A2:F2")
    ws.cell(row=2, column=1,
            value=f"{' + '.join(i.name for i in institutions)}  ·  "
                  f"généré le {datetime.date.today().strftime('%d/%m/%Y')}  ·  "
                  f"chaque valeur est une formule liée à l'onglet Total correspondant").font = F_SOUS_TITRE

    lien = ws.cell(row=3, column=1, value="◄ Retour au sommaire")
    lien.font = Font(name="Arial", size=9, color=EMERAUDE, underline="single")
    lien.alignment = ALIGN_LIBELLE
    lien.hyperlink = Hyperlink(ref="A3", location="'Sommaire'!A1")

    if indicateurs is None:
        indicateurs = discover_indicators(institutions, cartographie=cartographie)

    # -- Vue d'ensemble : compteurs STRUCTURELS, pas de sélection métier ---
    # Aucun indicateur n'est mis en avant plutôt qu'un autre : ces quatre
    # chiffres décrivent la couverture du gabarit, pas son contenu.
    n_feuilles = len({i.sheet for i in indicateurs} | set(KNOWN_SHEETS))
    n_couvertes = len([s for s in KNOWN_SHEETS if any(i.sheet == s for i in indicateurs)])
    n_total = len(indicateurs)
    n_renseignes = sum(1 for i in indicateurs if i.has_data)

    ws.cell(row=5, column=1, value="VUE D'ENSEMBLE").font = F_RUBRIQUE
    compteurs = [
        ("ÉTABLISSEMENTS", len(institutions), ""),
        ("FEUILLES DU GABARIT", f"{n_couvertes}/{len(KNOWN_SHEETS)}", "avec au moins une donnée"),
        ("INDICATEURS SUIVIS", n_total, "toutes lignes du gabarit"),
        ("DONT RENSEIGNÉS", n_renseignes, f"{n_renseignes / n_total * 100:.0f}% du gabarit" if n_total else ""),
    ]
    for idx, (libelle, valeur, sous) in enumerate(compteurs):
        col = 1 + idx * 2
        for dr in range(3):
            ws.cell(row=6 + dr, column=col).fill = FILL_COMPTEUR
            ws.cell(row=6 + dr, column=col + 1).fill = FILL_COMPTEUR
        h = ws.cell(row=6, column=col, value=libelle)
        h.font, h.fill, h.alignment = F_COMPTEUR_TITRE, FILL_COMPTEUR, ALIGN_LIBELLE
        v = ws.cell(row=7, column=col, value=valeur)
        v.font, v.fill, v.alignment = F_COMPTEUR_VALEUR, FILL_COMPTEUR, ALIGN_LIBELLE
        if isinstance(valeur, int):
            v.number_format = FMT_NOMBRE
        s = ws.cell(row=8, column=col, value=sous)
        s.font, s.fill, s.alignment = F_NOTE, FILL_COMPTEUR, ALIGN_LIBELLE

    # -- Détail EXHAUSTIF : une ligne par indicateur x mesure, sans exception --
    ligne = 10
    ws.cell(row=ligne, column=1, value="DÉTAIL COMPLET — TOUS LES INDICATEURS, PAR FEUILLE ET PAR TABLEAU").font = F_RUBRIQUE
    ligne += 1
    entete = ["Feuille", "Tableau d'origine", "Indicateur", "Mesure", "Total marché"]
    for c, texte in enumerate(entete, start=1):
        cell = ws.cell(row=ligne, column=c, value=texte)
        cell.font, cell.fill, cell.border, cell.alignment = F_ENTETE, FILL_ENTETE, B_ENTETE, ALIGN_ENTETE
    ligne_entete = ligne
    ligne += 1

    n_cols = 5
    for sheet in KNOWN_SHEETS:
        if sheet not in noms_total:
            continue
        lignes_feuille = [i for i in indicateurs if i.sheet == sheet]

        cell = ws.cell(row=ligne, column=1, value=sheet)
        cell.font, cell.fill, cell.border, cell.alignment = F_RUBRIQUE, FILL_RUBRIQUE, B_GRILLE, ALIGN_LIBELLE
        for c in range(2, n_cols + 1):
            c2 = ws.cell(row=ligne, column=c)
            c2.fill, c2.border = FILL_RUBRIQUE, B_GRILLE
        ligne += 1

        if not lignes_feuille:
            cell = ws.cell(row=ligne, column=2,
                           value="Grille libre : le gabarit ne prévoit aucune ligne prédéfinie.")
            cell.font, cell.border, cell.alignment = F_NOTE, B_GRILLE, ALIGN_LIBELLE
            ligne += 1
            continue

        rubrique_courante = object()
        for ind in lignes_feuille:
            if ind.rubric != rubrique_courante:
                rubrique_courante = ind.rubric
                cell = ws.cell(row=ligne, column=2, value=ind.rubric or "—")
                cell.font, cell.fill, cell.border, cell.alignment = (
                    F_SOUS_SECTION, FILL_SOUS_SECTION, B_GRILLE, ALIGN_LIBELLE)
                for c in [1, 3, 4, 5]:
                    c2 = ws.cell(row=ligne, column=c)
                    c2.fill, c2.border = FILL_SOUS_SECTION, B_GRILLE
                ligne += 1

            marqueur = "●" if ind.has_data else "○"
            for mesure in ind.measures:
                for col, texte in enumerate([sheet, ind.rubric or "—",
                                             f"{marqueur} {ind.display_name}",
                                             mesure or "Valeur"], start=1):
                    cell = ws.cell(row=ligne, column=col, value=texte)
                    cell.font, cell.border, cell.alignment = F_LIBELLE, B_GRILLE, ALIGN_LIBELLE

                adresse = _adresse_total(institutions, sheet, ind.row, mesure)
                valeur = _formule_vers_total(noms_total[sheet], adresse) if adresse else 0
                cell = ws.cell(row=ligne, column=5, value=valeur)
                cell.font, cell.border, cell.alignment = F_DONNEE, B_GRILLE, ALIGN_NOMBRE
                cell.number_format = FMT_NOMBRE
                ligne += 1

    derniere_ligne = ligne - 1
    ws.auto_filter.ref = f"A{ligne_entete}:{get_column_letter(n_cols)}{derniere_ligne}"
    ws.freeze_panes = f"A{ligne_entete + 1}"

    note = ws.cell(row=ligne + 1, column=1,
                   value="● ligne renseignée   ○ ligne prévue par le gabarit mais non renseignée   ·   "
                         "chaque valeur est une formule : elle se recalcule si une donnée source change   ·   "
                         "utilisez les flèches de filtre pour n'afficher qu'une feuille, un tableau, "
                         "ou que les lignes renseignées.")
    note.font = F_NOTE

    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 34
    ws.column_dimensions["C"].width = 46
    ws.column_dimensions["D"].width = 14
    ws.column_dimensions["E"].width = 20

    couleur_onglet(ws, EMERAUDE)
    ws.sheet_view.tabSelected = True
    wb.active = wb.index(ws)
