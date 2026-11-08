/* KTVDI frontend events: delegated UI events and Streamlit message lifecycle. */
'use strict';
// Global delegated navigation and forms.
document.addEventListener('click', e => { const coverage = e.target.closest('[data-coverage]'); if (coverage) {
    const [provinsi, wilayah, mux] = coverage.dataset.coverage.split('|');
    state.selected = { provinsi, wilayah, mux };
    state.mapMuxSelection = coverage.dataset.coverage;
    state.terrain = null;
    state.terrainRequestedKey = coverage.dataset.coverage;
    coverage.disabled = true;
    coverage.textContent = 'Menghitung…';
    coverage.classList.add('is-loading');
    notice('Menghitung prediksi coverage berdasarkan kontur terrain dan data pemancar…');
    send('calculate_terrain', state.selected);
    return;
} const showTechnical = e.target.closest('[data-show-technical]'); if (showTechnical) {
    const [provinsi, wilayah, mux] = showTechnical.dataset.showTechnical.split('|');
    state.selected = { provinsi, wilayah, mux };
    state.mapMuxSelection = showTechnical.dataset.showTechnical;
    state.detail = null;
    state.comments = [];
    state.measurements = [];
    showTechnical.disabled = true;
    showTechnical.textContent = 'Memuat data…';
    send('load_details', state.selected);
    return;
} const toggle = e.target.closest('[data-toggle-password]'); if (toggle) {
    const input = toggle.closest('.password-input-wrap')?.querySelector('input[name="password"]');
    if (input) {
        const visible = input.type === 'password';
        input.type = visible ? 'text' : 'password';
        toggle.setAttribute('aria-label', visible ? 'Sembunyikan password' : 'Tampilkan password');
        toggle.setAttribute('aria-pressed', String(visible));
        toggle.innerHTML = visible ? '<i data-lucide="eye-off" aria-hidden="true"></i>' : '<i data-lucide="eye" aria-hidden="true"></i>';
        if (window.lucide && typeof window.lucide.createIcons === 'function')
            window.lucide.createIcons();
    }
    return;
} const more = e.target.closest('[data-more]'); if (more) {
    const k = more.dataset.more;
    if (k === 'changes')
        state.changeLimit = (state.changeLimit || 10) + 10;
    else if (k === 'users')
        state.userLimit = (state.userLimit || 10) + 10;
    else if (k === 'leader')
        state.leaderLimit = (state.leaderLimit || 20) + 20;
    else if (k === 'reports')
        state.reportLimit = (state.reportLimit || 10) + 10;
    else if (k === 'logs')
        state.logLimit = (state.logLimit || 10) + 10;
    else if (k === 'measurements')
        state.measurementLimit = (state.measurementLimit || 5) + 5;
    else if (k === 'comments')
        state.commentLimit = (state.commentLimit || 5) + 5;
    render();
    if (state.page === 'map' && state.selected)
        detailsPanel();
    return;
} if (e.target.closest('#resetDatabaseFilters')) {
    state.databaseQuery = '';
    state.databaseProvince = '';
    state.databaseArea = '';
    state.databaseMux = '';
    state.databaseRequestTarget = null;
    render();
    return;
} const dbEdit = e.target.closest('[data-db-edit]'); if (dbEdit) {
    const [provinsi, wilayah, mux] = dbEdit.dataset.dbEdit.split('|');
    state.selected = { provinsi, wilayah, mux };
    state.page = 'edit';
    render();
    return;
} const dbDelete = e.target.closest('[data-db-delete]'); if (dbDelete) {
    const [provinsi, wilayah, mux] = dbDelete.dataset.dbDelete.split('|');
    state.selected = { provinsi, wilayah, mux };
    if (confirm('Hapus seluruh data MUX dan daftar kanal ini?'))
        send('delete_broadcast', state.selected);
    return;
} const dbRequest = e.target.closest('[data-db-request]'); if (dbRequest) {
    state.databaseRequestTarget = dbRequest.dataset.dbRequest;
    render();
    return;
} if (e.target.closest('#cancelDatabaseRequest')) {
    state.databaseRequestTarget = null;
    render();
    return;
} const dbApprove = e.target.closest('[data-db-approve]'); if (dbApprove) {
    const [provinsi, wilayah, mux, requester] = dbApprove.dataset.dbApprove.split('|');
    if (confirm('Setujui permohonan dan langsung terapkan daftar kanal yang diusulkan?'))
        send('approve_broadcast_edit_request', { provinsi, wilayah, mux, requester });
    return;
} const dbReject = e.target.closest('[data-db-reject]'); if (dbReject) {
    const [provinsi, wilayah, mux, requester] = dbReject.dataset.dbReject.split('|');
    if (confirm('Tolak permohonan perubahan kanal ini?'))
        send('reject_broadcast_edit_request', { provinsi, wilayah, mux, requester });
    return;
} const dbSelect = e.target.closest('[data-db-select]'); if (dbSelect) {
    const [provinsi, wilayah, mux] = dbSelect.dataset.dbSelect.split('|');
    state.selected = { provinsi, wilayah, mux };
    state.detail = null;
    state.comments = [];
    state.measurements = [];
    send('load_details', state.selected);
    return;
} const navEl = e.target.closest('[data-page]'); if (navEl) {
    e.preventDefault();
    const page = navEl.dataset.page;
    if (page === 'search') {
        state.page = 'database';
        render();
        return;
    }
    if (page === 'login' && auth()) {
        send('logout');
        return;
    }
    state.page = page;
    if (['community', 'leaderboard', 'profile'].includes(page) && auth())
        send('load_community');
    if (page === 'admin' && state.auth?.admin)
        send('load_admin');
    if (page === 'database' && auth())
        send('load_broadcast_edit_requests');
    if (page === 'map')
        send('load_measurements');
    if (page === 'addPoint' && auth()) {
        state.pointSelected = state.pointSelected || null;
        send('load_point_requests');
    }
    render();
    return;
} const approvePoint = e.target.closest('[data-point-approve]'); if (approvePoint) {
    const [sp, sw, sm] = (state.pointSelected || '').split('|');
    const provinsi = approvePoint.dataset.provinsi || sp, wilayah = approvePoint.dataset.wilayah || sw, mux = approvePoint.dataset.mux || sm;
    send('approve_point_change_request', { provinsi, wilayah, mux, requester: approvePoint.dataset.pointApprove });
    return;
} const rejectPoint = e.target.closest('[data-point-reject]'); if (rejectPoint) {
    const [sp, sw, sm] = (state.pointSelected || '').split('|');
    const provinsi = rejectPoint.dataset.provinsi || sp, wilayah = rejectPoint.dataset.wilayah || sw, mux = rejectPoint.dataset.mux || sm;
    if (confirm('Tolak permohonan perubahan titik ini?'))
        send('reject_point_change_request', { provinsi, wilayah, mux, requester: rejectPoint.dataset.pointReject });
    return;
} if (e.target.closest('[data-delete-point]')) {
    if (state.pointSelected && confirm('Hapus titik pemancar ini? Data MUX, kanal siaran, dan informasi teknis tidak akan dihapus.')) {
        const [provinsi, wilayah, mux] = state.pointSelected.split('|');
        send('delete_coordinates', { provinsi, wilayah, mux });
    }
    return;
} const managePoint = e.target.closest('[data-manage-point]'); if (managePoint) {
    state.pointSelected = managePoint.dataset.managePoint;
    state.page = 'addPoint';
    render();
    return;
} const sel = e.target.closest('[data-select]'); if (sel) {
    const [provinsi, wilayah, mux] = sel.dataset.select.split('|');
    state.selected = { provinsi, wilayah, mux };
    state.terrain = null;
    state.terrainRequestedKey = null;
    state.detail = null;
    state.comments = [];
    send('load_details', state.selected);
    return;
} const ed = e.target.closest('[data-edit]'); if (ed) {
    const [provinsi, wilayah, mux] = ed.dataset.edit.split('|');
    state.selected = { provinsi, wilayah, mux };
    state.page = 'edit';
    render();
    return;
} const restore = e.target.closest('[data-restore]'); if (restore && confirm('Pulihkan snapshot data ini?'))
    send('admin_restore', { log_id: restore.dataset.restore }); const user = e.target.closest('[data-user]'); if (user)
    send('load_user_profile', { username: user.dataset.user }); const delCoord = e.target.closest('[data-delete-coordinates]'); if (delCoord && state.selected && confirm('Hapus koordinat pemancar ini?'))
    send('delete_coordinates', state.selected); if (e.target.id === 'logout')
    send('logout'); if (e.target.id === 'deleteBroadcast' && confirm('Hapus data MUX ini?'))
    send('delete_broadcast', state.selected); });

