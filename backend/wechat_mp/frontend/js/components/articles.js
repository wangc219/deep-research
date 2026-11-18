/**
 * 文章下载页面组件
 */
const ArticlesPage = {
    currentFakeid: '',
    currentName: '',
    articles: [],
    selectedArticles: new Set(),
    pageCache: {},
    loadedArticlesMap: new Map(),
    selectionMode: 'single',
    currentPage: 0,
    pageSize: 20,
    total: 0,
    totalExact: false,
    totalPages: null,
    totalPagesExact: false,
    confirmedTotalPages: null,
    minimumTotalPages: 1,
    pageCountLoading: false,
    _pageCountToken: 0,
    includePdf: false,
    stateFilter: 'all',
    keyword: '',
    dateSearchStart: 0,
    dateSearchEnd: 0,
    searchScanned: 0,
    searchScanComplete: true,
    downloadTaskId: null,
    _pollTimer: null,

    render() {
        return `
            <div class="page-header">
                <h2 class="page-title">文章下载</h2>
                <p class="page-description">选择公众号，浏览并下载文章</p>
            </div>

            <!-- 公众号选择器 -->
            <div class="card" style="margin-bottom: var(--spacing-lg);">
                <div class="card-header">
                    <h3 class="card-title">📌 选择公众号</h3>
                </div>
                <div id="account-selector" style="display: flex; flex-wrap: wrap; gap: 8px;">
                    <div class="spinner" style="margin: 0 auto;"></div>
                </div>
            </div>

            <!-- 文章列表区域 -->
            <div id="articles-section" style="display: none;">
                <div class="article-controls">
                    <div class="article-control-row">
                        <div class="search-box">
                            <svg class="search-icon" viewBox="0 0 24 24" fill="none">
                                <circle cx="11" cy="11" r="8" stroke="currentColor" stroke-width="2"/>
                                <line x1="21" y1="21" x2="16.65" y2="16.65" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
                            </svg>
                            <input type="text" class="form-input" id="search-article-input"
                                   placeholder="全局搜索该公众号全部文章标题..."
                                   onkeydown="if(event.key==='Enter') ArticlesPage.searchArticles()">
                        </div>
                        <button class="btn btn-secondary btn-sm" onclick="ArticlesPage.searchArticles()">搜索</button>
                        <button class="btn btn-secondary btn-sm" onclick="ArticlesPage.clearSearch()">清除</button>
                        <div class="article-mode-switch">
                            <button class="btn btn-primary btn-sm" id="btn-mode-single" onclick="ArticlesPage.setSelectionMode('single')">单篇</button>
                            <button class="btn btn-secondary btn-sm" id="btn-mode-multi" onclick="ArticlesPage.setSelectionMode('multi')">多选</button>
                        </div>
                    </div>
                    <div class="article-control-row article-date-row">
                        <span class="article-date-label">时间范围</span>
                        <input type="date" class="form-input" id="article-start-date">
                        <span class="article-date-separator">至</span>
                        <input type="date" class="form-input" id="article-end-date">
                        <select class="form-input" id="article-quick-date" onchange="ArticlesPage.onQuickDateChange(this.value)" style="width:auto;padding:4px 8px;font-size:.85rem;cursor:pointer;">
                            <option value="">快捷日期</option>
                            <option value="today">今天</option>
                            <option value="3days">近3天</option>
                            <option value="7days">近7天</option>
                            <option value="30days">近30天</option>
                            <option value="this_month">本月</option>
                        </select>
                        <button class="btn btn-secondary btn-sm" onclick="ArticlesPage.searchDateRange()">按时间搜索</button>
                        <button class="btn btn-primary btn-sm" onclick="ArticlesPage.downloadDateRange()">按时间下载</button>
                        <button class="btn btn-secondary btn-sm" onclick="ArticlesPage.clearDateFilter()">重置</button>
                        <label style="display:inline-flex;align-items:center;gap:6px;color:var(--text-secondary);font-size:.85rem;">
                            <input type="checkbox" id="article-include-pdf" onchange="ArticlesPage.setIncludePdf(this.checked)">
                            同时生成 PDF（可选）
                        </label>
                        <select class="form-input" id="article-state-filter" style="width:auto;" onchange="ArticlesPage.setStateFilter(this.value)">
                            <option value="all">全部状态</option>
                            <option value="not_downloaded">未下载</option>
                            <option value="downloaded">已下载未入库</option>
                            <option value="importing">入库中</option>
                            <option value="imported">已入库</option>
                            <option value="failed">失败</option>
                        </select>
                        
                        <!-- 多选操作控制按钮组 -->
                        <div id="multi-select-actions" style="display: none; align-items: center; gap: 8px; margin-left: auto;">
                            <button class="btn btn-secondary btn-sm" id="btn-select-all-loaded" onclick="ArticlesPage.selectAllLoaded()" title="全选所有已翻页加载且尚未下载的文章">
                                ☑️ 全选未下载 (<span id="selectable-total-count">0</span>)
                            </button>
                            <button class="btn btn-secondary btn-sm" onclick="ArticlesPage.clearSelection()">
                                ❌ 取消全选
                            </button>
                            <button class="btn btn-primary btn-sm" id="btn-download-selected" onclick="ArticlesPage.downloadSelected()" disabled>
                                📥 下载选中 (<span id="selected-count">0</span>)
                            </button>
                        </div>
                    </div>
                </div>

                <!-- 文章列表 -->
                <div id="articles-list" class="article-list">
                    <div class="empty-state">
                        <p class="empty-state-desc">请先选择一个公众号</p>
                    </div>
                </div>

                <!-- 分页 -->
                <div class="pagination" id="articles-pagination" style="display: none;">
                    <button class="btn btn-secondary btn-sm" onclick="ArticlesPage.prevPage()" id="btn-prev-page">上一页</button>
                    <span class="pagination-info" id="pagination-info">第 1 页</span>
                    <button class="btn btn-secondary btn-sm" onclick="ArticlesPage.nextPage()" id="btn-next-page">下一页</button>
                </div>
            </div>

            <!-- 下载进度 -->
            <div id="download-progress-section" style="display: none;">
                <div class="download-progress-card">
                    <div class="download-progress-header" style="display: flex; align-items: center; justify-content: space-between; gap: 8px;">
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <h3 class="card-title" style="color: #000000;">📥 下载进度</h3>
                            <span class="badge badge-info" id="download-status-badge">下载中</span>
                        </div>
                        <button class="btn btn-primary btn-sm" onclick="ArticlesPage.openFolder()" style="padding: 4px 10px; font-size: 0.85rem;">
                            📂 打开下载目录
                        </button>
                        <button class="btn btn-danger btn-sm" id="btn-cancel-download" onclick="ArticlesPage.cancelDownload()" style="padding: 4px 10px; font-size: 0.85rem; display: none;">
                            停止
                        </button>
                    </div>
                    <div class="progress-bar" style="margin-top: 12px;">
                        <div class="progress-fill" id="download-progress-bar" style="width: 0%"></div>
                    </div>
                    <div class="download-progress-stats">
                        <span>当前: <strong id="download-current">-</strong></span>
                        <span>完成: <strong id="download-completed">0</strong></span>
                        <span>失败: <strong id="download-failed">0</strong></span>
                        <span>总计: <strong id="download-total">0</strong></span>
                        <span id="download-scanned-wrap" style="display: none;">已扫描: <strong id="download-scanned">0</strong></span>
                    </div>
                    <div id="download-stop-reason" style="display: none; margin-top: 8px; color: var(--text-muted); font-size: 0.85rem;"></div>
                    <div id="download-note" style="margin-top: 12px; color: var(--text-muted); font-size: 0.85rem;">
                        下载完成后可在“下载历史”中查看文件列表。
                    </div>
                </div>
            </div>
        `;
    },

    async init(params = {}) {
        this.includePdf = localStorage.getItem('wechat-article-include-pdf') === 'true';
        await this.loadAccountSelector();
        const pdfToggle = document.getElementById('article-include-pdf');
        if (pdfToggle) pdfToggle.checked = this.includePdf;
        if (params.fakeid && params.name) {
            this.selectAccount(params.fakeid, params.name);
        }
    },

    destroy() {
        this._pageCountToken++;
        this.pageCountLoading = false;
        if (this._pollTimer) {
            clearInterval(this._pollTimer);
            this._pollTimer = null;
        }
    },

    async loadAccountSelector() {
        const container = document.getElementById('account-selector');
        try {
            const data = await API.accounts.list();
            const accounts = data.accounts || [];

            if (accounts.length === 0) {
                container.innerHTML = `
                    <div style="text-align: center; width: 100%; color: var(--text-muted); padding: 12px;">
                        还没有收藏公众号，<a href="#accounts" style="color: var(--primary); text-decoration: none;">去添加</a>
                    </div>
                `;
                return;
            }

            container.innerHTML = accounts.map(acc => `
                <button class="btn btn-secondary btn-sm account-selector-btn"
                        data-fakeid="${acc.fakeid}"
                        onclick="ArticlesPage.selectAccount('${acc.fakeid}', '${acc.nickname}')">
                    ${acc.nickname}
                </button>
            `).join('');
        } catch (err) {
            container.innerHTML = '<span style="color: var(--error);">加载失败</span>';
        }
    },

    async selectAccount(fakeid, name) {
        this.currentFakeid = fakeid;
        this.currentName = name;
        this.currentPage = 0;
        this.selectedArticles.clear();
        this.pageCache = {};
        this.loadedArticlesMap.clear();
        this.selectionMode = 'single';
        this.keyword = '';
        this.dateSearchStart = 0;
        this.dateSearchEnd = 0;
        this.searchScanned = 0;
        this.searchScanComplete = true;
        this.total = 0;
        this.totalExact = false;
        this.totalPages = null;
        this.totalPagesExact = false;
        this.confirmedTotalPages = null;
        this.minimumTotalPages = 1;
        this.pageCountLoading = true;
        const pageCountToken = ++this._pageCountToken;

        // 高亮选中的公众号
        document.querySelectorAll('.account-selector-btn').forEach(btn => {
            btn.classList.toggle('btn-primary', btn.dataset.fakeid === fakeid);
            btn.classList.toggle('btn-secondary', btn.dataset.fakeid !== fakeid);
        });

        document.getElementById('articles-section').style.display = 'block';
        document.getElementById('search-article-input').value = '';
        
        const startDateEl = document.getElementById('article-start-date');
        const endDateEl = document.getElementById('article-end-date');
        const quickDateEl = document.getElementById('article-quick-date');
        if (startDateEl) startDateEl.value = '';
        if (endDateEl) endDateEl.value = '';
        if (quickDateEl) quickDateEl.value = '';
        
        this.updateSelectedCount();
        this.updateModeUI();

        await this.loadArticles();
        void this.loadConfirmedPageCount(fakeid, pageCountToken);
    },

    async loadConfirmedPageCount(fakeid, token) {
        try {
            const data = await API.articles.pageCount(fakeid, this.pageSize);
            if (token !== this._pageCountToken || fakeid !== this.currentFakeid) return;
            const totalPages = Number(data.total_pages);
            if (data.total_pages_exact !== true || !Number.isInteger(totalPages) || totalPages < 1) return;

            this.confirmedTotalPages = totalPages;
            this.totalPages = totalPages;
            this.totalPagesExact = true;
            this.minimumTotalPages = totalPages;
            this.canMsgContinue = this.currentPage + 1 < totalPages ? 1 : 0;
            Object.entries(this.pageCache).forEach(([pageIndex, cached]) => {
                cached.totalPages = totalPages;
                cached.totalPagesExact = true;
                cached.minimumTotalPages = totalPages;
                cached.canMsgContinue = Number(pageIndex) + 1 < totalPages ? 1 : 0;
            });
        } catch (_err) {
            // 总页数统计失败不阻断文章浏览，继续展示保守的“至少 N 页”。
        } finally {
            if (token === this._pageCountToken && fakeid === this.currentFakeid) {
                this.pageCountLoading = false;
                this.updatePagination();
            }
        }
    },

    async loadArticles() {
        const container = document.getElementById('articles-list');

        // ⚡ 1. 内存缓存检查：已加载过的数据直接调取，无需重复请求接口
        if (this.pageCache[this.currentPage]) {
            const cached = this.pageCache[this.currentPage];
            this.articles = cached.articles;
            this.total = cached.total;
            this.totalExact = cached.totalExact;
            this.totalPages = cached.totalPages;
            this.totalPagesExact = cached.totalPagesExact;
            this.minimumTotalPages = cached.minimumTotalPages;
            this.canMsgContinue = cached.canMsgContinue;
            this.searchScanned = cached.searchScanned || 0;
            this.searchScanComplete = cached.searchScanComplete !== false;
            if (!this.hasActiveSearch() && this.confirmedTotalPages) {
                this.totalPages = this.confirmedTotalPages;
                this.totalPagesExact = true;
                this.minimumTotalPages = this.confirmedTotalPages;
                this.canMsgContinue = this.currentPage + 1 < this.confirmedTotalPages ? 1 : 0;
            }
            this.renderArticles();
            this.updatePagination();
            this.updateSelectedCount();
            return;
        }

        container.innerHTML = '<div class="loading-screen" style="min-height: 200px;"><div class="spinner"></div><p>加载文章列表...</p></div>';

        try {
            const begin = this.currentPage * this.pageSize;
            const data = this.hasActiveSearch()
                ? await API.articles.search(
                    this.currentFakeid,
                    this.keyword,
                    begin,
                    this.pageSize,
                    this.currentName,
                    this.dateSearchStart,
                    this.dateSearchEnd
                )
                : await API.articles.list(this.currentFakeid, begin, this.pageSize, '', this.currentName);

            this.articles = data.articles || [];
            if (!this.hasActiveSearch() && data.terminal_empty === true && this.currentPage > 0) {
                this.confirmedTotalPages = Math.max(1, Number(data.total_pages) || this.currentPage);
                this.currentPage = this.confirmedTotalPages - 1;
                const lastPage = this.pageCache[this.currentPage];
                if (lastPage) {
                    lastPage.canMsgContinue = 0;
                    lastPage.totalPages = this.confirmedTotalPages;
                    lastPage.totalPagesExact = true;
                    lastPage.minimumTotalPages = this.confirmedTotalPages;
                }
                Toast.info(`已加载全部历史文章，共 ${this.confirmedTotalPages} 页`);
                await this.loadArticles();
                return;
            }

            this.total = data.total || 0;
            this.totalExact = data.total_exact === true;
            this.totalPages = data.total_pages || null;
            this.totalPagesExact = data.total_pages_exact === true;
            this.minimumTotalPages = data.minimum_total_pages || (this.currentPage + 1);
            this.canMsgContinue = data.can_msg_continue !== undefined ? data.can_msg_continue : (this.articles.length > 0 ? 1 : 0);
            this.searchScanned = this.hasActiveSearch() ? (data.scanned || 0) : 0;
            this.searchScanComplete = this.hasActiveSearch() ? data.scan_complete !== false : true;

            if (this.totalPagesExact && this.totalPages) {
                this.confirmedTotalPages = this.totalPages;
            }
            if (!this.hasActiveSearch() && this.confirmedTotalPages) {
                this.totalPages = this.confirmedTotalPages;
                this.totalPagesExact = true;
                this.minimumTotalPages = this.confirmedTotalPages;
                if (this.currentPage + 1 >= this.confirmedTotalPages) {
                    this.canMsgContinue = 0;
                }
            }

            // 写入页码缓存
            this.pageCache[this.currentPage] = {
                articles: this.articles,
                total: this.total,
                totalExact: this.totalExact,
                totalPages: this.totalPages,
                totalPagesExact: this.totalPagesExact,
                minimumTotalPages: this.minimumTotalPages,
                canMsgContinue: this.canMsgContinue,
                searchScanned: this.searchScanned,
                searchScanComplete: this.searchScanComplete
            };

            // 索引到已加载列表映射，供跨页多选与全选使用
            this.articles.forEach((article, idx) => {
                const globalIdx = this.currentPage * 1000 + idx;
                this.loadedArticlesMap.set(globalIdx, article);
            });

            this.renderArticles();
            this.updatePagination();
            this.updateSelectedCount();
        } catch (err) {
            const isWaterwall = err.message && (err.message.includes('防水墙') || err.message.includes('安全验证') || err.message.includes('tcaptcha') || err.message.includes('人机验证'));
            const isAuthError = !isWaterwall && err.message && (err.message.includes('失效') || err.message.includes('未找到有效凭证') || err.message.includes('ret=-3') || err.message.includes('401') || err.message.includes('过期') || err.message.includes('会话'));
            const accountName = this.currentAccount ? (this.currentAccount.nickname || '') : '';
            
            if (isWaterwall) {
                container.innerHTML = `
                    <div class="empty-state" style="padding: 40px 20px;">
                        <div style="font-size: 2.8rem; margin-bottom: 12px;">🛡️</div>
                        <h3 class="empty-state-title" style="margin-bottom: 8px; color: #f59e0b;">触发腾讯安全验证（防水墙）</h3>
                        <p class="empty-state-desc" style="max-width: 540px; margin: 0 auto 20px; line-height: 1.6; color: var(--text-secondary, #666);">
                            微信读书上游接口检测到频率较高，触发了人机验证。<br>
                            👉 <strong>方法 1（推荐）</strong>：点击下方按钮直接在网页中滑动完成验证码；<br>
                            👉 <strong>方法 2</strong>：在手机微信读书 App 中打开任意书籍阅读片刻后，点击“已在手机处理”。
                        </p>
                        <div style="display: flex; justify-content: center; gap: 10px; flex-wrap: wrap;">
                            <button class="btn btn-primary" onclick="WaterWall.triggerCaptcha({ onSuccess: () => ArticlesPage.loadArticles() })">🧩 立即网页滑动验证</button>
                            <button class="btn btn-secondary" onclick="fetch('/api/wechat-mp/app/api/waterwall/clear', {method:'POST',headers:{'X-Requested-With':'WechatMP'}}).then(() => ArticlesPage.loadArticles())">✅ 已在App处理并重试</button>
                        </div>
                    </div>
                `;
            } else {
                container.innerHTML = `
                    <div class="empty-state" style="padding: 40px 20px;">
                        <div style="font-size: 2.5rem; margin-bottom: 12px;">${isAuthError ? '🔐' : '⚠️'}</div>
                        <h3 class="empty-state-title" style="margin-bottom: 8px;">${isAuthError ? (accountName ? `【${accountName}】尚未建立阅读会话` : '微信采集凭证已过期') : '加载文章列表失败'}</h3>
                        <p class="empty-state-desc" style="max-width: 540px; margin: 0 auto 20px; line-height: 1.6; color: var(--text-secondary, #666);">
                            ${isAuthError ? `微信 PC 客户端要求每个公众号首次抓取前建立独立阅读 Session（需打开公众号『主页』，仅点开文章不够）。<br>👉 <strong>方法 1</strong>：点击下方按钮，由系统自动在电脑微信中打开该号主页；<br>👉 <strong>方法 2</strong>：在电脑微信中进入该公众号任一文章 → 点击文章顶部的<strong>公众号名称/头像</strong>进入主页（出现历史文章列表即成功）。` : (err.message || '网络连接超时')}
                        </p>
                        <div style="display: flex; justify-content: center; gap: 10px; flex-wrap: wrap;">
                            ${accountName ? `<button class="btn btn-primary" onclick="ArticlesPage.syncTargetAccount('${accountName}')">🤖 自动为【${accountName}】同步凭证</button>` : ''}
                            <button class="btn btn-secondary" onclick="ArticlesPage.loadArticles()">🔄 重新检测并加载</button>
                        </div>
                    </div>
                `;
            }
        }
    },

    async syncTargetAccount(accountName) {
        if (!accountName) return;
        Toast.info(`正在尝试为【${accountName}】自动在微信中打开文章，请稍候...`);
        try {
            const resp = await fetch('/api/wechat-mp/app/api/accounts/sync-pc-wechat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'WechatMP' },
                body: JSON.stringify({ keyword: accountName })
            });
            const data = await resp.json();
            if (data.success) {
                Toast.success(`【${accountName}】文章已定位，正在重新拉取列表...`);
                setTimeout(() => this.loadArticles(), 2500);
            } else {
                Toast.warning(`自动化指令已发送，若未成功请手动在微信点开一篇文章后点击重试。`);
            }
        } catch (e) {
            Toast.error(`触发自动同步失败: ${e.message}`);
        }
    },

    setSelectionMode(mode) {
        this.selectionMode = mode;
        if (mode === 'single') {
            this.selectedArticles.clear();
        }
        this.renderArticles();
        this.updateModeUI();
        this.updateSelectedCount();
    },

    updateModeUI() {
        const singleBtn = document.getElementById('btn-mode-single');
        const multiBtn = document.getElementById('btn-mode-multi');
        const multiActions = document.getElementById('multi-select-actions');
        if (singleBtn) {
            singleBtn.classList.toggle('btn-primary', this.selectionMode === 'single');
            singleBtn.classList.toggle('btn-secondary', this.selectionMode !== 'single');
        }
        if (multiBtn) {
            multiBtn.classList.toggle('btn-primary', this.selectionMode === 'multi');
            multiBtn.classList.toggle('btn-secondary', this.selectionMode !== 'multi');
        }
        if (multiActions) {
            multiActions.style.display = this.selectionMode === 'multi' ? 'flex' : 'none';
        }
    },

    renderArticles() {
        const container = document.getElementById('articles-list');

        const hasSearch = this.hasActiveSearch();
        const searchKind = this.keyword && this.dateSearchStart
            ? '标题与时间范围'
            : (this.dateSearchStart ? '时间范围' : '标题');

        if (this.articles.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <h3 class="empty-state-title">没有找到文章</h3>
                    <p class="empty-state-desc">${hasSearch
                        ? (this.searchScanComplete ? `已按${searchKind}搜索该公众号全部历史文章，请调整筛选条件` : '上游分页提前中断，未能完成全部历史文章搜索，请稍后重试')
                        : '该公众号暂无文章'}</p>
                </div>
            `;
            return;
        }

        const searchStatus = hasSearch ? `
            <div class="article-search-status" style="margin-bottom: 12px; color: var(--text-muted); font-size: 0.88rem;">
                ${this.searchScanComplete
                    ? `已按${searchKind}全局扫描 ${this.searchScanned} 篇历史文章`
                    : `已扫描 ${this.searchScanned} 篇，但上游分页提前中断；结果可能不完整`}
            </div>
        ` : '';
        container.innerHTML = searchStatus + this.articles.map((article, idx) => {
            if (this.stateFilter !== 'all' && article.download_state !== this.stateFilter) return '';
            const globalIdx = this.currentPage * 1000 + idx;
            const isSelected = this.selectedArticles.has(globalIdx);
            const time = article.update_time
                ? new Date(article.update_time * 1000).toLocaleDateString('zh-CN')
                : '';
            const state = article.download_state || 'not_downloaded';
            const stateLabels = {
                not_downloaded: '未下载',
                downloaded: '已下载未入库',
                importing: '入库中',
                imported: '已入库',
                failed: article.failure_stage === 'ingest' ? '入库失败' : '下载失败',
            };
            const stateLabel = `${article.download_scope === 'global' ? '全局' : ''}${stateLabels[state] || state}`;
            const stateClass = state === 'failed' ? 'badge-error' : state === 'imported' ? 'badge-success' : 'badge-info';

            return `
                <div class="article-item ${isSelected ? 'selected' : ''}" data-idx="${globalIdx}" onclick="ArticlesPage.handleArticleClick(${globalIdx}, ${idx}, event)">
                    ${this.selectionMode === 'multi' ? `
                        <div class="article-checkbox">
                            <input type="checkbox" ${isSelected ? 'checked' : ''}
                                   onchange="event.stopPropagation(); ArticlesPage.toggleArticle(${globalIdx}, ${idx}, this.checked)">
                        </div>
                    ` : ''}
                    ${article.cover
                        ? `<img class="article-cover" src="${article.cover}" alt="" loading="lazy" onerror="this.style.display='none'">`
                        : ''
                    }
                    <div class="article-info">
                        <div class="article-title">
                            <a href="${article.link || '#'}" target="_blank" rel="noopener noreferrer"
                               style="color: var(--text-primary); text-decoration: none; font-weight: 600; transition: color 0.2s;"
                               onmouseenter="this.style.color='var(--primary)';this.style.textDecoration='underline'"
                               onmouseleave="this.style.color='var(--text-primary)';this.style.textDecoration='none'"
                               onclick="event.stopPropagation()">
                                ${article.title || '无标题'} ↗
                            </a>
                        </div>
                        ${article.digest ? `<div class="article-digest">${article.digest}</div>` : ''}
                        <div class="article-meta">
                            ${time ? `<span>📅 ${time}</span>` : ''}
                            ${article.author ? `<span>✍️ ${article.author}</span>` : ''}
                            ${article.is_original ? '<span class="badge badge-info" style="font-size: 0.7rem;">原创</span>' : ''}
                            <span class="badge ${stateClass}" style="font-size:0.7rem;">${stateLabel}</span>
                        </div>
                        ${article.ingest_task_id ? `<div class="article-meta" style="margin-top:4px;font-size:0.72rem;color:var(--text-muted);">
                            <span>知识库 ${article.target_kb_id || '-'}</span>
                            <span>任务 ${article.ingest_task_id}</span>
                            ${article.knowledge_file_id ? `<span>文件 ${article.knowledge_file_id}</span>` : ''}
                        </div>` : ''}
                    </div>
                    <div class="article-actions" style="display: flex; gap: 8px; align-items: center;">
                        ${article.link ? `
                            <a class="btn btn-secondary btn-sm" href="${article.link}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()" style="font-size: 0.8rem; padding: 4px 10px; display: inline-flex; align-items: center; gap: 4px;">
                                🌐 打开原文
                            </a>
                        ` : ''}
                        <button class="btn btn-primary btn-sm" onclick="event.stopPropagation(); ArticlesPage.downloadSingle(${idx})">${state === 'downloaded' || state === 'imported' ? '重新下载' : '下载'}</button>
                    </div>
                </div>
            `;
        }).join('');
    },

    handleArticleClick(globalIdx, localIdx, event) {
        // 如果点击的是操作按钮或复选框等，不处理跳转/选中
        if (event.target.closest('.article-actions') || event.target.closest('.article-checkbox')) {
            return;
        }

        if (this.selectionMode === 'multi') {
            const isSelected = this.selectedArticles.has(globalIdx);
            const nextChecked = !isSelected;
            
            // 同步更新复选框 DOM 状态
            const item = document.querySelector(`.article-item[data-idx="${globalIdx}"]`);
            if (item) {
                const checkbox = item.querySelector('.article-checkbox input[type="checkbox"]');
                if (checkbox) checkbox.checked = nextChecked;
            }
            this.toggleArticle(globalIdx, localIdx, nextChecked);
        } else {
            const article = this.articles[localIdx];
            if (article && article.link) {
                window.open(article.link, '_blank');
            }
        }
    },

    toggleArticle(globalIdx, localIdx, checked) {
        if (checked) {
            this.selectedArticles.add(globalIdx);
            this.articles[localIdx]._selected = true;
        } else {
            this.selectedArticles.delete(globalIdx);
            this.articles[localIdx]._selected = false;
        }

        // 更新视觉状态
        const item = document.querySelector(`.article-item[data-idx="${globalIdx}"]`);
        if (item) item.classList.toggle('selected', checked);

        this.updateSelectedCount();
    },

    updateSelectedCount() {
        const countEl = document.getElementById('selected-count');
        const selectableTotalEl = document.getElementById('selectable-total-count');
        const selectAllBtn = document.getElementById('btn-select-all-loaded');
        const btn = document.getElementById('btn-download-selected');
        const selectableCount = Array.from(this.loadedArticlesMap.values())
            .filter(article => this.isBatchSelectable(article)).length;
        if (countEl) countEl.textContent = this.selectedArticles.size;
        if (selectableTotalEl) selectableTotalEl.textContent = selectableCount;
        if (selectAllBtn) selectAllBtn.disabled = selectableCount === 0;
        if (btn) btn.disabled = this.selectedArticles.size === 0;
    },

    isBatchSelectable(article) {
        const state = article?.download_state || 'not_downloaded';
        return !['downloaded', 'importing', 'imported'].includes(state);
    },

    selectAllLoaded() {
        if (this.loadedArticlesMap.size === 0) {
            Toast.warning('当前暂无已加载的文章');
            return;
        }
        let selectableCount = 0;
        let skippedCount = 0;
        this.loadedArticlesMap.forEach((article, globalIdx) => {
            if (this.isBatchSelectable(article)) {
                this.selectedArticles.add(globalIdx);
                selectableCount++;
            } else {
                this.selectedArticles.delete(globalIdx);
                skippedCount++;
            }
        });
        this.renderArticles();
        this.updateSelectedCount();
        if (selectableCount === 0) {
            Toast.info('已加载文章均已下载或正在入库，无需重复选择');
            return;
        }
        const skipped = skippedCount ? `，已跳过 ${skippedCount} 篇已处理文章` : '';
        Toast.success(`已选中 ${selectableCount} 篇未下载文章${skipped}`);
    },

    clearSelection() {
        this.selectedArticles.clear();
        this.renderArticles();
        this.updateSelectedCount();
        Toast.info('已取消选择');
    },

    hasActiveSearch() {
        return Boolean(this.keyword || (this.dateSearchStart && this.dateSearchEnd));
    },

    resetSearchPagination() {
        this.currentPage = 0;
        this.selectedArticles.clear();
        this.pageCache = {};
        this.loadedArticlesMap.clear();
        this.confirmedTotalPages = null;
        this.pageCountLoading = false;
        this._pageCountToken++;
    },

    async searchArticles() {
        const input = document.getElementById('search-article-input');
        const startValue = document.getElementById('article-start-date')?.value || '';
        const endValue = document.getElementById('article-end-date')?.value || '';
        if (Boolean(startValue) !== Boolean(endValue)) {
            Toast.warning('请选择完整的开始和结束日期');
            return;
        }

        const range = startValue && endValue ? this.getDateRange() : null;
        if (range?.error) {
            Toast.warning(range.error);
            return;
        }
        this.keyword = input?.value.trim() || '';
        this.dateSearchStart = range?.startTimestamp || 0;
        this.dateSearchEnd = range?.endTimestamp || 0;
        this.resetSearchPagination();
        if (!this.hasActiveSearch()) this.pageCountLoading = true;
        const pageCountToken = this._pageCountToken;
        await this.loadArticles();
        if (!this.hasActiveSearch()) {
            void this.loadConfirmedPageCount(this.currentFakeid, pageCountToken);
        }
    },

    async clearSearch() {
        document.getElementById('search-article-input').value = '';
        this.keyword = '';
        this.dateSearchStart = 0;
        this.dateSearchEnd = 0;
        const startDateEl = document.getElementById('article-start-date');
        const endDateEl = document.getElementById('article-end-date');
        const quickDateEl = document.getElementById('article-quick-date');
        if (startDateEl) startDateEl.value = '';
        if (endDateEl) endDateEl.value = '';
        if (quickDateEl) quickDateEl.value = '';
        this.resetSearchPagination();
        this.pageCountLoading = true;
        const pageCountToken = this._pageCountToken;
        await this.loadArticles();
        void this.loadConfirmedPageCount(this.currentFakeid, pageCountToken);
    },

    getDateRange() {
        const startVal = document.getElementById('article-start-date')?.value;
        const endVal = document.getElementById('article-end-date')?.value;
        if (!startVal || !endVal) {
            return null;
        }
        const startTimestamp = Math.floor(new Date(startVal + 'T00:00:00').getTime() / 1000);
        const endTimestamp = Math.floor(new Date(endVal + 'T23:59:59').getTime() / 1000);
        if (!Number.isFinite(startTimestamp) || !Number.isFinite(endTimestamp)) {
            return { error: '日期格式无效，请重新选择' };
        }
        if (startTimestamp > endTimestamp) {
            return { error: '开始日期不能晚于结束日期' };
        }
        return { startTimestamp, endTimestamp };
    },

    onQuickDateChange(type) {
        if (!type) return;
        const startInput = document.getElementById('article-start-date');
        const endInput = document.getElementById('article-end-date');
        if (!startInput || !endInput) return;

        const now = new Date();
        const formatDate = date => {
            const year = date.getFullYear();
            const month = String(date.getMonth() + 1).padStart(2, '0');
            const day = String(date.getDate()).padStart(2, '0');
            return `${year}-${month}-${day}`;
        };
        let start = new Date(now);
        if (type === '3days') start.setDate(start.getDate() - 2);
        if (type === '7days') start.setDate(start.getDate() - 6);
        if (type === '30days') start.setDate(start.getDate() - 29);
        if (type === 'this_month') start = new Date(now.getFullYear(), now.getMonth(), 1);

        startInput.value = formatDate(start);
        endInput.value = formatDate(now);
    },

    async searchDateRange() {
        if (!this.currentFakeid) {
            Toast.warning('请先选择公众号');
            return;
        }
        const range = this.getDateRange();
        if (!range) {
            Toast.warning('请选择完整的开始和结束日期');
            return;
        }
        if (range.error) {
            Toast.warning(range.error);
            return;
        }

        const input = document.getElementById('search-article-input');
        this.keyword = input?.value.trim() || '';
        this.dateSearchStart = range.startTimestamp;
        this.dateSearchEnd = range.endTimestamp;
        this.resetSearchPagination();
        await this.loadArticles();
        Toast.success(this.keyword ? '已按标题与时间范围筛选' : '已按时间范围筛选');
    },

    async clearDateFilter() {
        const startInput = document.getElementById('article-start-date');
        const endInput = document.getElementById('article-end-date');
        const quickSelect = document.getElementById('article-quick-date');
        if (startInput) startInput.value = '';
        if (endInput) endInput.value = '';
        if (quickSelect) quickSelect.value = '';

        const hadActiveDateSearch = Boolean(this.dateSearchStart && this.dateSearchEnd);
        this.dateSearchStart = 0;
        this.dateSearchEnd = 0;
        if (!hadActiveDateSearch) return;

        this.resetSearchPagination();
        if (!this.keyword) this.pageCountLoading = true;
        const pageCountToken = this._pageCountToken;
        await this.loadArticles();
        if (!this.keyword) {
            void this.loadConfirmedPageCount(this.currentFakeid, pageCountToken);
        }
    },

    setIncludePdf(value) {
        this.includePdf = Boolean(value);
        localStorage.setItem('wechat-article-include-pdf', String(this.includePdf));
    },

    setStateFilter(value) {
        this.stateFilter = value || 'all';
        this.renderArticles();
    },

    updatePagination() {
        const paginationEl = document.getElementById('articles-pagination');
        const infoEl = document.getElementById('pagination-info');
        const prevBtn = document.getElementById('btn-prev-page');
        const nextBtn = document.getElementById('btn-next-page');

        const currentPageNum = this.currentPage + 1;
        const hasNext = (this.canMsgContinue === 1 || this.canMsgContinue === undefined) && this.articles.length > 0;

        paginationEl.style.display = (this.articles.length > 0 || this.currentPage > 0) ? 'flex' : 'none';
        if (this.totalPagesExact && this.totalPages) {
            infoEl.textContent = this.totalExact
                ? `第 ${currentPageNum} / ${this.totalPages} 页 · 共 ${this.total} 篇`
                : `第 ${currentPageNum} / ${this.totalPages} 页`;
        } else if (this.pageCountLoading) {
            infoEl.textContent = `第 ${currentPageNum} 页 / 正在统计总页数…（至少 ${Math.max(currentPageNum, this.minimumTotalPages)} 页）`;
        } else {
            infoEl.textContent = `第 ${currentPageNum} 页 / 至少 ${Math.max(currentPageNum, this.minimumTotalPages)} 页`;
        }
        prevBtn.disabled = this.currentPage <= 0;
        nextBtn.disabled = !hasNext;
    },

    prevPage() {
        if (this.currentPage > 0) {
            this.currentPage--;
            this.loadArticles();
        }
    },

    nextPage() {
        if (this.articles.length > 0 && this.canMsgContinue !== 0) {
            this.currentPage++;
            this.loadArticles();
        }
    },

    startTask(data) {
        this.downloadTaskId = data.task_id;
        Toast.success(data.message);
        this.showDownloadProgress();
        this.startProgressPolling();
    },

    async downloadArticles(articles) {
        try {
            const data = await API.articles.download(articles, this.currentName, this.includePdf);
            this.startTask(data);
        } catch (err) {
            // error shown by API
        }
    },

    async downloadSingle(localIdx) {
        const article = this.articles[localIdx];
        if (!article) return;
        await this.downloadArticles([{ title: article.title, link: article.link, id: article.id, aid: article.id }]);
    },

    async downloadSelected() {
        const selectedList = [];
        this.selectedArticles.forEach(globalIdx => {
            const article = this.loadedArticlesMap.get(globalIdx);
            if (article && article.link) {
                selectedList.push({ title: article.title, link: article.link, id: article.id, aid: article.id });
            }
        });

        if (selectedList.length === 0) {
            Toast.warning('请先选择要下载的文章');
            return;
        }
        await this.downloadArticles(selectedList);
    },

    async downloadDateRange() {
        if (!this.currentFakeid) {
            Toast.warning('请先选择公众号');
            return;
        }
        const range = this.getDateRange();
        if (!range) {
            Toast.warning('请选择完整的开始和结束日期');
            return;
        }
        if (range.error) {
            Toast.warning(range.error);
            return;
        }

        try {
            const data = await API.articles.downloadRange({
                fakeid: this.currentFakeid,
                account_name: this.currentName,
                start_time: range.startTimestamp,
                end_time: range.endTimestamp,
                keyword: this.keyword,
                page_size: this.pageSize,
                include_pdf: this.includePdf,
            });
            this.startTask(data);
        } catch (err) {
            // error shown by API
        }
    },

    showDownloadProgress() {
        document.getElementById('download-progress-section').style.display = 'block';
        document.getElementById('download-progress-section').scrollIntoView({ behavior: 'smooth' });
        const cancelBtn = document.getElementById('btn-cancel-download');
        if (cancelBtn) cancelBtn.style.display = 'inline-flex';
    },

    startProgressPolling() {
        if (this._pollTimer) clearInterval(this._pollTimer);

        this._pollTimer = setInterval(async () => {
            try {
                const task = await API.articles.downloadStatus(this.downloadTaskId);
                this.updateDownloadProgress(task);

                if (task.status === 'completed' || task.status === 'failed' || task.status === 'cancelled') {
                    clearInterval(this._pollTimer);
                    this._pollTimer = null;
                }
            } catch (err) {
                clearInterval(this._pollTimer);
                this._pollTimer = null;
            }
        }, 1000);
    },

    updateDownloadProgress(task) {
        const total = task.total || 0;
        const completed = task.completed || 0;
        const failed = task.failed || 0;
        const progress = total > 0 ? Math.round(((completed + failed) / total) * 100) : 0;

        document.getElementById('download-progress-bar').style.width = `${progress}%`;
        document.getElementById('download-current').textContent = task.current || '-';
        document.getElementById('download-completed').textContent = completed;
        document.getElementById('download-failed').textContent = failed;
        document.getElementById('download-total').textContent = total;

        const scannedWrap = document.getElementById('download-scanned-wrap');
        const scannedEl = document.getElementById('download-scanned');
        if (scannedWrap && scannedEl) {
            scannedWrap.style.display = task.scanned ? 'inline' : 'none';
            scannedEl.textContent = task.scanned || 0;
        }

        const reasonEl = document.getElementById('download-stop-reason');
        if (reasonEl) {
            reasonEl.style.display = task.stop_reason ? 'block' : 'none';
            reasonEl.textContent = task.stop_reason ? `停止原因：${task.stop_reason}` : '';
        }

        const badge = document.getElementById('download-status-badge');
        if (task.status === 'completed') {
            badge.className = 'badge badge-success';
            badge.textContent = '已完成';
            Toast.success(`下载完成！成功 ${completed} 篇，失败 ${failed} 篇`);
            this.pageCache = {};
            setTimeout(() => this.loadArticles(), 0);
        } else if (task.status === 'failed') {
            badge.className = 'badge badge-error';
            badge.textContent = '失败';
        } else if (task.status === 'cancelled') {
            badge.className = 'badge badge-warning';
            badge.textContent = '已停止';
        } else if (task.status === 'cancelling') {
            badge.className = 'badge badge-warning';
            badge.textContent = '停止中';
        } else {
            badge.className = 'badge badge-info';
            badge.textContent = '下载中';
        }

        const cancelBtn = document.getElementById('btn-cancel-download');
        if (cancelBtn) {
            cancelBtn.style.display = (task.status === 'running' || task.status === 'cancelling') ? 'inline-flex' : 'none';
            cancelBtn.disabled = task.status === 'cancelling';
        }

        const note = document.getElementById('download-note');
        if (note && task.status === 'completed') {
            note.innerHTML = '下载完成。请到 <a href="#history" style="color: var(--primary); text-decoration: none;">下载历史</a> 查看文件列表。';
        }
    },

    async cancelDownload() {
        if (!this.downloadTaskId) return;
        try {
            await API.articles.cancelDownload(this.downloadTaskId);
            Toast.info('正在停止下载...');
        } catch (err) {
            // shown by API
        }
    },

    async openFolder() {
        try {
            const result = await API.articles.openFolder(this.currentName); window.open(result.url, '_blank', 'noopener');
            Toast.success('下载目录已打开');
        } catch (err) {
            // shown by API
        }
    },
};
