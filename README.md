# Analyse - Consolidateur de liasses statistiques de paiements

[![tests](https://github.com/Daniel-200600/consolidateur-liasses-paiements/actions/workflows/tests.yml/badge.svg)](https://github.com/Daniel-200600/consolidateur-liasses-paiements/actions/workflows/tests.yml)
![Python](https://img.shields.io/badge/python-3.11-blue)
![License](https://img.shields.io/badge/license-MIT-green)

Application Python/Streamlit, 100 % locale, pour consolider des liasses statistiques de paiements (Excel), calculer des indicateurs, produire des graphiques et exporter les resultats.

- Application : [consolidateur/](consolidateur/) (voir [README](consolidateur/README.md) et [guide utilisateur](consolidateur/GUIDE_UTILISATEUR.md))
- Executable Windows : voir [README_EXECUTABLE.md](README_EXECUTABLE.md) - lancer `build_Analyse.bat` pour generer `dist\Analyse.exe`

## Lancer depuis les sources

```bash
python -m venv venv
venv\Scripts\activate
pip install -r consolidateur/requirements.txt
streamlit run consolidateur/app.py
```

Les donnees deposees restent sur le poste. Les fichiers de test contenant des donnees reelles ne sont pas publies.
