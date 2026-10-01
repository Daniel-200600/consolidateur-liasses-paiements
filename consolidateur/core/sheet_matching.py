"""
core/sheet_matching.py

Reconnaissance de familles d'onglets.

Contexte : le gabarit officiel BEAC demande explicitement, pour certains
thèmes (« Cartes 2 », « Transfert d'argent »…), de « remplir un formulaire
pour chaque réseau ». Un établissement qui suit cette consigne à la lettre
produit plusieurs onglets (« Cartes 2 GIMAC », « Cartes 2 VISA »…) là où
BanqueA, notre référence initiale, n'en produisait qu'un seul. D'autres
séparent par système de règlement (SYGMA, SYSTAC, FOREX) ou par prestataire
(WESTERN UNION, RIA, MoneyGram), parfois sans même conserver d'onglet « de
base ».

Principe : un onglet dont le NOM ne correspond à aucun des 11 thèmes connus
peut néanmoins être rattaché à un thème si sa structure interne — la
succession de ses lignes non vides — concorde substantiellement avec le
gabarit officiel, MÊME SI une ligne a été insérée ou supprimée quelque part
(une ligne vide en trop en haut de fichier, par exemple, décale sinon tout
le reste et ferait échouer une comparaison position par position pourtant
légitime). L'alignement se fait donc par plus longue sous-séquence commune
(LCS) sur l'ordre des lignes, pas par simple égalité de position.

La correspondance ne se fie jamais au seul nom, et le seuil est délibérément
prudent : mieux vaut laisser un onglet légitime en attente de rattachement
manuel que consolider à tort un onglet qui n'a rien à voir — une erreur dans
ce sens fausserait un total réglementaire sans laisser aucune trace visible.
"""

from __future__ import annotations

import json
from collections import Counter
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

REFERENCE_PATH = Path(__file__).resolve().parent / "reference" / "gabarit_beac.json"

def empreinte_libelles(grid: list[list]) -> list[tuple[int, str]]:
    """Séquence du libellé le plus SPÉCIFIQUE des colonnes A et B, ligne par
    ligne — le plus long des deux textes normalisés, pas leur concaténation.

    Complète `sequence()` (empreinte ligne entière) pour un cas réel
    rencontré : un établissement peut suivre un thème mensuel (colonnes par
    mois, comme Mobile Money) là où le gabarit de référence est statique
    (une seule paire Nombre/Valeur). La comparaison ligne entière échoue
    alors quasi systématiquement, alors que les LIBELLÉS eux-mêmes
    (« Transfert d'argent reçus », « - dont Cameroun »…) sont rigoureusement
    identiques — c'est cette empreinte, plus étroite mais plus robuste aux
    différences de mise en page, qui les retrouve.

    Le plus long des deux textes est retenu plutôt que leur concaténation :
    certains établissements placent le titre de rubrique et le libellé de
    la première ligne de données SUR LA MÊME LIGNE (« TOTAL (A+B) » en
    colonne A, « Transfert d'argent reçus » en colonne B) — une
    concaténation romprait alors la correspondance avec la référence, où le
    libellé de donnée occupe seul sa propre ligne."""
    out = []
    for r, row in enumerate(grid):
        candidats = [_norm(v) for v in row[:2] if isinstance(v, str) and v.strip()]
        if candidats:
            out.append((r, max(candidats, key=len)))
    return out


def colonne_libelle_candidat(grid: list[list], ligne: int) -> Optional[int]:
    """Colonne (0 ou 1) qui porte le libellé le plus spécifique sur une
    ligne donnée — même règle que empreinte_libelles, appliquée après coup
    pour déterminer un éventuel décalage de colonnes avec la référence."""
    if ligne >= len(grid):
        return None
    row = grid[ligne]
    a = _norm(row[0]) if len(row) > 0 and isinstance(row[0], str) else ""
    b = _norm(row[1]) if len(row) > 1 and isinstance(row[1], str) else ""
    if not a and not b:
        return None
    return 0 if len(a) >= len(b) else 1


SEUIL_CORRESPONDANCE = 0.80
CHEVAUCHEMENT_MINIMAL = 5
# Seuil distinct, plus permissif, pour signaler une simple PISTE (jamais
# appliquée automatiquement, seulement proposée en un clic avec une
# confiance clairement affichée). Un onglet réellement plus pauvre que le
# gabarit officiel (activité partiellement renseignée) peut n'avoir que 3-4
# lignes en commun avec un thème tout en étant le bon — mieux vaut montrer
# une piste faible que rester muet, tant que rien n'est jamais appliqué
# sans un clic explicite.
CHEVAUCHEMENT_MINIMAL_PISTE = 3
# Un onglet dont le contenu total est démesurément plus long que la
# référence n'est probablement pas une variante du thème, même s'il en
# contient un fragment qui correspond bien : c'est le signe d'un onglet
# composite regroupant plusieurs thèmes (constaté sur un cas réel — un
# onglet de 153 lignes retrouvait 8/10 lignes d'un thème de 10 lignes,
# alors que le reste du contenu appartenait à d'autres thèmes entièrement).
# Les rattachements légitimes observés ont tous un ratio proche de 1,0.
RATIO_TAILLE_MAX = 1.8

SEUIL_LIBELLES_PROPOSITION = 0.55
SEUIL_LIBELLES_AUTO = 0.85


def _norm(v) -> str:
    """Normalise un texte pour comparaison structurelle.

    Les repères de note de bas de page intégrés au libellé lui-même
    (« Recharge de monnaie électronique(1) », « … (2) »…) sont retirés :
    leur numérotation varie d'un établissement à l'autre — voire disparaît
    totalement — alors que le texte substantiel, lui, est identique. Sans
    ce retrait, deux libellés en tout point équivalents ne se
    reconnaissaient pas (cas réel : « recharge de monnaie électronique(1) »
    du gabarit de référence contre « Recharge de monnaie électronique »,
    sans note, chez un autre établissement).

    Une coquille connue du gabarit de référence lui-même (« Nobre de
    clients » au lieu de « Nombre de clients », déjà repérée en tout début
    de projet) est également corrigée : sans quoi elle empêchait de
    reconnaître le libellé correctement orthographié chez tout autre
    établissement.

    Une année brute collée en fin de libellé, sans parenthèses
    (« Nombre de clients 2025 » au lieu de « Nombre de clients »), est
    retirée pour la même raison que les notes entre parenthèses : elle
    varie d'un établissement à l'autre sans changer le sens du libellé.
    """
    if v is None:
        return ""
    s = str(v).lower().strip()
    s = re.sub(r"\(\s*\d+\s*\)\s*$", "", s).strip()
    s = re.sub(r"\s+(19|20)\d{2}\s*$", "", s).strip()
    s = re.sub(r"\bnobre\b", "nombre", s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def empreinte_ligne(row: list) -> str:
    """Concatène tout le texte d'une ligne (jamais les nombres) : capte à la
    fois les libellés de la colonne A et les en-têtes de mesure (Nombre /
    Valeur) situés dans d'autres colonnes, sans être perturbé par les
    montants eux-mêmes — qui, eux, varient légitimement d'un établissement à
    l'autre."""
    morceaux = [_norm(v) for v in row if isinstance(v, str) and v.strip()]
    return " | ".join(m for m in morceaux if m)


def sequence(grid: list[list]) -> list[tuple[int, str]]:
    """[(index_ligne, empreinte), ...] pour les lignes non vides, dans l'ordre."""
    out = []
    for r, row in enumerate(grid):
        e = empreinte_ligne(row)
        if e:
            out.append((r, e))
    return out


_reference_cache: Optional[dict] = None


def _charger_reference() -> dict:
    data = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    out = {}
    for theme, v in data.items():
        out[theme] = {
            "sequence": [(int(r), e) for r, e in v["sequence"]],
            "sequence_libelles": [(int(r), e) for r, e in v["sequence_libelles"]],
            "colonnes_libelles": {int(r): c for r, c in v.get("colonnes_libelles", {}).items()},
            "n_lignes": v["n_lignes"],
            "n_colonnes": v["n_colonnes"],
            "mesures_statiques": v.get("mesures_statiques"),
        }
    return out


def reference() -> dict:
    """{thème: {"sequence": [(ligne, empreinte), ...], "n_lignes": int, "n_colonnes": int}}"""
    global _reference_cache
    if _reference_cache is None:
        _reference_cache = _charger_reference()
    return _reference_cache


def dimensions_canoniques(theme: str) -> tuple[int, int]:
    v = reference()[theme]
    return v["n_lignes"], v["n_colonnes"]


def mesures_statiques_canoniques(theme: str) -> Optional[dict[str, int]]:
    """{mesure_normalisée: colonne} pour un thème STATIQUE ; None pour un
    thème mensuel (Mobile Money…), qui n'a pas de colonne de mesure fixe."""
    return reference()[theme].get("mesures_statiques")


def alignement_lcs(seq_candidate: list[tuple[int, str]],
                   seq_reference: list[tuple[int, str]]) -> tuple[list[tuple[int, int]], int]:
    """Alignement par plus longue sous-séquence commune.

    Renvoie la liste des paires (ligne_candidate, ligne_référence) appariées,
    et la longueur de la sous-séquence commune. Tolère les lignes insérées
    ou supprimées de part et d'autre, tant que l'ORDRE relatif des lignes
    appariées est préservé — c'est exactement la propriété qui distingue
    « une ligne vide en trop » (les libellés restent dans le même ordre) d'un
    document réellement différent (l'ordre ne concorderait pas)."""
    a = [e for _, e in seq_candidate]
    b = [e for _, e in seq_reference]
    n, m = len(a), len(b)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        ai = a[i - 1]
        row_i, row_im1 = dp[i], dp[i - 1]
        for j in range(1, m + 1):
            if ai == b[j - 1]:
                row_i[j] = row_im1[j - 1] + 1
            else:
                row_i[j] = row_im1[j] if row_im1[j] >= row_i[j - 1] else row_i[j - 1]

    i, j = n, m
    paires: list[tuple[int, int]] = []
    while i > 0 and j > 0:
        if a[i - 1] == b[j - 1]:
            paires.append((seq_candidate[i - 1][0], seq_reference[j - 1][0]))
            i -= 1
            j -= 1
        elif dp[i - 1][j] >= dp[i][j - 1]:
            i -= 1
        else:
            j -= 1
    paires.reverse()
    return paires, dp[n][m]


def remapper_grille(grid: list[list], alignement: list[tuple[int, int]],
                    n_lignes: int, n_colonnes: int, decalage_colonnes: int = 0) -> list[list]:
    """Reconstruit une grille dans le REPÈRE DE LIGNES CANONIQUE, à partir
    d'une grille candidate dont certaines lignes ont été décalées (ligne
    insérée ou supprimée) par rapport au gabarit officiel.

    Seules les lignes explicitement appariées par l'alignement sont reprises
    — une ligne du candidat qui ne correspond à rien de connu est ignorée
    plutôt que placée à une position arbitraire, ce qui pourrait la faire
    atterrir sur la mauvaise ligne canonique.

    `decalage_colonnes` corrige un éventuel décalage SYSTÉMATIQUE de
    colonnes (cas réel : un établissement place son libellé une colonne
    plus loin que le gabarit officiel — « Nombre de clients 2025 » en
    colonne B au lieu de A — décalant d'autant la valeur qui suit). Sans
    cette correction, la valeur atterrirait dans la mauvaise colonne du
    thème canonique, silencieusement."""
    grille = [[None] * n_colonnes for _ in range(n_lignes)]
    mapping = dict(alignement)  # ligne_candidate -> ligne_canonique
    for r_candidate, row in enumerate(grid):
        r_ref = mapping.get(r_candidate)
        if r_ref is None or r_ref >= n_lignes:
            continue
        for c, v in enumerate(row):
            c_cible = c - decalage_colonnes
            if 0 <= c_cible < n_colonnes:
                grille[r_ref][c_cible] = v
    return grille


def detecter_decalage_colonnes(grid: list[list], alignement: list[tuple[int, int]], theme: str) -> int:
    """Décalage constant de colonnes entre l'onglet candidat et la
    référence, déterminé par vote majoritaire sur les lignes appariées.

    0 dans l'immense majorité des cas (même mise en page que le gabarit
    officiel). Un décalage non nul signale un onglet à la structure
    réellement personnalisée (ex. un onglet composite maison) plutôt qu'une
    simple variante du gabarit."""
    colonnes_ref = reference()[theme].get("colonnes_libelles", {})
    if not colonnes_ref or not alignement:
        return 0
    ecarts = []
    for r_candidate, r_ref in alignement:
        col_candidate = colonne_libelle_candidat(grid, r_candidate)
        col_ref = colonnes_ref.get(r_ref)
        if col_candidate is not None and col_ref is not None:
            ecarts.append(col_candidate - col_ref)
    if not ecarts:
        return 0
    return Counter(ecarts).most_common(1)[0][0]


import datetime

MEASURE_WORDS = ("nombre", "valeur", "montant")


def _est_date(v) -> bool:
    return isinstance(v, (datetime.datetime, datetime.date))


def _est_nombre(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def detecter_disposition_mensuelle(grid: list[list]) -> Optional[list[tuple[datetime.date, dict[str, int]]]]:
    """Si la grille utilise une disposition MENSUELLE (dates en en-tête de
    colonnes, comme les onglets Mobile Money), renvoie
    [(période, {mesure_normalisée: colonne}), ...] ; sinon None.

    Version autonome, volontairement plus simple que
    core.indicators.analyze_layout (dont ce module ne peut dépendre : elle
    importe déjà core.parsing, qui importe ce module-ci — la dépendre en
    retour créerait un import circulaire). Elle ne sert qu'à un besoin
    précis : reconnaître qu'un établissement a décliné un thème
    normalement statique (« Transfert d'argent ») sous une forme mensuelle,
    et en extraire le dernier mois renseigné.
    """
    header_row, date_cols = -1, []
    for r, row in enumerate(grid[:8]):
        cols = [c for c, v in enumerate(row) if _est_date(v)]
        if len(cols) >= 2:
            header_row, date_cols = r, sorted(cols)
            break
    if header_row == -1:
        return None

    sous_mesures: list[tuple[str, int]] = []
    if header_row + 1 < len(grid):
        for c, v in enumerate(grid[header_row + 1]):
            if c == 0 or not isinstance(v, str):
                continue
            n = _norm(v)
            if any(w in n for w in MEASURE_WORDS):
                sous_mesures.append((n, c))

    periodes = []
    for i, c in enumerate(date_cols):
        fin = date_cols[i + 1] if i + 1 < len(date_cols) else None
        d = grid[header_row][c]
        d = datetime.date(d.year, d.month, 1)
        mesures = {nom: col for nom, col in sous_mesures if col >= c and (fin is None or col < fin)}
        if not mesures:
            mesures = {"": c}
        periodes.append((d, mesures))
    return periodes


def extraire_derniere_periode(grid: list[list], periodes: list[tuple[datetime.date, dict[str, int]]],
                              ligne: int) -> dict[str, float]:
    """Pour une ligne donnée, les valeurs de la DERNIÈRE période où au moins
    une mesure y est renseignée — cohérent avec le reste de l'application,
    qui retient systématiquement le dernier mois disponible plutôt que
    d'exiger une mise à jour manuelle chaque mois."""
    if ligne >= len(grid):
        return {}
    row = grid[ligne]
    for _periode, mesures in reversed(periodes):
        valeurs, trouve = {}, False
        for nom, col in mesures.items():
            if col >= len(row):
                continue
            v = row[col]
            if _est_nombre(v):
                valeurs[nom] = v
                if v != 0:
                    trouve = True
        if trouve:
            return valeurs
    return {}


@dataclass
class Reconnaissance:
    theme: Optional[str]
    correspondance_exacte: bool
    taux: float = 0.0
    chevauchement: int = 0
    alignement: list = None  # [(ligne_candidate, ligne_reference), ...]
    suggestion: Optional[str] = None
    # Reconnu, mais avec une confiance qui n'autorise pas une consolidation
    # automatique sans un coup d'œil : présenté comme une PROPOSITION
    # prête à valider en un clic, jamais comme un rattachement à construire
    # à la main.
    necessite_validation: bool = False
    # La candidate décline le thème sous une forme MENSUELLE (dates en
    # colonnes) alors que le gabarit de référence est statique : la fusion
    # doit alors extraire le dernier mois renseigné plutôt que recopier la
    # grille telle quelle.
    disposition_mensuelle: bool = False
    periodes_mensuelles: list = None
    # Deuxième candidat le plus proche, quand l'écart avec le premier est
    # trop faible pour trancher avec confiance (cas réel : un onglet
    # « RIA » scorait 74% contre MobileMoney3 et 72% contre Transfert
    # d'argent — les deux thèmes partagent la même ventilation par pays de
    # la CEMAC. Mieux vaut présenter les deux choix que d'en imposer un au
    # hasard d'un écart de deux points).
    alternative: Optional[str] = None
    taux_alternative: float = 0.0


@dataclass
class SegmentDetecte:
    """Un fragment d'onglet composite qui correspond à un thème canonique,
    localisé sur une plage de lignes plutôt que sur l'onglet entier — cas
    réel : un établissement peut regrouper plusieurs thèmes du gabarit
    (clients/comptes/cartes, puis transactions par réseau…) dans UN SEUL
    onglet à sa façon, plutôt que de suivre le découpage officiel en 11
    onglets distincts."""

    theme: str
    ligne_debut: int
    ligne_fin: int
    taux: float
    alignement: list
    disposition_mensuelle: bool = False
    periodes_mensuelles: list = None


# Un segment doit rester relativement compact par rapport à la taille du
# thème qu'il prétend représenter : un même thème détecté sur une plage
# démesurément large n'est plus un segment localisé, c'est un faux positif
# dispersé sur tout l'onglet (le même risque, à l'échelle du segment, que le
# ratio de taille global écarte pour un onglet entier).
RATIO_SEGMENT_MAX = 2.2
SEUIL_SEGMENT = 0.35


# Écart maximal entre deux lignes appariées consécutives pour qu'elles
# appartiennent à la même grappe : au-delà, on considère qu'on change de
# zone de l'onglet plutôt que de rester dans le même segment.
ECART_GRAPPE_MAX = 15


def _plus_grande_grappe(lignes: list[int]) -> list[int]:
    """Isole la grappe de lignes la plus dense parmi celles appariées.

    Un thème peut, par coïncidence de vocabulaire, retrouver quelques
    libellés isolés loin de son vrai emplacement dans l'onglet (cas réel :
    Cartes1 retrouvait la quasi-totalité de son contenu compacté sur les
    lignes 10-25, mais aussi quelques libellés isolés vers la ligne 95,
    déjà partagée avec un tout autre segment). Sans ce filtre, l'étendue
    brute (10 à 101) aurait fait passer un segment par ailleurs légitime
    pour un faux positif dispersé."""
    if not lignes:
        return []
    lignes = sorted(lignes)
    grappes: list[list[int]] = [[lignes[0]]]
    for l in lignes[1:]:
        if l - grappes[-1][-1] <= ECART_GRAPPE_MAX:
            grappes[-1].append(l)
        else:
            grappes.append([l])
    return max(grappes, key=len)


def detecter_segments(grid: list[list]) -> list[SegmentDetecte]:
    """Cherche, pour chacun des 11 thèmes, un fragment LOCALISÉ de l'onglet
    qui lui correspond. Plusieurs segments (de thèmes différents, sur des
    plages de lignes différentes) peuvent être trouvés dans un même onglet.
    """
    candidats: list[SegmentDetecte] = []
    seq_ligne = sequence(grid)
    seq_lib = empreinte_libelles(grid)

    for theme, ref_data in reference().items():
        for seq_candidate, seq_ref in ((seq_ligne, ref_data["sequence"]),
                                       (seq_lib, ref_data["sequence_libelles"])):
            if len(seq_candidate) < CHEVAUCHEMENT_MINIMAL_PISTE or not seq_ref:
                continue
            alignement, longueur = alignement_lcs(seq_candidate, seq_ref)
            if longueur < CHEVAUCHEMENT_MINIMAL_PISTE:
                continue
            lignes_candidate = _plus_grande_grappe([r for r, _ in alignement])
            alignement = [(r, ref_r) for r, ref_r in alignement if r in lignes_candidate]
            longueur = len(alignement)
            if longueur < CHEVAUCHEMENT_MINIMAL_PISTE:
                continue
            span = max(lignes_candidate) - min(lignes_candidate) + 1
            if span > len(seq_ref) * RATIO_SEGMENT_MAX:
                continue  # dispersé sur tout l'onglet : pas un segment localisé
            taux = longueur / len(seq_ref)
            if taux < SEUIL_SEGMENT:
                continue
            periodes = detecter_disposition_mensuelle(grid)
            ref_mensuelle = ref_data.get("mesures_statiques") is None
            candidats.append(SegmentDetecte(
                theme=theme, ligne_debut=min(lignes_candidate), ligne_fin=max(lignes_candidate),
                taux=taux, alignement=alignement,
                disposition_mensuelle=bool(periodes) and not ref_mensuelle,
                periodes_mensuelles=periodes,
            ))
            break  # la meilleure des deux passes pour ce thème suffit

    # Élimine les recouvrements : on garde le segment le plus confiant
    # d'abord, on écarte tout candidat suivant qui chevauche trop un segment
    # déjà retenu (le même fragment ne peut appartenir qu'à un seul thème).
    candidats.sort(key=lambda s: -s.taux)
    retenus: list[SegmentDetecte] = []
    for c in candidats:
        chevauche = any(
            c.ligne_debut <= r.ligne_fin and r.ligne_debut <= c.ligne_fin
            for r in retenus
        )
        if not chevauche:
            retenus.append(c)
    retenus.sort(key=lambda s: s.ligne_debut)
    return retenus


def annees_mentionnees(grid: list[list]) -> set[int]:
    """Années auxquelles se rapporte un onglet, lues dans son titre et ses
    en-têtes (premières lignes) puis, à défaut, dans ses dates.

    Sert à repérer un onglet portant sur une PÉRIODE RÉVOLUE : un
    établissement peut laisser dans son classeur d'anciens onglets d'un
    exercice précédent (constaté sur un fichier réel : « chèques&VIR 1er
    SEMESTRE 22 », titré « … 1er TRIMESTRE 2022 », aux côtés d'onglets
    2025-2026). Ces onglets ressemblent structurellement au gabarit à plus
    de 90 % — les rattacher mélangerait des montants de 2022 dans un total
    2025-2026, sans qu'aucune erreur ne soit signalée.
    """
    annees: set[int] = set()
    for row in grid[:4]:
        for v in row:
            if isinstance(v, str):
                for m in re.finditer(r"\b(20\d{2})\b", v):
                    annees.add(int(m.group(1)))
    if not annees:
        for row in grid:
            for v in row:
                if isinstance(v, (datetime.datetime, datetime.date)):
                    annees.add(v.year)
    return annees


_MOTIF_PERIODE = re.compile(
    r"p[ée]riode\s*:?\s*du\s*(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4})\s*au\s*(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4})",
    re.IGNORECASE,
)


def _parser_date(texte: str) -> Optional[datetime.date]:
    """Tolère un jour hors plage (ex. « 31/06 », une coquille réelle
    rencontrée — juin n'a que 30 jours) : ramené au dernier jour valide du
    mois plutôt que rejeté. Seuls le mois et l'année comptent vraiment ici,
    pour déterminer quelle période est la plus récente."""
    import calendar

    m = re.match(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})", texte)
    if not m:
        return None
    jour, mois, annee = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if annee < 100:
        annee += 2000
    if not (1 <= mois <= 12):
        return None
    dernier_jour = calendar.monthrange(annee, mois)[1]
    jour = min(max(jour, 1), dernier_jour)
    try:
        return datetime.date(annee, mois, jour)
    except ValueError:
        return None


def detecter_periode_declaree(grid: list[list]) -> Optional[tuple[datetime.date, datetime.date]]:
    """Période explicitement déclarée en tête d'onglet (« Période : du
    01/01/2025 au 31/12/2025 »), si présente.

    Cas réel ayant motivé cette fonction : un établissement a réparti son
    activité Cartes sur DEUX onglets composites distincts, l'un couvrant
    l'année 2025, l'autre le premier semestre 2026 — la MÊME clientèle
    photographiée à deux dates, pas deux catégories à additionner (des
    effectifs à moins de 1 % d'écart d'une date à l'autre : une croissance
    organique plausible, pas deux populations distinctes). Les fusionner
    comme des réseaux parallèles (GIMAC + VISA) aurait doublé la quasi
    -totalité des effectifs, silencieusement.
    """
    for row in grid[:8]:
        for v in row:
            if not isinstance(v, str):
                continue
            m = _MOTIF_PERIODE.search(v)
            if not m:
                continue
            debut, fin = _parser_date(m.group(1)), _parser_date(m.group(2))
            if debut and fin:
                return (debut, fin)
    return None


def reconnaissance_pour_theme(grid: list[list], theme: str) -> Reconnaissance:
    """Recalcule l'alignement d'un onglet contre un thème DÉJÀ VALIDÉ (cf.
    core.calibration) : pas de nouvelle décision à prendre, seulement
    reconstruire l'alignement — nécessaire à chaque nouveau fichier, puisque
    les positions de ligne peuvent différer d'un dépôt à l'autre même pour
    un onglet du même nom."""
    ref_data = reference()[theme]
    periodes = detecter_disposition_mensuelle(grid)
    ref_mensuelle = ref_data.get("mesures_statiques") is None
    disposition_mensuelle = bool(periodes) and not ref_mensuelle

    seq_candidate = sequence(grid)
    alignement, longueur = alignement_lcs(seq_candidate, ref_data["sequence"])
    if longueur >= CHEVAUCHEMENT_MINIMAL and not disposition_mensuelle:
        # Disposition compatible avec la référence : l'alignement ligne
        # entière suffit, pas besoin de repli sur les libellés seuls.
        return Reconnaissance(theme=theme, correspondance_exacte=False,
                              taux=longueur / len(ref_data["sequence"]), chevauchement=longueur,
                              alignement=alignement)

    seq_lib = empreinte_libelles(grid)
    alignement_lib, longueur_lib = alignement_lcs(seq_lib, ref_data["sequence_libelles"])
    if longueur_lib >= longueur:
        alignement, longueur = alignement_lib, longueur_lib
        diviseur = len(ref_data["sequence_libelles"]) or 1
    else:
        diviseur = len(ref_data["sequence"]) or 1

    return Reconnaissance(theme=theme, correspondance_exacte=False,
                          taux=longueur / diviseur, chevauchement=longueur,
                          alignement=alignement,
                          disposition_mensuelle=disposition_mensuelle,
                          periodes_mensuelles=periodes)


def reconnaitre_onglet(nom: str, grid: list[list], noms_connus: set[str]) -> Reconnaissance:
    """Détermine à quel thème canonique un onglet appartient, s'il y a lieu.

    Deux passes :
    1. Empreinte LIGNE ENTIÈRE (libellés + en-têtes de mesure) : la plus
       fiable, adaptée aux variantes qui suivent la même disposition que le
       gabarit (réseau, système de règlement…).
    2. À défaut, empreinte LIBELLÉS SEULS (colonnes A+B, sans les colonnes
       de mesure) : retrouve un thème décliné sous une disposition MENSUELLE
       (dates en colonnes) là où le gabarit de référence est statique — cas
       réel où la passe 1 échoue quasi systématiquement alors que les
       libellés eux-mêmes sont identiques.
    """
    if nom.strip() in noms_connus:
        return Reconnaissance(theme=nom.strip(), correspondance_exacte=True, taux=1.0)

    seq_candidate = sequence(grid)
    if len(seq_candidate) >= CHEVAUCHEMENT_MINIMAL_PISTE:
        meilleur_theme, meilleur_taux, meilleur_align = None, 0.0, None
        for theme, ref_data in reference().items():
            seq_ref = ref_data["sequence"]
            alignement, longueur = alignement_lcs(seq_candidate, seq_ref)
            if longueur < CHEVAUCHEMENT_MINIMAL_PISTE:
                continue
            if len(seq_candidate) / len(seq_ref) > RATIO_TAILLE_MAX:
                continue
            taux = longueur / len(seq_ref)
            if taux > meilleur_taux:
                meilleur_theme, meilleur_taux, meilleur_align = theme, taux, alignement

        if meilleur_theme and meilleur_taux >= SEUIL_CORRESPONDANCE:
            return Reconnaissance(theme=meilleur_theme, correspondance_exacte=False,
                                  taux=meilleur_taux, chevauchement=len(meilleur_align),
                                  alignement=meilleur_align)
    else:
        meilleur_theme, meilleur_taux = None, 0.0

    # --- Passe 2 : libellés seuls, tolérante à une disposition différente ---
    seq_lib = empreinte_libelles(grid)
    if len(seq_lib) >= CHEVAUCHEMENT_MINIMAL_PISTE:
        classement: list[tuple[float, str, int, list]] = []
        for theme, ref_data in reference().items():
            seq_ref_lib = ref_data["sequence_libelles"]
            alignement, longueur = alignement_lcs(seq_lib, seq_ref_lib)
            if longueur < CHEVAUCHEMENT_MINIMAL_PISTE:
                continue
            if len(seq_lib) / len(seq_ref_lib) > RATIO_TAILLE_MAX:
                continue
            classement.append((longueur / len(seq_ref_lib), theme, len(alignement), alignement))
        classement.sort(key=lambda x: -x[0])

        if classement and classement[0][0] >= SEUIL_LIBELLES_PROPOSITION:
            meilleur_taux_lib, meilleur_theme_lib, chevauchement, meilleur_align_lib = classement[0]
            deuxieme = classement[1] if len(classement) > 1 else None
            # Écart trop faible entre les deux premiers candidats : les
            # deux thèmes se ressemblent trop pour trancher automatiquement
            # (ex. Transfert d'argent et MobileMoney3 partagent la même
            # ventilation par pays de la CEMAC).
            ambigu = deuxieme is not None and (meilleur_taux_lib - deuxieme[0]) < 0.05

            periodes = detecter_disposition_mensuelle(grid)
            ref_mensuelle = reference()[meilleur_theme_lib].get("mesures_statiques") is None
            return Reconnaissance(
                theme=meilleur_theme_lib, correspondance_exacte=False,
                taux=meilleur_taux_lib, chevauchement=chevauchement,
                alignement=meilleur_align_lib,
                necessite_validation=True,
                disposition_mensuelle=bool(periodes) and not ref_mensuelle,
                periodes_mensuelles=periodes,
                alternative=deuxieme[1] if ambigu else None,
                taux_alternative=deuxieme[0] if ambigu else 0.0,
            )
        meilleur_taux_lib = classement[0][0] if classement else 0.0
        meilleur_theme_lib = classement[0][1] if classement else None
        if meilleur_taux_lib > meilleur_taux:
            meilleur_theme, meilleur_taux = meilleur_theme_lib, meilleur_taux_lib

    return Reconnaissance(theme=None, correspondance_exacte=False,
                          suggestion=meilleur_theme, taux=meilleur_taux)


# --------------------------------------------------------------------- #
# Rapprochement d'onglets non reconnus entre établissements différents
#
# Un onglet qui ne correspond à aucun des 11 thèmes du gabarit reste
# individuellement visible (cf. core.parsing / core.export), mais rien ne
# signalait jusqu'ici qu'un onglet inconnu chez un établissement pouvait
# structurellement RESSEMBLER à un onglet inconnu chez un autre — signe
# possible d'une pratique commune à formaliser dans une future version du
# gabarit. Demandé explicitement par l'utilisateur : « en attendant de
# faire un rapprochement avec d'autres si y'en a qui sont aussi
# différents ».
# --------------------------------------------------------------------- #

def rapprocher_onglets_non_reconnus(
        institutions: list, seuil: float = 0.3
) -> list[tuple[list[tuple[str, str]], float]]:
    """Regroupe les onglets non reconnus structurellement proches, ENTRE
    établissements différents (jamais au sein d'un même établissement : ses
    propres onglets « 2025 » et « 2026 » se ressemblent presque toujours,
    sans que ce soit une découverte).

    Renvoie une liste de (membres, taux_moyen_de_ressemblance), chaque
    groupe comportant au moins deux onglets, triée du rapprochement le
    plus net au plus faible.
    """
    entrees = []
    for inst in institutions:
        for o in getattr(inst, "non_reconnus", []):
            seq = empreinte_libelles(o.grid)
            if seq:
                entrees.append((inst.name, o.nom, seq))

    n = len(entrees)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    scores_paires: dict[tuple[int, int], float] = {}
    for i in range(n):
        for j in range(i + 1, n):
            if entrees[i][0] == entrees[j][0]:
                continue  # rapprochement entre établissements différents uniquement
            _, longueur = alignement_lcs(entrees[i][2], entrees[j][2])
            # Le plus petit des deux dénominateurs, pas le plus grand : ici,
            # aucun des deux côtés n'est un gabarit de référence fixe — les
            # deux sont des inconnus comparés entre eux. Un onglet clairsemé
            # (une poignée de lignes) entièrement retrouvé dans un onglet
            # plus riche chez un autre établissement EST un rapprochement
            # significatif, même si le second en contient beaucoup plus.
            taux = longueur / min(len(entrees[i][2]), len(entrees[j][2]))
            if taux >= seuil:
                union(i, j)
                scores_paires[(i, j)] = taux

    groupes: dict[int, list[int]] = {}
    for i in range(n):
        groupes.setdefault(find(i), []).append(i)

    resultats = []
    for indices in groupes.values():
        if len(indices) < 2:
            continue
        membres = [(entrees[i][0], entrees[i][1]) for i in indices]
        scores_du_groupe = [v for (i, j), v in scores_paires.items()
                           if i in indices and j in indices]
        taux_moyen = sum(scores_du_groupe) / len(scores_du_groupe) if scores_du_groupe else 0.0
        resultats.append((membres, taux_moyen))

    resultats.sort(key=lambda r: -r[1])
    return resultats
