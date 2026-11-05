window.parent.postMessage({ isStreamlitMessage: true, type: 'streamlit:componentReady', apiVersion: 1 }, '*');
// Restore the user's opaque, revocable session token after a page reload.
try {
    const token = window.localStorage.getItem('ktvdi_persistent_session');
    if (token) send('restore_session', { token });
} catch (_) {
    // Storage may be unavailable in restricted/private browsing contexts.
}
height();
const ktvdiRoot = document.getElementById('app');
if (ktvdiRoot && 'ResizeObserver' in window) {
    const ktvdiResizeObserver = new ResizeObserver(() => height());
    ktvdiResizeObserver.observe(ktvdiRoot);
}
if (ktvdiRoot && 'MutationObserver' in window) {
    const ktvdiMutationObserver = new MutationObserver(() => height());
    ktvdiMutationObserver.observe(ktvdiRoot, { childList: true, subtree: true, attributes: true, characterData: true });
}
window.addEventListener('load', () => { height(); if (window.lucide && typeof window.lucide.createIcons === 'function')
    window.lucide.createIcons(); if (state.page === 'map' && !state.map && window.L)
    initMap(); });
window.addEventListener('resize', height);

