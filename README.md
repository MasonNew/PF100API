# Pump.fun API Scraper

A FastAPI-based web scraper that provides API endpoints to fetch data from pump.fun/board.

## Features

- Get list of all tokens
- Get detailed information about specific tokens
- Fetch recent trades for tokens
- Get discussion threads
- View token holders information

## Installation

1. Clone this repository
2. Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

1. Start the API server:
```bash
python main.py
```

2. The API will be available at `http://localhost:8000`

## API Endpoints

- `GET /`: Welcome message
- `GET /tokens`: List all tokens
- `GET /token/{symbol}`: Get detailed information about a specific token
- `GET /trades/{symbol}`: Get recent trades for a token
- `GET /threads`: Get recent discussion threads
- `GET /holders/{symbol}`: Get list of token holders

## Parameters

- `limit`: Optional parameter for /trades and /threads endpoints to limit the number of results
- `symbol`: Required parameter for token-specific endpoints

## Example Usage

```python
import requests

# Get all tokens
response = requests.get('http://localhost:8000/tokens')
tokens = response.json()

# Get specific token details
response = requests.get('http://localhost:8000/token/BTC')
token_details = response.json()

# Get recent trades with limit
response = requests.get('http://localhost:8000/trades/BTC?limit=10')
recent_trades = response.json()
``` 