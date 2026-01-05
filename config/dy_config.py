# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/config/dy_config.py
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

# 抖音平台配置
PUBLISH_TIME_TYPE = 0

# 是否跳过登录（直接使用搜索URL进行抓取，不需要登录）
# 设置为True时，将跳过登录检查，直接访问SEARCH_URL（如果设置了）
# 注意：跳过登录后，某些需要登录的功能可能无法使用
SKIP_LOGIN = False

# 直接使用的搜索URL（可选）
# 如果设置了此URL，且SKIP_LOGIN=True，将直接访问此URL而不需要登录
# 例如: "https://www.douyin.com/search/%E9%85%B8%E5%A5%B6" (搜索"酸奶")
# 使用方式：
# 1. 设置 SKIP_LOGIN = True
# 2. 设置 SEARCH_URL = "https://www.douyin.com/search/%E9%85%B8%E5%A5%B6"
# 3. 设置 CRAWLER_TYPE = "search"
# 4. 如果使用浏览器自动化模式，设置 ENABLE_BROWSER_AUTOMATION_MODE = True
SEARCH_URL = ""

# 指定DY视频URL列表 (支持多种格式)
# 支持格式:
# 1. 完整视频URL: "https://www.douyin.com/video/7525538910311632128"
# 2. 带modal_id的URL: "https://www.douyin.com/user/xxx?modal_id=7525538910311632128"
# 3. 搜索页带modal_id: "https://www.douyin.com/root/search/python?modal_id=7525538910311632128"
# 4. 短链接: "https://v.douyin.com/drIPtQ_WPWY/"
# 5. 纯视频ID: "7280854932641664319"
DY_SPECIFIED_ID_LIST = [
    "https://www.douyin.com/video/7525538910311632128",
    "https://v.douyin.com/drIPtQ_WPWY/",
    "https://www.douyin.com/user/MS4wLjABAAAATJPY7LAlaa5X-c8uNdWkvz0jUGgpw4eeXIwu_8BhvqE?from_tab_name=main&modal_id=7525538910311632128",
    "7202432992642387233",
    # ........................
]

# 指定DY创作者URL列表 (支持完整URL或sec_user_id)
# 支持格式:
# 1. 完整创作者主页URL: "https://www.douyin.com/user/MS4wLjABAAAATJPY7LAlaa5X-c8uNdWkvz0jUGgpw4eeXIwu_8BhvqE?from_tab_name=main"
# 2. sec_user_id: "MS4wLjABAAAATJPY7LAlaa5X-c8uNdWkvz0jUGgpw4eeXIwu_8BhvqE"
DY_CREATOR_ID_LIST = [
    "https://www.douyin.com/user/MS4wLjABAAAATJPY7LAlaa5X-c8uNdWkvz0jUGgpw4eeXIwu_8BhvqE?from_tab_name=main",
    "MS4wLjABAAAATJPY7LAlaa5X-c8uNdWkvz0jUGgpw4eeXIwu_8BhvqE"
    # ........................
]
