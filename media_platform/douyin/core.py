# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/douyin/core.py
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
import os
import random
from asyncio import Task
from typing import Any, Dict, List, Optional, Tuple

from playwright.async_api import (
    BrowserContext,
    BrowserType,
    Page,
    Playwright,
    async_playwright,
)
from playwright._impl._errors import TargetClosedError

import config
from base.base_crawler import AbstractCrawler
from proxy.proxy_ip_pool import IpInfoModel, create_ip_pool
from store import douyin as douyin_store
from tools import utils
from tools.cdp_browser import CDPBrowserManager
from var import crawler_type_var, source_keyword_var

from .client import DouYinClient
from .exception import DataFetchError
from .field import PublishTimeType
from .help import parse_video_info_from_url, parse_creator_info_from_url
from .login import DouYinLogin


class DouYinCrawler(AbstractCrawler):
    context_page: Page
    dy_client: DouYinClient
    browser_context: BrowserContext
    cdp_manager: Optional[CDPBrowserManager]

    def __init__(self) -> None:
        self.index_url = "https://www.douyin.com"
        self.cdp_manager = None
        self.ip_proxy_pool = None  # 代理IP池，用于代理自动刷新
        self.keep_browser_open = False  # 标志：是否保持浏览器打开

    async def start(self) -> None:
        playwright_proxy_format, httpx_proxy_format = None, None
        if config.ENABLE_IP_PROXY:
            self.ip_proxy_pool = await create_ip_pool(config.IP_PROXY_POOL_COUNT, enable_validate_ip=True)
            ip_proxy_info: IpInfoModel = await self.ip_proxy_pool.get_proxy()
            playwright_proxy_format, httpx_proxy_format = utils.format_proxy_info(ip_proxy_info)

        async with async_playwright() as playwright:
            # 根据配置选择启动模式
            if config.ENABLE_CDP_MODE:
                utils.logger.info("[DouYinCrawler] 使用CDP模式启动浏览器")
                self.browser_context = await self.launch_browser_with_cdp(
                    playwright,
                    playwright_proxy_format,
                    None,
                    headless=config.CDP_HEADLESS,
                )
                # CDP模式下也添加stealth脚本和交互脚本
                try:
                    await self.browser_context.add_init_script(path="libs/stealth.min.js")
                    utils.logger.info("[DouYinCrawler] CDP模式已添加stealth脚本")
                except Exception as e:
                    utils.logger.warning(f"[DouYinCrawler] CDP模式添加stealth脚本失败: {e}")
                
                # 添加脚本确保页面可以交互（移除可能阻止点击的样式）
                try:
                    await self.browser_context.add_init_script("""
                        // 确保页面可以交互
                        (function() {
                            // 移除可能阻止点击的pointer-events样式
                            const style = document.createElement('style');
                            style.textContent = `
                                * {
                                    pointer-events: auto !important;
                                }
                            `;
                            document.head.appendChild(style);
                            
                            // 确保body可以交互
                            if (document.body) {
                                document.body.style.pointerEvents = 'auto';
                            }
                        })();
                    """)
                    utils.logger.info("[DouYinCrawler] CDP模式已添加交互脚本")
                except Exception as e:
                    utils.logger.warning(f"[DouYinCrawler] CDP模式添加交互脚本失败: {e}")
            else:
                utils.logger.info("[DouYinCrawler] 使用标准模式启动浏览器")
                # Launch a browser context.
                chromium = playwright.chromium
                self.browser_context = await self.launch_browser(
                    chromium,
                    playwright_proxy_format,
                    user_agent=None,
                    headless=config.HEADLESS,
                )
                # stealth.min.js is a js script to prevent the website from detecting the crawler.
                await self.browser_context.add_init_script(path="libs/stealth.min.js")

            self.context_page = await self.browser_context.new_page()
            
            # 如果设置了跳过登录和搜索URL，直接访问搜索URL
            if config.SKIP_LOGIN and config.SEARCH_URL:
                utils.logger.info(f"[DouYinCrawler.start] 跳过登录，直接访问搜索URL: {config.SEARCH_URL}")
                await self.context_page.goto(config.SEARCH_URL)
                await asyncio.sleep(2)  # 等待页面加载
            else:
                await self.context_page.goto(self.index_url)

            self.dy_client = await self.create_douyin_client(httpx_proxy_format)
            
            # 如果设置了跳过登录，则跳过登录检查
            if config.SKIP_LOGIN:
                utils.logger.info("[DouYinCrawler.start] 已设置跳过登录，直接进行抓取")
                # 仍然更新cookies（可能有一些基础cookies）
                await self.dy_client.update_cookies(browser_context=self.browser_context)
            else:
                # 检查登录状态
                is_logged_in = await self.dy_client.pong(browser_context=self.browser_context)
                if is_logged_in:
                    utils.logger.info("[DouYinCrawler.start] 检测到已保存的登录状态，跳过登录流程")
                    # 即使已登录，也更新一次cookies确保最新
                    await self.dy_client.update_cookies(browser_context=self.browser_context)
                else:
                    utils.logger.info("[DouYinCrawler.start] 未检测到登录状态，开始登录流程")
                    login_obj = DouYinLogin(
                        login_type=config.LOGIN_TYPE,
                        login_phone="",  # you phone number
                        browser_context=self.browser_context,
                        context_page=self.context_page,
                        cookie_str=config.COOKIES,
                    )
                    await login_obj.begin()
                    await self.dy_client.update_cookies(browser_context=self.browser_context)
                    utils.logger.info("[DouYinCrawler.start] 登录完成，登录状态已保存到本地")
            crawler_type_var.set(config.CRAWLER_TYPE)
            has_data = False  # 跟踪是否成功提取到数据
            
            if config.CRAWLER_TYPE == "search":
                # 如果设置了搜索URL且跳过登录，直接从当前页面抓取数据
                if config.SKIP_LOGIN and config.SEARCH_URL:
                    utils.logger.info("[DouYinCrawler.start] 使用搜索URL直接抓取，跳过搜索步骤")
                    # 从URL中提取关键词（如果有）
                    keyword = ""
                    if "/search/" in config.SEARCH_URL:
                        try:
                            # 提取URL中的关键词（URL编码的）
                            import urllib.parse
                            keyword_part = config.SEARCH_URL.split("/search/")[-1].split("?")[0]
                            keyword = urllib.parse.unquote(keyword_part)
                            source_keyword_var.set(keyword)
                            utils.logger.info(f"[DouYinCrawler.start] 从URL提取关键词: {keyword}")
                        except Exception as e:
                            utils.logger.warning(f"[DouYinCrawler.start] 无法从URL提取关键词: {e}")
                    
                    # 如果启用了浏览器自动化模式，直接从当前页面抓取
                    if config.ENABLE_BROWSER_AUTOMATION_MODE:
                        has_data = await self.search_by_browser_from_current_page()
                    else:
                        # API模式，使用提取的关键词进行搜索
                        if keyword:
                            has_data = await self._search_by_api(keyword)
                        else:
                            utils.logger.warning("[DouYinCrawler.start] 无法提取关键词，跳过搜索")
                else:
                    # Search for notes and retrieve their comment information.
                    has_data = await self.search()
            elif config.CRAWLER_TYPE == "detail":
                # Get the information and comments of the specified post
                await self.get_specified_awemes()
                has_data = True  # detail类型假设成功
            elif config.CRAWLER_TYPE == "creator":
                # Get the information and comments of the specified creator
                await self.get_creators_and_videos()
                has_data = True  # creator类型假设成功

            utils.logger.info("[DouYinCrawler.start] Douyin Crawler finished ...")
            
            # 如果未找到数据且配置了保持浏览器打开，则不关闭浏览器
            if not has_data and config.KEEP_BROWSER_OPEN_ON_FAILURE:
                utils.logger.warning("[DouYinCrawler.start] 未找到视频数据，根据配置保持浏览器打开以便分析页面")
                utils.logger.info(f"[DouYinCrawler.start] 当前页面URL: {self.context_page.url}")
                try:
                    page_title = await self.context_page.title()
                    utils.logger.info(f"[DouYinCrawler.start] 页面标题: {page_title}")
                except Exception:
                    pass
                utils.logger.info("[DouYinCrawler.start] 请手动分析页面结构，检查：")
                utils.logger.info("[DouYinCrawler.start] 1. 页面是否正常加载")
                utils.logger.info("[DouYinCrawler.start] 2. 视频元素的选择器是否正确")
                utils.logger.info("[DouYinCrawler.start] 3. 是否需要登录或验证")
                utils.logger.info("[DouYinCrawler.start] 分析完成后可手动关闭浏览器")
                # 设置标志，防止main.py中的cleanup函数关闭浏览器
                self.keep_browser_open = True
                config.AUTO_CLOSE_BROWSER = False
                # 等待用户输入，保持程序运行
                utils.logger.info("[DouYinCrawler.start] 浏览器将保持打开，按 Ctrl+C 退出程序...")
                try:
                    # 在异步环境中等待，保持程序运行
                    # 使用一个长时间等待，但可以被中断
                    await asyncio.sleep(86400)  # 等待24小时（足够长的时间）
                except (KeyboardInterrupt, asyncio.CancelledError):
                    utils.logger.info("[DouYinCrawler.start] 收到退出信号，浏览器将保持打开")
                return  # 不执行清理，保持浏览器打开

    async def search(self) -> bool:
        utils.logger.info("[DouYinCrawler.search] Begin search douyin keywords")
        
        # 检查是否使用浏览器自动化模式
        if config.ENABLE_BROWSER_AUTOMATION_MODE:
            utils.logger.info("[DouYinCrawler.search] 使用浏览器自动化模式（通过输入框搜索）")
            return await self.search_by_browser()
        
        # 原有的API搜索模式
        dy_limit_count = 10  # douyin limit page fixed value
        # 不再强制设置最小值为10，允许采集少于10个视频
        start_page = config.START_PAGE  # start page number
        for keyword in config.KEYWORDS.split(","):
            source_keyword_var.set(keyword)
            utils.logger.info(f"[DouYinCrawler.search] Current keyword: {keyword}")
            aweme_list: List[str] = []
            page = 0
            dy_search_id = ""
            while (page - start_page + 1) * dy_limit_count <= config.CRAWLER_MAX_NOTES_COUNT:
                if page < start_page:
                    utils.logger.info(f"[DouYinCrawler.search] Skip {page}")
                    page += 1
                    continue
                try:
                    utils.logger.info(f"[DouYinCrawler.search] search douyin keyword: {keyword}, page: {page}")
                    posts_res = await self.dy_client.search_info_by_keyword(
                        keyword=keyword,
                        offset=page * dy_limit_count - dy_limit_count,
                        publish_time=PublishTimeType(config.PUBLISH_TIME_TYPE),
                        search_id=dy_search_id,
                    )
                    
                    # 添加详细的响应日志
                    utils.logger.info(f"[DouYinCrawler.search] Search response keys: {list(posts_res.keys()) if posts_res else 'None'}")
                    if posts_res:
                        utils.logger.info(f"[DouYinCrawler.search] Response status_code: {posts_res.get('status_code', 'N/A')}")
                        utils.logger.info(f"[DouYinCrawler.search] Response has_more: {posts_res.get('has_more', 'N/A')}")
                        if "data" in posts_res:
                            data_len = len(posts_res.get("data", [])) if posts_res.get("data") else 0
                            utils.logger.info(f"[DouYinCrawler.search] Response data length: {data_len}")
                            if data_len > 0:
                                # 打印第一条数据的结构
                                first_item = posts_res.get("data", [])[0]
                                utils.logger.info(f"[DouYinCrawler.search] First item keys: {list(first_item.keys()) if isinstance(first_item, dict) else type(first_item)}")
                    
                    if posts_res.get("data") is None or posts_res.get("data") == []:
                        utils.logger.warning(f"[DouYinCrawler.search] search douyin keyword: {keyword}, page: {page} is empty, response: {posts_res}")
                        # 如果返回了错误码，记录详细信息
                        if posts_res.get("status_code") and posts_res.get("status_code") != 0:
                            utils.logger.error(f"[DouYinCrawler.search] API returned error status_code: {posts_res.get('status_code')}, status_msg: {posts_res.get('status_msg', 'N/A')}")
                        break
                except DataFetchError as e:
                    utils.logger.error(f"[DouYinCrawler.search] search douyin keyword: {keyword} failed, error: {e}")
                    break
                except Exception as e:
                    utils.logger.error(f"[DouYinCrawler.search] Unexpected error: {e}, type: {type(e)}")
                    break

                page += 1
                if "data" not in posts_res:
                    utils.logger.error(f"[DouYinCrawler.search] search douyin keyword: {keyword} failed，账号也许被风控了。Response: {posts_res}")
                    break
                dy_search_id = posts_res.get("extra", {}).get("logid", "")
                for post_item in posts_res.get("data"):
                    # 如果已经达到最大采集数量，停止采集
                    if len(aweme_list) >= config.CRAWLER_MAX_NOTES_COUNT:
                        utils.logger.info(f"[DouYinCrawler.search] Reached max notes count: {config.CRAWLER_MAX_NOTES_COUNT}, stopping collection")
                        break
                    try:
                        aweme_info: Dict = (post_item.get("aweme_info") or post_item.get("aweme_mix_info", {}).get("mix_items")[0])
                    except TypeError:
                        continue
                    aweme_list.append(aweme_info.get("aweme_id", ""))
                    await douyin_store.update_douyin_aweme(aweme_item=aweme_info)
                    await self.get_aweme_media(aweme_item=aweme_info)
                # 如果已经达到最大采集数量，退出外层循环
                if len(aweme_list) >= config.CRAWLER_MAX_NOTES_COUNT:
                    utils.logger.info(f"[DouYinCrawler.search] Reached max notes count: {config.CRAWLER_MAX_NOTES_COUNT}, exiting search loop")
                    break
                # Sleep after each page navigation
                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                utils.logger.info(f"[DouYinCrawler.search] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after page {page-1}")
            utils.logger.info(f"[DouYinCrawler.search] keyword:{keyword}, aweme_list:{aweme_list}")
            if aweme_list:
                await self.batch_get_note_comments(aweme_list)
                return True
            else:
                return False

    async def search_by_browser(self) -> bool:
        """
        基于浏览器自动化的搜索模式，通过输入框输入关键词并点击搜索
        完全模拟真实用户操作，避免API验证码
        """
        utils.logger.info("[DouYinCrawler.search_by_browser] 开始使用浏览器自动化搜索...")
        
        # 访问抖音首页
        utils.logger.info("[DouYinCrawler.search_by_browser] 访问抖音首页...")
        await self.context_page.goto(self.index_url, wait_until="domcontentloaded", timeout=30000)
        utils.logger.info("[DouYinCrawler.search_by_browser] 等待页面完全加载...")
        await asyncio.sleep(5)  # 增加等待时间，确保页面完全加载
        
        for keyword in config.KEYWORDS.split(","):
            source_keyword_var.set(keyword)
            utils.logger.info(f"[DouYinCrawler.search_by_browser] 搜索关键词: {keyword}")
            
            try:
                # 查找搜索输入框（抖音的搜索框通常在顶部导航栏）
                # 尝试多种可能的选择器
                search_input_selectors = [
                    "input[placeholder*='搜索']",
                    "input[placeholder*='Search']",
                    ".search-input input",
                    "#search-input",
                    "input[type='search']",
                    "//input[@placeholder='搜索' or @placeholder='Search']",
                    "//input[contains(@placeholder, '搜索')]",
                    "//input[contains(@placeholder, 'Search')]",
                    "input[placeholder]",
                ]
                
                search_input = None
                utils.logger.info("[DouYinCrawler.search_by_browser] 开始查找搜索输入框...")
                
                # 等待搜索输入框出现，增加超时时间
                for selector in search_input_selectors:
                    try:
                        utils.logger.debug(f"[DouYinCrawler.search_by_browser] 尝试选择器: {selector}")
                        if selector.startswith("//"):
                            search_input = self.context_page.locator(f"xpath={selector}")
                        else:
                            search_input = self.context_page.locator(selector)
                        
                        # 等待元素出现，增加超时时间到15秒
                        try:
                            await search_input.first.wait_for(state="visible", timeout=15000)
                            count = await search_input.count()
                            if count > 0:
                                utils.logger.info(f"[DouYinCrawler.search_by_browser] 找到搜索输入框: {selector} (数量: {count})")
                                break
                        except Exception as e:
                            utils.logger.debug(f"[DouYinCrawler.search_by_browser] 选择器 {selector} 等待超时或未找到: {e}")
                            continue
                    except Exception as e:
                        utils.logger.debug(f"[DouYinCrawler.search_by_browser] 选择器 {selector} 出错: {e}")
                        continue
                
                if not search_input or await search_input.count() == 0:
                    # 如果找不到输入框，尝试点击搜索图标
                    utils.logger.info("[DouYinCrawler.search_by_browser] 未找到搜索输入框，尝试点击搜索图标...")
                    await asyncio.sleep(2)  # 额外等待时间
                    
                    search_icon_selectors = [
                        "//div[contains(@class, 'search')]",
                        "//svg[contains(@class, 'search')]",
                        ".search-icon",
                        "[data-e2e='search-icon']",
                        "//button[contains(@class, 'search')]",
                        "//div[contains(@class, 'search-box')]",
                        "//div[contains(@class, 'search-bar')]",
                    ]
                    
                    for icon_selector in search_icon_selectors:
                        try:
                            utils.logger.debug(f"[DouYinCrawler.search_by_browser] 尝试搜索图标选择器: {icon_selector}")
                            if icon_selector.startswith("//"):
                                icon = self.context_page.locator(f"xpath={icon_selector}")
                            else:
                                icon = self.context_page.locator(icon_selector)
                            
                            # 等待图标出现
                            try:
                                await icon.first.wait_for(state="visible", timeout=10000)
                                count = await icon.count()
                                if count > 0:
                                    utils.logger.info(f"[DouYinCrawler.search_by_browser] 找到搜索图标: {icon_selector}")
                                    await icon.first.click()
                                    await asyncio.sleep(3)  # 等待搜索框出现
                                    
                                    # 再次尝试查找输入框，增加等待时间
                                    for selector in search_input_selectors:
                                        try:
                                            if selector.startswith("//"):
                                                search_input = self.context_page.locator(f"xpath={selector}")
                                            else:
                                                search_input = self.context_page.locator(selector)
                                            
                                            await search_input.first.wait_for(state="visible", timeout=10000)
                                            if await search_input.count() > 0:
                                                utils.logger.info(f"[DouYinCrawler.search_by_browser] 点击图标后找到搜索输入框: {selector}")
                                                break
                                        except Exception:
                                            continue
                                    break
                            except Exception as e:
                                utils.logger.debug(f"[DouYinCrawler.search_by_browser] 搜索图标 {icon_selector} 未找到: {e}")
                                continue
                        except Exception as e:
                            utils.logger.debug(f"[DouYinCrawler.search_by_browser] 搜索图标选择器 {icon_selector} 出错: {e}")
                            continue
                
                if not search_input or await search_input.count() == 0:
                    utils.logger.error("[DouYinCrawler.search_by_browser] 无法找到搜索输入框，回退到API模式")
                    # 回退到API模式
                    await self._search_by_api(keyword)
                    continue
                
                # 清空输入框并输入关键词
                utils.logger.info(f"[DouYinCrawler.search_by_browser] 输入关键词: {keyword}")
                await search_input.click()
                await asyncio.sleep(0.5)
                await search_input.fill("")  # 清空
                await asyncio.sleep(0.3)
                await search_input.fill(keyword)  # 输入关键词
                await asyncio.sleep(0.5)
                
                # 查找并点击搜索按钮
                search_button_selectors = [
                    "//button[contains(text(), '搜索')]",
                    "//button[contains(text(), 'Search')]",
                    ".search-button",
                    "button[type='submit']",
                    "[data-e2e='search-button']",
                    "//span[contains(text(), '搜索')]/parent::button",
                ]
                
                search_button = None
                for btn_selector in search_button_selectors:
                    try:
                        if btn_selector.startswith("//"):
                            search_button = self.context_page.locator(f"xpath={btn_selector}")
                        else:
                            search_button = self.context_page.locator(btn_selector)
                        
                        if await search_button.count() > 0:
                            utils.logger.info(f"[DouYinCrawler.search_by_browser] 找到搜索按钮: {btn_selector}")
                            break
                    except Exception:
                        continue
                
                # 如果找不到搜索按钮，尝试按Enter键
                if not search_button or await search_button.count() == 0:
                    utils.logger.info("[DouYinCrawler.search_by_browser] 未找到搜索按钮，使用Enter键搜索")
                    await search_input.press("Enter")
                else:
                    await search_button.click()
                
                # 等待搜索结果页面加载
                utils.logger.info("[DouYinCrawler.search_by_browser] 等待搜索结果页面加载...")
                await asyncio.sleep(3)
                
                # 等待URL变化，确认已跳转到搜索结果页
                try:
                    await self.context_page.wait_for_function(
                        "() => window.location.href.includes('/search/')",
                        timeout=10000
                    )
                    utils.logger.info(f"[DouYinCrawler.search_by_browser] 已跳转到搜索结果页: {self.context_page.url}")
                except Exception:
                    utils.logger.warning("[DouYinCrawler.search_by_browser] 等待URL变化超时，继续执行...")
                
                # 等待搜索结果加载
                await asyncio.sleep(2)
                
                # 从搜索结果页面点击视频链接并提取视频数据
                aweme_list = await self._extract_videos_from_search_page(keyword)
                
                if aweme_list:
                    utils.logger.info(f"[DouYinCrawler.search_by_browser] 从页面提取到 {len(aweme_list)} 个视频ID")
                    await self.batch_get_note_comments(aweme_list)
                    return True
                else:
                    utils.logger.warning(f"[DouYinCrawler.search_by_browser] 未从页面提取到视频")
                    # 添加页面分析提示
                    if config.KEEP_BROWSER_OPEN_ON_FAILURE:
                        utils.logger.info("[DouYinCrawler.search_by_browser] 浏览器将保持打开，请检查页面元素结构")
                    return False
                
            except Exception as e:
                utils.logger.error(f"[DouYinCrawler.search_by_browser] 浏览器搜索失败: {e}")
                import traceback
                utils.logger.error(f"[DouYinCrawler.search_by_browser] 错误详情: {traceback.format_exc()}")
                return False
        
        # 如果没有处理任何关键词，返回False
        return False

    async def _search_by_api(self, keyword: str) -> bool:
        """
        使用API模式搜索（原有逻辑）
        """
        utils.logger.info(f"[DouYinCrawler._search_by_api] 使用API模式搜索关键词: {keyword}")
        dy_limit_count = 10
        start_page = config.START_PAGE
        aweme_list: List[str] = []
        page = 0
        dy_search_id = ""
        
        while (page - start_page + 1) * dy_limit_count <= config.CRAWLER_MAX_NOTES_COUNT:
            if page < start_page:
                page += 1
                continue
            
            try:
                utils.logger.info(f"[DouYinCrawler._search_by_api] search douyin keyword: {keyword}, page: {page}")
                posts_res = await self.dy_client.search_info_by_keyword(
                    keyword=keyword,
                    offset=page * dy_limit_count - dy_limit_count,
                    publish_time=PublishTimeType(config.PUBLISH_TIME_TYPE),
                    search_id=dy_search_id,
                )
                
                if posts_res.get("data") is None or posts_res.get("data") == []:
                    utils.logger.warning(f"[DouYinCrawler._search_by_api] search douyin keyword: {keyword}, page: {page} is empty")
                    break
                
                page += 1
                if "data" not in posts_res:
                    utils.logger.error(f"[DouYinCrawler._search_by_api] search douyin keyword: {keyword} failed")
                    break
                
                dy_search_id = posts_res.get("extra", {}).get("logid", "")
                for post_item in posts_res.get("data"):
                    if len(aweme_list) >= config.CRAWLER_MAX_NOTES_COUNT:
                        break
                    try:
                        aweme_info: Dict = (post_item.get("aweme_info") or post_item.get("aweme_mix_info", {}).get("mix_items")[0])
                    except TypeError:
                        continue
                    aweme_list.append(aweme_info.get("aweme_id", ""))
                    await douyin_store.update_douyin_aweme(aweme_item=aweme_info)
                    await self.get_aweme_media(aweme_item=aweme_info)
                
                if len(aweme_list) >= config.CRAWLER_MAX_NOTES_COUNT:
                    break
                
                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
            except Exception as e:
                utils.logger.error(f"[DouYinCrawler._search_by_api] Error: {e}")
                break
        
        if aweme_list:
            await self.batch_get_note_comments(aweme_list)
            return True
        else:
            return False

    async def search_by_browser_from_current_page(self) -> bool:
        """
        从当前页面（已经是搜索结果页）直接抓取数据，不需要再次搜索
        适用于直接使用搜索URL的情况
        """
        utils.logger.info("[DouYinCrawler.search_by_browser_from_current_page] 从当前搜索结果页面直接抓取数据...")
        
        # 从URL中提取关键词（如果有）
        keyword = ""
        if "/search/" in self.context_page.url:
            try:
                import urllib.parse
                keyword_part = self.context_page.url.split("/search/")[-1].split("?")[0]
                keyword = urllib.parse.unquote(keyword_part)
                source_keyword_var.set(keyword)
                utils.logger.info(f"[DouYinCrawler.search_by_browser_from_current_page] 从URL提取关键词: {keyword}")
            except Exception as e:
                utils.logger.warning(f"[DouYinCrawler.search_by_browser_from_current_page] 无法从URL提取关键词: {e}")
        
        # 等待页面加载完成
        utils.logger.info("[DouYinCrawler.search_by_browser_from_current_page] 等待搜索结果页面加载...")
        await asyncio.sleep(3)
        
        # 确认当前页面是搜索结果页
        if "/search/" not in self.context_page.url:
            utils.logger.warning(f"[DouYinCrawler.search_by_browser_from_current_page] 当前URL不是搜索结果页: {self.context_page.url}")
        
        # 从搜索结果页面提取视频数据
        aweme_list = await self._extract_videos_from_search_page(keyword)
        
        if aweme_list:
            utils.logger.info(f"[DouYinCrawler.search_by_browser_from_current_page] 从页面提取到 {len(aweme_list)} 个视频ID")
            await self.batch_get_note_comments(aweme_list)
            return True
        else:
            utils.logger.warning(f"[DouYinCrawler.search_by_browser_from_current_page] 未从页面提取到视频")
            # 添加页面分析提示
            if config.KEEP_BROWSER_OPEN_ON_FAILURE:
                utils.logger.info("[DouYinCrawler.search_by_browser_from_current_page] 浏览器将保持打开，请检查页面元素结构")
                # 尝试获取页面HTML结构信息用于调试
                try:
                    page_title = await self.context_page.title()
                    page_url = self.context_page.url
                    utils.logger.info(f"[DouYinCrawler.search_by_browser_from_current_page] 页面标题: {page_title}")
                    utils.logger.info(f"[DouYinCrawler.search_by_browser_from_current_page] 页面URL: {page_url}")
                except Exception as e:
                    utils.logger.debug(f"[DouYinCrawler.search_by_browser_from_current_page] 获取页面信息失败: {e}")
            return False

    async def _extract_videos_from_search_page(self, keyword: str) -> List[str]:
        """
        从搜索结果页面点击视频链接，从弹出的视频中获取视频ID和信息
        """
        aweme_list: List[str] = []
        
        try:
            # 等待搜索结果加载
            await asyncio.sleep(3)
            
            # 等待搜索结果容器加载
            try:
                await self.context_page.wait_for_selector("#search-result-container", timeout=10000)
                utils.logger.info("[DouYinCrawler._extract_videos_from_search_page] 搜索结果容器已加载")
            except Exception as e:
                utils.logger.warning(f"[DouYinCrawler._extract_videos_from_search_page] 等待搜索结果容器超时: {e}")
            
            # 等待瀑布流容器加载
            try:
                await self.context_page.wait_for_selector("#waterFallScrollContainer", timeout=10000)
                utils.logger.info("[DouYinCrawler._extract_videos_from_search_page] 瀑布流容器已加载")
            except Exception as e:
                utils.logger.warning(f"[DouYinCrawler._extract_videos_from_search_page] 等待瀑布流容器超时: {e}")
            
            # 尝试多种方式查找视频结果项元素（根据实际页面结构）
            video_card_selectors = [
                "#waterFallScrollContainer div[id^='waterfall_item_']",  # 瀑布流中的视频项（优先）
                "#search-result-container div[id^='waterfall_item_']",  # 搜索结果容器中的视频项
                "div.st17zJnd",  # 使用class选择器
                "#waterFallScrollContainer div.st17zJnd",  # 瀑布流中使用class
                "#search-result-container div.st17zJnd",  # 搜索结果容器中使用class
                "//div[@id='waterFallScrollContainer']//div[starts-with(@id, 'waterfall_item_')]",  # XPath方式
                "//div[@id='search-result-container']//div[starts-with(@id, 'waterfall_item_')]",  # XPath方式
                "//div[contains(@class, 'st17zJnd')]",  # XPath class方式
                "//div[contains(@class, 'video-card')]//a",  # 旧的选择器（备用）
                "//a[contains(@href, '/video/')]",  # 旧的选择器（备用）
                "a[href*='/video/']",  # 旧的选择器（备用）
            ]
            
            video_elements = None
            selected_selector = None
            for selector in video_card_selectors:
                try:
                    if selector.startswith("//"):
                        elements = self.context_page.locator(f"xpath={selector}")
                    else:
                        elements = self.context_page.locator(selector)
                    
                    count = await elements.count()
                    if count > 0:
                        utils.logger.info(f"[DouYinCrawler._extract_videos_from_search_page] 找到 {count} 个视频链接 (selector: {selector})")
                        video_elements = elements
                        selected_selector = selector
                        break
                except Exception as e:
                    utils.logger.debug(f"[DouYinCrawler._extract_videos_from_search_page] 选择器 {selector} 失败: {e}")
                    continue
            
            if not video_elements or not selected_selector:
                utils.logger.warning("[DouYinCrawler._extract_videos_from_search_page] 未找到视频链接元素")
                return aweme_list
            
            # 获取要采集的视频数量
            max_count = min(await video_elements.count(), config.CRAWLER_MAX_NOTES_COUNT)
            utils.logger.info(f"[DouYinCrawler._extract_videos_from_search_page] 准备点击 {max_count} 个视频")
            
            # 记录当前页面URL，用于返回
            search_page_url = self.context_page.url
            
            # 逐个点击视频链接并提取信息
            for i in range(max_count):
                try:
                    if len(aweme_list) >= config.CRAWLER_MAX_NOTES_COUNT:
                        break
                    
                    utils.logger.info(f"[DouYinCrawler._extract_videos_from_search_page] 点击第 {i+1}/{max_count} 个视频")
                    
                    # 重新获取元素（因为页面可能变化）
                    if selected_selector.startswith("//"):
                        current_elements = self.context_page.locator(f"xpath={selected_selector}")
                    else:
                        current_elements = self.context_page.locator(selected_selector)
                    
                    if await current_elements.count() <= i:
                        utils.logger.warning(f"[DouYinCrawler._extract_videos_from_search_page] 视频元素数量不足，跳过")
                        break
                    
                    # 获取视频项元素
                    video_item_element = current_elements.nth(i)
                    
                    # 尝试从div的id中提取视频ID（如 waterfall_item_7489810900917046588）
                    aweme_id = None
                    import re
                    
                    # 方法1: 从div的id属性提取（waterfall_item_7489810900917046588）
                    item_id = await video_item_element.get_attribute("id")
                    if item_id and item_id.startswith("waterfall_item_"):
                        aweme_id = item_id.replace("waterfall_item_", "")
                        utils.logger.info(f"[DouYinCrawler._extract_videos_from_search_page] 从div id提取视频ID: {aweme_id}")
                    
                    # 方法2: 查找div内部的链接
                    if not aweme_id:
                        try:
                            # 查找div内部的a标签
                            link_element = video_item_element.locator("a[href*='/video/']").first
                            link_count = await link_element.count()
                            if link_count > 0:
                                href = await link_element.get_attribute("href")
                                if href:
                                    match = re.search(r'/video/(\d+)', href)
                                    if match:
                                        aweme_id = match.group(1)
                                        utils.logger.info(f"[DouYinCrawler._extract_videos_from_search_page] 从链接提取视频ID: {aweme_id}")
                        except Exception as e:
                            utils.logger.debug(f"[DouYinCrawler._extract_videos_from_search_page] 查找内部链接失败: {e}")
                    
                    # 方法3: 查找div内部的任何包含视频ID的元素
                    if not aweme_id:
                        try:
                            # 尝试从div的data属性或其他属性中提取
                            all_attrs = await video_item_element.evaluate("el => Array.from(el.attributes).map(a => ({name: a.name, value: a.value}))")
                            for attr in all_attrs:
                                match = re.search(r'(\d{19})', attr.get('value', ''))  # 抖音视频ID通常是19位数字
                                if match:
                                    aweme_id = match.group(1)
                                    utils.logger.info(f"[DouYinCrawler._extract_videos_from_search_page] 从属性 {attr.get('name')} 提取视频ID: {aweme_id}")
                                    break
                        except Exception as e:
                            utils.logger.debug(f"[DouYinCrawler._extract_videos_from_search_page] 从属性提取失败: {e}")
                    
                    # 如果已经提取到视频ID，检查是否已存在
                    if aweme_id and aweme_id in aweme_list:
                        utils.logger.info(f"[DouYinCrawler._extract_videos_from_search_page] 视频ID {aweme_id} 已存在，跳过")
                        continue
                    
                    # 如果未提取到视频ID，尝试点击后从URL获取
                    if not aweme_id:
                        utils.logger.warning(f"[DouYinCrawler._extract_videos_from_search_page] 第 {i+1} 个视频无法提取视频ID，尝试点击后从URL获取")
                    
                    utils.logger.info(f"[DouYinCrawler._extract_videos_from_search_page] 点击视频项，视频ID: {aweme_id if aweme_id else '待提取'}")
                    
                    # 点击视频项进入视频页面
                    try:
                        # 滚动到元素可见
                        await video_item_element.scroll_into_view_if_needed()
                        await asyncio.sleep(0.5)
                        
                        # 点击视频项（可能会打开新标签页或跳转）
                        await video_item_element.click(timeout=5000)
                        await asyncio.sleep(2)  # 等待视频加载或页面跳转
                        
                        # 如果之前未提取到视频ID，现在尝试从URL获取
                        if not aweme_id:
                            current_url = self.context_page.url
                            match = re.search(r'/video/(\d+)', current_url)
                            if match:
                                aweme_id = match.group(1)
                                utils.logger.info(f"[DouYinCrawler._extract_videos_from_search_page] 从跳转后的URL提取视频ID: {aweme_id}")
                            else:
                                utils.logger.warning(f"[DouYinCrawler._extract_videos_from_search_page] 点击后仍无法提取视频ID，当前URL: {current_url}")
                                # 返回搜索结果页
                                await self.context_page.goto(search_page_url)
                                await asyncio.sleep(1)
                                continue
                        
                        # 检查是否跳转到视频页面或弹出视频
                        current_url = self.context_page.url
                        utils.logger.info(f"[DouYinCrawler._extract_videos_from_search_page] 当前URL: {current_url}")
                        
                        # 如果URL包含视频ID，说明跳转到了视频页面
                        if aweme_id and (aweme_id in current_url or '/video/' in current_url):
                            utils.logger.info(f"[DouYinCrawler._extract_videos_from_search_page] 已跳转到视频页面")
                            
                            # 等待视频页面加载完成
                            await asyncio.sleep(2)
                            
                            # 尝试从页面获取视频详细信息
                            try:
                                # 调用API获取视频详情（使用当前页面的cookies）
                                aweme_detail = await self.dy_client.get_video_by_id(aweme_id)
                                if aweme_detail:
                                    await douyin_store.update_douyin_aweme(aweme_item=aweme_detail)
                                    await self.get_aweme_media(aweme_item=aweme_detail)
                                    aweme_list.append(aweme_id)
                                    utils.logger.info(f"[DouYinCrawler._extract_videos_from_search_page] 成功获取视频详情: {aweme_id}")
                                else:
                                    # 如果API获取失败，至少保存视频ID
                                    aweme_list.append(aweme_id)
                                    utils.logger.warning(f"[DouYinCrawler._extract_videos_from_search_page] API获取失败，仅保存视频ID: {aweme_id}")
                            except Exception as e:
                                utils.logger.warning(f"[DouYinCrawler._extract_videos_from_search_page] 获取视频详情失败: {e}，仅保存视频ID")
                                if aweme_id:
                                    aweme_list.append(aweme_id)
                            
                            # 返回搜索结果页面
                            utils.logger.info("[DouYinCrawler._extract_videos_from_search_page] 返回搜索结果页面")
                            await self.context_page.goto(search_page_url, wait_until="domcontentloaded", timeout=30000)
                            await asyncio.sleep(2)  # 等待页面加载
                            
                            # 更新dy_client的playwright_page引用，确保评论获取时使用正确的页面
                            if self.dy_client:
                                self.dy_client.playwright_page = self.context_page
                            
                        elif aweme_id:
                            # 可能是弹窗形式，URL没有变化，但视频已显示
                            utils.logger.info("[DouYinCrawler._extract_videos_from_search_page] 视频可能以弹窗形式显示，尝试获取详情")
                            
                            # 尝试从页面获取视频详细信息
                            try:
                                aweme_detail = await self.dy_client.get_video_by_id(aweme_id)
                                if aweme_detail:
                                    await douyin_store.update_douyin_aweme(aweme_item=aweme_detail)
                                    await self.get_aweme_media(aweme_item=aweme_detail)
                                    aweme_list.append(aweme_id)
                                    utils.logger.info(f"[DouYinCrawler._extract_videos_from_search_page] 成功获取视频详情: {aweme_id}")
                                else:
                                    aweme_list.append(aweme_id)
                                    utils.logger.warning(f"[DouYinCrawler._extract_videos_from_search_page] API获取失败，仅保存视频ID: {aweme_id}")
                            except Exception as e:
                                utils.logger.warning(f"[DouYinCrawler._extract_videos_from_search_page] 获取视频详情失败: {e}，仅保存视频ID")
                                aweme_list.append(aweme_id)
                            
                            # 尝试按ESC关闭弹窗
                            try:
                                await self.context_page.keyboard.press("Escape")
                                await asyncio.sleep(1)
                            except Exception:
                                pass
                        else:
                            # 无法提取视频ID，返回搜索结果页
                            utils.logger.warning("[DouYinCrawler._extract_videos_from_search_page] 无法提取视频ID，返回搜索结果页")
                            await self.context_page.goto(search_page_url)
                            await asyncio.sleep(1)
                            
                    except Exception as e:
                        utils.logger.error(f"[DouYinCrawler._extract_videos_from_search_page] 点击视频失败: {e}")
                        # 即使点击失败，也保存视频ID（如果已提取）
                        if aweme_id and aweme_id not in aweme_list:
                            aweme_list.append(aweme_id)
                    
                    # 采集间隔
                    if i < max_count - 1:
                        await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                    
                except Exception as e:
                    utils.logger.error(f"[DouYinCrawler._extract_videos_from_search_page] 处理第 {i+1} 个视频时出错: {e}")
                    import traceback
                    utils.logger.debug(f"[DouYinCrawler._extract_videos_from_search_page] 错误详情: {traceback.format_exc()}")
                    continue
            
            utils.logger.info(f"[DouYinCrawler._extract_videos_from_search_page] 共提取到 {len(aweme_list)} 个视频ID")
            
        except Exception as e:
            utils.logger.error(f"[DouYinCrawler._extract_videos_from_search_page] 提取视频失败: {e}")
            import traceback
            utils.logger.error(f"[DouYinCrawler._extract_videos_from_search_page] 错误详情: {traceback.format_exc()}")
        
        return aweme_list

    async def get_specified_awemes(self):
        """Get the information and comments of the specified post from URLs or IDs"""
        utils.logger.info("[DouYinCrawler.get_specified_awemes] Parsing video URLs...")
        aweme_id_list = []
        for video_url in config.DY_SPECIFIED_ID_LIST:
            try:
                video_info = parse_video_info_from_url(video_url)

                # 处理短链接
                if video_info.url_type == "short":
                    utils.logger.info(f"[DouYinCrawler.get_specified_awemes] Resolving short link: {video_url}")
                    resolved_url = await self.dy_client.resolve_short_url(video_url)
                    if resolved_url:
                        # 从解析后的URL中提取视频ID
                        video_info = parse_video_info_from_url(resolved_url)
                        utils.logger.info(f"[DouYinCrawler.get_specified_awemes] Short link resolved to aweme ID: {video_info.aweme_id}")
                    else:
                        utils.logger.error(f"[DouYinCrawler.get_specified_awemes] Failed to resolve short link: {video_url}")
                        continue

                aweme_id_list.append(video_info.aweme_id)
                utils.logger.info(f"[DouYinCrawler.get_specified_awemes] Parsed aweme ID: {video_info.aweme_id} from {video_url}")
            except ValueError as e:
                utils.logger.error(f"[DouYinCrawler.get_specified_awemes] Failed to parse video URL: {e}")
                continue

        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list = [self.get_aweme_detail(aweme_id=aweme_id, semaphore=semaphore) for aweme_id in aweme_id_list]
        aweme_details = await asyncio.gather(*task_list)
        for aweme_detail in aweme_details:
            if aweme_detail is not None:
                await douyin_store.update_douyin_aweme(aweme_item=aweme_detail)
                await self.get_aweme_media(aweme_item=aweme_detail)
        await self.batch_get_note_comments(aweme_id_list)

    async def get_aweme_detail(self, aweme_id: str, semaphore: asyncio.Semaphore) -> Any:
        """Get note detail"""
        async with semaphore:
            try:
                result = await self.dy_client.get_video_by_id(aweme_id)
                # Sleep after fetching aweme detail
                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                utils.logger.info(f"[DouYinCrawler.get_aweme_detail] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after fetching aweme {aweme_id}")
                return result
            except DataFetchError as ex:
                utils.logger.error(f"[DouYinCrawler.get_aweme_detail] Get aweme detail error: {ex}")
                return None
            except KeyError as ex:
                utils.logger.error(f"[DouYinCrawler.get_aweme_detail] have not fund note detail aweme_id:{aweme_id}, err: {ex}")
                return None

    async def batch_get_note_comments(self, aweme_list: List[str]) -> None:
        """
        Batch get note comments
        """
        if not config.ENABLE_GET_COMMENTS:
            utils.logger.info(f"[DouYinCrawler.batch_get_note_comments] Crawling comment mode is not enabled")
            return

        task_list: List[Task] = []
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        for aweme_id in aweme_list:
            task = asyncio.create_task(self.get_comments(aweme_id, semaphore), name=aweme_id)
            task_list.append(task)
        if len(task_list) > 0:
            await asyncio.wait(task_list)

    async def get_comments(self, aweme_id: str, semaphore: asyncio.Semaphore) -> None:
        async with semaphore:
            try:
                # 将关键词列表传递给 get_aweme_all_comments 方法
                # Use fixed crawling interval
                crawl_interval = config.CRAWLER_MAX_SLEEP_SEC
                await self.dy_client.get_aweme_all_comments(
                    aweme_id=aweme_id,
                    crawl_interval=crawl_interval,
                    is_fetch_sub_comments=config.ENABLE_GET_SUB_COMMENTS,
                    callback=douyin_store.batch_update_dy_aweme_comments,
                    max_count=config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES,
                )
                # Sleep after fetching comments
                await asyncio.sleep(crawl_interval)
                utils.logger.info(f"[DouYinCrawler.get_comments] Sleeping for {crawl_interval} seconds after fetching comments for aweme {aweme_id}")
                utils.logger.info(f"[DouYinCrawler.get_comments] aweme_id: {aweme_id} comments have all been obtained and filtered ...")
            except TargetClosedError as e:
                utils.logger.error(f"[DouYinCrawler.get_comments] aweme_id: {aweme_id} 页面已关闭，无法获取评论: {e}")
            except DataFetchError as e:
                utils.logger.error(f"[DouYinCrawler.get_comments] aweme_id: {aweme_id} get comments failed, error: {e}")
            except Exception as e:
                utils.logger.error(f"[DouYinCrawler.get_comments] aweme_id: {aweme_id} get comments failed with unexpected error: {e}")

    async def get_creators_and_videos(self) -> None:
        """
        Get the information and videos of the specified creator from URLs or IDs
        """
        utils.logger.info("[DouYinCrawler.get_creators_and_videos] Begin get douyin creators")
        utils.logger.info("[DouYinCrawler.get_creators_and_videos] Parsing creator URLs...")

        for creator_url in config.DY_CREATOR_ID_LIST:
            try:
                creator_info_parsed = parse_creator_info_from_url(creator_url)
                user_id = creator_info_parsed.sec_user_id
                utils.logger.info(f"[DouYinCrawler.get_creators_and_videos] Parsed sec_user_id: {user_id} from {creator_url}")
            except ValueError as e:
                utils.logger.error(f"[DouYinCrawler.get_creators_and_videos] Failed to parse creator URL: {e}")
                continue

            creator_info: Dict = await self.dy_client.get_user_info(user_id)
            if creator_info:
                await douyin_store.save_creator(user_id, creator=creator_info)

            # Get all video information of the creator
            all_video_list = await self.dy_client.get_all_user_aweme_posts(sec_user_id=user_id, callback=self.fetch_creator_video_detail)

            video_ids = [video_item.get("aweme_id") for video_item in all_video_list]
            await self.batch_get_note_comments(video_ids)

    async def fetch_creator_video_detail(self, video_list: List[Dict]):
        """
        Concurrently obtain the specified post list and save the data
        """
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list = [self.get_aweme_detail(post_item.get("aweme_id"), semaphore) for post_item in video_list]

        note_details = await asyncio.gather(*task_list)
        for aweme_item in note_details:
            if aweme_item is not None:
                await douyin_store.update_douyin_aweme(aweme_item=aweme_item)
                await self.get_aweme_media(aweme_item=aweme_item)

    async def create_douyin_client(self, httpx_proxy: Optional[str]) -> DouYinClient:
        """Create douyin client"""
        cookie_str, cookie_dict = utils.convert_cookies(await self.browser_context.cookies())  # type: ignore
        douyin_client = DouYinClient(
            proxy=httpx_proxy,
            headers={
                "User-Agent": await self.context_page.evaluate("() => navigator.userAgent"),
                "Cookie": cookie_str,
                "Host": "www.douyin.com",
                "Origin": "https://www.douyin.com/",
                "Referer": "https://www.douyin.com/",
                "Content-Type": "application/json;charset=UTF-8",
            },
            playwright_page=self.context_page,
            cookie_dict=cookie_dict,
            proxy_ip_pool=self.ip_proxy_pool,  # 传递代理池用于自动刷新
        )
        # 保存browser_context引用，以便在页面关闭时使用
        douyin_client._browser_context = self.browser_context  # type: ignore
        return douyin_client

    async def launch_browser(
        self,
        chromium: BrowserType,
        playwright_proxy: Optional[Dict],
        user_agent: Optional[str],
        headless: bool = True,
    ) -> BrowserContext:
        """Launch browser and create browser context"""
        if config.SAVE_LOGIN_STATE:
            user_data_dir = os.path.join(os.getcwd(), "browser_data", config.USER_DATA_DIR % config.PLATFORM)  # type: ignore
            browser_context = await chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                accept_downloads=True,
                headless=headless,
                proxy=playwright_proxy,  # type: ignore
                viewport={
                    "width": 1920,
                    "height": 1080
                },
                user_agent=user_agent,
            )  # type: ignore
            return browser_context
        else:
            browser = await chromium.launch(headless=headless, proxy=playwright_proxy)  # type: ignore
            browser_context = await browser.new_context(viewport={"width": 1920, "height": 1080}, user_agent=user_agent)
            return browser_context

    async def launch_browser_with_cdp(
        self,
        playwright: Playwright,
        playwright_proxy: Optional[Dict],
        user_agent: Optional[str],
        headless: bool = True,
    ) -> BrowserContext:
        """
        使用CDP模式启动浏览器
        """
        try:
            self.cdp_manager = CDPBrowserManager()
            browser_context = await self.cdp_manager.launch_and_connect(
                playwright=playwright,
                playwright_proxy=playwright_proxy,
                user_agent=user_agent,
                headless=headless,
            )

            # 添加反检测脚本
            await self.cdp_manager.add_stealth_script()

            # 显示浏览器信息
            browser_info = await self.cdp_manager.get_browser_info()
            utils.logger.info(f"[DouYinCrawler] CDP浏览器信息: {browser_info}")

            return browser_context

        except Exception as e:
            utils.logger.error(f"[DouYinCrawler] CDP模式启动失败，回退到标准模式: {e}")
            # 回退到标准模式
            chromium = playwright.chromium
            return await self.launch_browser(chromium, playwright_proxy, user_agent, headless)

    async def close(self) -> None:
        """Close browser context"""
        # 如果使用CDP模式，需要特殊处理
        if self.cdp_manager:
            await self.cdp_manager.cleanup()
            self.cdp_manager = None
        else:
            await self.browser_context.close()
        utils.logger.info("[DouYinCrawler.close] Browser context closed ...")

    async def get_aweme_media(self, aweme_item: Dict):
        """
        获取抖音媒体，自动判断媒体类型是短视频还是帖子图片并下载

        Args:
            aweme_item (Dict): 抖音作品详情
        """
        if not config.ENABLE_GET_MEIDAS:
            utils.logger.info(f"[DouYinCrawler.get_aweme_media] Crawling image mode is not enabled")
            return
        # 笔记 urls 列表，若为短视频类型则返回为空列表
        note_download_url: List[str] = douyin_store._extract_note_image_list(aweme_item)
        # 视频 url，永远存在，但为短视频类型时的文件其实是音频文件
        video_download_url: str = douyin_store._extract_video_download_url(aweme_item)
        # TODO: 抖音并没采用音视频分离的策略，故音频可从原视频中分离，暂不提取
        if note_download_url:
            await self.get_aweme_images(aweme_item)
        else:
            await self.get_aweme_video(aweme_item)

    async def get_aweme_images(self, aweme_item: Dict):
        """
        get aweme images. please use get_aweme_media

        Args:
            aweme_item (Dict): 抖音作品详情
        """
        if not config.ENABLE_GET_MEIDAS:
            return
        aweme_id = aweme_item.get("aweme_id")
        # 笔记 urls 列表，若为短视频类型则返回为空列表
        note_download_url: List[str] = douyin_store._extract_note_image_list(aweme_item)

        if not note_download_url:
            return
        picNum = 0
        for url in note_download_url:
            if not url:
                continue
            content = await self.dy_client.get_aweme_media(url)
            await asyncio.sleep(random.random())
            if content is None:
                continue
            extension_file_name = f"{picNum:>03d}.jpeg"
            picNum += 1
            await douyin_store.update_dy_aweme_image(aweme_id, content, extension_file_name)

    async def get_aweme_video(self, aweme_item: Dict):
        """
        get aweme videos. please use get_aweme_media

        Args:
            aweme_item (Dict): 抖音作品详情
        """
        if not config.ENABLE_GET_MEIDAS:
            return
        aweme_id = aweme_item.get("aweme_id")

        # 视频 url，永远存在，但为短视频类型时的文件其实是音频文件
        video_download_url: str = douyin_store._extract_video_download_url(aweme_item)

        if not video_download_url:
            return
        content = await self.dy_client.get_aweme_media(video_download_url)
        await asyncio.sleep(random.random())
        if content is None:
            return
        extension_file_name = f"video.mp4"
        await douyin_store.update_dy_aweme_video(aweme_id, content, extension_file_name)
