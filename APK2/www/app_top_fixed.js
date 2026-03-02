/**
 * ---------------------------------------------------------
 * CONFIGURATION APK & SERVEUR
 * ---------------------------------------------------------
 */
let API_BASE_URL = "";

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
(function initServerLogic() {
    apkLog("Initialisation de l'application...");
    const activeServer = localStorage.getItem("jukebox_active_server");
    const welcome = document.getElementById("welcomeScreen");

    if (activeServer) {
        if (welcome) welcome.style.display = "none";
        API_BASE_URL = activeServer.replace(/\/$/, ""); // Retirer le slash final
        apkLog("URL Active: " + API_BASE_URL);

        // Vérification de connexion
        fetch(`${API_BASE_URL}/ping`)
            .then(r => {
                if (r.ok) apkLog("Ping OK !");
                else apkLog("Ping Erreur: " + r.status);
            })
            .catch(e => {
                apkLog("Erreur Ping (Démarrage): " + e.message);
                // Si on a un écran vide au démarrage, on force un affichage de message d'erreur plus tard
            });
    } else {
        apkLog("Aucun serveur configuré au démarrage.");
        if (welcome) welcome.style.display = "flex";
    }
    renderServerList();
})();

// --- GESTION SETUP INITIAL (APK ONLY) ---
function setupInitialServer() {
    const input = document.getElementById("initialServerUrl");
    let url = input.value.trim();
    if (!url) {
        alert("Veuillez saisir une adresse valide.");
        return;
    }

    if (!url.startsWith("http")) {
        url = "http://" + url;
    }

    apkLog("Configuration du premier serveur: " + url);

    // On stocke et on active
    let servers = JSON.parse(localStorage.getItem("jukebox_servers") || "[]");
    if (!servers.includes(url)) {
        servers.push(url);
        localStorage.setItem("jukebox_servers", JSON.stringify(servers));
    }

    selectServer(url); // Reload
}
window.setupInitialServer = setupInitialServer;
