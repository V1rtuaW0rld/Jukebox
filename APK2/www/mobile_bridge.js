// WinJukeBox Mobile Bridge
// Handles server URL configuration and API call prefixing

(function () {
    const STORAGE_KEY = 'winjukebox_server_url';
    window.API_BASE_URL = localStorage.getItem(STORAGE_KEY) || '';

    // Function to check and show setup UI
    function checkSetup() {
        if (!window.API_BASE_URL) {
            showSetupModal();
        }
    }

    function showSetupModal() {
        // Create modal overlay if it doesn't exist
        let modal = document.getElementById('mobile-setup-modal');
        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'mobile-setup-modal';
            modal.style = `
                position: fixed;
                inset: 0;
                background: rgba(0,0,0,0.9);
                z-index: 99999;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                padding: 20px;
                font-family: sans-serif;
                color: white;
            `;
            modal.innerHTML = `
                <h1 style="color: #1DB954; margin-bottom: 30px;">Configuration Mobile</h1>
                <p style="text-align: center; margin-bottom: 20px; opacity: 0.8;">Entrez l'adresse de votre serveur WinJukeBox :</p>
                <input type="text" id="mobile-url-input" placeholder="http://192.168.0.7:8000" 
                    style="width: 100%; max-width: 300px; padding: 15px; border-radius: 10px; border: 1px solid #333; background: #222; color: white; margin-bottom: 20px; font-size: 16px;">
                <button id="mobile-save-btn" 
                    style="width: 100%; max-width: 300px; padding: 15px; border-radius: 30px; border: none; background: #1DB954; color: black; font-weight: bold; cursor: pointer; font-size: 16px;">
                    Se Connecter
                </button>
            `;
            document.body.appendChild(modal);

            document.getElementById('mobile-save-btn').onclick = function () {
                let url = document.getElementById('mobile-url-input').value.trim();
                if (url) {
                    // Normalize URL (ensure http:// and no trailing slash)
                    if (!url.startsWith('http')) url = 'http://' + url;
                    if (url.endsWith('/')) url = url.slice(0, -1);

                    localStorage.setItem(STORAGE_KEY, url);
                    window.API_BASE_URL = url;
                    modal.style.display = 'none';
                    location.reload(); // Reload to apply changes
                }
            };
        } else {
            modal.style.display = 'flex';
        }
    }

    // Helper for non-fetch URLs
    window.fixUrl = function (path) {
        if (!path || typeof path !== 'string' || path.startsWith('http') || path.startsWith('data:') || path.startsWith('blob:')) return path;
        const base = window.API_BASE_URL || '';
        if (!path.startsWith('/')) path = '/' + path;
        return base + path;
    };

    // Override fetch to automatically prepend API_BASE_URL if it starts with /
    const originalFetch = window.fetch;
    window.fetch = function (input, init) {
        if (typeof input === 'string' && input.startsWith('/') && window.API_BASE_URL) {
            input = window.API_BASE_URL + input;
        }
        return originalFetch(input, init);
    };

    // Override EventSource
    const originalEventSource = window.EventSource;
    window.EventSource = function (url, configuration) {
        if (typeof url === 'string' && url.startsWith('/') && window.API_BASE_URL) {
            url = window.API_BASE_URL + url;
        }
        return new originalEventSource(url, configuration);
    };
    window.EventSource.prototype = originalEventSource.prototype;

    // Add a way to reset the URL (e.g., from settings)
    window.resetServerUrl = function () {
        localStorage.removeItem(STORAGE_KEY);
        location.reload();
    };

    // Run check on load
    window.addEventListener('DOMContentLoaded', checkSetup);
})();
