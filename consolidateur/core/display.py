"""
core/display.py

Formatage des grilles brutes (aperçu des onglets) pour l'affichage.

Une grille lue depuis le gabarit mélange, dans une même colonne, des
libellés, des nombres et des dates. Streamlit sérialise ses tableaux via
Apache Arrow, qui exige un type homogène par colonne : sans conversion
préalable, chaque affichage déclenchait un avertissement de sérialisation
et un repli automatique.

On convertit donc tout en texte pour l'affichage — ce qui règle
l'avertissement et améliore au passage la lisibilité (séparateurs de
milliers, mois abrégés). Les grilles elles-mêmes ne sont pas modifiées :
tous les calculs et les exports continuent de travailler sur les valeurs
numériques d'origine.
"""

from __future__ import annotations

import datetime

import pandas as pd

from core.charts import fmt_month


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def format_cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (datetime.datetime, datetime.date)):
        return fmt_month(v)
    if _is_number(v):
        if isinstance(v, float) and not v.is_integer():
            return f"{v:,.2f}".replace(",", " ").replace(".", ",")
        return f"{v:,.0f}".replace(",", " ")
    return str(v)


def grid_to_display_df(grid: list[list]) -> pd.DataFrame:
    """Convertit une grille en DataFrame de texte, prêt pour st.dataframe.

    Les colonnes sont numérotées comme dans Excel (A, B, C…) afin que
    l'utilisateur puisse faire le lien avec le fichier source, notamment
    quand le contrôle qualité signale une cellule précise (ex. AB13).
    """
    if not grid:
        return pd.DataFrame()

    max_cols = max((len(row) for row in grid), default=0)
    rows = [[format_cell(row[c]) if c < len(row) else "" for c in range(max_cols)] for row in grid]

    from openpyxl.utils import get_column_letter
    columns = [get_column_letter(c + 1) for c in range(max_cols)]
    index = [str(i + 1) for i in range(len(rows))]  # numéros de ligne Excel
    return pd.DataFrame(rows, columns=columns, index=index)
