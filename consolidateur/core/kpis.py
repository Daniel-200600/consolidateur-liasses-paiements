"""
core/kpis.py

Phase 4 du Cahier des charges : indicateurs clés (KPI).

Les règles d'extraction implémentées ici reprennent exactement le tableau de
la section 6 du Cahier des charges. Toute modification de ce tableau doit
être répercutée ici.

Deux modes d'extraction :
- "latest_month"  : indicateur mensuel (onglet Mobile Money1). La colonne
                     retenue est la plus récente colonne de date pour
                     laquelle AU MOINS UN établissement a une valeur
                     numérique — elle s'adapte donc automatiquement aux mois
                     disponibles, sans valeur codée en dur.
- "first_value"   : indicateur "instantané" (onglet Cartes1). On prend la
                     première valeur numérique de la ligne trouvée.

Le cas "Retraits GAB" (onglet Cartes 5) est traité à part par
`retrait_gab_kpi`, car le libellé "Retrait GAB" se répète à l'identique dans
4 sections différentes de l'onglet : il faut donc se positionner par rapport
à la section "TRANSACTIONS DE VOS PORTEURS" avant de chercher la ligne.
"""

from __future__ import annotations

import datetime
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Callable, Optional

from core.parsing import Institution, SheetData


def normalize(value) -> str:
    """Normalise un libellé pour une comparaison tolérante aux accents, à la
    casse et à la ponctuation (cf. CDC section 6, remarque finale)."""
    if value is None:
        return ""
    s = str(value).lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return s


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_date(v) -> bool:
    return isinstance(v, (datetime.datetime, datetime.date))


def find_row_index(grid: list[list], matcher: Callable[[str], bool], from_row: int = 0, to_row: Optional[int] = None) -> int:
    end = len(grid) if to_row is None else min(to_row, len(grid))
    for r in range(from_row, end):
        label = normalize(grid[r][0] if grid[r] else None)
        if matcher(label):
            return r
    return -1


def find_date_columns(grid: list[list], max_scan_rows: int = 6) -> tuple[int, list[int]]:
    for r in range(min(max_scan_rows, len(grid))):
        cols = [c for c, v in enumerate(grid[r]) if _is_date(v)]
        if len(cols) >= 2:
            return r, cols
    return -1, []


def latest_common_column(sheet_datas: list[SheetData], matcher: Callable[[str], bool]) -> int:
    """Colonne de date la plus récente pour laquelle au moins un établissement
    a une valeur numérique sur la ligne recherchée."""
    best_col = -1
    for sd in sheet_datas:
        _, cols = find_date_columns(sd.grid)
        r = find_row_index(sd.grid, matcher)
        if r == -1:
            continue
        row = sd.grid[r]
        for c in reversed(cols):
            v = row[c] if c < len(row) else None
            if _is_number(v):
                best_col = max(best_col, c)
                break
    return best_col


def value_at(sheet_data: Optional[SheetData], matcher: Callable[[str], bool], col: int) -> float:
    if sheet_data is None or col < 0:
        return 0
    r = find_row_index(sheet_data.grid, matcher)
    if r == -1:
        return 0
    row = sheet_data.grid[r]
    v = row[col] if col < len(row) else None
    return v if _is_number(v) else 0


def first_numeric_in_row(sheet_data: Optional[SheetData], matcher: Callable[[str], bool], to_row: Optional[int] = None) -> float:
    if sheet_data is None:
        return 0
    r = find_row_index(sheet_data.grid, matcher, 0, to_row)
    if r == -1:
        return 0
    row = sheet_data.grid[r]
    for v in row[1:]:
        if _is_number(v):
            return v
    return 0


# Tableau de référence — cf. Cahier des charges, section 6.
KPI_DEFS = [
    {
        "key": "porteurs_mm_total", "label": "Porteurs Mobile Money (total cumulé)",
        "sheet": "Mobile Money1", "mode": "latest_month",
        "matcher": lambda l: "nombre total de porteurs de mobile money" in l,
    },
    {
        "key": "porteurs_mm_actifs", "label": "Porteurs Mobile Money actifs",
        "sheet": "Mobile Money1", "mode": "latest_month",
        "matcher": lambda l: "nombre de porteurs de mobile money actifs" in l,
    },
    {
        "key": "encours_me", "label": "Encours de monnaie électronique (XAF)",
        "sheet": "Mobile Money1", "mode": "latest_month",
        "matcher": lambda l: "solde du compte" in l,
    },
    {
        "key": "clients_cartes", "label": "Clients porteurs de cartes",
        "sheet": "Cartes1", "mode": "first_value", "to_row": 6,
        "matcher": lambda l: "client" in l,
    },
    {
        "key": "comptes_cartes", "label": "Comptes cartes",
        "sheet": "Cartes1", "mode": "first_value", "to_row": 6,
        "matcher": lambda l: "nombre de comptes" in l,
    },
    {
        "key": "cartes_debit", "label": "Cartes de débit émises",
        "sheet": "Cartes1", "mode": "first_value",
        "matcher": lambda l: l == "cartes de debit",
    },
]


@dataclass
class KpiResult:
    key: str
    label: str
    sheet: str
    mode: str
    per_inst: list[tuple[str, float]] = field(default_factory=list)
    total: float = 0
    col: Optional[int] = None
    # Établissements dont l'onglet contient de vraies données, mais dans
    # lequel le libellé recherché est introuvable. C'est le signal d'une
    # évolution du gabarit BEAC (ou d'une saisie non conforme) : sans cette
    # trace, l'indicateur retomberait silencieusement à 0 et ce 0 se
    # propagerait jusqu'au Total marché et aux exports.
    missing_label_for: list[str] = field(default_factory=list)


def _sheet_has_real_data(sheet_data: Optional[SheetData]) -> bool:
    """Vrai si l'onglet contient au moins une valeur numérique non nulle, en
    excluant les en-têtes d'année (ex. 2025) qui ne sont pas des données
    métier — même règle que core.quality.has_real_data."""
    if sheet_data is None:
        return False
    for row in sheet_data.grid:
        for v in row:
            if _is_number(v) and v != 0:
                if isinstance(v, int) and 2000 <= v <= 2100:
                    continue
                return True
    return False


def compute_kpis(institutions: list[Institution]) -> list[KpiResult]:
    results: list[KpiResult] = []
    for d in KPI_DEFS:
        sheet_name = d["sheet"]
        matcher = d["matcher"]
        col = None
        if d["mode"] == "latest_month":
            present = [inst.sheets[sheet_name] for inst in institutions if sheet_name in inst.sheets]
            col = latest_common_column(present, matcher)

        per_inst = []
        missing_label_for = []
        for inst in institutions:
            sd = inst.sheets.get(sheet_name)
            if d["mode"] == "latest_month":
                value = value_at(sd, matcher, col) if col is not None else 0
            else:
                value = first_numeric_in_row(sd, matcher, d.get("to_row"))
            per_inst.append((inst.name, value))

            # Anomalie seulement si l'onglet est réellement renseigné : un
            # établissement qui ne couvre pas ce domaine (onglet vide) est un
            # cas normal, déjà signalé par ailleurs comme "onglet vide".
            if _sheet_has_real_data(sd):
                to_row = d.get("to_row") if d["mode"] != "latest_month" else None
                if find_row_index(sd.grid, matcher, 0, to_row) == -1:
                    missing_label_for.append(inst.name)

        results.append(KpiResult(
            key=d["key"], label=d["label"], sheet=sheet_name, mode=d["mode"],
            per_inst=per_inst, total=sum(v for _, v in per_inst), col=col,
            missing_label_for=missing_label_for,
        ))
    return results


def retrait_gab_kpi(institutions: list[Institution]) -> dict:
    """Cf. CDC section 6 : lecture contextuelle après la section
    "TRANSACTIONS DE VOS PORTEURS" de l'onglet Cartes 5."""

    def get(sd: Optional[SheetData]) -> tuple[float, float, bool]:
        """Renvoie (nombre, valeur, found) — `found` distingue "vraiment 0"
        de "structure attendue introuvable" (cf. KpiResult.missing_label_for)."""
        if sd is None:
            return 0, 0, False
        grid = sd.grid
        section = find_row_index(grid, lambda l: "transactions de vos porteurs" in l)
        if section == -1:
            return 0, 0, False
        next_section = find_row_index(grid, lambda l: "transactions des porteurs de la cemac" in l, section + 1)
        to_row = next_section if next_section != -1 else None
        r = find_row_index(grid, lambda l: "retrait gab" in l, section + 1, to_row)
        if r == -1:
            return 0, 0, False
        row = grid[r]
        nombre = row[1] if len(row) > 1 and _is_number(row[1]) else 0
        valeur = row[2] if len(row) > 2 and _is_number(row[2]) else 0
        return nombre, valeur, True

    per_inst = []
    missing_label_for = []
    for inst in institutions:
        sd = inst.sheets.get("Cartes 5")
        nombre, valeur, found = get(sd)
        per_inst.append({"name": inst.name, "nombre": nombre, "valeur": valeur})
        # Même règle que compute_kpis : anomalie seulement si l'onglet est
        # réellement renseigné mais que la structure attendue est absente.
        if not found and _sheet_has_real_data(sd):
            missing_label_for.append(inst.name)

    return {
        "per_inst": per_inst,
        "missing_label_for": missing_label_for,
        "total": {
            "nombre": sum(p["nombre"] for p in per_inst),
            "valeur": sum(p["valeur"] for p in per_inst),
        },
    }
