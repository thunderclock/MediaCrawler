# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/xhs/core.py
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
import pathlib
import random
from asyncio import Task
from datetime import datetime
from typing import Dict, List, Optional

from playwright.async_api import (
    BrowserContext,
    BrowserType,
    Page,
    Playwright,
    async_playwright,
)
from tenacity import RetryError

import config
from base.base_crawler import AbstractCrawler
from config import CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES
from model.m_xiaohongshu import NoteUrlInfo, CreatorUrlInfo
from proxy.proxy_ip_pool import IpInfoModel, create_ip_pool
from store import xhs as xhs_store
from tools import utils
from tools.cdp_browser import CDPBrowserManager
from var import crawler_type_var, source_keyword_var

from .client import XiaoHongShuClient
from .exception import DataFetchError
from .field import SearchSortType
from .help import parse_note_info_from_note_url, parse_creator_info_from_url, get_search_id
from .login import XiaoHongShuLogin


class XiaoHongShuCrawler(AbstractCrawler):
    context_page: Page
    xhs_client: XiaoHongShuClient
    browser_context: BrowserContext
    cdp_manager: Optional[CDPBrowserManager]

    def __init__(self) -> None:
        self.index_url = "https://www.xiaohongshu.com"
        # self.user_agent = utils.get_user_agent()
        self.user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        self.cdp_manager = None
        self.ip_proxy_pool = None  # Proxy IP pool for automatic proxy refresh

    async def start(self) -> None:
        playwright_proxy_format, httpx_proxy_format = None, None
        if config.ENABLE_IP_PROXY:
            self.ip_proxy_pool = await create_ip_pool(config.IP_PROXY_POOL_COUNT, enable_validate_ip=True)
            ip_proxy_info: IpInfoModel = await self.ip_proxy_pool.get_proxy()
            playwright_proxy_format, httpx_proxy_format = utils.format_proxy_info(ip_proxy_info)

        async with async_playwright() as playwright:
            # Choose launch mode based on configuration
            if config.ENABLE_CDP_MODE:
                utils.logger.info("[XiaoHongShuCrawler] Launching browser using CDP mode")
                self.browser_context = await self.launch_browser_with_cdp(
                    playwright,
                    playwright_proxy_format,
                    self.user_agent,
                    headless=config.CDP_HEADLESS,
                )
            else:
                utils.logger.info("[XiaoHongShuCrawler] Launching browser using standard mode")
                # Launch a browser context.
                chromium = playwright.chromium
                self.browser_context = await self.launch_browser(
                    chromium,
                    playwright_proxy_format,
                    self.user_agent,
                    headless=config.HEADLESS,
                )
                # stealth.min.js is a js script to prevent the website from detecting the crawler.
                await self.browser_context.add_init_script(path="libs/stealth.min.js")

            self.context_page = await self.browser_context.new_page()
            await self.context_page.goto(self.index_url)

            # Create a client to interact with the Xiaohongshu website.
            self.xhs_client = await self.create_xhs_client(httpx_proxy_format)
            if not await self.xhs_client.pong():
                login_obj = XiaoHongShuLogin(
                    login_type=config.LOGIN_TYPE,
                    login_phone="",  # input your phone number
                    browser_context=self.browser_context,
                    context_page=self.context_page,
                    cookie_str=config.COOKIES,
                )
                await login_obj.begin()
                await self.xhs_client.update_cookies(browser_context=self.browser_context)

            # 在开始爬取前，访问一次首页激活Cookie，避免验证码问题
            if config.CRAWLER_TYPE == "search":
                try:
                    utils.logger.info("[XiaoHongShuCrawler] 访问首页激活Cookie...")
                    await self.context_page.goto("https://www.xiaohongshu.com", wait_until="domcontentloaded", timeout=10000)
                    await asyncio.sleep(2)  # 等待页面加载完成
                    # 更新Cookie以确保API请求使用最新的Cookie
                    await self.xhs_client.update_cookies(browser_context=self.browser_context)
                    utils.logger.info("[XiaoHongShuCrawler] Cookie已更新，等待30秒让账号状态稳定...")
                    await asyncio.sleep(30)  # 等待30秒让账号状态稳定，避免触发验证码
                    utils.logger.info("[XiaoHongShuCrawler] 账号状态已稳定，开始搜索...")
                except Exception as e:
                    utils.logger.warning(f"[XiaoHongShuCrawler] 访问首页失败，等待30秒后开始搜索: {e}")
                    # 即使访问首页失败，也更新一次Cookie，然后等待一段时间
                    await self.xhs_client.update_cookies(browser_context=self.browser_context)
                    utils.logger.info("[XiaoHongShuCrawler] 等待30秒让账号状态稳定...")
                    await asyncio.sleep(30)
            
            crawler_type_var.set(config.CRAWLER_TYPE)
            if config.CRAWLER_TYPE == "search":
                # Search for notes and retrieve their comment information.
                await self.search()
            elif config.CRAWLER_TYPE == "detail":
                # Get the information and comments of the specified post
                await self.get_specified_notes()
            elif config.CRAWLER_TYPE == "creator":
                # Get creator's information and their notes and comments
                await self.get_creators_and_notes()
            else:
                pass

            utils.logger.info("[XiaoHongShuCrawler.start] Xhs Crawler finished ...")

    async def search(self) -> None:
        """Search for notes and retrieve their comment information."""
<<<<<<< HEAD
        utils.logger.info("[XiaoHongShuCrawler.search] Begin search xiaohongshu keywords")
        
        # 检查是否使用浏览器自动化模式
        if config.ENABLE_BROWSER_AUTOMATION_MODE:
            utils.logger.info("[XiaoHongShuCrawler.search] 使用浏览器自动化模式（避免API验证码）")
            await self.search_by_browser()
            return
        
        # 原有的API搜索模式
        xhs_limit_count = 20  # xhs limit page fixed value
=======
        utils.logger.info("[XiaoHongShuCrawler.search] Begin search Xiaohongshu keywords")
        xhs_limit_count = 20  # Xiaohongshu limit page fixed value
>>>>>>> origin/main
        if config.CRAWLER_MAX_NOTES_COUNT < xhs_limit_count:
            config.CRAWLER_MAX_NOTES_COUNT = xhs_limit_count
        start_page = config.START_PAGE
        for keyword in config.KEYWORDS.split(","):
            source_keyword_var.set(keyword)
            utils.logger.info(f"[XiaoHongShuCrawler.search] Current search keyword: {keyword}")
            page = 1
            search_id = get_search_id()
            while (page - start_page + 1) * xhs_limit_count <= config.CRAWLER_MAX_NOTES_COUNT:
                if page < start_page:
                    utils.logger.info(f"[XiaoHongShuCrawler.search] Skip page {page}")
                    page += 1
                    continue

                try:
<<<<<<< HEAD
                    utils.logger.info(f"[XiaoHongShuCrawler.search] search xhs keyword: {keyword}, page: {page}")
                    # 首次搜索前增加额外延迟，让账号状态更稳定
                    if page == 1:
                        utils.logger.info(f"[XiaoHongShuCrawler.search] 首次搜索，额外等待15秒...")
                        await asyncio.sleep(15)
=======
                    utils.logger.info(f"[XiaoHongShuCrawler.search] search Xiaohongshu keyword: {keyword}, page: {page}")
>>>>>>> origin/main
                    note_ids: List[str] = []
                    xsec_tokens: List[str] = []
                    notes_res = await self.xhs_client.get_note_by_keyword(
                        keyword=keyword,
                        search_id=search_id,
                        page=page,
                        sort=(SearchSortType(config.SORT_TYPE) if config.SORT_TYPE != "" else SearchSortType.GENERAL),
                    )
                    utils.logger.info(f"[XiaoHongShuCrawler.search] Search notes response: {notes_res}")
                    if not notes_res or not notes_res.get("has_more", False):
                        utils.logger.info("[XiaoHongShuCrawler.search] No more content!")
                        break
                    semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
                    task_list = [
                        self.get_note_detail_async_task(
                            note_id=post_item.get("id"),
                            xsec_source=post_item.get("xsec_source"),
                            xsec_token=post_item.get("xsec_token"),
                            semaphore=semaphore,
                        ) for post_item in notes_res.get("items", {}) if post_item.get("model_type") not in ("rec_query", "hot_query")
                    ]
                    note_details = await asyncio.gather(*task_list)
                    for note_detail in note_details:
                        if note_detail:
                            await xhs_store.update_xhs_note(note_detail)
                            await self.get_notice_media(note_detail)
                            note_ids.append(note_detail.get("note_id"))
                            xsec_tokens.append(note_detail.get("xsec_token"))
                    page += 1
                    utils.logger.info(f"[XiaoHongShuCrawler.search] Note details: {note_details}")
                    await self.batch_get_note_comments(note_ids, xsec_tokens)

                    # Sleep after each page navigation
                    await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                    utils.logger.info(f"[XiaoHongShuCrawler.search] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after page {page-1}")
                except DataFetchError:
                    utils.logger.error("[XiaoHongShuCrawler.search] Get note detail error")
                    break

    async def search_by_browser(self) -> None:
        """基于浏览器自动化的搜索模式，完全通过浏览器操作，避免API验证码"""
        utils.logger.info("[XiaoHongShuCrawler.search_by_browser] 开始使用浏览器自动化搜索...")
        
        for keyword in config.KEYWORDS.split(","):
            source_keyword_var.set(keyword)
            utils.logger.info(f"[XiaoHongShuCrawler.search_by_browser] 搜索关键词: {keyword}")
            
            try:
                # 构建搜索URL
                search_url = f"https://www.xiaohongshu.com/search_result?keyword={keyword}"
                if config.SORT_TYPE:
                    sort_map = {
                        "popularity_descending": "popularity_descending",
                        "time_descending": "time_descending",
                        "general": "general"
                    }
                    sort_value = sort_map.get(config.SORT_TYPE, "general")
                    search_url += f"&sort={sort_value}"
                
                utils.logger.info(f"[XiaoHongShuCrawler.search_by_browser] 访问搜索页面: {search_url}")
                await self.context_page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(5)  # 等待页面加载和结果渲染
                
                # 等待搜索结果加载
                try:
                    await self.context_page.wait_for_selector(".feeds-page, .note-item, [class*='note']", timeout=15000)
                except:
                    utils.logger.warning("[XiaoHongShuCrawler.search_by_browser] 未找到搜索结果容器，继续尝试...")
                
                # 从页面中提取笔记信息
                note_items = await self.extract_notes_from_search_page(keyword)
                
                if not note_items or len(note_items) == 0:
                    utils.logger.warning(f"[XiaoHongShuCrawler.search_by_browser] 未找到笔记，尝试从页面链接提取...")
                    # 备选方案：从页面链接中提取
                    note_items = await self.extract_note_links_from_page()
                
                if not note_items:
                    utils.logger.error(f"[XiaoHongShuCrawler.search_by_browser] 无法从页面提取笔记信息")
                    continue
                
                utils.logger.info(f"[XiaoHongShuCrawler.search_by_browser] 找到 {len(note_items)} 条笔记")
                
                # 限制数量
                max_count = min(config.CRAWLER_MAX_NOTES_COUNT, len(note_items))
                note_items = note_items[:max_count]
                
                # 获取笔记详情
                note_ids = []
                xsec_tokens = []
                semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
                
                task_list = [
                    self.get_note_detail_async_task(
                        note_id=item.get("note_id") or item.get("id"),
                        xsec_source=item.get("xsec_source", "pc_search"),
                        xsec_token=item.get("xsec_token", ""),
                        semaphore=semaphore,
                    ) for item in note_items
                ]
                
                note_details = await asyncio.gather(*task_list)
                for note_detail in note_details:
                    if note_detail:
                        await xhs_store.update_xhs_note(note_detail)
                        await self.get_notice_media(note_detail)
                        note_ids.append(note_detail.get("note_id"))
                        xsec_tokens.append(note_detail.get("xsec_token"))
                
                # 获取评论
                await self.batch_get_note_comments(note_ids, xsec_tokens)
                
                utils.logger.info(f"[XiaoHongShuCrawler.search_by_browser] 关键词 '{keyword}' 爬取完成")
                
            except Exception as e:
                utils.logger.error(f"[XiaoHongShuCrawler.search_by_browser] 搜索 '{keyword}' 失败: {e}")
                continue

    async def extract_notes_from_search_page(self, keyword: str) -> List[Dict]:
        """从搜索页面的window.__INITIAL_STATE__中提取笔记信息"""
        try:
            # 执行JavaScript提取window.__INITIAL_STATE__
            initial_state = await self.context_page.evaluate("""
                () => {
                    if (window.__INITIAL_STATE__) {
                        return JSON.stringify(window.__INITIAL_STATE__);
                    }
                    return null;
                }
            """)
            
            if not initial_state:
                return []
            
            import json
            import humps
            state = json.loads(initial_state.replace(":undefined", ":null"))
            state = humps.decamelize(state)
            
            # 从state中提取搜索结果
            notes = []
            # 小红书搜索结果可能在不同的路径下
            if "searchResult" in state and "notes" in state["searchResult"]:
                notes = state["searchResult"]["notes"]
            elif "search" in state and "notes" in state["search"]:
                notes = state["search"]["notes"]
            
            result = []
            for note in notes:
                if isinstance(note, dict):
                    result.append({
                        "note_id": note.get("noteId") or note.get("id") or note.get("note_id"),
                        "xsec_source": note.get("xsecSource") or note.get("xsec_source", "pc_search"),
                        "xsec_token": note.get("xsecToken") or note.get("xsec_token", ""),
                        "id": note.get("noteId") or note.get("id") or note.get("note_id"),
                    })
            
            return result
            
        except Exception as e:
            utils.logger.error(f"[XiaoHongShuCrawler.extract_notes_from_search_page] 提取失败: {e}")
            return []

    async def extract_note_links_from_page(self) -> List[Dict]:
        """从页面链接中提取笔记ID"""
        try:
            # 查找所有笔记链接
            note_links = await self.context_page.evaluate("""
                () => {
                    const links = [];
                    // 查找所有包含 /explore/ 的链接
                    document.querySelectorAll('a[href*="/explore/"]').forEach(link => {
                        const href = link.getAttribute('href');
                        if (href) {
                            const match = href.match(/\/explore\/([a-zA-Z0-9]+)/);
                            if (match) {
                                const noteId = match[1];
                                // 从URL参数中提取xsec_token和xsec_source
                                const urlParams = new URLSearchParams(href.split('?')[1] || '');
                                links.push({
                                    note_id: noteId,
                                    xsec_source: urlParams.get('xsec_source') || 'pc_search',
                                    xsec_token: urlParams.get('xsec_token') || '',
                                    id: noteId
                                });
                            }
                        }
                    });
                    return links;
                }
            """)
            
            # 去重
            seen = set()
            unique_links = []
            for link in note_links:
                note_id = link.get("note_id")
                if note_id and note_id not in seen:
                    seen.add(note_id)
                    unique_links.append(link)
            
            return unique_links
            
        except Exception as e:
            utils.logger.error(f"[XiaoHongShuCrawler.extract_note_links_from_page] 提取链接失败: {e}")
            return []

    async def get_creators_and_notes(self) -> None:
        """Get creator's notes and retrieve their comment information."""
        utils.logger.info("[XiaoHongShuCrawler.get_creators_and_notes] Begin get Xiaohongshu creators")
        for creator_url in config.XHS_CREATOR_ID_LIST:
            try:
                # Parse creator URL to get user_id and security tokens
                creator_info: CreatorUrlInfo = parse_creator_info_from_url(creator_url)
                utils.logger.info(f"[XiaoHongShuCrawler.get_creators_and_notes] Parse creator URL info: {creator_info}")
                user_id = creator_info.user_id

                # get creator detail info from web html content
                createor_info: Dict = await self.xhs_client.get_creator_info(
                    user_id=user_id,
                    xsec_token=creator_info.xsec_token,
                    xsec_source=creator_info.xsec_source
                )
                if createor_info:
                    await xhs_store.save_creator(user_id, creator=createor_info)
            except ValueError as e:
                utils.logger.error(f"[XiaoHongShuCrawler.get_creators_and_notes] Failed to parse creator URL: {e}")
                continue

            # Use fixed crawling interval
            crawl_interval = config.CRAWLER_MAX_SLEEP_SEC
            # Get all note information of the creator
            all_notes_list = await self.xhs_client.get_all_notes_by_creator(
                user_id=user_id,
                crawl_interval=crawl_interval,
                callback=self.fetch_creator_notes_detail,
                xsec_token=creator_info.xsec_token,
                xsec_source=creator_info.xsec_source,
            )

            note_ids = []
            xsec_tokens = []
            for note_item in all_notes_list:
                note_ids.append(note_item.get("note_id"))
                xsec_tokens.append(note_item.get("xsec_token"))
            await self.batch_get_note_comments(note_ids, xsec_tokens)

    async def fetch_creator_notes_detail(self, note_list: List[Dict]):
        """Concurrently obtain the specified post list and save the data"""
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list = [
            self.get_note_detail_async_task(
                note_id=post_item.get("note_id"),
                xsec_source=post_item.get("xsec_source"),
                xsec_token=post_item.get("xsec_token"),
                semaphore=semaphore,
            ) for post_item in note_list
        ]

        note_details = await asyncio.gather(*task_list)
        for note_detail in note_details:
            if note_detail:
                await xhs_store.update_xhs_note(note_detail)
                await self.get_notice_media(note_detail)

    async def get_specified_notes(self):
        """Get the information and comments of the specified post

        Note: Must specify note_id, xsec_source, xsec_token
        """
        get_note_detail_task_list = []
        for full_note_url in config.XHS_SPECIFIED_NOTE_URL_LIST:
            note_url_info: NoteUrlInfo = parse_note_info_from_note_url(full_note_url)
            utils.logger.info(f"[XiaoHongShuCrawler.get_specified_notes] Parse note url info: {note_url_info}")
            crawler_task = self.get_note_detail_async_task(
                note_id=note_url_info.note_id,
                xsec_source=note_url_info.xsec_source,
                xsec_token=note_url_info.xsec_token,
                semaphore=asyncio.Semaphore(config.MAX_CONCURRENCY_NUM),
            )
            get_note_detail_task_list.append(crawler_task)

        need_get_comment_note_ids = []
        xsec_tokens = []
        note_details = await asyncio.gather(*get_note_detail_task_list)
        for note_detail in note_details:
            if note_detail:
                need_get_comment_note_ids.append(note_detail.get("note_id", ""))
                xsec_tokens.append(note_detail.get("xsec_token", ""))
                await xhs_store.update_xhs_note(note_detail)
                await self.get_notice_media(note_detail)
        await self.batch_get_note_comments(need_get_comment_note_ids, xsec_tokens)

    async def get_note_detail_async_task(
        self,
        note_id: str,
        xsec_source: str,
        xsec_token: str,
        semaphore: asyncio.Semaphore,
    ) -> Optional[Dict]:
        """Get note detail

        Args:
            note_id:
            xsec_source:
            xsec_token:
            semaphore:

        Returns:
            Dict: note detail
        """
        note_detail = None
        utils.logger.info(f"[get_note_detail_async_task] Begin get note detail, note_id: {note_id}")
        async with semaphore:
            try:
<<<<<<< HEAD
                utils.logger.info(f"[get_note_detail_async_task] Begin get note detail, note_id: {note_id}")
                
                # 浏览器自动化模式下，直接通过浏览器访问页面
                if config.ENABLE_BROWSER_AUTOMATION_MODE:
                    note_detail = await self.get_note_detail_by_browser(note_id, xsec_source, xsec_token)
                else:
                    note_detail = await self.xhs_client.get_note_by_id_from_html(note_id, xsec_source, xsec_token, enable_cookie=True)
                
=======
                try:
                    note_detail = await self.xhs_client.get_note_by_id(note_id, xsec_source, xsec_token)
                except RetryError:
                    pass

>>>>>>> origin/main
                if not note_detail:
                    note_detail = await self.xhs_client.get_note_by_id_from_html(note_id, xsec_source, xsec_token,
                                                                                 enable_cookie=True)
                    if not note_detail:
                        raise Exception(f"[get_note_detail_async_task] Failed to get note detail, Id: {note_id}")

                note_detail.update({"xsec_token": xsec_token, "xsec_source": xsec_source})

                # Sleep after fetching note detail
                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                utils.logger.info(f"[get_note_detail_async_task] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after fetching note {note_id}")

                return note_detail

            except DataFetchError as ex:
                utils.logger.error(f"[XiaoHongShuCrawler.get_note_detail_async_task] Get note detail error: {ex}")
                return None
            except KeyError as ex:
                utils.logger.error(f"[XiaoHongShuCrawler.get_note_detail_async_task] have not fund note detail note_id:{note_id}, err: {ex}")
                return None
    
    async def get_note_detail_by_browser(self, note_id: str, xsec_source: str, xsec_token: str) -> Optional[Dict]:
        """通过浏览器访问笔记详情页面获取数据"""
        page = None
        try:
            # 构建笔记详情URL（即使没有xsec_token也可以访问）
            if xsec_token:
                note_url = f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token={xsec_token}&xsec_source={xsec_source}"
            else:
                note_url = f"https://www.xiaohongshu.com/explore/{note_id}"
            
            utils.logger.info(f"[XiaoHongShuCrawler.get_note_detail_by_browser] 访问笔记详情页: {note_url}")
            
            # 创建新标签页访问笔记详情
            page = await self.browser_context.new_page()
            await page.goto(note_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)  # 等待页面加载完成
            
            # 截图保存到本地文件
            try:
                # 创建截图保存目录
                screenshot_dir = "data/xhs/screenshots"
                pathlib.Path(screenshot_dir).mkdir(parents=True, exist_ok=True)
                
                # 生成文件名：note_id + 时间戳
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                screenshot_path = f"{screenshot_dir}/{note_id}_{timestamp}.png"
                
                # 截取全页面
                await page.screenshot(path=screenshot_path, full_page=True)
                utils.logger.info(f"[XiaoHongShuCrawler.get_note_detail_by_browser] 截图已保存: {screenshot_path}")
            except Exception as screenshot_e:
                utils.logger.warning(f"[XiaoHongShuCrawler.get_note_detail_by_browser] 截图失败: {screenshot_e}")
            
            # 方法1: 优先使用JavaScript直接从window.__INITIAL_STATE__提取（更可靠）
            try:
                initial_state = await page.evaluate("""
                    () => {
                        if (window.__INITIAL_STATE__ && window.__INITIAL_STATE__.note && 
                            window.__INITIAL_STATE__.note.noteDetailMap) {
                            try {
                                return JSON.stringify(window.__INITIAL_STATE__);
                            } catch (e) {
                                return null;
                            }
                        }
                        return null;
                    }
                """)
                
                if initial_state:
                    import json
                    import humps
                    state = json.loads(initial_state)
                    state = humps.decamelize(state)
                    
                    if "note" in state and "note_detail_map" in state["note"]:
                        note_detail_map = state["note"]["note_detail_map"]
                        if note_id in note_detail_map and "note" in note_detail_map[note_id]:
                            note_detail = note_detail_map[note_id]["note"]
                            utils.logger.info(f"[XiaoHongShuCrawler.get_note_detail_by_browser] 成功通过JS提取笔记详情: {note_id}")
                            await page.close()
                            return note_detail
            except Exception as js_e:
                utils.logger.warning(f"[XiaoHongShuCrawler.get_note_detail_by_browser] JS提取失败，尝试HTML解析: {js_e}")
            
            # 方法2: 如果JS提取失败，回退到HTML解析
            html = await page.content()
            await page.close()
            page = None
            
            note_detail = self.xhs_client._extractor.extract_note_detail_from_html(note_id, html)
            
            if note_detail:
                utils.logger.info(f"[XiaoHongShuCrawler.get_note_detail_by_browser] 成功通过HTML提取笔记详情: {note_id}")
            else:
                utils.logger.warning(f"[XiaoHongShuCrawler.get_note_detail_by_browser] 无法从HTML提取笔记详情: {note_id}")
            
            return note_detail
            
        except Exception as e:
            utils.logger.error(f"[XiaoHongShuCrawler.get_note_detail_by_browser] 获取笔记详情失败: {e}")
            if page:
                try:
                    await page.close()
                except:
                    pass
            return None

    async def batch_get_note_comments(self, note_list: List[str], xsec_tokens: List[str]):
        """Batch get note comments"""
        if not config.ENABLE_GET_COMMENTS:
            utils.logger.info(f"[XiaoHongShuCrawler.batch_get_note_comments] Crawling comment mode is not enabled")
            return

        utils.logger.info(f"[XiaoHongShuCrawler.batch_get_note_comments] Begin batch get note comments, note list: {note_list}")
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list: List[Task] = []
        for index, note_id in enumerate(note_list):
            task = asyncio.create_task(
                self.get_comments(note_id=note_id, xsec_token=xsec_tokens[index], semaphore=semaphore),
                name=note_id,
            )
            task_list.append(task)
        await asyncio.gather(*task_list)

    async def get_comments(self, note_id: str, xsec_token: str, semaphore: asyncio.Semaphore):
        """Get note comments with keyword filtering and quantity limitation"""
        async with semaphore:
            utils.logger.info(f"[XiaoHongShuCrawler.get_comments] Begin get note id comments {note_id}")
            # Use fixed crawling interval
            crawl_interval = config.CRAWLER_MAX_SLEEP_SEC
            await self.xhs_client.get_note_all_comments(
                note_id=note_id,
                xsec_token=xsec_token,
                crawl_interval=crawl_interval,
                callback=xhs_store.batch_update_xhs_note_comments,
                max_count=CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES,
            )

            # Sleep after fetching comments
            await asyncio.sleep(crawl_interval)
            utils.logger.info(f"[XiaoHongShuCrawler.get_comments] Sleeping for {crawl_interval} seconds after fetching comments for note {note_id}")

    async def create_xhs_client(self, httpx_proxy: Optional[str]) -> XiaoHongShuClient:
        """Create Xiaohongshu client"""
        utils.logger.info("[XiaoHongShuCrawler.create_xhs_client] Begin create Xiaohongshu API client ...")
        cookie_str, cookie_dict = utils.convert_cookies(await self.browser_context.cookies())
        xhs_client_obj = XiaoHongShuClient(
            proxy=httpx_proxy,
            headers={
                "accept": "application/json, text/plain, */*",
                "accept-language": "zh-CN,zh;q=0.9",
                "cache-control": "no-cache",
                "content-type": "application/json;charset=UTF-8",
                "origin": "https://www.xiaohongshu.com",
                "pragma": "no-cache",
                "priority": "u=1, i",
                "referer": "https://www.xiaohongshu.com/",
                "sec-ch-ua": '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-site",
                "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
                "Cookie": cookie_str,
            },
            playwright_page=self.context_page,
            cookie_dict=cookie_dict,
            proxy_ip_pool=self.ip_proxy_pool,  # Pass proxy pool for automatic refresh
        )
        return xhs_client_obj

    async def launch_browser(
        self,
        chromium: BrowserType,
        playwright_proxy: Optional[Dict],
        user_agent: Optional[str],
        headless: bool = True,
    ) -> BrowserContext:
        """Launch browser and create browser context"""
        utils.logger.info("[XiaoHongShuCrawler.launch_browser] Begin create browser context ...")
        if config.SAVE_LOGIN_STATE:
            # feat issue #14
            # we will save login state to avoid login every time
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
            )
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
        """Launch browser using CDP mode"""
        try:
            self.cdp_manager = CDPBrowserManager()
            browser_context = await self.cdp_manager.launch_and_connect(
                playwright=playwright,
                playwright_proxy=playwright_proxy,
                user_agent=user_agent,
                headless=headless,
            )

            # Display browser information
            browser_info = await self.cdp_manager.get_browser_info()
            utils.logger.info(f"[XiaoHongShuCrawler] CDP browser info: {browser_info}")

            return browser_context

        except Exception as e:
            utils.logger.error(f"[XiaoHongShuCrawler] CDP mode launch failed, falling back to standard mode: {e}")
            # Fall back to standard mode
            chromium = playwright.chromium
            return await self.launch_browser(chromium, playwright_proxy, user_agent, headless)

    async def close(self):
        """Close browser context"""
        # Special handling if using CDP mode
        if self.cdp_manager:
            await self.cdp_manager.cleanup()
            self.cdp_manager = None
        else:
            await self.browser_context.close()
        utils.logger.info("[XiaoHongShuCrawler.close] Browser context closed ...")

    async def get_notice_media(self, note_detail: Dict):
        if not config.ENABLE_GET_MEIDAS:
            utils.logger.info(f"[XiaoHongShuCrawler.get_notice_media] Crawling image mode is not enabled")
            return
        await self.get_note_images(note_detail)
        await self.get_notice_video(note_detail)

    async def get_note_images(self, note_item: Dict):
        """Get note images. Please use get_notice_media

        Args:
            note_item: Note item dictionary
        """
        if not config.ENABLE_GET_MEIDAS:
            return
        note_id = note_item.get("note_id")
        image_list: List[Dict] = note_item.get("image_list", [])

        for img in image_list:
            if img.get("url_default") != "":
                img.update({"url": img.get("url_default")})

        if not image_list:
            return
        picNum = 0
        for pic in image_list:
            url = pic.get("url")
            if not url:
                continue
            content = await self.xhs_client.get_note_media(url)
            await asyncio.sleep(random.random())
            if content is None:
                continue
            extension_file_name = f"{picNum}.jpg"
            picNum += 1
            await xhs_store.update_xhs_note_image(note_id, content, extension_file_name)

    async def get_notice_video(self, note_item: Dict):
        """Get note videos. Please use get_notice_media

        Args:
            note_item: Note item dictionary
        """
        if not config.ENABLE_GET_MEIDAS:
            return
        note_id = note_item.get("note_id")

        videos = xhs_store.get_video_url_arr(note_item)

        if not videos:
            return
        videoNum = 0
        for url in videos:
            content = await self.xhs_client.get_note_media(url)
            await asyncio.sleep(random.random())
            if content is None:
                continue
            extension_file_name = f"{videoNum}.mp4"
            videoNum += 1
            await xhs_store.update_xhs_note_video(note_id, content, extension_file_name)
