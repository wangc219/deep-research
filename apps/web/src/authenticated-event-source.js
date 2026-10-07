/** Fetch-backed SSE keeps Bearer credentials out of URLs and browser history. */
export class AuthenticatedEventSource extends EventTarget {
  static CLOSED = 2;
  readyState = 0;
  onopen = null;
  onerror = null;
  constructor(url, headers = {}) {
    super();
    this.url = url;
    this.headers = headers;
    this.controller = new AbortController();
    this.lastEventId = '';
    void this.connect();
  }
  close() {
    this.readyState = 2;
    clearTimeout(this.retry);
    this.controller.abort();
  }
  async connect() {
    try {
      const token = globalThis.localStorage?.getItem('user_token');
      const response = await fetch(this.url, {
        headers: { ...this.headers, Accept: 'text/event-stream',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
          ...(this.lastEventId ? { 'Last-Event-ID': this.lastEventId } : {}) },
        signal: this.controller.signal
      });
      if (!response.ok || !response.body) {
        if ([401, 403, 404].includes(response.status)) this.close();
        throw new Error(`SSE HTTP ${response.status}`);
      }
      this.readyState = 1;
      this.onopen?.(new Event('open'));
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let pending = '';
      let type = 'message';
      let data = [];
      try {
        while (this.readyState !== 2) {
          const chunk = await reader.read();
          if (chunk.done) break;
          pending += decoder.decode(chunk.value, { stream: true });
          let end;
          while ((end = pending.indexOf('\n')) >= 0) {
            const line = pending.slice(0, end).replace(/\r$/, '');
            pending = pending.slice(end + 1);
            if (!line) {
              if (data.length) this.dispatchEvent(new MessageEvent(type, { data: data.join('\n'), lastEventId: this.lastEventId }));
              type = 'message'; data = [];
            } else if (line.startsWith('event:')) type = line.slice(6).trim();
            else if (line.startsWith('id:')) this.lastEventId = line.slice(3).trim();
            else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''));
          }
        }
      } finally { reader.releaseLock(); }
    } catch (error) {
      if (error.name !== 'AbortError') this.onerror?.(new Event('error'));
    }
    if (this.readyState !== 2) {
      this.readyState = 0;
      this.retry = setTimeout(() => void this.connect(), 2000);
    }
  }
}
