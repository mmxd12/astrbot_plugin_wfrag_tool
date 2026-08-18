#!/usr/bin/env python3
"""刷新 riven_weapons.json（紫卡武器表：en/zh/rivenType/disposition）。

数据源是 wfapi 的 /wm/auctions，里面的 riven_items + auctionsWeapons 就是
wm 的紫卡武器与玄骸/姐妹武器词库。DE 调整倾向值后跑一次即可。

    python3 refresh_riven_weapons.py
"""
import json
import urllib.request
from pathlib import Path

API = "http://111.170.14.106:18511/wm/auctions"
OUT = Path(__file__).parent / "riven_weapons.json"


def main() -> None:
    req = urllib.request.Request(API, headers={"User-Agent": "riven-analyse/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode())

    table: dict[str, dict] = {}
    for key in ("riven_items", "auctionsWeapons"):
        for it in data.get(key, []):
            i18n = it.get("i18n") or {}
            en = (i18n.get("en") or {}).get("name") or it.get("slug", "")
            if not en:
                continue
            table[en] = {
                "en": en,
                "zh": (i18n.get("zh-hans") or {}).get("name") or en,
                "rivenType": it.get("rivenType", "rifle"),
                "disposition": it.get("disposition", 1.0),
                "slug": it.get("slug", ""),
            }

    if len(table) < 300:
        raise SystemExit(f"只拿到 {len(table)} 把武器，疑似数据源异常，未写入")

    OUT.write_text(json.dumps(table, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"已写入 {OUT}：{len(table)} 把武器")


if __name__ == "__main__":
    main()
