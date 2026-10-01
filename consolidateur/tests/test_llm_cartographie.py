"""
tests/test_llm_cartographie.py

Assistance d'un modèle local (Ollama) pour qualifier les lignes du gabarit.

Le serveur Ollama n'étant pas nécessairement présent, toute la logique est
testée au travers d'un TRANSPORT SIMULÉ : les tests couvrent la construction
de l'invite, le décodage des réponses, les cas de panne, la persistance et
l'effet sur la lecture des liasses — sans dépendre d'un modèle installé.

Exigence structurante vérifiée ici : sans cartographie ni serveur,
l'application se comporte exactement comme avant. Le modèle est un confort,
jamais une dépendance.
"""

import json
from pathlib import Path

import pytest

from core.cartographie import (
    Cartographie, EntreeCartographie, construire, lignes_ambigues, role_heuristique,
)
from core.indicators import discover_indicators
from core.llm import (
    MODELE_PAR_DEFAUT, ROLE_DONNEE, ROLE_ENTETE, ROLE_NOTE, ROLE_TITRE,
    ClientOllama, _extraire_role,
)
from core.parsing import Institution, parse_workbook

FIXTURES = Path(__file__).parent / "fixtures_fictives"


@pytest.fixture(scope="module")
def institutions():
    return [
        Institution(name="BanqueA", file_name="BanqueA.xlsx", sheets=parse_workbook(FIXTURES / "BanqueA.xlsx")),
        Institution(name="OperateurB", file_name="OperateurB.xlsx", sheets=parse_workbook(FIXTURES / "OperateurB.xlsx")),
    ]


def transport_fixe(reponse: str):
    """Simule Ollama : renvoie toujours la même réponse."""
    def _t(url, charge, delai):
        return json.dumps({"response": reponse})
    return _t


def transport_selon_libelle(table: dict[str, str], defaut: str = "DONNEE"):
    """Simule un modèle qui répond selon le libellé présent dans l'invite."""
    def _t(url, charge, delai):
        invite = charge["prompt"]
        for libelle, role in table.items():
            if f'Ligne à classer: "{libelle}"' in invite:
                return json.dumps({"response": role})
        return json.dumps({"response": defaut})
    return _t


# --------------------------------------------------------------------- #
# Décodage des réponses
# --------------------------------------------------------------------- #

@pytest.mark.parametrize("reponse, attendu", [
    ("TITRE", ROLE_TITRE),
    ("DONNEE", ROLE_DONNEE),
    (" entete ", ROLE_ENTETE),
    ("note", ROLE_NOTE),
    ("La réponse est TITRE.", ROLE_TITRE),
    ("DONNEE\n", ROLE_DONNEE),
])
def test_reponses_du_modele_sont_decodees(reponse, attendu):
    client = ClientOllama(transport=transport_fixe(reponse))
    assert client.classer("CHEQUES").role == attendu


def test_reponse_incomprehensible_bascule_en_donnee():
    """Repli prudent : mieux vaut afficher une ligne de trop que d'en faire
    disparaître une du récapitulatif."""
    client = ClientOllama(transport=transport_fixe("je ne sais pas"))
    verdict = client.classer("MASTERCARD")
    assert verdict.role == ROLE_DONNEE
    assert verdict.interprete is False


def test_serveur_absent_ne_fait_pas_echouer():
    def transport_en_panne(url, charge, delai):
        raise ConnectionRefusedError("Ollama n'est pas démarré")

    client = ClientOllama(transport=transport_en_panne)
    verdict = client.classer("VISA")
    assert verdict.role == ROLE_DONNEE
    assert verdict.interprete is False
    assert "erreur" in verdict.brut


def test_disponibilite_est_fausse_sans_serveur():
    # Port volontairement inutilisé : la vérification doit renvoyer False
    # sans lever d'exception.
    assert ClientOllama(url="http://localhost:1").disponible() is False


def test_extraire_role_prend_le_premier_cite():
    assert _extraire_role("TITRE puis DONNEE") == ROLE_TITRE
    assert _extraire_role("rien de pertinent") is None


# --------------------------------------------------------------------- #
# Construction de l'invite
# --------------------------------------------------------------------- #

def test_invite_ne_contient_aucun_montant(institutions):
    """Exigence de confidentialité : seuls des libellés sont transmis."""
    captures = []

    def transport_espion(url, charge, delai):
        captures.append(charge["prompt"])
        return json.dumps({"response": "DONNEE"})

    client = ClientOllama(transport=transport_espion)
    construire(institutions, client)

    assert captures
    montants = ["1232671", "359593", "14942539230", "11386", "21298", "142872"]
    for invite in captures:
        for montant in montants:
            assert montant not in invite, f"Un montant a fuité dans l'invite : {montant}"


def test_invite_est_deterministe(institutions):
    client = ClientOllama(transport=transport_fixe("TITRE"))
    a = client._invite("CHEQUES", "", "Nombre", True)
    b = client._invite("CHEQUES", "", "Nombre", True)
    assert a == b


def test_temperature_nulle_pour_la_reproductibilite():
    captures = []

    def transport_espion(url, charge, delai):
        captures.append(charge)
        return json.dumps({"response": "TITRE"})

    ClientOllama(transport=transport_espion).classer("CHEQUES")
    assert captures[0]["options"]["temperature"] == 0
    assert captures[0]["stream"] is False


# --------------------------------------------------------------------- #
# Sélection des lignes soumises
# --------------------------------------------------------------------- #

def test_seules_les_lignes_sans_valeur_sont_soumises(institutions):
    """Une ligne portant des valeurs est forcément une donnée : l'interroger
    coûterait du temps pour rien."""
    lignes = lignes_ambigues(institutions)
    soumises = {(s, r) for s, r, *_ in lignes}
    # « Retrait GAB » de Cartes 5 (ligne 10) porte 142 872 : jamais soumis.
    assert ("Cartes 5", 10) not in soumises
    # « MASTERCARD » de Cartes 1 (ligne 19) est vide : c'est un cas ambigu.
    assert ("Cartes1", 19) in soumises


def test_le_contexte_des_lignes_est_transmis(institutions):
    lignes = {(s, r): (prec, suiv, ent) for s, r, _, prec, suiv, ent in lignes_ambigues(institutions)}
    precedent, suivant, suivi_entete = lignes[("Cartes1", 19)]
    assert precedent == "VISA"
    assert suivant == "UnionPay"
    assert suivi_entete is False


def test_verdict_heuristique_sert_de_comparaison(institutions):
    # « CHEQUES » ouvre un tableau : les règles actuelles le voient déjà.
    assert role_heuristique(institutions, "chèques&VIR", 6) == ROLE_TITRE
    # « MASTERCARD » est bien traité comme une donnée depuis la correction.
    assert role_heuristique(institutions, "Cartes1", 19) == ROLE_DONNEE


# --------------------------------------------------------------------- #
# Cartographie : persistance et application
# --------------------------------------------------------------------- #

def test_construire_signale_les_desaccords(institutions):
    client = ClientOllama(transport=transport_selon_libelle({"MASTERCARD": "TITRE"}))
    carto, details = construire(institutions, client)
    desaccords = [d for d in details if not d["accord"]]
    assert any(d["libelle"] == "MASTERCARD" for d in desaccords)
    assert all({"feuille", "ligne", "libelle", "modele", "heuristique"} <= set(d) for d in details)


def test_enregistrement_et_relecture(tmp_path, institutions):
    client = ClientOllama(transport=transport_fixe("DONNEE"))
    carto, _ = construire(institutions, client)
    chemin = tmp_path / "carto.json"
    carto.enregistrer(chemin)

    relue = Cartographie.charger(chemin)
    assert len(relue.entrees) == len(carto.entrees)
    assert relue.modele == MODELE_PAR_DEFAUT


def test_cartographie_absente_renvoie_vide(tmp_path):
    assert Cartographie.charger(tmp_path / "inexistant.json").entrees == {}


def test_fichier_corrompu_ne_fait_pas_echouer(tmp_path):
    chemin = tmp_path / "carto.json"
    chemin.write_text("{ceci n'est pas du JSON", encoding="utf-8")
    assert Cartographie.charger(chemin).entrees == {}


def test_entree_ignoree_si_le_libelle_a_change():
    """Un gabarit remanié ne doit pas se voir appliquer une cartographie
    périmée : c'est le garde-fou contre une classification devenue fausse."""
    carto = Cartographie()
    carto.entrees[("Cartes1", 19)] = EntreeCartographie(
        sheet="Cartes1", row=19, libelle="MASTERCARD", role=ROLE_TITRE)
    assert carto.role("Cartes1", 19, "MASTERCARD") == ROLE_TITRE
    assert carto.role("Cartes1", 19, "UnionPay") is None      # libellé différent
    assert carto.role("Cartes1", 99, "MASTERCARD") is None    # ligne inconnue


def test_sans_cartographie_le_resultat_est_inchange(institutions):
    """Garde-fou central : le modèle ne doit rien changer tant qu'aucune
    cartographie n'a été validée."""
    avant = discover_indicators(institutions)
    apres = discover_indicators(institutions, cartographie=Cartographie())
    assert [i.key for i in avant] == [i.key for i in apres]


def test_une_cartographie_validee_est_appliquee(institutions):
    """Requalifier une ligne en titre doit la retirer du récapitulatif."""
    avant = discover_indicators(institutions)
    assert any(i.sheet == "Cartes1" and i.row == 19 for i in avant)

    carto = Cartographie()
    carto.entrees[("Cartes1", 19)] = EntreeCartographie(
        sheet="Cartes1", row=19, libelle="MASTERCARD", role=ROLE_TITRE)
    apres = discover_indicators(institutions, cartographie=carto)

    assert not any(i.sheet == "Cartes1" and i.row == 19 for i in apres)
    assert len(apres) == len(avant) - 1
