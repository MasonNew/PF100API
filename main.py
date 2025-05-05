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
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
import re

# Enhanced logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Cache settings
CACHE_DURATION = 300  # 5 minutes instead of 30 seconds
CACHE_FALLBACK_DURATION = 24 * 60 * 60  # 24 hours for fallback when API is down
token_cache = {
    "data": None,
    "last_updated": None
}

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
MAX_RETRIES = 5  # Increased from 3 to 5
INITIAL_RETRY_DELAY = 1

async def fetch_with_retry(session, url, params):
    """Helper function to fetch data with exponential backoff retry logic"""
    for attempt in range(MAX_RETRIES):
        try:
            logger.info(f"Attempt {attempt + 1}/{MAX_RETRIES} for URL: {url}")
            async with session.get(url, params=params, headers=headers, timeout=TIMEOUT) as response:
                if response.status == 429:  # Rate limit
                    retry_after = int(response.headers.get('Retry-After', INITIAL_RETRY_DELAY * (2 ** attempt)))
                    logger.warning(f"Rate limited, waiting {retry_after} seconds (attempt {attempt + 1}/{MAX_RETRIES})")
                    await asyncio.sleep(retry_after)
                    continue
                
                if response.status == 503 or response.status == 502:  # Service Unavailable or Bad Gateway
                    retry_delay = INITIAL_RETRY_DELAY * (2 ** attempt)
                    logger.warning(f"Service unavailable (status: {response.status}), retrying in {retry_delay} seconds")
                    await asyncio.sleep(retry_delay)
                    continue
                
                if response.status != 200:
                    logger.error(f"HTTP error: {response.status} for URL: {url}")
                    if attempt == MAX_RETRIES - 1:
                        return None  # Return None instead of raising exception to allow fallbacks
                    await asyncio.sleep(INITIAL_RETRY_DELAY * (2 ** attempt))
                    continue
                
                return await response.json()
                
        except asyncio.TimeoutError:
            retry_delay = INITIAL_RETRY_DELAY * (2 ** attempt)  # Exponential backoff
            logger.warning(f"Timeout on attempt {attempt + 1}/{MAX_RETRIES}, waiting {retry_delay} seconds")
            if attempt == MAX_RETRIES - 1:
                return None  # Return None instead of raising exception to allow fallbacks
            await asyncio.sleep(retry_delay)
            
        except ClientError as e:
            retry_delay = INITIAL_RETRY_DELAY * (2 ** attempt)  # Exponential backoff
            logger.error(f"Network error on attempt {attempt + 1}/{MAX_RETRIES}: {str(e)}")
            if attempt == MAX_RETRIES - 1:
                return None  # Return None instead of raising exception to allow fallbacks
            await asyncio.sleep(retry_delay)
            
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            if attempt == MAX_RETRIES - 1:
                return None
            await asyncio.sleep(INITIAL_RETRY_DELAY * (2 ** attempt))
    
    return None  # Return None if all attempts failed

async def fetch_tokens(limit: int = 100, force_refresh: bool = False):
    """Fetch tokens with caching"""
    current_time = datetime.now()
    
    # Return cached data if available and not expired
    if not force_refresh and token_cache["data"] is not None:
        cache_age = (current_time - token_cache["last_updated"]).total_seconds()
        if cache_age < CACHE_DURATION:
            logger.info("Returning cached token data")
            return token_cache["data"][:limit]
    
    connector = aiohttp.TCPConnector(limit=10, force_close=True)
    
    async with aiohttp.ClientSession(connector=connector) as session:
        try:
            all_tokens = []
            offset = 0
            batch_size = 50
            api_success = False
            
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
                    
                    if batch is None:
                        logger.error(f"Failed to fetch tokens after {MAX_RETRIES} retries")
                        break
                    
                    if not batch or len(batch) == 0:
                        logger.info("No more tokens available")
                        api_success = True
                        break
                    
                    logger.info(f"Received {len(batch)} tokens in current batch")
                    all_tokens.extend(batch)
                    api_success = True
                    
                    if len(all_tokens) >= limit or len(batch) < 50:
                        break
                    
                    offset += 50
                    
                except Exception as e:
                    logger.error(f"Error in batch fetch: {str(e)}")
                    break
            
            # If API fetch failed and we have cached data, use that instead
            if not api_success and token_cache["data"] is not None:
                logger.info("API fetch failed, using cached data")
                
                # Check if cached data is too old (beyond fallback duration)
                cache_age = (current_time - token_cache["last_updated"]).total_seconds()
                if cache_age > CACHE_FALLBACK_DURATION:
                    logger.warning(f"Cached data is too old ({cache_age} seconds), but using anyway as fallback")
                    
                return token_cache["data"][:limit]
            
            # If API fetch failed and we have no cached data
            if len(all_tokens) == 0:
                logger.error("Failed to fetch tokens and no cache available")
                raise HTTPException(status_code=503, detail="Service unavailable - please try again later")
            
            logger.info(f"Received total of {len(all_tokens)} tokens from API")
            
            # Process tokens
            processed_tokens = [
                {
                    "name": token.get("name", "").strip(),
                    "price": round(float(token.get("usd_market_cap", 0)) / 1_000_000_000, 8),
                    "market_cap": round(float(token.get("usd_market_cap", 0))),
                    "description": token.get("description", ""),
                    "replies": token.get("reply_count", 0),
                    "image_url": token.get("image_uri", ""),
                    "token_url": f"https://pump.fun/board/{token.get('mint', '')}"
                }
                for token in all_tokens
            ]
            
            # Update cache
            token_cache["data"] = processed_tokens
            token_cache["last_updated"] = current_time
            
            return processed_tokens[:limit]
            
        except Exception as e:
            logger.error(f"Error fetching tokens: {str(e)}\n{traceback.format_exc()}")
            
            # Fallback to cached data if available
            if token_cache["data"] is not None:
                logger.info("Using cached data as fallback due to error")
                
                # Check if cached data is too old (beyond fallback duration)
                cache_age = (current_time - token_cache["last_updated"]).total_seconds()
                if cache_age > CACHE_FALLBACK_DURATION:
                    logger.warning(f"Cached data is too old ({cache_age} seconds), but using anyway as fallback")
                    
                return token_cache["data"][:limit]
                
            raise HTTPException(status_code=503, detail="Service unavailable - please try again later")

@app.get("/tokens")
async def get_tokens(limit: Optional[int] = 100, force_refresh: Optional[bool] = False):
    """Get list of top tokens from pump.fun, sorted by market cap"""
    try:
        if not 1 <= limit <= 1000:
            raise HTTPException(status_code=400, detail="Limit must be between 1 and 1000")
            
        tokens = await fetch_tokens(limit, force_refresh)
        return JSONResponse(content=tokens)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_tokens: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error"
        )

@app.get("/token/{token_address}")
async def get_token(token_address: str):
    """Get specific token details by address"""
    try:
        # Directly scrape the token's page
        url = f"https://pump.fun/board/{token_address}"
        logger.info(f"Fetching token data from: {url}")
        
        # First try to get from cached tokens
        if token_cache["data"] is not None:
            for token in token_cache["data"]:
                if token["token_url"].endswith(token_address):
                    logger.info(f"Found token in cache: {token['name']}")
                    return token
        
        # If not in cache, scrape the website
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml",
            "Accept-Language": "en-US,en;q=0.9",
        }
        
        try:
            response = requests.get(url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                logger.info("Successfully fetched token page")
                html = response.text
                soup = BeautifulSoup(html, 'lxml')
                
                # Debug the HTML structure
                logger.debug(f"Page title: {soup.title.string if soup.title else 'No title found'}")
                
                # Try to find token name (various selectors to increase chances)
                name_elem = None
                for selector in ['h1', 'h2.token-name', '.token-name', '.token-header h1']:
                    if name_elem:
                        break
                    name_elem = soup.select_one(selector)
                
                name = name_elem.text.strip() if name_elem else token_address
                logger.info(f"Found token name: {name}")
                
                # Find market cap using multiple approaches
                market_cap = 0
                market_cap_elem = None
                
                # Approach 1: Look for text containing "Market Cap"
                for div in soup.find_all(['div', 'span', 'p']):
                    if div.text and 'Market Cap' in div.text:
                        # Look for the nearest element with a dollar value
                        for sibling in div.find_next_siblings():
                            if '$' in sibling.text:
                                market_cap_elem = sibling
                                break
                        if market_cap_elem:
                            break
                
                # Approach 2: Look for specific classes or patterns
                if not market_cap_elem:
                    market_cap_elem = soup.select_one('.market-cap, .token-market-cap, .stats-value')
                
                if market_cap_elem:
                    market_cap_text = market_cap_elem.text.strip()
                    # Extract just the numeric part, removing $, commas, etc.
                    market_cap_text = re.sub(r'[^\d.]', '', market_cap_text)
                    try:
                        market_cap = float(market_cap_text)
                        logger.info(f"Found market cap: ${market_cap}")
                    except ValueError:
                        logger.warning(f"Could not parse market cap: {market_cap_text}")
                
                # Calculate price from market cap
                price = round(market_cap / 1_000_000_000, 8) if market_cap > 0 else 0
                
                # Get description
                desc_elem = None
                for selector in ['.whitespace-pre-wrap', '.token-description', '.description', 'p.description']:
                    if desc_elem:
                        break
                    desc_elem = soup.select_one(selector)
                
                description = desc_elem.text.strip() if desc_elem else ""
                
                # Get image - try multiple approaches
                image_url = ""
                # Try to find image by alt text
                img_elem = soup.find('img', {'alt': name}) if name else None
                if img_elem and 'src' in img_elem.attrs:
                    image_url = img_elem['src']
                
                # If not found, try common image classes
                if not image_url:
                    img_elem = soup.select_one('.token-image, .coin-image, .token-logo')
                    if img_elem and 'src' in img_elem.attrs:
                        image_url = img_elem['src']
                
                # Get holders count
                holders = 0
                holders_elem = None
                
                for div in soup.find_all(['div', 'span', 'p']):
                    if div.text and 'Holders' in div.text:
                        for sibling in div.find_next_siblings():
                            if sibling.text and sibling.text.strip().isdigit():
                                holders_elem = sibling
                                break
                        if not holders_elem:
                            # The number might be in the same element
                            text = div.text.strip()
                            matches = re.search(r'Holders[:\s]*([0-9,]+)', text)
                            if matches:
                                try:
                                    holders = int(matches.group(1).replace(',', ''))
                                except ValueError:
                                    pass
                        break
                
                if holders_elem:
                    try:
                        holders = int(holders_elem.text.strip().replace(',', ''))
                    except ValueError:
                        pass
                
                token_info = {
                    "name": name,
                    "price": price,
                    "market_cap": market_cap,
                    "description": description,
                    "image_url": image_url,
                    "token_url": url,
                    "mint": token_address,
                    "supply": "1,000,000,000",
                    "holders": holders
                }
                
                logger.info(f"Successfully scraped token: {name}")
                return token_info
            elif response.status_code == 404:
                raise HTTPException(status_code=404, detail=f"Token not found: {token_address}")
            else:
                logger.error(f"HTTP error when fetching token: {response.status_code}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Error fetching token data, status code: {response.status_code}"
                )
        except requests.RequestException as e:
            logger.error(f"Request error when fetching token: {str(e)}")
            raise HTTPException(status_code=503, detail="Service unavailable - please try again later")
                    
    except Exception as e:
        logger.error(f"Error fetching token: {str(e)}\nTraceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="An error occurred while fetching token data")

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"Global exception handler caught: {str(exc)}\n{traceback.format_exc()}")
    
    if isinstance(exc, HTTPException):
        # Pass through HTTP exceptions with their status codes
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail}
        )
    
    # For other exceptions, return a generic 500 error
    return JSONResponse(
        status_code=500,
        content={"detail": "The server encountered an unexpected error. Please try again later."}
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