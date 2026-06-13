---
name: paper-parse
description: 独立 PDF/图片/URL 论文解析工具(任意 agent 可复用)。把 PDF/图片/arXiv URL 解析成合并 Markdown + 可打开 HTML(图/公式/表还原),只需 OCR API、不依赖任何通用大模型(GPT/Claude/Kimi),按内容哈希全库去重(同一篇换名/换位只解析一次,命中秒回)。当用户要解析 / 读取 / OCR / 转换一篇 PDF 或图片为 Markdown/HTML 时使用。自包含、库无关:输入→输出。
---

# paper-parse — PDF/图片 → Markdown/HTML(只用 OCR,不用大模型)

**自包含**:代码与依赖都在本目录。`<SKILL>` 指本 skill 所在目录。

## 首次使用前(agent 请主动提醒用户,勿默默跑)
1. 依赖:`pip install requests`(可选 `pymupdf`)。
2. **OCR token**:需设环境变量 `PADDLEOCR_TOKEN=<你的 token>`(本工具不内置;未设会报错)。
3. **缓存位置(务必告知用户)**:解析产物默认存在 **`<SKILL>/store/`**;本地副本默认放在 **PDF 文件旁的 `.parse/`**。
   首次解析前请告诉用户这两个默认位置,并**询问是否更换缓存目录**:
   - 更换中心缓存:设环境变量 `PAPER_PARSE_STORE=<目录>`(或单次 `--store-root <目录>`);
   - 不在 PDF 旁留副本:加 `--no-local-cache`。

## 用法 A:命令行
```
python "<SKILL>/parse_doc.py" "<pdf/图片/文件夹/http(s) url>" [-o 输出目录] [--no-local-cache] [--refresh] [--proxy http://127.0.0.1:7897]
```
产物:`<SKILL>/store/<key>/parsed/{<key>.full.md, <key>.html, images/}`。

## 用法 B:Python import(返回 dict)
```python
import sys; sys.path.insert(0, r"<SKILL>")
from parse_doc import parse
r = parse("xxx.pdf")     # r["md"] 是解析后全文路径
text = open(r["md"], encoding="utf-8").read()
```

## 约定
- 整篇一次提交(非逐页);内容哈希去重,命中秒回。
- token:`--token` > 环境变量 `PADDLEOCR_TOKEN`;未设置会报错提示。
- **绝不调通用大模型,库无关(输入→输出)。**
- 浏览/搜索:`python "<SKILL>/serve.py" --open`;核对副本:`python "<SKILL>/doctor.py" [--fix]`。

详见仓库 `README.md`。
