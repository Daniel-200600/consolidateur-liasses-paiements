"""
core/consolidation.py

Phase 3 du Cahier des charges : moteur de consolidation.

Pour chaque onglet connu du gabarit (cf. core.parsing.KNOWN_SHEETS), produit
une grille "Total marché" à partir des grilles de tous les établissements
chargés, en appliquant la règle définie en section 5.2 du CDC :

- cellule numérique  -> somme des valeurs numériques de tous les établissements
                        (une cellule vide/non numérique compte pour 0) ;
- cellule date        -> recopiée telle quelle (les en-têtes de mois sont
                        strictement identiques d'un établissement à l'autre) ;
- cellule texte        -> recopiée telle quelle (premier établissement qui la
                        renseigne, le gabarit étant identique partout) ;
- cellule vide partout -> laissée à None.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any

from core.parsing import KNOWN_SHEETS, Institution, SheetData


@dataclass
class ConsolidatedSheet:
    grid: list[list[Any]] = field(default_factory=list)
    n_institutions_present: int = 0  # nb d'établissements ayant réellement cet onglet


def _is_number(v: Any) -> bool:
    # bool est une sous-classe de int en Python : on l'exclut explicitement,
    # une case à cocher ne doit jamais être additionnée comme un montant.
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_date(v: Any) -> bool:
    return isinstance(v, (datetime.datetime, datetime.date))


def consolidate_sheet(sheet_datas: list[SheetData]) -> ConsolidatedSheet:
    """Construit la grille Total marché pour UN onglet, à partir de la liste
    des SheetData de chaque établissement qui possède cet onglet."""
    if not sheet_datas:
        return ConsolidatedSheet(grid=[], n_institutions_present=0)

    max_rows = max(len(s.grid) for s in sheet_datas)
    max_cols = max((len(row) for s in sheet_datas for row in s.grid), default=0)

    total_grid: list[list[Any]] = []
    for r in range(max_rows):
        total_row: list[Any] = []
        for c in range(max_cols):
            values = []
            for s in sheet_datas:
                if r < len(s.grid) and c < len(s.grid[r]):
                    values.append(s.grid[r][c])
                else:
                    values.append(None)

            has_date = any(_is_date(v) for v in values)
            has_number = any(_is_number(v) for v in values)
            has_string = any(isinstance(v, str) and v != "" for v in values)

            if has_date:
                cell = next(v for v in values if _is_date(v))
            elif has_string and not has_number:
                cell = next(v for v in values if isinstance(v, str) and v != "")
            elif has_number:
                cell = sum(v for v in values if _is_number(v))
            else:
                cell = None
            total_row.append(cell)
        total_grid.append(total_row)

    return ConsolidatedSheet(grid=total_grid, n_institutions_present=len(sheet_datas))


def consolidate_all(institutions: list[Institution]) -> dict[str, ConsolidatedSheet]:
    """Construit la grille Total marché pour chacun des 11 onglets connus,
    en ne considérant que les établissements qui possèdent effectivement cet
    onglet (un établissement sans l'onglet n'apporte simplement aucune valeur,
    plutôt que des zéros artificiels)."""
    totals: dict[str, ConsolidatedSheet] = {}
    for sheet_name in KNOWN_SHEETS:
        sheet_datas = [
            inst.sheets[sheet_name] for inst in institutions if sheet_name in inst.sheets
        ]
        if not sheet_datas:
            continue
        totals[sheet_name] = consolidate_sheet(sheet_datas)
    return totals
