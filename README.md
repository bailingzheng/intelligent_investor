# Graham's Defensive Investor Stock Screener

Evaluate stocks against Benjamin Graham's 7 rules from "The Intelligent Investor".

## The 7 Rules

1. Market cap > $10B
2. Current Ratio > 2.0 AND Long-term debt < Working Capital (Utilities: debt/equity < 2)
3. Positive earnings in each of past 10 years
4. Uninterrupted dividends >= 20 years
5. EPS growth > 33.3% (3-year averages, 10-year period)
6. P/E < 15 (3-year average earnings)
7. P/B < 1.5

## Setup

1. Get API key from [Alpha Vantage](https://www.alphavantage.co/support/#api-key)
2. Add key to `config.py`
3. Run: `pip install -r requirements.txt`
4. Run: `python defensive_investor_screener.py AAPL`

## Source

Graham, Benjamin; Jason Zweig. The Intelligent Investor, Rev. Ed (p. 386-387)
