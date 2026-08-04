/*
 * Shared product save-queue UI — used by both the Product Manager and All
 * Products pages. Self-injects a modal (Queue + Logs tabs) into the page, polls
 * GET /api/product-queue, greys/locks queued products, and drives Cancel/Retry.
 *
 * Pages opt in by:
 *   - including this script,
 *   - adding a button that calls ProductQueue.open(),
 *   - marking rows with data-product-id (so locks can grey them), and
 *   - optionally defining window.onQueueLockUpdate(lockedSet) to react to locks.
 */
(function () {
  if (window.ProductQueue) return;

  var POLL_MS = 3000;
  var lockedIds = new Set();      // strings
  var jobs = [];
  var selectedLogJobId = null;
  var pollTimer = null;
  var isOpen = false;
  var lastQueueSig = '';          // last rendered queue signature (skip no-op rebuilds)
  var lastPickerSig = '';         // last rendered logs shell signature
  var lastLogSig = '';            // last rendered log-content signature
  var logLoadedFor = null;        // job id whose final logs are already shown

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function ago(iso) {
    if (!iso) return '';
    var t = Date.parse(iso);
    if (isNaN(t)) return '';
    var s = Math.max(0, Math.round((Date.now() - t) / 1000));
    if (s < 60) return s + 's ago';
    if (s < 3600) return Math.round(s / 60) + 'm ago';
    if (s < 86400) return Math.round(s / 3600) + 'h ago';
    return Math.round(s / 86400) + 'd ago';
  }

  var STATUS = {
    queued:    { label: 'Queued',    cls: 'pq-b-queued' },
    running:   { label: 'Saving',    cls: 'pq-b-running' },
    done:      { label: 'Done',      cls: 'pq-b-done' },
    failed:    { label: 'Failed',    cls: 'pq-b-failed' },
    cancelled: { label: 'Cancelled', cls: 'pq-b-cancel' }
  };

  function injectStyles() {
    if (document.getElementById('pq-styles')) return;
    var css = ''
      + '.pq-overlay{position:fixed;inset:0;background:rgba(15,23,42,.55);display:none;z-index:100000;align-items:center;justify-content:center;}'
      + '.pq-overlay.open{display:flex;}'
      + '.pq-panel{background:#fff;width:min(860px,94vw);max-height:88vh;border-radius:12px;box-shadow:0 20px 60px rgba(0,0,0,.3);display:flex;flex-direction:column;overflow:hidden;font-family:inherit;}'
      + '.pq-head{display:flex;align-items:center;gap:12px;padding:14px 18px;border-bottom:1px solid #e2e8f0;}'
      + '.pq-head h3{margin:0;font-size:17px;font-weight:700;color:#0f172a;}'
      + '.pq-tabs{display:flex;gap:6px;margin-left:8px;}'
      + '.pq-tab{border:0;background:#f1f5f9;color:#334155;padding:6px 14px;border-radius:8px;cursor:pointer;font-size:13px;font-weight:600;}'
      + '.pq-tab.active{background:#2563eb;color:#fff;}'
      + '.pq-x{margin-left:auto;border:0;background:transparent;font-size:20px;line-height:1;cursor:pointer;color:#64748b;}'
      + '.pq-body{padding:14px 18px;overflow:auto;}'
      + '.pq-empty{color:#64748b;text-align:center;padding:28px 0;}'
      + '.pq-job{display:flex;align-items:center;gap:10px;padding:10px 12px;border:1px solid #e2e8f0;border-radius:10px;margin-bottom:8px;}'
      + '.pq-job .pq-title{font-weight:600;color:#0f172a;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}'
      + '.pq-job .pq-time{color:#94a3b8;font-size:12px;white-space:nowrap;}'
      + '.pq-badge{font-size:11px;font-weight:700;padding:3px 9px;border-radius:999px;white-space:nowrap;}'
      + '.pq-b-queued{background:#e2e8f0;color:#475569;}'
      + '.pq-b-running{background:#dbeafe;color:#1d4ed8;}'
      + '.pq-b-done{background:#dcfce7;color:#15803d;}'
      + '.pq-b-failed{background:#fee2e2;color:#b91c1c;}'
      + '.pq-b-cancel{background:#f1f5f9;color:#64748b;}'
      + '.pq-act{border:0;background:#f8fafc;border:1px solid #e2e8f0;border-radius:7px;padding:5px 10px;font-size:12px;cursor:pointer;color:#334155;}'
      + '.pq-act:hover{background:#eef2f7;}'
      + '.pq-act.pq-danger{color:#b91c1c;}'
      + '.pq-logsel{margin-bottom:10px;font-size:13px;color:#475569;}'
      + '.pq-verify{margin:0 0 12px;border-collapse:collapse;width:100%;font-size:12px;}'
      + '.pq-verify th,.pq-verify td{border:1px solid #e2e8f0;padding:5px 8px;text-align:left;vertical-align:top;}'
      + '.pq-verify .ok{color:#15803d;}.pq-verify .bad{color:#b91c1c;}'
      + '.pq-log{background:#0b1020;color:#d1e0ff;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px;line-height:1.5;white-space:pre-wrap;word-break:break-word;padding:12px;border-radius:8px;max-height:52vh;overflow:auto;}'
      + '.pq-live{display:flex;align-items:center;gap:6px;color:#15803d;font-size:12px;font-weight:700;margin-bottom:6px;}'
      + '.pq-live::before{content:"";width:8px;height:8px;border-radius:50%;background:#22c55e;animation:pq-pulse 1.2s infinite;}'
      + '@keyframes pq-pulse{0%,100%{opacity:1;}50%{opacity:.25;}}'
      + '.pq-count{display:inline-block;min-width:18px;padding:0 5px;margin-left:4px;background:#ef4444;color:#fff;border-radius:999px;font-size:11px;font-weight:700;text-align:center;}'
      + '.pq-count:empty{display:none;}'
      + '[data-product-id].pq-locked{opacity:.55;pointer-events:none;filter:grayscale(.4);}'
      + '[data-product-id].pq-locked .edit-btn{pointer-events:none;opacity:.5;}'
      + '.pq-locked-option{opacity:.5 !important;pointer-events:none !important;cursor:not-allowed !important;position:relative;}'
      + '.pq-locked-option::after{content:"in queue";position:absolute;right:10px;top:50%;transform:translateY(-50%);font-size:10px;font-weight:700;color:#b91c1c;text-transform:uppercase;letter-spacing:.03em;}';
    var st = document.createElement('style');
    st.id = 'pq-styles';
    st.textContent = css;
    document.head.appendChild(st);
  }

  function buildModal() {
    if (document.getElementById('pq-overlay')) return;
    var ov = document.createElement('div');
    ov.className = 'pq-overlay';
    ov.id = 'pq-overlay';
    ov.innerHTML = ''
      + '<div class="pq-panel" role="dialog" aria-modal="true">'
      + '  <div class="pq-head">'
      + '    <h3>Save Queue</h3>'
      + '    <div class="pq-tabs">'
      + '      <button type="button" class="pq-tab active" data-tab="queue">Queue</button>'
      + '      <button type="button" class="pq-tab" data-tab="logs">Logs</button>'
      + '    </div>'
      + '    <button type="button" class="pq-x" aria-label="Close">&times;</button>'
      + '  </div>'
      + '  <div class="pq-body" id="pq-body-queue"></div>'
      + '  <div class="pq-body" id="pq-body-logs" style="display:none;"></div>'
      + '</div>';
    document.body.appendChild(ov);

    ov.addEventListener('click', function (e) { if (e.target === ov) close(); });
    ov.querySelector('.pq-x').addEventListener('click', close);
    ov.querySelectorAll('.pq-tab').forEach(function (t) {
      t.addEventListener('click', function () { switchTab(t.getAttribute('data-tab')); });
    });
  }

  function switchTab(name) {
    var ov = document.getElementById('pq-overlay');
    if (!ov) return;
    ov.querySelectorAll('.pq-tab').forEach(function (t) {
      t.classList.toggle('active', t.getAttribute('data-tab') === name);
    });
    document.getElementById('pq-body-queue').style.display = name === 'queue' ? '' : 'none';
    document.getElementById('pq-body-logs').style.display = name === 'logs' ? '' : 'none';
    if (name === 'logs') { renderLogsShell(); refreshLogContent(true); }
  }

  function jobById(id) {
    for (var i = 0; i < jobs.length; i++) { if (jobs[i].job_id === id) return jobs[i]; }
    return null;
  }

  function isTerminal(status) {
    return status === 'done' || status === 'failed' || status === 'cancelled';
  }

  // Signature of everything that affects the rendered queue rows (excludes the
  // relative time, which is ticked over in place so the list never rebuilds just
  // because a second passed).
  function queueSig() {
    return jobs.map(function (j) {
      return [j.job_id, j.status, j.attempts, j.verify_ok].join(':');
    }).join('|');
  }

  function renderQueue(force) {
    var el = document.getElementById('pq-body-queue');
    if (!el) return;
    var sig = queueSig();
    if (!force && sig === lastQueueSig) { updateTimes(); return; }
    lastQueueSig = sig;
    if (!jobs.length) {
      el.innerHTML = '<div class="pq-empty">No saves in the queue.</div>';
      return;
    }
    var rows = jobs.slice().reverse().map(function (j) {
      var st = STATUS[j.status] || { label: j.status, cls: 'pq-b-cancel' };
      var label = st.label;
      if (j.status === 'done' && j.verify_ok === false) label = 'Done (mismatch)';
      var acts = '';
      if (j.status === 'failed' || j.status === 'cancelled') {
        acts += '<button type="button" class="pq-act" data-retry="' + esc(j.job_id) + '">Retry</button>';
      }
      acts += '<button type="button" class="pq-act" data-logs="' + esc(j.job_id) + '">Logs</button>';
      var attempts = (j.attempts && j.max_attempts) ? (' · try ' + j.attempts + '/' + j.max_attempts) : '';
      return '<div class="pq-job">'
        + '<span class="pq-badge ' + st.cls + '">' + esc(label) + '</span>'
        + '<span class="pq-title" title="' + esc(j.title) + '">' + esc(j.title) + '</span>'
        + '<span class="pq-time" data-created="' + esc(j.created_at) + '" data-attempts="' + esc(attempts) + '">'
        + esc(ago(j.created_at)) + esc(attempts) + '</span>'
        + acts
        + '</div>';
    }).join('');
    el.innerHTML = rows;

    el.querySelectorAll('[data-cancel]').forEach(function (b) {
      b.addEventListener('click', function () { act('cancel', b.getAttribute('data-cancel')); });
    });
    el.querySelectorAll('[data-retry]').forEach(function (b) {
      b.addEventListener('click', function () { act('retry', b.getAttribute('data-retry')); });
    });
    el.querySelectorAll('[data-logs]').forEach(function (b) {
      b.addEventListener('click', function () {
        selectedLogJobId = b.getAttribute('data-logs');
        logLoadedFor = null;
        switchTab('logs');
      });
    });
  }

  // Tick the relative timestamps without touching the rest of the row.
  function updateTimes() {
    document.querySelectorAll('#pq-body-queue .pq-time').forEach(function (el) {
      var created = el.getAttribute('data-created');
      var att = el.getAttribute('data-attempts') || '';
      el.textContent = ago(created) + att;
    });
  }

  function act(kind, jobId) {
    fetch('/api/product-queue/' + encodeURIComponent(jobId) + '/' + kind, { method: 'POST' })
      .then(function () { refresh(); })
      .catch(function () {});
  }

  // Build the Logs shell (job picker + content container) only when the set of
  // jobs or the selection changes — never on a plain poll, so the dropdown stays
  // open and nothing flickers.
  function renderLogsShell() {
    var el = document.getElementById('pq-body-logs');
    if (!el) return;
    if (!selectedLogJobId && jobs.length) selectedLogJobId = jobs[jobs.length - 1].job_id;
    if (!selectedLogJobId) {
      el.innerHTML = '<div class="pq-empty">Pick a job&rsquo;s <b>Logs</b> from the Queue tab.</div>';
      lastPickerSig = '';
      return;
    }
    var sig = jobs.map(function (j) { return j.job_id + ':' + j.status; }).join('|') + '||' + selectedLogJobId;
    if (sig === lastPickerSig && document.getElementById('pq-log-content')) return;
    lastPickerSig = sig;
    var picker = '<div class="pq-logsel">Showing logs for: <select id="pq-log-picker">'
      + jobs.slice().reverse().map(function (j) {
          var seld = j.job_id === selectedLogJobId ? ' selected' : '';
          return '<option value="' + esc(j.job_id) + '"' + seld + '>' + esc(j.title) + ' — ' + esc((STATUS[j.status] || {}).label || j.status) + '</option>';
        }).join('')
      + '</select></div>';
    el.innerHTML = picker + '<div id="pq-log-content"><div class="pq-empty">Loading…</div></div>';
    lastLogSig = '';  // force a content repaint after the shell is rebuilt
    var picEl = document.getElementById('pq-log-picker');
    if (picEl) picEl.addEventListener('change', function () {
      selectedLogJobId = picEl.value;
      logLoadedFor = null;
      renderLogsShell();
      refreshLogContent(true);
    });
  }

  // Fetch + paint the selected job's logs/verify, but only replace the DOM when
  // the content actually changed, and keep the log pane's scroll position.
  // Finished jobs are fetched once (their logs are final).
  function refreshLogContent(force) {
    if (!selectedLogJobId) return;
    var summary = jobById(selectedLogJobId);
    var terminal = summary && isTerminal(summary.status);
    if (!force && terminal && logLoadedFor === selectedLogJobId) return;
    fetch('/api/product-queue/' + encodeURIComponent(selectedLogJobId))
      .then(function (r) { return r.json(); })
      .then(function (job) {
        var c = document.getElementById('pq-log-content');
        if (!c) return;
        if (!job || job.error) {
          var msg = '<div class="pq-empty">' + esc((job && job.error) || 'Job not found') + '</div>';
          if (c.innerHTML !== msg) c.innerHTML = msg;
          return;
        }
        var verify = job.verify || [];
        var vhtml = '';
        if (verify.length) {
          vhtml = '<table class="pq-verify"><thead><tr><th>Field</th><th>Intended</th><th>On Shopify</th><th>OK</th></tr></thead><tbody>'
            + verify.map(function (v) {
                return '<tr><td>' + esc(v.field) + '</td><td>' + esc(v.intended) + '</td><td>' + esc(v.actual) + '</td>'
                  + '<td class="' + (v.ok ? 'ok' : 'bad') + '">' + (v.ok ? '✓' : '✗') + '</td></tr>';
              }).join('')
            + '</tbody></table>';
        }
        var status = job.status || '';
        var logs = job.logs || '';
        var body;
        if (!logs) {
          if (status === 'queued') {
            body = '<div class="pq-empty">&#9203; Waiting in the queue &mdash; this save hasn&rsquo;t started yet.</div>';
          } else if (status === 'running') {
            body = '<div class="pq-empty">&#9654; Starting&hellip; waiting for the first output.</div>';
          } else {
            body = '<div class="pq-log">(no output captured)</div>';
          }
        } else {
          var live = (status === 'running')
            ? '<div class="pq-live">&#9679; Live &mdash; updating as it saves&hellip;</div>' : '';
          body = live + '<div class="pq-log">' + esc(logs) + '</div>';
        }
        var html = vhtml + body;
        var sig = logs.length + ':' + verify.length + ':' + status;
        if (sig === lastLogSig) return;  // unchanged — don't repaint (no flash)
        lastLogSig = sig;
        var prev = c.querySelector('.pq-log');
        var atBottom = prev ? (prev.scrollTop + prev.clientHeight >= prev.scrollHeight - 8) : true;
        var prevTop = prev ? prev.scrollTop : 0;
        c.innerHTML = html;
        var now = c.querySelector('.pq-log');
        if (now) now.scrollTop = atBottom ? now.scrollHeight : prevTop;
        if (terminal) logLoadedFor = selectedLogJobId;
      })
      .catch(function () {});
  }

  function applyLocks() {
    document.querySelectorAll('[data-product-id]').forEach(function (row) {
      var id = String(row.getAttribute('data-product-id'));
      row.classList.toggle('pq-locked', lockedIds.has(id));
    });
    // Update any Queue-button count badges with the active job total.
    var active = jobs.filter(function (j) { return j.status === 'queued' || j.status === 'running'; }).length;
    document.querySelectorAll('.pq-count').forEach(function (b) { b.textContent = active ? String(active) : ''; });
    if (typeof window.onQueueLockUpdate === 'function') {
      try { window.onQueueLockUpdate(lockedIds); } catch (e) {}
    }
  }

  function refresh() {
    return fetch('/api/product-queue')
      .then(function (r) { return r.json(); })
      .then(function (d) {
        jobs = (d && d.jobs) || [];
        lockedIds = new Set(((d && d.locked) || []).map(String));
        renderQueue();
        if (isOpen) {
          var logsShown = document.getElementById('pq-body-logs');
          if (logsShown && logsShown.style.display !== 'none') {
            renderLogsShell();
            refreshLogContent(false);
          }
        }
        applyLocks();
      })
      .catch(function () {});
  }

  function open() {
    injectStyles();
    buildModal();
    isOpen = true;
    document.getElementById('pq-overlay').classList.add('open');
    switchTab('queue');
    refresh();
  }

  function close() {
    isOpen = false;
    var ov = document.getElementById('pq-overlay');
    if (ov) ov.classList.remove('open');
  }

  function start() {
    injectStyles();
    buildModal();
    refresh();
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(refresh, POLL_MS);
  }

  window.ProductQueue = {
    open: open,
    close: close,
    refresh: refresh,
    start: start,
    lockedIds: lockedIds,
    isLocked: function (id) { return lockedIds.has(String(id)); },
    // Grey out and disable a picker/autocomplete row when its product is
    // locked (queued/running save); otherwise wire the given select handler.
    applyLockToOption: function (item, productId, selectFn) {
      if (item && lockedIds.has(String(productId))) {
        item.classList.add('pq-locked-option');
        item.title = 'This product has a save in the queue and is locked';
        item.onclick = function (e) { if (e) { e.preventDefault(); e.stopPropagation(); } };
        return true;
      }
      if (item) item.onclick = selectFn;
      return false;
    }
  };
  // Keep the exposed set reference current across refreshes.
  Object.defineProperty(window.ProductQueue, 'lockedIds', { get: function () { return lockedIds; } });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
