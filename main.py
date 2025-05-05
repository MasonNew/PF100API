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

# Replace the API_URL with direct website URLs
# API_URL = "https://frontend-api.pump.fun"
WEBSITE_URL = "https://pump.fun"

# Define headers globally with more browser-like headers to avoid being blocked
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "max-age=0"
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
    """Fetch tokens by scraping pump.fun website directly"""
    current_time = datetime.now()
    
    # Return cached data if available and not expired
    if not force_refresh and token_cache["data"] is not None:
        cache_age = (current_time - token_cache["last_updated"]).total_seconds()
        if cache_age < CACHE_DURATION:
            logger.info("Returning cached token data")
            return token_cache["data"][:limit]
    
    try:
        logger.info(f"Scraping tokens from pump.fun website")
        
        # Use direct HTTP request instead of aiohttp for better compatibility with some sites
        url = f"{WEBSITE_URL}/board"
        response = requests.get(url, headers=headers, timeout=30)
        
        if response.status_code != 200:
            logger.error(f"Failed to fetch tokens, status code: {response.status_code}")
            # Try to use cached data as fallback
            if token_cache["data"] is not None:
                cache_age = (current_time - token_cache["last_updated"]).total_seconds()
                if cache_age > CACHE_FALLBACK_DURATION:
                    logger.warning(f"Cached data is too old ({cache_age} seconds), but using anyway as fallback")
                logger.info("Using cached data as fallback")
                return token_cache["data"][:limit]
            else:
                raise HTTPException(status_code=503, detail="Service unavailable - please try again later")
        
        # Parse the HTML
        soup = BeautifulSoup(response.text, 'lxml')
        
        # Find the token list (this will need to be updated based on actual HTML structure)
        tokens_data = []
        token_elements = soup.select('.token-list-item, .token-card, [data-token-address]')
        
        logger.info(f"Found {len(token_elements)} token elements on the page")
        
        for element in token_elements[:limit]:  # Only process up to the limit
            try:
                # Extract token data based on HTML structure
                token_address = element.get('data-token-address') or element.get('href', '').split('/')[-1]
                
                if not token_address or token_address == '#':
                    continue
                
                # Get token name
                name_elem = element.select_one('.token-name, h3, .name')
                name = name_elem.text.strip() if name_elem else token_address
                
                # Try to find market cap
                market_cap_elem = element.select_one('.market-cap, .cap')
                market_cap = 0
                if market_cap_elem:
                    market_cap_text = market_cap_elem.text.strip()
                    # Extract just the numeric part, removing $, commas, etc.
                    market_cap_text = re.sub(r'[^\d.]', '', market_cap_text)
                    try:
                        market_cap = float(market_cap_text)
                    except ValueError:
                        pass
                
                # Calculate price (1 billion supply)
                price = round(market_cap / 1_000_000_000, 8) if market_cap > 0 else 0
                
                # Get image URL
                img_elem = element.select_one('img')
                image_url = img_elem['src'] if img_elem and 'src' in img_elem.attrs else ""
                
                # Get description if available
                desc_elem = element.select_one('.description, .token-description')
                description = desc_elem.text.strip() if desc_elem else ""
                
                tokens_data.append({
                    "name": name,
                    "price": price,
                    "market_cap": market_cap,
                    "description": description,
                    "image_url": image_url,
                    "token_url": f"{WEBSITE_URL}/board/{token_address}",
                    "mint": token_address,
                    "supply": "1,000,000,000",
                    "replies": 0  # We don't have this information from scraping
                })
            except Exception as e:
                logger.error(f"Error processing token element: {str(e)}")
                continue
        
        logger.info(f"Successfully scraped {len(tokens_data)} tokens")
        
        # Update cache
        token_cache["data"] = tokens_data
        token_cache["last_updated"] = current_time
        
        return tokens_data[:limit]
        
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