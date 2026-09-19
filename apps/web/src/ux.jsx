/* Shared UX primitives: transient notifications, clipboard, human-readable
   timestamps and UI preferences that survive a reload. Everything here is
   additive and side-effect free on import, so it can be dropped into any view
   without touching data flow. */
import React, {useCallback, useEffect, useRef, useState} from 'react';
import {CheckCircle2, CircleAlert, Info, X} from 'lucide-react';

/* ------------------------------------------------------------- notifications */

const toastSubscribers = new Set();
let toastSequence = 0;

/* Fires a toast from anywhere, including outside React. A module-level bus
   keeps the giant view tree free of another provider/prop chain. */
export function notify(text, kind = 'ok', duration = 3400) {
  const message = String(text ?? '').trim();
  if (!message) return 0;
  toastSequence += 1;
  const toast = {id: toastSequence, message, kind, duration};
  toastSubscribers.forEach(listener => listener(toast));
  return toast.id;
}

const TOAST_ICONS = {ok: CheckCircle2, error: CircleAlert, info: Info};

export function ToastHost() {
  const [toasts, setToasts] = useState([]);
  const timers = useRef(new Map());
  const dismiss = useCallback(id => {
    const timer = timers.current.get(id);
    if (timer) { clearTimeout(timer); timers.current.delete(id); }
    setToasts(current => current.filter(item => item.id !== id));
  }, []);
  useEffect(() => {
    // Same-message toasts replace each other so a polling loop cannot stack up.
    const push = toast => setToasts(current => [...current.filter(item => item.message !== toast.message), toast].slice(-3));
    toastSubscribers.add(push);
    return () => toastSubscribers.delete(push);
  }, []);
  useEffect(() => {
    toasts.forEach(toast => {
      if (timers.current.has(toast.id)) return;
      timers.current.set(toast.id, setTimeout(() => dismiss(toast.id), toast.duration));
    });
  }, [toasts, dismiss]);
  useEffect(() => () => { timers.current.forEach(clearTimeout); timers.current.clear(); }, []);
  if (!toasts.length) return null;
  return <div className="toast-host" role="status" aria-live="polite">
    {toasts.map(toast => {
      const Icon = TOAST_ICONS[toast.kind] || TOAST_ICONS.info;
      return <button type="button" className={`toast ${toast.kind}`} key={toast.id} onClick={() => dismiss(toast.id)} title="点击关闭">
        <Icon size={16}/><span>{toast.message}</span><X className="toast-close" size={13}/>
      </button>;
    })}
  </div>;
}

/* --------------------------------------------------------------- placeholders */

/* A grey bar with the final content's footprint. Showing the shape of what is
   coming reads as faster than a spinner and stops the layout from jumping when
   the payload lands. */
export function Skeleton({width = '100%', height = 12, radius = 6, className = ''}) {
  return <span className={`skeleton ${className}`.trim()} style={{width, height, borderRadius: radius}} aria-hidden="true"/>;
}

/* ---------------------------------------------------------- failure isolation */

/* A render error in one view used to blank the entire workbench. The boundary
   keeps the chrome alive and offers a way back; `resetKey` clears the error when
   the user navigates elsewhere. */
export class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = {error: null};
    this.reset = () => this.setState({error: null});
  }
  static getDerivedStateFromError(error) { return {error}; }
  componentDidCatch(error, info) { console.error('[workbench] 界面渲染失败', error, info); }
  componentDidUpdate(previous) { if (this.state.error && previous.resetKey !== this.props.resetKey) this.reset(); }
  render() {
    if (!this.state.error) return this.props.children;
    return this.props.fallback ? this.props.fallback(this.state.error, this.reset) : null;
  }
}

/* --------------------------------------------------------------- overlay focus */

/* Overlays can stack (the command palette opens over the run drawer), so only
   the topmost one reacts to Escape and Tab. */
const overlayStack = [];

/* Keeps a dialog behaving like one: the page behind it does not scroll, Tab
   cannot wander into it, and focus returns to whatever opened it on close.
   Attach the returned ref to the dialog element. */
export function useOverlay(active, {onEscape} = {}) {
  const containerRef = useRef(null);
  const escapeRef = useRef(onEscape);
  escapeRef.current = onEscape;
  useEffect(() => {
    if (!active) return undefined;
    const token = {};
    overlayStack.push(token);
    const opener = document.activeElement;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const focusable = () => [...(containerRef.current?.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])') || [])]
      .filter(node => node.offsetWidth > 0 || node.offsetHeight > 0 || node === document.activeElement);
    const onKeyDown = event => {
      if (overlayStack[overlayStack.length - 1] !== token) return;
      if (event.key === 'Escape' && escapeRef.current) { event.preventDefault(); escapeRef.current(); return; }
      if (event.key !== 'Tab' || !containerRef.current) return;
      const nodes = focusable();
      if (!nodes.length) return;
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      if (!containerRef.current.contains(document.activeElement)) { event.preventDefault(); first.focus(); return; }
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener('keydown', onKeyDown, true);
    return () => {
      const index = overlayStack.indexOf(token);
      if (index >= 0) overlayStack.splice(index, 1);
      document.removeEventListener('keydown', onKeyDown, true);
      document.body.style.overflow = previousOverflow;
      if (opener instanceof HTMLElement && document.contains(opener)) opener.focus({preventScroll: true});
    };
  }, [active]);
  return containerRef;
}

/* ------------------------------------------------------------------ clipboard */

/* navigator.clipboard needs a secure context; local HTTP deployments fall back
   to the legacy path so copying keeps working off 127.0.0.1. */
export async function copyText(value) {
  const text = String(value ?? '');
  if (!text) return false;
  try {
    if (navigator.clipboard?.writeText) { await navigator.clipboard.writeText(text); return true; }
  } catch (_reason) { /* falls through to the legacy path */ }
  try {
    const area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', '');
    area.style.cssText = 'position:fixed;top:0;left:0;opacity:0;pointer-events:none';
    document.body.appendChild(area);
    area.select();
    const copied = document.execCommand('copy');
    area.remove();
    return copied;
  } catch (_reason) { return false; }
}

/* Copies and reports the outcome in one call, which is what every call site
   actually wants. */
export async function copyWithToast(value, label = '内容') {
  const copied = await copyText(value);
  notify(copied ? `${label} 已复制到剪贴板` : `${label} 复制失败，请手动选择文本`, copied ? 'ok' : 'error');
  return copied;
}

export function downloadText(filename, value, mime = 'text/markdown;charset=utf-8') {
  try {
    const blob = new Blob([String(value ?? '')], {type: mime});
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    return true;
  } catch (_reason) { return false; }
}

/* ------------------------------------------------------------------ timestamps */

export function absoluteTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return `${date.toLocaleDateString('zh-CN', {month: '2-digit', day: '2-digit'})} ${date.toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit', hour12: false})}`;
}

/* Recent activity reads better relatively; anything older keeps the absolute
   stamp so audit trails stay unambiguous. */
export function relativeTime(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const elapsed = Date.now() - date.getTime();
  if (elapsed < 0 || elapsed >= 86400000) return absoluteTime(value);
  if (elapsed < 45000) return '刚刚';
  if (elapsed < 3600000) return `${Math.max(1, Math.round(elapsed / 60000))} 分钟前`;
  return `${Math.floor(elapsed / 3600000)} 小时前`;
}

/* ------------------------------------------------------- persisted preferences */

const STORAGE_PREFIX = 'edr-ui:';

function readStored(key) {
  try { return window.localStorage.getItem(`${STORAGE_PREFIX}${key}`); } catch (_reason) { return null; }
}

function writeStored(key, value) {
  try {
    if (value === null || value === '') window.localStorage.removeItem(`${STORAGE_PREFIX}${key}`);
    else window.localStorage.setItem(`${STORAGE_PREFIX}${key}`, value);
  } catch (_reason) { /* private mode or a full quota simply disables the memory */ }
}

export function clearPersisted(key) { writeStored(key, null); }

/* useState for string preferences, mirrored into localStorage. `allowed`
   rejects stale values, so a narrow filter can never come back and leave the
   user staring at an empty list after a reload. */
export function usePersistentState(key, initial, {allowed} = {}) {
  const [value, setValue] = useState(() => {
    const stored = readStored(key);
    if (stored === null) return initial;
    if (allowed && !allowed.includes(stored)) return initial;
    return stored;
  });
  useEffect(() => { writeStored(key, allowed && !allowed.includes(value) ? null : value); }, [key, value]);
  return [value, setValue];
}

/* Same contract for free text (drafts): debounced so typing does not hammer
   localStorage, and capped so a runaway paste cannot fill the quota. */
export function usePersistentDraft(key, {limit = 8000, delay = 400} = {}) {
  const [value, setValue] = useState(() => (readStored(key) || '').slice(0, limit));
  useEffect(() => {
    const timer = setTimeout(() => writeStored(key, value.slice(0, limit)), delay);
    return () => clearTimeout(timer);
  }, [key, value, limit, delay]);
  return [value, setValue];
}
