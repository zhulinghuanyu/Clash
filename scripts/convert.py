#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将 links.txt 中的每个订阅链接转换为独立完整 Clash 配置，
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
REQUEST_INTERVAL = 1.5          # 每次请求间隔（秒），防止被限流
USER_AGENT = "ClashMetaForAndroid/2.11.1"
# ===============================================


def safe_name(url: str, idx: int) -> str:
    """从 URL 提取干净的文件名"""
    name = Path(urllib.parse.urlparse(url).path).stem
    name = re.sub(r"[^\w\-]", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name or f"sub_{idx:03d}"


def fetch_clash(session: requests.Session, url: str) -> str | None:
    """调用 subconverter 获取完整 Clash 配置"""
    params = {
        "target": "clash",
        "url": url,
        "emoji": "true",
        "list": "false",      # 完整配置
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
    """从完整配置中提取 proxies 列表"""
    try:
        data = yaml.safe_load(clash_text)
        if not data:
            return []
        proxies = data.get("proxies") or data.get("Proxy") or []
        return proxies if isinstance(proxies, list) else []
    except Exception:
        return []


def build_combined_config(proxies: list) -> dict:
    """构建完整的总订阅配置"""
    proxy_names = [p["name"] for p in proxies]

    return {
        "port": 7890,
        "socks-port": 7891,
        "allow-lan": True,
        "mode": "rule",
        "log-level": "info",
        "external-controller": "127.0.0.1:9090",
        "dns": {
            "enable": True,
            "listen": "0.0.0.0:53",
            "enhanced-mode": "fake-ip",
            "nameserver": [
                "https://dns.alidns.com/dns-query",
                "https://doh.pub/dns-query",
                "223.5.5.5",
            ],
            "fallback": [
                "https://1.1.1.1/dns-query",
                "https://dns.google/dns-query",
                "8.8.8.8",
            ],
            "fallback-filter": {
                "geoip": True,
                "geoip-code": "CN",
                "ipcidr": ["240.0.0.0/4"],
            },
        },
        "proxies": proxies,
        "proxy-groups": [
            {
                "name": "🚀 节点选择",
                "type": "select",
                "proxies": ["♻️ 自动选择", "DIRECT"] + proxy_names,
            },
            {
                "name": "♻️ 自动选择",
                "type": "url-test",
                "proxies": proxy_names,
                "url": "http://www.gstatic.com/generate_204",
                "interval": 300,
                "tolerance": 50,
            },
            {
                "name": "🌍 国外媒体",
                "type": "select",
                "proxies": ["🚀 节点选择", "♻️ 自动选择", "DIRECT"],
            },
            {
                "name": "📲 电报信息",
                "type": "select",
                "proxies": ["🚀 节点选择", "♻️ 自动选择", "DIRECT"],
            },
            {
                "name": "🍃 应用净化",
                "type": "select",
                "proxies": ["REJECT", "DIRECT", "🚀 节点选择"],
            },
            {
                "name": "🐟 漏网之鱼",
                "type": "select",
                "proxies": ["🚀 节点选择", "♻️ 自动选择", "DIRECT"],
            },
        ],
        "rules": [
            "DOMAIN-SUFFIX,local,DIRECT",
            "IP-CIDR,127.0.0.0/8,DIRECT",
            "IP-CIDR,192.168.0.0/16,DIRECT",
            "IP-CIDR,10.0.0.0/8,DIRECT",
            "IP-CIDR,172.16.0.0/12,DIRECT",
            "GEOIP,CN,DIRECT",
            "MATCH,🐟 漏网之鱼",
        ],
    }


def main():
    if not LINKS_FILE.exists():
        print(f"错误: 找不到 {LINKS_FILE}")
        return 1

    OUTPUT_DIR.mkdir(exist_ok=True)

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    # 读取订阅源
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

        # 保存单独完整配置
        out_file = OUTPUT_DIR / f"{name}.yaml"
        out_file.write_text(clash_text, encoding="utf-8")
        print(f"  → 已保存 {out_file}")

        # 提取节点用于总订阅（处理重名）
        proxies = extract_proxies(clash_text)
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

    # 生成总订阅
    if all_proxies:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        combined = build_combined_config(all_proxies)

        # 完整配置版
        combined_file = OUTPUT_DIR / "all.yaml"
        with open(combined_file, "w", encoding="utf-8") as f:
            f.write(f"# 自动生成于 {now}\n")
            f.write(f"# 来源数量: {success}  节点数量: {len(all_proxies)}\n\n")
            yaml.dump(
                combined,
                f,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
            )
        print(f"总订阅已生成: {combined_file}")

        # 纯 proxies 列表（适合 proxy-provider）
        provider_file = OUTPUT_DIR / "all-provider.yaml"
        with open(provider_file, "w", encoding="utf-8") as f:
            yaml.dump(
                {"proxies": all_proxies},
                f,
                allow_unicode=True,
                sort_keys=False,
            )
        print(f"Provider 版本已生成: {provider_file}")
    else:
        print("没有可用节点，跳过总订阅生成")

    print("\n全部完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
