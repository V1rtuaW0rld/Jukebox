/**
 * ---------------------------------------------------------
 *  GESTION DES PARAMÈTRES (SETTINGS)
 * ---------------------------------------------------------
 */
async function loadSettings() {
    try {
        const res = await fetch("/api/settings");
        const data = await res.json();

        const musicFolder = document.getElementById("conf_music_folder");
        const mbEmail = document.getElementById("conf_mb_email");
        const acoustidKey = document.getElementById("conf_acoustid_key");

        if (musicFolder) musicFolder.value = data.music_folder || "";
        if (mbEmail) mbEmail.value = data.musicbrainz_email || "";
        if (acoustidKey) acoustidKey.value = data.acoustid_api_key || "";

    } catch (e) {
        console.error("Erreur chargement settings:", e);
    }
}

async function saveSettings(event) {
    if (event) event.preventDefault();
    const msgDiv = document.getElementById("settingsMsg");
    if (msgDiv) {
        msgDiv.style.color = "#1db954";
        msgDiv.innerText = "Saving...";
    }

    const settings = {
        music_folder: document.getElementById("conf_music_folder").value,
        musicbrainz_email: document.getElementById("conf_mb_email").value,
        acoustid_api_key: document.getElementById("conf_acoustid_key").value
    };

    try {
        const res = await fetch("/api/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(settings)
        });

        if (res.ok) {
            if (msgDiv) {
                msgDiv.style.color = "#1db954";
                msgDiv.innerText = "Saved! (Updating env...)";
                setTimeout(() => {
                    msgDiv.innerText = "Settings saved! (Server updated)";
                }, 1000);
            }
        } else {
            console.error("Erreur save settings:", await res.text());
            if (msgDiv) {
                msgDiv.style.color = "red";
                msgDiv.innerText = "Error saving settings.";
            }
        }
    } catch (e) {
        console.error("Erreur sauvegarde:", e);
        if (msgDiv) {
            msgDiv.style.color = "red";
            msgDiv.innerText = "Network error.";
        }
    }
}

function openSettings() {
    const modal = document.getElementById("settingsModal");
    if (modal) {
        modal.style.display = "flex";
        loadSettings(); // Load data on open
    }
}

function closeSettings() {
    const modal = document.getElementById("settingsModal");
    if (modal) modal.style.display = "none";
}

// Expose globally
window.openSettings = openSettings;
window.closeSettings = closeSettings;
window.saveSettings = saveSettings;

// --- FOLDER PICKER ---

let fpCurrentPath = "";

function openFolderPicker() {
    const modal = document.getElementById("folderPickerModal");
    if (modal) modal.style.display = "flex";

    // Si un chemin est déjà saisi, on tente de l'ouvrir, sinon racine
    const currentInput = document.getElementById("conf_music_folder").value;
    loadFolderList(currentInput || "");
}

function closeFolderPicker() {
    const modal = document.getElementById("folderPickerModal");
    if (modal) modal.style.display = "none";
}

async function loadFolderList(path) {
    try {
        const encodedPath = encodeURIComponent(path);
        const res = await fetch(`/api/browse?path=${encodedPath}`);
        const data = await res.json();

        if (data.error) {
            console.warn("FolderPicker Error:", data.error);
            // Si le chemin n'existe pas, on charge la racine
            if (path !== "") loadFolderList("");
            return;
        }

        fpCurrentPath = data.current;
        const displayPath = document.getElementById("fpCurrentPath");
        if (displayPath) {
            // Affichage intelligent : si drive, on affiche "PC", sinon le chemin
            displayPath.innerText = fpCurrentPath || (data.folders.length > 0 && data.folders[0].is_drive ? "PC (Racine)" : "Racine");
            displayPath.title = fpCurrentPath; // Tooltip avec chemin complet
        }

        // Gestion bouton Parent
        const btnUp = document.getElementById("btnFpUp");
        if (btnUp) {
            btnUp.disabled = (data.parent === fpCurrentPath);
            btnUp.onclick = () => loadFolderList(data.parent);
        }

        const list = document.getElementById("fpFolderList");
        if (list) {
            list.innerHTML = "";

            data.folders.forEach(folder => {
                const div = document.createElement("div");
                div.style.padding = "10px 12px";
                div.style.cursor = "pointer";
                div.style.borderBottom = "1px solid #333";
                div.style.color = "#eee";
                div.style.display = "flex";
                div.style.alignItems = "center";
                div.style.gap = "12px";
                div.style.borderRadius = "4px";
                div.style.transition = "background 0.2s";

                // Icon
                const icon = folder.is_drive ? "💾" : "📁";

                div.innerHTML = `
                    <span style="font-size: 1.2em;">${icon}</span> 
                    <span style="font-weight: 500;">${folder.name}</span>
                `;

                // Events
                div.onmouseover = () => div.style.background = "#333";
                div.onmouseout = () => div.style.background = "transparent";
                div.onclick = () => loadFolderList(folder.path);

                list.appendChild(div);
            });

            if (data.folders.length === 0) {
                list.innerHTML = `<div style="padding: 20px; text-align: center; color: #666; font-style: italic;">Dossier vide</div>`;
            }
        }

    } catch (e) {
        console.error("Erreur FolderPicker:", e);
    }
}

function fpGoUp() {
    // Cette fonction est attachée dynamiquement dans loadFolderList
    // Mais on la garde pour référence si besoin
}

function selectCurrentFolder() {
    if (fpCurrentPath) {
        const input = document.getElementById("conf_music_folder");
        if (input) {
            input.value = fpCurrentPath;
            // Petit effet visuel pour confirmer
            input.style.borderColor = "#1DB954";
            setTimeout(() => input.style.borderColor = "rgba(255,255,255,0.1)", 1000);
        }
        closeFolderPicker();
    }
}

// Expose Folder Picker globally
window.openFolderPicker = openFolderPicker;
window.closeFolderPicker = closeFolderPicker;
window.selectCurrentFolder = selectCurrentFolder;
window.fpGoUp = fpGoUp;
