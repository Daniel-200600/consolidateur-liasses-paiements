"""
core/quality.py

Phase 5 du Cahier des charges : contrôle qualité.

Deux familles d'anomalies détectées (cf. CDC section 5.4), toutes deux
purement informatives — elles n'interrompent jamais le calcul ni l'export :

1. Cellules en erreur de formule dans un fichier source (déjà repérées lors
   du parsing, cf. core.parsing.SheetData.errors) : listées par
   établissement, onglet et cellule.
2. Onglets sans aucune donnée saisie par un établissement : une "donnée
   réelle" est une valeur numérique non nulle (les 0 de gabarit ne comptent
   pas comme une saisie), pour cohérence avec l'analyse manuelle qui a servi
   de référence (cf. CDC section 9).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from core.parsing import KNOWN_SHEETS, Institution, SheetData


@dataclass
class QualityFlag:
    kind: str  # "erreur_formule" | "onglet_vide"
    institution: str
    message: str
    sheet: Optional[str] = None
    details: list = field(default_factory=list)


def has_real_data(sheet_data: Optional[SheetData]) -> bool:
    """Une donnée réelle = une valeur numérique non nulle quelque part dans
    l'onglet (les 0 de gabarit ne comptent pas comme une saisie).

    Exception documentée : certains onglets du gabarit (ex. Cartes 4) portent
    un simple en-tête "Année" stocké comme nombre (ex. 2025) plutôt que comme
    texte, identique dans tous les fichiers. Ce n'est pas une donnée métier :
    on exclut donc les entiers ressemblant à une année de reporting (2000 à
    2100) de la détection, pour éviter de masquer un onglet réellement vide.
    """
    if sheet_data is None:
        return False
    for row in sheet_data.grid:
        for v in row:
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v != 0:
                if isinstance(v, int) and 2000 <= v <= 2100:
                    continue
                return True
    return False


def check_formula_errors(institutions: list[Institution]) -> list[QualityFlag]:
    flags: list[QualityFlag] = []
    for inst in institutions:
        for sheet_name in KNOWN_SHEETS:
            sd = inst.sheets.get(sheet_name)
            if sd and sd.errors:
                flags.append(QualityFlag(
                    kind="erreur_formule",
                    institution=inst.name,
                    sheet=sheet_name,
                    message=(
                        f"{inst.name} : {len(sd.errors)} cellule(s) en erreur de formule "
                        f"dans l'onglet « {sheet_name} » (reprises telles quelles, à corriger à la source)"
                    ),
                    details=sd.errors,
                ))
    return flags


def check_empty_sheets(institutions: list[Institution]) -> list[QualityFlag]:
    flags: list[QualityFlag] = []
    for inst in institutions:
        empty = [s for s in KNOWN_SHEETS if not has_real_data(inst.sheets.get(s))]
        if empty:
            flags.append(QualityFlag(
                kind="onglet_vide",
                institution=inst.name,
                sheet=None,
                message=f"{inst.name} : aucune donnée saisie sur {', '.join(empty)}",
                details=empty,
            ))
    return flags


def check_missing_labels(kpis, gab: dict | None = None) -> list[QualityFlag]:
    """Signale les indicateurs dont le libellé attendu est introuvable dans un
    onglet pourtant renseigné (cf. KpiResult.missing_label_for).

    C'est le garde-fou contre l'évolution silencieuse du gabarit BEAC : sans
    lui, un libellé modifié à la source ferait retomber l'indicateur à 0 sans
    que rien ne l'indique, et ce 0 se propagerait au Total marché puis aux
    exports."""
    flags: list[QualityFlag] = []
    for k in kpis:
        for inst_name in getattr(k, "missing_label_for", []):
            flags.append(QualityFlag(
                kind="libelle_introuvable",
                institution=inst_name,
                sheet=k.sheet,
                message=(
                    f"{inst_name} : l'indicateur « {k.label} » est introuvable dans l'onglet "
                    f"« {k.sheet} », pourtant renseigné. La valeur affichée (0) n'est donc pas "
                    f"fiable — le libellé a probablement changé dans le gabarit."
                ),
                details=[k.key],
            ))
    if gab:
        for inst_name in gab.get("missing_label_for", []):
            flags.append(QualityFlag(
                kind="libelle_introuvable",
                institution=inst_name,
                sheet="Cartes 5",
                message=(
                    f"{inst_name} : la ligne « Retrait GAB » de la section « TRANSACTIONS DE VOS "
                    f"PORTEURS » est introuvable dans l'onglet « Cartes 5 », pourtant renseigné. "
                    f"La valeur affichée (0) n'est donc pas fiable."
                ),
                details=["retrait_gab"],
            ))
    return flags


def check_text_numbers(institutions: list[Institution]) -> list[QualityFlag]:
    """Nombres saisis en TEXTE dans un fichier source.

    Excel n'additionne pas ces cellules : laissées telles quelles, elles
    seraient comptées comme zéro et fausseraient les totaux (plusieurs
    milliards de XAF sur les liasses reçues). L'outil les récupère
    automatiquement (cf. core.parsing), mais l'anomalie doit être corrigée à
    la source, d'où ce signalement.
    """
    flags: list[QualityFlag] = []
    for inst in institutions:
        for sheet_name in KNOWN_SHEETS:
            sd = inst.sheets.get(sheet_name)
            if sd and getattr(sd, "text_numbers", None):
                total = sum(t["parsed"] for t in sd.text_numbers)
                flags.append(QualityFlag(
                    kind="nombre_en_texte",
                    institution=inst.name,
                    sheet=sheet_name,
                    message=(
                        f"{inst.name} : {len(sd.text_numbers)} cellule(s) de l'onglet "
                        f"« {sheet_name} » contiennent un nombre saisi en texte "
                        f"({total:,.0f} XAF au total). Ces valeurs ont été récupérées "
                        f"automatiquement, mais restent à corriger à la source."
                    ).replace(",", " "),
                    details=sd.text_numbers,
                ))
    return flags


def check_onglets_non_reconnus(institutions: list[Institution]) -> list[QualityFlag]:
    """Onglets d'un fichier source dont ni le nom ni la structure ne
    correspondent à un thème connu du gabarit (cf. core.sheet_matching).

    Jamais silencieusement ignorés : signalés ici pour rester visibles,
    y compris dans les documents exportés, même après la fin de la session
    d'analyse."""
    flags: list[QualityFlag] = []
    for inst in institutions:
        for o in getattr(inst, "non_reconnus", []):
            suggestion = f" (proche de « {o.suggestion} », {o.taux_suggestion:.0%})" if o.suggestion else ""
            flags.append(QualityFlag(
                kind="onglet_non_reconnu",
                institution=inst.name,
                sheet=o.nom,
                message=(f"{inst.name} : l'onglet « {o.nom} » ne correspond à aucun thème connu du "
                        f"gabarit{suggestion} — non consolidé, à rattacher manuellement si besoin."),
                details=[],
            ))
    return flags


def check_totaux_incoherents(institutions: list[Institution]) -> list[QualityFlag]:
    """Un total de tête qui ne correspond pas à la somme de ses propres
    sous-zones, DANS LE FICHIER SOURCE d'un même établissement.

    Cas réel trouvé en réauditant les calculs : sur « Transfert d'argent »,
    le total « toutes zones » (A+B) doit en principe égaler exactement la
    somme de la zone CEMAC et de la zone internationale — vérifié à l'exact
    XAF près sur deux établissements réels. Un troisième affichait pourtant
    un écart de plus de 2 milliards de XAF entre les deux : une incohérence
    dans SA PROPRE saisie, pas un rapprochement entre établissements.

    Le calcul retient toujours le total de tête tel que déclaré (jamais
    recalculé silencieusement à la place de l'établissement — cf.
    core.montant_total), mais cet écart mérite d'être signalé : il peut
    indiquer une case oubliée, un total resté d'une version antérieure du
    fichier, ou une zone non décomposée.
    """
    from core.montant_total import _COMPOSANTES, _valeur_a

    flags: list[QualityFlag] = []
    for inst in institutions:
        for comp in _COMPOSANTES:
            if not comp.lignes_repli or comp.sheet not in inst.sheets:
                continue
            total_tete = _valeur_a([inst], comp.sheet, comp.ligne_tete, comp.mesure)
            somme_composantes = sum(_valeur_a([inst], comp.sheet, r, comp.mesure) for r in comp.lignes_repli)
            if not total_tete or not somme_composantes:
                continue  # rien à rapprocher si l'une des deux parts est vide
            ecart = total_tete - somme_composantes
            if abs(ecart) > max(1.0, abs(total_tete) * 0.001):
                flags.append(QualityFlag(
                    kind="total_incoherent",
                    institution=inst.name,
                    sheet=comp.sheet,
                    message=(f"{inst.name}, {comp.sheet} : le total de tête ({total_tete:,.0f} XAF) "
                            f"ne correspond pas à la somme de ses propres sous-zones "
                            f"({somme_composantes:,.0f} XAF) — écart de {ecart:,.0f} XAF dans le "
                            f"fichier source.".replace(",", " ")),
                    details=[],
                ))
    return flags



def run_quality_checks(institutions: list[Institution], kpis=None, gab: dict | None = None) -> list[QualityFlag]:
    flags = (check_formula_errors(institutions) + check_text_numbers(institutions)
            + check_empty_sheets(institutions) + check_onglets_non_reconnus(institutions)
            + check_totaux_incoherents(institutions))
    if kpis is not None:
        flags += check_missing_labels(kpis, gab)
    return flags
