#!/usr/bin/env python3
"""
Kronos NLP Intent Routing Verification
Tests the NLP parser from assistant/nlp.py for intent routing accuracy.
"""
import sys
sys.path.insert(0, '.')

from assistant.nlp import parse_intent

# Test cases: (input, expected_intent, expected_tickers, description)
test_cases = [
    ("forecast AAPL", "forecast", ["AAPL"], "baseline forecast command"),
    ("is TSLA a good buy", "opinion", ["TSLA"], "opinion question - not forecast"),
    ("compare NVDA and AMD", "compare", ["NVDA", "AMD"], "two-ticker comparison"),
    ("any risks?", "unknown", [], "short follow-up without context"),
    ("what's the risk of investing in a bear market in general", "unknown", [], "long ambiguous - should NOT be risk"),
    ("how are you doing", "unknown", [], "general chat - not stock-related"),
    ("how's it going", "unknown", [], "general chat - not stock-related"),
    ("AAPL vs MSFT comparison", "compare", ["AAPL", "MSFT"], "vs comparison"),
    ("news on AAPL", "news", ["AAPL"], "news request"),
    ("fundamentals TSLA", "fundamentals", ["TSLA"], "fundamentals request"),
    ("backtest AAPL", "backtest", ["AAPL"], "backtest request"),
]

results = []

for text, expected_intent, expected_tickers, description in test_cases:
    result = parse_intent(text)
    intent = result.get("intent", "unknown")
    tickers = result.get("tickers", [])
    
    # Normalize for comparison
    intent = intent.strip().lower() if intent else "unknown"
    expected_intent = expected_intent.strip().lower()
    tickers_sorted = sorted([t.upper() for t in tickers if t])
    expected_sorted = sorted([t.upper() for t in expected_tickers if t])
    
    match = (intent == expected_intent) and (tickers_sorted == expected_sorted)
    
    status = "✓" if match else "✗"
    print(f"{status} Input: '{text}'")
    print(f"  Expected: intent={expected_intent}, tickers={expected_sorted}")
    print(f"  Got:      intent={intent}, tickers={tickers_sorted}")
    if not match:
        print(f"  MISMATCH!")
    print()
    
    results.append({
        "input": text,
        "description": description,
        "status": "PASS" if match else "FAIL",
        "expected": (expected_intent, expected_sorted),
        "actual": (intent, tickers_sorted)
    })

print("=" * 70)
print("RESULTS SUMMARY")
print("=" * 70)
passed = len([r for r in results if r["status"] == "PASS"])
failed = len([r for r in results if r["status"] == "FAIL"])

print(f"Passed: {passed}/{len(results)}")
print(f"Failed: {failed}/{len(results)}")

if failed > 0:
    print("\nFailed tests:")
    for r in results:
        if r["status"] == "FAIL":
            print(f"  - {r['description']}")
            print(f"    Input: {r['input']}")
            print(f"    Expected: {r['expected']}")
            print(f"    Got: {r['actual']}")

sys.exit(0 if failed == 0 else 1)
