/* KTVDI views: navigation and shared page validation helpers. */
function nav() {
    document.querySelectorAll('[data-page]').forEach(el => {
        const active = el.dataset.page === state.page;
        el.classList.toggle('active', active);
        if (el.matches('button')) {
            if (active) el.setAttribute('aria-current', 'page');
            else el.removeAttribute('aria-current');
        }
    });
    const loginButton = document.getElementById('loginNav');
    loginButton.textContent = state.auth ? 'Keluar' : 'Login';
    loginButton.classList.toggle('logout-nav', !!state.auth);
    document.getElementById('profileNav').hidden = !auth();
    document.getElementById('adminNav').hidden = !(state.auth && state.auth.admin);
}
function hasValidTransmitterCoordinates(row) { if (!row)
    return false; const rawLat = row.latitude, rawLon = row.longitude; if (rawLat === null || rawLat === undefined || rawLon === null || rawLon === undefined || String(rawLat).trim() === '' || String(rawLon).trim() === '')
    return false; const lat = Number(rawLat), lon = Number(rawLon); return Number.isFinite(lat) && Number.isFinite(lon) && lat >= -11 && lat <= 6 && lon >= 95 && lon <= 141; }

