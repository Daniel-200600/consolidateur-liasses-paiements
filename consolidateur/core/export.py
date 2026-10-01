"""
core/export.py

Phase 7 du Cahier des charges : exports Excel.

Deux exports, tous deux avec des formules natives (recalcul automatique à
l'ouverture dans Excel) :

- build_resume_workbook : un seul onglet "Résumé", les indicateurs clés en
  lignes, un établissement par colonne + une colonne "Total marché" calculée
  par une formule SUM sur la même ligne.
- build_full_workbook : un sommaire cliquable, puis pour chaque onglet connu
  du gabarit un onglet par établissement (valeurs recopiées telles quelles,
  erreurs de formule source remplacées par un message explicite) + un onglet
  "Total" dont chaque cellule numérique est une formule additionnant les
  onglets établissements correspondants (fonction N(), qui traite une cellule
  vide ou texte comme 0).

La mise en forme (couleurs, bordures, largeurs) est définie dans
core/export_style.py et suit le thème de l'application.
"""

from __future__ import annotations

import datetime
import re


from openpyxl import Workbook
from openpyxl.styles import NamedStyle
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.hyperlink import Hyperlink

from core.export_style import (
    F_LIEN_SOMMAIRE, ALIGN_ENTETE, ALIGN_LIBELLE, ALIGN_NOMBRE, AMBRE, B_ENTETE, B_GRILLE, B_TOTAL,
    CREME, EMERAUDE, FILL_ENTETE, FILL_RUBRIQUE, FILL_SOUS_SECTION, FILL_TITRE,
    FILL_TOTAL, FMT_MOIS, FMT_NOMBRE, F_DONNEE, F_ENTETE, F_ERREUR, F_LIBELLE,
    F_LIEN, F_NOTE, F_RUBRIQUE, F_SOUS_SECTION, F_SOUS_TITRE, F_TITRE, F_TOTAL,
    OR, OR_PAYS, ajuster_largeurs, couleur_onglet,
)
from core.export_dashboard import ajouter_tableau_de_bord
from core.indicators import analyze_layout, discover_indicators, extraire_notes, indicator_totals
from core.pays import NOM_PAYS
from core.kpis import KpiResult, compute_kpis, retrait_gab_kpi
from core.montant_total import _COMPOSANTES, _anomalie_mensuelle, detail_montant_total, montant_total_argent
from core.sheet_matching import rapprocher_onglets_non_reconnus
from core.parsing import KNOWN_SHEETS, Institution
from core.quality import run_quality_checks

def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_date(v) -> bool:
    return isinstance(v, (datetime.datetime, datetime.date))


def _escape_sheet_ref(name: str) -> str:
    """Un nom d'onglet contenant une apostrophe doit la voir doublée dans une
    référence de formule Excel ('Transfert d''argent-BanqueA'!A1)."""
    return name.replace("'", "''")


def sanitize_sheet_name(name: str, used: set[str]) -> str:
    base = re.sub(r"[\[\]:*?/\\]", "", str(name)).strip() or "Feuille"
    candidate = base[:31]
    i = 2
    while candidate.lower() in used:
        suffix = f"~{i}"
        candidate = base[: 31 - len(suffix)] + suffix
        i += 1
    used.add(candidate.lower())
    return candidate


# --------------------------------------------------------------------------- #
# Mise en forme d'un onglet reprenant la structure du gabarit
# --------------------------------------------------------------------------- #

_STYLES_GRILLE: dict[str, dict] = {
    "cg_rub_lib": dict(font=F_RUBRIQUE, fill=FILL_RUBRIQUE, border=B_GRILLE, alignment=ALIGN_LIBELLE),
    "cg_rub_num": dict(font=F_RUBRIQUE, fill=FILL_RUBRIQUE, border=B_GRILLE, alignment=ALIGN_NOMBRE),
    "cg_sec_lib": dict(font=F_SOUS_SECTION, fill=FILL_SOUS_SECTION, border=B_GRILLE, alignment=ALIGN_LIBELLE),
    "cg_sec_num": dict(font=F_SOUS_SECTION, fill=FILL_SOUS_SECTION, border=B_GRILLE, alignment=ALIGN_NOMBRE),
    "cg_libelle": dict(font=F_LIBELLE, border=B_GRILLE, alignment=ALIGN_LIBELLE),
    "cg_mois": dict(font=F_ENTETE, fill=FILL_ENTETE, border=B_GRILLE, alignment=ALIGN_ENTETE,
                    number_format=FMT_MOIS),
    "cg_erreur": dict(font=F_ERREUR, border=B_GRILLE, alignment=ALIGN_LIBELLE),
    "cg_mesure": dict(font=F_ENTETE, fill=FILL_ENTETE, border=B_GRILLE, alignment=ALIGN_ENTETE),
    "cg_texte": dict(font=F_DONNEE, border=B_GRILLE, alignment=ALIGN_ENTETE),
    "cg_nombre": dict(font=F_DONNEE, border=B_GRILLE, alignment=ALIGN_NOMBRE,
                      number_format=FMT_NOMBRE),
    # Bloc de détail du résumé : plusieurs centaines de lignes x une colonne
    # par établissement, soit le deuxième poste de temps de génération.
    "rs_libelle": dict(font=F_LIBELLE, border=B_GRILLE, alignment=ALIGN_LIBELLE),
    "rs_donnee": dict(font=F_DONNEE, border=B_GRILLE, alignment=ALIGN_NOMBRE,
                      number_format=FMT_NOMBRE),
    "rs_total": dict(font=F_TOTAL, border=B_TOTAL, alignment=ALIGN_NOMBRE,
                     fill=FILL_TOTAL, number_format=FMT_NOMBRE),
}


def _enregistrer_styles_grille(wb) -> None:
    """Enregistre une fois pour toutes les styles de grille dans le classeur.

    openpyxl recalcule une empreinte de l'objet style à CHAQUE affectation
    (`cell.font = …`), ce qui, sur un classeur de plusieurs dizaines de
    milliers de cellules, devient le premier poste de temps de génération —
    mesuré à plus de 20 secondes cumulées sur un cas réel. Un style nommé
    n'est haché qu'une fois : la cellule ne porte plus qu'une référence.
    """
    if getattr(wb, "_styles_grille_prets", False):
        return
    for nom, spec in _STYLES_GRILLE.items():
        style = NamedStyle(name=nom)
        for attribut, valeur in spec.items():
            setattr(style, attribut, valeur)
        wb.add_named_style(style)
    wb._styles_grille_prets = True


def _styler_grille(ws, grid: list[list], layout, n_rows: int, n_cols: int) -> None:
    """Applique la charte à un onglet qui reproduit un tableau du gabarit.

    Les titres de tableau et les sous-sections détectés par
    core.indicators.analyze_layout sont mis en valeur, et la grille de données
    reçoit un tracé complet — c'est ce qui manquait le plus aux exports
    précédents, où toutes les lignes se ressemblaient.
    """
    _enregistrer_styles_grille(ws.parent)

    rubriques = set()
    sous_sections = set()
    vus_rubrique, vus_section = "", ""
    for r in range(n_rows):
        rub = layout.row_rubrics.get(r, "")
        sec = layout.row_sections.get(r, "")
        label = grid[r][0] if r < len(grid) and grid[r] and isinstance(grid[r][0], str) else ""
        label = label.strip()
        if label and rub and rub == label and rub != vus_rubrique:
            rubriques.add(r)
            vus_rubrique = rub
        elif label and sec and sec == label and sec != vus_section:
            sous_sections.add(r)
            vus_section = sec

    for r in range(1, n_rows + 1):
        idx = r - 1
        est_rubrique = idx in rubriques
        est_section = idx in sous_sections
        for c in range(1, n_cols + 1):
            cell = ws.cell(row=r, column=c)
            if est_rubrique:
                cell.style = "cg_rub_lib" if c == 1 else "cg_rub_num"
                continue
            if est_section:
                cell.style = "cg_sec_lib" if c == 1 else "cg_sec_num"
                continue

            v = cell.value
            if c == 1:
                cell.style = "cg_libelle"
            elif _is_date(v):
                cell.style = "cg_mois"
            elif isinstance(v, str) and v.startswith("Erreur de formule"):
                cell.style = "cg_erreur"
            elif isinstance(v, str):
                cell.style = "cg_mesure" if v.strip().lower() in ("nombre", "valeur", "montant") else "cg_texte"
            else:
                cell.style = "cg_nombre"

    ws.freeze_panes = "B1"
    ajuster_largeurs(ws, largeur_libelle=48, largeur_donnee=15, max_col=n_cols)


NOM_SOMMAIRE = "Sommaire"


def _lien_retour_sommaire(ws, n_cols: int) -> None:
    """Pose un lien « Retour au sommaire » sur le bandeau de titre.

    Le lien est placé dans une cellule LIBRE de la première ligne — jamais
    inséré. Ajouter une ligne décalerait toute la grille alors que les
    formules des onglets Total référencent les adresses d'origine : les
    totaux deviendraient faux sans qu'aucune erreur ne soit signalée.

    Dans les gabarits reçus, seule la colonne A de la première ligne porte un
    intitulé ; le lien se pose donc en B1, immédiatement visible. Si cette
    cellule venait à être occupée, la première colonne libre est retenue.
    """
    colonne = None
    for c in range(2, max(n_cols, 2) + 2):
        if ws.cell(row=1, column=c).value in (None, ""):
            colonne = c
            break
    if colonne is None:
        return

    cell = ws.cell(row=1, column=colonne, value="◄ Retour au sommaire")
    cell.font = F_LIEN_SOMMAIRE
    cell.alignment = ALIGN_LIBELLE
    cell.hyperlink = Hyperlink(
        ref=cell.coordinate,
        location=f"'{_escape_sheet_ref(NOM_SOMMAIRE)}'!A1",
    )


def _habiller_titre(ws, n_cols: int) -> None:
    """Met en valeur la ligne de titre DÉJÀ présente dans le gabarit.

    Aucune ligne n'est insérée : la numérotation des lignes reste rigoureusement
    identique à celle de la liasse d'origine, ce qui permet de comparer cellule
    à cellule avec le fichier source. (Un bandeau inséré au-dessus décalerait
    la grille de deux lignes, alors que les formules des onglets Total
    référencent les adresses d'origine : les totaux deviendraient faux sans
    qu'aucune erreur de formule ne soit signalée.)
    """
    for c in range(1, max(n_cols, 1) + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill = FILL_TITRE
        cell.font = F_TITRE
        cell.border = B_ENTETE
    ws.row_dimensions[1].height = 22


def _analyse_qualitative_pays(theme: str, code_pays: str, institutions_theme: list[Institution],
                               institutions_pays_total: list[Institution]) -> list[str]:
    """Texte d'analyse qualitative pour un onglet Total par pays : quel
    établissement domine ce thème dans ce pays, quelle part des
    établissements du pays le renseignent, et si une anomalie y a été
    détectée — un résumé complet plutôt qu'un simple empilement de
    chiffres, demandé explicitement par l'utilisateur.

    La « dominance » se mesure par la somme de toutes les valeurs
    numériques de l'onglet de l'établissement pour ce thème : une mesure
    volontairement générique (fonctionne identiquement sur les 11 thèmes,
    aux structures très différentes) plutôt qu'une règle métier par thème,
    qui aurait multiplié les cas particuliers à maintenir.
    """
    contributions = []
    for inst in institutions_theme:
        sd = inst.sheets.get(theme)
        if not sd:
            continue
        total = sum(v for row in sd.grid for v in row
                   if isinstance(v, (int, float)) and not isinstance(v, bool))
        contributions.append((inst.name, total))
    contributions.sort(key=lambda x: -x[1])

    lignes = []
    somme_generale = sum(c[1] for c in contributions)
    if contributions and somme_generale > 0:
        nom_dom, val_dom = contributions[0]
        part = val_dom / somme_generale * 100
        lignes.append(f"Établissement dominant sur ce thème : {nom_dom} ({part:.0f} % de "
                      f"l'activité cumulée des établissements de ce pays sur ce thème).")
        if len(contributions) > 1 and part < 40:
            lignes.append("Activité répartie entre plusieurs établissements, sans dominance nette.")
    else:
        lignes.append("Aucune activité chiffrée renseignée sur ce thème pour ce pays.")

    n_theme = len(institutions_theme)
    n_pays = len(institutions_pays_total)
    lignes.append(f"Couverture : {n_theme} établissement(s) sur {n_pays} chargé(s) pour ce pays "
                  f"renseignent ce thème.")
    if n_theme < n_pays:
        manquants = sorted(i.name for i in institutions_pays_total
                          if i.name not in {c[0] for c in contributions} and theme not in i.sheets)
        if manquants:
            lignes.append(f"N'ont pas renseigné ce thème : {', '.join(manquants)}.")

    composantes_theme = [c for c in _COMPOSANTES if c.sheet == theme]
    etabs_avec_anomalie = sorted({
        inst.name for inst in institutions_theme for comp in composantes_theme
        if _anomalie_mensuelle([inst], comp.sheet, comp.ligne_tete, comp.mesure)
        or any(_anomalie_mensuelle([inst], comp.sheet, r, comp.mesure) for r in comp.lignes_repli)
        or any(_anomalie_mensuelle([inst], comp.sheet, r, comp.mesure) for r in comp.lignes_repli_profond)
    })
    if etabs_avec_anomalie:
        lignes.append(f"⚠️ Saut mensuel invraisemblable détecté chez : "
                      f"{', '.join(etabs_avec_anomalie)} — à vérifier dans le fichier source.")
    else:
        lignes.append("Aucune anomalie mensuelle détectée sur ce thème pour ce pays.")

    return lignes


def _ecrire_analyse_qualitative(ws, lignes: list[str], ligne_depart: int, n_cols: int) -> None:
    r = ligne_depart
    titre = ws.cell(row=r, column=1, value="ANALYSE QUALITATIVE")
    titre.font, titre.fill = F_SOUS_TITRE, FILL_TITRE
    for c in range(2, n_cols + 1):
        ws.cell(row=r, column=c).fill = FILL_TITRE
    r += 2
    for ligne in lignes:
        cell = ws.cell(row=r, column=1, value=ligne)
        cell.font = F_ERREUR if ligne.startswith("⚠️") else F_LIBELLE
        cell.alignment = ALIGN_LIBELLE
        r += 1


def _construire_onglet_total(wb: Workbook, tmpl: str, institutions_subset: list[Institution],
                             inst_sheet_names: dict[str, str], nom_onglet: str,
                             couleur: str, analyse_qualitative: list[str] | None = None) -> None:
    """Crée un onglet Total (formules de sommation) pour un sous-ensemble
    d'établissements donné — le même mécanisme sert au total CEMAC (tous les
    établissements) et à chaque total pays (les établissements de ce seul
    pays) : dans les deux cas, ce sont de vraies formules Excel, jamais des
    valeurs recopiées."""
    ref_grid = institutions_subset[0].sheets[tmpl].grid
    max_rows = max(len(inst.sheets[tmpl].grid) for inst in institutions_subset)
    max_cols = max((len(row) for inst in institutions_subset for row in inst.sheets[tmpl].grid), default=0)
    ws_t = wb.create_sheet(nom_onglet)

    for r in range(max_rows):
        for c in range(max_cols):
            values = []
            for inst in institutions_subset:
                grid = inst.sheets[tmpl].grid
                v = grid[r][c] if r < len(grid) and c < len(grid[r]) else None
                values.append(v)

            has_date = any(_is_date(v) for v in values)
            has_number = any(_is_number(v) for v in values)
            has_string = any(isinstance(v, str) and v for v in values)

            if has_date:
                ws_t.cell(row=r + 1, column=c + 1, value=next(v for v in values if _is_date(v)))
            elif has_number:
                addr = f"{get_column_letter(c + 1)}{r + 1}"
                parts = [f"N('{_escape_sheet_ref(inst_sheet_names[inst.name])}'!{addr})"
                        for inst in institutions_subset]
                ws_t.cell(row=r + 1, column=c + 1, value="=" + "+".join(parts))
            elif has_string:
                ws_t.cell(row=r + 1, column=c + 1,
                          value=next(v for v in values if isinstance(v, str) and v))

    _styler_grille(ws_t, ref_grid, analyze_layout(ref_grid), max_rows, max_cols)
    for r in range(1, max_rows + 1):
        for c in range(2, max_cols + 1):
            cell = ws_t.cell(row=r, column=c)
            if isinstance(cell.value, str) and cell.value.startswith("="):
                cell.style = "rs_total"
    _habiller_titre(ws_t, max_cols)
    _lien_retour_sommaire(ws_t, max_cols)
    couleur_onglet(ws_t, couleur)

    if analyse_qualitative:
        _ecrire_analyse_qualitative(ws_t, analyse_qualitative, max_rows + 3, max_cols)


def build_full_workbook(institutions: list[Institution], cartographie=None) -> Workbook:
    wb = Workbook()
    wb.remove(wb.active)
    used: set[str] = set()
    sommaire_entries: list[tuple[str, list[tuple[str, str]], str]] = []
    # {tmpl: {code_pays: nom_onglet_total_pays}} — pour le récapitulatif du
    # Sommaire.
    totaux_pays_entries: dict[str, list[tuple[str, str]]] = {}

    for tmpl in KNOWN_SHEETS:
        present = [inst for inst in institutions if tmpl in inst.sheets]
        if not present:
            continue

        inst_sheet_names: list[tuple[str, str]] = []
        noms_par_institution: dict[str, str] = {}
        for inst in present:
            sd = inst.sheets[tmpl]
            exported_name = sanitize_sheet_name(f"{tmpl[:20]}-{inst.name}", used)
            ws = wb.create_sheet(exported_name)
            err_map = {(e["row"], e["col"]): e["text"] for e in sd.errors}
            n_cols = 0
            for r, row in enumerate(sd.grid):
                n_cols = max(n_cols, len(row))
                for c, v in enumerate(row):
                    if (r, c) in err_map:
                        ws.cell(row=r + 1, column=c + 1,
                                value=f"Erreur de formule dans le fichier source ({inst.name})")
                    elif v is not None:
                        ws.cell(row=r + 1, column=c + 1, value=v)
            layout = analyze_layout(sd.grid)
            _styler_grille(ws, sd.grid, layout, len(sd.grid), n_cols)
            _habiller_titre(ws, n_cols)
            _lien_retour_sommaire(ws, n_cols)
            couleur_onglet(ws, EMERAUDE)
            inst_sheet_names.append((inst.name, exported_name))
            noms_par_institution[inst.name] = exported_name

        # --- Un onglet Total par PAYS (formules), avant le total CEMAC -----
        #
        # Chaque pays représenté sur ce thème obtient son propre total,
        # additionnant uniquement SES établissements — un « visuel
        # individuel par pays », comme demandé, tout en gardant le total
        # CEMAC (tous pays confondus) inchangé juste après.
        par_pays: dict[str, list[Institution]] = {}
        for inst in present:
            if inst.pays:
                par_pays.setdefault(inst.pays, []).append(inst)

        for code_pays, insts_pays in par_pays.items():
            nom_total_pays = sanitize_sheet_name(f"{tmpl[:18]}-Total-{code_pays}", used)
            tous_etabs_pays = [i for i in institutions if i.pays == code_pays]
            analyse = _analyse_qualitative_pays(tmpl, code_pays, insts_pays, tous_etabs_pays)
            _construire_onglet_total(wb, tmpl, insts_pays, noms_par_institution,
                                     nom_total_pays, OR_PAYS, analyse_qualitative=analyse)
            totaux_pays_entries.setdefault(tmpl, []).append((code_pays, nom_total_pays))

        # --- Onglet Total CEMAC (tous les établissements, tous pays) -------
        total_name = sanitize_sheet_name(f"{tmpl[:24]}-Total", used)
        _construire_onglet_total(wb, tmpl, present, noms_par_institution, total_name, OR)

        sommaire_entries.append((tmpl, inst_sheet_names, total_name))

    # --- Onglets hors gabarit standard : jamais absents des documents -------
    #
    # Un onglet qu'aucun établissement ne partage avec un autre (mise en page
    # propre à une banque, thème composite non encore segmenté…) ne peut être
    # fusionné dans un thème commun — mais l'écarter des documents livrés
    # reviendrait à perdre une information réelle. Il est donc exporté
    # INDIVIDUELLEMENT, tel quel, avec ses propres erreurs de formule et
    # nombres en texte déjà récupérés comme n'importe quel autre onglet.
    hors_gabarit_entries: list[tuple[str, str, str]] = []  # (établissement, nom d'origine, nom exporté)
    for inst in institutions:
        for o in inst.non_reconnus:
            exported_name = sanitize_sheet_name(f"{o.nom[:20]}-{inst.name}", used)
            ws = wb.create_sheet(exported_name)
            err_map = {(e["row"], e["col"]): e["text"] for e in o.errors}
            n_cols = 0
            for r, row in enumerate(o.grid):
                n_cols = max(n_cols, len(row))
                for c, v in enumerate(row):
                    if (r, c) in err_map:
                        ws.cell(row=r + 1, column=c + 1,
                                value=f"Erreur de formule dans le fichier source ({inst.name})")
                    elif v is not None:
                        ws.cell(row=r + 1, column=c + 1, value=v)
            layout = analyze_layout(o.grid)
            _styler_grille(ws, o.grid, layout, len(o.grid), n_cols)
            _habiller_titre(ws, n_cols)
            _lien_retour_sommaire(ws, n_cols)

            note_texte = (f"Onglet propre à {inst.name}, hors des 11 thèmes standards du gabarit — "
                         f"non fusionné avec d'autres établissements.")
            if o.suggestion or o.theme_propose:
                piste = o.theme_propose or o.suggestion
                taux = o.taux_propose or o.taux_suggestion
                note_texte += f" Piste possible mais non validée : {piste} ({taux:.0%})."
            # Placée loin après la dernière colonne réellement utilisée,
            # jamais sur une cellule susceptible de porter du contenu source
            # (aucune ligne n'est insérée, contrairement au bandeau de
            # titre : ici rien ne référence ces onglets par position fixe,
            # mais la prudence reste la même).
            note = ws.cell(row=1, column=n_cols + 3, value=note_texte)
            note.font = F_NOTE

            couleur_onglet(ws, AMBRE)
            hors_gabarit_entries.append((inst.name, o.nom, exported_name))

    rapprochements = rapprocher_onglets_non_reconnus(institutions)
    _ajouter_sommaire(wb, institutions, sommaire_entries, hors_gabarit_entries,
                      totaux_pays_entries, rapprochements)
    # Ajouté en dernier : la feuille se place en tête du classeur et ses
    # formules pointent vers les onglets Total créés ci-dessus — d'où son
    # absence quand aucun thème du gabarit n'a été consolidé.
    if sommaire_entries:
        noms_total = {tmpl: total_name for tmpl, _, total_name in sommaire_entries}
        ajouter_tableau_de_bord(wb, institutions, noms_total, cartographie=cartographie)
    return wb


def _ajouter_sommaire(wb: Workbook, institutions: list[Institution],
                      entries: list[tuple[str, list[tuple[str, str]], str]],
                      hors_gabarit: list[tuple[str, str, str]] | None = None,
                      totaux_pays: dict[str, list[tuple[str, str]]] | None = None,
                      rapprochements: list[tuple[list[tuple[str, str]], float]] | None = None) -> None:
    """Page d'accueil : un lien cliquable vers chaque onglet du classeur.

    Sans elle, un classeur de plus de trente onglets est difficile à parcourir.
    """
    ws = wb.create_sheet(NOM_SOMMAIRE, 0)
    ws.sheet_view.showGridLines = False

    ws.cell(row=1, column=1, value="SYNTHÈSE MARCHÉ DES PAIEMENTS")
    ws.cell(row=1, column=1).font = F_TITRE
    for c in range(1, 5):
        ws.cell(row=1, column=c).fill = FILL_TITRE
    ws.row_dimensions[1].height = 24

    ws.cell(row=3, column=1,
            value=f"Généré le {datetime.date.today().strftime('%d/%m/%Y')}")
    ws.cell(row=3, column=1).font = F_SOUS_TITRE

    header = 5
    for c, titre in enumerate(["Thème du gabarit", "Onglets établissements", "Total marché"], start=1):
        cell = ws.cell(row=header, column=c, value=titre)
        cell.font = F_ENTETE
        cell.fill = FILL_ENTETE
        cell.border = B_ENTETE
        cell.alignment = ALIGN_ENTETE

    r = header + 1
    for tmpl, inst_sheets, total_name in entries:
        cell = ws.cell(row=r, column=1, value=tmpl)
        cell.font = F_RUBRIQUE
        cell.fill = FILL_RUBRIQUE
        cell.border = B_GRILLE
        cell.alignment = ALIGN_LIBELLE

        noms = ws.cell(row=r, column=2, value=", ".join(n for n, _ in inst_sheets))
        noms.font = F_LIBELLE
        noms.border = B_GRILLE
        noms.alignment = ALIGN_LIBELLE

        lien = ws.cell(row=r, column=3, value=total_name)
        lien.font = F_LIEN
        lien.border = B_GRILLE
        lien.alignment = ALIGN_LIBELLE
        # L'apostrophe doit être doublée, comme dans une formule : sans cela
        # « Transfert d'argent-Total » produit une référence qu'Excel refuse
        # (« La référence n'est pas valide »).
        lien.hyperlink = Hyperlink(
            ref=lien.coordinate,
            location=f"'{_escape_sheet_ref(total_name)}'!A1",
        )
        r += 1

    ws.cell(row=r + 1, column=1,
            value="Chaque thème comporte un onglet par établissement (onglets verts) "
                  "et un onglet Total (onglet doré) dont les cellules sont des formules.")
    ws.cell(row=r + 1, column=1).font = F_NOTE
    r += 3

    if totaux_pays:
        r = _entete_bloc(ws, r, "TOTAUX PAR PAYS (CEMAC)", 3)
        r = _ligne_entete(ws, r, ["Thème du gabarit", "Pays", "Accès"])
        for tmpl, entrees_pays in totaux_pays.items():
            for code_pays, nom_onglet in sorted(entrees_pays, key=lambda e: NOM_PAYS.get(e[0], e[0])):
                c1 = ws.cell(row=r, column=1, value=tmpl)
                c1.font, c1.border, c1.alignment = F_LIBELLE, B_GRILLE, ALIGN_LIBELLE
                c2 = ws.cell(row=r, column=2, value=NOM_PAYS.get(code_pays, code_pays))
                c2.font, c2.border, c2.alignment = F_LIBELLE, B_GRILLE, ALIGN_LIBELLE
                lien = ws.cell(row=r, column=3, value=nom_onglet)
                lien.font, lien.border, lien.alignment = F_LIEN, B_GRILLE, ALIGN_LIBELLE
                lien.hyperlink = Hyperlink(ref=lien.coordinate,
                                           location=f"'{_escape_sheet_ref(nom_onglet)}'!A1")
                r += 1
        note_pays = ws.cell(row=r + 1, column=1,
                            value="Un total par pays additionne uniquement les établissements de ce "
                                  "pays (onglets bruns), en plus du total CEMAC ci-dessus qui les "
                                  "additionne tous.")
        note_pays.font = F_NOTE
        r += 3

    if hors_gabarit:
        r = _entete_bloc(ws, r, "ONGLETS HORS GABARIT STANDARD (onglets ambrés)", 3)
        r = _ligne_entete(ws, r, ["Établissement", "Onglet d'origine", "Accès"])
        for nom_etab, nom_origine, nom_exporte in hors_gabarit:
            c1 = ws.cell(row=r, column=1, value=nom_etab)
            c1.font, c1.border, c1.alignment = F_LIBELLE, B_GRILLE, ALIGN_LIBELLE
            c2 = ws.cell(row=r, column=2, value=nom_origine)
            c2.font, c2.border, c2.alignment = F_LIBELLE, B_GRILLE, ALIGN_LIBELLE
            lien = ws.cell(row=r, column=3, value="Ouvrir")
            lien.font, lien.border, lien.alignment = F_LIEN, B_GRILLE, ALIGN_LIBELLE
            lien.hyperlink = Hyperlink(ref=lien.coordinate,
                                       location=f"'{_escape_sheet_ref(nom_exporte)}'!A1")
            r += 1
        note2 = ws.cell(row=r + 1, column=1,
                        value="Ces onglets n'appartiennent à aucun des 11 thèmes standards "
                              "(mise en page propre à l'établissement) : conservés tels quels, "
                              "individuellement, jamais fusionnés ni omis.")
        note2.font = F_NOTE
        r += 3

    if rapprochements:
        noms_exportes = {(etab, origine): exporte for etab, origine, exporte in (hors_gabarit or [])}
        r = _entete_bloc(ws, r, "RAPPROCHEMENTS POSSIBLES ENTRE ÉTABLISSEMENTS", 3)
        for membres, taux in rapprochements:
            titre_groupe = ws.cell(row=r, column=1,
                                   value=f"Ressemblance structurelle ~{taux:.0%} — à rapprocher :")
            titre_groupe.font = F_RUBRIQUE
            titre_groupe.fill = FILL_RUBRIQUE
            for col in range(2, 4):
                ws.cell(row=r, column=col).fill = FILL_RUBRIQUE
            r += 1
            for nom_etab, nom_origine in membres:
                c1 = ws.cell(row=r, column=1, value=nom_etab)
                c1.font, c1.border, c1.alignment = F_LIBELLE, B_GRILLE, ALIGN_LIBELLE
                c2 = ws.cell(row=r, column=2, value=nom_origine)
                c2.font, c2.border, c2.alignment = F_LIBELLE, B_GRILLE, ALIGN_LIBELLE
                nom_exporte = noms_exportes.get((nom_etab, nom_origine))
                if nom_exporte:
                    lien = ws.cell(row=r, column=3, value="Ouvrir")
                    lien.font, lien.border, lien.alignment = F_LIEN, B_GRILLE, ALIGN_LIBELLE
                    lien.hyperlink = Hyperlink(ref=lien.coordinate,
                                               location=f"'{_escape_sheet_ref(nom_exporte)}'!A1")
                else:
                    ws.cell(row=r, column=3).border = B_GRILLE
                r += 1
            r += 1
        note3 = ws.cell(row=r, column=1,
                        value="Des onglets structurellement proches, chez des établissements "
                              "différents, tous deux hors des 11 thèmes standards — signe possible "
                              "d'une pratique commune à examiner, jamais consolidés automatiquement "
                              "entre eux.")
        note3.font = F_NOTE

    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 34
    ws.column_dimensions["C"].width = 32
    couleur_onglet(ws, CREME)


# --------------------------------------------------------------------------- #
# Export « Résumé »
# --------------------------------------------------------------------------- #

def _bloc_titre(ws, institutions, derniere_col: int) -> int:
    ws["A1"] = "SYNTHÈSE MARCHÉ DES PAIEMENTS"
    ws["A1"].font = F_TITRE
    for col in range(1, derniere_col + 1):
        ws.cell(row=1, column=col).fill = FILL_TITRE
    ws.row_dimensions[1].height = 26

    ws["A3"] = f"Généré le {datetime.date.today().strftime('%d/%m/%Y')}"
    ws["A3"].font = F_SOUS_TITRE
    return 5


def _entete_bloc(ws, ligne: int, titre: str, derniere_col: int) -> int:
    """Titre de bloc, pour séparer nettement les sections du résumé."""
    cell = ws.cell(row=ligne, column=1, value=titre)
    cell.font = F_RUBRIQUE
    cell.alignment = ALIGN_LIBELLE
    for col in range(1, derniere_col + 1):
        c2 = ws.cell(row=ligne, column=col)
        c2.fill = FILL_RUBRIQUE
        c2.border = B_ENTETE
    ws.row_dimensions[ligne].height = 18
    return ligne + 1


def _ligne_entete(ws, ligne: int, titres: list[str]) -> int:
    for col, titre in enumerate(titres, start=1):
        cell = ws.cell(row=ligne, column=col, value=titre)
        cell.font, cell.fill, cell.border, cell.alignment = F_ENTETE, FILL_ENTETE, B_ENTETE, ALIGN_ENTETE
    return ligne + 1


def build_resume_workbook(institutions: list[Institution], kpis: list[KpiResult], gab: dict,
                          cartographie=None) -> Workbook:
    """Résumé détaillé, en quatre blocs nettement séparés :

    1. les indicateurs clés ;
    2. un récapitulatif de COUVERTURE feuille par feuille (combien de lignes
       le gabarit prévoit, combien sont renseignées, et par qui) ;
    3. le détail de toutes les lignes renseignées, regroupées par feuille et
       par tableau d'origine ;
    4. les points de vigilance relevés sur les fichiers sources.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Résumé"
    # Les styles nommés doivent être déclarés dans CE classeur : le résumé
    # n'appelle pas _styler_grille, qui s'en charge pour le fichier complet.
    _enregistrer_styles_grille(wb)
    ws.sheet_view.showGridLines = False

    n_inst = len(institutions)
    col_total = 4 + n_inst          # bloc 3 : Feuille | Tableau | Indicateur | Mesure | …
    # Le bloc 3 est le plus large : 4 libellés + un établissement par colonne
    # + le total marché. Les bandeaux et le filtre doivent couvrir jusque-là.
    derniere_col = max(col_total + 1, 4)

    r = _bloc_titre(ws, institutions, derniere_col)

    # ------------------------------------------------------------------ #
    # Bloc 1 — Indicateurs clés
    # ------------------------------------------------------------------ #
    r = _entete_bloc(ws, r, "1 · INDICATEURS CLÉS", derniere_col)
    col_total_kpi = 2 + n_inst
    r = _ligne_entete(ws, r, ["Indicateur"] + [i.name for i in institutions] + ["Total marché"])

    def _ligne_kpi(label: str, par_etab: dict):
        nonlocal r
        alterne = r % 2 == 0
        ws.cell(row=r, column=1, value=label).style = "rs_libelle"
        for i, inst in enumerate(institutions):
            cell = ws.cell(row=r, column=2 + i, value=par_etab.get(inst.name, 0))
            cell.style = "rs_donnee"
            if alterne:
                cell.fill = FILL_SOUS_SECTION
        formule = (f"=SUM({get_column_letter(2)}{r}:{get_column_letter(col_total_kpi - 1)}{r})"
                   if institutions else 0)
        ws.cell(row=r, column=col_total_kpi, value=formule).style = "rs_total"
        r += 1

    for k in kpis:
        _ligne_kpi(k.label, dict(k.per_inst))
    _ligne_kpi("Retraits GAB - nombre", {p["name"]: p["nombre"] for p in gab["per_inst"]})
    _ligne_kpi("Retraits GAB - valeur (XAF)", {p["name"]: p["valeur"] for p in gab["per_inst"]})

    # ------------------------------------------------------------------ #
    # Bloc 1bis — MONTANT TOTAL PAR PAYS (toutes activités confondues)
    #
    # Un tableau volontairement simple : les pays d'un côté, une seule
    # somme XAF de l'autre — plutôt qu'une grille détaillée croisant
    # plusieurs indicateurs, qui diluait la lecture. Le détail des
    # composantes de ce total (par activité) est repris juste en dessous,
    # pour que le chiffre reste vérifiable plutôt qu'une boîte noire.
    # ------------------------------------------------------------------ #
    pays_presents: dict[str, list[Institution]] = {}
    for inst in institutions:
        if inst.pays:
            pays_presents.setdefault(inst.pays, []).append(inst)

    if pays_presents:
        codes_pays = sorted(pays_presents.keys(), key=lambda c: NOM_PAYS.get(c, c))

        r += 1
        r = _entete_bloc(ws, r, "1bis · MONTANT TOTAL PAR PAYS (XAF, TOUTES ACTIVITÉS CONFONDUES)",
                         derniere_col)
        r = _ligne_entete(ws, r, ["Pays", "Montant total (XAF)"])

        for i, code in enumerate(codes_pays):
            montant = montant_total_argent(pays_presents[code])
            alterne = i % 2 == 0
            c1 = ws.cell(row=r, column=1, value=NOM_PAYS.get(code, code))
            c1.style = "rs_libelle"
            c2 = ws.cell(row=r, column=2, value=montant)
            c2.style = "rs_donnee"
            if alterne:
                c1.fill = c2.fill = FILL_SOUS_SECTION
            r += 1

        montant_cemac = montant_total_argent(institutions)
        c1 = ws.cell(row=r, column=1, value="CEMAC (total)")
        c1.style = "rs_total"
        c1.alignment = ALIGN_LIBELLE
        c2 = ws.cell(row=r, column=2, value=montant_cemac)
        c2.style = "rs_total"
        r += 2

        note_pays = ws.cell(row=r, column=1,
                            value="Additionne les principaux flux monétaires du gabarit (chèques, "
                                  "virements, transferts, Mobile Money, cartes) et l'encours de "
                                  "monnaie électronique, sans compter deux fois un même total et ses "
                                  "propres sous-totaux. Une composante au saut mensuel invraisemblable "
                                  "est exclue du total et signalée ci-dessous plutôt qu'intégrée "
                                  "silencieusement.")
        note_pays.font = F_NOTE
        r += 2

        r = _ligne_entete(ws, r, ["Composante du montant total", "CEMAC (XAF)"])
        for libelle, valeur, anomalie in detail_montant_total(institutions):
            c1 = ws.cell(row=r, column=1,
                        value=libelle + ("  ⚠️ saut invraisemblable — exclue du total" if anomalie else ""))
            c1.font, c1.border, c1.alignment = (F_ERREUR if anomalie else F_LIBELLE), B_GRILLE, ALIGN_LIBELLE
            c2 = ws.cell(row=r, column=2, value=valeur)
            c2.font, c2.border, c2.alignment = F_DONNEE, B_GRILLE, ALIGN_NOMBRE
            c2.number_format = FMT_NOMBRE
            r += 1
        r += 2

    # ------------------------------------------------------------------ #
    # Bloc 2 — Couverture feuille par feuille
    # ------------------------------------------------------------------ #
    r += 1
    r = _entete_bloc(ws, r, "2 · RÉCAPITULATIF PAR FEUILLE — COUVERTURE DU GABARIT", derniere_col)
    r = _ligne_entete(ws, r, ["Feuille du gabarit", "Lignes prévues", "Lignes renseignées"]
                      + [f"dont {i.name}" for i in institutions] + ["Taux de remplissage"])

    indicateurs = discover_indicators(institutions, cartographie=cartographie)
    premiere_ligne_couv = r
    for sheet in KNOWN_SHEETS:
        lignes = [i for i in indicateurs if i.sheet == sheet]
        # Aucune feuille n'est passée sous silence : celles dont le gabarit ne
        # prévoit aucune ligne prédéfinie (PrêtsCredits est une grille libre)
        # apparaissent avec un effectif nul, plutôt que de disparaître du
        # récapitulatif.
        renseignees = [i for i in lignes if i.has_data]
        cell = ws.cell(row=r, column=1, value=sheet)
        cell.font, cell.border, cell.alignment = F_LIBELLE, B_GRILLE, ALIGN_LIBELLE
        for col, valeur in ((2, len(lignes)), (3, len(renseignees))):
            cell = ws.cell(row=r, column=col, value=valeur)
            cell.font, cell.border, cell.alignment = F_DONNEE, B_GRILLE, ALIGN_NOMBRE
            cell.number_format = FMT_NOMBRE
        for i, inst in enumerate(institutions):
            n = sum(
                1 for ind in lignes
                if any(indicator_totals([inst], ind, m)[1] for m in ind.measures)
            )
            cell = ws.cell(row=r, column=4 + i, value=n)
            cell.font, cell.border, cell.alignment = F_DONNEE, B_GRILLE, ALIGN_NOMBRE
            cell.number_format = FMT_NOMBRE
        cell = ws.cell(row=r, column=4 + n_inst,
                       value=f"=IF(B{r}=0,0,C{r}/B{r})")
        cell.font, cell.border, cell.alignment = F_TOTAL, B_TOTAL, ALIGN_NOMBRE
        cell.fill, cell.number_format = FILL_TOTAL, "0.0%"
        r += 1

    cell = ws.cell(row=r, column=1, value="TOTAL")
    cell.font, cell.border, cell.alignment = F_TOTAL, B_TOTAL, ALIGN_LIBELLE
    cell.fill = FILL_TOTAL
    for col in range(2, 4 + n_inst):
        lettre = get_column_letter(col)
        cell = ws.cell(row=r, column=col, value=f"=SUM({lettre}{premiere_ligne_couv}:{lettre}{r - 1})")
        cell.font, cell.border, cell.alignment = F_TOTAL, B_TOTAL, ALIGN_NOMBRE
        cell.fill, cell.number_format = FILL_TOTAL, FMT_NOMBRE
    cell = ws.cell(row=r, column=4 + n_inst, value=f"=IF(B{r}=0,0,C{r}/B{r})")
    cell.font, cell.border, cell.alignment = F_TOTAL, B_TOTAL, ALIGN_NOMBRE
    cell.fill, cell.number_format = FILL_TOTAL, "0.0%"
    r += 1

    # ------------------------------------------------------------------ #
    # Bloc 3 — Détail de toutes les lignes renseignées
    # ------------------------------------------------------------------ #
    r += 1
    r = _entete_bloc(ws, r, "3 · DÉTAIL DE TOUTES LES LIGNES, PAR FEUILLE ET PAR TABLEAU", derniere_col)
    ligne_entete_detail = r
    r = _ligne_entete(ws, r, ["Feuille", "Tableau d'origine", "Indicateur", "Mesure"]
                      + [i.name for i in institutions] + ["Total marché"])

    # Restitution EXHAUSTIVE : chaque feuille du gabarit, chaque titre de
    # tableau qu'elle contient, et chaque ligne — renseignée (●) ou non (○).
    # Une ligne vide est en soi une information de reporting : elle indique
    # que l'établissement n'a rien déclaré sur ce poste.
    for sheet in KNOWN_SHEETS:
        lignes_feuille = [i for i in indicateurs if i.sheet == sheet]

        cell = ws.cell(row=r, column=1, value=sheet)
        cell.font, cell.fill, cell.border = F_RUBRIQUE, FILL_RUBRIQUE, B_GRILLE
        cell.alignment = ALIGN_LIBELLE
        for col in range(2, derniere_col + 1):
            c2 = ws.cell(row=r, column=col)
            c2.fill, c2.border = FILL_RUBRIQUE, B_GRILLE
        r += 1

        if not lignes_feuille:
            cell = ws.cell(row=r, column=2,
                           value="Grille libre : le gabarit ne prévoit aucune ligne prédéfinie "
                                 "(à remplir ligne par ligne par l'établissement).")
            cell.font, cell.border, cell.alignment = F_NOTE, B_GRILLE, ALIGN_LIBELLE
            r += 1
            continue

        rubrique_courante = object()  # sentinelle : force l'écriture du 1er titre
        for ind in lignes_feuille:
            if ind.rubric != rubrique_courante:
                rubrique_courante = ind.rubric
                cell = ws.cell(row=r, column=2, value=ind.rubric or "—")
                cell.font, cell.fill, cell.border = F_SOUS_SECTION, FILL_SOUS_SECTION, B_GRILLE
                cell.alignment = ALIGN_LIBELLE
                for col in list(range(3, derniere_col + 1)) + [1]:
                    c2 = ws.cell(row=r, column=col)
                    c2.fill, c2.border = FILL_SOUS_SECTION, B_GRILLE
                r += 1

            marqueur = "●" if ind.has_data else "○"
            for mesure in ind.measures:
                par_etab, total = indicator_totals(institutions, ind, mesure)
                # La feuille et le tableau sont répétés sur CHAQUE ligne : le
                # bloc dépasse 400 lignes, et une ligne doit rester
                # compréhensible seule, une fois le tableau trié ou filtré.
                for col, texte in enumerate([sheet, ind.rubric or "—",
                                             f"{marqueur} {ind.display_name}",
                                             mesure or "Valeur"], start=1):
                    ws.cell(row=r, column=col, value=texte).style = "rs_libelle"
                for i, (_, valeur) in enumerate(par_etab):
                    ws.cell(row=r, column=5 + i, value=valeur).style = "rs_donnee"
                formule = (f"=SUM({get_column_letter(5)}{r}:{get_column_letter(4 + n_inst)}{r})"
                           if institutions else 0)
                ws.cell(row=r, column=5 + n_inst, value=formule).style = "rs_total"
                r += 1

    derniere_ligne_detail = r - 1

    # Filtre automatique sur le bloc de détail : il compte plusieurs centaines
    # de lignes, et c'est le moyen le plus direct de n'afficher qu'une feuille,
    # qu'un tableau ou que les lignes renseignées.
    ws.auto_filter.ref = (
        f"A{ligne_entete_detail}:{get_column_letter(derniere_col)}{derniere_ligne_detail}"
    )
    # Geler seulement la colonne A (comme partout ailleurs dans l'app) —
    # jamais un pan vertical profond : figer les 60+ lignes précédant ce
    # bloc, sur un document qui en compte plusieurs milliers, remplissait
    # tout l'écran visible d'une zone gelée et rendait le début du document
    # impossible à atteindre en faisant défiler. Le filtre automatique
    # ci-dessus offre déjà une navigation directe dans le détail.
    ws.freeze_panes = "B1"

    cell = ws.cell(row=r, column=1,
                   value="● ligne renseignée   ○ ligne prévue par le gabarit mais non renseignée   ·   "
                         "Utilisez les flèches de filtre de la ligne d'en-tête pour n'afficher "
                         "qu'une feuille, qu'un tableau, ou que les lignes renseignées.")
    cell.font = F_NOTE
    r += 1

    # ------------------------------------------------------------------ #
    # Bloc 4 — Points de vigilance
    # ------------------------------------------------------------------ #
    r += 1
    r = _entete_bloc(ws, r, "4 · POINTS DE VIGILANCE SUR LES FICHIERS SOURCES", derniere_col)
    r = _ligne_entete(ws, r, ["Nature", "Établissement", "Feuille", "Détail"])

    libelle_type = {
        "erreur_formule": "Erreur de formule",
        "nombre_en_texte": "Nombre saisi en texte",
        "onglet_vide": "Feuille non renseignée",
        "libelle_introuvable": "Libellé introuvable",
        "onglet_non_reconnu": "Onglet non rattaché",
        "total_incoherent": "Total interne incohérent",
    }
    flags = run_quality_checks(institutions, kpis, gab)
    if not flags:
        cell = ws.cell(row=r, column=1, value="Aucune anomalie détectée.")
        cell.font, cell.border, cell.alignment = F_LIBELLE, B_GRILLE, ALIGN_LIBELLE
        r += 1
    for f in flags:
        valeurs = [libelle_type.get(f.kind, f.kind), f.institution, f.sheet or "—", f.message]
        for col, texte in enumerate(valeurs, start=1):
            cell = ws.cell(row=r, column=col, value=texte)
            cell.font = F_ERREUR if f.kind == "erreur_formule" else F_LIBELLE
            cell.border, cell.alignment = B_GRILLE, ALIGN_LIBELLE
        r += 1

    note = ws.cell(row=r + 1, column=1,
                   value="Les colonnes « Total marché » et « Taux de remplissage » sont des "
                         "formules : elles se recalculent si une valeur est modifiée. "
                         "Un tiret signale une donnée non renseignée.")
    note.font = F_NOTE
    r += 3

    # ------------------------------------------------------------------ #
    # Bloc 5 — Notes et définitions du gabarit
    #
    # Exclues des indicateurs (ce sont des définitions, pas des données),
    # mais restées invisibles nulle part ailleurs : un lecteur du résumé
    # seul n'aurait autrement aucun moyen de savoir, par exemple, ce que
    # recouvre précisément un « porteur actif ».
    # ------------------------------------------------------------------ #
    notes = extraire_notes(institutions)
    if notes:
        r = _entete_bloc(ws, r, "5 · NOTES ET DÉFINITIONS DU GABARIT", derniere_col)
        r = _ligne_entete(ws, r, ["Feuille", "Définition"])
        for sheet, texte in notes:
            c1 = ws.cell(row=r, column=1, value=sheet)
            c1.font, c1.border, c1.alignment = F_LIBELLE, B_GRILLE, ALIGN_LIBELLE
            c2 = ws.cell(row=r, column=2, value=texte)
            c2.font, c2.border, c2.alignment = F_LIBELLE, B_GRILLE, ALIGN_LIBELLE
            for col in range(3, derniere_col + 1):
                ws.cell(row=r, column=col).border = B_GRILLE
            r += 1
        r += 1

    # ------------------------------------------------------------------ #
    # Bloc 6 — Onglets hors gabarit standard
    #
    # Un onglet qu'aucun thème commun ne recouvre (mise en page propre à un
    # établissement) ne peut pas être résumé numériquement ici comme les
    # thèmes consolidés — mais il ne doit pas non plus disparaître du
    # document : au minimum, son existence et sa localisation (fichier
    # complet) restent tracées.
    # ------------------------------------------------------------------ #
    def _motif_non_rattachement(o) -> str:
        """Pourquoi cet onglet n'est pas consolidé — pour que la présence
        d'un onglet inattendu dans ce tableau soit toujours explicable."""
        if getattr(o, "periode_revolue", False):
            annees = ", ".join(str(a) for a in o.annees) if o.annees else "période antérieure"
            return f"Exercice révolu ({annees}) — exclu pour ne pas mélanger les périodes"
        if o.segments:
            themes = ", ".join(s.theme for s in o.segments)
            return f"Onglet composite : {len(o.segments)} thèmes détectés ({themes}) — à valider"
        if o.theme_propose:
            return f"Proposé : {o.theme_propose} ({o.taux_propose:.0%}) — en attente de validation"
        if o.suggestion:
            return f"Piste faible : {o.suggestion} ({o.taux_suggestion:.0%}) — à vérifier"
        return "Structure sans correspondance dans le gabarit standard"

    hors_gabarit = [(inst.name, o) for inst in institutions for o in inst.non_reconnus]
    if hors_gabarit:
        r = _entete_bloc(ws, r, "6 · ONGLETS HORS GABARIT STANDARD", derniere_col)
        r = _ligne_entete(ws, r, ["Établissement", "Onglet d'origine", "Pourquoi non consolidé"])
        for nom_etab, o in hors_gabarit:
            c1 = ws.cell(row=r, column=1, value=nom_etab)
            c1.font, c1.border, c1.alignment = F_LIBELLE, B_GRILLE, ALIGN_LIBELLE
            c2 = ws.cell(row=r, column=2, value=o.nom)
            c2.font, c2.border, c2.alignment = F_LIBELLE, B_GRILLE, ALIGN_LIBELLE
            c3 = ws.cell(row=r, column=3, value=_motif_non_rattachement(o))
            c3.font, c3.border, c3.alignment = F_NOTE, B_GRILLE, ALIGN_LIBELLE
            for col in range(4, derniere_col + 1):
                ws.cell(row=r, column=col).border = B_GRILLE
            r += 1
        note_hg = ws.cell(row=r + 1, column=1,
                          value="Ces onglets ne sont pas consolidés dans les totaux ci-dessus, mais "
                                "sont repris intégralement, tels quels, dans le fichier complet. La "
                                "colonne « Pourquoi non consolidé » indique la raison exacte pour "
                                "chacun — un onglet d'un exercice antérieur laissé dans le classeur "
                                "est écarté délibérément, pour ne jamais mélanger deux périodes.")
        note_hg.font = F_NOTE

    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 34
    ws.column_dimensions["C"].width = 46
    ws.column_dimensions["D"].width = 14
    for i in range(n_inst + 1):
        ws.column_dimensions[get_column_letter(5 + i)].width = 20
    couleur_onglet(ws, EMERAUDE)

    return wb
