(function () {
    'use strict';

    let overlay = null;
    let state = {
        orderId: '',
        orderName: '',
        itemId: '',
        productLabel: '',
        prep: null,
        rates: [],
        selectedRateId: '',
        providers: {},
    };

    function escapeHtml(s) {
        return String(s || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function formatMoney(amount, currency) {
        if (amount == null || amount === '') return '—';
        const n = Number(amount);
        if (Number.isNaN(n)) return String(amount);
        try {
            return new Intl.NumberFormat('en-GB', {
                style: 'currency',
                currency: (currency || 'GBP').toUpperCase(),
            }).format(n);
        } catch (_) {
            return `£${n.toFixed(2)}`;
        }
    }

    function ensureOverlay() {
        if (overlay) return overlay;
        overlay = document.createElement('div');
        overlay.className = 'ship-overlay';
        overlay.hidden = true;
        overlay.innerHTML = `
            <div class="ship-modal" role="dialog" aria-modal="true" aria-labelledby="ship-modal-title">
                <div class="ship-modal-header">
                    <h2 id="ship-modal-title">Ship order</h2>
                    <button type="button" class="ship-modal-close" aria-label="Close">&times;</button>
                </div>
                <div class="ship-modal-body" id="ship-modal-body"></div>
                <div class="ship-modal-footer">
                    <button type="button" class="ship-btn-secondary" data-ship-action="cancel">Cancel</button>
                    <button type="button" class="ship-btn-secondary" data-ship-action="quote">Get rates</button>
                    <button type="button" class="ship-btn-primary" data-ship-action="confirm" disabled>
                        Confirm &amp; print label
                    </button>
                </div>
            </div>`;
        document.body.appendChild(overlay);

        overlay.addEventListener('click', e => {
            if (e.target === overlay) closeModal();
        });
        overlay.querySelector('.ship-modal-close')?.addEventListener('click', closeModal);
        overlay.querySelector('[data-ship-action="cancel"]')?.addEventListener('click', closeModal);
        overlay.querySelector('[data-ship-action="quote"]')?.addEventListener('click', fetchRates);
        overlay.querySelector('[data-ship-action="confirm"]')?.addEventListener('click', confirmShip);
        overlay.querySelector('.ship-modal')?.addEventListener('click', e => e.stopPropagation());

        return overlay;
    }

    function setMsg(text, kind) {
        const el = overlay?.querySelector('#ship-modal-msg');
        if (!el) return;
        if (!text) {
            el.hidden = true;
            el.textContent = '';
            return;
        }
        el.hidden = false;
        el.className = 'ship-msg ' + (kind || 'info');
        el.textContent = text;
    }

    function setConfirmEnabled(on) {
        const btn = overlay?.querySelector('[data-ship-action="confirm"]');
        if (btn) btn.disabled = !on;
    }

    function readForm() {
        const body = overlay?.querySelector('#ship-modal-body');
        if (!body) return {};
        const parseDim = id => {
            const raw = body.querySelector(id)?.value;
            if (raw === '' || raw == null) return null;
            const n = parseFloat(raw);
            return Number.isFinite(n) && n > 0 ? n : null;
        };
        const weightRaw = body.querySelector('#ship-weight')?.value;
        const weightFallback = state.prep?.defaults?.weight_kg || 1;
        const weight = parseFloat(weightRaw);
        return {
            shipment_type: body.querySelector('[name="shipment_type"]:checked')?.value || 'parcel',
            weight_kg: Number.isFinite(weight) && weight > 0 ? weight : weightFallback,
            length_cm: parseDim('#ship-length'),
            width_cm: parseDim('#ship-width'),
            height_cm: parseDim('#ship-height'),
        };
    }

    function renderBody() {
        const prep = state.prep;
        const body = overlay.querySelector('#ship-modal-body');
        if (!prep || !body) return;

        const shipTo = prep.ship_to || {};
        const addressText = shipTo.text || (shipTo.lines || []).join('\n') || '—';
        const itemsHtml = (prep.items || []).map(it =>
            `<li>${escapeHtml(it.title)}${it.quantity > 1 ? ` × ${it.quantity}` : ''}</li>`
        ).join('') || '<li>—</li>';

        const defs = prep.defaults || {};
        const palletDisabled = !state.providers.palletways;
        const palletHint = palletDisabled
            ? '<p class="ship-pallet-notice">Palletways API key pending — pallet shipping unavailable.</p>'
            : '';
        const weightVal = defs.weight_kg != null ? defs.weight_kg : '';

        body.innerHTML = `
            <div id="ship-modal-msg" hidden></div>
            <div class="ship-grid">
                <div>
                    <div class="ship-section">
                        <div class="ship-section-title">Deliver to</div>
                        <div class="ship-address">${escapeHtml(addressText)}</div>
                    </div>
                    <div class="ship-section">
                        <div class="ship-section-title">${state.itemId ? 'Shipping this line' : 'Order lines'}</div>
                        <ul class="ship-items">${itemsHtml}</ul>
                    </div>
                </div>
                <div>
                    <div class="ship-section">
                        <div class="ship-section-title">Shipment type</div>
                        <div class="ship-type-toggle">
                            <label class="ship-type-btn active">
                                <input type="radio" name="shipment_type" value="parcel" checked hidden> Parcel
                            </label>
                            <label class="ship-type-btn${palletDisabled ? ' disabled' : ''}">
                                <input type="radio" name="shipment_type" value="pallet"${palletDisabled ? ' disabled' : ''} hidden> Pallet
                            </label>
                        </div>
                        ${palletHint}
                    </div>
                    <div class="ship-section ship-package-section">
                        <div class="ship-section-title">Package</div>
                        <div class="ship-fields">
                            <div class="ship-field">
                                <label for="ship-weight">Weight (kg)</label>
                                <input type="number" id="ship-weight" min="0.01" step="0.001" value="${weightVal}">
                            </div>
                            <div class="ship-field">
                                <label for="ship-length">Length (cm)</label>
                                <input type="number" id="ship-length" min="1" step="1" placeholder="—">
                            </div>
                            <div class="ship-field">
                                <label for="ship-width">Width (cm)</label>
                                <input type="number" id="ship-width" min="1" step="1" placeholder="—">
                            </div>
                            <div class="ship-field">
                                <label for="ship-height">Height (cm)</label>
                                <input type="number" id="ship-height" min="1" step="1" placeholder="—">
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            <div class="ship-section ship-rates">
                <div class="ship-section-title">Rates</div>
                <div id="ship-rates-area"><p class="ship-msg info">Click “Get rates” to load carrier options.</p></div>
            </div>`;

        body.querySelectorAll('.ship-type-btn').forEach(label => {
            const input = label.querySelector('input');
            if (!input || input.disabled) return;
            label.addEventListener('click', () => {
                body.querySelectorAll('.ship-type-btn').forEach(l => l.classList.remove('active'));
                label.classList.add('active');
                input.checked = true;
            });
        });
    }

    function renderRates(rates) {
        const area = overlay?.querySelector('#ship-rates-area');
        if (!area) return;
        if (!rates.length) {
            area.innerHTML = '<p class="ship-msg err">No rates returned for this package.</p>';
            return;
        }
        area.innerHTML = `<ul class="ship-rate-list">${rates.map(r => `
            <li class="ship-rate-item${r.rate_id === state.selectedRateId ? ' selected' : ''}" data-rate-id="${escapeHtml(r.rate_id)}">
                <input type="radio" name="ship_rate" value="${escapeHtml(r.rate_id)}"${r.rate_id === state.selectedRateId ? ' checked' : ''}>
                <div class="ship-rate-main">
                    <div class="ship-rate-carrier">${escapeHtml(r.carrier_friendly_name || r.carrier_code)}</div>
                    <div class="ship-rate-service">${escapeHtml(r.service_type || r.service_code)}</div>
                </div>
                <div class="ship-rate-price">${escapeHtml(formatMoney(r.price, r.currency))}</div>
            </li>`).join('')}</ul>`;

        area.querySelectorAll('.ship-rate-item').forEach(item => {
            item.addEventListener('click', () => {
                state.selectedRateId = item.dataset.rateId || '';
                area.querySelectorAll('.ship-rate-item').forEach(i => i.classList.toggle('selected', i === item));
                const radio = item.querySelector('input');
                if (radio) radio.checked = true;
                setConfirmEnabled(!!state.selectedRateId);
            });
        });
    }

    async function fetchRates() {
        setMsg('Loading rates…', 'info');
        setConfirmEnabled(false);
        state.selectedRateId = '';
        const form = readForm();
        if (form.shipment_type === 'pallet') {
            setMsg('Palletways is not configured yet. Use parcel or wait for your API key.', 'err');
            return;
        }
        try {
            const res = await fetch('/api/shipping/quote', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({
                    order_id: state.orderId,
                    item_id: state.itemId || undefined,
                    ...form,
                }),
            });
            const data = await res.json();
            if (!res.ok || !data.success) throw new Error(data.error || 'Could not get rates');
            state.rates = data.rates || [];
            if (state.rates.length) {
                state.selectedRateId = state.rates[0].rate_id;
                setConfirmEnabled(true);
            }
            renderRates(state.rates);
            setMsg(state.rates.length ? `${state.rates.length} rate(s) loaded.` : '', 'ok');
        } catch (err) {
            state.rates = [];
            renderRates([]);
            setMsg(err.message || 'Rate lookup failed', 'err');
        }
    }

    async function confirmShip() {
        if (!state.selectedRateId) {
            setMsg('Select a rate first.', 'err');
            return;
        }
        const form = readForm();
        const btn = overlay.querySelector('[data-ship-action="confirm"]');
        if (btn) btn.disabled = true;
        setMsg('Purchasing label…', 'info');
        try {
            const res = await fetch('/api/shipping/ship', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({
                    order_id: state.orderId,
                    item_id: state.itemId || undefined,
                    rate_id: state.selectedRateId,
                    ...form,
                }),
            });
            const data = await res.json();
            if (!res.ok || !data.success) throw new Error(data.error || 'Ship failed');

            let msg = `Label created. Tracking: ${data.tracking_number || '—'}`;
            const print = data.print || {};
            if (print.skipped) {
                msg += ' (Print server not configured — label saved in ShipStation.)';
            } else if (print.success === false) {
                msg += ` Print failed: ${print.error || 'unknown'}. Reprint from ShipStation if needed.`;
            } else {
                msg += ' Sent to office printer.';
            }
            setMsg(msg, 'ok');

            if (typeof window.__diaryReload === 'function') {
                setTimeout(() => {
                    window.__diaryReload();
                    closeModal();
                }, 1200);
            } else {
                setTimeout(closeModal, 2000);
            }
        } catch (err) {
            setMsg(err.message || 'Could not purchase label', 'err');
            if (btn) btn.disabled = false;
        }
    }

    function closeModal() {
        if (overlay) overlay.hidden = true;
        state = {
            orderId: '', orderName: '', itemId: '', productLabel: '',
            prep: null, rates: [], selectedRateId: '', providers: {},
        };
        document.body.style.overflow = '';
    }

    async function openShippingModal(orderId, orderName, itemId, productLabel) {
        ensureOverlay();
        state.orderId = String(orderId);
        state.orderName = orderName || '';
        state.itemId = (itemId || '').trim();
        state.productLabel = (productLabel || '').trim();
        state.rates = [];
        state.selectedRateId = '';
        setConfirmEnabled(false);

        overlay.hidden = false;
        document.body.style.overflow = 'hidden';
        const titleParts = [orderName ? `Ship ${orderName}` : 'Ship order'];
        if (state.productLabel) {
            titleParts.push(state.productLabel);
        }
        overlay.querySelector('#ship-modal-title').textContent = titleParts.join(' — ');
        overlay.querySelector('#ship-modal-body').innerHTML =
            '<p class="ship-msg info">Loading order…</p>';
        setMsg('', 'info');

        try {
            const itemQuery = state.itemId
                ? `?item_id=${encodeURIComponent(state.itemId)}`
                : '';
            const [prepRes, statusRes] = await Promise.all([
                fetch(`/api/shipping/prepare/${encodeURIComponent(orderId)}${itemQuery}`, { credentials: 'same-origin' }),
                fetch('/api/shipping/status', { credentials: 'same-origin' }),
            ]);
            const prep = await prepRes.json();
            const status = await statusRes.json();
            if (!prepRes.ok || !prep.success) throw new Error(prep.error || 'Could not load order');
            state.prep = prep;
            state.providers = (status.providers || prep.providers || {});
            if (!state.providers.shipstation) {
                setMsg('ShipStation is not configured. Set SHIPSTATION_API_KEY on the server.', 'err');
            } else if (state.providers.ship_from_ready === false) {
                setMsg(
                    'Ship-from address is missing. In ShipStation: Settings → Shipping → Warehouses, ' +
                    'or set SHIPSTATION_ORIGIN_* env vars on Render.',
                    'err'
                );
            }
            renderBody();
        } catch (err) {
            overlay.querySelector('#ship-modal-body').innerHTML = '';
            setMsg(err.message || 'Could not open shipping', 'err');
        }
    }

    window.openShippingModal = openShippingModal;
})();
