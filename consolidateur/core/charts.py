"""
core/charts.py

Phase 6 du Cahier des charges : préparation des données pour les deux
graphiques du tableau de bord (cf. CDC section 5.5) :

- build_market_share_data : part de marché (%) de chaque établissement,
  pour chaque indicateur (base 100 % = total marché de l'indicateur).
- build_monthly_series : évolution mensuelle d'un indicateur Mobile Money,
  une colonne par établissement, pour tous les mois communs disponibles.

Ce module ne dessine rien : il renvoie des DataFrame pandas, que app.py
transforme en graphiques Plotly. Cette séparation permet de tester les
données indépendamment du rendu visuel.
"""

from __future__ import annotations

import datetime
from typing import Callable

import pandas as pd

from core.kpis import KpiResult, find_date_columns, find_row_index
from core.parsing import Institution

MONTHS_FR = ["janv", "févr", "mars", "avr", "mai", "juin", "juil", "août", "sept", "oct", "nov", "déc"]


def fmt_month(d: datetime.date) -> str:
    return f"{MONTHS_FR[d.month - 1]}-{str(d.year)[2:]}"


def build_market_share_data(kpis: list[KpiResult], gab: dict, inst_names: list[str]) -> pd.DataFrame:
    """Une ligne par indicateur, une colonne par établissement, valeurs en %
    du total marché de l'indicateur (0 % partout si le total est nul)."""
    rows = []

    def add_row(label: str, per_inst: dict, total: float):
        row = {"Indicateur": label}
        for name in inst_names:
            v = per_inst.get(name, 0)
            row[name] = round(v / total * 100, 1) if total else 0.0
        rows.append(row)

    for k in kpis:
        add_row(k.label, dict(k.per_inst), k.total)

    gab_per_inst = {p["name"]: p["nombre"] for p in gab["per_inst"]}
    add_row("Retraits GAB - nombre", gab_per_inst, gab["total"]["nombre"])

    return pd.DataFrame(rows).set_index("Indicateur")


def build_monthly_series(institutions: list[Institution], sheet: str, matcher: Callable[[str], bool]) -> pd.DataFrame:
    """Une ligne par mois (union des mois disponibles, triés chronologiquement),
    une colonne par établissement."""
    all_dates: set[datetime.date] = set()
    for inst in institutions:
        sd = inst.sheets.get(sheet)
        if not sd:
            continue
        header_row, cols = find_date_columns(sd.grid)
        if header_row == -1:
            continue
        for c in cols:
            d = sd.grid[header_row][c]
            if isinstance(d, (datetime.datetime, datetime.date)):
                all_dates.add(d)

    if not all_dates:
        return pd.DataFrame()

    rows = []
    for d in sorted(all_dates):
        row = {"Mois": fmt_month(d)}
        for inst in institutions:
            value = 0
            sd = inst.sheets.get(sheet)
            if sd:
                header_row, cols = find_date_columns(sd.grid)
                col = next((c for c in cols if sd.grid[header_row][c] == d), None)
                if col is not None:
                    r = find_row_index(sd.grid, matcher)
                    if r != -1:
                        v = sd.grid[r][col] if col < len(sd.grid[r]) else None
                        if isinstance(v, (int, float)) and not isinstance(v, bool):
                            value = v
            row[inst.name] = value
        rows.append(row)

    return pd.DataFrame(rows).set_index("Mois")
