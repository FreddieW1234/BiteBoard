(function () {
    'use strict';

    var STORAGE_RETURN = 'productsReturnView';
    var DEFAULT_VIEW = 'all';
    var PREFETCH_PREFIX = 'pcProductPrefetch:';
    var PREFETCH_TTL_MS = 5 * 60 * 1000;
    var MANAGER_BASE_SRC = '/app/Product_Creator?embed=1';

    function getParam(name) {
        return new URLSearchParams(window.location.search).get(name);
    }

    function prefetchProductForEditor(productId) {
        var id = String(productId || '').trim();
        if (!id) return;
        try {
            var key = PREFETCH_PREFIX + id;
            var existing = sessionStorage.getItem(key);
            if (existing) {
                var parsed = JSON.parse(existing);
                if (parsed && parsed.at && (Date.now() - parsed.at) < PREFETCH_TTL_MS) return;
            }
        } catch (_) { /* ignore */ }
        fetch('/api/product/' + encodeURIComponent(id) + '/prices', { credentials: 'same-origin' })
            .then(function (resp) { return resp.ok ? resp.json() : null; })
            .then(function (data) {
                if (!data || !data.id) return;
                try {
                    sessionStorage.setItem(PREFETCH_PREFIX + id, JSON.stringify({ at: Date.now(), data: data }));
                } catch (_) { /* ignore quota */ }
            })
            .catch(function () { /* ignore */ });
    }

    function tryOpenProductInFrame(frame, productId) {
        if (!frame || !productId) return false;
        try {
            var win = frame.contentWindow;
            if (!win || typeof win.pcPopulateFromProduct !== 'function') return false;
            if (!win.document || win.document.readyState !== 'complete') return false;
            var current = frame.getAttribute('data-src') || '';
            if (!current.startsWith(MANAGER_BASE_SRC)) return false;
            win.pcPopulateFromProduct(String(productId), '');
            return true;
        } catch (_) {
            return false;
        }
    }

    function warmManagerFrame() {
        var frame = document.getElementById('products-manager-frame');
        if (!frame || frame.getAttribute('data-src')) return;
        frame.src = MANAGER_BASE_SRC;
        frame.setAttribute('data-src', MANAGER_BASE_SRC);
    }

    function setView(view, options) {
        options = options || {};
        view = view === 'manager' ? 'manager' : 'all';

        var allPanel = document.getElementById('products-view-all');
        var mgrPanel = document.getElementById('products-view-manager');
        var frame = document.getElementById('products-manager-frame');
        if (!allPanel || !mgrPanel) return;

        allPanel.hidden = view !== 'all';
        mgrPanel.hidden = view !== 'manager';

        document.querySelectorAll('.products-view-toggle [data-view]').forEach(function (btn) {
            var active = btn.getAttribute('data-view') === view;
            btn.classList.toggle('active', active);
            btn.setAttribute('aria-pressed', active ? 'true' : 'false');
        });

        if (view === 'manager' && frame) {
            var editId = options.editId != null ? String(options.editId) : getParam('edit');
            var src = MANAGER_BASE_SRC;
            if (editId) src += '&edit=' + encodeURIComponent(editId);
            var openedInPlace = editId && tryOpenProductInFrame(frame, editId);
            if (!openedInPlace && frame.getAttribute('data-src') !== src) {
                frame.src = src;
                frame.setAttribute('data-src', src);
            } else if (openedInPlace) {
                frame.setAttribute('data-src', src);
            }
        }

        if (!options.skipUrl) {
            var url = new URL(window.location.href);
            url.pathname = '/app/Products';
            url.searchParams.set('view', view);
            if (view === 'manager' && options.editId) {
                url.searchParams.set('edit', String(options.editId));
            } else if (view === 'manager' && getParam('edit')) {
                url.searchParams.set('edit', getParam('edit'));
            } else {
                url.searchParams.delete('edit');
            }
            if (view === 'manager' && options.returnView) {
                url.searchParams.set('return', options.returnView);
            } else {
                url.searchParams.delete('return');
            }
            try {
                history.replaceState({ productsView: view }, '', url.pathname + url.search);
            } catch (_) { /* ignore */ }
        }
    }

    function setReturnView(view) {
        try {
            sessionStorage.setItem(STORAGE_RETURN, view === 'manager' ? 'manager' : 'all');
        } catch (_) { /* ignore */ }
    }

    function getReturnView() {
        var fromUrl = getParam('return');
        if (fromUrl === 'all' || fromUrl === 'manager') return fromUrl;
        try {
            var stored = sessionStorage.getItem(STORAGE_RETURN);
            if (stored === 'all' || stored === 'manager') return stored;
        } catch (_) { /* ignore */ }
        return DEFAULT_VIEW;
    }

    function syncManagerFrameUrl() {
        var homeSrc = '/app/Product_Creator?embed=1';
        var frame = document.getElementById('products-manager-frame');
        if (frame) frame.setAttribute('data-src', homeSrc);
        try {
            var url = new URL(window.location.href);
            url.searchParams.set('view', 'manager');
            url.searchParams.delete('edit');
            url.searchParams.delete('return');
            history.replaceState({ productsView: 'manager' }, '', url.pathname + url.search);
        } catch (_) { /* ignore */ }
    }

    function resetManagerFrame() {
        var frame = document.getElementById('products-manager-frame');
        if (!frame) return;
        var homeSrc = '/app/Product_Creator?embed=1';
        frame.removeAttribute('data-src');
        frame.src = homeSrc;
    }

    function resetManagerFrameInPlace() {
        var frame = document.getElementById('products-manager-frame');
        if (!frame) return;
        var homeSrc = '/app/Product_Creator?embed=1';
        if (frame.contentWindow && typeof frame.contentWindow.resetProductCreatorHomeUI === 'function') {
            try {
                frame.contentWindow.resetProductCreatorHomeUI();
            } catch (_) { /* ignore */ }
        }
        frame.setAttribute('data-src', homeSrc);
        try {
            var url = new URL(window.location.href);
            url.pathname = '/app/Products';
            url.searchParams.set('view', 'manager');
            url.searchParams.delete('edit');
            url.searchParams.delete('return');
            history.replaceState({ productsView: 'manager' }, '', url.pathname + url.search);
        } catch (_) { /* ignore */ }
    }

    function openEditor(productId) {
        prefetchProductForEditor(productId);
        setReturnView('all');
        setView('manager', { editId: productId, returnView: 'all' });
    }

    function backFromEditor() {
        var ret = getReturnView();
        if (ret === 'all') {
            setView('all');
            resetManagerFrame();
            return;
        }
        setView('manager', { skipUrl: true });
        resetManagerFrameInPlace();
    }

    function initToggle() {
        document.querySelectorAll('.products-view-toggle [data-view]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var view = btn.getAttribute('data-view');
                if (view === 'manager') {
                    setReturnView('manager');
                } else {
                    setReturnView('all');
                }
                setView(view);
            });
        });
    }

    function initFromUrl() {
        var view = getParam('view') === 'manager' ? 'manager' : DEFAULT_VIEW;
        var editId = getParam('edit');
        var returnView = getParam('return');
        if (returnView === 'all' || returnView === 'manager') {
            setReturnView(returnView);
        } else if (editId && view === 'manager') {
            setReturnView('all');
        }
        setView(view, { editId: editId, skipUrl: true });
    }

    window.ProductsShell = {
        setView: setView,
        openEditor: openEditor,
        backFromEditor: backFromEditor,
        setReturnView: setReturnView,
        getReturnView: getReturnView,
        syncManagerFrameUrl: syncManagerFrameUrl,
        prefetchProductForEditor: prefetchProductForEditor,
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () {
            initToggle();
            initFromUrl();
            if (getParam('view') !== 'manager') {
                setTimeout(warmManagerFrame, 1500);
            }
        });
    } else {
        initToggle();
        initFromUrl();
        if (getParam('view') !== 'manager') {
            setTimeout(warmManagerFrame, 1500);
        }
    }
})();
