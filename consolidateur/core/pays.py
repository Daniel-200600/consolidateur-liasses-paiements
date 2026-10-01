"""
core/pays.py

Détection du pays d'un établissement, à partir du nom de son fichier.

Les 6 pays de la CEMAC ne sont pas codés de façon uniforme d'un fichier à
l'autre : on l'a constaté concrètement dès les tout premiers fichiers reçus
— un établissement centrafricain a nommé son fichier « BanqueA_CA-… », un autre
« OperateurB_RCA_… », pour le même pays. La détection couvre donc plusieurs
codes par pays, mais reste — comme le nom d'établissement — une PROPOSITION
modifiable en un clic, jamais une affectation silencieuse : un pays mal
détecté fausserait un total pays sans que rien ne le signale.
"""

from __future__ import annotations

import re
import unicodedata

PAYS_CEMAC: dict[str, dict] = {
    "CM": {
        "nom": "Cameroun",
        "codes": ["CM", "CMR"],
        "mots": ["cameroun", "cameroon"],
    },
    "CF": {
        "nom": "République Centrafricaine",
        # « CA » est ambigu (pourrait être une coïncidence) mais correspond
        # à un cas réel constaté ; « RCA » et « CAF » aussi rencontrés.
        "codes": ["CF", "RCA", "CAF", "CA"],
        "mots": ["centrafrique", "centrafricaine", "republique centrafricaine"],
    },
    "CG": {
        "nom": "Congo",
        "codes": ["CG", "COG"],
        "mots": ["congo"],
    },
    "GA": {
        "nom": "Gabon",
        "codes": ["GA", "GAB"],
        "mots": ["gabon"],
    },
    "GQ": {
        "nom": "Guinée Équatoriale",
        "codes": ["GQ", "GNQ", "EG"],
        "mots": ["guinee equatoriale", "guinee equatorial", "equatorial guinea"],
    },
    "TD": {
        "nom": "Tchad",
        "codes": ["TD", "TCD"],
        "mots": ["tchad", "chad"],
    },
}

NOM_PAYS = {code: v["nom"] for code, v in PAYS_CEMAC.items()}
PAYS_NON_DETECTE = "Non déterminé"


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def detecter_pays(nom_fichier: str) -> str | None:
    """Renvoie le code pays (CM/CF/CG/GA/GQ/TD) détecté dans un nom de
    fichier, ou None si rien de fiable n'a été trouvé.

    Les codes courts (2-3 lettres, ex. « CM », « CA ») ne sont reconnus que
    comme TOKEN ISOLÉ — délimité par un séparateur (« - », « _ », espace,
    début/fin de nom) — jamais comme simple sous-chaîne : sans cette
    précaution, « CA » matcherait à tort à l'intérieur d'un mot comme
    « Cartes » ou « Cash ». Les noms complets de pays, eux, sont recherchés
    n'importe où dans le nom, insensibles à la casse et aux accents.
    """
    base = nom_fichier.rsplit(".", 1)[0]
    tokens = [t for t in re.split(r"[^A-Za-z0-9]+", base) if t]
    tokens_upper = {t.upper() for t in tokens}
    texte_norm = _norm(base)

    for code, info in PAYS_CEMAC.items():
        if any(c in tokens_upper for c in info["codes"]):
            return code

    for code, info in PAYS_CEMAC.items():
        if any(mot in texte_norm for mot in info["mots"]):
            return code

    return None
