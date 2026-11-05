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

    // Build account details with DOM nodes: account names must never be parsed as HTML.
    const account = document.getElementById('account');
    account.replaceChildren();
    if (state.auth) {
        const userIcon = document.createElement('i');
        userIcon.dataset.lucide = 'user-round';
        userIcon.setAttribute('aria-hidden', 'true');
        const userName = document.createElement('span');
        userName.textContent = state.auth.nama || state.auth.username || 'Pengguna';
        const separator = document.createElement('span');
        separator.textContent = '·';
        separator.setAttribute('aria-hidden', 'true');
        const pointsIcon = document.createElement('i');
        pointsIcon.dataset.lucide = 'star';
        pointsIcon.setAttribute('aria-hidden', 'true');
        const points = document.createElement('span');
        points.textContent = `${Number(state.auth.points) || 0} poin`;
        account.append(userIcon, userName, separator, pointsIcon, points);
    }
    const loginButton = document.getElementById('loginNav');
    loginButton.textContent = state.auth ? 'Keluar' : 'Login';
    loginButton.classList.toggle('logout-nav', !!state.auth);
    document.getElementById('profileNav').hidden = !auth();
    document.getElementById('adminNav').hidden = !(state.auth && state.auth.admin);
}
function hasValidTransmitterCoordinates(row) { if (!row)
    return false; const rawLat = row.latitude, rawLon = row.longitude; if (rawLat === null || rawLat === undefined || rawLon === null || rawLon === undefined || String(rawLat).trim() === '' || String(rawLon).trim() === '')
    return false; const lat = Number(rawLat), lon = Number(rawLon); return Number.isFinite(lat) && Number.isFinite(lon) && lat >= -11 && lat <= 6 && lon >= 95 && lon <= 141; }

