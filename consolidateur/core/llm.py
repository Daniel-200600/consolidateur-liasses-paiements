"""
core/llm.py

Client minimal pour un modèle de langage servi localement par Ollama.

Périmètre volontairement étroit (cf. arbitrage retenu) : le modèle sert
UNIQUEMENT à qualifier la nature des lignes d'un gabarit — titre de tableau,
ligne de données, en-tête de colonnes, note. Il ne voit aucun montant et
n'intervient jamais dans un calcul : les totaux transmis au régulateur
restent produits par du code déterministe.

Confidentialité : seuls des LIBELLÉS sont transmis, à un serveur tournant sur
la machine (http://localhost:11434). Aucune donnée ne quitte le poste, ce qui
respecte l'exigence du cahier des charges (section 7).

Aucune dépendance nouvelle : la requête HTTP passe par urllib (bibliothèque
standard).
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

URL_PAR_DEFAUT = "http://localhost:11434"
MODELE_PAR_DEFAUT = "gemma3:1b"

# Réponses acceptées du modèle.
ROLE_TITRE = "TITRE"
ROLE_DONNEE = "DONNEE"
ROLE_ENTETE = "ENTETE"
ROLE_NOTE = "NOTE"
ROLES = (ROLE_TITRE, ROLE_DONNEE, ROLE_ENTETE, ROLE_NOTE)

# Un transport est une fonction (url, charge_utile, delai) -> texte de réponse.
# L'injecter permet de tester toute la logique sans serveur Ollama.
Transport = Callable[[str, dict, float], str]


def _transport_http(url: str, charge: dict, delai: float) -> str:
    requete = urllib.request.Request(
        url,
        data=json.dumps(charge).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(requete, timeout=delai) as reponse:
        return reponse.read().decode("utf-8")


@dataclass
class Verdict:
    """Nature attribuée à une ligne par le modèle."""

    libelle: str
    role: str               # l'un de ROLES
    brut: str = ""          # réponse brute, conservée pour vérification
    interprete: bool = True  # False si la réponse n'a pas pu être décodée


class ClientOllama:
    def __init__(self, url: str = URL_PAR_DEFAUT, modele: str = MODELE_PAR_DEFAUT,
                 transport: Optional[Transport] = None, delai: float = 60.0):
        self.url = url.rstrip("/")
        self.modele = modele
        self._transport = transport or _transport_http
        self.delai = delai

    # -- disponibilité ----------------------------------------------------
    def modeles_disponibles(self) -> list[str]:
        """Liste les modèles installés. Renvoie [] si Ollama ne répond pas —
        l'application doit rester utilisable sans lui."""
        try:
            requete = urllib.request.Request(f"{self.url}/api/tags", method="GET")
            with urllib.request.urlopen(requete, timeout=5) as rep:
                data = json.loads(rep.read().decode("utf-8"))
            return [m.get("name", "") for m in data.get("models", [])]
        except Exception:
            return []

    def disponible(self) -> bool:
        return bool(self.modeles_disponibles())

    # -- classification ---------------------------------------------------
    def _invite(self, libelle: str, precedent: str, suivant: str,
               suivi_entete: bool) -> str:
        """Invite courte et très cadrée : le modèle visé (1 milliard de
        paramètres) suit mal les consignes longues ou nuancées."""
        return (
            "Tu classes une ligne d'un tableau statistique bancaire.\n"
            "Réponds par UN SEUL mot parmi : TITRE, DONNEE, ENTETE, NOTE.\n\n"
            "TITRE = intitulé qui ouvre un tableau (CHEQUES, VIREMENTS)\n"
            "DONNEE = poste chiffrable (VISA, Retrait GAB, Total A, - dont Cameroun)\n"
            "ENTETE = en-tête de colonnes (Nombre, Valeur, Montant)\n"
            "NOTE = note de bas de tableau ou consigne de remplissage\n\n"
            "Exemples :\n"
            "Ligne: \"CHEQUES\" -> TITRE\n"
            "Ligne: \"MASTERCARD\" -> DONNEE\n"
            "Ligne: \"Nombre\" -> ENTETE\n"
            "Ligne: \"(1) porteurs ayant effectué une transaction\" -> NOTE\n\n"
            f"Ligne précédente: \"{precedent}\"\n"
            f"Ligne à classer: \"{libelle}\"\n"
            f"Ligne suivante: \"{suivant}\"\n"
            f"Un en-tête de colonnes suit immédiatement: {'oui' if suivi_entete else 'non'}\n"
            "Réponse:"
        )

    def classer(self, libelle: str, precedent: str = "", suivant: str = "",
                suivi_entete: bool = False) -> Verdict:
        charge = {
            "model": self.modele,
            "prompt": self._invite(libelle, precedent, suivant, suivi_entete),
            "stream": False,
            # Température nulle : un rapport réglementaire doit rester
            # reproductible d'une exécution à l'autre.
            "options": {"temperature": 0, "num_predict": 8},
        }
        try:
            brut = self._transport(f"{self.url}/api/generate", charge, self.delai)
        except Exception as exc:                       # serveur absent, modèle inconnu…
            return Verdict(libelle, ROLE_DONNEE, brut=f"erreur: {exc}", interprete=False)

        try:
            texte = json.loads(brut).get("response", "")
        except json.JSONDecodeError:
            texte = brut

        role = _extraire_role(texte)
        if role is None:
            # Repli prudent : en cas de réponse indécodable, la ligne est
            # traitée comme une DONNÉE. Mieux vaut afficher une ligne de trop
            # que d'en faire disparaître une.
            return Verdict(libelle, ROLE_DONNEE, brut=texte.strip(), interprete=False)
        return Verdict(libelle, role, brut=texte.strip(), interprete=True)


def _extraire_role(texte: str) -> Optional[str]:
    majuscules = texte.upper()
    positions = [(majuscules.find(role), role) for role in ROLES if role in majuscules]
    if not positions:
        return None
    return min(positions)[1]      # le premier rôle cité dans la réponse
