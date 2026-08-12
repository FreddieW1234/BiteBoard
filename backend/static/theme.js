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

    function footerInsertBefore(footer, el, before) {
        if (before) footer.insertBefore(el, before);
        else footer.appendChild(el);
    }

    function injectUserType(footer, data) {
        if (footer.querySelector('.sidebar-user-type')) return;
        var userType = (data && data.user_type) || '';
        if (!userType) return;

        var el = document.createElement('div');
        el.className = 'sidebar-user-type' + (userType === 'Dev' ? ' is-dev' : ' is-staff');
        var username = (data && data.username) || '';
        if (username) el.title = username;
        var icon = userType === 'Dev' ? 'fa-code' : 'fa-user-tie';
        el.innerHTML =
            '<i class="fas ' + icon + '" aria-hidden="true"></i>' +
            '<span class="sidebar-user-type-label">' + userType + '</span>';

        var before =
            footer.querySelector('.sidebar-commit-info') ||
            footer.querySelector('.sidebar-theme-toggle') ||
            footer.querySelector('.dashboard-tab') ||
            footer.firstChild;
        footerInsertBefore(footer, el, before);
    }

    function injectCommitInfo(footer, data) {
        if (footer.querySelector('.sidebar-commit-info')) return;

        var el = document.createElement('div');
        el.className = 'sidebar-commit-info';
        el.setAttribute('aria-live', 'polite');
        el.innerHTML =
            '<span class="sidebar-commit-prefix">Commit: </span>' +
            '<span class="sidebar-commit-sha">…</span>';

        var before =
            footer.querySelector('.sidebar-theme-toggle') ||
            footer.querySelector('.dashboard-tab') ||
            footer.firstChild;
        footerInsertBefore(footer, el, before);

        function applyLabel(payload) {
            var span = el.querySelector('.sidebar-commit-sha');
            if (!span) return;
            var label = (payload && (payload.label || payload.commit_short)) || '';
            span.textContent = label || 'unknown';
            if (payload && payload.commit) {
                el.title = payload.commit + (payload.branch ? ' (' + payload.branch + ')' : '');
            }
        }

        if (data) {
            applyLabel(data);
            return;
        }

        fetch('/api/build-info', { credentials: 'same-origin' })
            .then(function (res) { return res.json(); })
            .then(applyLabel)
            .catch(function () {
                var span = el.querySelector('.sidebar-commit-sha');
                if (span) span.textContent = 'unknown';
            });
    }

    function injectThemeToggle() {
        var footer = document.querySelector('.sidebar .sidebar-footer');
        if (!footer) return;

        if (!footer.querySelector('.sidebar-theme-toggle')) {
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
        }

        fetch('/api/build-info', { credentials: 'same-origin' })
            .then(function (res) { return res.json(); })
            .then(function (data) {
                injectCommitInfo(footer, data);
                injectUserType(footer, data);
            })
            .catch(function () {
                injectCommitInfo(footer, null);
            });

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
