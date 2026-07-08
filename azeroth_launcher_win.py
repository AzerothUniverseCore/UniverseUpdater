#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Azeroth Universe - Launcher client (Windows)
========================================================

Ce launcher :
  1. Récupère le manifeste du client (liste complète des fichiers,
     tailles et empreintes) depuis le serveur.
  2. Compare le contenu du dossier d'installation local avec ce
     manifeste pour déterminer les fichiers manquants ou obsolètes.
  3. Télécharge directement (en parallèle) chaque fichier concerné,
     avec une interface graphique dans l'esprit World of Warcraft
     (fond sombre, dorures, barre de progression dégradée).

Aucune dépendance externe n'est nécessaire (uniquement la bibliothèque
standard Python + Tkinter), afin de simplifier la compilation en
exécutable Windows via PyInstaller.

Compilation (Windows) :
    pip install pyinstaller
    pyinstaller --onefile --windowed --name AzerothLauncher ^
                --icon=azeroth.ico azeroth_launcher.py

L'exécutable généré (dist/AzerothLauncher.exe) est prévu pour être
placé à la racine du dossier du jeu, ou dans un dossier séparé : au
premier lancement, l'utilisateur choisit lui-même le dossier
d'installation via le bouton "Parcourir...".
"""

import os
import sys
import json
import time
import queue
import threading
import webbrowser
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ----------------------------------------------------------------------
# Configuration - à adapter selon votre infrastructure
# ----------------------------------------------------------------------

# URL du manifeste JSON (généré côté serveur par generate_manifest.php,
# même structure que manifest_cache.json : {"files":[{"path","url",
# "size","md5","modified"}, ...]})
MANIFEST_URL = "https://azeroth-universe.eu/universe_launcher/manifest.php"

WEBSITE_URL = "https://azeroth-universe.eu"
REGISTER_URL = "https://azeroth-universe.eu/register"

CONFIG_FILE = "launcher_config.json"
DEFAULT_SUBFOLDER = "AzerothUniverse"

MAX_WORKERS = 4                 # téléchargements simultanés
CHUNK_SIZE = 1024 * 256         # 256 Ko par lecture réseau
SPEED_WINDOW_SECONDS = 5        # fenêtre glissante pour le calcul de vitesse

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

def fetch_manifest():
    """Télécharge et parse le manifeste JSON du client."""
    req = urllib.request.Request(
        MANIFEST_URL, headers={"User-Agent": "AzerothUniverseLauncher/2.0"}
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = resp.read()
    return json.loads(data.decode("utf-8"))


def scan_updates(manifest, install_dir):
    """
    Compare le manifeste avec le contenu local.
    Un fichier est considéré à télécharger s'il est absent ou si sa
    taille diffère de celle attendue (vérification rapide, cohérente
    avec le fonctionnement standard des launchers de clients WoW).
    """
    to_download = []
    for entry in manifest.get("files", []):
        rel = entry["path"].replace("/", os.sep)
        local_path = os.path.join(install_dir, rel)
        need = False
        if not os.path.isfile(local_path):
            need = True
        else:
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

    def _download_one(self, entry):
        if self.cancel_event.is_set():
            return
        rel_path = entry["path"].replace("/", os.sep)
        dest = os.path.join(self.install_dir, rel_path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        tmp = dest + ".part"
        url = entry["url"]
        req = urllib.request.Request(
            url, headers={"User-Agent": "AzerothUniverseLauncher/2.0"}
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp, open(tmp, "wb") as out:
                while True:
                    if self.cancel_event.is_set():
                        raise InterruptedError("Téléchargement annulé")
                    chunk = resp.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    out.write(chunk)
                    self.q.put(("bytes", len(chunk)))
            os.replace(tmp, dest)
            self.q.put(("file_done", entry["path"]))
        except Exception as exc:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            self.q.put(("file_error", entry["path"], str(exc)))

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
        self.title("Azeroth Universe Launcher")
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
            bar, text="AZEROTH UNIVERSE - LAUNCHER", bg=COLOR_PANEL_2,
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

        self.info_var = tk.StringVar(value="Client 3.3.5a - Connexion au serveur…")
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
        self.set_status("Vérification des mises à jour…")
        self.current_file_var.set("")
        threading.Thread(target=self._check_updates_thread, args=(auto_download,), daemon=True).start()

    def _check_updates_thread(self, auto_download):
        try:
            manifest = fetch_manifest()
        except Exception as exc:
            self.progress_queue.put(("error", f"Connexion au serveur impossible : {exc}"))
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
        self.total_bytes_to_download = sum(e.get("size", 0) for e in self.files_to_update)
        self.speed_samples = [(time.time(), 0)]
        self.files_var.set(f"0 / {len(self.files_to_update)} fichiers")
        self.set_status("Téléchargement en cours…")

        downloader = Downloader(self.install_dir, self.files_to_update, self.progress_queue, self.cancel_event)
        threading.Thread(target=downloader.run, daemon=True).start()

    def set_status(self, text):
        self.status_var.set(text)

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
                    self.current_file_var.set(f"Erreur sur {item[1]} - nouvel essai possible via 'Mettre à jour'")

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
                        self.progress_bar.set_ratio(1.0)
                        self.set_status("✅ Mise à jour terminée ! Client prêt à jouer.")
                        self.current_file_var.set("")
                        self.files_to_update = []
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
