"""
verifier_ollama.py

Auto-test à lancer sur le poste où Ollama est installé :

    python verifier_ollama.py
    python verifier_ollama.py --modele gemma3:1b

Il vérifie, dans l'ordre : que le serveur répond, que le modèle demandé est
installé, puis il soumet quelques libellés réels du gabarit et affiche le
classement obtenu. C'est le contrôle que je n'ai pas pu faire à votre place,
faute d'Ollama dans mon environnement.
"""

from __future__ import annotations

import argparse
import sys
import time

from core.llm import MODELE_PAR_DEFAUT, URL_PAR_DEFAUT, ClientOllama

# Cas représentatifs, dont ceux qui ont réellement posé problème.
CAS = [
    ("CHEQUES", "", "Nombre", True, "TITRE"),
    ("VIREMENTS", "", "Nombre", True, "TITRE"),
    ("MASTERCARD", "VISA", "UnionPay", False, "DONNEE"),
    ("VISA", "GIMAC", "MASTERCARD", False, "DONNEE"),
    ("TOTAL (A+B+C)", "- dont reçus", "", False, "DONNEE"),
    ("Nombre", "", "", False, "ENTETE"),
    ("(1) porteurs ayant effectué au moins une transaction", "", "", False, "NOTE"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Vérifie l'accès au modèle local Ollama.")
    parser.add_argument("--modele", default=MODELE_PAR_DEFAUT)
    parser.add_argument("--url", default=URL_PAR_DEFAUT)
    args = parser.parse_args()

    client = ClientOllama(url=args.url, modele=args.modele)

    print(f"Serveur      : {args.url}")
    modeles = client.modeles_disponibles()
    if not modeles:
        print("\n[ÉCHEC] Le serveur ne répond pas.")
        print("        Démarrez-le avec :  ollama serve")
        return 1
    print(f"Modèles      : {', '.join(modeles)}")

    if not any(m == args.modele or m.startswith(args.modele.split(':')[0]) for m in modeles):
        print(f"\n[ÉCHEC] Le modèle « {args.modele} » n'est pas installé.")
        print(f"        Installez-le avec :  ollama pull {args.modele}")
        return 1
    print(f"Modèle testé : {args.modele}\n")

    justes = 0
    debut = time.time()
    for libelle, precedent, suivant, entete, attendu in CAS:
        t0 = time.time()
        verdict = client.classer(libelle, precedent, suivant, entete)
        duree = time.time() - t0
        ok = verdict.role == attendu
        justes += ok
        marque = "OK  " if ok else "DIFF"
        print(f"  [{marque}] {libelle[:46]:<46} -> {verdict.role:<7} "
              f"(attendu {attendu:<7}) {duree:4.1f}s")
        if not verdict.interprete:
            print(f"         réponse brute non comprise : {verdict.brut[:60]!r}")

    total = time.time() - debut
    print(f"\n{justes}/{len(CAS)} classements conformes — {total:.1f}s "
          f"({total/len(CAS):.1f}s par ligne)")

    if justes < len(CAS):
        print("\nUn modèle de 1 milliard de paramètres se trompe parfois : c'est\n"
              "précisément pourquoi la cartographie doit être RELUE et validée\n"
              "dans l'application avant d'être appliquée.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
