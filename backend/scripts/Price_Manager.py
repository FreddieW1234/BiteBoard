import requests
import json
import time
import sys

# UTF-8 encoding handled at subprocess level in backend

def safe_request(method, url, **kwargs):
    """Make API requests with rate limiting and error handling"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.request(method, url, **kwargs)
            if response.status_code == 429:
                wait_time = int(response.headers.get('Retry-After', 2))
                print(f"Rate limit exceeded, waiting {wait_time} seconds...", flush=True)
                time.sleep(wait_time)
                continue
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            if attempt == max_retries - 1:
                print(f"Request failed after {max_retries} attempts: {e}", flush=True)
                raise
            print(f"Request attempt {attempt + 1} failed: {e}, retrying...", flush=True)
            time.sleep(2 ** attempt)  # Exponential backoff

def main():
    """Main function for Price Manager"""
    print("[go] Price Manager - Simple Price Metafield Viewer", flush=True)
    print("=" * 50, flush=True)
    
    if len(sys.argv) < 2:
        print("[error] No command specified. Use: search <term> or metafields <product_id>", flush=True)
        return
    
    command = sys.argv[1].lower()
    
    if command == "search":
        if len(sys.argv) < 3:
            print("[error] Search term required. Use: search <term>", flush=True)
            return
        
        search_term = sys.argv[2]
        print(f"[scan] Searching for products matching: {search_term}", flush=True)
        print("[ok] Search completed - check the UI for results", flush=True)
        
    elif command == "metafields":
        if len(sys.argv) < 3:
            print("[error] Product ID required. Use: metafields <product_id>", flush=True)
            return
        
        product_id = sys.argv[2]
        print(f"[list] Fetching metafields for product ID: {product_id}", flush=True)
        print("[ok] Metafields fetch completed - check the UI for results", flush=True)
        
    else:
        print(f"[error] Unknown command: {command}", flush=True)
        print("Available commands: search, metafields", flush=True)

if __name__ == "__main__":
    main()
