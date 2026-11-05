document.addEventListener('submit', e => { e.preventDefault(); const f = e.target, d = Object.fromEntries(new FormData(f).entries()); if (f.id === 'loginForm')
    send('login', d);
else if (f.id === 'terrainSimulationForm') {
    if (!state.selected) {
        notice('Pilih MUX bertitik terlebih dahulu.');
        return;
    }
    state.terrainRequestedKey = [state.selected.provinsi, state.selected.wilayah, state.selected.mux].join('|');
    send('calculate_terrain', { ...state.selected, erp_w: d.sim_erp_w, tx_height_m: d.sim_tx_height_m, rx_height_m: d.sim_rx_height_m, rx_threshold_dbm: d.sim_rx_threshold_dbm, extra_loss_db: d.sim_extra_loss_db });
}
else if (f.id === 'registerForm')
    send('register_request', d);
else if (f.id === 'registerVerify')
    send('register_verify', d);
else if (f.id === 'forgotRequest')
    send('forgot_request', d);
else if (f.id === 'forgotReset')
    send('forgot_reset', d);
else if (f.id === 'addForm')
    send('add_broadcast', d);
else if (f.id === 'pointCoordinateForm') {
    const [provinsi, wilayah, mux] = (state.pointSelected || '').split('|');
    send('save_coordinates', { ...d, provinsi, wilayah, mux });
}
else if (f.id === 'pointRequestForm') {
    const [provinsi, wilayah, mux] = (state.pointSelected || '').split('|');
    send('submit_point_change_request', { ...d, provinsi, wilayah, mux });
}
else if (f.id === 'editForm')
    send('edit_broadcast', { ...d, ...state.selected });
else if (f.id === 'databaseRequestForm') {
    if (!state.databaseRequestTarget) {
        notice('Pilih MUX terlebih dahulu.');
        return;
    }
    const [provinsi, wilayah, mux] = state.databaseRequestTarget.split('|');
    send('submit_broadcast_edit_request', { ...d, provinsi, wilayah, mux });
}
else if (f.id === 'profileForm')
    send('save_profile', d);
else if (f.id === 'commentForm')
    send('add_comment', { ...d, ...state.selected });
else if (f.id === 'technicalForm')
    send('save_technical', { ...d, ...state.selected });
else if (f.id === 'coordinateForm')
    send('save_coordinates', { ...d, ...state.selected });
else if (f.id === 'measurementForm')
    send('submit_measurement', { ...d, ...state.selected });
else if (f.id === 'reportForm') {
    const [provinsi, wilayah, mux] = (d.target || '').split('|');
    send('submit_report', { ...d, provinsi, wilayah, mux });
}
else if (f.id === 'chatForm') {
    state.chat.push({ role: 'user', text: d.message });
    render();
    send('chat', d);
}
else if (f.classList.contains('adminReport'))
    send('admin_report_update', { id: f.dataset.id, ...d }); });

