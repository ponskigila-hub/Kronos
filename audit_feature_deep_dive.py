#!/usr/bin/env python3
"""
Kronos Feature Verification - Deep Dive
Tests detailed feature scenarios beyond basic connectivity.
"""
import requests
import json
import time
import sys
import io
from pathlib import Path

BASE_URL = "http://127.0.0.1:5050"
session = requests.Session()

# Get a session user ID
def get_user_id():
    """Extract user ID from session cookies."""
    # First, make a request to establish the session
    resp = session.get(f"{BASE_URL}/")
    return session.cookies.get("session", "test-user")

user_id = get_user_id()
print(f"Using session user ID: {user_id[:20]}...")

results = []

def test_feature(name, test_fn):
    """Wrapper for running a feature test."""
    try:
        result = test_fn()
        status = "PASS" if result else "FAIL"
        print(f"{'✓' if result else '✗'} {name}")
        results.append({"name": name, "status": status})
        return result
    except Exception as e:
        print(f"✗ {name}: {str(e)}")
        results.append({"name": name, "status": "ERROR", "error": str(e)})
        return False

def main():
    print("=" * 70)
    print("KRONOS FEATURE DEEP DIVE - DETAILED SCENARIOS")
    print("=" * 70)
    print()
    
    # --- WATCHLIST TESTS ---
    print("--- WATCHLIST FEATURE ---")
    
    def test_watchlist_add():
        resp = session.post(f"{BASE_URL}/watchlist/add", 
                          data={"ticker": "AAPL"})
        return resp.status_code in [200, 302]  # May redirect
    
    def test_watchlist_details():
        resp = session.get(f"{BASE_URL}/api/watchlist/details")
        if resp.status_code != 200:
            return False
        data = resp.json()
        return isinstance(data, dict)
    
    def test_watchlist_note():
        resp = session.post(f"{BASE_URL}/watchlist/note",
                          json={"ticker": "AAPL", "note": "Test note"})
        return resp.status_code in [200, 302]
    
    def test_watchlist_entry_zone():
        resp = session.post(f"{BASE_URL}/watchlist/entry_zone",
                          json={"ticker": "AAPL", "low": "150", "high": "200"})
        return resp.status_code in [200, 302]
    
    def test_watchlist_export():
        resp = session.get(f"{BASE_URL}/watchlist/export")
        return resp.status_code == 200 and len(resp.content) > 0
    
    def test_watchlist_remove():
        resp = session.post(f"{BASE_URL}/watchlist/remove",
                          data={"ticker": "AAPL"})
        return resp.status_code in [200, 302]
    
    test_feature("Watchlist: Add AAPL", test_watchlist_add)
    test_feature("Watchlist: Fetch details API", test_watchlist_details)
    test_feature("Watchlist: Add note to AAPL", test_watchlist_note)
    test_feature("Watchlist: Set entry zone", test_watchlist_entry_zone)
    test_feature("Watchlist: Export", test_watchlist_export)
    test_feature("Watchlist: Remove AAPL", test_watchlist_remove)
    
    print()
    print("--- BACKTEST & SIMULATION ---")
    
    def test_backtest_run():
        resp = session.post(f"{BASE_URL}/backtest/run",
                          data={"ticker": "AAPL", "max_windows": "10"})
        if resp.status_code != 200:
            print(f"  Backtest run returned {resp.status_code}")
            return False
        data = resp.json()
        return "job_id" in data
    
    def test_simulation_buy():
        resp = session.post(f"{BASE_URL}/backtest/simulation/buy",
                          data={"ticker": "AAPL", "amount_type": "dollars", "amount": "1000"})
        return resp.status_code in [200, 302]
    
    def test_simulation_sell():
        resp = session.post(f"{BASE_URL}/backtest/simulation/sell",
                          data={"ticker": "AAPL", "shares": "10"})
        # May fail if no open position, which is OK for this test
        return resp.status_code in [200, 400, 302]
    
    def test_simulation_reset():
        resp = session.post(f"{BASE_URL}/backtest/simulation/reset")
        return resp.status_code in [200, 302]
    
    test_feature("Backtest: Submit run (AAPL)", test_backtest_run)
    test_feature("Simulation: Buy AAPL", test_simulation_buy)
    test_feature("Simulation: Sell AAPL", test_simulation_sell)
    test_feature("Simulation: Reset portfolio", test_simulation_reset)
    
    print()
    print("--- CHAT FEATURE ---")
    
    def test_chat_send():
        resp = session.post(f"{BASE_URL}/api/chat/send",
                          json={"message": "forecast AAPL"})
        if resp.status_code != 200:
            print(f"  Chat send returned {resp.status_code}: {resp.text if resp.status_code < 500 else 'server error'}")
            return False
        data = resp.json()
        return "job_id" in data
    
    def test_chat_job_poll():
        # First send a message
        resp = session.post(f"{BASE_URL}/api/chat/send",
                          json={"message": "how are you?"})
        if resp.status_code != 200:
            return False
        
        job_id = resp.json().get("job_id")
        if not job_id:
            return False
        
        # Poll for result
        for i in range(10):
            resp = session.get(f"{BASE_URL}/api/chat/job/{job_id}")
            if resp.status_code != 200:
                print(f"    Poll returned {resp.status_code}")
                return False
            
            data = resp.json()
            if data.get("status") != "pending":
                return True
            
            time.sleep(1)
        
        return False  # Timeout
    
    test_feature("Chat: Send message", test_chat_send)
    test_feature("Chat: Poll for result (with job transition)", test_chat_job_poll)
    
    print()
    print("--- SCREENER FEATURE ---")
    
    def test_screener_run():
        resp = session.post(f"{BASE_URL}/screener/run",
                          data={
                              "universe": "sp500",
                              "preset": "momentum",
                              "custom_text": "",
                              "max_results": "10"
                          },
                          timeout=120)
        if resp.status_code != 200:
            print(f"  Screener run returned {resp.status_code}")
            return False
        data = resp.json()
        return "job_id" in data
    
    def test_screener_history():
        resp = session.get(f"{BASE_URL}/api/screener/history")
        # May return 404 if no history, which is OK
        return resp.status_code in [200, 404]
    
    test_feature("Screener: Submit run", test_screener_run)
    test_feature("Screener: Check history", test_screener_history)
    
    print()
    print("--- RESULTS SUMMARY ---")
    passed = len([r for r in results if r["status"] == "PASS"])
    failed = len([r for r in results if r["status"] == "FAIL"])
    errors = len([r for r in results if r["status"] == "ERROR"])
    
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Errors: {errors}")
    print()
    
    if failed > 0 or errors > 0:
        print("Failed/Error tests:")
        for r in results:
            if r["status"] != "PASS":
                error = r.get("error", "unknown")
                print(f"  - {r['name']}: {error}")
    
    return 0 if (failed == 0 and errors == 0) else 1

if __name__ == "__main__":
    sys.exit(main())
