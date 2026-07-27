(function () {
    'use strict';

    /** Staff app routes — HTML is warmed via link prefetch + low-priority fetch (browser cache). */
    var ROUTES = [
        '/',
        '/app/Products',
        '/app/Orders',
        '/app/Diary',
        '/app/Customers',
        '/app/Artwork_Updater',
        '/app/Files',
    ];

    var htmlInflight = Object.create(null);

    function normPath(path) {
        if (!path) return '/';
        try {
            path = new URL(path, window.location.origin).pathname;
        } catch (_) { /* keep path as-is */ }
        if (path.length > 1 && path.endsWith('/')) {
            path = path.slice(0, -1);
        }
        return path || '/';
    }

    function isStaffRoute(path) {
        return ROUTES.indexOf(normPath(path)) >= 0;
    }

    function isStaffNavLink(anchor) {
        if (!anchor || !anchor.getAttribute) return false;
        if (anchor.target === '_blank') return false;
        if (anchor.hasAttribute('download')) return false;

        var href = anchor.getAttribute('href') || '';
        if (!href || href.indexOf('javascript:') === 0) return false;
        if (href.indexOf('?') >= 0) return false;

        var path = normPath(href);
        if (path === '/staff/logout') return false;
        if (!isStaffRoute(path)) return false;

        if (anchor.classList.contains('app-tab')) return true;
        if (anchor.classList.contains('dashboard-tab') && path === '/') return true;
        if (anchor.closest('.sidebar-brand') && path === '/') return true;
        return false;
    }

    function warmHtml(path) {
        path = normPath(path);
        if (htmlInflight[path]) return htmlInflight[path];

        htmlInflight[path] = fetch(path, { credentials: 'same-origin', priority: 'low' })
            .catch(function () { /* ignore */ })
            .finally(function () {
                delete htmlInflight[path];
            });

        return htmlInflight[path];
    }

    function injectPrefetchLinks() {
        var current = normPath(window.location.pathname);
        var head = document.head || document.getElementsByTagName('head')[0];
        if (!head) return;

        ROUTES.forEach(function (route) {
            if (route === current) return;
            var link = document.createElement('link');
            link.rel = 'prefetch';
            link.href = route;
            link.as = 'document';
            head.appendChild(link);
        });
    }

    function warmAllHtml(exceptPath) {
        exceptPath = normPath(exceptPath || window.location.pathname);
        ROUTES.forEach(function (route) {
            if (route !== exceptPath) warmHtml(route);
        });
    }

    function onLinkHover(event) {
        var anchor = event.target.closest('a');
        if (!isStaffNavLink(anchor)) return;
        warmHtml(normPath(anchor.getAttribute('href')));
    }

    function startWarmup() {
        var current = normPath(window.location.pathname);
        if (!isStaffRoute(current)) return;

        injectPrefetchLinks();
        warmAllHtml(current);

        if (window.BiteDataCache && typeof window.BiteDataCache.warmStaffApp === 'function') {
            window.BiteDataCache.warmStaffApp(current);
        }
    }

    document.addEventListener('mouseover', onLinkHover, true);

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', startWarmup, { once: true });
    } else {
        startWarmup();
    }
})();
