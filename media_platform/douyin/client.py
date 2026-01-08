# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/douyin/client.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#

# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。

import asyncio
import copy
import json
import pathlib
import urllib.parse
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable, Dict, Union, Optional

import aiofiles
import httpx
from playwright.async_api import BrowserContext, Page
from playwright._impl._errors import TargetClosedError

from base.base_crawler import AbstractApiClient
from proxy.proxy_mixin import ProxyRefreshMixin
from tools import utils
from var import request_keyword_var

if TYPE_CHECKING:
    from proxy.proxy_ip_pool import ProxyIpPool

from .exception import *
from .field import *
from .help import *


class DouYinClient(AbstractApiClient, ProxyRefreshMixin):

    def __init__(
        self,
        timeout=60,  # 若开启爬取媒体选项，抖音的短视频需要更久的超时时间
        proxy=None,
        *,
        headers: Dict,
        playwright_page: Optional[Page],
        cookie_dict: Dict,
        proxy_ip_pool: Optional["ProxyIpPool"] = None,
    ):
        self.proxy = proxy
        self.timeout = timeout
        self.headers = headers
        self._host = "https://www.douyin.com"
        self.playwright_page = playwright_page
        self.cookie_dict = cookie_dict
        self._browser_context = None  # 用于在页面关闭时获取其他页面
        # 初始化代理池（来自 ProxyRefreshMixin）
        self.init_proxy_pool(proxy_ip_pool)

    async def __process_req_params(
        self,
        uri: str,
        params: Optional[Dict] = None,
        headers: Optional[Dict] = None,
        request_method="GET",
    ):

        if not params:
            return
        headers = headers or self.headers
        
        # 获取localStorage，如果页面已关闭，尝试使用浏览器上下文中的其他页面
        local_storage: Dict = {}
        try:
            if self.playwright_page and not self.playwright_page.is_closed():
                local_storage = await self.playwright_page.evaluate("() => window.localStorage")  # type: ignore
            else:
                # 如果页面已关闭，尝试从浏览器上下文中获取一个有效的页面
                if hasattr(self, '_browser_context') and self._browser_context:
                    pages = self._browser_context.pages
                    if pages:
                        # 使用第一个可用的页面
                        for page in pages:
                            if not page.is_closed():
                                try:
                                    local_storage = await page.evaluate("() => window.localStorage")
                                    # 更新playwright_page引用
                                    self.playwright_page = page
                                    break
                                except (TargetClosedError, Exception):
                                    continue
                # 如果仍然无法获取，使用空字典
                if not local_storage:
                    utils.logger.warning("[DouYinClient.__process_req_params] 无法获取localStorage，使用空值")
                    local_storage = {}
        except TargetClosedError as e:
            utils.logger.warning(f"[DouYinClient.__process_req_params] 页面已关闭，无法获取localStorage: {e}，使用空值")
            local_storage = {}
        except Exception as e:
            utils.logger.warning(f"[DouYinClient.__process_req_params] 获取localStorage失败: {e}，使用空值")
            local_storage = {}
        common_params = {
            "device_platform": "webapp",
            "aid": "6383",
            "channel": "channel_pc_web",
            "version_code": "190600",
            "version_name": "19.6.0",
            "update_version_code": "170400",
            "pc_client_type": "1",
            "cookie_enabled": "true",
            "browser_language": "zh-CN",
            "browser_platform": "MacIntel",
            "browser_name": "Chrome",
            "browser_version": "125.0.0.0",
            "browser_online": "true",
            "engine_name": "Blink",
            "os_name": "Mac OS",
            "os_version": "10.15.7",
            "cpu_core_num": "8",
            "device_memory": "8",
            "engine_version": "109.0",
            "platform": "PC",
            "screen_width": "2560",
            "screen_height": "1440",
            'effective_type': '4g',
            "round_trip_time": "50",
            "webid": get_web_id(),
            "msToken": local_storage.get("xmst"),
        }
        params.update(common_params)
        query_string = urllib.parse.urlencode(params)

        # 20240927 a-bogus更新（JS版本）
        post_data = {}
        if request_method == "POST":
            post_data = params

        if "/v1/web/general/search" not in uri:
            # 获取a_bogus，如果页面已关闭，尝试使用浏览器上下文中的其他页面
            page_for_a_bogus = self.playwright_page
            if not page_for_a_bogus or page_for_a_bogus.is_closed():
                # 尝试从浏览器上下文中获取一个有效的页面
                if hasattr(self, '_browser_context') and self._browser_context:
                    pages = self._browser_context.pages
                    if pages:
                        for page in pages:
                            if not page.is_closed():
                                page_for_a_bogus = page
                                # 更新playwright_page引用
                                self.playwright_page = page
                                break
            
            if page_for_a_bogus and not page_for_a_bogus.is_closed():
                try:
                    a_bogus = await get_a_bogus(uri, query_string, post_data, headers["User-Agent"], page_for_a_bogus)
                    params["a_bogus"] = a_bogus
                except Exception as e:
                    utils.logger.warning(f"[DouYinClient.__process_req_params] 获取a_bogus失败: {e}，继续执行")
            else:
                utils.logger.warning("[DouYinClient.__process_req_params] 无法获取有效页面用于a_bogus计算，跳过")

    async def request(self, method, url, **kwargs):
        # 每次请求前检测代理是否过期
        await self._refresh_proxy_if_expired()

        async with httpx.AsyncClient(proxy=self.proxy) as client:
            response = await client.request(method, url, timeout=self.timeout, **kwargs)
        try:
            if response.text == "" or response.text == "blocked":
                utils.logger.error(f"request params incrr, response.text: {response.text}")
                raise Exception("account blocked")
            return response.json()
        except Exception as e:
            raise DataFetchError(f"{e}, {response.text}")

    async def get(self, uri: str, params: Optional[Dict] = None, headers: Optional[Dict] = None):
        """
        GET请求
        """
        await self.__process_req_params(uri, params, headers)
        headers = headers or self.headers
        return await self.request(method="GET", url=f"{self._host}{uri}", params=params, headers=headers)

    async def post(self, uri: str, data: dict, headers: Optional[Dict] = None):
        await self.__process_req_params(uri, data, headers)
        headers = headers or self.headers
        return await self.request(method="POST", url=f"{self._host}{uri}", data=data, headers=headers)

    async def _save_html_for_debug(self, page: Page, context: str = "") -> str:
        """
        将HTML内容保存到本地文件用于调试
        
        Args:
            page: 要保存的页面对象
            context: 上下文信息（用于生成文件名）
        
        Returns:
            保存的文件路径
        """
        try:
            # 创建保存目录
            debug_dir = pathlib.Path("data/douyin/debug_html")
            debug_dir.mkdir(parents=True, exist_ok=True)
            
            # 生成文件名：包含时间戳和上下文信息
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            # 清理上下文信息中的特殊字符，用于文件名
            safe_context = "".join(c for c in context if c.isalnum() or c in ('-', '_'))[:50]
            if safe_context:
                filename = f"douyin_pong_{safe_context}_{timestamp}.html"
            else:
                filename = f"douyin_pong_{timestamp}.html"
            
            file_path = debug_dir / filename
            
            # 获取页面HTML内容
            html_content = await page.content()
            
            # 异步写入文件
            async with aiofiles.open(file_path, 'w', encoding='utf-8') as f:
                await f.write(html_content)
            
            utils.logger.info(f"[DouYinClient.pong] HTML已保存到文件用于调试: {file_path}")
            return str(file_path)
        except Exception as e:
            utils.logger.warning(f"[DouYinClient.pong] 保存HTML文件失败: {e}")
            return ""

    async def pong(self, browser_context: BrowserContext) -> bool:
        # 获取一个可用的页面，优先使用已导航到抖音URL的页面
        page_to_check = None
        douyin_domains = ["douyin.com", "www.douyin.com"]
        
        # 优先使用 playwright_page（如果设置了）
        if self.playwright_page and not self.playwright_page.is_closed():
            page_to_check = self.playwright_page
            utils.logger.debug("[DouYinClient.pong] 使用 playwright_page 进行检查")
        else:
            # 从浏览器上下文中查找已导航到抖音的页面
            pages = browser_context.pages
            for page in pages:
                if not page.is_closed():
                    try:
                        current_url = page.url
                        # 检查页面URL是否包含抖音域名
                        if any(domain in current_url for domain in douyin_domains):
                            page_to_check = page
                            utils.logger.debug(f"[DouYinClient.pong] 找到已导航到抖音的页面: {current_url}")
                            break
                    except Exception:
                        # 如果获取URL失败，继续查找下一个页面
                        continue
            
            # 如果没有找到已导航到抖音的页面，使用第一个可用页面
            if not page_to_check:
                for page in pages:
                    if not page.is_closed():
                        page_to_check = page
                        utils.logger.debug(f"[DouYinClient.pong] 使用第一个可用页面: {page.url}")
                        break
        
        # 如果仍然没有找到页面，创建一个新页面
        if not page_to_check:
            try:
                page_to_check = await browser_context.new_page()
                utils.logger.debug("[DouYinClient.pong] 创建新页面用于登录检查")
            except Exception as e:
                utils.logger.warning(f"[DouYinClient.pong] 无法创建新页面: {e}")
                return False
        
        # 确保页面已导航到抖音URL（如果不是）
        try:
            current_url = page_to_check.url
            if not any(domain in current_url for domain in douyin_domains):
                utils.logger.info(f"[DouYinClient.pong] 页面未在抖音URL ({current_url})，导航到抖音首页...")
                await page_to_check.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(2)  # 等待页面加载
        except Exception as e:
            utils.logger.warning(f"[DouYinClient.pong] 导航到抖音URL失败: {e}")

        # 等待页面加载完成
        try:
            # 等待页面加载状态为 'load' 或 'domcontentloaded'
            await page_to_check.wait_for_load_state("domcontentloaded", timeout=10000)
            # 额外等待一段时间，确保动态内容加载完成
            await asyncio.sleep(2)
            
            # 尝试等待关键元素出现（最多等待5秒）
            try:
                # 等待页面主体加载完成
                await page_to_check.wait_for_selector("body", timeout=5000)
            except Exception:
                pass  # 如果超时，继续执行后续检查
        except Exception as e:
            utils.logger.warning(f"[DouYinClient.pong] 等待页面加载失败: {e}")

        # 统一通过页面元素判断登录状态（localStorage和Cookie可能无效）
        # 首先检查是否有登录弹窗，如果有弹窗就一定需要登录
        try:
            # 检查登录弹窗（最优先判断）
            login_dialog_selector = "xpath=//div[@id='login-panel-new']"
            try:
                login_dialog = await page_to_check.wait_for_selector(login_dialog_selector, timeout=3000)
                if login_dialog:
                    # 检查弹窗是否可见
                    is_visible = await login_dialog.is_visible()
                    if is_visible:
                        utils.logger.info("[DouYinClient.pong] 检测到登录弹窗，需要登录")
                        return False
            except Exception:
                pass  # 超时或未找到登录弹窗，继续检查登录元素
        except Exception as e:
            utils.logger.debug(f"[DouYinClient.pong] 检查登录弹窗时出错: {e}")
        
        # 检查页面元素 - 是否存在用户菜单（包含"退出登录"或用户头像链接）
        try:
            # 检查是否存在用户菜单相关元素
            # 方式1: 检查是否存在"退出登录"文本（最可靠的登录标识）
            try:
                exit_login_element = await page_to_check.wait_for_selector('text=退出登录', timeout=5000)
                if exit_login_element:
                    utils.logger.info("[DouYinClient.pong] 通过页面元素（退出登录）检测到登录状态")
                    return True
            except Exception:
                pass  # 超时或未找到，继续检查其他元素
            
            # 方式2: 检查是否存在用户头像链接 (href包含"/user/self")
            try:
                user_self_link = await page_to_check.wait_for_selector('a[href*="/user/self"]', timeout=5000)
                if user_self_link:
                    utils.logger.info("[DouYinClient.pong] 通过页面元素（用户头像链接）检测到登录状态")
                    return True
            except Exception:
                pass  # 超时或未找到，继续检查其他元素
            
            # 方式3: 检查是否存在用户菜单面板（通过data-e2e="live-avatar"）
            try:
                user_avatar = await page_to_check.wait_for_selector('[data-e2e="live-avatar"]', timeout=5000)
                if user_avatar:
                    utils.logger.info("[DouYinClient.pong] 通过页面元素（用户头像）检测到登录状态")
                    return True
            except Exception:
                pass  # 超时或未找到
            
            # 方式4: 检查是否存在用户相关的其他标识元素
            try:
                # 检查用户菜单下拉按钮（通常包含用户头像）
                user_menu_selectors = [
                    '[class*="user-menu"]',
                    '[class*="avatar"]',
                    '[data-e2e="user-avatar"]',
                    'a[href*="/user/"]',
                ]
                for selector in user_menu_selectors:
                    try:
                        element = await page_to_check.wait_for_selector(selector, timeout=2000)
                        if element:
                            # 验证元素是否可见且可交互
                            is_visible = await element.is_visible()
                            if is_visible:
                                utils.logger.info(f"[DouYinClient.pong] 通过页面元素（{selector}）检测到登录状态")
                                return True
                    except Exception:
                        continue
            except Exception:
                pass
            
            # 如果所有检查都失败，保存HTML用于调试
            utils.logger.warning("[DouYinClient.pong] 所有登录状态检查均失败，保存HTML用于调试")
            await self._save_html_for_debug(page_to_check, "login_check_failed")
            
        except (TargetClosedError, Exception) as e:
            utils.logger.warning(f"[DouYinClient.pong] 检查页面元素失败: {e}")
            # 即使出错也保存HTML用于调试
            try:
                await self._save_html_for_debug(page_to_check, f"error_{type(e).__name__}")
            except Exception:
                pass

        return False

    async def update_cookies(self, browser_context: BrowserContext):
        cookie_str, cookie_dict = utils.convert_cookies(await browser_context.cookies())
        self.headers["Cookie"] = cookie_str
        self.cookie_dict = cookie_dict

    async def search_info_by_keyword(
        self,
        keyword: str,
        offset: int = 0,
        search_channel: SearchChannelType = SearchChannelType.GENERAL,
        sort_type: SearchSortType = SearchSortType.GENERAL,
        publish_time: PublishTimeType = PublishTimeType.UNLIMITED,
        search_id: str = "",
    ):
        """
        DouYin Web Search API
        :param keyword:
        :param offset:
        :param search_channel:
        :param sort_type:
        :param publish_time: ·
        :param search_id: ·
        :return:
        """
        query_params = {
            'search_channel': search_channel.value,
            'enable_history': '1',
            'keyword': keyword,
            'search_source': 'tab_search',
            'query_correct_type': '1',
            'is_filter_search': '0',
            'from_group_id': '7378810571505847586',
            'offset': offset,
            'count': '15',
            'need_filter_settings': '1',
            'list_type': 'multi',
            'search_id': search_id,
        }
        if sort_type.value != SearchSortType.GENERAL.value or publish_time.value != PublishTimeType.UNLIMITED.value:
            query_params["filter_selected"] = json.dumps({"sort_type": str(sort_type.value), "publish_time": str(publish_time.value)})
            query_params["is_filter_search"] = 1
            query_params["search_source"] = "tab_search"
        referer_url = f"https://www.douyin.com/search/{keyword}?aid=f594bbd9-a0e2-4651-9319-ebe3cb6298c1&type=general"
        headers = copy.copy(self.headers)
        headers["Referer"] = urllib.parse.quote(referer_url, safe=':/')
        return await self.get("/aweme/v1/web/general/search/single/", query_params, headers=headers)

    async def get_video_by_id(self, aweme_id: str) -> Any:
        """
        DouYin Video Detail API
        :param aweme_id:
        :return:
        """
        params = {"aweme_id": aweme_id}
        headers = copy.copy(self.headers)
        del headers["Origin"]
        res = await self.get("/aweme/v1/web/aweme/detail/", params, headers)
        return res.get("aweme_detail", {})

    async def get_aweme_comments(self, aweme_id: str, cursor: int = 0):
        """get note comments

        """
        uri = "/aweme/v1/web/comment/list/"
        params = {"aweme_id": aweme_id, "cursor": cursor, "count": 20, "item_type": 0}
        keywords = request_keyword_var.get()
        referer_url = "https://www.douyin.com/search/" + keywords + '?aid=3a3cec5a-9e27-4040-b6aa-ef548c2c1138&publish_time=0&sort_type=0&source=search_history&type=general'
        headers = copy.copy(self.headers)
        headers["Referer"] = urllib.parse.quote(referer_url, safe=':/')
        return await self.get(uri, params)

    async def get_sub_comments(self, aweme_id: str, comment_id: str, cursor: int = 0):
        """
            获取子评论
        """
        uri = "/aweme/v1/web/comment/list/reply/"
        params = {
            'comment_id': comment_id,
            "cursor": cursor,
            "count": 20,
            "item_type": 0,
            "item_id": aweme_id,
        }
        keywords = request_keyword_var.get()
        referer_url = "https://www.douyin.com/search/" + keywords + '?aid=3a3cec5a-9e27-4040-b6aa-ef548c2c1138&publish_time=0&sort_type=0&source=search_history&type=general'
        headers = copy.copy(self.headers)
        headers["Referer"] = urllib.parse.quote(referer_url, safe=':/')
        return await self.get(uri, params)

    async def get_aweme_all_comments(
        self,
        aweme_id: str,
        crawl_interval: float = 1.0,
        is_fetch_sub_comments=False,
        callback: Optional[Callable] = None,
        max_count: int = 10,
    ):
        """
        获取帖子的所有评论，包括子评论
        :param aweme_id: 帖子ID
        :param crawl_interval: 抓取间隔
        :param is_fetch_sub_comments: 是否抓取子评论
        :param callback: 回调函数，用于处理抓取到的评论
        :param max_count: 一次帖子爬取的最大评论数量
        :return: 评论列表
        """
        result = []
        comments_has_more = 1
        comments_cursor = 0
        while comments_has_more and len(result) < max_count:
            comments_res = await self.get_aweme_comments(aweme_id, comments_cursor)
            comments_has_more = comments_res.get("has_more", 0)
            comments_cursor = comments_res.get("cursor", 0)
            comments = comments_res.get("comments", [])
            if not comments:
                continue
            if len(result) + len(comments) > max_count:
                comments = comments[:max_count - len(result)]
            result.extend(comments)
            if callback:  # 如果有回调函数，就执行回调函数
                await callback(aweme_id, comments)

            await asyncio.sleep(crawl_interval)
            if not is_fetch_sub_comments:
                continue
            # 获取二级评论
            for comment in comments:
                reply_comment_total = comment.get("reply_comment_total")

                if reply_comment_total > 0:
                    comment_id = comment.get("cid")
                    sub_comments_has_more = 1
                    sub_comments_cursor = 0

                    while sub_comments_has_more:
                        sub_comments_res = await self.get_sub_comments(aweme_id, comment_id, sub_comments_cursor)
                        sub_comments_has_more = sub_comments_res.get("has_more", 0)
                        sub_comments_cursor = sub_comments_res.get("cursor", 0)
                        sub_comments = sub_comments_res.get("comments", [])

                        if not sub_comments:
                            continue
                        result.extend(sub_comments)
                        if callback:  # 如果有回调函数，就执行回调函数
                            await callback(aweme_id, sub_comments)
                        await asyncio.sleep(crawl_interval)
        return result

    async def get_user_info(self, sec_user_id: str):
        uri = "/aweme/v1/web/user/profile/other/"
        params = {
            "sec_user_id": sec_user_id,
            "publish_video_strategy_type": 2,
            "personal_center_strategy": 1,
        }
        return await self.get(uri, params)

    async def get_user_aweme_posts(self, sec_user_id: str, max_cursor: str = "") -> Dict:
        uri = "/aweme/v1/web/aweme/post/"
        params = {
            "sec_user_id": sec_user_id,
            "count": 18,
            "max_cursor": max_cursor,
            "locate_query": "false",
            "publish_video_strategy_type": 2,
            'verifyFp': 'verify_ma3hrt8n_q2q2HyYA_uLyO_4N6D_BLvX_E2LgoGmkA1BU',
            'fp': 'verify_ma3hrt8n_q2q2HyYA_uLyO_4N6D_BLvX_E2LgoGmkA1BU'
        }
        return await self.get(uri, params)

    async def get_all_user_aweme_posts(self, sec_user_id: str, callback: Optional[Callable] = None):
        posts_has_more = 1
        max_cursor = ""
        result = []
        while posts_has_more == 1:
            aweme_post_res = await self.get_user_aweme_posts(sec_user_id, max_cursor)
            posts_has_more = aweme_post_res.get("has_more", 0)
            max_cursor = aweme_post_res.get("max_cursor")
            aweme_list = aweme_post_res.get("aweme_list") if aweme_post_res.get("aweme_list") else []
            utils.logger.info(f"[DouYinClient.get_all_user_aweme_posts] get sec_user_id:{sec_user_id} video len : {len(aweme_list)}")
            if callback:
                await callback(aweme_list)
            result.extend(aweme_list)
        return result

    async def get_aweme_media(self, url: str) -> Union[bytes, None]:
        async with httpx.AsyncClient(proxy=self.proxy) as client:
            try:
                response = await client.request("GET", url, timeout=self.timeout, follow_redirects=True)
                response.raise_for_status()
                if not response.reason_phrase == "OK":
                    utils.logger.error(f"[DouYinClient.get_aweme_media] request {url} err, res:{response.text}")
                    return None
                else:
                    return response.content
            except httpx.HTTPError as exc:  # some wrong when call httpx.request method, such as connection error, client error, server error or response status code is not 2xx
                utils.logger.error(f"[DouYinClient.get_aweme_media] {exc.__class__.__name__} for {exc.request.url} - {exc}")  # 保留原始异常类型名称，以便开发者调试
                return None

    async def resolve_short_url(self, short_url: str) -> str:
        """
        解析抖音短链接,获取重定向后的真实URL
        Args:
            short_url: 短链接,如 https://v.douyin.com/iF12345ABC/
        Returns:
            重定向后的完整URL
        """
        async with httpx.AsyncClient(proxy=self.proxy, follow_redirects=False) as client:
            try:
                utils.logger.info(f"[DouYinClient.resolve_short_url] Resolving short URL: {short_url}")
                response = await client.get(short_url, timeout=10)

                # 短链接通常返回302重定向
                if response.status_code in [301, 302, 303, 307, 308]:
                    redirect_url = response.headers.get("Location", "")
                    utils.logger.info(f"[DouYinClient.resolve_short_url] Resolved to: {redirect_url}")
                    return redirect_url
                else:
                    utils.logger.warning(f"[DouYinClient.resolve_short_url] Unexpected status code: {response.status_code}")
                    return ""
            except Exception as e:
                utils.logger.error(f"[DouYinClient.resolve_short_url] Failed to resolve short URL: {e}")
                return ""
