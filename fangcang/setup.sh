#!/bin/bash
# -*- coding: utf-8 -*-
# Fangcang 环境设置脚本
# 用于初始化虚拟环境和安装依赖

set -e

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 颜色定义
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Fangcang 环境设置${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# 检查Python版本
echo -e "${BLUE}[1/4]${NC} 检查Python版本..."
if ! command -v python3 &> /dev/null; then
    echo -e "${YELLOW}错误: 未找到 python3 命令${NC}"
    exit 1
fi

PYTHON_VERSION=$(python3 --version)
echo -e "${GREEN}✓${NC} $PYTHON_VERSION"
echo ""

# 创建虚拟环境
echo -e "${BLUE}[2/4]${NC} 创建虚拟环境..."
if [ -d "venv" ]; then
    echo -e "${YELLOW}虚拟环境已存在，跳过创建${NC}"
else
    python3 -m venv venv
    echo -e "${GREEN}✓${NC} 虚拟环境创建成功"
fi
echo ""

# 激活虚拟环境
echo -e "${BLUE}[3/4]${NC} 激活虚拟环境..."
source venv/bin/activate
echo -e "${GREEN}✓${NC} 虚拟环境已激活"
echo ""

# 升级pip
echo -e "${BLUE}[4/4]${NC} 升级pip..."
pip install --quiet --upgrade pip
echo -e "${GREEN}✓${NC} pip已升级"
echo ""

# 安装依赖（如果存在）
if [ -f "requirements.txt" ]; then
    echo -e "${BLUE}[5/5]${NC} 安装依赖包..."
    if [ -s requirements.txt ]; then
        pip install --quiet -r requirements.txt
        echo -e "${GREEN}✓${NC} 依赖包安装完成"
    else
        echo -e "${YELLOW}requirements.txt 文件为空，跳过安装${NC}"
    fi
else
    echo -e "${YELLOW}未找到 requirements.txt 文件，跳过依赖安装${NC}"
fi
echo ""

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  环境设置完成！${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "使用以下命令激活虚拟环境："
echo "  source venv/bin/activate"
echo ""
echo "或者使用 run.sh 脚本运行Python文件："
echo "  ./run.sh example.py"
echo ""

