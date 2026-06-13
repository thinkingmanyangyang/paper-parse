#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""doctor —— 核对/修复 中心 store 与 本地副本(.parse)。库无关。
   python doctor.py [--fix] [--key K]
   按每篇 meta.source 推断默认本地副本 <source 目录>/.parse/<key>;-o 自定义位置的副本不在核对范围。
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parse_doc import load_config, mirror_entry

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def scan(store):
    out = []
    if os.path.isdir(store):
        for k in sorted(os.listdir(store)):
            mp = os.path.join(store, k, "meta.json")
            if os.path.isfile(mp):
                try:
                    with open(mp, encoding="utf-8") as f:
                        out.append((k, json.load(f)))
                except Exception:
                    pass
    return out


def read_sha(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f).get("content_sha256")
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description="核对/修复 中心 store ↔ 本地 .parse 副本")
    ap.add_argument("--fix", action="store_true")
    ap.add_argument("--key", default=None)
    ap.add_argument("--config", default=None)
    a = ap.parse_args()
    cfg = load_config(a.config)
    store = cfg.get("store_root")
    n = problems = fixed = 0
    for key, meta in scan(store):
        if a.key and key != a.key:
            continue
        n += 1
        central = os.path.join(store, key)
        src = meta.get("source", "")
        issues = []
        if src and not str(src).startswith("http"):
            local = os.path.join(os.path.dirname(src), ".parse", key)
            if not os.path.isfile(src):
                issues.append(f"原文不在:{src}")
            if not os.path.isdir(local):
                issues.append("默认本地副本缺失")
            elif read_sha(os.path.join(local, "meta.json")) != meta.get("content_sha256"):
                issues.append("本地副本与中心不一致")
            if a.fix and os.path.isdir(central) and ("本地副本" in " ".join(issues)):
                try:
                    mirror_entry(central, local)
                    fixed += 1
                    issues.append("→ 已重镜像")
                except Exception as e:  # noqa: BLE001
                    issues.append(f"→ 失败:{e}")
        else:
            issues.append("URL/无本地副本,仅中心")
        if issues and issues != ["URL/无本地副本,仅中心"]:
            problems += 1
            print(f"[!] {key}")
            for it in issues:
                print("    - " + it)
    print(f"\n核对 {n} 篇,问题 {problems}" + (f",已修 {fixed}" if a.fix else "(加 --fix 修复)"))


if __name__ == "__main__":
    main()