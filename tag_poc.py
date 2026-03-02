import os
import subprocess
import json
import requests
import musicbrainzngs
import re

from dotenv import load_dotenv

import sys

# --- CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")
load_dotenv(ENV_PATH)

if getattr(sys, 'frozen', False):
    FPCALC_PATH = os.path.join(sys._MEIPASS, "fpcalc.exe")
else:
    FPCALC_PATH = os.path.join(BASE_DIR, "fpcalc.exe")
ACOUSTID_API_KEY = os.getenv("ACOUSTID_API_KEY", "hLiR6XeAeq")
MB_EMAIL = os.getenv("MUSICBRAINZ_EMAIL", "ddrtsdr@yahoo.fr")
musicbrainzngs.set_useragent("WinJukeBox", "1.0", MB_EMAIL)

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
    """Recupere la tracklist propre d'une release specifique."""
    try:
        print(f"PIVOT: Recuperation tracklist MB Release: {release_id}...")
        data = musicbrainzngs.get_release_by_id(release_id, includes=["recordings", "artist-credits"])
        release = data['release']
        mediums = release.get('medium-list', [])
        
        tracklist = []
        for medium in mediums:
            for track in medium.get('track-list', []):
                tracklist.append({
                    "position": track.get('number'),
                    "title": track.get('recording', {}).get('title'),
                    "duration": int(track.get('length', 0)) // 1000 if track.get('length') else 0
                })
        return tracklist
    except Exception as e:
        print(f"ERREUR: MB Tracklist: {e}")
        return None

def get_best_release_from_group(mbid_group, target_track_count=None):
    """Pivot: Trouve la meilleure Release dans un Release Group."""
    try:
        print(f"PIVOT: Recherche releases pour le groupe: {mbid_group}...")
        data = musicbrainzngs.browse_releases(release_group=mbid_group)
        releases = data.get('release-list', [])
        
        if not releases:
            return None

        # Strategie simple : on cherche celle qui a le bon nombre de titres
        best_release = releases[0]
        return best_release['id']
    except Exception as e:
        print(f"ERREUR: Pivot MB: {e}")
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
        for track in data.get('tracklist', []):
            if track.get('title'):
                tracklist.append({
                    "position": track.get('position'),
                    "title": track.get('title')
                })
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

def poc_engine(filepath, manual_discogs_id=None, target_track_count=None):
    print(f"\n--- DEMARRAGE DU PIPELINE LOGIQUE ---")
    print(f"Fichier source : {filepath}")
    
    # 1. IDENTIFICATION ACOUSTIQUE
    print("\nEtape 1 : Identification acoustique (AcoustID)...")
    res = get_acoustid_data(filepath)
    mbid_group = None
    if res and res.get('results'):
        best_res = res['results'][0]
        rec = best_res.get('recordings', [{}])[0]
        mbid_group = rec.get('releasegroups', [{}])[0].get('id')
        print(f"OK: MBID Release-Group identifie : {mbid_group}")
    else:
        print("ERREUR: Echec de l'identification acoustique (Inconnu du web).")

    # 2. STRATEGIE MUSICBRAINZ
    if mbid_group:
        print(f"\nEtape 2 : Exploration MusicBrainz pour le groupe {mbid_group}...")
        release_id = get_best_release_from_group(mbid_group, target_track_count)
        if release_id:
            tracklist = get_tracklist_from_mb_release(release_id)
            if tracklist:
                print(f"SUCCES: {len(tracklist)} titres recuperes sur MusicBrainz.")
                return tracklist

    # 3. STRATEGIE DISCOGS
    if manual_discogs_id:
        print("\nEtape 3 : Recherche de secours via Discogs...")
        print(f"INFO: Tentative via ID Discogs Manuel : {manual_discogs_id}")
        tracklist = get_tracklist_from_discogs(manual_discogs_id)
        if tracklist:
            print(f"SUCCES: {len(tracklist)} titres recuperes via Discogs.")
            return tracklist

    # 4. FALLBACK PATH (Filet de sécurité - La "Solution du Pauvre")
    print("\nEtape 4 : Utilisation du filet de securite (Analyse locale)...")
    return get_tracklist_from_path(filepath)

if __name__ == "__main__":
    # TEST AVEC UNE CHANSON INCONNUE (DOIT ACTIVER L'ETAPE 4)
    TEST_FILE = os.path.normpath(r"\\192.168.0.3\music\SAM'NGUST\Infortune\01Mentir.mp3")
    
    # Aucun ID manuel pour simuler l'échec complet
    MANUAL_DISCOGS_ID = None 
    
    final_list = poc_engine(TEST_FILE, manual_discogs_id=MANUAL_DISCOGS_ID)
    
    if final_list:
        local_files = get_local_files_from_dir(TEST_FILE)
        match_tracklists(local_files, final_list)
    print("\n--- FIN DU POC ---")
