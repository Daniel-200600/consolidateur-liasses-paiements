"""
core/cartographie.py

Cartographie du gabarit : pour chaque feuille et chaque ligne, la NATURE de
la ligne (titre de tableau, donnée, en-tête, note).

Pourquoi ce module
------------------
La reconnaissance des lignes repose aujourd'hui sur des heuristiques
(proportion de majuscules, proximité d'un en-tête de colonnes, préfixe
« A- »…). Elles fonctionnent sur les liasses connues, mais se sont révélées
fragiles : « VISA » a été pris pour un titre, « MASTERCARD » a disparu du
récapitulatif, des lignes « TOTAL » ont été avalées. Un gabarit légèrement
remanié peut les mettre en défaut.

Le modèle local sert donc à établir cette cartographie UNE FOIS, à partir des
seuls libellés. Elle est ensuite relue, validée, puis enregistrée : les
exécutions suivantes n'appellent plus le modèle et restent parfaitement
reproductibles.

Garde-fous
----------
- Aucun montant n'est transmis au modèle, seulement des libellés.
- Une entrée n'est appliquée que si le libellé du fichier correspond
  exactement à celui enregistré : un gabarit modifié ne peut pas se voir
  appliquer une cartographie périmée.
- Sans fichier de cartographie, l'application fonctionne exactement comme
  avant : le modèle est un confort, jamais une dépendance.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from core.indicators import _measure_header, _norm as normalize, _ouvre_un_bloc
from core.llm import ROLE_DONNEE, ROLE_ENTETE, ROLE_NOTE, ROLE_TITRE, ClientOllama, Verdict
from core.parsing import KNOWN_SHEETS, Institution

VERSION_FORMAT = 1


def chemin_par_defaut() -> Path:
    """Hors du dossier du projet, comme l'historique : remplacer le dossier
    par une nouvelle version ne doit pas effacer une cartographie validée."""
    override = os.environ.get("CONSOLIDATEUR_CARTOGRAPHIE")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".consolidateur-liasses" / "cartographie.json"


@dataclass
class EntreeCartographie:
    sheet: str
    row: int
    libelle: str
    role: str
    origine: str = "modele"      # "modele" | "heuristique" | "humain"


@dataclass
class Cartographie:
    entrees: dict[tuple[str, int], EntreeCartographie] = field(default_factory=dict)
    modele: str = ""

    def role(self, sheet: str, row: int, libelle: str) -> Optional[str]:
        e = self.entrees.get((sheet, row))
        if e is None:
            return None
        # Le libellé doit correspondre : sinon le gabarit a changé et la
        # cartographie ne s'applique plus à cette ligne.
        if normalize(e.libelle) != normalize(libelle):
            return None
        return e.role

    # -- persistance ------------------------------------------------------
    def enregistrer(self, chemin: Path | None = None) -> Path:
        chemin = chemin or chemin_par_defaut()
        chemin.parent.mkdir(parents=True, exist_ok=True)
        charge = {
            "version": VERSION_FORMAT,
            "modele": self.modele,
            "entrees": [
                {"feuille": e.sheet, "ligne": e.row, "libelle": e.libelle,
                 "role": e.role, "origine": e.origine}
                for e in self.entrees.values()
            ],
        }
        chemin.write_text(json.dumps(charge, ensure_ascii=False, indent=2), encoding="utf-8")
        return chemin

    @classmethod
    def charger(cls, chemin: Path | None = None) -> "Cartographie":
        chemin = chemin or chemin_par_defaut()
        if not chemin.exists():
            return cls()
        try:
            charge = json.loads(chemin.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return cls()
        carto = cls(modele=charge.get("modele", ""))
        for e in charge.get("entrees", []):
            try:
                entree = EntreeCartographie(
                    sheet=e["feuille"], row=int(e["ligne"]), libelle=e["libelle"],
                    role=e["role"], origine=e.get("origine", "modele"),
                )
            except (KeyError, TypeError, ValueError):
                continue
            carto.entrees[(entree.sheet, entree.row)] = entree
        return carto


# --------------------------------------------------------------------------- #
# Repérage des lignes à soumettre au modèle
# --------------------------------------------------------------------------- #

def _libelle(grid: list[list], r: int) -> str:
    if r < 0 or r >= len(grid):
        return ""
    row = grid[r]
    return row[0].strip() if row and isinstance(row[0], str) and row[0].strip() else ""


def _porte_des_valeurs(grid: list[list], r: int) -> bool:
    if r >= len(grid):
        return False
    return any(isinstance(v, (int, float)) and not isinstance(v, bool) and v != 0
               for v in grid[r][1:])


def lignes_ambigues(institutions: list[Institution]) -> list[tuple[str, int, str, str, str, bool]]:
    """Lignes qu'il est utile de soumettre au modèle.

    Une ligne qui porte des valeurs chez au moins un établissement est
    forcément une ligne de données : inutile de la soumettre. Restent les
    lignes vides, précisément celles où les heuristiques se trompent — et
    cela réduit fortement le nombre d'appels, ce qui compte avec un petit
    modèle.
    """
    a_traiter = []
    for sheet in KNOWN_SHEETS:
        presents = [i for i in institutions if sheet in i.sheets]
        if not presents:
            continue
        ref = presents[0].sheets[sheet].grid
        for r in range(len(ref)):
            libelle = _libelle(ref, r)
            if not libelle or r == 0:
                continue
            if any(_porte_des_valeurs(i.sheets[sheet].grid, r) for i in presents):
                continue
            a_traiter.append((
                sheet, r, libelle,
                _libelle(ref, r - 1), _libelle(ref, r + 1),
                any(_measure_header(nxt) for nxt in ref[r + 1:r + 3]),
            ))
    return a_traiter


def role_heuristique(institutions: list[Institution], sheet: str, row: int) -> str:
    """Verdict des règles actuelles, pour comparaison avec celui du modèle."""
    presents = [i for i in institutions if sheet in i.sheets]
    if not presents:
        return ROLE_DONNEE
    grid = presents[0].sheets[sheet].grid
    if row >= len(grid):
        return ROLE_DONNEE
    if _measure_header(grid[row]):
        return ROLE_ENTETE
    if _ouvre_un_bloc(grid, row):
        return ROLE_TITRE
    libelle = _libelle(grid, row)
    if libelle.startswith("(") and len(libelle) > 20:
        return ROLE_NOTE
    return ROLE_DONNEE


def construire(institutions: list[Institution], client: ClientOllama,
               progression=None) -> tuple[Cartographie, list[dict]]:
    """Interroge le modèle sur les lignes ambiguës.

    Renvoie la cartographie proposée et le détail ligne à ligne, pour que
    l'utilisateur puisse relire — en particulier les désaccords avec les
    règles actuelles — avant de valider.
    """
    carto = Cartographie(modele=client.modele)
    details: list[dict] = []
    lignes = lignes_ambigues(institutions)

    for n, (sheet, row, libelle, precedent, suivant, suivi_entete) in enumerate(lignes, start=1):
        verdict: Verdict = client.classer(libelle, precedent, suivant, suivi_entete)
        heuristique = role_heuristique(institutions, sheet, row)
        carto.entrees[(sheet, row)] = EntreeCartographie(
            sheet=sheet, row=row, libelle=libelle, role=verdict.role, origine="modele",
        )
        details.append({
            "feuille": sheet, "ligne": row, "libelle": libelle,
            "modele": verdict.role, "heuristique": heuristique,
            "accord": verdict.role == heuristique,
            "interprete": verdict.interprete, "brut": verdict.brut,
        })
        if progression:
            progression(n, len(lignes))

    return carto, details
