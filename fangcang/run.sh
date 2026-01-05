#!/bin/bash
# -*- coding: utf-8 -*-
# Fangcang 脚本运行工具
# 用于快速激活虚拟环境并运行Python脚本

set -e  # 遇到错误立即退出

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 打印带颜色的消息
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查虚拟环境是否存在
check_venv() {
    if [ ! -d "venv" ]; then
        print_error "虚拟环境不存在！"
        print_info "正在创建虚拟环境..."
        python3 -m venv venv
        print_success "虚拟环境创建成功！"
    fi
}

# 激活虚拟环境
activate_venv() {
    if [ -f "venv/bin/activate" ]; then
        source venv/bin/activate
        print_success "虚拟环境已激活"
    else
        print_error "无法找到虚拟环境激活脚本"
        exit 1
    fi
}

# 安装依赖
install_dependencies() {
    if [ -f "requirements.txt" ]; then
        print_info "检查并安装依赖..."
        pip install -q --upgrade pip
        pip install -q -r requirements.txt
        print_success "依赖安装完成"
    else
        print_warning "未找到 requirements.txt 文件"
    fi
}

# 显示帮助信息
show_help() {
    echo "用法: ./run.sh [选项] [脚本文件]"
    echo ""
    echo "选项:"
    echo "  -h, --help              显示帮助信息"
    echo "  -i, --install           安装依赖包"
    echo "  -a, --activate          仅激活虚拟环境（不运行脚本）"
    echo "  -l, --list              列出所有Python脚本文件"
    echo "  -c, --create-venv       创建虚拟环境"
    echo ""
    echo "示例:"
    echo "  ./run.sh example.py              # 运行 example.py"
    echo "  ./run.sh -i                       # 安装依赖"
    echo "  ./run.sh -a                       # 仅激活虚拟环境"
    echo "  ./run.sh -l                       # 列出所有脚本"
}

# 列出所有Python脚本
list_scripts() {
    print_info "当前目录下的Python脚本："
    echo ""
    count=0
    for file in *.py; do
        if [ -f "$file" ]; then
            echo "  $((++count)). $file"
        fi
    done
    if [ $count -eq 0 ]; then
        print_warning "未找到Python脚本文件"
    fi
}

# 主函数
main() {
    # 解析参数
    case "${1:-}" in
        -h|--help)
            show_help
            exit 0
            ;;
        -i|--install)
            check_venv
            activate_venv
            install_dependencies
            exit 0
            ;;
        -a|--activate)
            check_venv
            activate_venv
            print_info "虚拟环境已激活，你可以运行Python命令"
            print_info "退出虚拟环境请输入: deactivate"
            exec $SHELL  # 启动新的shell保持激活状态
            ;;
        -l|--list)
            list_scripts
            exit 0
            ;;
        -c|--create-venv)
            check_venv
            exit 0
            ;;
        "")
            print_error "请指定要运行的Python脚本文件"
            echo ""
            show_help
            exit 1
            ;;
        *)
            # 检查文件是否存在
            if [ ! -f "$1" ]; then
                print_error "文件不存在: $1"
                exit 1
            fi
            
            # 检查是否是Python文件
            if [[ ! "$1" =~ \.py$ ]]; then
                print_warning "文件不是.py扩展名，继续执行..."
            fi
            
            # 检查并激活虚拟环境
            check_venv
            activate_venv
            
            # 安装依赖（如果需要）
            if [ -f "requirements.txt" ]; then
                install_dependencies
            fi
            
            # 运行脚本
            print_info "运行脚本: $1"
            echo ""
            python "$1" "${@:2}"  # 传递剩余的参数给Python脚本
            ;;
    esac
}

# 运行主函数
main "$@"

