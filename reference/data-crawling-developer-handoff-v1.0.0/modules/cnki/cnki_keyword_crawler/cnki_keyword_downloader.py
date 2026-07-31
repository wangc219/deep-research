# -*- coding: utf-8 -*-
"""
CNKI 疾病诊疗指南 PDF 全自动一键下载爬虫 (基于 DrissionPage 4.x)
=================================================================

功能说明：
    接管 Chromium 浏览器，模拟真实用户操作来搜索和下载 PDF。
    解决了传统 requests 爬虫无法绕过 CNKI 动态加密链接的问题。

核心流程：
    1. 启动浏览器 → 注入 Cookie → 进入 cnki.net 首页
    2. 输入关键词搜索 → 自动处理新标签页跳转
    3. 遍历搜索结果 → 按下载量过滤
    4. 对满足条件的文章：打开详情页 → 优先点击 PDF 按钮 → 失败后尝试直连下载链接兜底
    5. 生成下载报告

依赖库：
    pip install DrissionPage

使用方式：
    python cnki_keyword_downloader.py                              # 默认搜索"诊疗指南"
    python cnki_keyword_downloader.py --keyword "乳腺癌诊疗指南"   # 自定义关键词
    python cnki_keyword_downloader.py --min-downloads 1000          # 设定最低下载量阈值
    python cnki_keyword_downloader.py --max-pages 3                 # 抓取前 3 页

作者：邓宇恒
更新日期：2026-03-28
"""

import os
import json
import time
import random
import logging
import argparse
import glob
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

try:
    from DrissionPage import ChromiumPage, ChromiumOptions
except ImportError as exc:
    ChromiumPage = None
    ChromiumOptions = None
    DRISSIONPAGE_IMPORT_ERROR = exc
else:
    DRISSIONPAGE_IMPORT_ERROR = None

try:
    from verify_popup_notifier import show_verify_popup
except ImportError:  # 允许作为包导入：from cnki_keyword_crawler import CnkiDownloader
    from .verify_popup_notifier import show_verify_popup

# ============================================================
# 日志配置（UTF-8 输出，避免 Windows GBK 编码问题）
# ============================================================
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CNKI_RAW_DIR = PROJECT_ROOT / "data" / "raw" / "cnki"


@dataclass(frozen=True)
class StoragePaths:
    """CNKI 采集产物在当前项目中的默认落盘位置。"""

    raw_dir: Path
    output_dir: Path
    log_dir: Path
    log_path: Path
    report_path: Path
    fail_path: Path
    cookie_path: Path


def resolve_project_path(path_value, default_path):
    """将相对路径按项目根目录解析，绝对路径保持不变。"""
    raw_path = Path(path_value) if path_value else Path(default_path)
    raw_path = raw_path.expanduser()
    if raw_path.is_absolute():
        return raw_path.resolve()
    return (PROJECT_ROOT / raw_path).resolve()


def build_storage_paths(raw_dir=None, cookie_file=None):
    """生成默认存储路径，不创建目录，便于离线测试和 CLI 预览。"""
    raw_root = resolve_project_path(raw_dir, DEFAULT_CNKI_RAW_DIR)
    log_dir = raw_root / "logs"
    return StoragePaths(
        raw_dir=raw_root,
        output_dir=raw_root / "papers",
        log_dir=log_dir,
        log_path=log_dir / "spider_dp.log",
        report_path=raw_root / "download_report.json",
        fail_path=raw_root / "fail.txt",
        cookie_path=resolve_project_path(cookie_file, PROJECT_ROOT / "cookie.txt"),
    )


def configure_chromium_options(
    options,
    *,
    environment=None,
    os_name=None,
):
    """Apply cross-platform browser settings without changing desktop defaults."""
    resolved_env = os.environ if environment is None else environment
    resolved_os_name = os.name if os_name is None else os_name
    browser_path = str(resolved_env.get("CHROME_BIN", "")).strip()
    if browser_path:
        options.set_browser_path(browser_path)
    if resolved_os_name != "nt":
        options.set_argument("--no-sandbox")
        options.set_argument("--disable-dev-shm-usage")
        runtime_root = str(resolved_env.get("CRAWLER_RUNTIME_ROOT", "")).strip()
        if runtime_root:
            options.set_user_data_path(str(Path(runtime_root) / "cnki-chromium"))
    return options


def setup_logger(log_path):
    """配置日志：控制台 + 文件双输出"""
    logger = logging.getLogger("CnkiDP")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    import io, sys
    # 使用 UTF-8 编码包装 stdout
    utf8_stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    ch = logging.StreamHandler(utf8_stdout)
    ch.setLevel(logging.INFO)
    fmt = logging.Formatter("[%(asctime)s] %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    return logger


logger = logging.getLogger("CnkiDP")
logger.addHandler(logging.NullHandler())


# ============================================================
# 工具函数
# ============================================================
def clean_filename(name):
    """清理文件名中的非法字符"""
    for ch in '<>:"/\\|?*\n\r\t':
        name = name.replace(ch, '_')
    return name.strip()[:120]  # 限制文件名长度


def is_valid_pdf(filepath):
    """检查文件头是否为 %PDF"""
    if not os.path.exists(filepath) or os.path.getsize(filepath) < 10240:
        return False
    try:
        with open(filepath, "rb") as f:
            return f.read(4) == b"%PDF"
    except Exception:
        return False


def load_cookies(filepath="cookie.txt"):
    """从 cookie.txt 解析为 DrissionPage 可接受的 cookie 列表"""
    if not os.path.exists(filepath):
        logger.warning(f"未找到 {filepath}，将依赖浏览器已有登录状态。")
        return []

    with open(filepath, "r", encoding="utf-8") as f:
        raw = f.read().strip()

    cookies = []
    for pair in raw.split(";"):
        pair = pair.strip()
        if "=" in pair:
            k, v = pair.split("=", 1)
            cookies.append({"name": k.strip(), "value": v.strip(), "domain": ".cnki.net"})
    logger.info(f"从 cookie.txt 加载了 {len(cookies)} 条 Cookie。")
    return cookies


# ============================================================
# 核心爬虫类
# ============================================================
class CnkiDownloader:
    """
    基于 DrissionPage 的 CNKI PDF 全自动下载器。

    通过控制真实 Chromium 浏览器完成搜索、过滤、点击下载全流程，
    绕过 CNKI 的动态链接加密和防盗链机制。
    """

    def __init__(
        self,
        keyword="诊疗指南",
        min_downloads=1000,
        max_pages=1,
        start_page=1,
        start_url=None,
        raw_dir=None,
        cookie_file=None,
    ):
        # 搜索参数
        self.keyword = keyword
        self.min_downloads = min_downloads
        self.max_pages = max_pages
        self.start_page = start_page
        self.start_url = start_url

        # 输出路径
        self.paths = build_storage_paths(raw_dir=raw_dir, cookie_file=cookie_file)
        self.paths.raw_dir.mkdir(parents=True, exist_ok=True)
        self.paths.output_dir.mkdir(parents=True, exist_ok=True)
        self.paths.log_dir.mkdir(parents=True, exist_ok=True)

        global logger
        logger = setup_logger(self.paths.log_path)

        self.raw_dir = str(self.paths.raw_dir)
        self.output_dir = str(self.paths.output_dir)
        os.makedirs(self.output_dir, exist_ok=True)
        self.fail_path = str(self.paths.fail_path)
        self.cookie_path = str(self.paths.cookie_path)

        # 验证码页面前缀
        self.verify_url_prefix = "https://bar.cnki.net/bar/verify/"

        # 下载历史（断点续传）
        self.log_path = str(self.paths.log_path)
        self.report_path = str(self.paths.report_path)
        self.history = self._load_history()
        self.log_pdf_stems = self._load_log_pdf_stems()

        # 统计计数器
        self.stats = {"success": 0, "fail": 0, "skip": 0, "total": 0}

        # 搜索结果页的 tab 引用
        self.search_tab = None

        # 初始化浏览器
        self._init_browser()

    # ----------------------------------------------------------
    # 浏览器初始化
    # ----------------------------------------------------------
    def _init_browser(self):
        """配置并启动 Chromium 浏览器"""
        if DRISSIONPAGE_IMPORT_ERROR is not None:
            raise RuntimeError(
                "缺少依赖 DrissionPage，请先在当前目录运行: pip install -r requirements.txt"
            ) from DRISSIONPAGE_IMPORT_ERROR

        logger.info("正在启动浏览器...")
        co = configure_chromium_options(ChromiumOptions())
        # 不使用 headless，方便用户观察进度和手动扫码登录
        # co.headless()

        self.page = ChromiumPage(co)

        # 设置默认下载路径
        self.page.set.download_path(self.output_dir)
        # 同名文件自动重命名，避免覆盖
        self.page.set.when_download_file_exists('rename')

        logger.info("浏览器就绪！")

        # 先导航到知网首页，然后注入 Cookie
        self.page.get("https://www.cnki.net")
        cookies = load_cookies(self.cookie_path)
        if cookies:
            self.page.set.cookies(cookies)
            logger.info("Cookie 注入完成。")
            # 注入后刷新页面使 Cookie 生效
            self.page.refresh()

    # ----------------------------------------------------------
    # 历史记录管理（断点续传）
    # ----------------------------------------------------------
    def _load_history(self):
        """从下载报告加载已下载文件标题列表。"""
        if os.path.exists(self.report_path):
            try:
                with open(self.report_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return set(
                    item.get("title", "")
                    for item in data.get("downloaded", [])
                    if item.get("status") == "success"
                )
            except Exception:
                pass
        return set()

    def _load_log_pdf_stems(self):
        """从 spider_dp.log 中提取成功下载的 PDF 文件名 stem。"""
        if not os.path.exists(self.log_path):
            return set()

        saved_re = re.compile(r"\[成功\]\s*已保存\s*[:：]\s*(.+?)\s*$")
        stems = set()
        try:
            with open(self.log_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    m = saved_re.search(line)
                    if not m:
                        continue
                    file_name = os.path.basename(m.group(1).strip())
                    stem, ext = os.path.splitext(file_name)
                    if ext.lower() == ".pdf" and stem:
                        stems.add(stem.lower())
        except Exception as e:
            logger.warning(f"读取下载日志失败，将仅使用报告历史: {e}")
            return set()

        if stems:
            logger.info(f"从日志历史中加载到 {len(stems)} 个已下载文件记录。")
        return stems

    def _is_in_log_history(self, title):
        """根据日志中的成功文件名判断标题是否已下载（兼容“标题_作者”）。"""
        if not self.log_pdf_stems:
            return False

        expected = clean_filename(title).lower()
        if expected in self.log_pdf_stems:
            return True
        return any(stem.startswith(expected + "_") for stem in self.log_pdf_stems)

    def _save_report(self, downloaded, skipped):
        """保存下载报告"""
        report = {
            "date": time.strftime("%Y-%m-%d %H:%M:%S"),
            "keyword": self.keyword,
            "stats": self.stats,
            "downloaded": downloaded,
            "skipped": skipped,
        }
        with open(self.report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        logger.info(f"报告已保存至 {self.report_path}")

    def _save_fail_list(self, failed):
        """将下载失败的文献写入 fail.txt"""
        with open(self.fail_path, "w", encoding="utf-8") as f:
            for item in failed:
                title = item.get("title", "")
                reason = item.get("reason", "下载失败")
                detail_url = item.get("detail_url", "")
                f.write(f"{title}\t{reason}\t{detail_url}\n")
        logger.info(f"失败列表已保存至 {self.fail_path}（共 {len(failed)} 条）")

    # ----------------------------------------------------------
    # 工具方法
    # ----------------------------------------------------------
    def _delay(self, lo=2, hi=5):
        """随机延迟，模拟人工操作节奏"""
        time.sleep(random.uniform(lo, hi))

    def _is_verify_page(self, tab):
        """判断当前 tab 是否为知网拼图验证页面"""
        if not tab:
            return False
        try:
            url = tab.url or ""
        except Exception:
            return False
        return url.startswith(self.verify_url_prefix)

    def _wait_verify_passed(self, tab, scene="当前页面"):
        """遇到拼图验证页时暂停，等待用户手动通过后继续"""
        if not self._is_verify_page(tab):
            return

        verify_url = ""
        try:
            verify_url = tab.url or ""
        except Exception:
            pass

        logger.warning("=" * 60)
        logger.warning(f"检测到知网拼图验证（{scene}）")
        logger.warning("请在浏览器中完成拼图验证，完成后回到终端按回车继续。")
        logger.warning("=" * 60)

        try:
            show_verify_popup(scene=scene, verify_url=verify_url)
        except Exception as e:
            logger.warning(f"弹窗提醒失败，将仅使用终端提醒: {e}")

        while self._is_verify_page(tab):
            try:
                input(">>> 完成拼图验证后按回车继续...")
            except EOFError:
                # 非交互环境下退化为等待轮询
                self._delay(2, 3)

            if self._is_verify_page(tab):
                logger.warning("仍处于验证页面，请先完成拼图验证。")
                try:
                    show_verify_popup(scene=scene, verify_url=verify_url)
                except Exception:
                    pass

        logger.info("✓ 验证通过，继续执行。")

    def _close_error_pages(self):
        """关闭 CNKI 错误页面提示（ErrorMsg.html）。"""
        if self.page.tabs_count < 2:
            return

        tabs_to_close = []
        for i in range(self.page.tabs_count):
            try:
                tab = self.page.get_tab(i)
                if tab and tab.url and tab.url.startswith("https://bar.cnki.net/bar/ErrorMsg.html"):
                    tabs_to_close.append(tab)
            except Exception:
                continue

        for tab in tabs_to_close:
            try:
                tab.close()
                logger.debug("已关闭 CNKI 错误提示页面")
            except Exception:
                pass

    def _title_matches_pdf_name(self, title, file_path):
        """判断 PDF 文件名是否匹配标题（允许末尾 _作者 后缀）"""
        expected = clean_filename(title).lower()
        stem = os.path.splitext(os.path.basename(file_path))[0].lower()
        return stem == expected or stem.startswith(expected + "_")

    def _get_new_download_file(self, existing_files, title=None):
        """从下载目录中找出新增的最终 PDF 文件"""
        all_files = set(glob.glob(os.path.join(self.output_dir, "*")))
        new_files = all_files - existing_files
        candidates = []
        for p in new_files:
            if not os.path.isfile(p):
                continue
            lower = p.lower()
            if lower.endswith(".crdownload") or lower.endswith(".tmp") or lower.endswith(".part"):
                continue
            if not lower.endswith(".pdf"):
                continue
            candidates.append(p)

        if not candidates:
            return None

        # 优先选择与标题匹配的文件名（兼容“标题_作者.pdf”）
        if title:
            matched = [p for p in candidates if self._title_matches_pdf_name(title, p)]
            if matched:
                return max(matched, key=os.path.getmtime)

        return max(candidates, key=os.path.getmtime)

    def _find_pdf_button(self, tab, timeout=18):
        """在详情页中尽可能稳健地定位下载按钮。"""
        selector_list = [
            '#pdfDown',
            'css:a#pdfDown',
            'css:.btn-dlpdf a',
            'css:.btn-dlpdf',
            'css:a[href*="pdfDown"]',
            'css:a[href*="download"]',
            'css:a[href*="kns/download"]',
            'css:.download a',
            'css:a[download]',
            'xpath://a[contains(normalize-space(.), "PDF下载")]',
            'xpath://a[contains(normalize-space(.), "PDF") and contains(normalize-space(.), "下载")]',
            'xpath://a[contains(normalize-space(.), "整本下载")]',
            'xpath://a[contains(normalize-space(.), "下载") and not(contains(@class, "disabled"))]',
        ]

        end_at = time.time() + timeout
        while time.time() < end_at:
            for sel in selector_list:
                try:
                    btn = tab.ele(sel, timeout=1)
                    if btn:
                        return btn, sel
                except Exception:
                    continue
            time.sleep(0.6)
        return None, None

    def _goto_start_page(self):
        """从第 1 页翻到指定起始页"""
        if self.start_page <= 1:
            return True

        logger.info(f"准备跳转到起始页：第 {self.start_page} 页")
        page_no = 1

        while page_no < self.start_page:
            self._wait_verify_passed(self.search_tab, scene=f"翻页到第 {page_no + 1} 页")

            next_btn = self.search_tab.ele('#PageNext', timeout=5)
            if not next_btn:
                logger.error("找不到下一页按钮，无法跳转到指定起始页。")
                return False

            cls = next_btn.attr('class') or ""
            if "disabled" in cls:
                logger.error(f"当前总页数不足，无法跳转到第 {self.start_page} 页。")
                return False

            next_btn.click()
            page_no += 1
            logger.info(f"已跳转到第 {page_no} 页")
            self._delay(2, 4)
            self.search_tab.ele('css:.result-table-list tbody tr', timeout=12)

        return True

    # ----------------------------------------------------------
    # 登录检测
    # ----------------------------------------------------------
    def _check_login(self):
        """
        检测当前页面是否处于未登录状态。
        如果未登录，等待用户在弹出的浏览器中手动扫码/输密码。
        """
        # 知网首页的登录状态通常由右上角的"登录"按钮判断
        # 我们检查页面上是否存在明确的"登录"链接（注意排除其他含"登录"的文本）
        login_btn = self.page.ele('css:.login > a', timeout=3)
        if login_btn:
            logger.warning("=" * 50)
            logger.warning("检测到当前未登录知网！")
            logger.warning("请在弹出的浏览器窗口中手动登录。")
            logger.warning("登录成功后程序将自动继续（最长等待 120 秒）。")
            logger.warning("=" * 50)

            # 等待"登录"按钮消失（用户登录成功后首页会自动更新）
            try:
                self.page.wait.ele_hidden('css:.login > a', timeout=120)
                logger.info("✓ 登录成功！继续任务...")
            except Exception:
                logger.error("等待登录超时（120秒），请检查登录状态后重新运行。")
                raise SystemExit(1)

            self._delay(2, 3)

    # ----------------------------------------------------------
    # 搜索
    # ----------------------------------------------------------
    def _search(self):
        """在知网首页执行关键词搜索"""
        logger.info(f"搜索关键词: {self.keyword}")
        self.page.get("https://www.cnki.net")
        self._delay(1, 2)

        self._check_login()

        # 定位搜索框并输入关键词
        search_box = self.page.ele('#txt_SearchText', timeout=5)
        if not search_box:
            logger.error("无法在首页找到搜索框！")
            return False

        search_box.clear()
        search_box.input(self.keyword)
        self._delay(0.5, 1)

        # 点击搜索按钮
        search_btn = self.page.ele('.search-btn', timeout=3)
        if search_btn:
            search_btn.click()
        else:
            logger.error("找不到搜索按钮！")
            return False

        # 知网搜索后会打开新标签页，等待并切换
        self._delay(2, 4)

        # 切到最新的标签页
        if self.page.tabs_count > 1:
            latest = self.page.latest_tab
            self.search_tab = latest
            logger.info(f"已切换到搜索结果标签页 (共 {self.page.tabs_count} 个标签)")
        else:
            self.search_tab = self.page
            logger.info("搜索结果在当前标签页加载")

        self._wait_verify_passed(self.search_tab, scene="搜索结果页")

        # 点击下载量排序 (按下载量从高到低)
        sort_btn = self.search_tab.ele('#DFR', timeout=10)
        if sort_btn:
            logger.info("点击按下载量从高到低排序...")
            sort_btn.click()
            self._delay(3, 5) # 排序后需等待列表重新渲染
        else:
            logger.warning("未找到下载量排序按钮 (#DFR)")

        # 等待结果表格出现
        result_table = self.search_tab.ele('.result-table-list', timeout=15)
        if result_table:
            logger.info("搜索结果列表加载成功！")
            return True
        else:
            logger.error("等待搜索结果列表超时（15秒）。")
            return False

    # ----------------------------------------------------------
    # 下载单篇文章的 PDF
    # ----------------------------------------------------------
    def _download_one(self, title, detail_url):
        """
        在新标签页中打开文章详情页，优先点击 PDF 下载按钮，失败后尝试直连链接。

        返回：
            True  — 下载成功
            False — 下载失败或跳过
        """
        logger.info(f"  打开详情页: {title[:50]}...")

        # 在新标签页中打开详情页
        detail_tab = self.search_tab.new_tab(detail_url)
        self._delay(2, 4)

        try:
            self._wait_verify_passed(detail_tab, scene="详情页")

            # 等待详情页加载（标题和下载区都可能异步渲染）
            detail_tab.ele('tag:h1', timeout=15)

            # 设置该标签页的下载路径
            detail_tab.set.download_path(self.output_dir)

            pdf_btn, hit_selector = self._find_pdf_button(detail_tab, timeout=20)

            if not pdf_btn:
                logger.warning(f"  >> [跳过] 未找到 PDF 下载按钮（可能无权限或页面结构变化），URL={detail_tab.url}")
                detail_tab.close()
                return False

            logger.info(f"  >> 找到 PDF 按钮: {hit_selector}")

            # 某些场景下自动点击不会触发 target=_blank，新标签页会被拦截
            download_url = ""
            try:
                download_url = (pdf_btn.attr('href') or "").strip()
            except Exception:
                download_url = ""
            if download_url:
                download_url = urljoin(detail_tab.url or "https://www.cnki.net", download_url)

            # 记录下载前的文件列表，用于识别新下载的文件
            existing_files = set(glob.glob(os.path.join(self.output_dir, "*")))

            def wait_for_pdf(timeout_secs, baseline_tabs_count, scene):
                """轮询等待 PDF 文件落地并通过基本校验。"""
                deadline = time.time() + timeout_secs
                while time.time() < deadline:
                    self._wait_verify_passed(detail_tab, scene=f"详情页下载-{scene}")

                    if self.page.tabs_count > baseline_tabs_count:
                        latest_tab = self.page.latest_tab
                        self._wait_verify_passed(latest_tab, scene=f"{scene}跳转页")

                    new_file = self._get_new_download_file(existing_files, title=title)
                    if not new_file:
                        time.sleep(1)
                        continue

                    if is_valid_pdf(new_file):
                        # 不在脚本侧重命名，避免与 DrissionPage 下载线程竞争同一文件
                        logger.info(f"  >> [成功] 已保存: {os.path.basename(new_file)}")
                        # 清理错误页面
                        self._close_error_pages()
                        detail_tab.close()
                        return True

                    logger.info("  >> 检测到 PDF 但尚未完整，继续等待...")
                    time.sleep(1)
                return False

            # 第一优先级：点击 PDF 下载按钮
            logger.info("  >> 点击 PDF 下载按钮...")
            click_baseline_tabs = self.page.tabs_count
            clicked = False
            try:
                pdf_btn.click()
                clicked = True
            except Exception:
                # 部分页面普通 click 会被前端脚本拦截，改用 JS 点击兜底
                try:
                    pdf_btn.click(by_js=True)
                    clicked = True
                except Exception:
                    clicked = False

            if clicked:
                self._delay(0.8, 1.2)
                logger.info("  >> 等待下载文件落地（最多 40 秒）...")
                if wait_for_pdf(timeout_secs=40, baseline_tabs_count=click_baseline_tabs, scene="按钮"):
                    return True
                logger.info("  >> 按钮点击未在预期时间内完成下载，尝试直连链接兜底...")
            else:
                logger.warning("  >> 下载按钮点击失败，改为尝试访问下载链接。")

            # 第二优先级：直接访问下载链接兜底
            if download_url:
                logger.info("  >> 尝试直接访问下载链接...")
                direct_baseline_tabs = self.page.tabs_count
                try:
                    self.page.new_tab(download_url)
                    logger.info("  >> 已直接访问下载链接，等待文件落地（最多 15 秒）...")
                    if wait_for_pdf(timeout_secs=15, baseline_tabs_count=direct_baseline_tabs, scene="直链"):
                        return True
                except Exception as e:
                    logger.warning(f"  >> 直开下载链接失败: {e}")
            else:
                logger.info("  >> 无可用下载链接，无法继续尝试。")

            logger.warning("  >> [失败] 无法通过任何方式完成下载")

        except Exception as e:
            logger.error(f"  >> [异常] 处理详情页出错: {e}")

        # 关闭详情页标签
        try:
            detail_tab.close()
        except Exception:
            pass
        return False

    # ----------------------------------------------------------
    # 主运行流程
    # ----------------------------------------------------------
    def run(self):
        """爬虫主入口：搜索 → 遍历 → 过滤 → 下载"""
        logger.info("=" * 60)
        logger.info("CNKI 诊疗指南 PDF 全自动下载爬虫 (DrissionPage 版)")
        logger.info("=" * 60)
        logger.info(f"搜索关键词  : {self.keyword}")
        logger.info(f"最低下载量  : {self.min_downloads}")
        logger.info(f"起始页码    : {self.start_page}")
        logger.info(f"结束页码    : {self.max_pages}")
        logger.info(f"CNKI raw目录 : {self.raw_dir}")
        logger.info(f"输出目录    : {self.output_dir}")
        logger.info(f"日志文件    : {self.log_path}")
        logger.info(f"报告文件    : {self.report_path}")
        if self.start_url:
            logger.info(f"直达 URL     : {self.start_url}")
        logger.info("=" * 60)

        if self.start_url:
            # 模式 A: URL 直达
            logger.info("采用 URL 直达模式...")
            self.page.get(self.start_url)
            self.search_tab = self.page
            self._check_login()  # 即使直达也要检查登录状态
            self._wait_verify_passed(self.search_tab, scene="直达结果页")

            # 尝试自动获取当前页码（知网页码通常在 .page-number 类的 active 元素中）
            try:
                active_page = self.search_tab.ele('css:a.cur', timeout=3)
                if active_page and active_page.text.isdigit():
                    current_page = int(active_page.text)
                    logger.info(f"识别到当前位于第 {current_page} 页")
                else:
                    current_page = self.start_page
            except Exception:
                current_page = self.start_page
        else:
            # 模式 B: 常规搜索流程
            if not self._search():
                logger.error("搜索失败，退出。")
                return
            if not self._goto_start_page():
                logger.error("无法跳转到指定起始页，退出。")
                return
            current_page = self.start_page

        downloaded_list = []
        skipped_list = []
        failed_list = []

        while current_page <= self.max_pages:
            logger.info(f"{'─' * 40}")
            logger.info(f"正在处理第 {current_page} / {self.max_pages} 页")
            logger.info(f"{'─' * 40}")
            self._delay(2, 4)
            self._wait_verify_passed(self.search_tab, scene=f"第 {current_page} 页结果")

            # 获取当前页的所有结果行
            rows = self.search_tab.eles('css:.result-table-list tbody tr')
            if not rows:
                logger.warning("当前页未找到任何文献数据，停止。")
                break

            logger.info(f"本页共 {len(rows)} 条结果")

            for idx, row in enumerate(rows, 1):
                self.stats["total"] += 1
                try:
                    # 提取标题和详情链接
                    name_a = row.ele('css:.name a', timeout=2)
                    if not name_a:
                        continue
                    title = name_a.text.strip()
                    detail_url = name_a.link

                    if not title or not detail_url:
                        continue

                    # 提取下载量
                    dl_ele = row.ele('css:.download', timeout=1)
                    dl_text = dl_ele.text.strip() if dl_ele else "0"
                    dl_count = int(dl_text) if dl_text.isdigit() else 0

                    logger.info(f"[第{current_page}页 {idx}/{len(rows)}] {title[:60]}")
                    logger.info(f"  下载量: {dl_count}")

                    # 过滤：下载量不足
                    if dl_count < self.min_downloads:
                        logger.info(f"  >> 跳过（下载量 {dl_count} < {self.min_downloads}）")
                        self.stats["skip"] += 1
                        skipped_list.append({"title": title, "reason": f"下载量不足({dl_count})"})
                        continue

                    # 过滤：已下载
                    if title in self.history or self._is_in_log_history(title):
                        logger.info("  >> 跳过（已在下载历史中）")
                        self.stats["skip"] += 1
                        skipped_list.append({"title": title, "reason": "已下载"})
                        continue

                    # 尝试下载
                    success = self._download_one(title, detail_url)

                    if success:
                        self.stats["success"] += 1
                        downloaded_list.append({"title": title, "status": "success", "dl_count": dl_count})
                        self.history.add(title)
                    else:
                        self.stats["fail"] += 1
                        downloaded_list.append({"title": title, "status": "fail", "dl_count": dl_count})
                        failed_list.append({"title": title, "reason": "下载失败", "detail_url": detail_url})

                    # 随机延迟，避免触发反爬
                    self._delay(3, 7)

                except Exception as e:
                    logger.debug(f"解析第 {idx} 行时出错: {e}")
                    continue

            # 翻页逻辑
            if current_page >= self.max_pages:
                break

            next_btn = self.search_tab.ele('#PageNext', timeout=3)
            if next_btn:
                # 检查是否可以点击（不是 disabled 状态）
                cls = next_btn.attr('class') or ""
                if "disabled" in cls:
                    logger.info("已到达最后一页。")
                    break
                logger.info("翻到下一页...")
                next_btn.click()
                current_page += 1
                # 等待新页面加载
                self._delay(3, 5)
                self.search_tab.ele('css:.result-table-list tbody tr', timeout=10)
            else:
                logger.info("找不到翻页按钮，结束。")
                break

        # 保存报告
        self._save_report(downloaded_list, skipped_list)
        self._save_fail_list(failed_list)

        # 打印汇总
        logger.info("=" * 60)
        logger.info("爬取完成！统计信息：")
        logger.info(f"  搜索到文章总数  : {self.stats['total']}")
        logger.info(f"  成功下载文件数  : {self.stats['success']}")
        logger.info(f"  下载失败文件数  : {self.stats['fail']}")
        logger.info(f"  跳过文章总数    : {self.stats['skip']}")
        logger.info(f"  文件存储路径    : {self.output_dir}")
        logger.info("=" * 60)

        # 不自动关闭浏览器，方便用户检查
        # self.page.quit()


# ============================================================
# 入口函数
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="CNKI 疾病诊疗指南 PDF 全自动下载工具 (DrissionPage 版)"
    )
    parser.add_argument("--keyword", type=str, default="诊疗指南",
                        help="搜索关键词（默认: 诊疗指南）")
    parser.add_argument("--min-downloads", type=int, default=1000,
                        help="最低下载量阈值（默认: 1000）")
    parser.add_argument("--max-pages", type=int, default=1,
                        help="抓取截止页码（默认: 1）")
    parser.add_argument("--start-page", type=int, default=1,
                        help="起始页码（默认: 1）")
    parser.add_argument("--url", type=str, default=None,
                        help="直接指定搜索结果页 URL（绕过首页搜索和翻页）")
    parser.add_argument("--raw-dir", type=str, default=None,
                        help="CNKI 原始采集目录（默认: data/raw/cnki）")
    parser.add_argument("--cookie-file", type=str, default=None,
                        help="Cookie 文件路径（默认: 项目根目录 cookie.txt）")

    args = parser.parse_args()

    if args.start_page < 1:
        parser.error("--start-page 必须 >= 1")
    if args.max_pages < args.start_page:
        parser.error("--max-pages 必须 >= --start-page")

    spider = CnkiDownloader(
        keyword=args.keyword,
        min_downloads=args.min_downloads,
        max_pages=args.max_pages,
        start_page=args.start_page,
        start_url=args.url,
        raw_dir=args.raw_dir,
        cookie_file=args.cookie_file,
    )

    try:
        spider.run()
    except KeyboardInterrupt:
        logger.warning("用户手动中止任务。")
    except RuntimeError as e:
        logger.error(str(e))
        raise SystemExit(1)
    except SystemExit:
        pass


if __name__ == "__main__":
    main()
