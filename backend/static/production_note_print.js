/** Print a single-item production note via hidden iframe (keeps user-gesture print dialog). */
function printProductionNote(orderId, lineNumber) {
    if (!orderId || lineNumber == null || lineNumber === '') return;
    const url = `/orders/${encodeURIComponent(orderId)}/production-notes?line=${encodeURIComponent(lineNumber)}&embed=1`;
    let iframe = document.getElementById('production-note-print-frame');
    if (!iframe) {
        iframe = document.createElement('iframe');
        iframe.id = 'production-note-print-frame';
        iframe.setAttribute('title', 'Production note');
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
