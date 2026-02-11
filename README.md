# Market Daily Snapshot

Daily market snapshot + news crawler for personal automation and note-taking.

- Generates **indices + top movers** in Markdown (Obsidian-style `[[wikilink]]` compatible)
- Crawls global news (BlackQuant) and exports Markdown/JSON

## Quickstart

```bash
pip install -r requirements.txt

# 시장 스냅샷(지수 + movers) → 마크다운 저장
python3 daily_market_prices.py --markdown daily/$(date +%Y-%m-%d).md

# 뉴스(중요 뉴스) → 마크다운 저장
python3 news_crawler.py --important --limit 20 --markdown news/$(date +%Y-%m-%d).md
```

## Features

- **Market Indices**: S&P 500, NASDAQ 100, Hang Seng 실시간 지수
- **Top Movers**: 상승/하락 Top 10 종목
- **Global News**: BlackQuant 뉴스룸 크롤링
- **Markdown Export**: Obsidian/GitHub wiki 호환 `[[backlink]]` 지원

## Scripts

| Script | Description | Data Source |
|--------|-------------|-------------|
| `daily_market_prices.py` | 지수 + 상승/하락 Top 10 | Multi-source fallback (아래 참조) |
| `news_crawler.py` | 글로벌 뉴스 크롤링 | BlackQuant |

### Data Source Fallback Chain

`daily_market_prices.py`는 다음 순서로 데이터를 조회합니다:

```
1. Cache (최근 2일 이내) → 가장 빠름
2. Stooq Daily CSV → 무료, 속도 제한 있음
3. Alpha Vantage (ETF 프록시) → SPY, QQQ, EWH
4. yfinance → 백업
5. Cache (오래된 데이터) → 최후의 수단
```

**ETF 프록시 매핑:**
| Index | ETF Proxy | Reason |
|-------|-----------|--------|
| S&P 500 (^GSPC) | SPY | Alpha Vantage는 지수 직접 조회 불가 |
| NASDAQ 100 (^NDX) | QQQ | ETF로 대체 |
| Hang Seng (^HSI) | EWH | iShares MSCI Hong Kong ETF |

## Installation

```bash
# 기본 의존성
pip install -r requirements.txt

# 뉴스 크롤러용 (Playwright)
pip install playwright
playwright install chromium
```

> Tip: movers 조회는 Alpha Vantage 무료 제한(분당 5회) 때문에 3~5분 걸릴 수 있음.

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
# Daily Market Snapshot - 2026-02-06

## 🇺🇸 US Indices
| Index | Close | Change | % | Source |
|-------|------:|-------:|--:|--------|
| [[S&P 500]] | 6,819.57 | -63.15 | -0.92% | stooq |
| [[NASDAQ 100]] | 24,690.87 | -200.38 | -0.81% | alphavantage(QQQ) |

## 📈 Top Gainers
- [[AMGN]] **+8.15%** - Amgen
- [[CHTR]] **+5.38%** - Charter Communications

## Related
- [[Daily Market Snapshot - 2026-02-05|어제 시황]]
- [[Global News - 2026-02-06|오늘 뉴스]]
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

## Claude Code 연동

생성된 마크다운 파일을 Claude Code(클로드봇)가 읽고 후처리할 수 있습니다.

### 사용 예시

```bash
# 1. 스크립트로 마크다운 생성
python3 news_crawler.py --markdown news/2026-02-06.md

# 2. Claude Code에게 후처리 요청
# "news/2026-02-06.md 읽고 한글로 요약해줘"
# "daily/2026-02-06.md에 시장 코멘트 추가해줘"
```

### Claude Code가 할 수 있는 작업

| 작업 | 설명 | 예시 프롬프트 |
|------|------|--------------|
| 요약 다듬기 | 뉴스 요약을 더 간결하게 | "요약을 2줄로 줄여줘" |
| 한글 번역 | 영문 뉴스 한글화 | "제목들 한글로 번역해줘" |
| 코멘트 추가 | 시황 분석 코멘트 | "오늘 시장 분석 코멘트 추가해줘" |
| 백링크 추가 | 관련 노트 연결 | "관련 종목 노트 링크 추가해줘" |
| 포맷 수정 | 마크다운 구조 변경 | "테이블을 리스트로 바꿔줘" |

### 자동화 워크플로우

```bash
# 매일 자동 실행 (cron 등)
python3 daily_market_prices.py --markdown daily/$(date +%Y-%m-%d).md
python3 news_crawler.py --important --limit 20 --markdown news/$(date +%Y-%m-%d).md

# Claude Code로 후처리
# → 파일 읽기 → 내용 다듬기 → 저장
```

## Notes

- **Multi-source fallback**: 하나의 소스가 실패해도 자동으로 다음 소스 시도
- **Alpha Vantage 무료 tier**: 분당 5회 제한 (movers 조회 ~5분 소요)
- **Stooq**: 간헐적 rate limit 발생 → Alpha Vantage로 자동 폴백
- **yfinance**: 백업용, rate limit 발생 시 폴백
- **Cache**: `~/Library/Caches/market-daily-prices/cache.json`에 저장
- **중국 지수**: Stooq 미지원, ETF 프록시 없음 → 캐시 데이터 사용
- **BlackQuant 뉴스**: JavaScript 렌더링 필요 (Playwright 사용)

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
