# Guide utilisateur — Consolidateur de liasses statistiques de paiements

Ce guide permet de prendre l'application en main sans assistance, du premier
lancement à l'export des fichiers Excel.

## 1. Premier lancement

```
cd consolidateur
python -m venv venv
venv\Scripts\activate          # macOS/Linux : source venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Le navigateur s'ouvre automatiquement sur `http://localhost:8501`. Si ce
n'est pas le cas, ouvre cette adresse toi-même.

**Important : ces commandes doivent être exécutées depuis le dossier
`consolidateur` lui-même** (celui qui contient `app.py`), pas depuis son
dossier parent. Si `pip install` ou `streamlit run` renvoie une erreur du
type *"No such file or directory"*, tape `cd consolidateur` puis réessaie.

## 2. Interface

Toutes les commandes vivent dans la **barre latérale gauche** (fond vert
émeraude) :
1. **Fichiers** — dépôt des liasses, renommage et retrait des établissements
2. **Indicateurs détaillés** — onglet à explorer et indicateur à tracer
3. **Gabarit (IA locale)** — cartographie assistée, facultative
4. **Historique** — choix de l'indicateur à suivre dans le temps
5. **Affichage** — établissement/onglet à afficher dans l'aperçu détaillé
6. **Exports** — les deux boutons de téléchargement

La zone principale n'affiche que des résultats : tableaux, graphiques et
alertes. Le thème (vert émeraude / or) est défini nativement dans
`.streamlit/config.toml` — pour l'ajuster, modifie les couleurs hexadécimales
dans ce fichier (pas besoin de toucher au code).

## 3. Utilisation courante

1. **Dépose tes fichiers** dans la barre latérale (section « 1. Fichiers ») —
   un nombre quelconque de liasses `.xlsx`, glissées en une seule fois ou
   ajoutées au fur et à mesure.
2. **Vérifie/renomme chaque établissement** dans le champ texte juste en
   dessous. Le nom proposé par défaut vient du nom de fichier.
3. Consulte le **tableau des indicateurs clés** et les **deux graphiques**
   (part de marché, évolution mensuelle Mobile Money).
4. Vérifie le panneau **« Points de vigilance »** s'il apparaît : il signale
   les onglets non renseignés par un établissement et les éventuelles
   erreurs de formule présentes dans un fichier source. Ces alertes
   n'empêchent jamais de continuer.
5. **Télécharge** le résumé ou le fichier complet via les deux boutons en
   bas de la barre latérale (section « 5. Exports »).
6. Pour changer de jeu de fichiers, clique sur **« Retirer »** à côté d'un
   établissement, ou dépose simplement de nouveaux fichiers.

## 4. Tous les indicateurs (détection automatique)

Le gabarit BEAC contient bien plus que les 8 indicateurs de synthèse. La
section « 🔍 Tous les indicateurs » expose **toute ligne porteuse de
données**, détectée automatiquement — 45 indicateurs sur les liasses de
référence, contre 8 auparavant.

- Choisis l'onglet à explorer dans la barre latérale (section « 2. Indicateurs
  détaillés ») : le tableau affiche chaque ligne, chaque mesure
  (Nombre / Valeur), par établissement et en total marché.
- Pour les onglets mensuels, choisis un indicateur à tracer : sa courbe
  d'évolution s'affiche sous le tableau.
- Les libellés qui se répètent dans plusieurs sections d'un même onglet
  (« Retrait GAB » apparaît 4 fois dans Cartes 5) sont préfixés par leur
  section pour lever toute ambiguïté.

Aucune liste n'est codée en dur : si la BEAC ajoute des lignes au gabarit,
elles apparaîtront d'elles-mêmes.

## 5. Cartographie du gabarit assistée par IA locale (facultatif)

La lecture des liasses repose sur des règles automatiques (proportion de
majuscules, proximité d'un en-tête de colonnes…). Elles fonctionnent, mais
restent sensibles à une variante de mise en page. Un modèle de langage
tournant **sur votre machine** peut fiabiliser cette lecture.

### Prérequis
Ollama installé et démarré, avec un modèle :
```
ollama serve
ollama pull gemma3:1b
```

Vérifiez que tout répond avant d'utiliser l'application :
```
python verifier_ollama.py --modele gemma3:1b
```

### Utilisation
1. Chargez vos liasses, puis ouvrez « 3. Gabarit (IA locale) » dans la barre
   latérale.
2. Cliquez sur **Analyser le gabarit**. Environ 290 libellés sont soumis au
   modèle ; comptez quelques minutes selon votre machine.
3. L'écran affiche les **désaccords** entre les règles actuelles et le
   modèle — ce sont les seuls cas où la validation changera quelque chose.
4. Relisez-les, puis **Valider** ou **Abandonner**.

Une fois validée, la cartographie est enregistrée dans
`~/.consolidateur-liasses/cartographie.json` et réutilisée à chaque
exécution : le modèle n'est plus sollicité, et les résultats restent
strictement reproductibles.

### Ce que le modèle voit — et ne voit pas
- Il ne reçoit que des **libellés** (« MASTERCARD », « CHEQUES »). **Aucun
  montant** ne lui est transmis.
- Il tourne en local : rien ne quitte votre poste.
- Il n'intervient **jamais dans un calcul**. Totaux, consolidations et
  formules restent produits par du code déterministe. Le modèle qualifie la
  nature d'une ligne, rien de plus.
- Sans Ollama ni cartographie validée, l'application fonctionne exactement
  comme avant.

### Précaution
Un modèle de 1 milliard de paramètres se trompe régulièrement. C'est
précisément pourquoi rien n'est appliqué sans votre validation, et pourquoi
une cartographie devient caduque dès qu'un libellé change dans le gabarit.

Pour repartir des règles automatiques : bouton « Oublier la cartographie »,
ou suppression du fichier `cartographie.json`.

## 5bis. Reconnaissance des variantes d'onglets

Le gabarit officiel demande, pour certains thèmes, de « remplir un
formulaire pour chaque réseau ». Un établissement qui applique cette
consigne produit plusieurs onglets (`Cartes 2 GIMAC`, `Cartes 2 VISA`,
`Transfert d'argent (SYGMA)`…) là où d'autres n'en produisent qu'un seul —
l'application les reconnaît automatiquement et les additionne dans le bon
thème, à condition que leur structure interne concorde réellement avec le
gabarit officiel (jamais sur la seule foi du nom).

Un onglet dont la structure ne correspond à rien de connu (mise en page
différente, gabarit non conforme) n'est **jamais deviné à l'aveugle** : il
reste visible, avec une suggestion si une ressemblance partielle a été
détectée, dans :
- la barre latérale, sous chaque établissement concerné (« ⚠️ N onglet(s)
  non rattaché(s) ») ;
- le panneau « Points de vigilance » ;
- le bloc « Points de vigilance » des deux exports.

Quand une correspondance suffisamment probable a été détectée, elle
apparaît comme une **proposition prête à valider en un clic** — jamais un
formulaire à remplir. Un bouton `✅ [thème] (taux%)` suffit ; s'il existe
une seconde piste plausible, un bouton `↔️` propose l'alternative. Une
mention « mensuel → dernier mois retenu » signale qu'un thème normalement
statique a été décliné en version mensuelle (comme Mobile Money) — le
dernier mois renseigné est alors automatiquement extrait.

**Une fois validé, plus jamais redemandé** : le rattachement est mémorisé
(comme la cartographie IA, hors du dossier projet), et un nouveau dépôt
d'un fichier portant un onglet du même nom sera reconnu directement.

Trois niveaux, du plus au moins confiant :
- **✅ Proposition** — un clic valide, mémorisé pour la suite.
- **❔ Piste faible** — l'onglet ne couvre qu'une partie du gabarit (activité
  partiellement renseignée, ex. sans ventilation sectorielle) : le taux de
  concordance reste bas, mais la piste est affichée et reste validable en
  un clic si elle vous semble juste.
- **Sans piste** — structure trop différente pour proposer quoi que ce soit
  sans risque (le plus souvent, un onglet qui mélange plusieurs thèmes en
  un seul, avec des lignes décalées) : non consolidé, mais rien n'est
  perdu — l'onglet reste visible.

### Indicateurs clés — les 11 thèmes du gabarit

Le tableau « Indicateurs clés » de l'application ne se limite plus à
Mobile Money1, Cartes1 et Cartes 5 : il reprend désormais aussi les
grandes lignes monétaires de chaque thème (chèques, virements, transferts
d'argent, les cinq catégories de Mobile Money, les transactions cartes en
émission comme en acquisition) — les mêmes lignes, déjà vérifiées, que le
montant total par pays des exports. Un établissement dont l'activité ne
relève pas de Mobile Money (transferts d'argent, paiements cartes en
acquisition…) n'apparaît plus à tort comme une colonne vide.

Une colonne à zéro peut aussi signaler un onglet **en attente de
validation** (voir « ⚠️ onglet(s) non rattaché(s) » dans la barre
latérale) plutôt qu'une absence réelle d'activité.

La section « Graphiques » a été retirée.

## Regroupement par pays (CEMAC)

Chaque établissement est automatiquement rattaché à un pays (Cameroun,
Centrafrique, Congo, Gabon, Guinée Équatoriale, Tchad), détecté depuis le
nom du fichier — plusieurs codages sont reconnus pour un même pays (« CA »,
« RCA », « CAF » désignent tous la Centrafrique). Le pays proposé reste
**toujours modifiable** juste sous le nom de l'établissement, dans la barre
latérale : jamais d'affectation silencieuse.

### Dans le fichier complet
Le même tableau « Pays / Montant total » apparaît bien en évidence, tout en haut du Sommaire — avant même la liste des thèmes. Chaque thème du gabarit comporte en plus, en plus de l'onglet Total CEMAC (tous établissements), un **onglet Total par pays** (couleur brune), additionnant uniquement les établissements de ce pays.

### Dans le résumé
Un nouveau bloc **« Indicateurs clés par pays »** reprend les mêmes
indicateurs que le bloc principal, mais regroupés par pays plutôt que par
établissement, avec une colonne CEMAC en bout de tableau qui redonne le
total d'ensemble — toujours identique au Total marché du premier bloc.

Un établissement dont le pays n'a pas pu être détecté (ou n'a pas été
renseigné) n'apparaît simplement dans aucun total pays, sans bloquer le
reste de la consolidation.

## Onglets d'un exercice révolu

Un établissement laisse parfois dans son classeur d'anciens onglets d'une
période antérieure (constaté sur un fichier réel : des onglets « 1er
SEMESTRE 22 », titrés « 1er TRIMESTRE 2022 », aux côtés d'onglets
2025-2026 — et bel et bien renseignés, 45 milliards XAF sur les chèques).

Ces onglets ressemblent au gabarit à plus de 90 % : sans précaution, ils
seraient rattachés et leurs montants de 2022 viendraient gonfler les totaux
de la période courante, **sans qu'aucune erreur ne soit signalée**.
L'application détecte donc la période de chaque onglet (lue dans son titre)
et écarte délibérément ceux d'un exercice antérieur : ils restent visibles
et tracés, avec la mention « Exercice révolu », mais ne sont jamais proposés
au rattachement en un clic.

Dans le résumé, la colonne **« Pourquoi non consolidé »** du bloc « Onglets
hors gabarit » indique la raison exacte pour chaque onglet — plus aucun
onglet n'apparaît sans explication.

## Onglets composites (plusieurs thèmes en un seul)

Un établissement peut assembler le contenu de plusieurs onglets du gabarit
(par exemple Cartes1 à Cartes 5) en une seule feuille maison. L'application
détecte automatiquement chaque portion et son thème, avec sa plage de
lignes et son niveau de confiance — un seul bouton **« ✅ Valider ces N
segments »** confirme l'ensemble d'un coup, jamais un par un.

### Onglets hors gabarit standard

Un onglet dont la structure ne correspond à rien de connu, même partiellement
(mise en page entièrement propre à un établissement), **n'est jamais perdu** :
- il apparaît dans le fichier complet, sur son propre onglet (couleur ambre),
  avec son contenu intégral ;
- il est référencé dans le Sommaire, avec un lien direct ;
- il figure dans le résumé (bloc « Onglets hors gabarit standard »), par
  établissement.

Il n'est simplement pas additionné dans les totaux marché, puisqu'aucun
autre établissement ne partage la même structure.

## 6. Comprendre les indicateurs

Le détail exact de chaque règle de calcul est dans le **Cahier des
charges, section 6**. En résumé :

- Les indicateurs Mobile Money (porteurs, encours) retiennent automatiquement
  le **dernier mois renseigné en commun** par au moins un établissement —
  pas besoin de mettre l'outil à jour chaque mois.
- Le **Total marché** additionne simplement les établissements qui
  renseignent effectivement chaque indicateur (un établissement qui ne
  renseigne pas un onglet n'apporte ni ne retire rien au total).

## 7. Les deux exports

| Export | Contenu | Quand l'utiliser |
|---|---|---|
| **Résumé** | Un seul onglet, les indicateurs clés | Partage rapide, revue de direction |
| **Complet** | Un onglet par établissement + un onglet Total, pour chacun des 11 thèmes du gabarit | Archivage, dossier réglementaire, contrôle détaillé |

d'un **Sommaire** dont chaque ligne mène au thème correspondant. Chaque
feuille porte en **cellule B1** un lien **« ◄ Retour au sommaire »**.

mêmes que dans la section « Tous les indicateurs » de l'application, avec le
même marquage ● renseigné / ○ vide, un filtre automatique et un en-tête
figé pour s'y retrouver malgré son volume. Chaque valeur y est une **formule**
reliée à l'onglet Total correspondant : elle se recalcule avec le classeur, et
respecte une cartographie du gabarit validée via l'IA locale, le cas échéant. La numérotation des lignes y reste identique à
celle de votre liasse d'origine : vous pouvez comparer cellule à cellule.

Les deux fichiers contiennent de **vraies formules Excel** (pas des valeurs
figées) : si tu modifies une valeur dans un onglet établissement du fichier
complet, le total se recalcule automatiquement.

## 8. Dépannage

**`ModuleNotFoundError: No module named 'xxx'`**
Une dépendance manque dans ton environnement. Dans le dossier
`consolidateur`, avec l'environnement virtuel activé :
```
pip install -r requirements.txt
```

**`ERROR: Could not open requirements file: [Errno 2] No such file or directory`**
Tu n'es pas dans le bon dossier. Tape `cd consolidateur` (en ajustant le
chemin si besoin), vérifie avec `dir` (Windows) ou `ls` (macOS/Linux) que
`requirements.txt` apparaît bien dans la liste, puis relance la commande.

**Le fichier déposé n'est reconnu par aucun onglet**
Le fichier n'utilise pas le gabarit attendu (les 11 onglets du Cahier des
charges, Annexe A). L'app affiche une erreur à côté du fichier concerné mais
continue de fonctionner avec les autres fichiers valides.

**J'ai cliqué sur « Retirer » mais l'établissement revient**
Cela ne devrait plus arriver (corrigé en Phase 8) — si le problème persiste,
vérifie que tu utilises bien la dernière version du dossier fournie après
cette phase.

**« L'indicateur X est introuvable dans l'onglet Y, pourtant renseigné »**
C'est l'alerte la plus importante de l'outil : elle signifie qu'un libellé
attendu n'a pas été trouvé alors que l'onglet contient bien des données —
typiquement parce que la BEAC a modifié la formulation dans son gabarit, ou
qu'un établissement l'a saisie différemment. **La valeur affichée (0) n'est
alors pas fiable** et ne doit pas être transmise telle quelle. Ouvre l'onglet
concerné dans l'aperçu pour repérer le nouveau libellé, puis signale-le pour
que la règle de lecture soit mise à jour (Cahier des charges, section 6).

**Une valeur affichée à 0 alors que le fichier semble renseigné**
Deux causes possibles, toutes deux signalées dans « Points de vigilance » :
un **libellé introuvable** (le gabarit a changé) ou une **cellule en erreur
de formule** dans le fichier source. Les nombres saisis en texte, eux, sont
récupérés automatiquement et simplement signalés en orange.

**Deux établissements avec le même nom**
L'app ajoute automatiquement un suffixe « (2) » pour les distinguer et
affiche un avertissement, afin qu'aucune valeur ne soit perdue dans les
calculs.

## 9. Historique dans le temps

Chaque consolidation réussie enregistre automatiquement une ligne dans
`historique.csv` — un fichier texte simple, ouvrable dans Excel ou un
éditeur de texte si tu veux l'inspecter ou le corriger à la main.

**Où se trouve ce fichier ?** Dans ton dossier personnel, à l'emplacement
`~/.consolidateur-liasses/historique.csv` (sous Windows :
`C:\Users\<TonNom>\.consolidateur-liasses\historique.csv`).

Il est volontairement rangé **en dehors du dossier de l'application** : ainsi,
quand tu remplaces le dossier `consolidateur` par une nouvelle version de
l'outil, ton historique accumulé n'est pas effacé. Si un historique existait
déjà dans l'ancien emplacement (`consolidateur/data/`), il est recopié
automatiquement au premier lancement.

Pour le ranger ailleurs (dossier partagé, dossier sauvegardé
automatiquement), définis la variable d'environnement
`CONSOLIDATEUR_HISTORIQUE` avec le chemin voulu.

- La **période** enregistrée est déduite automatiquement du dernier mois
  Mobile Money disponible dans les fichiers déposés (ex. « déc-25 »). Sans
  donnée Mobile Money, le mois en cours sert de repli.
- Si tu recharges les mêmes fichiers (ou relances l'app) pour une période
  déjà enregistrée, la ligne existante est **mise à jour**, jamais dupliquée.
- Dès qu'une deuxième période apparaît dans l'historique, la section
  « 📈 Historique » affiche :
  - la **variation** de chaque indicateur clé par rapport à la période
    précédente (flèche verte/rouge sous chaque chiffre) ;
  - une **courbe d'évolution** pour l'indicateur de ton choix, sur toutes
    les périodes enregistrées à ce jour.
- Le détail complet est consultable (et modifiable) via « Voir le détail de
  l'historique (CSV) ».

Pour repartir de zéro, il suffit de supprimer ce fichier `historique.csv`
(ou de le vider en gardant uniquement la ligne d'en-tête).

## 10. Lancer les tests (pour vérifier une modification)

```
pytest
```

309 tests couvrent le parsing, la consolidation, les indicateurs, le contrôle
qualité, les graphiques, les exports, l'historique et la détection des
libellés introuvables — dont plusieurs qui
simulent un vrai dépôt de fichiers dans l'application (comme un utilisateur
le ferait dans le navigateur) et d'autres qui recalculent réellement les
fichiers Excel générés avec LibreOffice pour garantir l'absence d'erreur de
formule.
