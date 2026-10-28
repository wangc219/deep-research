/**
 * 前端 Hash 路由管理器
 */
const Router = {
    routes: {},
    currentPage: null,
    currentKey: null,
    pageCache: {},

    init() {
        // 注册路由
        this.routes = { login: LoginPage, accounts: AccountsPage, articles: ArticlesPage,
            download: DownloadPage, history: HistoryPage, proxy: ProxyPage, settings: SettingsPage };
        // 监听 hash 变化
        window.addEventListener('hashchange', () => this.handleRouting());
        document.querySelectorAll('.nav-item').forEach(item => {
            item.addEventListener('click', (event) => {
                const page = item.getAttribute('data-page');
                if (page && window.location.href.startsWith('about:srcdoc')) {
                    event.preventDefault();
                    this.navigate(page);
                    return;
                }
                if (page && page === this.currentKey) {
                    event.preventDefault();
                    this.refreshCurrent();
                }
            });
        });

        document.addEventListener('click', event => {
            if (event.defaultPrevented || !window.location.href.startsWith('about:srcdoc')) return;
            const link = event.target.closest('a[href^="#"]');
            if (!link) return;
            event.preventDefault();
            this.embeddedHash = link.getAttribute('href').slice(1);
            this.handleRouting();
        });

        // 首次加载路由
        this.handleRouting();
    },

    async handleRouting() {
        const hash = this.embeddedHash || window.location.hash.slice(1) || 'login';
        const pageKey = hash.split('?')[0]; // 去掉查询参数
        const page = this.routes[pageKey];

        // 公众号精简模式：未打包的页面直接回退，避免渲染出调用 501 接口的空页面
        if (window.MP_MODE && Array.isArray(window.MP_MODE.allowed) &&
            window.MP_MODE.allowed.indexOf(pageKey) === -1) {
            window.location.hash = '#' + window.MP_MODE.fallback;
            return;
        }

        if (!page) {
            window.location.hash = '#login';
            return;
        }

        const hasParams = hash.includes('?');
        const routeParams = Object.fromEntries(new URLSearchParams(hash.split('?')[1] || ''));
        if (hasParams && this.pageCache[pageKey]) {
            this.pageCache[pageKey].el.remove();
            delete this.pageCache[pageKey];
        }
        this.currentPage = page;
        this.currentKey = pageKey;

        // 更新导航栏激活状态
        this.updateNavUI(pageKey);

        const container = document.getElementById('page-container');
        if (!container) return;

        Array.from(container.children).forEach(child => {
            if (!child.classList.contains('route-page')) child.remove();
        });

        Object.values(this.pageCache).forEach(entry => {
            if (entry.el) entry.el.style.display = 'none';
        });

        if (this.pageCache[pageKey]) {
            this.pageCache[pageKey].el.style.display = 'block';
            container.prepend(this.pageCache[pageKey].el);
            // 命中缓存页：触发可选的 onShow 钩子（用于数据刷新等轻量更新，无需重渲染 DOM）
            const cachedPage = this.pageCache[pageKey].page;
            if (cachedPage && typeof cachedPage.onShow === 'function') {
                try {
                    cachedPage.onShow();
                } catch (err) {
                    console.error('onShow hook error:', err);
                }
            }
            return;
        }

        // 显示加载动画
        const pageEl = document.createElement('div');
        pageEl.className = 'route-page';
        pageEl.dataset.page = pageKey;
        pageEl.innerHTML = `
            <div class="loading-screen">
                <div class="spinner"></div>
                <p>加载中...</p>
            </div>
        `;
        container.prepend(pageEl);

        try {
            // 渲染 HTML
            pageEl.innerHTML = page.render();
            this.pageCache[pageKey] = { page, el: pageEl };

            // 初始化新页面
            if (typeof page.init === 'function') {
                await page.init(routeParams);
            }
        } catch (err) {
            console.error('Routing load error:', err);
            pageEl.innerHTML = `
                <div style="text-align: center; padding: 40px; color: var(--error);">
                    <h3>❌ 页面加载失败</h3>
                    <p style="margin-top: var(--spacing-sm); color: var(--text-muted);">${err.message || err}</p>
                    <button class="btn btn-primary" onclick="Router.handleRouting()" style="margin-top: var(--spacing-md);">重新加载</button>
                </div>
            `;
        }
    },

    async refreshCurrent() {
        if (!this.currentKey) return;
        const cached = this.pageCache[this.currentKey];
        if (!cached) {
            await this.handleRouting();
            return;
        }
        if (cached.page && typeof cached.page.destroy === 'function') {
            try {
                cached.page.destroy();
            } catch (err) {
                console.error('Destroying page error:', err);
            }
        }
        delete this.pageCache[this.currentKey];
        cached.el.remove();
        await this.handleRouting();
    },

    updateNavUI(activeKey) {
        const navItems = document.querySelectorAll('.nav-item');
        navItems.forEach(item => {
            const page = item.getAttribute('data-page');
            if (page === activeKey) {
                item.classList.add('active');
            } else {
                item.classList.remove('active');
            }
        });

        const activeGroup = ['proxy', 'settings'].includes(activeKey) ? 'common' : 'wechat';
        const groups = ['wechat', 'common'];
        groups.forEach(g => {
            const itemsEl = document.getElementById(`items-${g}`);
            const titleEl = document.querySelector(`.nav-group-title[data-group="${g}"]`);
            const arrowEl = titleEl ? titleEl.querySelector('.group-arrow') : null;
            
            if (g === activeGroup) {
                if (itemsEl) {
                    itemsEl.classList.remove('collapsed');
                    if (arrowEl) arrowEl.textContent = '▼';
                }
            } else {
                if (itemsEl) {
                    itemsEl.classList.add('collapsed');
                    if (arrowEl) arrowEl.textContent = '▶';
                }
            }
        });
    },

    navigate(path, params) {
        let hash = '#' + path;
        if (params) {
            const qs = new URLSearchParams(params).toString();
            if (qs) hash += '?' + qs;
        }
        if (window.location.href.startsWith('about:srcdoc')) {
            if (this.currentKey === path && !params) return this.refreshCurrent();
            this.embeddedHash = hash.slice(1);
            this.handleRouting();
        } else {
            window.location.hash = hash;
        }
    }
};
