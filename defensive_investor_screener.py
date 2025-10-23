#!/usr/bin/env python3
"""
Evaluate stocks against Graham's 7 Rules for Defensive Investors

Rules:
1. Market cap > $10B
2. Utilities: debt/equity < 2
   Non-utilities: Current Ratio > 2.0 AND Long-term debt < Working Capital
3. Positive earnings in each of past 10 years
4. Uninterrupted dividends >= 20 years
5. EPS growth > 33.3% (3-year averages, 10-year period)
6. P/E < 15 (3-year average earnings)
7. P/B < 1.5

Source: Graham, Benjamin; Jason Zweig. The Intelligent Investor, Rev. Ed (p. 386-387)
"""

import time
import requests
from typing import Dict, Tuple, Optional
import warnings
import os
warnings.filterwarnings('ignore')


# ============================================================================
# CONFIGURATION
# ============================================================================

class Config:
    """Configuration for the screener."""
    # API Settings
    API_CALLS_PER_STOCK = 4  # Overview, Income Statement, Balance Sheet, Dividends
    CALLS_PER_MINUTE = 5
    MAX_DAILY_CALLS = 25  # Free tier limit
    
    # Graham's Criteria
    MIN_MARKET_CAP = 10_000_000_000  # $10B
    MIN_CURRENT_RATIO = 2.0
    MIN_DIVIDEND_YEARS = 20
    MIN_EARNINGS_GROWTH = 1/3  # 33.33%
    MAX_PE_RATIO = 15
    MAX_PB_RATIO = 1.5
    MIN_EARNINGS_YEARS = 10


def get_api_key() -> str:
    """Get API key from config.py or environment."""
    try:
        from config import ALPHA_VANTAGE_API_KEY
        return ALPHA_VANTAGE_API_KEY
    except ImportError:
        return os.environ.get('ALPHA_VANTAGE_API_KEY', '')


def validate_api_key(api_key: str) -> bool:
    """Validate API key is configured."""
    return api_key and api_key != 'your_api_key_here'


# ============================================================================
# ALPHA VANTAGE API CLIENT
# ============================================================================

class AlphaVantageClient:
    """API client with rate limiting."""
    
    BASE_URL = "https://www.alphavantage.co/query"
    
    def __init__(self, api_key: str, calls_per_minute: int = None):
        self.api_key = api_key
        self.calls_per_minute = calls_per_minute or Config.CALLS_PER_MINUTE
        self.min_delay = 60.0 / self.calls_per_minute
        self.last_call_time = 0
        self.daily_calls = 0
        self.max_daily_calls = Config.MAX_DAILY_CALLS
    
    def _rate_limit(self):
        """Enforce rate limiting."""
        elapsed = time.time() - self.last_call_time
        if elapsed < self.min_delay:
            time.sleep(self.min_delay - elapsed)
        self.last_call_time = time.time()
        self.daily_calls += 1
    
    def _make_request(self, params: Dict) -> Optional[Dict]:
        """Make API request."""
        if self.daily_calls >= self.max_daily_calls:
            print(f"\n⚠️  Reached daily API limit ({self.max_daily_calls} calls)")
            return None
        
        self._rate_limit()
        params['apikey'] = self.api_key
        
        try:
            response = requests.get(self.BASE_URL, params=params, timeout=30)
            
            if response.status_code != 200:
                print(f"API error: HTTP {response.status_code}")
                return None
            
            data = response.json()

            if 'Information' in data:  # Rate limit or API restriction
                print(f"\n⚠️  API Information: {data['Information']}")
                return None
            
            return data
        except Exception as e:
            print(f"API error: {str(e)[:50]}")
            return None
    
    def _get_data(self, function: str, symbol: str) -> Optional[Dict]:
        """Fetch data from API."""
        return self._make_request({'function': function, 'symbol': symbol})
    
    def get_overview(self, symbol: str) -> Optional[Dict]:
        """Get company overview."""
        return self._get_data('OVERVIEW', symbol)
    
    def get_income_statement(self, symbol: str) -> Optional[Dict]:
        """Get income statement."""
        return self._get_data('INCOME_STATEMENT', symbol)
    
    def get_balance_sheet(self, symbol: str) -> Optional[Dict]:
        """Get balance sheet."""
        return self._get_data('BALANCE_SHEET', symbol)
    
    def get_cash_flow(self, symbol: str) -> Optional[Dict]:
        """Get cash flow statement."""
        return self._get_data('CASH_FLOW', symbol)
    
    def get_dividends(self, symbol: str) -> Optional[Dict]:
        """Get dividend history."""
        return self._make_request({'function': 'DIVIDENDS', 'symbol': symbol})


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_field(data: Dict, field: str) -> float:
    """Get and validate field value, raise error if invalid."""
    value = data.get(field)
    if value is None or value == '' or value == 'None' or value == '-':
        raise ValueError(f"{field} N/A")
    try:
        return float(value)
    except (ValueError, TypeError) as e:
        raise ValueError(f"{field} invalid: {value}")


# ============================================================================
# RULE CHECKING FUNCTIONS
# ============================================================================

def check_rule_1_size(overview: Dict) -> Tuple[bool, str]:
    """Rule 1: Market Cap > $10B"""
    try:
        market_cap = get_field(overview, 'MarketCapitalization')
        passed = market_cap > Config.MIN_MARKET_CAP
        msg = f"market cap ${market_cap/1e9:.2f}B"
        return passed, msg if passed else f"{msg} (< $10B)"
    except Exception as e:
        return False, f"error ({str(e)})"


def check_rule_2_financial_condition(balance_sheet: Dict, income_statement: Dict, overview: Dict) -> Tuple[bool, str]:
    """Rule 2: Utilities check debt/equity < 2; Non-utilities check current ratio > 2 AND long-term debt < working capital; Print interest coverage (7yr) for all"""
    try:
        if 'annualReports' not in balance_sheet or not balance_sheet['annualReports']:
            return False, "no balance sheet data"
        
        latest = balance_sheet['annualReports'][0]
        
        # Total debt = Long-term debt + Short-term debt
        long_term_debt = get_field(latest, 'longTermDebt')
        short_term_debt = get_field(latest, 'shortTermDebt')
        total_debt = long_term_debt + short_term_debt
        total_equity = get_field(latest, 'totalShareholderEquity')
        
        # Calculate debt/equity ratio
        debt_to_equity_ratio = total_debt / total_equity if total_equity > 0 else None
        
        # Calculate interest coverage for past 7 years (for all companies)
        interest_coverage_list = []
        if 'annualReports' in income_statement and income_statement['annualReports']:
            for i, report in enumerate(income_statement['annualReports'][:7]):
                try:
                    ebit = get_field(report, 'ebit')
                    interest_expense = get_field(report, 'interestExpense')
                    if interest_expense > 0:
                        coverage = ebit / interest_expense
                        interest_coverage_list.append(f"{coverage:.2f}")
                    else:
                        interest_coverage_list.append("N/A")
                except:
                    interest_coverage_list.append("N/A")
        
        interest_coverage_str = f"7-yr interest coverage: [{', '.join(interest_coverage_list)}]" if interest_coverage_list else "Interest coverage: N/A"
        
        # Check if utility
        sector = overview.get('Sector', '').lower()
        is_utility = sector == 'utilities'
        
        if is_utility:
            # Utilities: debt/equity < 2
            passed = debt_to_equity_ratio is not None and debt_to_equity_ratio < 2.0
            
            if debt_to_equity_ratio is None:
                msg = f"debt/equity N/A (negative equity), {interest_coverage_str}"
            elif passed:
                msg = f"debt/equity {debt_to_equity_ratio:.2f}, {interest_coverage_str}"
            else:
                msg = f"debt/equity {debt_to_equity_ratio:.2f} (>= 2.0), {interest_coverage_str}"
            
            return passed, msg
        else:
            # Non-utilities: current ratio > 2.0 AND long-term debt < working capital
            current_assets = get_field(latest, 'totalCurrentAssets')
            current_liabilities = get_field(latest, 'totalCurrentLiabilities')
            # long_term_debt already fetched above
            
            current_ratio = current_assets / current_liabilities
            working_capital = current_assets - current_liabilities
            
            ratio_ok = current_ratio > Config.MIN_CURRENT_RATIO
            debt_ok = long_term_debt < working_capital
            
            parts = []
            if ratio_ok:
                parts.append(f"current ratio {current_ratio:.2f}")
            else:
                parts.append(f"current ratio {current_ratio:.2f} (<= 2.0)")
            
            if debt_ok:
                parts.append(f"long-term debt ${long_term_debt/1e6:.1f}M, working capital ${working_capital/1e6:.1f}M")
            else:
                parts.append(f"long-term debt ${long_term_debt/1e6:.1f}M (>= working capital ${working_capital/1e6:.1f}M)")
            
            parts.append(interest_coverage_str)
            
            msg = ", ".join(parts)
            return (ratio_ok and debt_ok), msg
    except Exception as e:
        return False, f"error ({str(e)})"


def check_rule_3_earnings_stability(income_statement: Dict) -> Tuple[bool, str]:
    """Rule 3: Positive earnings in past 10 years"""
    try:
        if 'annualReports' not in income_statement or not income_statement['annualReports']:
            return False, "no income statement data"
        
        reports = income_statement['annualReports'][:Config.MIN_EARNINGS_YEARS]
        
        if len(reports) < Config.MIN_EARNINGS_YEARS:
            return False, f"need {Config.MIN_EARNINGS_YEARS} years of data (only {len(reports)} available)"
        
        positive_years = sum(1 for r in reports if get_field(r, 'netIncome') > 0)
        
        passed = positive_years == Config.MIN_EARNINGS_YEARS
        msg = f"positive earnings {positive_years}/{Config.MIN_EARNINGS_YEARS} years"
        return passed, msg
    except Exception as e:
        return False, f"error ({str(e)})"


def check_rule_4_dividend_record(overview: Dict, dividends: Dict) -> Tuple[bool, str]:
    """Rule 4: Uninterrupted dividends >= 20 years"""
    try:
        dividend_yield = get_field(overview, 'DividendYield')
        
        if 'data' not in dividends or not dividends['data']:
            return False, f"dividend yield {dividend_yield*100:.2f}% (history not available)"
        
        dividend_data = dividends['data']
        
        from datetime import datetime
        years_with_dividends = set()
        
        for record in dividend_data:
            ex_date = record.get('ex_dividend_date')
            if ex_date:
                try:
                    year = datetime.strptime(ex_date, '%Y-%m-%d').year
                    years_with_dividends.add(year)
                except:
                    continue
        
        if not years_with_dividends:
            return False, "no valid dividend dates found"
        
        sorted_years = sorted(years_with_dividends, reverse=True)
        consecutive_years = 0
        
        for i, year in enumerate(sorted_years):
            if i == 0:
                consecutive_years = 1
            elif year == sorted_years[i-1] - 1:
                consecutive_years += 1
            else:
                break  # Gap found, dividends interrupted
        
        if consecutive_years >= Config.MIN_DIVIDEND_YEARS:
            return True, f"dividend yield {dividend_yield*100:.2f}%, {consecutive_years} consecutive years"
        else:
            return False, f"only {consecutive_years} consecutive years (< {Config.MIN_DIVIDEND_YEARS})"
    except Exception as e:
        return False, f"error ({str(e)})"


def check_rule_5_earnings_growth(income_statement: Dict, balance_sheet: Dict) -> Tuple[bool, str]:
    """Rule 5: EPS growth > 33.3% (3-year averages, 10-year period)"""
    try:
        if 'annualReports' not in income_statement or len(income_statement['annualReports']) < 10:
            years = len(income_statement.get('annualReports', []))
            return False, f"need 10 years of data (only {years} available)"
        
        if 'annualReports' not in balance_sheet or len(balance_sheet['annualReports']) < 10:
            years = len(balance_sheet.get('annualReports', []))
            return False, f"need 10 years of balance sheet data (only {years} available)"
        
        income_reports = income_statement['annualReports'][:10]
        balance_reports = balance_sheet['annualReports'][:10]
        
        eps_values = []
        for income_report, balance_report in zip(income_reports, balance_reports):
            try:
                net_income = get_field(income_report, 'netIncome')
                shares_outstanding = get_field(balance_report, 'commonStockSharesOutstanding')
                eps_values.append(net_income / shares_outstanding)
            except:
                eps_values.append(None)
        
        if len([e for e in eps_values if e is not None]) < 10:
            return False, f"need 10 years of EPS data (only {len([e for e in eps_values if e is not None])} available)"
        
        # 3-year averages: recent 3 years vs years 7-9
        ending_eps = [eps_values[i] for i in range(3) if eps_values[i] is not None]
        beginning_eps = [eps_values[i] for i in range(7, 10) if eps_values[i] is not None]
        
        if len(ending_eps) < 3 or len(beginning_eps) < 3:
            return False, "insufficient EPS data for 3-year averages"
        
        ending_avg = sum(ending_eps) / len(ending_eps)
        beginning_avg = sum(beginning_eps) / len(beginning_eps)
        
        if beginning_avg <= 0:
            return False, "starting 3-year average EPS not positive"
        
        growth = (ending_avg - beginning_avg) / abs(beginning_avg)
        passed = growth > Config.MIN_EARNINGS_GROWTH
        
        beginning_eps_str = ", ".join([f"${eps:.2f}" for eps in beginning_eps])
        ending_eps_str = ", ".join([f"${eps:.2f}" for eps in ending_eps])
        
        msg = f"EPS growth {growth*100:.1f}% (3-yr avg ${beginning_avg:.2f} → ${ending_avg:.2f}), beginning 3-yr EPS [{beginning_eps_str}], ending 3-yr EPS [{ending_eps_str}]"
        if passed:
            return passed, msg
        else:
            return passed, f"EPS growth {growth*100:.1f}% (3-yr avg ${beginning_avg:.2f} → ${ending_avg:.2f}) (<= 33.3%, per-share basis), beginning 3-yr EPS [{beginning_eps_str}], ending 3-yr EPS [{ending_eps_str}]"
    except Exception as e:
        return False, f"error ({str(e)})"


def check_rule_6_pe_ratio(overview: Dict, income_statement: Dict, balance_sheet: Dict) -> Tuple[bool, str]:
    """Rule 6: P/E < 15 (3-year average earnings)"""
    try:
        price = get_field(overview, '50DayMovingAverage')
        
        if 'annualReports' not in income_statement or len(income_statement['annualReports']) < 3:
            return False, "need 3 years of earnings data"
        
        if 'annualReports' not in balance_sheet or len(balance_sheet['annualReports']) < 3:
            return False, "need 3 years of balance sheet data"
        
        income_reports = income_statement['annualReports'][:3]
        balance_reports = balance_sheet['annualReports'][:3]
        eps_values = []
        
        for income_report, balance_report in zip(income_reports, balance_reports):
            try:
                net_income = get_field(income_report, 'netIncome')
                shares_outstanding = get_field(balance_report, 'commonStockSharesOutstanding')
                eps_values.append(net_income / shares_outstanding)
            except:
                pass
        
        if len(eps_values) < 3:
            return False, "need 3 years of EPS data"
        
        avg_eps = sum(eps_values) / len(eps_values)
        
        if avg_eps <= 0:
            return False, "3-year average EPS not positive"
        
        price_to_avg_earnings = price / avg_eps
        passed = price_to_avg_earnings < Config.MAX_PE_RATIO
        
        eps_str = ", ".join([f"${eps:.2f}" for eps in eps_values])
        
        msg = f"price/avg earnings {price_to_avg_earnings:.2f} (price ${price:.2f}, 3-yr avg EPS ${avg_eps:.2f}), 3-yr EPS [{eps_str}]"
        return passed, msg if passed else f"price/avg earnings {price_to_avg_earnings:.2f} (>= {Config.MAX_PE_RATIO}), price ${price:.2f}, 3-yr EPS [{eps_str}]"
    except Exception as e:
        return False, f"error ({str(e)})"


def check_rule_7_price_to_book(overview: Dict) -> Tuple[bool, str]:
    """Rule 7: P/B < 1.5"""
    try:
        pb_ratio = get_field(overview, 'PriceToBookRatio')
        
        passed = pb_ratio < Config.MAX_PB_RATIO
        msg = f"P/B {pb_ratio:.2f}"
        return passed, msg if passed else f"{msg} (>= {Config.MAX_PB_RATIO})"
    except Exception as e:
        return False, f"error ({str(e)})"


# ============================================================================
# STOCK EVALUATION
# ============================================================================

def evaluate_stock(ticker: str, client: AlphaVantageClient, verbose: bool = False, output_func=None) -> Optional[Dict]:
    """Evaluate a stock against all 7 Graham rules."""
    out = output_func if output_func else print
    
    try:
        if verbose:
            out(f"Fetching data for {ticker}...", end=" ", flush=True)
        
        overview = client.get_overview(ticker)
        if not overview or not overview.get('Symbol'):
            if verbose:
                out(f"❌ No data")
            return None
        
        income_statement = client.get_income_statement(ticker)
        balance_sheet = client.get_balance_sheet(ticker)
        dividends = client.get_dividends(ticker)
        
        rules = [
            ('Rule 1 (adequate size)', check_rule_1_size(overview)),
            ('Rule 2 (strong financial condition)', check_rule_2_financial_condition(balance_sheet or {}, income_statement or {}, overview)),
            ('Rule 3 (earnings stability)', check_rule_3_earnings_stability(income_statement or {})),
            ('Rule 4 (dividend record)', check_rule_4_dividend_record(overview, dividends or {})),
            ('Rule 5 (earnings growth)', check_rule_5_earnings_growth(income_statement or {}, balance_sheet or {})),
            ('Rule 6 (moderate P/E)', check_rule_6_pe_ratio(overview, income_statement or {}, balance_sheet or {})),
            ('Rule 7 (moderate P/B)', check_rule_7_price_to_book(overview)),
        ]
        
        results = {
            'ticker': ticker,
            'company_name': overview.get('Name', ticker),
            'current_price': overview.get('50DayMovingAverage', 'N/A'),
            'rules_passed': [],
            'rules_failed': [],
            'rule_details': {},
            'total_passed': 0,
            'passes_all': False
        }
        
        for rule_name, (passed, detail) in rules:
            results['rule_details'][rule_name] = detail
            if passed:
                results['rules_passed'].append(rule_name)
            else:
                results['rules_failed'].append(rule_name)
        
        results['total_passed'] = len(results['rules_passed'])
        results['passes_all'] = results['total_passed'] == 7
        
        if verbose:
            status = "✅ PASS" if results['passes_all'] else f"⚠️  {results['total_passed']}/7"
            out(f"{status} {results['company_name']}")
            for rule_name, detail in results['rule_details'].items():
                symbol = "✓" if rule_name in results['rules_passed'] else "✗"
                out(f"  {symbol} {rule_name}: {detail}")
            out()
        
        return results
    except Exception as e:
        if verbose:
            out(f"❌ Error: {str(e)[:50]}")
        return None


# ============================================================================
# COMMAND LINE INTERFACE
# ============================================================================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Evaluate a stock against Graham's 7 Rules (Alpha Vantage API)"
    )
    parser.add_argument('ticker', type=str,
                        help='Stock ticker symbol to evaluate')
    parser.add_argument('--output', '-o', type=str, default='screening_results.txt',
                        help='Output file (default: screening_results.txt)')
    parser.add_argument('--api-key', '-k', type=str,
                        help='Alpha Vantage API key (or set in config.py)')
    
    args = parser.parse_args()
    
    api_key = args.api_key or get_api_key()
    
    if not validate_api_key(api_key):
        print("❌ Error: API key not configured")
        print("   Get a free key: https://www.alphavantage.co/support/#api-key")
        print("   Then create config.py from config.py.example")
        exit(1)
    
    # Open output file
    output_file = open(args.output, 'a', encoding='utf-8')
    
    def output(text="", end="\n", flush=False):
        """Print to console and file."""
        print(text, end=end, flush=flush)
        output_file.write(str(text) + end)
        if flush:
            output_file.flush()
    
    client = AlphaVantageClient(api_key)
    result = evaluate_stock(args.ticker, client, verbose=True, output_func=output)
    
    output_file.close()
