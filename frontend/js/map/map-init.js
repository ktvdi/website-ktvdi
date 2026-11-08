/* Leaflet map setup, controls, GPS, and point editor map. */
'use strict';
function initMap() { const el = document.getElementById('map'); if (!el || !window.L)
    return; if (state.map) { try { state.map.off(); state.map.remove(); } catch (_) {} state.map = null; state.mapTerrainLayer = null; state.mapCoverageCircle = null; state.mapLayerControl = null; } state.map = L.map(el, { preferCanvas: true, fadeAnimation: true, markerZoomAnimation: true }).setView([-2.5, 118], 5); const street = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '© OpenStreetMap' }).addTo(state.map); const satellite = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', { maxZoom: 19, attribution: 'Tiles © Esri' }); const baseLayers = { 'Peta jalan': street, 'Satelit': satellite }; const overlays = {}; if (state.terrain?.image_data_uri && Array.isArray(state.terrain.bounds)) {
    const terrain = L.imageOverlay(state.terrain.image_data_uri, state.terrain.bounds, { opacity: .82, interactive: false });
    overlays['Prediksi terrain DEM'] = terrain;
    state.mapTerrainLayer = terrain;
    terrain.addTo(state.map);
    if (typeof addTerrainLegend === 'function') addTerrainLegend();
    state.map.fitBounds(state.terrain.bounds, { padding: [18, 18] });
} state.mapLayerControl = L.control.layers(baseLayers, overlays, { position: 'topright', collapsed: true }).addTo(state.map); L.control.scale({ metric: true, imperial: false, position: 'bottomleft' }).addTo(state.map); drawMapLayers(); if (!state.terrain && state.selected) {
    const r = state.rows.find(x => x.provinsi === state.selected.provinsi && x.wilayah === state.selected.wilayah && x.mux === state.selected.mux);
    if (hasValidTransmitterCoordinates(r))
        state.map.setView([mapViewerCoordinate(r.latitude), mapViewerCoordinate(r.longitude)], auth() ? 11 : 8);
} state.map.on('mousemove', ev => { const c = document.getElementById('mapCoordinates'); if (c)
    c.textContent = `Koordinat${auth() ? '' : ' (dibulatkan)'}: ${mapViewerCoordinateText(ev.latlng.lat)}, ${mapViewerCoordinateText(ev.latlng.lng)}`; }); const search = document.getElementById('mapSearchInput');
if (search) search.addEventListener('input', () => {
    state.mapSearch = search.value;
    drawMapLayers();
    const count = document.querySelector('.map-filter-summary strong');
    if (count) count.textContent = mapFilteredRows().length.toLocaleString('id-ID');
});
const prov = document.getElementById('mapProvinceFilter'), area = document.getElementById('mapAreaFilter'), mux = document.getElementById('mapMuxFilter'); if (prov)
    prov.addEventListener('change', () => { state.mapProvince = prov.value; state.mapArea = ''; state.mapMuxSelection = ''; state.selected = null; state.terrain = null; state.terrainRequestedKey = null; render(); }); if (area)
    area.addEventListener('change', () => { state.mapArea = area.value; state.mapMuxSelection = ''; state.selected = null; state.terrain = null; state.terrainRequestedKey = null; render(); }); if (mux)
    mux.addEventListener('change', () => { state.mapMuxSelection = mux.value; if (!mux.value)
        return; window.ktvdiSelect(mux.value, false); const marker = state.mapMarkerIndex[mux.value]; if (marker) {
        marker.openPopup();
        const ll = marker.getLatLng();
        state.map.setView(ll, auth() ? Math.max(11, state.map.getZoom()) : 8);
    } }); const locate = document.getElementById('mapLocate'); if (locate)
    locate.addEventListener('click', () => { if (!navigator.geolocation) {
        notice('Browser ini tidak mendukung GPS.');
        return;
    } locate.disabled = true; locate.textContent = '…'; navigator.geolocation.getCurrentPosition(pos => { const lat = pos.coords.latitude, lon = pos.coords.longitude, acc = pos.coords.accuracy; state.map.setView([lat, lon], Math.max(13, state.map.getZoom())); if (state.mapUserMarker)
        state.map.removeLayer(state.mapUserMarker); state.mapUserMarker = L.layerGroup().addTo(state.map); L.circle([lat, lon], { radius: acc, color: '#2563eb', fillOpacity: .08, weight: 1 }).addTo(state.mapUserMarker); L.marker([lat, lon]).addTo(state.mapUserMarker).bindPopup(`Lokasi saya<br>Akurasi ±${Math.round(acc)} m`).openPopup(); const c = document.getElementById('mapCoordinates'); if (c)
        c.textContent = `Lokasi GPS${auth() ? '' : ' (dibulatkan)'}: ${mapViewerCoordinateText(lat)}, ${mapViewerCoordinateText(lon)}${auth() ? ` · akurasi ±${Math.round(acc)} m` : ''}`; locate.disabled = false; locate.innerHTML = '<i data-lucide="crosshair" aria-hidden="true"></i>'; if (window.lucide) window.lucide.createIcons(); }, err => { notice(`GPS gagal: ${err.message}. Periksa izin lokasi browser dan koneksi HTTPS.`); locate.disabled = false; locate.innerHTML = '<i data-lucide="crosshair" aria-hidden="true"></i>'; if (window.lucide) window.lucide.createIcons(); }, { enableHighAccuracy: true, timeout: 15000, maximumAge: 30000 }); }); const reset = document.getElementById('resetMapFilters'); if (reset)
    reset.addEventListener('click', () => { state.mapProvince = ''; state.mapArea = ''; state.mapMuxSelection = ''; state.mapSearch = ''; state.selected = null; state.terrain = null; state.terrainRequestedKey = null; render(); }); if (state.selected) {
    const key = [state.selected.provinsi, state.selected.wilayah, state.selected.mux].join('|'), marker = state.mapMarkerIndex[key];
    if (marker)
        marker.openPopup();
} setTimeout(() => state.map.invalidateSize(), 180); }
function initPointMap() { const el = document.getElementById('pointMap'); if (!el || !window.L || !state.pointSelected)
    return; if (state.pointMap) {
    state.pointMap.remove();
    state.pointMap = null;
} const row = state.rows.find(r => [r.provinsi, r.wilayah, r.mux].join('|') === state.pointSelected); if (!row)
    return; const valid = hasValidTransmitterCoordinates(row); const center = valid ? [Number(row.latitude), Number(row.longitude)] : [-2.5, 118]; const map = L.map(el, { preferCanvas: true }).setView(center, valid ? 14 : 5); state.pointMap = map; const street = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '© OpenStreetMap' }).addTo(map); const satellite = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', { maxZoom: 19, attribution: 'Tiles © Esri' }); L.control.layers({ 'Peta jalan': street, 'Satelit': satellite }, null, { position: 'topright' }).addTo(map); if (valid)
    L.marker(center).addTo(map).bindPopup(`Koordinat tersimpan<br>${center[0].toFixed(6)}, ${center[1].toFixed(6)}`); const update = () => { const c = map.getCenter(), lat = c.lat.toFixed(6), lon = c.lng.toFixed(6); document.getElementById('pointLatitude').value = lat; document.getElementById('pointLongitude').value = lon; document.getElementById('pointCoordinates').textContent = `Koordinat tanda bidik: ${lat}, ${lon}`; }; map.on('move', update); map.on('moveend', update); update(); const gps = document.getElementById('pointGps'); if (gps)
    gps.addEventListener('click', () => { if (!navigator.geolocation) {
        notice('Browser tidak mendukung GPS.');
        return;
    } gps.disabled = true; gps.textContent = 'Mencari GPS…'; navigator.geolocation.getCurrentPosition(pos => { map.setView([pos.coords.latitude, pos.coords.longitude], 16); gps.disabled = false; gps.textContent = '<i data-lucide="target" aria-hidden="true"></i> Gunakan GPS saya'; }, err => { notice(`GPS gagal: ${err.message}`); gps.disabled = false; gps.textContent = '<i data-lucide="target" aria-hidden="true"></i> Gunakan GPS saya'; }, { enableHighAccuracy: true, timeout: 15000, maximumAge: 30000 }); }); setTimeout(() => map.invalidateSize(), 120); }
