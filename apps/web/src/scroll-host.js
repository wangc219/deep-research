/* Standalone, the workbench scrolls the document. Embedded in the platform
   shell, the scroller is an ancestor element, so window.scrollY/scrollTo are
   inert: "back to top" never appears and switching views keeps the previous
   offset. Resolve the real scroller instead of assuming the window. */

const SCROLLABLE = /(auto|scroll|overlay)/;

const documentScroller = () =>
  (typeof document === 'undefined' ? null : document.scrollingElement || document.documentElement);

export function getScrollHost() {
  if (typeof document === 'undefined') return null;
  const mount = document.querySelector('.equipment-workbench-host') || document.getElementById('root');
  let node = mount?.parentElement || null;
  while (node && node !== document.body && node !== document.documentElement) {
    if (SCROLLABLE.test(getComputedStyle(node).overflowY)) return node;
    node = node.parentElement;
  }
  return documentScroller();
}

const isDocumentHost = (host) => !host || host === documentScroller();

export function getScrollHostOffset() {
  const host = getScrollHost();
  return isDocumentHost(host) ? window.scrollY : host.scrollTop;
}

export function scrollHostTo(options) {
  const host = getScrollHost();
  if (isDocumentHost(host)) window.scrollTo(options);
  else host.scrollTo(options);
}

export function scrollHostToTop(options = {}) {
  scrollHostTo({top: 0, ...options});
}

export function observeScrollHost(listener) {
  const host = getScrollHost();
  const target = isDocumentHost(host) ? window : host;
  if (!target) return () => {};
  target.addEventListener('scroll', listener, {passive: true});
  return () => target.removeEventListener('scroll', listener);
}
