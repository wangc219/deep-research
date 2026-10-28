/**
 * API 调用封装
 * 统一处理请求、错误和 loading 状态
 */
const API = {
    baseUrl: '',

    async request(url, options = {}) {
        const { method = 'GET', body = null, showError = true } = options;

        const fetchOptions = {
            method,
            headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'WechatMP', 'X-Platform-Origin': window.parent.location.origin },
        };

        if (body) {
            fetchOptions.body = JSON.stringify(body);
        }

        try {
            const resp = await fetch(`${this.baseUrl}${url}`, fetchOptions);
            if (resp.status === 401) { window.parent.postMessage({ type: 'wechat-mp-session-expired' }, window.parent.location.origin); }
            const text = await resp.text();
            let data = {};
            let isJson = true;
            try {
                data = JSON.parse(text);
            } catch (jsonErr) {
                isJson = false;
                data = { error: `服务响应解析失败 (HTTP ${resp.status})` };
            }

            if (!resp.ok || !isJson) {
                const errMsg = data.error || data.message || `HTTP ${resp.status}`;
                if (data && (data.need_verify || data.waterwall)) {
                    if (window.WaterWall && typeof WaterWall.handleDetection === 'function') {
                        WaterWall.handleDetection(data.waterwall || data);
                    }
                }
                if (showError) Toast.error(errMsg);
                // 保留结构化错误码，便于调用方区分「未登录」「风控」等可引导的场景
                const error = new Error(errMsg);
                error.code = data.code || '';
                error.status = resp.status;
                error.data = data;
                throw error;
            }

            return data;
        } catch (err) {
            if (err.name === 'TypeError' && err.message.includes('fetch')) {
                if (showError) Toast.error('网络连接失败，请检查服务是否运行');
            }
            throw err;
        }
    },

    get(url, opts) {
        return this.request(url, { method: 'GET', ...opts });
    },

    post(url, body, opts) {
        return this.request(url, { method: 'POST', body, ...opts });
    },

    put(url, body, opts) {
        return this.request(url, { method: 'PUT', body, ...opts });
    },

    delete(url, opts) {
        return this.request(url, { method: 'DELETE', ...opts });
    },

    // ── Auth API ──────────────────────────────────────
    auth: {
        status() { return API.get('/api/wechat-mp/app/api/auth/status', { showError: false }); },
        login() { return API.post('/api/wechat-mp/app/api/auth/login'); },
        logout() { return API.post('/api/wechat-mp/app/api/auth/logout'); },
        cancel() { return API.post('/api/wechat-mp/app/api/auth/cancel'); },
        checkCredentials() { return API.get('/api/wechat-mp/app/api/auth/check-credentials', { showError: false }); },
    },

    // ── Account Pool API ─────────────────────────────
    accountPool: {
        list()                     { return API.get('/api/wechat-mp/app/api/account-pool'); },
        summary()                  { return API.get('/api/wechat-mp/app/api/account-pool/summary', { showError: false }); },
        remove(id)                 { return API.delete(`/api/wechat-mp/app/api/account-pool/${id}`); },
        events()                   { return API.get('/api/wechat-mp/app/api/account-pool/events', { showError: false }); },
        getAutoRefreshConfig()     { return API.get('/api/wechat-mp/app/api/account-pool/auto-refresh-config', { showError: false }); },
        toggleAutoRefresh(enabled) { return API.post('/api/wechat-mp/app/api/account-pool/auto-refresh-toggle', { enabled }); },
        syncManual()               { return API.post('/api/wechat-mp/app/api/account-pool/sync-manual'); },
    },

    // ── Accounts API ─────────────────────────────────
    accounts: {
        list() { return API.get('/api/wechat-mp/app/api/accounts'); },
        search(keyword) { return API.post('/api/wechat-mp/app/api/accounts/search', { keyword }); },
        add(account) { return API.post('/api/wechat-mp/app/api/accounts', account); },
        remove(fakeid) { return API.delete(`/api/wechat-mp/app/api/accounts/${fakeid}`); },
        update(fakeid, data) { return API.put(`/api/wechat-mp/app/api/accounts/${fakeid}`, data); },
        rssSubscribe(fakeid, interval_minutes = 60) {
            return API.post(`/api/wechat-mp/app/api/accounts/${fakeid}/rss-subscribe`, { interval_minutes });
        },
        rssUnsubscribe(fakeid) {
            return API.delete(`/api/wechat-mp/app/api/accounts/${fakeid}/rss-subscribe`);
        },
        rssSubscriptions() { return API.get('/api/wechat-mp/app/api/accounts/rss-subscriptions'); },
        rssForceUpload(fakeid) { return API.post(`/api/wechat-mp/app/api/accounts/${fakeid}/rss-force-upload`); },
        rssUploadLog(account, limit = 30) {
            const qs = new URLSearchParams({ limit });
            if (account) qs.set('account', account);
            return API.get(`/api/wechat-mp/app/api/accounts/rss-upload-log?${qs.toString()}`);
        },
    },

    // ── Articles API ─────────────────────────────────
    articles: {
        list(fakeid, begin = 0, count = 10, keyword = '') {
            const params = new URLSearchParams({ begin, count, keyword });
            return API.get(`/api/wechat-mp/app/api/articles/list/${fakeid}?${params}`);
        },
        download(articles, accountName) {
            return API.post('/api/wechat-mp/app/api/articles/download', { articles, account_name: accountName });
        },
        downloadRange(payload) {
            return API.post('/api/wechat-mp/app/api/articles/download-range', payload);
        },
        cancelDownload(taskId) {
            return API.post(`/api/wechat-mp/app/api/articles/download-cancel/${taskId}`);
        },
        downloadByUrl(urls) {
            return API.post('/api/wechat-mp/app/api/articles/download-url', { urls });
        },
        downloadStatus(taskId) {
            return API.get(`/api/wechat-mp/app/api/articles/download-status/${taskId}`, { showError: false });
        },
        history(limit = 50) {
            return API.get(`/api/wechat-mp/app/api/articles/history?limit=${limit}`);
        },
        clearHistory() {
            return API.delete('/api/wechat-mp/app/api/articles/history');
        },
        deleteHistory(index) {
            return API.delete(`/api/wechat-mp/app/api/articles/history/${index}`);
        },
        openFolder(account = '') { return API.post('/api/wechat-mp/app/api/articles/open-folder', { account }); },
        openFile(path, type = null) { return API.post('/api/wechat-mp/app/api/articles/open-file', { path, type }); },
        openParent(path) { return API.post('/api/wechat-mp/app/api/articles/open-parent', { path }); },
    },

    // ── Proxy API ────────────────────────────────────
    proxy: {
        getConfig() { return API.get('/api/wechat-mp/app/api/proxy/config'); },
        saveConfig(config) { return API.post('/api/wechat-mp/app/api/proxy/config', config); },
        test(config) { return API.post('/api/wechat-mp/app/api/proxy/test', config); },
        getPool() { return API.get('/api/wechat-mp/app/api/proxy/pool'); },
        addToPool(proxy) { return API.post('/api/wechat-mp/app/api/proxy/pool', proxy); },
        removeFromPool(index) { return API.delete(`/api/wechat-mp/app/api/proxy/pool/${index}`); },
    },

    // ── Settings API ─────────────────────────────────
    settings: {
        get() { return API.get('/api/wechat-mp/app/api/settings'); },
        save(settings) { return API.post('/api/wechat-mp/app/api/settings', settings); },
    }
};
