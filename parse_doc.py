#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
paper-parse —— 独立、可复用的论文解析工具(库无关)。CLI + 可 import。

PDF / 图片 / 文件夹(批量) / URL → 解析包(合并 Markdown + 可打开 HTML + 图)。
只依赖 requests(OCR 云接口)+ 可选 pymupdf。**不依赖任何通用大模型。**

始终"双缓存":
  - 中心缓存(store/<key>/):恒写,内部按内容哈希去重。
  - 本地副本:默认 PDF 旁 .parse/<key>/;-o <dir> 放到 <dir>/.parse/<key>/;URL 或 --no-local-cache 则不产本地副本。

CLI:  python parse_doc.py <input> [-o <dir>] [--no-local-cache] [--refresh] [--proxy P]
API:  from parse_doc import parse;  r = parse("<pdf>", output=None)
"""
import argparse
import datetime
import glob
import hashlib
import json
import os
import re
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote, quote_plus

import requests

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except Exception:  # pragma: no cover
    HTTPAdapter = Retry = None

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
DEFAULT_STORE_ROOT = os.path.join(SCRIPT_DIR, "store")
DEFAULT_JOB_URL = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
DEFAULT_MODEL = "PaddleOCR-VL-1.6"
DEFAULT_TOKEN = os.environ.get("PADDLEOCR_TOKEN")  # 开源版无内置 token,使用者自备环境变量 PADDLEOCR_TOKEN
PAPERS_COOL_SEARCH = "https://papers.cool/arxiv/search?highlight=1&query="
OPTIONAL_PAYLOAD = {"useDocOrientationClassify": False, "useDocUnwarping": False, "useChartRecognition": False}
MAX_PATH = 250


def load_config(path=None):
    cfg = {"store_root": DEFAULT_STORE_ROOT,
           "ocr": {"endpoint": DEFAULT_JOB_URL, "model": DEFAULT_MODEL, "token_env": "PADDLEOCR_TOKEN"},
           "papers_cool_search": PAPERS_COOL_SEARCH}
    path = path or DEFAULT_CONFIG_PATH
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                user = json.load(f)
            for k, v in user.items():
                if k == "ocr" and isinstance(v, dict):
                    cfg["ocr"].update(v)
                else:
                    cfg[k] = v
        except Exception as e:  # noqa: BLE001
            print(f"[警告] 读 config 失败,用默认:{e}")
    # 环境变量覆盖(便于一处配置,无需改 config / 每次传 --store-root)
    env_store = os.environ.get("PAPER_PARSE_STORE")
    if env_store:
        cfg["store_root"] = env_store
    return cfg


def _now():
    try:
        return datetime.datetime.now().isoformat(timespec="seconds")
    except Exception:
        return ""


def slugify(name):
    s = str(name).strip()
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"[^\w\-]", "-", s, flags=re.UNICODE)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    s = "".join(c.lower() if "A" <= c <= "Z" else c for c in s)
    return s or "document"


def resolve_key(base, source_id, papers_root):
    cand, i = base, 1
    while True:
        meta_p = os.path.join(papers_root, cand, "meta.json")
        if not os.path.isfile(meta_p):
            return cand
        try:
            with open(meta_p, encoding="utf-8") as f:
                if json.load(f).get("source") == source_id:
                    return cand
        except Exception:
            return cand
        i += 1
        cand = f"{base}-{i}"


def cap_key(key, papers_root, local_parent, content_sha):
    def longest(k):
        a = len(os.path.join(papers_root, k, "parsed", k + ".full.md"))
        b = (len(os.path.join(local_parent, ".parse", k, "parsed", k + ".full.md")) if local_parent else 0)
        return max(a, b)
    if longest(key) <= MAX_PATH:
        return key
    suffix = "-" + content_sha[:6]
    budget = max(8, len(key) - (longest(key) - MAX_PATH) - len(suffix))
    return key[:budget].rstrip("-") + suffix


def find_by_sha(store_root, content_sha):
    mp = os.path.join(store_root, "manifest.jsonl")
    if not os.path.isfile(mp):
        return None
    try:
        with open(mp, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and json.loads(line).get("content_sha256") == content_sha:
                    return json.loads(line).get("key")
    except Exception:
        pass
    return None


def make_session(proxy=None):
    s = requests.Session()
    if proxy:
        s.proxies.update({"http": proxy, "https": proxy})
    if HTTPAdapter and Retry:
        r = Retry(total=3, backoff_factor=0.6, status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=["GET", "POST"])
        ad = HTTPAdapter(max_retries=r)
        s.mount("http://", ad)
        s.mount("https://", ad)
    return s


def submit_job(session, source, model, token, job_url):
    headers = {"Authorization": f"bearer {token}"}
    if str(source).startswith("http"):
        headers["Content-Type"] = "application/json"
        payload = {"fileUrl": source, "model": model, "optionalPayload": OPTIONAL_PAYLOAD}
        resp = session.post(job_url, json=payload, headers=headers, timeout=60)
    else:
        data = {"model": model, "optionalPayload": json.dumps(OPTIONAL_PAYLOAD)}
        with open(source, "rb") as f:
            resp = session.post(job_url, headers=headers, data=data, files={"file": f}, timeout=300)
    if resp.status_code != 200:
        sys.exit(f"[错误] 提交失败 HTTP {resp.status_code}:{resp.text}")
    jid = resp.json()["data"]["jobId"]
    print(f"[提交成功] jobId = {jid}")
    return jid


def poll_job(session, job_id, token, job_url, interval=5, timeout=1800):
    headers = {"Authorization": f"bearer {token}"}
    deadline = time.monotonic() + timeout
    last = ""
    while True:
        if time.monotonic() > deadline:
            sys.exit(f"[错误] 轮询超时(>{timeout}s)")
        resp = session.get(f"{job_url}/{job_id}", headers=headers, timeout=60)
        if resp.status_code != 200:
            time.sleep(interval)
            continue
        data = resp.json()["data"]
        st = data.get("state")
        if st == "done":
            prog = data.get("extractProgress", {}) or {}
            print(f"[完成] 解析 {prog.get('extractedPages', '?')} 页")
            return data["resultUrl"]["jsonUrl"]
        if st == "failed":
            sys.exit(f"[错误] 任务失败:{data.get('errorMsg')}")
        msg = {"pending": "排队中", "running": "解析中"}.get(st, st)
        if msg != last:
            print("  状态:" + str(msg))
            last = msg
        time.sleep(interval)


def fetch_results(session, jsonl_url):
    resp = session.get(jsonl_url, timeout=120)
    resp.raise_for_status()
    out = []
    for line in resp.text.strip().split("\n"):
        line = line.strip()
        if line:
            out.append(json.loads(line)["result"])
    return out


def _download_one(session, url, dst):
    try:
        r = session.get(url, timeout=120)
        if r.status_code == 200:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as f:
                f.write(r.content)
            return True
    except Exception:
        pass
    return False


def merge_results(session, results, parsed_dir, workers=8):
    os.makedirs(parsed_dir, exist_ok=True)
    parts, tasks, page = [], [], 0
    for result in results:
        for res in result.get("layoutParsingResults", []):
            md = res.get("markdown", {}) or {}
            text = md.get("text", "") or ""
            images = md.get("images", {}) or {}
            for rel in sorted(images.keys(), key=len, reverse=True):
                new_rel = f"images/p{page:03d}_{os.path.basename(rel)}"
                text = text.replace(rel, new_rel)
                tasks.append((images[rel], os.path.join(parsed_dir, new_rel)))
            parts.append(text.strip())
            page += 1
    merged = "\n\n".join(p for p in parts if p)
    ok = 0
    if tasks:
        print(f"[下载图片] {len(tasks)} 张 ...")
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(_download_one, session, u, d) for u, d in tasks]
            ok = sum(1 for f in as_completed(futs) if f.result())
    return merged, {"pages": page, "images_ok": ok, "images_fail": len(tasks) - ok}


def extract_title(md_text, fallback):
    for line in md_text.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def md_header(source, papers_cool):
    return f"> 📄 原文:`{source}`\n>\n> 🔗 papers.cool:{papers_cool}\n\n---\n\n"


def file_url(src):
    if str(src).startswith("http"):
        return src
    return "file:///" + quote(src.replace("\\", "/"), safe="/:")


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<script>
window.MathJax = { tex: { inlineMath: [['$','$'],['\\(','\\)']], displayMath: [['$$','$$'],['\\[','\\]']] },
  options: { skipHtmlTags: ['script','noscript','style','textarea','pre','code'] } };
</script>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js" async></script>
<style>
 body{max-width:880px;margin:28px auto;padding:0 20px;font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;line-height:1.7;color:#1a1a1a}
 .phead{background:#f6f8fa;border:1px solid #e1e4e8;border-radius:8px;padding:8px 12px;font-size:13px;margin-bottom:18px}
 img{max-width:100%;height:auto;display:block;margin:12px auto}
 table{border-collapse:collapse;margin:16px auto;font-size:14px}
 th,td{border:1px solid #bbb;padding:5px 9px;text-align:center}
 th{background:#f2f2f2}
 pre{background:#f6f8fa;padding:12px;overflow-x:auto}
 code{background:#f0f0f0;padding:1px 4px;border-radius:3px}
</style></head>
<body>
<div class="phead">📄 <a id="pp-open" href="__FILEURL__" target="_blank">打开原文</a> &nbsp;|&nbsp; 📂 <a id="pp-reveal" href="#">文件位置</a> &nbsp;|&nbsp; 🔗 <a href="__PCOOL__" target="_blank">papers.cool 搜索</a></div>
<script>
(function(){var k="__KEY__",served=(location.protocol==='http:'||location.protocol==='https:');
 function call(p){return function(e){e.preventDefault();
  fetch(p+encodeURIComponent(k)).then(function(r){return r.json();})
  .then(function(d){if(!d.ok)alert(d.msg||'操作失败');})
  .catch(function(){alert('此功能需通过本地服务器(serve.py)访问');});};}
 var o=document.getElementById('pp-open'),rv=document.getElementById('pp-reveal');
 if(served){if(o)o.addEventListener('click',call('/open?key='));if(rv)rv.addEventListener('click',call('/reveal?key='));}
 else{if(rv)rv.addEventListener('click',function(e){e.preventDefault();alert('“文件位置”需通过本地服务器(serve.py)访问');});}
})();
</script>
<div id="content">正在渲染…</div>
<script id="md-source" type="text/markdown">__MD__</script>
<script>
function render(){
 var md=document.getElementById('md-source').textContent, math=[];
 function stash(re,s){return s.replace(re,function(m){math.push(m);return '@@M'+(math.length-1)+'@@';});}
 md=stash(/\$\$[\s\S]+?\$\$/g,md); md=stash(/\\\[[\s\S]+?\\\]/g,md);
 md=stash(/\\\([\s\S]+?\\\)/g,md); md=stash(/\$[^\$\n]+?\$/g,md);
 var html=marked.parse(md);
 function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
 html=html.replace(/@@M(\d+)@@/g,function(m,i){return esc(math[+i]);});
 document.getElementById('content').innerHTML=html;
 document.querySelectorAll('#content a[href]').forEach(function(a){a.target='_blank';a.rel='noopener noreferrer';});
 if(window.MathJax&&MathJax.typesetPromise)MathJax.typesetPromise();
}
if(window.marked)render(); else window.addEventListener('load',render);
</script>
</body></html>
"""


def build_html(md_text, html_path, title, source, papers_cool, key=""):
    safe = md_text.replace("</script>", "<\\/script>")
    html = (HTML_TEMPLATE.replace("__TITLE__", title).replace("__FILEURL__", file_url(source))
            .replace("__KEY__", key).replace("__PCOOL__", papers_cool).replace("__MD__", safe))
    os.makedirs(os.path.dirname(html_path), exist_ok=True)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)


def write_meta(central, meta):
    with open(os.path.join(central, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def upsert_manifest(store_root, meta):
    path = os.path.join(store_root, "manifest.jsonl")
    rows = {}
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        r = json.loads(line)
                        rows[r["key"]] = r
                    except Exception:
                        pass
    rows[meta["key"]] = {"key": meta["key"], "title": meta.get("title", ""), "source": meta.get("source", ""),
                         "content_sha256": meta.get("content_sha256", ""),
                         "papers_cool": meta.get("papers_cool", ""), "status": meta.get("status", "")}
    os.makedirs(store_root, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for k in sorted(rows):
            f.write(json.dumps(rows[k], ensure_ascii=False) + "\n")


def update_index(store_root, meta):
    path = os.path.join(store_root, "index.md")
    line = f"- {meta.get('title','')} 〔{meta['key']}〕"
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
    except Exception:
        content = "# paper-parse store 索引\n\n"
    if meta["key"] not in content:
        content += line + "\n"
        os.makedirs(store_root, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)


def append_log(store_root, msg):
    os.makedirs(store_root, exist_ok=True)
    with open(os.path.join(store_root, "log.md"), "a", encoding="utf-8") as f:
        f.write(f"\n## [{_now()[:10]}] {msg}\n")


def mirror_entry(src_dir, dst_dir):
    if os.path.abspath(src_dir) == os.path.abspath(dst_dir):
        return
    if os.path.isdir(dst_dir):
        shutil.rmtree(dst_dir, ignore_errors=True)
    os.makedirs(os.path.dirname(dst_dir), exist_ok=True)
    shutil.copytree(src_dir, dst_dir)


def parse(pdf, output=None, refresh=False, config_path=None, store_root=None,
          token=None, proxy=None, no_local_cache=False, workers=8):
    """解析一篇 PDF/URL,返回 dict。库无关:输入→输出,中心缓存恒写。"""
    cfg = load_config(config_path)
    store = store_root or cfg.get("store_root") or DEFAULT_STORE_ROOT
    token = token or os.environ.get(cfg["ocr"].get("token_env", "PADDLEOCR_TOKEN")) or DEFAULT_TOKEN
    if not token:
        sys.exit("[错误] 未配置 OCR token。请设置环境变量 PADDLEOCR_TOKEN(或用 --token 传入)。"
                 "\n  PowerShell: $env:PADDLEOCR_TOKEN='你的token'   bash: export PADDLEOCR_TOKEN=你的token")
    job_url = cfg["ocr"].get("endpoint", DEFAULT_JOB_URL)
    model = cfg["ocr"].get("model", DEFAULT_MODEL)
    pcool_base = cfg.get("papers_cool_search", PAPERS_COOL_SEARCH)

    is_url = str(pdf).startswith("http")
    if not is_url and not os.path.isfile(pdf):
        sys.exit(f"[错误] 文件不存在:{pdf}")
    source = pdf if is_url else os.path.abspath(pdf)
    _bn = os.path.basename(str(pdf).split("?")[0].rstrip("/")) or "document"
    _root, _ext = os.path.splitext(_bn)
    stem = (_root if _ext.lower() in (".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp") else _bn) or "document"

    papers_root = store
    if no_local_cache or is_url:
        local_parent = None
    elif output:
        local_parent = os.path.abspath(output)
    else:
        local_parent = os.path.dirname(source)

    sha = hashlib.sha256()
    if is_url:
        sha.update(pdf.encode("utf-8"))
    else:
        with open(pdf, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                sha.update(chunk)
    sha.update(("|" + model).encode("utf-8"))
    content_sha = sha.hexdigest()

    key = cap_key(resolve_key(slugify(stem), source, papers_root), papers_root, local_parent, content_sha)
    central = os.path.join(papers_root, key)
    parsed_dir = os.path.join(central, "parsed")
    md_path = os.path.join(parsed_dir, f"{key}.full.md")
    html_path = os.path.join(parsed_dir, f"{key}.html")
    meta_path = os.path.join(central, "meta.json")
    local_dir = os.path.join(local_parent, ".parse", key) if local_parent else None

    def _mirror(src):
        if local_dir:
            try:
                mirror_entry(src, local_dir)
                print(f"[本地副本] {local_dir}")
            except Exception as e:  # noqa: BLE001
                print(f"[警告] 本地副本失败:{e}")

    def _res(c, k, title, pc, status, hit):
        return {"key": k, "title": title, "central": c, "local": local_dir,
                "md": os.path.join(c, "parsed", k + ".full.md"), "html": os.path.join(c, "parsed", k + ".html"),
                "source": source, "papers_cool": pc, "status": status, "cache_hit": hit}

    if not refresh:
        dup = find_by_sha(store, content_sha)
        if dup:
            dd = os.path.join(papers_root, dup)
            if os.path.isfile(os.path.join(dd, "meta.json")) and os.path.isfile(os.path.join(dd, "parsed", dup + ".full.md")):
                with open(os.path.join(dd, "meta.json"), encoding="utf-8") as f:
                    om = json.load(f)
                print(f"[内容去重命中] 已解析为 {dup},直接复用(不重 OCR)")
                _mirror(dd)
                return _res(dd, dup, om.get("title"), om.get("papers_cool"), om.get("status", "parsed"), True)

    if not refresh and os.path.isfile(meta_path) and os.path.isfile(md_path):
        try:
            with open(meta_path, encoding="utf-8") as f:
                old = json.load(f)
            if old.get("content_sha256") == content_sha:
                print(f"[缓存命中] {key}(跳过 OCR)")
                _mirror(central)
                return _res(central, key, old.get("title"), old.get("papers_cool"), old.get("status", "parsed"), True)
        except Exception:
            pass

    session = make_session(proxy)
    print(f"[处理] {pdf}  (model={model})")
    jid = submit_job(session, pdf, model, token, job_url)
    jsonl_url = poll_job(session, jid, token, job_url)
    results = fetch_results(session, jsonl_url)
    merged, stats = merge_results(session, results, parsed_dir, workers=workers)

    title = extract_title(merged, stem)
    papers_cool = pcool_base + quote_plus(title)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_header(source, papers_cool) + merged)
    build_html(merged, html_path, title, source, papers_cool, key)
    print(f"[合并完成] {stats['pages']} 页,图片 {stats['images_ok']}/{stats['images_ok'] + stats['images_fail']}")

    meta = {}
    if os.path.isfile(meta_path):
        try:
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            meta = {}
    meta.update({"key": key, "title": title, "source": source, "content_sha256": content_sha,
                 "papers_cool": papers_cool, "parsed_at": _now()})
    meta.setdefault("aliases", [])
    meta.setdefault("status", "parsed")
    write_meta(central, meta)
    upsert_manifest(store, meta)
    update_index(store, meta)
    append_log(store, f"parse | {title}")
    _mirror(central)
    print(f"[完成] 中心包:{central}")
    return _res(central, key, title, papers_cool, "parsed", False)


def main():
    p = argparse.ArgumentParser(description="paper-parse:PDF/文件夹/URL → 解析包(库无关,不用通用大模型)")
    p.add_argument("input", help="PDF 路径 / 文件夹(批量,递归 *.pdf)/ http(s) URL")
    p.add_argument("-o", "--output", default=None, help="本地副本输出目录(默认 PDF 旁 .parse)")
    p.add_argument("--no-local-cache", action="store_true", help="只写中心缓存,不产本地副本")
    p.add_argument("--refresh", action="store_true", help="强制重解析")
    p.add_argument("--store-root", dest="store_root", default=None, help="覆盖中心 store 根")
    p.add_argument("--config", default=None)
    p.add_argument("--token", default=None)
    p.add_argument("--proxy", default=None)
    p.add_argument("--workers", type=int, default=8)
    a = p.parse_args()
    kw = dict(output=a.output, refresh=a.refresh, config_path=a.config, store_root=a.store_root,
              token=a.token, proxy=a.proxy, no_local_cache=a.no_local_cache, workers=a.workers)
    if (not str(a.input).startswith("http")) and os.path.isdir(a.input):
        pdfs = sorted(glob.glob(os.path.join(a.input, "**", "*.pdf"), recursive=True))
        print(f"[批量] 共 {len(pdfs)} 个 PDF")
        ok = 0
        for i, pp in enumerate(pdfs, 1):
            print(f"\n--- [{i}/{len(pdfs)}] {os.path.basename(pp)} ---")
            try:
                parse(pp, **kw)
                ok += 1
            except SystemExit as e:
                print(f"[跳过] {e}")
            except Exception as e:  # noqa: BLE001
                print(f"[出错] {e}")
        print(f"\n[批量完成] 成功 {ok}/{len(pdfs)}")
        return
    r = parse(a.input, **kw)
    print(json.dumps({k: r[k] for k in ("key", "title", "central", "local", "papers_cool", "status", "cache_hit")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()