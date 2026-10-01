# Construire Analyse.exe

## Ce que fait l'exécutable

`Analyse.exe` lance l'application Streamlit localement et ouvre automatiquement
le navigateur par défaut.

- Serveur local uniquement : `127.0.0.1`
- Aucun besoin d'ouvrir VS Code
- Aucun besoin de taper `streamlit run app.py`
- Le port est choisi automatiquement
- Les fichiers Excel déposés restent sur le PC
- L'historique reste dans `%USERPROFILE%\.consolidateur-liasses\` comme prévu par l'application

## Important : "n'importe quelle machine"

L'exécutable Windows ne peut pas être universel pour tous les systèmes.
Cette version cible les PC **Windows 10/11 64 bits**.

La machine cible n'a normalement pas besoin d'avoir Python, Streamlit ou les
bibliothèques du projet installés : PyInstaller les embarque dans l'exécutable.

## Construire l'exécutable

Sur un PC Windows de développement :

1. Décompresser le projet.
2. Ouvrir le dossier `Analyse`.
3. Double-cliquer sur `build_Analyse.bat`.
4. Attendre la fin de la construction.
5. Récupérer :

`dist\Analyse.exe`

## Tester

Double-cliquer sur `dist\Analyse.exe`.

Le navigateur doit s'ouvrir automatiquement sur une adresse locale de type :

`http://127.0.0.1:xxxxx`

Fermer la fenêtre/processus `Analyse.exe` arrête l'application.

## Journal en cas d'erreur

Si l'application ne démarre pas, consulter :

`%LOCALAPPDATA%\Analyse\Analyse.log`

## Ollama

Le projet contient une intégration facultative avec Ollama. L'application reste
utilisable sans Ollama. Si une fonction dépendant du LLM est utilisée, Ollama
doit être installé et son modèle local disponible sur la machine concernée.

## Recommandation de distribution

Pour une utilisation interne, distribuer `Analyse.exe` avec une version
identifiée du projet. Pour une vraie distribution à plusieurs postes, il est
préférable de créer ensuite un installateur Windows (par exemple avec Inno
Setup) afin de gérer raccourci, dossier de données et désinstallation.


## Correctif Streamlit

Le lanceur force `global.developmentMode=false` afin de permettre l'utilisation d'un port local dynamique dans l'exécutable PyInstaller. Il attend également que le serveur accepte les connexions avant d'ouvrir le navigateur.
