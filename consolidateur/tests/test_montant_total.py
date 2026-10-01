"""
tests/test_montant_total.py

Le montant total « toutes activités confondues », par établissement (donc
agrégeable par pays ou pour l'ensemble CEMAC).

Une exploration systématique des lignes « Total » du gabarit a révélé deux
pièges concrets, chacun verrouillé ici par un test dédié :
- des totaux de tête qui recouvrent déjà leurs propres sous-totaux (les
  additionner compterait deux fois les mêmes transactions) ;
- des totaux de tête laissés vides par l'établissement alors que leurs
  sous-composantes sont, elles, correctement renseignées.

Un contrôle de vraisemblance supplémentaire, découvert sur un cas réel
(un saut de facteur 300 d'un mois à l'autre dans le fichier OperateurB de
référence, signe quasi certain d'une erreur de saisie), exclut du total
toute composante dont la valeur bondit de façon invraisemblable — jamais
silencieusement, toujours signalée dans le détail.
"""

from pathlib import Path

import pytest

from core.montant_total import detail_montant_total, montant_total_argent
from core.parsing import Institution, parse_workbook

FIXTURES = Path(__file__).parent / "fixtures_fictives"


@pytest.fixture(scope="module")
def banque_a_operateur_b():
    return [
        Institution("BanqueA", "b.xlsx", parse_workbook(FIXTURES / "BanqueA.xlsx")),
        Institution("OperateurB", "o.xlsx", parse_workbook(FIXTURES / "OperateurB.xlsx")),
    ]


def test_le_total_est_un_nombre_positif(banque_a_operateur_b):
    total = montant_total_argent(banque_a_operateur_b)
    assert total > 0


def test_institution_vide_donne_un_total_nul():
    assert montant_total_argent([]) == 0


def test_pas_de_double_comptage_sur_les_totaux_hierarchiques(banque_a_operateur_b):
    """Cas réel : MobileMoney3 a un total de tête (toutes zones) déjà égal
    à la somme de ses deux sous-zones (CEMAC + hors CEMAC). Le détail ne
    doit retenir qu'UNE seule fois cette valeur, pas trois."""
    detail = detail_montant_total(banque_a_operateur_b)
    libelles = [d[0] for d in detail]
    occurrences_mm3 = [l for l in libelles if "interopérables" in l]
    assert len(occurrences_mm3) == 1


def test_repli_sur_les_composantes_quand_le_total_de_tete_est_vide(banque_a_operateur_b):
    """Cas réel : sur Cartes 2 et Cartes 5, BanqueA a renseigné les
    sous-totaux (banque / CEMAC / international) mais a laissé le total de
    tête à vide. Le calcul doit alors reprendre la somme des composantes,
    plutôt que compter 0 alors que de l'argent réel existe."""
    detail = detail_montant_total(banque_a_operateur_b)
    par_libelle = {l.replace(" (via composantes)", ""): (l, v, a) for l, v, a in detail}

    libelle, valeur, anomalie = par_libelle["Cartes — retraits (bloc 1)"]
    assert "(via composantes)" in libelle
    assert valeur == pytest.approx(14942539230 + 3300909329)  # B + C (D est vide)
    assert not anomalie


def test_anomalie_de_saut_mensuel_est_exclue_du_total(banque_a_operateur_b):
    """Cas réel trouvé dans le fichier OperateurB de référence : la ligne
    « Transfert d'argent » de MobileMoney2 affiche 5 097 milliards XAF pour
    un mois, contre 9 à 17 milliards les mois voisins — un facteur ~300,
    signe quasi certain d'une erreur de saisie plutôt que d'une activité
    réelle. Cette composante doit être EXCLUE du total, mais rester visible
    dans le détail avec un signalement explicite."""
    detail = detail_montant_total(banque_a_operateur_b)
    ligne_suspecte = next(d for d in detail if "transferts" in d[0])
    assert ligne_suspecte[1] > 1_000_000_000_000  # toujours visible, valeur brute
    assert ligne_suspecte[2] is True  # mais signalée comme anomalie

    total = montant_total_argent(banque_a_operateur_b)
    assert total < 200_000_000_000  # l'anomalie de 5 000 Md n'y figure pas


def test_total_narrondit_rien_hors_anomalie(banque_a_operateur_b):
    """Somme exacte des composantes non signalées + encours."""
    detail = detail_montant_total(banque_a_operateur_b)
    attendu = sum(v for _, v, anomalie in detail if not anomalie)
    assert montant_total_argent(banque_a_operateur_b) == pytest.approx(attendu)


def test_seule_banque_a_narrondit_rien():
    """Sur un seul établissement (BanqueA, sans données Mobile Money), le
    total doit rester exact et ne jamais planter."""
    banque_a = [Institution("BanqueA", "b.xlsx", parse_workbook(FIXTURES / "BanqueA.xlsx"))]
    total = montant_total_argent(banque_a)
    detail = detail_montant_total(banque_a)
    assert total >= 0
    assert any(v > 0 for _, v, _ in detail)  # les retraits GAB de BanqueA y figurent


def test_detail_inclut_toujours_lencours(banque_a_operateur_b):
    detail = detail_montant_total(banque_a_operateur_b)
    libelles = [d[0] for d in detail]
    assert "Encours de monnaie électronique" in libelles
    encours = next(v for l, v, _ in detail if l == "Encours de monnaie électronique")
    assert encours == 14621281997  # valeur de référence déjà validée


# --------------------------------------------------------------------- #
# Lecture robuste sur une feuille reconstituée par segmentation
# --------------------------------------------------------------------- #



def test_cartes4_exclue_pour_ne_pas_compter_deux_fois_les_paiements():
    """« Cartes 4 » (PAIEMENTS PAR CARTES) est une ventilation sectorielle
    d'un montant déjà compté en acquisition, pas une catégorie
    supplémentaire : chez le seul établissement des fichiers réels qui la
    renseigne, elle vaut presque exactement les paiements en
    acquisition — 0,7 % d'écart, bien trop proche pour être une
    coïncidence."""
    detail_libelles = [d[0] for d in detail_montant_total([])]
    assert not any("acquisition" in l and "Cartes 4" in l for l in detail_libelles)
    from core.montant_total import _COMPOSANTES
    assert not any(c.sheet == "Cartes 4" for c in _COMPOSANTES)




def test_le_total_est_additif_entre_groupes():
    """Propriété essentielle : le total d'un groupe doit toujours valoir la
    somme des totaux de ses membres — sans quoi le total CEMAC affiché ne
    correspondrait pas à la somme des totaux par pays juste au-dessus.

    Régression réelle : la détection d'anomalie était menée sur le groupe
    entier, si bien qu'une donnée douteuse chez un établissement faisait
    disparaître aussi la contribution de ses voisins. L'écart constaté
    valait exactement le montant complet d'un établissement."""
    banque_a = Institution("BanqueA", "b.xlsx", parse_workbook(FIXTURES / "BanqueA.xlsx"), pays="CF")
    operateur_b = Institution("OperateurB", "o.xlsx", parse_workbook(FIXTURES / "OperateurB.xlsx"), pays="CF")
    banque_a_cm = Institution("BanqueA-CM", "b2.xlsx", parse_workbook(FIXTURES / "BanqueA.xlsx"), pays="CM")

    total_groupe = montant_total_argent([banque_a, operateur_b, banque_a_cm])
    somme_individuels = sum(montant_total_argent([i]) for i in [banque_a, operateur_b, banque_a_cm])
    assert total_groupe == pytest.approx(somme_individuels)

    # et par pays, comme affiché dans les exports
    total_cf = montant_total_argent([banque_a, operateur_b])
    total_cm = montant_total_argent([banque_a_cm])
    assert total_groupe == pytest.approx(total_cf + total_cm)


# --------------------------------------------------------------------- #
# Contrôle de cohérence des totaux hiérarchiques (Transfert d'argent,
# MobileMoney3, Cartes 2, Cartes 5) — vérifié sur des fichiers réels
# après un signalement de l'utilisateur qui soupçonnait des erreurs de
# calcul, notamment sur « Transfert d'argent ».
# --------------------------------------------------------------------- #











# --------------------------------------------------------------------- #
# Catégories manquantes trouvées en réauditant après le signalement de
# l'utilisateur — chèques&VIR avait 5 rubriques, seules 3 étaient comptées ;
# PrêtsCredits (tableau à nombre de lignes variable) n'était compté nulle
# part du tout.
# --------------------------------------------------------------------- #





def test_cinq_rubriques_de_cheques_vir_toutes_couvertes():
    from core.montant_total import _COMPOSANTES
    lignes_cheques_vir = {c.description for c in _COMPOSANTES if c.sheet == "chèques&VIR"}
    assert lignes_cheques_vir == {
        "Chèques — total", "Virements — total", "Prélèvements — total",
        "Effets de commerce — total", "Retraits manuels — total",
    }










# --------------------------------------------------------------------- #
# Répartition par pays et par rubrique — socle des camemberts interactifs
# --------------------------------------------------------------------- #

    # Prélèvements est à 0 chez ETABB (vérifié précédemment) : absente à
    # raison, une rubrique vide ne doit pas polluer le camembert.








def test_repartition_vide_pour_theme_sans_composante_ni_cas_particulier():
    from core.montant_total import repartition_par_pays_et_rubrique
    banque_a = Institution("BanqueA", "b.xlsx", parse_workbook(FIXTURES / "BanqueA.xlsx"), pays="CF")
    assert repartition_par_pays_et_rubrique([banque_a], "Cartes 3") == []


def test_repartition_vide_sans_pays_renseigne():
    from core.montant_total import repartition_par_pays_et_rubrique
    banque_a = Institution("BanqueA", "b.xlsx", parse_workbook(FIXTURES / "BanqueA.xlsx"), pays=None)
    assert repartition_par_pays_et_rubrique([banque_a], "chèques&VIR") == []




def test_second_niveau_de_repli_najamais_de_double_comptage():
    """La ligne 'dont vente à distance' est un SOUS-détail de 'Paiements /
    achats', jamais une catégorie parallèle — ne doit jamais être ajoutée
    en plus."""
    from core.montant_total import _COMPOSANTES
    comp = next(c for c in _COMPOSANTES if c.description == "Cartes — transactions en émission")
    # lignes 4,6,7,8,9 uniquement : jamais la ligne 5 ("dont vente à distance")
    assert comp.lignes_repli_profond == [4, 6, 7, 8, 9]


# --------------------------------------------------------------------- #
# Second niveau de repli (lignes détaillées) — cas réel majeur trouvé
#
# Chez un établissement réel (ETABB), même les sous-totaux de zone (B/C/D)
# de Cartes 2 étaient remplis d'espaces au lieu de nombres, alors que les
# lignes détaillées elles-mêmes (Paiements/achats, retraits GAB…) portaient
# de vraies données — 7,25 Md XAF qui affichaient 0 avant ce correctif.
# --------------------------------------------------------------------- #



def test_repli_profond_najamais_declenche_si_le_repli_normal_suffit():
    """Sur un établissement dont le total de tête OU les sous-totaux de
    zone sont correctement renseignés, le repli profond ne doit jamais
    être sollicité — non-régression sur ce qui fonctionnait déjà."""
    from core.montant_total import calculer_composantes
    banque_a = Institution("BanqueA", "b.xlsx", parse_workbook(FIXTURES / "BanqueA.xlsx"))
    c = next(c for c in calculer_composantes([banque_a]) if "retraits (bloc 1)" in c.description)
    assert c.valeur == pytest.approx(14942539230 + 3300909329)  # valeur déjà validée, inchangée


def test_repli_profond_najoute_jamais_la_ligne_dont_sous_detail():
    """'  -dont vente à distance' est un sous-détail de 'Paiements/achats',
    pas une catégorie parallèle — jamais additionné en plus, sous peine de
    compter deux fois la même activité."""
    from core.montant_total import _COMPOSANTES
    comp = next(c for c in _COMPOSANTES if c.sheet == "Cartes 2")
    # lignes attendues : Paiements/achats(4), retraits GAB(6), Transferts(7),
    # Avoirs/Crédits(8), Remboursements(9) — jamais la ligne 5 ("dont…")
    assert comp.lignes_repli_profond == [4, 6, 7, 8, 9]


# --------------------------------------------------------------------- #
# Répartition par réseau de carte (VISA, GIMAC…)
# --------------------------------------------------------------------- #



def test_repartition_par_reseau_vide_sans_variante():
    """Un établissement qui ne segmente pas ses onglets par réseau
    (un seul onglet 'Cartes 2', pas de suffixe GIMAC/VISA) ne doit renvoyer
    aucune répartition réseau — rien à éclater."""
    from core.montant_total import repartition_par_reseau
    fichiers = [("BanqueA.xlsx", (FIXTURES / "BanqueA.xlsx").read_bytes(), "CF")]
    assert repartition_par_reseau(fichiers, "Cartes 2") == []


