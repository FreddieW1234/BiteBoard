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
        return rows.filter(row => {
            const iso = rowFilterDateIso(row);
            if (!iso) return false;
            return iso >= range.start && iso <= range.end;
        });
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
            <th>Carrier</th>
            </tr></thead><tbody>`;

        displayRows.forEach((row, idx) => {
            const key = rowKey(row);
            const dispatchPrint = formatDisplayDate(row.dispatch_date_iso);
            const carrierPrint = carrierLabel(row.carrier);
            html += `<tr data-idx="${idx}" data-key="${escapeHtml(key)}" data-row-id="${escapeHtml(key)}">`;
            html += `<td class="diary-dispatch-cell">
                <input type="date" class="diary-date-input diary-screen-only" data-field="dispatch"
                    value="${escapeHtml(row.dispatch_date_iso || '')}"
                    aria-label="Dispatch date for ${escapeHtml(row.product_label)}">
                <span class="diary-print-only">${escapeHtml(dispatchPrint)}</span>
            </td>`;
            html += `<td class="diary-requested">${escapeHtml(row.requested_date || '—')}</td>`;
            html += `<td><a class="diary-order-link diary-screen-only" href="/app/Orders#order-${escapeHtml(row.order_id)}">${escapeHtml(row.order_name)}</a><span class="diary-print-only">${escapeHtml(row.order_name)}</span></td>`;
            html += `<td class="diary-product">${escapeHtml(row.product_label)}</td>`;
            html += `<td class="diary-company">${escapeHtml(row.company || '—')}</td>`;
            html += `<td>
                <div class="diary-carrier-cell">
                    <select class="diary-carrier-select diary-screen-only ${carrierClass(row.carrier)}" data-field="carrier" aria-label="Carrier for ${escapeHtml(row.product_label)}">
                        ${CARRIERS.map(c => `<option value="${escapeHtml(c.value)}"${c.value === row.carrier ? ' selected' : ''}>${escapeHtml(c.label)}</option>`).join('')}
                    </select>
                    <span class="diary-print-only diary-print-carrier ${carrierClass(row.carrier)}">${escapeHtml(carrierPrint)}</span>
                    <span class="diary-save-msg diary-screen-only" data-msg="${escapeHtml(key)}" hidden></span>
                </div>
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

    function onTableChange(e) {
        const tr = e.target.closest('tr[data-row-id]');
        if (!tr) return;
        const row = findRowByKey(tr.dataset.rowId);
        if (!row) return;

        if (e.target.dataset.field === 'dispatch') {
            scheduleSave(row, {
                dispatch_date: e.target.value || '',
                dispatch_manual: true,
            });
        }
        if (e.target.dataset.field === 'carrier') {
            e.target.className = 'diary-carrier-select diary-screen-only ' + carrierClass(e.target.value);
            scheduleSave(row, { carrier: e.target.value });
        }
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
        const origTitle = document.title;
        document.title = ' ';
        const restoreTitle = () => {
            document.title = origTitle;
            window.removeEventListener('afterprint', restoreTitle);
        };
        window.addEventListener('afterprint', restoreTitle);
        window.print();
    }

    async function loadDiary() {
        const pill = document.getElementById('diary-count-pill');
        const content = document.getElementById('diary-content');
        if (content) {
            content.innerHTML = '<div class="diary-table-card"><div class="diary-empty"><i class="fas fa-spinner fa-spin"></i> Loading diary…</div></div>';
        }
        try {
            const res = await fetch('/api/diary', { credentials: 'same-origin' });
            const data = await res.json();
            if (!res.ok || !data.success) throw new Error(data.error || 'Could not load diary');
            allRows = data.rows || [];
            if (pill && !document.getElementById('diary-range-label')) {
                pill.textContent = `${allRows.length} line${allRows.length === 1 ? '' : 's'}`;
            }
            renderTable();
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
