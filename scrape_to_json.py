import asyncio
import json
import os
import re
from argparse import ArgumentParser
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import aiohttp
from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler


def collect_candidate_links(links_obj: Dict, base_domain: Optional[str] = None, limit: Optional[int] = 30) -> List[str]:
    """Collect likely article links from crawl4ai result.links
    - Prefer internal links on same domain
    - Heuristics for news-like content (contains '/news/', '/articles/', '/sport/')
    - Filter out media players and non-HTML assets
    """
    candidates: List[str] = []

    def accept(u: str) -> bool:
        if not u or not u.startswith("http"):
            return False
        # Exclude obvious non-article endpoints
        if any(x in u for x in [
            "/audio/play/", "/reel/video/", "/video", "/live/", "playlist", "/sounds/",
            ".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".m3u8", ".pdf", ".css", ".js"
        ]):
            return False
        # Keep news-y paths
        if any(seg in u for seg in ["/news/", "/articles/", "/sport/", "/business/", "/world/"]):
            return True
        return False

    def add_urls(items: List[Dict]):
        for it in items:
            href = it.get("href")
            if not href:
                continue
            if base_domain:
                try:
                    if urlparse(href).netloc and base_domain not in urlparse(href).netloc:
                        # only keep same-domain if base_domain specified
                        continue
                except Exception:
                    continue
            if accept(href) and href not in candidates:
                candidates.append(href)

    if isinstance(links_obj, dict):
        if isinstance(links_obj.get("internal"), list):
            add_urls(links_obj["internal"])
        if isinstance(links_obj.get("external"), list) and not base_domain:
            # If base_domain not enforced, we can optionally include external links too
            add_urls(links_obj["external"])

    if limit is not None:
        candidates = candidates[:limit]
    return candidates


async def fetch_html(session: aiohttp.ClientSession, url: str, timeout: int = 25) -> Tuple[str, Optional[str]]:
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
    }
    try:
        async with session.get(url, headers=headers, timeout=timeout) as resp:
            resp.raise_for_status()
            return url, await resp.text()
    except Exception:
        return url, None


def parse_article_meta(html: str, url: str) -> Dict[str, str]:
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
        p = soup.find("p")
        if p:
            desc = p.get_text(strip=True)[:400]

    return {
        "title": title or url,
        "summary": desc or "",
        "readMore": url,
    }


async def scrape_to_payload(url: str, limit: int = 20, same_domain_only: bool = True, concurrency: int = 8) -> Dict:
    async with AsyncWebCrawler() as crawler:
        crawl = await crawler.arun(url=url)

    base_host = urlparse(url).netloc if same_domain_only else None
    links = collect_candidate_links(crawl.links or {}, base_domain=base_host, limit=limit)

    connector = aiohttp.TCPConnector(limit_per_host=concurrency)
    async with aiohttp.ClientSession(connector=connector) as session:
        sem = asyncio.Semaphore(concurrency)

        async def bounded(u: str):
            async with sem:
                return await fetch_html(session, u)

        results = await asyncio.gather(*(bounded(u) for u in links))

    articles: List[Dict[str, str]] = []
    referral_urls: List[str] = []
    for u, html in results:
        if not html:
            continue
        art = parse_article_meta(html, u)
        articles.append(art)
        referral_urls.append(art["readMore"])

    payload = {
        "source": url,
        "generatedAt": datetime.utcnow().isoformat() + "Z",
        "articles": articles,
        "referralURLs": referral_urls,
        "count": len(articles),
    }
    return payload


def save_payload(payload: Dict, output: Optional[str] = None) -> str:
    if output is None:
        host = urlparse(payload.get("source", "news")).netloc or "news"
        outdir = Path("output")
        outdir.mkdir(parents=True, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%SZ")
        output = str(outdir / f"news_{host}_{ts}.json")
    with open(output, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return output


def parse_args():
    p = ArgumentParser(description="Scrape a page for article links and save JSON summary")
    p.add_argument("--url", required=True, help="Seed URL, e.g., https://www.bbc.com/")
    p.add_argument("--limit", type=int, default=20, help="Max number of article links to follow")
    p.add_argument("--all-domains", action="store_true", help="Allow following links to other domains")
    p.add_argument("--concurrency", type=int, default=8, help="Concurrent fetches for article pages")
    p.add_argument("--output", default=None, help="Output file path (default: output/news_<host>_<ts>.json)")
    return p.parse_args()


async def _amain():
    args = parse_args()
    payload = await scrape_to_payload(
        url=args.url,
        limit=args.limit,
        same_domain_only=not args.all_domains,
        concurrency=args.concurrency,
    )
    path = save_payload(payload, args.output)
    print(json.dumps({"saved": path, "count": payload["count"]}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(_amain())
