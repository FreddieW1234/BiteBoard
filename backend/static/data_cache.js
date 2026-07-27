(function () {
    'use strict';

    /**
     * GET response cache + background prefetch for staff app pages.
     * Use BiteDataCache.fetch() instead of fetch() for read-mostly API loads.
     */
    var CACHE_PROP = '__biteApiCache';
    var INFLIGHT_PROP = '__biteApiInflight';

    if (!window[CACHE_PROP]) {
        window[CACHE_PROP] = Object.create(null);
    }
    if (!window[INFLIGHT_PROP]) {
        window[INFLIGHT_PROP] = Object.create(null);
    }

    var cache = window[CACHE_PROP];
    var inFlight = window[INFLIGHT_PROP];

    var DEFAULT_TTL_MS = 10 * 60 * 1000;
    var SHORT_TTL_MS = 3 * 60 * 1000;
    var PREFETCH_CONCURRENCY = 6;

    var ROUTE_DATA_ENDPOINTS = {
        '/': [
            '/api/tools',
            '/api/live-products-count',
            '/api/products-parent-child-tree',
        ],
        '/app/Products': [
            '/api/all-products',
            '/api/shopify/files',
            '/api/products-parent-child-tree',
            '/api/pricing-qty-bands',
            '/api/products',
            '/api/metafield-choices/custom.custom_category',
            '/api/metafield-choices/custom.subcategory?all=1',
            '/api/category-groups',
        ],
        '/app/Orders': [
            '/api/orders',
        ],
        '/app/Diary': [
            '/api/diary',
            '/api/shipping/status',
        ],
        '/app/Customers': [
            '/api/customers',
        ],
        '/app/Artwork_Updater': [
            '/api/shopify/files',
        ],
        '/app/Files': [
            '/api/office-files',
        ],
    };

    function normPath(path) {
        if (!path) return '/';
        try {
            path = new URL(path, window.location.origin).pathname;
        } catch (_) { /* keep */ }
        if (path.length > 1 && path.endsWith('/')) {
            path = path.slice(0, -1);
        }
        return path || '/';
    }

    function cacheKey(url) {
        try {
            var u = new URL(url, window.location.origin);
            return u.pathname + u.search;
        } catch (_) {
            return String(url || '');
        }
    }

    function ttlFor(key) {
        if (key.indexOf('/api/orders/') === 0 && key.indexOf('/tracking') > 0) return SHORT_TTL_MS;
        if (key === '/api/orders') return SHORT_TTL_MS;
        if (key === '/api/diary') return SHORT_TTL_MS;
        if (key === '/api/shipping/status') return 2 * 60 * 1000;
        if (key === '/api/all-products') return DEFAULT_TTL_MS;
        return DEFAULT_TTL_MS;
    }

    function isFresh(entry) {
        if (!entry) return false;
        return Date.now() - entry.storedAt < (entry.ttl || DEFAULT_TTL_MS);
    }

    function responseFromEntry(entry) {
        return new Response(entry.body, {
            status: entry.status || 200,
            statusText: entry.statusText || 'OK',
            headers: {
                'Content-Type': entry.contentType || 'application/json',
                'X-Bite-Cache': '1',
            },
        });
    }

    function syncSideCaches(key, body) {
        if (key.indexOf('/api/products-parent-child-tree') !== 0) return;
        try {
            var data = JSON.parse(body);
            if (data && data.tree) {
                window.__productFamilyTreeCache = data;
                window.__productFamilyTreeCacheTime = Date.now();
            }
        } catch (_) { /* ignore */ }
    }

    function storeResponse(key, response, body) {
        var contentType = (response.headers && response.headers.get('content-type')) || 'application/json';
        cache[key] = {
            body: body,
            status: response.status,
            statusText: response.statusText,
            contentType: contentType,
            storedAt: Date.now(),
            ttl: ttlFor(key),
        };
        syncSideCaches(key, body);
    }

    function has(url) {
        return isFresh(cache[cacheKey(url)]);
    }

    function getCachedJson(url) {
        var key = cacheKey(url);
        var entry = cache[key];
        if (!isFresh(entry)) return null;
        try {
            return JSON.parse(entry.body);
        } catch (_) {
            return null;
        }
    }

    function invalidate(url) {
        delete cache[cacheKey(url)];
    }

    function invalidatePrefix(prefix) {
        Object.keys(cache).forEach(function (key) {
            if (key.indexOf(prefix) === 0) delete cache[key];
        });
    }

    function shouldCacheFetch(url, options) {
        options = options || {};
        var method = (options.method || 'GET').toUpperCase();
        if (method !== 'GET') return false;
        if (options.body) return false;
        if (options.cache === 'no-store') return false;
        if (options.bypassCache) return false;
        return cacheKey(url).indexOf('/api/') === 0;
    }

    function fetchCached(url, options) {
        options = options || {};
        var key = cacheKey(url);

        if (options.bypassCache && shouldCacheFetch(url, options)) {
            delete cache[key];
        }

        if (!shouldCacheFetch(url, options)) {
            return fetch(url, options);
        }

        var hit = cache[key];
        if (isFresh(hit)) {
            return Promise.resolve(responseFromEntry(hit));
        }

        if (inFlight[key]) {
            return inFlight[key].then(function (entry) {
                return responseFromEntry(entry);
            });
        }

        var networkPromise = fetch(url, options)
            .then(function (response) {
                return response.clone().text().then(function (body) {
                    if (response.ok) {
                        storeResponse(key, response, body);
                    }
                    return cache[key];
                });
            })
            .finally(function () {
                delete inFlight[key];
            });

        inFlight[key] = networkPromise;
        return networkPromise.then(function (entry) {
            if (entry) return responseFromEntry(entry);
            return fetch(url, options);
        });
    }

    function prefetch(url, options) {
        if (!shouldCacheFetch(url, options)) {
            return Promise.resolve(false);
        }
        var key = cacheKey(url);
        if (isFresh(cache[key])) {
            return Promise.resolve(true);
        }
        return fetchCached(url, options).then(function () { return true; }).catch(function () { return false; });
    }

    function runPool(tasks, concurrency) {
        if (!tasks.length) return Promise.resolve();
        concurrency = Math.max(1, concurrency || PREFETCH_CONCURRENCY);
        var index = 0;

        function worker() {
            if (index >= tasks.length) return Promise.resolve();
            var task = tasks[index++];
            return Promise.resolve()
                .then(task)
                .catch(function () { /* ignore */ })
                .then(worker);
        }

        var workers = [];
        for (var i = 0; i < Math.min(concurrency, tasks.length); i++) {
            workers.push(worker());
        }
        return Promise.all(workers);
    }

    function warmOrderTracking(ordersPayload) {
        if (!ordersPayload || !ordersPayload.success) {
            return Promise.resolve();
        }
        var ids = (ordersPayload.orders || [])
            .map(function (o) { return o && o.id; })
            .filter(Boolean);
        if (!ids.length) return Promise.resolve();

        return runPool(ids.map(function (id) {
            return function () {
                return prefetch('/api/orders/' + encodeURIComponent(id) + '/tracking', { credentials: 'same-origin' });
            };
        }), 4);
    }

    function prefetchEndpoint(url) {
        return prefetch(url, { credentials: 'same-origin' }).then(function (ok) {
            if (ok && cacheKey(url) === '/api/orders') {
                try {
                    var entry = cache['/api/orders'];
                    if (entry && entry.body) {
                        return warmOrderTracking(JSON.parse(entry.body));
                    }
                } catch (_) { /* ignore */ }
            }
            return ok;
        });
    }

    function prefetchRouteData(routePath) {
        routePath = normPath(routePath);
        var endpoints = ROUTE_DATA_ENDPOINTS[routePath];
        if (!endpoints || !endpoints.length) {
            return Promise.resolve();
        }

        return runPool(endpoints.map(function (url) {
            return function () { return prefetchEndpoint(url); };
        }), PREFETCH_CONCURRENCY);
    }

    function prefetchAllBackground(exceptPath) {
        exceptPath = normPath(exceptPath || window.location.pathname);
        var routes = Object.keys(ROUTE_DATA_ENDPOINTS).filter(function (route) {
            return route !== exceptPath;
        });

        return runPool(routes.map(function (route) {
            return function () { return prefetchRouteData(route); };
        }), 3);
    }

    function warmStaffApp(currentPath) {
        currentPath = normPath(currentPath || window.location.pathname);
        if (!ROUTE_DATA_ENDPOINTS[currentPath] && currentPath !== '/') return;

        prefetchRouteData(currentPath);
        prefetchAllBackground(currentPath);
    }

    function trackingCacheRatio(orderIds) {
        if (!orderIds || !orderIds.length) return 0;
        var cached = 0;
        orderIds.forEach(function (id) {
            if (has('/api/orders/' + encodeURIComponent(id) + '/tracking')) cached += 1;
        });
        return cached / orderIds.length;
    }

    function isStaffPath(path) {
        path = normPath(path);
        return path === '/' || path.indexOf('/app/') === 0;
    }

    function autoWarmIfStaffPage() {
        var path = normPath(window.location.pathname);
        if (!isStaffPath(path)) return;
        warmStaffApp(path);
    }

    window.BiteDataCache = {
        fetch: fetchCached,
        prefetch: prefetch,
        prefetchRouteData: prefetchRouteData,
        prefetchAllBackground: prefetchAllBackground,
        warmStaffApp: warmStaffApp,
        has: has,
        getCachedJson: getCachedJson,
        invalidate: invalidate,
        invalidatePrefix: invalidatePrefix,
        trackingCacheRatio: trackingCacheRatio,
        warmOrderTracking: warmOrderTracking,
        ROUTE_DATA_ENDPOINTS: ROUTE_DATA_ENDPOINTS,
    };

    autoWarmIfStaffPage();
})();
