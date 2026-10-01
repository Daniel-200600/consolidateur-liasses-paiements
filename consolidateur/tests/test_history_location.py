"""
tests/test_history_location.py

L'historique s'accumule dans le temps : il ne doit PAS vivre dans le dossier
de l'application, sinon il est effacé à chaque remplacement du dossier par
une nouvelle version de l'outil (ce qui est arrivé à chaque phase du projet).

On vérifie ici qu'il est bien stocké hors du projet, qu'il est
paramétrable, et qu'un historique déjà commencé à l'ancien emplacement est
récupéré automatiquement.
"""

from pathlib import Path

import pandas as pd
import pytest

import core.history as history_module
from core.history import (
    HISTORY_COLUMNS, default_history_path, legacy_history_path,
    load_history, migrate_legacy_history, save_snapshot,
)

SAMPLE_ROW = {
    "periode_date": "2025-12-01", "periode": "déc-25", "date_enregistrement": "2025-12-31T10:00:00",
    "etablissements": "BanqueA, OperateurB", "porteurs_mm_total": 1232671, "porteurs_mm_actifs": 359593,
    "encours_me": 14621281997, "clients_cartes": 11386, "comptes_cartes": 29374, "cartes_debit": 21298,
    "gab_nombre": 142872, "gab_valeur": 14942539230,
}


def test_history_lives_outside_the_project_folder(monkeypatch):
    monkeypatch.delenv("CONSOLIDATEUR_HISTORIQUE", raising=False)
    path = default_history_path()
    project_root = Path(history_module.__file__).resolve().parent.parent
    assert project_root not in path.parents, (
        f"L'historique ({path}) est dans le dossier du projet ({project_root}) : "
        "il serait effacé à chaque mise à jour de l'application."
    )
    assert path.is_absolute()


def test_history_path_can_be_overridden_by_env(monkeypatch, tmp_path):
    custom = tmp_path / "dossier_partage" / "mon_historique.csv"
    monkeypatch.setenv("CONSOLIDATEUR_HISTORIQUE", str(custom))
    assert default_history_path() == custom


def test_legacy_history_is_migrated_once(tmp_path, monkeypatch):
    legacy = tmp_path / "ancien" / "historique.csv"
    legacy.parent.mkdir(parents=True)
    pd.DataFrame([SAMPLE_ROW])[HISTORY_COLUMNS].to_csv(legacy, index=False)

    new_path = tmp_path / "nouveau" / "historique.csv"
    monkeypatch.setattr(history_module, "legacy_history_path", lambda: legacy)

    assert migrate_legacy_history(new_path) is True
    assert new_path.exists()
    assert len(load_history(new_path)) == 1

    # Deuxième appel : plus rien à migrer, et surtout on n'écrase pas les
    # données déjà accumulées au nouvel emplacement.
    assert migrate_legacy_history(new_path) is False


def test_migration_never_overwrites_existing_history(tmp_path, monkeypatch):
    legacy = tmp_path / "ancien" / "historique.csv"
    legacy.parent.mkdir(parents=True)
    pd.DataFrame([SAMPLE_ROW])[HISTORY_COLUMNS].to_csv(legacy, index=False)

    new_path = tmp_path / "nouveau" / "historique.csv"
    new_path.parent.mkdir(parents=True)
    recent = dict(SAMPLE_ROW, periode_date="2026-01-01", periode="janv-26", porteurs_mm_actifs=400000)
    pd.DataFrame([recent])[HISTORY_COLUMNS].to_csv(new_path, index=False)

    monkeypatch.setattr(history_module, "legacy_history_path", lambda: legacy)
    assert migrate_legacy_history(new_path) is False

    df = load_history(new_path)
    assert len(df) == 1
    assert df.loc[0, "porteurs_mm_actifs"] == 400000  # les données récentes sont intactes


def test_save_snapshot_triggers_migration(tmp_path, monkeypatch):
    legacy = tmp_path / "ancien" / "historique.csv"
    legacy.parent.mkdir(parents=True)
    old_row = dict(SAMPLE_ROW, periode_date="2025-11-01", periode="nov-25")
    pd.DataFrame([old_row])[HISTORY_COLUMNS].to_csv(legacy, index=False)

    new_path = tmp_path / "nouveau" / "historique.csv"
    monkeypatch.setattr(history_module, "legacy_history_path", lambda: legacy)

    df = save_snapshot(SAMPLE_ROW, new_path)
    # L'ancienne période migrée ET la nouvelle doivent coexister.
    assert len(df) == 2
    assert list(df["periode"]) == ["nov-25", "déc-25"]
