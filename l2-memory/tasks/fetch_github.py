#!/usr/bin/env python3
"""fetch_github.py — GitHub 官方 REST API 采集原语（search repositories）。
契约：stdout JSON，退出码 0/非0。外部响应边界校验。零 LLM。
可选 GITHUB_TOKEN 环境变量提升限额；无 token 未认证 60 req/hr 足够。
"""
import sys, json, os, urllib.request, urllib.parse

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

API = "https://api.github.com/search/repositories"
QUERY = "topic:artificial-intelligence pushed:>2026-08-11 sort:stars"


def fetch(url):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "h3-tracking/0.1"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", default=QUERY)
    ap.add_argument("--json", action="store_true",
                    help="兼容 wfengine json 标记（输出始终为 JSON）")
    args = ap.parse_args()
    q = args.query
    url = API + "?" + urllib.parse.urlencode({"q": q, "per_page": 20, "sort": "stars"})
    try:
        raw = json.loads(fetch(url))
    except Exception as e:
        sys.stderr.write(f"fetch_github FAIL: {e}\n")
        sys.exit(1)
    items = raw.get("items")
    if not isinstance(items, list):
        sys.stderr.write(f"fetch_github FAIL: unexpected payload\n")
        sys.exit(1)
    out = []
    for r in items:
        out.append({
            "id": str(r.get("id", "")),
            "title": r.get("full_name", ""),
            "url": r.get("html_url", ""),
            "date": r.get("pushed_at", ""),
            "summary": (r.get("description") or ""),
            "stars": r.get("stargazers_count"),
        })
    print(json.dumps({"source": "github", "items": out}, ensure_ascii=False))


if __name__ == "__main__":
    main()
