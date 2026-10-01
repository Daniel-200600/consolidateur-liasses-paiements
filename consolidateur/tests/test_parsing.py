

# --------------------------------------------------------------------- #
# clean_institution_name : jamais un code pays comme nom d'établissement
#
# Cas réel signalé par capture d'écran : des fichiers nommés en commençant
# par le code pays (« CF-BanqueXYZ_Liasse_... ») faisaient retenir « CF »
# comme nom d'établissement. Deux fichiers de pays différents ainsi nommés
# produisaient une colonne de Sommaire absurde une fois désambiguïsés par
# suffixe (« CF », « CF (2) », « CG », « CG (2) »...).
# --------------------------------------------------------------------- #

def test_code_pays_en_tete_de_fichier_nest_jamais_retenu():
    from core.parsing import clean_institution_name
    assert clean_institution_name("CF-BanqueXYZ_Liasse_Stats_Paiements_2025.xlsx") == "BanqueXYZ"
    assert clean_institution_name("CG-AutreBanque_Liasse_2025.xlsx") == "AutreBanque"
    assert clean_institution_name("GA_UneBanqueGabonaise-Liasse_2025.xlsx") == "UneBanqueGabonaise"


def test_code_pays_suivi_de_vocabulaire_generique_nest_jamais_retenu():
    """Une fois le code pays écarté, le mot générique suivant (Liasse,
    Stats, Paiements...) ne doit pas non plus être pris pour un nom
    d'établissement."""
    from core.parsing import clean_institution_name
    assert clean_institution_name("CF_Liasse_Stats_Paiements_2025.xlsx") != "Stats"
    assert clean_institution_name("CG_Liasse_Statistiques_Paiement_2025.xlsx") != "Statistiques"


def test_non_regression_sur_les_dix_fichiers_reels_connus():
    """Le correctif ne doit rien casser des extractions déjà validées."""
    from core.parsing import clean_institution_name
    attendu = {
        "ETABA-CM_Liasse_Stats_Paiements_2025_2026.xlsx": "ETABA",
        "BanqueA_CA-Liasse_Stats_Paiements_2025__1_.xlsx": "BanqueA",
        "OperateurB_RCA_Liasse_Stats_Paiements_2025_1.xlsx": "OperateurB",
        "ETABB-CM_Liasse_Stats_Paiements_du_01012025_au_30062026.xlsx": "ETABB",
        "ETABC-CM_Liasse_Stats_Paiements_2025_JUNE_2026_BANQUE_FICTIVE.xlsx": "ETABC",
        "ETABD-CM_Liasse_Stats_Paiements_2025.xlsx": "ETABD",
        "ETABE-CM_Liasse_Stats_Paiements_2025-V1.xlsx": "ETABE",
        "ETATS_TRANSFERT_ACA_BANK_2025_-_2026__1_.xlsx": "ETATS",
        "ETABG-CM_Statistiques_Transfert_dargent__transmission_de_fonds__JAN_2025_JUIN_2026.xlsx": "ETABG",
    }
    for nom, valeur_attendue in attendu.items():
        assert clean_institution_name(nom) == valeur_attendue, nom


def test_deux_fichiers_de_pays_differents_ne_collisionnent_plus():
    """Reproduction exacte du cas signalé : deux établissements de pays
    différents, nommés en tête par leur code pays, ne doivent plus produire
    le même nom faussement désambiguïsé (« CF », « CF (2) »)."""
    from core.parsing import clean_institution_name
    nom_cf = clean_institution_name("CF-PremiereBanque_Liasse_2025.xlsx")
    nom_cg = clean_institution_name("CG-DeuxiemeBanque_Liasse_2025.xlsx")
    assert nom_cf != "CF"
    assert nom_cg != "CG"
    assert nom_cf != nom_cg


def test_nom_de_fichier_sans_rien_dexploitable_ne_plante_jamais():
    """Cas extrême : un fichier nommé uniquement d'après son pays et le
    vocabulaire générique du gabarit, sans aucun nom d'établissement. Ne
    doit jamais planter ni renvoyer une chaîne vide — le champ reste de
    toute façon modifiable dans l'interface."""
    from core.parsing import clean_institution_name
    resultat = clean_institution_name("CF_Liasse_Stats_Paiements_2025.xlsx")
    assert resultat  # jamais vide
    assert resultat.upper() != "CF"  # jamais le code pays lui-même


# --------------------------------------------------------------------- #
# Le nom déclaré par l'établissement lui-même prime sur le nom de fichier
#
# Cas réel trouvé en auditant un export utilisateur à grande échelle (568
# onglets, 47 établissements) : deux fichiers d'un établissement réel
# (« ETABH ») avaient un nom de fichier ne portant aucune trace
# exploitable de ce nom — le nom proposé automatiquement était donc
# entièrement faux (« ETABA »), une erreur d'étiquetage dans un document
# destiné à la BEAC.
# --------------------------------------------------------------------- #

def test_annee_collee_par_espace_est_retiree_sans_perdre_le_reste():
    """Cas réel : 'BAC TCHAD' était devenu '2025 BAC TCHAD' — l'année,
    collée par un espace plutôt qu'un séparateur, doit être retirée sans
    jeter le reste du nom."""
    from core.parsing import clean_institution_name
    assert clean_institution_name("2025 BAC TCHAD_Liasse_Stats_2025.xlsx") == "BAC TCHAD"
    assert clean_institution_name("2026 BAC TCHAD_Liasse_Stats_2026.xlsx") == "BAC TCHAD"


def test_repli_final_najamais_un_code_pays_meme_sans_rien_dautre():
    """Le repli de dernier recours (nom de fichier réduit à un code pays,
    une année et du vocabulaire générique) ne doit jamais renvoyer le code
    pays lui-même tant qu'un autre segment, même imparfait, existe."""
    from core.parsing import clean_institution_name
    resultat = clean_institution_name("CF_Liasse_Stats_Paiements_2025.xlsx")
    assert resultat.upper() != "CF"


def test_nom_declare_extrait_le_bon_champ():
    from core.parsing import SheetData, nom_declare
    sd = SheetData(grid=[
        ["STATISTIQUES 2025", None],
        ["Etablissement :", "ETABH"],
    ], errors=[], text_numbers=[])
    assert nom_declare({"chèques&VIR": sd}) == "ETABH"


def test_nom_declare_renvoie_none_si_champ_vide():
    """La grande majorité des établissements laissent ce champ vide dans
    la pratique : ne doit jamais planter, ni renvoyer une valeur inventée."""
    from core.parsing import SheetData, nom_declare
    sd = SheetData(grid=[
        ["STATISTIQUES 2025", None],
        ["Etablissement :", None],
    ], errors=[], text_numbers=[])
    assert nom_declare({"chèques&VIR": sd}) is None
    assert nom_declare({}) is None


def test_nom_declare_ignore_un_libelle_duplique():
    """Cas réel trouvé en corrigeant ce bug : un établissement (ETABE) répète
    'Etablissement :' deux fois dans la même ligne (artefact de fusion de
    cellules) — la seconde occurrence ne doit jamais être prise pour une
    valeur exploitable."""
    from core.parsing import SheetData, nom_declare
    sd = SheetData(grid=[
        ["STATISTIQUES 2025", None],
        ["Etablissement :", None, None, None, "Etablissement :"],
    ], errors=[], text_numbers=[])
    assert nom_declare({"chèques&VIR": sd}) is None


def test_le_nom_de_fichier_uploade_sert_toujours_de_nom_par_defaut():
    """Sur demande explicite de l'utilisateur : le nom d'établissement est
    désormais TOUJOURS le nom du fichier tel qu'uploadé (sans extension),
    jamais deviné ni transformé — même quand le fichier déclare un autre
    nom en interne (champ « Etablissement : »). Le champ de renommage
    manuel a depuis été retiré (barre latérale simplifiée), le nom est
    donc fixe."""
    import shutil
    import tempfile
    from pathlib import Path

    import openpyxl
    import core.history as hm
    import core.calibration as cm2
    import core.cartographie as cg
    from streamlit.testing.v1 import AppTest

    hm.default_history_path = lambda: Path(tempfile.mkdtemp()) / "h.csv"
    cm2.chemin_par_defaut = lambda: Path(tempfile.mkdtemp()) / "c.json"
    cg.chemin_par_defaut = lambda: Path(tempfile.mkdtemp()) / "g.json"

    racine = Path(__file__).parent.parent
    tmp = Path(tempfile.mkdtemp()) / "ETABA-CM_Liasse_Stats_Paiements_2025.xlsx"
    shutil.copy(racine / "tests" / "fixtures_fictives" / "BanqueA.xlsx", tmp)
    wb = openpyxl.load_workbook(tmp)
    wb["chèques&VIR"]["B2"] = "ETABH"
    wb.save(tmp)

    at = AppTest.from_file(str(racine / "app.py"), default_timeout=90)
    at.run()
    fu = at.file_uploader[0]
    fu.upload(tmp.name, tmp.read_bytes())
    fu.run()
    assert not at.exception

    df = at.get("dataframe")[0].value
    assert "ETABA-CM_Liasse_Stats_Paiements_2025" in df.columns
