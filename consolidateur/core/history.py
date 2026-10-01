"""
core/history.py

Phase 9 du Cahier des charges (optionnelle, cadrée séparément) :
historisation multi-période.

Règles retenues lors du cadrage de cette phase :
- Enregistrement AUTOMATIQUE à chaque consolidation réussie.
- Stockage dans un fichier CSV local (lisible/modifiable à la main).
- Une ligne par PÉRIODE (mois) : si une consolidation est relancée pour une
  période déjà enregistrée (cas normal, puisque Streamlit relance le script
  à chaque interaction), la ligne existante est mise à jour plutôt que
  dupliquée. La période est déduite du dernier mois Mobile Money commun
  utilisé pour les indicateurs (cf. core/kpis.py) ; à défaut de donnée
  Mobile Money, le mois courant sert de repli.
- Le CSV ne stocke que les totaux marché (pas le détail par établissement) :
  l'historique répond à "comment le marché évolue-t-il dans le temps",
  la répartition par établissement restant du ressort du tableau de bord
  du jour (Phases 4 à 6).
"""

from __future__ import annotations

import datetime
import os
import shutil
from pathlib import Path

import pandas as pd

from core.charts import fmt_month
from core.kpis import KpiResult, find_date_columns
from core.parsing import Institution

# Colonnes numériques de l'historique, avec leur libellé d'affichage.
HISTORY_KPI_COLUMNS: dict[str, str] = {
    "porteurs_mm_total": "Porteurs Mobile Money (total cumulé)",
    "porteurs_mm_actifs": "Porteurs Mobile Money actifs",
    "encours_me": "Encours de monnaie électronique (XAF)",
    "clients_cartes": "Clients porteurs de cartes",
    "comptes_cartes": "Comptes cartes",
    "cartes_debit": "Cartes de débit émises",
    "gab_nombre": "Retraits GAB - nombre",
    "gab_valeur": "Retraits GAB - valeur (XAF)",
}

HISTORY_COLUMNS = ["periode_date", "periode", "date_enregistrement", "etablissements"] + list(HISTORY_KPI_COLUMNS)


def default_history_path() -> Path:
    """Emplacement de l'historique, HORS du dossier de l'application.

    L'historique est une donnée métier qui s'accumule dans le temps : le
    ranger dans le dossier du projet l'exposerait à être effacé à chaque
    remplacement du dossier par une nouvelle version de l'outil. On le place
    donc dans le dossier personnel de l'utilisateur.

    Peut être redéfini via la variable d'environnement
    CONSOLIDATEUR_HISTORIQUE (utile pour pointer un dossier partagé ou
    sauvegardé automatiquement).
    """
    override = os.environ.get("CONSOLIDATEUR_HISTORIQUE")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".consolidateur-liasses" / "historique.csv"


def legacy_history_path() -> Path:
    """Ancien emplacement (dans le dossier du projet), conservé uniquement
    pour migrer automatiquement un historique déjà commencé."""
    return Path(__file__).resolve().parent.parent / "data" / "historique.csv"


def migrate_legacy_history(path: Path | None = None) -> bool:
    """Recopie l'historique de l'ancien emplacement vers le nouveau, s'il
    existe et que le nouveau est encore vide. Renvoie True si une migration
    a eu lieu."""
    path = path or default_history_path()
    legacy = legacy_history_path()
    if path.exists() or not legacy.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(legacy, path)
    return True


def determine_period(institutions: list[Institution], kpis: list[KpiResult]) -> datetime.date:
    """1er jour du mois représentant la période consolidée : le dernier mois
    Mobile Money commun utilisé pour les indicateurs, ou le mois courant à
    défaut (cf. règle de cadrage ci-dessus)."""
    mm_kpi = next((k for k in kpis if k.sheet == "Mobile Money1" and k.col is not None and k.col >= 0), None)
    if mm_kpi:
        for inst in institutions:
            sd = inst.sheets.get("Mobile Money1")
            if not sd:
                continue
            header_row, _ = find_date_columns(sd.grid)
            if header_row == -1 or mm_kpi.col >= len(sd.grid[header_row]):
                continue
            d = sd.grid[header_row][mm_kpi.col]
            if isinstance(d, (datetime.datetime, datetime.date)):
                return datetime.date(d.year, d.month, 1)
    today = datetime.date.today()
    return datetime.date(today.year, today.month, 1)


def build_snapshot_row(institutions: list[Institution], kpis: list[KpiResult], gab: dict) -> dict:
    period_date = determine_period(institutions, kpis)
    kpi_totals = {k.key: k.total for k in kpis}
    row = {
        "periode_date": period_date.isoformat(),
        "periode": fmt_month(period_date),
        "date_enregistrement": datetime.datetime.now().isoformat(timespec="seconds"),
        "etablissements": ", ".join(inst.name for inst in institutions),
        "porteurs_mm_total": kpi_totals.get("porteurs_mm_total", 0),
        "porteurs_mm_actifs": kpi_totals.get("porteurs_mm_actifs", 0),
        "encours_me": kpi_totals.get("encours_me", 0),
        "clients_cartes": kpi_totals.get("clients_cartes", 0),
        "comptes_cartes": kpi_totals.get("comptes_cartes", 0),
        "cartes_debit": kpi_totals.get("cartes_debit", 0),
        "gab_nombre": gab["total"]["nombre"],
        "gab_valeur": gab["total"]["valeur"],
    }
    return row


def load_history(path: Path | None = None) -> pd.DataFrame:
    path = path or default_history_path()
    if not path.exists():
        return pd.DataFrame(columns=HISTORY_COLUMNS)
    df = pd.read_csv(path)
    for col in HISTORY_COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df.sort_values("periode_date").reset_index(drop=True)


def save_snapshot(row: dict, path: Path | None = None) -> pd.DataFrame:
    """Enregistre (ou met à jour, si la période existe déjà) une ligne dans
    l'historique CSV. Renvoie l'historique complet, trié chronologiquement."""
    path = path or default_history_path()
    migrate_legacy_history(path)  # récupère un historique commencé à l'ancien emplacement
    path.parent.mkdir(parents=True, exist_ok=True)
    df = load_history(path)
    df = df[df["periode_date"] != row["periode_date"]]  # retire l'éventuelle ligne existante pour cette période
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df = df.sort_values("periode_date").reset_index(drop=True)
    df.to_csv(path, index=False)
    return df


def compute_deltas(df: pd.DataFrame, current_period_date: str) -> dict[str, float | None]:
    """Variation de chaque indicateur entre `current_period_date` et la
    période juste avant elle dans l'historique. None si pas de période
    antérieure disponible (ex. première consolidation)."""
    if df.empty:
        return {col: None for col in HISTORY_KPI_COLUMNS}
    df_sorted = df.sort_values("periode_date").reset_index(drop=True)
    matches = df_sorted.index[df_sorted["periode_date"] == current_period_date]
    if len(matches) == 0 or matches[0] == 0:
        return {col: None for col in HISTORY_KPI_COLUMNS}
    idx = matches[0]
    cur, prev = df_sorted.loc[idx], df_sorted.loc[idx - 1]
    deltas = {}
    for col in HISTORY_KPI_COLUMNS:
        try:
            deltas[col] = float(cur[col]) - float(prev[col])
        except (TypeError, ValueError):
            deltas[col] = None
    return deltas
