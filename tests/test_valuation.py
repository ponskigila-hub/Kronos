import importlib.util
from pathlib import Path

_module_spec = importlib.util.spec_from_file_location(
    "valuation_under_test", Path(__file__).resolve().parents[1] / "assistant" / "valuation.py"
)
_valuation = importlib.util.module_from_spec(_module_spec)
_module_spec.loader.exec_module(_valuation)
analyze_profiles = _valuation.analyze_profiles
_to_profile = _valuation._to_profile


def _profile(ticker, *, price=100, pe=20, ps=4, pb=4, ev=10,
             eps=5, rev_ps=20, book_ps=25, ebitda=10_000_000,
             shares=1_000_000, debt=5_000_000, cash=1_000_000,
             sector="Technology", industry="Software"):
    return {
        "ticker": ticker, "name": ticker, "price": price, "currency": "USD",
        "sector": sector, "industry": industry, "market_cap": 100_000_000,
        "trailing_pe": pe, "forward_pe": pe, "price_to_sales": ps,
        "price_to_book": pb, "ev_to_ebitda": ev, "forward_eps": eps,
        "revenue_per_share": rev_ps, "book_value_per_share": book_ps,
        "ebitda": ebitda, "shares_outstanding": shares, "total_debt": debt,
        "total_cash": cash, "revenue_growth": 0.1, "earnings_growth": 0.12,
        "profit_margin": 0.2, "free_cash_flow": 8_000_000,
        "regular_market_time": None,
    }


def test_relative_valuation_builds_four_ranges_from_user_peers():
    target = _profile("TGT", price=90, pe=18, ps=3, pb=3, ev=9)
    peers = [
        _profile("P1", pe=15, ps=2, pb=3, ev=8),
        _profile("P2", pe=20, ps=3, pb=4, ev=10),
        _profile("P3", pe=25, ps=4, pb=5, ev=12),
    ]
    result = analyze_profiles("TGT", [p["ticker"] for p in peers], target, peers)
    assert len(result["methods"]) == 4
    pe = next(m for m in result["methods"] if m["name"] == "Forward P/E")
    assert pe["peer_count"] == 3
    assert pe["implied_mid"] == 100
    assert result["summary"]["method_count"] == 4
    assert result["summary"]["upside_vs_price_pct"] > 0
    assert "not a DCF" in result["warnings"][0]


def test_no_combined_reference_when_only_one_method_is_usable():
    target = _profile("TGT", eps=5, rev_ps=None, book_ps=None, ebitda=None)
    peers = [_profile("P1"), _profile("P2"), _profile("P3")]
    result = analyze_profiles("TGT", [p["ticker"] for p in peers], target, peers)
    assert [m["name"] for m in result["methods"]] == ["Forward P/E"]
    assert result["summary"] is None
    assert any("Fewer than two" in warning for warning in result["warnings"])


def test_negative_or_missing_earnings_do_not_produce_pe_valuation():
    target = _profile("TGT", eps=-1)
    peers = [_profile("P1"), _profile("P2"), _profile("P3")]
    result = analyze_profiles("TGT", [p["ticker"] for p in peers], target, peers)
    assert all(m["name"] != "Forward P/E" for m in result["methods"])


def test_method_is_omitted_without_three_usable_peer_multiples():
    target = _profile("TGT")
    peers = [_profile("P1", pe=10), _profile("P2", pe=None), _profile("P3", pe=None)]
    result = analyze_profiles("TGT", [p["ticker"] for p in peers], target, peers)
    assert all(m["name"] != "Forward P/E" for m in result["methods"])


def test_profile_normalization_excludes_raw_fields_and_converts_timestamp():
    normalized = _to_profile("XYZ", {
        "longName": "Example Co", "currentPrice": 12,
        "regularMarketTime": 1_700_000_000, "forwardEps": 1.5,
        "privateContact": "should not leak",
    })
    assert normalized["name"] == "Example Co"
    assert normalized["regular_market_time"].startswith("2023-")
    assert "privateContact" not in normalized
    assert normalized["forward_eps"] == 1.5
