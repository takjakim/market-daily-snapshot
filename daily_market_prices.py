#!/usr/bin/env python3
"""Daily market index snapshot (free, best-effort).

Outputs a Telegram-friendly text report:
- US / CN / HK sections
- Each section has a monospace table: [index | close | change | change%]
- Plus: top 10 movers (largest absolute % move) per market from a representative universe.

Data sources (best-effort):
- Stooq daily CSV for major indices when available
- yfinance for index levels and constituents (batched, small universes)
- local cache as last resort

Usage:
  python3 scripts/daily_market_prices.py
  python3 scripts/daily_market_prices.py --date 2026-02-04
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import time
from pathlib import Path
from typing import Iterable

import pandas as pd

try:
    import yfinance as yf
except Exception as e:
    raise SystemExit(
        "Missing dependency yfinance. Install with: pip install yfinance pandas\n"
        f"Import error: {e}"
    )

try:
    import requests
except Exception as e:
    raise SystemExit(
        "Missing dependency requests. Install with: pip install requests\n"
        f"Import error: {e}"
    )

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

    Note: Stooq uses symbols like 'spx', 'ndx', 'hsi' (lowercase), and country suffixes like '.us'.
    """
    url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
    try:
        txt = requests.get(url, headers=UA, timeout=30).text.strip()
        if not txt or txt.startswith("Exceeded the daily hits limit"):
            return None
        if not txt.startswith("Date,"):
            return None
        df = pd.read_csv(pd.io.common.StringIO(txt))
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


def _yf_last_two_closes(ticker: str, as_of: str | None = None) -> tuple[pd.Timestamp, float, float] | None:
    """Return (date, last_close, prev_close) for the latest available trading day <= as_of via yfinance."""
    end = pd.to_datetime(as_of) + pd.Timedelta(days=1) if as_of else None

    for attempt in range(3):
        try:
            df = yf.download(
                tickers=ticker,
                period="14d" if end is None else None,
                start=None if end is None else (end - pd.Timedelta(days=21)).strftime("%Y-%m-%d"),
                end=None if end is None else end.strftime("%Y-%m-%d"),
                interval="1d",
                group_by="ticker",
                auto_adjust=False,
                threads=False,
                progress=False,
            )
            if df is None or df.empty:
                raise RuntimeError("empty")

            df = df.dropna(subset=["Close"], how="any")
            if len(df) < 2:
                raise RuntimeError("not enough rows")

            df.index = pd.to_datetime(df.index)
            df = df.sort_index()

            last_dt = df.index[-1]
            last_close = float(df.iloc[-1]["Close"])
            prev_close = float(df.iloc[-2]["Close"])
            if prev_close <= 0:
                raise RuntimeError("bad prev")
            return last_dt, last_close, prev_close
        except Exception:
            time.sleep(1.0 + attempt * 1.5)
            continue

    return None


def _last_two_closes(ticker: str, *, stooq_symbol: str | None = None, as_of: str | None = None) -> tuple[pd.Timestamp, float, float] | None:
    """Try Stooq first (if symbol provided), then yfinance, then cache."""
    # 1) stooq
    if stooq_symbol:
        r = _stooq_last_two_closes(stooq_symbol, as_of=as_of)
        if r is not None:
            return r

    # 2) yfinance
    r = _yf_last_two_closes(ticker, as_of=as_of)
    if r is not None:
        return r

    # 3) cache
    cache = _load_cache()
    if ticker in cache:
        try:
            d = pd.to_datetime(cache[ticker]["date"])
            return pd.Timestamp(d), float(cache[ticker]["close"]), float(cache[ticker]["prev"])  # type: ignore
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


def _movers_table(title: str, movers: list[tuple[str, str, float]] | None) -> str:
    """movers: list of (ticker, name, pct)."""
    if not movers:
        return f"{title}\n- (조회 실패/데이터 없음)"

    lines = ["ticker      | name                           | move%", "-" * 62]
    for t, n, p in movers[:10]:
        n2 = (n or "").strip().replace("\n", " ")
        if len(n2) > 30:
            n2 = n2[:27] + "..."
        lines.append(f"{t:<10} | {n2:<30} | {p:+.2f}%")
    return f"{title}\n```\n" + "\n".join(lines) + "\n```"


def _section(title: str, rows: list[str]) -> str:
    header = "지수               |         종가 |      변동 |    변동%"
    sep = "-" * len(header)
    body = "\n".join([header, sep, *rows])
    return f"{title}\n```\n{body}\n```"


def _read_constituents_csv(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    df = pd.read_csv(path)
    # Expect: ticker,name,(optional)sector
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
    tables = pd.read_html(html)

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

    # pick a name-ish column
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
    # Prefer blog repo pinned list if you later add it; fallback to Wikipedia.
    df = _read_constituents_csv(BLOG_CONSTITUENTS / "us_ndx.csv")
    if df is not None:
        return df
    df = _wiki_table_first("https://en.wikipedia.org/wiki/Nasdaq-100")
    return df.head(110)


def _get_universe_cn_csi300() -> pd.DataFrame:
    df = _read_constituents_csv(BLOG_CONSTITUENTS / "cn_csi300.csv")
    if df is not None:
        return df
    # Fallback: small representative list (avoids huge scrape).
    return pd.DataFrame({
        "ticker": ["600519.SS", "601398.SS", "600036.SS", "600276.SS", "300750.SZ", "000333.SZ", "000858.SZ", "601318.SS", "600887.SS", "601888.SS"],
        "name": ["Kweichow Moutai", "ICBC", "CMB", "Hengrui", "CATL", "Midea", "Wuliangye", "Ping An", "Ili", "China Tourism"],
    })


def _get_universe_hk_hsi() -> pd.DataFrame:
    df = _read_constituents_csv(BLOG_CONSTITUENTS / "hk_hsi.csv")
    if df is not None:
        return df
    # Wikipedia sometimes contains SEHK:xxxx. Normalize to 4-digit .HK
    df = _wiki_table_first("https://en.wikipedia.org/wiki/Hang_Seng_Index")
    dig = df["ticker"].str.extract(r"(\d+)", expand=False).fillna("")
    df["ticker"] = dig.apply(lambda x: x.zfill(4) if x else x)
    df = df[df["ticker"].str.len() > 0]
    df["ticker"] = df["ticker"] + ".HK"
    return df.head(60)


def _pct_changes_for_universe(df: pd.DataFrame, as_of: str | None) -> pd.DataFrame:
    """Return df with pct column for last available day <= as_of.

    Uses yfinance in batches; if rate-limited, returns empty.
    """
    tickers = df["ticker"].astype(str).tolist()

    # de-dup
    seen = set()
    tickers = [t for t in tickers if not (t in seen or seen.add(t))]

    end = pd.to_datetime(as_of) + pd.Timedelta(days=1) if as_of else None
    start = (end - pd.Timedelta(days=21)) if end is not None else None

    out = []
    batch_size = 40

    for i0 in range(0, len(tickers), batch_size):
        batch = tickers[i0 : i0 + batch_size]
        try:
            data = yf.download(
                tickers=batch,
                start=None if start is None else start.strftime("%Y-%m-%d"),
                end=None if end is None else end.strftime("%Y-%m-%d"),
                period="14d" if end is None else None,
                interval="1d",
                group_by="ticker",
                auto_adjust=False,
                threads=False,
                progress=False,
            )
        except Exception:
            return pd.DataFrame()

        for t in batch:
            try:
                if isinstance(data.columns, pd.MultiIndex):
                    if (t, "Close") not in data.columns:
                        continue
                    s = data[(t, "Close")].dropna()
                else:
                    s = data["Close"].dropna()

                if len(s) < 2:
                    continue

                s.index = pd.to_datetime(s.index)
                # pick last day
                last = float(s.iloc[-1])
                prev = float(s.iloc[-2])
                if prev <= 0:
                    continue
                pct = (last / prev - 1.0) * 100.0
                out.append((t, pct))
            except Exception:
                continue

        time.sleep(0.8)

    if not out:
        return pd.DataFrame()

    pct_df = pd.DataFrame(out, columns=["ticker", "pct"]).drop_duplicates("ticker")
    merged = df.merge(pct_df, on="ticker", how="left")
    return merged


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD (optional). If omitted, uses latest available.")
    args = ap.parse_args(list(argv) if argv is not None else None)

    as_of = args.date

    # Tickers: keep it small.
    # Map includes optional Stooq symbol for fallback.
    us = {
        "S&P 500": {"yf": "^GSPC", "stooq": "spx"},
        "NASDAQ 100": {"yf": "^NDX", "stooq": "ndx"},
    }
    cn = {
        "SSE": {"yf": "000001.SS", "stooq": None},
        "CSI 300": {"yf": "000300.SS", "stooq": None},
    }
    hk = {
        "Hang Seng": {"yf": "^HSI", "stooq": "hsi"},
    }

    # Movers universes (kept moderate for rate-limit resilience)
    uni_us = _get_universe_us_ndx()
    uni_cn = _get_universe_cn_csi300()
    uni_hk = _get_universe_hk_hsi()

    sections = []
    failures = []
    report_date: dt.date | None = None

    cache = _load_cache()

    for title, mp in [("🇺🇸 미국 (전일 종가 기준)", us), ("🇨🇳 중국 (직전 거래일 종가 기준)", cn), ("🇭🇰 홍콩 (직전 거래일 종가 기준)", hk)]:
        rows = []
        for name, spec in mp.items():
            yf_tkr = spec["yf"]
            stooq_sym = spec.get("stooq")

            r = _last_two_closes(yf_tkr, stooq_symbol=stooq_sym, as_of=as_of)
            if r is None:
                rows.append(_fmt_row(name, None, None, None))
                failures.append(yf_tkr)
                continue

            d, close, prev = r
            chg = close - prev
            pct = (close / prev - 1.0) * 100.0
            rows.append(_fmt_row(name, close, chg, pct))

            # update cache
            cache[yf_tkr] = {"date": d.strftime("%Y-%m-%d"), "close": close, "prev": prev}

            if report_date is None:
                report_date = d.date()

        sections.append(_section(title, rows))

    # Movers
    movers_blocks = []
    def top10(df_uni: pd.DataFrame, label: str) -> list[tuple[str, str, float]]:
        dfp = _pct_changes_for_universe(df_uni, as_of=as_of)
        if dfp.empty or "pct" not in dfp.columns:
            return []
        dfp = dfp.dropna(subset=["pct"]).copy()
        if dfp.empty:
            return []
        dfp["abs"] = dfp["pct"].abs()
        dfp = dfp.sort_values("abs", ascending=False).head(10)
        return [(r["ticker"], r.get("name", r["ticker"]), float(r["pct"])) for _, r in dfp.iterrows()]

    movers_blocks.append(_movers_table("🇺🇸 미국 Top movers (NDX universe, |move%| Top 10)", top10(uni_us, "US")))
    movers_blocks.append(_movers_table("🇨🇳 중국 Top movers (CSI300 universe, |move%| Top 10)", top10(uni_cn, "CN")))
    movers_blocks.append(_movers_table("🇭🇰 홍콩 Top movers (HSI universe, |move%| Top 10)", top10(uni_hk, "HK")))

    _save_cache(cache)

    date_line = f"기준일(데이터 최신일): {report_date.isoformat()}" if report_date else "기준일: 조회 실패"

    comments = [
        "코멘트:",
        "- 히트맵/종목 단위는 오늘은 스킵(무료 소스 제한 때문에 안정성 우선)",
        "- 지수 데이터가 '조회 실패'로 나오면, 보통 무료 엔드포인트(야후) 일시 제한/네트워크 이슈",
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
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
