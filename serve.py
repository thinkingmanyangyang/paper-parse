#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""serve —— paper-parse 本地浏览 / 搜索 / 在资源管理器定位原文。纯标准库。
   python serve.py [--port 8765] [--open]"""
import argparse
import html as html_mod
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from parse_doc import load_config
except Exception:
    def load_config(p=None):
        return {"store_root": os.path.join(os.path.dirname(os.path.abspath(__file__)), "store")}

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_md_cache = {}


def read_text(path):
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return ""
    hit = _md_cache.get(path)
    if hit and hit[0] == mt:
        return hit[1]
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            c = f.read()
    except Exception:
        c = ""
    _md_cache[path] = (mt, c)
    return c


def scan(store):
    out = []
    if not os.path.isdir(store):
        return out
    for key in sorted(os.listdir(store)):
        d = os.path.join(store, key)
        mp = os.path.join(d, "meta.json")
        if not os.path.isfile(mp):
            continue
        try:
            with open(mp, encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            meta = {}
        html_rel = f"{key}/parsed/{key}.html"
        out.append({"key": key, "title": meta.get("title") or key, "status": meta.get("status", ""),
                    "papers_cool": meta.get("papers_cool", ""), "source": meta.get("source", ""),
                    "html": html_rel if os.path.isfile(os.path.join(store, html_rel)) else "",
                    "full_md": os.path.join(d, "parsed", f"{key}.full.md")})
    return out


def snippet(content, terms, width=100):
    low = content.lower()
    pos = min([p for p in (low.find(t) for t in terms) if p != -1] or [-1])
    if pos == -1:
        return ""
    s, e = max(0, pos - width // 3), min(len(content), pos + width)
    seg = html_mod.escape(content[s:e].replace("\n", " "))
    for t in sorted(set(terms), key=len, reverse=True):
        if t:
            seg = re.sub("(" + re.escape(html_mod.escape(t)) + ")", r"<mark>\1</mark>", seg, flags=re.I)
    return ("… " if s > 0 else "") + seg + (" …" if e < len(content) else "")


def search(entries, q):
    q = (q or "").strip()
    if not q:
        return [{**e, "snippet": "", "nm": True} for e in entries]
    terms = [t for t in q.lower().split() if t]
    res = []
    for e in entries:
        name = e["title"].lower()
        body = read_text(e["full_md"]).lower()
        if all(t in name + "\n" + body for t in terms):
            nm = all(t in name for t in terms)
            res.append({**e, "nm": nm, "snippet": "" if nm else snippet(read_text(e["full_md"]), terms)})
    return res


INDEX_HTML = """<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>paper-parse 论文库</title>
<style>
 body{max-width:1000px;margin:24px auto;padding:0 16px;font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;color:#1a1a1a}
 #q{width:100%;font-size:16px;padding:10px 12px;box-sizing:border-box;border:1px solid #ccc;border-radius:8px}
 .meta{color:#888;font-size:13px;margin:10px 0}
 .item{padding:12px 0;border-bottom:1px solid #eee}
 .item a.t{font-size:16px;font-weight:600;color:#1558d6;text-decoration:none}
 .sub{color:#777;font-size:12px;margin-top:3px}
 .snip{color:#333;font-size:13px;margin-top:6px;background:#fafafa;padding:6px 9px;border-radius:6px;line-height:1.6}
 mark{background:#ffe28a} .tag{font-size:11px;color:#fff;background:#34a853;border-radius:4px;padding:0 6px;margin-left:6px}
 .pc{font-size:12px;color:#b8860b;margin-left:8px;text-decoration:none}
 .rv{font-size:12px;margin-left:8px;border:1px solid #ccc;background:#fafafa;border-radius:5px;cursor:pointer;padding:1px 7px}
</style></head><body>
<h1>📄 paper-parse 论文库</h1>
<input id="q" placeholder="搜索 标题 / 全文(空格分隔多词=同时包含)…" autofocus>
<div class="meta" id="meta"></div><div id="list"></div>
<script>
const q=document.getElementById('q'),L=document.getElementById('list'),M=document.getElementById('meta');let t=null;
function esc(s){return (s||'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function reveal(k){fetch('/reveal?key='+k).then(r=>r.json()).then(d=>{if(!d.ok)alert(d.msg||'定位失败');});}
function render(d){M.textContent=d.count+' 篇';
 L.innerHTML=d.papers.map(p=>{
  const open=p.html?`<a class="t" href="/kb/${encodeURIComponent(p.key)}/parsed/${encodeURIComponent(p.key)}.html" target="_blank">${esc(p.title)}</a>`:esc(p.title);
  const pc=p.papers_cool?`<a class="pc" href="${p.papers_cool}" target="_blank">papers.cool↗</a>`:'';
  const rv=(p.source&&!String(p.source).startsWith('http'))?`<button class="rv" onclick="reveal('${encodeURIComponent(p.key)}')">📂 定位原文</button>`:'';
  const tag=p.nm?'<span class="tag">名称</span>':'';
  const sn=p.snippet?`<div class="snip">${p.snippet}</div>`:'';
  return `<div class="item">${open}${tag}${pc}${rv}<div class="sub">〔${esc(p.key)}〕 · ${esc(p.status)}</div>${sn}</div>`;
 }).join('')||'<div style="color:#999;padding:30px 0">没有匹配。</div>';}
function go(){fetch('/api/papers?q='+encodeURIComponent(q.value)).then(r=>r.json()).then(render);}
q.addEventListener('input',()=>{clearTimeout(t);t=setTimeout(go,180);});go();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    store = ""

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def do_GET(self):
        u = urlparse(self.path)
        path = unquote(u.path)
        if path in ("/", "/index.html"):
            self._send(200, INDEX_HTML)
        elif path == "/api/papers":
            q = parse_qs(u.query).get("q", [""])[0]
            res = search(scan(self.store), q)
            out = [{k: v for k, v in r.items() if k != "full_md"} for r in res]
            self._send(200, json.dumps({"count": len(out), "papers": out}, ensure_ascii=False), "application/json; charset=utf-8")
        elif path == "/reveal":
            key = parse_qs(u.query).get("key", [""])[0]
            self._send(200, json.dumps(self._reveal(key), ensure_ascii=False), "application/json; charset=utf-8")
        elif path == "/open":
            key = parse_qs(u.query).get("key", [""])[0]
            self._send(200, json.dumps(self._open(key), ensure_ascii=False), "application/json; charset=utf-8")
        elif path.startswith("/kb/"):
            self._file(path[len("/kb/"):])
        else:
            self._send(404, "not found", "text/plain; charset=utf-8")

    def _reveal(self, key):
        mp = os.path.join(self.store, key, "meta.json")
        if not os.path.isfile(mp):
            return {"ok": False, "msg": "未知 key"}
        try:
            with open(mp, encoding="utf-8") as f:
                src = json.load(f).get("source", "")
        except Exception:
            return {"ok": False, "msg": "读 meta 失败"}
        if not src or str(src).startswith("http"):
            return {"ok": False, "msg": "无本地原文(URL 来源)"}
        if not os.path.isfile(src):
            return {"ok": False, "msg": "原文已移动/删除:" + src}
        try:
            subprocess.Popen('explorer /select,"' + src + '"')
            return {"ok": True}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "msg": str(e)}

    def _open(self, key):
        mp = os.path.join(self.store, key, "meta.json")
        if not os.path.isfile(mp):
            return {"ok": False, "msg": "未知 key"}
        try:
            with open(mp, encoding="utf-8") as f:
                src = json.load(f).get("source", "")
        except Exception:
            return {"ok": False, "msg": "读 meta 失败"}
        if not src or str(src).startswith("http"):
            return {"ok": False, "msg": "无本地原文(URL 来源)"}
        if not os.path.isfile(src):
            return {"ok": False, "msg": "原文已移动/删除:" + src}
        try:
            os.startfile(src)  # noqa: S606  Windows 默认程序打开 PDF
            return {"ok": True}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "msg": str(e)}

    @staticmethod
    def _inject_open(htmltext, key):
        if "pp-reveal" in htmltext or "/reveal?key=" in htmltext:
            return htmltext  # 新模板已自带三项,勿重复注入
        script = ("<script>(function(){try{var k=" + json.dumps(key) + ";"
                  "var h=document.querySelector('.phead');if(!h)return;"
                  "function call(p){return function(e){e.preventDefault();"
                  "fetch(p+encodeURIComponent(k)).then(function(r){return r.json();})"
                  ".then(function(d){if(!d.ok)alert(d.msg||'操作失败');})"
                  ".catch(function(){alert('操作失败');});};}"
                  "var a=h.querySelector('a');if(a)a.addEventListener('click',call('/open?key='));"
                  "var s=document.createTextNode(' | ');"
                  "var rv=document.createElement('a');rv.href='#';rv.textContent='📂 文件位置';"
                  "rv.addEventListener('click',call('/reveal?key='));"
                  "h.appendChild(s);h.appendChild(rv);"
                  "}catch(e){}})();</script>")
        if "</body>" in htmltext:
            return htmltext.replace("</body>", script + "</body>", 1)
        return htmltext + script

    def _file(self, rel):
        root = os.path.realpath(self.store)
        full = os.path.realpath(os.path.join(root, rel))
        if full != root and not full.startswith(root + os.sep):
            self._send(403, "forbidden", "text/plain")
            return
        if not os.path.isfile(full):
            self._send(404, "not found", "text/plain")
            return
        if full.lower().endswith(".html"):
            key = rel.replace("\\", "/").strip("/").split("/")[0]
            self._send(200, self._inject_open(read_text(full), key))
            return
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype == "application/json":
            ctype += "; charset=utf-8"
        with open(full, "rb") as f:
            self._send(200, f.read(), ctype)


def main():
    ap = argparse.ArgumentParser(description="paper-parse 浏览/搜索/定位原文")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--store-root", dest="store_root", default=None)
    ap.add_argument("--config", default=None)
    ap.add_argument("--open", action="store_true")
    a = ap.parse_args()
    Handler.store = os.path.abspath(a.store_root or load_config(a.config)["store_root"])
    url = f"http://{a.host}:{a.port}/"
    print(f"[paper-parse 浏览] {url}  (store: {Handler.store}, {len(scan(Handler.store))} 篇)  Ctrl+C 停")
    if a.open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        ThreadingHTTPServer((a.host, a.port), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\n[已停止]")


if __name__ == "__main__":
    main()