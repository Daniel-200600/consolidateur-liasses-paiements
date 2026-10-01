"""
core/indicators.py

Découverte AUTOMATIQUE des indicateurs présents dans les liasses.

Motivation (évolution demandée après la Phase 9) : la liste d'indicateurs
écrite à la main dans core/kpis.py ne couvrait que 8 des ~45 lignes de
données réellement présentes dans le gabarit BEAC. Tout le détail sectoriel
des paiements Mobile Money, les accepteurs/distributeurs, les transactions
cartes par zone, etc. restaient invisibles dans le tableau de bord (ils
étaient bien consolidés et exportés, mais jamais "lus").

Principe retenu : plutôt que d'énumérer les indicateurs, on parcourt chaque
onglet et on expose TOUTE ligne porteuse de données. L'outil s'adapte donc
seul si la BEAC ajoute des lignes au gabarit.

Fiabilité de l'indexation : le gabarit étant strictement identique d'un
établissement à l'autre (vérifié : 0 écart de libellé ligne à ligne sur les
11 onglets des fichiers de référence), un indicateur est identifié par sa
POSITION (onglet + numéro de ligne), et non par une recherche de libellé.
C'est nettement plus robuste, et cela règle au passage le problème des
libellés qui se répètent à l'identique dans plusieurs sections d'un même
onglet (« Retrait GAB » apparaît 4 fois dans Cartes 5).

Deux dispositions d'onglets sont gérées :
- mensuelle   : une ligne d'en-tête contient des dates. Chaque mois peut
                porter une seule valeur (Mobile Money1) ou un couple
                Nombre/Valeur (MobileMoney2).
- statique    : pas de dates ; les colonnes de mesure sont décrites par des
                en-têtes « Nombre » / « Valeur » qui peuvent se répéter à
                chaque section de l'onglet (Cartes 2, Cartes 5).
"""

from __future__ import annotations

import datetime
import functools
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

from core.parsing import KNOWN_SHEETS, Institution, SheetData

MEASURE_WORDS = ("nombre", "valeur", "montant")


@functools.lru_cache(maxsize=8192)
def _norm_texte(s: str) -> str:
    s = s.lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _norm(v) -> str:
    """Normalisation d'un libellé, MÉMORISÉE.

    Un profilage a mesuré près de 5 millions d'appels pour une seule
    consolidation de quatre établissements, sur un vocabulaire très
    répétitif (les mêmes libellés de gabarit, réexaminés à chaque passe).
    """
    if v is None:
        return ""
    return _norm_texte(str(v))


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_date(v) -> bool:
    return isinstance(v, (datetime.datetime, datetime.date))


def _is_real_data(v) -> bool:
    """Une donnée métier : numérique, non nulle, et qui n'est pas un simple
    en-tête d'année (ex. 2025) — même règle que core.quality.has_real_data."""
    if not _is_number(v) or v == 0:
        return False
    if isinstance(v, int) and 2000 <= v <= 2100:
        return False
    return True


_SECTION_PREFIX_RE = re.compile(r"^[A-Z]\s*[-–—.)]\s*\S")


def _looks_like_section(row: list, following_rows: Optional[list[list]] = None) -> bool:
    """Ligne de titre de section : du texte, aucune donnée chiffrée, et un
    signal typographique.

    Trois signaux acceptés, car les gabarits mélangent les styles :
    - majuscules dominantes (« TRANSACTIONS DE VOS PORTEURS ») ;
    - numérotation de section (« B- Transactions internationales… »), qui
      serait manquée par le seul critère de casse ;
    - ligne suivie de près par un en-tête de colonnes (« Nombre | Valeur »),
      qui marque le début d'un nouveau bloc de tableau.
    """
    if any(_is_number(v) and v != 0 for v in row[1:]):
        return False
    text = next((v for v in row[:2] if isinstance(v, str) and v.strip()), None)
    if not text or len(text.strip()) < 4:
        return False
    text = text.strip()

    letters = [c for c in text if c.isalpha()]
    if letters and sum(1 for c in letters if c.isupper()) / len(letters) > 0.7:
        return True
    if _SECTION_PREFIX_RE.match(text):
        return True
    if following_rows:
        for nxt in following_rows[:3]:
            if _measure_header(nxt):
                return True
    return False


def _measure_header(row: list) -> list[tuple[str, int]]:
    """Si la ligne décrit des colonnes de mesure (« Nombre », « Valeur »…),
    renvoie [(nom_de_mesure, index_colonne), ...].

    Une LISTE et non un dictionnaire : dans les onglets mensuels, les
    en-têtes « Nombre » / « Valeur » se répètent pour chaque mois. Un
    dictionnaire ne conserverait que la dernière colonne de chaque nom, et
    tous les mois sauf le dernier perdraient leurs mesures.
    """
    found: list[tuple[str, int]] = []
    for c, v in enumerate(row):
        if c == 0 or not isinstance(v, str):
            continue
        n = _norm(v)
        if any(w in n for w in MEASURE_WORDS):
            found.append((v.strip(), c))
    return found


def _upper_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    return sum(1 for c in letters if c.isupper()) / len(letters) if letters else 0.0


def _is_major_heading(text: str) -> bool:
    """Titre de TABLEAU (« CHEQUES », « VIREMENTS », « EFFETS DE COMMERCE »).

    Signal : capitales dominantes. Les lignes « TOTAL … » sont exclues : ce
    sont des lignes de résultat, pas des ouvertures de tableau, alors qu'elles
    sont elles aussi en majuscules.
    """
    t = text.strip()
    if _norm(t).startswith("total"):
        return False
    return _upper_ratio(t) >= 0.85


def _is_lettered_heading(text: str) -> bool:
    """Titre numéroté par une lettre (« A- … », « B- … »)."""
    return bool(_SECTION_PREFIX_RE.match(text.strip()))


@dataclass
class SheetLayout:
    is_monthly: bool = False
    # Disposition mensuelle : [(période, {mesure: colonne}), ...]
    periods: list[tuple[datetime.date, dict[str, int]]] = field(default_factory=list)
    # Disposition statique : {numéro de ligne: {mesure: colonne}}
    row_measures: dict[int, dict[str, int]] = field(default_factory=dict)
    # Sous-section applicable à chaque ligne
    row_sections: dict[int, str] = field(default_factory=dict)
    # Titre du TABLEAU auquel appartient chaque ligne (« CHEQUES »,
    # « VIREMENTS », « PRELEVEMENTS »…)
    row_rubrics: dict[int, str] = field(default_factory=dict)


_layout_cache: dict[int, tuple[list, "SheetLayout"]] = {}


def analyze_layout(grid: list[list]) -> SheetLayout:
    """Analyse la disposition d'une grille (titres, périodes, mesures).

    Résultat MÉMORISÉ : un profilage a montré que cette fonction, purement
    déterministe, était rappelée des centaines de fois sur les mêmes grilles
    au cours d'une seule consolidation (180 appels là où 22 suffisaient) —
    de loin le premier poste de temps de calcul, et le temps croît avec le
    nombre d'établissements chargés.

    La clé est l'identité de l'objet grille : les grilles ne sont jamais
    modifiées après lecture du fichier. Une référence à la grille est
    conservée dans le cache, ce qui garantit que son identifiant ne peut pas
    être réattribué à un autre objet entre-temps.
    """
    cle = id(grid)
    en_cache = _layout_cache.get(cle)
    if en_cache is not None and en_cache[0] is grid:
        return en_cache[1]

    layout = _analyser_layout(grid)
    _layout_cache[cle] = (grid, layout)
    return layout


def vider_cache_layout() -> None:
    """Libère le cache d'analyse de disposition (utile entre deux jeux de
    fichiers, ou dans les tests pour repartir d'un état neuf)."""
    _layout_cache.clear()


def _analyser_layout(grid: list[list]) -> SheetLayout:
    layout = SheetLayout()

    # --- Titres de tableau et sous-sections ---------------------------------
    # Deux niveaux sont distingués, car les gabarits imbriquent des blocs :
    #   CHEQUES                              <- rubrique (titre de tableau)
    #     A -Transaction entre clients…      <- sous-section
    #     B- Transactions SYSTAC             <- sous-section
    #        - dont émis par vos clients     <- ligne de données
    #
    # Règles, dans cet ordre :
    #  1. un titre en capitales ouvre un nouveau TABLEAU ;
    #  2. un titre numéroté (« B- … ») est FRÈRE de la rubrique courante si
    #     celle-ci est elle aussi numérotée — c'est le cas de MobileMoney3
    #     (« A- OPERATIONS DOMESTIQUES » puis « B- Transactions
    #     internationales »), alors que dans chèques&VIR les « A- / B- »
    #     sont au contraire des subdivisions de « CHEQUES » ;
    #  3. tout autre titre est une sous-section de la rubrique courante.
    current_rubric = ""
    current_section = ""
    # Un même titre peut ouvrir PLUSIEURS tableaux dans une même feuille :
    # Cartes 5 comporte ainsi deux blocs « TRANSACTIONS DE VOS PORTEURS »
    # (retraits, puis paiements). Sans distinction, deux lignes homonymes
    # portant des valeurs différentes deviendraient indiscernables. Les
    # occurrences suivantes sont donc numérotées.
    occurrences: dict[str, int] = {}

    def _nommer_rubrique(titre: str) -> str:
        n = occurrences.get(titre, 0) + 1
        occurrences[titre] = n
        return titre if n == 1 else f"{titre} ({n})"

    for r, row in enumerate(grid):
        if row and _looks_like_section(row, grid[r + 1:r + 4]):
            # Un élément d'énumération (VISA, MASTERCARD…) n'ouvre pas de
            # tableau : il ne doit pas devenir un titre, sauf s'il précède
            # immédiatement un en-tête de colonnes.
            if _element_de_liste(grid, r) and not _ouvre_un_bloc(grid, r):
                layout.row_sections[r] = current_section
                layout.row_rubrics[r] = current_rubric
                continue
            title = next(v for v in row[:2] if isinstance(v, str) and v.strip()).strip()
            if _is_major_heading(title):
                current_rubric, current_section = _nommer_rubrique(title), ""
            elif _is_lettered_heading(title) and current_rubric and _is_lettered_heading(current_rubric):
                current_rubric, current_section = _nommer_rubrique(title), ""
            else:
                current_section = title
        layout.row_sections[r] = current_section
        layout.row_rubrics[r] = current_rubric

    # --- Disposition mensuelle ? ---
    header_row = -1
    date_cols: list[int] = []
    for r, row in enumerate(grid[:8]):
        cols = [c for c, v in enumerate(row) if _is_date(v)]
        if len(cols) >= 2:
            header_row, date_cols = r, sorted(cols)
            break

    if header_row != -1:
        layout.is_monthly = True
        sub = _measure_header(grid[header_row + 1]) if header_row + 1 < len(grid) else []
        for i, c in enumerate(date_cols):
            end = date_cols[i + 1] if i + 1 < len(date_cols) else None
            period = grid[header_row][c]
            period = datetime.date(period.year, period.month, 1)
            measures = {
                name: col for name, col in sub
                if col >= c and (end is None or col < end)
            }
            if not measures:
                measures = {"": c}
            layout.periods.append((period, measures))
        return layout

    # --- Disposition statique : les en-têtes de mesure peuvent se répéter ---
    current: dict[str, int] = {"": 1}
    for r, row in enumerate(grid):
        header = _measure_header(row)
        if header:
            # première occurrence conservée si un nom apparaît deux fois
            current = {}
            for name, col in header:
                current.setdefault(name, col)
        layout.row_measures[r] = dict(current)
    return layout


@dataclass
class Indicator:
    key: str                       # "<onglet>|<ligne>" — identifiant stable
    sheet: str
    row: int
    label: str
    section: str                   # sous-section (« B- Transactions SYSTAC »)
    rubric: str                    # titre du tableau (« CHEQUES », « VIREMENTS »…)
    is_monthly: bool
    measures: list[str]            # noms des mesures ("Nombre", "Valeur", ou "")
    display_name: str = ""         # libellé affiché, désambiguïsé si besoin
    has_data: bool = False         # au moins une valeur non nulle chez un établissement


# Lignes d'en-tête administratif du gabarit : ce ne sont pas des indicateurs.
# Liste volontairement courte et explicite (plutôt qu'une heuristique sur les
# libellés se terminant par « : », qui écarterait à tort « Nobre de clients : »
# ou « Nombre de comptes : », qui sont eux de véritables indicateurs).
_METADATA_LABELS = {
    "etablissement",
    "service",
    "reseau",
    "nom de l etablissement",
    "nature de l information",
}


def _libelle_voisin(grid: list[list], r: int, sens: int) -> str:
    """Libellé de la ligne renseignée la plus proche, au-dessus ou en dessous."""
    i = r + sens
    while 0 <= i < len(grid):
        row = grid[i]
        if row and isinstance(row[0], str) and row[0].strip():
            return row[0].strip()
        if row and any(v is not None for v in row):
            return ""       # ligne d'en-tête ou de données : on s'arrête
        i += sens
    return ""


def _element_de_liste(grid: list[list], r: int) -> bool:
    """La ligne appartient-elle à une ÉNUMÉRATION plutôt qu'à un titre ?

    Les gabarits listent les réseaux monétiques en capitales — Privative,
    GIMAC, VISA, MASTERCARD, UnionPay, American Express. Chacun est une ligne
    de données, mais celles qu'aucun établissement ne renseigne étaient prises
    pour des titres de tableau, faute de valeur : « VISA » devenait un titre
    dans Cartes 3, et « UnionPay » se retrouvait classé sous une rubrique
    « MASTERCARD ».

    Repère : un voisin immédiat est lui aussi en capitales. Un vrai bandeau
    (« TRANSACTIONS DE VOS PORTEURS ») est au contraire entouré de libellés
    en casse ordinaire.
    """
    for sens in (-1, 1):
        voisin = _libelle_voisin(grid, r, sens)
        if voisin and _upper_ratio(voisin) >= 0.85 and not _norm(voisin).startswith("total"):
            return True
    return False


def _ouvre_un_bloc(grid: list[list], r: int) -> bool:
    """La ligne `r` ouvre-t-elle un bloc de tableau ?

    Critère : elle ne porte aucune donnée et un en-tête de colonnes
    (« Nombre | Valeur ») la suit immédiatement. C'est la signature d'un
    titre comme « CHEQUES » ou « VIREMENTS », qui précède toujours l'en-tête
    de son tableau.

    La fenêtre est délibérément courte (deux lignes). Plus large, elle
    happerait la dernière ligne de données d'un bloc, qui se trouve à
    quelques lignes de l'en-tête du bloc suivant : « TOTAL (A+B+C) » ou
    « Annulation/remboursement » disparaissaient ainsi du récapitulatif.
    """
    if r >= len(grid):
        return False
    row = grid[r]
    if any(_is_number(v) and v != 0 for v in row[1:]):
        return False
    return any(_measure_header(nxt) for nxt in grid[r + 1:r + 3])


def _is_metadata_row(label: str) -> bool:
    if _norm(label) in _METADATA_LABELS:
        return True
    # Consigne de remplissage adressée à l'établissement, et non une ligne de
    # données : « (Pour chacun de vos réseaux d'acquisition, veuillez…) ».
    stripped = label.strip()
    return stripped.startswith("(") and len(stripped) > 20


def extraire_notes(institutions: list[Institution]) -> list[tuple[str, str]]:
    """Notes et définitions du gabarit (« (1) porteurs qui ont effectué… »).

    Exclues des indicateurs (ce sont des définitions, pas des données), elles
    restent une information utile pour comprendre les indicateurs : cette
    fonction les rend disponibles pour être affichées ailleurs (résumé),
    plutôt que simplement écartées et donc invisibles.

    Renvoie [(feuille, texte), ...], dédupliqué : le gabarit étant identique
    d'un établissement à l'autre, la même note apparaît dans chaque fichier.
    """
    notes: list[tuple[str, str]] = []
    vues: set[tuple[str, str]] = set()
    for sheet in KNOWN_SHEETS:
        presents = [i for i in institutions if sheet in i.sheets]
        if not presents:
            continue
        grid = presents[0].sheets[sheet].grid
        for row in grid:
            if not row or not isinstance(row[0], str):
                continue
            label = row[0].strip()
            if label.startswith("(") and len(label) > 20:
                cle = (sheet, label)
                if cle not in vues:
                    vues.add(cle)
                    notes.append(cle)
    return notes


def _label_at(grid: list[list], r: int) -> str:
    if r >= len(grid) or not grid[r]:
        return ""
    v = grid[r][0]
    return v.strip() if isinstance(v, str) and v.strip() else ""


_indicateurs_cache: dict[tuple, tuple[list, list]] = {}


def vider_cache_indicateurs() -> None:
    """Libère le cache de découverte d'indicateurs."""
    _indicateurs_cache.clear()


def discover_indicators(institutions: list[Institution], cartographie=None) -> list[Indicator]:
    """Découverte des indicateurs, MÉMORISÉE par jeu d'établissements.

    Un profilage a mesuré 46 découvertes complètes du gabarit pour une seule
    génération de résumé, toutes identiques : la découverte est déterministe
    à établissements et cartographie constants. Le cache est indexé sur
    l'IDENTITÉ des grilles chargées (jamais modifiées après lecture) et de
    la cartographie ; les objets sont conservés dans le cache, ce qui
    garantit que leurs identifiants ne peuvent pas être réattribués.
    """
    cle = (tuple((i.name, id(i.sheets)) for i in institutions), id(cartographie))
    en_cache = _indicateurs_cache.get(cle)
    if en_cache is not None:
        garde, resultat = en_cache
        return resultat

    resultat = _discover_indicators(institutions, cartographie)
    # `garde` retient les objets pour empêcher toute réattribution d'identifiant.
    _indicateurs_cache[cle] = ([i.sheets for i in institutions] + [cartographie], resultat)
    return resultat


def _discover_indicators(institutions: list[Institution], cartographie=None) -> list[Indicator]:
    """Toute ligne de tableau, dans tout onglet connu, portant un libellé.

    On expose la STRUCTURE COMPLÈTE du gabarit, y compris les lignes non
    renseignées (« - dont Cameroun », « - dont Tchad »…) : le fait qu'une
    ventilation soit vide est en soi une information de reporting. Chaque
    indicateur porte `has_data` pour permettre de filtrer à l'affichage.
    """
    indicators: list[Indicator] = []

    for sheet in KNOWN_SHEETS:
        present = [i for i in institutions if sheet in i.sheets]
        if not present:
            continue

        layouts = {i.name: analyze_layout(i.sheets[sheet].grid) for i in present}
        ref_layout = layouts[present[0].name]
        max_rows = max(len(i.sheets[sheet].grid) for i in present)

        by_label: dict[str, list[Indicator]] = {}
        pending: list[tuple[Indicator, str]] = []  # (indicateur, libellé parent)
        current_parent = ""
        for r in range(max_rows):
            raw_label = ""
            for inst in present:
                grid_i = inst.sheets[sheet].grid
                if r < len(grid_i) and grid_i[r] and isinstance(grid_i[r][0], str) and grid_i[r][0].strip():
                    raw_label = grid_i[r][0]
                    break
            label = raw_label.strip()
            if not label or _is_metadata_row(label):
                continue
            # La première ligne porte le titre de la feuille : c'est un
            # bandeau, jamais une ligne de données.
            if r == 0:
                continue

            ref_grid = present[0].sheets[sheet].grid
            ref_row = ref_grid[r] if r < len(ref_grid) else []
            # Exclusion volontairement RESTRICTIVE : seules sont écartées la
            # ligne d'en-tête de colonnes elle-même et la ligne qui OUVRE un
            # bloc de tableau, c'est-à-dire suivie de très près par cet
            # en-tête (« CHEQUES », puis « Nombre | Montant »).
            #
            # La détection de titre utilisée pour le REGROUPEMENT
            # (_looks_like_section) est bien plus large : elle retient toute
            # ligne en capitales. S'en servir ici faisait disparaître de
            # vraies lignes de données — « MASTERCARD », « VISA », « UnionPay »
            # ou tout le bloc « Fraude sur les cartes » n'étaient jamais
            # restitués, faute de valeur chez l'un des établissements.
            # Cartographie validée (assistée par le modèle local, cf.
            # core/cartographie.py) : elle prime sur les heuristiques, mais
            # uniquement si le libellé du fichier correspond toujours.
            role = cartographie.role(sheet, r, label) if cartographie is not None else None
            if role is not None:
                if role != "DONNEE":
                    current_parent = ""
                    continue
            elif _measure_header(ref_row) or _ouvre_un_bloc(ref_grid, r):
                current_parent = ""
                continue

            # Ventilation indentée (« - dont Cameroun ») : elle se rattache à
            # la dernière ligne de premier niveau. Sans cela, les ventilations
            # de « Transfert d'argent reçus » et de « Transfert d'argent
            # envoi » porteraient exactement le même nom.
            is_child = raw_label[:1].isspace() or label.startswith(("-", "–", "—"))
            parent = current_parent if is_child else ""
            if not is_child:
                current_parent = label

            has_data = False
            measure_names: list[str] = []
            for inst in present:
                grid = inst.sheets[sheet].grid
                lay = layouts[inst.name]
                if r >= len(grid):
                    continue
                if lay.is_monthly:
                    for _, measures in lay.periods:
                        for name, c in measures.items():
                            if name not in measure_names:
                                measure_names.append(name)
                            if c < len(grid[r]) and _is_real_data(grid[r][c]):
                                has_data = True
                else:
                    for name, c in lay.row_measures.get(r, {}).items():
                        if name not in measure_names:
                            measure_names.append(name)
                        if c < len(grid[r]) and _is_real_data(grid[r][c]):
                            has_data = True

            if not measure_names:
                continue

            ind = Indicator(
                key=f"{sheet}|{r}",
                sheet=sheet,
                row=r,
                label=label,
                section=ref_layout.row_sections.get(r, ""),
                rubric=ref_layout.row_rubrics.get(r, ""),
                is_monthly=ref_layout.is_monthly,
                measures=measure_names,
                has_data=has_data,
            )
            indicators.append(ind)
            pending.append((ind, parent))

        # Nommage : on n'ajoute du contexte que lorsqu'il est nécessaire pour
        # distinguer deux lignes homonymes du même onglet.
        for ind, parent in pending:
            base = f"{parent} › {ind.label}" if parent else ind.label
            by_label.setdefault(_norm(base), []).append((ind, base))

        for same in by_label.values():
            duplicated = len(same) > 1
            for ind, base in same:
                # Seule la sous-section est ajoutée au libellé : le titre du
                # tableau figure dans sa propre colonne à l'affichage, l'y
                # répéter ferait doublon.
                if duplicated and ind.section:
                    ind.display_name = f"{ind.section} › {base}"
                else:
                    ind.display_name = base

    return indicators


def latest_period_with_data(inst: Institution, ind: Indicator) -> Optional[datetime.date]:
    """Dernière période où l'indicateur porte une valeur, TOUTES mesures
    confondues.

    Indispensable pour que « Nombre » et « Valeur » d'une même ligne soient
    toujours lus sur le MÊME mois : sinon, si une seule des deux colonnes est
    renseignée au dernier mois, on afficherait côte à côte des valeurs issues
    de mois différents.
    """
    sd = inst.sheets.get(ind.sheet)
    if sd is None or ind.row >= len(sd.grid):
        return None
    lay = analyze_layout(sd.grid)
    if not lay.is_monthly:
        return None
    row = sd.grid[ind.row]
    for period, measures in reversed(lay.periods):
        for c in measures.values():
            if c < len(row) and _is_number(row[c]) and row[c] != 0:
                return period
    return None


def indicator_value(inst: Institution, ind: Indicator, measure: str,
                    period: Optional[datetime.date] = None) -> float:
    """Valeur d'un indicateur pour un établissement.
    Pour un indicateur mensuel, `period` cible un mois précis ; sans période,
    la dernière période renseignée de la ligne est retenue (la même pour
    toutes ses mesures, cf. latest_period_with_data)."""
    sd = inst.sheets.get(ind.sheet)
    if sd is None or ind.row >= len(sd.grid):
        return 0
    grid = sd.grid
    lay = analyze_layout(grid)
    row = grid[ind.row]

    if lay.is_monthly:
        target = period or latest_period_with_data(inst, ind)
        if target is None:
            return 0
        for p, measures in lay.periods:
            if p != target:
                continue
            c = measures.get(measure)
            if c is not None and c < len(row) and _is_number(row[c]):
                return row[c]
        return 0

    c = lay.row_measures.get(ind.row, {}).get(measure)
    if c is None or c >= len(row):
        return 0
    return row[c] if _is_number(row[c]) else 0


def indicator_totals(institutions: list[Institution], ind: Indicator,
                     measure: str) -> tuple[list[tuple[str, float]], float]:
    per_inst = [(i.name, indicator_value(i, ind, measure)) for i in institutions]
    return per_inst, sum(v for _, v in per_inst)


def indicator_periods(institutions: list[Institution], ind: Indicator) -> list[datetime.date]:
    periods: set[datetime.date] = set()
    for inst in institutions:
        sd = inst.sheets.get(ind.sheet)
        if sd is None:
            continue
        lay = analyze_layout(sd.grid)
        for p, _ in lay.periods:
            periods.add(p)
    return sorted(periods)


def _est_mesure_monetaire(mesure: str) -> bool:
    """Une mesure est monétaire (XAF) si son nom contient « valeur » ou
    « montant », mais pas « nombre » — écarte donc les mesures de comptage
    dont le nom contient malgré tout ces mots (« Nombre de cartes »,
    « Montants octroyés » compte comme monétaire, « Nombre de transactions
    frauduleuses » comme un comptage)."""
    n = (mesure or "").strip().lower()
    if "nombre" in n:
        return False
    return "valeur" in n or "montant" in n


def _est_ligne_calculee(label: str) -> bool:
    """Une ligne de SOUS-TOTAL ou de VENTILATION (« Total (B) »,
    « - dont Cameroun »…), à exclure d'une somme « tout confondu » : sans
    ce filtre, le montant d'un sous-total s'additionnerait à celui de sa
    propre ligne de détail, comptant le même argent deux fois."""
    n = label.strip().lower()
    return n.startswith("total") or n.startswith("- dont") or n.startswith("-dont")


def montant_total_argent(institutions: list[Institution]) -> float:
    """Somme de TOUTES les valeurs monétaires (XAF) trouvées sur l'ensemble
    des indicateurs découverts, tous thèmes confondus — le grand total
    « tout l'argent confondu » demandé pour la vue par pays.

    Exclut les lignes de sous-total et les ventilations « - dont » pour
    éviter de compter deux fois le même argent (une somme brute, structurée
    uniquement par ce que le gabarit distingue lui-même comme des lignes de
    détail — pas un agrégat comptable au sens strict, faute d'une relation
    garantie entre chaque sous-catégorie et le total dont elle relève)."""
    total = 0.0
    for ind in discover_indicators(institutions):
        if _est_ligne_calculee(ind.label):
            continue
        for mesure in ind.measures:
            if _est_mesure_monetaire(mesure):
                _, t = indicator_totals(institutions, ind, mesure)
                total += t
    return total


def indicator_series(institutions: list[Institution], ind: Indicator,
                     measure: str) -> list[tuple[datetime.date, dict[str, float]]]:
    """Série mensuelle : [(période, {établissement: valeur}), ...]"""
    out = []
    for p in indicator_periods(institutions, ind):
        out.append((p, {i.name: indicator_value(i, ind, measure, p) for i in institutions}))
    return out
