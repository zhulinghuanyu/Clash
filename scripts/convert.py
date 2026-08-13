import os
import re
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

# ==================== 自定义 YAML Dumper 以实现 proxies 单行输出 ====================
class FlowDict(dict):
    pass
class FlowDumper(yaml.SafeDumper):
    pass
def _represent_flow_dict(dumper, data):
    return dumper.represent_mapping('tag:yaml.org,2002:map', data.items(), flow_style=True)
FlowDumper.add_representer(FlowDict, _represent_flow_dict)

def convert_to_flow(obj):
    if isinstance(obj, dict):
        return FlowDict({k: convert_to_flow(v) for k, v in obj.items()})
    elif isinstance(obj, list):
        return [convert_to_flow(i) for i in obj]
    return obj
# ====================================================================================

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
    params = {
        "target": "clash",
        "url": url,
        "emoji": "true",
        "list": "false",      
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

def simplify_and_format_clash(clash_text: str, proxies: list) -> str:
    try:
        data = yaml.safe_load(clash_text)
        if not data or not isinstance(data, dict):
            return clash_text    
        names = [p.get("name") for p in proxies if p.get("name")]
        data["proxies"] = convert_to_flow(proxies)
        data["proxy-groups"] = [
            {
                "name": "🚀 节点选择",
                "type": "select",
                "proxies": ["♻️ 自动选择"] + names
            },
            {
                "name": "♻️ 自动选择",
                "type": "url-test",
                "proxies": names,
                "url": "http://www.gstatic.com/generate_204",
                "interval": 300
            },
            {
                "name": "🐟 漏网之鱼",
                "type": "select",
                "proxies": ["🚀 节点选择", "♻️ 自动选择"]
            },
        ]
        data["rules"] = [
            "GEOIP,LAN,DIRECT",
            "GEOIP,CN,DIRECT",
            "MATCH,🐟 漏网之鱼"
        ]
        for key in ["dns", "rule-providers", "tun", "ebpf", "script", "ruleset", "proxy-provider", "listeners"]:
            data.pop(key, None)            
        return yaml.dump(
            data, 
            Dumper=FlowDumper, 
            allow_unicode=True, 
            sort_keys=False, 
            default_flow_style=False, 
            width=4096 
        )
    except Exception:
        return clash_text

def build_combined_config(proxies: list) -> dict:
    proxy_names = [p["name"] for p in proxies]
    return {
        "port": 7890,
        "socks-port": 7891,
        "allow-lan": True,
        "mode": "rule",
        "log-level": "info",
        "proxies": convert_to_flow(proxies),
        "proxy-groups": [
            {
                "name": "🚀 节点选择",
                "type": "select",
                "proxies": ["♻️ 自动选择"] + proxy_names,
            },
            {
                "name": "♻️ 自动选择",
                "type": "url-test",
                "proxies": proxy_names,
                "url": "http://www.gstatic.com/generate_204",
                "interval": 300,
            },
            {
                "name": "🐟 漏网之鱼",
                "type": "select",
                "proxies": ["🚀 节点选择", "♻️ 自动选择"],
            },
        ],
        "rules": [
            "GEOIP,LAN,DIRECT",
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
        raw_proxies = extract_proxies(clash_text)
        simplified_proxies = []
        for p in raw_proxies:
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
            simplified_proxies.append(p)
        success += 1
        simplified_text = simplify_and_format_clash(clash_text, simplified_proxies)
        out_file = OUTPUT_DIR / f"{name}.yaml"
        out_file.write_text(simplified_text, encoding="utf-8")
        print(f"  → 已保存 {out_file}")
        time.sleep(REQUEST_INTERVAL)
    print(f"\n单独转换完成: 成功 {success}，失败 {failed}")
    print(f"去重后节点总数: {len(all_proxies)}")

    if all_proxies:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        combined = build_combined_config(all_proxies)
        combined_file = OUTPUT_DIR / "all.yaml"
        with open(combined_file, "w", encoding="utf-8") as f:
            f.write(f"# 自动生成于 {now}\n")
            f.write(f"# 来源数量: {success}  节点数量: {len(all_proxies)}\n\n")
            yaml.dump(
                combined,
                f,
                Dumper=FlowDumper,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
                width=4096
            )
        print(f"总订阅已生成: {combined_file}")
        provider_file = OUTPUT_DIR / "all-provider.yaml"
        with open(provider_file, "w", encoding="utf-8") as f:
            yaml.dump(
                {"proxies": convert_to_flow(all_proxies)},
                f,
                Dumper=FlowDumper,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
                width=4096
            )
        print(f"Provider 版本已生成: {provider_file}")
    else:
        print("没有可用节点，跳过总订阅生成")
    print("\n全部完成")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
