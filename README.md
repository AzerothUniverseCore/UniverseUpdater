# UniverseUpdater

Utilitaires officiels d'installation et de mise à jour du client **Azeroth Universe**, pour **macOS** et **Windows**.

Il permet aux joueurs de :
- télécharger et installer le client de jeu (complet ou par fichier, selon la plateforme)
- mettre à jour automatiquement le client sans manipulation manuelle

> Sous Windows, deux options existent : le **Launcher Azeroth Universe** complet (application WPF, projet séparé) et le **Mini Launcher** (script Python présent dans ce dépôt), une alternative légère sans dépendance externe.

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

---

## 🗂️ Structure du dépôt

```
UniverseUpdater/
├── .github/workflows/
│   ├── build-mac.yml         # Build automatique macOS
│   └── build-win.yml         # Build automatique Windows
├── azeroth_updater_mac.py    # Script principal macOS (console)
├── azeroth_launcher_win.py   # Script principal Windows (interface graphique)
├── icon.png                  # Icône source (convertie en .icns par la CI macOS)
├── icon.icns                 # Icône compilée pour macOS
├── icon.ico                  # Icône pour la version Windows
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

---

## 📄 Licence

Projet interne à **Azeroth Universe**. Tous droits réservés.
