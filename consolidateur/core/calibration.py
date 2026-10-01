"""
core/calibration.py

Mémorisation des rattachements d'onglets validés par l'utilisateur.

Un onglet non reconnu automatiquement (cf. core.sheet_matching) peut être
proposé à l'utilisateur avec une suggestion — jamais appliqué sans un
geste explicite. Une fois validé d'un clic, le rattachement est mémorisé :
un prochain fichier portant un onglet du même nom (« RIA 25-26 »,
« Cartes_2025 »…) sera reconnu directement, sans redemander de validation.

Stocké hors du dossier projet, comme la cartographie IA et l'historique :
remplacer le dossier de l'application ne doit jamais effacer un
rattachement déjà validé — c'est précisément ce qui permet de ne quasiment
rien avoir à refaire à la main d'un fichier à l'autre.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


def chemin_par_defaut() -> Path:
    override = os.environ.get("CONSOLIDATEUR_CALIBRATION")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".consolidateur-liasses" / "calibration.json"


def cle_onglet(nom_onglet: str) -> str:
    s = nom_onglet.strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


@dataclass
class Calibration:
    # clé_onglet -> thème (onglet simple) OU liste de thèmes (onglet composite)
    rattachements: dict[str, "str | list[str]"] = field(default_factory=dict)

    def theme_pour(self, nom_onglet: str) -> Optional[str]:
        v = self.rattachements.get(cle_onglet(nom_onglet))
        return v if isinstance(v, str) else None

    def segments_pour(self, nom_onglet: str) -> Optional[list[str]]:
        """Thèmes validés pour un onglet COMPOSITE (plusieurs segments dans
        le même onglet, cf. core.sheet_matching.detecter_segments)."""
        v = self.rattachements.get(cle_onglet(nom_onglet))
        return v if isinstance(v, list) else None

    def valider(self, nom_onglet: str, theme: str) -> None:
        self.rattachements[cle_onglet(nom_onglet)] = theme

    def valider_segments(self, nom_onglet: str, themes: list[str]) -> None:
        self.rattachements[cle_onglet(nom_onglet)] = list(themes)

    def oublier(self, nom_onglet: str) -> None:
        self.rattachements.pop(cle_onglet(nom_onglet), None)

    def enregistrer(self, chemin: Optional[Path] = None) -> Path:
        chemin = chemin or chemin_par_defaut()
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(json.dumps(self.rattachements, ensure_ascii=False, indent=2), encoding="utf-8")
        return chemin

    @classmethod
    def charger(cls, chemin: Optional[Path] = None) -> "Calibration":
        chemin = chemin or chemin_par_defaut()
        if not chemin.exists():
            return cls()
        try:
            data = json.loads(chemin.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return cls()
        return cls(rattachements=data if isinstance(data, dict) else {})
