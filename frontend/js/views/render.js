/* KTVDI views: page rendering dispatcher and page templates. */
'use strict';

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
        const located = state.rows.filter(r => hasValidTransmitterCoordinates(r));
        const provinces = [...new Set(located.map(r => r.provinsi).filter(Boolean))].sort((a,b) => a.localeCompare(b, 'id'));
        const areas = [...new Set(located.filter(r => !state.mapProvince || r.provinsi === state.mapProvince).map(r => r.wilayah).filter(Boolean))].sort((a,b) => a.localeCompare(b, 'id'));
        const searchTerm = String(state.mapSearch || '').trim().toLocaleLowerCase('id-ID');
        const filtered = located.filter(r => (!state.mapProvince || r.provinsi === state.mapProvince) && (!state.mapArea || r.wilayah === state.mapArea) &&
          (!searchTerm || [r.provinsi,r.wilayah,r.mux,...(r.siaran || [])].some(v => String(v || '').toLocaleLowerCase('id-ID').includes(searchTerm))));
        const muxes = filtered.map(r => ({key:[r.provinsi,r.wilayah,r.mux].join('|'), label:rowTitle(r)}));
        const channelCount = filtered.reduce((n,r) => n + (r.siaran || []).length, 0);
        app.innerHTML = `<section class="map-dashboard" aria-label="Dashboard Peta Pemancar">
          <header class="map-dashboard-head">
            <div><span class="map-eyebrow">MONITORING SIARAN DIGITAL</span><h1>Peta Pemancar</h1><p>Pantau lokasi pemancar, wilayah layanan, dan informasi teknis siaran televisi digital Indonesia.</p></div>
          </header>
          <div class="map-kpi-grid">
            <article class="map-kpi"><span class="map-kpi-icon"><i data-lucide="radio-tower"></i></span><div><small>Pemancar berkoordinat</small><strong>${located.length.toLocaleString('id-ID')}</strong><em>Lokasi tersedia di peta</em></div></article>
            <article class="map-kpi"><span class="map-kpi-icon"><i data-lucide="map"></i></span><div><small>Provinsi terjangkau</small><strong>${new Set(located.map(r=>r.provinsi)).size.toLocaleString('id-ID')}</strong><em>Cakupan data pemancar</em></div></article>
            <article class="map-kpi"><span class="map-kpi-icon"><i data-lucide="layers"></i></span><div><small>Wilayah layanan</small><strong>${new Set(filtered.map(r=>r.wilayah)).size.toLocaleString('id-ID')}</strong><em>Sesuai filter aktif</em></div></article>
            <article class="map-kpi"><span class="map-kpi-icon"><i data-lucide="tv"></i></span><div><small>Kanal siaran terdata</small><strong>${channelCount.toLocaleString('id-ID')}</strong><em>Dalam hasil filter</em></div></article>
          </div>
          <div class="map-workspace">
            <aside class="map-filter-panel">
              <div class="map-panel-title"><div><span class="map-eyebrow">PENYARINGAN</span><h2>Filter peta</h2></div><i data-lucide="sliders-horizontal"></i></div>
              <label class="map-filter-field">Cari pemancar / kanal<input id="mapSearchInput" type="search" value="${attr(state.mapSearch || '')}" placeholder="Nama MUX, wilayah, kanal…"></label>
              <label class="map-filter-field">Provinsi<select id="mapProvinceFilter"><option value="">Semua provinsi</option>${options(provinces,state.mapProvince)}</select></label>
              <label class="map-filter-field">Wilayah layanan<select id="mapAreaFilter"><option value="">Semua wilayah</option>${options(areas,state.mapArea)}</select></label>
              <label class="map-filter-field">Pilih pemancar<select id="mapMuxFilter"><option value="">Semua pemancar</option>${muxes.map(x=>`<option value="${attr(x.key)}" ${x.key===state.mapMuxSelection?'selected':''}>${esc(x.label)}</option>`).join('')}</select></label>
              <button type="button" class="map-utility-btn map-reset-filter" id="resetMapFilters"><i data-lucide="rotate-ccw" aria-hidden="true"></i> Reset filter</button>
              <div class="map-filter-summary"><strong>${filtered.length.toLocaleString('id-ID')}</strong><span>pemancar ditampilkan</span></div>
              <div class="map-legend"><span><i class="map-legend-dot"></i> Lokasi pemancar</span><span><i class="map-legend-dot selected"></i> Pemancar dipilih</span></div>
              <p class="map-privacy-note"><i data-lucide="shield-check"></i> ${auth() ? 'Koordinat presisi tersedia untuk pengguna login.' : 'Koordinat publik ditampilkan dengan pembulatan untuk melindungi privasi.'}</p>
            </aside>
            <div class="map-main-column">
              <div class="map-canvas-card"><div class="map-canvas-toolbar"><div><strong>Peta interaktif</strong><span>Jelajahi lokasi pemancar di seluruh Indonesia</span></div><span class="map-live-indicator"><i></i> DATA PEMANCAR</span></div><div class="map-canvas-wrap"><div id="map" role="application" aria-label="Peta interaktif lokasi pemancar TV digital"></div><button type="button" class="map-location-control" id="mapLocate" aria-label="Lokasi saya" title="Lokasi saya"><i data-lucide="crosshair" aria-hidden="true"></i></button></div><div class="map-coordinate-bar"><i data-lucide="map-pin"></i><span id="mapCoordinates">Arahkan kursor ke peta untuk melihat koordinat</span><span class="map-coordinate-hint">Leaflet · OpenStreetMap</span></div></div>
              <section id="detailsPanel" class="map-details-placeholder"><div class="map-empty-icon"><i data-lucide="mouse-pointer-click"></i></div><strong>Pilih marker pemancar</strong><p>Pilih salah satu titik pada peta untuk melihat detail siaran, data teknis, dan kontribusi pengukuran komunitas.</p></section>
            </div>
          </div>
        </section>`;
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

