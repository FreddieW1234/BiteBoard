/**
 * Shared Office Order API tracking UI (status bar, uploads, proof approval).
 */
(function (global) {
    'use strict';

    function escapeHtml(s) {
        return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    const SALES_EMAIL = 'sales@bitepromotions.co.uk';
    const SALES_PHONE_DISPLAY = '01792 293689';
    const SALES_PHONE_TEL = '+441792293689';

    function isPortalEmbed() {
        return document.documentElement.classList.contains('co-embed') || window.parent !== window;
    }

    function setParentOverlayMode(active) {
        if (window.parent === window) return;
        try {
            window.parent.postMessage({ source: 'bite-portal', type: 'overlay-mode', active: !!active }, '*');
        } catch (_) { /* ignore */ }
    }

    function showOfficeModal(modal) {
        if (!modal) return;
        if (!modal.parentElement || modal.parentElement !== document.body) {
            document.body.appendChild(modal);
        }
        document.documentElement.classList.add('office-modal-open');
        modal.hidden = false;
        if (isPortalEmbed()) {
            setParentOverlayMode(true);
            window.scrollTo(0, 0);
        }
    }

    function hideOfficeModal(modal) {
        if (modal) modal.hidden = true;
        const openModals = document.querySelectorAll('.office-changes-modal:not([hidden]):not(.office-changes-popover)');
        if (!openModals.length) {
            document.documentElement.classList.remove('office-modal-open');
            if (isPortalEmbed()) setParentOverlayMode(false);
        }
    }

    function positionChangesPopover(modal, anchorBtn) {
        const panel = modal && modal.querySelector('.office-changes-modal-panel');
        if (!panel || !anchorBtn) return;

        panel.style.visibility = 'hidden';
        panel.style.position = 'fixed';
        panel.style.top = '0';
        panel.style.left = '0';

        const btnRect = anchorBtn.getBoundingClientRect();
        const panelRect = panel.getBoundingClientRect();
        const gap = 10;
        const margin = 12;
        const vw = window.innerWidth;
        const vh = window.innerHeight;

        let top = btnRect.bottom + gap;
        if (top + panelRect.height > vh - margin && btnRect.top - panelRect.height - gap >= margin) {
            top = btnRect.top - panelRect.height - gap;
        }
        top = Math.max(margin, Math.min(top, vh - panelRect.height - margin));

        let left = btnRect.left;
        left = Math.max(margin, Math.min(left, vw - panelRect.width - margin));

        panel.style.top = `${Math.round(top)}px`;
        panel.style.left = `${Math.round(left)}px`;
        panel.style.visibility = '';
    }

    function bindChangesPopoverReposition(modal) {
        if (modal._repositionHandler) return;
        modal._repositionHandler = function () {
            if (!modal.hidden && modal._anchorBtn) positionChangesPopover(modal, modal._anchorBtn);
        };
        window.addEventListener('resize', modal._repositionHandler);
        window.addEventListener('scroll', modal._repositionHandler, true);
    }

    function unbindChangesPopoverReposition(modal) {
        if (!modal || !modal._repositionHandler) return;
        window.removeEventListener('resize', modal._repositionHandler);
        window.removeEventListener('scroll', modal._repositionHandler, true);
        modal._repositionHandler = null;
    }

    function showChangesPopover(modal, anchorBtn) {
        if (!modal || !anchorBtn) return;
        if (!modal.parentElement || modal.parentElement !== document.body) {
            document.body.appendChild(modal);
        }
        modal._anchorBtn = anchorBtn;
        modal.classList.add('office-changes-popover');
        modal.hidden = false;
        bindChangesPopoverReposition(modal);
        requestAnimationFrame(function () {
            positionChangesPopover(modal, anchorBtn);
        });
    }

    function hideChangesPopover(modal) {
        if (!modal) return;
        modal.hidden = true;
        modal.classList.remove('office-changes-popover');
        modal._anchorBtn = null;
        unbindChangesPopoverReposition(modal);
        const panel = modal.querySelector('.office-changes-modal-panel');
        if (panel) {
            panel.style.top = '';
            panel.style.left = '';
            panel.style.position = '';
            panel.style.visibility = '';
        }
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

    function canDeleteFile(role, office, file) {
        if (!office || !file) return false;
        if (role === 'staff') return true;
        if (role !== 'client') return false;
        const stage = office.current_stage || '';
        if (stage !== 'received' && stage !== 'artwork') return false;
        return fileKind(file) === 'artwork';
    }

    function roleFromApiPrefix(apiPrefix) {
        return apiPrefix && String(apiPrefix).includes('/client') ? 'client' : 'staff';
    }

    function renderFileRow(f, orderId, itemId, apiPrefix, role, office) {
        const viewUrl = f.download_url
            ? (f.download_url + (f.download_url.includes('?') ? '&' : '?') + 'inline=1')
            : proxyFileUrl(orderId, itemId, f.name, apiPrefix, true);
        const downloadUrl = f.download_url || proxyFileUrl(orderId, itemId, f.name, apiPrefix, false);
        const versionLabel = f.version ? ` v${f.version}` : '';
        let deleteBtn = '';
        if (canDeleteFile(role, office, f)) {
            deleteBtn = `<button type="button" class="office-file-link office-file-delete office-delete-file-btn"
                data-order-id="${escapeHtml(orderId)}" data-item-id="${escapeHtml(itemId)}"
                data-filename="${escapeHtml(f.name)}" data-api-prefix="${escapeHtml(apiPrefix)}"
                title="Archive file"><i class="fas fa-times"></i> Remove</button>`;
        }
        return `<li class="office-file-row">
            <span class="office-file-name">${escapeHtml(f.name)}${versionLabel ? `<span class="office-file-ver">${escapeHtml(versionLabel.trim())}</span>` : ''}</span>
            <span class="office-file-actions">
                <a class="office-file-link" href="${escapeHtml(viewUrl)}" target="_blank" rel="noopener"><i class="fas fa-eye"></i> View</a>
                <a class="office-file-link office-file-download" href="${escapeHtml(downloadUrl)}" download="${escapeHtml(f.name)}"><i class="fas fa-download"></i> Download</a>
                ${deleteBtn}
            </span>
        </li>`;
    }

    function renderFileSection(title, files, orderId, itemId, apiPrefix, role, office) {
        if (!files || !files.length) return '';
        let html = `<div class="office-file-section"><h5 class="office-file-section-title">${escapeHtml(title)}</h5><ul class="office-file-list">`;
        sortFilesByVersion(files).forEach(f => {
            html += renderFileRow(f, orderId, itemId, apiPrefix, role, office);
        });
        html += '</ul></div>';
        return html;
    }

    function renderFileSections(files, orderId, itemId, apiPrefix, role, office) {
        if (!files || !files.length) return '';
        const artwork = files.filter(f => fileKind(f) === 'artwork');
        const proofs = files.filter(f => fileKind(f) === 'proof');
        let html = '<div class="office-files-wrap">';
        html += renderFileSection('Artwork', artwork, orderId, itemId, apiPrefix, role, office);
        html += renderFileSection('Proofs', proofs, orderId, itemId, apiPrefix, role, office);
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

    /** Office API uses stage key `printing` only; distinguish Printing vs In Production via history notes. */
    function displayPhaseForPrinting(office) {
        const history = office.history || [];
        for (let i = history.length - 1; i >= 0; i--) {
            const h = history[i];
            const st = h.stage || h.key || '';
            if (st !== 'printing') continue;
            const note = (h.note || '').toLowerCase();
            if (note.includes('in production')) return 'in_production';
            if (note.includes('printing')) return 'printing';
        }
        return 'printing';
    }

    function effectiveDisplayStage(office) {
        const current = office.current_stage || '';
        if (current === 'printing' && displayPhaseForPrinting(office) === 'in_production') {
            return 'in_production';
        }
        return current;
    }

    function staffSelectStageKey(office) {
        return effectiveDisplayStage(office);
    }

    /** Expand proof_1..proof_N and add Printing before In Production for display. */
    function normalizeStagesForDisplay(office) {
        const current = effectiveDisplayStage(office);
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

    function pipelineIndex(stageKey, maxProof) {
        const mp = Math.max(maxProof, proofNum(stageKey), 1);
        const keys = buildPipelineKeys(mp);
        const idx = keys.indexOf(stageKey);
        if (idx >= 0) return idx;
        return ALL_STAGE_OPTIONS.findIndex(o => o.key === stageKey);
    }

    function getOfficeForItem(detailsEl, itemId, lineNumber) {
        const payload = detailsEl && detailsEl._officeTracking;
        if (!payload || !payload.items) return null;
        let item = payload.items.find(i => i.office_item_id === itemId);
        if (!item && lineNumber != null) {
            item = payload.items.find(i => i.line_number === lineNumber);
        }
        return item && item.office ? item.office : null;
    }

    function getSkipAheadWarnings(office, targetStage) {
        if (!office || !targetStage) return null;
        const current = effectiveDisplayStage(office);
        if (targetStage === current) return null;

        const maxProof = Math.max(maxProofReached(office), proofNum(targetStage), 1);
        const currentIdx = pipelineIndex(current, maxProof);
        const targetIdx = pipelineIndex(targetStage, maxProof);
        if (currentIdx < 0 || targetIdx < 0 || targetIdx <= currentIdx) return null;

        const warnings = [];
        const files = office.files || [];
        const hasArtwork = files.some(f => fileKind(f) === 'artwork');
        const hasProof = files.some(f => fileKind(f) === 'proof');
        const approvedIdx = pipelineIndex('approved', maxProof);
        const firstProofIdx = pipelineIndex('proof_1', maxProof);
        const artworkIdx = pipelineIndex('artwork', maxProof);

        if (targetIdx > artworkIdx && !hasArtwork) {
            warnings.push('No artwork file has been uploaded');
        }
        if (targetIdx >= firstProofIdx && !hasProof) {
            warnings.push('No proof has been uploaded');
        }
        if (targetIdx >= approvedIdx && current !== 'approved') {
            warnings.push('Proof has not been approved by the customer');
        }
        if (warnings.length) return [...new Set(warnings)];

        if (targetIdx > currentIdx + 1) {
            return ['You are skipping one or more stages in the workflow'];
        }
        return null;
    }

    let skipConfirmResolver = null;

    function ensureSkipConfirmModal() {
        let modal = document.getElementById('office-skip-modal');
        if (modal) return modal;
        modal = document.createElement('div');
        modal.id = 'office-skip-modal';
        modal.className = 'office-changes-modal';
        modal.hidden = true;
        modal.innerHTML = `
            <div class="office-changes-modal-backdrop" data-close-skip-modal></div>
            <div class="office-changes-modal-panel" role="dialog" aria-modal="true" aria-labelledby="office-skip-modal-title">
                <button type="button" class="office-changes-modal-close" data-close-skip-modal aria-label="Close">&times;</button>
                <h3 id="office-skip-modal-title">Skip ahead?</h3>
                <p class="office-changes-modal-lead" id="office-skip-modal-lead"></p>
                <ul class="office-changes-modal-steps office-skip-warnings" id="office-skip-warnings"></ul>
                <div class="office-changes-modal-actions">
                    <button type="button" class="office-btn office-btn-set-stage" id="office-skip-confirm-btn">Yes, skip ahead</button>
                    <button type="button" class="office-btn office-btn-changes" data-close-skip-modal>Cancel</button>
                </div>
            </div>`;
        document.body.appendChild(modal);
        modal.addEventListener('click', function (e) {
            if (e.target.closest('[data-close-skip-modal]')) finishSkipConfirm(false);
        });
        document.getElementById('office-skip-confirm-btn').addEventListener('click', function () {
            finishSkipConfirm(true);
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && modal && !modal.hidden) finishSkipConfirm(false);
        });
        return modal;
    }

    function finishSkipConfirm(confirmed) {
        hideOfficeModal(document.getElementById('office-skip-modal'));
        if (skipConfirmResolver) {
            const resolve = skipConfirmResolver;
            skipConfirmResolver = null;
            resolve(confirmed);
        }
    }

    function confirmSkipAhead(warnings, targetLabel) {
        const modal = ensureSkipConfirmModal();
        const lead = document.getElementById('office-skip-modal-lead');
        const list = document.getElementById('office-skip-warnings');
        if (lead) {
            lead.textContent = `Move to "${targetLabel}" anyway? You are skipping ahead with:`;
        }
        if (list) {
            list.innerHTML = (warnings || []).map(w => `<li>${escapeHtml(w)}</li>`).join('');
        }
        showOfficeModal(modal);
        return new Promise(resolve => { skipConfirmResolver = resolve; });
    }

    let deleteConfirmResolver = null;

    function ensureDeleteConfirmModal() {
        let modal = document.getElementById('office-delete-modal');
        if (modal) return modal;
        modal = document.createElement('div');
        modal.id = 'office-delete-modal';
        modal.className = 'office-changes-modal';
        modal.hidden = true;
        modal.innerHTML = `
            <div class="office-changes-modal-backdrop" data-close-delete-modal></div>
            <div class="office-changes-modal-panel" role="dialog" aria-modal="true" aria-labelledby="office-delete-modal-title">
                <button type="button" class="office-changes-modal-close" data-close-delete-modal aria-label="Close">&times;</button>
                <h3 id="office-delete-modal-title">Remove file?</h3>
                <p class="office-changes-modal-lead" id="office-delete-modal-lead"></p>
                <p class="office-delete-modal-note" id="office-delete-staff-note">
                    After removing a file, check the order progress and timeline to ensure they are still accurate.
                </p>
                <div class="office-changes-modal-actions">
                    <button type="button" class="office-btn-danger" id="office-delete-confirm-btn">Remove</button>
                    <button type="button" class="office-btn office-btn-changes" data-close-delete-modal>Cancel</button>
                </div>
            </div>`;
        document.body.appendChild(modal);
        modal.addEventListener('click', function (e) {
            if (e.target.closest('[data-close-delete-modal]')) finishDeleteConfirm(false);
        });
        document.getElementById('office-delete-confirm-btn').addEventListener('click', function () {
            finishDeleteConfirm(true);
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && modal && !modal.hidden) finishDeleteConfirm(false);
        });
        return modal;
    }

    function finishDeleteConfirm(confirmed) {
        hideOfficeModal(document.getElementById('office-delete-modal'));
        if (deleteConfirmResolver) {
            const resolve = deleteConfirmResolver;
            deleteConfirmResolver = null;
            resolve(confirmed);
        }
    }

    function confirmDeleteFile(filename, role) {
        const modal = ensureDeleteConfirmModal();
        const lead = document.getElementById('office-delete-modal-lead');
        const staffNote = document.getElementById('office-delete-staff-note');
        if (lead) {
            lead.innerHTML = `Remove <strong>${escapeHtml(filename)}</strong>? It will be archived and hidden from the file list.`;
        }
        if (staffNote) {
            staffNote.hidden = role !== 'staff';
        }
        showOfficeModal(modal);
        return new Promise(resolve => { deleteConfirmResolver = resolve; });
    }

    function renderStaffProofUpload(orderId, itemId, apiPrefix) {
        return `<label class="office-upload-btn office-upload-proof"><i class="fas fa-file-image"></i> Upload proof
            <input type="file" class="office-proof-input" data-order-id="${escapeHtml(orderId)}"
                data-item-id="${escapeHtml(itemId)}" data-api-prefix="${escapeHtml(apiPrefix)}"></label>`;
    }

    function renderStaffStatusControls(office, orderId, itemId, apiPrefix) {
        const current = staffSelectStageKey(office);
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
            html += renderFileSections(office.files, orderId, itemId, apiPrefix, role, office);
            html += renderStaffStatusControls(office, orderId, itemId, apiPrefix);
            html += '</div>';
            html += '<div class="office-tracking-actions office-staff-actions">';
            html += renderStaffProofUpload(orderId, itemId, apiPrefix);
            html += '<span class="office-tracking-msg" hidden></span></div>';
        } else {
            html += renderFileSections(office.files, orderId, itemId, apiPrefix, role, office);
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
        if (lineNumber == null || lineNumber === '') return null;
        const key = String(lineNumber);
        return detailsEl.querySelector('.office-tracking-host[data-line-number="' + key + '"]');
    }

    function ensureNotifyHost(detailsEl) {
        let host = detailsEl.querySelector('.office-notify-host');
        if (!host) {
            host = document.createElement('div');
            host.className = 'office-notify-host';
            detailsEl.insertBefore(host, detailsEl.firstChild);
        }
        return host;
    }

    function notifyIsExplicitlySet(notify) {
        return !!(notify && notify.updated_at);
    }

    function notifyDefaultEnabled(notify, role) {
        if ((role === 'client' || role === 'staff') && !notifyIsExplicitlySet(notify)) return true;
        return !!(notify && notify.enabled);
    }

    function renderNotifyBlock(orderId, apiPrefix, notify, sessionEmail, customerEmail, role) {
        const enabled = notifyDefaultEnabled(notify, role);
        const savedEmail = (notify && notify.email) || '';
        const defaultEmail = (savedEmail || sessionEmail || customerEmail || '').trim();
        const emailField = `<input type="email" class="office-notify-email" placeholder="Email address" value="${escapeHtml(defaultEmail)}">`;
        const explicit = notifyIsExplicitlySet(notify) ? '1' : '0';
        const isStaff = role === 'staff';
        const labelText = isStaff
            ? 'Email production updates to:'
            : 'Email me production updates for this order';
        const staffClass = isStaff ? ' office-order-notify--staff' : '';
        return `<div class="office-order-notify${staffClass}" data-order-id="${escapeHtml(orderId)}" data-api-prefix="${escapeHtml(apiPrefix)}" data-session-email="${escapeHtml(sessionEmail || '')}" data-customer-email="${escapeHtml(customerEmail || '')}" data-notify-explicit="${explicit}" data-notify-role="${escapeHtml(role || '')}">
            <label class="office-notify-label">
                <input type="checkbox" class="office-notify-checkbox"${enabled ? ' checked' : ''}>
                <span>${escapeHtml(labelText)}</span>
            </label>
            ${emailField}
            <span class="office-notify-msg" hidden></span>
        </div>`;
    }

    function fitNotifyEmailWidth(input) {
        if (!input) return;
        const block = input.closest('.office-order-notify');
        if (!block || block.dataset.notifyRole !== 'staff') return;
        const minChars = 40;
        const text = input.value || input.placeholder || '';
        const chars = Math.max(minChars, text.length + 1);
        input.style.width = chars + 'ch';
    }

    function initNotifyEmailAutoWidth(block) {
        if (!block || block.dataset.notifyRole !== 'staff') return;
        const input = block.querySelector('.office-notify-email');
        if (!input) return;
        fitNotifyEmailWidth(input);
        if (input.dataset.notifyAutoWidth) return;
        input.dataset.notifyAutoWidth = '1';
        input.addEventListener('input', () => fitNotifyEmailWidth(input));
    }

    function paintNotifyHost(detailsEl, payload, orderId, apiPrefix, role) {
        if (role !== 'client' && role !== 'staff') return;
        const host = ensureNotifyHost(detailsEl);
        const notify = payload.notify || {};
        host.innerHTML = renderNotifyBlock(
            orderId,
            apiPrefix,
            notify,
            payload.session_email || '',
            payload.customer_email || '',
            role
        );
        if (!notifyIsExplicitlySet(notify)) {
            const block = host.querySelector('.office-order-notify');
            const email = (
                (notify && notify.email) ||
                payload.session_email ||
                payload.customer_email ||
                ''
            ).trim();
            if (block && email && block.querySelector('.office-notify-checkbox')?.checked) {
                saveNotifyPref(block, { silent: true });
            }
        }
        const block = host.querySelector('.office-order-notify');
        if (block) {
            requestAnimationFrame(() => initNotifyEmailAutoWidth(block));
        }
    }

    async function saveNotifyPref(block, options) {
        const silent = !!(options && options.silent);
        if (!block || block._notifySaving) return;
        const orderId = block.dataset.orderId;
        const apiPrefix = block.dataset.apiPrefix || '/api/client/orders';
        const checkbox = block.querySelector('.office-notify-checkbox');
        const emailInput = block.querySelector('.office-notify-email');
        const msg = block.querySelector('.office-notify-msg');
        if (!checkbox) return;
        const enabled = checkbox.checked;
        let email = '';
        if (emailInput) {
            email = (emailInput.value || '').trim();
        } else {
            email = (block.dataset.sessionEmail || block.dataset.customerEmail || '').trim();
        }
        if (enabled && !email) {
            if (!emailInput) {
                const input = document.createElement('input');
                input.type = 'email';
                input.className = 'office-notify-email';
                input.placeholder = 'Email address';
                input.value = (block.dataset.sessionEmail || block.dataset.customerEmail || '').trim();
                block.insertBefore(input, msg);
                initNotifyEmailAutoWidth(block);
                input.focus();
            }
            if (msg) {
                msg.textContent = 'Enter your email address to receive updates.';
                msg.className = 'office-notify-msg err';
                msg.hidden = false;
            }
            checkbox.checked = false;
            return;
        }
        block._notifySaving = true;
        if (msg) msg.hidden = true;
        try {
            const res = await fetch(`${apiPrefix}/${encodeURIComponent(orderId)}/notify`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ enabled, email }),
            });
            const data = await parseJsonResponse(res);
            if (!res.ok || !data.success) throw new Error(data.error || 'Could not save preference');
            if (data.notify) {
                block.dataset.sessionEmail = block.dataset.sessionEmail || email;
                block.dataset.notifyExplicit = '1';
            }
            if (msg && !silent) {
                msg.textContent = 'Saved';
                msg.className = 'office-notify-msg ok';
                msg.hidden = false;
                setTimeout(() => { if (msg.parentElement) msg.hidden = true; }, 2000);
            }
        } catch (err) {
            if (!silent) checkbox.checked = !enabled;
            if (msg && !silent) {
                msg.textContent = err.message || 'Could not save preference';
                msg.className = 'office-notify-msg err';
                msg.hidden = false;
            }
        } finally {
            block._notifySaving = false;
        }
    }

    function paintTrackingHosts(detailsEl, payload, orderId, apiPrefix, role) {
        const painted = new Set();
        (payload.items || []).forEach(item => {
            const host = findTrackingHost(detailsEl, item.line_number);
            if (!host) return;
            host.innerHTML = renderTrackingBlock(item, orderId, apiPrefix, role);
            painted.add(host);
        });
        detailsEl.querySelectorAll('.office-tracking-host').forEach(host => {
            if (painted.has(host)) return;
            if (host.querySelector('.office-tracking-loading') || !host.querySelector('.office-tracking')) {
                host.innerHTML = '<div class="office-tracking"><p class="office-tracking-error">Tracking unavailable</p></div>';
            }
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
        const key = String(orderId);
        orderTrackingCache[key] = { status: 'done', data };
        if (detailsEl) {
            detailsEl._officeTracking = data;
            detailsEl.dataset.trackingLoaded = '1';
        }
        const item = (data.items || []).find(i => i.office_item_id === itemId || i.line_number === lineNumber);
        if (!item) throw new Error('Item not found');
        const host = detailsEl ? findTrackingHost(detailsEl, item.line_number) : null;
        if (host) {
            host.innerHTML = renderTrackingBlock(item, orderId, apiPrefix, role);
            bindTrackingEvents(detailsEl);
        }
        syncOrderListBadge(orderId, data.items, role, true);
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

        const lineNumber = trackingLineNumber(btn);
        const office = getOfficeForItem(detailsEl, itemId, lineNumber);
        const warnings = office ? getSkipAheadWarnings(office, stage) : null;
        if (warnings && warnings.length) {
            const targetLabel = (ALL_STAGE_OPTIONS.find(o => o.key === stage) || {}).label || stage;
            const confirmed = await confirmSkipAhead(warnings, targetLabel);
            if (!confirmed) return;
        }

        btn.disabled = true;
        showTrackingMsg(host, 'Updating status…', true);
        let note = 'Status updated by staff';
        if (stage === 'printing') note = 'Printing';
        else if (stage === 'in_production') note = 'In Production';
        try {
            const res = await fetch(`${apiPrefix}/${encodeURIComponent(orderId)}/items/${encodeURIComponent(itemId)}/status`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ stage: stage, note: note, by: 'staff' }),
            });
            const data = await parseJsonResponse(res);
            if (!res.ok || !data.success) throw new Error(data.error || 'Could not update status');
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
                <p class="office-changes-modal-lead">To request changes to your proof, please contact our sales team by email or phone:</p>
                <p class="office-changes-modal-contact">
                    <a href="mailto:${SALES_EMAIL}" class="office-changes-contact-link" id="office-changes-mailto">${SALES_EMAIL}</a>
                    <span class="office-changes-contact-or">or</span>
                    <a href="tel:${SALES_PHONE_TEL}" class="office-changes-contact-link" id="office-changes-phone">${SALES_PHONE_DISPLAY}</a>
                </p>
                <ul class="office-changes-modal-steps">
                    <li>Quote your order number: <strong id="office-changes-order-num"></strong></li>
                    <li>Explain the changes you would like made to the proof</li>
                </ul>
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

    function showChangesModal(orderName, anchorBtn) {
        const modal = ensureChangesModal();
        const name = (orderName || '').trim() || 'your order';
        const subject = encodeURIComponent(`Order ${name} – proof change request`);
        const mailto = `mailto:${SALES_EMAIL}?subject=${subject}`;
        const orderEl = document.getElementById('office-changes-order-num');
        const mailLink = document.getElementById('office-changes-mailto');
        const phoneLink = document.getElementById('office-changes-phone');
        if (orderEl) orderEl.textContent = name;
        if (mailLink) mailLink.href = mailto;
        if (phoneLink) phoneLink.href = `tel:${SALES_PHONE_TEL}`;
        showChangesPopover(modal, anchorBtn);
    }

    function hideChangesModal() {
        hideChangesPopover(document.getElementById('office-changes-modal'));
    }

    function handleRequestChanges(btn) {
        const modal = document.getElementById('office-changes-modal');
        if (modal && !modal.hidden && modal._anchorBtn === btn) {
            hideChangesModal();
            return;
        }
        const orderName = btn.dataset.orderName;
        const detailsEl = btn.closest('.details-inner') || btn.closest('td') || document.body;
        const fromPayload = detailsEl._officeTracking && detailsEl._officeTracking.order;
        showChangesModal(orderName || fromPayload || '', btn);
    }

    async function handleDeleteFile(btn) {
        if (!btn || btn.disabled) return;
        btn.blur();
        const orderId = btn.dataset.orderId;
        const itemId = btn.dataset.itemId;
        const filename = btn.dataset.filename;
        const apiPrefix = btn.dataset.apiPrefix || '/api/orders';
        const role = roleFromApiPrefix(apiPrefix);
        let confirmed = false;
        if (role === 'staff') {
            confirmed = await confirmDeleteFile(filename, role);
        } else {
            confirmed = window.confirm('Remove this file? It will be archived and hidden from the file list.');
        }
        if (!confirmed) return;
        const tracking = btn.closest('.office-tracking');
        const detailsEl = btn.closest('.details-inner') || btn.closest('td') || document.body;
        const lineNumber = trackingLineNumber(btn);
        btn.disabled = true;
        if (tracking) showTrackingMsg(tracking, '', true);
        try {
            const res = await fetch(
                `${apiPrefix}/${encodeURIComponent(orderId)}/items/${encodeURIComponent(itemId)}/files/${encodeURIComponent(filename)}`,
                { method: 'DELETE', credentials: 'same-origin' }
            );
            const data = await parseJsonResponse(res);
            if (!res.ok || !data.success) throw new Error(data.error || 'Could not remove file');
            await refreshItemTracking(detailsEl, orderId, itemId, apiPrefix, role, lineNumber);
            const refreshed = detailsEl.querySelector('.office-tracking[data-item-id="' + CSS.escape(itemId) + '"]');
            showTrackingMsg(refreshed || tracking, 'File archived.', true);
        } catch (err) {
            showTrackingMsg(tracking, err.message || 'Could not remove file', false);
        } finally {
            btn.disabled = false;
        }
    }

    const boundRoots = new WeakSet();

    const TRACKING_LOADING_HTML = '<div class="office-tracking-loading"><i class="fas fa-spinner fa-spin"></i> Loading tracking…</div>';
    const orderTrackingCache = Object.create(null);

    function trackingDetailsEl(orderId) {
        const row = document.getElementById('details-' + String(orderId));
        return row ? (row.querySelector('.details-inner') || row) : null;
    }

    function setTrackingLoadingHosts(detailsEl) {
        if (!detailsEl) return;
        detailsEl.querySelectorAll('.office-tracking-host').forEach(h => {
            if (!h.querySelector('.office-tracking')) {
                h.innerHTML = TRACKING_LOADING_HTML;
            }
        });
    }

    function applyTrackingToDetails(orderId, data, apiPrefix, role, detailsEl) {
        const el = detailsEl || trackingDetailsEl(orderId);
        if (!el || !data) return;
        el._officeTracking = data;
        el.dataset.trackingLoaded = '1';
        paintTrackingHosts(el, data, orderId, apiPrefix, role);
        paintNotifyHost(el, data, orderId, apiPrefix, role);
    }

    function applyTrackingErrorToDetails(orderId, message, detailsEl) {
        const el = detailsEl || trackingDetailsEl(orderId);
        if (!el) return;
        el.querySelectorAll('.office-tracking-host').forEach(h => {
            h.innerHTML = '<div class="office-tracking"><p class="office-tracking-error">' + escapeHtml(message || 'Tracking unavailable') + '</p></div>';
        });
        el.dataset.trackingLoaded = '1';
    }

    async function fetchOrderTrackingPayload(orderId, apiPrefix) {
        const res = await fetch(`${apiPrefix}/${encodeURIComponent(orderId)}/tracking`, { credentials: 'same-origin' });
        const data = await parseJsonResponse(res);
        if (!res.ok || !data.success) throw new Error(data.error || 'Tracking unavailable');
        return data;
    }

    async function ensureOrderTracking(orderId, apiPrefix, detailsEl, role) {
        const key = String(orderId);
        const entry = orderTrackingCache[key];
        if (entry && entry.status === 'done') {
            applyTrackingToDetails(orderId, entry.data, apiPrefix, role, detailsEl);
            syncOrderListBadge(orderId, entry.data.items, role);
            return entry.data;
        }
        if (entry && entry.status === 'loading') {
            if (detailsEl) setTrackingLoadingHosts(detailsEl);
            try {
                const data = await entry.promise;
                if (detailsEl && orderTrackingCache[key] && orderTrackingCache[key].status === 'done') {
                    applyTrackingToDetails(orderId, orderTrackingCache[key].data, apiPrefix, role, detailsEl);
                }
                return data;
            } catch (err) {
                if (detailsEl && orderTrackingCache[key] && orderTrackingCache[key].status === 'error') {
                    applyTrackingErrorToDetails(orderId, orderTrackingCache[key].error, detailsEl);
                }
                throw err;
            }
        }
        if (detailsEl) setTrackingLoadingHosts(detailsEl);
        const promise = fetchOrderTrackingPayload(orderId, apiPrefix)
            .then(data => {
                orderTrackingCache[key] = { status: 'done', data };
                applyTrackingToDetails(orderId, data, apiPrefix, role, null);
                syncOrderListBadge(orderId, data.items, role);
                return data;
            })
            .catch(err => {
                const message = err.message || 'Tracking unavailable';
                orderTrackingCache[key] = { status: 'error', error: message };
                applyTrackingErrorToDetails(orderId, message, null);
                throw err;
            });
        orderTrackingCache[key] = { status: 'loading', promise };
        return promise;
    }

    function prefetchAllOrderTracking(orderIds, apiPrefix, role, onSettled, concurrency = 8) {
        const ids = [...new Set((orderIds || []).filter(Boolean).map(String))];
        if (!ids.length) return Promise.resolve();
        const queue = [...ids];
        async function worker() {
            while (queue.length) {
                const orderId = queue.shift();
                try {
                    await ensureOrderTracking(orderId, apiPrefix, null, role);
                } catch (_) { /* cached as error */ }
                if (onSettled) onSettled(orderId, orderTrackingCache[orderId]);
            }
        }
        return Promise.all(Array.from({ length: Math.min(concurrency, ids.length) }, () => worker()));
    }

    function applyCachedTrackingIn(container, apiPrefix, role) {
        if (!container) return;
        container.querySelectorAll('.details-row[id^="details-"]').forEach(row => {
            const orderId = row.id.replace(/^details-/, '');
            const entry = orderTrackingCache[orderId];
            const inner = row.querySelector('.details-inner') || row;
            if (entry && entry.status === 'done') {
                applyTrackingToDetails(orderId, entry.data, apiPrefix, role, inner);
            } else if (entry && entry.status === 'error') {
                applyTrackingErrorToDetails(orderId, entry.error, inner);
            } else {
                setTrackingLoadingHosts(inner);
            }
        });
    }

    function getCachedOrderIndicator(orderId) {
        const entry = orderTrackingCache[String(orderId)];
        if (entry && entry.status === 'done') return computeOrderIndicator(entry.data.items);
        if (entry && entry.status === 'error') return 'none';
        return null;
    }

    function clearOrderTrackingCache() {
        Object.keys(orderTrackingCache).forEach(k => { delete orderTrackingCache[k]; });
    }

    function bindTrackingEvents(root) {
        if (!root || boundRoots.has(root)) return;
        boundRoots.add(root);
        root.addEventListener('change', function (e) {
            if (e.target.classList.contains('office-artwork-input')) handleArtworkUpload(e.target);
            if (e.target.classList.contains('office-notify-checkbox')) {
                saveNotifyPref(e.target.closest('.office-order-notify'));
            }
            if (e.target.classList.contains('office-proof-input')) handleProofUpload(e.target);
        });
        root.addEventListener('blur', function (e) {
            if (!e.target.classList.contains('office-notify-email')) return;
            const block = e.target.closest('.office-order-notify');
            const cb = block && block.querySelector('.office-notify-checkbox');
            if (block && cb && cb.checked) saveNotifyPref(block);
        }, true);
        root.addEventListener('click', function (e) {
            const deleteBtn = e.target.closest('.office-delete-file-btn');
            if (deleteBtn) { e.preventDefault(); handleDeleteFile(deleteBtn); return; }
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
        try {
            await ensureOrderTracking(orderId, apiPrefix, detailsEl, role);
            const entry = orderTrackingCache[String(orderId)];
            if (entry && entry.status === 'done') {
                applyTrackingToDetails(orderId, entry.data, apiPrefix, role, detailsEl);
            } else if (entry && entry.status === 'error') {
                applyTrackingErrorToDetails(orderId, entry.error, detailsEl);
            }
        } catch (err) {
            applyTrackingErrorToDetails(orderId, err.message || 'Tracking unavailable', detailsEl);
        }
    }

    function syncOrderListBadge(orderId, items, role, immediate) {
        const indicator = computeOrderIndicator(items);
        updateOrderRowStatus(orderId, items);
        if (role !== 'client') {
            updateOrderRowIndicator(orderId, indicator);
        }
        if (typeof document !== 'undefined') {
            document.dispatchEvent(new CustomEvent('office-order-tracking-changed', {
                detail: { orderId: String(orderId), items, indicator, role, immediate: !!immediate },
            }));
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
        if (stage === 'printing') {
            return displayPhaseForPrinting(office) === 'in_production' ? 'production' : 'printing';
        }
        if (stage === 'received') return 'yellow';
        if (/^proof_/.test(stage)) return 'yellow';
        if (stage === 'artwork') return 'red';
        if (stage === 'approved') return 'red';
        return 'yellow';
    }

    function officeStageLabel(office) {
        if (!office) return '—';
        const stage = effectiveDisplayStage(office);
        if (!stage) return '—';
        const apiStage = (office.stages || []).find(s => (s.key || '') === (office.current_stage || ''));
        return labelForStage(stage, apiStage, maxProofReached(office)) || '—';
    }

    function computeOrderStatusLabel(items) {
        let picked = null;
        let pickedP = INDICATOR_PRIORITY.none;
        (items || []).forEach(item => {
            const office = item && item.office;
            if (!office) return;
            const t = computeItemIndicator(office);
            const p = INDICATOR_PRIORITY[t] ?? INDICATOR_PRIORITY.none;
            if (p < pickedP || !picked) {
                picked = item;
                pickedP = p;
            }
        });
        if (!picked || !picked.office) return '—';
        return officeStageLabel(picked.office);
    }

    function updateOrderRowStatus(orderId, items) {
        const label = computeOrderStatusLabel(items);
        document.querySelectorAll(`.order-status-label-slot[data-order-id="${CSS.escape(String(orderId))}"]`).forEach(slot => {
            slot.textContent = label;
        });
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

    function refreshOrderStatusLabelsIn(container) {
        if (!container) return;
        container.querySelectorAll('.order-status-label-slot[data-order-id]').forEach(slot => {
            const orderId = slot.dataset.orderId;
            const entry = orderTrackingCache[String(orderId)];
            if (entry && entry.status === 'done') {
                slot.textContent = computeOrderStatusLabel(entry.data.items);
            }
        });
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
            const items = data.items || [];
            slotEl.innerHTML = renderOrderIndicatorHtml(computeOrderIndicator(items));
            updateOrderRowStatus(orderId, items);
        } catch (_) { /* ignore */ }
    }

    function loadOrderIndicatorsIn(container, apiPrefix) {
        if (!container) return;
        container.querySelectorAll('.order-status-indicator-slot[data-order-id]').forEach(slot => {
            loadOrderIndicator(slot.dataset.orderId, apiPrefix, slot);
        });
    }

    function isCompletedIndicator(type) {
        return type === 'green';
    }

    function indicatorSortPriority(type) {
        return INDICATOR_PRIORITY[type] ?? INDICATOR_PRIORITY.none;
    }

    async function fetchOrderIndicators(orderIds, apiPrefix, concurrency = 12) {
        const result = {};
        const ids = [...new Set((orderIds || []).filter(Boolean).map(String))];
        if (!ids.length) return result;
        const queue = [...ids];
        async function worker() {
            while (queue.length) {
                const orderId = queue.shift();
                try {
                    const res = await fetch(`${apiPrefix}/${encodeURIComponent(orderId)}/indicator`, { credentials: 'same-origin' });
                    const data = await parseJsonResponse(res);
                    result[orderId] = (res.ok && data.success) ? computeOrderIndicator(data.items) : 'none';
                } catch (_) {
                    result[orderId] = 'none';
                }
            }
        }
        const workers = Array.from({ length: Math.min(concurrency, ids.length) }, () => worker());
        await Promise.all(workers);
        return result;
    }

    global.OfficeTracking = {
        loadOrderTracking,
        renderTrackingBlock,
        renderStatusBar,
        proxyFileUrl,
        bindTrackingEvents,
        computeOrderIndicator,
        computeOrderStatusLabel,
        loadOrderIndicatorsIn,
        updateOrderRowIndicator,
        updateOrderRowStatus,
        refreshOrderStatusLabelsIn,
        syncOrderListBadge,
        fetchOrderIndicators,
        isCompletedIndicator,
        indicatorSortPriority,
        renderOrderIndicatorHtml,
        prefetchAllOrderTracking,
        applyCachedTrackingIn,
        getCachedOrderIndicator,
        clearOrderTrackingCache,
        INDICATOR_PRIORITY,
    };
})(typeof window !== 'undefined' ? window : this);
