/**
 * Shared Office Order API tracking UI (status bar, uploads, proof approval).
 */
(function (global) {
    'use strict';

    function escapeHtml(s) {
        return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function latestProofFile(files) {
        const proofs = (files || []).filter(f => f.kind === 'proof');
        if (!proofs.length) return null;
        return proofs.reduce((a, b) => ((b.version || 0) > (a.version || 0) ? b : a));
    }

    function renderStatusBar(stages) {
        if (!stages || !stages.length) return '';
        let html = '<div class="office-status-bar">';
        stages.forEach((st, i) => {
            const state = st.state || 'pending';
            const icon = state === 'done' ? '<i class="fas fa-check"></i>' : (state === 'current' ? '●' : '');
            html += `<div class="office-status-step ${escapeHtml(state)}">
                <div class="office-status-node">
                    <div class="office-status-dot">${icon}</div>
                    <span class="office-status-label">${escapeHtml(st.label || st.key)}</span>
                </div>
                ${i < stages.length - 1 ? '<div class="office-status-connector"></div>' : ''}
            </div>`;
        });
        html += '</div>';
        return html;
    }

    function renderFileList(files, orderId, itemId, apiPrefix) {
        if (!files || !files.length) return '';
        let html = '<ul class="office-file-list">';
        files.forEach(f => {
            const url = f.download_url || proxyFileUrl(orderId, itemId, f.name, apiPrefix);
            html += `<li><a href="${escapeHtml(url)}" target="_blank" rel="noopener">${escapeHtml(f.name)}</a></li>`;
        });
        html += '</ul>';
        return html;
    }

    function proxyFileUrl(orderId, itemId, filename, apiPrefix) {
        return `${apiPrefix}/${encodeURIComponent(orderId)}/items/${encodeURIComponent(itemId)}/files/${encodeURIComponent(filename)}`;
    }

    const ALL_STAGE_OPTIONS = [
        { key: 'received', label: 'Order Received' },
        { key: 'artwork', label: 'Artwork Received' },
        { key: 'proof_1', label: 'Proof 1' },
        { key: 'proof_2', label: 'Proof 2' },
        { key: 'proof_3', label: 'Proof 3' },
        { key: 'proof_4', label: 'Proof 4' },
        { key: 'proof_5', label: 'Proof 5' },
        { key: 'proof_6', label: 'Proof 6' },
        { key: 'proof_7', label: 'Proof 7' },
        { key: 'proof_8', label: 'Proof 8' },
        { key: 'approved', label: 'Proof Approved' },
        { key: 'printing', label: 'In Production' },
        { key: 'shipped', label: 'Shipped' },
    ];

    function stageOptionsForSelect(office) {
        const fromApi = (office.stages || []).map(s => ({ key: s.key, label: s.label || s.key }));
        const seen = new Set(fromApi.map(s => s.key));
        ALL_STAGE_OPTIONS.forEach(s => {
            if (!seen.has(s.key)) fromApi.push(s);
        });
        return fromApi;
    }

    function renderStaffStatusControls(office, orderId, itemId, apiPrefix) {
        const current = office.current_stage || '';
        const options = stageOptionsForSelect(office);
        let html = '<div class="office-staff-status">';
        html += '<label class="office-staff-status-label">Move to stage</label>';
        html += `<select class="office-stage-select" data-order-id="${escapeHtml(orderId)}" data-item-id="${escapeHtml(itemId)}" data-api-prefix="${escapeHtml(apiPrefix)}">`;
        options.forEach(opt => {
            const sel = opt.key === current ? ' selected' : '';
            html += `<option value="${escapeHtml(opt.key)}"${sel}>${escapeHtml(opt.label)}</option>`;
        });
        html += '</select>';
        html += `<input type="text" class="office-stage-note" placeholder="Note (optional)" data-order-id="${escapeHtml(orderId)}" data-item-id="${escapeHtml(itemId)}" data-api-prefix="${escapeHtml(apiPrefix)}">`;
        html += `<button type="button" class="office-btn office-btn-set-stage office-set-stage-btn"
            data-order-id="${escapeHtml(orderId)}" data-item-id="${escapeHtml(itemId)}"
            data-api-prefix="${escapeHtml(apiPrefix)}">Update status</button>`;
        html += '</div>';
        return html;
    }

    function canUploadArtwork(office) {
        const stage = office && office.current_stage;
        return stage === 'received' || stage === 'artwork';
    }

    function isProofStage(stage) {
        return stage && /^proof_\d+$/.test(stage);
    }

    function renderTrackingBlock(item, orderId, apiPrefix, role) {
        const office = item.office;
        if (!office) {
            return '<div class="office-tracking"><p class="office-tracking-error">Tracking unavailable</p></div>';
        }
        const itemId = item.office_item_id;
        const stage = office.current_stage || '';
        let html = '<div class="office-tracking" data-item-id="' + escapeHtml(itemId) + '">';
        html += renderStatusBar(office.stages);
        html += renderFileList(office.files, orderId, itemId, apiPrefix);

        html += '<div class="office-tracking-actions">';
        if (role === 'client' && canUploadArtwork(office)) {
            html += `<label class="office-upload-btn"><i class="fas fa-upload"></i> Upload artwork
                <input type="file" class="office-artwork-input" data-order-id="${escapeHtml(orderId)}"
                    data-item-id="${escapeHtml(itemId)}" data-api-prefix="${escapeHtml(apiPrefix)}"></label>`;
        }
        if (role === 'staff') {
            html += `<label class="office-upload-btn"><i class="fas fa-file-image"></i> Upload proof
                <input type="file" class="office-proof-input" data-order-id="${escapeHtml(orderId)}"
                    data-item-id="${escapeHtml(itemId)}" data-api-prefix="${escapeHtml(apiPrefix)}"></label>`;
            html += renderStaffStatusControls(office, orderId, itemId, apiPrefix);
        }
        if (role === 'client' && isProofStage(stage)) {
            const proof = latestProofFile(office.files);
            if (proof) {
                const proofUrl = proof.download_url || proxyFileUrl(orderId, itemId, proof.name, apiPrefix);
                html += `<a class="office-proof-link" href="${escapeHtml(proofUrl)}" target="_blank" rel="noopener">
                    <i class="fas fa-eye"></i> View proof${proof.version ? ' v' + proof.version : ''}</a>`;
                html += `<button type="button" class="office-btn office-btn-approve office-approve-btn"
                    data-order-id="${escapeHtml(orderId)}" data-item-id="${escapeHtml(itemId)}"
                    data-api-prefix="${escapeHtml(apiPrefix)}">Approve proof</button>`;
                html += `<button type="button" class="office-btn office-btn-changes office-changes-btn"
                    data-order-id="${escapeHtml(orderId)}" data-item-id="${escapeHtml(itemId)}"
                    data-stage="${escapeHtml(stage)}" data-api-prefix="${escapeHtml(apiPrefix)}">Request changes</button>`;
            }
        }
        html += '<span class="office-tracking-msg" hidden></span></div></div>';
        return html;
    }

    function trackingLineNumber(el) {
        const host = el && el.closest('.office-tracking-host');
        if (host && host.dataset.lineNumber) return parseInt(host.dataset.lineNumber, 10);
        const tracking = el && el.closest('.office-tracking');
        const parent = tracking && tracking.parentElement;
        if (parent && parent.classList.contains('office-tracking-host') && parent.dataset.lineNumber) {
            return parseInt(parent.dataset.lineNumber, 10);
        }
        return null;
    }

    function findTrackingHost(detailsEl, lineNumber) {
        return detailsEl.querySelector('.office-tracking-host[data-line-number="' + lineNumber + '"]');
    }

    function paintTrackingHosts(detailsEl, payload, orderId, apiPrefix, role) {
        (payload.items || []).forEach(item => {
            const host = findTrackingHost(detailsEl, item.line_number);
            if (!host) return;
            host.innerHTML = renderTrackingBlock(item, orderId, apiPrefix, role);
        });
        bindTrackingEvents(detailsEl);
    }

    function showTrackingMsg(el, text, ok) {
        const msg = el && el.querySelector('.office-tracking-msg');
        if (!msg) return;
        msg.textContent = text;
        msg.className = 'office-tracking-msg ' + (ok ? 'ok' : 'err');
        msg.hidden = !text;
    }

    async function refreshItemTracking(detailsEl, orderId, itemId, apiPrefix, role, lineNumber) {
        const res = await fetch(`${apiPrefix}/${encodeURIComponent(orderId)}/tracking`, { credentials: 'same-origin' });
        const data = await res.json();
        if (!res.ok || !data.success) throw new Error(data.error || 'Could not refresh tracking');
        const item = (data.items || []).find(i => i.office_item_id === itemId || i.line_number === lineNumber);
        if (!item) throw new Error('Item not found');
        const host = findTrackingHost(detailsEl, item.line_number);
        if (host) {
            host.innerHTML = renderTrackingBlock(item, orderId, apiPrefix, role);
            bindTrackingEvents(detailsEl);
        }
        if (detailsEl._officeTracking) {
            const idx = (detailsEl._officeTracking.items || []).findIndex(i => i.line_number === item.line_number);
            if (idx >= 0) detailsEl._officeTracking.items[idx] = item;
        }
    }

    async function handleArtworkUpload(input) {
        const orderId = input.dataset.orderId;
        const itemId = input.dataset.itemId;
        const apiPrefix = input.dataset.apiPrefix;
        const file = input.files && input.files[0];
        if (!file) return;
        const host = input.closest('.office-tracking');
        const detailsEl = input.closest('.details-inner') || input.closest('td') || document.body;
        showTrackingMsg(host, 'Uploading…', true);
        const fd = new FormData();
        fd.append('file', file);
        try {
            const res = await fetch(`${apiPrefix}/${encodeURIComponent(orderId)}/items/${encodeURIComponent(itemId)}/artwork`, {
                method: 'POST',
                body: fd,
                credentials: 'same-origin',
            });
            const data = await res.json();
            if (!res.ok || !data.success) throw new Error(data.error || 'Upload failed');
            const role = apiPrefix.indexOf('/client/') >= 0 ? 'client' : 'staff';
            const lineNumber = trackingLineNumber(input);
            await refreshItemTracking(detailsEl, orderId, itemId, apiPrefix, role, lineNumber);
            const hostEl = lineNumber != null ? findTrackingHost(detailsEl, lineNumber) : null;
            showTrackingMsg(hostEl && hostEl.querySelector('.office-tracking'), 'Artwork uploaded.', true);
        } catch (err) {
            showTrackingMsg(host, err.message || 'Upload failed', false);
        } finally {
            input.value = '';
        }
    }

    async function handleProofUpload(input) {
        const orderId = input.dataset.orderId;
        const itemId = input.dataset.itemId;
        const apiPrefix = input.dataset.apiPrefix;
        const file = input.files && input.files[0];
        if (!file) return;
        const host = input.closest('.office-tracking');
        const detailsEl = input.closest('.details-inner') || input.closest('td') || document.body;
        showTrackingMsg(host, 'Uploading…', true);
        const fd = new FormData();
        fd.append('file', file);
        try {
            const res = await fetch(`${apiPrefix}/${encodeURIComponent(orderId)}/items/${encodeURIComponent(itemId)}/proof`, {
                method: 'POST',
                body: fd,
                credentials: 'same-origin',
            });
            const data = await res.json();
            if (!res.ok || !data.success) throw new Error(data.error || 'Upload failed');
            const lineNumber = trackingLineNumber(input);
            await refreshItemTracking(detailsEl, orderId, itemId, apiPrefix, 'staff', lineNumber);
        } catch (err) {
            showTrackingMsg(host, err.message || 'Upload failed', false);
        } finally {
            input.value = '';
        }
    }

    async function handleApprove(btn) {
        const orderId = btn.dataset.orderId;
        const itemId = btn.dataset.itemId;
        const apiPrefix = btn.dataset.apiPrefix;
        const host = btn.closest('.office-tracking');
        const detailsEl = btn.closest('.details-inner') || btn.closest('td') || document.body;
        btn.disabled = true;
        try {
            const res = await fetch(`${apiPrefix}/${encodeURIComponent(orderId)}/items/${encodeURIComponent(itemId)}/status`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ stage: 'approved', note: 'Proof approved by customer', by: 'customer' }),
            });
            const data = await res.json();
            if (!res.ok || !data.success) throw new Error(data.error || 'Could not approve');
            const lineNumber = trackingLineNumber(btn);
            await refreshItemTracking(detailsEl, orderId, itemId, apiPrefix, 'client', lineNumber);
        } catch (err) {
            showTrackingMsg(host, err.message || 'Could not approve', false);
            btn.disabled = false;
        }
    }

    async function handleSetStage(btn) {
        const orderId = btn.dataset.orderId;
        const itemId = btn.dataset.itemId;
        const apiPrefix = btn.dataset.apiPrefix;
        const host = btn.closest('.office-tracking');
        const detailsEl = btn.closest('.details-inner') || btn.closest('td') || document.body;
        const select = host && host.querySelector('.office-stage-select');
        const noteInput = host && host.querySelector('.office-stage-note');
        const stage = select && select.value;
        const note = (noteInput && noteInput.value) ? noteInput.value.trim() : '';
        if (!stage) return;
        btn.disabled = true;
        showTrackingMsg(host, 'Updating status…', true);
        try {
            const res = await fetch(`${apiPrefix}/${encodeURIComponent(orderId)}/items/${encodeURIComponent(itemId)}/status`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ stage: stage, note: note || 'Status updated by staff', by: 'staff' }),
            });
            const data = await res.json();
            if (!res.ok || !data.success) throw new Error(data.error || 'Could not update status');
            const lineNumber = trackingLineNumber(btn);
            await refreshItemTracking(detailsEl, orderId, itemId, apiPrefix, 'staff', lineNumber);
            showTrackingMsg(findTrackingHost(detailsEl, lineNumber)?.querySelector('.office-tracking'), 'Status updated.', true);
        } catch (err) {
            showTrackingMsg(host, err.message || 'Could not update status', false);
        } finally {
            btn.disabled = false;
        }
    }

    async function handleRequestChanges(btn) {
        const orderId = btn.dataset.orderId;
        const itemId = btn.dataset.itemId;
        const stage = btn.dataset.stage;
        const apiPrefix = btn.dataset.apiPrefix;
        const note = window.prompt('What changes would you like?');
        if (note === null) return;
        if (!note.trim()) {
            alert('Please describe the changes you need.');
            return;
        }
        const host = btn.closest('.office-tracking');
        const detailsEl = btn.closest('.details-inner') || btn.closest('td') || document.body;
        btn.disabled = true;
        try {
            const res = await fetch(`${apiPrefix}/${encodeURIComponent(orderId)}/items/${encodeURIComponent(itemId)}/status`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ stage: stage, note: note.trim(), by: 'customer' }),
            });
            const data = await res.json();
            if (!res.ok || !data.success) throw new Error(data.error || 'Could not send request');
            showTrackingMsg(host, 'Change request sent to our team.', true);
        } catch (err) {
            showTrackingMsg(host, err.message || 'Could not send request', false);
        } finally {
            btn.disabled = false;
        }
    }

    const boundRoots = new WeakSet();

    function bindTrackingEvents(root) {
        if (!root || boundRoots.has(root)) return;
        boundRoots.add(root);
        root.addEventListener('change', function (e) {
            if (e.target.classList.contains('office-artwork-input')) handleArtworkUpload(e.target);
            if (e.target.classList.contains('office-proof-input')) handleProofUpload(e.target);
        });
        root.addEventListener('click', function (e) {
            const approve = e.target.closest('.office-approve-btn');
            if (approve) { e.preventDefault(); handleApprove(approve); return; }
            const changes = e.target.closest('.office-changes-btn');
            if (changes) { e.preventDefault(); handleRequestChanges(changes); return; }
            const setStage = e.target.closest('.office-set-stage-btn');
            if (setStage) { e.preventDefault(); handleSetStage(setStage); }
        });
    }

    async function loadOrderTracking(orderId, apiPrefix, detailsEl, role) {
        if (!detailsEl || !orderId) return;
        if (detailsEl.dataset.trackingLoaded === '1' && detailsEl._officeTracking) {
            paintTrackingHosts(detailsEl, detailsEl._officeTracking, orderId, apiPrefix, role);
            return;
        }
        const hosts = detailsEl.querySelectorAll('.office-tracking-host');
        hosts.forEach(h => {
            h.innerHTML = '<div class="office-tracking-loading"><i class="fas fa-spinner fa-spin"></i> Loading tracking…</div>';
        });
        try {
            const res = await fetch(`${apiPrefix}/${encodeURIComponent(orderId)}/tracking`, { credentials: 'same-origin' });
            const data = await res.json();
            if (!res.ok || !data.success) throw new Error(data.error || 'Tracking unavailable');
            detailsEl._officeTracking = data;
            detailsEl.dataset.trackingLoaded = '1';
            paintTrackingHosts(detailsEl, data, orderId, apiPrefix, role);
        } catch (err) {
            hosts.forEach(h => {
                h.innerHTML = '<div class="office-tracking"><p class="office-tracking-error">' + escapeHtml(err.message || 'Tracking unavailable') + '</p></div>';
            });
            detailsEl.dataset.trackingLoaded = '1';
        }
    }

    global.OfficeTracking = {
        loadOrderTracking,
        renderTrackingBlock,
        renderStatusBar,
        proxyFileUrl,
        bindTrackingEvents,
    };
})(typeof window !== 'undefined' ? window : this);
