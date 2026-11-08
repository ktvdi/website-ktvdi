/* Shared map helpers: coordinates, filtering, and map focus. */
'use strict';
/* KTVDI frontend maps: Leaflet maps and transmitter detail panels. */
'use strict';
function focusTransmitterMap() { setTimeout(() => { const target = document.querySelector('.map-container') || document.getElementById('map'); if (target)
    target.scrollIntoView({ behavior: 'auto', block: 'center' }); }, 100); }
function mapLocatedRows() { return state.rows.filter(r => hasValidTransmitterCoordinates(r)); }
function mapViewerCoordinate(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return n;
    return auth() ? n : Math.round(n * 100) / 100;
}
function mapViewerCoordinateText(value) {
    const n = Number(value);
    return Number.isFinite(n) ? mapViewerCoordinate(n).toFixed(2) : '—';
}
function mapViewerIdentity(item) {
    if (auth()) return item.display_name || item.username || 'Kontributor komunitas';
    return item.display_name || 'Kontributor komunitas';
}
function mapFilteredRows() {
    const query = String(state.mapSearch || '').trim().toLocaleLowerCase('id-ID');
    return mapLocatedRows().filter(r =>
        (!state.mapProvince || r.provinsi === state.mapProvince) &&
        (!state.mapArea || r.wilayah === state.mapArea) &&
        (!query || [r.provinsi, r.wilayah, r.mux, ...(r.siaran || [])]
            .some(value => String(value || '').toLocaleLowerCase('id-ID').includes(query)))
    );
}
