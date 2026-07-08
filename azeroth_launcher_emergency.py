#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Azeroth Universe - Launcher client (Windows) - VERSION D'URGENCE
==================================================================

Version de secours du launcher, à utiliser si l'hébergement principal
(azeroth-universe.eu) est indisponible.

Contrairement à la version standard qui récupère la liste des fichiers
via un manifeste JSON généré côté serveur (manifest.php), cette version
utilise une liste de liens fixes pointant vers les Releases GitHub du
dépôt AzerothUniverseCore/UniverseClient. Tout le reste du launcher
(interface, logique de comparaison, téléchargement parallèle) est
strictement identique à la version standard.

Ce launcher :
  1. Construit la liste des fichiers du client à partir des liens
     GitHub codés en dur ci-dessous, puis interroge chaque URL pour
     connaître sa taille (requête HEAD).
  2. Compare le contenu du dossier d'installation local à cette liste
     pour déterminer les fichiers manquants ou obsolètes.
  3. Télécharge directement (en parallèle) chaque fichier concerné,
     avec une interface graphique dans l'esprit World of Warcraft
     (fond sombre, dorures, barre de progression dégradée).

Aucune dépendance externe n'est nécessaire (uniquement la bibliothèque
standard Python + Tkinter), afin de simplifier la compilation en
exécutable Windows via PyInstaller.

Compilation (Windows) :
    pip install pyinstaller
    pyinstaller --onefile --windowed --name AzerothLauncherUrgence ^
                --icon=azeroth.ico azeroth_launcher_emergency.py

L'exécutable généré est prévu pour être placé où l'utilisateur le
souhaite : au premier lancement, il choisit lui-même le dossier
d'installation via le bouton "Parcourir...".
"""

import os
import sys
import json
import time
import queue
import shutil
import threading
import subprocess
import webbrowser
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ----------------------------------------------------------------------
# Configuration - à adapter selon votre infrastructure
# ----------------------------------------------------------------------

WEBSITE_URL = "https://azeroth-universe.eu"
REGISTER_URL = "https://azeroth-universe.eu/register"

CONFIG_FILE = "launcher_config.json"
DEFAULT_SUBFOLDER = "AzerothUniverse"

MAX_WORKERS = 4                 # téléchargements simultanés
SIZE_LOOKUP_WORKERS = 8         # requêtes HEAD simultanées (résolution des tailles)
CHUNK_SIZE = 1024 * 256         # 256 Ko par lecture réseau
SPEED_WINDOW_SECONDS = 5        # fenêtre glissante pour le calcul de vitesse
MAX_RETRIES = 3                 # tentatives par fichier (ou par partie) en cas d'échec réseau
RETRY_DELAY_SECONDS = 2         # pause entre deux tentatives (x2 à chaque nouvel essai)
MAX_RAR_PARTS_PROBE = 30        # nombre maximal de parties .partN.rar à sonder par patch

# ----------------------------------------------------------------------
# Liste statique des fichiers - Releases GitHub (mode de secours)
# ----------------------------------------------------------------------
# Chaque patch est publié en tant que Release GitHub distincte, dont le
# tag porte le même nom que le fichier, par exemple :
#   https://github.com/AzerothUniverseCore/UniverseClient/releases/download/patch.MPQ/patch.MPQ
# Il suffit d'ajouter/retirer un nom dans ROOT_PATCHES ou FRFR_PATCHES
# pour que ce launcher le prenne en compte (à condition que la Release
# GitHub correspondante existe).
#
# Certains patchs dépassent la limite de 2 Go par asset GitHub : ils sont
# alors publiés sous forme de volumes RAR multi-parties dans la MÊME
# Release, nommés "{nom-sans-extension}.part1.rar", ".part2.rar", etc.
# (ex: la Release "patch-4.MPQ" contient patch-4.part1.rar ... part5.rar).
# Ce launcher détecte ce cas automatiquement : il essaie d'abord l'asset
# unique attendu, et si celui-ci est introuvable, sonde les volumes
# .partN.rar jusqu'à ce qu'il n'en trouve plus. Les parties sont ensuite
# téléchargées puis reconstituées via UnRAR (voir find_unrar_exe ci-dessous).

GITHUB_RELEASES_BASE = "https://github.com/AzerothUniverseCore/UniverseClient/releases/download"

# Patchs du dossier Data/
ROOT_PATCHES = [
    "common.MPQ", "common-2.MPQ", "expansion.MPQ", "lichking.MPQ",
    "patch.MPQ", "patch-2.MPQ", "patch-3.MPQ", "patch-4.MPQ",
    "patch-5.MPQ", "patch-6.MPQ", "patch-7.MPQ", "patch-8.MPQ",
    "patch-9.MPQ", "patch-A.MPQ", "patch-B.MPQ", "patch-C.MPQ",
    "patch-D.MPQ", "patch-E.MPQ", "patch-F.MPQ", "patch-I.MPQ",
    "patch-K.MPQ", "patch-N.MPQ", "patch-T.MPQ", "patch-U.MPQ",
    "patch-V.MPQ", "patch-Y.MPQ", "patch-Z.MPQ",
]

# Patchs du dossier Data/frFR/
FRFR_PATCHES = [
    "backup-frFR.MPQ", "base-frFR.MPQ", "expansion-locale-frFR.MPQ",
    "expansion-speech-frFR.MPQ", "lichking-locale-frFR.MPQ",
    "lichking-speech-frFR.MPQ", "locale-frFR.MPQ", "patch-frFR.MPQ",
    "patch-frFR-2.MPQ", "patch-frFR-3.MPQ", "patch-frFR-4.MPQ",
    "patch-frFR-5.MPQ", "patch-frFR-6.MPQ", "patch-frFR-7.MPQ",
    "patch-frFR-8.MPQ", "patch-frFR-U.MPQ", "patch-frFR-X.MPQ",
    "speech-frFR.MPQ",
]

# Archives complémentaires, publiées avec un nom de tag différent du
# nom de fichier -> renseignées explicitement. Contrairement aux
# patchs .MPQ, ce sont de vraies archives RAR (mono-partie) qui doivent
# être extraites après téléchargement :
#   - "path"       : où le .rar est téléchargé (relatif au dossier d'installation)
#   - "extract_to" : dossier de destination de l'extraction ("" = racine)
#   - "marker"     : fichier témoin créé après extraction réussie, pour
#                    savoir que c'est déjà fait sans devoir deviner le
#                    contenu exact de l'archive
EXTRA_ARCHIVES = [
    {
        "path": "AzerothUniverse.rar", "type": "archive",
        "url": f"{GITHUB_RELEASES_BASE}/AzerothUniverse/AzerothUniverse.rar",
        "extract_to": "", "marker": ".installed_AzerothUniverse",
    },
    {
        "path": "Data/frFR/Additional.rar", "type": "archive",
        "url": f"{GITHUB_RELEASES_BASE}/Additional/Additional.rar",
        "extract_to": "Data/frFR", "marker": "Data/frFR/.installed_Additional",
    },
]


def resolve_patch_entry(name, dest_path):
    """
    Détermine comment un patch doit être téléchargé :
      - asset unique -> {"type": "single", "url": ..., "size": ...}
      - volumes RAR  -> {"type": "rar_parts", "parts": [...], "size": ...}
    `size` vaut 0 si rien n'a pu être résolu (le fichier sera alors
    signalé en échec au moment du téléchargement, avec la vraie raison
    HTTP dans le rapport d'erreurs).
    """
    tag = name  # le tag de Release porte le même nom que le fichier
    single_url = f"{GITHUB_RELEASES_BASE}/{tag}/{name}"
    size = _get_remote_size(single_url)
    if size is not None:
        return {"path": dest_path, "type": "single", "url": single_url, "size": size}

    # Asset unique introuvable -> on sonde les volumes RAR multi-parties.
    # Deux conventions de nommage coexistent selon les patchs :
    #   - "part1.rar", "part2.rar", ...        (pas de zéro devant)
    #   - "part01.rar", "part02.rar", ...       (zéro-paddé sur 2 chiffres)
    base = os.path.splitext(name)[0]
    for number_format in ("{}", "{:02d}"):
        parts = []
        n = 1
        while n <= MAX_RAR_PARTS_PROBE:
            part_name = f"{base}.part{number_format.format(n)}.rar"
            part_url = f"{GITHUB_RELEASES_BASE}/{tag}/{part_name}"
            part_size = _get_remote_size(part_url)
            if part_size is None:
                break
            parts.append({"url": part_url, "size": part_size})
            n += 1
        if parts:
            return {
                "path": dest_path, "type": "rar_parts", "parts": parts,
                "size": sum(p["size"] for p in parts),
            }

    # Rien trouvé (ni asset unique, ni volumes) -> échec 404 classique,
    # remonté tel quel lors du téléchargement.
    return {"path": dest_path, "type": "single", "url": single_url, "size": 0}


def build_static_jobs():
    """Construit la liste (nom, chemin de destination) pour tous les patchs."""
    jobs = []
    for name in ROOT_PATCHES:
        jobs.append((name, f"Data/{name}"))
    for name in FRFR_PATCHES:
        jobs.append((name, f"Data/frFR/{name}"))
    return jobs


def find_unrar_exe():
    """
    Recherche un exécutable UnRAR (ou Rar.exe) capable d'extraire les
    volumes multi-parties, dans cet ordre :
      1. à côté du launcher (UnRAR.exe / unrar.exe)
      2. dans le dossier temporaire PyInstaller si le launcher est
         compilé avec --add-binary
      3. dans les emplacements d'installation habituels de WinRAR
      4. dans le PATH système
    Renvoie le chemin trouvé, ou None.
    """
    candidates = [
        os.path.join(base_dir(), "UnRAR.exe"),
        os.path.join(base_dir(), "unrar.exe"),
    ]
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        candidates.append(os.path.join(sys._MEIPASS, "UnRAR.exe"))
    for env_var in ("ProgramFiles", "ProgramFiles(x86)"):
        prog_dir = os.environ.get(env_var)
        if prog_dir:
            candidates.append(os.path.join(prog_dir, "WinRAR", "UnRAR.exe"))
            candidates.append(os.path.join(prog_dir, "WinRAR", "Rar.exe"))
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return (
        shutil.which("UnRAR.exe") or shutil.which("unrar")
        or shutil.which("Rar.exe") or shutil.which("rar")
    )



# ----------------------------------------------------------------------
# Palette "World of Warcraft" (sombre / doré)
# ----------------------------------------------------------------------

COLOR_BORDER      = "#4a3c22"
COLOR_BG          = "#0c0a08"
COLOR_PANEL       = "#15110c"
COLOR_PANEL_2     = "#20190f"
COLOR_GOLD        = "#c8aa6e"
COLOR_GOLD_LIGHT  = "#ffd970"
COLOR_TEXT        = "#e8dcb8"
COLOR_TEXT_DIM    = "#9c8f70"
COLOR_RED         = "#c0483f"
COLOR_GREEN       = "#7fae52"
COLOR_BAR_BG      = "#241d12"
COLOR_BAR_FILL_1  = "#6e5423"
COLOR_BAR_FILL_2  = "#ffd970"

FONT_TITLE = ("Georgia", 22, "bold")
FONT_SUB   = ("Segoe UI", 10)
FONT_HEAD  = ("Georgia", 12, "bold")
FONT_BODY  = ("Segoe UI", 10)
FONT_SMALL = ("Segoe UI", 9)


# ----------------------------------------------------------------------
# Utilitaires généraux
# ----------------------------------------------------------------------

def base_dir():
    """Dossier contenant l'exécutable / le script (pour le fichier de config)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def config_path():
    return os.path.join(base_dir(), CONFIG_FILE)


def load_config():
    path = config_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def save_config(cfg):
    try:
        with open(config_path(), "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def human_size(n_bytes):
    n = float(max(0, n_bytes))
    for unit in ("o", "Ko", "Mo", "Go"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} To"


def human_time(seconds):
    if seconds is None or seconds == float("inf") or seconds < 0:
        return "--:--"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:d}h {m:02d}m"
    return f"{m:02d}:{s:02d}"


def lerp_color(c1, c2, t):
    """Interpole deux couleurs hexadécimales (#rrggbb) selon t in [0,1]."""
    c1 = c1.lstrip("#")
    c2 = c2.lstrip("#")
    r1, g1, b1 = int(c1[0:2], 16), int(c1[2:4], 16), int(c1[4:6], 16)
    r2, g2, b2 = int(c2[0:2], 16), int(c2[2:4], 16), int(c2[4:6], 16)
    r = int(r1 + (r2 - r1) * t)
    g = int(g1 + (g2 - g1) * t)
    b = int(b1 + (b2 - b1) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


# ----------------------------------------------------------------------
# Logique manifeste / téléchargement (aucune dépendance à Tkinter ici)
# ----------------------------------------------------------------------

def _get_remote_size(url):
    """Récupère la taille (Content-Length) d'un fichier distant via une
    requête HEAD ; se rabat sur une requête GET (en-têtes seulement) si
    le serveur ne supporte pas HEAD. Renvoie None si indéterminable."""
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(
                url, method=method,
                headers={"User-Agent": "AzerothUniverseLauncher/2.0"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                length = resp.headers.get("Content-Length")
                if length:
                    return int(length)
        except Exception:
            continue
    return None


def build_manifest():
    """
    Construit un manifeste au même format que celui normalement fourni
    par le serveur ({"version", "total_size", "files":[...]}), mais à
    partir de la liste statique de liens GitHub (mode de secours).
    Pour chaque patch, on résout en parallèle s'il s'agit d'un asset
    unique ou de volumes RAR multi-parties (voir resolve_patch_entry).
    """
    jobs = build_static_jobs()

    with ThreadPoolExecutor(max_workers=SIZE_LOOKUP_WORKERS) as pool:
        resolved = list(pool.map(lambda job: resolve_patch_entry(job[0], job[1]), jobs))

    for extra in EXTRA_ARCHIVES:
        size = _get_remote_size(extra["url"])
        resolved.append({**extra, "size": size or 0})

    return {
        "version": "Mode de secours (GitHub)",
        "total_size": sum(e["size"] for e in resolved),
        "files": resolved,
    }


def scan_updates(manifest, install_dir):
    """
    Compare le manifeste avec le contenu local.
    Un fichier est considéré à télécharger s'il est absent ou si sa
    taille diffère de celle attendue (vérification rapide, cohérente
    avec le fonctionnement standard des launchers de clients WoW).

    Cas particuliers :
      - "rar_parts" (patchs multi-parties) : seule la présence du
        fichier final est vérifiée (la taille exacte après extraction
        n'est pas connue à l'avance).
      - "archive" (AzerothUniverse.rar, Additional.rar...) : on vérifie
        la présence du fichier témoin ("marker"), créé uniquement après
        une extraction réussie - pas la présence du .rar lui-même.
    """
    to_download = []
    for entry in manifest.get("files", []):
        entry_type = entry.get("type")

        if entry_type == "archive":
            marker_path = os.path.join(install_dir, entry["marker"].replace("/", os.sep))
            need = not os.path.isfile(marker_path)
        else:
            rel = entry["path"].replace("/", os.sep)
            local_path = os.path.join(install_dir, rel)
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


class Downloader:
    """Télécharge en parallèle une liste de fichiers du manifeste."""

    def __init__(self, install_dir, files, progress_queue, cancel_event):
        self.install_dir = install_dir
        self.files = files
        self.q = progress_queue
        self.cancel_event = cancel_event

    def _download_to_file(self, url, dest_path):
        """
        Télécharge `url` vers `dest_path` avec plusieurs tentatives.
        Renvoie (True, None) en cas de succès, ou (False, message
        d'erreur) sinon. Les octets d'une tentative ratée sont retirés
        du décompte global pour garder une progression cohérente.
        """
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        tmp = dest_path + ".part"
        last_error = None

        for attempt in range(1, MAX_RETRIES + 1):
            if self.cancel_event.is_set():
                return False, "Téléchargement annulé"
            bytes_written = 0
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": "AzerothUniverseLauncher/2.0"}
                )
                with urllib.request.urlopen(req, timeout=30) as resp, open(tmp, "wb") as out:
                    while True:
                        if self.cancel_event.is_set():
                            raise InterruptedError("Téléchargement annulé")
                        chunk = resp.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        out.write(chunk)
                        bytes_written += len(chunk)
                        self.q.put(("bytes", len(chunk)))
                os.replace(tmp, dest_path)
                return True, None
            except Exception as exc:
                last_error = str(exc)
                if os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
                if bytes_written:
                    self.q.put(("bytes", -bytes_written))
                if self.cancel_event.is_set():
                    return False, last_error
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY_SECONDS * attempt)

        return False, last_error

    def _download_single(self, entry):
        rel_path = entry["path"].replace("/", os.sep)
        dest = os.path.join(self.install_dir, rel_path)
        ok, err = self._download_to_file(entry["url"], dest)
        if ok:
            self.q.put(("file_done", entry["path"]))
        else:
            self.q.put(("file_error", entry["path"], err or "Erreur inconnue"))

    def _download_rar_parts(self, entry):
        """
        Télécharge tous les volumes .partN.rar d'un patch, puis les
        reconstitue via UnRAR. Le fichier final doit apparaître à
        `entry["path"]` pour être considéré comme réussi.
        """
        rel_path = entry["path"].replace("/", os.sep)
        dest = os.path.join(self.install_dir, rel_path)
        dest_dir = os.path.dirname(dest)
        os.makedirs(dest_dir, exist_ok=True)

        parts_dir = os.path.join(
            self.install_dir, ".parts_tmp", os.path.splitext(os.path.basename(dest))[0]
        )
        os.makedirs(parts_dir, exist_ok=True)
        part_paths = []

        try:
            for part in entry["parts"]:
                if self.cancel_event.is_set():
                    return
                part_path = os.path.join(parts_dir, os.path.basename(part["url"]))
                ok, err = self._download_to_file(part["url"], part_path)
                if not ok:
                    raise RuntimeError(err or "Échec du téléchargement d'une partie")
                part_paths.append(part_path)

            if self.cancel_event.is_set():
                return

            unrar = find_unrar_exe()
            if not unrar:
                raise RuntimeError(
                    "UnRAR.exe introuvable - installez WinRAR ou placez UnRAR.exe "
                    "à côté du launcher pour extraire les patchs en plusieurs parties "
                    "(https://www.rarlab.com/rar_add.htm)."
                )

            self.q.put((
                "status",
                f"Extraction de {entry['path']} en cours (peut prendre plusieurs minutes)…"
            ))
            result = subprocess.run(
                [unrar, "x", "-y", "-o+", part_paths[0], dest_dir + os.sep],
                capture_output=True, text=True, timeout=1800,
            )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "").strip()[:300]
                raise RuntimeError(f"Échec de l'extraction UnRAR (code {result.returncode}) : {detail}")

            if not os.path.isfile(dest):
                raise RuntimeError(
                    "Extraction terminée mais le fichier attendu est introuvable "
                    "(vérifiez que l'archive RAR contient bien le fichier à sa racine)."
                )

            self.q.put(("file_done", entry["path"]))
        except Exception as exc:
            self.q.put(("file_error", entry["path"], str(exc)))
        finally:
            shutil.rmtree(parts_dir, ignore_errors=True)

    def _download_archive(self, entry):
        """
        Télécharge une archive RAR mono-partie (ex: AzerothUniverse.rar,
        Additional.rar), l'extrait vers entry["extract_to"], puis crée
        le fichier témoin entry["marker"] pour signaler la réussite.
        Le .rar est ensuite supprimé pour ne pas rester "orphelin".
        """
        rel_path = entry["path"].replace("/", os.sep)
        dest = os.path.join(self.install_dir, rel_path)
        extract_to = os.path.join(self.install_dir, entry["extract_to"].replace("/", os.sep))
        marker = os.path.join(self.install_dir, entry["marker"].replace("/", os.sep))
        os.makedirs(extract_to, exist_ok=True)

        try:
            # Si le .rar est déjà présent avec la bonne taille (essai
            # précédent interrompu après le téléchargement), inutile de
            # le retélécharger.
            already_downloaded = (
                os.path.isfile(dest) and os.path.getsize(dest) == entry.get("size", -1)
            )
            if not already_downloaded:
                ok, err = self._download_to_file(entry["url"], dest)
                if not ok:
                    raise RuntimeError(err or "Échec du téléchargement")

            if self.cancel_event.is_set():
                return

            unrar = find_unrar_exe()
            if not unrar:
                raise RuntimeError(
                    "UnRAR.exe introuvable - installez WinRAR ou placez UnRAR.exe "
                    "à côté du launcher pour extraire cette archive "
                    "(https://www.rarlab.com/rar_add.htm)."
                )

            self.q.put(("status", f"Extraction de {entry['path']} en cours…"))
            result = subprocess.run(
                [unrar, "x", "-y", "-o+", dest, extract_to + os.sep],
                capture_output=True, text=True, timeout=1800,
            )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "").strip()[:300]
                raise RuntimeError(f"Échec de l'extraction UnRAR (code {result.returncode}) : {detail}")

            os.makedirs(os.path.dirname(marker), exist_ok=True)
            with open(marker, "w", encoding="utf-8") as f:
                f.write("OK")

            try:
                os.remove(dest)
            except OSError:
                pass  # pas bloquant : le fichier témoin fait foi

            self.q.put(("file_done", entry["path"]))
        except Exception as exc:
            self.q.put(("file_error", entry["path"], str(exc)))

    def _download_one(self, entry):
        if self.cancel_event.is_set():
            return
        entry_type = entry.get("type")
        if entry_type == "rar_parts":
            self._download_rar_parts(entry)
        elif entry_type == "archive":
            self._download_archive(entry)
        else:
            self._download_single(entry)

    def run(self):
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = [pool.submit(self._download_one, e) for e in self.files]
            for _ in as_completed(futures):
                if self.cancel_event.is_set():
                    break
        self.q.put(("all_done", None))


# ----------------------------------------------------------------------
# Widgets personnalisés
# ----------------------------------------------------------------------

class GoldProgressBar(tk.Canvas):
    """Barre de progression avec dégradé doré, dans l'esprit WoW."""

    def __init__(self, parent, width=760, height=24, **kwargs):
        super().__init__(
            parent, width=width, height=height, bg=COLOR_BAR_BG,
            highlightthickness=1, highlightbackground=COLOR_BORDER, **kwargs
        )
        # NB: on évite les noms self._w / self._h, réservés en interne par
        # Tkinter (self._w stocke le chemin du widget) - les écraser casse
        # tous les appels internes (delete, create_*, etc.).
        self._bar_width = width
        self._bar_height = height
        self._ratio = 0.0
        self._draw()

    def _draw(self):
        self.delete("all")
        w, h = self._bar_width, self._bar_height
        self.create_rectangle(0, 0, w, h, fill=COLOR_BAR_BG, outline="")
        fill_w = int(w * self._ratio)
        if fill_w > 0:
            for x in range(0, fill_w, 2):
                t = x / max(1, w)
                color = lerp_color(COLOR_BAR_FILL_1, COLOR_BAR_FILL_2, t)
                self.create_line(x, 1, x, h - 1, fill=color, width=2)
            self.create_line(fill_w, 0, fill_w, h, fill=COLOR_GOLD_LIGHT)
        pct = int(self._ratio * 100)
        self.create_text(
            w // 2, h // 2, text=f"{pct}%",
            fill=COLOR_TEXT, font=FONT_SMALL
        )

    def set_ratio(self, ratio):
        ratio = max(0.0, min(1.0, ratio))
        if abs(ratio - self._ratio) < 0.001:
            return
        self._ratio = ratio
        self._draw()


def make_button(parent, text, command, primary=False, small=False):
    """Bouton stylisé (Label cliquable) dans l'esprit WoW."""
    bg = COLOR_GOLD if primary else COLOR_PANEL_2
    fg = "#1a1408" if primary else COLOR_GOLD
    hover_bg = COLOR_GOLD_LIGHT if primary else "#2a2314"
    border = COLOR_GOLD_LIGHT if primary else COLOR_BORDER
    font = FONT_HEAD if primary else (FONT_SMALL if small else FONT_BODY)
    pady = 6 if small else 9
    padx = 12 if small else 18

    # Couleurs distinctes pour l'état désactivé, avec un contraste suffisant
    # dans les deux cas (bouton doré "primary" vs bouton sombre "secondary").
    bg_disabled = "#4a4022" if primary else COLOR_PANEL_2
    fg_disabled = "#8f8560" if primary else COLOR_TEXT_DIM

    btn = tk.Label(
        parent, text=text, font=font, bg=bg, fg=fg,
        padx=padx, pady=pady, cursor="hand2",
        highlightthickness=1, highlightbackground=border, highlightcolor=border,
    )
    btn._enabled = True
    btn._bg_normal = bg
    btn._bg_hover = hover_bg
    btn._bg_disabled = bg_disabled
    btn._fg_normal = fg
    btn._fg_disabled = fg_disabled

    def on_enter(_e):
        if btn._enabled:
            btn.configure(bg=btn._bg_hover)

    def on_leave(_e):
        btn.configure(bg=(btn._bg_normal if btn._enabled else btn._bg_disabled))

    def on_click(_e):
        if btn._enabled:
            command()

    btn.bind("<Enter>", on_enter)
    btn.bind("<Leave>", on_leave)
    btn.bind("<Button-1>", on_click)
    return btn


def set_button_enabled(btn, enabled):
    btn._enabled = enabled
    if enabled:
        btn.configure(bg=btn._bg_normal, fg=btn._fg_normal, cursor="hand2")
    else:
        btn.configure(bg=btn._bg_disabled, fg=btn._fg_disabled, cursor="arrow")


# ----------------------------------------------------------------------
# Application principale
# ----------------------------------------------------------------------

class LauncherApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Azeroth Universe Launcher - Mode de secours")
        self.geometry("920x600+200+100")
        self.configure(bg=COLOR_BORDER)
        self.resizable(False, False)
        self.overrideredirect(True)
        self.bind("<Map>", self._on_map)

        cfg = load_config()
        self.install_dir = cfg.get("install_dir") or os.path.join(base_dir(), DEFAULT_SUBFOLDER)
        self.config_data = cfg

        self.manifest = None
        self.files_to_update = []
        self.total_bytes_to_download = 0
        self.bytes_downloaded = 0
        self.downloaded_count = 0
        self.is_working = False
        self.cancel_event = threading.Event()
        self.progress_queue = queue.Queue()
        self.speed_samples = []
        self.error_log = []
        self._drag = {"x": 0, "y": 0}

        self._build_ui()
        self.after(300, lambda: self.check_updates(auto_download=False))
        self._poll_queue()

    # ------------------------------------------------------------------
    # Construction de l'interface
    # ------------------------------------------------------------------

    def _build_ui(self):
        outer = tk.Frame(self, bg=COLOR_BORDER, bd=0)
        outer.pack(fill="both", expand=True, padx=1, pady=1)

        panel = tk.Frame(outer, bg=COLOR_PANEL)
        panel.pack(fill="both", expand=True)

        self._build_titlebar(panel)
        self._build_header(panel)
        self._build_install_row(panel)
        self._build_progress_section(panel)
        self._build_buttons_row(panel)

    def _build_titlebar(self, parent):
        bar = tk.Frame(parent, bg=COLOR_PANEL_2, height=34)
        bar.pack(fill="x", side="top")
        bar.pack_propagate(False)

        title = tk.Label(
            bar, text="AZEROTH UNIVERSE - LAUNCHER (MODE DE SECOURS)", bg=COLOR_PANEL_2,
            fg=COLOR_GOLD, font=("Segoe UI", 9, "bold")
        )
        title.pack(side="left", padx=12)

        for widget in (bar, title):
            widget.bind("<ButtonPress-1>", self._start_move)
            widget.bind("<B1-Motion>", self._do_move)

        close_btn = tk.Label(
            bar, text="✕", bg=COLOR_PANEL_2, fg=COLOR_TEXT_DIM,
            font=("Segoe UI", 11), padx=12, cursor="hand2"
        )
        close_btn.pack(side="right", fill="y")
        close_btn.bind("<Enter>", lambda e: close_btn.configure(bg=COLOR_RED, fg="white"))
        close_btn.bind("<Leave>", lambda e: close_btn.configure(bg=COLOR_PANEL_2, fg=COLOR_TEXT_DIM))
        close_btn.bind("<Button-1>", lambda e: self.on_close())

        min_btn = tk.Label(
            bar, text="-", bg=COLOR_PANEL_2, fg=COLOR_TEXT_DIM,
            font=("Segoe UI", 11), padx=12, cursor="hand2"
        )
        min_btn.pack(side="right", fill="y")
        min_btn.bind("<Enter>", lambda e: min_btn.configure(bg="#2a2314", fg=COLOR_GOLD))
        min_btn.bind("<Leave>", lambda e: min_btn.configure(bg=COLOR_PANEL_2, fg=COLOR_TEXT_DIM))
        min_btn.bind("<Button-1>", lambda e: self.minimize())

    def _start_move(self, event):
        self._drag["x"] = event.x
        self._drag["y"] = event.y

    def _do_move(self, event):
        x = self.winfo_pointerx() - self._drag["x"]
        y = self.winfo_pointery() - self._drag["y"]
        self.geometry(f"+{x}+{y}")

    def minimize(self):
        # Astuce classique pour minimiser une fenêtre sans bordure (overrideredirect)
        self.overrideredirect(False)
        self.iconify()

    def _on_map(self, _event=None):
        # Ré-applique le mode sans bordure quand la fenêtre est restaurée
        if self.state() == "normal":
            self.overrideredirect(True)

    def _build_header(self, parent):
        header = tk.Frame(parent, bg=COLOR_PANEL)
        header.pack(fill="x", padx=30, pady=(22, 10))

        tk.Label(
            header, text="AZEROTH UNIVERSE", bg=COLOR_PANEL,
            fg=COLOR_GOLD_LIGHT, font=FONT_TITLE
        ).pack(anchor="w")

        self.info_var = tk.StringVar(value="Client 3.3.5a - Mode de secours - Connexion à GitHub…")
        tk.Label(
            header, textvariable=self.info_var, bg=COLOR_PANEL,
            fg=COLOR_TEXT_DIM, font=FONT_SUB
        ).pack(anchor="w", pady=(2, 0))

        sep = tk.Frame(parent, bg=COLOR_BORDER, height=1)
        sep.pack(fill="x", padx=30, pady=(12, 4))

    def _build_install_row(self, parent):
        row = tk.Frame(parent, bg=COLOR_PANEL)
        row.pack(fill="x", padx=30, pady=(14, 6))

        tk.Label(
            row, text="Emplacement du client :", bg=COLOR_PANEL,
            fg=COLOR_TEXT_DIM, font=FONT_BODY
        ).pack(side="top", anchor="w")

        path_row = tk.Frame(row, bg=COLOR_PANEL)
        path_row.pack(fill="x", pady=(4, 0))

        self.install_dir_var = tk.StringVar(value=self.install_dir)
        entry = tk.Entry(
            path_row, textvariable=self.install_dir_var, state="readonly",
            readonlybackground=COLOR_PANEL_2, fg=COLOR_TEXT, relief="flat",
            font=FONT_BODY, highlightthickness=1,
            highlightbackground=COLOR_BORDER, highlightcolor=COLOR_GOLD,
        )
        entry.pack(side="left", fill="x", expand=True, ipady=6, padx=(0, 10))

        browse_btn = make_button(path_row, "Parcourir…", self.choose_install_dir, small=True)
        browse_btn.pack(side="left")

    def _build_progress_section(self, parent):
        section = tk.Frame(parent, bg=COLOR_PANEL)
        section.pack(fill="x", padx=30, pady=(18, 6))

        self.status_var = tk.StringVar(value="Prêt.")
        tk.Label(
            section, textvariable=self.status_var, bg=COLOR_PANEL,
            fg=COLOR_TEXT, font=FONT_BODY, anchor="w"
        ).pack(fill="x", anchor="w")

        self.current_file_var = tk.StringVar(value="")
        tk.Label(
            section, textvariable=self.current_file_var, bg=COLOR_PANEL,
            fg=COLOR_TEXT_DIM, font=FONT_SMALL, anchor="w"
        ).pack(fill="x", anchor="w", pady=(2, 8))

        self.progress_bar = GoldProgressBar(section, width=858, height=24)
        self.progress_bar.pack(fill="x")

        stats_row = tk.Frame(section, bg=COLOR_PANEL)
        stats_row.pack(fill="x", pady=(10, 0))

        self.files_var = tk.StringVar(value="0 / 0 fichiers")
        self.speed_var = tk.StringVar(value="0 Ko/s")
        self.eta_var = tk.StringVar(value="--:--")

        self._stat_block(stats_row, "Fichiers", self.files_var).pack(side="left", padx=(0, 30))
        self._stat_block(stats_row, "Vitesse", self.speed_var).pack(side="left", padx=(0, 30))
        self._stat_block(stats_row, "Temps restant", self.eta_var).pack(side="left")

    def _stat_block(self, parent, label, var):
        block = tk.Frame(parent, bg=COLOR_PANEL)
        tk.Label(
            block, text=label.upper(), bg=COLOR_PANEL, fg=COLOR_TEXT_DIM,
            font=("Segoe UI", 8, "bold")
        ).pack(anchor="w")
        tk.Label(
            block, textvariable=var, bg=COLOR_PANEL, fg=COLOR_GOLD,
            font=("Segoe UI", 12, "bold")
        ).pack(anchor="w")
        return block

    def _build_buttons_row(self, parent):
        footer = tk.Frame(parent, bg=COLOR_PANEL)
        footer.pack(fill="x", side="bottom", padx=30, pady=22)

        left = tk.Frame(footer, bg=COLOR_PANEL)
        left.pack(side="left")
        make_button(left, "Site Web", lambda: webbrowser.open(WEBSITE_URL)).pack(side="left", padx=(0, 10))
        make_button(left, "Inscription", lambda: webbrowser.open(REGISTER_URL)).pack(side="left")

        right = tk.Frame(footer, bg=COLOR_PANEL)
        right.pack(side="right")
        self.check_btn = make_button(right, "Vérifier les mises à jour", lambda: self.check_updates(False))
        self.check_btn.pack(side="left", padx=(0, 10))
        self.update_btn = make_button(right, "⚔  METTRE À JOUR", self.start_update, primary=True)
        self.update_btn.pack(side="left")

    # ------------------------------------------------------------------
    # Actions utilisateur
    # ------------------------------------------------------------------

    def choose_install_dir(self):
        path = filedialog.askdirectory(
            initialdir=self.install_dir if os.path.isdir(self.install_dir) else base_dir(),
            title="Choisir le dossier d'installation du client",
        )
        if path:
            self.install_dir = path
            self.install_dir_var.set(path)
            self.config_data["install_dir"] = path
            save_config(self.config_data)
            self.set_status("Dossier d'installation mis à jour.")
            # Un changement de dossier invalide la précédente analyse
            self.files_to_update = []
            self.progress_bar.set_ratio(0.0)

    def check_updates(self, auto_download):
        if self.is_working:
            return
        self.is_working = True
        set_button_enabled(self.update_btn, False)
        set_button_enabled(self.check_btn, False)
        self.set_status("Connexion à GitHub — récupération des informations sur les fichiers…")
        self.current_file_var.set("")
        threading.Thread(target=self._check_updates_thread, args=(auto_download,), daemon=True).start()

    def _check_updates_thread(self, auto_download):
        try:
            manifest = build_manifest()
        except Exception as exc:
            self.progress_queue.put(("error", f"Connexion à GitHub impossible : {exc}"))
            return
        self.manifest = manifest
        try:
            os.makedirs(self.install_dir, exist_ok=True)
        except OSError as exc:
            self.progress_queue.put(("error", f"Dossier d'installation invalide : {exc}"))
            return
        to_update = scan_updates(manifest, self.install_dir)
        self.progress_queue.put(("scan_done", to_update, auto_download))

    def start_update(self):
        if self.is_working:
            return
        if self.files_to_update:
            self._begin_download()
        else:
            # Relance une vérification, puis démarre automatiquement le
            # téléchargement si des fichiers sont manquants/obsolètes.
            self.check_updates(auto_download=True)

    def _begin_download(self):
        self.is_working = True
        set_button_enabled(self.update_btn, False)
        set_button_enabled(self.check_btn, False)
        self.cancel_event.clear()
        self.bytes_downloaded = 0
        self.downloaded_count = 0
        self.error_log = []
        self.total_bytes_to_download = sum(e.get("size", 0) for e in self.files_to_update)
        self.speed_samples = [(time.time(), 0)]
        self.files_var.set(f"0 / {len(self.files_to_update)} fichiers")
        self.set_status("Téléchargement en cours…")

        downloader = Downloader(self.install_dir, self.files_to_update, self.progress_queue, self.cancel_event)
        threading.Thread(target=downloader.run, daemon=True).start()

    def set_status(self, text):
        self.status_var.set(text)

    def _show_error_report(self):
        """
        Affiche le détail des échecs (fichier + raison exacte) pour
        pouvoir distinguer un vrai problème réseau (timeout, connexion
        réinitialisée) d'une Release GitHub manquante (404 Not Found).
        """
        if not self.error_log:
            return
        lines = [f"• {path} → {reason}" for path, reason in self.error_log[:20]]
        if len(self.error_log) > 20:
            lines.append(f"… et {len(self.error_log) - 20} autre(s).")
        detail = "\n".join(lines)

        not_found = sum(1 for _, reason in self.error_log if "404" in reason or "Not Found" in reason)
        hint = ""
        if not_found:
            hint = (
                f"\n\n{not_found} fichier(s) semblent renvoyer une erreur 404 (Release "
                "GitHub introuvable) : vérifiez que ces Releases existent bien sur GitHub, "
                "avec un tag et un nom d'asset identiques au nom du fichier."
            )

        messagebox.showwarning(
            "Détail des échecs de téléchargement",
            f"{len(self.error_log)} fichier(s) ont échoué :\n\n{detail}{hint}",
        )

    # ------------------------------------------------------------------
    # Boucle de traitement des événements de fond (thread-safe via Queue)
    # ------------------------------------------------------------------

    def _poll_queue(self):
        try:
            while True:
                item = self.progress_queue.get_nowait()
                kind = item[0]

                if kind == "bytes":
                    self.bytes_downloaded += item[1]

                elif kind == "file_done":
                    self.downloaded_count += 1
                    self.current_file_var.set(f"Terminé : {item[1]}")

                elif kind == "file_error":
                    self.downloaded_count += 1
                    self.error_log.append((item[1], item[2]))
                    self.current_file_var.set(f"Erreur sur {item[1]} - nouvel essai possible via 'Mettre à jour'")

                elif kind == "status":
                    self.current_file_var.set(item[1])

                elif kind == "scan_done":
                    self._handle_scan_done(item[1], item[2])

                elif kind == "error":
                    self.is_working = False
                    set_button_enabled(self.update_btn, True)
                    set_button_enabled(self.check_btn, True)
                    self.set_status(f"⚠ {item[1]}")
                    messagebox.showerror("Azeroth Universe", item[1])

                elif kind == "all_done":
                    self.is_working = False
                    set_button_enabled(self.update_btn, True)
                    set_button_enabled(self.check_btn, True)
                    if self.cancel_event.is_set():
                        self.set_status("Mise à jour annulée.")
                    else:
                        # On revérifie sur le disque plutôt que de supposer
                        # que tout a réussi : certains fichiers peuvent
                        # avoir échoué même après les tentatives de retry.
                        remaining = scan_updates(self.manifest, self.install_dir) if self.manifest else []
                        self.files_to_update = remaining
                        self.current_file_var.set("")
                        if remaining:
                            missing_size = sum(e.get("size", 0) for e in remaining)
                            self.progress_bar.set_ratio(0.0)
                            self.files_var.set(f"0 / {len(remaining)} fichiers")
                            self.set_status(
                                f"⚠ {len(remaining)} fichier(s) n'ont pas pu être téléchargés "
                                f"({human_size(missing_size)}). Cliquez sur 'Mettre à jour' pour réessayer."
                            )
                            self._show_error_report()
                        else:
                            self.progress_bar.set_ratio(1.0)
                            self.set_status("✅ Mise à jour terminée ! Client prêt à jouer.")
        except queue.Empty:
            pass

        if self.total_bytes_to_download > 0 and self.is_working:
            ratio = self.bytes_downloaded / self.total_bytes_to_download
            self.progress_bar.set_ratio(ratio)
            self.files_var.set(f"{self.downloaded_count} / {len(self.files_to_update)} fichiers")

            now = time.time()
            self.speed_samples.append((now, self.bytes_downloaded))
            self.speed_samples = [s for s in self.speed_samples if now - s[0] <= SPEED_WINDOW_SECONDS]
            if len(self.speed_samples) >= 2:
                t0, b0 = self.speed_samples[0]
                dt = now - t0
                speed = (self.bytes_downloaded - b0) / dt if dt > 0 else 0
            else:
                speed = 0
            self.speed_var.set(f"{human_size(speed)}/s")

            remaining = max(0, self.total_bytes_to_download - self.bytes_downloaded)
            eta = (remaining / speed) if speed > 0 else float("inf")
            self.eta_var.set(human_time(eta))

        self.after(150, self._poll_queue)

    def _handle_scan_done(self, to_update, auto_download):
        self.is_working = False
        set_button_enabled(self.update_btn, True)
        set_button_enabled(self.check_btn, True)
        self.files_to_update = to_update

        total_files = len(self.manifest.get("files", [])) if self.manifest else 0
        total_size = self.manifest.get("total_size", 0) if self.manifest else 0
        version = self.manifest.get("version", "?") if self.manifest else "?"
        self.info_var.set(f"Client {version} - {total_files} fichiers - {human_size(total_size)}")

        if not to_update:
            self.progress_bar.set_ratio(1.0)
            self.files_var.set(f"{total_files} / {total_files} fichiers")
            self.speed_var.set("0 Ko/s")
            self.eta_var.set("--:--")
            self.set_status("✅ Le client est déjà à jour.")
        else:
            missing_size = sum(e.get("size", 0) for e in to_update)
            self.progress_bar.set_ratio(0.0)
            self.files_var.set(f"0 / {len(to_update)} fichiers")
            self.set_status(f"{len(to_update)} fichier(s) à télécharger ({human_size(missing_size)}).")

            needs_rar = any(e.get("type") == "rar_parts" for e in to_update)
            if needs_rar and not find_unrar_exe():
                messagebox.showwarning(
                    "UnRAR introuvable",
                    "Certains patchs volumineux sont publiés en plusieurs parties RAR "
                    "et nécessitent UnRAR pour être reconstitués après téléchargement.\n\n"
                    "Installez WinRAR, ou placez UnRAR.exe à côté du launcher, puis "
                    "relancez la mise à jour.\n\nTéléchargement : https://www.rarlab.com/rar_add.htm"
                )

            if auto_download:
                self._begin_download()

    # ------------------------------------------------------------------
    # Fermeture
    # ------------------------------------------------------------------

    def on_close(self):
        if self.is_working:
            if not messagebox.askyesno(
                "Azeroth Universe",
                "Une mise à jour est en cours. Voulez-vous vraiment quitter ?"
            ):
                return
            self.cancel_event.set()
        self.destroy()


# ----------------------------------------------------------------------
# Point d'entrée
# ----------------------------------------------------------------------

def main():
    app = LauncherApp()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()


if __name__ == "__main__":
    main()
