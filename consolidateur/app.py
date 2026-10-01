"""
app.py — Consolidateur de liasses statistiques de paiements (BEAC)

Toutes les options de l'utilisateur (dépôt de fichiers, gestion des
établissements, choix d'affichage, export) vivent dans la barre latérale ;
la zone principale n'affiche que des résultats (tableaux, graphiques,
alertes). Thème vert émeraude / or défini nativement dans
.streamlit/config.toml (cf. Cahier des charges, section 4 pour l'architecture
générale ; cette organisation UI est une évolution demandée après la Phase 9).
"""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import streamlit as st


def _px():
    """Accès différé à plotly.express.

    L'import de plotly coûte plus d'une seconde au démarrage, alors que les
    graphiques ne sont pas systématiquement consultés : on ne le paie donc
    qu'au premier affichage réel d'un graphique, ce qui rend l'ouverture de
    l'application nettement plus rapide.
    """
    import plotly.express as px
    return px

from core.export import build_full_workbook, build_resume_workbook
from core.kpis import compute_kpis, retrait_gab_kpi
from core.montant_total import composantes_par_categorie, repartition_par_pays_et_rubrique, repartition_par_reseau
from core.cartographie import Cartographie
from core.indicators import discover_indicators, indicator_series, indicator_totals
from core.calibration import Calibration
from core.pays import NOM_PAYS, detecter_pays
from core.parsing import KNOWN_SHEETS, Institution, analyser_fichier, parse_workbook
from core.quality import run_quality_checks

st.set_page_config(
    page_title="Consolidateur de liasses — Paiements RCA",
    page_icon="📊",
    layout="wide",
)

# ---------------------------------------------------------------------------
# État de session
# ---------------------------------------------------------------------------
if "parsed_cache" not in st.session_state:
    # Cache par identifiant de fichier — seulement pour éviter de reparser
    # à chaque interaction (coûteux). La liste des établissements ACTIFS
    # est toujours dérivée de ce que l'uploader natif contient à l'instant
    # présent (cf. plus bas) : retirer un fichier ne demande plus de bouton
    # dédié, la croix native du composant d'upload suffit.
    st.session_state.parsed_cache = {}


# Rattachements d'onglets déjà validés (cf. Étape 1) : chargés une fois,
# hors du dossier projet, pour ne jamais redemander une validation déjà
# faite lors d'un précédent dépôt.
calibration = Calibration.charger()


def _rattacher_automatiquement(non_reconnus, calib) -> bool:
    """Valide automatiquement toute piste plausible trouvée sur un onglet
    non reconnu — proposition forte, piste faible, ou segments d'un onglet
    composite — exactement comme le ferait un clic manuel, mais sans
    attendre ce clic. Sur demande explicite de l'utilisateur : un onglet
    rempli mais non standard doit être rattaché automatiquement.

    Seule exception, la seule qui se soit révélée réellement nécessaire au
    fil de ce projet : un onglet d'une période de reporting révolue n'est
    JAMAIS rattaché automatiquement, quelle que soit la confiance de la
    piste — le consolider gonflerait les totaux d'une période avec des
    montants d'une autre, sans qu'aucune erreur ne le signale (cas réel :
    des onglets 2022 laissés dans un fichier 2025-2026, ressemblant au
    gabarit à plus de 90 %).
    """
    change = False
    for o in non_reconnus:
        if o.periode_revolue:
            continue
        if o.theme_propose:
            calib.valider(o.nom, o.theme_propose)
            change = True
        elif o.segments:
            calib.valider_segments(o.nom, [s.theme for s in o.segments])
            change = True
        elif o.suggestion:
            calib.valider(o.nom, o.suggestion)
            change = True
    return change


def _parser_avec_cache(f) -> dict:
    """Analyse un fichier une seule fois (mis en cache par id), même s'il
    est reparcouru à chaque interaction de l'utilisateur ailleurs dans
    l'app."""
    file_id = f"{f.name}-{f.size}"
    if file_id in st.session_state.parsed_cache:
        return st.session_state.parsed_cache[file_id]

    raw = f.getvalue()
    pays_detecte = detecter_pays(f.name)
    try:
        sheets, non_reconnus = analyser_fichier(io.BytesIO(raw), f.name, calibration=calibration)
        if _rattacher_automatiquement(non_reconnus, calibration):
            calibration.enregistrer()
            sheets, non_reconnus = analyser_fichier(io.BytesIO(raw), f.name, calibration=calibration)
        # Aucun rejet, même si `sheets` est vide (aucun des 11 thèmes
        # reconnu) : tous les fichiers, sans exception, doivent être lus
        # et traités. Un fichier sans onglet reconnu reste consolidé
        # normalement (avec zéro contribution aux totaux), et TOUS ses
        # onglets restent visibles dans le tableau hors gabarit.
        resultat = {
            "id": file_id, "name": Path(f.name).stem, "file_name": f.name,
            "sheets": sheets, "non_reconnus": non_reconnus, "raw": raw, "pays": pays_detecte, "error": None,
        }
    except Exception as exc:
        # Uniquement pour un fichier réellement illisible (pas un classeur
        # Excel valide) : là, rien à consolider ni à lister.
        resultat = {
            "id": file_id, "name": Path(f.name).stem, "file_name": f.name,
            "sheets": {}, "non_reconnus": [], "raw": raw, "pays": pays_detecte, "error": str(exc),
        }
    st.session_state.parsed_cache[file_id] = resultat
    return resultat


def _fmt(n) -> str:
    return f"{n:,.0f}".replace(",", " ")


# ---------------------------------------------------------------------------
# SIDEBAR — 1. Dépôt des fichiers + gestion des établissements
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("## Consolidateur")
    st.caption("Statistiques de paiements")
    st.divider()

    st.markdown("### 1. Fichiers")
    mode_depot = st.radio(
        "Mode de dépôt", ["Fichiers", "Dossier entier"],
        horizontal=True, label_visibility="collapsed", key="mode_depot",
    )
    if mode_depot == "Dossier entier":
        uploaded = st.file_uploader(
            "Dépose un dossier contenant tes liasses (.xlsx)",
            type=["xlsx", "xlsm"],
            accept_multiple_files="directory",
        )
        st.caption("Tous les fichiers .xlsx du dossier (et de ses sous-dossiers) sont repris automatiquement.")
    else:
        uploaded = st.file_uploader(
            "Dépose une ou plusieurs liasses (.xlsx)",
            type=["xlsx", "xlsm"],
            accept_multiple_files=True,
        )
    if uploaded:
        vus: set[str] = set()
        institutions = []
        for f in uploaded:
            file_id = f"{f.name}-{f.size}"
            if file_id in vus:
                continue  # même fichier déposé plusieurs fois : jamais compté deux fois
            vus.add(file_id)
            institutions.append(_parser_avec_cache(f))
    else:
        institutions = []

    erreurs = [i for i in institutions if i["error"]]
    for inst in erreurs:
        st.error(f"❌ {inst['file_name']}")
        st.caption(inst["error"])

    total_non_rattaches = sum(len(i.get("non_reconnus", [])) for i in institutions if not i["error"])
    if total_non_rattaches:
        st.caption(f"⚠️ {total_non_rattaches} onglet(s) au total restent hors gabarit "
                  f"(période révolue ou structure sans piste) — détail dans les exports.")

# ---------------------------------------------------------------------------
# En-tête (zone principale)
# ---------------------------------------------------------------------------
st.title("📊 Consolidateur de liasses statistiques de paiements")
st.caption("Import multi-fichiers, consolidation marché et indicateurs clés")

if not institutions:
    st.info("👈 Dépose une ou plusieurs liasses dans la barre latérale pour commencer.")
    st.stop()

valid_institutions = [i for i in institutions if not i["error"]]

if not valid_institutions:
    st.warning("Aucun fichier valide chargé.")
    st.stop()

# Garde-fou : les indicateurs sont agrégés par nom d'établissement (cf.
# core/kpis.py). Deux établissements affichant le même nom écraseraient donc
# silencieusement leurs valeurs l'un l'autre. On désambiguïse automatiquement
# tout doublon (y compris après un renommage manuel) et on prévient l'utilisateur.
seen_names: dict[str, int] = {}
renamed_for_dedup = False
for inst in valid_institutions:
    base = inst["name"].strip() or inst["file_name"]
    if base in seen_names:
        seen_names[base] += 1
        inst["name"] = f"{base} ({seen_names[base]})"
        renamed_for_dedup = True
    else:
        seen_names[base] = 1
        inst["name"] = base
if renamed_for_dedup:
    st.warning("Deux établissements portaient le même nom : un suffixe a été ajouté automatiquement pour les distinguer.")

inst_names = [i["name"] for i in valid_institutions]

# ---------------------------------------------------------------------------
# Consolidation (Phase 3)
# ---------------------------------------------------------------------------
institution_objs = [
    Institution(name=i["name"], file_name=i["file_name"], sheets=i["sheets"],
               non_reconnus=i.get("non_reconnus", []), pays=i.get("pays"))
    for i in valid_institutions
]

# ---------------------------------------------------------------------------
# Indicateurs clés (Phase 4)
# ---------------------------------------------------------------------------
st.subheader("Indicateurs clés")

kpis = compute_kpis(institution_objs)
gab = retrait_gab_kpi(institution_objs)

rows = []
# Sur les 6 indicateurs historiques, deux faisaient doublon avec un voisin
# plus informatif (porteurs « total cumulé » avec « actifs » ; « comptes »
# avec « clients » et « cartes de débit ») — retirés pour resserrer le
# tableau, sur demande explicite : moins d'indicateurs, mais plus utiles.
cles_a_garder = {"porteurs_mm_actifs", "encours_me", "clients_cartes", "cartes_debit"}
for k in kpis:
    if k.key not in cles_a_garder:
        continue
    per_inst = dict(k.per_inst)
    row = {"Indicateur": k.label}
    for name in inst_names:
        row[name] = _fmt(per_inst.get(name, 0))
    row["Total marché"] = _fmt(k.total)
    rows.append(row)

gab_per_inst = {p["name"]: p for p in gab["per_inst"]}
row_val = {"Indicateur": "Retraits GAB — valeur (XAF)"}
for name in inst_names:
    row_val[name] = _fmt(gab_per_inst.get(name, {}).get("valeur", 0))
row_val["Total marché"] = _fmt(gab["total"]["valeur"])
rows.append(row_val)

# Grandes familles d'activité (5 lignes), regroupant les 17 lignes
# détaillées du gabarit — mêmes montants, déjà vérifiés (sans double
# comptage, avec repli sur les sous-totaux quand un total de tête est vide,
# anomalie signalée plutôt qu'incluse silencieusement), simplement présentés
# par famille plutôt qu'un par un. Le détail ligne à ligne reste disponible
# dans les exports (bloc « Montant total par pays » du résumé).
categories_totales = {c.description: c for c in composantes_par_categorie(institution_objs)}
categories_par_inst = {inst.name: {c.description: c for c in composantes_par_categorie([inst])}
                       for inst in institution_objs}
une_anomalie_existe = False
for description, cat_totale in categories_totales.items():
    row = {"Indicateur": description}
    for name in inst_names:
        c = categories_par_inst[name].get(description)
        marque = " ⚠️" if c and c.anomalie else ""
        row[name] = _fmt(c.valeur if c else 0) + marque
        une_anomalie_existe = une_anomalie_existe or bool(marque)
    row["Total marché"] = _fmt(cat_totale.valeur) + (" ⚠️" if cat_totale.anomalie else "")
    rows.append(row)

kpi_df = pd.DataFrame(rows).set_index("Indicateur").astype(str)
st.dataframe(kpi_df, width="stretch")
st.caption(
    "Les indicateurs Mobile Money retiennent automatiquement le dernier mois renseigné en commun "
    "par au moins un établissement (cf. Cahier des charges, section 6). Une colonne à zéro peut "
    "signaler un onglet en attente de validation plutôt qu'une absence réelle d'activité — voir "
    "« ⚠️ onglet(s) non rattaché(s) » dans la barre latérale."
)
if une_anomalie_existe:
    st.caption(
        "⚠️ Une famille marquée contient au moins une valeur au saut mensuel invraisemblable "
        "(facteur supérieur à 15 par rapport au mois précédent) : à vérifier dans le fichier "
        "source. Exclue du montant total par pays des exports, mais restée visible ici."
    )

# ---------------------------------------------------------------------------
# Tous les indicateurs (découverte automatique)
#
# La liste d'indicateurs écrite à la main ne couvrait que 8 des ~45 lignes de
# données du gabarit. Ici, chaque ligne porteuse de données est exposée, quel
# que soit l'onglet — sans énumération codée en dur (cf. core/indicators.py).
# ---------------------------------------------------------------------------
# Cartographie du gabarit validée au préalable (assistée par le modèle local).
# En son absence, les heuristiques s'appliquent : le modèle est un confort,
# jamais une dépendance.
cartographie = Cartographie.charger()
all_indicators = discover_indicators(institution_objs, cartographie=cartographie)
sheets_with_indicators = sorted({i.sheet for i in all_indicators}, key=KNOWN_SHEETS.index)

with st.sidebar:
    st.markdown("### 2. Indicateurs détaillés")
    if sheets_with_indicators:
        # Le premier onglet du gabarit (chèques&VIR) n'a pas de disposition
        # mensuelle : le sélectionner par défaut laissait « Indicateur à
        # tracer » sans aucune option, et donc le graphique d'évolution par
        # pays sans rien à afficher — sans que ce soit visible comme un
        # problème de sélection plutôt qu'une vraie absence de données.
        # Priorité au premier onglet qui a une série mensuelle renseignée.
        index_defaut = 0
        for i, feuille in enumerate(sheets_with_indicators):
            if any(ind.sheet == feuille and ind.is_monthly and ind.has_data for ind in all_indicators):
                index_defaut = i
                break
        explored_sheet = st.selectbox("Onglet à explorer", sheets_with_indicators,
                                      index=index_defaut, key="explored_sheet")
        sheet_indicators = [i for i in all_indicators if i.sheet == explored_sheet]
        only_filled = st.checkbox(
            "Masquer les lignes non renseignées", value=False, key="only_filled",
            help="Par défaut, toute la structure du tableau est affichée, y compris les ventilations vides.",
        )
        # On ne propose au traçage que les lignes renseignées : une courbe
        # plate à zéro n'apporte rien.
        traceable = [i for i in sheet_indicators if i.is_monthly and i.has_data]
        traced_name = st.selectbox(
            "Indicateur à tracer",
            [i.display_name for i in traceable],
            key="traced_indicator",
            disabled=not traceable,
            help=None if traceable else "Aucune série mensuelle renseignée sur cet onglet.",
        )
    else:
        explored_sheet, sheet_indicators, traceable, traced_name = None, [], [], None
        only_filled = False

st.subheader("🔍 Tous les indicateurs")

if not all_indicators:
    st.caption("Aucune structure de tableau détectée dans les fichiers chargés.")
else:
    n_filled = sum(1 for i in all_indicators if i.has_data)
    st.caption(
        f"{len(all_indicators)} lignes de tableau détectées automatiquement dans "
        f"{len(sheets_with_indicators)} onglet(s), dont {n_filled} renseignée(s) — "
        f"onglet affiché : **{explored_sheet}**."
    )

    shown = [i for i in sheet_indicators if i.has_data] if only_filled else sheet_indicators
    detail_rows = []
    for ind in shown:
        marker = "●" if ind.has_data else "○"
        for measure in ind.measures:
            per_inst, total = indicator_totals(institution_objs, ind, measure)
            row = {
                "Tableau": ind.rubric or "—",
                "Indicateur": f"{marker} {ind.display_name}",
                "Mesure": measure or "Valeur",
            }
            for name, value in per_inst:
                row[name] = _fmt(value)
            row["Total marché"] = _fmt(total)
            detail_rows.append(row)

    if detail_rows:
        detail_df = pd.DataFrame(detail_rows).set_index(["Tableau", "Indicateur", "Mesure"]).astype(str)
        st.dataframe(detail_df, width="stretch", height=460)
        legend = "● ligne renseignée · ○ ligne prévue par le gabarit mais non renseignée"
        if sheet_indicators and sheet_indicators[0].is_monthly:
            legend += " — les indicateurs mensuels affichent le dernier mois renseigné"
        st.caption(legend)
    else:
        st.caption("Aucune ligne à afficher avec le filtre actuel.")

    # Courbe d'un indicateur mensuel au choix
    if traceable and traced_name:
        traced = next(i for i in traceable if i.display_name == traced_name)
        for measure in traced.measures:
            series = indicator_series(institution_objs, traced, measure)
            if not series or all(v == 0 for _, vals in series for v in vals.values()):
                continue
            chart_rows = []
            for period, values in series:
                for inst_name, value in values.items():
                    chart_rows.append({
                        "Mois": period.strftime("%Y-%m"),
                        "Établissement": inst_name,
                        "Valeur": value,
                    })
            chart_df = pd.DataFrame(chart_rows)
            fig_ind = _px().line(chart_df, x="Mois", y="Valeur", color="Établissement", markers=True)
            fig_ind.update_layout(
                height=320, margin=dict(l=0, r=0, t=30, b=0), legend_title_text="",
                title=f"{traced.display_name} — {measure or 'Valeur'}",
            )
            st.plotly_chart(fig_ind, width="stretch")

# ---------------------------------------------------------------------------
# Évolution par pays (remplace l'Historique multi-période, retiré)
#
# Réutilise le même indicateur que celui choisi juste au-dessus pour le
# tracé par établissement (« Indicateur à tracer », sidebar 2) — plutôt que
# d'ajouter un second menu déroulant redondant, l'utilisateur choisit une
# fois, et voit les deux angles : par établissement, puis par pays.
# ---------------------------------------------------------------------------
st.subheader("🌍 Évolution par pays")

pays_presents = sorted({i.pays for i in institution_objs if i.pays}, key=lambda c: NOM_PAYS.get(c, c))
if not pays_presents:
    st.caption("Aucun pays détecté sur les établissements chargés — l'évolution par pays "
               "apparaîtra dès qu'au moins un établissement aura un pays renseigné.")
elif not (traceable and traced_name):
    repartition = repartition_par_pays_et_rubrique(institution_objs, explored_sheet) if explored_sheet else []
    if not repartition:
        st.caption("Aucune donnée exploitable pour une répartition par pays sur cet onglet.")
    else:
        # Sur demande explicite : un thème sans évolution mensuelle à
        # tracer (chèques&VIR, Cartes, PrêtsCredits…) montre plutôt une
        # répartition — par pays, et par rubrique (chèques&VIR : Chèques,
        # Virements, Prélèvements, Effets de commerce, Retraits manuels).
        # Le sélecteur permet d'entrer dans le détail de chaque rubrique,
        # « ses détails » demandés explicitement.
        options_rubrique = ["Toutes les rubriques (ensemble du thème)"] + [r for r, _ in repartition]
        rubrique_choisie = st.selectbox(
            "Rubrique à explorer", options_rubrique, key=f"rubrique_{explored_sheet}",
        )
        mesure_choisie = st.radio(
            "Mesure", ["Nombre", "Montant (XAF)"], horizontal=True, key=f"mesure_{explored_sheet}",
        )
        cle_mesure = "Nombre" if mesure_choisie == "Nombre" else "Montant"

        def _agreger_par_pays(rubriques_a_sommer):
            totaux: dict[str, float] = {}
            for _, par_pays in rubriques_a_sommer:
                for code, vals in par_pays.items():
                    totaux[code] = totaux.get(code, 0) + vals[cle_mesure]
            return totaux

        col_pays, col_rubrique = st.columns(2)

        if rubrique_choisie == options_rubrique[0]:
            totaux_pays = _agreger_par_pays(repartition)
            titre_pays = f"{explored_sheet} — {mesure_choisie} par pays (toutes rubriques)"
        else:
            rubriques_filtrees = [(r, p) for r, p in repartition if r == rubrique_choisie]
            totaux_pays = _agreger_par_pays(rubriques_filtrees)
            titre_pays = f"{rubrique_choisie} — {mesure_choisie} par pays"

        if totaux_pays:
            df_pays = pd.DataFrame([
                {"Pays": NOM_PAYS.get(c, c), mesure_choisie: v} for c, v in totaux_pays.items() if v
            ])
        else:
            df_pays = pd.DataFrame()

        if not df_pays.empty:
            fig1 = _px().pie(df_pays, names="Pays", values=mesure_choisie, hole=0.35, title=titre_pays)
            fig1.update_traces(textinfo="label+percent", hovertemplate="%{label} : %{value:,.0f}<extra></extra>")
            fig1.update_layout(height=380, margin=dict(l=0, r=0, t=40, b=0))
            col_pays.plotly_chart(fig1, width="stretch")
        else:
            col_pays.caption("Rien à représenter pour cette sélection "
                            f"(« {mesure_choisie} » n'est pas renseigné pour ce thème).")

        # Second camembert, uniquement en vue d'ensemble : la répartition
        # ENTRE les rubriques elles-mêmes (toutes zones/pays confondus) —
        # « virement avec ses détails, prélèvements avec ses détails… ».
        if rubrique_choisie == options_rubrique[0]:
            totaux_rubriques = {r: sum(v[cle_mesure] for v in par_pays.values())
                               for r, par_pays in repartition}
            df_rubriques = pd.DataFrame([
                {"Rubrique": r, mesure_choisie: v} for r, v in totaux_rubriques.items() if v
            ])
            if not df_rubriques.empty:
                fig2 = _px().pie(df_rubriques, names="Rubrique", values=mesure_choisie, hole=0.35,
                                 title=f"{explored_sheet} — {mesure_choisie} par rubrique (tous pays)")
                fig2.update_traces(textinfo="label+percent",
                                   hovertemplate="%{label} : %{value:,.0f}<extra></extra>")
                fig2.update_layout(height=380, margin=dict(l=0, r=0, t=40, b=0))
                col_rubrique.plotly_chart(fig2, width="stretch")
            else:
                col_rubrique.caption("Rien à représenter pour cette sélection.")
        else:
            col_rubrique.caption(
                f"« {rubrique_choisie} » sélectionnée : le camembert par rubrique n'a de sens "
                f"qu'en vue d'ensemble. Choisissez « Toutes les rubriques » pour le voir."
            )

        # Répartition par RÉSEAU de carte (GIMAC, VISA…) — une information
        # normalement fondue dans le thème consolidé (« Cartes 2 GIMAC » +
        # « Cartes 2 VISA » sont additionnés en un seul « Cartes 2 » lors
        # de la fusion), et donc invisible sans cette reconstitution.
        # Exploite les onglets sources bruts, jamais la consolidation
        # elle-même : aucun risque de perturber ce qui est déjà vérifié.
        fichiers_bruts = [(i["file_name"], i["raw"], i.get("pays")) for i in institutions if not i["error"]]
        repartition_reseau = repartition_par_reseau(fichiers_bruts, explored_sheet) if explored_sheet else []
        if repartition_reseau:
            st.markdown(f"**{explored_sheet} — répartition par réseau de carte**")
            totaux_reseau = {reseau: sum(v[cle_mesure] for v in par_pays.values())
                            for reseau, par_pays in repartition_reseau}
            df_reseau = pd.DataFrame([
                {"Réseau": r, mesure_choisie: v} for r, v in totaux_reseau.items() if v
            ])
            if not df_reseau.empty:
                fig3 = _px().pie(df_reseau, names="Réseau", values=mesure_choisie, hole=0.35,
                                 title=f"{explored_sheet} — {mesure_choisie} par réseau (tous pays)")
                fig3.update_traces(textinfo="label+percent",
                                   hovertemplate="%{label} : %{value:,.0f}<extra></extra>")
                fig3.update_layout(height=380, margin=dict(l=0, r=0, t=40, b=0))
                st.plotly_chart(fig3, width="stretch")
            st.caption(
                "Reconstitué à partir des onglets sources par réseau (ex. « Cartes 2 GIMAC », "
                "« Cartes 2 VISA ») — une information normalement fondue dans le total consolidé "
                "ci-dessus, et donc invisible sans cette vue dédiée."
            )
else:
    traced = next(i for i in traceable if i.display_name == traced_name)
    trace_dessinee = False
    for measure in traced.measures:
        series = indicator_series(institution_objs, traced, measure)
        if not series or all(v == 0 for _, vals in series for v in vals.values()):
            continue
        par_nom_inst = {i.name: i.pays for i in institution_objs}
        chart_rows = []
        for period, values in series:
            totaux_pays = {}
            for inst_name, value in values.items():
                code = par_nom_inst.get(inst_name)
                if code:
                    totaux_pays[code] = totaux_pays.get(code, 0) + value
            for code, total in totaux_pays.items():
                chart_rows.append({
                    "Mois": period.strftime("%Y-%m"),
                    "Pays": NOM_PAYS.get(code, code),
                    "Valeur": total,
                })
        if not chart_rows:
            continue
        trace_dessinee = True
        chart_df = pd.DataFrame(chart_rows)
        fig_pays = _px().line(chart_df, x="Mois", y="Valeur", color="Pays", markers=True)
        fig_pays.update_layout(
            height=360, margin=dict(l=0, r=0, t=30, b=0), legend_title_text="",
            title=f"{traced.display_name} — {measure or 'Valeur'}, par pays",
        )
        st.plotly_chart(fig_pays, width="stretch")
    if not trace_dessinee:
        st.caption("Aucune série mensuelle exploitable pour cet indicateur avec les pays actuellement renseignés.")

# ---------------------------------------------------------------------------
# Contrôle qualité (Phase 5)
# ---------------------------------------------------------------------------
quality_flags = run_quality_checks(institution_objs, kpis, gab)

if quality_flags:
    st.subheader("⚠️ Points de vigilance")
    missing_label_flags = [f for f in quality_flags if f.kind == "libelle_introuvable"]
    error_flags = [f for f in quality_flags if f.kind == "erreur_formule"]
    info_flags = [f for f in quality_flags if f.kind == "onglet_vide"]
    text_number_flags = [f for f in quality_flags if f.kind == "nombre_en_texte"]
    non_reconnu_flags = [f for f in quality_flags if f.kind == "onglet_non_reconnu"]

    # Priorité d'affichage : un libellé introuvable fausse silencieusement un
    # indicateur (valeur affichée à 0), c'est l'anomalie la plus grave.
    for f in missing_label_flags:
        st.error(f"🛑 {f.message}")

    for f in error_flags:
        with st.expander(f"🔴 {f.message}"):
            for e in f.details:
                st.write(f"Cellule {e['addr']} — erreur source : {e['text']}")

    for f in text_number_flags:
        with st.expander(f"🟠 {f.message}"):
            for t in f.details[:40]:
                st.write(f"Cellule {t['addr']} — saisi « {t['original']} » → lu {t['parsed']:,.0f}".replace(",", " "))
            if len(f.details) > 40:
                st.caption(f"… et {len(f.details) - 40} autres cellules.")

    for f in non_reconnu_flags:
        st.warning(f"⚠️ {f.message}")

    for f in info_flags:
        st.info(f"ℹ️ {f.message}")

# ---------------------------------------------------------------------------
# SIDEBAR — 4. Options d'affichage (Aperçu des onglets)
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### 3. Exports")

    # Les deux classeurs coûtent plusieurs secondes à produire (davantage
    # avec beaucoup d'établissements). Les générer à chaque exécution du
    # script — donc à CHAQUE clic, sélection ou validation — rendait toute
    # l'application lente, alors que l'utilisateur ne télécharge qu'à la
    # fin. Ils ne sont donc construits que sur demande explicite, puis
    # conservés jusqu'à la prochaine modification des données.
    signature = (
        tuple((i.name, i.file_name, i.pays, tuple(sorted(i.sheets))) for i in institution_objs),
        len(cartographie.entrees),
    )
    if st.session_state.get("exports_signature") != signature:
        st.session_state.pop("exports_prets", None)

    if "exports_prets" not in st.session_state:
        if st.button("📦 Préparer les exports", width="stretch"):
            with st.spinner("Génération des deux classeurs…"):
                resume_buf = io.BytesIO()
                build_resume_workbook(institution_objs, kpis, gab, cartographie=cartographie).save(resume_buf)
                resume_bytes = resume_buf.getvalue()

                full_buf = io.BytesIO()
                build_full_workbook(institution_objs, cartographie=cartographie).save(full_buf)
                full_bytes = full_buf.getvalue()

                st.session_state["exports_prets"] = (resume_bytes, full_bytes)
                st.session_state["exports_signature"] = signature
            st.rerun()
        st.caption("Les fichiers sont produits à la demande : l'application reste fluide "
                   "pendant que vous chargez et vérifiez vos liasses.")
    else:
        resume_bytes, full_bytes = st.session_state["exports_prets"]
        st.download_button(
            "⬇️ Résumé (.xlsx)",
            data=resume_bytes,
            file_name="Resume_Marche_Paiements.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
        )
        st.download_button(
            "⬇️ Fichier complet (.xlsx)",
            data=full_bytes,
            file_name="Synthese_Marche_Paiements_Complete.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
        )
        st.caption("Le fichier complet contient un onglet par établissement + un onglet Total par thème, avec formules natives.")
