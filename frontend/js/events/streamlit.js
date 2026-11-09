window.addEventListener('message', e => { const d = e.data; if (!d || d.type !== 'streamlit:render')
    return; const a = d.args || {};
    // Restore only after Streamlit has delivered the initial render to this component.
// Sending setComponentValue before this handshake can be dropped on a cold reload.
if (!window.__ktvdiRestoreRequested) {
    window.__ktvdiRestoreRequested = true;
    try {
        const savedToken = window.localStorage.getItem('ktvdi_persistent_session');
        if (savedToken) send('restore_session', { token: savedToken });
    } catch (_) {
        // Browser storage may be unavailable in private/restricted contexts.
    }
}
 state.stats = a.stats || state.stats; state.rows = a.rows || state.rows; state.changes = a.changes || state.changes; state.provinces = a.provinces || state.provinces; state.mapLastUpdated = a.map_last_updated ?? state.mapLastUpdated; state.auth = a.auth || state.auth; state.result = a.result || null;
    if (state.result?.action === 'login' && state.result.ok && state.result.persistent_token) {
        try { window.localStorage.setItem('ktvdi_persistent_session', state.result.persistent_token); } catch (_) {}
    }
    if (state.result?.clear_persistent_token || state.result?.action === 'logout') {
        try { window.localStorage.removeItem('ktvdi_persistent_session'); } catch (_) {}
    }
    if (state.result?.action === 'restore_session') {
        if (state.result.ok && state.result.auth) {
            state.auth = state.result.auth;
            state.page = 'beranda';
        } else {
            state.auth = null;
        }
    }
    if (state.result?.action === 'login' && state.result.ok) {
    state.auth = { username: state.result.username, nama: state.result.nama, points: state.result.points, admin: state.result.admin };
    state.page = 'beranda';
} if (state.result?.action === 'logout' && state.result.ok) {
    state.auth = null;
    state.page = 'beranda';
    state.selected = null;
    state.terrain = null;
} let showDetail = false, message = ''; if (state.result) {
    const r = state.result;
    // API payloads use distinct public/authenticated envelopes. Normalize only
    // for the existing view layer; filtering already happened on the server.
    const rolePayload = r.public_data || r.authenticated_data;
    if (rolePayload && typeof rolePayload === 'object') Object.assign(r, rolePayload);
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
    if (r.action === 'calculate_terrain') {
        if (r.ok && r.terrain) {
            state.terrain = r.terrain;
            state.terrainRequestedKey = [state.selected?.provinsi, state.selected?.wilayah, state.selected?.mux].join('|');
        } else {
            state.terrain = null;
        }
    }
    if (r.measurements) {
        state.measurements = r.measurements;
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
    if (r.ok && ['add_broadcast', 'edit_broadcast', 'delete_broadcast', 'save_profile', 'add_comment', 'submit_report', 'admin_report_update', 'admin_restore', 'register_verify', 'forgot_reset', 'save_technical', 'save_coordinates', 'delete_coordinates', 'submit_measurement'].includes(r.action)) {
        send('refresh');
    }
} const keepMapForSelection = state.page === 'map' && state.result?.action === 'load_details' && !!state.map; const keepMapForCoverage = state.page === 'map' && state.result?.action === 'calculate_terrain' && !!state.map; if (!keepMapForSelection && !keepMapForCoverage) render(); if (keepMapForCoverage) { if (state.result?.ok && state.terrain && typeof window.ktvdiUpdateTerrain === 'function') window.ktvdiUpdateTerrain(); else { document.querySelectorAll('[data-coverage]').forEach(button => { button.disabled = false; button.dataset.coverageBusy = '0'; button.textContent = 'Lihat Coverage'; button.classList.remove('is-loading'); }); } } if (state.page === 'map' && showDetail && state.selected && !keepMapForCoverage) detailsPanel(); if (message)
    notice(message); if (state.viewedProfile && state.page === 'community') {
    const c = document.getElementById('profileCard');
    if (c)
        c.innerHTML = profileCard(state.viewedProfile);
} if (state.page === 'map' && state.selected && !keepMapForSelection) focusTransmitterMap(); });

