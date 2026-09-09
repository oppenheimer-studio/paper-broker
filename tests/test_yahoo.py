from paper_broker.adapters.yahoo import YahooFeed


def test_parse_dividends_and_splits():
    payload = {
        "chart": {
            "result": [
                {
                    "timestamp": [],
                    "indicators": {"quote": [{}], "adjclose": [{}]},
                    "events": {
                        "dividends": {
                            "1756944000": {"amount": 0.25, "date": 1756944000},
                        },
                        "splits": {
                            "1756944000": {
                                "date": 1756944000,
                                "numerator": 4,
                                "denominator": 1,
                                "splitRatio": "4:1",
                            }
                        },
                    },
                }
            ]
        }
    }
    feed = YahooFeed("test-agent", 5)
    actions = feed._parse_actions("AAPL", payload)
    kinds = {a.action: a for a in actions}
    assert "dividend" in kinds
    assert kinds["dividend"].value == 0.25
    assert "split" in kinds
    assert kinds["split"].numerator == 4
    assert kinds["split"].denominator == 1
    assert kinds["split"].value == 4.0
