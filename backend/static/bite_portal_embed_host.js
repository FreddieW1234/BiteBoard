/**
 * Shopify theme helper: place this script on the page that embeds the client portal iframe.
 * Handles iframe resize messages and fullscreen overlay mode for centred modals.
 */
(function () {
    'use strict';

    var overlayState = null;
    var portalIframe = null;

    function findIframeBySource(sourceWindow) {
        var iframes = document.querySelectorAll('iframe');
        for (var i = 0; i < iframes.length; i++) {
            try {
                if (iframes[i].contentWindow === sourceWindow) return iframes[i];
            } catch (_) { /* cross-origin */ }
        }
        return null;
    }

    function findPortalIframe() {
        if (portalIframe && document.body.contains(portalIframe)) return portalIframe;
        var selectors = [
            'iframe[data-bite-portal]',
            'iframe[src*="/client/orders"]',
            'iframe[src*="client%2Forders"]',
        ];
        for (var i = 0; i < selectors.length; i++) {
            var el = document.querySelector(selectors[i]);
            if (el) return el;
        }
        return null;
    }

    function enterOverlayMode(iframe) {
        if (!iframe || overlayState) return;
        overlayState = {
            el: iframe,
            style: iframe.getAttribute('style') || '',
            parentOverflow: document.documentElement.style.overflow,
            bodyOverflow: document.body.style.overflow,
        };
        iframe.setAttribute(
            'style',
            'position:fixed!important;inset:0!important;width:100%!important;height:100%!important;max-height:none!important;z-index:2147483646!important;border:none!important;margin:0!important;'
        );
        document.documentElement.style.overflow = 'hidden';
        document.body.style.overflow = 'hidden';
    }

    function exitOverlayMode() {
        if (!overlayState) return;
        overlayState.el.setAttribute('style', overlayState.style);
        document.documentElement.style.overflow = overlayState.parentOverflow || '';
        document.body.style.overflow = overlayState.bodyOverflow || '';
        overlayState = null;
    }

    window.addEventListener('message', function (e) {
        var data = e.data;
        if (!data || data.source !== 'bite-portal') return;

        var iframe = findIframeBySource(e.source) || portalIframe || findPortalIframe();
        if (iframe) portalIframe = iframe;

        if (data.type === 'resize' && iframe && data.height) {
            if (!overlayState) {
                iframe.style.height = Math.max(200, Number(data.height) || 200) + 'px';
            }
            return;
        }

        if (data.type === 'overlay-mode') {
            if (data.active) enterOverlayMode(iframe || findPortalIframe());
            else exitOverlayMode();
        }
    });
})();
