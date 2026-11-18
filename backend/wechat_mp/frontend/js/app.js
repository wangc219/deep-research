/** 公众号模块启动器；保留原版页面，移除其他平台后台轮询。 */
const App = {
    ffmpegAvailable: false,
    async init() {
        Toast.init(); Modal.init(); Router.init();
        this.checkAuthStatus();
        this.authTimer = setInterval(() => this.checkAuthStatus(), 30000);
        window.addEventListener('pagehide', () => clearInterval(this.authTimer));
        document.querySelectorAll('.nav-group-title').forEach(el => el.addEventListener('click', () => {
            el.nextElementSibling.classList.toggle('collapsed');
        }));
    },
    async checkAuthStatus() {
        try {
            const state = await API.auth.status();
            const expired = state.expired || state.may_expired;
            document.getElementById('status-indicator').className = 'status-dot ' + (state.logged_in ? expired ? 'expired' : 'online' : 'offline');
            document.getElementById('status-text').textContent = state.logged_in ? expired ? '登录过期' : '已登录' : '未登录';
            const data = await API.accountPool.events();
            for (const event of data.events || []) Toast.warning(`账号【${event.nickname || '未知'}】${event.reason}`);
        } catch (error) { console.error('公众号连接失败', error.message); }
    },
};
document.addEventListener('DOMContentLoaded', () => App.init());
