/**
 * ---------------------------------------------------------
 * CONFIGURATION APK & SERVEUR
 * ---------------------------------------------------------
 */
let API_BASE_URL = "";
let isLocalAudioEnabled = false;
let currentLocalTrackId = null;
let isWaitingForNextTrack = false;

// --- DEBUGGER POUR APK ---
function apkLog(msg) {
    console.log("[APK]: " + msg);
    const logDiv = document.getElementById("apkDebugLog");
    if (logDiv) {
        const time = new Date().toLocaleTimeString();
        logDiv.innerHTML = `<div>[${time}] ${msg}</div>` + logDiv.innerHTML;
        if (logDiv.children.length > 20) logDiv.lastElementChild.remove();
    }
}

function toggleDebugLog() {
    const logDiv = document.getElementById("apkDebugLog");
    if (logDiv) {
        logDiv.style.display = logDiv.style.display === "none" ? "block" : "none";
    }
}

// Initialisation au démarrage
(function initApp() {
    apkLog("Démarrage de l'APK...");
    const activeServer = localStorage.getItem("jukebox_active_server");
    const welcome = document.getElementById("welcomeScreen");

    if (activeServer) {
        if (welcome) welcome.style.display = "none";
        API_BASE_URL = activeServer.replace(/\/$/, ""); // Retirer le slash final
        apkLog("Serveur actif: " + API_BASE_URL);

        // Vérification de connexion
        fetch(`${API_BASE_URL}/ping`)
            .then(r => {
                if (r.ok) apkLog("Ping OK !");
                else apkLog("Ping Erreur: " + r.status);
            })
            .catch(e => {
                apkLog("Serveur injoignable: " + e.message);
            });
    } else {
        apkLog("Attente de configuration d'un serveur.");
        if (welcome) welcome.style.display = "flex";
    }
    // Note: renderServerList() est défini plus bas
    window.addEventListener('load', () => {
        renderServerList();
    });
})();

// --- GESTION SETUP INITIAL (APK ONLY) ---
function setupInitialServer() {
    const input = document.getElementById("initialServerUrl");
    let url = input.value.trim();
    if (!url) {
        alert("Veuillez saisir une adresse valide.");
        return;
    }
    if (!url.startsWith("http")) url = "http://" + url;

    apkLog("Config initial: " + url);
    let servers = JSON.parse(localStorage.getItem("jukebox_servers") || "[]");
    if (!servers.includes(url)) {
        servers.push(url);
        localStorage.setItem("jukebox_servers", JSON.stringify(servers));
    }
    selectServer(url);
}

// --- GESTION SIDEBAR ---
function toggleServerSidebar() {
    const sidebar = document.getElementById("serverSidebar");
    const overlay = document.getElementById("sidebarOverlay");
    if (sidebar && overlay) {
        sidebar.classList.toggle("active");
        overlay.classList.toggle("active");
    }
}

function addServer() {
    const input = document.getElementById("newServerUrl");
    let url = input.value.trim();
    if (!url) return;
    if (!url.startsWith("http")) url = "http://" + url;

    let servers = JSON.parse(localStorage.getItem("jukebox_servers") || "[]");
    if (!servers.includes(url)) {
        servers.push(url);
        localStorage.setItem("jukebox_servers", JSON.stringify(servers));

        if (servers.length === 1) {
            selectServer(url);
        }
        renderServerList();
        input.value = "";
    }
}

function removeServer(url, event) {
    if (event) event.stopPropagation();
    let servers = JSON.parse(localStorage.getItem("jukebox_servers") || "[]");
    servers = servers.filter(s => s !== url);
    localStorage.setItem("jukebox_servers", JSON.stringify(servers));

    const active = localStorage.getItem("jukebox_active_server");
    if (active === url) {
        localStorage.removeItem("jukebox_active_server");
        API_BASE_URL = "";
        location.reload();
    }
    renderServerList();
}

function selectServer(url) {
    apkLog("Sélection serveur: " + url);
    localStorage.setItem("jukebox_active_server", url);
    API_BASE_URL = url;
    location.reload();
}

function renderServerList() {
    const container = document.getElementById("serverListContainer");
    if (!container) return;

    const servers = JSON.parse(localStorage.getItem("jukebox_servers") || "[]");
    const active = localStorage.getItem("jukebox_active_server");

    container.innerHTML = servers.map(url => `
        <div class="server-list-item ${url === active ? 'active' : ''}" onclick="selectServer('${url}')">
            <div class="server-info">
                <span class="server-url">${url}</span>
                <span class="server-status">${url === active ? 'Actif' : 'Cliquer pour activer'}</span>
            </div>
            <button class="delete-server-btn" onclick="removeServer('${url}', event)">&times;</button>
        </div>
    `).join("");
}

// --- GESTION GESTURES (SWIPE) ---
document.addEventListener('touchstart', handleTouchStart, false);
document.addEventListener('touchmove', handleTouchMove, false);

let xDown = null;
let yDown = null;

function handleTouchStart(evt) {
    const firstTouch = evt.touches[0];
    xDown = firstTouch.clientX;
    yDown = firstTouch.clientY;
}

function handleTouchMove(evt) {
    if (!xDown || !yDown) return;

    let xUp = evt.touches[0].clientX;
    let yUp = evt.touches[0].clientY;

    let xDiff = xDown - xUp;
    let yDiff = yDown - yUp;

    // Si le mouvement est horizontal et commence près du bord gauche (< 50px)
    if (Math.abs(xDiff) > Math.abs(yDiff) && xDown < 50) {
        if (xDiff < 0) { // Swipe Right
            const sidebar = document.getElementById("serverSidebar");
            if (sidebar && !sidebar.classList.contains("active")) {
                toggleServerSidebar();
            }
        }
    }
    // Reset
    xDown = null;
    yDown = null;
}

/**
 * ---------------------------------------------------------
 * VARIABLES GLOBALES
 * ---------------------------------------------------------
 */
let lastLibraryCount = 0;
let currentTrackId = null; // morceau actuellement joué
let currentCoverKey = null;     // clé logique pour la cover
let currentMode = "playlist"; // ou "album" 

// --- INFINITE SCROLL STATE ---
let allSearchResults = [];
let currentRenderCount = 0;
const BATCH_SIZE = 50;
let infiniteScrollObserver = null;


/**
 * ---------------------------------------------------------
 * RECHERCHE ET AFFICHAGE DES MORCEAUX ET DOSSIERS
 * ---------------------------------------------------------
 */
let currentSearchMode = 'artist';

async function switchMode(newMode) {
    const input = document.getElementById("searchInput");
    const previousValue = input ? input.value : ""; // On sauvegarde la recherche actuelle

    // 1. Mise à jour du mode
    currentSearchMode = newMode;

    // 2. Interface (boutons actifs)
    document.querySelectorAll('.nav-mode-btn').forEach(btn => {
        btn.classList.toggle('active', btn.getAttribute('data-mode') === newMode);
    });

    if (newMode === 'folder') {
        input.placeholder = "Filtrer les dossiers...";

        // --- LA MAGIE EST ICI ---
        // On force le chargement de la racine (pour avoir les dossiers à filtrer)
        // On attend que le chargement soit fini (await)
        await loadFolderContent("");

        // Une fois que les dossiers sont dans le DOM, on remet le texte 
        // et on déclenche le filtrage local
        if (previousValue.trim() !== "") {
            input.value = previousValue;
            doSearch();
        }
    } else {
        input.placeholder = `Rechercher ${newMode}...`;
        // Pour les autres modes, on garde le texte et on lance la recherche BDD
        await doSearch();
    }
}


// Fonction pour vider l'input x dans le barre de recherche
function clearSearchInput() {
    const input = document.getElementById("searchInput");
    const clearBtn = document.getElementById("clearSearch");

    input.value = "";
    clearBtn.style.display = "none";
    input.focus(); // Redonne le focus pour retaper vite

    // On relance la recherche à vide pour réafficher tout le monde
    doSearch();
}

/**
 * Fonction principale de recherche et filtrage
 */
async function doSearch() {
    // --- NOUVEAU : GESTION DE LA CROIX (Dès le début) ---
    const input = document.getElementById("searchInput");
    const clearBtn = document.getElementById("clearSearch");

    if (clearBtn && input) {
        // Affiche la croix si l'input n'est pas vide, sinon la cache
        clearBtn.style.display = input.value.length > 0 ? "block" : "none";
    }

    try {
        const query = input.value.toLowerCase() || "";
        const list = document.getElementById("songList");

        // 🔥 RESET DE LA VUE (Pour ne pas rester bloqué en "library")
        list.dataset.view = "search";

        // --- A. MODE DOSSIER : FILTRAGE LOCAL ---
        if (currentSearchMode === 'folder') {
            const cards = list.querySelectorAll(".folder-card, .file-card");
            cards.forEach(card => {
                const nameEl = card.querySelector(".folder-name");
                if (nameEl) {
                    const name = nameEl.innerText.toLowerCase();
                    card.style.display = name.includes(query) ? "flex" : "none";
                }
            });
            return;
        }

        // --- B. MODES MUSIQUE : RECHERCHE SERVEUR ---
        const url = `${API_BASE_URL}/search?q=${encodeURIComponent(query)}&mode=${currentSearchMode}`;
        const response = await fetch(url);

        if (!response.ok) throw new Error("Erreur serveur");
        const data = await response.json();

        list.innerHTML = "";

        if (!data.songs || data.songs.length === 0) {
            list.innerHTML = `<div style="text-align:center; padding:20px;">Aucune musique trouvée 🎸</div>`;
            return;
        }

        // --- C. RENDU DES RÉSULTATS (INFINITE SCROLL) ---
        allSearchResults = data.songs;
        currentRenderCount = 0;

        // 1. Mise en place de l'observateur (AVANT le rendu)
        setupInfiniteScroll();

        // 2. Premier rendu (qui va créer le sentinel)
        renderNextBatch();

    } catch (err) {
        console.error("Erreur doSearch:", err);
    }
}


/**
 * Affiche le prochain paquet de résultats (Infinite Scroll)
 */
function renderNextBatch() {
    const list = document.getElementById("songList");
    const total = allSearchResults.length;

    // Si on a tout affiché, on arrête
    if (currentRenderCount >= total) {
        // On retire le sentinel s'il existe
        const sentinel = document.getElementById("scroll-sentinel");
        if (sentinel) sentinel.remove();
        return;
    }

    const nextBatch = allSearchResults.slice(currentRenderCount, currentRenderCount + BATCH_SIZE);

    // On retire le sentinel temporairement pour ajouter les items AVANT lui
    let sentinel = document.getElementById("scroll-sentinel");
    if (sentinel) sentinel.remove();

    nextBatch.forEach(song => {
        const card = createSongCard(song);
        list.appendChild(card);
    });

    currentRenderCount += nextBatch.length;

    // On remet le sentinel à la fin si on a encore des choses à afficher
    if (currentRenderCount < total) {
        sentinel = document.createElement("div");
        sentinel.id = "scroll-sentinel";
        sentinel.style.height = "50px"; // On force une hauteur pour que l'observer le voit
        sentinel.style.width = "100%";
        sentinel.style.marginTop = "20px";
        // sentinel.style.background = "red"; // DEBUG: Décommenter si besoin
        sentinel.innerText = "Chargement...";
        sentinel.style.textAlign = "center";
        sentinel.style.color = "#666";
        list.appendChild(sentinel);

        // On reconnecte l'observateur au nouveau sentinel
        if (infiniteScrollObserver) {
            infiniteScrollObserver.observe(sentinel);
        }
    }
}

function createSongCard(song) {
    const card = document.createElement("div");
    const isGroupMode = (currentSearchMode === 'artist' || currentSearchMode === 'album');
    card.className = isGroupMode ? "song-card album-card-container" : "song-card";

    const cleanTitle = song.title.replace(/"/g, '&quot;').replace(/'/g, "\\'");
    const cleanArtist = song.artist.replace(/"/g, '&quot;').replace(/'/g, "\\'");
    const cleanAlbum = (song.album || "").replace(/"/g, '&quot;').replace(/'/g, "\\'");

    if (isGroupMode) {
        const albumCoverUrl = `${API_BASE_URL}/cover/${song.id}`;
        card.innerHTML = `
        <div class="album-card-content" style="display: flex; flex-direction: column; width: 100%;">
            <div class="album-header" style="display: flex; align-items: center; padding: 12px;">
                <span class="expand-icon" style="cursor:pointer; margin-right:15px; font-size:1.2em; color:#1db954; flex-shrink: 0;" 
                      onclick="toggleAlbum('${cleanAlbum}', '${cleanArtist}', this)">▶</span>
                <div class="cover-slot" style="width: 100px; height: 100px; margin-right: 20px; flex-shrink: 0; display: flex; align-items: center; justify-content: center;"></div>
                
                <div class="album-identity" style="display: flex; flex-direction: row; flex-grow: 1; align-items: flex-start; justify-content: space-between;">
                    
                    <!-- Colonne gauche : Titre, Artiste, Bouton Ajout -->
                    <div style="display: flex; flex-direction: column; flex-grow: 1; min-width: 0; margin-right: 15px;">
                        <div class="song-title" style="color: #1db954; font-weight: bold; font-size: 1.1em; word-break: break-word; white-space: normal; line-height: 1.25; margin-bottom: 5px;">${song.album}</div>
                        <div class="song-subtext" style="color: #b3b3b3; margin-bottom: 10px; font-size: 0.9em;">${song.artist}</div>
                        <button class="add-album-btn" style="width: fit-content; background:#1db954; color:white; border:none; border-radius:20px; padding:5px 15px; font-size:0.75em; font-weight:bold; cursor:pointer;" 
                                onclick="addFullAlbum('${cleanAlbum}', '${cleanArtist}')">➕</button>
                    </div>

                    <!-- Colonne droite : Bouton Play dédié (fixe) -->
                    <div style="display: flex; align-items: center; justify-content: center; height: 100%; padding-top: 5px;">
                         <button class="play-btn" title="Écouter cet album" onclick="playFullAlbumNow('${cleanAlbum}', '${cleanArtist}')"
                                 style="flex-shrink: 0; width: 40px; height: 40px; border-radius: 50%; font-size: 1.2em; display: flex; align-items: center; justify-content: center;">▶</button>
                    </div>

                </div>
            </div>
            <div class="album-details" style="display: none; width: 100%;"></div>
        </div>`;

        const imgTest = new Image();
        imgTest.src = albumCoverUrl;
        imgTest.onload = () => {
            const slot = card.querySelector('.cover-slot');
            if (slot) slot.innerHTML = `<img src="${albumCoverUrl}" loading="lazy" style="width: 100%; height: 100%; border-radius: 4px; object-fit: cover; box-shadow: 0 4px 12px rgba(0,0,0,0.5);">`;
        };
    } else {
        const albumInfo = song.album ? ` > ${song.album}` : "";
        card.innerHTML = `
            <div class="song-info">
                <div class="song-title">${song.title}</div>
                <div class="song-subtext">
                    <span class="song-artist">${song.artist}</span>
                    <span class="song-album">${albumInfo}</span>
                </div>
            </div>
            <div class="song-actions">
                <button class="add-to-playlist-btn" data-id="${song.id}" data-title="${cleanTitle}" data-artist="${cleanArtist}" data-album="${cleanAlbum}">➕</button>
                <button class="play-btn" data-id="${song.id}">▶</button>
            </div>`;
    }
    return card;
}

function setupInfiniteScroll() {
    // Nettoyage ancien observer
    if (infiniteScrollObserver) {
        infiniteScrollObserver.disconnect();
    }

    const options = {
        root: null, // viewport
        rootMargin: '200px', // On charge 200px avant d'arriver en bas
        threshold: 0.1
    };

    infiniteScrollObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                renderNextBatch();
            }
        });
    }, options);
}

/**
 * Fonction pour vider la barre de recherche
 */
function clearSearchInput() {
    const input = document.getElementById("searchInput");
    if (input) {
        input.value = ""; // On vide le texte
        input.focus();    // On remet le curseur dedans pour retaper
        doSearch();       // On relance doSearch pour cacher la croix et reset la liste
    }
}

async function toggleAlbum(albumName, artistName, element) {
    const detailDiv = element.closest('.album-card-container').querySelector('.album-details');

    if (detailDiv.style.display === 'block') {
        detailDiv.style.display = 'none';
        element.innerText = '▶';
        return;
    }

    if (detailDiv.innerHTML.trim() === "") {
        try {
            const url = `${API_BASE_URL}/album_tracks?album=${encodeURIComponent(albumName)}&artist=${encodeURIComponent(artistName)}`;
            const response = await fetch(url);
            const data = await response.json();

            if (data.tracks && data.tracks.length > 0) {
                let html = "";
                data.tracks.forEach(track => {
                    const cleanT = track.title.replace(/"/g, '&quot;').replace(/'/g, "\\'");

                    // AJOUT : class="album-track-item" et data-id sur la div parente
                    html += `
        <div class="album-track-item" data-id="${track.id}" 
             style="padding: 10px 30px 10px 10px; border-bottom: 1px solid #222; display: flex; justify-content: space-between; align-items: center;">
            
            <span class="track-title-text" style="color: #ccc;">${track.title}</span>
            
            <div class="song-actions" style="display: flex; gap: 10px;">
                <button class="add-to-playlist-btn" 
                        data-id="${track.id}" 
                        data-title="${cleanT}" 
                        data-artist="${artistName.replace(/'/g, "\\'")}" 
                        data-album="${albumName.replace(/'/g, "\\'")}">➕</button>
                
                <button class="play-btn" data-id="${track.id}" onclick="play(${track.id})">▶</button>
            </div>
        </div>`;
                });
                detailDiv.innerHTML = html;
            }
        } catch (err) {
            console.error("Erreur:", err);
        }
    }

    detailDiv.style.display = 'block';
    element.innerText = '▼';
}
async function addFullAlbum(albumName, artistName) {
    console.log(`Préparation de l'ajout global : ${albumName}`);

    try {
        // 1. On utilise ta route existante pour lister les titres
        const response = await fetch(`${API_BASE_URL}/album_tracks?album=${encodeURIComponent(albumName)}&artist=${encodeURIComponent(artistName)}`);
        const data = await response.json();

        if (data.tracks && data.tracks.length > 0) {
            // 2. On boucle sur chaque piste reçue
            for (const track of data.tracks) {
                // On utilise ta route existante pour ajouter UN titre
                // Le "await" ici est crucial : il attend que le Python ait fini l'insertion 
                // avant de demander la suivante, évitant de bloquer ta base de données.
                await fetch(`${API_BASE_URL}/playlist/add/${track.id}`, { method: "POST" });
            }

            // 3. Une fois la boucle terminée, on rafraîchit la playlist à droite
            loadPlaylistFromServer();

            // 4. On affiche l'alerte
            alert(`L'album "${albumName}" a été ajouté à la playlist.`);
        }
    } catch (err) {
        console.error("Erreur lors de l'ajout groupé :", err);
    }
}


/**
 * ---------------------------------------------------------
 * Passer en mode arborescence des dossiers
 * ---------------------------------------------------------
 */

/* Ne pas allumer tous les boutons en meme temps Quand on clique sur Folder, on étend les trois autres boutons de recherche.*/
async function toggleFolderView() {
    const input = document.getElementById("searchInput");
    const btn = document.getElementById('folderIconBtn');

    // --- SAUVEGARDE IMMÉDIATE DU TEXTE ---
    const savedQuery = input ? input.value : "";
    console.log("Texte sauvegardé avant switch :", savedQuery);

    // 1. MISE À JOUR DU MODE
    currentSearchMode = 'folder';

    // 2. GESTION VISUELLE DES BOUTONS
    document.querySelectorAll('.nav-mode-btn').forEach(icon => {
        icon.classList.remove('active');
    });
    if (btn) btn.classList.add('active');

    // 3. FORCE LE TEXTE À RESTER (pour contrer un éventuel reset ailleurs)
    if (input) {
        input.value = savedQuery;
        input.placeholder = "Filtrer les dossiers...";
    }

    // 4. LOGIQUE DE CHARGEMENT
    if (savedQuery.trim() !== "") {
        // On ne fait PAS loadFolderContent(""), on laisse les résultats actuels
        // et on applique le filtre local
        doSearch();
    } else {
        // Seulement si c'est vide, on charge l'explorateur
        await loadFolderContent("");
    }
}

/* DETECTION dans l'EXPLORER les repertoires et morceaux manquant de TAGs et/ou cover*/
function getStatusIcon(status) {
    switch (status) {
        case 0: return `<span style="color:#ff4444; margin-left:8px;" title="Totalement incomplet (Tags + Cover)">⚠️</span>`;
        case 2: return `<span style="color:#ffbb33; margin-left:8px;" title="Manque Tags (Artiste/Album/Titre)">🏷️</span>`;
        case 3: return `<span style="color:#ffbb33; margin-left:8px;" title="Manque Pochette">📷</span>`;
        default: return ""; // Code 1 (parfait) ou autre : on n'affiche rien
    }
}


/* Navigation pure dans les dossiers (Mode Explorateur) */
async function loadFolderContent(path = "") {
    const container = document.getElementById("songList");
    if (!container) return;

    container.scrollTo(0, 0);

    // 🔥 RESET DE LA VUE
    container.dataset.view = "folder";

    try {
        const response = await fetch(`${API_BASE_URL}/api/files/browse?path=${encodeURIComponent(path)}`);
        const data = await response.json();
        currentFolderFiles = data.items;

        if (data.error) {
            container.innerHTML = `<div class="error">${data.error}</div>`;
            return;
        }

        container.innerHTML = "";

        // --- 1. BARRE DE NAVIGATION (CONSERVÉE À 100%) ---
        if (path !== "" && path !== ".") {
            const navBar = document.createElement("div");
            navBar.className = "folder-nav-bar";
            const breadcrumb = path.replace(/\\/g, ' / ');

            const hasMusic = data.items.some(item =>
                item.type === "file" &&
                (item.name.toLowerCase().endsWith('.mp3') || item.name.toLowerCase().endsWith('.wma'))
            );

            const infoBtnHtml = hasMusic ?
                `<button class="info-folder-btn" title="Informations" 
                    style="background:none; border:none; padding:0; cursor:pointer; display:flex; align-items:center; margin-right: 5px;">
                    <img src="icons/info.png" style="width:30px; height:30px; display:block; filter: brightness(1.5);">
                 </button>` : '';

            navBar.innerHTML = `
                <div class="back-button-mini" style="cursor:pointer; flex-shrink: 0;"><span style="color: #1db954; font-size: 1.2em;">▲</span></div>
                <div class="current-path-display" style="margin-left: 20px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${breadcrumb}</div>
                <div style="flex-grow: 1;"></div> 
                <div class="folder-actions-top" style="display: flex; gap: 10px; align-items: center; flex-shrink: 0;">
                    ${infoBtnHtml}
                    <button class="add-all-folder" title="Tout ajouter">➕</button>
                    <button class="play-btn play-all-folder" title="Tout lire maintenant">▶</button>
                </div>
            `;

            navBar.querySelector('.back-button-mini').onclick = () => loadFolderContent(data.parent_path || "");
            navBar.querySelector('.add-all-folder').onclick = () => addFolderToPlaylist(path);
            navBar.querySelector('.play-all-folder').onclick = () => playWholeFolder(path);

            const infoBtn = navBar.querySelector('.info-folder-btn');
            if (infoBtn) {
                infoBtn.onclick = () => showFolderInfo(path);
            }

            container.appendChild(navBar);

            // --- 1bis. LA BANNIÈRE DE L'ALBUM (INSERTION PRUDENTE) ---
            const firstMusicFile = data.items.find(item => item.type === "file" && item.id);
            if (hasMusic && firstMusicFile) {
                const banner = document.createElement("div");
                banner.className = "album-banner-container"; // On utilise une nouvelle classe
                banner.style.display = "flex";
                banner.style.alignItems = "center";
                banner.style.gap = "20px";
                banner.style.padding = "15px 45px"; // Aligné sous le texte du chemin
                banner.style.marginBottom = "10px";

                banner.innerHTML = `
                    <img src="${API_BASE_URL}/cover/${firstMusicFile.id}" 
                         onerror="this.src='default_cover.png'" 
                         style="width:80px; height:80px; border-radius:6px; object-fit:cover; box-shadow: 0 4px 10px rgba(0,0,0,0.5);">
                    <div style="min-width: 0;">
                        <h2 style="margin:0; font-size:1.5em; color:white; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
                            ${path.split(/[\\/]/).pop()}
                        </h2>
                        <p style="color:#1db954; margin:5px 0; font-weight:bold;">
                            ${firstMusicFile.artist || '-M-'} <span style="color:#888; font-weight:normal;">• ${data.items.filter(i => i.type === 'file').length} titres</span>
                        </p>
                    </div>
                `;
                container.appendChild(banner);
            }
        }

        // --- 2. AFFICHAGE DES ITEMS (Dossiers ou Fichiers) ---
        data.items.forEach(item => {
            // ON RE-CRÉE LE DIV (C'est ce qui manquait !)
            const div = document.createElement("div");

            // Définition de l'alerte
            const alertHtml = getStatusIcon(item.status); // Utilise la fonction helper que je t'ai donnée avant

            if (item.type === "directory") {
                div.className = "folder-card";
                div.innerHTML = `<div class="folder-name">${item.name} ${alertHtml}</div>`;
                div.onclick = () => loadFolderContent(item.path);
            } else {
                div.className = "file-card";
                div.dataset.id = item.id;
                div.innerHTML = `
                    <div class="file-info">
                        <div class="folder-icon">🎵</div>
                        <div class="file-details">
                            <div class="folder-name">${item.name}${alertHtml}</div>
                            <small class="file-artist">${item.artist || 'Artiste inconnu'}</small>
                        </div>
                    </div>
                    <div class="file-actions">
                        <button class="add-to-playlist-btn" data-id="${item.id}" title="Ajouter à la playlist">➕</button>
                        <button class="play-btn" data-id="${item.id}" title="Lire maintenant">▶</button>
                    </div>
                `;


                div.querySelector(".play-btn").onclick = (e) => {
                    e.stopPropagation();
                    playTrack(item.id);
                };

                div.querySelector(".add-to-playlist-btn").onclick = (e) => {
                    e.stopPropagation();
                    addToPlaylist(item.id);
                };
            }
            container.appendChild(div);
        });

    } catch (err) {
        console.error("Erreur navigation dossiers:", err);
    }
}

/* Affichage des fichiers dans le dossier */
async function renderFolderShow(container) {
    const res = await fetch(`${API_BASE_URL}/api/folder_show/load`);
    const data = await res.json();

    data.items.forEach((track, index) => {
        const div = document.createElement("div");
        div.className = "file-card";

        // --- CHIRURGIE ICI : On ajoute l'ID pour le highlight ---
        div.dataset.id = track.id;

        div.innerHTML = `
            <div class="file-info" style="display:flex; align-items:center; flex-grow:1;">
                <div class="folder-icon">🎵</div>
                <div class="folder-name">${track.title}</div>
            </div>
            <button class="play-btn" title="Lire maintenant">▶</button>
        `;

        div.querySelector(".play-btn").onclick = (e) => {
            e.stopPropagation();
            playFolderTrack(index);
        };

        container.appendChild(div);
    });
}

/**
 * LECTURE UNIVERSELLE (Dossiers ou Recherche)
 */
async function playTrack(trackId) {
    console.log("Lecture demandée pour l'ID:", trackId);

    try {
        // On appelle ta route Python /play/{song_id}
        const res = await fetch(`${API_BASE_URL}/play/${trackId}`);
        const data = await res.json();

        if (data.status === "playing") {
            // On synchronise les globales JS
            currentTrackId = data.id;
            currentMode = data.mode;

            // On met à jour le bandeau (Header) avec les infos renvoyées par universal_player
            updateHeaderUI(data);
        }
    } catch (err) {
        console.error("Erreur lors de la lecture unitaire:", err);
    }
}

/* Lecture intégrale d'un dossier */
async function playWholeFolder(path) {
    console.log("Demande de lecture intégrale du dossier:", path);
    try {
        const response = await fetch(`${API_BASE_URL}/api/play_folder_now`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: path })
        });

        const data = await response.json();

        if (data.first_id) {
            // On utilise ta fonction play() existante
            isPlaylistMode = false; // On quitte le mode playlist perso
            play(data.first_id);
        }
    } catch (err) {
        console.error("Erreur lecture dossier:", err);
    }
}


/* Ajout intégral d'un dossier à la playlist (Version optimisée) */
async function addFolderToPlaylist(path) {
    try {
        const response = await fetch(`${API_BASE_URL}/api/folder/add_to_playlist`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: path }) // On envoie juste le chemin !
        });

        const data = await response.json();
        if (data.status === "success") {
            loadPlaylistFromServer();
            // Pas besoin d'appeler loadSavedPlaylists(), 
            // bump_playlist_library_version() s'en occupera tout seul !
        }
    } catch (err) {
        console.error("Erreur:", err);
    }
}

/**
 * ---------------------------------------------------------
 * COMMANDES SERVEUR & GESTION AUDIO DYNAMIQUE
 * ---------------------------------------------------------
 */
let isLaunching = false;
// On récupère le dernier device utilisé ou "auto" par défaut
let selectedDevice = localStorage.getItem("selectedAudioDevice") || "auto";

async function play(id) {
    if (isLaunching) return;
    isLaunching = true;


    // On encode le device pour gérer les espaces et caractères spéciaux du FriendlyName
    const deviceParam = encodeURIComponent(selectedDevice);
    await fetch(`${API_BASE_URL}/play/${id}?device=${deviceParam}`);

    setTimeout(() => {
        isLaunching = false;
    }, 500);
}

async function stopMusic() {
    await fetch(`${API_BASE_URL}/stop`);
}

async function togglePause() {
    await fetch(`${API_BASE_URL}/pause`);
}

// Variable locale pour éviter que le curseur ne saute pendant qu'on le bouge
let isDraggingVolume = false;

async function changeVolume(level) {
    // On met à jour le volume sur le serveur
    await fetch(`${API_BASE_URL}/volume/${level}`);

    // Optionnel : on peut stocker aussi dans le navigateur pour un backup
    localStorage.setItem("lastVolume", level);
}

async function seek(seconds) {
    await fetch(`${API_BASE_URL}/seek/${seconds}`);
}

async function playNext() {
    // On laisse le serveur décider si on n'a pas d'ID local valide
    let idToSend = currentTrackId;

    const res = await fetch(`${API_BASE_URL}/next?current_id=${encodeURIComponent(idToSend)}`);
    const data = await res.json();

    if (data.status === "playing") {
        currentTrackId = data.id;
        updateHeaderUI(data); // On force la mise à jour du bandeau immédiatement
    }
}

async function playPrevious() {
    let idToSend = currentTrackId;

    const res = await fetch(`${API_BASE_URL}/previous?current_id=${encodeURIComponent(idToSend)}`);
    const data = await res.json();

    if (data.status === "playing") {
        currentTrackId = data.id;
        updateHeaderUI(data);
    }
}

/**
 * ---------------------------------------------------------
 * SÉLECTEUR DE SORTIE AUDIO (MODALE)
 * ---------------------------------------------------------
 */
const headerSpeakerBtn = document.getElementById("headerSpeakerBtn");
if (headerSpeakerBtn) {
    headerSpeakerBtn.addEventListener("click", openDeviceModal);
}

/**
 * ---------------------------------------------------------
 * LECTURE LOCALE (RELAY)
 * ---------------------------------------------------------
 */
let isWaitingForServerStart = false; // "Smart Start" Flag

function toggleLocalAudio() {
    isLocalAudioEnabled = !isLocalAudioEnabled;
    const btn = document.getElementById("local-audio-btn");
    const plBtn = document.getElementById("plLocalAudioBtn");
    const audio = document.getElementById("remote-audio-relay");

    const opacity = isLocalAudioEnabled ? "1" : "0.5";
    const filter = isLocalAudioEnabled ? "drop-shadow(0 0 5px #1db954)" : "none";

    console.log("Toggle Local Audio:", isLocalAudioEnabled);

    if (btn) {
        btn.style.opacity = opacity;
        btn.style.filter = filter;
    }

    if (plBtn) {
        plBtn.style.opacity = opacity;
        plBtn.style.filter = "none";
        if (isLocalAudioEnabled) plBtn.style.opacity = "1";
    }

    if (isLocalAudioEnabled) {
        // --- NATIVE PLUGIN SYNC ---
        // On réinitialise l'ID pour forcer la détection de piste dans updateStatus
        currentLocalTrackId = null;

        // On tente de lancer l'audio relay (legacy browser mode)
        if (audio && audio.src) {
            audio.play().catch(e => console.log("Autoplay block (legacy):", e));
        }
    } else {
        // Nettoyage legacy
        if (audio) {
            audio.pause();
            audio.src = "";
        }
        // --- NATIVE PLUGIN STOP ---
        if (typeof Capacitor !== 'undefined' && Capacitor.Plugins.JukeBox) {
            Capacitor.Plugins.JukeBox.pause();
        }
    }

    // On force un update immédiat pour éviter le lag de 1s
    if (typeof updateStatus === 'function') {
        updateStatus();
    }
}

async function openDeviceModal() {
    const modal = document.getElementById("deviceModal");
    const list = document.getElementById("deviceList");

    modal.style.display = "flex";
    list.innerHTML = "<p style='color: #888;'>Recherche des périphériques...</p>";

    try {
        const resp = await fetch(`${API_BASE_URL}/audio-devices`);
        const data = await resp.json();

        list.innerHTML = ""; // On vide le message de chargement

        if (data.devices && data.devices.length > 0) {
            data.devices.forEach(name => {
                // FIX: On n'ajoute PAS "wasapi/" pour le device virtuel "Stream Only"
                const fullDeviceString = name.includes("Stream Only") ? name : `wasapi/${name}`;

                const div = document.createElement("div");
                div.className = "device-item";

                // Si c'est le device actuel, on ajoute une classe visuelle
                if (selectedDevice === fullDeviceString) {
                    div.classList.add("active");
                }

                div.innerText = name;
                div.onclick = async () => {
                    selectedDevice = fullDeviceString;
                    localStorage.setItem("selectedAudioDevice", selectedDevice);
                    console.log("Sortie audio définie sur :", selectedDevice);

                    // SYNC SERVEUR : On prévient le serveur pour qu'il utilise ce device pour l'Auto-Next
                    try {
                        await fetch(`${API_BASE_URL}/set-device?device=${encodeURIComponent(selectedDevice)}`, { method: 'POST' });
                    } catch (e) { console.error("Erreur sync set-device", e); }

                    closeDeviceModal();

                    // Optionnel : petit feedback visuel
                    alert(`Sortie configurée : ${name}\nPrendra effet au prochain morceau.`);
                };
                list.appendChild(div);
            });
        } else {
            list.innerHTML = "<p>Aucun périphérique trouvé.</p>";
        }
    } catch (err) {
        list.innerHTML = "<p>Erreur lors de la récupération des périphériques.</p>";
        console.error(err);
    }
}

function closeDeviceModal() {
    document.getElementById("deviceModal").style.display = "none";
}

// Fermer la modale si on clique en dehors du cadre
window.onclick = function (event) {
    const modal = document.getElementById("deviceModal");
    if (event.target == modal) {
        closeDeviceModal();
    }
}

/**
 * ---------------------------------------------------------
 *  FORMATAGE DU TEMPS
 * ---------------------------------------------------------
 */
function formatTime(seconds) {
    if (!seconds || seconds < 0) return "0:00";
    const min = Math.floor(seconds / 60);
    const sec = Math.floor(seconds % 60);
    return `${min}:${sec < 10 ? "0" : ""}${sec}`;
}

/**
 * ---------------------------------------------------------
 *  BARRE DE PROGRESSION
 * ---------------------------------------------------------
 */

let isDragging = false;
let isDraggingPl = false;
let slider = null;
let plSlider = null;

function initProgressBar() {
    slider = document.getElementById("progressSlider");
    if (!slider) return;

    slider.addEventListener("mousedown", () => {
        isDragging = true;
    });

    slider.addEventListener("touchstart", () => {
        isDragging = true;
    });

    slider.addEventListener("mouseup", async (e) => {
        isDragging = false;
        const newPos = Number(e.target.value);
        if (typeof isLocalAudioEnabled !== 'undefined' && isLocalAudioEnabled) {
            Capacitor.Plugins.JukeBox.seek({ pos: newPos });
        }
        await fetch(`${API_BASE_URL}/setpos/${newPos}`);
    });

    slider.addEventListener("touchend", async () => {
        isDragging = false;
        const newPos = Number(slider.value);
        if (typeof isLocalAudioEnabled !== 'undefined' && isLocalAudioEnabled) {
            Capacitor.Plugins.JukeBox.seek({ pos: newPos });
        }
        await fetch(`${API_BASE_URL}/setpos/${newPos}`);
        setTimeout(updateStatus, 300);
    });

    slider.addEventListener("input", (e) => {
        const currentTxt = document.getElementById("currentTime");
        currentTxt.innerText = formatTime(Number(e.target.value));
    });

    // --- NOUVEAU : Slider du panneau playlist ---
    plSlider = document.getElementById("plProgressSlider");
    if (plSlider) {
        plSlider.addEventListener("mousedown", () => { isDraggingPl = true; });
        plSlider.addEventListener("touchstart", () => { isDraggingPl = true; });

        plSlider.addEventListener("mouseup", async (e) => {
            isDraggingPl = false;
            const newPos = Number(e.target.value);
            if (typeof isLocalAudioEnabled !== 'undefined' && isLocalAudioEnabled) {
                Capacitor.Plugins.JukeBox.seek({ pos: newPos });
            }
            await fetch(`${API_BASE_URL}/setpos/${newPos}`);
        });

        plSlider.addEventListener("touchend", async () => {
            isDraggingPl = false;
            const newPos = Number(plSlider.value);
            if (typeof isLocalAudioEnabled !== 'undefined' && isLocalAudioEnabled) {
                Capacitor.Plugins.JukeBox.seek({ pos: newPos });
            }
            await fetch(`${API_BASE_URL}/setpos/${newPos}`);
            setTimeout(updateStatus, 300);
        });

        plSlider.addEventListener("input", (e) => {
            const currentTxt = document.getElementById("plCurrentTime");
            if (currentTxt) currentTxt.innerText = formatTime(Number(e.target.value));
        });
    }
}

/**
 * ---------------------------------------------------------
 * GESTION DU VOLUME (SYNC & DRAG)
 * ---------------------------------------------------------
 */
function initVolumeControl() {
    const volSlider = document.getElementById("volumeSlider");
    if (!volSlider) return;

    // Bloque la synchro auto pendant qu'on manipule le curseur
    volSlider.addEventListener("mousedown", () => { isDraggingVolume = true; });
    volSlider.addEventListener("touchstart", () => { isDraggingVolume = true; });

    // Relance la synchro auto quand on relâche
    volSlider.addEventListener("mouseup", () => { isDraggingVolume = false; });
    volSlider.addEventListener("touchend", () => { isDraggingVolume = false; });

    // Envoie la valeur au serveur en temps réel pendant le glissement
    volSlider.addEventListener("input", (e) => {
        changeVolume(e.target.value);
    });
}


// --- SYNCHRO AUTOMATIQUE DE LA BIBLIOTHÈQUE DE PLAYLISTS ---
let lastPlaylistLibraryVersion = 0;

async function checkPlaylistLibraryVersion() {
    try {
        const res = await fetch(`${API_BASE_URL}/api/playlists/version`);
        const data = await res.json();

        if (data.version === lastPlaylistLibraryVersion) return;
        lastPlaylistLibraryVersion = data.version;

        const mainContainer = document.getElementById("songList");
        // On vérifie où on est
        const isLibraryView = mainContainer?.dataset.view === "library";

        if (isLibraryView) {
            // Si on regarde la librairie, on la rafraîchit normalement
            if (typeof showLibrary === "function") showLibrary();
        } else {
            // SI ON EST AILLEURS (ex: Folder View)
            // On appelle une fonction qui recharge les données des cartes 
            // SANS vider le mainContainer ou changer de vue.
            if (typeof loadSavedPlaylists === "function") {
                // On suppose que loadSavedPlaylists met à jour les variables 
                // mais ne fait pas de setActiveView
                loadSavedPlaylists();
            }
        }

    } catch (err) {
        console.error("Erreur synchro bibliothèque :", err);
    }
}


// --- SYNCHRO AUTOMATIQUE DU VOLET DE PLAYLISTS ---

let lastPlaylistVersion = 0;

async function checkPlaylistUpdate() {
    try {
        const res = await fetch(`${API_BASE_URL}/api/playlist/version`);
        const data = await res.json();

        if (data.version !== lastPlaylistVersion) {
            lastPlaylistVersion = data.version;

            // Si le volet playlist est ouvert, on le rafraîchit
            const panel = document.getElementById('playlistPanel');
            if (panel && panel.classList.contains('open')) {
                if (typeof loadPlaylistFromServer === 'function') {
                    loadPlaylistFromServer();
                }
            }
        }
    } catch (e) {
        console.error("Erreur synchro playlist:", e);
    }
}

setInterval(checkPlaylistUpdate, 2500); // Augmenté de 1500 à 2500ms




// Vérification toutes les 4 secondes (Augmenté de 2000 à 4000ms)
setInterval(checkPlaylistLibraryVersion, 4000);




/**
 * ---------------------------------------------------------
 * SYNCHRONISATION AVEC MPV & AFFICHAGE INFOS BDD
 * ---------------------------------------------------------
 */

async function updateStatus() {
    try {
        const response = await fetch(`${API_BASE_URL}/status`);
        if (!response.ok) return;
        const data = await response.json();

        // --- 1. MISE À JOUR DES INFOS (HEADER & TEXTES) ---
        if (data.track) {
            // Mise à jour de l'ID global (qu'il soit INT ou STR/Path)
            //currentTrackId = data.track.id;

            const elTitle = document.getElementById("trackTitle");
            const elArtist = document.getElementById("trackArtist");
            const elAlbum = document.getElementById("trackAlbum");

            if (elTitle && elTitle.innerText !== data.track.title) {
                elTitle.innerText = data.track.title || "---";
                if (elArtist) elArtist.innerText = data.track.artist || "---";
                if (elAlbum) elAlbum.innerText = data.track.album || "";
            }

            // --- MISE À JOUR DE LA POCHETTE ---
            const elHeader = document.querySelector(".jukebox-header");
            const elCover = document.getElementById("current-cover");

            let coverKey = null;
            let nextSrc = null;

            // Logique de sélection de la source d'image
            if (data.track.cover_path) {
                coverKey = data.track.cover_path;
                // Si le chemin commence par http, on le garde, sinon on préfixe
                if (data.track.cover_path.startsWith('http')) {
                    nextSrc = data.track.cover_path;
                } else {
                    // On s'assure qu'il y a un slash entre base et path
                    const path = data.track.cover_path.startsWith('/') ? data.track.cover_path : '/' + data.track.cover_path;
                    nextSrc = `${API_BASE_URL}${path}`;
                }
            } else {
                coverKey = `id:${data.track.id}`;
                nextSrc = `${API_BASE_URL}/cover/${data.track.id}`;
            }

            // Anti‑clignotement : on ne recharge que si la source change
            if (coverKey !== currentCoverKey) {
                const fullSrc = `${nextSrc}${nextSrc.includes('?') ? '&' : '?'}t=${Date.now()}`;
                const imgTester = new Image();
                imgTester.src = fullSrc;

                imgTester.onload = () => {
                    const urlFormat = `url("${fullSrc}")`;
                    document.body.style.backgroundImage = urlFormat;
                    if (elHeader) elHeader.style.backgroundImage = urlFormat;
                    if (elCover) {
                        elCover.style.display = "block";
                        elCover.src = fullSrc;
                    }
                };

                imgTester.onerror = () => {
                    const neutralBg = "linear-gradient(135deg, #121212 0%, #282828 100%)";
                    document.body.style.backgroundImage = neutralBg;
                    if (elHeader) elHeader.style.backgroundImage = neutralBg;
                    if (elCover) elCover.style.display = "none";
                };

                currentCoverKey = coverKey;
            }
        }

        // --- 2. GESTION DU HIGHLIGHT & AUTO-SCROLL INTELLIGENT ---
        const allItems = document.querySelectorAll(".playlist-item, .song-item, .album-track-item, .file-card");
        const newTrackId = data.track ? data.track.id : null;

        allItems.forEach(item => {
            const isCurrent = (newTrackId && String(item.dataset.id) === String(newTrackId));
            item.classList.toggle("playing-now", isCurrent);

            if (isCurrent && item.classList.contains('playlist-item')) {
                const panel = document.getElementById('playlistPanel');

                // Ici, currentTrackId a encore l'ANCIENNE valeur (grâce à la modif de la section 1)
                const hasChanged = (currentTrackId !== newTrackId);

                if (panel && panel.classList.contains('open') && hasChanged) {
                    const footer = panel.querySelector('.playlist-actions-container');
                    const isHoveringPanel = panel.matches(':hover');
                    const isHoveringFooter = footer && footer.matches(':hover');

                    // On scroll SI : 
                    // 1. La souris n'est PAS sur le panneau (cas général)
                    // 2. OU SI la souris est SUR le footer (boutons de navigation)
                    if (!isHoveringPanel || isHoveringFooter) {
                        item.scrollIntoView({
                            behavior: 'smooth',
                            block: 'center'
                        });
                    }
                }
            }
        });

        // C'EST ICI qu'on met à jour l'ID global, une fois que le scroll a été testé
        currentTrackId = newTrackId;

        // --- 3. BARRE DE PROGRESSION & TEMPS ---
        const currentTxt = document.getElementById("currentTime");
        const totalTxt = document.getElementById("totalTime");
        if (!slider) slider = document.getElementById("progressSlider");

        if (slider) {
            if (data.duration > 0) {
                slider.max = Math.floor(data.duration);
                if (totalTxt) totalTxt.innerText = formatTime(data.duration);
            }
            if (!isDragging) {
                slider.value = Math.floor(data.pos || 0);
                if (currentTxt) currentTxt.innerText = formatTime(data.pos || 0);
            }
        }

        // --- 3b. IDEM POUR LE MINI-PLAYER (Playlist) ---
        const plCurrentTxt = document.getElementById("plCurrentTime");
        const plTotalTxt = document.getElementById("plTotalTime");
        if (!plSlider) plSlider = document.getElementById("plProgressSlider");

        if (plSlider) {
            if (data.duration > 0) {
                plSlider.max = Math.floor(data.duration);
                if (plTotalTxt) plTotalTxt.innerText = formatTime(data.duration);
            }
            if (!isDraggingPl) {
                plSlider.value = Math.floor(data.pos || 0);
                if (plCurrentTxt) plCurrentTxt.innerText = formatTime(data.pos || 0);
            }
        }

        // --- 3c. HIGHLIGHT PROGRESS VISUALIZATION ---
        // On calcule le pourcentage d'avancement
        let progressPct = 0;
        if (data.duration > 0) {
            progressPct = ((data.pos || 0) / data.duration) * 100;
        }

        // On applique ce pourcentage à tous les éléments "playing-now"
        const playingItems = document.querySelectorAll(".playing-now");
        playingItems.forEach(item => {
            item.style.setProperty("--progress", progressPct + "%");
        });

        // --- 4. ÉTAT DU BOUTON PAUSE ---
        const btn = document.getElementById("pauseBtn");
        if (btn) {
            if (data.paused) {
                btn.classList.add("paused");
                btn.classList.remove("playing");
            } else {
                btn.classList.add("playing");
                btn.classList.remove("paused");
            }
        }


        const plBtn = document.getElementById("plPauseBtn");
        if (plBtn) {
            if (data.paused) {
                plBtn.classList.add("paused");
                plBtn.classList.remove("playing");
            } else {
                plBtn.classList.add("playing");
                plBtn.classList.remove("paused");
            }
        }

        // --- 5. SYNCHRO DU SLIDER VOLUME ---
        const volSlider = document.getElementById("volumeSlider");
        const plVolSlider = document.getElementById("plVolumeSlider");
        const speakerBtn = document.getElementById("speakerBtn");

        if (!isDraggingVolume) {
            if (data.volume !== undefined) {
                if (volSlider) volSlider.value = data.volume;
                if (plVolSlider) plVolSlider.value = data.volume;

                // Update icône mute et opacité (POUR LE HEADER ET LA PLAYLIST)
                const plSpeakerBtn = document.getElementById("plSpeakerBtn");
                const headerSpeakerBtn = document.getElementById("headerSpeakerBtn");

                // Fonction d'update visuel (icône + opacité)
                const updateSpeakerIcon = (btn) => {
                    const vol = parseInt(data.volume, 10);
                    if (vol === 0) {
                        btn.innerText = "🔊";
                        btn.style.opacity = "0.5";
                    } else {
                        btn.style.opacity = "1";
                        if (vol < 30) btn.innerText = "🔈";
                        else if (vol < 70) btn.innerText = "🔉";
                        else btn.innerText = "🔊";
                    }
                };

                if (plSpeakerBtn) updateSpeakerIcon(plSpeakerBtn);
                if (headerSpeakerBtn) updateSpeakerIcon(headerSpeakerBtn);
            }
        }

        // --- 6. SYNCHRO PLAYLIST (NOM + CONTENU) ---
        const nameElement = document.getElementById('current-playlist-name');
        if (nameElement && data.playlist_name) {
            if (nameElement.innerText !== data.playlist_name) {
                nameElement.innerText = data.playlist_name;
                localStorage.setItem('currentPlaylistName', data.playlist_name);
                if (typeof loadPlaylistFromServer === 'function') {
                    loadPlaylistFromServer();
                }
            }
        }

        // --- 7. SYNCHRO BIBLIOTHÈQUE ---
        const libraryMarker = document.getElementById('library-marker');
        if (libraryMarker && data.library) {
            if (typeof renderLibraryUI === 'function') {
                renderLibraryUI(data.library);
            }
        }

        // --- 8. SYNCHRO DU BOUTON SHUFFLE ---
        if (data.shuffle !== undefined) {
            // On met à jour la variable locale globale
            shuffleActive = data.shuffle;

            // On met à jour l'apparence du bouton
            const sbtn = document.getElementById("shufflePlaylistBtn");
            if (sbtn) {
                // Utilise tes classes existantes
                sbtn.classList.toggle("active", data.shuffle);
                sbtn.classList.toggle("inactive", !data.shuffle);
            }
        }

        // --- SYNCHRO DU SCAN DANS updateStatus() ---
        if (data.scan) {
            const s = data.scan;
            const btn = document.getElementById('btn-reindex');

            // 1. Gestion du bouton (Synchronisé)
            if (btn) {
                if (s.status === "running") {
                    btn.disabled = true;
                    btn.innerText = "Scanning en cours...";
                } else if (s.status === "completed") {
                    btn.disabled = false;
                    btn.innerText = "Re-run Full Index";
                } else {
                    btn.disabled = false;
                    btn.innerText = "Full Reindex";
                }
            }

            // 2. Mise à jour visuelle du cercle et des textes
            // On envoie l'objet 's' ENTIER à updateScanStatus
            if (document.getElementById('settingsModal').style.display === 'flex') {
                updateScanStatus(s);
            }
        }


        // --- 9. SYNCHRO AUDIO CLIENT (RELAY) ---
        // --- 9. SYNCHRO AUDIO CLIENT (NATIVE) ---
        if (isLocalAudioEnabled) {

            // 1. Get Native State
            const JukeBox = Capacitor.Plugins.JukeBox;
            const nativeState = await JukeBox.getPosition();
            // returns { pos: 12.3, duration: 180, isPlaying: true/false }

            const serverPos = data.pos || 0;
            const serverPaused = data.paused;
            let streamUrl = null;

            // Détection de la source
            if (data.track && data.track.id && String(data.track.id).startsWith("folder_")) {
                const idx = data.track.id.split("_")[1];
                streamUrl = `${API_BASE_URL}/stream/folder/${idx}`;
            } else if (data.track && data.track.id) {
                streamUrl = `${API_BASE_URL}/stream/track/${data.track.id}`;
            }

            // A. Changement de piste
            if (isWaitingForNextTrack && data.track && String(data.track.id) === String(currentLocalTrackId)) {
                // On attend que le serveur change l'ID après une fin de morceau
                return;
            }

            if (streamUrl && currentLocalTrackId !== data.track.id) {
                console.log("Local Audio (Native): Nouveau morceau détecté", streamUrl);
                currentLocalTrackId = data.track.id;
                isWaitingForNextTrack = false; // On a reçu le nouveau, on débloque.

                // Metadata for Native Lockscreen
                let coverUrl = "";
                if (data.track.cover_path) {
                    if (data.track.cover_path.startsWith('http')) {
                        coverUrl = data.track.cover_path;
                    } else {
                        const path = data.track.cover_path.startsWith('/') ? data.track.cover_path : '/' + data.track.cover_path;
                        coverUrl = `${API_BASE_URL}${path}`;
                    }
                } else {
                    coverUrl = `${API_BASE_URL}/cover/${data.track.id}`;
                }

                await JukeBox.setMetadata({
                    title: data.track.title || "Titre inconnu",
                    artist: data.track.artist || "Artiste inconnu",
                    album: data.track.album || "WinJukeBox",
                    cover: coverUrl
                });

                // Start Playback
                // Note: We don't check serverPaused here. If we change track, we buffer it.
                // But we should respecting serverPaused for *starting*?
                // If server is paused, we load but don't play? 
                // Native "playUrl" starts immediately.
                // We will rely on section B to pause if needed.
                await JukeBox.play({ url: streamUrl });
                // Immediate seek sync (handled by native pendingSeekPos logic)
                await JukeBox.seek({ pos: serverPos });

                // If server is paused, we might start and then immediately pause in section B.
                // That's acceptable for now to ensure loading.
            }

            // B. Synchro Lecture / Pause
            if (serverPaused && nativeState.isPlaying) {
                await JukeBox.pause();
            } else if (!serverPaused && !nativeState.isPlaying && streamUrl) {
                // Only resume if we have a track
                await JukeBox.resume();
            }

            // C. Synchro Temps (Drift Correction)
            // L'audio local a tendance à être en avance (Lead). On tolère ça.
            const localTime = nativeState.pos; // seconds
            const drift = localTime - serverPos;
            const maxLead = 6.0;
            const maxLag = 2.0;

            // On corrige le temps SI :
            // 1. Le player natif joue effectivemment
            // 2. OU SI le serveur joue, qu'on a une URL, mais qu'on est largué (ex: au début du stream)
            const shouldSync = nativeState.isPlaying || (!serverPaused && streamUrl && Math.abs(drift) > maxLag);

            if (shouldSync) {
                if (drift > maxLead) {
                    console.log(`Resync (Lead > ${maxLead}s): Local=${localTime} / Server=${serverPos} -> Seek Back`);
                    await JukeBox.seek({ pos: serverPos });
                } else if (drift < -maxLag) {
                    console.log(`Resync (Lag > ${maxLag}s): Local=${localTime} / Server=${serverPos} -> Seek Fwd`);
                    await JukeBox.seek({ pos: serverPos });
                }
            }
        }

    } catch (err) {
        console.error("Erreur updateStatus:", err);
    }
}

// Lancement de la boucle
setInterval(updateStatus, 1000);

// --- NATIVE CALLBACK : AUTO-NEXT ---
if (typeof Capacitor !== 'undefined' && Capacitor.Plugins.JukeBox) {
    Capacitor.Plugins.JukeBox.addListener('trackFinished', () => {
        console.log("Native Event: Track Finished -> Triggering immediate updateStatus");
        isWaitingForNextTrack = true; // Empêche de relancer le même morceau
        if (typeof updateStatus === 'function') {
            updateStatus();
        }
    });
}

/**
 * Lancer un album complet
 */
async function playFullAlbumNow(albumName, artistName) {
    try {
        const response = await fetch(`${API_BASE_URL}/api/play_album_now`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ album: albumName, artist: artistName })
        });

        const data = await response.json();

        if (data.first_id) {
            play(data.first_id);
            console.log("Lecture de l'album lancée :", albumName);
        } else {
            console.error("Erreur : Aucun ID retourné par le serveur");
        }
    } catch (err) {
        console.error("Erreur lors de la requête album :", err);
    }
}

/**
 * ---------------------------------------------------------
 *  PLAYLIST (SQLITE + PANNEAU SLIDE-IN + ENCHAÎNEMENT)
 * ---------------------------------------------------------
 */

let playlist = [];
let currentPlaylistIndex = -1;
let isPlaylistMode = false;





/* Charger la playlist depuis le serveur */
async function loadPlaylistFromServer() {
    try {
        const res = await fetch(`${API_BASE_URL}/playlist`);
        const data = await res.json();
        playlist = data.songs || [];
        refreshPlaylistUI();
    } catch (e) {
        console.warn("Erreur de chargement de la playlist", e);
    }
}

/* Ajouter une chanson à la playlist via son ID */
async function addToPlaylist(id) {
    if (!id) return;

    await fetch(`${API_BASE_URL}/playlist/add/${id}`, { method: "POST" });

    // Mise à jour silencieuse de la playlist
    if (typeof updatePlaylistUI === 'function') {
        updatePlaylistUI();
    }

    // Mise à jour silencieuse de la bibliothèque (si elle est affichée)
    const mainContainer = document.getElementById("songList");
    const isLibraryView = mainContainer?.dataset.view === "library";

    if (isLibraryView && typeof showLibrary === 'function') {
        showLibrary();
    } else if (typeof updateLibraryUI === 'function') {
        updateLibraryUI();
    }
}

/* Ajouter une chanson à la playlist via un élément (bouton) */
async function addToPlaylistFromElement(target) {
    const id = Number(target.dataset.id);
    if (!id) return;
    await addToPlaylist(id);
}

/* Supprimer une chanson de la playlist */
async function removeFromPlaylist(id) {
    await fetch(`${API_BASE_URL}/playlist/remove/${id}`, { method: "DELETE" });
    loadPlaylistFromServer();
}

/* Rafraîchir l'affichage du panneau playlist */
function refreshPlaylistUI() {
    const ul = document.getElementById("playlistItems");
    if (!ul) return;

    ul.innerHTML = "";

    playlist.forEach((song, index) => {
        const li = document.createElement("li");
        li.classList.add("playlist-item");
        li.dataset.id = song.id;

        // 1. Création du Slot pour la mini-cover (fixe à 32px)
        const coverSlot = document.createElement("div");
        coverSlot.style.width = "32px";
        coverSlot.style.height = "32px";
        coverSlot.style.marginRight = "12px";
        coverSlot.style.flexShrink = "0";
        coverSlot.style.borderRadius = "3px";
        coverSlot.style.overflow = "hidden";
        coverSlot.style.backgroundColor = "rgba(255,255,255,0.05)"; // Optionnel : léger fond gris
        coverSlot.style.display = "flex";
        coverSlot.style.alignItems = "center";
        coverSlot.style.justifyContent = "center";

        // 2. Test de l'image pour la mini-cover
        const miniImg = new Image();
        miniImg.src = `${API_BASE_URL}/cover/${song.id}`;
        // miniImg.loading = "lazy"; // RETRAIT : Cause des soucis d'affichage dans le volet masqué
        miniImg.style.width = "100%";
        miniImg.style.height = "100%";
        miniImg.style.objectFit = "cover";

        miniImg.onload = () => {
            coverSlot.appendChild(miniImg);
        };
        // Si erreur (404), on ne fait rien : le slot reste vide (zone de vide propre)

        // 3. Zone texte cliquable
        const textSpan = document.createElement("span");
        textSpan.textContent = `${song.title} — ${song.artist}`;
        textSpan.classList.add("playlist-text");
        textSpan.style.flexGrow = "1"; // Pour que le texte occupe l'espace
        textSpan.style.fontSize = "0.85em";
        textSpan.style.whiteSpace = "nowrap";
        textSpan.style.overflow = "hidden";
        textSpan.style.textOverflow = "ellipsis";

        textSpan.addEventListener("click", () => {
            const foundIndex = playlist.findIndex(s => s.id === song.id);
            if (foundIndex !== -1) {
                isPlaylistMode = true;
                currentPlaylistIndex = foundIndex;
                play(song.id);
            }
        });

        // 4. Bouton corbeille
        const trashBtn = document.createElement("button");
        trashBtn.textContent = "🗑";
        trashBtn.classList.add("remove-btn");
        trashBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            removeFromPlaylist(song.id);
        });

        // Assemblage (Vignette + Texte + Poubelle)
        li.appendChild(coverSlot);
        li.appendChild(textSpan);
        li.appendChild(trashBtn);
        ul.appendChild(li);
    });
}

/**
 * GESTION DE L'OUVERTURE DU PANNEAU (Fonction partagée)
 */
function togglePlaylist() {
    const playlistPanel = document.getElementById('playlistPanel');
    if (!playlistPanel) return;

    const isOpen = playlistPanel.classList.contains('open');

    if (isOpen) {
        playlistPanel.classList.remove('open');
        document.body.classList.remove('playlist-is-open');
    } else {
        playlistPanel.classList.add('open');
        document.body.classList.add('playlist-is-open');

        // --- CHIRURGIE : Focus au centre à l'ouverture ---
        setTimeout(() => {
            const current = playlistPanel.querySelector('.playlist-item.playing-now');
            if (current) {
                current.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
        }, 400); // 400ms pour laisser le temps au CSS de finir le slide-in
    }
}


/* Initialisation du panneau playlist */
function initPlaylistPanel() {
    const playlistPanel = document.getElementById("playlistPanel");
    const openPlaylistBtn = document.getElementById("openPlaylistBtn");
    const closePlaylistBtn = document.getElementById("closePlaylistBtn");
    const playPlaylistBtn = document.getElementById("playPlaylistBtn");
    const shufflePlaylistBtn = document.getElementById("shufflePlaylistBtn");
    const nextBtn = document.getElementById("nextBtn");
    const prevBtn = document.getElementById("prevBtn");
    const clearPlaylistBtn = document.getElementById("clearPlaylistBtn");

    if (clearPlaylistBtn) {
        clearPlaylistBtn.addEventListener("click", async () => {
            await fetch(`${API_BASE_URL}/playlist/clear`, { method: "DELETE" });
            loadPlaylistFromServer();
        });
    }


    if (closePlaylistBtn && playlistPanel) {
        closePlaylistBtn.addEventListener("click", () => {
            // On ferme le panneau et on retire le décalage
            playlistPanel.classList.remove("open");
            document.body.classList.remove("playlist-is-open");
        });
    }

    if (playPlaylistBtn) {
        playPlaylistBtn.addEventListener("click", () => {
            if (playlist.length > 0) {
                isPlaylistMode = true;
                currentPlaylistIndex = 0;
                play(playlist[0].id);
            }
        });
    }

    if (shufflePlaylistBtn) {
        shufflePlaylistBtn.addEventListener("click", () => {
            toggleShuffle();
        });
    }

    // Dans initPlaylistPanel, remplace les blocs nextBtn et prevBtn par :
    if (nextBtn) {
        nextBtn.addEventListener("click", () => {
            playNext(); // On laisse playNext gérer l'ID (qu'il soit chiffre ou chemin)
        });
    }

    if (prevBtn) {
        prevBtn.addEventListener("click", () => {
            playPrevious();
        });
    }

    // NOUVEAUX BOUTONS DANS LE PANNEAU PLAYLIST
    const plNext = document.getElementById("plNextBtn");
    const plPrev = document.getElementById("plPrevBtn");

    if (plNext) {
        plNext.addEventListener("click", () => playNext());
    }
    if (plPrev) {
        plPrev.addEventListener("click", () => playPrevious());
    }


    // Gestion des clics délégués pour les boutons dans les cartes
    // --- 1. Gestion des clics délégués (Ton bloc actuel) ---
    document.addEventListener("click", (e) => {
        const addBtn = e.target.closest(".add-to-playlist-btn");
        if (addBtn) {
            addToPlaylistFromElement(addBtn);
        }

        const playBtn = e.target.closest(".play-btn");
        if (playBtn) {
            const id = Number(playBtn.dataset.id);
            if (id) {
                const isInPanel = !!playBtn.closest("#playlistPanel");
                if (isInPanel) {
                    isPlaylistMode = true;
                    fetch(`${API_BASE_URL}/api/clear_album_table`, { method: "POST" }).catch(() => { });
                } else {
                    isPlaylistMode = false;
                }
                play(id);
            }
        }
    });

    // --- 2. Fonctions de chargement initial ---
    loadPlaylistFromServer();
    refreshShuffleStatus();

    // --- 3. LE FIX : Lancement automatique du mode Artiste avec délai ---
    // On attend que le navigateur ait fini de traiter les fonctions ci-dessus
    setTimeout(() => {
        console.log("Démarrage auto : Simulation clic Artiste");
        const artistBtn = document.querySelector('.nav-mode-btn[data-mode="artist"]');
        if (artistBtn) {
            artistBtn.click(); // Cela va lancer switchMode ET doSearch proprement
        }
    }, 500); // 500ms pour laisser le temps à la base de données/DOM d'être prêts
}


/* Ajout des helpers shuffle */
let shuffleActive = false;

async function refreshShuffleStatus() { // Déclarée comme ça, c'est parfait
    try {
        const response = await fetch(`${API_BASE_URL}/api/playlist/shuffle_status`);
        const data = await response.json();
        shuffleActive = data.shuffle;
        const shuffleBtn = document.getElementById("shuffleBtn");
        if (shuffleBtn) {
            shuffleBtn.classList.toggle("active", shuffleActive);
        }
    } catch (err) {
        console.error("Erreur shuffle status:", err);
    }
}

function updateShuffleButton() {
    const btn = document.getElementById("shufflePlaylistBtn");
    if (!btn) return;
    btn.classList.toggle("active", shuffleActive);
    btn.classList.toggle("inactive", !shuffleActive);
}

async function enableShuffle() {
    try {
        const res = await fetch(`${API_BASE_URL}/shuffle/enable`, { method: "POST" });
        const data = await res.json();
        shuffleActive = true;
        isPlaylistMode = true;        // on lit en mode "playlist"
        currentPlaylistIndex = -1;    // index local n'a plus de sens en shuffle
        updateShuffleButton();
    } catch (e) {
        console.warn("Erreur /shuffle/enable", e);
    }
}

async function disableShuffle() {
    try {
        await fetch(`${API_BASE_URL}/shuffle/disable`, { method: "POST" });
        shuffleActive = false;
        updateShuffleButton();
    } catch (e) {
        console.warn("Erreur /shuffle/disable", e);
    }
}

async function toggleShuffle() {
    if (shuffleActive) {
        await disableShuffle();
    } else {
        await enableShuffle();
    }
}



// --- GESTION DES PLAYLISTS SAUVEGARDÉES ---
// 1. CRÉER UNE NOUVELLE PLAYLIST (Bouton +) - VERSION DIRECTE
async function createNewPlaylist() {
    const name = prompt("Nom de votre nouvelle playlist :", "Ma Playlist");
    if (!name || name.trim() === "") return;

    try {
        // --- Création réelle sur le serveur ---
        const response = await fetch(`${API_BASE_URL}/api/playlists/create`, {
            method: "POST",
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: name })
        });

        const result = await response.json();
        if (result.status !== "success") return;

        // --- 1. Mettre à jour le titre affiché immédiatement ---
        const nameElement = document.getElementById('current-playlist-name');
        if (nameElement) nameElement.innerText = name;

        localStorage.setItem('currentPlaylistName', name);

        // --- 2. Vider visuellement la liste de droite ---
        if (typeof loadPlaylistFromServer === 'function') {
            await loadPlaylistFromServer();
        }

        // --- 3. Rafraîchir la bibliothèque (si ouverte) ---
        const container = document.getElementById("songList");
        const isLibraryView = container?.dataset.view === "library";

        if (isLibraryView && typeof showLibrary === 'function') {
            showLibrary();
        } else if (typeof updateLibraryUI === 'function') {
            updateLibraryUI();
        }

        // --- 4. Message de succès ---
        container.innerHTML = `
            <div style="padding: 40px; text-align: center;">
                <h2 style="color: #1db954;">✨ Playlist "${name}" prête</h2>
                <p style="color: #888;">Elle est actuellement vide. Ajoutez des titres !</p>
            </div>`;

    } catch (err) {
        console.error("Erreur création playlist:", err);
    }
}


// 2. SAUVEGARDER (Bouton Disquette) - Version silencieuse
async function promptSavePlaylist() {
    const nameElement = document.getElementById('current-playlist-name');
    const name = nameElement.innerText.trim();

    if (!name) return; // sécurité

    try {
        await fetch(`${API_BASE_URL}/api/playlists/save`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name })
        });

        // 🔇 Mode silencieux : aucune modification d'UI, aucun showLibrary()
        // On laisse la synchro multi-device faire son travail en arrière-plan.

    } catch (err) {
        console.error("Erreur réseau sauvegarde:", err);
    }
}

function updatePlaylistUI() {
    fetch(`${API_BASE_URL}/playlist`)
        .then(res => res.json())
        .then(data => {
            playlist = data.songs || [];
            refreshPlaylistUI();
        })
        .catch(err => console.error("Erreur mise à jour playlist :", err));
}


// Mise à jour silencieuse de la bibliothèque (sans changer de vue)
async function updateLibraryUI() {
    try {
        const response = await fetch(`${API_BASE_URL}/api/playlists`);
        const data = await response.json();

        if (data.playlists && typeof renderLibraryUI === "function") {
            renderLibraryUI(data.playlists);
        }
    } catch (err) {
        console.error("Erreur updateLibraryUI:", err);
    }
}

// 3. AFFICHER LA BIBLIOTHÈQUE (Panneau central)
async function showLibrary() {
    try {
        const response = await fetch(`${API_BASE_URL}/api/playlists`);
        const data = await response.json();
        const mainContainer = document.getElementById('songList');

        // 🔥 AJOUT ICI
        mainContainer.dataset.view = "library";

        let html = `

    <div style="padding: 20px;">
        <div style="display: flex; align-items: center; gap: 15px; margin-bottom: 20px;">
            <div class="header-btn-pill" style="cursor: default;">
                <img src="icons/playlists.png" alt="Bibliothèques" class="btn-icon-large">
            </div>
            
            <button onclick="createNewPlaylist(event)" title="Nouvelle Playlist" class="header-btn-pill">
                <img src="icons/createplaylist.png" alt="Créer Playlist" class="btn-icon-large">
            </button>
        </div>
        <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 20px;">
`;

        if (data.playlists && data.playlists.length > 0) {
            data.playlists.forEach(pl => {
                html += `
                    <div class="playlist-card" style="background: #181818; padding: 20px; border-radius: 10px; border: 1px solid #333; text-align: left;">
                        <h3 style="margin: 0 0 10px 0; color: #1db954; cursor: pointer; border-bottom: 1px dashed rgba(29, 185, 84, 0.3);" 
                            title="Cliquez pour renommer"
                            onclick="startRenamePlaylist(${pl.id}, '${pl.name.replace(/'/g, "\\'")}', this)">${pl.name}</h3>
                        <p style="color: #aaa; font-size: 0.9rem; margin-bottom: 15px;">${pl.count} morceaux</p>
                        <div style="display: flex; gap: 10px;">
                           <button onclick="loadSavedPlaylist(${pl.id}, '${pl.name.replace(/'/g, "\\'")}')" style="background: #1db954; border: none; padding: 5px 10px; border-radius: 4px; cursor: pointer;"><img src="icons/load.png" style="height:16px; vertical-align:middle;"></button>
                           <button onclick="deleteSavedPlaylist(${pl.id})" style="background: transparent; border: 1px solid #ff4444; color: #ff4444; padding: 5px 10px; border-radius: 4px; cursor: pointer;"><img src="icons/close.png" style="height:16px; vertical-align:middle;"></button>
                        </div>
                    </div>
                `;
            });
        } else {
            html += `<p style="color: gray;">Aucune playlist sauvegardée.</p>`;
        }

        html += `</div></div>`;
        mainContainer.innerHTML = html;
    } catch (err) {
        console.error("Erreur bibliothèque:", err);
        const mainContainer = document.getElementById('songList');
        if (mainContainer) {
            mainContainer.innerHTML = `
                <div style="padding: 40px; text-align: center; color: #ff4444;">
                    <h3>Erreur de connexion</h3>
                    <p>${err.message}</p>
                    <p style="font-size: 0.8rem; color: gray;">Tentative sur : ${API_BASE_URL}</p>
                    <button onclick="showLibrary()" style="margin-top: 20px; background: #1db954; border: none; padding: 10px 20px; border-radius: 20px; color: black; font-weight: bold; cursor: pointer;">Réessayer</button>
                    <button onclick="toggleServerSidebar()" style="margin-top: 20px; background: transparent; border: 1px solid #1db954; padding: 10px 20px; border-radius: 20px; color: #1db954; font-weight: bold; cursor: pointer; margin-left: 10px;">Changer de serveur</button>
                </div>
            `;
        }
    }
}

// 4. CHARGER UNE PLAYLIST SAUVEGARDÉE
async function loadSavedPlaylist(id, name) {
    try {
        // --- Désactivation du shuffle avant chargement ---
        if (typeof disableShuffle === 'function') {
            await disableShuffle();
        }

        const response = await fetch(`${API_BASE_URL}/api/playlists/load`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: id })
        });

        if (!response.ok) {
            const errorData = await response.json();
            alert("Erreur : " + (errorData.error || "Impossible de charger la playlist."));
            return;
        }

        // --- Mise à jour du nom de la playlist ---
        const nameElement = document.getElementById('current-playlist-name');
        if (nameElement) nameElement.innerText = name;
        localStorage.setItem('currentPlaylistName', name);

        // --- Rechargement de la playlist depuis le serveur ---
        if (typeof loadPlaylistFromServer === 'function') {
            await loadPlaylistFromServer();
        }

        // --- Message dans le panneau central ---
        const mainContainer = document.getElementById('songList');
        if (mainContainer) {
            mainContainer.innerHTML = `
                <div style="padding: 40px; text-align: center;">
                    <h2 style="color: #1db954;">✅ "${name}" chargée</h2>
                    <p style="color: #888;">Le mode aléatoire a été désactivé pour cette nouvelle liste.</p>
                    <p style="color: #555; font-size: 0.9rem;">Retrouvez vos titres dans le volet playlist</p>
                </div>`;
        }

        // --- AUTO-OUVERTURE & RAFRAÎCHISSEMENT ---
        setTimeout(() => {
            const sidePanel = document.getElementById('playlistPanel');
            const isOpen = sidePanel && sidePanel.classList.contains('open');

            // Ouvrir le panneau playlist si nécessaire
            if (!isOpen && typeof togglePlaylist === 'function') {
                togglePlaylist();
            }

            // Rafraîchir la bibliothèque si nécessaire
            const container = document.getElementById("songList");
            const isLibraryView = container?.dataset.view === "library";

            if (isLibraryView && typeof showLibrary === 'function') {
                showLibrary();
            } else if (typeof updateLibraryUI === 'function') {
                updateLibraryUI();
            }

        }, 1000);

    } catch (err) {
        console.error("Erreur critique lors du chargement:", err);
    }
}


// 5. SUPPRIMER UNE PLAYLIST
async function deleteSavedPlaylist(id) {
    if (!confirm("Supprimer définitivement cette playlist ?")) return;
    try {
        const response = await fetch(`${API_BASE_URL}/api/playlists/${id}`, { method: 'DELETE' });
        if (response.ok) showLibrary();
    } catch (err) {
        console.error("Erreur suppression:", err);
    }
}

// 6. RENOMMER UNE PLAYLIST (UI Inline)
function startRenamePlaylist(id, currentName, titleElement) {
    // Si déjà en mode édition, on ne fait rien
    if (titleElement.querySelector('input')) return;

    // Sauvegarde du HTML actuel pour restoration si annulation (via Escape)
    const originalHtml = titleElement.innerHTML;

    titleElement.innerHTML = `
        <div style="display: flex; align-items: center; gap: 5px;">
            <input type="text" value="${currentName.replace(/"/g, '&quot;')}" 
                style="background: #333; border: 1px solid #1db954; color: white; padding: 2px 5px; border-radius: 4px; font-size: 0.9em; width: 100%;"
                onkeydown="handleRenameKey(event, ${id}, this, '${currentName.replace(/'/g, "\\'")}')"
            >
            <button onclick="confirmRenamePlaylist(${id}, this.previousElementSibling)" 
                style="background: #1db954; border: none; cursor: pointer; border-radius: 4px; padding: 2px 6px; font-size: 0.8em;">✔</button>
        </div>
    `;

    // Focus sur l'input
    const input = titleElement.querySelector('input');
    if (input) {
        input.focus();
        input.select();
        // Gestion de la touche Echap pour annuler
        input.addEventListener('blur', (e) => {
            // Optionnel : On pourrait valider au blur, ou annuler.
            // Ici, on va annuler si on clique ailleurs pour éviter les fausses manips, 
            // ou alors on laisse tel quel. Le mieux pour l'UX est souvent d'annuler ou de demander.
            // Pour la simplicité, on ne fait rien au blur pour l'instant, l'utilisateur doit valider ou Echap.
        });
    }
}

function handleRenameKey(event, id, input, originalName) {
    if (event.key === 'Enter') {
        confirmRenamePlaylist(id, input);
    } else if (event.key === 'Escape') {
        // Annulation : on remet le titre original
        const container = input.closest('h3');
        if (container) {
            container.innerHTML = originalName; // Simplification, ou recharge UI
            // Comme renderLibraryUI recrée tout, le plus simple est parfois de laisser faire
            // Mais ici on veut juste remettre le texte clean.
            updateLibraryUI(); // On recharge pour être sûr d'être propre
        }
    }
}

async function confirmRenamePlaylist(id, inputElement) {
    const newName = inputElement.value.trim();
    if (!newName) return;

    try {
        const res = await fetch(`${API_BASE_URL}/api/playlists/rename`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: id, name: newName })
        });

        const result = await res.json();
        if (result.status === "success") {
            // On laisse updateLibraryUI gérer le rafraîchissement global
            // Mais pour une réactivité immédiate, on peut aussi maj le DOM localement
            updateLibraryUI();
        } else {
            alert("Erreur: " + result.error);
        }
    } catch (e) {
        console.error("Erreur rename:", e);
    }
}

function renderLibraryUI(playlists) {
    const mainContainer = document.getElementById('songList');
    if (!mainContainer) return;

    const isLibraryView = mainContainer.dataset.view === "library";

    // Si on n'est pas dans la vue bibliothèque, on ne touche pas à l'écran
    if (!isLibraryView) {
        return;
    }

    let cardsHtml = '';
    playlists.forEach(pl => {
        const safeName = pl.name.replace(/'/g, "\\'");
        cardsHtml += `
            <div class="playlist-card" style="background: #181818; padding: 20px; border-radius: 10px; border: 1px solid #333;">
                <h3 style="margin: 0 0 10px 0; color: #1db954;">${pl.name}</h3>
                <p style="color: #aaa; font-size: 0.9rem; margin-bottom: 15px;">${pl.count} morceaux</p>
                <div style="display: flex; gap: 10px;">
                   <button onclick="loadSavedPlaylist(${pl.id}, '${safeName}')" class="btn-action-green">
                        <img src="icons/load.png" style="height:16px;">
                   </button>
                   <button onclick="deleteSavedPlaylist(${pl.id})" class="btn-action-red">
                        <img src="icons/close.png" style="height:16px;">
                   </button>
                </div>
            </div>`;
    });

    mainContainer.innerHTML = `
        <div id="library-marker" style="padding: 20px;">
            <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 20px;">
                ${cardsHtml}
            </div>
        </div>`;
}


/* ********************************** MODALE INFO ************************************/

/**
 * Affiche la popup d'informations en analysant le premier MP3 du dossier
 */
/* ********************************** MODALE INFO ************************************/
// Variable globale pour stocker les fichiers du dossier actuel
/* ********************************** LOGIQUE DE NAVIGATION MODALE ************************************/

// Une seule variable globale pour suivre la position
let currentAnalysisIndex = 0;
let currentMusicFiles = [];
/**
 * Ferme la popup
 */
function closeInfoModal() {
    const modal = document.getElementById("infoModal");
    if (modal) modal.style.display = "none";
}
async function showFolderInfo(path, index = -1) {
    const modal = document.getElementById("infoModal");
    const statusZone = document.getElementById("infoStatus");
    const detailsZone = document.getElementById("infoDetails");
    const pathDisplay = document.getElementById("infoPath");

    modal.style.display = "flex";
    statusZone.style.display = "block";
    detailsZone.style.display = "none";

    // 1. On crée la liste des fichiers éligibles (MP3/WMA)
    currentMusicFiles = currentFolderFiles.filter(item =>
        item.type === "file" &&
        (item.name.toLowerCase().endsWith('.mp3') || item.name.toLowerCase().endsWith('.wma'))
    );

    if (currentMusicFiles.length === 0) {
        pathDisplay.innerText = "Aucun fichier musical trouvé.";
        statusZone.innerHTML = "❌ Aucun média compatible.";
        return;
    }

    // 2. Gestion intelligente de l'index
    // Si on appelle la fonction sans index (premier clic sur le bouton info)
    if (index === -1) {
        currentAnalysisIndex = 0;
    } else {
        currentAnalysisIndex = index;
    }

    const targetFile = currentMusicFiles[currentAnalysisIndex];
    pathDisplay.innerText = `[${currentAnalysisIndex + 1}/${currentMusicFiles.length}] - ${targetFile.name}`;

    // 3. Mise à jour des boutons Next/Prev (les IDs de tes icônes PNG)
    const prevBtn = document.getElementById("infoPrevBtn");
    const nextBtn = document.getElementById("infoNextBtn");

    if (prevBtn) {
        prevBtn.style.opacity = currentAnalysisIndex > 0 ? "1" : "0.2";
        prevBtn.style.pointerEvents = currentAnalysisIndex > 0 ? "auto" : "none";
        prevBtn.onclick = () => showFolderInfo(null, currentAnalysisIndex - 1);
    }

    if (nextBtn) {
        nextBtn.style.opacity = currentAnalysisIndex < currentMusicFiles.length - 1 ? "1" : "0.2";
        nextBtn.style.pointerEvents = currentAnalysisIndex < currentMusicFiles.length - 1 ? "auto" : "none";
        nextBtn.onclick = () => showFolderInfo(null, currentAnalysisIndex + 1);
    }

    // 4. Lancement de l'analyse Python
    // On reset la zone de status pour vider les erreurs précédentes
    statusZone.innerHTML = `
        <div class="loader"></div>
        <p style="text-align:center;">Identification acoustique...</p>
    `;

    try {
        const response = await fetch(`${API_BASE_URL}/api/analyze_folder_info`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: targetFile.path })
        });

        const info = await response.json();

        // On bascule quoi qu'il arrive vers le rendu de détails (qui gère le cas id_found: false)
        statusZone.style.display = "none";
        renderInfoDetails(info);

    } catch (err) {
        statusZone.innerHTML = `<p style="color:#ff6b6b; padding:10px;">❌ Erreur de connexion serveur.</p>`;
        // On affiche quand même les boutons de navigation pour ne pas rester bloqué
        setupInfoNavigation(musicFiles.length);
    }
}

/**
 * Génère le contenu HTML des résultats avec le bouton de téléchargement
 */
function renderInfoDetails(info) {
    const detailsZone = document.getElementById("infoDetails");
    detailsZone.style.display = "block";

    // 1. EXTRACTION DU CHEMIN
    const currentFilePath = currentMusicFiles[currentAnalysisIndex].path;
    const cleanPath = currentFilePath.replace(/\\/g, '/');

    // Cas où le morceau n'est pas identifié
    if (info.id_found === false) {
        detailsZone.innerHTML = `
            <div style="text-align:center; padding: 20px 0;">
                <img src="default_cover.png" style="width:100px; opacity:0.3; margin-bottom:15px;">
                <h2 style="color:#888; font-size:1.1em;">${info.error || "Morceau non identifié"}</h2>
                <p style="color:#555; font-size:0.9em;">Aucune information trouvée sur MusicBrainz.</p>
                
                <div style="margin-top: 20px;">
                    <button class="tag-icon-btn" title="Ouvrir le moteur de taggage manuel" style="padding: 10px 20px; font-size: 1.2em; border-radius: 20px;">
                        🏷️ Taggage Manuel
                    </button>
                </div>
            </div>
            <hr style="border:0; border-top:1px solid #333; margin:15px 0;">
            <div style="display:flex; justify-content:flex-end;">
                <div class="info-nav-wrapper">
                    <button id="infoPrevBtn" title="Précédent"></button>
                    <button id="infoNextBtn" title="Suivant"></button>
                </div>
            </div>
        `;
        setupInfoNavigation(currentMusicFiles.length);

        // Branchement du bouton tag dans le cas failure
        setTimeout(() => {
            const tagBtn = detailsZone.querySelector('.tag-icon-btn');
            if (tagBtn) {
                tagBtn.onclick = () => openTagModal(null, cleanPath);
            }
        }, 50);
        return;
    }

    const confianceColor = info.confiance > 80 ? "#1db954" : "#f57c00";

    // 2. GÉNÉRATION DU HTML (Navigation préservée)
    detailsZone.innerHTML = `
        <div style="display:flex; gap:20px; align-items:start;">
            <div class="info-cover-container" 
                  onclick="window.open('${info.pochette}', '_blank')" 
                  style="position:relative; cursor:zoom-in;">
                <img id="pochetteImg" src="${info.pochette}" 
                     onerror="if (this.src != '${info.pochette_fallback}') { this.src = '${info.pochette_fallback}'; } else { this.src = 'default_cover.png'; }"
                     onload="window.updateImgMeta(this)"
                     style="width:140px; height:140px; border-radius:8px; object-fit:cover; border: 1px solid #333;">
                <div id="pochetteMeta" class="info-cover-overlay">Chargement...</div>
            </div>

            <div style="flex:1;">
                <h2 style="margin:0; font-size:1.3em; color:white;">${info.nom_album}</h2>
                <p style="color:#1db954; font-weight:bold; margin:8px 0;">${info.nom_artiste}</p>
                <p style="font-size:0.9em; color:#888;">📅 Sortie : ${info.annee}</p>
                
                <div style="margin-top:10px; font-size:0.8em; color:#aaa;">
                    Confiance : <span style="color:${confianceColor}; font-weight:bold;">${info.confiance}%</span>
                    <div style="width:100%; height:4px; background:#333; border-radius:2px; margin-top:4px;">
                        <div style="width:${info.confiance}%; height:100%; background:${confianceColor}; border-radius:2px;"></div>
                    </div>
                </div>
            </div>
        </div>

        <div style="display: flex; align-items: center; gap: 15px; margin: 15px 0;">
            <button class="download-icon-btn" title="Enregistrer cette image comme cover.jpg">
                <img src="icons/getcover.png" alt="Download">
            </button>
            <button class="tag-icon-btn" title="Chemin : ${cleanPath} | MBID : ${info.mbid_album}">
                🏷️
            </button>
        </div>

        <div style="margin-top:15px; font-size:0.7em; color:#555; font-family:monospace;">
            MBID Album : ${info.mbid_album}
        </div>

        <hr style="border:0; border-top:1px solid #333; margin:15px 0;">

        <div style="display:flex; justify-content:space-between; align-items:flex-end;">
            <div style="flex:1;">
                 <p style="font-size:0.7em; color:#555; text-transform:uppercase; margin-bottom:10px;">Liens et Ressources</p>
                 <div style="display:flex; flex-wrap:wrap; gap:8px;">
                    ${Object.entries(info.liens).length > 0
            ? Object.entries(info.liens).map(([name, url]) => `<a href="${url}" target="_blank" class="info-badge">${name}</a>`).join('')
            : '<span style="color:#444; font-size:0.8em;">Aucun lien</span>'}
                 </div>
            </div>

            <div class="info-nav-wrapper">
                <button id="infoPrevBtn" title="Précédent"></button>
                <button id="infoNextBtn" title="Suivant"></button>
            </div>
        </div>
    `;

    // On branche les boutons de navigation (Indispensable !)
    setupInfoNavigation(currentFolderFiles.length);

    // --- BRANCHEMENT PROGRAMMATIQUE DES BOUTONS (PLUS ROBUSTE) ---
    setTimeout(() => {
        const dlBtn = detailsZone.querySelector('.download-icon-btn');
        const tagBtn = detailsZone.querySelector('.tag-icon-btn');

        if (dlBtn) {
            dlBtn.onclick = () => {
                console.log("[TAG-DEBUG] Clic Download Cover");
                downloadAlbumCover(info.pochette, cleanPath);
            };
        }

        if (tagBtn) {
            tagBtn.onclick = () => {
                console.log("[TAG-DEBUG] Clic Open Tag Modal");
                openTagModal(info.mbid_album, cleanPath);
            };
        }
    }, 50);
}

// Les fonctions de support restent identiques
window.updateImgMeta = function (img) {
    const meta = document.getElementById('pochetteMeta');
    if (meta && img.naturalWidth > 1) {
        meta.innerText = `${img.naturalWidth} x ${img.naturalHeight} `;
        if (img.naturalWidth >= 1000) {
            meta.style.color = "#1db954";
            meta.style.fontWeight = "bold";
        }
    }
};

function setupInfoNavigation(totalFiles) {
    const prevBtn = document.getElementById("infoPrevBtn");
    const nextBtn = document.getElementById("infoNextBtn");

    if (prevBtn) {
        prevBtn.disabled = (currentAnalysisIndex <= 0);
        // On remet ta logique exacte
        prevBtn.onclick = () => showFolderInfo(null, currentAnalysisIndex - 1);
    }

    if (nextBtn) {
        nextBtn.disabled = (currentAnalysisIndex >= totalFiles - 1);
        nextBtn.onclick = () => showFolderInfo(null, currentAnalysisIndex + 1);
    }
}


/**
 * Fonction pour envoyer l'ordre de téléchargement au serveur
 */
async function downloadAlbumCover(url, filePath) {
    try {
        const response = await fetch(`${API_BASE_URL}/download_cover`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: url, file_path: filePath })
        });

        const result = await response.json();
        if (result.status === "success") {
            alert("✅ " + result.message);
        } else {
            alert("❌ Erreur : " + result.message);
        }
    } catch (error) {
        console.error("Erreur DL:", error);
        alert("Erreur de communication avec le serveur.");
    }
}

/**
 * Ouvre la modale de taggage avec le MBID et le chemin du fichier
 */
function openTagModal(mbid, path) {
    console.log("[TAG-DEBUG] openTagModal appelée avec:", { mbid, path });
    const modal = document.getElementById("tagModal");
    const statusZone = document.getElementById("tagStatus");
    const detailsZone = document.getElementById("tagDetails");
    const discogsInput = document.getElementById("discogsIdInput");
    const mbidInput = document.getElementById("mbidInput");
    const searchBtn = document.getElementById("tagSearchBtn");

    if (!modal) {
        console.error("[TAG-DEBUG] Elément #tagModal introuvable dans le DOM !");
        return;
    }

    // Reset inputs
    if (discogsInput) discogsInput.value = "";
    if (mbidInput) mbidInput.value = mbid || "";

    // Liaison du bouton de recherche unifié
    if (searchBtn) {
        searchBtn.onclick = () => {
            const m = mbidInput ? mbidInput.value.trim() : "";
            const d = discogsInput ? discogsInput.value.trim() : "";
            loadTagSuggestions(m, path, d);
        };
    }

    const pathBtn = document.getElementById("tagPathBtn");
    if (pathBtn) {
        pathBtn.onclick = () => {
            console.log("[TAG] Forçage analyse via chemin local");
            loadTagSuggestions(null, path, null, true); // true = forcePath
        };
    }

    modal.style.display = "flex";
    statusZone.style.display = "block";
    statusZone.innerHTML = `<div class="loader"></div><p>Initialisation du moteur...</p>`;
    detailsZone.style.display = "none";

    loadTagSuggestions(mbid, path);
}

// Variables globales temporaires pour stocker les suggestions et infos en cours
// On évite les redeclaraions en vérifiant si elles existent (ou on utilise var)
if (typeof currentTagSuggestions === 'undefined') {
    var currentTagSuggestions = null;
    var currentTagFolderPath = null;
    var currentTagMbid = null;
}

/**
 * Charge les suggestions de tag via le serveur et construit la table
 */
async function loadTagSuggestions(mbid, filepath, discogsId = null, forcePath = false) {
    const statusZone = document.getElementById("tagStatus");
    const detailsZone = document.getElementById("tagDetails");
    const tableBody = document.getElementById("tagTableBody");

    console.log("[TAG] Début loadTagSuggestions pour:", filepath, "MBID:", mbid, "DiscogsID:", discogsId, "ForcePath:", forcePath);
    currentTagFolderPath = filepath;
    currentTagMbid = mbid;

    statusZone.style.display = "block";
    detailsZone.style.display = "none";
    statusZone.innerHTML = `<div class="loader"></div><p>Récupération des suggestions...</p>`;

    try {
        const response = await fetch(`${API_BASE_URL}/api/get_tag_suggestions`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                path: filepath,
                mbid: mbid,
                discogs_id: discogsId,
                force_path: forcePath
            })
        });

        const data = await response.json();
        console.log("[TAG] Données reçues:", data);

        if (data.error) {
            statusZone.innerHTML = `<p style="color:#ff6b6b;">❌ Erreur: ${data.error}</p>`;
            return;
        }

        if (data.matched_pairs) {
            // SÉPARATION PISTES / ORPHELINS
            // On reconstruit currentTagSuggestions pour que applyTags continue de fonctionner
            currentTagSuggestions = data.matched_pairs
                .filter(p => p.track)
                .map(p => p.track);

            tableBody.innerHTML = "";

            data.matched_pairs.forEach(pair => {
                const tr = document.createElement("tr");

                // --- CAS 1 : C'est une Piste Web (avec ou sans fichier en face) ---
                if (pair.track) {
                    // Important : le fichier associé à cette ligne
                    tr.dataset.filename = pair.file || "";

                    const suggest = pair.track;
                    const suggestTitle = suggest.title;
                    const suggestArtist = suggest.artist || "---";
                    const suggestAlbum = suggest.album || "";
                    const suggestYear = suggest.year || "";

                    // Affichage du fichier
                    let fileDisplay = "";
                    if (pair.file) {
                        // Code couleur selon le score de confiance
                        const color = pair.score >= 80 ? "#1db954" : (pair.score >= 50 ? "#ffcc00" : "#ccc");
                        const icon = pair.match_type === "duration" ? "⏱" : "📝";
                        fileDisplay = `<span style="color:${color}" title="Match: ${pair.match_type} (${pair.score}%)">${icon} ${pair.file}</span>`;
                    } else {
                        fileDisplay = `<span style="color: #555; font-style: italic; opacity:0.5;">--- (Fichier manquant)</span>`;
                    }

                    tr.innerHTML = `
                        <td style="text-align: center;">
                            <input type="number" class="tag-match-input" value="${pair.track_number}" min="1" max="${currentTagSuggestions.length}">
                        </td>
                        <td style="white-space: nowrap;">${fileDisplay}</td>
                        <td>
                            <div style="color: #1db954; font-weight: bold;">${suggestTitle}</div>
                            <div style="font-size: 0.8em; color: #666;">${suggestArtist} ${suggestAlbum ? ' | ' + suggestAlbum : ''} ${suggestYear ? '(' + suggestYear + ')' : ''}</div>
                        </td>
                    `;
                    tableBody.appendChild(tr);
                }
                // --- CAS 2 : Fichier Orphelin (Pas de piste Web trouvée) ---
                else if (pair.match_type === "orphan") {
                    tr.dataset.filename = pair.file;

                    tr.innerHTML = `
                        <td style="text-align: center;">
                            <input type="number" class="tag-match-input" value="" placeholder="?">
                        </td>
                        <td style="color: #bbb; white-space: nowrap;">${pair.file}</td>
                        <td style="color: #555; font-style: italic;">
                            -- Non identifié --
                        </td>
                    `;
                    tableBody.appendChild(tr);
                }
            });

        } else if (data.local_files) {
            // BACKWARD COMPATIBILITY (Au cas où)
            currentTagSuggestions = data.suggestions;
            // ... (L'ancien code est écrasé ici de toute façon par le replace)
        }

        statusZone.style.display = "none";
        detailsZone.style.display = "block";

        // Liaison du bouton "Appliquer les Tags"
        const applyBtn = document.getElementById("applyTagsBtn");
        if (applyBtn) {
            applyBtn.onclick = () => applyTags();
        }

    } catch (err) {
        console.error("Erreur loadTagSuggestions:", err);
        statusZone.innerHTML = `<p style="color:#ff6b6b;">❌ Erreur de communication serveur.</p>`;
    }
}

/**
 * Collecte les choix de l'utilisateur et envoie l'ordre d'écriture au serveur
 */
async function applyTags() {
    if (!currentTagSuggestions || !currentTagFolderPath) return;

    const applyBtn = document.getElementById("applyTagsBtn");
    const tableBody = document.getElementById("tagTableBody");
    const renameCheckbox = document.getElementById("renameFilesCheckbox");
    const renameFiles = renameCheckbox ? renameCheckbox.checked : false;

    const rows = tableBody.querySelectorAll("tr");

    const mappings = [];

    rows.forEach(row => {
        const filename = row.dataset.filename;
        if (!filename) return; // Saute les lignes orphelines

        const input = row.querySelector(".tag-match-input");
        const matchIdx = parseInt(input.value) - 1;

        if (!isNaN(matchIdx) && currentTagSuggestions[matchIdx]) {
            mappings.push({
                file: filename,
                metadata: currentTagSuggestions[matchIdx],
                track_number: parseInt(input.value) // Important pour le renommage
            });
        }
    });

    if (mappings.length === 0) {
        alert("Aucun matching valide à appliquer.");
        return;
    }

    if (!confirm(`Appliquer les modifications sur ${mappings.length} fichiers ? ${renameFiles ? '\n(Les fichiers seront renommés)' : ''}`)) return;

    applyBtn.disabled = true;
    applyBtn.innerText = "Application...";

    try {
        const response = await fetch(`${API_BASE_URL}/api/apply_tags`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                folder_path: currentTagFolderPath,
                mappings: mappings,
                rename_files: renameFiles
            })
        });

        const result = await response.json();

        if (result.status === "success") {
            alert("✅ " + result.message);
            document.getElementById("tagModal").style.display = "none";
            // On pourrait rafraîchir ici la vue courante
        } else {
            alert("❌ Erreur : " + result.message);
        }
    } catch (err) {
        console.error("Erreur applyTags:", err);
        alert("Erreur de communication avec le serveur.");
    } finally {
        applyBtn.disabled = false;
        applyBtn.innerText = "Appliquer les Tags";
    }
}




/**
 * ********************* MODAL SETTINGS *********************
 */

function openSettings() {
    document.getElementById('settingsModal').style.display = 'flex';

    fetch(`${API_BASE_URL}/scan_status`)
        .then(response => response.json())
        .then(data => {
            const btn = document.getElementById('btn-reindex'); // Assure-toi que ton bouton a cet ID

            if (data.status === "running") {
                // SYNCHRONISATION : Si un autre device a lancé le scan
                updateScanStatus(data.current, data.total, data.speed || 0);

                if (btn) {
                    btn.disabled = true;
                    btn.innerText = "Scanning (from other device)...";
                }

                // OPTIONNEL : Relancer l'écoute automatique du flux pour voir la barre bouger
                // startListeningToProgress(); 
            }
            else if (data.status === "finished") {
                updateScanStatus(data.total, data.total, 0);
                if (btn) {
                    btn.disabled = false;
                    btn.innerText = "Full Reindex";
                }
            }
        });
}

function closeSettings() {
    document.getElementById('settingsModal').style.display = 'none';
}

// Fonction de mise à jour visuelle (Cercle + Textes + ETA)
function updateScanStatus(data, isFast = false) {
    if (!data) return;

    const prefix = isFast ? "fast-" : "";
    const circle = document.getElementById(`${prefix}scan-circle`);
    const percentEl = document.getElementById(`${prefix}scan-percent`);
    const countEl = document.getElementById(`${prefix}scan-count`);
    const etaEl = document.getElementById(`${prefix}scan-eta`);

    const btnDeep = document.getElementById('btn-reindex');
    const btnFast = document.getElementById('btn-fast-reindex');

    // Gestion de l'interdépendance des boutons
    if (data.status === "running") {
        if (isFast) {
            if (btnDeep) btnDeep.disabled = true;
        } else {
            if (btnFast) btnFast.disabled = true;
        }
    } else if (data.status === "completed") {
        if (btnDeep) btnDeep.disabled = false;
        if (btnFast) btnFast.disabled = false;
    }

    // Si on est en cours de scan ou fini
    const current = data.current || 0;
    const total = data.total || 0;
    const speed = data.speed || 0;

    if (data.status === "completed") {
        if (percentEl) percentEl.innerText = "100";
        if (circle) circle.style.strokeDashoffset = 0;

        if (isFast) {
            // CACHER LE CERCLE ET ENTRER EN MODE BILAN LARGE
            const svg = document.getElementById('fast-scan-svg');
            const infoContainer = document.getElementById('fast-scan-info-container');
            const countElMore = document.getElementById('fast-scan-count');

            if (svg) svg.style.display = 'none';
            if (infoContainer) {
                // On passe en statique pour prendre toute la place
                infoContainer.style.position = 'relative';
                infoContainer.style.height = 'auto';
                infoContainer.style.minHeight = '180px';

                infoContainer.innerHTML = `
                        <div class="fast-scan-result">
                        <div class="result-header">SCAN TERMINÉ</div>
                        
                        <div class="result-main-stats">
                            <span>⏱ ${data.duration}</span>
                            <span>🚀 ${data.speed} t/s</span>
                        </div>

                        <div class="result-details">
                            <div class="detail-item"><span>📂 Shortlist (Dossiers vus)</span><span>${data.count_shortlist}</span></div>
                            <div class="detail-item"><span>🛠 Dossiers réindexés</span><span>${data.folders_updated}</span></div>
                            <div class="detail-item"><span>🎵 Pistes mises à jour</span><span>${data.tracks_updated}</span></div>
                            <div class="detail-item"><span>🧹 Pistes supprimées</span><span>${data.deleted || 0}</span></div>
                            <div class="detail-item"><span>📦 Volume total BDD</span><span>${data.total_db}</span></div>
                        </div>
                    </div >
        `;
            }
            if (countElMore) countElMore.innerText = `Complété le ${data.completed_at} `;
            if (etaEl) etaEl.style.display = 'none';
        } else {
            if (countEl) countEl.innerHTML = `Last: ${data.completed_at || 'Done'} <br>Duration: ${data.duration || '--'}`;
            if (etaEl) etaEl.innerText = `Avg: ${speed} f/s`;
        }
    } else {
        const percent = Math.round((current / total) * 100) || 0;
        const offset = 515.2 - (percent / 100 * 515.2);

        if (circle) circle.style.strokeDashoffset = offset;
        if (percentEl) percentEl.innerText = percent;

        if (isFast && data.folder) {
            if (countEl) countEl.innerText = `Checking: ${data.folder}`;
        } else {
            if (countEl) countEl.innerText = `${current} / ${total}`;
        }

        if (speed > 0 && current < total) {
            let sec = Math.floor((total - current) / speed);
            let m = Math.floor(sec / 60);
            let s = sec % 60;
            if (etaEl) etaEl.innerText = `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
        } else {
            if (etaEl) etaEl.innerText = isFast ? "..." : "00:00";
        }
    }
}

/**
 * ********************* LANCER FULL RÉ-INDEX *********************
 */
/**
 * ********************* LANCER FULL RÉ-INDEX *********************
 */
let activeReindexEventSource = null;

function startFullReindex() {
    if (activeReindexEventSource) {
        console.log("Full Reindex déjà en cours de suivi.");
        return;
    }

    const btn = document.getElementById('btn-reindex');
    const btnFast = document.getElementById('btn-fast-reindex');

    if (btn) {
        btn.disabled = true;
        btn.innerText = "Scanning...";
    }
    if (btnFast) btnFast.disabled = true;

    activeReindexEventSource = new EventSource(`${API_BASE_URL}/api/run_reindex`);

    activeReindexEventSource.onmessage = function (event) {
        try {
            const data = JSON.parse(event.data);
            if (data.done) {
                activeReindexEventSource.close();
                activeReindexEventSource = null;
                return;
            }
            if (data.current !== undefined) {
                updateScanStatus(data, false);
            }
        } catch (e) {
            console.log("Flux système :", event.data);
        }
    };

    activeReindexEventSource.onerror = function () {
        activeReindexEventSource.close();
        activeReindexEventSource = null;
        if (btn) {
            btn.disabled = false;
            btn.innerText = "Error - Retry";
        }
        if (btnFast) btnFast.disabled = false;
    };
}

/**
 * ********************* LANCER FAST RÉ-INDEX *********************
 */
let activeFastReindexEventSource = null;

function startFastReindex() {
    if (activeFastReindexEventSource) {
        console.log("Fast Reindex déjà en cours de suivi.");
        return;
    }

    const btnFast = document.getElementById('btn-fast-reindex');
    const btnDeep = document.getElementById('btn-reindex');

    if (btnFast) {
        btnFast.disabled = true;
        btnFast.innerText = "Updating...";
    }
    if (btnDeep) btnDeep.disabled = true;

    // RESET UI POUR UN NOUVEAU SCAN
    const svg = document.getElementById('fast-scan-svg');
    const infoContainer = document.getElementById('fast-scan-info-container');
    const etaEl = document.getElementById('fast-scan-eta');
    const countEl = document.getElementById('fast-scan-count');

    if (svg) svg.style.display = 'block';
    if (infoContainer) {
        infoContainer.style.position = 'absolute';
        infoContainer.style.height = 'auto'; // Reset
        infoContainer.style.minHeight = '0';
        infoContainer.innerHTML = `
        <span style="font-size: 2.5rem; font-weight: 100; color: white; letter-spacing: -2px;"><span
            id="fast-scan-percent">0</span><span
                style="font-size: 1rem; color: #ffffff; margin-left: 2px;">%</span></span>
        <span id="fast-scan-eta"
            style="font-size: 0.75rem; font-family: monospace; color: #ffffff; opacity: 0.8; margin-top: 5px;">00:00</span>
        `;
    }
    if (etaEl) {
        etaEl.style.display = 'block';
        etaEl.innerText = "00:00";
    }
    if (countEl) countEl.innerText = "Ready to Update";

    activeFastReindexEventSource = new EventSource(`${API_BASE_URL}/api/run_fast_reindex`);

    activeFastReindexEventSource.onmessage = function (event) {
        try {
            const data = JSON.parse(event.data);
            if (data.done) {
                activeFastReindexEventSource.close();
                activeFastReindexEventSource = null;
                if (btnFast) btnFast.innerText = "Fast Update";
                return;
            }
            if (data.current !== undefined) {
                updateScanStatus(data, true);
            }
        } catch (e) {
            console.log("Flux système (Fast) :", event.data);
        }
    };

    activeFastReindexEventSource.onerror = function () {
        activeFastReindexEventSource.close();
        activeFastReindexEventSource = null;
        if (btnFast) {
            btnFast.disabled = false;
            btnFast.innerText = "Error - Retry";
        }
        if (btnDeep) btnDeep.disabled = false;
    };
}

/**
 * ---------------------------------------------------------
 * INITIALISATION GLOBALE
 * ---------------------------------------------------------
 */
window.addEventListener("load", () => {
    initProgressBar();
    initPlaylistPanel();
    initVolumeControl();

    // --- Rétablir le bilan ou la progression Deep Reindex ---
    fetch(`${API_BASE_URL}/scan_status`)
        .then(res => res.json())
        .then(data => {
            if (data && data.status === "completed") {
                updateScanStatus(data, false);
            } else if (data && data.status === "running") {
                if (data.is_active) {
                    console.log("[SCAN] Reprise du suivi (Process actif)...");
                    startFullReindex();
                } else {
                    console.log("[SCAN] Statut stale détecté (Le process n'est plus là). Nettoyage affichage...");
                    // On affiche juste pour info, mais on ne relance pas
                    updateScanStatus(data, false);
                    const btn = document.getElementById('btn-reindex');
                    if (btn) { btn.disabled = false; btn.innerText = "Reindex Interrupted - Resume?"; }
                }
            }
        })
        .catch(err => console.error("Erreur récup status deep scan:", err));

    // --- Rétablir le bilan ou la progression Fast Reindex ---
    fetch(`${API_BASE_URL}/api/fast_scan_status`)
        .then(res => res.json())
        .then(data => {
            if (data && data.status === "completed") {
                updateScanStatus(data, true);
            } else if (data && data.status === "running") {
                if (data.is_active) {
                    console.log("[SCAN] Reprise du suivi Fast (Process actif)...");
                    startFastReindex();
                } else {
                    updateScanStatus(data, true);
                    const btnFast = document.getElementById('btn-fast-reindex');
                    if (btnFast) { btnFast.disabled = false; btnFast.innerText = "Fast Update (Interrupted)"; }
                }
            }
        })
        .catch(err => console.error("Erreur récup status fast scan:", err));

    switchMode('title');
});

/**
 * ---------------------------------------------------------
 *  EXPOSITION GLOBALE (pour les attributs onclick HTML)
 * ---------------------------------------------------------
 */
window.play = play;
window.stopMusic = stopMusic;
window.doSearch = doSearch;
window.changeVolume = changeVolume;
window.toggleMute = toggleMute;

let lastVolumeBeforeMute = 30;

function toggleMute() {
    const slider = document.getElementById("plVolumeSlider") || document.getElementById("volumeSlider");
    let currentVol = slider ? parseInt(slider.value, 10) : 50;

    if (currentVol > 0) {
        lastVolumeBeforeMute = currentVol;
        changeVolume(0);
    } else {
        changeVolume(lastVolumeBeforeMute || 30);
    }
}
window.togglePause = togglePause;
window.seek = seek;
window.playNext = playNext;
window.playPrevious = playPrevious;
window.promptSavePlaylist = promptSavePlaylist;
window.showLibrary = showLibrary;
window.loadSavedPlaylist = loadSavedPlaylist;
window.deleteSavedPlaylist = deleteSavedPlaylist;
window.createNewPlaylist = createNewPlaylist;
window.togglePlaylist = togglePlaylist;
window.addToPlaylist = addToPlaylist;
window.startFullReindex = startFullReindex;
window.startFastReindex = startFastReindex;
window.openCurrentAlbum = openCurrentAlbum;

async function openCurrentAlbum() {
    const albumEl = document.getElementById("trackAlbum");
    const artistEl = document.getElementById("trackArtist");

    if (!albumEl) return;
    const albumName = albumEl.innerText.trim();
    const artistName = artistEl ? artistEl.innerText.trim() : "";

    if (!albumName || albumName === "---" || albumName === "") return;

    const input = document.getElementById("searchInput");
    if (input) {
        input.value = albumName;
        // On switch de mode et on attend la fin de la recherche
        await switchMode('album');

        // On cherche la carte correspondante
        // On laisse un tout petit délai pour que le DOM se mette à jour si besoin, 
        // bien que await doSearch devrait suffire si renderNextBatch est synchrone.
        setTimeout(() => {
            const cards = document.querySelectorAll('.album-card-container');
            for (const card of cards) {
                const titleEl = card.querySelector('.song-title');
                const artistSubEl = card.querySelector('.song-subtext');

                const cardAlbum = titleEl ? titleEl.innerText.trim() : "";
                const cardArtist = artistSubEl ? artistSubEl.innerText.trim() : "";

                if (cardAlbum.toLowerCase() === albumName.toLowerCase()) {
                    if (cardArtist && artistName && artistName !== "---") {
                        if (cardArtist.toLowerCase() !== artistName.toLowerCase()) {
                            continue;
                        }
                    }

                    card.scrollIntoView({ behavior: 'smooth', block: 'center' });

                    const expandBtn = card.querySelector('.expand-icon');
                    const details = card.querySelector('.album-details');

                    if (expandBtn && details && details.style.display !== 'block') {
                        expandBtn.click();
                    }
                    break;
                }
            }
        }, 100);
    }
}

window.openCurrentArtist = openCurrentArtist;

async function openCurrentArtist() {
    const albumEl = document.getElementById("trackAlbum");
    const artistEl = document.getElementById("trackArtist");

    if (!artistEl) return;
    const artistName = artistEl.innerText.trim();
    const albumName = albumEl ? albumEl.innerText.trim() : "";

    if (!artistName || artistName === "---" || artistName === "") return;

    const input = document.getElementById("searchInput");
    if (input) {
        input.value = artistName;
        // On switch de mode et on attend la fin de la recherche
        await switchMode('artist');

        // On cherche la carte correspondante à l'album en cours
        setTimeout(() => {
            const cards = document.querySelectorAll('.album-card-container');
            for (const card of cards) {
                const titleEl = card.querySelector('.song-title'); // C'est le nom de l'album en mode group

                const cardAlbum = titleEl ? titleEl.innerText.trim() : "";

                // On cherche l'album spécifique dans la liste des albums de l'artiste
                if (cardAlbum.toLowerCase() === albumName.toLowerCase()) {
                    card.scrollIntoView({ behavior: 'smooth', block: 'center' });

                    const expandBtn = card.querySelector('.expand-icon');
                    const details = card.querySelector('.album-details');

                    if (expandBtn && details && details.style.display !== 'block') {
                        expandBtn.click();
                    }
                    break;
                }
            }
        }, 100);
    }
}