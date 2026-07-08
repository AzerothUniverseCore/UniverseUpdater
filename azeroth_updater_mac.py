#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Azeroth Universe Installateur / Updater client (Mac)
========================================================

Ce script :
  1. Télécharge et extrait l'archive du client de base
     (AzerothUniverse_platform_Mac.zip)
  2. Récupère le manifeste du client (liste complète des patchs, tailles
     et empreintes) depuis le même serveur que le launcher Windows, et
     ne télécharge que les fichiers manquants ou obsolètes (Data/ et
     Data/frFR/) - au lieu de tout retélécharger à chaque fois.

L'exécutable compilé (voir instructions à la fin) est prévu pour être placé
directement à la racine du dossier du jeu, à côté du dossier "Data" :

    AzerothUniverse/
        Application(.app/.exe)
        Data/
        Data/frFR/
        ...

Aucune dépendance externe n'est nécessaire (uniquement la bibliothèque
standard Python), afin de simplifier la compilation en exécutable.
Seule l'extraction des éventuels patchs multi-parties (volumes RAR,
utilisés pour les fichiers dépassant certaines limites d'hébergement)
nécessite un exécutable `unrar` externe - voir la section correspondante.
"""

import os
import sys
import json
import time
import shutil
import zipfile
import tempfile
import subprocess
import urllib.request
import urllib.error

# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------

CLIENT_ZIP_URL = "https://azeroth-universe.eu/uploads/client/AzerothUniverse_platform_Mac.zip"

# Même manifeste que le Mini Launcher Windows (azeroth_launcher_win.py) :
# {"version", "total_size", "files":[{"path","url","size","md5"}, ...]}
# En centralisant la liste des patchs côté serveur plutôt que dans ce
# script, on évite le problème qui a cassé cette version : des URLs
# codées en dur qui finissent par ne plus correspondre à la réalité de
# l'hébergement.
MANIFEST_URL = "https://azeroth-universe.eu/universe_launcher/manifest.php"

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2   # x2 à chaque nouvel essai
CHUNK_SIZE = 1024 * 256   # 256 Ko


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
    n_bytes = float(n_bytes)
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
    multiples en cas d'échec réseau (délai progressif entre essais).
    """
    label = label or os.path.basename(dest_path)
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    tmp_path = dest_path + ".part"

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AzerothUniverseUpdater/2.0"})
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
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY_SECONDS * attempt)

    print(f"  ✗ Impossible de télécharger {label} : {last_error}")
    return False


def find_unrar_bin():
    """
    Recherche un exécutable `unrar` capable d'extraire les patchs
    multi-parties, dans cet ordre :
      1. à côté du script/app (base_dir()/unrar)
      2. emplacements Homebrew habituels (Apple Silicon puis Intel)
      3. dans le PATH système
    Renvoie le chemin trouvé, ou None.

    Installation via Homebrew : `brew install unrar` (ou `brew install rar`
    selon les versions de formule disponibles).
    """
    candidates = [
        os.path.join(base_dir(), "unrar"),
        "/opt/homebrew/bin/unrar",
        "/usr/local/bin/unrar",
    ]
    for path in candidates:
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return shutil.which("unrar")


# ----------------------------------------------------------------------
# Manifeste / vérification des patchs
# ----------------------------------------------------------------------

def fetch_manifest():
    """Télécharge et parse le manifeste JSON du client (même source que
    le launcher Windows)."""
    req = urllib.request.Request(
        MANIFEST_URL, headers={"User-Agent": "AzerothUniverseUpdater/2.0"}
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = resp.read()
    return json.loads(data.decode("utf-8"))


def scan_updates(manifest, root):
    """
    Compare le manifeste avec le contenu local et renvoie la liste des
    entrées à télécharger : fichier absent, taille différente, ou (pour
    les patchs multi-parties / archives) fichier témoin d'extraction
    manquant.
    """
    to_download = []
    for entry in manifest.get("files", []):
        entry_type = entry.get("type", "single")

        if entry_type == "archive":
            marker_path = os.path.join(root, entry["marker"].replace("/", os.sep))
            need = not os.path.isfile(marker_path)
        else:
            rel = entry["path"].replace("/", os.sep)
            local_path = os.path.join(root, rel)
            need = False
            if not os.path.isfile(local_path):
                need = True
            elif entry_type != "rar_parts":
                try:
                    if os.path.getsize(local_path) != entry.get("size", -1):
                        need = True
                except OSError:
                    need = True

        if need:
            to_download.append(entry)
    return to_download


def download_entry(entry, root):
    """
    Télécharge (et extrait si nécessaire) une entrée du manifeste.
    Gère trois cas : fichier simple, patch multi-parties (volumes RAR),
    et archive à extraire (avec fichier témoin) - ces deux derniers cas
    ne servent que si le manifeste les utilise un jour ; dans le cas
    normal (patchs .MPQ classiques), seul le cas "single" est utilisé.
    """
    entry_type = entry.get("type", "single")
    label = entry["path"]

    if entry_type == "single":
        dest = os.path.join(root, entry["path"].replace("/", os.sep))
        if os.path.exists(dest):
            os.remove(dest)
        return download_file(entry["url"], dest, label=label)

    if entry_type == "rar_parts":
        dest = os.path.join(root, entry["path"].replace("/", os.sep))
        parts_dir = os.path.join(root, ".parts_tmp", os.path.splitext(os.path.basename(dest))[0])
        os.makedirs(parts_dir, exist_ok=True)
        part_paths = []
        try:
            for part in entry["parts"]:
                part_path = os.path.join(parts_dir, os.path.basename(part["url"]))
                if not download_file(part["url"], part_path, label=f"{label} (partie)"):
                    return False
                part_paths.append(part_path)

            unrar = find_unrar_bin()
            if not unrar:
                print(f"  ✗ unrar introuvable : impossible d'extraire {label} "
                      f"(brew install unrar, ou placez le binaire à côté de l'application).")
                return False

            print(f"  Extraction de {label} en cours…")
            result = subprocess.run(
                [unrar, "x", "-y", "-o+", part_paths[0], os.path.dirname(dest) + os.sep],
                capture_output=True, text=True, timeout=1800,
            )
            if result.returncode != 0:
                print(f"  ✗ Échec de l'extraction de {label} : {(result.stderr or result.stdout)[:300]}")
                return False
            if not os.path.isfile(dest):
                print(f"  ✗ Extraction terminée mais {label} est introuvable.")
                return False
            return True
        finally:
            shutil.rmtree(parts_dir, ignore_errors=True)

    if entry_type == "archive":
        dest = os.path.join(root, entry["path"].replace("/", os.sep))
        extract_to = os.path.join(root, entry.get("extract_to", "").replace("/", os.sep))
        marker = os.path.join(root, entry["marker"].replace("/", os.sep))
        os.makedirs(extract_to, exist_ok=True)
        if not download_file(entry["url"], dest, label=label):
            return False

        unrar = find_unrar_bin()
        if not unrar:
            print(f"  ✗ unrar introuvable : impossible d'extraire {label}.")
            return False

        print(f"  Extraction de {label} en cours…")
        result = subprocess.run(
            [unrar, "x", "-y", "-o+", dest, extract_to + os.sep],
            capture_output=True, text=True, timeout=1800,
        )
        if result.returncode != 0:
            print(f"  ✗ Échec de l'extraction de {label} : {(result.stderr or result.stdout)[:300]}")
            return False

        os.makedirs(os.path.dirname(marker), exist_ok=True)
        with open(marker, "w", encoding="utf-8") as f:
            f.write("OK")
        try:
            os.remove(dest)
        except OSError:
            pass
        return True

    print(f"  ✗ Type d'entrée inconnu pour {label} : {entry_type}")
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
    """
    Récupère le manifeste et ne télécharge que les patchs manquants ou
    obsolètes (Data/ et Data/frFR/), au lieu de tout retélécharger.
    """
    print("\n=== Étape 2/2 : Mise à jour des patchs (via manifeste) ===\n")

    try:
        manifest = fetch_manifest()
    except Exception as exc:
        print(f"✗ Impossible de récupérer le manifeste ({MANIFEST_URL}) : {exc}")
        print("  Vérifiez votre connexion, ou que cette URL est bien accessible.")
        return False

    to_update = scan_updates(manifest, root)
    total_files = len(manifest.get("files", []))

    if not to_update:
        print(f"✅ Client déjà à jour ({total_files} fichiers vérifiés).")
        return True

    missing_size = sum(e.get("size", 0) for e in to_update)
    print(f"{len(to_update)}/{total_files} fichier(s) à télécharger ({human_size(missing_size)}).\n")

    ok_count = 0
    failed = []
    for i, entry in enumerate(to_update, start=1):
        print(f"[{i}/{len(to_update)}] {entry['path']}")
        if download_entry(entry, root):
            ok_count += 1
        else:
            failed.append(entry["path"])

    print(f"\nPatchs mis à jour : {ok_count}/{len(to_update)}")
    if failed:
        print("Les fichiers suivants n'ont pas pu être téléchargés :")
        for f in failed:
            print(f"  - {f}")
        print("\nRelancez la mise à jour (option 2) pour réessayer uniquement ces fichiers.")
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
