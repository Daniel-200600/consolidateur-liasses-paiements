"""
tests/test_app_e2e.py

Test de bout en bout de l'interface (Phase 4) : simule un vrai dépôt des deux
fichiers de référence dans l'app Streamlit et vérifie que le tableau de bord
affiche les valeurs attendues. Utilise streamlit.testing.v1.AppTest, qui
exécute réellement app.py (et non une copie de sa logique).
"""

from pathlib import Path

import time
import io

import pytest
from streamlit.testing.v1 import AppTest

import core.calibration as calibration_module
import core.history as history_module

FIXTURES = Path(__file__).parent / "fixtures_fictives"


@pytest.fixture(autouse=True)
def isolate_history(tmp_path, monkeypatch):
    """Phase 9 : app.py enregistre automatiquement un instantané dans
    data/historique.csv à chaque consolidation. On redirige ce fichier vers
    un dossier temporaire pendant les tests, pour ne jamais polluer
    l'historique réel du projet ni faire dépendre un test de l'ordre
    d'exécution des autres."""
    monkeypatch.setattr(history_module, "default_history_path", lambda: tmp_path / "historique_test.csv")


@pytest.fixture(autouse=True)
def isolate_calibration(tmp_path, monkeypatch):
    """Étape 1 : les rattachements d'onglets validés sont mémorisés hors du
    dossier projet. Même isolation que l'historique, pour les mêmes
    raisons."""
    monkeypatch.setattr(calibration_module, "chemin_par_defaut", lambda: tmp_path / "calibration_test.json")


def test_upload_two_files_shows_correct_dashboard():
    at = AppTest.from_file(str(Path(__file__).parent.parent / "app.py"), default_timeout=30)
    at.run()

    fu = at.file_uploader[0]
    fu.upload("BanqueA.xlsx", (FIXTURES / "BanqueA.xlsx").read_bytes(),
               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    fu.upload("OperateurB.xlsx", (FIXTURES / "OperateurB.xlsx").read_bytes(),
               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    fu.run()

    assert not at.exception, f"L'app a levé une exception : {at.exception}"

    # Le tableau des KPI est affiché via st.dataframe : on récupère son contenu.
    dataframes = at.get("dataframe")
    assert len(dataframes) >= 1
    kpi_table = dataframes[0].value  # pandas DataFrame

    assert "359 593" in kpi_table.loc["Porteurs Mobile Money actifs"].values
    assert "11 386" in kpi_table.loc["Clients porteurs de cartes"].values
    assert "14 942 539 230" in kpi_table.loc["Retraits GAB — valeur (XAF)"].values

    # Phase 5 : le panneau qualité doit signaler l'erreur de formule connue
    # (OperateurB / MobileMoney2) et les onglets non renseignés, sans jamais
    # faire planter l'app.
    subheaders = [el.value for el in at.subheader]
    assert any("vigilance" in s.lower() for s in subheaders)

    infos = [el.value for el in at.info]
    assert any("OperateurB" in i and "Cartes1" in i for i in infos)
    assert any("BanqueA" in i and "Mobile Money1" in i for i in infos)

    expanders = [el.label for el in at.expander]
    assert any("MobileMoney2" in e for e in expanders)

    # Le tableau de bord de graphiques (« Part de marché », « évolution
    # mensuelle ») a été retiré à la demande de l'utilisateur : il ne doit
    # simplement plus exister, sans faire planter le reste de l'app.
    assert not at.exception
    assert not [s for s in [el.value for el in at.subheader] if s == "Graphiques"]

    # Découverte automatique : la section « Tous les indicateurs » doit
    # exposer toute la structure du gabarit (280 lignes sur les fichiers de
    # référence, dont 45 renseignées), là où seuls 8 indicateurs étaient
    # visibles auparavant.
    subheaders = [el.value for el in at.subheader]
    assert any("Tous les indicateurs" in s for s in subheaders)
    captions = " ".join(c.value for c in at.caption)
    assert "280 lignes de tableau détectées" in captions
    assert "45 renseignée" in captions

    # Les exports sont produits À LA DEMANDE (ils coûtent plusieurs secondes
    # et rendaient toute l'application lente s'ils étaient régénérés à chaque
    # interaction). Aucun bouton de téléchargement tant qu'ils n'ont pas été
    # préparés — c'est le comportement voulu.
    assert len(at.download_button) == 0
    bouton_preparer = [b for b in at.button if "Préparer les exports" in b.label]
    assert bouton_preparer, "Le bouton de préparation des exports est introuvable"

    bouton_preparer[0].click().run()
    download_buttons = at.download_button
    assert len(download_buttons) == 2
    labels = [b.label for b in download_buttons]
    assert any("résumé" in l.lower() for l in labels)
    assert any("complet" in l.lower() for l in labels)

    print(kpi_table)


def test_duplicate_institution_names_are_auto_disambiguated():
    # Découvert en revue de robustesse (Phase 8) : les indicateurs sont
    # agrégés par nom d'établissement. Deux fichiers PEUVENT porter le même
    # nom de base (même stem, contenus différents — cas réel plausible :
    # deux dossiers différents contenant chacun un fichier « Liasse.xlsx ») :
    # les valeurs ne doivent jamais s'écraser silencieusement.
    at = AppTest.from_file(str(Path(__file__).parent.parent / "app.py"), default_timeout=30)
    at.run()

    fu = at.file_uploader[0]
    # Même nom de fichier cible, contenus réellement différents (tailles
    # différentes -> file_id différents, mais même stem "Meme").
    fu.upload("Meme.xlsx", (FIXTURES / "BanqueA.xlsx").read_bytes())
    fu.upload("Meme.xlsx", (FIXTURES / "OperateurB.xlsx").read_bytes())
    fu.run()

    assert not at.exception

    warnings = [w.value for w in at.warning]
    assert any("même nom" in w.lower() for w in warnings)

    dataframes = at.get("dataframe")
    kpi_table = dataframes[0].value
    # Les deux valeurs doivent toujours apparaître (colonnes désambiguïsées),
    # et le total marché doit rester juste malgré la collision de nom.
    assert "359 593" in kpi_table.loc["Porteurs Mobile Money actifs"].values
    assert "11 386" in kpi_table.loc["Clients porteurs de cartes"].values


def test_invalid_file_shows_error_without_crashing():
    at = AppTest.from_file(str(Path(__file__).parent.parent / "app.py"), default_timeout=30)
    at.run()

    fu = at.file_uploader[0]
    fu.upload("pas_un_classeur.xlsx", b"ceci n'est pas un fichier Excel valide")
    fu.run()

    assert not at.exception
    errors = [e.value for e in at.error]
    assert any("pas_un_classeur.xlsx" in e for e in errors)
    # L'app doit rester utilisable : le message "aucun fichier valide" doit
    # s'afficher plutôt qu'un plantage.
    infos = [i.value for i in at.warning] + [i.value for i in at.info]
    assert any("valide" in i.lower() for i in infos)


def test_duplicate_upload_of_same_file_is_ignored():
    """Cas réel corrigé : le même fichier déposé deux fois (l'utilisateur
    le sélectionne par erreur une seconde fois) doublait silencieusement
    tous les totaux — plus qu'une seule colonne dans le tableau, jamais
    deux, pour un fichier strictement identique (même nom, même taille)."""
    at = AppTest.from_file(str(Path(__file__).parent.parent / "app.py"), default_timeout=30)
    at.run()

    fu = at.file_uploader[0]
    content = (FIXTURES / "BanqueA.xlsx").read_bytes()
    fu.upload("BanqueA.xlsx", content)
    fu.upload("BanqueA.xlsx", content)  # même fichier déposé une seconde fois
    fu.run()

    assert not at.exception
    df = at.get("dataframe")[0].value
    assert list(df.columns) == ["BanqueA", "Total marché"]  # une seule colonne, pas "BanqueA (2)"
    assert df.loc["Clients porteurs de cartes", "Total marché"] == "11 386"  # jamais doublé


def test_aucun_bouton_de_retrait_dedie_larchivage_natif_suffit():
    """Sur demande explicite : plus aucune information ni contrôle
    individuel par fichier dans la barre latérale. Retirer un fichier se
    fait via la croix native du composant d'upload, jamais un bouton
    dédié construit à la main."""
    at = AppTest.from_file(str(Path(__file__).parent.parent / "app.py"), default_timeout=30)
    at.run()

    fu = at.file_uploader[0]
    fu.upload("BanqueA.xlsx", (FIXTURES / "BanqueA.xlsx").read_bytes())
    fu.upload("OperateurB.xlsx", (FIXTURES / "OperateurB.xlsx").read_bytes())
    fu.run()

    assert not at.exception
    assert not [b for b in at.button if b.key and b.key.startswith("remove_")]
    # aucun sélecteur de pays ni champ de nom par fichier
    assert not [s for s in at.selectbox if s.key and s.key.startswith("pays_")]
    assert not [t for t in at.text_input if t.key and t.key.startswith("name_")]


def test_evolution_par_pays_saffiche_avec_un_indicateur_mensuel_reel():
    """L'Historique multi-période a été retiré sur demande de l'utilisateur,
    remplacé par un graphique d'évolution par pays qui réutilise le
    sélecteur d'indicateur déjà existant (pas de second menu déroulant
    redondant)."""
    at = AppTest.from_file(str(Path(__file__).parent.parent / "app.py"), default_timeout=30)
    at.run()

    fu = at.file_uploader[0]
    fu.upload("BanqueA_CA.xlsx", (FIXTURES / "BanqueA.xlsx").read_bytes())
    fu.upload("OperateurB_RCA.xlsx", (FIXTURES / "OperateurB.xlsx").read_bytes())
    fu.run()
    assert not at.exception

    subheaders = [s.value for s in at.subheader]
    assert any("Évolution par pays" in s for s in subheaders)
    assert not any("Historique" in s for s in subheaders)  # bien retiré, pas juste renommé

    # Sans indicateur mensuel sélectionné (onglet par défaut non mensuel),
    # un message d'attente s'affiche plutôt qu'un graphique vide.
    at.selectbox(key="explored_sheet").set_value("Mobile Money1").run()
    trace = at.selectbox(key="traced_indicator")
    assert trace.options  # au moins un indicateur mensuel renseigné sur ce fichier de référence
    trace.set_value(trace.options[0]).run()
    assert not at.exception

    # Deux graphiques désormais : un par établissement (déjà existant), un
    # par pays (nouveau).
    assert len(at.get("plotly_chart")) == 2


if __name__ == "__main__":
    test_upload_two_files_shows_correct_dashboard()
    print("\n✅ Test end-to-end OK : upload réel simulé -> tableau de bord correct")






def test_les_exports_ne_sont_pas_regeneres_a_chaque_interaction():
    """Régression de performance : les deux classeurs coûtent plusieurs
    secondes à produire. Les générer à chaque exécution du script — donc à
    chaque clic, sélection ou validation — rendait toute l'application
    lente (mesuré : ~3 s par interaction avec deux établissements
    seulement, davantage au-delà). Ils ne doivent être construits que sur
    demande explicite."""
    at = AppTest.from_file(str(Path(__file__).parent.parent / "app.py"), default_timeout=120)
    at.run()
    fu = at.file_uploader[0]
    fu.upload("BanqueA.xlsx", (FIXTURES / "BanqueA.xlsx").read_bytes())
    fu.upload("OperateurB.xlsx", (FIXTURES / "OperateurB.xlsx").read_bytes())
    fu.run()

    # Aucun export produit tant que l'utilisateur ne l'a pas demandé.
    assert len(at.download_button) == 0

    debut = time.time()
    selecteur = at.selectbox(key="explored_sheet")
    selecteur.set_value(selecteur.options[2]).run()
    duree_interaction = time.time() - debut
    assert not at.exception
    assert duree_interaction < 1.5, (
        f"Une interaction courante prend {duree_interaction:.1f}s : les exports sont "
        f"probablement régénérés à chaque exécution du script"
    )


def test_les_exports_prepares_sont_conserves_entre_interactions():
    """Une fois préparés, les classeurs ne doivent pas être reconstruits à
    chaque interaction suivante — sans quoi le gain serait perdu."""
    at = AppTest.from_file(str(Path(__file__).parent.parent / "app.py"), default_timeout=120)
    at.run()
    fu = at.file_uploader[0]
    fu.upload("BanqueA.xlsx", (FIXTURES / "BanqueA.xlsx").read_bytes())
    fu.upload("OperateurB.xlsx", (FIXTURES / "OperateurB.xlsx").read_bytes())
    fu.run()

    [b for b in at.button if "Préparer" in b.label][0].click().run()
    assert len(at.download_button) == 2

    debut = time.time()
    selecteur = at.selectbox(key="explored_sheet")
    selecteur.set_value(selecteur.options[1]).run()
    duree = time.time() - debut
    assert len(at.download_button) == 2  # toujours disponibles
    assert duree < 1.5, f"Interaction lente après préparation : {duree:.1f}s"


# --------------------------------------------------------------------- #
# Tableau « Indicateurs clés » étendu aux 11 thèmes
#
# Les 8 indicateurs d'origine ne couvraient que Mobile Money1, Cartes1 et
# Cartes 5 : un établissement dont l'activité réelle porte sur les
# chèques, les transferts d'argent ou les paiements cartes en acquisition
# (cas réel : ETABA, dont l'activité 2025-2026 est presque entièrement
# portée par les cartes) y apparaissait à tort comme une colonne vide.
# --------------------------------------------------------------------- #

def test_tableau_indicateurs_cles_couvre_les_11_themes():
    """Un tableau resserré (10 lignes, sur demande explicite : moins
    d'indicateurs mais plus utiles) doit néanmoins représenter les 11
    thèmes — regroupés par grande famille d'activité plutôt qu'une ligne
    détaillée par sous-catégorie."""
    at = AppTest.from_file(str(Path(__file__).parent.parent / "app.py"), default_timeout=60)
    at.run()
    fu = at.file_uploader[0]
    fu.upload("BanqueA.xlsx", (FIXTURES / "BanqueA.xlsx").read_bytes())
    fu.run()
    assert not at.exception

    df = at.get("dataframe")[0].value
    assert len(df) == 10
    for libelle in ["Chèques, virements & effets de commerce — total", "Transfert d'argent — total",
                    "Mobile Money — flux total", "Cartes — transactions totales",
                    "Prêts / crédits octroyés — total"]:
        assert libelle in df.index




def test_valeurs_de_reference_inchangees_dans_le_tableau_etendu():
    """La refonte ne doit rien casser des indicateurs déjà validés de longue
    date."""
    at = AppTest.from_file(str(Path(__file__).parent.parent / "app.py"), default_timeout=60)
    at.run()
    fu = at.file_uploader[0]
    fu.upload("BanqueA.xlsx", (FIXTURES / "BanqueA.xlsx").read_bytes())
    fu.upload("OperateurB.xlsx", (FIXTURES / "OperateurB.xlsx").read_bytes())
    fu.run()
    assert not at.exception

    df = at.get("dataframe")[0].value
    assert df.loc["Porteurs Mobile Money actifs", "Total marché"] == "359 593"
    assert df.loc["Clients porteurs de cartes", "Total marché"] == "11 386"
    assert df.loc["Retraits GAB — valeur (XAF)", "Total marché"] == "14 942 539 230"


# --------------------------------------------------------------------- #
# Dépôt d'un dossier entier (accept_multiple_files="directory")
# --------------------------------------------------------------------- #

def test_bascule_vers_le_mode_dossier_ne_plante_pas():
    at = AppTest.from_file(str(Path(__file__).parent.parent / "app.py"), default_timeout=60)
    at.run()
    radio = at.radio(key="mode_depot")
    assert radio.options == ["Fichiers", "Dossier entier"]
    radio.set_value("Dossier entier").run()
    assert not at.exception


def test_fichiers_deposes_en_mode_dossier_sont_traites_normalement():
    """Le mode « dossier entier » doit produire exactement le même
    traitement que le dépôt fichier par fichier — seul le sélecteur du
    navigateur change, jamais la logique de consolidation."""
    at = AppTest.from_file(str(Path(__file__).parent.parent / "app.py"), default_timeout=60)
    at.run()
    at.radio(key="mode_depot").set_value("Dossier entier").run()

    fu = at.file_uploader[0]
    fu.upload("BanqueA.xlsx", (FIXTURES / "BanqueA.xlsx").read_bytes())
    fu.upload("OperateurB.xlsx", (FIXTURES / "OperateurB.xlsx").read_bytes())
    fu.run()
    assert not at.exception

    df = at.get("dataframe")[0].value
    assert df.loc["Porteurs Mobile Money actifs", "Total marché"] == "359 593"


# --------------------------------------------------------------------- #
# Tous les fichiers, sans exception — même sans aucun onglet reconnu
#
# Un fichier dont aucun onglet ne correspond aux 11 thèmes du gabarit était
# auparavant rejeté (message d'erreur, exclu de toute consolidation) — et,
# pire, son VRAI contenu (non_reconnus) était jeté et remplacé par une
# liste vide, le rendant invisible même du tableau hors gabarit. Sur
# demande explicite de l'utilisateur : plus aucun rejet.
# --------------------------------------------------------------------- #

def test_fichier_sans_onglet_reconnu_nest_plus_jamais_rejete(tmp_path):
    import openpyxl

    chemin = tmp_path / "etranger.xlsx"
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("Assurance emprunteur")
    ws["A1"] = "STATISTIQUES ASSURANCE EMPRUNTEUR 2025"
    ws["A2"], ws["B2"] = "Nombre de contrats souscrits", 4200
    wb.save(chemin)

    at = AppTest.from_file(str(Path(__file__).parent.parent / "app.py"), default_timeout=60)
    at.run()
    fu = at.file_uploader[0]
    fu.upload(chemin.name, chemin.read_bytes())
    fu.run()

    assert not at.exception
    assert not at.error  # jamais de message de rejet
    df = at.get("dataframe")[0].value
    assert list(df.columns) == ["etranger", "Total marché"]  # bien traité comme un établissement normal


def test_fichier_sans_onglet_reconnu_apparait_dans_lexport(tmp_path):
    """Son contenu doit rester accessible dans le fichier complet — jamais
    silencieusement perdu."""
    import openpyxl
    from core.export import build_full_workbook
    from core.parsing import Institution, analyser_fichier

    chemin = tmp_path / "etranger.xlsx"
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("Assurance emprunteur")
    ws["A1"] = "STATISTIQUES ASSURANCE EMPRUNTEUR 2025"
    ws["A2"], ws["B2"] = "Nombre de contrats souscrits", 4200
    wb.save(chemin)

    sheets, non_reconnus = analyser_fichier(chemin)
    assert sheets == {}
    assert len(non_reconnus) == 1  # jamais jeté

    inst = Institution("etranger", "etranger.xlsx", sheets, non_reconnus)
    wb_export = build_full_workbook([inst])
    assert any("Assurance emprunteur" in n for n in wb_export.sheetnames)


def test_onglet_par_defaut_a_une_serie_mensuelle_exploitable():
    """Cas réel signalé : « Évolution par pays » ne montrait rien, car
    l'onglet sélectionné par défaut (chèques&VIR, premier du gabarit) n'a
    pas de disposition mensuelle — le menu « Indicateur à tracer » restait
    donc vide sans qu'aucune interaction ne soit nécessaire pour le
    remarquer. Le défaut doit désormais pointer vers un onglet réellement
    traçable, sans aucune action de l'utilisateur."""
    at = AppTest.from_file(str(Path(__file__).parent.parent / "app.py"), default_timeout=60)
    at.run()
    fu = at.file_uploader[0]
    fu.upload("BanqueA.xlsx", (FIXTURES / "BanqueA.xlsx").read_bytes())
    fu.upload("OperateurB.xlsx", (FIXTURES / "OperateurB.xlsx").read_bytes())
    fu.run()
    assert not at.exception

    assert at.selectbox(key="explored_sheet").value != "chèques&VIR"
    assert at.selectbox(key="traced_indicator").value is not None
    assert len(at.get("plotly_chart")) >= 1




