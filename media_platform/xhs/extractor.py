# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/xhs/extractor.py
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

import json
import re
from typing import Dict, Optional

import humps


class XiaoHongShuExtractor:
    def __init__(self):
        pass

    def extract_note_detail_from_html(self, note_id: str, html: str) -> Optional[Dict]:
        """Extract note details from HTML

        Args:
            html (str): HTML string

        Returns:
            Dict: Note details dictionary
        """
        if "noteDetailMap" not in html:
            # Either a CAPTCHA appeared or the note doesn't exist
            return None

        try:
            # 使用更健壮的正则表达式提取，支持多行匹配
            # 使用非贪婪匹配和更精确的模式
            match = re.search(
                r"window\.__INITIAL_STATE__\s*=\s*({.+?})\s*</script>", 
                html, 
                re.DOTALL | re.MULTILINE
            )
            
            if not match:
                # 尝试备用模式（不带等号周围空格）
                match = re.search(
                    r"window\.__INITIAL_STATE__=({.+?})</script>", 
                    html, 
                    re.DOTALL
                )
            
            if not match:
                return None
            
            state_str = match.group(1)
            
            # 清理JSON字符串：将undefined替换为null，处理可能的JSON格式问题
            state_str = state_str.replace(":undefined", ":null")
            state_str = state_str.replace("undefined", "null")
            
            # 解析JSON，使用strict=False允许控制字符
            try:
                state_dict = json.loads(state_str, strict=False)
            except json.JSONDecodeError as e:
                # 如果解析失败，尝试修复常见的JSON问题
                # 移除可能的尾随逗号
                state_str = re.sub(r',\s*}', '}', state_str)
                state_str = re.sub(r',\s*]', ']', state_str)
                try:
                    state_dict = json.loads(state_str, strict=False)
                except json.JSONDecodeError:
                    # 如果还是失败，返回None
                    return None
            
            if not state_dict or state_dict == {}:
                return None
            
            # 转换为小写下划线格式
            note_dict = humps.decamelize(state_dict)
            
            # 提取笔记详情
            if "note" in note_dict and "note_detail_map" in note_dict["note"]:
                note_detail_map = note_dict["note"]["note_detail_map"]
                if note_id in note_detail_map and "note" in note_detail_map[note_id]:
                    return note_detail_map[note_id]["note"]
            
            return None
            
        except Exception as e:
            # 记录错误但返回None，让调用者处理
            return None

    def extract_creator_info_from_html(self, html: str) -> Optional[Dict]:
        """Extract user information from HTML

        Args:
            html (str): HTML string

        Returns:
            Dict: User information dictionary
        """
        match = re.search(
            r"<script>window.__INITIAL_STATE__=(.+)<\/script>", html, re.M
        )
        if match is None:
            return None
        info = json.loads(match.group(1).replace(":undefined", ":null"), strict=False)
        if info is None:
            return None
        return info.get("user").get("userPageData")
