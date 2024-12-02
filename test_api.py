import requests
import json

print("Starting API tests...")

print("\nFetching top 100 tokens by market cap...")
response = requests.get("http://localhost:3000/tokens?limit=100")
print(f"Status Code: {response.status_code}")

if response.status_code == 200:
    data = response.json()
    
    if isinstance(data, list):
        print(f"\nReceived {len(data)} tokens")
        print(f"\nTop {len(data)} tokens by market cap:")
        for i, token in enumerate(data, 1):
            print(f"\n{i}. {token['name']}:")
            print(f"   Market cap: ${token['market_cap']:,}")
            print(f"   Replies: {token['replies']}")
            print(f"   Description: {token['description']}")
            print(f"   Image URL: {token['image_url']}")
            print(f"   Token URL: {token['token_url']}")
    else:
        print("\nDebug info from response:")
        print(json.dumps(data, indent=2))
else:
    print("Error:", response.text) 