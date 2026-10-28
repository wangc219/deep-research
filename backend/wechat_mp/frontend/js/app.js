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
    showDisclaimer() {
        Modal.open({
            title: '免责声明',
            content: `
                <div style="font-size: 0.9rem; line-height: 1.6; color: var(--text-secondary);">
                    <p style="margin-bottom: 12px; font-weight: 500; color: var(--text-primary);">在使用本工具前，请仔细阅读以下免责声明：</p>
                    <p style="margin-top: 8px; margin-bottom: 8px; text-indent: -1.2em; padding-left: 1.2em;">1. 本项目所有功能仅用于个人学习、研究与本地备份，请勿用于任何商业用途或非法牟利。</p>
                    <p style="margin-top: 8px; margin-bottom: 8px; text-indent: -1.2em; padding-left: 1.2em;">2. 使用本工具下载资源时需遵守平台的用户服务协议及相关法律法规。用户因滥用本工具造成的账号风控、限制或法律纠纷，由用户本人承担，与本项目作者无关。</p>
                    <p style="margin-top: 8px; margin-bottom: 8px; text-indent: -1.2em; padding-left: 1.2em;">3. 本项目为开源软件，不提供任何形式的担保或售后承诺。</p>
                </div>
            `,
            footer: '<button class="btn btn-primary" onclick="Modal.close()" style="width: 100%;">我已阅知</button>'
        });
    },

};
document.addEventListener('DOMContentLoaded', () => App.init());
