#!/usr/bin/env python3
"""Daily market index snapshot (free, best-effort).

Outputs a Telegram-friendly text report:
- US / CN / HK sections
- Each section has a monospace table: [index | close | change | change%]
- Plus: top 10 movers (largest absolute % move) per market from a representative universe.

Data sources (best-effort):
- Stooq daily CSV for major indices
- Alpha Vantage for US stock movers (free tier: 5 calls/min)
- local cache as last resort

Usage:
  python3 daily_market_prices.py
  python3 daily_market_prices.py --date 2026-02-04
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import time
from pathlib import Path
from typing import Iterable
from io import StringIO

import pandas as pd

try:
    import requests
except Exception as e:
    raise SystemExit(
        "Missing dependency requests. Install with: pip install requests\n"
        f"Import error: {e}"
    )

# Alpha Vantage API Key
ALPHA_VANTAGE_API_KEY = os.environ.get("ALPHA_VANTAGE_API_KEY", "RDOL5OM5RQ6AP8RB")

CACHE_PATH = Path(os.path.expanduser("~/Library/Caches/market-daily-prices/cache.json"))
CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X)"}

# Optional: reuse constituent CSVs from the blog repo if present.
BLOG_REPO = Path(os.path.expanduser("~/clawd/work/takjakim.github.io"))
BLOG_CONSTITUENTS = BLOG_REPO / "data" / "constituents"


def _load_cache() -> dict:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _stooq_last_two_closes(symbol: str, as_of: str | None = None) -> tuple[pd.Timestamp, float, float] | None:
    """Fetch last two closes from Stooq daily CSV.

    Returns (date, last_close, prev_close). If Stooq is rate-limited, returns None.
    """
    url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
    try:
        txt = requests.get(url, headers=UA, timeout=30).text.strip()
        if not txt or txt.startswith("Exceeded the daily hits limit"):
            return None
        if not txt.startswith("Date,"):
            return None
        df = pd.read_csv(StringIO(txt))
        if "Date" not in df.columns or "Close" not in df.columns:
            return None
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df = df.dropna(subset=["Date", "Close"]).sort_values("Date")
        if df.empty or len(df) < 2:
            return None
        if as_of:
            cutoff = pd.to_datetime(as_of)
            df = df[df["Date"] <= cutoff]
            if len(df) < 2:
                return None
        last = df.iloc[-1]
        prev = df.iloc[-2]
        return pd.Timestamp(last["Date"]), float(last["Close"]), float(prev["Close"])
    except Exception:
        return None


def _alphavantage_quote(symbol: str) -> tuple[float, float, float] | None:
    """Get quote from Alpha Vantage GLOBAL_QUOTE.

    Returns (price, change, change_percent) or None.
    """
    url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={symbol}&apikey={ALPHA_VANTAGE_API_KEY}"
    try:
        resp = requests.get(url, timeout=30)
        data = resp.json()

        if "Global Quote" not in data or not data["Global Quote"]:
            return None

        q = data["Global Quote"]
        price = float(q.get("05. price", 0))
        change = float(q.get("09. change", 0))
        change_pct = float(q.get("10. change percent", "0").replace("%", ""))

        if price <= 0:
            return None

        return price, change, change_pct
    except Exception:
        return None


def _alphavantage_daily(symbol: str) -> tuple[pd.Timestamp, float, float] | None:
    """Get last two closes from Alpha Vantage TIME_SERIES_DAILY.

    Returns (date, last_close, prev_close) or None.
    """
    url = f"https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol={symbol}&apikey={ALPHA_VANTAGE_API_KEY}&outputsize=compact"
    try:
        resp = requests.get(url, timeout=30)
        data = resp.json()

        if "Time Series (Daily)" not in data:
            return None

        ts = data["Time Series (Daily)"]
        dates = sorted(ts.keys(), reverse=True)

        if len(dates) < 2:
            return None

        last_date = dates[0]
        prev_date = dates[1]

        last_close = float(ts[last_date]["4. close"])
        prev_close = float(ts[prev_date]["4. close"])

        if prev_close <= 0:
            return None

        return pd.Timestamp(last_date), last_close, prev_close
    except Exception:
        return None


def _last_two_closes_index(ticker: str, stooq_symbol: str | None = None, as_of: str | None = None) -> tuple[pd.Timestamp, float, float] | None:
    """Try Stooq first for indices, then cache."""
    # 1) stooq (best for indices)
    if stooq_symbol:
        r = _stooq_last_two_closes(stooq_symbol, as_of=as_of)
        if r is not None:
            return r

    # 2) cache
    cache = _load_cache()
    if ticker in cache:
        try:
            d = pd.to_datetime(cache[ticker]["date"])
            return pd.Timestamp(d), float(cache[ticker]["close"]), float(cache[ticker]["prev"])
        except Exception:
            return None

    return None


def _fmt_row(name: str, close: float | None, chg: float | None, pct: float | None) -> str:
    def fnum(x: float | None) -> str:
        return "조회 실패" if x is None else f"{x:,.2f}"

    def fpct(x: float | None) -> str:
        return "조회 실패" if x is None else f"{x:+.2f}%"

    close_s = fnum(close)
    chg_s = "조회 실패" if chg is None else f"{chg:+,.2f}"
    pct_s = fpct(pct)

    return f"{name:<18} | {close_s:>12} | {chg_s:>10} | {pct_s:>9}"


def _movers_table(title: str, movers: list[tuple[str, str, float]] | None, limit: int = 10) -> str:
    """movers: list of (ticker, name, pct)."""
    if not movers:
        return f"{title}\n- (조회 실패/데이터 없음)"

    lines = ["ticker      | name                           | move%", "-" * 62]
    for t, n, p in movers[:limit]:
        n2 = (n or "").strip().replace("\n", " ")
        if len(n2) > 30:
            n2 = n2[:27] + "..."
        lines.append(f"{t:<10} | {n2:<30} | {p:+.2f}%")
    return f"{title}\n```\n" + "\n".join(lines) + "\n```"


def _format_gainers_losers(gainers: list[tuple[str, str, float]], losers: list[tuple[str, str, float]], market: str) -> str:
    """Format gainers and losers into two tables."""
    parts = []

    # Gainers (sorted by pct descending)
    gainers_sorted = sorted(gainers, key=lambda x: x[2], reverse=True)[:10]
    parts.append(_movers_table(f"📈 {market} 상승 Top 10", gainers_sorted))

    # Losers (sorted by pct ascending)
    losers_sorted = sorted(losers, key=lambda x: x[2])[:10]
    parts.append(_movers_table(f"📉 {market} 하락 Top 10", losers_sorted))

    return "\n\n".join(parts)


def _section(title: str, rows: list[str]) -> str:
    header = "지수               |         종가 |      변동 |    변동%"
    sep = "-" * len(header)
    body = "\n".join([header, sep, *rows])
    return f"{title}\n```\n{body}\n```"


def _read_constituents_csv(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    df = pd.read_csv(path)
    if "ticker" not in df.columns:
        return None
    if "name" not in df.columns:
        df["name"] = df["ticker"]
    df["ticker"] = df["ticker"].astype(str).str.strip()
    df["name"] = df["name"].astype(str).str.strip()
    df = df[df["ticker"].str.len() > 0].drop_duplicates("ticker")
    return df[["ticker", "name"]]


def _wiki_table_first(url: str) -> pd.DataFrame:
    html = requests.get(url, headers=UA, timeout=30).text
    tables = pd.read_html(StringIO(html))

    target = None
    tcol = None
    for t in tables:
        for c in t.columns:
            lc = str(c).lower()
            if lc == "ticker" or "ticker" in lc or "symbol" in lc:
                target = t
                tcol = c
                break
        if target is not None:
            break
    if target is None or tcol is None:
        raise RuntimeError(f"Ticker table not found: {url}")

    ncol = None
    for c in target.columns:
        lc = str(c).lower()
        if lc in ("company", "security", "name") or "company" in lc or "security" in lc:
            ncol = c
            break

    df = pd.DataFrame({
        "ticker": target[tcol].astype(str).str.strip().str.replace(".", "-", regex=False),
        "name": (target[ncol].astype(str).str.strip() if ncol is not None else target[tcol].astype(str).str.strip()),
    })
    df = df[df["ticker"].str.len() > 0].drop_duplicates("ticker")
    return df


def _get_universe_us_ndx() -> pd.DataFrame:
    df = _read_constituents_csv(BLOG_CONSTITUENTS / "us_ndx.csv")
    if df is not None:
        return df
    df = _wiki_table_first("https://en.wikipedia.org/wiki/Nasdaq-100")
    return df.head(110)


def _get_universe_cn_csi300() -> pd.DataFrame:
    df = _read_constituents_csv(BLOG_CONSTITUENTS / "cn_csi300.csv")
    if df is not None:
        return df
    return pd.DataFrame({
        "ticker": ["600519.SS", "601398.SS", "600036.SS", "600276.SS", "300750.SZ", "000333.SZ", "000858.SZ", "601318.SS", "600887.SS", "601888.SS"],
        "name": ["Kweichow Moutai", "ICBC", "CMB", "Hengrui", "CATL", "Midea", "Wuliangye", "Ping An", "Ili", "China Tourism"],
    })


def _get_universe_hk_hsi() -> pd.DataFrame:
    df = _read_constituents_csv(BLOG_CONSTITUENTS / "hk_hsi.csv")
    if df is not None:
        return df
    df = _wiki_table_first("https://en.wikipedia.org/wiki/Hang_Seng_Index")
    dig = df["ticker"].str.extract(r"(\d+)", expand=False).fillna("")
    df["ticker"] = dig.apply(lambda x: x.zfill(4) if x else x)
    df = df[df["ticker"].str.len() > 0]
    df["ticker"] = df["ticker"] + ".HK"
    return df.head(60)


def _get_movers_alphavantage(df: pd.DataFrame, market: str) -> tuple[list[tuple[str, str, float]], list[tuple[str, str, float]]]:
    """Get top movers using Alpha Vantage.

    Due to rate limit (5/min), only fetch top 25 tickers.
    Returns (gainers, losers) tuple.
    """
    tickers = df["ticker"].astype(str).tolist()[:25]  # Limit due to rate limit
    ticker_to_name = dict(zip(df["ticker"], df["name"]))

    gainers = []
    losers = []

    for i, ticker in enumerate(tickers):
        # Alpha Vantage uses plain symbols for US stocks
        av_symbol = ticker.replace("-", ".")

        quote = _alphavantage_quote(av_symbol)
        if quote:
            price, change, change_pct = quote
            item = (ticker, ticker_to_name.get(ticker, ticker), change_pct)
            if change_pct >= 0:
                gainers.append(item)
            else:
                losers.append(item)

        # Rate limit: 5 calls per minute = 12 seconds between calls
        # But we'll use 13 seconds to be safe
        if i < len(tickers) - 1:
            print(f"  [{market}] Fetched {ticker}, waiting... ({i+1}/{len(tickers)})")
            time.sleep(13)

    return gainers, losers


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD (optional). If omitted, uses latest available.")
    ap.add_argument("--skip-movers", action="store_true", help="Skip fetching movers (faster)")
    args = ap.parse_args(list(argv) if argv is not None else None)

    as_of = args.date

    # Index definitions with Stooq symbols
    us = {
        "S&P 500": {"ticker": "^GSPC", "stooq": "^spx"},
        "NASDAQ 100": {"ticker": "^NDX", "stooq": "^ndx"},
    }
    cn = {
        "SSE": {"ticker": "000001.SS", "stooq": "000001.ss"},
        "CSI 300": {"ticker": "000300.SS", "stooq": None},
    }
    hk = {
        "Hang Seng": {"ticker": "^HSI", "stooq": "^hsi"},
    }

    # Movers universes
    uni_us = _get_universe_us_ndx()
    uni_cn = _get_universe_cn_csi300()
    uni_hk = _get_universe_hk_hsi()

    sections = []
    failures = []
    report_date: dt.date | None = None

    cache = _load_cache()

    print("Fetching index data from Stooq...")
    for title, mp in [("🇺🇸 미국 (전일 종가 기준)", us), ("🇨🇳 중국 (직전 거래일 종가 기준)", cn), ("🇭🇰 홍콩 (직전 거래일 종가 기준)", hk)]:
        rows = []
        for name, spec in mp.items():
            ticker = spec["ticker"]
            stooq_sym = spec.get("stooq")

            r = _last_two_closes_index(ticker, stooq_symbol=stooq_sym, as_of=as_of)
            if r is None:
                rows.append(_fmt_row(name, None, None, None))
                failures.append(ticker)
                continue

            d, close, prev = r
            chg = close - prev
            pct = (close / prev - 1.0) * 100.0
            rows.append(_fmt_row(name, close, chg, pct))

            cache[ticker] = {"date": d.strftime("%Y-%m-%d"), "close": close, "prev": prev}

            if report_date is None:
                report_date = d.date()

        sections.append(_section(title, rows))

    # Movers (using Alpha Vantage for US only due to rate limits)
    movers_blocks = []

    if args.skip_movers:
        movers_blocks.append("🇺🇸 미국 상승/하락 Top 10\n- (--skip-movers 옵션으로 스킵)")
        movers_blocks.append("🇨🇳 중국 상승/하락 Top 10\n- (--skip-movers 옵션으로 스킵)")
        movers_blocks.append("🇭🇰 홍콩 상승/하락 Top 10\n- (--skip-movers 옵션으로 스킵)")
    else:
        print("\nFetching US movers from Alpha Vantage (this takes ~5 minutes due to rate limit)...")
        us_gainers, us_losers = _get_movers_alphavantage(uni_us, "US")
        movers_blocks.append(_format_gainers_losers(us_gainers, us_losers, "🇺🇸 미국 (NDX)"))

        # For CN and HK, Alpha Vantage doesn't support well, so skip or use placeholder
        movers_blocks.append("🇨🇳 중국 상승/하락 Top 10\n- (Alpha Vantage 미지원)")
        movers_blocks.append("🇭🇰 홍콩 상승/하락 Top 10\n- (Alpha Vantage 미지원)")

    _save_cache(cache)

    date_line = f"기준일(데이터 최신일): {report_date.isoformat()}" if report_date else "기준일: 조회 실패"

    comments = [
        "코멘트:",
        "- 지수: Stooq 무료 API 사용",
        "- US Movers: Alpha Vantage 무료 API (분당 5회 제한)",
        "- CN/HK Movers: Alpha Vantage 미지원으로 스킵",
    ]
    if failures:
        comments.append(f"- 실패 티커: {', '.join(failures)}")

    out = "\n\n".join([
        "📌 데일리 지수 스냅샷",
        date_line,
        *sections,
        *movers_blocks,
        "\n".join(comments),
    ])
    print("\n" + "="*60 + "\n")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
