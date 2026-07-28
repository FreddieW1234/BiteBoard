/** Print order line sheets via hidden iframe (keeps user-gesture print dialog). */
function _printOrderLineSheet(url, frameId, title) {
    let iframe = document.getElementById(frameId);
    if (!iframe) {
        iframe = document.createElement('iframe');
        iframe.id = frameId;
        iframe.setAttribute('title', title);
        iframe.style.cssText = 'position:fixed;width:0;height:0;border:0;visibility:hidden';
        document.body.appendChild(iframe);
    }
    iframe.onload = function () {
        iframe.onload = null;
        const win = iframe.contentWindow;
        if (!win) return;
        const cleanup = function () {
            iframe.src = 'about:blank';
        };
        if ('onafterprint' in win) {
            win.onafterprint = cleanup;
        } else {
            setTimeout(cleanup, 1500);
        }
        win.focus();
        win.print();
    };
    iframe.src = url;
}

function printProductionNote(orderId, lineNumber) {
    if (!orderId || lineNumber == null || lineNumber === '') return;
    const url = `/orders/${encodeURIComponent(orderId)}/production-notes?line=${encodeURIComponent(lineNumber)}&embed=1`;
    _printOrderLineSheet(url, 'production-note-print-frame', 'Production note');
}

function printArtJobSheet(orderId, lineNumber) {
    if (!orderId || lineNumber == null || lineNumber === '') return;
    const url = `/orders/${encodeURIComponent(orderId)}/art-job-sheet?line=${encodeURIComponent(lineNumber)}&embed=1`;
    _printOrderLineSheet(url, 'art-job-sheet-print-frame', 'Art job sheet');
}
