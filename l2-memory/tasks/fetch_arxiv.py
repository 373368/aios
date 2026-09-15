#!/usr/bin/env python3
"""fetch_arxiv.py — arXiv 官方 API 采集原语。
契约：stdout JSON，退出码 0/非0。外部响应边界校验。零 LLM。
"""
import sys, json, time, urllib.request, urllib.parse
import xml.etree.ElementTree as ET

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

ARXIV_API = "http://export.arxiv.org/api/query"
NS = {"a": "http://www.w3.org/2005/Atom"}

QUERY = 'cat:cs.AI OR cat:cs.LG OR cat:hep-th OR cat:quant-ph'
MAX = 30  # 一次窗口最多条数


def fetch(query, days=1, max_results=MAX):
    params = {
        "search_query": query,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": str(max_results),
    }
    url = ARXIV_API + "?" + urllib.parse.urlencode(params)
    time.sleep(1)  # arXiv 建议 ≤1 req/3s，单次查询 1s 保守
    req = urllib.request.Request(url, headers={"User-Agent": "h3-tracking/0.1"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def parse(xml_bytes):
    root = ET.fromstring(xml_bytes)
    items = []
    for entry in root.findall("a:entry", NS):
        aid = entry.find("a:id", NS).text.split("/abs/")[-1]
        title = " ".join((entry.find("a:title", NS).text or "").split())
        summary = " ".join((entry.find("a:summary", NS).text or "").split())
        published = entry.find("a:published", NS).text
        authors = [a.find("a:name", NS).text for a in entry.findall("a:author", NS)]
        items.append({
            "id": aid,
            "title": title,
            "url": f"https://arxiv.org/abs/{aid}",
            "authors": authors,
            "date": published,
            "summary": summary,
        })
    return items


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", default=QUERY)
    args = ap.parse_args()
    query = args.query
    try:
        xml_bytes = fetch(query)
        items = parse(xml_bytes)
    except Exception as e:
        sys.stderr.write(f"fetch_arxiv FAIL: {e}\n")
        sys.exit(1)
    # 边界校验：非法 shape 直接失败
    if not isinstance(items, list):
        sys.stderr.write("fetch_arxiv FAIL: unexpected payload\n")
        sys.exit(1)
    print(json.dumps({"source": "arxiv", "items": items}, ensure_ascii=False))


if __name__ == "__main__":
    main()
