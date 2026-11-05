/* KTVDI frontend core: shared state, Streamlit bridge, and common helpers. */
'use strict';
'use strict';
var state = { page: 'beranda', stats: {}, rows: [], changes: [], auth: null, result: null, provinces: [], selected: null, comments: [], users: [], reports: [], logs: [], profile: null, map: null, terrain: null, terrainAuto: true, terrainRequestedKey: null, measurements: [], chat: [], mapProvince: '', mapArea: '', mapMuxSelection: '', mapUserMarker: null, mapCoordinate: null, mapMarkerIndex: {}, pointSelected: null, pointMap: null, mapLastUpdated: null, pointRequests: [], databaseProvince: '', databaseArea: '', databaseMux: '', databaseQuery: '', broadcastEditRequests: [], databaseRequestTarget: null };
var app = document.getElementById('main');
var esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
var attr = s => esc(s).replace(/`/g, '&#96;');
var send = (action, data = {}) => window.parent.postMessage({ isStreamlitMessage: true, type: 'streamlit:setComponentValue', value: { action, ...data, event_id: Date.now().toString(36) + Math.random().toString(36).slice(2) } }, '*');
var height = () => {
    requestAnimationFrame(() => requestAnimationFrame(() => {
        const root = document.getElementById('app');
        if (!root)
            return;
        const rootRect = root.getBoundingClientRect();
        const rootStyle = getComputedStyle(root);
        const bottomPadding = parseFloat(rootStyle.paddingBottom) || 0;
        const contentBottom = Math.max(root.scrollHeight, rootRect.height);
        const h = Math.ceil(contentBottom - bottomPadding);
        window.parent.postMessage({ isStreamlitMessage: true, type: 'streamlit:setFrameHeight', height: Math.max(1, h) }, '*');
    }));
};
var auth = () => !!state.auth;
var requireLogin = () => { if (!auth()) {
    state.page = 'login';
    render();
    notice('Silakan login untuk menggunakan fitur ini.');
    return false;
} return true; };
var notice = t => { let n = document.getElementById('globalNotice'); if (!n) {
    n = document.createElement('div');
    n.id = 'globalNotice';
    n.className = 'notice';
    app.prepend(n);
} n.textContent = t; };
var statsHTML = () => `<div class="stats">${[['Provinsi dengan data', 'provinsi'], ['Wilayah layanan', 'wilayah'], ['MUX terdata', 'mux'], ['Nama kanal unik', 'kanal']].map(([l, k]) => `<div class="stat"><span>${l}</span><strong>${esc(state.stats[k] ?? '—')}</strong></div>`).join('')}</div>`;
var field = (label, name, placeholder = '', type = 'text', value = '') => `<label class="field">${label}<input name="${name}" type="${type}" placeholder="${attr(placeholder)}" value="${attr(value)}" required></label>`;
var options = (values, selected = '') => values.map(x => `<option value="${attr(x)}" ${x === selected ? 'selected' : ''}>${esc(x)}</option>`).join('');
var rowTitle = r => `${r.mux} — ${r.wilayah}, ${r.provinsi}`;

