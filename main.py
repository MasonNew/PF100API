from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import aiohttp
import logging
from typing import Optional, Dict, List
import json
import traceback
import os

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Pump.fun API Scraper",
    description="API for scraping pump.fun data including tokens, marketcap, trades, and more",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

API_URL = "https://frontend-api.pump.fun"

# Define headers globally
headers = {
    "Accept": "application/json",
    "Origin": "https://pump.fun",
    "Referer": "https://pump.fun/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

async def fetch_tokens(limit: int = 100):
    """Fetch tokens directly from pump.fun API"""
    async with aiohttp.ClientSession() as session:
        try:
            all_tokens = []
            offset = 0
            batch_size = 50  # API returns 50 tokens per page
            
            while len(all_tokens) < limit:
                url = f"{API_URL}/coins"
                params = {
                    "offset": str(offset),
                    "limit": "50",  # API expects exactly "50" for pagination
                    "sort": "market_cap",
                    "order": "DESC",
                    "includeNsfw": "false"
                }
                
                logger.info(f"Fetching tokens from API: {url} (offset: {offset})")
                
                try:
                    async with session.get(url, params=params, headers=headers) as response:
                        response.raise_for_status()  # Raise exception for non-200 status codes
                        batch = await response.json()
                        
                        if not batch or len(batch) == 0:
                            logger.info("No more tokens available")
                            break
                        
                        logger.info(f"Received {len(batch)} tokens in current batch")
                        all_tokens.extend(batch)
                        
                        if len(all_tokens) >= limit or len(batch) < 50:
                            break
                        
                        offset += 50  # Move to next page
                except aiohttp.ClientError as e:
                    logger.error(f"Network error fetching batch: {str(e)}")
                    raise HTTPException(status_code=500, detail=f"Network error: {str(e)}")
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON response: {str(e)}")
                    raise HTTPException(status_code=500, detail="Invalid response from API")
            
            logger.info(f"Received total of {len(all_tokens)} tokens from API")
            
            # Process and return only the requested number of tokens
            tokens = all_tokens[:limit]
            return [
                {
                    "name": token["name"].strip(),
                    "market_cap": round(token["usd_market_cap"]),
                    "description": token["description"],
                    "replies": token["reply_count"],
                    "image_url": token["image_uri"],
                    "token_url": f"https://pump.fun/board/{token['mint']}"
                }
                for token in tokens
            ]
            
        except Exception as e:
            logger.error(f"Error fetching tokens: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

@app.get("/tokens")
async def get_tokens(limit: Optional[int] = 100):
    """Get list of top tokens from pump.fun, sorted by market cap"""
    try:
        tokens = await fetch_tokens(limit)
        return tokens
    except Exception as e:
        logger.error(f"Error in get_tokens: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error processing request: {str(e)}"
        )

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 3000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True) 