import os
import sqlite3
import time
import mutagen
from mutagen.id3 import ID3
from mutagen.asf import ASF
import datetime
import hashlib
import json
import sys

from dotenv import load_dotenv

# --- CONFIGURATION (Avec Robustesse) ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")

try:
    load_dotenv(ENV_PATH)
except:
    pass # On continue, les défauts s'appliqueront

MUSIC_FOLDER = os.path.normpath(os.getenv("MUSIC_FOLDER", "//192.168.0.3/music"))

# Détection de l'environnement (Frozen/Dev) pour la DB
if getattr(sys, 'frozen', False):
    import sys
    base_path = sys._MEIPASS
else:
    base_path = os.path.dirname(os.path.abspath(__file__))

DB_NAME = os.path.join(base_path, "jukebox.db")
FAST_SCAN_STATUS_PATH = os.path.join(base_path, "fast_scan_status.json")

def send_update(data):
    """Envoie une mise à jour JSON sur stdout et la sauvegarde dans un fichier."""
    msg = json.dumps(data)
    print(msg, flush=True)
    try:
        with open(FAST_SCAN_STATUS_PATH, "w") as f:
            f.write(msg)
    except:
        pass

def get_clean_tag(audio, tag_id):
    """Extrait et nettoie un tag ID3."""
    try:
        frame = audio.get(tag_id)
        if frame and frame.text:
            val = str(frame.text[0]).strip()
            # On considère comme vide si c'est un tag générique inutile
            if val.lower() in ["unknown", "none", "null", "artiste", "album"]:
                return ""
            return val
    except: pass
    return ""

def get_file_info(filepath):
    """Calcule Hash (8 derniers Ko), Taille et Durée."""
    try:
        f_size = os.path.getsize(filepath)
        if f_size < 8192: return "", f_size, 0
        with open(filepath, 'rb') as f:
            f.seek(-8192, os.SEEK_END)
            f_hash = hashlib.md5(f.read()).hexdigest()
        try:
            audio = mutagen.File(filepath)
            f_duration = int(audio.info.length) if audio and audio.info else 0
        except: f_duration = 0
        return f_hash, f_size, f_duration
    except: return "", 0, 0
def find_cover(root):
    """
    Recherche une pochette avec la logique de profondeur relative.
    Cherche dans le dossier, et remonte d'un cran si on est dans un sous-dossier d'album (profondeur >= 3).
    """
    # Normalisation pour éviter les embrouilles
    n_root = os.path.normpath(root)
    n_music = os.path.normpath(MUSIC_FOLDER)

    # Calcul de la profondeur par rapport à la racine music
    try:
        rel_path = os.path.relpath(n_root, n_music)
        depth = 0 if rel_path == "." else len(rel_path.split(os.sep))
    except:
        depth = 0

    def check_folder(path):
        try:
            # print(f"DEBUG: Scan cover dans {path}...") 
            with os.scandir(path) as it:
                for entry in it:
                    if entry.is_file():
                        if entry.name.lower().endswith((".jpg", ".jpeg", ".png", ".bmp")):
                            # print(f"DEBUG: COVER TROUVÉE -> {entry.path}")
                            return entry.path
        except Exception as e: 
            print(f"DEBUG: Erreur scan {path}: {e}")
        return None

    # Test 1 : Dossier actuel (Wildcard)
    found = check_folder(n_root)
    if found: return found

    # Test 2 : Remontée si profondeur suffisante
    if depth >= 2: # On commence à 2 pour CD1/CD2
        parent = os.path.dirname(n_root)
        # Sécurité pour ne pas remonter trop haut (au dessus de MUSIC_FOLDER)
        if parent.startswith(n_music) and len(parent) >= len(n_music):
            # print(f"DEBUG: Remontée parent -> {parent}")
            found = check_folder(parent)
            if found: return found
            
    return ""

def fast_scan_statut_full():
    # 1. INITIALISATION DU CHRONO ET CONNEXION
    start_time = time.time()
    
    conn = sqlite3.connect(DB_NAME)
    conn.execute("PRAGMA journal_mode=WAL")
    c = conn.cursor()

    # 1.bis SÉCURITÉ NAS
    if not os.path.exists(MUSIC_FOLDER):
        print(f"ERREUR: {MUSIC_FOLDER} inaccessible. Scan annulé.")
        send_update({"status": "completed", "error": "Source inaccessible"})
        conn.close()
        return

    # JALON 1 : Initialisation terminée
    send_update({"status": "running", "current": 10, "total": 100})

    # Compte total initial
    c.execute("SELECT count(*) FROM tracks")
    total_db_tracks = c.fetchone()[0] or 0
    
    # 1.ter CALCUL DE L (Date de la donnée la plus ancienne)
    # C'est la référence pour savoir ce qui est "vieux" et stable.
    c.execute("SELECT MIN(last_seen) FROM tracks")
    L = c.fetchone()[0] or 0
    # Sécurité : Si L est trop vieux (ex: 0), on force une date récente pour ne pas tout ignorer
    # Ou l'inverse : Si L est 0, on recheck tout.

    # 2. CHARGEMENT DU CACHE MTIME (Normalisation des chemins)
    db_mtimes = {}
    c.execute("SELECT path, folder_mtime FROM tracks")
    for p, m in c.fetchall():
        d = os.path.normpath(os.path.dirname(p))
        if d not in db_mtimes or (m and m > db_mtimes.get(d, 0)):
            db_mtimes[d] = m

    # JALON 2 : Cache chargé
    send_update({"status": "running", "current": 30, "total": 100})

    count_folders_updated = 0
    count_tracks_updated = 0
    count_shortlist = 0
    count_deleted = 0
    seen_folders = set()
    norm_music_folder = os.path.normpath(MUSIC_FOLDER)

    # 4. PARCOURS
    progress = 30
    for root, dirs, files in os.walk(MUSIC_FOLDER):
        normalized_root = os.path.normpath(root)
        seen_folders.add(normalized_root)
        
        try:
            mtime_nas = os.path.getmtime(root)
            mtime_bdd = db_mtimes.get(normalized_root, 0)
            
            # --- OPTIMISATION UTILISATEUR (L) ---
            # Si le dossier est plus vieux que la plus vieille donnée de la base (L),
            # on l'ignore (Shortlist logic).
            if mtime_nas < L:
                 continue

            # --- ÉTAPE 1 : LE DOSSIER A-T-IL CHANGÉ ? ---
            # Check classique (redondant mais sécurité)
            if normalized_root in db_mtimes and abs(mtime_nas - mtime_bdd) < 0.01:
                continue


            count_shortlist += 1
            
            if progress < 90:
                progress += 1
            
            # DEBUG: Affichage pour savoir ce qui est traité
            # print(f"DEBUG: Traitement de {root}")
            send_update({"status": "running", "current": progress, "total": 100, "folder": os.path.basename(root)})
            
            # --- ÉTAPE 3 : RÉINDEXATION RÉELLE ---
            music_files = [f for f in files if f.lower().endswith(('.mp3', '.wma'))]
            
            # Recherche Smart Cover
            current_cover = find_cover(root)
            now_ts = time.time()

            if music_files:
                count_folders_updated += 1
                for f_name in music_files:
                    full_path = os.path.join(root, f_name)
                    f_hash, f_size, f_duration = get_file_info(full_path)
                    
                    c.execute("SELECT id FROM tracks WHERE path = ?", (full_path,))
                    row_exists = c.fetchone()

                    if not row_exists:
                        c.execute("""
                            SELECT id FROM tracks 
                            WHERE hash = ? AND file_size = ? AND last_seen < ? 
                            LIMIT 1
                        """, (f_hash, f_size, now_ts - 5))
                        relic = c.fetchone()
                        if relic:
                            c.execute("UPDATE tracks SET path = ?, last_seen = ? WHERE id = ?", (full_path, now_ts, relic[0]))
                            count_tracks_updated += 1
                            continue

                    # EXTRACTION TAGS
                    title, artist, album = f_name, "", ""
                    if f_name.lower().endswith(".mp3"):
                        try:
                            audio = ID3(full_path)
                            # title = get_clean_tag(audio, 'TIT2') or f_name
                            title = os.path.splitext(f_name)[0]
                            artist = get_clean_tag(audio, 'TPE1')
                            album = get_clean_tag(audio, 'TALB')
                        except: pass
                    elif f_name.lower().endswith(".wma"):
                        try:
                            audio = ASF(full_path)
                            # title = str(audio["Title"][0]) if "Title" in audio else f_name
                            title = os.path.splitext(f_name)[0]
                            artist = str(audio["WM/Author"][0]) if "WM/Author" in audio else ""
                            album = str(audio["WM/AlbumTitle"][0]) if "WM/AlbumTitle" in audio else ""
                        except: pass

                    has_meta = bool(artist and artist.strip() and album and album.strip()) 
                    has_cover = bool(current_cover and current_cover.strip())
                    is_full = 1 if has_meta and has_cover else (2 if has_cover else (3 if has_meta else 0))

                    c.execute("""
                        INSERT INTO tracks (title, artist, album, path, cover_path, full, folder_mtime, last_seen, hash, duration, file_size)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(path) DO UPDATE SET
                            title=excluded.title, artist=excluded.artist, album=excluded.album,
                            cover_path=excluded.cover_path, full=excluded.full, folder_mtime=excluded.folder_mtime,
                            last_seen=excluded.last_seen, hash=excluded.hash, duration=excluded.duration, file_size=excluded.file_size
                    """, (title, artist, album, full_path, current_cover, is_full, mtime_nas, now_ts, f_hash, f_duration, f_size))
                    count_tracks_updated += 1

            # --- NETTOYAGE CHIRURGICAL NON-RÉCURSIF DU DOSSIER ---
            # On ne supprime que les fichiers DIRECTEMENT dans ce dossier
            prefix = root + os.sep
            c.execute("SELECT id, path FROM tracks WHERE path LIKE ? AND last_seen < ?", (prefix + '%', now_ts))
            to_delete = []
            for g_id, g_path in c.fetchall():
                # On vérifie qu'il n'y a pas d'autre dossier dans la partie restante
                relative = g_path[len(prefix):]
                if os.sep not in relative and '/' not in relative:
                    to_delete.append(g_id)
            
            for g_id in to_delete:
                c.execute("DELETE FROM tracks WHERE id = ?", (g_id,))
                count_deleted += 1
            
            conn.commit()

        except Exception as e:
            pass

    # 4.bis NETTOYAGE DES DOSSIERS ENTIERS SUPPRIMÉS (Avec garde-fou)
    db_folders = set(db_mtimes.keys())
    missing_folders = db_folders - seen_folders
    
    if missing_folders:
        # Garde-fou : si plus de 20% de la base est menacée par des dossiers "disparus"
        if len(missing_folders) > (len(db_folders) * 0.2) and len(db_folders) > 50:
            print(f"\n[ALERTE SÉCURITÉ] {len(missing_folders)} dossiers disparus. C'est trop suspect (ex: NAS déconnecté). Abandon du nettoyage de masse.")
        else:
            print(f"\n[CLEANUP] {len(missing_folders)} dossiers disparus détectés.")
            for folder in missing_folders:
                if len(folder) <= len(norm_music_folder): continue # Sécurité root
                c.execute("DELETE FROM tracks WHERE path LIKE ?", (folder + os.sep + '%',))
                count_deleted += c.rowcount
            conn.commit()

    # 5. BILAN FINAL
    execution_time = time.time() - start_time
    m, s = divmod(int(execution_time), 60)
    duration_str = f"{m:02d}:{s:02d}"
    speed = round(count_tracks_updated / execution_time, 2) if execution_time > 0 else 0

    summary = {
        "status": "completed",
        "current": 100,
        "total": 100,
        "duration": duration_str,
        "execution_time": round(execution_time, 2),
        "count_shortlist": count_shortlist,
        "folders_updated": count_folders_updated,
        "tracks_updated": count_tracks_updated,
        "deleted": count_deleted,
        "speed": speed,
        "total_db": total_db_tracks,
        "completed_at": datetime.datetime.now().strftime('%d/%m/%Y %H:%M')
    }
    send_update(summary)
    
    conn.close()

def run_fast_scan():
    try:
        send_update({"status": "running", "current": 0, "total": 100})
        fast_scan_statut_full()
    except Exception as e:
        # Catch-all pour éviter le crash silencieux qui casse le JSON frontend
        err_msg = json.dumps({
            "status": "completed", 
            "error": str(e), 
            "current": 100, 
            "total": 100
        })
        print(err_msg, flush=True)
        try:
            with open(FAST_SCAN_STATUS_PATH, "w") as f:
                f.write(err_msg)
        except: pass

if __name__ == "__main__":
    run_fast_scan()
