(function () {
    'use strict';

    var STORAGE_KEY = 'biteboard-theme';

    function isDark() {
        return document.documentElement.getAttribute('data-theme') === 'dark';
    }

    function applyTheme(theme) {
        var dark = theme === 'dark';
        document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
        try { localStorage.setItem(STORAGE_KEY, dark ? 'dark' : 'light'); } catch (_) { /* ignore */ }
        syncToggleButtons();
    }

    function syncToggleButtons() {
        document.querySelectorAll('.sidebar-theme-toggle').forEach(function (btn) {
            var dark = isDark();
            btn.setAttribute('aria-pressed', dark ? 'true' : 'false');
            btn.setAttribute('aria-label', dark ? 'Switch to light mode' : 'Switch to dark mode');
            var label = btn.querySelector('.theme-toggle-label');
            if (label) label.textContent = dark ? 'Light mode' : 'Dark mode';
        });
    }

    function injectCommitInfo(footer) {
        if (footer.querySelector('.sidebar-commit-info')) return;

        var el = document.createElement('div');
        el.className = 'sidebar-commit-info';
        el.setAttribute('aria-live', 'polite');
        el.innerHTML =
            '<span class="sidebar-commit-prefix">Commit: </span>' +
            '<span class="sidebar-commit-sha">…</span>';

        var before = footer.querySelector('.sidebar-theme-toggle') || footer.querySelector('.dashboard-tab') || footer.firstChild;
        if (before) footer.insertBefore(el, before);
        else footer.appendChild(el);

        fetch('/api/build-info', { credentials: 'same-origin' })
            .then(function (res) { return res.json(); })
            .then(function (data) {
                var span = el.querySelector('.sidebar-commit-sha');
                if (!span) return;
                var label = data.label || data.commit_short || '';
                span.textContent = label || 'unknown';
                if (data.commit) {
                    el.title = data.commit + (data.branch ? ' (' + data.branch + ')' : '');
                }
            })
            .catch(function () {
                var span = el.querySelector('.sidebar-commit-sha');
                if (span) span.textContent = 'unknown';
            });
    }

    function injectThemeToggle() {
        var footer = document.querySelector('.sidebar .sidebar-footer');
        if (!footer) return;

        injectCommitInfo(footer);

        if (footer.querySelector('.sidebar-theme-toggle')) return;

        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'sidebar-theme-toggle theme-toggle-btn';
        btn.innerHTML =
            '<i class="fas fa-moon theme-icon-when-light" aria-hidden="true"></i>' +
            '<i class="fas fa-sun theme-icon-when-dark" aria-hidden="true"></i>' +
            '<span class="theme-toggle-label">Dark mode</span>';
        btn.addEventListener('click', function () {
            applyTheme(isDark() ? 'light' : 'dark');
        });

        var dash = footer.querySelector('.dashboard-tab');
        if (dash) footer.insertBefore(btn, dash);
        else footer.insertBefore(btn, footer.firstChild);

        injectCommitInfo(footer);
        syncToggleButtons();
    }

    try {
        if (localStorage.getItem(STORAGE_KEY) === 'dark') {
            document.documentElement.setAttribute('data-theme', 'dark');
        }
    } catch (_) { /* ignore */ }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', injectThemeToggle);
    } else {
        injectThemeToggle();
    }

    window.BiteTheme = { applyTheme: applyTheme, isDark: isDark };
})();
