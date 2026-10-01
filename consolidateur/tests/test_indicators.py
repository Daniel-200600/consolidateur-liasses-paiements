"""
tests/test_indicators.py

Découverte automatique des indicateurs (évolution post-Phase 9).

Objectif : vérifier que l'application expose désormais TOUTES les lignes
porteuses de données du gabarit (45 sur les fichiers de référence, contre 8
indicateurs écrits à la main auparavant), et que les valeurs extraites
restent rigoureusement identiques aux références validées
(cf. Cahier des charges, section 9).
"""

import datetime
from pathlib import Path

import pytest

from core.indicators import (
    analyze_layout, discover_indicators, indicator_periods, indicator_series,
    indicator_totals, indicator_value,
)
from core.parsing import Institution, parse_workbook

FIXTURES = Path(__file__).parent / "fixtures_fictives"


@pytest.fixture
def institutions():
    return [
        Institution(name="BanqueA", file_name="BanqueA.xlsx", sheets=parse_workbook(FIXTURES / "BanqueA.xlsx")),
        Institution(name="OperateurB", file_name="OperateurB.xlsx", sheets=parse_workbook(FIXTURES / "OperateurB.xlsx")),
    ]


@pytest.fixture
def indicators(institutions):
    return discover_indicators(institutions)


def _find(indicators, sheet, row):
    return next(i for i in indicators if i.sheet == sheet and i.row == row)


# --------------------------------------------------------------------- #
# Couverture
# --------------------------------------------------------------------- #

def test_exposes_the_full_table_structure(indicators):
    """Toute la structure du gabarit est exposée, pas seulement les lignes
    déjà remplies : une ventilation vide (« - dont Cameroun ») est en soi une
    information de reporting.

    Les notes de bas de tableau (« (1) porteurs qui ont effectué… ») en sont
    exclues : ce sont des définitions, pas des lignes de données.

    Le compte inclut les énumérations de réseaux monétiques (Privative,
    GIMAC, VISA, MASTERCARD, UnionPay, American Express) : celles qu'aucun
    établissement ne renseignait étaient auparavant prises pour des titres et
    disparaissaient du récapitulatif."""
    assert len(indicators) == 280


def test_filled_rows_match_the_expected_count(indicators):
    assert len([i for i in indicators if i.has_data]) == 45


def test_every_populated_sheet_is_covered(indicators):
    filled_sheets = {i.sheet for i in indicators if i.has_data}
    # Les 7 onglets réellement renseignés dans les fichiers de référence.
    assert filled_sheets == {
        "Mobile Money1", "MobileMoney2", "MobileMoney3",
        "Cartes1", "Cartes 2", "Cartes 3", "Cartes 5",
    }


def test_structure_of_unfilled_sheets_is_still_exposed(indicators):
    """Un onglet qu'aucun établissement n'a rempli doit tout de même montrer
    sa structure : c'est ainsi qu'on voit ce qui reste à collecter."""
    for sheet in ("chèques&VIR", "Transfert d'argent", "Cartes 4"):
        rows = [i for i in indicators if i.sheet == sheet]
        assert rows, f"{sheet} devrait exposer sa structure"
        assert all(not i.has_data for i in rows)


def test_previously_ignored_sheets_are_now_exposed(indicators):
    # MobileMoney2 (l'onglet le plus riche : 274 valeurs) n'exposait
    # auparavant aucun indicateur.
    assert len([i for i in indicators if i.sheet == "MobileMoney2" and i.has_data]) == 10
    assert len([i for i in indicators if i.sheet == "Cartes 2" and i.has_data]) == 10
    assert len([i for i in indicators if i.sheet == "MobileMoney3" and i.has_data]) == 3


def test_mobilemoney3_full_breakdown_is_visible(indicators):
    """Cas signalé : l'onglet MobileMoney3 n'affichait que 3 lignes alors que
    le tableau en compte une quarantaine (ventilation par pays et par zone)."""
    mm3 = [i for i in indicators if i.sheet == "MobileMoney3"]
    assert len(mm3) == 37
    names = [i.display_name for i in mm3]
    # Chaque ligne reste identifiable : « Transfert d'argent reçus » figure
    # dans plusieurs tableaux, c'est le couple (tableau, libellé) qui lève
    # l'ambiguïté — le titre du tableau ayant sa propre colonne à l'affichage.
    assert len({(i.rubric, i.display_name) for i in mm3}) == len(mm3)
    assert any("dont Cameroun" in n for n in names)
    assert any("dont Tchad" in n for n in names)
    assert any("dont Oceanie" in n for n in names)
    # Les deux blocs de ventilation (reçus / envoi) sont bien distingués.
    assert any(n.startswith("Transfert d'argent reçus ›") for n in names)
    assert any(n.startswith("Transfert d'argent envoi ›") for n in names)


def test_both_sections_of_mobilemoney3_are_detected(indicators):
    """« A- OPERATIONS DOMESTIQUES » et « B- Transactions internationales »
    sont deux TABLEAUX distincts de l'onglet. Le second est en minuscules :
    il échappait à la détection fondée sur la seule casse, d'où la règle de
    fratrie entre titres numérotés (A-, B-)."""
    rubrics = {i.rubric for i in indicators if i.sheet == "MobileMoney3"}
    assert any(r.startswith("A-") for r in rubrics)
    assert any(r.startswith("B-") for r in rubrics)


def test_rubrics_name_the_source_tables(indicators):
    """Chaque ligne doit porter le titre du tableau dont elle provient, tel
    qu'il figure dans le gabarit (« CHEQUES », « VIREMENTS »…)."""
    rubrics = {i.rubric for i in indicators if i.sheet == "chèques&VIR"}
    assert {"CHEQUES", "VIREMENTS", "PRELEVEMENTS", "EFFETS DE COMMERCE"} <= rubrics


def test_total_rows_are_not_treated_as_table_titles(indicators):
    """« TOTAL (A+B+C) » est en majuscules mais reste une ligne de résultat :
    elle ne doit jamais devenir un titre de tableau."""
    rubrics = {i.rubric for i in indicators}
    assert not any(r.upper().startswith("TOTAL") for r in rubrics)


def test_repeated_labels_are_separated_by_their_table(indicators):
    """« Retrait GAB » apparaît dans quatre tableaux de Cartes 5 : chaque
    occurrence doit rester identifiable."""
    gabs = [i for i in indicators if i.sheet == "Cartes 5" and i.label.strip().lower() == "retrait gab"]
    assert len(gabs) >= 3
    assert len({(i.rubric, i.display_name) for i in gabs}) == len(gabs)


def test_header_rows_are_not_indicators(indicators):
    """Les lignes administratives et les en-têtes de colonnes ne doivent pas
    être présentés comme des indicateurs."""
    labels = {i.label.lower().rstrip(" :") for i in indicators}
    for junk in ("etablissement", "service", "réseau", "nature de l’information"):
        assert junk not in labels
    # ... mais les libellés qui ressemblent à des en-têtes tout en portant une
    # vraie donnée restent bien des indicateurs.
    assert any("nobre de clients" in i.label.lower() for i in indicators)


# --------------------------------------------------------------------- #
# Exactitude : mêmes valeurs que les références validées
# --------------------------------------------------------------------- #

def test_retrait_gab_matches_reference(institutions, indicators):
    gab = _find(indicators, "Cartes 5", 10)
    assert indicator_totals(institutions, gab, "Nombre")[1] == 142872
    assert indicator_totals(institutions, gab, "Valeur")[1] == 14942539230


def test_cartes1_values_match_reference(institutions, indicators):
    assert indicator_totals(institutions, _find(indicators, "Cartes1", 2), "")[1] == 11386
    assert indicator_totals(institutions, _find(indicators, "Cartes1", 3), "")[1] == 29374
    assert indicator_totals(institutions, _find(indicators, "Cartes1", 9), "Nombre de cartes")[1] == 21298


def test_mobile_money_monthly_values_match_reference(institutions, indicators):
    dec = datetime.date(2025, 12, 1)
    porteurs = dict(indicator_series(institutions, _find(indicators, "Mobile Money1", 6), ""))
    assert sum(porteurs[dec].values()) == 1232671
    actifs = dict(indicator_series(institutions, _find(indicators, "Mobile Money1", 7), ""))
    assert sum(actifs[dec].values()) == 359593


def test_monthly_sheet_with_nombre_valeur_pairs(institutions, indicators):
    """MobileMoney2 porte un couple Nombre/Valeur PAR MOIS. Un bug initial
    (dictionnaire au lieu d'une liste de paires) écrasait les colonnes et ne
    conservait que le dernier mois : ce test verrouille la correction."""
    recharge = _find(indicators, "MobileMoney2", 5)
    nb = dict(indicator_series(institutions, recharge, "Nombre"))
    val = dict(indicator_series(institutions, recharge, "Valeur"))
    assert sum(nb[datetime.date(2025, 1, 1)].values()) == 975862
    assert sum(nb[datetime.date(2025, 2, 1)].values()) == 1199948
    assert sum(nb[datetime.date(2025, 3, 1)].values()) == 874222
    assert sum(val[datetime.date(2025, 1, 1)].values()) == 18535567925


def test_sector_detail_is_now_readable(institutions, indicators):
    # Détail sectoriel des paiements, totalement absent du tableau de bord
    # jusqu'ici.
    jan = datetime.date(2025, 1, 1)
    elec = dict(indicator_series(institutions, _find(indicators, "MobileMoney2", 12), "Nombre"))
    tel = dict(indicator_series(institutions, _find(indicators, "MobileMoney2", 13), "Nombre"))
    assert sum(elec[jan].values()) == 7376
    assert sum(tel[jan].values()) == 2190099


# --------------------------------------------------------------------- #
# Robustesse
# --------------------------------------------------------------------- #

def test_repeated_labels_are_disambiguated_by_section(indicators):
    """« Retrait GAB » apparaît plusieurs fois dans Cartes 5 : chaque
    occurrence doit rester identifiable, par son tableau d'origine et, le cas
    échéant, par sa sous-section."""
    gabs = [i for i in indicators if i.sheet == "Cartes 5" and "retrait gab" in i.label.lower()]
    assert len(gabs) >= 2
    assert len({(i.rubric, i.display_name) for i in gabs}) == len(gabs)
    assert any("VOS PORTEURS" in i.rubric.upper() for i in gabs)


def test_indicator_keys_are_unique_and_stable(indicators):
    keys = [i.key for i in indicators]
    assert len(set(keys)) == len(keys)
    gab = next(i for i in indicators if i.sheet == "Cartes 5" and i.row == 10)
    assert gab.key == "Cartes 5|10"  # position, pas libellé : stable


def test_institution_without_sheet_contributes_zero(institutions, indicators):
    # BanqueA ne renseigne pas Mobile Money1 : sa contribution vaut 0, et le
    # total marché reste correct.
    porteurs = _find(indicators, "Mobile Money1", 6)
    per_inst, total = indicator_totals(institutions, porteurs, "")
    assert dict(per_inst)["BanqueA"] == 0
    assert dict(per_inst)["OperateurB"] == total


def test_works_with_single_institution():
    operateur_b = Institution(name="OperateurB", file_name="o.xlsx", sheets=parse_workbook(FIXTURES / "OperateurB.xlsx"))
    inds = discover_indicators([operateur_b])
    assert len(inds) > 0
    assert all(i.sheet.startswith("Mobile") for i in inds if i.has_data)


def test_no_institutions_returns_empty():
    assert discover_indicators([]) == []


def test_monthly_periods_are_chronological(institutions, indicators):
    periods = indicator_periods(institutions, _find(indicators, "Mobile Money1", 6))
    assert periods == sorted(periods)
    assert datetime.date(2025, 1, 1) in periods


def test_layout_detects_monthly_vs_static(institutions):
    sheets = institutions[1].sheets  # OperateurB
    assert analyze_layout(sheets["Mobile Money1"].grid).is_monthly is True
    assert analyze_layout(sheets["MobileMoney2"].grid).is_monthly is True
    assert analyze_layout(sheets["Cartes1"].grid).is_monthly is False


def test_latest_period_used_when_none_specified(institutions, indicators):
    """Sans période précisée, la dernière valeur renseignée est retenue."""
    porteurs = _find(indicators, "Mobile Money1", 6)
    operateur_b = institutions[1]
    series = dict(indicator_series([operateur_b], porteurs, ""))
    last_with_data = max(p for p, v in series.items() if v["OperateurB"] != 0)
    assert indicator_value(operateur_b, porteurs, "") == series[last_with_data]["OperateurB"]


# --------------------------------------------------------------------- #
# Mémorisation (performance) : un cache ne doit JAMAIS renvoyer un
# résultat périmé — sur un outil réglementaire, un chiffre obsolète
# affiché comme à jour serait pire qu'une lenteur.
# --------------------------------------------------------------------- #

def test_cache_distingue_deux_jeux_detablissements_differents():
    from core.parsing import Institution, parse_workbook

    banque_a = Institution("BanqueA", "b.xlsx", parse_workbook(FIXTURES / "BanqueA.xlsx"))
    operateur_b = Institution("OperateurB", "o.xlsx", parse_workbook(FIXTURES / "OperateurB.xlsx"))

    seul = discover_indicators([banque_a])
    ensemble = discover_indicators([banque_a, operateur_b])
    assert len(ensemble) >= len(seul)
    # Les deux résultats doivent être distincts, pas le même objet mis en cache
    assert seul is not ensemble


def test_cache_distingue_avec_et_sans_cartographie():
    from core.cartographie import Cartographie, EntreeCartographie
    from core.llm import ROLE_TITRE
    from core.parsing import Institution, parse_workbook

    insts = [Institution("BanqueA", "b.xlsx", parse_workbook(FIXTURES / "BanqueA.xlsx"))]
    sans = discover_indicators(insts)

    carto = Cartographie()
    carto.entrees[("Cartes1", 19)] = EntreeCartographie(
        sheet="Cartes1", row=19, libelle="MASTERCARD", role=ROLE_TITRE)
    avec = discover_indicators(insts, cartographie=carto)

    assert len(avec) < len(sans), "la cartographie doit retirer au moins une ligne"


def test_cache_layout_ne_melange_pas_deux_grilles():
    from core.indicators import analyze_layout, vider_cache_layout

    vider_cache_layout()
    grille_mensuelle = [
        ["Titre"], [None],
        [None, datetime.date(2025, 1, 1), None, datetime.date(2025, 2, 1)],
        ["Nature", "Nombre", "Valeur", "Nombre", "Valeur"],
        ["Ligne A", 1, 2, 3, 4],
    ]
    grille_statique = [["Titre"], ["Nature", "Nombre", "Valeur"], ["Ligne A", 1, 2]]

    l1 = analyze_layout(grille_mensuelle)
    l2 = analyze_layout(grille_statique)
    l1_bis = analyze_layout(grille_mensuelle)

    assert l1.is_monthly is True
    assert l2.is_monthly is False
    assert l1_bis is l1  # bien mis en cache
    assert l1_bis.is_monthly is True  # et pas écrasé par l'autre grille


def test_resultats_identiques_avec_et_sans_cache():
    """Le cache ne doit rien changer au résultat : deux appels successifs
    doivent donner exactement les mêmes indicateurs qu'un calcul à froid."""
    from core.indicators import vider_cache_indicateurs, vider_cache_layout
    from core.parsing import Institution, parse_workbook

    insts = [
        Institution("BanqueA", "b.xlsx", parse_workbook(FIXTURES / "BanqueA.xlsx")),
        Institution("OperateurB", "o.xlsx", parse_workbook(FIXTURES / "OperateurB.xlsx")),
    ]
    vider_cache_indicateurs()
    vider_cache_layout()
    a_froid = [(i.key, i.label, i.has_data, tuple(i.measures)) for i in discover_indicators(insts)]

    vider_cache_indicateurs()
    vider_cache_layout()
    discover_indicators(insts)  # remplit le cache
    depuis_cache = [(i.key, i.label, i.has_data, tuple(i.measures)) for i in discover_indicators(insts)]

    assert a_froid == depuis_cache
