# UniverseUpdater

Utilitaire officiel d'installation et de mise à jour du client **Azeroth Universe** pour macOS.

Il permet aux joueurs de :
- télécharger et installer le client de jeu complet en un clic
- mettre à jour automatiquement tous les patchs (`Data/` et `Data/frFR/`) sans manipulation manuelle

> Pour Windows, voir le launcher dédié **Azeroth Launcher**.

---

## ✨ Fonctionnalités

- Téléchargement du client complet (`AzerothUniverse_platform_Mac.zip`) et extraction automatique
- Téléchargement et remplacement de tous les patchs `.MPQ` (dossier `Data/` et `Data/frFR/`)
- Barre de progression en temps réel pour chaque téléchargement
- Nouvelles tentatives automatiques en cas d'échec réseau (3 essais par fichier)
- Aucune dépendance externe (bibliothèque standard Python uniquement)
- Détection automatique du dossier racine du jeu (fonctionne où que l'app soit placée)

---

## 📦 Installation (joueurs)

1. Télécharger la dernière version depuis l'onglet [Releases](../../releases)
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

### ⚠️ Premier lancement sur macOS

Le binaire n'étant pas signé (pas de compte Apple Developer), macOS Gatekeeper le bloquera au premier lancement.

Solution : **clic-droit sur l'application → Ouvrir**, puis confirmer. Cette étape n'est nécessaire qu'une seule fois.

---

## 🗂️ Structure du dépôt

```
UniverseUpdater/
├── .github/workflows/
│   └── build-mac.yml        # Build automatique macOS (+ Release si tag "v*")
├── azeroth_updater.py        # Script principal
├── icon.png                  # Icône source (convertie en .icns par la CI)
├── icon.ico                  # Icône pour la version Windows
└── README.md
```

---

## 🛠️ Compilation depuis les sources

### macOS (recommandé via GitHub Actions)

Le workflow `.github/workflows/build-mac.yml` compile automatiquement l'application macOS :

- à chaque push sur `main` (build de test, disponible en *Artifact* pendant 90 jours)
- à chaque push d'un tag `vX.Y.Z` (build **+ publication automatique en Release**)

Publier une nouvelle version :

```bash
git tag v1.0.0
git push origin v1.0.0
```

Le binaire est ensuite disponible dans l'onglet [Releases](../../releases).

#### Build manuel (sur un Mac)

```bash
pip3 install pyinstaller
pyinstaller --onefile --console --name "AzerothUniverseUpdater" --icon=AzerothUniverse.icns azeroth_updater.py
```

### Windows

```bash
pip install pyinstaller
pyinstaller --onefile --console --name "AzerothUniverseUpdater" --icon=icon.ico azeroth_updater.py
```

Le binaire compilé se trouve dans `dist/`.

---

## ⚙️ Configuration

Les URLs de téléchargement et la liste des patchs sont définies en tête du fichier `azeroth_updater.py` :

```python
CLIENT_ZIP_URL = "https://azeroth-universe.eu/uploads/client/AzerothUniverse_platform_Mac.zip"
PATCH_BASE_ROOT = "https://azeroth-universe.eu/universe_client/Data"
PATCH_BASE_FRFR = "https://azeroth-universe.eu/universe_client/Data/frFR"

ROOT_PATCHES = [...]
FRFR_PATCHES = [...]
```

Pour ajouter, renommer ou retirer un patch, il suffit de modifier les listes `ROOT_PATCHES` / `FRFR_PATCHES`.

---

## 📄 Licence

Projet interne à **Azeroth Universe**. Tous droits réservés.
