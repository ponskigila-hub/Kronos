#!/usr/bin/env python3
"""
Kronos Feature Verification Test
Tests all major routes and features as per the audit checklist.
"""
import requests
import json
import time
import sys
from pathlib import Path

BASE_URL = "http://127.0.0.1:5050"
session = requests.Session()

# Track results
results = []

def test_route(method, path, description, **kwargs):
    """Test a route and record results."""
    url = f"{BASE_URL}{path}"
    try:
        timeout = kwargs.pop("timeout", None)
        if method == "GET":
            resp = session.get(url, timeout=timeout or 10)
        elif method == "POST":
            resp = session.post(url, timeout=timeout or 30, **kwargs)
        else:
            return f"UNKNOWN: {method} {path}"
        
        # Check response
        status = f"{resp.status_code}"
        success = resp.status_code < 400
        
        result = {
            "status": "PASS" if success else "FAIL",
            "method": method,
            "path": path,
            "description": description,
            "code": resp.status_code,
            "has_content": len(resp.content) > 0,
            "content_type": resp.headers.get("content-type", "unknown")
        }
        results.append(result)
        print(f"{'✓' if success else '✗'} {method} {path}: {status} - {description}")
        return result
        
    except Exception as e:
        result = {
            "status": "ERROR",
            "method": method,
            "path": path,
            "description": description,
            "error": str(e)
        }
        results.append(result)
        print(f"✗ {method} {path}: ERROR - {str(e)}")
        return result

def main():
    print("=" * 70)
    print("KRONOS FEATURE VERIFICATION TEST")
    print("=" * 70)
    print()
    
    # Wait a moment for app to be ready
    time.sleep(1)
    
    # Test connectivity
    try:
        resp = session.get(f"{BASE_URL}/", timeout=5)
        print(f"✓ Server connected: {BASE_URL}")
    except Exception as e:
        print(f"✗ Cannot connect to server at {BASE_URL}: {e}")
        sys.exit(1)
    
    print()
    print("--- DASHBOARD & HOMEPAGE ---")
    test_route("GET", "/", "Dashboard homepage")
    
    print()
    print("--- FORECAST FEATURE ---")
    test_route("GET", "/forecast", "Forecast page")
    
    # Try to run a forecast for a known ticker
    print()
    print("--- FORECAST: Ticker Test (AAPL) ---")
    test_route("POST", "/forecast/ticker", 
               "Submit AAPL forecast", 
               data={"ticker": "AAPL", "pred_len": "30", "lookback": "365", "detailed": "off"},
               timeout=60)
    
    print()
    print("--- SCREENER FEATURE ---")
    test_route("GET", "/screener", "Screener page")
    
    print()
    print("--- NEWS FEATURE ---")
    test_route("GET", "/news", "News page")
    test_route("GET", "/api/news", "News API - default ticker")
    test_route("GET", "/api/news?ticker=AAPL", "News API - AAPL")
    
    print()
    print("--- TICKER SEARCH ---")
    test_route("GET", "/api/tickers/search?q=apple", "Ticker search - 'apple'")
    
    print()
    print("--- WATCHLIST ---")
    test_route("GET", "/watchlist", "Watchlist page")
    test_route("GET", "/api/watchlist/prices", "Watchlist prices API")
    test_route("GET", "/watchlist/correlation", "Watchlist correlation view")
    
    print()
    print("--- BACKTEST FEATURE ---")
    test_route("GET", "/backtest", "Backtest page")
    
    print()
    print("--- CHAT FEATURE ---")
    test_route("GET", "/chat", "Chat page")
    test_route("GET", "/api/chat/history", "Chat history API")
    
    print()
    print("--- RESULTS SUMMARY ---")
    passed = len([r for r in results if r.get("status") == "PASS"])
    failed = len([r for r in results if r.get("status") == "FAIL"])
    errors = len([r for r in results if r.get("status") == "ERROR"])
    
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Errors: {errors}")
    print()
    
    if failed > 0 or errors > 0:
        print("Failed/Error tests:")
        for r in results:
            if r["status"] != "PASS":
                print(f"  - {r['method']} {r['path']}: {r.get('error', r.get('code'))}")
    
    return 0 if (failed == 0 and errors == 0) else 1

if __name__ == "__main__":
    sys.exit(main())
