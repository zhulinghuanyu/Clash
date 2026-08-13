#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将 links.txt 中的每一行订阅链接转换为独立的 Clash YAML 文件
"""

import os
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

# 公共 subconverter 接口列表（按优先级）
BACKENDS = [
    "https://api.v1.mk/sub?target=clash&url=",
    "https://sub.xeton.dev/sub?target=clash&url=",
    "https://url.v1.mk/sub?target=clash&url=",
]

INPUT_FILE = "links.txt"
OUTPUT_DIR = "clash_subs"
MAX_WORKERS = 8
TIMEOUT = 30


def download_links():
    """从 GitHub 下载最新的 links.txt"""
    url = "https://raw.githubusercontent.com/zhulinghuanyu/jiedian/main/links.txt"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        content = resp.read().decode("utf-8")
    with open(INPUT_FILE, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"已下载 links.txt，共 {len(content.strip().splitlines())} 行")


def extract_name(url: str) -> str:
    """从原始链接提取文件名（去掉 _nodes.txt 等）"""
    # 例如 .../nodes/91vpn_nodes.txt → 91vpn
    m = re.search(r"/nodes/([^/]+?)(?:_nodes)?\.txt$", url)
    if m:
        name = m.group(1)
        return name.replace("_nodes", "").replace("-", "_")
    # fallback
    return re.sub(r"[^\w\-]", "_", url.split("/")[-1].replace(".txt", ""))[:40]


def convert_one(idx: int, original_url: str) -> tuple[str, bool, str]:
    """转换单个订阅链接，返回 (文件名, 是否成功, 消息)"""
    name = extract_name(original_url)
    filename = f"{idx:02d}_{name}.yaml"
    filepath = os.path.join(OUTPUT_DIR, filename)

    encoded = urllib.parse.quote(original_url, safe="")
    last_error = ""

    for backend in BACKENDS:
        convert_url = backend + encoded
        try:
            req = urllib.request.Request(
                convert_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "text/yaml, text/plain, */*",
                },
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                content = resp.read().decode("utf-8", errors="ignore")

            # 简单校验是否像 Clash 配置
            if "proxies:" in content or "Proxy:" in content or content.strip().startswith("port:"):
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(content)
                return filename, True, f"OK ({len(content)} bytes)"
            else:
                last_error = f"返回内容不像 Clash YAML (前100字: {content[:100]!r})"
        except Exception as e:
            last_error = str(e)
            time.sleep(0.5)
            continue

    return filename, False, last_error


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    if not os.path.exists(INPUT_FILE):
        print("本地没有 links.txt，正在下载...")
        download_links()

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        links = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    print(f"共 {len(links)} 个订阅链接，开始转换为 Clash YAML 文件...\n")

    success = 0
    failed = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(convert_one, i + 1, url): (i + 1, url)
            for i, url in enumerate(links)
        }

        for future in as_completed(futures):
            idx, url = futures[future]
            try:
                filename, ok, msg = future.result()
                if ok:
                    success += 1
                    print(f"[✓] {filename}  ← {msg}")
                else:
                    failed.append((filename, msg))
                    print(f"[✗] {filename}  ← {msg}")
            except Exception as e:
                print(f"[✗] 未知错误: {e}")

    print("\n" + "=" * 50)
    print(f"完成！成功 {success}/{len(links)} 个")
    if failed:
        print(f"失败 {len(failed)} 个：")
        for name, err in failed:
            print(f"  - {name}: {err}")

    print(f"\n所有文件保存在目录: {os.path.abspath(OUTPUT_DIR)}")


if __name__ == "__main__":
    main()
