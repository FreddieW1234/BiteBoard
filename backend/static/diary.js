(function () {
    'use strict';

    const CARRIERS = [
        { value: '', label: '—' },
        { value: 'royal_mail', label: 'Royal Mail' },
        { value: 'fedex', label: 'FedEx' },
        { value: 'frenni', label: 'Frenni' },
    ];

    let rows = [];
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

    function isoToInputValue(iso) {
        return iso || '';
    }

    function carrierClass(value) {
        return value ? `carrier-${value}` : '';
    }

    function renderTable() {
        const content = document.getElementById('diary-content');
        if (!content) return;

        if (!rows.length) {
            content.innerHTML = '<div class="diary-table-card"><div class="diary-empty">No product lines found in recent orders.</div></div>';
            return;
        }

        let html = '<div class="diary-table-card"><div class="diary-table-scroll"><table class="diary-table"><thead><tr>';
        html += '<th>Dispatch date</th>';
        html += '<th>Requested delivery date</th>';
        html += '<th>Order number</th>';
        html += '<th>Product</th>';
        html += '<th>Carrier</th>';
        html += '</tr></thead><tbody>';

        rows.forEach((row, idx) => {
            const key = rowKey(row);
            html += `<tr data-idx="${idx}" data-key="${escapeHtml(key)}">`;
            html += `<td>
                <input type="date" class="diary-date-input" data-field="dispatch"
                    value="${escapeHtml(isoToInputValue(row.dispatch_date_iso))}"
                    aria-label="Dispatch date for ${escapeHtml(row.product_label)}">
                <span class="diary-save-msg" data-msg="${escapeHtml(key)}" hidden></span>
            </td>`;
            html += `<td class="diary-requested">${escapeHtml(row.requested_date || '—')}</td>`;
            html += `<td><a class="diary-order-link" href="/app/Orders#order-${escapeHtml(row.order_id)}">${escapeHtml(row.order_name)}</a></td>`;
            html += `<td class="diary-product">${escapeHtml(row.product_label)}</td>`;
            html += `<td>
                <select class="diary-carrier-select ${carrierClass(row.carrier)}" data-field="carrier" aria-label="Carrier for ${escapeHtml(row.product_label)}">
                    ${CARRIERS.map(c => `<option value="${escapeHtml(c.value)}"${c.value === row.carrier ? ' selected' : ''}>${escapeHtml(c.label)}</option>`).join('')}
                </select>
            </td>`;
            html += '</tr>';
        });

        html += '</tbody></table></div></div>';
        content.innerHTML = html;
    }

    function showMsg(key, text, ok) {
        const el = document.querySelector(`.diary-save-msg[data-msg="${CSS.escape(key)}"]`);
        if (!el) return;
        el.textContent = text;
        el.className = 'diary-save-msg' + (ok ? '' : ' err');
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
                const parts = patch.dispatch_date.split('-');
                if (parts.length === 3) {
                    row.dispatch_date = `${parts[2]}.${parts[1]}.${parts[0]}`;
                }
            }
            if (patch.carrier !== undefined) {
                row.carrier = patch.carrier;
                row.carrier_label = CARRIERS.find(c => c.value === patch.carrier)?.label || '';
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
        const tr = e.target.closest('tr[data-idx]');
        if (!tr) return;
        const idx = parseInt(tr.dataset.idx, 10);
        const row = rows[idx];
        if (!row) return;

        if (e.target.dataset.field === 'dispatch') {
            scheduleSave(row, {
                dispatch_date: e.target.value || '',
                dispatch_manual: true,
            });
        }
        if (e.target.dataset.field === 'carrier') {
            e.target.className = 'diary-carrier-select ' + carrierClass(e.target.value);
            scheduleSave(row, { carrier: e.target.value });
        }
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
            rows = data.rows || [];
            if (pill) pill.textContent = `${rows.length} line${rows.length === 1 ? '' : 's'}`;
            renderTable();
        } catch (err) {
            if (pill) pill.textContent = 'Error';
            if (content) {
                content.innerHTML = `<div class="diary-table-card"><div class="diary-empty">${escapeHtml(err.message || 'Could not load diary')}</div></div>`;
            }
        }
    }

    document.getElementById('diary-refresh-btn')?.addEventListener('click', loadDiary);
    document.getElementById('diary-content')?.addEventListener('change', onTableChange);

    loadDiary();
})();
