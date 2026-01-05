#!/bin/bash
# -*- coding: utf-8 -*-
# 抖音视频采集脚本
# 用于采集抖音视频数据

set -e  # 遇到错误立即退出

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# 项目根目录（fangcang的上一级）
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
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

print_header() {
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}========================================${NC}"
}

# 默认参数配置
PLATFORM="dy"
CRAWLER_TYPE="search"
KEYWORDS="牛奶"
START_PAGE=1
MAX_COUNT=3

# 解析命令行参数
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            -k|--keywords)
                KEYWORDS="$2"
                shift 2
                ;;
            -p|--page)
                START_PAGE="$2"
                shift 2
                ;;
            -c|--count)
                MAX_COUNT="$2"
                shift 2
                ;;
            -h|--help)
                show_help
                exit 0
                ;;
            *)
                print_error "未知参数: $1"
                show_help
                exit 1
                ;;
        esac
    done
}

# 显示帮助信息
show_help() {
    echo "用法: ./crawl_douyin.sh [选项]"
    echo ""
    echo "选项:"
    echo "  -k, --keywords KEYWORDS    搜索关键词（默认: 牛奶）"
    echo "  -p, --page PAGE            起始页码（默认: 1）"
    echo "  -c, --count COUNT          最大采集数量（默认: 3）"
    echo "  -h, --help                 显示帮助信息"
    echo ""
    echo "示例:"
    echo "  ./crawl_douyin.sh                           # 使用默认参数（搜索'牛奶'，采集3个）"
    echo "  ./crawl_douyin.sh -k '编程' -c 5            # 搜索'编程'，采集5个"
    echo "  ./crawl_douyin.sh --keywords 'Python' --count 10  # 搜索'Python'，采集10个"
    echo ""
}

# 检查项目环境
check_environment() {
    print_info "检查项目环境..."
    
    # 检查main.py是否存在
    if [ ! -f "main.py" ]; then
        print_error "未找到 main.py 文件，请确保在正确的项目目录下运行"
        exit 1
    fi
    
    # 检查是否可以使用uv
    if command -v uv &> /dev/null; then
        USE_UV=true
        print_success "检测到 uv 工具，将使用 uv 运行"
    else
        USE_UV=false
        print_warning "未检测到 uv 工具，将使用 python3 运行"
        
        # 检查python3是否存在
        if ! command -v python3 &> /dev/null; then
            print_error "未找到 python3 命令"
            exit 1
        fi
    fi
    
    # 检查配置文件
    if [ ! -f "config/base_config.py" ]; then
        print_warning "未找到 config/base_config.py 文件"
    fi
}

# 更新配置文件中的采集数量
update_config() {
    print_info "更新配置：最大采集数量 = $MAX_COUNT"
    
    CONFIG_FILE="config/base_config.py"
    if [ -f "$CONFIG_FILE" ]; then
        # 使用sed更新CRAWLER_MAX_NOTES_COUNT
        if [[ "$OSTYPE" == "darwin"* ]]; then
            # macOS
            sed -i '' "s/^CRAWLER_MAX_NOTES_COUNT = .*/CRAWLER_MAX_NOTES_COUNT = $MAX_COUNT/" "$CONFIG_FILE"
        else
            # Linux
            sed -i "s/^CRAWLER_MAX_NOTES_COUNT = .*/CRAWLER_MAX_NOTES_COUNT = $MAX_COUNT/" "$CONFIG_FILE"
        fi
        print_success "配置已更新"
    else
        print_warning "配置文件不存在，跳过配置更新"
    fi
}

# 运行采集任务
run_crawler() {
    print_header "开始采集抖音视频"
    echo ""
    print_info "平台: 抖音 (douyin)"
    print_info "类型: 搜索 (search)"
    print_info "关键词: $KEYWORDS"
    print_info "起始页: $START_PAGE"
    print_info "最大采集数量: $MAX_COUNT"
    echo ""
    
    # 构建命令
    if [ "$USE_UV" = true ]; then
        CMD="uv run python main.py --platform $PLATFORM --type $CRAWLER_TYPE --keywords \"$KEYWORDS\" --start $START_PAGE"
    else
        CMD="python3 main.py --platform $PLATFORM --type $CRAWLER_TYPE --keywords \"$KEYWORDS\" --start $START_PAGE"
    fi
    
    print_info "执行命令: $CMD"
    echo ""
    
    # 运行采集任务
    eval $CMD
    
    local exit_code=$?
    
    if [ $exit_code -eq 0 ]; then
        echo ""
        print_success "采集任务完成！"
        print_info "数据保存在: data/douyin/ 目录"
    else
        echo ""
        print_error "采集任务失败，退出码: $exit_code"
        exit $exit_code
    fi
}

# 主函数
main() {
    print_header "抖音视频采集工具"
    echo ""
    
    # 解析参数
    parse_args "$@"
    
    # 检查环境
    check_environment
    
    # 更新配置
    update_config
    
    # 运行采集
    run_crawler
}

# 运行主函数
main "$@"

