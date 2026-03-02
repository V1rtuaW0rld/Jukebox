#lancer le fichier actuel avec cette commande ci-dessous pour avoir un reload auto à chaque ctrl+s
# uvicorn server:app --reload --host 0.0.0.0 --port 8000
import subprocess
import os
import sys
import sqlite3
import uvicorn
import json
import time
import random
import ctypes
import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi import Request
import re
import glob
from fastapi.responses import JSONResponse
import datetime
import tag  # Import ici
from dotenv import load_dotenv, set_key
from pydantic import BaseModel

# --- CONFIGURATION WINDOWS LOOP ---
# Force l'utilisation du ProactorEventLoop qui est plus robuste pour les sockets/pipes sous Windows
# Cela corrige potentiellement l'erreur "AssertionError: Data should not be empty" lors des reloads.
if sys.platform == 'win32':
    print(">>> [INIT] Force WindowsProactorEventLoopPolicy...")
    policy = asyncio.WindowsProactorEventLoopPolicy()
    asyncio.set_event_loop_policy(policy)
    print(f">>> [INIT] Policy set to: {type(asyncio.get_event_loop_policy())}")

# --- AJOUT: GESTION MISE EN VEILLE ---
# Constantes Windows
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002

def set_keep_awake(enable=True):
    """Active ou désactive le mode 'pas de veille'."""
    try:
        if enable:
            ctypes.windll.kernel32.SetThreadExecutionState(
                ES_CONTINUOUS | ES_SYSTEM_REQUIRED
            )
        else:
            ctypes.windll.kernel32.SetThreadExecutionState(
                ES_CONTINUOUS
            )
    except Exception as e:
        print(f"Erreur gestion veille: {e}")

# Variables pour le timer de veille
last_music_time = time.time()
TIMEOUT_DELAY = 5 * 60  # 5 minutes


# --- CONFIGURATION INITIALE ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env") # Chemin du fichier .env
load_dotenv(ENV_PATH) # Chargement des variables

# Valeur par défaut si non défini dans .env
raw_music_folder = os.getenv("MUSIC_FOLDER", "//192.168.0.3/music")
MUSIC_FOLDER = os.path.normpath(raw_music_folder)

# Détection de l'environnement (Frozen/Dev) pour la DB
if getattr(sys, 'frozen', False):
    base_path = sys._MEIPASS
else:
    base_path = os.path.dirname(os.path.abspath(__file__))

MPV_PATH = os.path.join(base_path, "mpv.exe")
DB_NAME = os.path.join(base_path, "jukebox.db")
SCAN_STATUS_PATH = os.path.join(base_path, "scan_status.json")
FAST_SCAN_STATUS_PATH = os.path.join(base_path, "fast_scan_status.json")
STATIC_PATH = os.path.join(BASE_DIR, "static")
IPC_PIPE = r"\\.\pipe\mpv-juke"
shuffle_mode = False 
current_playing_id = None
DEVICE_ID = "auto"
current_volume = 70
current_playlist_name = "Playlist"
current_mpv_process = None # Référence au process MPV
playlist_library_version = 0
playlist_active_version = 0
playlist_active_version = 0
# Variables pour la lecture de dossier (Hors BDD)
current_folder_playlist = []  # Liste de chemins (strings)
current_folder_index = -1     # Index actuel
current_source = "none"  # "tracks", "folder_show", "album", "radio"
current_mode = "playlist"   # playlist, album, folder
active_scan_process = None  # Tracking du scan en cours

def get_db_conn():
    conn = sqlite3.connect(DB_NAME, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn



def run_mpv_command(command_list):
    """Envoie une commande JSON à MPV via le Pipe Windows"""
    try:
        with open(IPC_PIPE, "w+b") as f:
            msg = json.dumps({"command": command_list}).encode("utf-8") + b"\n"
            f.write(msg)
    except Exception as e:
        # print(f"Erreur MPV Command: {e}") 
        pass

def read_mpv_property(prop):
    """Lit une propriété MPV via IPC JSON"""
    try:
        # 1. Envoi de la requête
        msg = json.dumps({"command": ["get_property", prop]}).encode("utf-8") + b"\n"
        
        # CallNamedPipe est plus robuste pour le R/W atomique sur les pipes nommés
        # Mais nécessite le chemin complet.
        # Attention: CallNamedPipe attend bytes pour read/write
        # response = ctypes.windll.kernel32.CallNamedPipeA(
        #     CURRENT_IPC_PIPE.encode('ascii'), 
        #     msg, len(msg), 
        #     ctypes.create_string_buffer(1024), 1024, 
        #     ctypes.byref(ctypes.c_ulong()), 
        #     100 # Timeout ms
        # )
        
        # NOTE: CallNamedPipeA n'est pas trivial à wrapper rapidement en Python pur sans win32file
        # On va rester sur l'approche fichier simple qui marche souvent bien si le pipe est dispo
        # Sauf si on veut vraiment la robustesse.
        
        # RETOUR À L'APPROCHE FICHIER SIMPLE (Blockant mais ok avec timeout court via thread si besoin)
        # Pour faire simple : on ouvre en 'r+b'
        with open(IPC_PIPE, "r+b") as f:
            f.write(msg)
            f.flush()
            
            # Lecture
            res_json = f.readline()
            if res_json:
                data = json.loads(res_json)
                return data.get("data")
                
    except Exception:
        return None

# --- AJOUT: TÂCHE DE FOND (BACKGROUND TASK) ---
from contextlib import asynccontextmanager # <--- Ajoute cet import en haut du fichier

from fastapi import FastAPI
from contextlib import asynccontextmanager
import asyncio

# --- INITIALISATION BDD (Au démarrage) ---
def init_db():
    """Initialise la base de données au démarrage (First Run Experience)."""
    try:
        conn = get_db_conn()
        c = conn.cursor()
        
        # 1. Table Tracks
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

        # 2. Tables Playlist
        c.execute('''CREATE TABLE IF NOT EXISTS playlist 
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                      track_id INTEGER NOT NULL, 
                      position INTEGER NOT NULL)''')

        c.execute('''CREATE TABLE IF NOT EXISTS shuffled_playlist 
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                      track_id INTEGER NOT NULL, 
                      position INTEGER NOT NULL)''')
                      
        c.execute('''CREATE TABLE IF NOT EXISTS playlist_album 
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                      track_id INTEGER NOT NULL, 
                      position INTEGER NOT NULL)''')

        # 3. Tables Saved Playlists
        c.execute('''CREATE TABLE IF NOT EXISTS saved_playlists_info 
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                      name TEXT UNIQUE NOT NULL, 
                      created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')

        c.execute('''CREATE TABLE IF NOT EXISTS saved_playlists_content (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        playlist_id INTEGER NOT NULL,
                        track_id INTEGER NOT NULL,
                        position INTEGER NOT NULL,
                        FOREIGN KEY(playlist_id) REFERENCES saved_playlists_info(id) ON DELETE CASCADE)''')
        
        conn.commit()
        conn.close()
        print(">>> DB INIT SUCCESS: Schema verified.")
    except Exception as e:
        print(f"!!! DB INIT FAILED: {e}")

# --- GESTION DU CYCLE DE VIE (LIFESPAN) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- INIT DB (Pour le premier lancement à vide) ---
    init_db()

    loop = asyncio.get_running_loop()
    print(f">>> [LIFESPAN] Running with loop: {type(loop)}")
    print(f">>> [LIFESPAN] Loop policy: {type(asyncio.get_event_loop_policy())}")

    print(">>> LIFESPAN START: launching monitor_sleep_loop")
    monitor_task = asyncio.create_task(monitor_sleep_loop())
    yield
    print(">>> LIFESPAN END: stopping monitor_sleep_loop")
    
    # Nettoyage du scan en cours si nécessaire
    global active_scan_process
    if active_scan_process and active_scan_process.poll() is None:
        print(">>> LIFESPAN: Terminant le scan d'indexation actif...")
        active_scan_process.terminate()
        
    monitor_task.cancel()
    set_keep_awake(False)

# --- CORRECTIF CRASH WINDOWS (SELECTOR LIMIT) ---
# On force l'utilisation de ProactorEventLoop pour supporter > 64 connexions
import sys
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# --- CRÉATION DE L'APP AVEC LIFESPAN ---
app = FastAPI(lifespan=lifespan)


# 2. Configuration CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
def handle_previous(current_id):
    """
    Détermine le morceau précédent.
    Supporte les IDs (int) pour Playlist/Album et les Paths (str) pour Folder.
    """
    global shuffle_mode, current_mode
    conn = get_db_conn()
    cur = conn.cursor()
    
    try:
        # --- 1. MODE FOLDER ---
        if current_mode == "folder":
            cur.execute("SELECT position FROM playlist_folder WHERE path = ?", (str(current_id),))
            res_f = cur.fetchone()
            if res_f:
                # On cherche la position inférieure, triée en DESC pour avoir le plus proche
                cur.execute("SELECT path FROM playlist_folder WHERE position < ? ORDER BY position DESC LIMIT 1", (res_f[0],))
                row = cur.fetchone()
                return {"path": row[0] if row else None}
            return {"path": None}

        # --- 2. MODE ALBUM ---
        cur.execute("SELECT position FROM playlist_album WHERE track_id = ?", (current_id,))
        res_a = cur.fetchone()
        if res_a:
            cur.execute("SELECT track_id FROM playlist_album WHERE position < ? ORDER BY position DESC LIMIT 1", (res_a[0],))
            row = cur.fetchone()
            return {"id": row[0] if row else None}

        # --- 3. GESTION DU SHUFFLE (Initialisation si nécessaire) ---
        if shuffle_mode:
            cur.execute("SELECT COUNT(*) FROM shuffled_playlist")
            if cur.fetchone()[0] == 0:
                cur.execute("SELECT track_id FROM playlist")
                ids = [r[0] for r in cur.fetchall()]
                if ids:
                    import random
                    random.shuffle(ids)
                    for i, tid in enumerate(ids):
                        cur.execute("INSERT INTO shuffled_playlist (track_id, position) VALUES (?, ?)", (tid, i))
                    conn.commit()

        # --- 4. LOGIQUE PLAYLIST (Normal ou Shuffle) ---
        table = "shuffled_playlist" if shuffle_mode else "playlist"

        # Sécurité si current_id est invalide
        if not current_id or current_id == 0:
            cur.execute(f"SELECT track_id FROM {table} ORDER BY position ASC LIMIT 1")
            row = cur.fetchone()
            return {"id": row[0] if row else None}

        # Trouver la position actuelle
        cur.execute(f"SELECT position FROM {table} WHERE track_id = ?", (current_id,))
        res_p = cur.fetchone()

        if res_p:
            # Chercher le précédent (position < actuelle)
            cur.execute(f"SELECT track_id FROM {table} WHERE position < ? ORDER BY position DESC LIMIT 1", (res_p[0],))
            row = cur.fetchone()
            return {"id": row[0] if row else None}
        else:
            # Si non trouvé, on renvoie le premier par défaut
            cur.execute(f"SELECT track_id FROM {table} ORDER BY position ASC LIMIT 1")
            row = cur.fetchone()
            return {"id": row[0] if row else None}

    except Exception as e:
        print(f"!!! Erreur handle_previous: {e}")
        return {"id": None}
    finally:
        conn.close()


def handle_next(current_id):
    global shuffle_mode, current_mode
    conn = get_db_conn()
    cur = conn.cursor()
    
    try:
        # --- 1. MODE FOLDER ---
        if current_mode == "folder":
            cur.execute("SELECT position FROM playlist_folder WHERE path = ?", (str(current_id),))
            res_f = cur.fetchone()
            if res_f:
                cur.execute("SELECT path FROM playlist_folder WHERE position > ? ORDER BY position ASC LIMIT 1", (res_f[0],))
                row = cur.fetchone()
                return {"path": row[0] if row else None}
            return {"path": None}

        # --- 2. MODE ALBUM ---
        cur.execute("SELECT position FROM playlist_album WHERE track_id = ?", (current_id,))
        res_a = cur.fetchone()
        if res_a:
            cur.execute("SELECT track_id FROM playlist_album WHERE position > ? ORDER BY position ASC LIMIT 1", (res_a[0],))
            row = cur.fetchone()
            if row:
                return {"id": row[0]}
            else:
                cur.execute("DELETE FROM playlist_album")
                conn.commit()
                return {"id": None}

        # --- 3. GESTION DU SHUFFLE (Ton bloc indispensable) ---
        if shuffle_mode:
            cur.execute("SELECT COUNT(*) FROM shuffled_playlist")
            if cur.fetchone()[0] == 0:
                cur.execute("SELECT track_id FROM playlist")
                ids = [r[0] for r in cur.fetchall()]
                if ids:
                    import random
                    random.shuffle(ids)
                    for i, tid in enumerate(ids):
                        cur.execute("INSERT INTO shuffled_playlist (track_id, position) VALUES (?, ?)", (tid, i))
                    conn.commit()

        # --- 4. LOGIQUE PLAYLIST (Normal ou Shuffle) ---
        table = "shuffled_playlist" if shuffle_mode else "playlist"

        # On cherche la position actuelle
        cur.execute(f"SELECT position FROM {table} WHERE track_id = ?", (current_id,))
        res_p = cur.fetchone()

        if res_p:
            cur.execute(f"SELECT track_id FROM {table} WHERE position > ? ORDER BY position ASC LIMIT 1", (res_p[0],))
        else:
            # Sécurité : si le morceau actuel n'est pas dans la liste, on commence au début
            cur.execute(f"SELECT track_id FROM {table} ORDER BY position ASC LIMIT 1")
        
        row = cur.fetchone()
        return {"id": row[0] if row else None}

    except Exception as e:
        print(f"!!! Erreur handle_next: {e}")
        return {"id": None}
    finally:
        conn.close()


def play_song_by_path(path):
    global current_playing_id, current_track_path, current_mode
    print(">>> MODE SET TO FOLDER via play_song_by_path", path)
    try:
        # On met à jour l'état global
        current_track_path = path
        current_playing_id = path  # En mode folder, l'ID = le path
        current_mode = "folder"

        print(f"Lecture fichier (folder): {path}")

        # On envoie le fichier directement à MPV
        mpv_command = f'loadfile "{path}" replace'
        send_mpv_command(mpv_command)

    except Exception as e:
        print(f"Erreur play_song_by_path: {e}")


async def monitor_sleep_loop():
    global last_music_time, current_playing_id, current_mode, current_source, current_mpv_process
    print("--- Surveillance Veille & Auto-Next Active ---")
    
    while True:
        try:
            pos = read_mpv_property("time-pos")
            is_paused = read_mpv_property("pause")
            current_time = time.time()

            # 1. GESTION DE LA VEILLE
            is_playing = (pos is not None and not is_paused)
            if is_playing:
                last_music_time = current_time
                set_keep_awake(True)
            else:
                set_keep_awake((current_time - last_music_time) < TIMEOUT_DELAY)

            # 2. LOGIQUE AUTO-NEXT
            # Si MPV est arrêté (pos is None) alors qu'on avait un morceau en cours
            if pos is None and current_playing_id is not None:
                # --- FIX SLOW HARDWARE (Polling Loop) ---
                # Au lieu d'attendre bêtement 6s, on check toutes les 0.5s si ça se débloque.
                # Cela permet de reprendre dès que la musique part (ex: à 4.2s) sans payer le prix fort.
                mpv_recovered = False
                for _ in range(12): # 12 * 0.5s = 6 secondes max
                    await asyncio.sleep(0.5)
                    
                    # Si MPV est mort entre temps
                    if current_mpv_process and current_mpv_process.poll() is not None:
                        break # Il est mort, on sort pour trigger le Next
                        
                    # Si MPV rapporte une position valide -> C'est parti !
                    if read_mpv_property("time-pos") is not None:
                         mpv_recovered = True
                         break
                
                if mpv_recovered:
                    # print(">>> [AUTO-NEXT] MPV Recovered! Continuing playback.")
                    continue

                # Si on arrive ici, c'est que soit il est mort, soit il est toujours bloqué après 6s.
                # On revérifie une dernière fois pour être sûr.
                if read_mpv_property("time-pos") is None:
                    # Si le process est revenu à la vie (cas improbable) ou si nouvelle lecture lancée entre temps
                    if current_mpv_process and current_mpv_process.poll() is None:
                         print(">>> [AUTO-NEXT] Process recovered/new process detected. Abort skip.")
                         continue

                    print(f">>> AUTO-NEXT TRIGGERED (Mode: {current_mode})")
                    
                    # --- SOLUTION SIMPLE : On appelle directement notre fonction get_next ---
                    # Cela garantit que la logique de dossier et de playlist est la même 
                    # que quand on clique sur le bouton "Next"
                    await asyncio.to_thread(get_next, current_playing_id)
                    
                    # On laisse un peu de temps au système pour mettre à jour current_playing_id
                    await asyncio.sleep(1)
                    continue

        except Exception as e:
            print(f"!!! Erreur moniteur: {e}")

        await asyncio.sleep(2)


# --- ROUTES ---

@app.get("/")
def read_index():
    return FileResponse(os.path.join(STATIC_PATH, "index.html"))
    
# Moteur de recherche principal - Version "Full Only"
@app.get("/search")
def search_songs(q: str = "", mode: str = "title"):
    conn = get_db_conn()
    cur = conn.cursor()
    term = f"%{q}%"
    
    # On applique 'full = 1' strictement sur tous les modes
    # Cela garantit : Tags complets + Cover présente (si tu as mis à jour l'indexeur)
    
    if mode == "artist":
        # On groupe par album : un artiste peut avoir plusieurs albums "full"
        query = """SELECT MIN(id), album, artist, album 
                   FROM tracks 
                   WHERE artist LIKE ? AND full = 1
                   GROUP BY album 
                   ORDER BY album ASC"""
        cur.execute(query, (term,))
        
    elif mode == "album":
        # On n'affiche que les disques dont l'indexation est parfaite
        query = """SELECT MIN(id), album, artist, album 
                   FROM tracks 
                   WHERE album LIKE ? AND full = 1
                   GROUP BY album, artist 
                   ORDER BY album ASC"""
        cur.execute(query, (term,))
        
    else:
        # Mode titre : évite de polluer les résultats avec des noms de fichiers bruts
        # On ajoute 'path' pour permettre le tri "Album -> Piste"
        query = """SELECT id, title, artist, album, path 
                   FROM tracks 
                   WHERE (title LIKE ? OR artist LIKE ?) AND full = 1
                   ORDER BY album ASC, title ASC"""
        cur.execute(query, (term, term))

    songs = cur.fetchall()
    conn.close()
    
    # Si on est en mode "else" (Titre/Artiste), on a récupéré le path (index 4)
    if mode not in ["artist", "album"]:
        # On recrée la liste avec le path pour le tri
        temp_list = [
            {"id": s[0], "title": s[1], "artist": s[2], "album": s[3], "path": s[4]} 
            for s in songs
        ]
        # Tri : 1. Par Album, 2. Par Nom de fichier (naturel)
        temp_list.sort(key=lambda x: (x['album'], natural_key(os.path.basename(x['path']))))
        
        # On remet au format attendu
        song_list = [
            {"id": s['id'], "title": s['title'], "artist": s['artist'], "album": s['album']} 
            for s in temp_list
        ]
    else:
        # Cas standard (Artist/Album)
        # Pour Artist, on veut aussi voir les vrais noms de fichiers si disponibles via le path
        # Mais le fetchall ne renvoie pas le path dans ce bloc...
        # Le bloc 'else' (Title/Artist) renvoie le path en index 4.
        
        # NOTE: Si on veut appliquer ça partout, il faut modifier la requête SQL des blocs if/elif au-dessus
        # ou accepter que ce correctif ne s'applique qu'à la recherche texte
        song_list = [
            {"id": s[0], "title": s[1], "artist": s[2], "album": s[3]} 
            for s in songs
        ]

    return {
        "songs": song_list
    }

# On applique la même rigueur au déploiement de l'album
@app.get("/album_tracks")
def get_album_tracks(album: str, artist: str):
    conn = get_db_conn()
    cur = conn.cursor()
    # Ici aussi, on ne liste que les pistes 'full = 1' pour éviter les morceaux "fantômes"
    # sans tags au milieu d'un album propre.
    query = """SELECT id, title, artist, album, path 
               FROM tracks 
               WHERE album = ? AND artist = ? AND full = 1
               ORDER BY path ASC"""
    cur.execute(query, (album, artist))
    tracks = cur.fetchall()
    conn.close()
    
    # Conversion en dictionnaire pour manipulation facile
    track_list = [
        {"id": t[0], "title": t[1], "artist": t[2], "album": t[3], "path": t[4]} 
        for t in tracks
    ]
    
    # Tri naturel sur le NOM DE FICHIER (pour respecter l'ordre 01, 02... du disque)
    # On utilise os.path.basename pour ne trier que sur le nom du fichier, pas le dossier parent
    track_list.sort(key=lambda x: natural_key(os.path.basename(x['path'])))

    return {"tracks": track_list}
@app.get("/audio-devices")
def get_audio_devices():
    """Récupère la liste des noms 'FriendlyName' des sorties audio actives via PowerShell."""
    cmd = 'powershell "Get-PnpDevice -Class AudioEndpoint -Status OK | Select-Object FriendlyName | ConvertTo-Json"'
    try:
        result = subprocess.check_output(cmd, shell=True).decode('utf-8')
        if not result.strip():
            return {"devices": []}
            
        data = json.loads(result)
        # Gestion du cas où il n'y a qu'un seul périphérique (objet vs liste)
        devices = [d['FriendlyName'] for d in (data if isinstance(data, list) else [data])]
        
        # Ajout de l'option virtuelle "Stream Only" (pour lire sans sortie physique)
        devices.insert(0, "Stream Only (No Sound)")
        
        return {"devices": devices}
    except Exception as e:
        print(f"Erreur audio-devices: {e}")
        # En cas d'erreur ou si pas de device, on propose au moins le Stream Only
        return {"devices": ["Stream Only (No Sound)"]}


@app.post("/set-device")
def set_device(device: str):
    """Permet au client de définir le périphérique de sortie global (pour Auto-Next)."""
    global DEVICE_ID
    print(f">>> SET DEVICE: {device}")
    DEVICE_ID = device
    return {"status": "ok", "device": DEVICE_ID}

def force_kill_mpv():
    """S'assure que mpv est mort et enterré avant de continuer."""
    global current_mpv_process
    
    print(">>> [PROCESS] FORCE KILL MPV REQUESTED")
    
    # 1. Kill via l'objet Python (plus propre)
    if current_mpv_process:
        print(">>> [PROCESS] Terminating Popen object...")
        try:
            current_mpv_process.kill()
            current_mpv_process.wait(timeout=1) # On attend qu'il crève
        except Exception as e:
            print(f">>> [PROCESS] Error killing Popen object: {e}")
        current_mpv_process = None

    # 2. Nettoyage de printemps (zombies ou lancements externes)
    # On boucle tant qu'on voit un mpv.exe (Max 2s)
    max_attempts = 20
    killed_once = False
    
    while max_attempts > 0:
        # Verification silencieuse
        check = subprocess.run('tasklist /FI "IMAGENAME eq mpv.exe" /NH', capture_output=True, text=True, shell=True)
        if "mpv.exe" in check.stdout:
            print(">>> [PROCESS] Zombie MPV detected -> TASKKILL")
            subprocess.run("taskkill /F /IM mpv.exe /T >nul 2>&1", shell=True)
            killed_once = True
            time.sleep(0.1) # Petit délai pour laisser l'OS respirer
        else:
            if killed_once:
                print(">>> [PROCESS] All MPV processes eliminated.")
            break
        
        max_attempts -= 1

    # 3. Délai de libération du driver (WASAPI est capricieux)
    # On réduit à 0.5s si tout s'est bien passé, sinon on assure.
    grace_period = 0.5
    time.sleep(grace_period)


@app.get("/play/{song_id}")
def play_song(song_id: int, device: str = None):
    """Route principale de lecture unitaire (Recherche ou Explorateur)"""
    conn = get_db_conn()
    cur = conn.cursor()
    # On récupère le chemin pour MPV
    cur.execute("SELECT path FROM tracks WHERE id = ?", (song_id,))
    res = cur.fetchone()
    conn.close()

    if res:
        # On utilise le mode "search" par défaut pour la lecture unitaire
        # FIX STABILITÉ : On force "Auto" SAUF si l'utilisateur choisit explicitement "Stream Only"
        target_dev = None
        if device == "Stream Only (No Sound)":
            target_dev = device
            
        return universal_player(res[0], current_mode, song_id, device=target_dev) 
    return {"status": "error", "message": "Song not found"}




@app.get("/volume/{level}")
def set_volume(level: int):
    global current_volume
    current_volume = int(level) # On mémorise le nouveau volume
    run_mpv_command(["set_property", "volume", current_volume])
    return {"volume": current_volume}

@app.get("/stop")
def stop():
    subprocess.run(["taskkill", "/F", "/IM", "mpv.exe"], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    return {"status": "stopped"}

@app.get("/pause")
def toggle_pause():
    run_mpv_command(["cycle", "pause"])
    return {"status": "toggled"}

@app.get("/seek/{seconds}")
def seek_time(seconds: int):
    run_mpv_command(["seek", seconds])
    return {"status": "moved"}

@app.get("/setpos/{position}")
def set_position(position: int):
    run_mpv_command(["set_property", "time-pos", int(position)])
    return {"status": "set"}

@app.get("/status")
def get_status():
    global current_playing_id, current_folder_index, current_volume, current_playlist_name, current_source

    pos = read_mpv_property("time-pos") or 0
    duration = read_mpv_property("duration") or 0
    paused = read_mpv_property("pause") or False
    
    conn = get_db_conn()
    cur = conn.cursor()

    track_info = None

    # 1. LECTURE DEPUIS TRACKS (Base de données classique)
    if current_source == "tracks" and current_playing_id:
        cur.execute("""
            SELECT id, title, artist, album, cover_path
            FROM tracks
            WHERE id = ?
        """, (current_playing_id,))
        row = cur.fetchone()
        if row:
            track_info = {
                "id": row[0],
                "title": row[1],
                "artist": row[2],
                "album": row[3],
                "cover_path": f"/cover/{row[0]}"
            }

    # 2. LECTURE DEPUIS PLAYLIST_FOLDER
    elif current_source == "playlist_folder":
        # On vérifie la valeur réelle de l'index dans le terminal
        print(f"DEBUG SQL: Recherche position = {current_folder_index} (Type: {type(current_folder_index)})")
        
        if current_folder_index is not None:
            cur.execute("""
                SELECT title, artist, album, path, cover_path
                FROM playlist_folder
                WHERE position = ?
            """, (current_folder_index,))
            row = cur.fetchone()
            
            if row:
                track_info = {
                    "id": f"folder_{current_folder_index}",
                    "title": row[0],
                    "artist": row[1],
                    "album": row[2],
                    "path": row[3],
                    "cover_path": f"/cover_folder/{current_folder_index}"
                }
            else:
                print(f"ERREUR: Position {current_folder_index} existe pas dans la table !")
        else:
            print("ERREUR: current_folder_index est None, impossible de chercher dans la table.")

    # 3. RÉCUPÉRATION DES PLAYLISTS
    cur.execute("""
        SELECT info.id, info.name, COUNT(content.id)
        FROM saved_playlists_info info
        LEFT JOIN saved_playlists_content content ON info.id = content.playlist_id
        GROUP BY info.id
        ORDER BY info.created_at DESC
    """)
    playlists_data = [{"id": r[0], "name": r[1], "count": r[2]} for r in cur.fetchall()]
    conn.close()

    # --- LE FLAG DE BUG (Juste avant le return pour que ça s'affiche !) ---
    # --- OPTIMISATION LOGS : FIN DU SPAM DEBUG ---
    # print("--- DEBUG STATUS ---") ... (Supprimé pour perf)
    
    # AJOUT DE LA SYNCHRO FULL SCAN
    scan_info = {"status": "idle", "current": 0, "total": 0} # Structure par défaut
    if os.path.exists(SCAN_STATUS_PATH):
        try:
            with open(SCAN_STATUS_PATH, "r") as f:
                content = json.load(f)
                if content: scan_info = content
        except:
            pass

    return {
        "pos": pos,
        "duration": duration,
        "paused": paused,
        "track": track_info,
        "volume": current_volume,
        "playlist_name": current_playlist_name,
        "library": playlists_data,
        "shuffle": shuffle_mode,
        "scan": scan_info
    }


# --- LIRE un ALBUM en entier ---
# Version FastAPI (à utiliser si tu as "from fastapi import ...")
@app.post("/api/play_album_now")
async def play_album_now(data: dict): # data: dict est nécessaire pour FastAPI
    album = data.get('album')
    artist = data.get('artist')

    conn = get_db_conn() 
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    try:
        c.execute("DELETE FROM playlist_album")
        
        # On récupère les morceaux depuis la table 'tracks'
        tracks = c.execute(
            "SELECT id, path FROM tracks WHERE album = ? AND artist = ? ORDER BY path", 
            (album, artist)
        ).fetchall()

        if not tracks:
            return {"error": "Album non trouvé"}

        # Conversion en dictionnaires pour le tri
        track_list = [dict(t) for t in tracks]
        # Tri Naturel Python sur le NOM DE FICHIER (basename)
        track_list.sort(key=lambda x: natural_key(os.path.basename(x['path'])))

        for index, track in enumerate(track_list):
            c.execute("INSERT INTO playlist_album (track_id, position) VALUES (?, ?)", 
                      (track['id'], index))

        conn.commit()
        return {
            "status": "success", 
            "first_id": tracks[0]['id'],
            "count": len(tracks)
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        conn.close()


# Fonction pour incrémenter la version de la bibliothèque de playlists
# Elle va permettre de forcer le rafraîchissement côté client
def bump_playlist_library_version():
    global playlist_library_version
    playlist_library_version += 1

@app.get("/api/playlists/version")
def get_playlist_library_version():
    return {"version": playlist_library_version}


def bump_playlist_active_version():
    global playlist_active_version
    playlist_active_version += 1

@app.get("/api/playlist/version")
def get_playlist_active_version():
    return {"version": playlist_active_version}


# --- PLAYLIST ---
@app.post("/playlist/add/{track_id}")
def add_to_playlist(track_id: int):
    global current_playlist_name
    conn = get_db_conn()
    cur = conn.cursor()

    # Trouver la prochaine position
    cur.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM playlist")
    pos = cur.fetchone()[0]

    # Insérer dans la playlist active
    cur.execute("INSERT INTO playlist (track_id, position) VALUES (?, ?)", (track_id, pos))

    # 🔥 AJOUT : si une playlist est active, on insère aussi dans saved_playlists_content
    cur.execute("SELECT id FROM saved_playlists_info WHERE name = ?", (current_playlist_name,))
    row = cur.fetchone()
    if row:
        playlist_id = row[0]
        cur.execute("""
            INSERT INTO saved_playlists_content (playlist_id, track_id, position)
            VALUES (?, ?, ?)
        """, (playlist_id, track_id, pos))

    conn.commit()
    conn.close()

    # 🔥 Synchro immédiate
    bump_playlist_library_version()
    bump_playlist_active_version()


    return {"status": "added"}



@app.get("/playlist")
def get_playlist():
    conn = get_db_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT playlist.track_id, tracks.title, tracks.artist
        FROM playlist
        JOIN tracks ON playlist.track_id = tracks.id
        ORDER BY playlist.position ASC
    """)

    songs = cur.fetchall()
    conn.close()

    return {"songs": [{"id": s[0], "title": s[1], "artist": s[2]} for s in songs]}

# --- VIDER la PLAYLIST ---
@app.delete("/playlist/clear")
def clear_playlist():
    global current_playlist_name
    conn = get_db_conn()
    cur = conn.cursor()
    
    # 1. Vider la playlist active
    cur.execute("DELETE FROM playlist")
    
    # 2. Si on est sur une playlist sauvegardée, on VIDE aussi son contenu sauvegardé
    # (Comportement attendu : "Vider" vide vraiment tout)
    if current_playlist_name and current_playlist_name != "Playlist":
        try:
            cur.execute("SELECT id FROM saved_playlists_info WHERE name = ?", (current_playlist_name,))
            row = cur.fetchone()
            if row:
                playlist_id = row[0]
                cur.execute("DELETE FROM saved_playlists_content WHERE playlist_id = ?", (playlist_id,))
        except Exception as e:
            print(f"Erreur lors du vidage de la sauvegarde : {e}")

    # 3. On ne change PAS le nom pour rester sur la playlist actuelle
    # current_playlist_name reste inchangé

    conn.commit()
    conn.close()

    # 4. On notifie tout le monde
    bump_playlist_library_version()
    bump_playlist_active_version()

    return {"status": "cleared", "playlist_name": current_playlist_name}



# --- GESTION DES PLAYLISTS SAUVEGARDÉES ---
@app.post("/api/playlists/create")
async def create_new_playlist_db(request: Request):
    global current_playlist_name
    data = await request.json()
    name = data.get('name')
    
    if not name:
        return {"error": "Nom manquant"}

    conn = get_db_conn()
    c = conn.cursor()
    try:
        c.execute("INSERT OR IGNORE INTO saved_playlists_info (name) VALUES (?)", (name,))
        c.execute("SELECT id FROM saved_playlists_info WHERE name = ?", (name,))
        playlist_id = c.fetchone()[0]

        c.execute("DELETE FROM playlist")

        current_playlist_name = name
        
        conn.commit()

        # 🔥 Synchro immédiate
        bump_playlist_library_version()
        bump_playlist_active_version()

        return {"status": "success", "id": playlist_id, "name": name}
    except Exception as e:
        return {"error": str(e)}
    finally:
        conn.close()


@app.post('/api/playlists/save')
async def save_playlist(request: Request):
    data = await request.json()
    name = data.get('name')
    
    if not name:
        return {"error": "Nom manquant"}

    conn = get_db_conn()
    c = conn.cursor()
    try:
        # 1. Vérifier si la playlist existe
        c.execute("SELECT id FROM saved_playlists_info WHERE name = ?", (name,))
        row = c.fetchone()

        if row:
            playlist_id = row[0]
            # Supprimer l'ancien contenu
            c.execute("DELETE FROM saved_playlists_content WHERE playlist_id = ?", (playlist_id,))
        else:
            # Créer une nouvelle entrée
            c.execute("INSERT INTO saved_playlists_info (name) VALUES (?)", (name,))
            playlist_id = c.lastrowid

        # 2. Récupérer les morceaux de la file d'attente actuelle
        c.execute("SELECT track_id, position FROM playlist ORDER BY position")
        current_tracks = c.fetchall()

        # 3. Sauvegarder les morceaux
        for track in current_tracks:
            c.execute("""
                INSERT INTO saved_playlists_content (playlist_id, track_id, position)
                VALUES (?, ?, ?)
            """, (playlist_id, track[0], track[1]))

        conn.commit()

        # 🔥 AJOUT : notifier tous les devices
        bump_playlist_library_version()

        return {"status": "success", "message": "Playlist enregistrée"}

    except Exception as e:
        print(f"Erreur SQL: {e}")
        return {"error": str(e)}
    finally:
        conn.close()


@app.get("/api/playlists")
def list_saved_playlists():
    """Renvoie la liste de toutes les playlists enregistrées."""
    conn = get_db_conn()
    c = conn.cursor()
    # On récupère le nom, la date, et on compte le nombre de morceaux au passage !
    c.execute("""
        SELECT info.id, info.name, info.created_at, COUNT(content.id)
        FROM saved_playlists_info info
        LEFT JOIN saved_playlists_content content ON info.id = content.playlist_id
        GROUP BY info.id
        ORDER BY info.created_at DESC
    """)
    rows = cur = c.fetchall()
    conn.close()
    return {
        "playlists": [
            {"id": r[0], "name": r[1], "date": r[2], "count": r[3]} 
            for r in rows
        ]
    }

@app.post("/api/playlists/load")
async def load_saved_playlist(data: dict):
    global shuffle_mode, current_playlist_name  # Mise à jour des deux globales
    playlist_id = data.get("id")
    if not playlist_id:
        return {"error": "ID de playlist manquant"}

    conn = get_db_conn()
    c = conn.cursor()
    try:
        # 0. Récupérer le nom de la playlist pour la synchro
        c.execute("SELECT name FROM saved_playlists_info WHERE id = ?", (playlist_id,))
        res_name = c.fetchone()
        if res_name:
            current_playlist_name = res_name[0]

        # 1. On vide TOUT pour repartir à neuf
        c.execute("DELETE FROM playlist")
        c.execute("DELETE FROM shuffled_playlist")
        c.execute("DELETE FROM playlist_album")
        
        # 2. On désactive le mode shuffle côté serveur
        shuffle_mode = False 

        # 3. On injecte les morceaux de la sauvegarde
        c.execute("""
            INSERT INTO playlist (track_id, position)
            SELECT track_id, position 
            FROM saved_playlists_content 
            WHERE playlist_id = ?
            ORDER BY position ASC
        """, (playlist_id,))

        conn.commit()
        conn.commit()
        bump_playlist_active_version()
        # On bump aussi la bibliothèque car on a potentiellement changé le focus ou l'état actif
        bump_playlist_library_version() 
        return {"status": "success"}
    except Exception as e:
        bump_playlist_active_version()
        return {"error": str(e)}
    finally:
        conn.close()


@app.delete("/api/playlists/{playlist_id}")
def delete_saved_playlist(playlist_id: int):
    """Supprime définitivement une playlist du catalogue."""
    conn = get_db_conn()
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        c = conn.cursor()
        c.execute("DELETE FROM saved_playlists_info WHERE id = ?", (playlist_id,))
        conn.commit()

        # 🔥 AJOUT : notifier tous les devices que la grille a changé
        bump_playlist_library_version()

        return {"status": "deleted"}

    finally:
        conn.close()

@app.post("/api/playlists/rename")
def rename_saved_playlist(data: dict):
    conn = get_db_conn()
    try:
        playlist_id = data.get("id")
        new_name = data.get("name")
        
        if not playlist_id or not new_name:
            return {"error": "Paramètres manquants"}

        c = conn.cursor()
        c.execute("UPDATE saved_playlists_info SET name = ? WHERE id = ?", (new_name, playlist_id))
        conn.commit()

        # 🔥 AJOUT : notifier tous les devices que la grille a changé
        bump_playlist_library_version()

        return {"status": "success"}

    except Exception as e:
        print(f"Erreur Rename: {e}")
        return {"error": str(e)}
    finally:
        conn.close()



@app.delete("/playlist/remove/{track_id}")
def remove_from_playlist(track_id: int):
    global current_playlist_name
    conn = get_db_conn()
    cur = conn.cursor()

    # Supprimer dans la playlist active
    cur.execute("DELETE FROM playlist WHERE track_id = ?", (track_id,))

    # 🔥 Supprimer aussi dans la sauvegarde si une playlist est active
    cur.execute("SELECT id FROM saved_playlists_info WHERE name = ?", (current_playlist_name,))
    row = cur.fetchone()
    if row:
        playlist_id = row[0]
        cur.execute("DELETE FROM saved_playlists_content WHERE playlist_id = ? AND track_id = ?", (playlist_id, track_id))

    conn.commit()
    conn.close()

    # 🔥 Synchro immédiate
    bump_playlist_library_version()
    bump_playlist_active_version()

    return {"status": "removed"}



# --- SHUFFLE ---
# ACTIVER
@app.post("/shuffle/enable")
def enable_shuffle():
    global shuffle_mode
    conn = get_db_conn()
    cur = conn.cursor()

    # On récupère la playlist actuelle dans l'ordre
    cur.execute("SELECT track_id FROM playlist ORDER BY position ASC")
    rows = cur.fetchall()
    track_ids = [r[0] for r in rows]

    # On vide la shuffled_playlist
    cur.execute("DELETE FROM shuffled_playlist")

    if track_ids:
        # Mélange sans remise
        random.shuffle(track_ids)
        # On réinsère avec une position 1..N
        for idx, tid in enumerate(track_ids, start=1):
            cur.execute(
                "INSERT INTO shuffled_playlist (track_id, position) VALUES (?, ?)",
                (tid, idx),
            )

    conn.commit()
    conn.close()

    shuffle_mode = True
    return {"status": "enabled", "count": len(track_ids)}

# DESACTIVER
@app.post("/shuffle/disable")
def disable_shuffle():
    global shuffle_mode
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM shuffled_playlist")
    conn.commit()
    conn.close()

    shuffle_mode = False
    return {"status": "disabled"}

#SHUFFLE Status
@app.get("/shuffle/status")
def shuffle_status():
    return {"shuffle": shuffle_mode}


# Route pour obtenir la prochaine chanson
from fastapi import Query
from typing import Union

@app.get("/next")
def get_next(current_id: str = Query(None)):
    global current_playing_id, current_mode, current_source, current_folder_index
    
    # 1. Déterminer l'ID sur lequel on se base
    target_id = current_id
    if current_id in [None, "undefined", "", "null"]:
        target_id = current_playing_id

    print(f">>> ROUTE /next : Cible actuelle = {target_id}")

    # --- CAS MODE FOLDER ---
    if current_source == "playlist_folder" or (target_id and str(target_id).startswith("folder_")):
        # On s'assure d'avoir l'index actuel
        try:
            if target_id and "folder_" in str(target_id):
                # On extrait le chiffre après "folder_" au cas où le global soit décalé
                idx_actuel = int(str(target_id).split("_")[1])
            else:
                idx_actuel = current_folder_index if current_folder_index is not None else 0
            
            new_index = idx_actuel + 1
            print(f"FOLDER NEXT : Passage de {idx_actuel} à {new_index}")
            
            # On vérifie en BDD si l'index suivant existe
            conn = get_db_conn()
            cur = conn.cursor()
            cur.execute("SELECT position FROM playlist_folder WHERE position = ?", (new_index,))
            exists = cur.fetchone()
            conn.close()
            
            if exists:
                return play_folder_track_pos(new_index)
            else:
                print("Fin du dossier atteint, retour au début (0)")
                return play_folder_track_pos(0)
        except Exception as e:
            print(f"Erreur calcul Next Folder: {e}")
            return play_folder_track_pos(0)

    # --- CAS CLASSIQUE ---
    next_data = handle_next(target_id)
    if next_data and "id" in next_data:
        conn = get_db_conn()
        res = conn.execute("SELECT path FROM tracks WHERE id=?", (next_data["id"],)).fetchone()
        conn.close()
        if res:
            return universal_player(res[0], current_mode, next_data["id"])

    return {"status": "end"}
@app.get("/previous")
def get_previous(current_id: str = Query(None)):
    global current_playing_id, current_mode, current_source, current_folder_index
    
    # 1. On récupère l'ID cible (identique à la logique de /next)
    target_id = current_id
    if target_id in [None, "undefined", "", "null"]:
        target_id = str(current_playing_id)

    print(f">>> DEBUG PREVIOUS : ID cible est {target_id}")

    # --- CAS LOGIQUE DOSSIER (ADELE) ---
    if "folder_" in str(target_id):
        try:
            # On extrait l'index actuel du nom "folder_X"
            idx_actuel = int(str(target_id).split("_")[1])
            
            # On calcule le précédent (en s'arrêtant à 0)
            new_index = max(0, idx_actuel - 1)
            
            print(f">>> FOLDER PREV détecté : de {idx_actuel} vers {new_index}")
            
            # On utilise la fonction de lecture qui gère tout (Header + MPV)
            return play_folder_track_pos(new_index)
            
        except Exception as e:
            print(f">>> Erreur Prev Folder : {e}")
            return play_folder_track_pos(0)

    # --- CAS LOGIQUE BDD CLASSIQUE ---
    print(">>> Passage par handle_previous classique")
    prev_data = handle_previous(target_id)
    if prev_data and "id" in prev_data:
        conn = get_db_conn()
        res = conn.execute("SELECT path FROM tracks WHERE id=?", (prev_data["id"],)).fetchone()
        conn.close()
        if res:
            return universal_player(res[0], current_mode, prev_data["id"])

    return {"status": "start", "message": "Début de liste"}

# VIDER la TABLE ALBUM (avant d'en charger un nouveau)
@app.post("/api/clear_album_table")
def clear_album_table():
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM playlist_album")
    conn.commit()
    conn.close()
    return {"status": "cleared"}

#récupérer les covers
@app.get("/cover/{track_id}")
async def get_cover(track_id: int):
    conn = get_db_conn()
    cursor = conn.cursor()
    # On récupère le chemin de la pochette pour ce morceau
    cursor.execute("SELECT cover_path FROM tracks WHERE id = ?", (track_id,))
    row = cursor.fetchone()
    conn.close()

    if row and row[0]:
        cover_path = row[0]
        if os.path.exists(cover_path):
            return FileResponse(cover_path)
    
    # Si pas d'image, on envoie une image par défaut
    return FileResponse("static/default_cover.png")

# --- STREAMING AUDIO POUR LE NAVIGATEUR (RELAY) ---

@app.get("/stream/track/{track_id}")
async def stream_track(track_id: int):
    conn = get_db_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT path FROM tracks WHERE id = ?", (track_id,))
    row = cursor.fetchone()
    conn.close()
    if row and row[0] and os.path.exists(row[0]):
        return FileResponse(row[0])
    raise HTTPException(status_code=404, detail="Track not found")

@app.get("/stream/folder/{position}")
async def stream_folder(position: int):
    conn = get_db_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT path FROM playlist_folder WHERE position = ?", (position,))
    row = cursor.fetchone()
    conn.close()
    if row and row[0] and os.path.exists(row[0]):
        return FileResponse(row[0])
    raise HTTPException(status_code=404, detail="Folder track not found")

# Montage des fichiers statiques
app.mount("/static", StaticFiles(directory=STATIC_PATH), name="static")


# --- INFOS SUR LA LECTURE EN COURS ---

@app.get("/current_playing")
def get_current_playing():
    global current_source, current_playing_id, current_folder_index

    # --- 1. Aucune lecture en cours ---
    if current_source is None or current_source == "none":
        return {"source": "none"}

    # --- 2. Lecture depuis la table TRACKS (playlist BDD) ---
    if current_source == "tracks" and current_playing_id is not None:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT title, artist, album, cover_path
            FROM tracks
            WHERE id = ?
        """, (current_playing_id,))
        row = cur.fetchone()
        conn.close()

        if row:
            title, artist, album, cover_path = row
            return {
                "source": "tracks",
                "id": current_playing_id,
                "title": title,
                "artist": artist,
                "album": album,
                "cover_path": cover_path
            }

        return {"source": "tracks", "error": "Track not found"}

    # --- 3. Lecture depuis FOLDER_SHOW (explorateur de dossiers) ---
    if current_source == "folder_show" and current_folder_index >= 0:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT title, artist, album, cover_url
            FROM folder_show
            WHERE position = ?
        """, (current_folder_index,))
        row = cur.fetchone()
        conn.close()

        if row:
            title, artist, album, cover_url = row
            return {
                "source": "folder_show",
                "position": current_folder_index,
                "title": title,
                "artist": artist,
                "album": album,
                "cover_url": cover_url
            }

        return {"source": "folder_show", "error": "Track not found"}

    # --- 4. Cas inattendu ---
    return {"source": "none"}


# **************************************************************** EXPLORATION FICHIERS **********************************************************************

def natural_key(text):
    """
    Clé de tri pour un tri naturel (Ex: 1, 2, 10 au lieu de 1, 10, 2).
    Sépare le texte en liste de chaînes et d'entiers.
    """
    return [int(c) if c.isdigit() else c.lower() for c in re.split('([0-9]+)', str(text))]


@app.get("/api/files/browse")
def browse_files(path: str = ""):
    search_prefix = os.path.join(MUSIC_FOLDER, path.replace("/", "\\"))
    if not search_prefix.endswith("\\"):
        search_prefix += "\\"

    items = []
    try:
        conn = get_db_conn()
        cur = conn.cursor()

        # 1. On récupère TOUS les morceaux qui ont un défaut (full != 1)
        # On crée un dictionnaire : { "chemin/complet/du/fichier": status }
        cur.execute("SELECT path, full FROM tracks WHERE full != 1")
        error_map = {row[0]: row[1] for row in cur.fetchall()}

        # --- 1. DOSSIERS ---
        query_dirs = """
            SELECT DISTINCT 
                SUBSTR(path, LENGTH(?) + 1, INSTR(SUBSTR(path, LENGTH(?) + 1), '\\') - 1) as subfolder
            FROM tracks 
            WHERE path LIKE ? || '%\\%'
        """
        cur.execute(query_dirs, (search_prefix, search_prefix, search_prefix))
        
        for row in cur.fetchall():
            folder_name = row[0]
            if folder_name:
                full_folder_path = os.path.join(search_prefix, folder_name)
                
                # On cherche les statuts des erreurs contenues dans ce dossier
                relevant_errors = [status for p, status in error_map.items() if p.startswith(full_folder_path)]
                
                # Logique de dossier : 
                # - Si erreurs présentes, on prend la valeur la plus petite (0 est prioritaire sur 2 ou 3)
                # - Si pas d'erreurs, le statut est 1 (OK)
                folder_status = min(relevant_errors) if relevant_errors else 1

                items.append({
                    "name": folder_name, 
                    "type": "directory",
                    "path": os.path.join(path, folder_name).replace("\\", "/"),
                    "status": int(folder_status) 
                })

        # --- 2. FICHIERS ---
        query_files = """
            SELECT id, path, artist, full 
            FROM tracks 
            WHERE path LIKE ? || '%' 
            AND SUBSTR(path, LENGTH(?) + 1) NOT LIKE '%\\%'
        """
        cur.execute(query_files, (search_prefix, search_prefix))
        
        for row in cur.fetchall():
            items.append({
                "id": row[0],
                "name": os.path.basename(row[1]),
                "type": "file",
                "path": row[1],
                "artist": row[2],
                "status": row[3] # Renvoie 0, 1, 2 ou 3
            })

        conn.close()
        # Tri Naturel : Dossiers d'abord, puis fichiers
        items.sort(key=lambda x: (x['type'] != 'directory', natural_key(x['name'])))
        p_path = "/".join(path.replace("\\", "/").strip("/").split("/")[:-1])
        
        return {"items": items, "parent_path": p_path}
    except Exception as e:
        print(f"Erreur browse_files: {e}")
        return {"error": str(e)}


# *********************************************** Lecture en mode FOLDER  ******************************************************
# --- NOUVELLE ROUTE POUR LE MODE DOSSIER ---
@app.get("/play_folder")
def play_folder_track(path: str, device: str = None):
    """Force le mode folder et joue un fichier par son chemin."""
    global current_mode, current_playing_id, current_source
    
    current_mode = "folder"
    current_source = "playlist_folder" # Important pour ton status
    current_playing_id = path # En mode folder, l'ID est le chemin
    
    # On utilise ta fonction existante qui appelle MPV
    play_song_by_path(path) 
    return {"status": "playing_folder", "path": path}


@app.get("/folder_show/play/{position}")
def play_folder_track_pos(position: int, device: str = None):
    # Ajout de current_source ici pour être sûr qu'on bascule bien le mode
    global current_folder_index, current_source 
    print(f">>> FOLDER PLAY : Position {position}")
    
    conn = get_db_conn()
    cur = conn.cursor()

    try:
        # 1. Reconstruction de la table temporaire
        cur.execute("DELETE FROM playlist_folder")
        cur.execute("""
            INSERT INTO playlist_folder (position, title, artist, album, path, cover_path)
            SELECT 
                ROW_NUMBER() OVER (ORDER BY id) - 1 AS position,
                title, artist, album, path, cover_path
            FROM folder_show
            ORDER BY id ASC
        """)
        conn.commit()

        # 2. Récupération du chemin
        cur.execute("SELECT path FROM playlist_folder WHERE position = ?", (position,))
        row = cur.fetchone()
        
        if row:
            file_path = row[0]
            # ON FIXE LES GLOBALES AVANT D'APPELER LE PLAYER
            current_folder_index = position
            current_source = "playlist_folder"
            
            # On appelle le player avec l'index comme identifier
            return universal_player(file_path, "folder", position, device)
            
        return {"status": "error", "message": "Position non trouvée"}

    except Exception as e:
        print(f"Erreur dans play_folder_track_pos: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()

# *********************************************** Lire toutl'album en mode FOLDER  ******************************************************
@app.post("/api/play_folder_now")
async def play_folder_now(data: dict):
    folder_path = data.get("path")
    if not folder_path:
        return {"error": "Path manquant"}

    search_path = os.path.join(MUSIC_FOLDER, folder_path.replace("/", "\\"))
    if not search_path.endswith("\\"):
        search_path += "\\"

    conn = get_db_conn()
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT id, path FROM tracks 
            WHERE path LIKE ? || '%' 
            ORDER BY path ASC
        """, (search_path,))
        rows = cur.fetchall()

        if not rows:
            return {"error": "Dossier vide ou introuvable"}

        # Conversion et Tri Naturel sur le chemin (path)
        # rows est une liste de tuples (id, path)
        track_list = [{"id": r[0], "path": r[1]} for r in rows]
        track_list.sort(key=lambda x: natural_key(os.path.basename(x['path'])))

        # On vide la table
        cur.execute("DELETE FROM playlist_album")
        
        # INSERTION AVEC POSITION
        # On utilise enumerate pour générer l'index (0, 1, 2...)
        for index, track in enumerate(track_list):
            cur.execute("""
                INSERT INTO playlist_album (track_id, position) 
                VALUES (?, ?)
            """, (track['id'], index))
        
        conn.commit()

        # On retourne le premier ID pour lancer la lecture
        return {"first_id": track_list[0]['id']}

    except Exception as e:
        print(f"Erreur play_folder_now: {e}")
        return {"error": str(e)}
    finally:
        conn.close()

#Mettre la liste ci-dessous dans la playlist 
@app.get("/api/folder/get_all_ids")
def get_folder_ids(path: str):
    search_path = os.path.join(MUSIC_FOLDER, path.replace("/", "\\"))
    if not search_path.endswith("\\"):
        search_path += "\\"

    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM tracks WHERE path LIKE ? || '%' ORDER BY path ASC", (search_path,))
    ids = [row[0] for row in cur.fetchall()]
    conn.close()
    
    return {"ids": ids}

#Ajouter la liste du repertoire dans la playlist
@app.post("/api/folder/add_to_playlist")
async def add_folder_to_playlist_db(data: dict):
    global current_playlist_name  # On récupère le nom de la playlist active
    path = data.get("path")
    
    if not path:
        return {"status": "error", "message": "Chemin manquant"}

    conn = get_db_conn()
    cur = conn.cursor()

    try:
        # 1. On récupère les IDs du dossier
        search_path = os.path.join(MUSIC_FOLDER, path.replace("/", "\\"))
        if not search_path.endswith("\\"): search_path += "\\"
        
        cur.execute("SELECT id FROM tracks WHERE path LIKE ? || '%' ORDER BY path ASC", (search_path,))
        track_ids = [row[0] for row in cur.fetchall()]

        if not track_ids:
            return {"status": "error", "message": "Aucun morceau trouvé"}

        # 2. Position pour la file d'attente (playlist)
        cur.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM playlist")
        pos_p = cur.fetchone()[0]

        # 3. Récupérer l'ID de la playlist sauvegardée via son NOM (comme ton ancien code)
        cur.execute("SELECT id FROM saved_playlists_info WHERE name = ?", (current_playlist_name,))
        row = cur.fetchone()
        playlist_id = row[0] if row else None

        # 4. On boucle pour tout insérer
        for t_id in track_ids:
            # Dans la file d'attente immédiate
            cur.execute("INSERT INTO playlist (track_id, position) VALUES (?, ?)", (t_id, pos_p))
            
            # Dans la playlist sauvegardée (si elle existe)
            if playlist_id:
                cur.execute("""
                    INSERT INTO saved_playlists_content (playlist_id, track_id, position)
                    VALUES (?, ?, ?)
                """, (playlist_id, t_id, pos_p))
            
            pos_p += 1
        
        conn.commit()
        
        # 🔥 Les deux fonctions de synchro que tu avais oubliées !
        bump_playlist_library_version()
        bump_playlist_active_version()
        
        return {"status": "success", "count": len(track_ids)}

    except Exception as e:
        print(f"Erreur Folder Add: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()


# Fonction universelle de lecture

def universal_player(file_path, mode, identifier, device=None):
    # On déclare TOUTES les globales nécessaires
    global current_mode, current_playing_id, current_source, current_volume, DEVICE_ID, current_folder_index, current_mpv_process
    
    print(f">>> PLAYER UNIFIÉ : Mode={mode} | Identifier={identifier}")
    
    # 1. Mise à jour de l'état global
    current_mode = mode
    
    if mode == "folder":
        current_source = "playlist_folder"
        current_playing_id = f"folder_{identifier}" 
        current_folder_index = identifier
    else:
        current_source = "tracks"
        current_playing_id = identifier
        current_folder_index = None 

    # 2. RECHERCHE DES INFOS POUR LE RETOUR API (Header)
    track_info = {"title": "---", "artist": "---", "album": "---", "cover_path": ""}
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        if mode == "folder":
            cur.execute("SELECT title, artist, album FROM playlist_folder WHERE position = ?", (identifier,))
        else:
            cur.execute("SELECT title, artist, album FROM tracks WHERE id = ?", (identifier,))
        
        res = cur.fetchone()
        if res:
            # On génère l'URL de l'image selon le mode
            c_url = f"/cover_folder/{identifier}" if mode == "folder" else f"/cover/{identifier}"
            track_info = {
                "title": res[0], 
                "artist": res[1], 
                "album": res[2], 
                "cover_path": c_url
            }
        conn.close()
    except Exception as e:
        print(f"Erreur SQL Metadata: {e}")

    # 3. Lancement MPV
    force_kill_mpv()
    target_device = device if device else DEVICE_ID
    
    target_device = device if device else DEVICE_ID
    
    # Construction des arguments MPV
    if target_device == "Stream Only (No Sound)":
        # Mode "Silence" : On décode tout mais on ne sort aucun son sur le serveur
        audio_arg = "--ao=null"
    else:
        # Mode Classique
        audio_arg = f"--audio-device={target_device}"

    args = [
        MPV_PATH, file_path, "--no-video", "--force-window=no", "--no-terminal",
        audio_arg, f"--input-ipc-server={IPC_PIPE}",
        f"--volume={current_volume}"
    ]
    
    # Un seul lancement
    current_mpv_process = subprocess.Popen(args, creationflags=0x08000000)

    # 4. Réponse JSON unique et complète
    return {
        "status": "playing", 
        "mode": mode, 
        "id": current_playing_id,
        "title": track_info["title"],
        "artist": track_info["artist"],
        "album": track_info["album"],
        "cover_path": track_info["cover_path"]
    }


# MODAL INFO : infopipeline.py
from fastapi import HTTPException
from pydantic import BaseModel
import os

# Importation de tes fonctions depuis infopipeline.py
from infopipeline import get_acoustid_data, preparer_affiche_album

# Structure de la requête attendue
class InfoRequest(BaseModel):
    path: str

@app.post("/api/analyze_folder_info")
async def analyze_folder_info(request_data: InfoRequest):
    file_path = request_data.path
    
    # Fallback par défaut
    fallback = {
        "id_found": False,
        "nom_album": "Inconnu",
        "nom_artiste": "Artiste Inconnu",
        "annee": "N/A",
        "pochette": "/static/default_cover.png",
        "pochette_fallback": "/static/default_cover.png",
        "mbid_album": "N/A",
        "confiance": 0,
        "liens": {}
    }

    try:
        if not file_path or not os.path.exists(file_path):
            return {**fallback, "error": "Fichier introuvable"}

        print(f"🔍 Analyse acoustique lancée : {file_path}")

        # 1. Calcul de l'empreinte via AcoustID
        acoustid_res = get_acoustid_data(file_path)
        if not acoustid_res:
            return {**fallback, "error": "Empreinte non générée"}

        # 2. Enrichissement via MusicBrainz
        affiche = preparer_affiche_album(acoustid_res)
        if not affiche:
            return {**fallback, "error": "Non identifié sur MusicBrainz"}

        # Succès
        return {**affiche, "id_found": True}

    except Exception as e:
        print(f"❌ Erreur Pipeline : {str(e)}")
        return {**fallback, "error": str(e)}

# Route pour télécharger une meilleure cover (Syntaxe FastAPI pure)
@app.post("/download_cover") # On utilise .post au lieu de .route
async def download_cover(request: Request):
    try:
        # On attend la réception du JSON
        data = await request.json()
        img_url = data.get('url')
        file_path = data.get('file_path')
        
        if not img_url or not file_path:
            return {"status": "error", "message": "Données manquantes (URL ou Chemin)"}

        # Nettoyage du chemin : on gère les éventuels // de réseau ou antislashs
        # os.path.dirname récupère le dossier du fichier mp3
        folder_path = os.path.dirname(file_path)
        
        # On définit la cible : cover.jpg
        target_path = os.path.join(folder_path, "cover.jpg")
        
        print(f"📥 Tentative de téléchargement vers : {target_path}")

        # Téléchargement de l'image (via requests)
        import requests # Assure-toi qu'il est importé
        response = requests.get(img_url, timeout=15)
        
        if response.status_code == 200:
            with open(target_path, 'wb') as f:
                f.write(response.content)
            print(f"✅ Succès ! Image enregistrée.")
            return {"status": "success", "message": "cover.jpg a été remplacé !"}
        
        return {"status": "error", "message": f"Erreur serveur image (Code {response.status_code})"}
        
    except Exception as e:
        print(f"❌ Erreur critique download_cover : {str(e)}")
        return {"status": "error", "message": str(e)}
    

######################################## ROUTE LANCER LA FULL RÉ-INDEXATION ########################################

import threading
from fastapi.responses import StreamingResponse
import indexMusicinDB
import fastReIndex

@app.get("/api/run_reindex")
async def run_reindex(request: Request):
    global active_scan_process
    
    # Re-attachement
    if active_scan_process and active_scan_process.is_alive():
        print("[SCAN] Re-attachement au scan Deep en cours...")
        async def reattach_stream():
            last_content = ""
            while active_scan_process and active_scan_process.is_alive():
                if await request.is_disconnected():
                    print("[SCAN] Client déconnecté (Reattach)")
                    break
                if os.path.exists(SCAN_STATUS_PATH):
                    try:
                        with open(SCAN_STATUS_PATH, "r") as f:
                            content = f.read().strip()
                            if content and content != last_content:
                                yield f"data: {content}\n\n"
                                last_content = content
                    except: pass
                await asyncio.sleep(1)
            yield "data: {\"done\": true}\n\n"
        return StreamingResponse(reattach_stream(), media_type="text/event-stream")

    def run_scan_thread():
        indexMusicinDB.run_scan()

    async def generate_progress():
        global active_scan_process
        print("[SCAN] Lancement d'un nouveau scan Deep (Thread)...")
        
        if os.path.exists(SCAN_STATUS_PATH):
            try: os.remove(SCAN_STATUS_PATH)
            except: pass

        active_scan_process = threading.Thread(target=run_scan_thread)
        active_scan_process.start()
        
        last_content = ""
        while active_scan_process.is_alive():
            if await request.is_disconnected():
                print("[SCAN] Client déconnecté (Deep Scan)")
                break

            if os.path.exists(SCAN_STATUS_PATH):
                try:
                    with open(SCAN_STATUS_PATH, "r") as f:
                        content = f.read().strip()
                        if content and content != last_content:
                            yield f"data: {content}\n\n"
                            last_content = content
                except: pass
            await asyncio.sleep(1) 
        
        # Dernier check
        if os.path.exists(SCAN_STATUS_PATH) and not await request.is_disconnected():
            try:
                with open(SCAN_STATUS_PATH, "r") as f:
                     content = f.read().strip()
                     if content and content != last_content:
                        yield f"data: {content}\n\n"
            except: pass

        yield "data: {\"done\": true}\n\n"

    return StreamingResponse(generate_progress(), media_type="text/event-stream")

@app.get("/api/run_fast_reindex")
async def run_fast_reindex(request: Request):
    global active_scan_process
    
    if active_scan_process and active_scan_process.is_alive():
        print("[SCAN] Re-attachement au scan Fast en cours...")
        async def reattach_stream():
            last_content = ""
            while active_scan_process and active_scan_process.is_alive():
                if await request.is_disconnected():
                    print("[SCAN] Client déconnecté (Reattach Fast)")
                    break
                if os.path.exists(FAST_SCAN_STATUS_PATH):
                    try:
                        with open(FAST_SCAN_STATUS_PATH, "r") as f:
                            content = f.read().strip()
                            if content and content != last_content:
                                yield f"data: {content}\n\n"
                                last_content = content
                    except: pass
                await asyncio.sleep(0.5)
            yield "data: {\"done\": true}\n\n"
        return StreamingResponse(reattach_stream(), media_type="text/event-stream")

    def run_fast_thread():
        fastReIndex.run_fast_scan()

    async def generate_progress():
        global active_scan_process
        print("[SCAN] Lancement d'un nouveau scan Fast (Thread)...")
        
        if os.path.exists(FAST_SCAN_STATUS_PATH):
            try: os.remove(FAST_SCAN_STATUS_PATH)
            except: pass

        active_scan_process = threading.Thread(target=run_fast_thread)
        active_scan_process.start()
        
        last_content = ""
        while active_scan_process.is_alive():
            if await request.is_disconnected():
                print("[SCAN] Client déconnecté (Fast Scan)")
                break

            if os.path.exists(FAST_SCAN_STATUS_PATH):
                try:
                    with open(FAST_SCAN_STATUS_PATH, "r") as f:
                        content = f.read().strip()
                        if content and content != last_content:
                            yield f"data: {content}\n\n"
                            last_content = content
                except: pass
            await asyncio.sleep(0.5)
        
        if os.path.exists(FAST_SCAN_STATUS_PATH) and not await request.is_disconnected():
            try:
                with open(FAST_SCAN_STATUS_PATH, "r") as f:
                        content = f.read().strip()
                        if content and content != last_content:
                            yield f"data: {content}\n\n"
            except: pass

        yield "data: {\"done\": true}\n\n"

    return StreamingResponse(generate_progress(), media_type="text/event-stream")

# LA STATUS DE LA FULL

from fastapi import Request
import json
import os

@app.post("/api/get_tag_suggestions")
async def get_tag_suggestions(data: dict):
    print("\n[DEBUG] Route /api/get_tag_suggestions appelee")
    filepath = data.get("path")
    mbid = data.get("mbid")
    discogs_id = data.get("discogs_id")
    force_path = data.get("force_path", False)
    
    if not filepath:
        print("[DEBUG] Erreur: Path manquant")
        return {"error": "Chemin du fichier manquant"}

    try:
        t_start = time.time()
        # 1. Récupérer la liste des fichiers locaux du dossier
        print(f"[DEBUG] Appel suggestions pour: {filepath} (ForcePath: {force_path})")
        local_files = tag.get_local_files_from_dir(filepath)
        print(f"[DEBUG] {len(local_files)} fichiers locaux trouvés")
        
        # 2. Récupérer les suggestions via le moteur
        print("[DEBUG] Etape 2: poc_engine en cours...")
        remote_tracks = tag.poc_engine(filepath, manual_discogs_id=discogs_id, target_track_count=len(local_files), mbid_album=mbid, force_path_fallback=force_path)
        
        # 3. MATCHING INTELLIGENT (Duree + Fuzzy)
        print("[DEBUG] Etape 3: Matching Intelligent...")
        folder_dir = os.path.dirname(filepath)
        local_files_full_paths = [os.path.join(folder_dir, f) for f in local_files]
        
        # Si on n'a pas de suggestions (echec web), on fait une liste vide
        if not remote_tracks:
            remote_tracks = []
            
        matched_pairs = tag.match_files_to_tracks(local_files_full_paths, remote_tracks)
        
        duration = time.time() - t_start
        print(f"[DEBUG] Suggestions terminées en {duration:.2f}s ({len(matched_pairs)} paires)")
        
        return {
            "matched_pairs": matched_pairs,
            "mbid_album": mbid
        }
    except Exception as e:
        print(f"[DEBUG] ERREUR CRITIQUE API: {e}")
        return {"error": str(e)}

@app.post("/api/apply_tags")
async def apply_tags(data: dict):
    print("\n[DEBUG] Route /api/apply_tags appelee")
    folder_path = data.get("folder_path")
    mappings = data.get("mappings") # Liste de {file: "filename", metadata: {...}}
    rename_files = data.get("rename_files", False) # Nouveau flag
    
    if not mappings:
        return {"error": "Aucune modification à appliquer"}

    results = []
    success_count = 0
    
    for item in mappings:
        filename = item.get("file")
        metadata = item.get("metadata")
        track_number = item.get("track_number") # Récupéré depuis l'input utilisateur

        # On reconstruit le chemin complet
        full_path = os.path.join(os.path.dirname(folder_path), filename)
        
        # 1. APPLICATION DES TAGS (Sur le fichier d'origine)
        ok, msg = tag.apply_metadata_to_file(full_path, metadata)
        
        current_path = full_path
        
        # 2. RENOMMAGE (Optionnel et si tag OK)
        if ok and rename_files and track_number and metadata.get("title"):
             try:
                # Format: 01 - Titre.mp3
                # Extension d'origine
                _, ext = os.path.splitext(filename)
                
                # Nettoyage du titre pour être un nom de fichier valide
                import re
                safe_title = re.sub(r'[\\/*?:"<>|]', "", metadata["title"])
                
                new_filename = f"{int(track_number):02d} - {safe_title}{ext}"
                new_full_path = os.path.join(os.path.dirname(folder_path), new_filename)
                
                # On renomme seulement si le nom change
                if new_full_path != current_path:
                    os.rename(current_path, new_full_path)
                    print(f"[RENAME] {filename} -> {new_filename}")
                    msg += f" + Renommé en {new_filename}"
             except Exception as e:
                print(f"[RENAME ERROR] {e}")
                msg += f" (Erreur renommage: {e})"

        if ok:
            success_count += 1
        results.append({"file": filename, "status": "ok" if ok else "error", "message": msg})
    
    if success_count > 0:
        try:
            # Si folder_path est un fichier, on prend son dossier. Si c'est déjà un dossier, on le garde.
            target_dir = folder_path if os.path.isdir(folder_path) else os.path.dirname(folder_path)
            
            # On s'assure que les backslashes sont doublés pour PowerShell ou on utilise des slashes
            ps_target = target_dir.replace('/', '\\')
            
            print(f"[DEBUG] Tentative de refresh LastWriteTime sur : {ps_target}")
            
            # Commande plus robuste : utilise -Path et quote correctement
            ps_cmd = f'(Get-Item -LiteralPath "{ps_target}").LastWriteTime = Get-Date'
            
            process = subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, text=True, check=False)
            
            if process.returncode != 0:
                print(f"[DEBUG] Erreur PowerShell (code {process.returncode}) : {process.stderr}")
            else:
                print(f"[DEBUG] Refresh LastWriteTime réussi via PowerShell")
        except Exception as e:
            print(f"[DEBUG] Erreur critique lors du refresh LastWriteTime : {e}")

    return {
        "status": "success" if success_count > 0 else "error",
        "message": f"{success_count} fichiers mis à jour sur {len(mappings)}",
        "details": results
    }

@app.get("/scan_status")
async def get_scan_status(request: Request):
    global active_scan_process
    status_file = SCAN_STATUS_PATH
    
    # On vérifie si le process est réellement actif dans l'OS
    is_running_now = active_scan_process is not None and active_scan_process.is_alive()
    
    if os.path.exists(status_file):
        try:
            with open(status_file, "r") as f:
                data = json.load(f)
                data["is_active"] = is_running_now
                return data
        except:
            pass
            
    return {"status": "idle", "current": 0, "total": 0, "is_active": is_running_now}

@app.get("/api/fast_scan_status")
async def get_fast_scan_status():
    global active_scan_process
    status_file = FAST_SCAN_STATUS_PATH
    is_running_now = active_scan_process is not None and active_scan_process.is_alive()
    
    if os.path.exists(status_file):
        try:
            with open(status_file, "r") as f:
                data = json.load(f)
                data["is_active"] = is_running_now
                return data
        except:
            pass
    return {"status": "idle", "current": 0, "total": 0, "is_active": is_running_now}


# --- API SETTINGS (CONFIGURATION) ---
@app.get("/api/settings")
async def get_settings():
    """Renvoie la configuration actuelle (env ou défaut)"""
    return {
        "music_folder": os.getenv("MUSIC_FOLDER", r"\\192.168.0.3\music"),
        "musicbrainz_email": os.getenv("MUSICBRAINZ_EMAIL", "ddrtsdr@yahoo.fr"),
        "acoustid_api_key": os.getenv("ACOUSTID_API_KEY", "hLiR6XeAeq")
    }

@app.get("/api/browse")
async def get_browse(path: str = ""):
    """
    Parcourt les dossiers du serveur.
    - Si path vide : retourne les lecteurs (C:\\, D:\\) sous Windows, ou / sous Linux.
    - Sinon : retourne les sous-dossiers.
    """
    folders = []
    current = path
    parent = ""

    try:
        # 1. Racine (Liste des lecteurs)
        if not path:
            if os.name == 'nt':
                import string
                drives = ['%s:\\' % d for d in string.ascii_uppercase if os.path.exists('%s:\\' % d)]
                current = ""
                for d in drives:
                    folders.append({"name": d, "path": d, "is_drive": True})
            else:
                current = "/"
                folders.append({"name": "Root", "path": "/", "is_drive": True})
        
        # 2. Exploration d'un dossier
        else:
            # Sécurité et Normalisation
            safe_path = os.path.normpath(path)
            if not os.path.exists(safe_path):
                return {"error": "Path not found", "current": safe_path, "folders": []}

            current = safe_path
            parent = os.path.dirname(safe_path)
            
            # Pour la racine d'un lecteur (ex: D:\), dirname renvoie D:\, donc on gère manuellement pour remonter à la liste des lecteurs
            if len(parent) == len(safe_path): 
                parent = "" 

            with os.scandir(safe_path) as it:
                for entry in it:
                    if entry.is_dir():
                        folders.append({
                            "name": entry.name,
                            "path": entry.path,
                            "is_drive": False
                        })
            
            # Tri alphabétique
            folders.sort(key=lambda x: x['name'].lower())

    except Exception as e:
        print(f"Erreur Browse: {e}")
        return {"error": str(e)}

    return {
        "current": current,
        "parent": parent,
        "folders": folders
    }

class SettingsUpdate(BaseModel):
    music_folder: str
    musicbrainz_email: str
    acoustid_api_key: str

@app.post("/api/settings")
async def update_settings(settings: SettingsUpdate):
    """Met à jour le fichier .env et recharge les variables"""
    try:
        # 1. Nettoyage et Normalisation
        # On convertit tout en slashs (/) pour éviter les problèmes d'échappement dans le .env
        clean_path = settings.music_folder.strip().replace('\\', '/')
        
        # 2. Réécriture COMPLÈTE du fichier .env (Pas de set_key qui append bêtement)
        new_content = f"MUSIC_FOLDER='{clean_path}'\n"
        new_content += f"MUSICBRAINZ_EMAIL='{settings.musicbrainz_email}'\n"
        new_content += f"ACOUSTID_API_KEY='{settings.acoustid_api_key}'\n"
        
        with open(ENV_PATH, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        # 3. Rechargement immédiat
        os.environ["MUSIC_FOLDER"] = clean_path
        os.environ["MUSICBRAINZ_EMAIL"] = settings.musicbrainz_email
        os.environ["ACOUSTID_API_KEY"] = settings.acoustid_api_key
        
        # Mise à jour de la variable globale (avec conversion backslash pour l'OS)
        global MUSIC_FOLDER
        MUSIC_FOLDER = os.path.normpath(clean_path)
        
        # 4. Rechargement des modules dépendants
        tag.reload_config()

        return {"status": "ok", "message": "Configuration sauvegardée"}
    except Exception as e:
        print(f"ERREUR SETTINGS: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, loop="asyncio")
