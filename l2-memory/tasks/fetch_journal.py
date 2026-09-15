#!/usr/bin/env python3
"""fetch_journal.py — 期刊官方 RSS 采集原语（PRL / Nature Physics / Science）。
契约：stdout JSON，退出码 0/非0。外部响应边界校验。零 LLM。
"""
import sys, json, time, urllib.request
import xml.etree.ElementTree as ET

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

FEEDS = {
    "prl": "https://feeds.aps.org/rss/recent/prl.xml",
    "nature-physics": "https://www.nature.com/nphys/current_issue/rss/",
    "science": "https://www.science.org/rss/news_current.xml",
}


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "h3-tracking/0.1"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def parse(xml_bytes):
    root = ET.fromstring(xml_bytes)
    items = []
    # RSS 2.0 的 item 是无命名空间的；RSS 1.0/RDF 的 item 在 purl.org/rss/1.0/ 命名空间
    for item in root.findall(".//item") + root.findall(".//{http://purl.org/rss/1.0/}item"):
        title = " ".join((item.findtext("title") or item.findtext("{http://purl.org/rss/1.0/}title") or "").split())
        link = (item.findtext("link") or item.findtext("{http://purl.org/rss/1.0/}link") or "").strip()
        pub_date = (item.findtext("pubDate") or item.findtext("{http://purl.org/rss/1.0/}date") or "").strip()
        desc = " ".join((item.findtext("description") or item.findtext("{http://purl.org/rss/1.0/}description") or "").split())
        items.append({
            "id": link,
            "title": title,
            "url": link,
            "date": pub_date,
            "summary": desc,
        })
    return items


def main():
    out_items = []
    for name, url in FEEDS.items():
        try:
            items = parse(fetch(url))
        except Exception as e:
            sys.stderr.write(f"fetch_journal {name} FAIL: {e}\n")
            continue
        if not isinstance(items, list):
            sys.stderr.write(f"fetch_journal {name} FAIL: unexpected payload\n")
            continue
        for it in items:
            it["source"] = name
        out_items.extend(items)
        time.sleep(1)
    print(json.dumps({"source": "journal", "items": out_items}, ensure_ascii=False))


if __name__ == "__main__":
    main()
