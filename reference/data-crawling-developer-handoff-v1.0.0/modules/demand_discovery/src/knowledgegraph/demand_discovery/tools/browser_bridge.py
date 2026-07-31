"""DrissionPage-backed browser fetch bridge.

This transport is intentionally isolated and lazily imports DrissionPage so the
ordinary HTTP path and CI tests do not require a local browser session. To use
it, start Chrome with a debugging port (default 9222). Calls are serialized
because a single attached browser page is shared process-wide.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import urlencode


_BROWSER_LOCK = asyncio.Lock()


async def fetch_with_browser_session(
    url: str,
    *,
    timeout_ms: int = 30_000,
    port: int = 9222,
) -> str:
    async with _BROWSER_LOCK:
        return await asyncio.to_thread(
            _fetch_sync,
            url,
            timeout_ms,
            port,
        )


async def observe_with_browser_session(
    url: str,
    *,
    timeout_ms: int = 30_000,
    port: int = 9222,
) -> dict[str, str]:
    """Return a raw page snapshot for browser_observe.

    Target extraction lives in ``browser_actions.py``. The bridge only owns the
    browser session boundary, so models never get arbitrary JS or selectors.
    """

    html = await fetch_with_browser_session(url, timeout_ms=timeout_ms, port=port)
    return {"url": url, "html": html, "download_url": ""}


async def action_with_browser_session(
    *,
    action: str,
    target: dict[str, Any],
    value: str = "",
    timeout_ms: int = 30_000,
    port: int = 9222,
) -> dict[str, str]:
    """Execute a controlled browser action from an observed target payload."""

    destination = resolve_controlled_action_url(action, target, value)
    if action == "download_link":
        page_url = str(target.get("page_url", ""))
        html = await fetch_with_browser_session(page_url, timeout_ms=timeout_ms, port=port)
        return {"url": page_url, "html": html, "download_url": destination}
    html = await fetch_with_browser_session(destination, timeout_ms=timeout_ms, port=port)
    return {"url": destination, "html": html, "download_url": ""}


async def execute_javascript_with_browser_session(
    *,
    script: str,
    timeout_ms: int = 30_000,
    max_return_chars: int = 4000,
    allow_network_probe: bool = False,
    safety_policy: dict[str, object] | None = None,
    port: int = 9222,
) -> dict[str, object]:
    """Execute guarded JavaScript in the attached browser page.

    The model script is not the security boundary. This bridge installs a page
    runtime guard before executing the script so same-origin GET/HEAD probes are
    credential-free and dangerous browser APIs fail closed.
    """

    async with _BROWSER_LOCK:
        return await asyncio.to_thread(
            _execute_javascript_sync,
            script,
            timeout_ms,
            max_return_chars,
            allow_network_probe,
            dict(safety_policy or {}),
            port,
        )


def resolve_controlled_action_url(
    action: str,
    target: dict[str, Any],
    value: str = "",
) -> str:
    """Resolve the destination URL for an allowlisted browser action.

    This helper intentionally accepts only structured target payloads produced
    by ``browser_observe``. It rejects arbitrary JS, CSS selector, and open URL
    actions at the bridge boundary.
    """

    if action in {"click_link", "next_page", "download_link"}:
        url = str(target.get("url", "")).strip()
        if not url:
            raise ValueError(f"controlled browser action {action} requires target url")
        return url
    if action == "fill_input":
        page_url = str(target.get("page_url", "")).strip()
        if not page_url:
            raise ValueError("controlled browser action fill_input requires page_url")
        return page_url
    if action == "submit_form":
        action_url = str(target.get("action_url", "") or target.get("page_url", "")).strip()
        if not action_url:
            raise ValueError("controlled browser action submit_form requires action_url")
        filled_values = {
            str(key): str(item)
            for key, item in dict(target.get("filled_values", {}) or {}).items()
        }
        if value and not filled_values:
            filled_values[str(target.get("name", "q") or "q")] = value
        if not filled_values:
            return action_url
        separator = "&" if "?" in action_url else "?"
        return f"{action_url}{separator}{urlencode(filled_values)}"
    raise ValueError(f"unsupported controlled browser action: {action}")


def _fetch_sync(url: str, timeout_ms: int, port: int) -> str:
    try:
        from DrissionPage import ChromiumOptions, ChromiumPage
    except Exception as exc:  # pragma: no cover - depends on local browser stack
        raise RuntimeError(
            "browser_session transport requires DrissionPage and a Chrome "
            f"debugging port on {port}"
        ) from exc
    options = ChromiumOptions().set_local_port(port)
    page = ChromiumPage(options)
    page.set.timeouts(page_load=max(timeout_ms / 1000, 1))
    page.get(url)
    return str(page.html)


def _execute_javascript_sync(
    script: str,
    timeout_ms: int,
    max_return_chars: int,
    allow_network_probe: bool,
    safety_policy: dict[str, object],
    port: int,
) -> dict[str, object]:
    try:
        from DrissionPage import ChromiumOptions, ChromiumPage
    except Exception as exc:  # pragma: no cover - depends on local browser stack
        raise RuntimeError(
            "browser JavaScript execution requires DrissionPage and a Chrome "
            f"debugging port on {port}"
        ) from exc

    options = ChromiumOptions().set_local_port(port)
    page = ChromiumPage(options)
    page.set.timeouts(page_load=max(timeout_ms / 1000, 1))
    guarded_script = _guarded_javascript(
        script=script,
        max_return_chars=max_return_chars,
        allow_network_probe=allow_network_probe,
        safety_policy=safety_policy,
    )
    try:
        result = page.run_js(guarded_script, timeout=max(timeout_ms / 1000, 1))
    except TypeError:  # pragma: no cover - DrissionPage version compatibility
        result = page.run_js(guarded_script)
    if isinstance(result, dict):
        return result
    return {
        "status": "success",
        "result": result,
        "url_after": str(getattr(page, "url", "")),
        "title_after": str(getattr(page, "title", "")),
        "html_after": str(getattr(page, "html", "")),
        "network_delta": [],
    }


def _guarded_javascript(
    *,
    script: str,
    max_return_chars: int,
    allow_network_probe: bool,
    safety_policy: dict[str, object],
) -> str:
    policy = dict(safety_policy)
    policy.setdefault("allow_network_probe", allow_network_probe)
    policy.setdefault("allowed_methods", ["GET", "HEAD"])
    policy.setdefault("force_credentials", "omit")
    policy.setdefault("max_return_chars", max_return_chars)
    policy_json = json.dumps(policy, ensure_ascii=False)
    script_json = json.dumps(script)
    return f"""
return (async () => {{
  const __policy = {policy_json};
  const __userScript = {script_json};
  const __networkDelta = [];
  const __actualWindow = window;
  const __actualDocument = document;
  const __actualLocation = window.location;
  const __blocked = (name) => {{
    const err = new Error(`${{name}} is blocked by browser javascript safety policy`);
    err.name = 'SecurityError';
    throw err;
  }};
  const __queryKeys = (url) => Array.from(new URL(url).searchParams.keys()).sort();
  const __originalFetch = __actualWindow.fetch ? __actualWindow.fetch.bind(__actualWindow) : null;
  const __safeFetch = async (input, init = {{}}) => {{
    if (!__policy.allow_network_probe) __blocked('fetch');
    if (__networkDelta.length >= (__policy.max_requests || 0)) __blocked('fetch.max_requests');
    const rawUrl = typeof input === 'string' ? input : input.url;
    const url = new URL(rawUrl, __actualLocation.href);
    const allowedOrigin = __policy.allowed_origin || __actualLocation.origin;
    if (url.origin !== allowedOrigin) __blocked('fetch.cross_origin');
    const method = String((init && init.method) || (input && input.method) || 'GET').toUpperCase();
    const allowedMethods = __policy.allowed_methods || ['GET', 'HEAD'];
    if (!allowedMethods.includes(method)) __blocked('fetch.method');
    const headers = new Headers((init && init.headers) || (input && input.headers) || {{}});
    for (const name of Array.from(headers.keys())) {{
      const lowered = name.toLowerCase();
      if (lowered === 'authorization' || lowered === 'cookie') __blocked('fetch.headers');
    }}
    if (!__originalFetch) __blocked('fetch.unavailable');
    const response = await __originalFetch(url.href, {{
      ...init,
      method,
      credentials: 'omit',
      body: undefined,
      headers
    }});
    __networkDelta.push({{
      method,
      scheme: url.protocol.replace(':', ''),
      host: url.hostname,
      path: url.pathname,
      query_keys: __queryKeys(url.href),
      status: response.status,
      content_type: response.headers.get('content-type') || '',
      purpose_guess: url.pathname.includes('search') ? 'search_results' : 'unknown'
    }});
    return response;
  }};
  const __blockedFunction = (name) => function() {{ __blocked(name); }};
  const __isSensitiveElement = (node) => {{
    if (!node || typeof node !== 'object') return false;
    const tagName = String(node.tagName || node.nodeName || '').toLowerCase();
    if (tagName !== 'input') return false;
    let typeValue = '';
    try {{
      typeValue = String(node.type || '').toLowerCase();
      if (!typeValue && typeof node.getAttribute === 'function') {{
        typeValue = String(node.getAttribute('type') || '').toLowerCase();
      }}
    }} catch (_) {{
      typeValue = '';
    }}
    return typeValue === 'password' || typeValue === 'hidden';
  }};
  const __containsSensitiveElement = (node) => {{
    if (__isSensitiveElement(node)) return true;
    if (!node || typeof node.querySelector !== 'function') return false;
    try {{
      return !!node.querySelector('input[type="password"], input[type="hidden"]');
    }} catch (_) {{
      return false;
    }}
  }};
  const __sanitizeNode = (node) => {{
    if (!node || typeof node !== 'object') return node;
    if (Array.isArray(node)) return node.map((item) => __sanitizeNode(item));
    return new Proxy(node, {{
      get(target, prop) {{
        if (__isSensitiveElement(target)) {{
          if (prop === 'value' || prop === 'defaultValue' || prop === 'outerHTML' || prop === 'innerHTML' || prop === 'textContent' || prop === 'innerText') {{
            __blocked('sensitive_form_field');
          }}
          if (prop === 'getAttribute') {{
            return (name) => {{
              if (String(name).toLowerCase() === 'value') __blocked('sensitive_form_field');
              return target.getAttribute(name);
            }};
          }}
        }}
        if ((prop === 'outerHTML' || prop === 'innerHTML' || prop === 'textContent' || prop === 'innerText') && __containsSensitiveElement(target)) {{
          __blocked('sensitive_form_field');
        }}
        const value = target[prop];
        if (typeof value === 'function') {{
          if (prop === 'querySelector' || prop === 'getElementById') {{
            return (...args) => __sanitizeNode(value.apply(target, args));
          }}
          if (prop === 'querySelectorAll' || prop === 'getElementsByTagName' || prop === 'getElementsByClassName') {{
            return (...args) => Array.from(value.apply(target, args)).map((item) => __sanitizeNode(item));
          }}
          return value.bind(target);
        }}
        return __sanitizeNode(value);
      }},
      set(target, prop, value) {{
        if (__isSensitiveElement(target) && (prop === 'value' || prop === 'defaultValue')) {{
          __blocked('sensitive_form_field');
        }}
        target[prop] = value;
        return true;
      }}
    }});
  }};
  const __documentProxy = new Proxy(__actualDocument, {{
    get(target, prop) {{
      if (prop === 'cookie') __blocked('document.cookie');
      if (prop === 'documentElement' || prop === 'body' || prop === 'forms') return __sanitizeNode(target[prop]);
      if (prop === 'querySelector' || prop === 'getElementById') {{
        return (...args) => __sanitizeNode(target[prop].apply(target, args));
      }}
      if (prop === 'querySelectorAll' || prop === 'getElementsByTagName' || prop === 'getElementsByClassName') {{
        return (...args) => Array.from(target[prop].apply(target, args)).map((item) => __sanitizeNode(item));
      }}
      const value = target[prop];
      return typeof value === 'function' ? value.bind(target) : value;
    }},
    set(target, prop, value) {{
      if (prop === 'cookie') __blocked('document.cookie');
      target[prop] = value;
      return true;
    }},
    defineProperty(target, prop, descriptor) {{
      if (prop === 'cookie') __blocked('document.cookie');
      return Reflect.defineProperty(target, prop, descriptor);
    }},
    deleteProperty(target, prop) {{
      if (prop === 'cookie') __blocked('document.cookie');
      return Reflect.deleteProperty(target, prop);
    }}
  }});
  let __sandboxWindow;
  const __windowProxy = new Proxy(__actualWindow, {{
    get(target, prop) {{
      if (prop === 'window' || prop === 'self' || prop === 'globalThis' || prop === 'top' || prop === 'parent' || prop === 'frames') return __sandboxWindow;
      if (prop === 'document') return __documentProxy;
      if (prop === 'fetch') return __safeFetch;
      if (prop === 'XMLHttpRequest') return __blockedFunction('XMLHttpRequest');
      if (prop === 'WebSocket') return __blockedFunction('WebSocket');
      if (prop === 'localStorage' || prop === 'sessionStorage' || prop === 'indexedDB') __blocked(String(prop));
      const value = target[prop];
      return typeof value === 'function' ? value.bind(target) : value;
    }},
    set(target, prop, value) {{
      if (prop === 'localStorage' || prop === 'sessionStorage' || prop === 'indexedDB') __blocked(String(prop));
      target[prop] = value;
      return true;
    }},
    defineProperty(target, prop, descriptor) {{
      if (prop === 'localStorage' || prop === 'sessionStorage' || prop === 'indexedDB') __blocked(String(prop));
      return Reflect.defineProperty(target, prop, descriptor);
    }},
    deleteProperty(target, prop) {{
      if (prop === 'localStorage' || prop === 'sessionStorage' || prop === 'indexedDB') __blocked(String(prop));
      return Reflect.deleteProperty(target, prop);
    }}
  }});
  __sandboxWindow = __windowProxy;
  const __sandboxBindings = {{
    window: __sandboxWindow,
    self: __sandboxWindow,
    globalThis: __sandboxWindow,
    top: __sandboxWindow,
    parent: __sandboxWindow,
    frames: __sandboxWindow,
    document: __documentProxy,
    location: __actualLocation,
    history: __actualWindow.history,
    fetch: __safeFetch,
    XMLHttpRequest: __blockedFunction('XMLHttpRequest'),
    WebSocket: __blockedFunction('WebSocket'),
    localStorage: undefined,
    sessionStorage: undefined,
    indexedDB: undefined,
    URL,
    URLSearchParams,
    Headers,
    Request,
    Response,
    JSON,
    Array,
    Object,
    String,
    Number,
    Boolean,
    Date,
    Math,
    RegExp,
    Promise,
    console,
    setTimeout: __actualWindow.setTimeout ? __actualWindow.setTimeout.bind(__actualWindow) : undefined,
    clearTimeout: __actualWindow.clearTimeout ? __actualWindow.clearTimeout.bind(__actualWindow) : undefined,
    encodeURI,
    encodeURIComponent,
    decodeURI,
    decodeURIComponent,
    parseInt,
    parseFloat,
    isNaN,
    isFinite
  }};
  Object.defineProperty(__sandboxBindings, 'localStorage', {{ get: () => __blocked('localStorage') }});
  Object.defineProperty(__sandboxBindings, 'sessionStorage', {{ get: () => __blocked('sessionStorage') }});
  Object.defineProperty(__sandboxBindings, 'indexedDB', {{ get: () => __blocked('indexedDB') }});
  const __sandbox = new Proxy(__sandboxBindings, {{
    has() {{ return true; }},
    get(target, prop) {{
      if (prop in target) return Reflect.get(target, prop, target);
      return Reflect.get(__windowProxy, prop, __windowProxy);
    }},
    set(target, prop, value) {{
      target[prop] = value;
      return true;
    }},
    defineProperty(target, prop, descriptor) {{ return Reflect.defineProperty(target, prop, descriptor); }},
    deleteProperty(target, prop) {{ return Reflect.deleteProperty(target, prop); }}
  }});
  try {{
    const __fn = new Function(
      '__sandbox',
      '__sandboxWindow',
      'return (async function() {{ with (__sandbox) {{\\n' + __userScript + '\\n}} }}).call(__sandboxWindow);'
    );
    const __result = await __fn(__sandbox, __sandboxWindow);
    return {{
      status: 'success',
      result: __result,
      url_after: __actualLocation.href,
      title_after: __actualDocument.title || '',
      html_after: __actualDocument.documentElement ? __actualDocument.documentElement.outerHTML : '',
      network_delta: __networkDelta
    }};
  }} catch (error) {{
    return {{
      status: 'failed',
      error: {{
        name: error && error.name ? String(error.name) : 'Error',
        message: error && error.message ? String(error.message) : String(error),
        line: error && error.lineNumber ? Number(error.lineNumber) : 0,
        column: error && error.columnNumber ? Number(error.columnNumber) : 0
      }},
      result: null,
      url_after: __actualLocation.href,
      title_after: __actualDocument.title || '',
      html_after: __actualDocument.documentElement ? __actualDocument.documentElement.outerHTML : '',
      network_delta: __networkDelta
    }};
  }}
}})();
"""
