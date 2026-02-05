# market-daily-snapshot

Daily market snapshot & news crawler for personal automation and note-taking.

## Features

- **Market Indices**: S&P 500, NASDAQ 100, Hang Seng 실시간 지수
- **Top Movers**: 상승/하락 Top 10 종목
- **Global News**: BlackQuant 뉴스룸 크롤링
- **Markdown Export**: Obsidian/GitHub wiki 호환 `[[backlink]]` 지원

## Scripts

| Script | Description | Data Source |
|--------|-------------|-------------|
| `daily_market_prices.py` | 지수 + 상승/하락 Top 10 | Stooq, Alpha Vantage |
| `news_crawler.py` | 글로벌 뉴스 크롤링 | BlackQuant |

## Installation

```bash
# 기본 의존성
pip install -r requirements.txt

# 뉴스 크롤러용 (Playwright)
pip install playwright
playwright install chromium
```

## Usage

### Market Snapshot

```bash
# 전체 실행 (지수 + movers, ~5분 소요)
python3 daily_market_prices.py

# 지수만 빠르게
python3 daily_market_prices.py --skip-movers

# 마크다운으로 저장
python3 daily_market_prices.py --markdown daily/2026-02-06.md
```

### News Crawler

```bash
# 기본 (10개)
python3 news_crawler.py

# 중요 뉴스만
python3 news_crawler.py --important --limit 20

# 마크다운으로 저장
python3 news_crawler.py --markdown news/2026-02-06.md

# JSON 저장
python3 news_crawler.py -o news.json
```

## Output Formats

### Console (기본)

```
📰 BlackQuant 글로벌 뉴스 요약
수집 시간: 2026-02-06 01:05

[1] 🔴 Alphabet 2026 spending forecast soars...
    📍 Yahoo Finance · 11분 전 📈
    📝 Alphabet (GOOGL, GOOG) stock fell...
```

### Markdown (--markdown)

Obsidian/GitHub wiki 호환 형식으로 저장됩니다:

```markdown
# Daily Market Snapshot
date: 2026-02-06

## US Indices
| Index | Close | Change |
|-------|-------|--------|
| [[S&P 500]] | 6,785.20 | -1.42% |

## Top Gainers
- [[AMGN]] +8.15% - Amgen
- [[CHTR]] +5.38% - Charter Communications

## Related
- [[2026-02-05|어제 시황]]
- [[AMZN|Amazon 관련 뉴스]]
```

### Telegram (--telegram)

```
📰 글로벌 뉴스 (01:05)

🔴↑ Alphabet 2026 spending forecast... [GOOGL.US]
🟡↓ Layoff Announcements Surge... [AMZN.US]
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ALPHA_VANTAGE_API_KEY` | Alpha Vantage API 키 | 내장 키 사용 |

## Notes

- Alpha Vantage 무료 tier: 분당 5회 제한 (movers 조회 ~5분 소요)
- Stooq: 중국 지수 미지원
- BlackQuant 뉴스: JavaScript 렌더링 필요 (Playwright 사용)

## File Structure

```
market-daily-snapshot/
├── daily_market_prices.py   # 시장 지수 + movers
├── news_crawler.py          # 뉴스 크롤러
├── requirements.txt         # 의존성
├── daily/                   # 일별 마켓 스냅샷 (markdown)
│   └── 2026-02-06.md
└── news/                    # 일별 뉴스 (markdown)
    └── 2026-02-06.md
```

## License

MIT
