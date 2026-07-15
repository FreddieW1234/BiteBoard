/**
 * Shopify /pages/portal helper: forward ?order=&item=&proof=&action= from the store page into the portal iframe.
 * Add to the portal page in your theme:
 *   <script src="https://YOUR-PORTAL-HOST/static/bite_portal_parent_deep_link.js" defer></script>
 */
(function () {
    'use strict';

    var FORWARD = ['order', 'item', 'proof', 'action'];

    function findPortalIframe() {
        var selectors = [
            'iframe[data-bite-portal]',
            'iframe[src*="/portal"]',
            'iframe[src*="/client/orders"]',
            'iframe[src*="client%2Forders"]',
        ];
        for (var i = 0; i < selectors.length; i++) {
            var el = document.querySelector(selectors[i]);
            if (el) return el;
        }
        return null;
    }

    function appendParamsToIframe(iframe) {
        if (!iframe || !iframe.src) return;
        var pageParams = new URLSearchParams(window.location.search);
        var hasForward = FORWARD.some(function (k) { return pageParams.get(k); });
        if (!hasForward) return;

        var url;
        try {
            url = new URL(iframe.src, window.location.href);
        } catch (_) {
            return;
        }

        FORWARD.forEach(function (key) {
            var val = pageParams.get(key);
            if (val) url.searchParams.set(key, val);
        });

        if (url.toString() !== iframe.src) {
            iframe.src = url.toString();
        }
    }

    function run() {
        var iframe = findPortalIframe();
        if (iframe) appendParamsToIframe(iframe);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', run);
    } else {
        run();
    }
})();
