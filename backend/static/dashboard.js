/* Staff home dashboard - renders /api/dashboard into #dash. */
(function () {
    const root = document.getElementById('dash');
    if (!root) return;

    const gbp = new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP', maximumFractionDigits: 0 });
    const gbp2 = new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP' });
    const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const orderUrl = name => '/app/Orders?q=' + encodeURIComponent(name || '');
    const dayFmt = new Intl.DateTimeFormat('en-GB', { weekday: 'short', day: 'numeric', month: 'short' });
    const shortDate = iso => { const d = new Date(iso + 'T12:00:00'); return isNaN(d) ? '' : dayFmt.format(d); };
    let dispatchView = 'today';
    let lastData = null;

    // "Good afternoon, Freddie" - the signed-in person's username.
    function greeting() {
        const h = new Date().getHours();
        const hello = h < 12 ? 'Good morning' : (h < 18 ? 'Good afternoon' : 'Good evening');
        const user = ((document.getElementById('dash') || {}).dataset || {}).user || '';
        return user ? `${hello}, ${esc(user)}` : hello;
    }

    function sectionError(data, key) {
        const msg = (data.errors || {})[key];
        return msg ? `<div class="err"><i class="fas fa-triangle-exclamation"></i> Couldn't load this: ${esc(msg)}</div>` : '';
    }

    function deltaHtml(now, before) {
        if (!before) return '';
        const pct = Math.round(((now - before) / before) * 100);
        const up = pct >= 0;
        return `<span class="delta ${up ? 'up' : 'down'}"><i class="fas fa-arrow-${up ? 'up' : 'down'}"></i>${Math.abs(pct)}%</span>`;
    }

    function statTiles(data) {
        const s = data.sales;
        if (!s) return `<div class="dash-card span-12">${sectionError(data, 'sales')}</div>`;
        const t = s.totals;
        const n = b => `${b.orders} order${b.orders === 1 ? '' : 's'}`;
        const tile = (label, value, meta) => `<div class="dash-card stat span-4">
            <div class="label">${label}</div><div class="value">${value}</div><div class="meta">${meta}</div></div>`;
        return tile('Today', gbp.format(t.today.net), n(t.today))
            + tile('This week', gbp.format(t.week.net), n(t.week))
            + tile('This month', gbp.format(t.month.net),
                `${n(t.month)} ${deltaHtml(t.month.net, t.last_month_same_point.net)}
                 <span title="Same days last month">vs ${gbp.format(t.last_month_same_point.net)}</span>`);
    }

    function chartCard(data) {
        const s = data.sales;
        const body = s ? `<div class="chart-wrap" id="dash-chart"></div>
            <div class="chart-foot">Takings per day, excluding VAT. Last month in total: ${gbp.format(s.totals.last_month.net)}.</div>`
            : sectionError(data, 'sales');
        return `<div class="dash-card span-8"><h2>Sales &ndash; last 30 days <a class="more" href="/app/Orders">All orders</a></h2>${body}</div>`;
    }

    function drawChart(days) {
        const wrap = document.getElementById('dash-chart');
        if (!wrap) return;
        const W = Math.max(wrap.clientWidth, 300), H = 240, padL = 48, padR = 6, padT = 10, padB = 24;
        const max = Math.max(...days.map(d => d.net), 1);
        const step = niceStep(max / 3);
        const top = Math.ceil(max / step) * step;
        const innerW = W - padL - padR, innerH = H - padT - padB;
        const slot = innerW / days.length;
        const barW = Math.max(slot - 2, 2);  // 2px gap between bars
        const y = v => padT + innerH - (v / top) * innerH;
        let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Daily sales for the last 30 days">`;
        for (let v = 0; v <= top + 0.001; v += step) {
            svg += `<line class="gridline" x1="${padL}" x2="${W - padR}" y1="${y(v)}" y2="${y(v)}"/>`
                + `<text class="axis-label" x="${padL - 6}" y="${y(v) + 4}" text-anchor="end">${gbp.format(v)}</text>`;
        }
        const todayIso = days.length ? days[days.length - 1].date : '';
        days.forEach((d, i) => {
            const x = padL + i * slot + (slot - barW) / 2;
            const h = Math.max(innerH * (d.net / top), d.net > 0 ? 2 : 0);
            const yTop = padT + innerH - h;
            const r = Math.min(4, barW / 2, h);
            // Rounded top, square base on the baseline.
            const path = h > 0 ? `M${x},${padT + innerH} V${yTop + r} Q${x},${yTop} ${x + r},${yTop} H${x + barW - r} Q${x + barW},${yTop} ${x + barW},${yTop + r} V${padT + innerH} Z` : '';
            svg += `<rect class="hit" data-i="${i}" x="${padL + i * slot}" y="${padT}" width="${slot}" height="${innerH}"/>`;
            if (path) svg += `<path class="bar${d.date === todayIso ? ' today' : ''}" data-i="${i}" d="${path}"/>`;
            const dt = new Date(d.date + 'T12:00:00');
            if (i % 5 === (days.length - 1) % 5) {
                svg += `<text class="axis-label" x="${padL + i * slot + slot / 2}" y="${H - 6}" text-anchor="middle">${dt.getDate()} ${dt.toLocaleString('en-GB', { month: 'short' })}</text>`;
            }
        });
        svg += '</svg><div class="chart-tip" id="dash-tip"></div>';
        wrap.innerHTML = svg;

        const tip = document.getElementById('dash-tip');
        wrap.querySelectorAll('.hit').forEach(hit => {
            hit.addEventListener('mouseenter', () => {
                const i = +hit.dataset.i, d = days[i];
                wrap.querySelectorAll('.bar.hover').forEach(b => b.classList.remove('hover'));
                const bar = wrap.querySelector(`.bar[data-i="${i}"]`);
                if (bar) bar.classList.add('hover');
                tip.innerHTML = `<span>${shortDate(d.date)}${d.date === todayIso ? ' (so far)' : ''}</span><strong>${gbp2.format(d.net)}</strong><span>${d.orders} order${d.orders === 1 ? '' : 's'}</span>`;
                const box = wrap.getBoundingClientRect(), svgBox = wrap.querySelector('svg').getBoundingClientRect();
                const scale = svgBox.width / W;
                tip.style.left = Math.min(Math.max((padL + i * slot + slot / 2) * scale, 70), box.width - 70) + 'px';
                tip.style.top = (Math.min(y(d.net), padT + innerH - 2) * scale) + 'px';
                tip.style.display = 'block';
            });
        });
        wrap.addEventListener('mouseleave', () => {
            tip.style.display = 'none';
            wrap.querySelectorAll('.bar.hover').forEach(b => b.classList.remove('hover'));
        });
    }

    function niceStep(raw) {
        const p = Math.pow(10, Math.floor(Math.log10(Math.max(raw, 1))));
        const m = raw / p;
        return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 5 ? 5 : 10) * p;
    }

    function topCustomers(data) {
        const s = data.sales;
        let body;
        if (!s) body = sectionError(data, 'sales');
        else if (!s.top_companies.length) body = '<div class="empty">No orders yet this month.</div>';
        else {
            const max = s.top_companies[0].net || 1;
            body = '<ul class="dash-list">' + s.top_companies.map((c, i) => `<li>
                <span class="rank">${i + 1}</span>
                <span class="main-txt">${esc(c.company)}<div class="share" style="width:${Math.max(4, (c.net / max) * 100)}%"></div></span>
                <span class="num">${gbp.format(c.net)}</span></li>`).join('') + '</ul>';
        }
        return `<div class="dash-card span-4"><h2>Top customers this month</h2>${body}</div>`;
    }

    function dispatchCard(data) {
        const d = data.dispatch;
        if (!d) return `<div class="dash-card span-7"><h2>Dispatch</h2>${sectionError(data, 'dispatch')}</div>`;
        const btn = (key, n, label, cls) => `<button type="button" class="dc ${cls || ''} ${dispatchView === key ? 'active' : ''}" data-view="${key}">
            <span class="n">${n}</span><span class="t">${label}</span></button>`;
        const lists = { today: d.today, tomorrow: d.tomorrow };
        const rows = lists[dispatchView] || [];
        const emptyMsg = { today: 'Nothing due to go out today.', tomorrow: 'Nothing due next working day.' }[dispatchView];
        const list = rows.length ? '<ul class="dash-list">' + rows.slice(0, 8).map(r => `<li>
                <span class="main-txt"><a href="${orderUrl(r.order_name)}">${esc(r.order_name)}</a> &middot; ${esc(r.product_label)}
                    <small>${esc(r.company || '')}</small></span>
                ${r.carrier_label ? `<span class="pill neutral">${esc(r.carrier_label)}</span>` : ''}
            </li>`).join('') + '</ul>'
            + (rows.length > 8 ? `<div class="chart-foot">+ ${rows.length - 8} more in the <a href="/app/Diary">Diary</a></div>` : '')
            : `<div class="empty">${emptyMsg}</div>`;
        return `<div class="dash-card span-7" id="dash-dispatch"><h2>Dispatch <a class="more" href="/app/Diary">Open Diary</a></h2>
            <div class="dispatch-counts">
                ${btn('today', d.today.length, 'Due today', '')}
                ${btn('tomorrow', d.tomorrow.length, 'Next working day', '')}
                <div class="dc static"><span class="n">${d.this_week}</span><span class="t">Still to go this week</span></div>
                <div class="dc static ${d.no_date ? 'warn' : ''}"><span class="n">${d.no_date}</span><span class="t">No dispatch date</span></div>
            </div>
            ${list}
        </div>`;
    }

    function attentionCard(data) {
        const parts = [];
        const p = data.pending_customers;
        if (p) {
            parts.push(`<h2>New sign-ups to approve <a class="more" href="/app/Customers">Customers</a></h2>`);
            parts.push(p.count ? '<ul class="dash-list">' + p.latest.map(c => `<li>
                <span class="main-txt">${esc(c.name)}<small>${esc(c.company || 'No company given')}</small></span>
                <span class="pill warn">${shortDate(c.created)}</span></li>`).join('') + '</ul>'
                + (p.count > p.latest.length ? `<div class="chart-foot">${p.count} waiting in total</div>` : '')
                : '<div class="empty">No one waiting.</div>');
        } else {
            parts.push('<h2>New sign-ups to approve</h2>' + sectionError(data, 'pending_customers'));
        }

        const a = data.autoprint || {};
        let print;
        if (!a.finished_at) print = '<span class="pill neutral">No run since the last restart</span>';
        else if (a.success) print = `<span class="pill good"><i class="fas fa-check"></i> ${(a.printed || []).length} printed</span>`;
        else print = `<span class="pill bad"><i class="fas fa-xmark"></i> ${esc(a.error || ((a.failed || []).length + ' failed'))}</span>`;
        parts.push(`<h2 style="margin-top:18px">6am print run</h2><div class="meta" style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;font-size:0.82rem;color:var(--d-muted)">
            ${print}${a.finished_at ? ' ' + esc(new Date(a.finished_at).toLocaleString('en-GB', { weekday: 'short', hour: '2-digit', minute: '2-digit' })) : ''}</div>`);
        return `<div class="dash-card span-5">${parts.join('')}</div>`;
    }

    function recentOrders(data) {
        const s = data.sales;
        if (!s) return '';
        const rows = s.recent_orders.map(o => `<tr>
            <td><a href="${orderUrl(o.name)}">${esc(o.name)}</a></td>
            <td class="hide-sm">${shortDate(o.date)}</td>
            <td class="company">${esc(o.company)}</td>
            <td class="hide-sm">${esc(o.fulfillment)}</td>
            <td class="r">${gbp2.format(o.total)}</td></tr>`).join('');
        return `<div class="dash-card span-12"><h2>Latest orders <a class="more" href="/app/Orders">All orders</a></h2>
            <div class="table-scroll"><table class="dash-table"><thead><tr>
                <th>Order</th><th class="hide-sm">Date</th><th>Customer</th><th class="hide-sm">Fulfilment</th><th class="r">Total inc VAT</th>
            </tr></thead><tbody>${rows || '<tr><td colspan="5" class="empty">No orders yet.</td></tr>'}</tbody></table></div></div>`;
    }

    function render(data) {
        lastData = data;
        const updated = data.generated_at ? new Date(data.generated_at).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) : '';
        root.innerHTML = `
            <div class="dash-head">
                <div><h1>${greeting()}</h1><div class="sub">${new Date().toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}${updated ? ' &middot; updated ' + updated : ''}</div></div>
                <button type="button" class="dash-refresh" id="dash-refresh"><i class="fas fa-rotate"></i> Refresh</button>
            </div>
            <div class="dash-grid">
                ${statTiles(data)}
                ${chartCard(data)}
                ${topCustomers(data)}
                ${dispatchCard(data)}
                ${attentionCard(data)}
                ${recentOrders(data)}
            </div>`;
        if (data.sales) drawChart(data.sales.daily);
        document.getElementById('dash-refresh').addEventListener('click', () => load(true));
        bindDispatch();
    }

    function bindDispatch() {
        const card = document.getElementById('dash-dispatch');
        if (!card) return;
        card.querySelectorAll('.dc[data-view]').forEach(b => b.addEventListener('click', () => {
            dispatchView = b.dataset.view;
            card.outerHTML = dispatchCard(lastData);
            bindDispatch();
        }));
    }

    function skeleton() {
        const sk = '<div class="skeleton" style="width:40%"></div><div class="skeleton" style="height:28px;width:70%"></div><div class="skeleton" style="width:55%"></div>';
        root.innerHTML = `<div class="dash-head"><div><h1>${greeting()}</h1><div class="sub">Loading the latest numbers&hellip;</div></div></div>
            <div class="dash-grid">${[1, 2, 3, 4].map(() => `<div class="dash-card span-3">${sk}</div>`).join('')}
            <div class="dash-card span-8" style="height:300px">${sk}</div><div class="dash-card span-4">${sk}${sk}</div></div>`;
    }

    async function load(refresh) {
        if (!lastData) skeleton();
        const btn = document.getElementById('dash-refresh');
        if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-rotate fa-spin"></i> Refreshing'; }
        try {
            const res = await fetch('/api/dashboard' + (refresh ? '?refresh=1' : ''), { credentials: 'same-origin' });
            const data = await res.json();
            if (!data.success) throw new Error(data.error || 'Could not load the dashboard');
            render(data);
        } catch (e) {
            root.innerHTML = `<div class="dash-card"><div class="err">${esc(e.message)}</div></div>`;
        }
    }

    let resizeTimer;
    window.addEventListener('resize', () => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => { if (lastData && lastData.sales) drawChart(lastData.sales.daily); }, 150);
    });
    setInterval(() => { if (!document.hidden) load(false); }, 5 * 60 * 1000);
    load(false);
})();
