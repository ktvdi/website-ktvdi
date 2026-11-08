/* DEM terrain coverage overlay lifecycle. */
'use strict';

function addTerrainLegend() {
    if (!state.map || !window.L || !L.control) return;
    if (state.mapTerrainLegend) {
        state.map.removeControl(state.mapTerrainLegend);
        state.mapTerrainLegend = null;
    }
    const legend = L.control({ position: 'bottomright' });
    legend.onAdd = function () {
        const div = L.DomUtil.create('div', 'map-terrain-legend');
        div.innerHTML = '<strong>Prediksi kekuatan sinyal</strong>' +
            '<span><i class="weak"></i>Lemah (&lt; 6 dB)</span>' +
            '<span><i class="medium"></i>Sedang (6–15 dB)</span>' +
            '<span><i class="strong"></i>Kuat (15–25 dB)</span>' +
            '<span><i class="very-strong"></i>Sangat kuat (≥ 25 dB)</span>';
        L.DomEvent.disableClickPropagation(div);
        return div;
    };
    legend.addTo(state.map);
    state.mapTerrainLegend = legend;
}

window.ktvdiUpdateTerrain = function () {
    const resetCoverageButtons = () => document.querySelectorAll('[data-coverage]').forEach(button => {
        button.disabled = false;
        button.textContent = 'Lihat Coverage';
        button.classList.remove('is-loading');
    });
    const terrain = state.terrain;
    if (!state.map || !terrain || typeof terrain.image_data_uri !== 'string' ||
        !terrain.image_data_uri.startsWith('data:image/png;base64,') ||
        !Array.isArray(terrain.bounds) || terrain.bounds.length !== 2 ||
        !terrain.bounds.every(point => Array.isArray(point) && point.length === 2 && point.every(Number.isFinite)) ||
        !(terrain.bounds[0][0] < terrain.bounds[1][0] && terrain.bounds[0][1] < terrain.bounds[1][1])) {
        resetCoverageButtons();
        notice('Hasil coverage diterima, tetapi data gambar atau batas peta tidak valid. Silakan coba lagi.');
        return false;
    }
    if (!window.L || typeof L.imageOverlay !== 'function') {
        resetCoverageButtons();
        notice('Pustaka peta belum siap. Muat ulang halaman lalu coba kembali.');
        return false;
    }
    if (state.mapTerrainLayer) {
        try {
            if (state.mapLayerControl) state.mapLayerControl.removeLayer(state.mapTerrainLayer);
            if (state.map.hasLayer(state.mapTerrainLayer)) state.map.removeLayer(state.mapTerrainLayer);
        } catch (_) {}
    }
    const layer = L.imageOverlay(terrain.image_data_uri, terrain.bounds, { opacity: .82, interactive: false });
    state.mapTerrainLayer = layer;
    layer.once('error', () => {
        resetCoverageButtons();
        notice('Gambar prediksi gagal dimuat pada peta. Periksa data PNG dari backend.');
    });
    layer.once('load', resetCoverageButtons);
    layer.addTo(state.map);
    addTerrainLegend();
    if (state.mapLayerControl) state.mapLayerControl.addOverlay(layer, 'Prediksi terrain DEM');
    state.map.fitBounds(terrain.bounds, { padding: [18, 18], animate: true, duration: .45 });
    // Fallback jika event load tidak terpanggil oleh browser.
    window.setTimeout(resetCoverageButtons, 1200);
    return true;
};
