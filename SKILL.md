---
name: paper-parse
description: 将 PDF/图片/arXiv URL 解析为合并 Markdown 与可打开 HTML(保留图、公式、表),基于 PaddleOCR-VL 云端 OCR,不依赖通用大语言模型,内置内容哈希缓存。当需要解析/读取/OCR/转换 PDF 或图片为 Markdown/HTML 时使用。可经命令行或 import 调用。
---

# paper-parse

`<SKILL>` 表示本 skill 所在目录。

## 前置
- `pip install requests`(`pymupdf` 可选)。
- OCR 令牌:在 https://aistudio.baidu.com/paddleocr 获取,设环境变量 `PADDLEOCR_TOKEN`(或 `--token`)。
- 缓存目录:中心缓存默认 `<SKILL>/store/`,本地副本默认 PDF 同级 `.parse/`。首次解析前确认是否需要改到其它位置:中心缓存设 `PAPER_PARSE_STORE=<目录>`(或 `--store-root`),关闭本地副本用 `--no-local-cache`。

## 命令行
```
python "<SKILL>/parse_doc.py" "<pdf/图片/目录/url>" [-o <dir>] [--no-local-cache] [--refresh] [--proxy <url>]
```
目录输入递归解析全部 `*.pdf`;产物在 `<SKILL>/store/<key>/parsed/{<key>.full.md, <key>.html, images/}`。

## Python
```python
import sys; sys.path.insert(0, r"<SKILL>")
from parse_doc import parse
r = parse("xxx.pdf")        # r["md"] 为合并全文路径
```

## 说明
- 整篇一次提交;内容哈希缓存,相同内容复用。
- 不调用通用大语言模型;库无关(输入→输出)。
- 浏览/搜索:`python "<SKILL>/serve.py" --open`;核对副本:`python "<SKILL>/doctor.py" [--fix]`。

详见仓库 `README.md`。
