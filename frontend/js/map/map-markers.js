/* Transmitter and community measurement map layers. */
'use strict';

function addMeasurementBatch() {
    if (!state.map) return;
    if (state.mapMeasurements) state.map.removeLayer(state.mapMeasurements);
    state.mapMeasurements = L.layerGroup().addTo(state.map);
    const measurements = Array.isArray(state.measurements) ? state.measurements : [];
    measurements.forEach((item) => {
        const lat = Number(item.latitude), lon = Number(item.longitude);
        if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
        if (state.mapProvince && item.provinsi !== state.mapProvince) return;
        if (state.mapArea && item.wilayah !== state.mapArea) return;
        const strength = Math.max(0, Math.min(100, Number(item.strength) || 0));
        const color = strength >= 70 ? '#16a36a' : strength >= 40 ? '#d18b18' : '#d64b4b';
        const marker = L.circleMarker([lat, lon], {
            radius: 5, color, weight: 1.5, fillColor: color, fillOpacity: .72
        });
        const identity = mapViewerIdentity(item);
        marker.bindPopup(
            `<div class="transmitter-popup"><div class="popup-kicker">PENGUKURAN KOMUNITAS</div>`+
            `<b>${esc(item.mux || '—')}</b><div>${esc(item.wilayah || '—')}, ${esc(item.provinsi || '—')}</div>`+
            `<div>Strength: ${strength}% · Quality: ${Number(item.quality) || 0}%</div>`+
            `<small>${esc(identity)} · ${esc(item.timestamp || '')}</small></div>`
        );
        marker.addTo(state.mapMeasurements);
    });
}

function drawMapLayers() {
    if (!state.map) return;
    const map = state.map;
    if (state.mapDrawToken) state.mapDrawToken++;
    const drawToken = state.mapDrawToken = (state.mapDrawToken || 0) + 1;
    if (state.mapTransmitters) map.removeLayer(state.mapTransmitters);
    // Marker clustering keeps dense national views responsive. Fall back to
    // a plain layer group if the optional Leaflet plugin is unavailable.
    state.mapTransmitters = typeof L.markerClusterGroup === 'function'
        ? L.markerClusterGroup({
            chunkedLoading: true,
            chunkInterval: 120,
            chunkDelay: 30,
            showCoverageOnHover: false,
            spiderfyOnMaxZoom: true,
            disableClusteringAtZoom: 11,
            maxClusterRadius: 58
          }).addTo(map)
        : L.layerGroup().addTo(map);
    state.mapMarkerIndex = {};
    const rows = mapFilteredRows();
    const addMarkerBatch = (start) => {
        if (drawToken !== state.mapDrawToken || !state.map) return;
        const end = Math.min(start + 80, rows.length);
        for (let i = start; i < end; i++) {
            const r = rows[i];
            const key = [r.provinsi, r.wilayah, r.mux].join('|');
            const selected = state.selected && key === [state.selected.provinsi, state.selected.wilayah, state.selected.mux].join('|');
            const channels = (r.siaran || []).length ? (r.siaran || []).map(x => `<li>${esc(x)}</li>`).join('') : '<li>Belum ada data kanal</li>';
            const popup = `<div class="transmitter-popup"><div class="popup-kicker">INFORMASI PEMANCAR</div><b>Wilayah Layanan</b><div>${esc(r.wilayah || '—')}, ${esc(r.provinsi || '—')}</div><b>Nama MUX</b><div>${esc(r.mux || '—')}</div><b>Daftar Kanal</b><ul>${channels}</ul><button type="button" class="small-action" data-show-technical="${attr(key)}">Lihat Data Teknis</button></div>`;
            const marker = L.marker([mapViewerCoordinate(r.latitude), mapViewerCoordinate(r.longitude)], { title: rowTitle(r), alt: rowTitle(r), keyboard: true });
            marker.bindPopup(popup, { maxWidth: 1200 });
            marker.on('click', () => {
                const [provinsi, wilayah, mux] = key.split('|');
                state.selected = { provinsi, wilayah, mux };
                state.mapMuxSelection = key;
                const filter = document.getElementById('mapMuxFilter');
                if (filter) filter.value = key;
            });
            if (selected) marker.setZIndexOffset(1000);
            marker.addTo(state.mapTransmitters);
            state.mapMarkerIndex[key] = marker;
        }
        if (end < rows.length) requestAnimationFrame(() => addMarkerBatch(end));
        else addMeasurementBatch(0);
    };
    addMarkerBatch(0);
}

