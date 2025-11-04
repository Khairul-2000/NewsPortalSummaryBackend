import asyncio
import json
from argparse import ArgumentParser
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import aiohttp
from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler


def select_article_links(links: Dict, base_host: Optional[str], limit: int) -> List[str]:
    """Pick likely article links from crawl4ai's result.links dict.
    - Prefer internal links matching news-like paths
    - Deduplicate and cap by limit
    """
    selected: List[str] = []

    def add_from(items: List[Dict]):
        if not isinstance(items, list):
            return
        for it in items:
            href = (it or {}).get("href")
            if not href or not href.startswith("http"):
                continue
            if base_host and urlparse(href).netloc != base_host:
                continue
            # Heuristics: include common news sections and article pages
            if any(seg in href for seg in ["/news/", "/articles/", "/sport/", "/business/", "/world/", "/culture/"]):
                if not any(href.lower().endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".m3u8", ".pdf", ".css", ".js"]):
                    if href not in selected:
                        selected.append(href)
                        if len(selected) >= limit:
                            return

    if isinstance(links, dict):
        add_from(links.get("internal"))
        if len(selected) < limit:
            add_from(links.get("external"))  # as fallback

    return selected[:limit]


async def fetch_html(session: aiohttp.ClientSession, url: str, timeout: int = 25) -> Tuple[str, Optional[str]]:
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        async with session.get(url, headers=headers, timeout=timeout) as resp:
            resp.raise_for_status()
            return url, await resp.text()
    except Exception:
        return url, None


def extract_article_fields(html: str, url: str) -> Dict[str, str]:
    soup = BeautifulSoup(html, "lxml")

    def meta(name=None, prop=None) -> Optional[str]:
        tag = None
        if name:
            tag = soup.find("meta", attrs={"name": name})
        if not tag and prop:
            tag = soup.find("meta", attrs={"property": prop})
        if tag and tag.get("content"):
            return tag["content"].strip()
        return None

    title = meta("og:title") or meta(prop="og:title") or meta("twitter:title")
    if not title and soup.title and soup.title.string:
        title = soup.title.string.strip()

    desc = meta("description") or meta(prop="og:description") or meta("twitter:description")
    if not desc:
        # Fallback: first 1-2 paragraphs of main content
        paragraphs = [p.get_text(strip=True) for p in soup.find_all("p") if p.get_text(strip=True)]
        desc = " ".join(paragraphs[:2])[:400] if paragraphs else ""

    return {"title": title or url, "summary": desc or "", "readMore": url}


async def scrape_and_save(url: str, limit: int = 20, concurrency: int = 8, output: Optional[str] = None) -> str:
    # 1) Crawl the seed page with crawl4ai to gather links
    async with AsyncWebCrawler() as crawler:
        seed = await crawler.arun(url=url)

    base_host = urlparse(url).netloc
    candidates = select_article_links(seed.links or {}, base_host, limit)

    # 2) Fetch candidate pages concurrently and extract meta
    connector = aiohttp.TCPConnector(limit_per_host=concurrency)
    async with aiohttp.ClientSession(connector=connector) as session:
        sem = asyncio.Semaphore(concurrency)

        async def bounded(u: str):
            async with sem:
                return await fetch_html(session, u)

        results = await asyncio.gather(*(bounded(u) for u in candidates))

    articles: List[Dict[str, str]] = []
    referrals: List[str] = []
    for u, html in results:
        if not html:
            continue
        art = extract_article_fields(html, u)
        articles.append(art)
        referrals.append(art["readMore"])

    payload = {
        "source": url,
        "generatedAt": datetime.utcnow().isoformat() + "Z",
        "articles": articles,
        "referralURLs": referrals,
        "count": len(articles),
    }

    if output is None:
        outdir = Path("output")
        outdir.mkdir(parents=True, exist_ok=True)
        host = base_host or "news"
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%SZ")
        output = str(outdir / f"news_{host}_{ts}.json")

    Path(output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def parse_args():
    p = ArgumentParser(description="Scrape a URL and save article summaries JSON")
    p.add_argument("--url", required=True, help="Seed URL, e.g., https://www.bbc.com/")
    p.add_argument("--limit", type=int, default=20, help="Max number of article links to follow")
    p.add_argument("--concurrency", type=int, default=8, help="Fetch concurrency for article pages")
    p.add_argument("--output", default=None, help="Output JSON path (default: output/news_<host>_<ts>.json)")
    return p.parse_args()


async def _amain():
    args = parse_args()
    out = await scrape_and_save(args.url, args.limit, args.concurrency, args.output)
    print(out)


if __name__ == "__main__":
    asyncio.run(_amain())
