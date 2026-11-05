window.addEventListener('message', e => { const d = e.data; if (!d || d.type !== 'streamlit:render')
    return; const a = d.args || {}; state.stats = a.stats || state.stats; state.rows = a.rows || state.rows; state.changes = a.changes || state.changes; state.provinces = a.provinces || state.provinces; state.mapLastUpdated = a.map_last_updated ?? state.mapLastUpdated; state.auth = a.auth || state.auth; state.result = a.result || null; if (state.result?.action === 'login' && state.result.ok) {
    state.auth = { username: state.result.username, nama: state.result.nama, points: state.result.points, admin: state.result.admin };
    state.page = 'beranda';
} if (state.result?.action === 'logout' && state.result.ok) {
    state.auth = null;
    state.page = 'beranda';
    state.selected = null;
    state.terrain = null;
} let showDetail = false, message = ''; if (state.result) {
    const r = state.result;
    if (r.stats)
        state.stats = r.stats;
    if (r.comments) {
        state.comments = r.comments;
        showDetail = true;
    }
    if (r.detail) {
        state.detail = r.detail;
        showDetail = true;
    }
    if (r.measurements) {
        state.measurements = r.measurements;
        showDetail = true;
    }
    if (r.terrain) {
        state.terrain = r.terrain;
        showDetail = true;
    }
    if (r.users) {
        state.users = r.users;
        state.profile = r.profile || state.profile;
    }
    if (r.user_profile) {
        state.viewedProfile = r.user_profile;
    }
    if (r.reports) {
        state.reports = r.reports;
        state.logs = r.logs || [];
    }
    if (r.point_requests) {
        state.pointRequests = r.point_requests;
    }
    if (r.broadcast_edit_requests) {
        state.broadcastEditRequests = r.broadcast_edit_requests;
    }
    if (r.ok && r.action === 'save_coordinates') {
        state.pointRequests = (state.pointRequests || []).filter(q => !(q.provinsi === state.pointSelected?.split('|')[0] && q.wilayah === state.pointSelected?.split('|')[1] && q.mux === state.pointSelected?.split('|')[2] && q.requester === state.auth?.username));
    }
    if (r.reply) {
        state.chat.push({ role: 'assistant', text: r.reply });
    }
    if (r.message)
        message = r.message;
    if (r.ok && r.action === 'delete_broadcast') {
        state.databaseMux = '';
        state.selected = null;
    }
    if (r.ok && ['submit_point_change_request', 'approve_point_change_request', 'reject_point_change_request'].includes(r.action)) {
        send('load_point_requests');
    }
    if (r.ok && ['submit_broadcast_edit_request', 'approve_broadcast_edit_request', 'reject_broadcast_edit_request'].includes(r.action)) {
        state.databaseRequestTarget = null;
        send('load_broadcast_edit_requests');
    }
    if (r.ok && ['add_broadcast', 'edit_broadcast', 'delete_broadcast', 'save_profile', 'add_comment', 'submit_report', 'admin_report_update', 'admin_restore', 'register_verify', 'forgot_reset', 'save_technical', 'save_coordinates', 'delete_coordinates', 'submit_measurement', 'calculate_terrain'].includes(r.action)) {
        send('refresh');
    }
} render(); if (showDetail && state.selected)
    detailsPanel(); if (message)
    notice(message); if (state.viewedProfile && state.page === 'community') {
    const c = document.getElementById('profileCard');
    if (c)
        c.innerHTML = profileCard(state.viewedProfile);
} if (state.page === 'map' && state.selected) {
    focusTransmitterMap();
    if (state.result?.action === 'load_details' && state.terrainAuto) {
        const selectedRow = state.rows.find(x => x.provinsi === state.selected.provinsi && x.wilayah === state.selected.wilayah && x.mux === state.selected.mux);
        const key = [state.selected.provinsi, state.selected.wilayah, state.selected.mux].join('|');
        if (hasValidTransmitterCoordinates(selectedRow) && /\bUHF\s*(2[1-9]|3[0-9]|4[0-8])\b/i.test(state.selected.mux) && state.terrainRequestedKey !== key) {
            state.terrainRequestedKey = key;
            notice('Menghitung prediksi terrain dari DEM MAPZEN…');
            send('calculate_terrain', state.selected);
        }
    }
} });

