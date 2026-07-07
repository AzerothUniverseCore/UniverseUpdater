#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Azeroth Universe - Installateur / Updater client (Mac)
========================================================

Ce script :
  1. Télécharge l'archive du client (AzerothUniverse_platform_Mac.zip)
  2. La dézippe dans le dossier racine du jeu
  3. Télécharge tous les patchs listés (Data/ et Data/frFR/) et les
     remplace dans les dossiers correspondants

L'exécutable compilé (voir instructions à la fin) est prévu pour être placé
directement à la racine du dossier du jeu, à côté du dossier "Data" :

    AzerothUniverse/
        Application(.app/.exe)
        Data/
        Data/frFR/
        ...

Aucune dépendance externe n'est nécessaire (uniquement la bibliothèque
standard Python), afin de simplifier la compilation en exécutable.
"""

import os
import sys
import shutil
import zipfile
import hashlib
import tempfile
import urllib.request
import urllib.error

# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------

CLIENT_ZIP_URL = "https://azeroth-universe.eu/uploads/client/AzerothUniverse_platform_Mac.zip"

PATCH_BASE_ROOT = "https://azeroth-universe.eu/universe_client/Data"
PATCH_BASE_FRFR = "https://azeroth-universe.eu/universe_client/Data/frFR"

# Liste des patchs du dossier Data/ (nom, taille en Ko - indicatif uniquement)
ROOT_PATCHES = [
    "common.MPQ", "common-2.MPQ", "expansion.MPQ", "lichking.MPQ",
    "patch.MPQ", "patch-2.MPQ", "patch-3.MPQ", "patch-4.MPQ",
    "patch-5.MPQ", "patch-6.MPQ", "patch-7.MPQ", "patch-8.MPQ",
    "patch-9.MPQ", "patch-A.MPQ", "patch-B.MPQ", "patch-C.MPQ",
    "patch-D.MPQ", "patch-E.MPQ", "patch-F.MPQ", "patch-I.MPQ",
    "patch-K.MPQ", "patch-N.MPQ", "patch-T.MPQ", "patch-U.MPQ",
    "patch-V.MPQ", "patch-Y.MPQ", "patch-Z.MPQ",
]

# Liste des patchs du dossier Data/frFR/
FRFR_PATCHES = [
    "backup-frFR.MPQ", "base-frFR.MPQ", "expansion-locale-frFR.MPQ",
    "expansion-speech-frFR.MPQ", "lichking-locale-frFR.MPQ",
    "lichking-speech-frFR.MPQ", "locale-frFR.MPQ", "patch-frFR.MPQ",
    "patch-frFR-2.MPQ", "patch-frFR-3.MPQ", "patch-frFR-4.MPQ",
    "patch-frFR-5.MPQ", "patch-frFR-6.MPQ", "patch-frFR-7.MPQ",
    "patch-frFR-8.MPQ", "patch-frFR-U.MPQ", "patch-frFR-X.MPQ",
    "speech-frFR.MPQ",
]

MAX_RETRIES = 3
CHUNK_SIZE = 1024 * 256  # 256 Ko


# ----------------------------------------------------------------------
# Utilitaires
# ----------------------------------------------------------------------

def base_dir():
    """
    Retourne le dossier dans lequel se trouve l'exécutable / le script.
    C'est ce dossier qui est considéré comme la racine du jeu
    (contenant Data/, Data/frFR/, etc.)
    """
    if getattr(sys, "frozen", False):
        # Exécutable compilé (PyInstaller)
        if sys.platform == "darwin" and ".app/Contents/MacOS" in sys.executable:
            # Remonte depuis Xxx.app/Contents/MacOS/Xxx jusqu'au dossier
            # qui contient le .app (racine du jeu)
            app_path = sys.executable
            while not app_path.endswith(".app") and app_path != os.path.dirname(app_path):
                app_path = os.path.dirname(app_path)
            return os.path.dirname(app_path)
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def human_size(n_bytes):
    for unit in ["o", "Ko", "Mo", "Go"]:
        if n_bytes < 1024:
            return f"{n_bytes:.1f} {unit}"
        n_bytes /= 1024
    return f"{n_bytes:.1f} To"


def print_progress(prefix, done, total, width=32):
    if total > 0:
        ratio = min(done / total, 1.0)
        filled = int(width * ratio)
        bar = "#" * filled + "-" * (width - filled)
        pct = ratio * 100
        sys.stdout.write(
            f"\r{prefix:<28} [{bar}] {pct:5.1f}%  "
            f"({human_size(done)}/{human_size(total)})"
        )
    else:
        sys.stdout.write(f"\r{prefix:<28} {human_size(done)} téléchargés")
    sys.stdout.flush()


def download_file(url, dest_path, label=None):
    """
    Télécharge un fichier avec affichage de progression et tentatives
    multiples en cas d'échec réseau.
    """
    label = label or os.path.basename(dest_path)
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    tmp_path = dest_path + ".part"

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AzerothUniverseUpdater/1.0"})
            with urllib.request.urlopen(req, timeout=30) as response, open(tmp_path, "wb") as out_file:
                total = int(response.headers.get("Content-Length", 0))
                downloaded = 0
                while True:
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    out_file.write(chunk)
                    downloaded += len(chunk)
                    print_progress(label, downloaded, total)
            print()  # nouvelle ligne après la barre de progression
            shutil.move(tmp_path, dest_path)
            return True
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
            last_error = exc
            print(f"\n  ! Échec ({attempt}/{MAX_RETRIES}) pour {label} : {exc}")
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    print(f"  ✗ Impossible de télécharger {label} : {last_error}")
    return False


# ----------------------------------------------------------------------
# Étapes principales
# ----------------------------------------------------------------------

def install_full_client(root):
    """Télécharge et extrait l'archive complète du client Mac."""
    print("\n=== Étape 1/2 : Téléchargement du client complet ===\n")

    with tempfile.TemporaryDirectory() as tmp_dir:
        zip_path = os.path.join(tmp_dir, "AzerothUniverse_platform_Mac.zip")
        ok = download_file(CLIENT_ZIP_URL, zip_path, label="Client Mac (zip)")
        if not ok:
            print("Le téléchargement du client a échoué. Arrêt.")
            return False

        print("\nExtraction de l'archive en cours…")
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                total_files = len(zf.infolist())
                for i, member in enumerate(zf.infolist(), start=1):
                    zf.extract(member, root)
                    print_progress("Extraction", i, total_files)
            print("\nExtraction terminée.")
        except zipfile.BadZipFile:
            print("✗ L'archive téléchargée est corrompue ou invalide.")
            return False

    return True


def update_patches(root):
    """Télécharge tous les patchs et remplace les anciens fichiers."""
    print("\n=== Étape 2/2 : Mise à jour des patchs ===\n")

    data_dir = os.path.join(root, "Data")
    frfr_dir = os.path.join(data_dir, "frFR")
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(frfr_dir, exist_ok=True)

    jobs = []
    for name in ROOT_PATCHES:
        jobs.append((f"{PATCH_BASE_ROOT}/{name}", os.path.join(data_dir, name), f"Data/{name}"))
    for name in FRFR_PATCHES:
        jobs.append((f"{PATCH_BASE_FRFR}/{name}", os.path.join(frfr_dir, name), f"Data/frFR/{name}"))

    ok_count = 0
    failed = []

    for i, (url, dest, label) in enumerate(jobs, start=1):
        print(f"[{i}/{len(jobs)}] {label}")
        # Remplace l'ancien fichier s'il existe déjà
        if os.path.exists(dest):
            os.remove(dest)
        if download_file(url, dest, label=label):
            ok_count += 1
        else:
            failed.append(label)

    print(f"\nPatchs mis à jour : {ok_count}/{len(jobs)}")
    if failed:
        print("Les patchs suivants n'ont pas pu être téléchargés :")
        for f in failed:
            print(f"  - {f}")
    return len(failed) == 0


# ----------------------------------------------------------------------
# Point d'entrée
# ----------------------------------------------------------------------

def main():
    root = base_dir()

    print("=" * 60)
    print(" Azeroth Universe — Installateur / Updater client (Mac)")
    print("=" * 60)
    print(f"\nDossier cible (racine du jeu) : {root}\n")

    print("Que souhaitez-vous faire ?")
    print("  1. Installation complète (télécharger le client + les patchs)")
    print("  2. Mettre à jour uniquement les patchs (Data/ et Data/frFR/)")
    print("  3. Quitter")

    choice = input("\nVotre choix [1/2/3] : ").strip()

    if choice == "1":
        if install_full_client(root):
            update_patches(root)
    elif choice == "2":
        update_patches(root)
    else:
        print("Annulé.")
        return

    print("\nTerminé. Appuyez sur Entrée pour fermer…")
    input()


if __name__ == "__main__":
    main()
