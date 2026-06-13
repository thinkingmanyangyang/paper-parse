# paper-parse

将 PDF / 图片 / arXiv URL 解析为一篇合并的 Markdown 与可打开的 HTML(保留图片、公式、表格)。基于 PaddleOCR-VL 云端 OCR,不依赖任何通用大语言模型。单文件,可经命令行或 `import` 调用,内置内容哈希缓存。

## 特性
- 整篇文档一次提交至 PaddleOCR-VL 异步接口,合并为单个 `<key>.full.md`。
- 生成 HTML(marked + MathJax 渲染公式/表格),自动下载图片。
- 内容哈希缓存:键为 `sha256(文件内容 + 模型)`,相同内容复用既有结果。
- `parse()` 返回结构化 dict,便于集成。

## 环境要求
- Python 3.8+
- `pip install -r requirements.txt`(`requests`;`pymupdf` 可选)

## 配置
| 项 | 作用 | 默认 |
|---|---|---|
| `PADDLEOCR_TOKEN`(环境变量)/ `--token` | OCR 接口令牌(必需) | — |
| `PAPER_PARSE_STORE`(环境变量)/ `--store-root` / config `store_root` | 中心缓存目录 | `<脚本目录>/store` |
| `-o <dir>` | 本地副本目录 | PDF 同级 `.parse/` |
| `--no-local-cache` | 不生成本地副本 | 生成 |
| `--proxy <url>` | HTTP(S) 代理 | 无 |

令牌在 [百度 AI Studio · PaddleOCR](https://aistudio.baidu.com/paddleocr) 获取:
```bash
export PADDLEOCR_TOKEN=<token>          # PowerShell: $env:PADDLEOCR_TOKEN='<token>'
```

## 用法
命令行:
```bash
python parse_doc.py "paper.pdf"
python parse_doc.py "https://arxiv.org/pdf/2502.00290"
python parse_doc.py "<目录>"            # 递归批量解析其中所有 *.pdf
```
Python:
```python
from parse_doc import parse
r = parse("paper.pdf")                  # 或 URL;可传 store_root / proxy / no_local_cache
text = open(r["md"], encoding="utf-8").read()
```

## 输出
```
store/<key>/
├── meta.json                 # 源路径、标题、content_sha256、papers.cool 链接、时间
└── parsed/
    ├── <key>.full.md         # 合并后的整篇 Markdown(图片为相对路径)
    ├── <key>.html
    └── images/
```
`key` 为文件名 slug(保留中文),完整标题见 `meta.title`。中心缓存始终写入;本地副本默认写至 PDF 同级 `.parse/<key>/`(URL 输入或 `--no-local-cache` 时不生成)。

## 浏览与搜索
```bash
python serve.py --port 8765 --open
```
本地 `http://127.0.0.1:8765` 提供列表、标题/全文搜索;单篇 HTML 顶栏含「打开原文 / 文件位置 / papers.cool」。`python doctor.py [--fix]` 核对本地副本。

## 作为 Claude Code skill
将本目录置于 `~/.claude/skills/paper-parse/` 即被自动发现;其它环境可直接经命令行或 `import` 调用。

## 第三方服务
依赖云端 OCR 接口 `paddleocr.aistudio-app.com`,其可用性、限流与条款由服务方决定;使用者自备令牌并遵循其条款。

## License
MIT,见 [LICENSE](LICENSE)。
