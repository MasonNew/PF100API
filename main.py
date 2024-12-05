from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import aiohttp
import logging
from typing import Optional, Dict, List
import json
import traceback
import os
from aiohttp import ClientTimeout
from aiohttp.client_exceptions import ClientError
import asyncio
from fastapi.responses import JSONResponse

# Enhanced logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Pump.fun API Scraper",
    description="API for scraping pump.fun data including tokens, marketcap, trades, and more",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_URL = "https://frontend-api.pump.fun"

# Define headers globally
headers = {
    "Accept": "application/json",
    "Origin": "https://pump.fun",
    "Referer": "https://pump.fun/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# Define timeout and retry settings
TIMEOUT = ClientTimeout(total=30, connect=10, sock_read=10)
MAX_RETRIES = 3
RETRY_DELAY = 1

async def fetch_with_retry(session, url, params):
    """Helper function to fetch data with retry logic"""
    for attempt in range(MAX_RETRIES):
        try:
            async with session.get(url, params=params, headers=headers, timeout=TIMEOUT) as response:
                if response.status == 429:  # Rate limit
                    retry_after = int(response.headers.get('Retry-After', RETRY_DELAY))
                    logger.warning(f"Rate limited, waiting {retry_after} seconds")
                    await asyncio.sleep(retry_after)
                    continue
                
                response.raise_for_status()
                return await response.json()
                
        except asyncio.TimeoutError:
            logger.warning(f"Timeout on attempt {attempt + 1}/{MAX_RETRIES}")
            if attempt == MAX_RETRIES - 1:
                raise HTTPException(status_code=504, detail="Request timeout")
            await asyncio.sleep(RETRY_DELAY * (attempt + 1))
            
        except ClientError as e:
            logger.error(f"Network error on attempt {attempt + 1}/{MAX_RETRIES}: {str(e)}")
            if attempt == MAX_RETRIES - 1:
                raise HTTPException(status_code=502, detail="Network error")
            await asyncio.sleep(RETRY_DELAY * (attempt + 1))
    
    raise HTTPException(status_code=500, detail="Max retries exceeded")

async def fetch_tokens(limit: int = 100):
    """Fetch tokens directly from pump.fun API"""
    connector = aiohttp.TCPConnector(limit=10, force_close=True)
    
    async with aiohttp.ClientSession(connector=connector) as session:
        try:
            all_tokens = []
            offset = 0
            batch_size = 50
            
            while len(all_tokens) < limit:
                url = f"{API_URL}/coins"
                params = {
                    "offset": str(offset),
                    "limit": "50",
                    "sort": "market_cap",
                    "order": "DESC",
                    "includeNsfw": "false"
                }
                
                logger.info(f"Fetching tokens from API: {url} (offset: {offset})")
                
                try:
                    batch = await fetch_with_retry(session, url, params)
                    
                    if not batch or len(batch) == 0:
                        logger.info("No more tokens available")
                        break
                    
                    logger.info(f"Received {len(batch)} tokens in current batch")
                    all_tokens.extend(batch)
                    
                    if len(all_tokens) >= limit or len(batch) < 50:
                        break
                    
                    offset += 50
                    
                except Exception as e:
                    logger.error(f"Error in batch fetch: {str(e)}")
                    raise
            
            logger.info(f"Received total of {len(all_tokens)} tokens from API")
            
            # Process and return only the requested number of tokens
            tokens = all_tokens[:limit]
            return [
                {
                    "name": token.get("name", "").strip(),
                    "market_cap": round(float(token.get("usd_market_cap", 0))),
                    "description": token.get("description", ""),
                    "replies": token.get("reply_count", 0),
                    "image_url": token.get("image_uri", ""),
                    "token_url": f"https://pump.fun/board/{token.get('mint', '')}"
                }
                for token in tokens
            ]
            
        except Exception as e:
            logger.error(f"Error fetching tokens: {str(e)}\n{traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=str(e))

@app.get("/tokens")
async def get_tokens(limit: Optional[int] = 100):
    """Get list of top tokens from pump.fun, sorted by market cap"""
    try:
        if not 1 <= limit <= 1000:
            raise HTTPException(status_code=400, detail="Limit must be between 1 and 1000")
            
        tokens = await fetch_tokens(limit)
        return JSONResponse(content=tokens)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_tokens: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error"
        )

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"Global exception handler caught: {str(exc)}\n{traceback.format_exc()}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 3000))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=True,
        timeout_keep_alive=30,
        access_log=True
    ) 