(function () {
    'use strict';

    const RATE_DEBOUNCE_MS = 450;

    const CARRIER_HINTS = [
        { label: 'Evri', needles: ['evri', 'hermes'] },
        { label: 'DPD', needles: ['dpd'] },
        { label: 'Royal Mail', needles: ['royal_mail', 'royal mail', 'stamps_com'] },
        { label: 'FedEx', needles: ['fedex'] },
    ];

    let overlay = null;
    let rateTimer = null;
    let rateRequestId = 0;
    let state = {
        orderId: '',
        orderName: '',
        itemId: '',
        productLabel: '',
        prep: null,
        rates: [],
        selectedRateId: '',
        providers: {},
        ratesLoading: false,
        carrierNotes: [],
        carriersQueried: [],
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
        const weight = parseFloat(weightRaw);
        return {
            shipment_type: body.querySelector('[name="shipment_type"]:checked')?.value || 'parcel',
            weight_kg: Number.isFinite(weight) && weight > 0 ? weight : null,
            length_cm: parseDim('#ship-length'),
            width_cm: parseDim('#ship-width'),
            height_cm: parseDim('#ship-height'),
        };
    }

    function hasWeight(form) {
        return form && Number.isFinite(form.weight_kg) && form.weight_kg > 0;
    }

    function showNeedWeight() {
        const area = overlay?.querySelector('#ship-rates-area');
        if (area) {
            area.innerHTML = '<p class="ship-msg info">Enter the package weight (kg) to load rates.</p>';
        }
        setConfirmEnabled(false);
        state.ratesLoading = false;
        state.rates = [];
        state.selectedRateId = '';
        setMsg('Weight is required before rates can load.', 'info');
    }

    function renderBody() {
        const prep = state.prep;
        const body = overlay.querySelector('#ship-modal-body');
        if (!prep || !body) return;

        const shipTo = prep.ship_to || {};
        const addressText = shipTo.text || (shipTo.lines || []).join('\n') || '—';
        const defs = prep.defaults || {};
        const palletDisabled = !state.providers.palletways;
        const palletHint = palletDisabled
            ? '<p class="ship-pallet-notice">Palletways direct API not connected yet.</p>'
            : '<p class="ship-pallet-notice">Palletways key present — direct integration pending.</p>';
        const knownWeight = Number.isFinite(Number(defs.weight_kg)) && Number(defs.weight_kg) > 0
            ? Number(defs.weight_kg)
            : null;
        const weightVal = knownWeight != null ? knownWeight : '';
        const weightHint = knownWeight == null
            ? '<p class="ship-weight-hint">Shopify has no weight for this line — enter it before rates load.</p>'
            : '';

        body.innerHTML = `
            <div id="ship-modal-msg" hidden></div>
            <div class="ship-top-row">
                <div class="ship-section">
                    <div class="ship-section-title">Deliver to</div>
                    <div class="ship-address">${escapeHtml(addressText)}</div>
                </div>
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
            </div>
            <div class="ship-section">
                <div class="ship-section-title">Package</div>
                <div class="ship-fields">
                    <div class="ship-field">
                        <label for="ship-weight">Weight (kg) <span class="ship-required">required</span></label>
                        <input type="number" id="ship-weight" min="0.01" step="0.001" value="${weightVal}" placeholder="e.g. 2.5" required>
                    </div>
                    <div class="ship-field">
                        <label for="ship-length">Length (cm)</label>
                        <input type="number" id="ship-length" min="0.1" step="0.1" placeholder="optional">
                    </div>
                    <div class="ship-field">
                        <label for="ship-width">Width (cm)</label>
                        <input type="number" id="ship-width" min="0.1" step="0.1" placeholder="optional">
                    </div>
                    <div class="ship-field">
                        <label for="ship-height">Height (cm)</label>
                        <input type="number" id="ship-height" min="0.1" step="0.1" placeholder="optional">
                    </div>
                </div>
                ${weightHint}
            </div>
            <div class="ship-section ship-rates">
                <div class="ship-section-title">Rates by carrier</div>
                <div id="ship-rates-area">
                    <p class="ship-msg info">Enter the package weight (kg) to load rates.</p>
                </div>
            </div>`;

        body.querySelectorAll('.ship-type-btn').forEach(label => {
            const input = label.querySelector('input');
            if (!input || input.disabled) return;
            label.addEventListener('click', () => {
                body.querySelectorAll('.ship-type-btn').forEach(l => l.classList.remove('active'));
                label.classList.add('active');
                input.checked = true;
                scheduleRates();
            });
        });

        ['#ship-weight', '#ship-length', '#ship-width', '#ship-height'].forEach(sel => {
            const input = body.querySelector(sel);
            if (!input) return;
            input.addEventListener('input', scheduleRates);
            input.addEventListener('change', scheduleRates);
        });
    }

    function showRatesLoading() {
        const area = overlay?.querySelector('#ship-rates-area');
        if (!area) return;
        area.innerHTML = `
            <div class="ship-rates-loading">
                <span class="ship-spinner" aria-hidden="true"></span>
                <span>Loading rates…</span>
            </div>`;
    }

    function carrierGroupLabel(rate) {
        const text = `${rate.carrier_friendly_name || ''} ${rate.carrier_code || ''}`.toLowerCase();
        for (const hint of CARRIER_HINTS) {
            if (hint.needles.some(n => text.includes(n))) return hint.label;
        }
        return (rate.carrier_friendly_name || rate.carrier_code || 'Other')
            .trim() || 'Other';
    }

    function matchesCarrier(label, haystack) {
        const text = String(haystack || '').toLowerCase();
        const hint = CARRIER_HINTS.find(h => h.label === label);
        if (hint) return hint.needles.some(n => text.includes(n));
        return text.includes(String(label).toLowerCase());
    }

    function groupRatesByCarrier(rates, carrierNotes, carriersQueried) {
        const groups = new Map();

        (rates || []).forEach(rate => {
            const label = carrierGroupLabel(rate);
            if (!groups.has(label)) {
                groups.set(label, { label, rates: [], note: null, minPrice: Infinity });
            }
            const g = groups.get(label);
            g.rates.push(rate);
            const price = Number(rate.price);
            if (Number.isFinite(price) && price < g.minPrice) g.minPrice = price;
        });

        (carrierNotes || []).forEach(note => {
            const label = note.carrier || 'Other';
            if (!groups.has(label)) {
                groups.set(label, { label, rates: [], note: note.message || '', minPrice: Infinity });
            } else if (!groups.get(label).rates.length && note.message) {
                groups.get(label).note = note.message;
            }
        });

        const queriedText = (carriersQueried || []).join(' ');
        CARRIER_HINTS.forEach(hint => {
            if (!matchesCarrier(hint.label, queriedText)) return;
            if (!groups.has(hint.label)) {
                groups.set(hint.label, {
                    label: hint.label,
                    rates: [],
                    note: `${hint.label} is connected but returned no rates for this package.`,
                    minPrice: Infinity,
                });
            }
        });

        return Array.from(groups.values()).sort((a, b) => {
            const aHas = a.rates.length > 0;
            const bHas = b.rates.length > 0;
            if (aHas && bHas) return a.minPrice - b.minPrice;
            if (aHas) return -1;
            if (bHas) return 1;
            return a.label.localeCompare(b.label);
        });
    }

    function renderRates(rates, hint) {
        const area = overlay?.querySelector('#ship-rates-area');
        if (!area) return;

        const groups = groupRatesByCarrier(rates, state.carrierNotes, state.carriersQueried);
        if (!groups.length) {
            area.innerHTML = `<p class="ship-msg err">${escapeHtml(hint || 'No rates returned for this package.')}</p>`;
            return;
        }

        area.innerHTML = groups.map(group => {
            const sorted = group.rates.slice().sort((a, b) => (a.price || 0) - (b.price || 0));
            if (!sorted.length) {
                return `
                    <div class="ship-carrier-row ship-carrier-empty">
                        <div class="ship-carrier-name">${escapeHtml(group.label)}</div>
                        <p class="ship-carrier-note">${escapeHtml(group.note || 'No rates for this package.')}</p>
                    </div>`;
            }
            const cards = sorted.map(r => {
                const selected = r.rate_id === state.selectedRateId ? ' selected' : '';
                const days = r.delivery_days != null
                    ? `<span class="ship-rate-days">${escapeHtml(String(r.delivery_days))} day${r.delivery_days === 1 ? '' : 's'}</span>`
                    : '';
                return `
                    <button type="button" class="ship-rate-card${selected}" data-rate-id="${escapeHtml(r.rate_id)}">
                        <span class="ship-rate-card-service">${escapeHtml(r.service_type || r.service_code || 'Service')}</span>
                        ${days}
                        <span class="ship-rate-card-price">${escapeHtml(formatMoney(r.price, r.currency))}</span>
                    </button>`;
            }).join('');
            return `
                <div class="ship-carrier-row">
                    <div class="ship-carrier-name">${escapeHtml(group.label)}</div>
                    <div class="ship-rate-cards">${cards}</div>
                </div>`;
        }).join('');

        area.querySelectorAll('.ship-rate-card').forEach(card => {
            card.addEventListener('click', () => {
                state.selectedRateId = card.dataset.rateId || '';
                area.querySelectorAll('.ship-rate-card').forEach(c => {
                    c.classList.toggle('selected', c === card);
                });
                setConfirmEnabled(!!state.selectedRateId);
            });
        });
    }

    function cancelPendingRates() {
        if (rateTimer) {
            clearTimeout(rateTimer);
            rateTimer = null;
        }
        rateRequestId += 1;
        state.ratesLoading = false;
    }

    function scheduleRates() {
        if (!state.prep || !overlay || overlay.hidden) return;
        setConfirmEnabled(false);
        state.selectedRateId = '';
        state.rates = [];

        const form = readForm();
        if (!hasWeight(form)) {
            if (rateTimer) {
                clearTimeout(rateTimer);
                rateTimer = null;
            }
            rateRequestId += 1;
            showNeedWeight();
            return;
        }

        state.ratesLoading = true;
        showRatesLoading();
        setMsg('', 'info');

        if (rateTimer) clearTimeout(rateTimer);
        rateTimer = setTimeout(() => {
            rateTimer = null;
            fetchRates();
        }, RATE_DEBOUNCE_MS);
    }

    async function fetchRates() {
        if (!state.orderId || !state.prep) return;
        const form = readForm();
        if (!hasWeight(form)) {
            showNeedWeight();
            return;
        }

        const requestId = ++rateRequestId;
        state.ratesLoading = true;
        setConfirmEnabled(false);
        state.selectedRateId = '';
        showRatesLoading();

        if (form.shipment_type === 'pallet') {
            if (requestId !== rateRequestId) return;
            state.ratesLoading = false;
            state.rates = [];
            state.carrierNotes = [];
            renderRates([], 'Palletways is not configured yet. Use parcel or wait for your API key.');
            setMsg('Palletways is not configured yet.', 'err');
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
            if (requestId !== rateRequestId) return;
            if (!res.ok || !data.success) throw new Error(data.error || 'Could not get rates');

            state.ratesLoading = false;
            state.rates = data.rates || [];
            state.carrierNotes = data.carrier_notes || [];
            state.carriersQueried = data.carriers_queried || [];
            if (state.rates.length) {
                state.selectedRateId = state.rates[0].rate_id;
                setConfirmEnabled(true);
            }
            renderRates(state.rates, data.error_hint || '');
            if (state.rates.length) {
                setMsg(`${state.rates.length} rate(s) loaded.`, 'ok');
            } else {
                setMsg(data.error_hint || 'No rates returned for this package.', 'err');
            }
        } catch (err) {
            if (requestId !== rateRequestId) return;
            state.ratesLoading = false;
            state.rates = [];
            state.carrierNotes = [];
            renderRates([], err.message || 'Rate lookup failed');
            setMsg(err.message || 'Rate lookup failed', 'err');
        }
    }

    function renderShipSuccess(data) {
        const body = overlay?.querySelector('#ship-modal-body');
        if (!body) return;

        const print = data.print || {};
        let printLine = 'Label ready.';
        if (print.skipped) {
            printLine = 'Nothing was sent to a printer (office print server not configured).';
        } else if (print.success === false) {
            printLine = `Print failed: ${print.error || 'unknown'}.`;
        } else {
            printLine = 'Sent to office printer.';
        }

        const downloadBtn = data.label_download_url
            ? `<a class="ship-btn-secondary" href="${escapeHtml(data.label_download_url)}" target="_blank" rel="noopener">Open label</a>`
            : (data.label_zpl_base64
                ? `<button type="button" class="ship-btn-secondary" id="ship-download-zpl">Download ZPL label</button>`
                : '');

        body.innerHTML = `
            <div class="ship-success">
                <p class="ship-msg ok">Label created successfully.</p>
                <dl class="ship-success-meta">
                    <div><dt>Carrier</dt><dd>${escapeHtml(data.carrier_label || data.carrier || '—')}</dd></div>
                    <div><dt>Service</dt><dd>${escapeHtml(data.service_code || '—')}</dd></div>
                    <div><dt>Tracking</dt><dd class="ship-tracking">${escapeHtml(data.tracking_number || '—')}</dd></div>
                </dl>
                <p class="ship-success-print">${escapeHtml(printLine)}</p>
                ${data.sandbox_note ? `<p class="ship-msg info">${escapeHtml(data.sandbox_note)}</p>` : ''}
                <p class="ship-success-hint">Check the Diary Ship column for this tracking number. Close when you’re done.</p>
                <div class="ship-success-actions">
                    ${downloadBtn}
                    <button type="button" class="ship-btn-primary" id="ship-success-done">Done</button>
                </div>
            </div>`;

        body.querySelector('#ship-success-done')?.addEventListener('click', () => {
            if (typeof window.__diaryReload === 'function') window.__diaryReload();
            closeModal();
        });

        const zplBtn = body.querySelector('#ship-download-zpl');
        if (zplBtn && data.label_zpl_base64) {
            zplBtn.addEventListener('click', () => {
                const bin = atob(data.label_zpl_base64);
                const bytes = new Uint8Array(bin.length);
                for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
                const blob = new Blob([bytes], { type: 'application/octet-stream' });
                const a = document.createElement('a');
                a.href = URL.createObjectURL(blob);
                a.download = `${(data.tracking_number || 'fedex-label').replace(/\s+/g, '_')}.zpl`;
                a.click();
                URL.revokeObjectURL(a.href);
            });
        }

        const confirmBtn = overlay.querySelector('[data-ship-action="confirm"]');
        if (confirmBtn) {
            confirmBtn.disabled = true;
            confirmBtn.textContent = 'Done';
        }
    }

    async function confirmShip() {
        if (!state.selectedRateId) {
            setMsg('Select a rate first.', 'err');
            return;
        }
        const form = readForm();
        if (!hasWeight(form)) {
            showNeedWeight();
            setMsg('Enter the package weight in kg before creating a label.', 'err');
            return;
        }
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
            if (typeof window.__diaryMarkShipped === 'function') {
                window.__diaryMarkShipped(
                    data.order_name || state.orderName,
                    data.item_id || state.itemId,
                    data
                );
            }
            renderShipSuccess(data);
            if (typeof window.__diaryReload === 'function') {
                window.__diaryReload();
            }
        } catch (err) {
            setMsg(err.message || 'Could not purchase label', 'err');
            if (btn) btn.disabled = false;
        }
    }

    function closeModal() {
        cancelPendingRates();
        if (overlay) overlay.hidden = true;
        state = {
            orderId: '', orderName: '', itemId: '', productLabel: '',
            prep: null, rates: [], selectedRateId: '', providers: {},
            ratesLoading: false, carrierNotes: [], carriersQueried: [],
        };
        document.body.style.overflow = '';
    }

    async function openShippingModal(orderId, orderName, itemId, productLabel) {
        ensureOverlay();
        cancelPendingRates();
        state.orderId = String(orderId);
        state.orderName = orderName || '';
        state.itemId = (itemId || '').trim();
        state.productLabel = (productLabel || '').trim();
        state.rates = [];
        state.selectedRateId = '';
        state.carrierNotes = [];
        state.carriersQueried = [];
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
            if (state.itemId && (prep.items || []).length !== 1) {
                throw new Error(
                    'This Ship action must cover one order line only, but the server returned ' +
                    `${(prep.items || []).length} line(s). Hard-refresh the Diary page and try again.`
                );
            }
            state.prep = prep;
            state.providers = (status.providers || prep.providers || {});
            const carrierMap = state.providers.carriers || {};
            state.carriersQueried = Object.values(carrierMap)
                .map(c => (c && c.label) || '')
                .filter(Boolean);
            if (!state.carriersQueried.length) {
                state.carriersQueried = ['Royal Mail', 'FedEx', 'Palletways'];
            }

            const fedexReady = !!(state.providers.carriers?.fedex?.ready || state.providers.fedex);
            if (state.providers.ship_from_ready === false) {
                setMsg(
                    'Ship-from address is missing. Set SHIP_FROM_LINE1 and SHIP_FROM_POSTCODE on Render.',
                    'err'
                );
            } else if (!fedexReady && !state.providers.royal_mail && !state.providers.palletways) {
                setMsg(
                    'No carrier APIs ready yet. Add FedEx / Royal Mail / Palletways credentials on Render.',
                    'info'
                );
            }
            renderBody();
            scheduleRates();
        } catch (err) {
            overlay.querySelector('#ship-modal-body').innerHTML = '';
            setMsg(err.message || 'Could not open shipping', 'err');
        }
    }

    window.openShippingModal = openShippingModal;
})();
