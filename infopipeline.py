import subprocess
import json
import requests
import os
import musicbrainzngs


from dotenv import load_dotenv

import sys

# ---------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")
load_dotenv(ENV_PATH)

if getattr(sys, 'frozen', False):
    FPCALC_PATH = os.path.join(sys._MEIPASS, "fpcalc.exe")
    DB_NAME = os.path.join(sys._MEIPASS, "jukebox.db")
else:
    FPCALC_PATH = os.path.join(BASE_DIR, "fpcalc.exe")
    DB_NAME = os.path.join(BASE_DIR, "jukebox.db")

ACOUSTID_API_KEY = os.getenv("ACOUSTID_API_KEY", "hLiR6XeAeq")
MB_EMAIL = os.getenv("MUSICBRAINZ_EMAIL", "ddrtsdr@yahoo.fr")
musicbrainzngs.set_useragent("WinJukeBox", "1.0", MB_EMAIL)

# ---------------------------------------------------------
# ETAPE 1 : ANALYSE ACOUSTIQUE (DYNAMIQUE)
# ---------------------------------------------------------

def get_acoustid_data(filepath):
    """Calcule l'empreinte et interroge AcoustID pour le fichier donné."""
    # On vérifie si le fichier existe avant de lancer fpcalc
    if not filepath or not os.path.exists(filepath):
        print(f"⚠️ Fichier introuvable ou chemin vide : {filepath}")
        return None

    # Exécution de fpcalc avec le chemin reçu en paramètre
    try:
        result = subprocess.run([FPCALC_PATH, filepath], capture_output=True, text=True, check=True)
        duration = None
        fingerprint = None
        for line in result.stdout.splitlines():
            if line.startswith("DURATION="): duration = int(line.split("=")[1])
            elif line.startswith("FINGERPRINT="): fingerprint = line.split("=")[1]
    except Exception as e:
        print(f"Erreur fpcalc sur {filepath} : {e}")
        return None

    # Requête AcoustID
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
    except Exception as e:
        print(f"Erreur API AcoustID : {e}")
        return None



# ---------------------------------------------------------
# ETAPE 2 : ENRICHISSEMENT (MusicBrainz)
# ---------------------------------------------------------
from io import BytesIO
from PIL import Image

def obtenir_details_image(url):
    """Récupère les dimensions d'une image à partir de son URL."""
    try:
        response = requests.get(url, timeout=5)
        img = Image.open(BytesIO(response.content))
        return f"{img.width}x{img.height}"
    except:
        return "Dimensions inconnues"


def preparer_affiche_album(acoustid_json):
    try:
        if not acoustid_json or not acoustid_json.get("results"):
            return None
        
        res = acoustid_json['results'][0]
        confiance = round(res.get('score', 0) * 100)

        rec = res.get('recordings', [{}])[0]
        rel_group = rec.get('releasegroups', [{}])[0]
        mbid_group = rel_group.get('id')
        
        releases = rel_group.get('releases', [{}])
        if not releases: return None
        mbid_release = releases[0]['id']

        # Récupération des infos propres via MusicBrainz
        mb_data = musicbrainzngs.get_release_by_id(mbid_release, includes=["url-rels", "artist-credits"])
        release = mb_data['release']
        
        # On définit l'URL de base avec le suffixe -500.jpg pour le type MIME correct
        url_group = f"https://coverartarchive.org/release-group/{mbid_group}/front-500.jpg"
    
        return {
            "nom_album": release.get('title'),
            "nom_artiste": release.get('artist-credit-phrase'),
            "annee": release.get('date', 'N/A'),
            # ON UTILISE LES VERSIONS ORIGINALES ICI :
            "pochette": url_group, 
            "pochette_fallback": f"https://coverartarchive.org/release/{mbid_release}/front-500.jpg",
            "mbid_album": mbid_group,
            "confiance": confiance,
            "liens": {rel['type']: rel['target'] for rel in release.get('url-relation-list', [])}
        }
    except Exception as e:
        print(f"Erreur enrichissement : {e}")
        return None

# ---------------------------------------------------------
# PROGRAMME PRINCIPAL (PIPELINE)
# ---------------------------------------------------------

def main():
    print(f"--- DÉBUT DE L'ANALYSE ---\nFichier : {FILEPATH}")

    # 1. Obtenir les données AcoustID (en mémoire)
    resultat_acoustid = get_acoustid_data(FILEPATH)

    if resultat_acoustid:
        # 2. Transformer en affiche via MusicBrainz
        infos_affiche = preparer_affiche_album(resultat_acoustid)
        
        if infos_affiche:
            print("\n--- AFFICHE DE L'ALBUM ---")
            print(f"📀 Album   : {infos_affiche['nom_album']}")
            print(f"🎤 Artiste : {infos_affiche['nom_artiste']}")
            print(f"📅 Année   : {infos_affiche['annee']}")
            print(f"🖼️  Image   : {infos_affiche['pochette']}")
            print("\n🔗 LIENS EXTERNES :")
            for platef, url in infos_affiche['liens'].items():
                print(f" - {platef:15}: {url}")
            
            # Ici, plus tard, on pourra ajouter :
            # if validation_utilisateur(): tagger_tout_le_dossier(infos_affiche)
        else:
            print("❌ Impossible de trouver les détails de l'album sur MusicBrainz.")
    else:
        print("❌ L'empreinte audio n'a pas pu être identifiée.")

if __name__ == "__main__":
    # Test avec un fichier local
    dummy_file = r"\\192.168.0.3\music\SAM'NGUST\Infortune\01Mentir.mp3"
    FILEPATH = os.path.normpath(dummy_file)
    main()