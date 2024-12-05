import requests
import json
import time
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

def create_session_with_retries():
    session = requests.Session()
    # Retry strategy: 3 retries with backoff
    retries = Retry(
        total=3,  # number of retries
        backoff_factor=0.5,  # wait 0.5, 1, 2 seconds between retries
        status_forcelist=[500, 502, 503, 504]  # retry on these status codes
    )
    session.mount('http://', HTTPAdapter(max_retries=retries))
    session.mount('https://', HTTPAdapter(max_retries=retries))
    return session

def fetch_tokens(limit=100, base_url="http://localhost:3000"):
    session = create_session_with_retries()
    
    print(f"\nFetching top {limit} tokens by market cap...")
    try:
        response = session.get(f"{base_url}/tokens?limit={limit}", timeout=10)
        print(f"Status Code: {response.status_code}")
        
        response.raise_for_status()  # Raise an exception for bad status codes
        
        data = response.json()
        
        if isinstance(data, list):
            print(f"\nReceived {len(data)} tokens")
            print(f"\nTop {len(data)} tokens by market cap:")
            for i, token in enumerate(data, 1):
                print(f"\n{i}. {token['name']}:")
                print(f"   Market cap: ${token.get('market_cap', 'N/A'):,}")
                print(f"   Replies: {token.get('replies', 'N/A')}")
                print(f"   Description: {token.get('description', 'N/A')}")
                print(f"   Image URL: {token.get('image_url', 'N/A')}")
                print(f"   Token URL: {token.get('token_url', 'N/A')}")
        else:
            print("\nDebug info from response:")
            print(json.dumps(data, indent=2))
            
    except requests.exceptions.RequestException as e:
        print(f"Error during API request: {str(e)}")
        return None
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON response: {str(e)}")
        return None
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        return None

if __name__ == "__main__":
    print("Starting API tests...")
    fetch_tokens() 