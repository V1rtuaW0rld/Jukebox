# 🎵 WinJukeBox v0.9 - Guide d'Utilisation

Bienvenue dans WinJukeBox, votre gestionnaire de musique personnel conçu pour transformer votre collection de fichiers audio en une bibliothèque numérique élégante et intelligente.

## 🚀 Mise en route rapide

1. **Lancement** : Exécutez le serveur (généralement `python server.py`).
2. **Accès** : Ouvrez votre navigateur sur `http://localhost:8000`.
3. **Configuration** : Cliquez sur l'icône ⚙️ (Paramètres) pour définir le chemin de votre dossier musique, votre email MusicBrainz et votre clé API AcoustID.
4. **Indexation** : Lancez un **Deep System Scan** pour que l'application scanne et indexe toute votre musique dans la base de données.

---

## 🔍 Navigation et Recherche

WinJukeBox propose quatre modes de recherche situés en haut à gauche :
- **🎤 Artiste** : Recherche par nom d'artiste.
- **📀 Album** : Recherche par titre d'album.
- **🎵 Titre** : Recherche par nom de morceau.
- **📂 Explorateur** : Navigation directe dans vos dossiers physiques.

---

## 🏷️ Moteur de Taggage Intelligent (NOUVEAU)

Si vos fichiers manquent de noms, d'artistes ou de pochettes, WinJukeBox peut les identifier automatiquement.

1. Allez dans l'**Explorateur**.
2. Les dossiers/fichiers avec des icônes d'avertissement (⚠️, 🏷️, 📷) ont besoin d'attention.
3. Cliquez sur le bouton **Info** (📄) ou **Tag** sur un dossier/fichier.
4. **Analyse Acoustique** : L'app va "écouter" le fichier pour l'identifier via AcoustID.
5. **Suggestions** : Examinez les correspondances trouvées sur MusicBrainz/Discogs.
6. **Appliquer** : Validez pour écrire les tags directement dans vos fichiers et les renommer proprement (ex: `01 - Titre.mp3`).

---

## 🎧 Lecture et Playlist

- **Lecture Immédiate** : Cliquez sur le bouton ▶ d'un morceau ou d'un album.
- **File d'attente** : Utilisez le bouton ➕ pour ajouter des morceaux à votre playlist actuelle.
- **Panneau Playlist** : Cliquez sur l'icône liste en haut à droite pour gérer votre file d'attente (réorganiser, supprimer, vider).
- **Sortie Audio** : Cliquez sur 🔊 dans le header pour choisir sur quel périphérique du serveur le son doit sortir.
- **Lecture Locale** : Cliquez sur l'icône 📱 pour streamer la musique directement sur l'appareil avec lequel vous naviguez (téléphone, tablette, autre PC).

---

## ⚙️ Paramètres Avancés

- **Full Reindex** : À faire lors d'un premier lancement ou de gros changements.
- **Fast Update** : Scanne uniquement les nouveaux fichiers ajoutés (plus rapide).
- **Relais Audio** : Permet de synchroniser la lecture entre le serveur et votre navigateur.

---

*Note : Cette version 0.9 est une version de pré-diffusion. N'hésitez pas à faire des retours sur d'éventuels bugs !*
