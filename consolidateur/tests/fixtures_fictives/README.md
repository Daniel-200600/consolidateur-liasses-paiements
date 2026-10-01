# Liasses fictives

`BanqueA.xlsx` et `OperateurB.xlsx` sont des liasses statistiques de
paiements **fictives**, utilisées par les tests publics et le CI.

Elles reprennent la structure du gabarit (onglets, libellés, notes de bas de
tableau, formules, cellules vides, nombres saisis en texte) afin d'exercer les
mêmes cas que des liasses réelles. Leur contenu, lui, ne correspond à aucun
établissement :

- aucun nom d'établissement ni de personne (le libellé « Etablissement : »
  porte au plus « BANQUE A (fictive) » ou « OPERATEUR B (fictif) ») ;
- chaque montant et chaque effectif est une valeur fictive de même ordre de
  grandeur que dans un fichier réel, les zéros et les cellules vides étant
  conservés pour que les onglets vides le restent ;
- les formules sont recalculées à partir de ces valeurs, si bien que les
  totaux restent cohérents ;
- aucune métadonnée de document (auteur, liaisons externes, propriétés
  personnalisées).

Les valeurs attendues dans les tests (`REFERENCE`, totaux, indicateurs)
correspondent à ces fichiers fictifs.
