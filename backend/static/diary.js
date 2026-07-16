(function () {
    'use strict';

    const CARRIERS = [
        { value: '', label: '—' },
        { value: 'royal_mail', label: 'Royal Mail' },
        { value: 'fedex', label: 'FedEx' },
        { value: 'frenni', label: 'Frenni' },
    ];

    const SORT_OPTIONS = [
        { value: 'dispatch_close', label: 'Closest dispatch' },
        { value: 'dispatch_far', label: 'Furthest dispatch' },
        { value: 'requested_close', label: 'Closest requested' },
        { value: 'requested_far', label: 'Furthest requested' },
    ];

    let allRows = [];
    let sortMode = localStorage.getItem('diary-sort') || 'dispatch_close';
    let viewMode = localStorage.getItem('diary-view') || 'week';
    let focusDate = parseIsoDate(localStorage.getItem('diary-focus')) || startOfDay(new Date());
    let printerReady = null; // null = unknown, true/false after health check
    const saveTimers = Object.create(null);

    function escapeHtml(s) {
        return String(s || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function rowKey(row) {
        return `${row.order_name}::${row.item_id}`;
    }

    function carrierClass(value) {
        return value ? `carrier-${value}` : '';
    }

    function carrierLabel(value) {
        return CARRIERS.find(c => c.value === value)?.label || '—';
    }

    function pad2(n) {
        return String(n).padStart(2, '0');
    }

    function toIsoDate(d) {
        return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
    }

    function parseIsoDate(iso) {
        if (!iso || typeof iso !== 'string') return null;
        const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso.trim());
        if (!m) return null;
        const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
        return Number.isNaN(d.getTime()) ? null : startOfDay(d);
    }

    function startOfDay(d) {
        return new Date(d.getFullYear(), d.getMonth(), d.getDate());
    }

    function addDays(d, n) {
        const x = new Date(d);
        x.setDate(x.getDate() + n);
        return startOfDay(x);
    }

    function startOfWeek(d) {
        const x = startOfDay(d);
        const day = x.getDay();
        const diff = day === 0 ? -6 : 1 - day;
        return addDays(x, diff);
    }

    function endOfWeek(d) {
        return addDays(startOfWeek(d), 6);
    }

    function startOfMonth(d) {
        return new Date(d.getFullYear(), d.getMonth(), 1);
    }

    function endOfMonth(d) {
        return new Date(d.getFullYear(), d.getMonth() + 1, 0);
    }

    function formatDisplayDate(iso) {
        const d = parseIsoDate(iso);
        if (!d) return '—';
        return d.toLocaleDateString('en-GB', { day: '2-digit', month: '2-digit', year: 'numeric' });
    }

    function formatLongDate(d) {
        return d.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
    }

    function formatMonthYear(d) {
        return d.toLocaleDateString('en-GB', { month: 'long', year: 'numeric' });
    }

    function rowFilterDateIso(row) {
        return (row.dispatch_date_iso || row.requested_date_iso || '').trim();
    }

    function getViewRange() {
        if (viewMode === 'day') {
            const iso = toIsoDate(focusDate);
            return { start: iso, end: iso, label: formatLongDate(focusDate) };
        }
        if (viewMode === 'week') {
            const start = startOfWeek(focusDate);
            const end = endOfWeek(focusDate);
            return {
                start: toIsoDate(start),
                end: toIsoDate(end),
                label: `Week ${start.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })} – ${end.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}`,
            };
        }
        const start = startOfMonth(focusDate);
        const end = endOfMonth(focusDate);
        return {
            start: toIsoDate(start),
            end: toIsoDate(end),
            label: formatMonthYear(focusDate),
        };
    }

    function filterRows(rows) {
        const range = getViewRange();
        // Once any line for an order falls in the current view, show every line
        // for that order (separate shipments for the same Shopify order).
        const ordersInRange = new Set();
        rows.forEach(row => {
            const iso = rowFilterDateIso(row);
            if (iso && iso >= range.start && iso <= range.end) {
                ordersInRange.add(row.order_name);
            }
        });
        return rows.filter(row => ordersInRange.has(row.order_name));
    }

    function sortRows(rows) {
        const list = rows.slice();
        const far = sortMode.endsWith('_far');
        const field = sortMode.startsWith('requested') ? 'requested_date_iso' : 'dispatch_date_iso';
        list.sort((a, b) => {
            const av = a[field] || '';
            const bv = b[field] || '';
            if (!av && !bv) return (a.order_name || '').localeCompare(b.order_name || '');
            if (!av) return 1;
            if (!bv) return -1;
            if (av === bv) return (a.order_name || '').localeCompare(b.order_name || '');
            return far ? bv.localeCompare(av) : av.localeCompare(bv);
        });
        return list;
    }

    function getDisplayRows() {
        return sortRows(filterRows(allRows));
    }

    function persistPrefs() {
        localStorage.setItem('diary-sort', sortMode);
        localStorage.setItem('diary-view', viewMode);
        localStorage.setItem('diary-focus', toIsoDate(focusDate));
    }

    function updateToolbarMeta() {
        const pill = document.getElementById('diary-count-pill');
        const rangeLabel = document.getElementById('diary-range-label');
        const display = getDisplayRows();
        const range = getViewRange();
        if (pill) {
            pill.textContent = `${display.length} line${display.length === 1 ? '' : 's'} shown`;
        }
        if (rangeLabel) {
            rangeLabel.textContent = range.label;
        }
        document.querySelectorAll('.diary-view-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.view === viewMode);
        });
        const focusInput = document.getElementById('diary-focus-input');
        if (focusInput) {
            focusInput.value = toIsoDate(focusDate);
        }
    }

    function renderTable() {
        const content = document.getElementById('diary-content');
        if (!content) return;

        const displayRows = getDisplayRows();
        const range = getViewRange();
        const sortLabel = SORT_OPTIONS.find(o => o.value === sortMode)?.label || sortMode;
        const viewLabel = viewMode.charAt(0).toUpperCase() + viewMode.slice(1);

        if (!displayRows.length) {
            content.innerHTML = `<div class="diary-table-card" id="diary-print-area">
                <div class="diary-print-header">
                    <h2>Bite Promotions — Dispatch Diary</h2>
                    <p>${escapeHtml(viewLabel)} view · ${escapeHtml(range.label)} · Sorted by ${escapeHtml(sortLabel)}</p>
                </div>
                <div class="diary-empty">No lines in this ${escapeHtml(viewMode)}.</div>
            </div>`;
            updateToolbarMeta();
            return;
        }

        let html = `<div class="diary-table-card" id="diary-print-area">
            <div class="diary-print-header">
                <h2>Bite Promotions — Dispatch Diary</h2>
                <p>${escapeHtml(viewLabel)} view · ${escapeHtml(range.label)} · Sorted by ${escapeHtml(sortLabel)}</p>
                <p class="diary-print-meta">Printed ${escapeHtml(new Date().toLocaleString('en-GB'))}</p>
            </div>
            <div class="diary-table-scroll"><table class="diary-table"><thead><tr>
            <th>Dispatch date</th>
            <th>Requested delivery date</th>
            <th>Order number</th>
            <th>Product</th>
            <th>Company</th>
            <th>Ship</th>
            </tr></thead><tbody>`;

        displayRows.forEach((row, idx) => {
            const key = rowKey(row);
            const dispatchPrint = formatDisplayDate(row.dispatch_date_iso);
            const carrierPrint = carrierLabel(row.carrier);
            const showShipBtn = !row.shipped;
            html += `<tr data-idx="${idx}" data-key="${escapeHtml(key)}" data-row-id="${escapeHtml(key)}">`;
            html += `<td class="diary-dispatch-cell">
                <div class="diary-date-wrap diary-screen-only">
                    <span class="diary-date-display">${escapeHtml(dispatchPrint)}</span>
                    <input type="date" class="diary-date-input" data-field="dispatch"
                        value="${escapeHtml(row.dispatch_date_iso || '')}"
                        tabindex="-1" aria-hidden="true">
                    <button type="button" class="diary-date-open" aria-label="Choose dispatch date for ${escapeHtml(row.product_label)}">
                        <i class="far fa-calendar" aria-hidden="true"></i>
                    </button>
                    <span class="diary-save-msg diary-screen-only" data-msg="${escapeHtml(key)}" hidden></span>
                </div>
                <span class="diary-print-only">${escapeHtml(dispatchPrint)}</span>
            </td>`;
            html += `<td class="diary-requested">${escapeHtml(row.requested_date || '—')}</td>`;
            html += `<td><a class="diary-order-link diary-screen-only" href="/app/Orders#order-${escapeHtml(row.order_id)}">${escapeHtml(row.order_name)}</a><span class="diary-print-only">${escapeHtml(row.order_name)}</span></td>`;
            html += `<td class="diary-product">${escapeHtml(row.product_label)}</td>`;
            html += `<td class="diary-company">${escapeHtml(row.company || '—')}</td>`;
            html += `<td class="diary-ship-cell">
                <div class="diary-screen-only">`;
            if (row.shipped) {
                const pending = !!row.label_status_pending;
                const hasStored = !!(row.can_print_label || row.can_reprint);
                let title = 'Send stored ZPL label to the office Zebra';
                let disabled = false;
                let label = 'Print label';
                if (pending) {
                    title = 'Checking office server for a saved label…';
                    label = 'Checking…';
                    disabled = true;
                } else if (row.label_check_failed) {
                    title = 'Label check missed it — click to reprint from office server';
                    disabled = false;
                } else if (!hasStored) {
                    title = 'No ZPL stored on the office server yet — ship again to save the label';
                    disabled = true;
                } else if (printerReady === false) {
                    title = 'Office printer may be offline — click to try anyway';
                }
                const printBtn = `<button type="button" class="diary-print-label-btn"
                    data-print-order-name="${escapeHtml(row.order_name)}"
                    data-print-item-id="${escapeHtml(row.item_id)}"
                    ${disabled ? 'disabled' : ''}
                    title="${escapeHtml(title)}">
                    <i class="fas fa-print"></i> ${escapeHtml(label)}
                </button>`;
                html += `<div class="diary-shipped-info">
                    <div class="diary-shipped-carrier ${carrierClass(row.carrier)}">${escapeHtml(row.carrier_label || carrierPrint)}</div>
                    ${row.tracking_number ? `<div class="diary-shipped-tracking">${escapeHtml(row.tracking_number)}</div>` : ''}
                    ${printBtn}
                </div>`;
            } else if (showShipBtn) {
                html += `<button type="button" class="diary-ship-btn"
                    data-ship-order-id="${escapeHtml(row.order_id)}"
                    data-ship-order-name="${escapeHtml(row.order_name)}"
                    data-ship-item-id="${escapeHtml(row.item_id)}"
                    data-ship-product="${escapeHtml(row.product_label)}">
                    <i class="fas fa-truck"></i> Ship
                </button>`;
            } else {
                html += `<span class="diary-shipped-tracking">—</span>`;
            }
            html += `</div>
                <span class="diary-print-only diary-print-carrier ${carrierClass(row.carrier)}">${escapeHtml(row.shipped ? (row.tracking_number ? row.tracking_number + ' · ' : '') + carrierPrint : '—')}</span>
            </td>`;
            html += '</tr>';
        });

        html += '</tbody></table></div></div>';
        content.innerHTML = html;
        updateToolbarMeta();
    }

    function findRowByKey(key) {
        return allRows.find(r => rowKey(r) === key);
    }

    function showMsg(key, text, ok) {
        const el = document.querySelector(`.diary-save-msg[data-msg="${CSS.escape(key)}"]`);
        if (!el) return;
        el.textContent = text;
        el.className = 'diary-save-msg diary-screen-only' + (ok ? '' : ' err');
        el.hidden = !text;
        if (text && ok) {
            setTimeout(() => { el.hidden = true; }, 1500);
        }
    }

    async function saveRow(row, patch) {
        const key = rowKey(row);
        const body = {
            order_name: row.order_name,
            item_id: row.item_id,
            ...patch,
        };
        try {
            const res = await fetch('/api/diary/entry', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify(body),
            });
            const data = await res.json();
            if (!res.ok || !data.success) throw new Error(data.error || 'Save failed');
            if (patch.dispatch_date !== undefined) {
                row.dispatch_date_iso = patch.dispatch_date;
                row.dispatch_manual = !!patch.dispatch_manual;
                row.dispatch_date = formatDisplayDate(patch.dispatch_date);
            }
            if (patch.carrier !== undefined) {
                row.carrier = patch.carrier;
                row.carrier_label = carrierLabel(patch.carrier);
            }
            showMsg(key, 'Saved', true);
        } catch (err) {
            showMsg(key, err.message || 'Save failed', false);
        }
    }

    function scheduleSave(row, patch) {
        const key = rowKey(row);
        clearTimeout(saveTimers[key]);
        saveTimers[key] = setTimeout(() => saveRow(row, patch), 400);
    }

    function onTableClick(e) {
        const btn = e.target.closest('.diary-date-open');
        if (!btn) return;
        const input = btn.closest('.diary-date-wrap')?.querySelector('.diary-date-input');
        if (!input) return;
        if (typeof input.showPicker === 'function') {
            try {
                input.showPicker();
                return;
            } catch (_) { /* fall through */ }
        }
        input.focus();
    }

    function onTableChange(e) {
        const tr = e.target.closest('tr[data-row-id]');
        if (!tr) return;
        const row = findRowByKey(tr.dataset.rowId);
        if (!row) return;

        if (e.target.dataset.field === 'dispatch') {
            const wrap = e.target.closest('.diary-date-wrap');
            const display = wrap?.querySelector('.diary-date-display');
            if (display) {
                display.textContent = formatDisplayDate(e.target.value || '');
            }
            scheduleSave(row, {
                dispatch_date: e.target.value || '',
                dispatch_manual: true,
                carrier: row.carrier || '',
            });
        }
    }

    function showDiaryToast(message, kind) {
        let el = document.getElementById('diary-toast');
        if (!el) {
            el = document.createElement('div');
            el.id = 'diary-toast';
            el.className = 'diary-toast';
            el.setAttribute('role', 'status');
            document.body.appendChild(el);
        }
        el.textContent = message || '';
        el.className = `diary-toast diary-toast-${kind === 'err' ? 'err' : 'ok'}`;
        el.hidden = false;
        clearTimeout(showDiaryToast._timer);
        showDiaryToast._timer = setTimeout(() => {
            el.hidden = true;
        }, kind === 'err' ? 6000 : 3200);
    }

    async function refreshPrinterHealth() {
        try {
            const res = await fetch('/api/shipping/status', { credentials: 'same-origin' });
            const data = await res.json();
            if (!res.ok || !data.success) {
                printerReady = false;
                return;
            }
            const providers = data.providers || {};
            if (typeof providers.printer_ready === 'boolean') {
                printerReady = providers.printer_ready;
            } else {
                printerReady = !!providers.print_server;
            }
        } catch (_) {
            printerReady = false;
        }
    }

    async function printStoredLabel(orderName, itemId, btn) {
        if (!orderName || !itemId || !btn || btn.disabled) return;
        const original = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Printing…';
        try {
            const res = await fetch('/api/shipping/reprint', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ order_name: orderName, item_id: itemId }),
            });
            const data = await res.json();
            if (!res.ok || !data.success) {
                throw new Error(data.error || 'Print failed');
            }
            showDiaryToast(data.message || 'Sent to printer', 'ok');
            btn.innerHTML = '<i class="fas fa-check"></i> Sent';
            setTimeout(() => {
                btn.disabled = printerReady === false;
                btn.innerHTML = original || '<i class="fas fa-print"></i> Print label';
            }, 1600);
        } catch (err) {
            showDiaryToast(err.message || 'Could not print label', 'err');
            btn.disabled = printerReady === false;
            btn.innerHTML = original || '<i class="fas fa-print"></i> Print label';
        }
    }

    function onTableClickShip(e) {
        const printBtn = e.target.closest('.diary-print-label-btn, .diary-reprint-btn');
        if (printBtn) {
            printStoredLabel(
                printBtn.dataset.printOrderName || printBtn.dataset.reprintOrderName || '',
                printBtn.dataset.printItemId || printBtn.dataset.reprintItemId || '',
                printBtn
            );
            return;
        }
        const shipBtn = e.target.closest('.diary-ship-btn');
        if (shipBtn) {
            const orderId = shipBtn.dataset.shipOrderId;
            const orderName = shipBtn.dataset.shipOrderName || '';
            if (orderId && typeof window.openShippingModal === 'function') {
                window.openShippingModal(
                    orderId,
                    orderName,
                    shipBtn.dataset.shipItemId || '',
                    shipBtn.dataset.shipProduct || ''
                );
            }
            return;
        }
        onTableClick(e);
    }

    function navigatePeriod(delta) {
        if (viewMode === 'day') {
            focusDate = addDays(focusDate, delta);
        } else if (viewMode === 'week') {
            focusDate = addDays(focusDate, delta * 7);
        } else {
            focusDate = new Date(focusDate.getFullYear(), focusDate.getMonth() + delta, 1);
        }
        persistPrefs();
        renderTable();
    }

    function goToday() {
        focusDate = startOfDay(new Date());
        persistPrefs();
        renderTable();
    }

    function printDiary() {
        window.print();
    }

    async function refreshLabelStatus() {
        const shipped = allRows.filter(r => r.shipped && r.order_name && r.item_id);
        if (!shipped.length) return;
        shipped.forEach(r => { r.label_status_pending = true; });
        renderTable();
        try {
            const res = await fetch('/api/shipping/labels-status', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({
                    items: shipped.map(r => ({
                        order_name: r.order_name,
                        item_id: r.item_id,
                    })),
                }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok || !data.success) {
                console.warn('Label status check failed', data.error || res.status);
                // Leave optimistic can_print_label so staff can still try Print.
                shipped.forEach(r => { r.label_status_pending = false; });
                renderTable();
                return;
            }
            const seen = new Set();
            for (const result of data.results || []) {
                const row = allRows.find(
                    r => r.order_name === result.order_name && r.item_id === result.item_id
                );
                if (!row) continue;
                seen.add(`${row.order_name}::${row.item_id}`);
                if (result.has_label) {
                    row.can_print_label = true;
                    row.can_reprint = true;
                    row.label_check_failed = false;
                    row.label_filename = result.filename || '';
                    console.info(
                        'Office label found',
                        result.order_name,
                        result.item_id,
                        result.filename || result.source || ''
                    );
                } else {
                    // Shipped lines may still have a label on disk — don't hard-disable Print.
                    const shippedLine = !!(row.tracking_number || row.label_id);
                    if (shippedLine) {
                        row.can_print_label = true;
                        row.can_reprint = true;
                        row.label_check_failed = true;
                    } else {
                        row.can_print_label = false;
                        row.can_reprint = false;
                        row.label_check_failed = false;
                    }
                    console.warn('No office label for', result.order_name, result.item_id, result.error || '');
                }
                row.label_status_pending = false;
            }
            shipped.forEach(r => {
                if (!seen.has(`${r.order_name}::${r.item_id}`)) {
                    r.label_status_pending = false;
                }
            });
            renderTable();
        } catch (err) {
            console.warn('Label status check error', err);
            shipped.forEach(r => { r.label_status_pending = false; });
            renderTable();
        }
    }

    async function loadDiary() {
        const pill = document.getElementById('diary-count-pill');
        const content = document.getElementById('diary-content');
        if (content) {
            content.innerHTML = '<div class="diary-table-card"><div class="diary-empty"><i class="fas fa-spinner fa-spin"></i> Loading diary…</div></div>';
        }
        try {
            const [res] = await Promise.all([
                fetch('/api/diary', { credentials: 'same-origin' }),
                refreshPrinterHealth(),
            ]);
            const data = await res.json();
            if (!res.ok || !data.success) throw new Error(data.error || 'Could not load diary');
            allRows = data.rows || [];
            if (pill && !document.getElementById('diary-range-label')) {
                pill.textContent = `${allRows.length} line${allRows.length === 1 ? '' : 's'}`;
            }
            renderTable();
            // Office label presence is checked separately so refresh doesn't miss
            // labels already on the office server (and doesn't download full ZPL).
            refreshLabelStatus();
        } catch (err) {
            if (pill) pill.textContent = 'Error';
            if (content) {
                content.innerHTML = `<div class="diary-table-card"><div class="diary-empty">${escapeHtml(err.message || 'Could not load diary')}</div></div>`;
            }
        }
    }

    document.getElementById('diary-refresh-btn')?.addEventListener('click', loadDiary);
    document.getElementById('diary-print-btn')?.addEventListener('click', printDiary);
    document.getElementById('diary-prev-btn')?.addEventListener('click', () => navigatePeriod(-1));
    document.getElementById('diary-next-btn')?.addEventListener('click', () => navigatePeriod(1));
    document.getElementById('diary-today-btn')?.addEventListener('click', goToday);
    document.getElementById('diary-sort-select')?.addEventListener('change', e => {
        sortMode = e.target.value;
        persistPrefs();
        renderTable();
    });
    document.getElementById('diary-focus-input')?.addEventListener('change', e => {
        const d = parseIsoDate(e.target.value);
        if (d) {
            focusDate = d;
            persistPrefs();
            renderTable();
        }
    });
    document.querySelectorAll('.diary-view-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            viewMode = btn.dataset.view || 'week';
            persistPrefs();
            renderTable();
        });
    });
    document.getElementById('diary-content')?.addEventListener('change', onTableChange);
    document.getElementById('diary-content')?.addEventListener('click', onTableClickShip);

    function markRowShipped(orderName, itemId, info) {
        const name = (orderName || '').trim();
        const id = (itemId || '').trim();
        if (!name || !id) return false;
        const row = allRows.find(r => r.order_name === name && r.item_id === id);
        if (!row) return false;
        row.shipped = true;
        row.carrier = info?.carrier || row.carrier || 'fedex';
        row.carrier_label = info?.carrier_label || carrierLabel(row.carrier);
        row.tracking_number = info?.tracking_number || info?.label_id || row.tracking_number || '';
        row.label_id = info?.label_id || row.label_id || '';
        row.can_print_label = !!(info?.label_stored || info?.has_zpl || info?.label_zpl_base64);
        row.can_reprint = row.can_print_label;
        row.label_status_pending = !!row.can_print_label;
        renderTable();
        if (row.can_print_label) {
            refreshLabelStatus();
        }
        return true;
    }

    window.__diaryReload = loadDiary;
    window.__diaryMarkShipped = markRowShipped;

    const sortSelect = document.getElementById('diary-sort-select');
    if (sortSelect) {
        sortSelect.innerHTML = SORT_OPTIONS.map(o =>
            `<option value="${escapeHtml(o.value)}"${o.value === sortMode ? ' selected' : ''}>${escapeHtml(o.label)}</option>`
        ).join('');
    }
    const focusInput = document.getElementById('diary-focus-input');
    if (focusInput) {
        focusInput.value = toIsoDate(focusDate);
    }
    document.querySelectorAll('.diary-view-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.view === viewMode);
    });

    loadDiary();
})();
