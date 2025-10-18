import asyncio
from crawl4ai import *
from openai import AsyncOpenAI
import os
from fastapi import FastAPI, Request, HTTPException 
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()


ALLOWED_ORIGINS = [
    "http://10.0.70.225:3000",  # For local development
    "https://news-portal-client-gamma.vercel.app",
     "http://localhost:3000",
     "*"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins= ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    
)


client = AsyncOpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),
)

class UrlRequest(BaseModel):
    url: str

# your_url = input("Enter URL: ")
async def main(your_url: str):



    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(
            # "https://www.nbcnews.com/business"
            url= your_url,
        )

    response = await client.chat.completions.create(
        model="gpt-4.1",
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
            # {
            #     "role": "user",
            #     "content": "Are semicolons optional in JavaScript?"
            # }
        ]
    )
    print(response.choices[0].message.content)
    return response.choices[0].message.content


    # print(result.markdown)
    # return result.markdown



@app.get("/")
def read_root():
    return {"Hello": "World"}




@app.post("/scraping")
async def APIHandle(body: UrlRequest):
   
    try:
        result = await main(body.url)
       
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

    return {"Status": "Success", "Data": result}

    




# if __name__ == "__main__":
#     asyncio.run(main())
