"""
文章获取与管理模块
获取文章列表、搜索文章、管理下载任务
"""

import os
import sys
import subprocess
import json
import logging
import html
import time
import re
import urllib.parse
import threading
import requests as req
import shutil
from flask import Blueprint, jsonify, request, Response, redirect
from datetime import datetime
from pathlib import Path

from backend.config import (
    CONFIG_FILE, BASE_URL, DEFAULT_HEADERS, OUTPUT_DIR, DATA_DIR,
    DOWNLOAD_HISTORY_FILE,
    load_json, save_json, get_settings, get_proxies_dict, report_proxy_status,
    normalize_wechat_url, get_default_wechat_ua
)
from backend.account_pool import borrow_session, borrow_weread_session, account_pool, get_weread_session
from backend.accounts import biz_to_book_id
from backend.wechat_url import (
    normalize_wechat_short_url,
    wechat_short_url_from_review_id,
)
from backend.runtime import desktop_available, host_path_hint
from backend.request_profile import sleep_backoff, sleep_throttled

articles_bp = Blueprint("articles", __name__, url_prefix="/api/articles")
logger = logging.getLogger(__name__)

# 下载进度管理
_download_tasks = {}
_download_lock = threading.Lock()
_article_search_cache = {}
_article_search_lock = threading.Lock()
_ARTICLE_SEARCH_CACHE_TTL = 300
_ARTICLE_SEARCH_CACHE_LIMIT = 32
_ARTICLE_SEARCH_PAGE_SIZE = 50
_ARTICLE_SEARCH_MAX_PAGES = 200
_WEB_HISTORY_BATCH_SIZE = 20
_WEB_HISTORY_URL = "https://weread.qq.com/web/mp/articles"
_WEB_HISTORY_CACHE_TTL = 300
_WEB_HISTORY_LATEST_CACHE_TTL = 30
_WEB_HISTORY_CACHE_LIMIT = 512
_WEB_PAGE_COUNT_CACHE_TTL = 1800
_WEB_PAGE_COUNT_MAX_PAGES = 512
_WEB_PAGE_COUNT_MAX_PROBES = 20
_web_history_cache = {}
_web_history_cache_lock = threading.Lock()
_web_page_count_cache = {}
_web_page_count_lock = threading.Lock()

_PAGINATION_MORE_KEYS = ("hasMore", "has_more", "canContinue", "can_continue")
_PAGINATION_END_KEYS = ("isEnd", "is_end", "endOfList", "end_of_list")
_PAGINATION_TOTAL_KEYS = (
    "totalCount",
    "total_count",
    "chapterCount",
    "chapter_count",
    "total",
)


def _get_session():
    """获取凭证（通过账号池）"""
    account_id, token, cookie_str = borrow_session()
    return token, cookie_str


def fetch_article_detail_content(url: str, review_id: str = "") -> str:
    """抓取微信公众号文章网页并提取 HTML 正文（.rich_media_content），还原图片 data-src
    参考 we-mp-rss 优化：支持微信读书免风控正文接口、移动微信高仿请求与无头浏览器兜底
    """
    import bs4
    from backend.downloader import fetch_wechat_article_html

    raw_html, _, error = fetch_wechat_article_html(url, review_id=review_id)
    if not raw_html:
        raise RuntimeError(error or "抓取文章内容失败")

    soup = bs4.BeautifulSoup(raw_html, "html.parser")
    content_node = soup.select_one(".rich_media_content") or soup.select_one("#js_content") or soup.select_one("#js_article")
    if not content_node:
        return raw_html

    for img in content_node.find_all("img"):
        if img.get("data-src"):
            img["src"] = img["data-src"]
            del img["data-src"]

    return str(content_node)


_review_url_cache: dict[str, str] = {}
_review_info_cache: dict[str, dict] = {}
_review_cache_lock = threading.Lock()


def _check_is_original(item: dict, mp_info: dict) -> bool:
    """从多个上游字段判断原创标记，未知时保持为非原创。"""
    for source in (mp_info, item):
        if not isinstance(source, dict):
            continue
        copyright_type = (
            source.get("copyright_type")
            or source.get("copyrightType")
            or source.get("copyright")
            or source.get("copyright_stat")
        )
        if copyright_type is not None:
            try:
                if int(copyright_type) > 0:
                    return True
            except (TypeError, ValueError):
                if str(copyright_type).strip().lower() in {"true", "yes", "original"}:
                    return True

        is_original = (
            source.get("is_original")
            or source.get("isOriginal")
            or source.get("original")
        )
        if is_original is True or str(is_original).strip().lower() in {"1", "true", "yes"}:
            return True
    return False


def _resolve_review_info(review_id: str, headers: dict) -> dict:
    """解析文章短链、真实发布时间和原创标记，并缓存结果。"""
    if not review_id:
        return {}

    with _review_cache_lock:
        cached = _review_info_cache.get(review_id)
        if cached is not None:
            return cached

    info = {
        "doc_url": "",
        "create_time": 0,
        "is_original": False,
        "title": "",
        "digest": "",
        "author": "",
        "cover": "",
    }
    short_url = wechat_short_url_from_review_id(review_id)
    if short_url:
        info["doc_url"] = short_url

    try:
        url = f"https://i.weread.qq.com/review/single?reviewId={review_id}"
        s = get_weread_session()
        resp = s.get(url, headers=headers, timeout=6)
        if resp.status_code == 200:
            review = resp.json().get("review") or {}
            mp_info = review.get("mpInfo") or {}
            orig_id = mp_info.get("originalId", "")
            doc_url = wechat_short_url_from_review_id(f"MP_WXS_0_{orig_id}")
            if not doc_url:
                doc_url = normalize_wechat_short_url(mp_info.get("doc_url", ""))
            if doc_url:
                info["doc_url"] = doc_url
            info["create_time"] = int(
                review.get("createTime")
                or review.get("updateTime")
                or mp_info.get("time")
                or mp_info.get("create_time")
                or mp_info.get("update_time")
                or mp_info.get("publish_time")
                or 0
            )
            info["title"] = mp_info.get("title") or review.get("title") or ""
            info["digest"] = mp_info.get("digest") or mp_info.get("content") or ""
            info["author"] = mp_info.get("author") or mp_info.get("mp_name") or ""
            info["cover"] = mp_info.get("pic_url") or mp_info.get("thumbUrl") or ""
            info["is_original"] = _check_is_original(review, mp_info)
    except Exception:
        pass

    with _review_cache_lock:
        _review_info_cache[review_id] = info
        if info["doc_url"]:
            _review_url_cache[review_id] = info["doc_url"]
    return info


def _resolve_review_doc_url(review_id: str, headers: dict) -> str:
    """通过微信读书 review/single 接口解析原生微信推文链接。"""
    if not review_id:
        return ""
    short_url = wechat_short_url_from_review_id(review_id)
    if short_url:
        return short_url
    with _review_cache_lock:
        if review_id in _review_url_cache:
            return _review_url_cache[review_id]
    return _resolve_review_info(review_id, headers).get("doc_url", "")


def _parse_upstream_pagination(
    data: dict,
    *,
    offset: int,
    returned_count: int,
) -> tuple[bool, bool, int | None]:
    """解析上游分页元数据，并区分明确结论与保守续页。"""

    metadata = [data]
    for key in ("pagination", "pageInfo", "page_info", "meta"):
        value = data.get(key)
        if isinstance(value, dict):
            metadata.append(value)

    total_count = None
    for item in metadata:
        for key in _PAGINATION_TOTAL_KEYS:
            if key not in item:
                continue
            total_count = _positive_int(item.get(key))
            if total_count is not None:
                break
        if total_count is not None:
            break

    if total_count is not None and total_count < offset + returned_count:
        logger.warning(
            "忽略不一致的上游文章总数: total=%s offset=%s returned=%s",
            total_count,
            offset,
            returned_count,
        )
        total_count = None

    if total_count is not None:
        return offset + returned_count < total_count, True, total_count

    for item in metadata:
        for key in _PAGINATION_MORE_KEYS:
            if key in item:
                return _pagination_bool(item.get(key)), True, total_count
        for key in _PAGINATION_END_KEYS:
            if key in item:
                return not _pagination_bool(item.get(key)), True, total_count

    for item in metadata:
        for key in ("nextOffset", "next_offset"):
            next_offset = _positive_int(item.get(key))
            if next_offset is not None:
                return next_offset > offset, True, total_count

    # 微信读书 mp/chapters 的部分响应没有 hasMore/totalCount，且中间页可能
    # 因删除、隐藏文章少于请求条数。非空页只能说明“至少还有可能”，
    # 不能据此宣判末页；真正空页才是可靠的终止信号。
    if returned_count > 0:
        return True, False, total_count
    return False, True, total_count


def _pagination_bool(value) -> bool:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"", "0", "false", "no", "off", "null", "none"}:
            return False
        if normalized in {"1", "true", "yes", "on"}:
            return True
    return bool(value)


def _fetch_web_articles_page(
    book_id: str,
    begin: int,
    count: int,
    account_name: str = "",
    keyword: str = "",
) -> tuple[list, int, int, bool, bool]:
    """通过微信读书 Web 历史接口读取完整分页，并展开多图文子文章。"""
    articles = []
    has_more = True
    continuation_exact = False
    normalized_keyword = keyword.casefold()

    for relative_offset in range(0, count, _WEB_HISTORY_BATCH_SIZE):
        requested = min(_WEB_HISTORY_BATCH_SIZE, count - relative_offset)
        data = _fetch_web_history_batch(book_id, begin + relative_offset)
        groups = data.get("reviews") or []

        selected_groups = groups[:requested]
        page_articles = _flatten_web_article_groups(selected_groups, book_id, account_name)
        if normalized_keyword:
            page_articles = [
                article
                for article in page_articles
                if normalized_keyword in str(article.get("title") or "").casefold()
            ]
        articles.extend(page_articles)

        if not groups:
            has_more = False
            continuation_exact = True
            break
        if len(groups) > requested:
            has_more = True
            continuation_exact = False
            break
        # clearAll 是客户端同步缓存重置标记，首屏也可能为 1，不能用来判断历史结束。
        # Web 接口还会因删除或隐藏文章返回不足 20 个分组，但更深 offset 仍有内容；
        # 因此只有空页才作为可靠终止信号。
        has_more = True
        continuation_exact = False

    minimum_total = begin + len(articles) + (1 if has_more else 0)
    return articles, minimum_total, 1 if has_more else 0, False, continuation_exact


def _fetch_web_history_batch(book_id: str, offset: int) -> dict:
    """读取一个 Web 历史分组批次，并用短 TTL 降低翻页与全局搜索的重复请求。"""
    from backend.waterwall import is_waterwall_active

    if is_waterwall_active():
        raise RuntimeError("微信读书上游正处于频控熔断期，请稍后再试")

    cache_key = (book_id, offset)
    now = time.monotonic()
    cache_ttl = _WEB_HISTORY_LATEST_CACHE_TTL if offset == 0 else _WEB_HISTORY_CACHE_TTL
    with _web_history_cache_lock:
        cached = _web_history_cache.get(cache_key)
        if cached and now - cached["cached_at"] <= cache_ttl:
            return cached["data"]
        if cached:
            _web_history_cache.pop(cache_key, None)

    session = get_weread_session()
    last_error = ""
    for attempt in range(2):
        try:
            account_id, _vid, _token, mobile_headers = borrow_weread_session()
        except RuntimeError as exc:
            raise RuntimeError("账号池中无可用微信读书账号，请先在『账号池』页面扫码登录") from exc

        headers = {
            "Cookie": mobile_headers.get("Cookie", ""),
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://weread.qq.com/",
        }
        try:
            response = session.get(
                _WEB_HISTORY_URL,
                params={"bookId": book_id, "offset": offset},
                headers=headers,
                timeout=12,
            )
        except Exception as exc:
            last_error = str(exc)
            sleep_backoff(attempt + 1, base=0.4, cap=2.0)
            continue

        try:
            candidate = response.json()
        except (TypeError, ValueError):
            candidate = {}
        error_code = candidate.get("errCode", candidate.get("errcode"))
        if response.status_code == 200 and not error_code and "reviews" in candidate:
            account_pool.report(account_id, is_success=True)
            reviews = candidate.get("reviews") or []
            if not reviews and attempt == 0:
                sleep_backoff(1, base=0.25, cap=0.5)
                continue
            if reviews:
                with _web_history_cache_lock:
                    if len(_web_history_cache) >= _WEB_HISTORY_CACHE_LIMIT:
                        oldest_key = min(
                            _web_history_cache,
                            key=lambda key: _web_history_cache[key]["cached_at"],
                        )
                        _web_history_cache.pop(oldest_key, None)
                    _web_history_cache[cache_key] = {"cached_at": now, "data": candidate}
            return candidate

        last_error = str(candidate.get("errMsg") or candidate.get("errmsg") or response.status_code)
        rate_limited = (
            error_code == -2014
            or "-2014" in response.text
            or response.status_code == 429
        )
        if rate_limited:
            from backend.waterwall import record_failure, waterwall_hit

            record_failure(
                _WEB_HISTORY_URL,
                response.status_code,
                response.headers,
                response.text,
                "-2014",
            )
        account_pool.report(
            account_id,
            status_code=response.status_code,
            ret=error_code,
            error_msg=last_error,
        )
        if rate_limited and attempt == 0:
            sleep_backoff(attempt + 1, base=0.5, cap=1.5)
            continue
        if rate_limited:
            waterwall_hit(_WEB_HISTORY_URL, response.status_code, "-2014")
            break
        if response.status_code not in {401, 429, 499} and not error_code:
            break
        sleep_backoff(attempt + 1, base=0.4, cap=2.0)

    raise RuntimeError(f"微信读书 Web 历史接口暂不可用: {last_error or '未知错误'}")


def _discover_web_total_pages(book_id: str, page_size: int) -> int | None:
    """用有界指数探测和二分定位总页数，结果缓存且不把单次空响应写入历史缓存。"""
    cache_key = (book_id, page_size)
    now = time.monotonic()
    with _web_page_count_lock:
        cached = _web_page_count_cache.get(cache_key)
        if cached and now - cached["cached_at"] <= _WEB_PAGE_COUNT_CACHE_TTL:
            return cached["total_pages"]

        observed = {}
        probes = 0

        def has_page(page_index: int) -> bool | None:
            nonlocal probes
            if page_index in observed:
                return observed[page_index]
            if probes >= _WEB_PAGE_COUNT_MAX_PROBES:
                return None
            probes += 1
            data = _fetch_web_history_batch(book_id, page_index * page_size)
            value = bool(data.get("reviews") or [])
            observed[page_index] = value
            return value

        if has_page(0) is not True:
            return None

        lower = 0
        upper = 1
        while upper < _WEB_PAGE_COUNT_MAX_PAGES:
            state = has_page(upper)
            if state is None:
                return None
            if not state:
                break
            lower = upper
            upper = min(_WEB_PAGE_COUNT_MAX_PAGES, upper * 2)

        if upper >= _WEB_PAGE_COUNT_MAX_PAGES:
            return None

        while lower + 1 < upper:
            middle = (lower + upper) // 2
            state = has_page(middle)
            if state is None:
                return None
            if state:
                lower = middle
            else:
                upper = middle

        total_pages = lower + 1
        _web_page_count_cache[cache_key] = {
            "cached_at": time.monotonic(),
            "total_pages": total_pages,
        }
        return total_pages


def _flatten_web_article_groups(groups: list, book_id: str, account_name: str) -> list:
    """把 Web 历史接口的推送分组展开成产品统一文章结构。"""
    articles = []
    seen = set()
    for group in groups:
        if not isinstance(group, dict):
            continue
        group_time = group.get("createTime") or 0
        for sub_review in group.get("subReviews") or []:
            if not isinstance(sub_review, dict):
                continue
            review = sub_review.get("review") or {}
            mp_info = review.get("mpInfo") or {}
            title = str(mp_info.get("title") or "").strip()
            if not title:
                continue
            original_id = str(mp_info.get("originalId") or "").strip()
            review_id = str(
                sub_review.get("reviewId")
                or review.get("reviewId")
                or (f"{book_id}_{original_id}" if original_id else "")
            )
            identity = review_id or f"{title}:{mp_info.get('time') or group_time}"
            if identity in seen:
                continue
            seen.add(identity)

            direct_link = wechat_short_url_from_review_id(review_id)
            lazy_link = (
                "/api/wechat-mp/app/api/articles/open?review_id="
                + urllib.parse.quote(review_id, safe="")
                if review_id
                else ""
            )
            articles.append(
                {
                    "title": title,
                    "link": direct_link or lazy_link,
                    "cover": mp_info.get("pic_url") or "",
                    "digest": mp_info.get("content") or "",
                    "author": mp_info.get("mp_name") or account_name,
                    "update_time": mp_info.get("time") or review.get("createTime") or group_time,
                    "is_original": _check_is_original(review, mp_info),
                    "item_show_type": 0,
                    "id": review_id,
                }
            )
    return articles








def _fetch_articles_page(
    fakeid: str,
    begin: int,
    count: int,
    keyword: str = "",
    account_name: str = "",
    from_article_id: str = "",
    with_meta: bool = False,
) -> tuple:
    """使用微信读书官方推文聚合引擎获取文章列表 (articles, total_count, can_continue)
    1. 统一 401 静默自愈续期通道，遇到凭据过期自动换取最新 token
    2. 首屏优先获取 mp/cover 置顶最新推文 (100% 成功率，带 doc_url)
    3. 获取 mp/chapters 分页推文；若受 499 临时限制自动平滑降级，绝不抛出 500
    4. 备用通道 article/list 兜底，并发解析每篇推文原生微信链接
    """
    book_id = biz_to_book_id(fakeid)
    if not book_id:
        raise RuntimeError(f"无效的公众号标识: {fakeid}")

    try:
        web_result = _fetch_web_articles_page(book_id, begin, count, account_name, keyword)
        return web_result if with_meta else web_result[:3]
    except RuntimeError as exc:
        from backend.waterwall import is_waterwall_active

        if is_waterwall_active():
            raise
        logger.warning("微信读书 Web 历史源降级到移动端: %s", exc)

    s = get_weread_session()

    def _do_get(url: str):
        """内部请求函数：对齐官方 SyncKeyRequestFeature 与 WRRetryHandler 错误码自愈策略"""
        from backend.waterwall import is_waterwall_active

        if is_waterwall_active():
            return None, None, None

        req_url = url
        # 遵循 APK SyncKeyRequestFeature: 同步型接口自动补全 synckey=0 规避 499 拒止
        if any(k in req_url for k in ("/mp/chapters", "/mp/list", "/shelf/sync", "/subscription/books")) and "synckey=" not in req_url:
            req_url = f"{req_url}&synckey=0" if "?" in req_url else f"{req_url}?synckey=0"

        last_resp = None
        last_h = None
        last_acc = None
        for att in range(2):
            try:
                acc_id, vid, tok, h = borrow_weread_session()
            except RuntimeError as e:
                raise RuntimeError("账号池中无可用微信读书账号，请先在『账号池』页面扫码登录") from e
            last_h = h
            last_acc = acc_id
            try:
                r = s.get(req_url, headers=h, timeout=10)
                last_resp = r

                # ── 优先检测腾讯防水墙 (TCaptcha) ──
                from backend.waterwall import detect_waterwall, waterwall_hit, record_failure
                ww_marker = detect_waterwall(r.status_code, r.text)
                if ww_marker:
                    record_failure(req_url, r.status_code, r.headers, r.text, ww_marker)
                    waterwall_hit(req_url, r.status_code, ww_marker)
                    return r, h, acc_id

                # 401 Token 过期: 自动静默续期重试
                if r.status_code == 401:
                    print(f"[_fetch_articles_page] 微信读书 401 Token 过期，触发自动静默续期 (第 {att+1} 次)...", flush=True)
                    account_pool.report(acc_id, status_code=401)
                    time.sleep(0.5)
                    continue

                # 429 或 499: 精准匹配官方错误码 (对齐 OverFreqInterceptor 与 WRRetryHandler 策略)
                if r.status_code in (429, 499):
                    err_json = {}
                    try:
                        err_json = r.json()
                    except Exception:
                        pass
                    err_c = err_json.get("errcode")
                    err_m = str(err_json.get("errmsg") or "")

                    # 1. 微信读书频控 -2014 (OverFreqInterceptor): 短时间瞬时并发过高，自动退避 1.5 秒后降频重试
                    if err_c == -2014 or "-2014" in r.text:
                        print(f"[_fetch_articles_page] 触发微信读书网关频控 (-2014)，自动退避 1.5 秒后降频重试...", flush=True)
                        time.sleep(1.5)
                        rate_limited_response = r
                        try:
                            r_retry = s.get(req_url, headers=h, timeout=10)
                            if r_retry.status_code == 200:
                                return r_retry, h, acc_id
                            rate_limited_response = r_retry
                        except Exception as ex_retry:
                            logger.debug("频控退避重试网络异常: %s", ex_retry)

                        record_failure(
                            req_url,
                            rate_limited_response.status_code,
                            rate_limited_response.headers,
                            rate_limited_response.text,
                            "-2014",
                        )
                        account_pool.report(
                            acc_id,
                            status_code=499,
                            ret=-2014,
                            error_msg="触发高频风控 (-2014)，账号已进入冷却",
                        )
                        if att == 0:
                            sleep_backoff(att + 1, base=0.5, cap=1.5)
                            continue
                        waterwall_hit(
                            req_url,
                            rate_limited_response.status_code,
                            "-2014",
                        )
                        return rate_limited_response, h, acc_id

                    # 2. 网关超时 -2012 (对齐 WRRetryHandler.canRetryTimeOut / whetherNeedToRetry 策略)
                    elif err_c == -2012 or "-2012" in r.text:
                        print(f"[_fetch_articles_page] 上游网关超时 (-2012)，遵循官方策略等待 0.5 秒自动重试...", flush=True)
                        time.sleep(0.5)
                        try:
                            r_retry = s.get(req_url, headers=h, timeout=10)
                            if r_retry.status_code == 200:
                                return r_retry, h, acc_id
                        except Exception:
                            pass

                    # 3. 账号人机验证 / 终端同步态 -2041 (对齐 WRRetryHandler.canRetryAfterVerify 策略)
                    elif err_c == -2041 or "2041" in r.text:
                        print(f"[_fetch_articles_page] 账号 [{acc_id}] 触发终端会话在线态核验 (-2041)，调用 activate_terminal_session 模拟真机同步...", flush=True)
                        from backend.weread_signer import activate_terminal_session
                        if activate_terminal_session(h, session=s):
                            try:
                                r_retry = s.get(req_url, headers=h, timeout=10)
                                if r_retry.status_code == 200:
                                    print(f"[_fetch_articles_page] 账号 [{acc_id}] 移动端会话同步激活成功，重试请求通过！", flush=True)
                                    return r_retry, h, acc_id
                            except Exception as ex:
                                logger.debug("重试请求异常: %s", ex)

                        # 若移动会话已激活但仍返回 -2041，确定触发官方 TCaptcha 人机验证，唤起前端滑块弹窗！
                        print(f"[_fetch_articles_page] 账号 [{acc_id}] 移动会话已激活但仍返回 -2041，确认为官方强制 TCaptcha 人机验证！", flush=True)
                        record_failure(req_url, r.status_code, r.headers, r.text, "-2041")
                        waterwall_hit(req_url, r.status_code, "-2041")
                        account_pool.report(acc_id, status_code=499, ret=-2041, error_msg="触发腾讯人机验证 (-2041)，需在网页完成滑块验证")
                        return r, h, acc_id
                    else:
                        print(f"[_fetch_articles_page] 账号 [{acc_id}] 遇到 499/429 限制 ({err_c} {err_m})，自动轮换账号池备用账号...", flush=True)
                        account_pool.report(acc_id, status_code=r.status_code, ret=err_c, error_msg=f"请求频控 ({err_c} {err_m})，临时冷却")

                    # 频控后指数退避，避免轮换账号的瞬间形成密集重试
                    sleep_backoff(att + 1, base=0.4, cap=4.0)
                    continue
                return r, h, acc_id
            except Exception as e:
                logger.debug("[_fetch_articles_page] 网络异常: %s", e)
                sleep_backoff(att + 1, base=0.5, cap=4.0)
        return last_resp, last_h, last_acc

    articles = []
    has_more = False
    continuation_exact = False
    upstream_total = None
    active_headers = None
    active_acc_id = None
    chapters_succeeded = False
    fallback_succeeded = False

    # ── 1. 优先获取 mp/cover 最新置顶推文 (第一页时优先执行，100% 成功率带 doc_url) ──
    from backend.waterwall import is_waterwall_active

    if begin == 0 and not is_waterwall_active():
        try:
            u_cov = f"https://i.weread.qq.com/mp/cover?bookId={book_id}"
            resp_cov, h_cov, acc_cov = _do_get(u_cov)
            if resp_cov and resp_cov.status_code == 200:
                active_headers = h_cov
                active_acc_id = acc_cov
                cdata = resp_cov.json()
                rid = cdata.get("reviewId", "")
                if rid:
                    doc_u = _resolve_review_doc_url(rid, h_cov or {})
                    t_cov = cdata.get("title", "")
                    if not keyword or keyword.lower() in t_cov.lower():
                        articles.append({
                            "title": t_cov,
                            "link": doc_u,
                            "cover": cdata.get("pic", "") or cdata.get("avatar", ""),
                            "digest": "",
                            "author": account_name or cdata.get("name", ""),
                            "update_time": 0,
                            "is_original": True,
                            "item_show_type": 0,
                            "id": rid,
                        })
        except Exception as e:
            logger.debug("[_fetch_articles_page] mp/cover 获取异常: %s", e)

    # ── 2. 尝试从 mp/chapters 获取分页推文列表 ──
    raw_items = []
    try:
        url_chap = f"https://i.weread.qq.com/mp/chapters?bookId={book_id}&count={count}&offset={begin}&pf=android"
        resp_chap, h_chap, acc_chap = _do_get(url_chap)
        if resp_chap:
            if resp_chap.status_code == 200:
                active_headers = h_chap or active_headers
                active_acc_id = acc_chap or active_acc_id
                data = resp_chap.json()
                raw_items = data.get("data") or data.get("chapters") or data.get("list") or []
                chapters_succeeded = True
                has_more, continuation_exact, upstream_total = _parse_upstream_pagination(
                    data,
                    offset=begin,
                    returned_count=len(raw_items),
                )
            elif resp_chap.status_code in (429, 499):
                print(f"[_fetch_articles_page] mp/chapters 返回 HTTP {resp_chap.status_code}，启用多级聚合引擎安全平滑降级...", flush=True)
    except Exception as e:
        logger.debug("[_fetch_articles_page] mp/chapters 异常: %s", e)

    # ── 3. 备用通道：若推文仍为空，尝试从 article/list 补齐 ──
    if (
        begin == 0
        and not chapters_succeeded
        and len(raw_items) == 0
        and not is_waterwall_active()
    ):
        try:
            u_alist = f"https://i.weread.qq.com/article/list?bookId={book_id}&synckey=0"
            resp_alist, h_alist, acc_alist = _do_get(u_alist)
            if resp_alist and resp_alist.status_code == 200:
                active_headers = h_alist or active_headers
                active_acc_id = acc_alist or active_acc_id
                fallback_succeeded = True
                al_data = resp_alist.json()
                raw_items = al_data.get("reviews") or al_data.get("data") or []
                has_more, continuation_exact, upstream_total = _parse_upstream_pagination(
                    al_data,
                    offset=begin,
                    returned_count=len(raw_items),
                )
        except Exception as e:
            logger.debug("[_fetch_articles_page] article/list 备用拉取异常: %s", e)

    if not chapters_succeeded and not fallback_succeeded:
        raise RuntimeError("上游历史文章分页暂时不可用，请稍后重试当前页")

    # ── 4. 并发解析推文原生官方链接 doc_url 并去重合并 ──
    if raw_items:
        import concurrent.futures
        def _get_item_meta(it):
            mp_info = it.get("mpInfo", {}) if isinstance(it.get("mpInfo"), dict) else {}
            rid = str(it.get("reviewId") or "")
            short_url = wechat_short_url_from_review_id(rid)
            doc_url = ""
            if short_url:
                doc_url = short_url
            else:
                doc_url = normalize_wechat_short_url(mp_info.get("doc_url", ""))

            create_time = (
                it.get("createTime")
                or it.get("updateTime")
                or it.get("publishTime")
                or mp_info.get("time")
                or mp_info.get("create_time")
                or mp_info.get("update_time")
                or mp_info.get("publish_time")
                or 0
            )
            is_original = _check_is_original(it, mp_info)
            if (not doc_url or not create_time) and rid:
                review_info = _resolve_review_info(rid, active_headers or {})
                doc_url = doc_url or review_info.get("doc_url", "")
                create_time = create_time or review_info.get("create_time", 0)
                is_original = is_original or review_info.get("is_original", False)
            return doc_url, int(create_time or 0), is_original

        with concurrent.futures.ThreadPoolExecutor(max_workers=min(10, max(1, len(raw_items)))) as ex:
            item_meta = list(ex.map(_get_item_meta, raw_items))

        for it, (doc_u, create_t, is_original) in zip(raw_items, item_meta):
            mp_i = it.get("mpInfo", {}) if isinstance(it.get("mpInfo"), dict) else {}
            title = mp_i.get("title") or it.get("title") or ""
            if not title:
                continue
            if keyword and keyword.lower() not in title.lower():
                continue
            # 去重：若已有（如置顶推文），跳过
            if any(existing.get("title") == title for existing in articles):
                continue

            pic = mp_i.get("pic_url") or mp_i.get("thumbUrl") or it.get("cover") or ""
            review_id = it.get("reviewId") or ""

            articles.append({
                "title": title,
                "link": doc_u,
                "cover": pic,
                "digest": mp_i.get("digest", ""),
                "author": mp_i.get("author") or account_name or "",
                "update_time": create_t,
                "is_original": is_original,
                "item_show_type": 0,
                "id": review_id,
            })

    minimum_total = begin + len(articles) + (1 if has_more else 0)
    total_count = upstream_total if upstream_total is not None else minimum_total
    can_continue = 1 if has_more else 0

    if active_acc_id:
        account_pool.report(active_acc_id, is_success=True)

    if with_meta:
        return (
            articles,
            total_count,
            can_continue,
            upstream_total is not None,
            continuation_exact,
        )
    return articles, total_count, can_continue


def _positive_int(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _apply_article_download_states(articles: list, account_name: str = "") -> None:
    """按中央下载历史标记未下载、已下载和下载失败；入库阶段由成果接口继续细分。"""
    history = load_json(DOWNLOAD_HISTORY_FILE, [])
    by_url = {}
    by_title = {}
    for item in history:
        if not isinstance(item, dict):
            continue
        link = normalize_wechat_url(item.get("link") or "")
        if link:
            by_url[link] = item
        title_key = (str(item.get("account") or ""), str(item.get("title") or ""))
        if title_key[1]:
            by_title[title_key] = item
    for article in articles:
        link = normalize_wechat_url(article.get("link") or "")
        record = by_url.get(link) or by_title.get((account_name, str(article.get("title") or "")))
        if record and record.get("success"):
            article["download_state"] = record.get("download_state") or "downloaded"
            article["failure_stage"] = record.get("failure_stage")
            article["download_path"] = record.get("path")
        elif record:
            article["download_state"] = "failed"
            article["failure_stage"] = record.get("failure_stage") or "download"
            article["download_error"] = record.get("error") or "下载失败"
        else:
            article["download_state"] = "not_downloaded"
            article["failure_stage"] = None


def _search_all_article_pages(
    fakeid: str,
    keyword: str,
    account_name: str = "",
    start_time: int = 0,
    end_time: int = 0,
) -> dict:
    """扫描所选公众号全部历史分页，再按标题与发布时间匹配并去重。"""

    normalized_keyword = " ".join(str(keyword or "").split()).casefold()
    if not normalized_keyword and not (start_time and end_time):
        return {"articles": [], "scanned": 0, "complete": True, "stop_reason": "empty_filter"}

    matches = []
    seen_articles = set()
    seen_pages = set()
    scanned = 0
    begin = 0
    complete = False
    stop_reason = ""

    for _page_index in range(_ARTICLE_SEARCH_MAX_PAGES):
        articles, _total_count, can_continue = _fetch_articles_page(
            fakeid,
            begin,
            _ARTICLE_SEARCH_PAGE_SIZE,
            "",
            account_name=account_name,
        )
        page_signature = tuple(
            str(item.get("id") or item.get("link") or item.get("title") or "")
            for item in articles
        )
        if page_signature in seen_pages:
            stop_reason = "upstream_repeated_page"
            break
        seen_pages.add(page_signature)
        if not articles:
            complete = not bool(can_continue)
            stop_reason = "upstream_complete" if complete else "upstream_empty_page"
            break

        page_times = []
        for article in articles:
            identity = str(
                article.get("id")
                or article.get("link")
                or f"{article.get('title', '')}:{article.get('update_time', '')}"
            )
            if identity in seen_articles:
                continue
            seen_articles.add(identity)
            scanned += 1
            article_time = int(article.get("update_time") or 0)
            if article_time:
                page_times.append(article_time)
            title_matches = (
                not normalized_keyword
                or normalized_keyword in str(article.get("title") or "").casefold()
            )
            date_matches = (
                not (start_time and end_time)
                or (article_time and start_time <= article_time <= end_time)
            )
            if title_matches and date_matches:
                matches.append(article)

        if start_time and page_times and len(page_times) == len(articles) and max(page_times) < start_time:
            complete = True
            stop_reason = "date_range_complete"
            break

        if not can_continue:
            complete = True
            stop_reason = "upstream_complete"
            break
        begin += _ARTICLE_SEARCH_PAGE_SIZE
    else:
        stop_reason = "safety_page_limit"

    return {
        "articles": matches,
        "scanned": scanned,
        "complete": complete,
        "stop_reason": stop_reason,
    }


@articles_bp.route("/page-count/<fakeid>", methods=["GET"])
def get_article_page_count(fakeid):
    """稀疏探测并缓存历史总页数；无法在调用预算内确认时保持未知。"""
    count = min(max(1, request.args.get("count", 20, type=int)), 100)
    book_id = biz_to_book_id(fakeid)
    if not book_id:
        return jsonify({"error": "无效的公众号标识"}), 400
    try:
        total_pages = _discover_web_total_pages(book_id, count)
    except Exception as exc:
        logger.warning("公众号总页数探测失败: book_id=%s error=%s", book_id, str(exc)[:240])
        total_pages = None
    return jsonify(
        {
            "total_pages": total_pages,
            "total_pages_exact": total_pages is not None,
        }
    )


@articles_bp.route("/list/<fakeid>", methods=["GET"])
def get_articles(fakeid):
    """获取指定公众号的文章列表"""
    begin = max(0, request.args.get("begin", 0, type=int))
    count = min(max(1, request.args.get("count", 10, type=int)), 100)
    keyword = request.args.get("keyword", "").strip()
    account_name = request.args.get("account_name", "").strip()
    from_article_id = request.args.get("from_article_id", "").strip()

    t_start = time.time()
    print(f"[Articles API] Start fetching articles for fakeid={fakeid} begin={begin} count={count} from_article_id={from_article_id}", flush=True)

    try:
        articles, total_count, can_continue, total_exact, continuation_exact = _fetch_articles_page(
            fakeid,
            begin,
            count,
            keyword,
            account_name=account_name,
            from_article_id=from_article_id,
            with_meta=True,
        )
        _apply_article_download_states(articles, account_name)
        print(f"[Articles API] Fetch finished in {time.time() - t_start:.2f}s, got {len(articles)} articles", flush=True)

        from backend.waterwall import is_waterwall_active, waterwall_snapshot
        current_page = begin // count + 1
        terminal_empty = bool(begin > 0 and not articles and continuation_exact and not can_continue)
        total_pages_exact = bool(total_exact or (continuation_exact and not can_continue))
        if total_exact:
            total_pages = (total_count + count - 1) // count
        elif terminal_empty:
            total_pages = max(1, current_page - 1)
        elif total_pages_exact:
            total_pages = current_page
        else:
            total_pages = None

        res_data = {
            "articles": articles,
            "total": total_count,
            "can_msg_continue": can_continue,
            "begin": begin,
            "count": len(articles),
            "total_exact": total_exact,
            "total_pages_exact": total_pages_exact,
            "total_pages": total_pages,
            "minimum_total_pages": (
                current_page + 1 if can_continue else max(1, total_pages or current_page)
            ),
            "terminal_empty": terminal_empty,
        }
        if is_waterwall_active():
            res_data["need_verify"] = True
            res_data["waterwall"] = waterwall_snapshot()

        return jsonify(res_data)

    except PermissionError as e:
        print(f"[Articles API] PermissionError in {time.time() - t_start:.2f}s: {e}", flush=True)
        return jsonify({"error": str(e)}), 401
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[Articles API] Exception in {time.time() - t_start:.2f}s: {e}", flush=True)
        from backend.waterwall import is_waterwall_active, waterwall_snapshot
        err_res = {"error": f"网络请求失败: {str(e)}", "articles": [], "total": 0, "count": 0}
        if is_waterwall_active():
            err_res["need_verify"] = True
            err_res["waterwall"] = waterwall_snapshot()
        return jsonify(err_res), 502


def _canonical_url_from_weread_html(raw_html: str) -> str:
    """从微信读书正文代理页提取并清洗公开微信文章地址。"""
    match = re.search(
        r'<meta[^>]+property=["\']og:url["\'][^>]+content=["\']([^"\']+)["\']',
        raw_html or "",
        re.I,
    )
    if not match:
        match = re.search(
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:url["\']',
            raw_html or "",
            re.I,
        )
    if not match:
        return ""

    candidate = html.unescape(match.group(1)).split("#", 1)[0]
    try:
        parsed = urllib.parse.urlsplit(candidate)
        if parsed.scheme not in {"http", "https"} or parsed.hostname != "mp.weixin.qq.com":
            return ""
        query = [
            (key, value)
            for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
            if key != "chksm"
        ]
        return urllib.parse.urlunsplit(
            parsed._replace(query=urllib.parse.urlencode(query, doseq=True), fragment="")
        )
    except (TypeError, ValueError):
        return ""


@articles_bp.route("/open", methods=["GET"])
def open_article():
    """按 reviewId 延迟解析真实微信链接，避免列表阶段批量拉取正文。"""
    review_id = request.args.get("review_id", "").strip()
    if not re.fullmatch(r"MP_WXS_[0-9]+_[A-Za-z0-9_~-]{15,160}", review_id):
        return jsonify({"error": "文章标识无效"}), 400

    direct_url = wechat_short_url_from_review_id(review_id)
    if direct_url:
        return redirect(direct_url, code=302)

    from backend.downloader import fetch_via_weread_content

    raw_html, ok = fetch_via_weread_content(review_id)
    target = _canonical_url_from_weread_html(raw_html) if ok else ""
    if not target:
        return jsonify({"error": "暂时无法解析文章公开链接，请稍后重试"}), 502
    return redirect(target, code=302)


@articles_bp.route("/search/<fakeid>", methods=["GET"])
def search_articles(fakeid):
    """在所选公众号全部历史中按标题、发布时间或二者组合搜索。"""

    keyword = " ".join(request.args.get("keyword", "").split())
    start_time = max(0, request.args.get("start_time", 0, type=int))
    end_time = max(0, request.args.get("end_time", 0, type=int))
    if bool(start_time) != bool(end_time):
        return jsonify({"error": "请选择完整的开始和结束日期"}), 400
    if start_time and start_time > end_time:
        return jsonify({"error": "开始日期不能晚于结束日期"}), 400
    if not keyword and not start_time:
        return jsonify({"error": "请输入搜索关键词或选择时间范围"}), 400
    begin = max(0, request.args.get("begin", 0, type=int))
    count = min(max(1, request.args.get("count", 20, type=int)), 100)
    account_name = request.args.get("account_name", "").strip()
    refresh = request.args.get("refresh", "") == "1"
    cache_key = (fakeid, keyword.casefold(), account_name, start_time, end_time)
    now = time.time()

    with _article_search_lock:
        cached = _article_search_cache.get(cache_key)
        if cached and now - cached["cached_at"] > _ARTICLE_SEARCH_CACHE_TTL:
            _article_search_cache.pop(cache_key, None)
            cached = None
        if refresh:
            _article_search_cache.pop(cache_key, None)
            cached = None

    try:
        if cached is None:
            result = _search_all_article_pages(
                fakeid,
                keyword,
                account_name,
                start_time,
                end_time,
            )
            cached = {**result, "cached_at": now}
            with _article_search_lock:
                if len(_article_search_cache) >= _ARTICLE_SEARCH_CACHE_LIMIT:
                    oldest_key = min(
                        _article_search_cache,
                        key=lambda key: _article_search_cache[key]["cached_at"],
                    )
                    _article_search_cache.pop(oldest_key, None)
                _article_search_cache[cache_key] = cached

        matches = list(cached["articles"])
        page = matches[begin : begin + count]
        _apply_article_download_states(page, account_name)
        return jsonify(
            {
                "articles": page,
                "total": len(matches),
                "can_msg_continue": 1 if begin + count < len(matches) else 0,
                "begin": begin,
                "count": len(page),
                "search_scope": "all_pages",
                "search_keyword": keyword,
                "start_time": start_time,
                "end_time": end_time,
                "scanned": cached["scanned"],
                "scan_complete": cached["complete"],
                "stop_reason": cached["stop_reason"],
                "cached": cached["cached_at"] != now,
                "total_exact": bool(cached["complete"]),
                "total_pages_exact": bool(cached["complete"]),
                "total_pages": (
                    (len(matches) + count - 1) // count if cached["complete"] and count else None
                ),
                "minimum_total_pages": (
                    (begin // count) + (2 if begin + count < len(matches) else 1)
                ),
            }
        )
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 401
    except Exception as exc:
        logger.exception("公众号全局文章搜索失败: fakeid=%s", fakeid)
        return jsonify({"error": f"全局搜索失败: {exc}"}), 500


@articles_bp.route("/list-via-appmsg/<fakeid>", methods=["GET"])
def get_articles_appmsg(fakeid):
    """向后兼容接口：获取指定公众号文章列表"""
    return get_articles(fakeid)


def _parse_publish_response(data: dict) -> tuple:
    """解析 appmsgpublish 返回的数据"""
    publish_page_str = data.get("publish_page", "")
    if not publish_page_str:
        return [], 0

    publish_page = json.loads(publish_page_str)
    publish_list = publish_page.get("publish_list", [])
    total_count = publish_page.get("total_count", 0)

    articles = []
    for item in publish_list:
        publish_info_str = item.get("publish_info", "")
        if not publish_info_str:
            continue
        publish_info = json.loads(publish_info_str)
        appmsgex = publish_info.get("appmsgex", [])
        for a in appmsgex:
            articles.append({
                "title": a.get("title", ""),
                "link": a.get("link", ""),
                "cover": a.get("cover", ""),
                "digest": a.get("digest", ""),
                "author": a.get("author", ""),
                "update_time": a.get("update_time", a.get("create_time", 0)),
                "is_original": a.get("copyright_type", "0") != "0",
                "item_show_type": a.get("item_show_type", 0),
            })

    return articles, total_count


@articles_bp.route("/download", methods=["POST"])
def start_download():
    """批量下载文章"""
    data = request.get_json() or {}
    articles = data.get("articles", [])
    account_name = data.get("account_name", "unknown")
    include_pdf = bool(data.get("include_pdf", False))

    if not articles:
        return jsonify({"error": "没有选择要下载的文章"}), 400

    task_id = f"batch_{int(time.time())}"

    with _download_lock:
        _download_tasks[task_id] = {
            "status": "running",
            "total": len(articles),
            "completed": 0,
            "failed": 0,
            "current": "",
            "results": [],
            "start_time": time.time(),
            "include_pdf": include_pdf,
        }

    thread = threading.Thread(
        target=_do_batch_download,
        args=(task_id, articles, account_name, include_pdf),
        daemon=True,
    )
    thread.start()

    return jsonify({"task_id": task_id, "message": f"已启动下载任务，共 {len(articles)} 篇"})


@articles_bp.route("/download-range", methods=["POST"])
def start_range_download():
    """按时间范围分页拉取文章并逐篇下载。"""
    data = request.get_json() or {}
    fakeid = data.get("fakeid", "")
    account_name = data.get("account_name", "unknown")
    start_time = data.get("start_time", 0)
    end_time = data.get("end_time", 0)
    keyword = data.get("keyword", "").strip()
    page_size = int(data.get("page_size", 10) or 10)
    include_pdf = bool(data.get("include_pdf", False))

    if not fakeid:
        return jsonify({"error": "缺少公众号 fakeid"}), 400
    if not start_time or not end_time:
        return jsonify({"error": "请选择完整的开始和结束日期"}), 400
    if start_time > end_time:
        return jsonify({"error": "开始日期不能晚于结束日期"}), 400

    task_id = f"range_{int(time.time())}"
    with _download_lock:
        _download_tasks[task_id] = {
            "status": "running",
            "mode": "range",
            "total": 0,
            "completed": 0,
            "failed": 0,
            "scanned": 0,
            "current": "",
            "results": [],
            "start_time": time.time(),
            "cancel_requested": False,
            "stop_reason": "",
            "include_pdf": include_pdf,
        }

    thread = threading.Thread(
        target=_do_range_download,
        args=(task_id, fakeid, account_name, start_time, end_time, keyword, page_size, include_pdf),
        daemon=True,
    )
    thread.start()

    return jsonify({"task_id": task_id, "message": "已启动按时间范围下载任务"})


@articles_bp.route("/download-cancel/<task_id>", methods=["POST"])
def cancel_download(task_id):
    """请求停止下载任务。"""
    with _download_lock:
        task = _download_tasks.get(task_id)
        if not task:
            return jsonify({"error": "任务不存在"}), 404
        if task["status"] not in ("running",):
            return jsonify({"message": "任务已结束"})
        task["cancel_requested"] = True
        task["status"] = "cancelling"
        task["stop_reason"] = "用户请求停止"
    return jsonify({"message": "正在停止下载任务"})


@articles_bp.route("/download-url", methods=["POST"])
def download_by_url():
    """通过 URL 下载单篇/多篇文章 (带智能正则提取与批量标准短链转换)"""
    data = request.get_json() or {}
    include_pdf = bool(data.get("include_pdf", False))
    raw_urls = data.get("urls", [])
    if isinstance(raw_urls, str):
        raw_urls = [u.strip() for u in raw_urls.split("\n") if u.strip()]

    if not raw_urls:
        return jsonify({"error": "请输入文章 URL"}), 400

    import re
    extracted_urls = []
    for item in raw_urls:
        if not item or not isinstance(item, str):
            continue
        # 兼容用户直接粘贴带有前后缀文本、标题或标点符号的微信推文链接
        found = re.findall(r'https?://(?:mp\.weixin\.qq\.com/s[^\s\'"<>]+|mp\.weixin\.qq\.com/[^\s\'"<>]+)', item)
        if found:
            for u in found:
                u = re.sub(r'[\)\]\>，。]+$', '', u)
                if u not in extracted_urls:
                    extracted_urls.append(u)
        elif item.startswith("http://") or item.startswith("https://"):
            u = item.strip()
            if u not in extracted_urls:
                extracted_urls.append(u)

    if not extracted_urls:
        return jsonify({"error": "未检测到有效的微信公众号文章链接"}), 400

    extracted_urls = list(dict.fromkeys(normalize_wechat_short_url(u) for u in extracted_urls))

    # 批量将长链接预解析为免风控的标准短链与 reviewId
    url_info_map = {}
    long_urls_to_resolve = [u for u in extracted_urls if "__biz=" in u]
    if long_urls_to_resolve:
        try:
            from backend.account_pool import borrow_weread_session, get_weread_session
            acc_id, vid, tok, h = borrow_weread_session()
            s = get_weread_session()
            res = s.post("https://i.weread.qq.com/mp/getreviewid", json={"urls": long_urls_to_resolve}, headers=h, timeout=8).json()
            for r_item in res.get("reviewIds", []):
                orig_u = r_item.get("url", "")
                rid = r_item.get("reviewId", "")
                short_url = wechat_short_url_from_review_id(rid)
                if short_url:
                    url_info_map[orig_u] = {
                        "short_url": short_url,
                        "review_id": rid,
                    }
        except Exception as e:
            logger.debug(f"[download_by_url] 批量预解析短链异常: {e}")

    articles = []
    for i, raw_u in enumerate(extracted_urls):
        mapped = url_info_map.get(raw_u, {})
        short_u = mapped.get("short_url")
        rid = mapped.get("review_id", "")
        if not rid and "/s/" in raw_u and "__biz=" not in raw_u:
            sid_match = re.search(r'/s/([A-Za-z0-9_-]{15,})', raw_u)
            if sid_match:
                rid = f"MP_WXS_0_{sid_match.group(1)}"

        articles.append({
            "title": f"article_{i+1}",
            "link": short_u or raw_u,
            "id": rid,
            "aid": rid,
            "original_url": raw_u,
        })

    task_id = f"url_{int(time.time())}"

    with _download_lock:
        _download_tasks[task_id] = {
            "status": "running",
            "total": len(articles),
            "completed": 0,
            "failed": 0,
            "current": "",
            "results": [],
            "start_time": time.time(),
            "cancel_requested": False,
            "stop_reason": "",
            "include_pdf": include_pdf,
        }

    thread = threading.Thread(
        target=_do_batch_download,
        args=(task_id, articles, "url_download", include_pdf),
        daemon=True,
    )
    thread.start()

    return jsonify({"task_id": task_id, "message": f"已启动下载任务，共 {len(articles)} 篇"})


@articles_bp.route("/download-progress/<task_id>", methods=["GET"])
def get_download_progress(task_id):
    """获取下载进度（SSE）"""
    def generate():
        while True:
            with _download_lock:
                task = _download_tasks.get(task_id)

            if not task:
                yield f"data: {json.dumps({'error': '任务不存在'})}\n\n"
                break

            yield f"data: {json.dumps(task, ensure_ascii=False)}\n\n"

            if task["status"] in ("completed", "failed"):
                break

            time.sleep(0.5)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@articles_bp.route("/download-status/<task_id>", methods=["GET"])
def get_download_status(task_id):
    """获取下载任务状态（普通 HTTP）"""
    with _download_lock:
        task = _download_tasks.get(task_id)
    if not task:
        return jsonify({"error": "任务不存在"}), 404
    return jsonify(task)


def _sync_history_from_disk(history: list) -> bool:
    """自动扫描本地下载文件夹，同步历史记录中缺失的条目，并自动清理残存的无正文空目录"""
    settings = get_settings()
    download_dir = Path(settings.get("download_dir") or str(OUTPUT_DIR))
    
    scan_dirs = []
    if download_dir.exists():
        scan_dirs.append(download_dir)
    if OUTPUT_DIR.resolve() != download_dir.resolve() and OUTPUT_DIR.exists():
        scan_dirs.append(OUTPUT_DIR)

    if not scan_dirs:
        return False

    existing_paths = {item.get("path") for item in history if isinstance(item, dict) and item.get("path")}
    changed = False

    try:
        for sdir in scan_dirs:
            for account_dir in sdir.iterdir():
                if not account_dir.is_dir() or account_dir.name in ("channels", "douyin_downloads", "xhs_downloads", "temp_uploads"):
                    continue

                for art_dir in account_dir.iterdir():
                    if not art_dir.is_dir():
                        continue

                    # 新成果以 Markdown 为主；HTML 仅兼容历史成果，PDF 不能单独代表正文。
                    markdown_files = list(art_dir.glob("*.md"))
                    legacy_html_files = [
                        f
                        for f in art_dir.glob("*.html")
                        if not f.name.endswith("_raw.html") and ".pdf-source." not in f.name
                    ]
                    if not markdown_files and not legacy_html_files:
                        # 检查是否为失败下载遗留的空目录（仅有空 media 目录等），如果是则安全清理
                        try:
                            has_files = any(f.is_file() for f in art_dir.rglob("*"))
                            if not has_files:
                                shutil.rmtree(art_dir, ignore_errors=True)
                        except Exception:
                            pass
                        continue

                    art_path_str = str(art_dir)
                    if art_path_str in existing_paths:
                        continue

                    meta_file = art_dir / "metadata.json"
                    meta = {}
                    if meta_file.exists():
                        try:
                            meta = json.loads(meta_file.read_text(encoding="utf-8"))
                        except Exception:
                            meta = {}

                    try:
                        link = meta.get("url", "")
                        mtime = art_dir.stat().st_mtime
                        time_val = mtime
                        if meta.get("time"):
                            try:
                                # 尝试解析 2026-06-17T08:12:44 等标准 ISO 格式时间
                                time_val = datetime.fromisoformat(meta["time"]).timestamp()
                            except Exception:
                                pass

                        has_md = meta.get("has_markdown") if "has_markdown" in meta else bool(markdown_files)
                        has_pdf = meta.get("has_pdf") if "has_pdf" in meta else (any(art_dir.glob("*.pdf")))
                        new_item = {
                            "title": meta.get("title") or art_dir.name,
                            "link": link,
                            "account": account_dir.name,
                            "success": True,
                            "time": time_val,
                            "error": None,
                            "path": art_path_str,
                            "cover_url": meta.get("cover_url", ""),
                            "digest": meta.get("digest", ""),
                            "publish_time": meta.get("publish_time") or int(time_val),
                            "has_markdown": has_md,
                            "has_pdf": has_pdf,
                        }
                        history.append(new_item)
                        existing_paths.add(art_path_str)
                        changed = True
                    except Exception:
                        pass
    except Exception:
        pass

    return changed


def _resolve_history_path(raw_path: str, download_dir: str) -> str:
    """把历史记录里的路径重定位到当前下载目录。

    迁移场景：桌面版记的是 /Users/xxx/.../articles_full/公众号/文章，
    容器里这份路径不存在。这里按 articles_full 之后的部分拼到当前
    download_dir 下，只有目标确实存在才替换，避免误伤。
    """
    if not raw_path:
        return raw_path
    try:
        if Path(raw_path).exists():
            return raw_path
    except OSError:
        pass

    parts = Path(raw_path).parts
    if "articles_full" in parts:
        idx = len(parts) - 1 - parts[::-1].index("articles_full")
        candidate = Path(download_dir).joinpath(*parts[idx + 1:])
        try:
            if candidate.exists():
                return str(candidate)
        except OSError:
            pass
    return raw_path


@articles_bp.route("/history", methods=["GET"])
def get_history():
    """获取下载历史"""
    history = load_json(DOWNLOAD_HISTORY_FILE, [])
    
    # 自动从磁盘同步丢失的历史记录
    if _sync_history_from_disk(history):
        save_json(DOWNLOAD_HISTORY_FILE, history)

    download_dir = get_settings().get("download_dir") or str(OUTPUT_DIR)

    indexed_history = []
    for index, item in enumerate(history):
        if isinstance(item, dict):
            if item.get("account") == "微信视频号":
                continue
            indexed = dict(item)
            if not indexed.get("account") and indexed.get("account_name"):
                indexed["account"] = indexed["account_name"]
            indexed["_index"] = index
            if indexed.get("path"):
                # 旧机器的绝对路径重定位到当前下载目录；界面上再显示宿主机路径
                indexed["path"] = _resolve_history_path(indexed["path"], download_dir)
                indexed["display_path"] = host_path_hint(indexed["path"])
                try:
                    artifact_path = Path(indexed["path"])
                    if artifact_path.is_dir():
                        indexed["has_markdown"] = any(artifact_path.glob("*.md"))
                        indexed["has_pdf"] = any(artifact_path.glob("*.pdf"))
                except OSError:
                    pass
            indexed["download_state"] = indexed.get("download_state") or (
                "downloaded" if indexed.get("success") else "failed"
            )
            if indexed["download_state"] == "failed":
                indexed["failure_stage"] = indexed.get("failure_stage") or "download"
            indexed_history.append(indexed)
    indexed_history.sort(key=lambda x: x.get("time", 0), reverse=True)
    # 限制返回数量
    limit = request.args.get("limit", 50, type=int)
    sliced_history = indexed_history if limit <= 0 else indexed_history[:limit]
    return jsonify({"history": sliced_history, "total": len(indexed_history)})


@articles_bp.route("/history", methods=["DELETE"])
def clear_history():
    """清空下载历史，并删除对应的本地下载文件/目录"""
    history = load_json(DOWNLOAD_HISTORY_FILE, [])
    deleted_dirs_count = 0
    remaining_history = []

    for item in history:
        if not isinstance(item, dict):
            continue

        # 保留微信视频号的历史记录不作处理（视频号有自己的 channels.py 清空接口）
        if item.get("account") == "微信视频号":
            remaining_history.append(item)
            continue

        path_str = item.get("path", "")
        if path_str:
            try:
                path = Path(path_str)
                if path.exists():
                    if path.is_dir():
                        shutil.rmtree(path)
                    else:
                        path.unlink()
                    deleted_dirs_count += 1
            except Exception:
                pass

    save_json(DOWNLOAD_HISTORY_FILE, remaining_history)

    # 自动清理空出来的公众号目录
    try:
        settings = get_settings()
        download_dir = Path(settings.get("download_dir") or str(OUTPUT_DIR))
        if download_dir.exists():
            for account_dir in download_dir.iterdir():
                if account_dir.is_dir() and account_dir.name not in ("channels", "douyin_downloads", "xhs_downloads", "temp_uploads"):
                    # 如果该公众号目录没有任何文件/文件夹，则将其删除
                    if not any(account_dir.iterdir()):
                        account_dir.rmdir()
    except Exception:
        pass

    return jsonify({
        "message": f"历史已清空，成功删除 {deleted_dirs_count} 个本地下载内容。"
    })


@articles_bp.route("/history/<int:index>", methods=["DELETE"])
def delete_history_item(index):
    """删除单条下载历史，并删除对应下载文件夹。"""
    history = load_json(DOWNLOAD_HISTORY_FILE, [])
    if index < 0 or index >= len(history):
        return jsonify({"error": "历史记录不存在"}), 404

    item = history[index]
    path_str = item.get("path", "") if isinstance(item, dict) else ""
    file_status = "no_path"
    if path_str:
        try:
            path = Path(path_str)
            if path.exists():
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                file_status = "deleted"
            else:
                file_status = "missing"
        except Exception as e:
            # 文件被占用或删除失败时不阻塞历史记录本身的删除
            file_status = f"error: {str(e)}"

    history.pop(index)
    save_json(DOWNLOAD_HISTORY_FILE, history)

    messages = {
        "deleted": "已删除下载文件和记录",
        "missing": "下载文件已不存在，已删除记录",
        "no_path": "记录没有文件路径，已删除记录",
    }
    msg = messages.get(file_status, f"下载文件清理失败（{file_status}），但已清除历史记录")
    return jsonify({"message": msg, "file_status": file_status})


def _do_batch_download(task_id: str, articles: list, account_name: str, include_pdf: bool = False):
    """执行批量下载（后台线程）"""
    from backend.downloader import download_single_article

    settings = get_settings()
    delay = settings.get("request_delay", 0.8)
    max_retries = settings.get("max_retries", 3)

    download_dir = Path(settings.get("download_dir") or str(OUTPUT_DIR))
    out_dir = download_dir / account_name
    out_dir.mkdir(parents=True, exist_ok=True)

    history = load_json(DOWNLOAD_HISTORY_FILE, [])

    try:
        for i, article in enumerate(articles):
            with _download_lock:
                task = _download_tasks.get(task_id, {})
                if task.get("cancel_requested") or task.get("status") == "cancelling":
                    task["status"] = "cancelled"
                    task["current"] = ""
                    task["end_time"] = time.time()
                    task["stop_reason"] = task.get("stop_reason") or "用户请求停止"
                    save_json(DOWNLOAD_HISTORY_FILE, history)
                    return

            link = normalize_wechat_short_url(article.get("link", ""))
            title = article.get("title", f"article_{i+1}")

            with _download_lock:
                _download_tasks[task_id]["current"] = f"正在下载第 {i+1} 篇..."

            if not link:
                with _download_lock:
                    _download_tasks[task_id]["failed"] += 1
                    _download_tasks[task_id]["results"].append({
                        "title": title, "success": False, "error": "无链接"
                    })
                continue

            success = False
            error_msg = ""
            result = {}
            review_id = article.get("id") or article.get("aid") or ""

            for attempt in range(1, max_retries + 1):
                try:
                    result = download_single_article(
                        link,
                        out_dir,
                        title,
                        review_id=review_id,
                        include_pdf=include_pdf,
                    )
                    if result.get("success"):
                        success = True
                        break
                    error_msg = result.get("error", "未知错误")
                except Exception as e:
                    error_msg = str(e)
                if attempt < max_retries:
                    # 指数退避 + 抖动，避免失败后齐步重试形成尖峰
                    sleep_backoff(attempt, base=1.0, cap=8.0)

            if result.get("title"):
                title = result["title"]

            downloaded_path = result.get("path") if success else None

            with _download_lock:
                if success:
                    _download_tasks[task_id]["completed"] += 1
                    _download_tasks[task_id]["current"] = f"已完成：{title}"
                    _download_tasks[task_id]["results"].append({
                        "title": title, "success": True, "path": downloaded_path or str(out_dir / title)
                    })
                else:
                    _download_tasks[task_id]["failed"] += 1
                    _download_tasks[task_id]["current"] = f"下载失败：{title}"
                    _download_tasks[task_id]["results"].append({
                        "title": title, "success": False, "error": error_msg
                    })

            real_account = result.get("source")
            if not real_account or real_account == "url_download":
                real_account = account_name if account_name != "url_download" else "链接下载"
            # 记录到下载历史
            history.append({
                "title": title,
                "link": normalize_wechat_short_url(article.get("original_url") or link),
                "account": real_account,
                "author": result.get("author", ""),
                "success": success,
                "time": time.time(),
                "error": error_msg if not success else None,
                "path": downloaded_path,
                "cover_url": result.get("cover_url", ""),
                "digest": result.get("digest", ""),
                "publish_time": result.get("publish_time", int(time.time())),
                "has_markdown": result.get("has_markdown", False),
                "has_pdf": result.get("has_pdf", False),
                "download_state": "downloaded" if success else "failed",
                "failure_stage": None if success else "download",
            })

            if i < len(articles) - 1:
                # 对数正态节流：均值与原实现 max(1.0, delay)+U(0.3,1.2) 的期望（约 1.75s）对齐，
                # 只是把原本 1.3~2.2s 的窄带换成带长尾的分布；min_delay 抬住下沿，
                # 保证没有任何一次间隔比原来的 1.3s 更密
                sleep_throttled(max(1.0, delay) + 0.75, min_delay=1.3)

        # 保存历史
        save_json(DOWNLOAD_HISTORY_FILE, history)

        with _download_lock:
            task = _download_tasks[task_id]
            if task.get("status") == "cancelling":
                task["status"] = "cancelled"
                task["stop_reason"] = task.get("stop_reason") or "用户请求停止"
            else:
                task["status"] = "completed"
            task["current"] = ""
            task["end_time"] = time.time()
    except Exception as e:
        print(f"[_do_batch_download] 异常: {e}", flush=True)
        save_json(DOWNLOAD_HISTORY_FILE, history)
        with _download_lock:
            task = _download_tasks.get(task_id, {})
            task["status"] = "failed"
            task["current"] = ""
            task["stop_reason"] = str(e)
            task["end_time"] = time.time()


def _download_article_into_task(
    task_id: str,
    article: dict,
    account_name: str,
    history: list,
    index: int = 0,
    include_pdf: bool = False,
):
    """Download one article and update task progress."""
    from backend.downloader import download_single_article

    settings = get_settings()
    max_retries = settings.get("max_retries", 3)
    download_dir = Path(settings.get("download_dir") or str(OUTPUT_DIR))
    out_dir = download_dir / account_name
    out_dir.mkdir(parents=True, exist_ok=True)

    link = normalize_wechat_short_url(article.get("link", ""))
    title = article.get("title", f"article_{index + 1}")
    review_id = article.get("id") or article.get("aid") or ""

    with _download_lock:
        _download_tasks[task_id]["current"] = title

    if not link:
        with _download_lock:
            _download_tasks[task_id]["failed"] += 1
            _download_tasks[task_id]["results"].append({
                "title": title, "success": False, "error": "无链接"
            })
        return

    success = False
    error_msg = ""
    result = {}
    for attempt in range(1, max_retries + 1):
        try:
            result = download_single_article(
                link,
                out_dir,
                title,
                review_id=review_id,
                include_pdf=include_pdf,
            )
            if result.get("success"):
                success = True
                break
            error_msg = result.get("error", "未知错误")
        except Exception as e:
            error_msg = str(e)
        if attempt < max_retries:
            # 指数退避 + 抖动，避免失败后齐步重试形成尖峰
            sleep_backoff(attempt, base=1.0, cap=8.0)

    if result.get("title"):
        title = result["title"]
    downloaded_path = result.get("path") if success else None

    with _download_lock:
        if success:
            _download_tasks[task_id]["completed"] += 1
            _download_tasks[task_id]["results"].append({
                "title": title, "success": True, "path": downloaded_path or str(out_dir / title)
            })
        else:
            _download_tasks[task_id]["failed"] += 1
            _download_tasks[task_id]["results"].append({
                "title": title, "success": False, "error": error_msg
            })

    history.append({
        "title": title,
        "link": link,
        "account": account_name,
        "success": success,
        "time": time.time(),
        "error": error_msg if not success else None,
        "path": downloaded_path,
        "cover_url": result.get("cover_url", ""),
        "digest": result.get("digest", ""),
        "publish_time": result.get("publish_time", int(time.time())),
        "has_markdown": result.get("has_markdown", False),
        "has_pdf": result.get("has_pdf", False),
        "download_state": "downloaded" if success else "failed",
        "failure_stage": None if success else "download",
    })


def _do_range_download(
    task_id: str,
    fakeid: str,
    account_name: str,
    start_time: int,
    end_time: int,
    keyword: str,
    page_size: int,
    include_pdf: bool = False,
):
    """分页拉取文章，下载时间范围内文章，遇到更早文章后停止。"""
    settings = get_settings()
    delay = settings.get("request_delay", 0.8)
    history = load_json(DOWNLOAD_HISTORY_FILE, [])
    begin = 0
    downloaded_index = 0
    stop = False

    try:
        while not stop:
            with _download_lock:
                task = _download_tasks.get(task_id, {})
                if task.get("cancel_requested") or task.get("status") == "cancelling":
                    task["status"] = "cancelled"
                    task["current"] = ""
                    task["end_time"] = time.time()
                    task["stop_reason"] = task.get("stop_reason") or "用户请求停止"
                    save_json(DOWNLOAD_HISTORY_FILE, history)
                    return
                task["current"] = f"正在获取第 {begin // page_size + 1} 页"

            res = _fetch_articles_page(fakeid, begin, page_size, keyword, account_name=account_name)
            articles, can_continue = res[0], bool(res[2])
            if not articles:
                if can_continue:
                    begin += page_size
                    continue
                stop = True
                with _download_lock:
                    _download_tasks[task_id]["stop_reason"] = "没有更多文章"
                break

            with _download_lock:
                _download_tasks[task_id]["scanned"] += len(articles)

            out_of_range_count = 0
            for article in articles:
                article_time = article.get("update_time") or 0
                # update_time 为 0 表示时间未知，不做时间过滤（宁多勿漏）
                if article_time > 0:
                    if article_time > end_time:
                        continue
                    if article_time < start_time:
                        out_of_range_count += 1
                        continue

                with _download_lock:
                    task = _download_tasks.get(task_id, {})
                    if task.get("cancel_requested") or task.get("status") == "cancelling":
                        task["status"] = "cancelled"
                        task["current"] = ""
                        task["end_time"] = time.time()
                        task["stop_reason"] = task.get("stop_reason") or "用户请求停止"
                        save_json(DOWNLOAD_HISTORY_FILE, history)
                        return
                    task["total"] += 1

                _download_article_into_task(
                    task_id,
                    article,
                    account_name,
                    history,
                    downloaded_index,
                    include_pdf,
                )
                downloaded_index += 1
                # 对数正态节流：均值与原实现 max(1.0, delay)+U(0.3,1.2) 的期望（约 1.75s）对齐，
                # 只是把原本 1.3~2.2s 的窄带换成带长尾的分布；min_delay 抬住下沿，
                # 保证没有任何一次间隔比原来的 1.3s 更密
                sleep_throttled(max(1.0, delay) + 0.75, min_delay=1.3)

            # 当前页所有文章都早于 start_time，说明后续页也不会有范围内的文章了
            if out_of_range_count > 0 and out_of_range_count >= len(articles):
                stop = True
                with _download_lock:
                    _download_tasks[task_id]["stop_reason"] = "已到达所选时间范围之前的文章"

            if not can_continue:
                with _download_lock:
                    _download_tasks[task_id]["stop_reason"] = "已扫描全部文章"
                break
            begin += page_size

        save_json(DOWNLOAD_HISTORY_FILE, history)
        with _download_lock:
            task = _download_tasks[task_id]
            if task["status"] not in ("cancelled",):
                task["status"] = "completed"
            task["current"] = ""
            task["end_time"] = time.time()

    except PermissionError as e:
        save_json(DOWNLOAD_HISTORY_FILE, history)
        with _download_lock:
            task = _download_tasks[task_id]
            task["status"] = "failed"
            task["current"] = ""
            task["stop_reason"] = str(e)
            task["end_time"] = time.time()
    except Exception as e:
        save_json(DOWNLOAD_HISTORY_FILE, history)
        with _download_lock:
            task = _download_tasks[task_id]
            task["status"] = "failed"
            task["current"] = ""
            task["stop_reason"] = str(e)
            task["end_time"] = time.time()


@articles_bp.route("/open-folder", methods=["POST"])
def open_folder():
    """在系统文件管理器中打开微信下载目录"""
    import subprocess
    import sys
    
    data = request.get_json() or {}
    account = data.get("account", "").strip()
    
    settings = get_settings()
    download_dir_str = settings.get("download_dir") or str(OUTPUT_DIR)
    path = Path(download_dir_str)
    
    if account:
        path = path / account
    
    try:
        path.mkdir(parents=True, exist_ok=True)
        resolved_path = str(path.resolve())

        # 容器部署没有桌面环境，调 xdg-open 只会抛 FileNotFoundError
        if not desktop_available():
            hint = host_path_hint(resolved_path)
            return jsonify({
                "error": f"容器部署没有桌面环境，请在宿主机打开：{hint}",
                "mode": "headless",
                "container_path": resolved_path,
                "host_path": hint,
            }), 501

        if sys.platform == "darwin":
            subprocess.run(["open", resolved_path])
        elif sys.platform == "win32":
            if hasattr(os, "startfile"):
                os.startfile(resolved_path)
            else:
                subprocess.run(["explorer", resolved_path])
        else:
            subprocess.run(["xdg-open", resolved_path])
        return jsonify({"message": "文件夹已打开"})
    except Exception as e:
        return jsonify({"error": f"打开文件夹失败: {str(e)}"}), 500


@articles_bp.route("/open-file", methods=["POST"])
def open_file():
    """在系统默认程序中打开特定的文件或文件夹，支持按类型定位 pdf/md"""
    import subprocess
    import sys

    data = request.get_json() or {}
    path_str = data.get("path", "")
    target_type = (data.get("type", "") or "").lower().strip()
    if not path_str:
        return jsonify({"error": "路径不能为空"}), 400

    try:
        path = Path(path_str)
        if not path.exists():
            return jsonify({"error": "文件或文件夹不存在"}), 404

        resolved_target = path
        if path.is_dir() and target_type:
            if target_type == "pdf":
                pdfs = list(path.glob("*.pdf"))
                if pdfs:
                    resolved_target = pdfs[0]
                else:
                    return jsonify({"error": "未找到 PDF 文件"}), 404
            elif target_type in ("md", "markdown"):
                mds = list(path.glob("*.md"))
                if mds:
                    resolved_target = mds[0]
                else:
                    return jsonify({"error": "未找到 Markdown 文件"}), 404

        resolved_path = str(resolved_target.resolve())

        # 容器部署：把「用系统程序打开」换成「浏览器直接访问」，前端会打开返回的 url
        if not desktop_available():
            url = "/api/articles/serve-file?path=" + urllib.parse.quote(resolved_path, safe="")
            return jsonify({
                "message": "已在浏览器中打开",
                "mode": "headless",
                "url": url,
                "container_path": resolved_path,
                "host_path": host_path_hint(resolved_path),
            })

        if sys.platform == "darwin":
            subprocess.run(["open", resolved_path])
        elif sys.platform == "win32":
            if hasattr(os, "startfile"):
                os.startfile(resolved_path)
            else:
                subprocess.run(["explorer", resolved_path])
        else:
            subprocess.run(["xdg-open", resolved_path])
        return jsonify({"message": "已打开"})
    except Exception as e:
        return jsonify({"error": f"打开失败: {str(e)}"}), 500


@articles_bp.route("/open-parent", methods=["POST"])
def open_parent():
    """打开文件所在的父目录并选中当前文件"""
    import subprocess
    import sys

    data = request.get_json() or {}
    path_str = data.get("path", "")
    if not path_str:
        return jsonify({"error": "路径不能为空"}), 400

    try:
        path = Path(path_str)
        if not path.exists():
            return jsonify({"error": "文件或文件夹不存在"}), 404
            
        resolved_path = str(path.resolve())

        if not desktop_available():
            target_dir = path.parent.resolve() if path.is_file() else path.resolve()
            hint = host_path_hint(str(target_dir))
            return jsonify({
                "error": f"容器部署没有桌面环境，请在宿主机打开：{hint}",
                "mode": "headless",
                "host_path": hint,
            }), 501

        if path.is_file():
            if sys.platform == "darwin":
                subprocess.run(["open", "-R", resolved_path])
            elif sys.platform == "win32":
                subprocess.run(f'explorer /select,"{resolved_path}"', shell=True)
            else:
                subprocess.run(["xdg-open", str(path.parent.resolve())])
        else:
            if sys.platform == "darwin":
                subprocess.run(["open", resolved_path])
            elif sys.platform == "win32":
                if hasattr(os, "startfile"):
                    os.startfile(resolved_path)
                else:
                    subprocess.run(["explorer", resolved_path])
            else:
                subprocess.run(["xdg-open", resolved_path])
        return jsonify({"message": "已打开"})
    except Exception as e:
        return jsonify({"error": f"打开失败: {str(e)}"}), 500


@articles_bp.route("/content-filter", methods=["GET"])
def get_content_filter():
    """获取内容过滤规则（屏蔽广告、二维码、小节标题横幅图等）"""
    from backend.content_filter import DEFAULT_RULES, last_stats, load_rules

    return jsonify({
        "rules": load_rules(),
        "defaults": DEFAULT_RULES,
        "last_stats": last_stats(),
    })


@articles_bp.route("/content-filter", methods=["POST"])
def save_content_filter():
    """保存内容过滤规则，新下载的文章立即生效"""
    from backend.content_filter import save_rules

    data = request.get_json() or {}
    rules = data.get("rules") if isinstance(data.get("rules"), dict) else data
    return jsonify({"rules": save_rules(rules), "message": "规则已保存"})


@articles_bp.route("/content-filter/apply-existing", methods=["POST"])
def apply_content_filter_existing():
    """仅对历史 HTML 下载重跑过滤。

    默认 dry_run=true 只统计不改文件；确认后传 {"dry_run": false} 才真正改写，
    新的 Markdown-only 成果不参与；改写前会把原 .html 备份成 .html.bak。
    """
    from backend.content_filter import refilter_existing

    data = request.get_json() or {}
    settings = get_settings()
    download_dir = settings.get("download_dir") or str(OUTPUT_DIR)
    result = refilter_existing(
        download_dir,
        dry_run=bool(data.get("dry_run", True)),
        force=bool(data.get("force", False)),
    )
    return jsonify(result)


@articles_bp.route("/serve-file", methods=["GET"])
@articles_bp.route("/serve-file/<path:filepath>", methods=["GET"])
def serve_file(filepath=""):
    """
    Serve a file from the configured download directory or OUTPUT_DIR.
    Supports ?path=<abs_or_rel_path> or /serve-file/<path:filepath>.
    Auto-detects Markdown first, with legacy HTML fallback for historical downloads.
    """
    from flask import send_from_directory, Response
    from urllib.parse import unquote
    settings = get_settings()
    download_dir = Path(settings.get("download_dir") or str(OUTPUT_DIR)).resolve()
    default_out_dir = OUTPUT_DIR.resolve()
    data_dir = DATA_DIR.resolve()

    allowed_roots = [download_dir, default_out_dir]
    safe_extensions = {
        ".html", ".htm", ".md", ".pdf",
        ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg",
        ".mp4", ".mp3", ".wav", ".m4a",
        ".css", ".js",
    }

    query_path = request.args.get("path", "").strip()
    raw_path_str = query_path or filepath
    if not raw_path_str:
        return "File not found", 404

    decoded_path_str = unquote(raw_path_str)

    def is_safe_path(p: Path) -> bool:
        p_res = str(p.resolve())
        return any(Path(p_res).is_relative_to(root) for root in allowed_roots)

    def find_preview_in_dir(d: Path) -> Path | None:
        if not d.exists() or not d.is_dir():
            return None
        markdown_files = list(d.glob("*.md"))
        if markdown_files:
            for candidate in markdown_files:
                if candidate.stem == d.name:
                    return candidate
            return markdown_files[0]
        candidates = [f for f in d.glob("*.html") if not f.name.endswith("_raw.html")]
        if candidates:
            for c in candidates:
                if c.stem == d.name:
                    return c
            return candidates[0]
        all_html = list(d.glob("*.html"))
        if all_html:
            return all_html[0]
        return None

    target_path = None

    # 1. 尝试直接作为绝对路径
    candidate_direct = Path(decoded_path_str)
    if candidate_direct.is_absolute() and candidate_direct.exists():
        if is_safe_path(candidate_direct):
            if candidate_direct.is_dir():
                target_path = find_preview_in_dir(candidate_direct)
            else:
                target_path = candidate_direct

    # 2. 尝试在 download_dir 或 default_out_dir 下查找
    if not target_path or not target_path.exists():
        for base_dir in [download_dir, default_out_dir]:
            cand = (base_dir / decoded_path_str).resolve()
            if is_safe_path(cand):
                if cand.is_file():
                    target_path = cand
                    break
                elif cand.is_dir():
                    found = find_preview_in_dir(cand)
                    if found:
                        target_path = found
                        break
                elif cand.parent.is_dir():
                    found = find_preview_in_dir(cand.parent)
                    if found:
                        target_path = found
                        break

    # 3. 尝试模糊跨账号查找（防止相对路径中缺少公众号目录）
    if not target_path or not target_path.exists():
        pure_name = Path(decoded_path_str).name
        if pure_name.endswith((".html", ".md")):
            pure_name = pure_name.rsplit(".", 1)[0]
        for base_dir in [download_dir, default_out_dir]:
            if base_dir.exists():
                for acc_dir in base_dir.iterdir():
                    if acc_dir.is_dir() and acc_dir.name not in ("channels", "douyin_downloads", "xhs_downloads", "temp_uploads"):
                        sub_cand = acc_dir / pure_name
                        if sub_cand.is_dir() and is_safe_path(sub_cand):
                            found = find_preview_in_dir(sub_cand)
                            if found:
                                target_path = found
                                break
            if target_path:
                break

    if not target_path or not target_path.exists():
        not_found_html = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", sans-serif; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 80vh; margin: 0; color: #555; text-align: center; }
        .icon { width: 56px; height: 56px; color: #f59e0b; margin-bottom: 16px; }
        h3 { color: #111; margin: 0 0 8px 0; font-size: 1.15rem; }
        p { margin: 0 0 16px 0; font-size: 0.9rem; max-width: 480px; line-height: 1.6; color: #666; }
    </style>
</head>
<body>
    <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="10"></circle>
        <line x1="12" y1="8" x2="12" y2="12"></line>
        <line x1="12" y1="16" x2="12.01" y2="16"></line>
    </svg>
    <h3>未找到本地文章正文文件 (File not found)</h3>
    <p>该文章本地内容可能因网络异常尚未下载完成、或已被清理。您可以点击右上角“原文链接”查看微信在线正文。</p>
</body>
</html>"""
        return Response(not_found_html, status=404, mimetype="text/html")

    if not is_safe_path(target_path) or target_path.suffix.lower() not in safe_extensions:
        return "Access denied", 403

    if target_path.suffix.lower() == ".md":
        from markdown_it import MarkdownIt

        markdown_text = target_path.read_text(encoding="utf-8")
        body = MarkdownIt("commonmark", {"html": False, "linkify": False}).render(markdown_text)
        document = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{{max-width:780px;margin:0 auto;padding:28px;font:16px/1.75 -apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;color:#222}}img,video{{max-width:100%;height:auto}}pre{{overflow:auto;background:#f6f8fa;padding:14px;border-radius:8px}}code{{background:#f6f8fa}}blockquote{{border-left:4px solid #07c160;margin:16px 0;padding:4px 16px;color:#555}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ddd;padding:8px}}</style></head><body>{body}</body></html>"""
        response = Response(document, mimetype="text/html")
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; img-src 'self' data: https:; media-src 'self' https:; "
            "style-src 'unsafe-inline'; font-src 'self'; base-uri 'none'; form-action 'none'"
        )
        return response

    return send_from_directory(target_path.parent, target_path.name)




@articles_bp.route("/avatars/<filename>", methods=["GET"])
def get_account_avatar_file(filename):
    from backend.avatar_cache import avatar_response

    return avatar_response(filename)


@articles_bp.route("/rss", methods=["GET"])
@articles_bp.route("/rss/<account>", methods=["GET"])
def get_rss(account=None):
    """RSS 2.0 订阅输出。

    具体实现见 backend/rss_feed.py：
      - 每次请求只读一次 rss_articles.json 并建索引（原实现按账号重复全量解析）
      - 按发布时间倒序，支持 ?limit= ?offset= 截断（默认 50，上限 500）
      - ?full=0 只输出摘要，不读 content.txt
      - 进程内缓存 + ETag/304，阅读器轮询基本不产生 IO
      - 反向代理下按 X-Forwarded-* 或 rss_base_url 生成链接
    """
    from backend.rss_feed import rss_response

    return rss_response(request, account)
