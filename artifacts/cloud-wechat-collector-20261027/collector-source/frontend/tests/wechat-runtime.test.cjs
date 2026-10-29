const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

const root = resolve(__dirname, '../..');
function errorRuntime() {
  const listeners = {};
  const window = { addEventListener: (name, callback) => { listeners[name] = callback; } };
  vm.runInNewContext(readFileSync(resolve(root, 'frontend/inject/error.js'), 'utf8'), { window, URL });
  window.errorModal.setView({ render() {} });
  return { listeners, model: window.errorModal };
}

test('微信正文图片、预加载 iframe 和浏览器扩展失败不会阻塞文章', () => {
  const { listeners, model } = errorRuntime();
  for (const [tagName, src] of [
    ['IFRAME', 'https://mp.weixin.qq.com/s?__biz=A&key=test-private'],
    ['IMG', 'https://mmbiz.qpic.cn/image'],
    ['SCRIPT', 'chrome-extension://example/resource/script.js'],
    ['SCRIPT', 'https://res.wx.qq.com/page.js'],
  ]) listeners.error({ target: { tagName, src } });
  listeners.unhandledrejection({ reason: new Error('Third-party failure') });
  assert.equal(model.visible, false);
  assert.equal(model.errors.length, 0);
});

test('采集器脚本失败仍提示，但隐藏 URL 参数和凭据', () => {
  const { listeners, model } = errorRuntime();
  listeners.error({ target: { tagName: 'SCRIPT', src: 'https://mp.weixin.qq.com/__assets/wxmp/inject/mp.main.js?key=test-private' } });
  assert.equal(model.visible, true);
  assert.equal(model.errors.length, 1);
  assert.equal(JSON.stringify(model.errors).includes('test-private'), false);
  model.show(new Error('用户主动操作失败'));
  assert.equal(model.errors.length, 2);
  for (let i = 0; i < 30; i++) model.show('Failure ' + i);
  assert.equal(model.errors.length, 20);
});

async function articleRuntime({ api = 'http://127.0.0.1:2022', key = 'test-key', pageData = true, reader = false, history = false } = {}) {
  const calls = [];
  const warnings = [];
  const pathname = history ? '/mp/profile_ext?action=home&' : '/s?';
  const location = new URL('https://mp.weixin.qq.com' + pathname + '__biz=A&mid=1&idx=1&sn=s&key=' + key + '&uin=test-uin&pass_ticket=test-ticket');
  let onLoad;
  const window = { location, cgiDataNew: pageData ? { bizuin: 'A', title: '文章' } : undefined };
  const sockets = [];
  if (reader) Object.assign(window, {
    WebSocket: class {
      constructor(url) { this.url = url; this.readyState = 1; this.sent = []; sockets.push(this); }
      send(value) { this.sent.push(JSON.parse(value)); }
      close() { this.readyState = 3; }
    },
    addEventListener() {}, setInterval() {}, clearInterval() {}, setTimeout() {},
  });
  const document = {
    getElementById: () => ({}),
    querySelector: () => ({ textContent: '人民日报' }),
  };
  const log = new Proxy({}, { get: () => () => log });
  const WXU = {
    config: { officialAccountEnabled: true, officialServerRefreshToken: '' }, log,
    onWindowLoaded: (callback) => { onLoad = callback; }, observe_node() {}, downloader: { browse() {} },
  };
  const runtime = vm.createContext({ window, document, location, URL, URLSearchParams, WXU,
    WXEnv: { get: () => api },
    console: { warn: (line) => warnings.push(line) }, AbortSignal,
    Timeless: { kit: { HttpClientCore: class {}, RequestCore: class {}, request_factory: () => ({}) }, web: { provide_http_client() {} } },
    fetch: async (url, options) => {
      calls.push({ url, body: options.body ? JSON.parse(options.body) : null });
      return { ok: true, status: 200, json: async () => ({ code: 0 }), text: async () => '{"ret":0,"general_msg_list":"{\\"list\\":[]}","can_msg_continue":0}' };
    },
  });
  vm.runInContext(readFileSync(resolve(root, 'pkg/scraper/wxmp/inject/mp.utils.js'), 'utf8'), runtime);
  vm.runInContext(readFileSync(resolve(root, 'pkg/scraper/wxmp/inject/mp.main.js'), 'utf8'), runtime);
  onLoad();
  await new Promise(setImmediate);
  return { calls, warnings, window, sockets };
}

test('在微信打开文章即自动登记精确账号，只把凭据交给本机采集器', async () => {
  const { calls, window } = await articleRuntime();
  assert.equal(calls.length, 1);
  assert.equal(new URL(calls[0].url).origin, 'http://127.0.0.1:2022');
  assert.equal(new URL(calls[0].url).pathname, '/api/mp/refresh');
  assert.equal(calls[0].body.biz, 'A');
  assert.equal(calls[0].body.nickname, '人民日报');
  assert.equal(calls[0].body.key, 'test-key');
  assert.equal(window.__wxmp_account_registered__, true);
});

test('缺失 cgiDataNew 不崩溃；无微信凭据和非本机服务不能冒充登记成功', async () => {
  assert.equal((await articleRuntime({ pageData: false })).calls.length, 1);
  assert.equal((await articleRuntime({ key: '' })).calls.length, 0);
  assert.equal((await articleRuntime({ api: 'https://unrelated.example' })).calls.length, 0);
});

test('Mac 正文通道只连本机，拒绝站外、跨账号和任意 JSAPI', async () => {
  const { sockets, calls } = await articleRuntime({ reader: true });
  assert.equal(sockets.length, 1);
  assert.equal(sockets[0].url, 'ws://127.0.0.1:2022/ws/mp');
  for (const url of ['https://evil.example/s/test', 'https://mp.weixin.qq.com/s?__biz=B', 'https://mp.weixin.qq.com/cgi-bin/searchbiz']) {
    await sockets[0].onmessage({ data: JSON.stringify({ type: 'api_call', data: { id: '1', key: 'key:fetch_page_content', data: { url } } }) });
    assert.equal(sockets[0].sent.at(-1).data.errCode, 1001);
  }
  await sockets[0].onmessage({ data: JSON.stringify({ type: 'api_call', data: { id: '2', key: 'key:jsapi', data: { method: 'sendAppMessage' } } }) });
  assert.equal(sockets[0].sent.at(-1).data.errCode, 1001);
  assert.equal(calls.length, 1); // 只有原有的本机登记请求。
  assert.equal((await articleRuntime({ reader: true, api: 'https://remote.example' })).sockets.length, 0);
});

test('历史请求在微信页面补齐会话，返回给平台的 URL 不含临时凭据', async () => {
  const { sockets, calls } = await articleRuntime({ reader: true });
  const url = 'https://mp.weixin.qq.com/mp/profile_ext?action=getmsg&__biz=A&offset=10';
  await sockets[0].onmessage({ data: JSON.stringify({ type: 'api_call', data: { id: '3', key: 'key:fetch_page_content', data: { url } } }) });
  const request = new URL(calls.at(-1).url);
  assert.equal(request.searchParams.get('key'), 'test-key');
  assert.equal(request.searchParams.get('offset'), '10');
  assert.equal(sockets[0].sent.at(-1).data.errCode, 0);
  assert.equal(sockets[0].sent.at(-1).data.data.url, url);
  assert.equal(JSON.stringify(sockets[0].sent).includes('test-key'), false);
});

test('公众号历史消息页也建立读取连接，不依赖先打开单篇文章', async () => {
  const { sockets, calls } = await articleRuntime({ reader: true, history: true, pageData: false });
  assert.equal(sockets.length, 1);
  const url = 'https://mp.weixin.qq.com/mp/profile_ext?action=getmsg&__biz=A&offset=20';
  await sockets[0].onmessage({ data: JSON.stringify({ type: 'api_call', data: { id: 'history', key: 'key:fetch_page_content', data: { url } } }) });
  const request = new URL(calls.at(-1).url);
  assert.equal(request.searchParams.get('offset'), '20');
  assert.equal(request.searchParams.get('key'), 'test-key');
  assert.equal(request.searchParams.get('uin'), 'test-uin');
  assert.equal(sockets[0].sent.at(-1).data.errCode, 0);
  assert.equal(JSON.stringify(sockets[0].sent).includes('test-key'), false);
});
