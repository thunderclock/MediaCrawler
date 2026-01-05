# Fangcang 独立脚本目录

这个目录用于存放独立的Python脚本文件，每个脚本都可以独立运行。

## 快速开始

### 方式一：使用Shell脚本（推荐）

#### 1. 初始化环境（首次使用）
```bash
cd fangcang
./setup.sh
```

#### 2. 运行Python脚本
```bash
./run.sh example.py
```

脚本会自动：
- 检查并创建虚拟环境（如果需要）
- 激活虚拟环境
- 安装依赖包（如果存在requirements.txt）
- 运行指定的Python脚本

#### 3. 其他常用命令
```bash
./run.sh -h              # 显示帮助信息
./run.sh -i              # 安装依赖包
./run.sh -l              # 列出所有Python脚本
./run.sh -a              # 仅激活虚拟环境（进入交互式shell）
./run.sh -c              # 创建虚拟环境
```

#### 4. 采集抖音视频
```bash
# 使用默认参数（搜索'牛奶'，采集3个视频）
./crawl_douyin.sh

# 自定义关键词和数量
./crawl_douyin.sh -k '编程' -c 5

# 查看帮助
./crawl_douyin.sh -h
```

### 方式二：手动操作

#### 1. 激活虚拟环境

**macOS/Linux:**
```bash
cd fangcang
source venv/bin/activate
```

**Windows:**
```bash
cd fangcang
venv\Scripts\activate
```

激活成功后，命令行提示符前会显示 `(venv)`。

#### 2. 安装依赖（如果需要）
```bash
pip install -r requirements.txt
```

#### 3. 运行脚本
```bash
python example.py
```

#### 4. 退出虚拟环境
```bash
deactivate
```

## 虚拟环境管理

### 创建虚拟环境（如果还没有）
```bash
cd fangcang
python3 -m venv venv
```

### 升级 pip
```bash
source venv/bin/activate  # 先激活虚拟环境
pip install --upgrade pip
```

### 查看已安装的包
```bash
pip list
```

### 导出依赖列表
```bash
pip freeze > requirements.txt
```

## 目录结构

```
fangcang/
├── venv/              # 虚拟环境目录（已创建）
├── README.md          # 说明文档
├── requirements.txt   # Python依赖包列表
├── .gitignore         # Git忽略文件配置
├── run.sh             # 脚本运行工具（自动激活环境并运行）
├── setup.sh           # 环境初始化脚本
├── crawl_douyin.sh    # 抖音视频采集脚本
└── *.py              # 独立的Python脚本文件
    └── example.py     # 示例脚本
```

## 使用说明

1. 将独立的Python脚本文件放在此目录下
2. 每个脚本应该可以独立运行，不依赖主项目的其他模块
3. 如果脚本需要额外的依赖包，请添加到 `requirements.txt`
4. 建议在虚拟环境中运行脚本，避免污染系统Python环境

## 抖音视频采集

### 使用 crawl_douyin.sh 脚本

这是一个专门用于采集抖音视频的脚本，会自动调用主项目的采集功能。

**默认配置：**
- 平台：抖音 (dy)
- 类型：搜索 (search)
- 关键词：牛奶
- 起始页：1
- 最大采集数量：3个

**使用方法：**
```bash
cd fangcang

# 使用默认参数（搜索'牛奶'，采集3个视频）
./crawl_douyin.sh

# 自定义关键词
./crawl_douyin.sh -k 'Python编程'

# 自定义采集数量
./crawl_douyin.sh -c 10

# 自定义关键词和数量
./crawl_douyin.sh --keywords '机器学习' --count 5

# 查看所有选项
./crawl_douyin.sh -h
```

**脚本功能：**
- 自动检测并使用 `uv` 或 `python3` 运行
- 自动更新配置文件中的采集数量
- 显示详细的运行信息和进度
- 采集完成后显示数据保存位置

**注意事项：**
- 脚本会在主项目目录下运行，需要确保主项目环境已配置好
- 采集过程中会打开浏览器窗口（如果未设置无头模式）
- 可能需要登录抖音账号（扫码或输入账号密码）
- 采集的数据保存在 `../data/douyin/` 目录

## 注意事项

- 虚拟环境目录 `venv/` 已在 `.gitignore` 中忽略，不会被提交到Git
- 每次使用前记得激活虚拟环境
- 如果脚本需要访问主项目的模块，可以考虑使用相对导入或添加路径
- `crawl_douyin.sh` 脚本需要在主项目目录下运行，确保主项目依赖已安装

