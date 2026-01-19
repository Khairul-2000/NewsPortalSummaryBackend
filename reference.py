import json
import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
import redis.asyncio as redis
from redis.exceptions import ConnectionError as RedisConnectionError
from crawl4ai import *
from openai import AsyncOpenAI
from urllib.parse import urlparse

# FastAPI app initialization
app = FastAPI(swagger_ui_parameters={"defaultModelsExpandDepth": -1})

# Allowed CORS origins
ALLOWED_ORIGINS = [
    "http://10.0.70.225:3000",  # For local development
    "https://news-portal-client-gamma.vercel.app",
    "http://localhost:3000",
    "*"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# OpenAI client setup
client = AsyncOpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),
)

# Redis setup (optional)
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
redis_client = redis.from_url(REDIS_URL, decode_responses=True) if REDIS_URL else None

@app.on_event("shutdown")
async def _shutdown() -> None:
    if redis_client:
        await redis_client.aclose()

# Pydantic model for receiving URL
class UrlRequest(BaseModel):
    url: str

# Cache expiration time (24 hours)
CACHE_EXPIRATION = 24 * 60 * 60  # 24 hours in seconds

# Normalize URL function to avoid issues with slashes and query parameters
def normalize_url(url: str) -> str:
    parsed_url = urlparse(url)
    return f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}"

# Function to scrape and summarize the URL
async def main(your_url: str):
    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(url=your_url)

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": f"""
                You are an assistant specialized in summarizing news. Your tasks are:
                -Summarize the latest news based on the provided context: {result.markdown}.
                -Use web search to find the most recent and relevant updates related to the context.
                -Suggest additional ideas or angles based on the latest news.
                -Attach a referral link (source link) to each piece of summarized news.
                -Format your response in JSON format, including the following fields:
                    - title: The title of the news article.
                    - summary: A brief summary of the news article.
                    - readMore: The referral link to the news article.
                - Provide a list of all referral URLs at the end of your response.
                - Ensure that the JSON is well-structured and easy to read.
                """
            },
        ],
        response_format={"type": "json_object"}
    )

    return response.choices[0].message.content

# Function to check Redis cache and scrape if necessary
async def check_cache_and_scrape(url: str):
    normalized_url = normalize_url(url)
    cache_key = f"scraped:{normalized_url}"

    if not redis_client:
        return await main(url)

    try:
        cached_data = await redis_client.get(cache_key)
    except (RedisConnectionError, OSError) as e:
        print(f"Redis unavailable ({e}); proceeding without cache")
        return await main(url)

    if cached_data:
        print(f"Cache hit for URL: {url}")
        return cached_data

    print(f"Cache miss for URL: {url}, scraping...")
    try:
        result = await main(url)
        await redis_client.setex(cache_key, CACHE_EXPIRATION, result)
        print(f"Cache set for URL {url}: {result}")
        return result
    except (RedisConnectionError, OSError) as e:
        print(f"Redis unavailable while caching ({e}); returning uncached result")
        return result

# Root endpoint
@app.get("/")
def read_root():
    return {"Hello": "World"}

# Endpoint for scraping
@app.post("/scraping")
async def APIHandle(body: UrlRequest):
    url = body.url
    print(f"Received URL: {url}")

    try:
        result = await check_cache_and_scrape(url)
        print(f"Scraping Result: {result}")
        print("Scraping and summarization completed successfully.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

    return {"Status": "Success", "Data": json.loads(result)}
