/* KTVDI views: page rendering dispatcher and page templates. */
'use strict';

function terrainSimulationDefaults(row) {
    const detail = row?.detail || {};
    const positive = value => {
        const n = Number(value);
        return Number.isFinite(n) && n > 0 ? n : null;
    };
    const finite = value => {
        if (value === null || value === undefined || String(value).trim() === '') return null;
        const n = Number(value);
        return Number.isFinite(n) ? n : null;
    };
    const actualErp = positive(detail.erp_w);
    const txPower = positive(detail.tx_power_w);
    const gain = finite(detail.antenna_gain_dbd);
    const feeder = finite(detail.feeder_loss_db);
    const txHeight = positive(detail.tx_height_m);
    let erp = actualErp;
    let erpSource = actualErp ? 'data teknis aktual' : 'asumsi';
    if (!erp && txPower) {
        erp = txPower * Math.pow(10, ((gain ?? 10) - (feeder ?? 2)) / 10);
        erpSource = gain !== null && feeder !== null
            ? 'estimasi dari data teknis pemancar'
            : 'estimasi; gain/rugi feeder sebagian diasumsikan';
    }
    return {
        erp: erp ?? 1000, erpSource,
        txHeight: txHeight ?? 30,
        txHeightSource: txHeight ? 'data teknis aktual' : 'asumsi',
        rxHeight: 10, rxThreshold: -90, extraLoss: 4
    };
}

function render() {
    nav();
    if (state.map) {
        state.map.remove();
        state.map = null;
    }
    if (state.pointMap) {
        state.pointMap.remove();
        state.pointMap = null;
    }
    if (state.page === 'beranda')
        app.innerHTML = renderHomePage();
    else if (state.page === 'database')
        app.innerHTML = databasePage();
    else if (state.page === 'statistics')
        app.innerHTML = renderStatisticsPage();
    else if (state.page === 'notifications')
        app.innerHTML = renderNotificationsPage();
    else if (state.page === 'map') {
        const located = mapLocatedRows();
        const provinces = [...new Set(located.map(r => r.provinsi).filter(Boolean))].sort();
        const areas = [...new Set(located.filter(r => (!state.mapProvince || r.provinsi === state.mapProvince)).map(r => r.wilayah).filter(Boolean))].sort();
        const muxRows = located.filter(r => (!state.mapProvince || r.provinsi === state.mapProvince) && (!state.mapArea || r.wilayah === state.mapArea));
        const muxOptions = muxRows.map(r => ({ value: [r.provinsi, r.wilayah, r.mux].join('|'), label: r.mux }));
        const selectedRow = state.selected ? (located.find(r => r.provinsi === state.selected.provinsi && r.wilayah === state.selected.wilayah && r.mux === state.selected.mux) || {}) : {};
        const simDefaults = terrainSimulationDefaults({ ...selectedRow, detail: state.detail || selectedRow.detail || {} });
        const simErpLabel = !auth() ? `ERP simulasi (W) · ${simDefaults.erpSource}` : 'ERP simulasi (W)';
        const simTxLabel = !auth() ? `Tinggi antena TX simulasi (m) · ${simDefaults.txHeightSource}` : 'Tinggi antena TX simulasi (m)';
        const simOtherSource = !auth() ? 'asumsi' : '';
        app.innerHTML = `<section class="panel map-panel"><h2><i data-lucide="map" aria-hidden="true"></i> Peta Pemancar & Kualitas Sinyal TV Digital</h2><p class="muted">Pilih Provinsi dan Wilayah Layanan, lalu pilih MUX bertitik. Prediksi terrain akan dihitung otomatis menggunakan data teknis yang tersedia. Gunakan form simulasi hanya jika ingin mengubah parameter dan menghitung ulang. Marker peta hanya menampilkan informasi pemancar.</p><div class="map-filterbar"><label>Provinsi<select id="mapProvinceFilter"><option value="">Semua provinsi</option>${options(provinces, state.mapProvince)}</select></label><label>Wilayah Layanan<select id="mapAreaFilter"><option value="">Semua wilayah</option>${options(areas, state.mapArea)}</select></label><label>Pilih MUX bertitik<select id="mapMuxFilter"><option value="">Pilih MUX pemancar</option>${muxOptions.map(o => `<option value="${attr(o.value)}" ${o.value === state.mapMuxSelection ? 'selected' : ''}>${esc(o.label)}</option>`).join('')}</select></label><button type="button" class="small-action" id="resetMapFilters">Reset filter</button></div><div class="map-container"><div id="map" style="height:600px;border-radius:14px;z-index:1"></div><button type="button" class="map-gps-button" id="mapLocate" title="Lokasi saya" aria-label="Lokasi saya"><i data-lucide="crosshair" aria-hidden="true"></i></button></div><div class="map-status"><span id="mapCount"></span><span id="mapCoordinates">Koordinat: —</span></div><div id="mapLastUpdated" class="map-last-updated">Update titik pemancar terakhir: ${esc(state.mapLastUpdated || "Belum ada riwayat perubahan")}</div><p class="muted map-disclaimer">GPS memerlukan izin lokasi browser dan HTTPS. Prediksi terrain merupakan estimasi berbasis DEM, bukan jaminan penerimaan siaran.</p><section class="terrain-simulation"><h3><i data-lucide="compass" aria-hidden="true"></i> Form Simulasi Prediksi Terrain</h3><p class="muted">Prediksi terrain otomatis menggunakan data teknis pemancar yang tersimpan (atau nilai asumsi jika belum tersedia). Ubah parameter di bawah hanya jika ingin mencoba simulasi alternatif. Nilai simulasi tidak disimpan ke database.</p><form id="terrainSimulationForm" class="simulation-grid">${field(simErpLabel, 'sim_erp_w', 'Default dari data/asumsi', 'number', String(simDefaults.erp))}${field(simTxLabel, 'sim_tx_height_m', 'Contoh 30', 'number', String(simDefaults.txHeight))}${field(`Tinggi antena penerima (m)${simOtherSource ? ' · asumsi' : ''}`, 'sim_rx_height_m', 'Contoh 10', 'number', String(simDefaults.rxHeight))}${field(`Ambang penerimaan (dBm)${simOtherSource ? ' · asumsi' : ''}`, 'sim_rx_threshold_dbm', 'Contoh -90', 'number', String(simDefaults.rxThreshold))}${field(`Rugi tambahan (dB)${simOtherSource ? ' · asumsi' : ''}`, 'sim_extra_loss_db', 'Contoh 4', 'number', String(simDefaults.extraLoss))}<button class="action" type="submit" ${state.selected ? '' : 'disabled'}>Terapkan simulasi & hitung ulang</button></form><p id="terrainSimulationStatus" class="muted">${state.selected ? (state.terrain ? 'Prediksi otomatis selesai. Ubah parameter jika ingin menghitung simulasi alternatif.' : 'Prediksi otomatis sedang diproses atau menunggu hasil.') : 'Pilih MUX pada daftar di atas; prediksi terrain akan berjalan otomatis.'}</p>${state.terrain ? `<div class="result"><b>Hasil prediksi:</b> ${esc(state.terrain.min_dbm ?? '—')} hingga ${esc(state.terrain.max_dbm ?? '—')} dBm · ${esc(state.terrain.prediction_data_status || 'Estimasi')}</div>` : ''}</section></section>`;
    }
    else if (state.page === 'login')
        app.innerHTML = renderLoginPage();
    else if (state.page === 'register')
        app.innerHTML = renderRegisterPage();
    else if (state.page === 'forgot')
        app.innerHTML = renderForgotPage();
    else if (state.page === 'addPoint') {
        if (!auth()) {
            app.innerHTML = `<section class="panel form"><h2><i data-lucide="map-pin" aria-hidden="true"></i> Kelola Titik Pemancar</h2><p>Login diperlukan untuk menambahkan titik atau mengajukan perubahan titik.</p><button data-page="login" class="action">Login / Daftar Akun</button></section>`;
        }
        else {
            const rows = [...state.rows].sort((a, b) => `${a.provinsi}/${a.wilayah}/${a.mux}`.localeCompare(`${b.provinsi}/${b.wilayah}/${b.mux}`));
            if (!state.pointSelected || !rows.some(r => [r.provinsi, r.wilayah, r.mux].join('|') === state.pointSelected))
                state.pointSelected = (rows.find(r => !hasValidTransmitterCoordinates(r)) || rows[0]) ? [((rows.find(r => !hasValidTransmitterCoordinates(r)) || rows[0]).provinsi), ((rows.find(r => !hasValidTransmitterCoordinates(r)) || rows[0]).wilayah), ((rows.find(r => !hasValidTransmitterCoordinates(r)) || rows[0]).mux)].join('|') : null;
            const chosen = rows.find(r => [r.provinsi, r.wilayah, r.mux].join('|') === state.pointSelected);
            const hasCoords = chosen && hasValidTransmitterCoordinates(chosen);
            const isAdmin = !!state.auth?.admin;
            const pointOwner = chosen?.point_added_by_username || '';
            const isCreator = !!pointOwner && pointOwner === state.auth?.username;
            const canManagePoint = isAdmin || isCreator;
            const pendingForChosen = (state.pointRequests || []).filter(q => q.provinsi === chosen?.provinsi && q.wilayah === chosen?.wilayah && q.mux === chosen?.mux);
            const ownPending = pendingForChosen.find(q => q.requester === state.auth?.username && q.status === 'Menunggu');
            const ownApproved = pendingForChosen.find(q => q.requester === state.auth?.username && q.status === 'Disetujui');
            const reviewable = pendingForChosen.filter(q => q.status === 'Menunggu' && (isAdmin || (pointOwner && pointOwner === state.auth?.username)));
            const reviewableAll = (state.pointRequests || []).filter(q => q.status === 'Menunggu' && (isAdmin || (q.point_added_by_username && q.point_added_by_username === state.auth?.username)));
            const approvalInbox = reviewableAll.length ? `<section class="result"><h3>${isAdmin ? 'Kotak Masuk Persetujuan Admin' : 'Permohonan untuk titik yang Anda buat'}</h3><p class="muted">Semua permohonan yang dapat Anda putuskan, tidak bergantung pada titik yang sedang dipilih.</p>${reviewableAll.map(q => `<article class="result"><b>${esc(q.requester_name || q.requester)}</b><p><b>${esc(q.mux || '')}</b> — ${esc(q.wilayah || '')}, ${esc(q.provinsi || '')}</p><p>${esc(q.reason || '')}</p><small>${esc(q.requested_at || '')}</small><div class="map-toolbar"><button type="button" class="small-action" data-point-approve="${attr(q.requester)}" data-provinsi="${attr(q.provinsi)}" data-wilayah="${attr(q.wilayah)}" data-mux="${attr(q.mux)}">Setujui</button><button type="button" class="small-action danger" data-point-reject="${attr(q.requester)}" data-provinsi="${attr(q.provinsi)}" data-wilayah="${attr(q.wilayah)}" data-mux="${attr(q.mux)}">Tolak</button></div></article>`).join('')}</section>` : `<section class="result"><h3>${isAdmin ? 'Kotak Masuk Persetujuan Admin' : 'Permohonan untuk titik yang Anda buat'}</h3><p class="muted">Belum ada permohonan yang menunggu persetujuan Anda.</p></section>`;
            app.innerHTML = `<section class="panel form"><h2><i data-lucide="map-pin" aria-hidden="true"></i> Kelola Titik Pemancar</h2>
${approvalInbox}
<p class="muted">Pengelolaan titik terpisah dari kepemilikan MUX. Pembuat titik dapat mengubah titiknya langsung. Pengguna lain dapat mengajukan perubahan; untuk titik yang memiliki pembuat, permohonan dapat disetujui admin dan/atau pembuat titik. Untuk titik lama tanpa identitas pembuat, persetujuan admin wajib.</p>
${rows.length ? `<label class="field">Pilih pemancar<select id="pointTargetSelect">${rows.map(r => { const k = [r.provinsi, r.wilayah, r.mux].join('|'), valid = hasValidTransmitterCoordinates(r); return `<option value="${attr(k)}" ${k === state.pointSelected ? 'selected' : ''}>${esc(rowTitle(r))} — ${valid ? 'sudah memiliki titik' : 'belum memiliki titik'}</option>`; }).join('')}</select></label>
<div class="result"><b>${esc(chosen?.mux || '')}</b><div>${esc(chosen?.wilayah || '')}, ${esc(chosen?.provinsi || '')}</div>
${hasCoords ? `<p>Koordinat tersimpan: ${Number(chosen.latitude).toFixed(6)}, ${Number(chosen.longitude).toFixed(6)}</p><p>Pembuat titik: ${esc(chosen.point_added_by_name || pointOwner || 'Belum diketahui (data lama)')}</p><p>Status hak: ${canManagePoint ? 'Anda dapat mengelola titik ini.' : pointOwner ? 'Perubahan memerlukan persetujuan admin dan/atau pembuat titik.' : 'Pembuat belum diketahui; perubahan hanya dapat disetujui admin.'}</p>` : '<p>Titik belum tersedia. Pengguna yang login dapat menambahkan titik baru; identitas pembuat akan dicatat otomatis.</p>'}</div>
<div class="map-toolbar"><button type="button" class="small-action" id="pointGps"><i data-lucide="target" aria-hidden="true"></i> Gunakan GPS saya</button><span class="muted">Geser peta, gunakan zoom, dan posisikan tanda bidik pada lokasi pemancar.</span></div>
<div id="pointMap" style="height:560px;border-radius:14px;z-index:1"><div class="map-crosshair">⊕</div></div><p id="pointCoordinates" class="muted">Koordinat tanda bidik: —</p>
${!hasCoords || canManagePoint || ownApproved ? `<form id="pointCoordinateForm"><input type="hidden" name="latitude" id="pointLatitude"><input type="hidden" name="longitude" id="pointLongitude"><button class="action">${hasCoords ? '<i data-lucide="save" aria-hidden="true"></i> Simpan perubahan titik' : '<i data-lucide="map-pin" aria-hidden="true"></i> Tambahkan titik pemancar'}</button></form>` : ''}
${hasCoords && !canManagePoint ? `${ownApproved ? `<div class="result"><b>Permohonan disetujui.</b><p>Anda dapat mengatur posisi pada peta dan menyimpan satu kali perubahan yang telah disetujui.</p></div>` : ownPending ? `<div class="result"><b>Permohonan Anda sedang menunggu persetujuan.</b><p>${esc(ownPending.reason || '')}</p><small>${esc(ownPending.requested_at || '')}</small></div>` : `<form id="pointRequestForm" class="field"><h3>Ajukan perubahan titik</h3><label class="field">Alasan perubahan<textarea name="reason" required minlength="10" maxlength="1000" placeholder="Jelaskan mengapa koordinat perlu diperbarui dan sertakan dasar informasinya."></textarea></label><button class="action">Kirim permohonan persetujuan</button></form>`}` : ''}
${hasCoords && canManagePoint ? `<button type="button" class="danger" data-delete-point title="Menghapus titik saja, bukan data MUX"><i data-lucide="trash-2" aria-hidden="true"></i> Hapus titik pemancar</button>` : ''}
${reviewable.length ? `<section class="result"><h3>Permohonan yang menunggu persetujuan</h3>${reviewable.map(q => `<article class="result"><b>${esc(q.requester_name || q.requester)}</b><p>${esc(q.reason || '')}</p><small>${esc(q.requested_at || '')}</small><div class="map-toolbar"><button type="button" class="small-action" data-point-approve="${attr(q.requester)}">Setujui</button><button type="button" class="small-action danger" data-point-reject="${attr(q.requester)}">Tolak</button></div></article>`).join('')}</section>` : ''}
` : '<p>Belum ada data pemancar. Tambahkan data siaran terlebih dahulu.</p>'}</section>`;
            if (chosen && rows.length)
                setTimeout(initPointMap, 50);
        }
    }
    else if (state.page === 'add')
        app.innerHTML = renderAddBroadcastPage();
    else if (state.page === 'edit')
        app.innerHTML = editPage();
    else if (state.page === 'report')
        app.innerHTML = renderReportPage();
    else if (state.page === 'community')
        app.innerHTML = renderCommunityPage();
    else if (state.page === 'leaderboard')
        app.innerHTML = renderLeaderboardPage();
    else if (state.page === 'profile')
        app.innerHTML = profilePage();
    else if (state.page === 'admin')
        app.innerHTML = adminPage();
    else if (state.page === 'chat')
        app.innerHTML = renderChatPage();
    height();
    if (window.lucide && typeof window.lucide.createIcons === 'function')
        window.lucide.createIcons();
    if (state.page === 'map')
        initMap();
}

