"""
core/montant_total.py

Un seul montant XAF « toutes activités confondues », par établissement (et
donc agrégeable par pays ou pour l'ensemble CEMAC).

Ce calcul est délibérément CURATÉ plutôt qu'auto-détecté ligne par ligne :
une exploration systématique des lignes « Total » du gabarit a révélé deux
pièges concrets qui auraient faussé le montant, silencieusement, si le
choix des lignes avait été laissé à une simple recherche de mots-clés :

1. Sur plusieurs thèmes (Transfert d'argent, MobileMoney3, Cartes 2,
   Cartes 5), le total « toutes zones confondues » (rubrique vide ou de
   tête) est immédiatement suivi de deux sous-totaux par zone (« A- zone
   CEMAC », « B- hors CEMAC ») qui s'additionnent pour redonner exactement
   le même total. Additionner les trois revient à compter deux fois les
   mêmes transactions.

2. À l'inverse, sur Cartes 2 et Cartes 5, le total de tête (« Total
   A=B+C+D ») est parfois resté VIDE dans le fichier source alors que ses
   propres composantes B/C/D sont, elles, correctement renseignées (constaté
   directement sur BanqueA : Total A=B+C+D = 0, alors que B seul vaut déjà
   11,68 Md XAF). Ignorer les composantes quand le total de tête est vide
   ferait disparaître de l'argent réel.

Chaque entrée ci-dessous a donc été choisie à la main après inspection du
gabarit officiel, avec un repli automatique sur la somme des composantes
quand la ligne de tête n'est pas renseignée. Le détail exact des lignes
retenues est documenté ligne par ligne : c'est un choix vérifiable et
corrigeable, pas une boîte noire.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.indicators import analyze_layout, discover_indicators, indicator_totals

# Mémoïsation de la découverte d'indicateurs : c'est l'opération la plus
# coûteuse du calcul, et elle était relancée pour chaque composante
# mensuelle (plusieurs fois par appel, puis à nouveau pour chaque pays et
# pour le détail). La conserver le temps d'une génération d'export évite ce
# travail répété, qui se ressentait directement sur le temps d'attente.
_CACHE_INDEX: dict[tuple, dict] = {}


def _cle_cache(institutions) -> tuple:
    return tuple(id(i) for i in institutions)


def _index_indicateurs(institutions) -> dict:
    """{(feuille, ligne): indicateur} — calculé une fois par jeu
    d'établissements, puis réutilisé."""
    cle = _cle_cache(institutions)
    if cle not in _CACHE_INDEX:
        _CACHE_INDEX[cle] = {(i.sheet, i.row): i for i in discover_indicators(institutions)}
    return _CACHE_INDEX[cle]


def vider_cache() -> None:
    """À appeler si les établissements sont rechargés — évite de conserver
    un index devenu obsolète."""
    _CACHE_INDEX.clear()
from core.kpis import compute_kpis
from typing import Optional

from core.parsing import Institution, SheetData, _grille_pour_fusion
from core.sheet_matching import mesures_statiques_canoniques


def _norm_mesure(mesure: str) -> str:
    """Le référentiel stocke les noms de mesure normalisés (minuscules, sans
    accent) : « Valeur » y est enregistré « valeur »."""
    import unicodedata
    s = unicodedata.normalize("NFKD", (mesure or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c)).strip()

# Un saut de plus de ce facteur par rapport au mois précédent est signalé
# plutôt qu'inclus tel quel dans le total — découvert concrètement sur un
# fichier réel : une ligne « Transfert d'argent » de MobileMoney2 affichait
# 5 097 milliards XAF pour un mois, contre ~9-17 milliards les mois
# voisins — une valeur près de 300 fois supérieure, signe quasi certain
# d'une erreur de saisie (chiffres fusionnés) plutôt que d'une activité
# réelle. Le seuil reste large pour ne jamais signaler à tort une
# croissance organique, même rapide.
FACTEUR_ANOMALIE = 15


@dataclass
class _Composante:
    sheet: str
    ligne_tete: int | None       # None si la catégorie n'a pas de sous-niveau
    mesure: str
    lignes_repli: list[int]      # sous-composantes utilisées si la tête est vide
    description: str
    # Second niveau de repli : les lignes DÉTAILLÉES d'une seule zone
    # (jamais plusieurs zones ensemble, sous peine de compter le même
    # argent deux fois — cf. le repli lui-même, qui est DÉJÀ une
    # décomposition de la tête). Cas réel trouvé chez un établissement
    # réel : même les sous-totaux de zone (B/C/D) étaient remplis
    # d'espaces au lieu de nombres, alors que les lignes détaillées
    # elles-mêmes (paiements, retraits GAB…) portaient de vraies données.
    lignes_repli_profond: list[int] = field(default_factory=list)


# Chaque composante est une catégorie économique distincte : aucune ne
# recouvre une autre, pour ne jamais compter le même argent deux fois.
_COMPOSANTES: list[_Composante] = [
    # chèques&VIR : trois rubriques parallèles (chèques / virements / effets
    # de commerce), chacune avec son propre total de tête — pas de
    # sous-niveau à ce total, donc pas de repli nécessaire.
    _Composante("chèques&VIR", 15, "Montant", [], "Chèques — total"),
    _Composante("chèques&VIR", 26, "Montant", [], "Virements — total"),
    # Prélèvements et retraits manuels : deux rubriques entières du thème
    # chèques&VIR, omises jusqu'ici — trouvées en réauditant les calculs
    # après un signalement de l'utilisateur. Chacune tient sur une seule
    # ligne (pas de sous-composantes A/B/C à additionner), mais porte de
    # vrais montants substantiels chez plusieurs établissements réels
    # (plusieurs milliers de milliards de XAF chez un seul établissement) :
    # les omettre sous-évaluait le montant total, silencieusement.
    _Composante("chèques&VIR", 31, "Montant", [], "Prélèvements — total"),
    _Composante("chèques&VIR", 48, "Montant", [], "Retraits manuels — total"),
    _Composante("chèques&VIR", 43, "Montant", [], "Effets de commerce — total"),

    # Transfert d'argent : le total de tête (toutes zones) équivaut déjà à
    # la somme des zones CEMAC + hors CEMAC — ne jamais additionner les
    # trois.
    _Composante("Transfert d'argent", 9, "valeur", [27, 49], "Transfert d'argent — total"),

    # MobileMoney2 : cinq catégories parallèles (recharge, transfert,
    # retraits automates, retraits guichet, paiement), sans total combiné —
    # chacune est sa propre ligne, jamais un sous-total d'une autre.
    _Composante("MobileMoney2", 5, "Valeur", [], "Mobile Money — recharges"),
    _Composante("MobileMoney2", 6, "Valeur", [], "Mobile Money — transferts"),
    _Composante("MobileMoney2", 7, "Valeur", [], "Mobile Money — retraits automates"),
    _Composante("MobileMoney2", 8, "Valeur", [], "Mobile Money — retraits guichet"),
    _Composante("MobileMoney2", 9, "Valeur", [], "Mobile Money — paiements"),

    # MobileMoney3 : même piège que Transfert d'argent (total de tête déjà
    # égal à CEMAC + hors CEMAC).
    _Composante("MobileMoney3", 8, "valeur", [27, 50], "Mobile Money — transactions interopérables"),

    # Cartes 2 : le total de tête (A=B+C+D) est parfois vide alors que ses
    # composantes (banque / CEMAC / international) sont renseignées —
    # d'où le repli.
    _Composante("Cartes 2", 10, "Valeur", [20, 30, 40], "Cartes — transactions en émission",
               lignes_repli_profond=[4, 6, 7, 8, 9]),

    # Cartes 4 (« PAIEMENTS PAR CARTES », ventilé par secteur d'activité)
    # est délibérément EXCLU : c'est une ventilation sectorielle d'un
    # montant déjà compté ailleurs, pas une catégorie supplémentaire. Le
    # seul établissement des fichiers réels qui la renseigne affiche un
    # montant à 0,7 % de ses paiements en acquisition (Cartes 5, bloc 2) —
    # écart bien trop faible pour être une coïncidence. L'inclure gonflerait
    # le total en comptant deux fois les mêmes paiements.

    # Cartes 5 : DEUX blocs parallèles et indépendants (retraits d'un côté,
    # TPE/paiements de l'autre) — chacun avec son propre risque de total de
    # tête vide.
    _Composante("Cartes 5", 8, "Valeur", [12, 16, 20], "Cartes — retraits (bloc 1)",
               lignes_repli_profond=[6, 7]),
    _Composante("Cartes 5", 27, "Valeur", [32, 37, 43], "Cartes — TPE et paiements (bloc 2)",
               lignes_repli_profond=[24, 26]),
]


def _valeur_a(institutions: list[Institution], sheet: str, row: int, mesure: str) -> float:
    """Valeur d'une ligne précise (feuille + position), 0 si absente.

    Sur un thème STATIQUE, la lecture se fait par POSITION DE COLONNE
    canonique plutôt que par nom de mesure. C'est indispensable : quand une
    feuille a été reconstituée depuis un onglet composite (cf.
    core.sheet_matching.detecter_segments), sa ligne d'en-tête
    « Nombre / Valeur » ne fait pas toujours partie des lignes appariées —
    les mesures deviennent alors anonymes et une recherche par nom renvoie
    0 alors que la donnée est bien là. Constaté concrètement : un
    établissement affichait 0 XAF de montant total alors que ses feuilles
    Cartes contenaient plus de 16 milliards.

    Sur un thème MENSUEL (Mobile Money…), il n'existe pas de colonne fixe :
    on repasse alors par la logique d'indicateurs, qui sait retenir le
    dernier mois renseigné.
    """
    if not institutions or not any(sheet in i.sheets for i in institutions):
        return 0.0

    mesures_canoniques = mesures_statiques_canoniques(sheet)
    if mesures_canoniques:
        colonne = mesures_canoniques.get(_norm_mesure(mesure))
        if colonne is None:
            return 0.0
        total = 0.0
        for inst in institutions:
            if sheet not in inst.sheets:
                continue
            grid = inst.sheets[sheet].grid
            if row < len(grid) and colonne < len(grid[row]):
                v = grid[row][colonne]
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    total += v
        return total

    index = _index_indicateurs(institutions)
    ind = index.get((sheet, row))
    if ind is None:
        return 0.0
    _, total = indicator_totals(institutions, ind, mesure)
    return total or 0.0


# PrêtsCredits est le seul thème du gabarit structuré en tableau à nombre
# de LIGNES VARIABLE (une ligne par type de prêt proposé, pas une position
# fixe) : « Montants octroyés » est toujours en colonne D (index 3), à
# partir de la ligne 4 (index 3), quel que soit le nombre de lignes
# remplies par l'établissement. Ce thème était totalement absent du calcul
# jusqu'ici — trouvé en réauditant après un signalement de l'utilisateur :
# un seul établissement réel y avait 3 820 lignes de prêts représentant
# 14,5 Md XAF, jamais comptés.
_COL_MONTANTS_OCTROYES = 3
_LIGNE_DEBUT_PRETS = 3


def _montant_prets_credits(institutions: list[Institution]) -> float:
    total = 0.0
    for inst in institutions:
        sd = inst.sheets.get("PrêtsCredits")
        if not sd:
            continue
        for row in sd.grid[_LIGNE_DEBUT_PRETS:]:
            if len(row) > _COL_MONTANTS_OCTROYES:
                v = row[_COL_MONTANTS_OCTROYES]
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    total += v
    return total


def _nombre_prets_credits(institutions: list[Institution]) -> int:
    """Nombre de prêts octroyés (une ligne du tableau = un prêt), plutôt
    que leur montant — les deux mesures sont utiles côte à côte, exactement
    comme Nombre et Montant pour les autres thèmes."""
    total = 0
    for inst in institutions:
        sd = inst.sheets.get("PrêtsCredits")
        if not sd:
            continue
        for row in sd.grid[_LIGNE_DEBUT_PRETS:]:
            if len(row) > _COL_MONTANTS_OCTROYES and isinstance(row[_COL_MONTANTS_OCTROYES], (int, float)) \
                    and not isinstance(row[_COL_MONTANTS_OCTROYES], bool):
                total += 1
    return total


def _anomalie_mensuelle(institutions: list[Institution], sheet: str, row: int, mesure: str) -> bool:
    """Signale un saut invraisemblable entre le dernier mois retenu et le
    mois précédent — jamais une correction silencieuse, seulement un signal
    pour que la valeur reste vérifiable avant d'être présentée comme un
    total fiable. Sans objet sur un thème statique (une seule valeur, rien
    à comparer)."""
    for inst in institutions:
        if sheet not in inst.sheets:
            continue
        grid = inst.sheets[sheet].grid
        layout = analyze_layout(grid)
        if not layout.is_monthly or row >= len(grid):
            continue
        valeurs = []
        for _periode, mesures in layout.periods:
            col = mesures.get(mesure)
            if col is not None and col < len(grid[row]):
                v = grid[row][col]
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    valeurs.append(v)
        non_nulles = [v for v in valeurs if v]
        if len(non_nulles) < 2:
            continue
        dernier, precedent = non_nulles[-1], non_nulles[-2]
        if precedent and abs(dernier) > FACTEUR_ANOMALIE * abs(precedent):
            return True
    return False


@dataclass
class _ResultatComposante:
    description: str
    valeur: float
    anomalie: bool
    via_composantes: bool


_RESEAUX_CARTES = ["GIMAC", "MASTERCARD", "VISA", "UNIONPAY", "DISCOVER", "AMEX"]


def _extraire_reseau(nom_onglet: str) -> Optional[str]:
    """Nom de réseau de carte porté par un onglet source (« Cartes 2
    GIMAC », « Cartes 4 VISA »…), s'il y en a un. MASTERCARD est cherché
    avant VISA pour éviter qu'un nom composé ne matche le mauvais réseau."""
    nom_maj = nom_onglet.upper()
    for reseau in _RESEAUX_CARTES:
        if reseau in nom_maj:
            return reseau
    return None


def repartition_par_reseau(
        fichiers: list[tuple[str, bytes, Optional[str]]], theme: str
) -> list[tuple[str, dict[str, dict[str, float]]]]:
    """Répartition par RÉSEAU de carte (GIMAC, VISA…), par pays — une
    information normalement FONDUE dans le thème consolidé (Cartes 2 GIMAC
    + Cartes 2 VISA sont additionnés en un seul « Cartes 2 » lors de la
    fusion), et donc invisible dans calculer_composantes /
    repartition_par_pays_et_rubrique. Reconstituée en ré-analysant
    structurellement chaque onglet source dont le nom porte un réseau
    connu, indépendamment de la consolidation principale — jamais en la
    modifiant, pour ne rien risquer sur ce qui est déjà vérifié.

    `fichiers` : liste de (nom_fichier, contenu_brut_xlsx, code_pays).
    Renvoie [] si aucun établissement ne segmente ce thème par réseau.
    """
    composantes_theme = [c for c in _COMPOSANTES if c.sheet == theme]
    if not composantes_theme:
        return []
    comp = composantes_theme[0]

    import io as _io

    import openpyxl as _openpyxl

    from core.sheet_matching import reconnaitre_onglet

    par_reseau: dict[str, dict[str, dict[str, float]]] = {}
    for nom_fichier, contenu, pays in fichiers:
        if not pays:
            continue
        try:
            wb = _openpyxl.load_workbook(_io.BytesIO(contenu), data_only=True)
        except Exception:
            continue
        for nom_onglet in wb.sheetnames:
            reseau = _extraire_reseau(nom_onglet)
            if not reseau:
                continue
            grid = [[c.value for c in row] for row in wb[nom_onglet].iter_rows()]
            reconnaissance = reconnaitre_onglet(nom_onglet, grid, {theme})
            if reconnaissance.theme != theme:
                continue
            grid_canon = _grille_pour_fusion(grid, reconnaissance)
            inst_temp = Institution(f"{nom_fichier}-{reseau}", nom_fichier,
                                    {theme: SheetData(grid=grid_canon, errors=[], text_numbers=[])})
            nombre = _valeur_a([inst_temp], theme, comp.ligne_tete, "Nombre")
            if nombre == 0 and comp.lignes_repli:
                nombre = sum(_valeur_a([inst_temp], theme, r, "Nombre") for r in comp.lignes_repli)
            if nombre == 0 and comp.lignes_repli_profond:
                nombre = sum(_valeur_a([inst_temp], theme, r, "Nombre") for r in comp.lignes_repli_profond)
            montant = _valeur_a([inst_temp], theme, comp.ligne_tete, comp.mesure)
            if montant == 0 and comp.lignes_repli:
                montant = sum(_valeur_a([inst_temp], theme, r, comp.mesure) for r in comp.lignes_repli)
            if montant == 0 and comp.lignes_repli_profond:
                montant = sum(_valeur_a([inst_temp], theme, r, comp.mesure) for r in comp.lignes_repli_profond)
            if not (nombre or montant):
                continue
            case = par_reseau.setdefault(reseau, {}).setdefault(pays, {"Nombre": 0.0, "Montant": 0.0})
            case["Nombre"] += nombre
            case["Montant"] += montant
        wb.close()

    return [(reseau, par_pays) for reseau, par_pays in par_reseau.items() if par_pays]


def repartition_par_pays_et_rubrique(
        institutions: list[Institution], theme: str
) -> list[tuple[str, dict[str, dict[str, float]]]]:
    """Pour un thème du gabarit, calcule — pour chaque rubrique déjà
    identifiée dans _COMPOSANTES (Chèques, Virements, Prélèvements…) — le
    Nombre et le Montant, PAR PAYS. Sert de socle aux camemberts interactifs
    de l'application pour les thèmes qui n'ont pas de disposition mensuelle
    (aucune évolution à tracer, mais une vraie répartition à visualiser).

    Réutilise les mêmes lignes que le montant total par pays — déjà
    vérifiées (jamais de double comptage entre un total de tête et ses
    propres sous-zones, repli sur les composantes quand le total de tête
    est vide) — plutôt qu'une nouvelle extraction ad hoc.

    Renvoie [] si ce thème n'a aucune composante définie (thèmes
    exclusivement mensuels, ou exclusivement comptés — Cartes1, Cartes 3).
    """
    composantes_theme = [c for c in _COMPOSANTES if c.sheet == theme]
    if not composantes_theme and theme not in ("PrêtsCredits", "Cartes1"):
        return []

    par_pays: dict[str, list[Institution]] = {}
    for inst in institutions:
        if inst.pays:
            par_pays.setdefault(inst.pays, []).append(inst)
    if not par_pays:
        return []

    if theme == "Cartes1":
        # Thème exclusivement compté (aucune colonne Montant) : les 3
        # indicateurs déjà fiabilisés de compute_kpis (par recherche de
        # libellé, pas par position fixe) servent directement de rubriques
        # — plutôt qu'une nouvelle logique d'extraction pour ce seul cas.
        resultats_cartes1 = []
        for cle, label in [("clients_cartes", "Clients porteurs de cartes"),
                           ("comptes_cartes", "Comptes cartes"),
                           ("cartes_debit", "Cartes de débit émises")]:
            valeurs_par_pays = {}
            for code, insts_pays in par_pays.items():
                valeur = next((k.total for k in compute_kpis(insts_pays) if k.key == cle), 0)
                if valeur:
                    valeurs_par_pays[code] = {"Nombre": valeur, "Montant": 0}
            if valeurs_par_pays:
                resultats_cartes1.append((label, valeurs_par_pays))
        return resultats_cartes1

    if theme == "PrêtsCredits":
        # Tableau à lignes variables (un prêt par ligne) : pas de position
        # fixe à interroger comme les autres thèmes, mais une seule
        # rubrique globale reste tout à fait exploitable en camembert.
        valeurs_par_pays = {
            code: {"Nombre": _nombre_prets_credits(insts_pays), "Montant": _montant_prets_credits(insts_pays)}
            for code, insts_pays in par_pays.items()
        }
        valeurs_par_pays = {c: v for c, v in valeurs_par_pays.items() if v["Montant"] or v["Nombre"]}
        return [("Prêts / crédits octroyés — total", valeurs_par_pays)] if valeurs_par_pays else []

    resultats = []
    for comp in composantes_theme:
        valeurs_par_pays: dict[str, dict[str, float]] = {}
        for code, insts_pays in par_pays.items():
            nombre = _valeur_a(insts_pays, comp.sheet, comp.ligne_tete, "Nombre")
            if nombre == 0 and comp.lignes_repli:
                nombre = sum(_valeur_a(insts_pays, comp.sheet, r, "Nombre") for r in comp.lignes_repli)
            if nombre == 0 and comp.lignes_repli_profond:
                nombre = sum(_valeur_a(insts_pays, comp.sheet, r, "Nombre") for r in comp.lignes_repli_profond)
            montant = _valeur_a(insts_pays, comp.sheet, comp.ligne_tete, comp.mesure)
            if montant == 0 and comp.lignes_repli:
                montant = sum(_valeur_a(insts_pays, comp.sheet, r, comp.mesure) for r in comp.lignes_repli)
            if montant == 0 and comp.lignes_repli_profond:
                montant = sum(_valeur_a(insts_pays, comp.sheet, r, comp.mesure) for r in comp.lignes_repli_profond)
            if nombre or montant:
                valeurs_par_pays[code] = {"Nombre": nombre, "Montant": montant}
        if valeurs_par_pays:
            resultats.append((comp.description, valeurs_par_pays))
    return resultats


def calculer_composantes(institutions: list[Institution]) -> list[_ResultatComposante]:
    """Version publique de _calculer_composantes — réutilisée par
    l'application pour bâtir un tableau « Indicateurs clés » qui couvre
    les 11 thèmes du gabarit, pas seulement Mobile Money1/Cartes1/Cartes 5.

    Inclut aussi PrêtsCredits (tableau à nombre de lignes variable, sommé
    différemment des autres thèmes) : sans cet ajout, le tableau de
    l'application resterait incomplet même après sa correction dans
    montant_total_argent / detail_montant_total — une seule fonction reste
    la source de vérité pour tous les usages."""
    resultats = _calculer_composantes(institutions)
    resultats.append(_ResultatComposante(
        description="Prêts / crédits octroyés — total",
        valeur=_montant_prets_credits(institutions),
        anomalie=False,
        via_composantes=False,
    ))
    return resultats


# Regroupement des 17 lignes détaillées en 5 grandes familles d'activité —
# un tableau « Indicateurs clés » de 17 lignes montrait beaucoup, mais
# noyait les montants importants dans le détail. Chaque ligne d'origine
# reste néanmoins comptée exactement une fois : rien n'est perdu, juste
# regroupé sous un intitulé plus lisible.
_CATEGORIES = {
    "Chèques, virements & effets de commerce — total": {
        "Chèques — total", "Virements — total", "Prélèvements — total",
        "Effets de commerce — total", "Retraits manuels — total",
    },
    "Transfert d'argent — total": {"Transfert d'argent — total"},
    "Mobile Money — flux total": {
        "Mobile Money — recharges", "Mobile Money — transferts",
        "Mobile Money — retraits automates", "Mobile Money — retraits guichet",
        "Mobile Money — paiements", "Mobile Money — transactions interopérables",
    },
    "Cartes — transactions totales": {
        "Cartes — transactions en émission", "Cartes — paiements en acquisition",
        "Cartes — retraits (bloc 1)", "Cartes — TPE et paiements (bloc 2)",
    },
    "Prêts / crédits octroyés — total": {"Prêts / crédits octroyés — total"},
}


def composantes_par_categorie(institutions: list[Institution]) -> list[_ResultatComposante]:
    """Vue resserrée pour le tableau « Indicateurs clés » : 5 grandes
    familles d'activité plutôt que 17 lignes détaillées — moins
    d'indicateurs, chacun plus représentatif. Le détail complet reste
    disponible via calculer_composantes (utilisé dans les exports)."""
    detail = {c.description: c for c in calculer_composantes(institutions)}
    resultats = []
    for categorie, membres in _CATEGORIES.items():
        valeur = sum(detail[m].valeur for m in membres if m in detail)
        anomalie = any(detail[m].anomalie for m in membres if m in detail)
        resultats.append(_ResultatComposante(categorie, valeur, anomalie, via_composantes=False))
    return resultats


def _calculer_composantes(institutions: list[Institution]) -> list[_ResultatComposante]:
    """Composantes calculées ÉTABLISSEMENT PAR ÉTABLISSEMENT, puis sommées.

    Indispensable pour l'additivité : si une composante est jugée
    invraisemblable chez un établissement, seule SA contribution doit être
    écartée — pas celle de ses voisins. Un calcul mené sur le groupe entier
    excluait la composante pour tout le monde, si bien que le total CEMAC
    ne valait plus la somme des totaux par pays (écart constaté : le
    montant entier d'un établissement, disparu du total d'ensemble alors
    qu'il figurait bien dans le total de son pays).
    """
    agrege: dict[str, _ResultatComposante] = {}
    for comp in _COMPOSANTES:
        agrege[comp.description] = _ResultatComposante(comp.description, 0.0, False, False)

    for inst in institutions:
        seul = [inst]
        for comp in _COMPOSANTES:
            anomalie = _anomalie_mensuelle(seul, comp.sheet, comp.ligne_tete, comp.mesure)
            valeur = _valeur_a(seul, comp.sheet, comp.ligne_tete, comp.mesure)
            via_composantes = False
            if valeur == 0 and comp.lignes_repli:
                valeur = sum(_valeur_a(seul, comp.sheet, r, comp.mesure) for r in comp.lignes_repli)
                anomalie = any(_anomalie_mensuelle(seul, comp.sheet, r, comp.mesure)
                              for r in comp.lignes_repli)
                via_composantes = True
            # Second niveau de repli : cas réel trouvé chez un
            # établissement réel où même les sous-totaux de zone (B/C/D)
            # étaient remplis d'espaces au lieu de nombres, alors que les
            # lignes détaillées elles-mêmes (paiements, retraits GAB…)
            # portaient de vraies données — 6,3 Md XAF de retraits qui
            # auraient silencieusement disparu du total sans ce repli.
            if valeur == 0 and comp.lignes_repli_profond:
                valeur = sum(_valeur_a(seul, comp.sheet, r, comp.mesure) for r in comp.lignes_repli_profond)
                anomalie = any(_anomalie_mensuelle(seul, comp.sheet, r, comp.mesure)
                              for r in comp.lignes_repli_profond)
                via_composantes = True

            cumul = agrege[comp.description]
            if anomalie:
                # La valeur reste visible dans le détail (pour rester
                # vérifiable), mais la composante est marquée : elle sera
                # écartée du total.
                cumul.anomalie = True
            cumul.valeur += valeur
            cumul.via_composantes = cumul.via_composantes or via_composantes

    return list(agrege.values())


def montant_total_argent(institutions: list[Institution]) -> float:
    """Somme, toutes activités confondues, en XAF — pour un sous-ensemble
    d'établissements donné (un pays, ou l'ensemble CEMAC).

    Additif par construction : le total d'un groupe vaut toujours la somme
    des totaux de ses membres, donc le total CEMAC vaut exactement la somme
    des totaux par pays.

    Une composante signalée comme invraisemblable (saut brutal d'un mois à
    l'autre, cf. FACTEUR_ANOMALIE) est EXCLUE de ce total plutôt que d'y
    être intégrée telle quelle — mieux vaut un total légèrement incomplet
    qu'un total gonflé par une donnée source manifestement erronée. Elle
    reste néanmoins visible, avec l'avertissement, dans `detail_montant_total`.

    Inclut aussi l'encours de monnaie électronique (une donnée de STOCK,
    pas de flux, mais explicitement demandée comme faisant partie des
    « sommes d'argent » à additionner) — repris depuis l'indicateur déjà
    validé, pour ne jamais dupliquer sa logique de calcul.
    """
    total = 0.0
    for inst in institutions:
        total += sum(r.valeur for r in calculer_composantes([inst]) if not r.anomalie)
        total += next((k.total for k in compute_kpis([inst]) if k.key == "encours_me"), 0.0)
    return total


def detail_montant_total(institutions: list[Institution]) -> list[tuple[str, float, bool]]:
    """Détail ligne par ligne du montant total — pour affichage transparent
    dans les exports, plutôt qu'un chiffre unique sans justification.

    Renvoie [(libellé, valeur, anomalie), ...] : une ligne marquée anomalie
    est affichée mais EXCLUE du total (cf. montant_total_argent) — jamais
    supprimée silencieusement, toujours vérifiable."""
    detail = []
    for r in calculer_composantes(institutions):
        libelle = r.description + (" (via composantes)" if r.via_composantes else "")
        detail.append((libelle, r.valeur, r.anomalie))

    encours = next((k.total for k in compute_kpis(institutions) if k.key == "encours_me"), 0.0)
    detail.append(("Encours de monnaie électronique", encours, False))
    return detail
