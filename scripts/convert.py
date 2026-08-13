#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将 links.txt 中的每个订阅链接转换为精简 Clash 配置，
并生成总订阅 all.yaml + all-provider.yaml
"""

import os
import re
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

# ==================== 配置区 ====================
SUBCONVERTER = os.environ.get("SUBCONVERTER", "https://api.v1.mk/sub")
LINKS_FILE = Path("links.txt")
OUTPUT_DIR = Path("clash")
REQUEST_TIMEOUT = 60
REQUEST_INTERVAL = 1.5
USER_AGENT = "ClashMetaForAndroid/2.11.1"
# ===============================================


def safe_name(url: str, idx: int) -> str:
    name = Path(urllib.parse.urlparse(url).path).stem
    name = re.sub(r"[^\w\-]", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name or f"sub_{idx:03d}"


def fetch_clash(session: requests.Session, url: str) -> str | None:
    """只拉取 proxies 列表（list=true），体积最小"""
    params = {
        "target": "clash",
        "url": url,
        "emoji": "true",
        "list": "true",       # 关键：只要节点列表
        "new_name": "true",
        "scv": "true",
    }
    try:
        r = session.get(SUBCONVERTER, params=params, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        text = r.text
        if "proxies:" not in text and "Proxy:" not in text:
            print(f"  [WARN] 返回内容不像 Clash 配置")
            return None
        return text
    except Exception as e:
        print(f"  [ERROR] 转换失败: {e}")
        return None


def extract_proxies(clash_text: str) -> list:
    try:
        data = yaml.safe_load(clash_text)
        if not data:
            return []
        proxies = data.get("proxies") or data.get("Proxy") or []
        return proxies if isinstance(proxies, list) else []
    except Exception:
        return []


def build_minimal_config(proxies: list, title: str = "") -> dict:
    """单独文件用的极简配置：只有节点 + 一个选择组"""
    names = [p["name"] for p in proxies]
    return {
        "proxies": proxies,
        "proxy-groups": [
            {
                "name": "🚀 节点选择",
                "type": "select",
                "proxies": ["DIRECT"] + names,
            },
            {
                "name": "♻️ 自动选择",
                "type": "url-test",
                "proxies": names,
                "url": "http://www.gstatic.com/generate_204",
                "interval": 300,
            },
        ],
        "rules": [
            "MATCH,🚀 节点选择",
        ],
    }


def build_combined_config(proxies: list) -> dict:
    """总订阅用的精简完整配置"""
    names = [p["name"] for p in proxies]
    return {
        "mixed-port": 7890,
        "allow-lan": True,
        "mode": "rule",
        "log-level": "info",
        "external-controller": "127.0.0.1:9090",
        "dns": {
            "enable": True,
            "enhanced-mode": "fake-ip",
            "nameserver": [
                "https://dns.alidns.com/dns-query",
                "223.5.5.5",
            ],
            "fallback": [
                "https://1.1.1.1/dns-query",
                "8.8.8.8",
            ],
        },
        "proxies": proxies,
        "proxy-groups": [
            {
                "name": "🚀 节点选择",
                "type": "select",
                "proxies": ["♻️ 自动选择", "DIRECT"] + names,
            },
            {
                "name": "♻️ 自动选择",
                "type": "url-test",
                "proxies": names,
                "url": "http://www.gstatic.com/generate_204",
                "interval": 300,
                "tolerance": 50,
            },
        ],
        "rules": [
            "GEOIP,CN,DIRECT",
            "MATCH,🚀 节点选择",
        ],
    }


def main():
    if not LINKS_FILE.exists():
        print(f"错误: 找不到 {LINKS_FILE}")
        return 1

    OUTPUT_DIR.mkdir(exist_ok=True)

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    lines = LINKS_FILE.read_text(encoding="utf-8").splitlines()
    urls = [
        line.strip()
        for line in lines
        if line.strip() and not line.strip().startswith("#")
    ]

    print(f"共 {len(urls)} 个订阅源，开始转换...\n")

    all_proxies = []
    seen_names = set()
    success = 0
    failed = 0

    for idx, url in enumerate(urls, 1):
        name = safe_name(url, idx)
        print(f"[{idx}/{len(urls)}] {name}")

        clash_text = fetch_clash(session, url)
        if not clash_text:
            failed += 1
            continue

        proxies = extract_proxies(clash_text)
        if not proxies:
            print(f"  [WARN] 没有解析到节点")
            failed += 1
            continue

        # 单独文件：极简配置
        minimal = build_minimal_config(proxies, name)
        out_file = OUTPUT_DIR / f"{name}.yaml"
        with open(out_file, "w", encoding="utf-8") as f:
            yaml.dump(minimal, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
        print(f"  → 已保存 {out_file}  ({len(proxies)} 节点)")

        # 收集到总列表（处理重名）
        for p in proxies:
            if not isinstance(p, dict):
                continue
            pname = p.get("name")
            if not pname:
                continue
            if pname in seen_names:
                base = pname
                n = 1
                while f"{base}_{n}" in seen_names:
                    n += 1
                p["name"] = f"{base}_{n}"
                pname = p["name"]
            seen_names.add(pname)
            all_proxies.append(p)

        success += 1
        time.sleep(REQUEST_INTERVAL)

    print(f"\n单独转换完成: 成功 {success}，失败 {failed}")
    print(f"去重后节点总数: {len(all_proxies)}")

    if all_proxies:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        # 总订阅（精简完整配置）
        combined = build_combined_config(all_proxies)
        combined_file = OUTPUT_DIR / "all.yaml"
        with open(combined_file, "w", encoding="utf-8") as f:
            f.write(f"# 自动生成于 {now}\n")
            f.write(f"# 来源: {success}  节点: {len(all_proxies)}\n\n")
            yaml.dump(combined, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
        print(f"总订阅已生成: {combined_file}")

        # 纯 proxies（proxy-provider 用）
        provider_file = OUTPUT_DIR / "all-provider.yaml"
        with open(provider_file, "w", encoding="utf-8") as f:
            yaml.dump({"proxies": all_proxies}, f, allow_unicode=True, sort_keys=False)
        print(f"Provider 版本已生成: {provider_file}")
    else:
        print("没有可用节点，跳过总订阅生成")

    print("\n全部完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
