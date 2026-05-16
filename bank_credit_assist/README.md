# 银行对公信贷智能化辅助系统

> 文档版本：v4.0
> 更新日期：2026-04-26

## 项目概述

本系统实现银行对公信贷流程的智能化辅助，包含三个核心步骤：

1. **Phase1 多模态资料解析**：自动识别、提取、校验企业尽调全量多模态资料的关键信息
2. **Phase2 财务分析与合规筛查**：基于结构化数据自动计算财务指标，完成合规筛查
3. **Phase3 智能报告生成**：AI辅助自动生成标准化授信审查报告初稿

## 项目结构

```
bank_credit_assist/
├── .env.example                  # 环境变量示例
├── requirements.txt              # Python 依赖清单
├── README.md                     # 项目说明
│
├── server.py                     # FastAPI 后端服务（主入口）
├── app_streamlit.py              # Streamlit 版 UI（备用）
├── orchestrator.py               # 工作流编排引擎
│
├── phase1_parser.py             # Phase1：多模态解析（含 Excel 分流）
├── phase2_analysis.py            # Phase2：财务分析 + 科技特征提取
├── phase2_compliance.py          # Phase2：双维度合规筛查
├── phase3_gemini.py              # Phase3：Gemini 报告生成
│
├── shared/
│   ├── __init__.py
│   ├── config.py                 # 配置中心（代理 + API Keys + 目录）
│   ├── mineru_client.py          # MinerU 异步状态机客户端
│   ├── gemini_client.py          # Gemini 客户端
│   ├── markdown_router.py        # 文档分类路由
│   └── data_schema.py            # Pydantic 数据模型
│
├── templates/
│   └── 授信调查报告模板.docx    # 银行报告模板
│
├── output/                       # 生成报告输出目录
└── tests/                        # 单元测试目录

项目根目录/
├── index.html                    # 前端页面（FastAPI 静态服务）
└── ...
```

## 快速开始

### 1. 环境准备

```bash
# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or
.\venv\Scripts\activate   # Windows

# 安装依赖
cd bank_credit_assist
pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env` 并配置：

```bash
cp .env.example .env
```

编辑 `.env` 文件：
```bash
# API Keys
MINERU_API_TOKEN=your_mineru_token_here
GEMINI_API_KEY=your_gemini_key_here

# 网络代理（本地开发必填）
HTTP_PROXY=http://127.0.0.1:15236
HTTPS_PROXY=http://127.0.0.1:15236
```

### 3. 启动应用

```bash
cd bank_credit_assist
uvicorn server:app --reload --host 0.0.0.0 --port 8000
```

浏览器打开 `http://localhost:8000`

### 4. 备用：Streamlit 版本

如需使用 Streamlit 版本：

```bash
streamlit run app_streamlit.py
```

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/upload` | 上传文件（按 doc_code 分类） |
| DELETE | `/api/upload/{session_id}/{doc_code}/{file_id}` | 删除已上传文件 |
| GET | `/api/status/{session_id}` | 查询工作流状态与进度 |
| POST | `/api/start-parse` | 触发 Phase1 解析 |
| POST | `/api/start-analyze` | 触发 Phase2 分析 |
| GET | `/api/phase2-result/{session_id}` | 获取 Phase2 分析结果 |
| POST | `/api/confirm-generate` | 确认数据并触发 Phase3 报告生成 |
| GET | `/api/download-report/{session_id}` | 下载生成的 Word 报告 |
| POST | `/api/reset` | 重置工作流 |

## 技术特性

- **FastAPI 后端**：原生 async 支持，自动 OpenAPI 文档
- **HTML 前端**：纯 HTML/CSS/JS，无框架依赖，易于定制
- **异步状态机**：使用 `asyncio.Event` + 回调管理批量文件解析
- **指数退避重试**：网络抖动时自动重试，最长间隔 16 秒
- **Excel 分流**：`.xlsx/.xls` 文件强制走 pandas 本地解析，禁止发给 MinerU
- **Token 控制**：按章节路由 Markdown 上下文，防止 Phase3 Token 溢出
- **Word 纯净**：展平数据时过滤所有溯源字段，输出纯净报告
- **Session 隔离**：UUID 会话管理，支持多用户并发
