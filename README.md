# UniverseUpdater

Utilitaires officiels d'installation et de mise à jour du client **Azeroth Universe**, pour **macOS** et **Windows**.

Il permet aux joueurs de :
- télécharger et installer le client de jeu (complet ou par fichier, selon la plateforme)
- mettre à jour automatiquement le client sans manipulation manuelle

> Sous Windows, deux options existent : le **Launcher Azeroth Universe** complet (application WPF, projet séparé) et le **Mini Launcher** (script Python présent dans ce dépôt), une alternative légère sans dépendance externe. Un **Launcher d'urgence** est également disponible en secours si l'hébergement principal est indisponible : il télécharge le client directement depuis les Releases GitHub.

---

## ✨ Fonctionnalités

### 🍏 macOS — `azeroth_updater_mac.py`
- Téléchargement du client complet (`AzerothUniverse_platform_Mac.zip`) et extraction automatique
- Téléchargement et remplacement de tous les patchs `.MPQ` (dossier `Data/` et `Data/frFR/`)
- Barre de progression en temps réel pour chaque téléchargement
- Nouvelles tentatives automatiques en cas d'échec réseau (3 essais par fichier)
- Détection automatique du dossier racine du jeu (fonctionne où que l'app soit placée)
- Aucune dépendance externe (bibliothèque standard Python uniquement)

### 🪟 Windows — `azeroth_launcher_win.py`
- Interface graphique dans l'esprit World of Warcraft (Tkinter, fond sombre, dorures)
- Récupère le manifeste du client (liste complète des fichiers, tailles et empreintes) depuis le serveur
- Compare automatiquement le contenu local au manifeste et ne télécharge que les fichiers manquants ou obsolètes
- Téléchargements en parallèle (4 threads), avec vitesse et temps restant affichés en direct
- Choix du dossier d'installation via une interface (mémorisé entre les lancements)
- Boutons intégrés : vérifier les mises à jour, mettre à jour, site web, inscription
- Aucune dépendance externe (bibliothèque standard Python + Tkinter uniquement)

### 🚨 Windows (secours) — `azeroth_launcher_emergency.py`
- Même interface et même logique que le Mini Launcher, à utiliser si l'hébergement principal (azeroth-universe.eu) est indisponible
- Ne dépend d'aucun serveur : télécharge directement depuis les Releases du dépôt GitHub [`UniverseClient`](https://github.com/AzerothUniverseCore/UniverseClient/releases)
- Détecte automatiquement, pour chaque patch, s'il s'agit d'un asset unique ou d'un patch volumineux scindé en plusieurs volumes RAR (`.part1.rar`/`.part01.rar`, les deux conventions de nommage sont gérées)
- Reconstitue et extrait automatiquement les patchs multi-parties et les archives complémentaires (`AzerothUniverse.rar`, `Additional.rar`) via UnRAR
- Tentatives multiples avec délai progressif en cas d'échec réseau, et rapport détaillé (fichier + raison exacte) en cas d'échec persistant
- Nécessite **UnRAR** (voir [Configuration](#windows-secours)) pour l'extraction des patchs volumineux et des archives complémentaires

---

## 📦 Installation (joueurs)

### macOS

1. Télécharger la dernière version depuis l'onglet [Releases](../../releases) (tag `UniversePatcher`)
2. Placer `AzerothUniverseUpdater` à la racine du dossier du jeu, à côté de `Data/` :

   ```
   AzerothUniverse/
   ├── AzerothUniverseUpdater
   ├── Data/
   │   └── frFR/
   └── ...
   ```

3. Lancer l'application
4. Choisir dans le menu :
   - **1** — Installation complète (client + patchs)
   - **2** — Mise à jour des patchs uniquement

#### ⚠️ Premier lancement sur macOS

Le binaire n'étant pas signé (pas de compte Apple Developer), macOS Gatekeeper le bloquera au premier lancement.

Solution : **clic-droit sur l'application → Ouvrir**, puis confirmer. Cette étape n'est nécessaire qu'une seule fois.

### Windows

1. Télécharger la dernière version depuis l'onglet [Releases](../../releases) (tag `UniverseMiniLauncher`)
2. Placer `AzerothLauncher.exe` où vous le souhaitez (il n'a pas besoin d'être à la racine du jeu)
3. Lancer l'application
4. Au premier lancement, cliquer sur **Parcourir…** pour choisir le dossier d'installation du client
5. Cliquer sur **Vérifier les mises à jour**, puis **Mettre à jour** pour télécharger le client

#### ⚠️ Premier lancement sur Windows

Le binaire n'étant pas signé (pas de certificat de signature de code), Windows SmartScreen peut afficher un avertissement au premier lancement.

Solution : cliquer sur **Informations complémentaires → Exécuter quand même**. Cette étape n'est nécessaire qu'une seule fois.

### Windows (secours)

À utiliser uniquement si le launcher standard ne fonctionne pas (hébergement principal indisponible).

1. Télécharger `AzerothLauncherUrgence.exe` depuis l'onglet [Actions](../../actions) (Artifact) ou [Releases](../../releases)
2. Si l'exécutable n'embarque pas déjà UnRAR (voir [Configuration](#windows-secours)), placer `UnRAR.exe` dans le même dossier que `AzerothLauncherUrgence.exe`
3. Lancer l'application et suivre les mêmes étapes que le launcher standard (choix du dossier, Vérifier les mises à jour, Mettre à jour)

Certains patchs volumineux sont scindés en plusieurs volumes RAR sur GitHub : le launcher les télécharge et les reconstitue automatiquement, à condition qu'UnRAR soit disponible (message d'avertissement explicite sinon, avant tout téléchargement inutile).

---

## 🗂️ Structure du dépôt

```
UniverseUpdater/
├── .github/workflows/
│   ├── build-mac.yml               # Build automatique macOS
│   ├── build-win.yml               # Build automatique Windows (standard)
│   └── build-win-emergency.yml     # Build automatique Windows (secours)
├── azeroth_updater_mac.py          # Script principal macOS (console)
├── azeroth_launcher_win.py         # Script principal Windows (interface graphique)
├── azeroth_launcher_emergency.py   # Launcher de secours Windows (téléchargement direct GitHub)
├── icon.png                        # Icône source (convertie en .icns par la CI macOS)
├── icon.icns                       # Icône compilée pour macOS
├── icon.ico                        # Icône pour les versions Windows
├── UnRAR.exe                       # (optionnel) embarqué dans le launcher de secours si présent
└── README.md
```

---

## 🛠️ Compilation depuis les sources

### macOS (recommandé via GitHub Actions)

Le workflow `.github/workflows/build-mac.yml` compile automatiquement l'application macOS à chaque push sur `main`/`master` touchant `azeroth_updater_mac.py`, `icon.png` ou le workflow lui-même (build de test, disponible en *Artifact*), ou manuellement depuis l'onglet **Actions**.

#### Build manuel (sur un Mac)

```bash
pip3 install pyinstaller
pyinstaller --onefile --console --name "AzerothUniverseUpdater" --icon=AzerothUniverse.icns azeroth_updater_mac.py
```

### Windows (recommandé via GitHub Actions)

Le workflow `.github/workflows/build-win.yml` compile automatiquement le launcher Windows à chaque push sur `main`/`master` touchant `azeroth_launcher_win.py`, `icon.ico` ou le workflow lui-même (build de test, disponible en *Artifact*), ou manuellement depuis l'onglet **Actions**.

#### Build manuel (sur Windows)

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name "AzerothLauncher" --icon=icon.ico azeroth_launcher_win.py
```

Le binaire compilé se trouve dans `dist/`.

> Contrairement à la version macOS (application console), le launcher Windows est une interface graphique : on utilise `--windowed` pour éviter qu'une fenêtre de console noire ne s'ouvre derrière l'application.

### Windows - secours (recommandé via GitHub Actions)

Le workflow `.github/workflows/build-win-emergency.yml` compile automatiquement le launcher de secours à chaque push touchant `azeroth_launcher_emergency.py`, `icon.ico`, `UnRAR.exe` ou le workflow lui-même, ou manuellement depuis l'onglet **Actions**.

Si `UnRAR.exe` est présent à la racine du dépôt, il est automatiquement embarqué dans l'exécutable (`--add-binary`) : le launcher le retrouve alors tout seul au démarrage, sans installation séparée nécessaire côté joueur.

#### Build manuel (sur Windows)

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name "AzerothLauncherUrgence" --icon=icon.ico azeroth_launcher_emergency.py
```

Pour embarquer UnRAR.exe manuellement, ajouter `--add-binary "UnRAR.exe;."` à la commande.

---

## ⚙️ Configuration

### macOS

Les URLs de téléchargement et la liste des patchs sont définies en tête du fichier `azeroth_updater_mac.py` :

```python
CLIENT_ZIP_URL = "https://azeroth-universe.eu/uploads/client/AzerothUniverse_platform_Mac.zip"
PATCH_BASE_ROOT = "https://azeroth-universe.eu/universe_client/Data"
PATCH_BASE_FRFR = "https://azeroth-universe.eu/universe_client/Data/frFR"

ROOT_PATCHES = [...]
FRFR_PATCHES = [...]
```

Pour ajouter, renommer ou retirer un patch, il suffit de modifier les listes `ROOT_PATCHES` / `FRFR_PATCHES`.

### Windows

Les URLs sont définies en tête du fichier `azeroth_launcher_win.py` :

```python
MANIFEST_URL = "https://azeroth-universe.eu/manifest.php"
WEBSITE_URL = "https://azeroth-universe.eu"
REGISTER_URL = "https://azeroth-universe.eu/register"
```

Contrairement à la version macOS, la liste des fichiers n'est pas codée en dur : elle est récupérée dynamiquement depuis `MANIFEST_URL` (généré côté serveur), qui doit renvoyer un JSON de la forme :

```json
{
  "version": "3.3.5a",
  "total_size": 71468236800,
  "files": [
    { "path": "Data/common.MPQ", "url": "https://...", "size": 123456, "md5": "..." }
  ]
}
```

Pour ajouter, retirer ou modifier un fichier du client, il suffit de mettre à jour le manifeste côté serveur — aucun changement de code n'est nécessaire.

### Windows (secours)

Contrairement aux deux autres scripts, le launcher de secours ne dépend d'aucune configuration serveur : tout est codé en tête du fichier `azeroth_launcher_emergency.py`.

```python
GITHUB_RELEASES_BASE = "https://github.com/AzerothUniverseCore/UniverseClient/releases/download"

ROOT_PATCHES = [...]   # patchs du dossier Data/
FRFR_PATCHES = [...]   # patchs du dossier Data/frFR/
EXTRA_ARCHIVES = [...] # archives complémentaires (AzerothUniverse.rar, Additional.rar)
```

Pour chaque patch, le launcher suppose qu'une Release GitHub existe avec un tag identique au nom du fichier (ex. `patch-4.MPQ`). Il essaie d'abord l'asset unique de même nom ; si absent, il sonde automatiquement les volumes RAR multi-parties selon les deux conventions de nommage utilisées sur le dépôt (`.part1.rar`, `.part2.rar`... ou `.part01.rar`, `.part02.rar`...).

**Prérequis pour l'extraction — UnRAR** : les patchs multi-parties et les archives complémentaires sont des volumes RAR qui doivent être reconstitués après téléchargement. Le launcher recherche un exécutable UnRAR dans cet ordre :
1. à côté du launcher (`UnRAR.exe`)
2. embarqué dans l'exécutable si compilé avec `--add-binary` (voir [Compilation](#windows---secours-recommandé-via-github-actions))
3. dans les emplacements d'installation habituels de WinRAR
4. dans le PATH système

Téléchargement d'UnRAR (freeware, redistribuable) : https://www.rarlab.com/rar_add.htm

> ⚠️ Contrairement au Mini Launcher, toute modification de la liste des patchs (ajout, suppression, renommage) nécessite de mettre à jour ce script et de recompiler — il n'y a pas de manifeste serveur à synchroniser automatiquement.

---

## 📄 Licence

Projet interne à **Azeroth Universe**. Tous droits réservés.
