import os
import difflib
import difflib
import time
import subprocess
import json
import requests
import musicbrainzngs
import re
import mutagen
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TDRC
from mutagen.mp3 import MP3
from mutagen.asf import ASF

from dotenv import load_dotenv

import sys

# --- CONFIGURATION INITIALE ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")
load_dotenv(ENV_PATH)

if getattr(sys, 'frozen', False):
    # Si on est dans l'exe PyInstaller
    FPCALC_PATH = os.path.join(sys._MEIPASS, "fpcalc.exe")
else:
    # Si on est en dev (script python)
    FPCALC_PATH = os.path.join(BASE_DIR, "fpcalc.exe")

# Variables chargées dynamiquement
ACOUSTID_API_KEY = os.getenv("ACOUSTID_API_KEY", "hLiR6XeAeq")
MB_EMAIL = os.getenv("MUSICBRAINZ_EMAIL", "ddrtsdr@yahoo.fr")

musicbrainzngs.set_useragent("WinJukeBox", "1.0", MB_EMAIL)

def reload_config():
    """Recharge les variables depuis le fichier .env"""
    global ACOUSTID_API_KEY, MB_EMAIL
    load_dotenv(ENV_PATH, override=True)
    ACOUSTID_API_KEY = os.getenv("ACOUSTID_API_KEY", "hLiR6XeAeq")
    MB_EMAIL = os.getenv("MUSICBRAINZ_EMAIL", "ddrtsdr@yahoo.fr")
    musicbrainzngs.set_useragent("WinJukeBox", "1.0", MB_EMAIL)
    print(f"INFO: Config Tag rechargée. Email: {MB_EMAIL}")

def get_acoustid_data(filepath):
    if not filepath or not os.path.exists(filepath):
        return None
    try:
        result = subprocess.run([FPCALC_PATH, filepath], capture_output=True, text=True, check=True)
        duration = None
        fingerprint = None
        for line in result.stdout.splitlines():
            if line.startswith("DURATION="): duration = int(line.split("=")[1])
            elif line.startswith("FINGERPRINT="): fingerprint = line.split("=")[1]
    except Exception as e:
        print(f"Erreur fpcalc : {e}")
        return None

    url = "https://api.acoustid.org/v2/lookup"
    payload = {
        "client": ACOUSTID_API_KEY,
        "duration": duration,
        "fingerprint": fingerprint,
        "meta": "recordings releases releasegroups"
    }
    try:
        r = requests.post(url, data=payload)
        return r.json()
    except Exception:
        return None

def get_tracklist_from_mb_release(release_id):
    """Recupere la tracklist propre d'une release specifique avec Artiste/Album/Annee."""
    try:
        print(f"PIVOT: Recuperation tracklist MB Release: {release_id}...")
        data = musicbrainzngs.get_release_by_id(release_id, includes=["recordings", "artist-credits", "release-groups"])
        release = data['release']
        album_name = release.get('title')
        artist_name = release.get('artist-credit', [{}])[0].get('artist', {}).get('name')
        year = release.get('date', '')[:4] if release.get('date') else ''
        
        mediums = release.get('medium-list', [])
        
        tracklist = []
        global_track_index = 1
        for medium in mediums:
            for track in medium.get('track-list', []):
                raw_title = track.get('recording', {}).get('title', '???')
                
                # Split automatique si le titre contient " / "
                # On enlève les espaces autour du slash
                parts = [p.strip() for p in raw_title.split('/')]
                
                for part in parts:
                    tracklist.append({
                        "position": str(global_track_index),
                        "title": part,
                        "artist": artist_name,
                        "album": album_name,
                        "year": year,
                        "duration": (int(track.get('length', 0)) // 1000 if track.get('length') else 0) // len(parts)
                    })
                    global_track_index += 1
        return tracklist
    except Exception as e:
        print(f"ERREUR: MB Tracklist: {e}")
        return None

def get_best_release_from_group(mbid_group, target_track_count=None):
    """Pivot: Trouve la meilleure Release dans un Release Group."""
    try:
        print(f"PIVOT: Recherche releases pour le groupe: {mbid_group}...")
        t0 = time.time()
        # On demande les media pour avoir le track-count
        data = musicbrainzngs.browse_releases(release_group=mbid_group, includes=["media"])
        print(f"PIVOT: MusicBrainz query took {time.time()-t0:.2f}s")
        
        releases = data.get('release-list', [])
        
        if not releases:
            print("PIVOT: Aucune release trouvée dans ce groupe.")
            return None

        print(f"PIVOT: {len(releases)} versions d'album trouvées.")

        # Calculer le nombre de pistes pour chaque release
        release_counts = []
        for rel in releases:
            count = 0
            for medium in rel.get('medium-list', []):
                count += int(medium.get('track-count', 0))
            
            # Score de "Standard" : on pénalise les titres avec Deluxe, Bonus, Limited, etc.
            title = rel.get('title', '').lower()
            penalty = 0
            if any(x in title for x in ['deluxe', 'bonus', 'limited', 'special', 'expanded']):
                penalty = 100
            
            release_counts.append({
                "count": count,
                "rel": rel,
                "penalty": penalty
            })

        # Heuristique :
        # On cherche la version la plus stable (moins de pénalité)
        # Et parmi elles, celle qui se rapproche du compte local
        if target_track_count:
            print(f"PIVOT: Recherche version standard proche de {target_track_count} titres...")
            # On trie d'abord par pénalité, puis par proximité absolue au compte local
            release_counts.sort(key=lambda x: (x['penalty'], abs(x['count'] - target_track_count)))
            best = release_counts[0]
            print(f"MATCH: Version choisie '{best['rel'].get('title')}' avec {best['count']} titres (ID: {best['rel']['id']})")
            return best['rel']['id']

        # Par défaut : la moins pénalisée avec le plus de pistes
        release_counts.sort(key=lambda x: (x['penalty'], -x['count']))
        best = release_counts[0]
        return best['rel']['id']
    except Exception as e:
        print(f"ERREUR: Pivot MB: {e}")
        if 'releases' in locals() and releases:
            return releases[0]['id']
        return None

def get_tracklist_from_discogs(discogs_id):
    """Recupere la tracklist propre via l'API Discogs."""
    try:
        print(f"API: Recuperation tracklist DISCOGS ID: {discogs_id}...")
        url = f"https://api.discogs.com/releases/{discogs_id}"
        headers = {'User-Agent': 'WinJukeBox/1.0'}
        r = requests.get(url, headers=headers)
        if r.status_code != 200:
            print(f"ERREUR API DISCOGS: Status {r.status_code}")
            return None
        
        data = r.json()
        tracklist = []
        global_idx = 1
        for track in data.get('tracklist', []):
            raw_title = track.get('title', '???')
            parts = [p.strip() for p in raw_title.split('/')]
            
            for part in parts:
                tracklist.append({
                    "position": str(global_idx),
                    "title": part,
                    "artist": data.get('artists', [{}])[0].get('name', '???'),
                    "album": data.get('title', '???'),
                    "year": str(data.get('year', ''))
                })
                global_idx += 1
        return tracklist
    except Exception as e:
        print(f"ERREUR: Discogs API: {e}")
        return None

def get_tracklist_from_path(filepath):
    """Filet de securite: Extraction de l'Artiste/Album via le chemin et scan du dossier."""
    print("FALLBACK: Utilisation de l'analyse du chemin de fichier pour tout le dossier...")
    try:
        # On normalise le chemin
        abs_path = os.path.abspath(filepath)
        parts = abs_path.replace('\\', '/').split('/')
        
        # Structure attendue : .../Artiste/Album/Fichier.mp3
        if len(parts) >= 3:
            extracted_artist = parts[-3]
            extracted_album = parts[-2]
            
            print(f"INFO: Extraction réussie -> Artiste: {extracted_artist} | Album: {extracted_album}")
            
            # On scanne tout le dossier pour générer une tracklist "locale"
            folder = os.path.dirname(abs_path)
            local_files = [f for f in os.listdir(folder) if f.lower().endswith(('.mp3', '.wma', '.flac'))]
            local_files.sort()
            
            tracklist = []
            for i, filename in enumerate(local_files):
                # Nettoyage basique du titre (enlève "01-", ".mp3", etc.)
                clean_title = re.sub(r'^\d+[\s\-_.\s]*', '', filename)
                clean_title = clean_title.rsplit('.', 1)[0]
                
                tracklist.append({
                    "position": str(i + 1),
                    "title": clean_title,
                    "artist": extracted_artist,
                    "album": extracted_album
                })
            return tracklist
    except Exception as e:
        print(f"ERREUR Fallback Path : {e}")
    return None

def match_tracklists(local_files, remote_tracks):
    """Simule l'algorithme de matching avec verbosite."""
    print(f"\n--- ANALYSE DE CORRESPONDANCE ({len(local_files)} fichiers vs {len(remote_tracks)} titres) ---")
    results = []
    
    for i, local_file in enumerate(local_files):
        match = None
        # On utilise une logique de matching simple (par index ou nom)
        # Ici on simplifie pour le POC
        if i < len(remote_tracks):
            remote = remote_tracks[i]
            print(f"  [MATCH AUTO] {local_file:30}  <-->  {remote['title']} ({remote['artist']} - {remote['album']})")
            match = {"file": local_file, "suggested": remote['title'], "score": 95}
        else:
            print(f"  [SANS MATCH] {local_file}")
            match = {"file": local_file, "suggested": "???", "score": 0}
        results.append(match)
    return results

def get_local_files_from_dir(filepath):
    """Récupère la liste réelle des fichiers musicaux dans le dossier du fichier cible."""
    try:
        folder = os.path.dirname(filepath)
        files = [f for f in os.listdir(folder) if f.lower().endswith(('.mp3', '.wma', '.flac'))]
        return sorted(files)
    except Exception as e:
        print(f"Erreur lecture dossier : {e}")
        return []


def get_audio_duration(filepath):
    """Retourne la durée en secondes (int) d'un fichier audio local."""
    try:
        if filepath.lower().endswith(".mp3"):
            audio = MP3(filepath)
            return int(audio.info.length)
        elif filepath.lower().endswith(".wma"):
            audio = ASF(filepath)
            return int(audio.info.length)
    except Exception:
        pass
    return 0

def match_files_to_tracks(local_files_paths, web_tracks):
    """
    Associe intelligemment les fichiers locaux aux pistes Web.
    Stratégie Hybride : Durée (prioritaire) > Fuzzy Name (fallback).
    Retourne une liste de PAIRES alignée sur l'ordre Web.
    """
    import difflib
    
    # Structure de sortie : Liste de dicts
    # [ { "track": {...}, "file": "chemin/vers/file.mp3", "match_type": "duration|fuzzy|none", "score": 90 }, ... ]
    
    # On travaille sur des copies pour ne pas modifier les listes originales pendant l'itération
    available_files = local_files_paths[:]
    
    # Dictionnaire de metadata locales pour éviter de ré-ouvrir 50 fois les fichiers
    local_meta = {}
    for f in available_files:
        local_meta[f] = {
            "name": os.path.basename(f),
            "duration": get_audio_duration(f)
        }

    # ---------------------------------------------------------
    # ÉTAPE 1 : MATCHING EXACT PAR DURÉE (+/- 2 sec)
    # ---------------------------------------------------------
    duration_tolerance = 2 # secondes
    
    # On itère sur les pistes web pour leur trouver un candidat
    matches = {} 

    for idx, track in enumerate(web_tracks):
        web_duration = track.get("duration", 0)
        if web_duration == 0: continue

        candidates = []
        for f in available_files:
            local_dur = local_meta[f]["duration"]
            if abs(local_dur - web_duration) <= duration_tolerance:
                candidates.append(f)
        
        # Si un seul candidat unique match par la durée, on le prend !
        if len(candidates) >= 1:
            best_candidate = candidates[0]
            if len(candidates) > 1:
                # Fuzzy match pour départager
                best_score = 0
                track_title = track.get("title", "").lower()
                for c in candidates:
                     score = difflib.SequenceMatcher(None, track_title, os.path.basename(c).lower()).ratio()
                     if score > best_score:
                         best_score = score
                         best_candidate = c
            
            matches[idx] = {"file": best_candidate, "type": "duration", "score": 100}

    # On retire les fichiers matchés de la liste des dispo
    for idx, match in matches.items():
        if match["file"] in available_files:
            available_files.remove(match["file"])

    # ---------------------------------------------------------
    # ÉTAPE 2 : FUZZY MATCHING SUR LE RESTE (TITRE)
    # ---------------------------------------------------------
    for idx, track in enumerate(web_tracks):
        # Si déjà matché par durée, on passe
        if idx in matches: continue

        track_title = track.get("title", "").lower()
        
        best_file = None
        best_score = 0.0

        for f in available_files:
            filename = os.path.basename(f).lower()
            # Nettoyage
            clean_name = re.sub(r'^\d+\s*[-_.]?\s*', '', os.path.splitext(filename)[0])
            
            score = difflib.SequenceMatcher(None, track_title, clean_name).ratio()
            
            if score > best_score:
                best_score = score
                best_file = f
        
        # Seuil de tolérance (ex: 40% de ressemblance mini)
        if best_score > 0.4:
             matches[idx] = {"file": best_file, "type": "fuzzy", "score": int(best_score * 100)}
             available_files.remove(best_file)

    # ---------------------------------------------------------
    # CONSTRUCTION DE LA SORTIE FINALE
    # ---------------------------------------------------------
    final_pairs = []
    
    for idx, track in enumerate(web_tracks):
        match_data = matches.get(idx)
        
        # Si on a un match, on l'utilise. Sinon None.
        matched_file_path = match_data["file"] if match_data else None
        
        # Le frontend attend le NOM SEUL du fichier, pas le path complet
        matched_filename = os.path.basename(matched_file_path) if matched_file_path else None
        
        pair = {
            "track": track,
            "file": matched_filename, 
            "match_type": match_data["type"] if match_data else "none",
            "score": match_data["score"] if match_data else 0,
            "track_number": idx + 1 # 1-based index
        }
        final_pairs.append(pair)

    # On ajoute les Orphelins à la fin (Fichiers qui n'ont matché personne)
    for f in available_files:
        final_pairs.append({
            "track": None, # Pas de piste Web
            "file": os.path.basename(f),
            "match_type": "orphan",
            "score": 0,
            "track_number": None
        })
        
    return final_pairs

def poc_engine(filepath, manual_discogs_id=None, target_track_count=None, mbid_album=None, force_path_fallback=False):
    print(f"\n--- DEMARRAGE DU PIPELINE LOGIQUE ---")
    print(f"Fichier source : {filepath}")

    # 0. OPTION : FORCE PATH FALLBACK (Sauter tout le reste)
    if force_path_fallback:
        print("\nEtape 0 : Forçage de l'analyse locale via le chemin (Dossier/Album)")
        return get_tracklist_from_path(filepath)
    
    # 1. PRIORITÉ : MBID MANUEL (RELEASE OU RELEASE-GROUP)
    if mbid_album:
        print(f"\nEtape 1 : Utilisation du MBID manuel fourni : {mbid_album}")
        # Est-ce une Release directe ?
        try:
            tracklist = get_tracklist_from_mb_release(mbid_album)
            if tracklist:
                print(f"SUCCES: ID reconnu comme Release directe. {len(tracklist)} titres.")
                return tracklist
        except:
            pass

        # Sinon, est-ce un Release-Group ?
        release_id = get_best_release_from_group(mbid_album, target_track_count)
        if release_id:
            tracklist = get_tracklist_from_mb_release(release_id)
            if tracklist:
                print(f"SUCCES: {len(tracklist)} titres recuperes sur MusicBrainz (via pivot).")
                return tracklist

    # 2. PRIORITÉ : DISCOGS MANUEL
    if manual_discogs_id:
        print(f"\nEtape 2 : Utilisation de l'ID Discogs manuel fourni : {manual_discogs_id}")
        tracklist = get_tracklist_from_discogs(manual_discogs_id)
        if tracklist:
            print(f"SUCCES: {len(tracklist)} titres recuperes via Discogs.")
            return tracklist

    # 3. IDENTIFICATION AUTOMATIQUE (ACOUSTID)
    print("\nEtape 3 : Identification acoustique automatique (AcoustID)...")
    res = get_acoustid_data(filepath)
    if res and res.get('results'):
        best_res = res['results'][0]
        rec = best_res.get('recordings', [{}])[0]
        mbid_discovered = rec.get('releasegroups', [{}])[0].get('id')
        if mbid_discovered:
            print(f"OK: MBID identifie via AcoustID : {mbid_discovered}")
            release_id = get_best_release_from_group(mbid_discovered, target_track_count)
            if release_id:
                tracklist = get_tracklist_from_mb_release(release_id)
                if tracklist:
                    return tracklist

    # 4. FALLBACK PATH (Analyse locale)
    print(f"\nEtape 4 : Utilisation du filet de securite (Analyse locale)...")
    return get_tracklist_from_path(filepath)

def apply_metadata_to_file(filepath, metadata):
    """Écrit les métadonnées dans le fichier audio via Mutagen."""
    try:
        if not os.path.exists(filepath):
            return False, "Fichier introuvable"

        if filepath.lower().endswith('.mp3'):
            audio = MP3(filepath, ID3=ID3)
            
            # Si le fichier n'a pas de tag ID3, on en crée
            if audio.tags is None:
                audio.add_tags()
            
            # Mapping des meta (Titre, Artiste, Album, Année)
            if metadata.get('title'): audio.tags.add(TIT2(encoding=3, text=metadata['title']))
            if metadata.get('artist'): audio.tags.add(TPE1(encoding=3, text=metadata['artist']))
            if metadata.get('album'): audio.tags.add(TALB(encoding=3, text=metadata['album']))
            if metadata.get('year'): audio.tags.add(TDRC(encoding=3, text=str(metadata['year'])))
            
            audio.save()
            return True, "Tags appliqués avec succès"
        elif filepath.lower().endswith('.wma'):
            audio = ASF(filepath)
            
            # Mapping ASF (WMA)
            # UTF-16 par défaut pour ASF
            if metadata.get('title'): audio["Title"] = [metadata['title']]
            if metadata.get('artist'): audio["WM/Author"] = [metadata['artist']]
            if metadata.get('album'): audio["WM/AlbumTitle"] = [metadata['album']]
            if metadata.get('year'): audio["WM/Year"] = [str(metadata['year'])]
            
            audio.save()
            return True, "Tags WMA appliqués avec succès"
        else:
            return False, f"Format {os.path.splitext(filepath)[1]} non supporté pour l'écriture"
    except Exception as e:
        print(f"Erreur écriture tags : {e}")
        return False, str(e)

if __name__ == "__main__":
    print("Moteur de taggage WinJukeBox prêt.")
    print("Utilisation: importer ce module et appeler poc_engine(filepath)")
