import asyncio
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse
from crawl4ai import AsyncWebCrawler

BASE_URL = "https://www.bbc.com"


def _is_article_url(u: str, base_host: str) -> bool:
    if not u or not u.startswith("http"):
        return False
    try:
        host = urlparse(u).netloc
    except Exception:
        return False
    if host != base_host:
        return False
    # Heuristics: include common BBC sections that contain articles
    if any(seg in u for seg in ["/news/", "/news/articles/", "/sport/", "/business/", "/world/"]):
        # Exclude obvious non-HTML assets or media players
        if not any(u.lower().endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".m3u8", ".pdf", ".css", ".js"]):
            return True
    return False


async def main():
    async with AsyncWebCrawler() as crawler:
        print("[STEP 1] Crawling BBC homepage...")
        homepage = await crawler.arun(url=BASE_URL)

        base_host = urlparse(homepage.redirected_url or BASE_URL).netloc
        print("[STEP 2] Extracting article links...")

        article_links = set()
        links = homepage.links or {}
        if isinstance(links, dict):
            for section in ("internal", "external"):
                for item in links.get(section, []) or []:
                    href = (item or {}).get("href")
                    if not href:
                        continue
                    full_url = href if href.startswith("http") else urljoin(BASE_URL, href)
                    if _is_article_url(full_url, base_host):
                        article_links.add(full_url)
        elif isinstance(links, list):
            # Fallback if links is a list of strings
            for href in links:
                full_url = href if href.startswith("http") else urljoin(BASE_URL, href)
                if _is_article_url(full_url, base_host):
                    article_links.add(full_url)

        article_links = list(article_links)
        print(f"[FOUND] {len(article_links)} article links")

        articles = []
        # Limit to avoid over-fetching during demo
        for url in article_links[:12]:
            try:
                print(f"[FETCHING] {url}")
                result = await crawler.arun(url=url)
                text = (result.markdown or "").strip()

                # Title from metadata fallbacks
                meta = result.metadata or {}
                title = (
                    meta.get("og:title")
                    or meta.get("twitter:title")
                    or meta.get("title")
                    or url.split("/")[-1].replace("-", " ").title()
                )

                # Simple summary from first ~70 words of markdown
                words = text.split()
                summary = (" ".join(words[:70]) + "...") if len(words) > 70 else text

                articles.append({
                    "title": (title or "Untitled").strip(),
                    "summary": (summary or "No summary available").strip(),
                    "readMore": url,
                })
            except Exception as e:
                print(f"[ERROR] Failed to fetch {url}: {e}")

        output = {
            "articles": articles,
            "referralURLs": article_links,
        }

        # Print JSON to stdout
        print(json.dumps(output, indent=2, ensure_ascii=False))

        # Also save to file for convenience
        out_dir = Path("output")
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%SZ")
        out_path = out_dir / f"news_bbc_{ts}.json"
        out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[SAVED] {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
