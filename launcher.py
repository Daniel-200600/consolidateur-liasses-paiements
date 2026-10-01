"""
Analyse - lanceur Windows pour l'application Streamlit.

Le lanceur démarre Streamlit localement puis ouvre automatiquement le navigateur.
Toutes les données restent sur la machine : l'application écoute uniquement sur
127.0.0.1.
"""
from __future__ import annotations

import logging
import os
import socket
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path


def application_dir() -> Path:
    """Retourne le dossier embarqué par PyInstaller ou le dossier source."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "app"
    return Path(__file__).resolve().parent


def free_port() -> int:
    """Réserve logiquement un port TCP local disponible."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def setup_logging() -> None:
    log_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Analyse"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=log_dir / "Analyse.log",
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        encoding="utf-8",
    )


def open_browser(port: int) -> None:
    """Ouvre le navigateur dès que le serveur Streamlit accepte les connexions."""
    deadline = time.time() + 30.0
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                url = f"http://127.0.0.1:{port}"
                logging.info("Ouverture du navigateur : %s", url)
                webbrowser.open(url)
                return
        except OSError:
            time.sleep(0.25)

    logging.error("Le serveur n'a pas ouvert le port %s dans les 30 secondes", port)


def main() -> int:
    setup_logging()
    try:
        app_dir = application_dir()
        app_file = app_dir / "consolidateur" / "app.py"

        if not app_file.exists():
            raise FileNotFoundError(f"Application introuvable : {app_file}")

        # Le code métier est chargé depuis le dossier embarqué.
        os.chdir(app_file.parent)
        sys.path.insert(0, str(app_file.parent))

        port = free_port()
        logging.info("Démarrage d'Analyse sur le port %s", port)

        threading.Thread(
            target=open_browser, args=(port,), daemon=True
        ).start()

        # Import différé : cela évite de charger Streamlit avant d'avoir
        # configuré le chemin de l'application.
        from streamlit.web import cli as stcli

        sys.argv = [
            "streamlit",
            "run",
            str(app_file),
            "--server.address=127.0.0.1",
            f"--server.port={port}",
            "--global.developmentMode=false",
            "--server.headless=true",
            "--server.fileWatcherType=none",
            "--browser.gatherUsageStats=false",
        ]

        return stcli.main()

    except SystemExit as exc:
        return int(exc.code or 0)
    except Exception:
        logging.exception("Erreur fatale au démarrage")
        # En mode console=False, l'erreur reste disponible dans le journal.
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0,
                "Analyse n'a pas pu démarrer.\n\n"
                "Consultez le fichier :\n"
                f"{Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'Analyse' / 'Analyse.log'}",
                "Analyse",
                0x10,
            )
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
