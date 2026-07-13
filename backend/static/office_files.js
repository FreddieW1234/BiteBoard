/**
 * Staff Files page — browse artwork and proof files across orders.
 */
(function () {
    'use strict';

    let searchTimer = null;
    let lastSearch = '';

    function escapeHtml(s) {
        return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function fileIcon(name) {
        const ext = (name || '').split('.').pop().toLowerCase();
        if (ext === 'pdf') return 'fa-file-pdf';
        if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'].includes(ext)) return 'fa-file-image';
        if (['zip', 'rar', '7z'].includes(ext)) return 'fa-file-archive';
        return 'fa-file';
    }

    function formatDate(iso) {
        if (!iso) return '';
        try {
            return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
        } catch (_) {
            return iso;
        }
    }

    function groupFiles(files) {
        const groups = [
            { key: 'artwork', label: 'Artwork' },
            { key: 'proof', label: 'Proofs' },
            { key: 'other', label: 'Other' },
        ];
        return groups.map(g => ({
            ...g,
            files: (files || []).filter(f => {
                const k = f.kind || 'other';
                return g.key === 'other' ? (k !== 'artwork' && k !== 'proof') : k === g.key;
            }).sort((a, b) => (b.version || 0) - (a.version || 0)),
        })).filter(g => g.files.length);
    }

    function renderFileRow(f, orderId, itemId) {
        const viewUrl = f.view_url || f.download_url;
        const downloadUrl = f.download_url || f.view_url;
        const ver = f.version ? ` v${f.version}` : '';
        const oid = orderId || f.order_id || '';
        const iid = itemId || f.office_item_id || '';
        return `<li class="of-file-row">
            <span class="of-file-info"><i class="fas ${fileIcon(f.name)}"></i>
                <span class="of-file-name">${escapeHtml(f.name)}${ver ? `<span class="of-file-ver">${escapeHtml(ver.trim())}</span>` : ''}</span>
            </span>
            <span class="of-file-actions">
                ${viewUrl ? `<a class="of-file-link" href="${escapeHtml(viewUrl)}" target="_blank" rel="noopener"><i class="fas fa-eye"></i> View</a>` : ''}
                ${downloadUrl ? `<a class="of-file-link" href="${escapeHtml(downloadUrl)}" download="${escapeHtml(f.name)}"><i class="fas fa-download"></i> Download</a>` : ''}
                ${oid && iid ? `<button type="button" class="of-file-link of-file-delete of-delete-file-btn"
                    data-order-id="${escapeHtml(oid)}" data-item-id="${escapeHtml(iid)}"
                    data-filename="${escapeHtml(f.name)}" title="Archive file"><i class="fas fa-times"></i> Remove</button>` : ''}
            </span>
        </li>`;
    }

    function renderItem(item, orderId) {
        const fileCount = (item.files || []).length;
        const groups = groupFiles(item.files);
        let body = '';
        groups.forEach(g => {
            body += `<div class="of-file-group"><div class="of-file-group-title">${escapeHtml(g.label)}</div><ul class="of-file-list">`;
            g.files.forEach(f => { body += renderFileRow(f, orderId, item.office_item_id); });
            body += '</ul></div>';
        });
        return `<div class="of-item">
            <button type="button" class="of-item-head" aria-expanded="false">
                <i class="fas fa-chevron-right of-chevron"></i>
                <i class="fas fa-cube of-item-icon"></i>
                <span class="of-item-meta">
                    <span class="of-order-title">${escapeHtml(item.title || 'Line item')}</span>
                    ${item.current_stage ? `<span class="of-item-sub">Stage: ${escapeHtml(item.current_stage.replace(/_/g, ' '))}</span>` : ''}
                </span>
                <span class="of-badge">${fileCount} file${fileCount === 1 ? '' : 's'}</span>
            </button>
            <div class="of-item-body">${body}</div>
        </div>`;
    }

    function renderOrder(order) {
        const itemCount = (order.items || []).length;
        const fileCount = (order.items || []).reduce((n, it) => n + (it.files || []).length, 0);
        let itemsHtml = '';
        (order.items || []).forEach(it => { itemsHtml += renderItem(it, order.order_id); });
        const sub = [order.customer_name, formatDate(order.processed_at)].filter(Boolean).join(' · ');
        return `<div class="of-order">
            <button type="button" class="of-order-head" aria-expanded="false">
                <i class="fas fa-chevron-right of-chevron"></i>
                <i class="fas fa-folder of-order-icon"></i>
                <span class="of-order-meta">
                    <span class="of-order-title">${escapeHtml(order.order_name || 'Order')}</span>
                    ${sub ? `<span class="of-order-sub">${escapeHtml(sub)}</span>` : ''}
                </span>
                <span class="of-badge">${itemCount} item${itemCount === 1 ? '' : 's'} · ${fileCount} file${fileCount === 1 ? '' : 's'}</span>
                <a class="of-order-link" href="/app/Orders" title="Open Orders page"><i class="fas fa-external-link-alt"></i> Orders</a>
            </button>
            <div class="of-order-body">${itemsHtml}</div>
        </div>`;
    }

    function bindTree(root) {
        root.querySelectorAll('.of-order-head, .of-item-head').forEach(btn => {
            btn.addEventListener('click', e => {
                if (e.target.closest('.of-order-link') || e.target.closest('.of-delete-file-btn')) return;
                e.preventDefault();
                const parent = btn.closest('.of-order, .of-item');
                if (!parent) return;
                const open = parent.classList.toggle('open');
                btn.setAttribute('aria-expanded', open ? 'true' : 'false');
            });
        });
    }

    async function parseJsonResponse(res) {
        const text = await res.text();
        if (!text) return res.ok ? {} : { error: 'Request failed (' + res.status + ')' };
        try {
            return JSON.parse(text);
        } catch (_) {
            throw new Error('Invalid server response');
        }
    }

    async function handleDeleteFile(btn) {
        if (!btn || btn.disabled) return;
        btn.blur();
        const orderId = btn.dataset.orderId;
        const itemId = btn.dataset.itemId;
        const filename = btn.dataset.filename;
        if (!orderId || !itemId || !filename) return;
        if (!window.confirm('Remove this file? It will be archived and hidden from the file list.')) return;
        btn.disabled = true;
        const row = btn.closest('.of-file-row');
        try {
            const url = `/api/orders/${encodeURIComponent(orderId)}/items/${encodeURIComponent(itemId)}/files/${encodeURIComponent(filename)}`;
            const res = await fetch(url, { method: 'DELETE', credentials: 'same-origin' });
            const data = await parseJsonResponse(res);
            if (!res.ok || !data.success) throw new Error(data.error || 'Could not archive file');
            const searchInput = document.getElementById('of-search');
            lastSearch = searchInput ? searchInput.value.trim() : lastSearch;
            await loadFiles(lastSearch);
        } catch (err) {
            btn.disabled = false;
            if (row) {
                let errEl = row.querySelector('.of-file-error');
                if (!errEl) {
                    errEl = document.createElement('span');
                    errEl.className = 'of-file-error';
                    row.appendChild(errEl);
                }
                errEl.textContent = err.message || 'Could not archive file';
            } else {
                window.alert(err.message || 'Could not archive file');
            }
        }
    }

    function bindDeleteButtons(root) {
        root.addEventListener('click', e => {
            const btn = e.target.closest('.of-delete-file-btn');
            if (!btn) return;
            e.preventDefault();
            e.stopPropagation();
            handleDeleteFile(btn);
        });
    }

    function setStats(data) {
        const el = document.getElementById('of-stats');
        if (!el) return;
        if (!data || !data.success) {
            el.textContent = '';
            return;
        }
        const oc = data.order_count || 0;
        const fc = data.total_files || 0;
        el.textContent = `${oc} order${oc === 1 ? '' : 's'} · ${fc} file${fc === 1 ? '' : 's'}`;
    }

    async function loadFiles(search) {
        const panel = document.getElementById('of-panel');
        if (!panel) return;
        panel.innerHTML = '<div class="of-state"><i class="fas fa-spinner fa-spin"></i> Loading files…</div>';
        setStats(null);
        const params = new URLSearchParams();
        if (search) params.set('search', search);
        try {
            const res = await fetch('/api/office-files?' + params.toString(), { credentials: 'same-origin' });
            const data = await res.json();
            if (!res.ok || !data.success) throw new Error(data.error || 'Could not load files');
            setStats(data);
            const orders = data.orders || [];
            if (!orders.length) {
                panel.innerHTML = '<div class="of-state">No files found' + (search ? ' for this search.' : '.') + '</div>';
                return;
            }
            let html = '<div class="of-tree">';
            orders.forEach(o => { html += renderOrder(o); });
            html += '</div>';
            panel.innerHTML = html;
            bindTree(panel);
        } catch (err) {
            panel.innerHTML = `<div class="of-state" style="color:#dc2626;"><i class="fas fa-exclamation-circle"></i> ${escapeHtml(err.message || 'Failed to load files')}</div>`;
        }
    }

    function init() {
        const searchInput = document.getElementById('of-search');
        const refreshBtn = document.getElementById('of-refresh');
        const panel = document.getElementById('of-panel');
        if (panel) bindDeleteButtons(panel);
        if (searchInput) {
            searchInput.addEventListener('input', () => {
                clearTimeout(searchTimer);
                searchTimer = setTimeout(() => {
                    const q = searchInput.value.trim();
                    if (q === lastSearch) return;
                    lastSearch = q;
                    loadFiles(q);
                }, 350);
            });
        }
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => {
                lastSearch = searchInput ? searchInput.value.trim() : '';
                loadFiles(lastSearch);
            });
        }
        loadFiles('');
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
