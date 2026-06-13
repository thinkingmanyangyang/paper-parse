# paper-parse

把 **PDF / 图片 / arXiv URL** 解析成 **一篇合并的 Markdown + 可打开的 HTML**(图、公式、表格都还原),只用一个云端 OCR 接口、**不依赖任何通用大模型(GPT/Claude/…)**。单文件、零配置即跑、按内容哈希全库去重(同一篇换名/换位只解析一次,命中秒回)。可被任意 agent 通过 CLI 或 `import` 复用。

## 特性
- 📄 整篇文档**一次请求**提交到 PaddleOCR-VL 云端异步 Job 接口,合并成单个 `.full.md`。
- 🖼 自动下载图片、生成可双击打开的 `.html`(marked + MathJax 渲染公式/表格)。
- 🧠 **不调通用大模型**,只需 OCR token;依赖极少(`requests`)。
- ♻️ **内容哈希去重**:`sha256(PDF 内容 + 模型)`,重复解析直接复用。
- 🔌 库无关:输入 → 输出;`parse()` 返回 dict,易于集成。

## 安装
```bash
pip install -r requirements.txt   # 仅 requests(pymupdf 可选)
```
需要一个 PaddleOCR-VL 云端接口的 token,放到环境变量:
```bash
# bash
export PADDLEOCR_TOKEN=你的token
# PowerShell
$env:PADDLEOCR_TOKEN='你的token'
```
> token 在 **百度 AI Studio PaddleOCR:https://aistudio.baidu.com/paddleocr** 申请/获取。本仓库**不内置任何 token**;未设置时会友好报错。

## 用法

**命令行**
```bash
python parse_doc.py "path/to/paper.pdf"
python parse_doc.py "https://arxiv.org/pdf/2502.00290"
python parse_doc.py "某文件夹"          # 递归批量解析其中所有 *.pdf
# 可选:-o <dir> 另存副本 | --no-local-cache 不在 PDF 旁存 | --refresh 强制重解析 | --proxy http://127.0.0.1:7897
```

**Python import**
```python
from parse_doc import parse
r = parse("paper.pdf")              # 或 URL;parse(pdf, no_local_cache=True, proxy="...")
# r = {key, title, central, local, md, html, source, papers_cool, status, cache_hit}
text = open(r["md"], encoding="utf-8").read()
```

## 产物结构
```
store/<key>/
├── meta.json                     # 源路径 / 标题 / content_sha256 / papers.cool 链接 / 时间
└── parsed/
    ├── <key>.full.md             # 合并后的整篇 Markdown(图片为相对路径)
    ├── <key>.html                # 可打开 HTML(图/公式/表)
    └── images/                   # 裁图
```
- `key` = 文件名 slug(保留中文);全称在 `meta.title`。
- 默认在 PDF 旁另存一份 `.parse/<key>/`(`-o` 改位置;URL 或 `--no-local-cache` 仅写中心 `store/`)。

## 缓存位置与配置
两处缓存,均可配置:

**中心缓存(恒写)** — 默认 `<脚本目录>/store/`。改它(优先级:CLI > 环境变量 > config > 默认):
```bash
# 1) 环境变量(推荐,一处配置,所有调用生效)
export PAPER_PARSE_STORE=/path/to/cache       # PowerShell: $env:PAPER_PARSE_STORE='D:\cache'
# 2) config.json 增加一行
#    "store_root": "/path/to/cache"
# 3) 命令行单次覆盖
python parse_doc.py xxx.pdf --store-root /path/to/cache
# 4) 代码:parse("xxx.pdf", store_root="/path/to/cache")
```

**本地副本(可选,就近一份)** — 默认在 PDF 旁 `.parse/<key>/`;`-o <dir>` 改位置,`--no-local-cache` 关闭(URL 输入不产)。

## 浏览 / 搜索已解析的论文
```bash
python serve.py --port 8765 --open
```
本地 `http://127.0.0.1:8765`:列表 + 标题/全文搜索;单篇 HTML 顶栏可「打开原文 / 文件位置(资源管理器)/ papers.cool 搜索」(需经本地服务器)。
核对本地副本完整性:`python doctor.py [--fix]`。

## 作为 Claude Code skill 使用
仓库自带 `SKILL.md`。把整个目录放到 `~/.claude/skills/paper-parse/` 即可被 Claude Code 自动发现;其它 agent(如 Codex)可直接按上面的 CLI/import 调用。

## 依赖的第三方服务
本工具依赖云端 OCR 接口 `paddleocr.aistudio-app.com`。该服务的可用性、限流、计费与条款由其提供方决定;使用者需自备 token 并遵守其服务条款。网络不通时可加 `--proxy`。

## License
MIT,见 [LICENSE](LICENSE)。
