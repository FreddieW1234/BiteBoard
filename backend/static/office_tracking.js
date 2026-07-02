/**
 * Shared Office Order API tracking UI (status bar, uploads, proof approval).
 */
(function (global) {
    'use strict';

    function escapeHtml(s) {
        return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    async function parseJsonResponse(res) {
        const text = await res.text();
        if (!text) {
            if (!res.ok) throw new Error('Request failed (' + res.status + ')');
            return {};
        }
        const ct = (res.headers.get('content-type') || '').toLowerCase();
        if (text.trim().startsWith('<') && !ct.includes('json')) {
            throw new Error(
                res.ok
                    ? 'Unexpected server response. Please refresh the page.'
                    : 'Request failed (' + res.status + '). Please refresh and try again.'
            );
        }
        try {
            return JSON.parse(text);
        } catch (_) {
            throw new Error('Invalid server response');
        }
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

    function proxyFileUrl(orderId, itemId, filename, apiPrefix, inline) {
        const base = `${apiPrefix}/${encodeURIComponent(orderId)}/items/${encodeURIComponent(itemId)}/files/${encodeURIComponent(filename)}`;
        return inline ? `${base}?inline=1` : base;
    }

    function fileKind(f) {
        if (f.kind === 'artwork' || f.kind === 'proof') return f.kind;
        const name = (f.name || '').toLowerCase();
        if (name.startsWith('customer-artwork') || name.includes('artwork')) return 'artwork';
        if (name.startsWith('proof')) return 'proof';
        return 'other';
    }

    function sortFilesByVersion(files) {
        return (files || []).slice().sort((a, b) => (b.version || 0) - (a.version || 0));
    }

    function renderFileRow(f, orderId, itemId, apiPrefix) {
        const viewUrl = f.download_url
            ? (f.download_url + (f.download_url.includes('?') ? '&' : '?') + 'inline=1')
            : proxyFileUrl(orderId, itemId, f.name, apiPrefix, true);
        const downloadUrl = f.download_url || proxyFileUrl(orderId, itemId, f.name, apiPrefix, false);
        const versionLabel = f.version ? ` v${f.version}` : '';
        return `<li class="office-file-row">
            <span class="office-file-name">${escapeHtml(f.name)}${versionLabel ? `<span class="office-file-ver">${escapeHtml(versionLabel.trim())}</span>` : ''}</span>
            <span class="office-file-actions">
                <a class="office-file-link" href="${escapeHtml(viewUrl)}" target="_blank" rel="noopener"><i class="fas fa-eye"></i> View</a>
                <a class="office-file-link office-file-download" href="${escapeHtml(downloadUrl)}" download="${escapeHtml(f.name)}"><i class="fas fa-download"></i> Download</a>
            </span>
        </li>`;
    }

    function renderFileSection(title, files, orderId, itemId, apiPrefix) {
        if (!files || !files.length) return '';
        let html = `<div class="office-file-section"><h5 class="office-file-section-title">${escapeHtml(title)}</h5><ul class="office-file-list">`;
        sortFilesByVersion(files).forEach(f => {
            html += renderFileRow(f, orderId, itemId, apiPrefix);
        });
        html += '</ul></div>';
        return html;
    }

    function renderFileSections(files, orderId, itemId, apiPrefix) {
        if (!files || !files.length) return '';
        const artwork = files.filter(f => fileKind(f) === 'artwork');
        const proofs = files.filter(f => fileKind(f) === 'proof');
        let html = '<div class="office-files-wrap">';
        html += renderFileSection('Artwork', artwork, orderId, itemId, apiPrefix);
        html += renderFileSection('Proofs', proofs, orderId, itemId, apiPrefix);
        html += '</div>';
        return html;
    }

    function proofNum(key) {
        const m = /^proof_(\d+)$/.exec(key || '');
        return m ? parseInt(m[1], 10) : 0;
    }

    const STAGE_LABELS = {
        received: 'Order Received',
        artwork: 'Artwork Received',
        approved: 'Proof Approved',
        printing: 'Printing',
        in_production: 'In Production',
        shipped: 'Shipped',
    };

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
        { key: 'printing', label: 'Printing' },
        { key: 'in_production', label: 'In Production' },
        { key: 'shipped', label: 'Shipped' },
    ];

    function proofLabel(n, maxProof) {
        if (maxProof <= 1) return 'Proof';
        return `Proof ${n}`;
    }

    function labelForStage(key, apiStage, maxProof) {
        const n = proofNum(key);
        if (n) {
            if (apiStage && apiStage.label) {
                if (maxProof <= 1) return 'Proof';
                if (/^Proof \d+$/i.test(apiStage.label)) return proofLabel(n, maxProof);
                return apiStage.label;
            }
            return proofLabel(n, maxProof);
        }
        if (apiStage && apiStage.label) {
            if (key === 'printing' && apiStage.label === 'In Production') return STAGE_LABELS.printing;
            return apiStage.label;
        }
        if (STAGE_LABELS[key]) return STAGE_LABELS[key];
        return key;
    }

    function maxProofReached(office) {
        let max = 0;
        (office.stages || []).forEach(s => { max = Math.max(max, proofNum(s.key)); });
        (office.files || []).forEach(f => {
            if (f.kind === 'proof' && f.version) max = Math.max(max, f.version);
        });
        max = Math.max(max, proofNum(office.current_stage));
        return max;
    }

    function buildPipelineKeys(maxProof) {
        const keys = ['received', 'artwork'];
        for (let i = 1; i <= maxProof; i++) keys.push(`proof_${i}`);
        keys.push('approved', 'printing', 'in_production', 'shipped');
        return keys;
    }

    /** Expand proof_1..proof_N and add Printing before In Production for display. */
    function normalizeStagesForDisplay(office) {
        const current = office.current_stage || '';
        const maxProof = maxProofReached(office);
        const keys = buildPipelineKeys(maxProof);
        const apiByKey = {};
        (office.stages || []).forEach(s => { apiByKey[s.key] = s; });

        let currentIdx = keys.indexOf(current);
        if (currentIdx < 0) {
            const apiCurrent = (office.stages || []).find(s => s.state === 'current');
            if (apiCurrent) currentIdx = keys.indexOf(apiCurrent.key);
        }

        return keys.map((key, idx) => {
            const fromApi = apiByKey[key];
            let state = 'pending';
            if (currentIdx >= 0) {
                if (idx < currentIdx) state = 'done';
                else if (idx === currentIdx) state = 'current';
            } else if (fromApi && fromApi.state) {
                state = fromApi.state;
            }
            return { key, label: labelForStage(key, fromApi, maxProof), state };
        });
    }

    function stageOptionsForSelect(_office) {
        return ALL_STAGE_OPTIONS.slice();
    }

    function renderStaffProofUpload(orderId, itemId, apiPrefix) {
        return `<label class="office-upload-btn office-upload-proof"><i class="fas fa-file-image"></i> Upload proof
            <input type="file" class="office-proof-input" data-order-id="${escapeHtml(orderId)}"
                data-item-id="${escapeHtml(itemId)}" data-api-prefix="${escapeHtml(apiPrefix)}"></label>`;
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
        html += renderStatusBar(normalizeStagesForDisplay(office));

        if (role === 'staff') {
            html += '<div class="office-tracking-body">';
            html += renderFileSections(office.files, orderId, itemId, apiPrefix);
            html += renderStaffStatusControls(office, orderId, itemId, apiPrefix);
            html += '</div>';
            html += '<div class="office-tracking-actions office-staff-actions">';
            html += renderStaffProofUpload(orderId, itemId, apiPrefix);
            html += '<span class="office-tracking-msg" hidden></span></div>';
        } else {
            html += renderFileSections(office.files, orderId, itemId, apiPrefix);
            html += '<div class="office-tracking-actions">';
            if (canUploadArtwork(office)) {
                html += `<label class="office-upload-btn"><i class="fas fa-upload"></i> Upload artwork
                    <input type="file" class="office-artwork-input" data-order-id="${escapeHtml(orderId)}"
                        data-item-id="${escapeHtml(itemId)}" data-api-prefix="${escapeHtml(apiPrefix)}"></label>`;
            }
            if (isProofStage(stage)) {
                const proof = latestProofFile(office.files);
                if (proof) {
                    html += `<button type="button" class="office-btn office-btn-approve office-approve-btn"
                        data-order-id="${escapeHtml(orderId)}" data-item-id="${escapeHtml(itemId)}"
                        data-api-prefix="${escapeHtml(apiPrefix)}">Approve proof</button>`;
                    html += `<button type="button" class="office-btn office-btn-changes office-changes-btn"
                        data-order-id="${escapeHtml(orderId)}" data-item-id="${escapeHtml(itemId)}"
                        data-order-name="${escapeHtml(office.order || '')}"
                        data-stage="${escapeHtml(stage)}" data-api-prefix="${escapeHtml(apiPrefix)}">Request changes</button>`;
                }
            }
            html += '<span class="office-tracking-msg" hidden></span></div>';
        }
        html += '</div>';
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
        const data = await parseJsonResponse(res);
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
            syncOrderListBadge(orderId, detailsEl._officeTracking.items, role);
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
            const data = await parseJsonResponse(res);
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
            const data = await parseJsonResponse(res);
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
            const data = await parseJsonResponse(res);
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
        const stage = select && select.value;
        if (!stage) return;
        btn.disabled = true;
        showTrackingMsg(host, 'Updating status…', true);
        try {
            const res = await fetch(`${apiPrefix}/${encodeURIComponent(orderId)}/items/${encodeURIComponent(itemId)}/status`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ stage: stage, note: 'Status updated by staff', by: 'staff' }),
            });
            const data = await parseJsonResponse(res);
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

    function ensureChangesModal() {
        let modal = document.getElementById('office-changes-modal');
        if (modal) return modal;
        modal = document.createElement('div');
        modal.id = 'office-changes-modal';
        modal.className = 'office-changes-modal';
        modal.hidden = true;
        modal.innerHTML = `
            <div class="office-changes-modal-backdrop" data-close-changes-modal></div>
            <div class="office-changes-modal-panel" role="dialog" aria-modal="true" aria-labelledby="office-changes-modal-title">
                <button type="button" class="office-changes-modal-close" data-close-changes-modal aria-label="Close">&times;</button>
                <h3 id="office-changes-modal-title">Request changes</h3>
                <p class="office-changes-modal-lead">To request changes to your proof, please email our sales team:</p>
                <p class="office-changes-modal-email"><a href="mailto:sales@bitepromotions.co.uk" id="office-changes-mailto">sales@bitepromotions.co.uk</a></p>
                <ul class="office-changes-modal-steps">
                    <li>Quote your order number: <strong id="office-changes-order-num"></strong></li>
                    <li>Explain the changes you would like made to the proof</li>
                </ul>
                <div class="office-changes-modal-actions">
                    <a class="office-btn office-btn-email" id="office-changes-email-btn" href="mailto:sales@bitepromotions.co.uk">Email sales</a>
                    <button type="button" class="office-btn office-btn-changes" data-close-changes-modal>Close</button>
                </div>
            </div>`;
        document.body.appendChild(modal);
        modal.addEventListener('click', function (e) {
            if (e.target.closest('[data-close-changes-modal]')) hideChangesModal();
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && modal && !modal.hidden) hideChangesModal();
        });
        return modal;
    }

    function showChangesModal(orderName) {
        const modal = ensureChangesModal();
        const name = (orderName || '').trim() || 'your order';
        const subject = encodeURIComponent(`Order ${name} – proof change request`);
        const mailto = `mailto:sales@bitepromotions.co.uk?subject=${subject}`;
        const orderEl = document.getElementById('office-changes-order-num');
        const mailLink = document.getElementById('office-changes-mailto');
        const emailBtn = document.getElementById('office-changes-email-btn');
        if (orderEl) orderEl.textContent = name;
        if (mailLink) mailLink.href = mailto;
        if (emailBtn) emailBtn.href = mailto;
        modal.hidden = false;
    }

    function hideChangesModal() {
        const modal = document.getElementById('office-changes-modal');
        if (modal) modal.hidden = true;
    }

    function handleRequestChanges(btn) {
        const orderName = btn.dataset.orderName;
        const detailsEl = btn.closest('.details-inner') || btn.closest('td') || document.body;
        const fromPayload = detailsEl._officeTracking && detailsEl._officeTracking.order;
        showChangesModal(orderName || fromPayload || '');
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
            syncOrderListBadge(orderId, detailsEl._officeTracking.items, role);
            return;
        }
        const hosts = detailsEl.querySelectorAll('.office-tracking-host');
        hosts.forEach(h => {
            h.innerHTML = '<div class="office-tracking-loading"><i class="fas fa-spinner fa-spin"></i> Loading tracking…</div>';
        });
        try {
            const res = await fetch(`${apiPrefix}/${encodeURIComponent(orderId)}/tracking`, { credentials: 'same-origin' });
            const data = await parseJsonResponse(res);
            if (!res.ok || !data.success) throw new Error(data.error || 'Tracking unavailable');
            detailsEl._officeTracking = data;
            detailsEl.dataset.trackingLoaded = '1';
            paintTrackingHosts(detailsEl, data, orderId, apiPrefix, role);
            syncOrderListBadge(orderId, data.items, role);
        } catch (err) {
            hosts.forEach(h => {
                h.innerHTML = '<div class="office-tracking"><p class="office-tracking-error">' + escapeHtml(err.message || 'Tracking unavailable') + '</p></div>';
            });
            detailsEl.dataset.trackingLoaded = '1';
        }
    }

    function syncOrderListBadge(orderId, items, role) {
        if (role !== 'client') {
            updateOrderRowIndicator(orderId, computeOrderIndicator(items));
        }
    }

    const INDICATOR_PRIORITY = { red: 1, yellow: 2, printing: 3, production: 4, green: 5, none: 99 };

    const INDICATOR_TITLES = {
        green: 'Shipped — order complete',
        yellow: 'Waiting on customer (artwork or proof approval)',
        red: 'Customer waiting on us (proof upload needed)',
        printing: 'Printing',
        production: 'In production',
    };

    function computeItemIndicator(office) {
        if (!office) return 'none';
        const stage = office.current_stage || '';
        if (stage === 'shipped') return 'green';
        if (stage === 'in_production') return 'production';
        if (stage === 'printing') return 'printing';
        if (stage === 'received') return 'yellow';
        if (/^proof_/.test(stage)) return 'yellow';
        if (stage === 'artwork') return 'red';
        if (stage === 'approved') return 'red';
        return 'yellow';
    }

    function computeOrderIndicator(items) {
        let worst = 'none';
        let worstP = INDICATOR_PRIORITY.none;
        (items || []).forEach(item => {
            const t = computeItemIndicator(item.office);
            const p = INDICATOR_PRIORITY[t] ?? INDICATOR_PRIORITY.none;
            if (p < worstP) {
                worst = t;
                worstP = p;
            }
        });
        return worst;
    }

    function renderOrderIndicatorHtml(type) {
        if (!type || type === 'none') return '';
        const title = INDICATOR_TITLES[type] || '';
        if (type === 'printing') {
            return `<span class="order-status-indicator printing" title="${escapeHtml(title)}"><i class="fas fa-print"></i></span>`;
        }
        if (type === 'production') {
            return `<span class="order-status-indicator production" title="${escapeHtml(title)}"><i class="fas fa-industry"></i></span>`;
        }
        return `<span class="order-status-indicator ${escapeHtml(type)}" title="${escapeHtml(title)}"><span class="order-status-dot"></span></span>`;
    }

    function updateOrderRowIndicator(orderId, type) {
        document.querySelectorAll(`.order-status-indicator-slot[data-order-id="${CSS.escape(String(orderId))}"]`).forEach(slot => {
            slot.innerHTML = renderOrderIndicatorHtml(type);
        });
    }

    async function loadOrderIndicator(orderId, apiPrefix, slotEl) {
        if (!slotEl || !orderId) return;
        try {
            const res = await fetch(`${apiPrefix}/${encodeURIComponent(orderId)}/indicator`, { credentials: 'same-origin' });
            const data = await parseJsonResponse(res);
            if (!res.ok || !data.success) return;
            slotEl.innerHTML = renderOrderIndicatorHtml(computeOrderIndicator(data.items));
        } catch (_) { /* ignore */ }
    }

    function loadOrderIndicatorsIn(container, apiPrefix) {
        if (!container) return;
        container.querySelectorAll('.order-status-indicator-slot[data-order-id]').forEach(slot => {
            loadOrderIndicator(slot.dataset.orderId, apiPrefix, slot);
        });
    }

    global.OfficeTracking = {
        loadOrderTracking,
        renderTrackingBlock,
        renderStatusBar,
        proxyFileUrl,
        bindTrackingEvents,
        computeOrderIndicator,
        loadOrderIndicatorsIn,
        updateOrderRowIndicator,
        syncOrderListBadge,
    };
})(typeof window !== 'undefined' ? window : this);
