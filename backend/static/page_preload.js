(function () {
    'use strict';

    /** Staff app routes (sidebar tabs + dashboard). Current page loads first; others prefetch in background. */
    var ROUTES = [
        '/',
        '/app/All_Products',
        '/app/Product_Creator',
        '/app/Orders',
        '/app/Diary',
        '/app/Customers',
        '/app/Artwork_Updater',
        '/app/Files',
    ];

    var CACHE_PROP = '__bitePageCache';
    if (!window[CACHE_PROP]) {
        window[CACHE_PROP] = new Map();
    }
    var cache = window[CACHE_PROP];
    var inFlight = {};

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

    function isStaffNavLink(anchor) {
        if (!anchor || !anchor.getAttribute) return false;
        if (anchor.target === '_blank') return false;
        if (anchor.hasAttribute('download')) return false;

        var href = anchor.getAttribute('href') || '';
        if (!href || href.indexOf('javascript:') === 0) return false;

        var path = normPath(href);
        if (path === '/staff/logout') return false;
        if (ROUTES.indexOf(path) < 0) return false;

        if (anchor.classList.contains('app-tab')) return true;
        if (anchor.classList.contains('dashboard-tab') && path === '/') return true;
        if (anchor.closest('.sidebar-brand') && path === '/') return true;
        return false;
    }

    function prefetchOne(path) {
        path = normPath(path);
        var current = normPath(window.location.pathname);
        if (path === current || cache.has(path)) {
            return Promise.resolve();
        }
        if (inFlight[path]) {
            return inFlight[path];
        }

        inFlight[path] = fetch(path, { credentials: 'same-origin' })
            .then(function (res) {
                if (!res.ok) throw new Error('HTTP ' + res.status);
                return res.text();
            })
            .then(function (html) {
                if (html) cache.set(path, html);
            })
            .catch(function () { /* ignore — fall back to normal navigation */ })
            .finally(function () {
                delete inFlight[path];
            });

        return inFlight[path];
    }

    function prefetchOthersInBackground() {
        var current = normPath(window.location.pathname);
        var others = ROUTES.filter(function (route) { return route !== current; });

        var chain = Promise.resolve();
        others.forEach(function (path) {
            chain = chain.then(function () {
                return prefetchOne(path);
            }).then(function () {
                return new Promise(function (resolve) {
                    if (window.requestIdleCallback) {
                        requestIdleCallback(resolve, { timeout: 2500 });
                    } else {
                        setTimeout(resolve, 80);
                    }
                });
            });
        });
        return chain;
    }

    function snapshotCurrentPage() {
        var path = normPath(window.location.pathname);
        if (ROUTES.indexOf(path) < 0 || cache.has(path)) return;
        try {
            var html = document.documentElement.outerHTML;
            if (html.indexOf('<!DOCTYPE') !== 0 && html.indexOf('<!doctype') !== 0) {
                html = '<!DOCTYPE html>\n' + html;
            }
            cache.set(path, html);
        } catch (_) { /* ignore */ }
    }

    function navigateFromCache(path) {
        path = normPath(path);
        var html = cache.get(path);
        if (!html) return false;

        window.__bitePendingUrl = path;
        document.open();
        document.write(html);
        document.close();
        return true;
    }

    function onDocumentClick(event) {
        if (event.defaultPrevented) return;
        if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
            return;
        }

        var anchor = event.target.closest('a');
        if (!isStaffNavLink(anchor)) return;

        var path = normPath(anchor.getAttribute('href'));
        if (path === normPath(window.location.pathname)) {
            event.preventDefault();
            return;
        }

        if (navigateFromCache(path)) {
            event.preventDefault();
            return;
        }

        prefetchOne(path);
    }

    function onLinkHover(event) {
        var anchor = event.target.closest('a');
        if (!isStaffNavLink(anchor)) return;
        prefetchOne(normPath(anchor.getAttribute('href')));
    }

    function onPopState() {
        var path = normPath(window.location.pathname);
        if (cache.has(path)) {
            navigateFromCache(path);
        }
    }

    if (window.__bitePendingUrl) {
        var pending = normPath(window.__bitePendingUrl);
        delete window.__bitePendingUrl;
        try {
            history.replaceState({ biteNav: true }, '', pending);
        } catch (_) { /* ignore */ }
    }

    document.addEventListener('click', onDocumentClick, true);
    document.addEventListener('mouseover', onLinkHover, true);
    window.addEventListener('popstate', onPopState);

    function startPreload() {
        snapshotCurrentPage();
        prefetchOthersInBackground();
    }

    if (document.readyState === 'complete') {
        setTimeout(startPreload, 0);
    } else {
        window.addEventListener('load', function () {
            setTimeout(startPreload, 0);
        }, { once: true });
    }
})();
