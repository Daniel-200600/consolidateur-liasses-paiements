"""
tests/test_sheet_matching.py

Étape 1 : reconnaissance de familles d'onglets.

Le gabarit officiel BEAC demande, pour certains thèmes, de « remplir un
formulaire pour chaque réseau ». Un établissement qui suit cette consigne
produit plusieurs onglets (« Cartes 2 GIMAC », « Cartes 2 VISA »…) là où
BanqueA, notre référence initiale, n'en produisait qu'un seul — ce n'est donc
pas une anomalie mais un usage légitime et même plus conforme du gabarit.

Ces tests s'appuient sur 8 fichiers RÉELS reçus d'établissements du Cameroun
(tests/fixtures/cameroun/), qui ont révélé ce besoin et deux pièges concrets :
- une ligne vide insérée en tête de fichier peut décaler toute la
  comparaison position par position (d'où l'alignement par plus longue
  sous-séquence commune, tolérant aux insertions/suppressions) ;
- un onglet composite regroupant plusieurs thèmes peut malgré tout
  contenir un fragment qui ressemble fortement à un thème canonique bien
  plus petit (d'où le garde-fou sur le ratio de taille).
"""

from pathlib import Path

import pytest

from core.parsing import KNOWN_SHEETS, analyser_fichier, parse_workbook
from core.sheet_matching import (
    alignement_lcs, dimensions_canoniques, reconnaitre_onglet, remapper_grille, sequence,
)

FIXTURES = Path(__file__).parent / "fixtures_fictives"

FICHIERS_CM = [
    "ETABA-CM_Liasse_Stats_Paiements_2025_2026.xlsx",
    "ETABB-CM_Liasse_Stats_Paiements_du_01012025_au_30062026.xlsx",
    "ETABD-CM_Liasse_Stats_Paiements_2025.xlsx",
    "ETABF-CM_Copie_de_Liasse_Stats_Paiements_2025-_Banque_Fictive.xlsx",
    "ETATS_TRANSFERT_ACA_BANK_2025_-_2026__1_.xlsx",
    "ETABE-CM_Liasse_Stats_Paiements_2025-V1.xlsx",
    "ETABC-CM_Liasse_Stats_Paiements_2025_JUNE_2026_BANQUE_FICTIVE.xlsx",
    "ETABG-CM_Statistiques_Transfert_dargent__transmission_de_fonds__JAN_2025_JUIN_2026.xlsx",
]


# --------------------------------------------------------------------- #
# Non-régression : le comportement sur les fichiers de référence initiaux
# doit rester rigoureusement inchangé.
# --------------------------------------------------------------------- #

def test_banque_a_et_operateur_b_inchanges():
    for fn in ("BanqueA.xlsx", "OperateurB.xlsx"):
        sheets = parse_workbook(FIXTURES / fn)
        assert set(sheets.keys()) == set(KNOWN_SHEETS)
        _, non_reconnus = analyser_fichier(FIXTURES / fn)
        assert non_reconnus == []


def test_valeurs_de_reference_toujours_exactes():
    from core.kpis import compute_kpis, retrait_gab_kpi
    from core.parsing import Institution

    insts = [
        Institution("BanqueA", "b", parse_workbook(FIXTURES / "BanqueA.xlsx")),
        Institution("OperateurB", "o", parse_workbook(FIXTURES / "OperateurB.xlsx")),
    ]
    attendu = {"porteurs_mm_total": 1232671, "porteurs_mm_actifs": 359593, "encours_me": 14621281997,
               "clients_cartes": 11386, "comptes_cartes": 29374, "cartes_debit": 21298}
    for k in compute_kpis(insts):
        assert k.total == attendu[k.key]
    gab = retrait_gab_kpi(insts)
    assert gab["total"] == {"nombre": 142872, "valeur": 14942539230}


# --------------------------------------------------------------------- #
# Reconnaissance par nom exact (chemin rapide)
# --------------------------------------------------------------------- #

def test_nom_exact_est_reconnu_sans_analyse_structurelle():
    r = reconnaitre_onglet("Cartes 2", [["x"]], set(KNOWN_SHEETS))
    assert r.theme == "Cartes 2"
    assert r.correspondance_exacte is True


def test_nom_avec_espace_parasite_est_tolere():
    """Un espace de fin (« PrêtsCredits ») ne doit pas empêcher la
    correspondance exacte — observé sur un fichier réel (ETABC)."""
    r = reconnaitre_onglet("PrêtsCredits ", [["x"]], set(KNOWN_SHEETS))
    assert r.theme == "PrêtsCredits"
    assert r.correspondance_exacte is True


# --------------------------------------------------------------------- #
# Reconnaissance par famille (structure), sur les 8 fichiers réels
# --------------------------------------------------------------------- #













# --------------------------------------------------------------------- #
# Exactitude de la fusion (sommation cellule à cellule)
# --------------------------------------------------------------------- #





# --------------------------------------------------------------------- #
# Rien n'est jamais silencieusement perdu
# --------------------------------------------------------------------- #





# --------------------------------------------------------------------- #
# Garde-fou : ratio de taille (le cas du faux positif corrigé)
# --------------------------------------------------------------------- #



# --------------------------------------------------------------------- #
# Alignement LCS : robustesse à une ligne insérée
# --------------------------------------------------------------------- #

def test_alignement_tolere_une_ligne_vide_inseree():
    """Cas réel corrigé : une ligne vide en tête de fichier décalait TOUTE
    la comparaison position par position, alors que le contenu était par
    ailleurs identique. L'alignement par plus longue sous-séquence commune
    doit rester insensible à ce genre de décalage."""
    reference_seq = [(0, "titre"), (1, "etablissement"), (2, "reseau"), (3, "nombre valeur"), (4, "total")]
    candidate_avec_ligne_en_plus = [(0, "titre"), (2, "etablissement"), (3, "reseau"),
                                     (4, "nombre valeur"), (5, "total")]
    paires, longueur = alignement_lcs(candidate_avec_ligne_en_plus, reference_seq)
    assert longueur == 5  # tout concorde malgré le décalage
    assert dict(paires) == {0: 0, 2: 1, 3: 2, 4: 3, 5: 4}


def test_remapper_grille_replace_les_valeurs_sur_les_bonnes_lignes():
    alignement = [(0, 0), (2, 1), (3, 2)]
    grille_candidate = [
        ["titre"],
        [None],              # ligne insérée, absente du gabarit officiel
        ["etablissement", 10],
        ["reseau", 20],
    ]
    resultat = remapper_grille(grille_candidate, alignement, n_lignes=3, n_colonnes=2)
    assert resultat[0] == ["titre", None]
    assert resultat[1] == ["etablissement", 10]
    assert resultat[2] == ["reseau", 20]


# --------------------------------------------------------------------- #
# Visibilité : signalement dans le contrôle qualité
# --------------------------------------------------------------------- #



def test_institution_sans_non_reconnus_ne_declenche_rien():
    from core.parsing import Institution
    from core.quality import check_onglets_non_reconnus

    sheets = parse_workbook(FIXTURES / "BanqueA.xlsx")
    inst = Institution(name="BanqueA", file_name="b.xlsx", sheets=sheets)
    assert check_onglets_non_reconnus([inst]) == []


# --------------------------------------------------------------------- #
# Piste faible : un onglet réellement plus pauvre que le gabarit officiel
# (activité partiellement renseignée) doit rester validable en un clic,
# même quand le taux de concordance est trop bas pour une proposition
# confiante — jamais un silence total.
# --------------------------------------------------------------------- #









# --------------------------------------------------------------------- #
# Rien n'est laissé de côté dans les documents exportés : même les onglets
# hors gabarit standard doivent apparaître, individuellement.
# --------------------------------------------------------------------- #









# --------------------------------------------------------------------- #
# Onglets composites : un même onglet regroupe plusieurs thèmes
#
# Cas réel : ETABA assemble le contenu de Cartes1 à Cartes 5 (190 lignes) en
# un seul onglet maison, plutôt que de suivre le découpage officiel en 5
# onglets distincts. Un rattachement à un seul thème aurait été faux pour
# tout le reste du contenu — d'où une segmentation par plage de lignes.
# --------------------------------------------------------------------- #













def test_annee_brute_collee_est_neutralisee():
    from core.sheet_matching import _norm
    assert _norm("Nombre de clients 2025") == _norm("Nombre de clients")
    assert _norm("Statistiques cartes 2026") == _norm("Statistiques cartes 2025") == "statistiques cartes"
    # un nombre qui n'est PAS une année ne doit pas être retiré à tort
    assert _norm("Total (A+B) 42") != _norm("Total (A+B)")


# --------------------------------------------------------------------- #
# Garde-fou de PÉRIODE
#
# Un établissement peut laisser dans son classeur d'anciens onglets d'un
# exercice précédent. Cas réel : un fichier 2025-2026 contenait aussi
# « chèques&VIR 1er SEMESTRE 22 », « RIA 1er SEMESTRE 22 » et
# « MoneyGram 1er SEMESTRE 22 », titrés « … 1er TRIMESTRE 2022 » et
# renseignés (45 milliards XAF sur les chèques). Ils ressemblent au gabarit
# à 90-94 % — les rattacher mélangerait des montants de 2022 dans un total
# 2025-2026, sans qu'aucune erreur ne soit signalée.
# --------------------------------------------------------------------- #







def test_fichiers_de_reference_ne_declenchent_aucun_garde_fou_de_periode():
    """BanqueA et OperateurB ne portent que sur la période courante : aucun de
    leurs onglets ne doit être écarté pour motif de période."""
    from core.parsing import analyser_fichier

    for fichier in ("BanqueA.xlsx", "OperateurB.xlsx"):
        _, non_reconnus = analyser_fichier(FIXTURES / fichier)
        assert not any(o.periode_revolue for o in non_reconnus)


# --------------------------------------------------------------------- #
# Conflit de période entre deux onglets composites
#
# Cas réel découvert lors d'un audit demandé par l'utilisateur : ETABA
# assemble son activité Cartes sur DEUX onglets composites distincts,
# « Cartes_2025 » (période du 01/01/2025 au 31/12/2025) et « Cartes_2026 »
# (période du 01/01/2026 au 30/06/2026) — la MÊME clientèle photographiée
# à deux dates, pas deux catégories à additionner. Les fusionner comme des
# réseaux parallèles (GIMAC + VISA) doublait la quasi-totalité des
# effectifs (deux fois le nombre réel de clients), silencieusement.
# --------------------------------------------------------------------- #

def test_detecter_periode_declaree_lit_la_declaration_explicite():
    from core.sheet_matching import detecter_periode_declaree
    import datetime

    grid = [["STATISTIQUES CARTES"], ["Période : du 01/01/2025 au 31/12/2025"]]
    assert detecter_periode_declaree(grid) == (datetime.date(2025, 1, 1), datetime.date(2025, 12, 31))


def test_detecter_periode_declaree_tolere_un_jour_hors_plage():
    """Cas réel : « 31/06/2026 » — juin n'a que 30 jours. Une coquille du
    fichier source ne doit jamais faire échouer toute la détection."""
    from core.sheet_matching import detecter_periode_declaree
    import datetime

    grid = [["Période : du 01/01/2026 au 31/06/2026"]]
    debut, fin = detecter_periode_declaree(grid)
    assert fin == datetime.date(2026, 6, 30)


def test_aucune_periode_declaree_renvoie_none():
    from core.sheet_matching import detecter_periode_declaree
    assert detecter_periode_declaree([["Rien à voir ici"]]) is None










# --------------------------------------------------------------------- #
# Rapprochement d'onglets non reconnus entre établissements différents
#
# Demandé explicitement par l'utilisateur : « en attendant de faire un
# rapprochement avec d'autres si y'en a qui sont aussi différents ».
# Cas réel trouvé sur un export utilisateur à grande échelle : MTN et
# FIRSTTRUST déposent chacun un onglet « Prêts/Crédits » orthographié
# différemment du gabarit officiel (« Prets-Credits » / « PretsCredits »
# au lieu de « PrêtsCredits ») — jamais reconnu automatiquement, mais
# structurellement le même motif chez deux établissements distincts.
# --------------------------------------------------------------------- #

def test_rapprochement_trouve_le_cas_reel_mtn_firsttrust():
    from core.parsing import Institution, OngletNonReconnu
    from core.sheet_matching import rapprocher_onglets_non_reconnus

    grid_mtn = [
        ["Prêts Credits octroyées aux particuliers en"], [None],
        ["Type de prêt (nom du service)"],
    ]
    grid_firsttrust_2025 = [
        ["Prêts Credits octroyées aux particuiers en"], [None],
        ["Type de prêt (nom du service)"],
        ["Financement fonds de roulement"], ["Crédit à la consommation"],
        ["Crédit équipement"], ["Crédit scolaire"],
    ]
    mtn = Institution("MTN", "mtn.xlsx", {}, non_reconnus=[
        OngletNonReconnu("Prets-Credits 2025", grid_mtn)])
    firsttrust = Institution("FIRSTTRUST", "ft.xlsx", {}, non_reconnus=[
        OngletNonReconnu("PretsCredits 2025", grid_firsttrust_2025)])

    groupes = rapprocher_onglets_non_reconnus([mtn, firsttrust], seuil=0.3)
    assert len(groupes) == 1
    membres, taux = groupes[0]
    assert taux >= 0.3
    assert ("MTN", "Prets-Credits 2025") in membres
    assert ("FIRSTTRUST", "PretsCredits 2025") in membres


def test_rapprochement_ignore_les_onglets_dun_meme_etablissement():
    """Les propres onglets 2025/2026 d'un établissement se ressemblent
    presque toujours — ce n'est pas une découverte, seul le rapprochement
    ENTRE établissements différents en est une."""
    from core.parsing import Institution, OngletNonReconnu
    from core.sheet_matching import rapprocher_onglets_non_reconnus

    grid = [["Prêts Credits octroyées aux particuliers en"], [None],
           ["Type de prêt (nom du service)"], ["Crédit équipement"]]
    seul_etab = Institution("FIRSTTRUST", "ft.xlsx", {}, non_reconnus=[
        OngletNonReconnu("PretsCredits 2025", grid),
        OngletNonReconnu("PretsCredits 2026", grid),
    ])
    groupes = rapprocher_onglets_non_reconnus([seul_etab], seuil=0.3)
    assert groupes == []


def test_rapprochement_najamais_de_faux_positif_entre_thematiques_differentes():
    """Un onglet sur l'assurance et un onglet sur le carburant ne doivent
    jamais être rapprochés, même avec un seuil bas."""
    from core.parsing import Institution, OngletNonReconnu
    from core.sheet_matching import rapprocher_onglets_non_reconnus

    grid_assurance = [["Assurance emprunteur"], ["Nombre de contrats souscrits"],
                      ["Primes collectées"], ["Sinistres réglés"]]
    grid_carburant = [["Statistiques carburant"], ["Litres vendus"],
                      ["Chiffre d'affaires"], ["Nombre de stations"]]
    inst1 = Institution("EtabA", "a.xlsx", {}, non_reconnus=[
        OngletNonReconnu("Assurance", grid_assurance)])
    inst2 = Institution("EtabB", "b.xlsx", {}, non_reconnus=[
        OngletNonReconnu("Carburant", grid_carburant)])
    groupes = rapprocher_onglets_non_reconnus([inst1, inst2], seuil=0.3)
    assert groupes == []


