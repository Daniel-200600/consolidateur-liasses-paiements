# Consolidateur de liasses statistiques de paiements (BEAC)

Application Python/Streamlit, 100 % locale, pour consolider un nombre
variable de liasses statistiques de paiements. Voir le Cahier des charges
pour le détail des règles de gestion et le plan de réalisation par phases,
et **GUIDE_UTILISATEUR.md** pour la prise en main et le dépannage courant.

## Interface

Toutes les options (dépôt de fichiers, gestion des établissements,
sélections d'affichage, exports) sont regroupées dans la **barre latérale**.
La zone principale n'affiche que les résultats. Thème vert émeraude / or
défini nativement dans `.streamlit/config.toml`.

## Installation

```bash
python -m venv venv
source venv/bin/activate      # Windows : venv\Scripts\activate
pip install -r requirements.txt
```

## Lancer l'application

```bash
streamlit run app.py
```

## Lancer les tests

Depuis le dossier `consolidateur/` :

```bash
python -m pytest tests
```

295 tests, exécutés par le CI GitHub à chaque push. Plusieurs simulent un
vrai dépôt de fichiers dans l'application via `streamlit.testing.v1.AppTest`,
d'autres recalculent réellement les fichiers Excel exportés avec LibreOffice
pour garantir l'absence d'erreur de formule (`tests/libreoffice_recalc.py` ;
ces tests sont ignorés si LibreOffice n'est pas installé).

Les tests s'appuient uniquement sur deux **liasses fictives**
(`tests/fixtures_fictives/`, voir le README de ce dossier). Les tests qui
portent sur de vraies liasses reçues restent locaux : ils vivent dans
`tests/donnees_reelles/` et lisent `tests/fixtures/`, deux dossiers exclus
de Git.

## Données persistantes

L'historique multi-période est stocké dans `~/.consolidateur-liasses/historique.csv`,
**hors du dossier de l'application**, pour survivre au remplacement du dossier
par une nouvelle version. Surchargeable via la variable d'environnement
`CONSOLIDATEUR_HISTORIQUE`.

## Détection automatique des indicateurs

La lecture des liasses ne repose plus sur une liste d'indicateurs codée en
dur : `core/indicators.py` parcourt chaque onglet et expose toute ligne
porteuse de données (45 sur les fichiers de référence, contre 8 auparavant).
Les indicateurs sont identifiés par leur POSITION dans le gabarit, identique
d'un établissement à l'autre — plus robuste qu'une recherche de libellé.

## Reconnaissance de familles d'onglets

`core/sheet_matching.py` reconnaît qu'un onglet dont le nom diffère du
gabarit connu (« Cartes 2 GIMAC », « WESTERN UNION »…) lui appartient tout
de même, si sa structure interne concorde substantiellement — par
alignement de séquence (tolérant aux lignes insérées/supprimées), jamais
sur la seule foi du nom. Les variantes reconnues sont sommées cellule à
cellule dans le thème correspondant. Un onglet qui ne correspond à rien de
connu n'est jamais deviné à l'aveugle : il reste visible (barre latérale,
panneau qualité, exports) pour un rattachement manuel.

Deux passes de reconnaissance : empreinte ligne entière (variantes de
même disposition — réseau, système), puis empreinte libellés seuls
(variantes qui déclinent un thème statique sous forme MENSUELLE, comme
Mobile Money — le dernier mois renseigné est alors extrait automatiquement,
cf. `extraire_derniere_periode`). Un onglet reconnu avec une confiance
insuffisante pour une consolidation automatique devient une proposition
validable en un clic (`core/calibration.py`), mémorisée hors du dossier
projet pour ne plus jamais être redemandée.

Validé sur 8 fichiers réels d'établissements du Cameroun
(`tests/fixtures/cameroun/`), avec deux garde-fous anti-faux-positif
découverts et corrigés grâce à ces mêmes fichiers : un ratio de taille
(onglet composite regroupant plusieurs thèmes) et une détection
d'ambiguïté (deux thèmes structurellement trop proches pour trancher sans
un coup d'œil, ex. Transfert d'argent vs MobileMoney3).

## Regroupement par pays (CEMAC)

`core.parsing.clean_institution_name` ignore désormais tout segment du nom
de fichier reconnu comme code pays (cf. core.pays), quelle que soit sa
position — cas réel corrigé : un fichier nommé « CF-BanqueXYZ_Liasse_… »
faisait retenir « CF » comme nom d'établissement, et plusieurs fichiers
ainsi nommés produisaient une colonne de Sommaire absurde une fois
désambiguïsés par suffixe (« CF », « CF (2) »…).

`core/pays.py` détecte automatiquement le pays d'un établissement (les 6
pays de la CEMAC) depuis le nom de son fichier, en couvrant plusieurs
codages possibles pour un même pays (constaté sur des fichiers réels : «
CA » et « RCA » désignent tous deux la Centrafrique). Toujours modifiable
en un clic dans la barre latérale.

Chaque export ajoute une dimension pays :
- **Fichier complet** : un onglet Total par pays, en plus du Total CEMAC,
  pour chacun des 11 thèmes.
- **Résumé** ET **Sommaire du fichier complet** : un tableau simple,
  « Pays / Montant total (XAF) » — `core/montant_total.py` additionne les
  principaux flux monétaires du gabarit sans double comptage (vérifié sur
  deux pièges réels : des totaux de tête qui recouvraient déjà leurs
  propres sous-totaux, et des totaux de tête laissés vides alors que leurs
  composantes étaient renseignées). Une composante au saut mensuel
  invraisemblable (facteur >15 d'un mois à l'autre) est exclue du total et
  signalée, jamais silencieusement incluse — découvert sur un cas réel
  dans les fichiers de référence.

## Garde-fou de période

`annees_mentionnees()` lit la période d'un onglet dans son titre. Un onglet
portant sur un exercice antérieur à celui du classeur est écarté du
rattachement automatique : il ressemble au gabarit à plus de 90 % (c'est le
même formulaire), et le consolider mélangerait deux périodes en silence.
Découvert sur un fichier réel contenant des onglets 2022 renseignés au
milieu d'un classeur 2025-2026.

## Généralisation

`tests/test_generalisation.py` vérifie sur des fichiers **entièrement
synthétiques** (noms d'établissement, d'onglets et de libellés jamais vus
ailleurs) que la reconnaissance ne dépend d'aucun nom connu — seule la
structure guide la décision, toujours avec la même prudence (piste
vérifiable, jamais un forçage) qu'avec les fichiers réels.

## Performance

Démarrage optimisé (~2 s) : plotly est importé au premier affichage de
graphique plutôt qu'au lancement, le surveillant de fichiers est désactivé,
et les polices sont désormais celles du système — les versions précédentes
les téléchargeaient depuis fonts.googleapis.com à chaque démarrage, ce qui
retardait l'affichage et contredisait le principe « rien ne quitte le
poste ». Les deux classeurs d'export sont produits à la demande.

## Conflit de période entre onglets composites

`core.sheet_matching.detecter_periode_declaree` lit une déclaration
explicite (« Période : du DD/MM/YYYY au DD/MM/YYYY »), tolérante à un jour
hors plage (cas réel : « 31/06 », juin n'a que 30 jours). Quand DEUX
onglets composites validés couvrent des périodes différentes pour le même
thème (cas réel : « Cartes_2025 » et « Cartes_2026 » d'un même
établissement — la même clientèle à deux dates, pas deux catégories à
additionner), seule la période la plus récente est retenue dans le total ;
l'autre reste visible, marquée `periode_revolue`, jamais silencieusement
doublée ni perdue.

## Nom d'établissement : le fichier uploadé, sans transformation

Sur demande explicite de l'utilisateur (après deux cas réels de mauvais
étiquetage automatique — un code pays, puis un établissement réel affiché
sous un autre nom), le nom d'établissement proposé par défaut est
désormais **toujours le nom du fichier tel qu'uploadé** (sans extension),
plus jamais deviné ni transformé. `clean_institution_name` et
`nom_declare` restent disponibles dans `core/parsing.py` (et testées) mais
ne sont plus appelées par défaut dans `app.py`. Le champ reste modifiable
en un clic, comme toujours.

## Aucun logo ni filigrane dans les exports

Le dépôt ne contient aucune image institutionnelle. La fonction
`core.export_background.apply_background_to_bytes` (fond de feuille Excel)
reste disponible mais n'est appelée nulle part par défaut ; l'appelant
fournit sa propre image s'il en veut une.

## Réaudit complet du montant total (5 catégories retrouvées)

Un signalement de l'utilisateur soupçonnant des erreurs de calcul a motivé
un réaudit exhaustif des 11 thèmes contre les fichiers réels, ligne par
ligne. Trouvé et corrigé :
- **Prélèvements** et **Retraits manuels**, deux rubriques entières de
  chèques&VIR absentes du calcul (plusieurs milliers de milliards de XAF
  chez un seul établissement) ;
- **PrêtsCredits**, thème entier absent — seul tableau du gabarit à
  nombre de lignes variable (un prêt par ligne), sommé différemment des
  autres (14,5 Md XAF chez un seul établissement, jusqu'à 3 820 lignes) ;
- un nouveau contrôle qualité (`check_totaux_incoherents`) qui compare
  chaque total de tête à la somme de ses propres sous-zones et signale
  tout écart — sans jamais recalculer à la place de l'établissement.

## Contrôle de période

`core.sheet_matching.annees_mentionnees` compare l'année déclarée par un
onglet à la période couverte par le reste du classeur. Un onglet nettement
antérieur (cas réel : des onglets d'un exercice 2022 laissés dans un fichier
2025-2026, ressemblant au gabarit à plus de 90 %) est marqué
`periode_revolue` et jamais proposé au rattachement — ses montants ne
peuvent donc pas se mélanger à ceux de la période courante.

## Généralisation

`tests/test_generalisation.py` vérifie sur des fichiers **entièrement
synthétiques** (noms d'établissement, d'onglets et de libellés jamais vus
ailleurs) que la reconnaissance ne dépend d'aucun nom connu — seule la
structure guide la décision, toujours avec la même prudence (piste
vérifiable, jamais un forçage) qu'avec les fichiers réels.

## Performance

Deux causes de lenteur mesurées et corrigées, verrouillées par des tests
structurels (`tests/test_tracabilite.py`) :
- le classeur était lu **trois fois** au chargement (bloc dupliqué) — une
  seule lecture désormais ;
- openpyxl recalcule une empreinte de l'objet style à chaque affectation
  `cell.font = …` : sur des dizaines de milliers de cellules, c'était le
  premier poste de temps de génération. Les styles de grille sont désormais
  des `NamedStyle`, hachés une seule fois par classeur.

Génération des deux exports (10 établissements) : **16,6 s → 9,3 s**.

## Onglets composites et hors gabarit

Un onglet regroupant plusieurs thèmes du gabarit (ex. Cartes1 à Cartes 5
assemblées en une seule feuille maison) est automatiquement **segmenté** :
chaque portion est localisée et rattachée à son propre thème, validable en
un seul clic pour l'ensemble. Un décalage systématique de colonnes entre
l'établissement et le gabarit officiel est détecté et corrigé à la volée.

Un onglet qui ne correspond à rien de connu, même partiellement, n'est
jamais omis des documents livrés : il apparaît individuellement dans le
fichier complet (onglet ambre) et est référencé dans le Sommaire et le
résumé, même s'il ne peut pas être additionné aux totaux d'un autre
établissement.

## IA locale (facultative)

`core/llm.py` et `core/cartographie.py` permettent à un modèle servi par
Ollama (par défaut `gemma3:1b`) de qualifier la nature des lignes du gabarit
— titre, donnée, en-tête, note. Seuls des libellés lui sont transmis, jamais
de montants, et il n'intervient dans aucun calcul. La cartographie est
relue puis validée par l'utilisateur, enregistrée hors du dossier projet, et
réutilisée ensuite sans nouvel appel au modèle.

Vérification de l'installation : `python verifier_ollama.py`

## État d'avancement

- [x] Phase 1 — Cadrage (cahier des charges)
- [x] Phase 2 — Socle technique (import multi-fichiers + affichage brut)
- [x] Phase 3 — Moteur de consolidation (Total marché pour les 11 onglets)
- [x] Phase 5 — Contrôle qualité (erreurs de formule + onglets vides)
- [x] Phase 7 — Exports Excel (résumé + complet, formules natives, 0 erreur au recalcul)
- [x] Phase 8 — Tests et documentation
- [x] Phase 9 — Historisation multi-période (enregistrement CSV automatique, variations et courbe d'évolution)



## Refonte majeure (sur demande explicite de l'utilisateur)

- **Barre latérale réduite à 3 sections** : Fichiers, Indicateurs détaillés,
  Exports. Gabarit (IA locale), Historique et Affichage retirés.
- **Indicateurs clés resserrés** : 21 lignes → 10, regroupées par grande
  famille d'activité (`core.montant_total.composantes_par_categorie`) —
  moins d'indicateurs, chacun plus représentatif. Concordance exacte
  vérifiée avec le détail complet (toujours disponible dans les exports).
- **Évolution par pays** (remplace l'Historique) : graphique multi-lignes
  par pays, réutilisant le sélecteur d'indicateur déjà existant plutôt
  qu'un second menu déroulant.
- **Analyse qualitative** en fin de chaque onglet Total par pays du fichier
  complet : établissement dominant, couverture, anomalies détectées.
- **Aucun fichier n'est plus jamais rejeté** : un fichier sans onglet
  reconnu était auparavant exclu de la consolidation, et son contenu réel
  (`non_reconnus`) était perdu — corrigé.
- **Rapprochement entre établissements** (`core.sheet_matching.
  rapprocher_onglets_non_reconnus`) : détecte les onglets hors gabarit
  structurellement proches entre établissements DIFFÉRENTS (jamais au sein
  d'un même établissement) — cas réel trouvé et vérifié : MTN et
  FIRSTTRUST déposent chacun un onglet « Prêts/Crédits » orthographié
  différemment du gabarit officiel, jamais reconnu automatiquement mais
  structurellement le même motif.

## Rattachement automatique (sur demande explicite de l'utilisateur)

Toute piste plausible sur un onglet non reconnu — proposition forte, piste
faible, ou segments d'un onglet composite — est désormais validée
automatiquement dès l'upload, sans clic. Seule exception : un onglet
d'une période révolue n'est jamais rattaché automatiquement (le
consolider mélangerait les montants de deux périodes différentes).

Un garde-fou déjà en place (`detecter_periode_declaree`) protège aussi
contre un piège voisin : deux onglets composites du même établissement
couvrant des périodes CONSÉCUTIVES mais non révolues (ex. « Cartes_2025 »
et « Cartes_2026 ») ne sont jamais additionnés — seule la période la plus
récente est retenue, l'autre reste listée hors gabarit. Sans ce garde-fou,
une figure de stock (nombre de clients) aurait été doublement comptée.

## Barre latérale simplifiée

Sur demande explicite : plus de champ de nom éditable, plus de menu
détaillé par onglet non reconnu (devenu inutile avec le rattachement
automatique). Chaque établissement tient sur une seule ligne compacte
(nom + pays + retrait). Un unique message de synthèse remplace le détail
par fichier quand des onglets restent hors gabarit.

## Correction du graphique « Évolution par pays »

L'onglet sélectionné par défaut pour le traçage (`explored_sheet`)
pointait vers le premier thème du gabarit (chèques&VIR), qui n'a pas de
disposition mensuelle — le graphique restait donc vide jusqu'à ce que
l'utilisateur change lui-même la sélection, sans que ce soit visible
comme un problème de sélection plutôt qu'une vraie absence de données.
Corrigé : le défaut pointe désormais vers le premier onglet réellement
traçable.

## Camemberts interactifs pour les thèmes non mensuels (sur demande explicite)

Un thème sans disposition mensuelle (chèques&VIR, Transfert d'argent,
MobileMoney2/3, Cartes 2/4/5, Cartes1, PrêtsCredits) montre désormais, dans
la section « Évolution par pays » de l'application, deux camemberts
Plotly interactifs plutôt qu'un message d'attente :
- répartition **par pays**, pour la rubrique sélectionnée (ou l'ensemble
  du thème) ;
- répartition **par rubrique** (Chèques, Virements, Prélèvements, Effets
  de commerce, Retraits manuels pour chèques&VIR), tous pays confondus.

Un sélecteur de rubrique permet d'entrer dans le détail de chacune
(« ses détails », demandé explicitement), et une bascule Nombre/Montant.
`core.montant_total.repartition_par_pays_et_rubrique` réutilise les mêmes
lignes déjà vérifiées que le montant total par pays (jamais de double
comptage), plus deux cas particuliers ajoutés pour la couverture : Cartes1
(thème exclusivement compté, réutilise les indicateurs déjà fiabilisés de
compute_kpis) et PrêtsCredits (tableau à lignes variables, comptage et
somme dédiés).

Un vrai bug trouvé et corrigé en construisant cette fonctionnalité :
Plotly plantait quand toutes les valeurs d'une mesure étaient à zéro après
filtrage (DataFrame vide sans les colonnes attendues) — reproduit sur
Cartes1 + Montant (thème purement compté, aucune colonne Montant),
verrouillé par test.

## Autres corrections (sur demande explicite)

- **Logo retiré** des deux exports.
- **Feuilles vides ou au nom générique Excel** (« Sheet1 », « Feuil2 »…)
  sans contenu substantiel : ignorées entièrement, ni consolidées ni
  listées hors gabarit.
- **Ligne « Établissements consolidés »** retirée des deux exports — plus
  rien concernant les fichiers individuellement.
- **Navigation du résumé réparée** : le gel de volets figeait jusqu'à 61
  lignes sur un document de plusieurs milliers, remplissant tout l'écran
  visible. Réduit à la seule colonne A, comme partout ailleurs.

## Barre latérale — retrait complet (pas un allègement)

Sur clarification explicite de l'utilisateur : plus AUCUNE information ni
contrôle individuel par fichier dans la barre latérale (ni nom, ni pays,
ni bouton de retrait dédié). L'architecture dérive `institutions`
directement de l'uploader natif à chaque exécution (`_parser_avec_cache`,
mis en cache par identifiant de fichier) — retirer un fichier se fait via
la croix native du composant d'upload, plus besoin d'aucun bouton
construit à la main.

Un vrai bug trouvé en vérifiant cette nouvelle architecture : déposer deux
fois le même fichier (même nom, même taille) doublait silencieusement
tous les totaux. Corrigé par une déduplication explicite par identifiant
de fichier avant construction de la liste des établissements.

## Second bug majeur trouvé : repli profond manquant à deux endroits

Le repli à deux niveaux (introduit pour corriger le total de ETABB, resté
à zéro malgré 7,25 Md XAF de vraie activité) n'avait été appliqué qu'à
`_calculer_composantes` — `repartition_par_pays_et_rubrique` en était
resté dépourvue, produisant un vrai désaccord entre le tableau
« Indicateurs clés » (corrigé) et les camemberts par pays/rubrique
(encore à zéro pour les mêmes établissements). Aligné, verrouillé par
test.

## Répartition par réseau de carte (VISA, GIMAC…)

Un troisième camembert apparaît désormais pour les thèmes Cartes qui
segmentent par réseau dans le fichier source (« Cartes 2 GIMAC »,
« Cartes 2 VISA »…) — une information normalement FONDUE dans le thème
consolidé (additionnée en un seul total lors de la fusion), reconstituée
en ré-analysant structurellement chaque onglet source portant un nom de
réseau connu (`core.montant_total.repartition_par_reseau`), sans jamais
toucher à la consolidation principale déjà vérifiée.

## Audit exhaustif final

Après les deux découvertes de repli manquant, un balayage systématique sur
les 10 fichiers réels et les 17 composantes a été mené pour vérifier qu'il
n'en restait aucune autre. Trouvé et corrigé un troisième point
d'incohérence : l'analyse qualitative des exports (`_analyse_qualitative_pays`)
ne vérifiait les anomalies mensuelles qu'aux deux premiers niveaux de
repli, jamais le troisième — aligné avec les 3 fonctions de calcul qui,
elles, l'utilisaient déjà toutes.

14 cas restants signalés par le balayage automatique ont été vérifiés
individuellement (Prélèvements, Mobile Money — retraits/paiements, Cartes
— TPE bloc 2) : tous confirmés comme de vrais zéros (aucune donnée cachée),
pas des bugs — le balayage lui-même comptait toute donnée numérique
présente n'importe où sur la feuille source, pas seulement celle liée à
la composante concernée.