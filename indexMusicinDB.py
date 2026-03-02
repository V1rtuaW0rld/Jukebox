import os
import sqlite3
import logging
import time
import mutagen
from mutagen.id3 import ID3
from mutagen.asf import ASF
from tqdm import tqdm
import sys
import json
import datetime
import hashlib
from dotenv import load_dotenv

# --- CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")
load_dotenv(ENV_PATH)

MUSIC_FOLDER = os.path.normpath(os.getenv("MUSIC_FOLDER", "//192.168.0.3/music"))

# Détection de l'environnement (Frozen/Dev) pour la DB
if getattr(sys, 'frozen', False):
    import sys
    base_path = sys._MEIPASS 
    # Ou si le fichier est à côté de l'exe : base_path = os.path.dirname(sys.executable)
else:
    base_path = os.path.dirname(os.path.abspath(__file__))

DB_NAME = os.path.join(base_path, "jukebox.db")
SCAN_STATUS_PATH = os.path.join(base_path, "scan_status.json")
BAD_TAGS = ["unknown", "none", "null", "v0", "v2", "titre", "artiste"] # <--- AJOUTE CETTE LIGNE

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

def init_db():
    conn = sqlite3.connect(DB_NAME)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    c = conn.cursor()
    
    # 1. Table principale des pistes
    c.execute('''CREATE TABLE IF NOT EXISTS tracks
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  title TEXT DEFAULT '', 
                  artist TEXT DEFAULT '', 
                  album TEXT DEFAULT '', 
                  path TEXT UNIQUE, 
                  cover_path TEXT DEFAULT '',
                  full INTEGER DEFAULT 0,
                  folder_mtime REAL DEFAULT 0,
                  last_seen REAL DEFAULT 0,
                  hash TEXT DEFAULT '',
                  duration INTEGER DEFAULT 0,
                  file_size INTEGER DEFAULT 0,
                  file_mtime REAL DEFAULT 0)''')
    
    # 2. Sécurité : Mise à jour des colonnes pour les bases existantes
    # On met TOUTES les colonnes critiques ici. 
    # Si la colonne existe déjà, SQLite renverra une erreur qu'on ignore (pass).
    safety_cols = [
        ("folder_mtime", "REAL"), 
        ("last_seen", "REAL"),
        ("hash", "TEXT"), 
        ("duration", "INTEGER"), 
        ("file_size", "INTEGER"),
        ("file_mtime", "REAL")
    ]
    
    for col_name, col_type in safety_cols:
        try:
            c.execute(f"ALTER TABLE tracks ADD COLUMN {col_name} {col_type}")
        except sqlite3.OperationalError:
            pass # La colonne existe déjà, tout va bien.

    # 2. Table Playlist (Lecture en cours)
    c.execute('''CREATE TABLE IF NOT EXISTS playlist 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  track_id INTEGER NOT NULL, 
                  position INTEGER NOT NULL)''')

    # 3. Table Shuffled Playlist
    c.execute('''CREATE TABLE IF NOT EXISTS shuffled_playlist 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  track_id INTEGER NOT NULL, 
                  position INTEGER NOT NULL)''')

    # 4. Table Playlist Album
    c.execute('''CREATE TABLE IF NOT EXISTS playlist_album 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  track_id INTEGER NOT NULL, 
                  position INTEGER NOT NULL)''')

    # 5. Table Infos Playlists Sauvegardées
    c.execute('''CREATE TABLE IF NOT EXISTS saved_playlists_info 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  name TEXT UNIQUE NOT NULL, 
                  created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')

    # 6. Table Contenu Playlists Sauvegardées
    c.execute('''CREATE TABLE IF NOT EXISTS saved_playlists_content (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    playlist_id INTEGER NOT NULL,
                    track_id INTEGER NOT NULL,
                    position INTEGER NOT NULL,
                    FOREIGN KEY(playlist_id) REFERENCES saved_playlists_info(id) ON DELETE CASCADE)''')

    conn.commit()
    return conn


def get_file_info(path):
    """Calcule le hash (8 derniers ko), la taille et la durée du fichier."""
    f_hash = ""
    f_size = 0
    f_duration = 0
    try:
        f_size = os.path.getsize(path)
        # 1. Calcul du Hash (8 derniers ko)
        if f_size > 0:
            with open(path, 'rb') as f:
                if f_size > 8192:
                    f.seek(-8192, 2)
                f_hash = hashlib.md5(f.read()).hexdigest()
        
        # 2. Calcul de la durée
        audio = mutagen.File(path)
        if audio and audio.info:
            f_duration = int(audio.info.length)
    except:
        pass
    return f_hash, f_size, f_duration





def extract_embedded_cover(file_path, root_folder):
    """
    Tente d'extraire la pochette intégrée (ID3 APIC pour MP3 ou WM/Picture pour WMA)
    et la sauvegarde sous le nom 'cover.jpg' dans le dossier racine.
    """
    try:
        if file_path.lower().endswith(".mp3"):
            audio = ID3(file_path)
            pics = audio.getall("APIC")
            if pics:
                data = pics[0].data
                target_path = os.path.join(root_folder, "cover.jpg")
                with open(target_path, "wb") as f:
                    f.write(data)
                return target_path
        elif file_path.lower().endswith(".wma"):
            audio = ASF(file_path)
            if "WM/Picture" in audio:
                # WM/Picture est une liste d'objets ASFMetadataAttribute
                # La donnée binaire est accessible via .value
                # Elle contient un header (type, mime, desc, puis DATA)
                # Mais mutagen.asf.ASFMetadataAttribute.value est souvent déjà le binaire
                # On prend la première image trouvée
                for pic in audio["WM/Picture"]:
                    data = pic.value
                    # Le tag ASF contient un header. On cherche le début du flux image.
                    # JPEG: \xFF\xD8, PNG: \x89PNG, BMP: BM
                    start_idx = -1
                    for magic in [b"\xff\xd8", b"\x89PNG", b"BM"]:
                        start_idx = data.find(magic)
                        if start_idx != -1: break
                    
                    if start_idx != -1:
                        target_path = os.path.join(root_folder, "cover.jpg")
                        with open(target_path, "wb") as f:
                            f.write(data[start_idx:])
                        return target_path
    except:
        pass
    return ""

def find_cover(root):
    """
    Recherche une pochette avec la logique de profondeur relative.
    Cherche dans le dossier, et remonte d'un cran si on est dans un sous-dossier d'album (profondeur >= 3).
    """
    COVER_NAMES = ['cover.jpg', 'cover.png', 'folder.jpg', 'front.jpg']
    
    # Calcul de la profondeur par rapport à la racine music
    try:
        rel_path = os.path.relpath(root, MUSIC_FOLDER)
        depth = 0 if rel_path == "." else len(rel_path.split(os.sep))
    except:
        depth = 0

    def check_folder(path):
        try:
            with os.scandir(path) as it:
                for entry in it:
                    if entry.is_file():
                        # On vérifie juste l'extension, peu importe le nom (le fameux Wildcard)
                        if entry.name.lower().endswith((".jpg", ".jpeg", ".png", ".bmp")):
                            return entry.path
        except:
            pass
        return None

    # Test 1 : Dossier actuel
    found = check_folder(root)
    if found:
        return found

    # Test 2 : Remontée si profondeur suffisante (Artiste/Album/CD1 -> depth 3)
    if depth >= 3:
        parent = os.path.dirname(root)
        if parent.startswith(MUSIC_FOLDER):
            found = check_folder(parent)
            if found:
                return found

    return ""

def scan_music():
    start_time = time.time()

    # 1. VÉRIFICATION ACCÈS NAS
    if not os.path.exists(MUSIC_FOLDER):
        logging.error(f"ERREUR CRITIQUE : Le dossier {MUSIC_FOLDER} est inaccessible.")
        return 

    # 2. RÉPARATION ET OPTIMISATION (Avant d'ouvrir la connexion WAL)
    logging.info("Vérification d'intégrité et Réparation...")
    try:
        # On ajoute un timeout de 30s pour être sûr de ne pas échouer si Flask a le fichier ouvert
        repair_conn = sqlite3.connect(DB_NAME, timeout=30) 
        repair_conn.execute("PRAGMA integrity_check")
        repair_conn.execute("VACUUM") # Reconstruit le fichier proprement
        repair_conn.close()
        logging.info("Base de données réparée et compactée.")
    except Exception as e:
        logging.warning(f"Note : Réparation ignorée (Base occupée ou déjà saine) : {e}")

    # 3. INITIALISATION NORMALE
    conn = init_db()
    c = conn.cursor()
    
        
    current_timestamp = time.time()
    all_files = []
    extensions = (".mp3", ".wma")

    logging.info(f"Début du scan : {MUSIC_FOLDER}")
    
    # Etape 1 : Collecte
    for root, dirs, files in os.walk(MUSIC_FOLDER):
        for file in files:
            if file.lower().endswith(extensions):
                all_files.append((root, file))

    total = len(all_files)
    logging.info(f"{total} fichiers trouvés.")

    # Etape 2 : Traitement
    data_to_upsert = []
    cover_cache = {}
    
    # On initialise tqdm sur la liste des fichiers
    pbar = tqdm(all_files, desc="Indexation", unit="file")

    # On utilise "enumerate(pbar)" : pbar gère l'affichage, enumerate gère l'index pour le modulo 10
    for index, (root, file) in enumerate(pbar):
        full_path = os.path.join(root, file)
        
        # --- ENVOI DE LA PROGRESSION ET MÉMOIRE ---
        if index % 50 == 0:
            actual_speed = round(pbar.format_dict['rate'] or 0, 2)
            status = {
                "current": index, 
                "total": total, 
                "speed": actual_speed,
                "status": "running"
            }
            # 1. Envoi au Front (via stdout/Flask)
            pbar.write(json.dumps(status))
            sys.stdout.flush()

            # 2. Sauvegarde pour la mémoire
            try:
                with open(SCAN_STATUS_PATH, "w") as f:
                    json.dump(status, f)
            except Exception as e:
                pass

        # Stats du fichier pour le check rapide
        try:
            stat = os.stat(full_path)
            f_size_actual = stat.st_size
            f_mtime_actual = stat.st_mtime
        except:
            continue # Fichier inaccessible, on passe

        # --- LOGIQUE DE SAUT (BYPASS) ---
        # Si le chemin existe ET que la taille/date correspondent, on ne fait RIEN apart mettre à jour last_seen
        c.execute("SELECT id, file_size, file_mtime FROM tracks WHERE path = ?", (full_path,))
        row = c.fetchone()
        
        if row:
            db_id, db_size, db_mtime = row
            # On vérifie que db_mtime n'est pas None (cas des anciens enregistrements)
            if db_mtime is not None and db_size == f_size_actual and abs(db_mtime - f_mtime_actual) < 1.0:
                # Le fichier est identique. On met juste à jour last_seen.
                c.execute("UPDATE tracks SET last_seen = ? WHERE id = ?", (current_timestamp, db_id))
                continue

        # --- SI ON ARRIVE ICI : LE FICHIER EST NOUVEAU OU CHANGÉ ---
        # On calcule le hash et les infos (C'est l'étape lourde)
        f_hash, f_size, f_duration = get_file_info(full_path)

        # --- LOGIQUE DÉTECTION RENOMMAGE (ANTI-DOUBLON) ---
        if not row: # Uniquement pour les nouveaux chemins
            c.execute("""
                SELECT id FROM tracks 
                WHERE hash = ? AND file_size = ? AND last_seen < ? 
                LIMIT 1
            """, (f_hash, f_size, current_timestamp))
            relic = c.fetchone()

            if relic:
                relic_id = relic[0]
                # BINGO : C'est le même fichier mais ailleurs. On met à jour le path.
                c.execute("UPDATE tracks SET path = ?, last_seen = ?, file_mtime = ? WHERE id = ?", 
                          (full_path, current_timestamp, f_mtime_actual, relic_id))
                continue

        # --- GESTION DU CACHE COVER ---
        if root not in cover_cache:
            path_found = find_cover(root)
            if path_found:
                cover_cache[root] = path_found
            else:
                if file.lower().endswith((".mp3", ".wma")):
                    extracted_path = extract_embedded_cover(full_path, root)
                    cover_cache[root] = extracted_path if extracted_path else ""
                else:
                    cover_cache[root] = ""
        
        current_cover = cover_cache[root]
        
        # --- EXTRACTION TAGS (Ton code d'origine) ---
        title, artist, album = "", "", ""
        if file.lower().endswith(".mp3"):
            try:
                audio = ID3(full_path)
                def get_clean(tag_id):
                    frame = audio.get(tag_id)
                    if frame and frame.text:
                        val = str(frame.text[0]).strip()
                        if val.lower() in BAD_TAGS or len(val) < 2:
                            return ""
                        return val
                    return ""

                # FORCE UTILSATEUR : On utilise le nom de fichier (sans extension) comme TITRE
                # au lieu du tag ID3 TIT2.
                # title = get_clean('TIT2') <--- ANCIEN CODE
                title = os.path.splitext(file)[0]
                artist = get_clean('TPE1')
                album = get_clean('TALB')
            except:
                pass 
        elif file.lower().endswith(".wma"):
            try:
                audio = ASF(full_path)
                # Mapping ASF (WMA)
                # FORCE USER : Nom de fichier comme Titre
                # title = str(audio["Title"][0]) if "Title" in audio else ""
                title = os.path.splitext(file)[0]
                
                # Gestion fine de l'artiste : Album Artist prioritaires pour le tri/affichage
                artist_val = ""
                if "WM/AlbumArtist" in audio: artist_val = str(audio["WM/AlbumArtist"][0])
                elif "WM/Author" in audio: artist_val = str(audio["WM/Author"][0])
                elif "Author" in audio: artist_val = str(audio["Author"][0])
                
                artist = artist_val
                album = str(audio["WM/AlbumTitle"][0]) if "WM/AlbumTitle" in audio else ""
            except:
                pass

        display_title = title if title else file
        
        # --- LOGIQUE DE STATUT (Ton code d'origine) ---
        has_meta = bool(artist and album) 
        has_cover = bool(current_cover and current_cover.strip())

        if has_meta and has_cover: is_full = 1
        elif not has_meta and has_cover: is_full = 2
        elif has_meta and not has_cover: is_full = 3
        else: is_full = 0

        # --- MODIFICATION DU UPSERT DATA ---
        try: folder_mtime = os.path.getmtime(root)
        except: folder_mtime = 0

        data_to_upsert.append((
            display_title, artist, album, full_path, 
            current_cover, is_full, folder_mtime, current_timestamp,
            f_hash, f_duration, f_size, f_mtime_actual
        ))
        
        # Upsert par blocs de 500 pour la performance
        if len(data_to_upsert) >= 500:
            c.executemany("""
                INSERT INTO tracks (
                    title, artist, album, path, cover_path, 
                    full, folder_mtime, last_seen, hash, duration, file_size, file_mtime
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    title=excluded.title, 
                    artist=excluded.artist, 
                    album=excluded.album,
                    cover_path=excluded.cover_path, 
                    full=excluded.full,
                    folder_mtime=excluded.folder_mtime, 
                    last_seen=excluded.last_seen,
                    hash=excluded.hash,
                    duration=excluded.duration,
                    file_size=excluded.file_size,
                    file_mtime=excluded.file_mtime
            """, data_to_upsert)
            data_to_upsert = []

    # On ferme la barre à la fin
    pbar.close()

    # Finalisation du dernier bloc
    if data_to_upsert:
            c.executemany("""
                INSERT INTO tracks (
                    title, artist, album, path, cover_path, 
                    full, folder_mtime, last_seen, hash, duration, file_size, file_mtime
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    title=excluded.title, 
                    artist=excluded.artist, 
                    album=excluded.album,
                    cover_path=excluded.cover_path, 
                    full=excluded.full,
                    folder_mtime=excluded.folder_mtime, 
                    last_seen=excluded.last_seen,
                    hash=excluded.hash,
                    duration=excluded.duration,
                    file_size=excluded.file_size,
                    file_mtime=excluded.file_mtime
            """, data_to_upsert)

    # Etape 3 : Nettoyage des fichiers supprimés du disque
    # c.execute("DELETE FROM tracks WHERE last_seen < ?", (current_timestamp,)) # <--- METS UN # AU DÉBUT ICI
    
    
    # --- ÉTAPE 4 : NETTOYAGE DES CHAÎNES (Pour éviter les espaces fantômes) ---
    logging.info("Nettoyage des données en base...")
    c.execute("UPDATE tracks SET artist = '' WHERE trim(artist) = '' OR artist IS NULL")
    c.execute("UPDATE tracks SET album = '' WHERE trim(album) = '' OR album IS NULL")
    c.execute("UPDATE tracks SET cover_path = '' WHERE trim(cover_path) = '' OR cover_path IS NULL")

    # --- ÉTAPE 5 : CALCUL DU STATUT 'FULL' (Logique pure SQL) ---
    logging.info("Calcul des statuts de complétion (is_full)...")
    
    # Par défaut, tout le monde est à 0 (Incomplet)
    c.execute("UPDATE tracks SET full = 0")

    # Statut 1 : PARFAIT (Tags OK ET Cover OK)
    c.execute("""
        UPDATE tracks SET full = 1 
        WHERE artist != '' AND album != '' AND cover_path != ''
    """)

    # Statut 2 : TAGS MANQUANTS (Cover OK mais Tags vides)
    c.execute("""
        UPDATE tracks SET full = 2 
        WHERE cover_path != '' AND (artist = '' OR album = '')
    """)

    # Statut 3 : COVER MANQUANTE (Tags OK mais Cover vide)
    c.execute("""
        UPDATE tracks SET full = 3 
        WHERE cover_path = '' AND artist != '' AND album != ''
    """)

    
    # --- 1. IDENTIFICATION DES FANTÔMES (Avant suppression pour le verbe) ---
    c.execute("SELECT id, path FROM tracks WHERE last_seen < ?", (start_time,))
    relics = c.fetchall()
    deleted_ids = [str(r[0]) for r in relics]
    deleted_count = len(deleted_ids)

    # --- 2. NETTOYAGE ---
    if deleted_count > 0:
        logging.info(f"🗑️  Suppression des IDs : {', '.join(deleted_ids[:10])}{'...' if deleted_count > 10 else ''}")
        c.execute("DELETE FROM tracks WHERE last_seen < ?", (start_time,))
    
    conn.commit()
    conn.close()

    # --- 3. CALCULS ET BILAN ---
    execution_time = time.time() - start_time
    m, s = divmod(int(execution_time), 60)
    
    final_status = {
        "status": "completed",
        "current": total,
        "total": total,
        "speed": round(total / execution_time, 2) if execution_time > 0 else 0,
        "duration": f"{m:02d}:{s:02d}",
        "deleted": deleted_count,
        "deleted_list": deleted_ids, # On garde la liste pour ton info
        "completed_at": datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    }
    
    with open(SCAN_STATUS_PATH, "w") as f:
        json.dump(final_status, f)
    
    # IMPORTANTE : Envoi sur stdout pour le flux temps réel
    print(json.dumps(final_status), flush=True)

    # --- 4. LOG FINAL ULTRA-VERBEUX (Sur stderr pour ne pas polluer le JSON) ---
    print(f"\n" + "="*50, file=sys.stderr)
    print(f"📊 BILAN DE L'INDEXATION", file=sys.stderr)
    print(f"="*50, file=sys.stderr)
    print(f"🎵 Pistes traitées     : {total}", file=sys.stderr)
    print(f"🧹 Pistes supprimées   : {deleted_count}", file=sys.stderr)
    if deleted_ids:
        print(f"🗑️  Détail IDs supprimés : {', '.join(deleted_ids)}", file=sys.stderr)
    print(f"⏱️  Temps total        : {m:02d}m {s:02d}s", file=sys.stderr)
    print(f"🚀 Vitesse moyenne    : {final_status['speed']} fichiers/s", file=sys.stderr)
    print(f"="*50, file=sys.stderr)

def run_scan():
    # Initial status pour le feedback UI immédiat
    try:
        with open(SCAN_STATUS_PATH, "w") as f:
            json.dump({"status": "running", "current": 0, "total": 100}, f)
    except: pass
    scan_music()

if __name__ == "__main__":
    run_scan()