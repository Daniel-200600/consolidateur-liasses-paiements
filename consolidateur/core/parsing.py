"""
core/parsing.py

Lecture des liasses statistiques de paiements (gabarit BEAC) et conversion en
structures Python simples.

Règle centrale (cf. Cahier des charges, section 5.1 et Annexe A) :
- Seuls les 11 onglets connus du gabarit sont lus ; tout autre onglet présent
  dans le fichier est ignoré.
- Chaque onglet est représenté par une "grille" (liste de listes), fidèle à la
  disposition des cellules du fichier source (ligne 0 = ligne 1 Excel, etc.).
- Une cellule dont la valeur en cache est une erreur de formule (#VALUE!,
  #REF!, #DIV/0!, ...) n'est PAS recopiée telle quelle dans la grille : elle
  est mise à None et consignée séparément dans la liste `errors`, afin de ne
  jamais laisser une erreur de formule source se propager silencieusement
  dans les calculs de consolidation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import openpyxl

from core.sheet_matching import (
    Reconnaissance, annees_mentionnees, detecter_decalage_colonnes,
    detecter_disposition_mensuelle, detecter_periode_declaree, detecter_segments,
    dimensions_canoniques, extraire_derniere_periode, mesures_statiques_canoniques,
    reconnaissance_pour_theme, reconnaitre_onglet, remapper_grille,
)

# Les 11 onglets du gabarit BEAC (cf. Cahier des charges, Annexe A).
KNOWN_SHEETS: list[str] = [
    "chèques&VIR",
    "Transfert d'argent",
    "Mobile Money1",
    "MobileMoney2",
    "MobileMoney3",
    "Cartes1",
    "Cartes 2",
    "Cartes 3",
    "Cartes 4",
    "Cartes 5",
    "PrêtsCredits",
]

# Valeurs que openpyxl restitue pour une cellule dont la formule source est en
# erreur, lorsque le classeur est ouvert avec data_only=True.
ERROR_MARKERS = {"#VALUE!", "#REF!", "#DIV/0!", "#NAME?", "#N/A", "#NULL!", "#NUM!"}


@dataclass
class SheetData:
    """Contenu d'un onglet, une fois nettoyé des erreurs de formule source."""

    grid: list[list[Any]] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)  # [{row, col, addr, text}]
    # Cellules qui contenaient un nombre SAISI EN TEXTE et qui ont été
    # converties (cf. _parse_numeric_text). Conservées pour pouvoir les
    # signaler à l'utilisateur : c'est une anomalie de saisie à corriger à la
    # source, même si l'outil sait la rattraper.
    text_numbers: list[dict] = field(default_factory=list)


# Motifs numériques tolérés dans une cellule texte : séparateurs de milliers
# (espace, espace insécable) et virgule décimale française.
_NUMERIC_TEXT_RE = re.compile(r"^-?\d+(?:[.,]\d+)?$")


def _parse_numeric_text(value: Any) -> Optional[float]:
    """Si `value` est une chaîne représentant un nombre (ex. '16470' ou
    '15 300 000 000,00'), renvoie ce nombre ; sinon None.

    Ces cellules existent réellement dans les liasses reçues : saisies en
    texte, Excel ne les additionne pas et elles seraient comptées comme zéro,
    ce qui fausse les totaux de plusieurs milliards. On les récupère donc,
    tout en les signalant (cf. SheetData.text_numbers).
    """
    if not isinstance(value, str):
        return None
    s = value.strip().replace("\u00a0", "").replace(" ", "")
    if not s:
        return None
    if not _NUMERIC_TEXT_RE.match(s):
        return None
    s = s.replace(",", ".")
    try:
        number = float(s)
    except ValueError:
        return None
    return int(number) if number.is_integer() else number


@dataclass
class OngletNonReconnu:
    """Un onglet dont ni le nom ni la structure ne correspondent avec une
    confiance suffisante à un thème connu du gabarit — jamais
    silencieusement ignoré : conservé pour être affiché à l'utilisateur.

    Si `theme_propose` n'est pas None, une PROPOSITION suffisamment
    confiante existe : elle peut être validée en un clic (jamais construite
    à la main), et sera alors mémorisée pour ne plus jamais être redemandée
    (cf. core.calibration)."""

    nom: str
    grid: list[list]
    errors: list[dict] = field(default_factory=list)
    text_numbers: list[dict] = field(default_factory=list)
    suggestion: Optional[str] = None       # piste la plus proche, même trop faible pour être proposée
    taux_suggestion: float = 0.0
    theme_propose: Optional[str] = None
    taux_propose: float = 0.0
    alternative: Optional[str] = None
    taux_alternative: float = 0.0
    disposition_mensuelle: bool = False
    # Onglet relevant d'une période de reporting révolue (exercice antérieur
    # laissé dans le fichier) : jamais proposé au rattachement, car
    # consolider ses montants avec ceux de la période courante gonflerait
    # les totaux sans qu'aucune erreur ne soit signalée.
    periode_revolue: bool = False
    annees: tuple = ()
    # Fragments détectés dans un onglet COMPOSITE (plusieurs thèmes dans un
    # même onglet, cf. core.sheet_matching.detecter_segments) — chacun
    # validable indépendamment, ou tous d'un coup.
    segments: list = field(default_factory=list)
    # Onglet portant sur un exercice révolu (ex. des onglets « 1er TRIMESTRE
    # 2022 » laissés dans un classeur 2025-2026) : jamais proposé au
    # rattachement en un clic, car ses montants se mélangeraient à ceux de
    # la période courante sans qu'aucune erreur ne soit signalée.
    periode_revolue: bool = False
    annees: list = field(default_factory=list)


@dataclass
class Institution:
    """Un établissement chargé : son nom (modifiable par l'utilisateur), le
    nom du fichier source, les onglets connus qu'il contient, les onglets
    du fichier qui n'ont pu être rattachés à aucun thème, et son pays."""

    name: str
    file_name: str
    sheets: dict[str, SheetData]
    non_reconnus: list[OngletNonReconnu] = field(default_factory=list)
    pays: Optional[str] = None


def _is_error_value(value: Any) -> bool:
    return isinstance(value, str) and value.strip() in ERROR_MARKERS


def _grille_depuis_mensuel(grid: list[list], reconnaissance: Reconnaissance,
                           n_lignes: int, n_colonnes: int) -> list[list]:
    """Reconstruit une grille canonique à partir d'un onglet qui décline le
    thème sous une forme MENSUELLE (dates en colonnes) alors que le gabarit
    de référence est statique : chaque ligne alignée reçoit les valeurs de
    son DERNIER mois renseigné, placées dans les colonnes Nombre/Valeur
    canoniques — cohérent avec le reste de l'application, qui retient
    systématiquement le dernier mois disponible plutôt que d'exiger une
    mise à jour manuelle."""
    grille: list[list] = [[None] * n_colonnes for _ in range(n_lignes)]
    mapping_mesures = mesures_statiques_canoniques(reconnaissance.theme) or {}
    mapping_lignes = dict(reconnaissance.alignement or [])

    for r_candidate, r_ref in mapping_lignes.items():
        if r_ref >= n_lignes:
            continue
        valeurs = extraire_derniere_periode(grid, reconnaissance.periodes_mensuelles or [], r_candidate)
        for nom_mesure, valeur in valeurs.items():
            col = mapping_mesures.get(nom_mesure)
            if col is not None and col < n_colonnes and valeur is not None:
                grille[r_ref][col] = valeur
        # Le libellé (colonne 0) reprend le texte le plus spécifique des
        # colonnes A/B candidates — pas systématiquement la colonne A brute,
        # qui peut porter un titre de rubrique plutôt que le libellé de la
        # ligne (cf. empreinte_libelles).
        if r_candidate < len(grid) and grid[r_candidate]:
            candidats = [v for v in grid[r_candidate][:2] if isinstance(v, str) and v.strip()]
            if candidats:
                grille[r_ref][0] = max(candidats, key=len)
    return grille


def _lire_grille_brute(ws) -> tuple[list[list[Any]], list[dict], list[dict]]:
    """Lit un onglet openpyxl tel quel : grille, erreurs de formule, nombres
    saisis en texte — sans aucune reconnaissance de thème."""
    grid: list[list[Any]] = []
    errors: list[dict] = []
    text_numbers: list[dict] = []
    for r_idx, row in enumerate(ws.iter_rows()):
        row_values = []
        for c_idx, cell in enumerate(row):
            value = cell.value
            if _is_error_value(value):
                row_values.append(None)
                errors.append({"row": r_idx, "col": c_idx, "addr": cell.coordinate, "text": value})
                continue
            if c_idx > 0:
                parsed = _parse_numeric_text(value)
                if parsed is not None:
                    row_values.append(parsed)
                    text_numbers.append({
                        "row": r_idx, "col": c_idx, "addr": cell.coordinate,
                        "original": value, "parsed": parsed,
                    })
                    continue
            row_values.append(value)
        grid.append(row_values)
    return grid, errors, text_numbers


def _fusionner(feuilles: list[tuple[str, list[list], list[dict], list[dict]]]) -> SheetData:
    """Combine plusieurs onglets déjà alignés sur le même repère de lignes
    canonique (un par variante — réseau, système de règlement…) en une seule
    SheetData : les cellules numériques s'additionnent, les libellés et
    autres textes sont repris de la première variante qui les porte (ils
    sont, par construction, identiques d'une variante à l'autre)."""
    if len(feuilles) == 1:
        _, grid, errors, text_numbers = feuilles[0]
        return SheetData(grid=grid, errors=errors, text_numbers=text_numbers)

    n_lignes = max(len(g) for _, g, _, _ in feuilles)
    n_colonnes = max((len(row) for _, g, _, _ in feuilles for row in g), default=0)
    grille: list[list[Any]] = [[None] * n_colonnes for _ in range(n_lignes)]
    errors: list[dict] = []
    text_numbers: list[dict] = []

    for nom_source, g, err, txt in feuilles:
        for r in range(min(len(g), n_lignes)):
            for c in range(min(len(g[r]), n_colonnes)):
                v = g[r][c]
                if v is None:
                    continue
                actuel = grille[r][c]
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    grille[r][c] = (actuel or 0) + v
                elif actuel is None:
                    grille[r][c] = v
        for e in err:
            errors.append({**e, "source": nom_source})
        for t in txt:
            text_numbers.append({**t, "source": nom_source})

    return SheetData(grid=grille, errors=errors, text_numbers=text_numbers)


def parse_workbook(path_or_buffer, file_name: str | None = None) -> dict[str, SheetData]:
    """Lit un gabarit .xlsx et renvoie {thème canonique: SheetData}.

    Reconnaît aussi bien les onglets nommés exactement comme le gabarit que
    les variantes (par réseau, système de règlement…) dont seule la
    STRUCTURE INTERNE concorde — cf. core.sheet_matching. Les onglets qui ne
    correspondent à aucun thème connu ne sont pas inclus ici ; voir
    `analyser_fichier` pour y accéder également.
    """
    return analyser_fichier(path_or_buffer, file_name)[0]


def _grille_pour_fusion(grid: list[list], reconnaissance: Reconnaissance) -> list[list]:
    """Construit la grille dans le repère canonique, quelle que soit la
    disposition d'origine de l'onglet (même mise en page que la référence,
    ou déclinaison mensuelle d'un thème normalement statique)."""
    n_lignes, n_colonnes = dimensions_canoniques(reconnaissance.theme)
    if reconnaissance.disposition_mensuelle:
        return _grille_depuis_mensuel(grid, reconnaissance, n_lignes, n_colonnes)
    decalage = detecter_decalage_colonnes(grid, reconnaissance.alignement, reconnaissance.theme)
    return remapper_grille(grid, reconnaissance.alignement, n_lignes, n_colonnes, decalage)


_NOM_GENERIQUE_EXCEL = re.compile(r"^(sheet|feuil)\s*\d*$", re.IGNORECASE)


def _onglet_sans_information_exploitable(nom: str, grid: list[list]) -> bool:
    """Une feuille véritablement vide, ou portant le nom générique par
    défaut d'Excel (« Sheet1 », « Feuil2 »…) sans le moindre contenu
    substantiel, n'apporte rien — sur demande explicite de l'utilisateur,
    elle est purement et simplement ignorée plutôt que listée hors
    gabarit.

    Le nom générique seul ne suffit pas à exclure une feuille : un
    établissement a pu renommer un onglet en son nom par défaut tout en y
    plaçant de vraies données, auquel cas elle reste évidemment exploitée.
    C'est la combinaison nom générique + contenu quasi inexistant qui
    signale une feuille laissée par erreur.
    """
    valeurs_reelles = sum(
        1 for row in grid for v in row
        if v is not None and not (isinstance(v, str) and not v.strip())
    )
    if valeurs_reelles == 0:
        return True
    return bool(_NOM_GENERIQUE_EXCEL.match(nom.strip())) and valeurs_reelles < 3


def analyser_fichier(path_or_buffer, file_name: str | None = None,
                     calibration=None) -> tuple[dict[str, SheetData], list[OngletNonReconnu]]:
    """Comme `parse_workbook`, mais renvoie en plus la liste des onglets du
    fichier qui n'ont pu être rattachés à aucun thème connu — jamais
    silencieusement perdus.

    `calibration` (cf. core.calibration.Calibration) porte les rattachements
    déjà validés par l'utilisateur pour un nom d'onglet donné : appliqués
    directement, sans redemander de validation. Un onglet reconnu mais avec
    une confiance insuffisante pour être consolidé automatiquement devient
    une PROPOSITION (`OngletNonReconnu.theme_propose`), prête à valider en
    un clic plutôt qu'à rattacher à la main.
    """
    wb = openpyxl.load_workbook(path_or_buffer, data_only=True)
    noms_connus = set(KNOWN_SHEETS)

    par_theme: dict[str, list[tuple[str, list[list], list[dict], list[dict]]]] = {}
    non_reconnus: list[OngletNonReconnu] = []

    # Période de référence du classeur : l'année la plus récente mentionnée,
    # toutes feuilles confondues. Un onglet nettement antérieur porte sur un
    # exercice révolu (cas réel : des onglets « 1er TRIMESTRE 2022 » laissés
    # dans un classeur 2025-2026) et ne doit jamais être proposé au
    # rattachement en un clic : ses montants se mélangeraient à ceux de la
    # période courante sans qu'aucune erreur ne soit signalée.
    # Le classeur n'est lu QU'UNE fois : les grilles servent à la fois au
    # calcul de la période de référence et à la consolidation elle-même.
    # Les relire pour chaque usage triplait le temps de chargement sur les
    # gros classeurs, sans rien apporter.
    grilles: dict[str, tuple[list[list], list[dict], list[dict]]] = {}
    annees_par_onglet: dict[str, set[int]] = {}
    for nom in wb.sheetnames:
        lu = _lire_grille_brute(wb[nom])
        grilles[nom] = lu
        annees_par_onglet[nom] = annees_mentionnees(lu[0])
    toutes_annees = {a for s in annees_par_onglet.values() for a in s}
    annee_reference = max(toutes_annees) if toutes_annees else None

    # --- Conflits de PÉRIODE entre onglets composites calibrés -----------
    #
    # Deux onglets composites peuvent tous deux avoir été validés (chacun
    # avec ses propres segments), tout en représentant en réalité la MÊME
    # activité photographiée à deux dates différentes plutôt que deux
    # catégories à additionner (cas réel : « Cartes_2025 » couvrant l'année
    # 2025, « Cartes_2026 » le premier semestre 2026 — la même clientèle,
    # pas deux populations distinctes). Les fusionner comme des réseaux
    # parallèles doublerait la quasi-totalité des effectifs, silencieusement.
    #
    # Détecté ici, AVANT la boucle principale, pour connaître l'ensemble des
    # périodes en jeu avant de décider laquelle retenir.
    periode_par_onglet: dict[str, Optional[tuple]] = {
        nom: detecter_periode_declaree(grid) for nom, (grid, _, _) in grilles.items()
    }
    onglets_composites_periodes: list[tuple[str, tuple]] = [
        (nom, periode_par_onglet[nom])
        for nom in wb.sheetnames
        if periode_par_onglet.get(nom) and calibration and calibration.segments_pour(nom)
    ]
    onglets_supplantes: set[str] = set()
    if len(onglets_composites_periodes) >= 2:
        derniere_fin = max(fin for _, (_, fin) in onglets_composites_periodes)
        onglets_supplantes = {
            nom for nom, (_, fin) in onglets_composites_periodes if fin < derniere_fin
        }

    for nom_onglet in wb.sheetnames:
        grid, errors, text_numbers = grilles[nom_onglet]

        # Une feuille vide, ou au nom générique par défaut d'Excel
        # (« Sheet1 », « Feuil1 »…) sans le moindre contenu exploitable, ne
        # sert à rien — ni consolidée, ni même listée hors gabarit : sur
        # demande explicite, purement et simplement ignorée.
        if _onglet_sans_information_exploitable(nom_onglet, grid):
            continue

        if nom_onglet in onglets_supplantes:
            periode = periode_par_onglet[nom_onglet]
            non_reconnus.append(OngletNonReconnu(
                nom=nom_onglet, grid=grid, errors=errors, text_numbers=text_numbers,
                periode_revolue=True, annees=(periode[0].year, periode[1].year),
            ))
            continue

        annees_onglet = annees_par_onglet.get(nom_onglet) or set()
        periode_revolue = bool(
            annee_reference and annees_onglet and max(annees_onglet) < annee_reference - 1
        )

        # --- Onglet composite déjà calibré : chaque segment validé est
        # fusionné dans son propre thème, indépendamment des autres. ---
        themes_calibres = calibration.segments_pour(nom_onglet) if calibration else None
        if themes_calibres:
            segments_actuels = {s.theme: s for s in detecter_segments(grid)}
            for theme in themes_calibres:
                segment = segments_actuels.get(theme)
                if segment is None:
                    continue  # structure changée depuis la validation : segment introuvable cette fois
                reconnaissance = Reconnaissance(
                    theme=theme, correspondance_exacte=False, taux=segment.taux,
                    alignement=segment.alignement, disposition_mensuelle=segment.disposition_mensuelle,
                    periodes_mensuelles=segment.periodes_mensuelles,
                )
                grid_aligne = _grille_pour_fusion(grid, reconnaissance)
                par_theme.setdefault(theme, []).append(
                    (f"{nom_onglet} [{theme}]", grid_aligne, [], []))

            # Si de nouveaux segments apparaissent (jamais validés) ou si un
            # segment déjà validé est introuvable cette fois, l'onglet brut
            # reste visible en secours : aucune portion ne doit disparaître
            # silencieusement au seul motif qu'une AUTRE portion a déjà été
            # validée.
            non_couverts = set(segments_actuels) - set(themes_calibres)
            introuvables = set(themes_calibres) - set(segments_actuels)
            if non_couverts or introuvables:
                non_reconnus.append(OngletNonReconnu(
                    nom=nom_onglet, grid=grid, errors=errors, text_numbers=text_numbers,
                    segments=[segments_actuels[t] for t in non_couverts],
                ))
            continue

        theme_calibre = calibration.theme_pour(nom_onglet) if calibration else None
        if theme_calibre and nom_onglet.strip() not in noms_connus:
            reconnaissance = reconnaissance_pour_theme(grid, theme_calibre)
        else:
            reconnaissance = reconnaitre_onglet(nom_onglet, grid, noms_connus)

        # --- Garde-fou de PÉRIODE, avant toute reconnaissance ------------
        # Un onglet portant sur un exercice révolu ressemble structurellement
        # au gabarit (souvent à plus de 90 %, c'est le même formulaire) : sans
        # ce garde-fou, il serait proposé — voire consolidé automatiquement —
        # et ses montants d'une autre année viendraient gonfler les totaux de
        # la période courante en silence. Il reste visible et rattachable,
        # mais jamais en un clic : la décision doit être consciente.
        if periode_revolue and nom_onglet.strip() not in noms_connus:
            reco_info = reconnaitre_onglet(nom_onglet, grid, noms_connus)
            non_reconnus.append(OngletNonReconnu(
                nom=nom_onglet, grid=grid, errors=errors, text_numbers=text_numbers,
                suggestion=reco_info.theme or reco_info.suggestion,
                taux_suggestion=reco_info.taux,
                periode_revolue=True,
                annees=sorted(annees_onglet),
            ))
            continue

        if reconnaissance.theme is None:
            # Aucun thème unique ne correspond à l'onglet ENTIER : peut-être
            # regroupe-t-il plusieurs thèmes (onglet composite) — chacun
            # localisé sur sa propre plage de lignes.
            segments = detecter_segments(grid)
            non_reconnus.append(OngletNonReconnu(
                nom=nom_onglet, grid=grid, errors=errors, text_numbers=text_numbers,
                suggestion=reconnaissance.suggestion, taux_suggestion=reconnaissance.taux,
                segments=segments,
            ))
            continue

        # Une proposition non encore validée n'est PAS consolidée — elle
        # reste visible, prête à valider en un clic, jamais construite à la
        # main. Un rattachement déjà calibré, lui, est appliqué directement
        # (`theme_calibre`), même s'il proviendrait autrement d'une
        # reconnaissance à faible confiance.
        if reconnaissance.necessite_validation and not theme_calibre:
            non_reconnus.append(OngletNonReconnu(
                nom=nom_onglet, grid=grid, errors=errors, text_numbers=text_numbers,
                theme_propose=reconnaissance.theme, taux_propose=reconnaissance.taux,
                alternative=reconnaissance.alternative, taux_alternative=reconnaissance.taux_alternative,
                disposition_mensuelle=reconnaissance.disposition_mensuelle,
            ))
            continue

        if reconnaissance.correspondance_exacte:
            par_theme.setdefault(reconnaissance.theme, []).append(
                (nom_onglet, grid, errors, text_numbers))
        else:
            # Les positions d'erreur/de nombres-en-texte restent, elles,
            # exprimées dans le repère du fichier source (adresse Excel
            # d'origine) : utile pour retrouver la cellule exacte dans SON
            # fichier, même si la ligne a été réalignée pour la consolidation.
            grid_aligne = _grille_pour_fusion(grid, reconnaissance)
            par_theme.setdefault(reconnaissance.theme, []).append(
                (nom_onglet, grid_aligne, errors, text_numbers))

    sheets = {theme: _fusionner(feuilles) for theme, feuilles in par_theme.items()}
    return sheets, non_reconnus


def clean_institution_name(file_name: str) -> str:
    """Propose un nom d'établissement à partir du nom de fichier (repris tel
    quel dans un champ modifiable côté interface — cf. CDC section 5.1).

    Cas réel corrigé : un nom de fichier commençant par le CODE PAYS
    (« CF-BanqueXYZ_Liasse_… ») faisait retenir « CF » comme nom
    d'établissement — un code pays n'est jamais un nom d'établissement
    exploitable, et deux fichiers de pays différents nommés ainsi
    produisaient une colonne de Sommaire absurde une fois désambiguïsés en
    « CF (2) », « CG (2) »…

    Second cas réel corrigé (fichier réel d'un établissement du Tchad) :
    une ANNÉE en tête de nom de fichier (« 2025-BAC_TCHAD_Liasse_… »)
    produisait « 2025 BAC TCHAD » comme nom d'établissement — une année
    n'est pas plus exploitable qu'un code pays.

    Les segments reconnus comme code pays (cf. core.pays) ou comme année
    sont donc ignorés, quelle que soit leur position — au début comme à la
    fin — et le premier segment restant, réellement porteur d'un nom, est
    retenu.
    """
    from core.pays import PAYS_CEMAC

    codes_pays = {c for info in PAYS_CEMAC.values() for c in info["codes"]}
    # Vocabulaire générique du gabarit, présent dans la quasi-totalité des
    # noms de fichiers réels rencontrés (« XXX_Liasse_Stats_Paiements_… ») :
    # jamais un nom d'établissement à lui seul. Cas réel corrigé : un nom de
    # fichier « CF_Liasse_Stats_… » retenait « Stats » comme établissement
    # une fois « CF » (code pays) et « Liasse » écartés.
    mots_generiques = {"liasse", "stats", "statistiques", "paiement", "paiements", "copie"}

    base = Path(file_name).stem
    segments = [s for s in re.split(r"[_\-]+", base) if s]

    for segment in segments:
        candidat = segment.split("Liasse")[0].split("liasse")[0].strip()
        # Une année collée en tête par un espace (« 2025 BAC TCHAD », le
        # séparateur du nom de fichier étant resté après « TCHAD ») doit
        # être retirée sans jeter le reste du segment, contrairement au
        # code pays ou au mot générique qui, eux, occupent tout le segment.
        candidat = re.sub(r"^(19|20)\d{2}\s+", "", candidat).strip()
        if not candidat:
            continue
        if re.fullmatch(r"(19|20)\d{2}", candidat):
            continue
        if candidat.upper() in codes_pays or candidat.lower() in mots_generiques:
            continue
        return candidat

    # Rien d'exploitable trouvé (nom de fichier réduit à un code pays, une
    # année et du vocabulaire générique) : on retombe sur le premier
    # segment qui n'est PAS un code pays plutôt que le tout premier
    # segment sans distinction — un code pays ne doit jamais être le nom
    # de repli tant qu'un autre segment, même imparfait, existe.
    non_pays = [s for s in segments if s.upper() not in codes_pays]
    if non_pays:
        return non_pays[0]
    return segments[0] if segments else base


# Libellés rencontrés dans les fichiers réels pour le champ où
# l'établissement est censé indiquer son propre nom — la casse et les
# variantes d'accent/apostrophe changent d'un fichier à l'autre.
_LIBELLES_ETABLISSEMENT = {"etablissement", "établissement", "nom de la banque", "nom de l etablissement"}


def nom_declare(sheets: dict) -> Optional[str]:
    """Nom d'établissement que le fichier déclare lui-même (champ
    « Etablissement : » du gabarit), s'il est renseigné.

    Cas réel corrigé : deux fichiers d'un établissement réel (« ETABH »)
    avaient un nom de fichier ne portant aucune trace exploitable de ce nom
    — le nom proposé automatiquement (déduit du fichier) était donc
    entièrement faux (« ETABA »), une erreur d'étiquetage sérieuse dans un
    document destiné à la BEAC. Le champ « Etablissement : » du gabarit,
    quand il est rempli, est autrement plus fiable qu'une déduction depuis
    le nom de fichier : il est donc préféré s'il existe.

    La plupart des établissements laissent ce champ vide dans la pratique
    (le nom de fichier suffit à les identifier de leur point de vue) : cette
    fonction renvoie alors None, sans rien changer au comportement habituel.
    """
    for sd in sheets.values():
        for row in sd.grid[:8]:
            if not row or not isinstance(row[0], str):
                continue
            if row[0].strip().rstrip(":").strip().lower() in _LIBELLES_ETABLISSEMENT:
                for v in row[1:]:
                    if not isinstance(v, str) or not v.strip():
                        continue
                    # Cas réel corrigé : une cellule dupliquant elle-même le
                    # libellé (« Etablissement : » répété dans la même
                    # ligne, artefact de fusion de cellules chez un
                    # établissement réel) n'est jamais un nom exploitable.
                    if v.strip().rstrip(":").strip().lower() in _LIBELLES_ETABLISSEMENT:
                        continue
                    return v.strip()
    return None


def load_institution(path_or_buffer, file_name: str, display_name: str | None = None) -> Institution:
    sheets = parse_workbook(path_or_buffer, file_name)
    return Institution(
        name=display_name or clean_institution_name(file_name),
        file_name=file_name,
        sheets=sheets,
    )
