/* KTVDI views: navigation and shared page validation helpers. */
function nav() { document.querySelectorAll('[data-page]').forEach(b => b.classList.toggle('active', b.dataset.page === state.page)); document.getElementById('account').textContent = state.auth ? `<i data-lucide="user-round" aria-hidden="true"></i> ${state.auth.nama} · <i data-lucide="star" aria-hidden="true"></i> ${state.auth.points || 0} poin` : ''; document.getElementById('loginNav').textContent = state.auth ? 'Keluar' : 'Login'; document.getElementById('loginNav').classList.toggle('logout-nav', !!state.auth); document.getElementById('profileNav').hidden = !auth(); document.getElementById('adminNav').hidden = !(state.auth && state.auth.admin); }
function hasValidTransmitterCoordinates(row) { if (!row)
    return false; const rawLat = row.latitude, rawLon = row.longitude; if (rawLat === null || rawLat === undefined || rawLon === null || rawLon === undefined || String(rawLat).trim() === '' || String(rawLon).trim() === '')
    return false; const lat = Number(rawLat), lon = Number(rawLon); return Number.isFinite(lat) && Number.isFinite(lon) && lat >= -11 && lat <= 6 && lon >= 95 && lon <= 141; }

