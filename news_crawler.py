#!/usr/bin/env python3
"""BlackQuant 뉴스룸 크롤러

Playwright를 사용하여 JavaScript 렌더링 후 뉴스를 크롤링합니다.

설치:
  pip install playwright
  playwright install chromium

사용:
  python3 news_crawler.py
  python3 news_crawler.py --limit 5
  python3 news_crawler.py --output news.json
  python3 news_crawler.py --important  # 중요 뉴스만
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime
from typing import TypedDict


class NewsItem(TypedDict):
    title: str
    summary: str
    source: str
    time: str
    importance: str
    sentiment: str
    tickers: list[str]


async def crawl_blackquant_news(
    limit: int = 10,
    headless: bool = True,
    important_only: bool = False
) -> list[NewsItem]:
    """BlackQuant 뉴스룸에서 뉴스를 크롤링합니다."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise SystemExit(
            "Playwright가 설치되지 않았습니다.\n"
            "설치: pip install playwright && playwright install chromium"
        )

    news_items: list[NewsItem] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
        page = await context.new_page()

        print("페이지 로딩 중...")
        await page.goto("https://blackquant.kr/newsroom", wait_until="networkidle")
        await page.wait_for_timeout(3000)

        # 중요 뉴스 필터 클릭 (선택적)
        if important_only:
            try:
                important_btn = await page.query_selector("button:has-text('중요')")
                if important_btn:
                    await important_btn.click()
                    await page.wait_for_timeout(1000)
                    print("중요 뉴스 필터 적용됨")
            except Exception:
                pass

        print("뉴스 목록 추출 중...")

        # 뉴스 카드 셀렉터 (분석된 구조 기반)
        news_cards = await page.query_selector_all(".group.p-4.rounded-xl.border")

        if not news_cards:
            # 대체 셀렉터 시도
            news_cards = await page.query_selector_all("[class*='group'][class*='p-4'][class*='rounded-xl']")

        print(f"  {len(news_cards)}개 뉴스 카드 발견")

        for card in news_cards[:limit]:
            try:
                # 제목 추출
                title_elem = await card.query_selector(".text-sm.mb-2.line-clamp-2")
                title = await title_elem.inner_text() if title_elem else ""
                title = title.strip()

                # 요약 추출
                summary_elem = await card.query_selector(".text-xs.text-muted-foreground.line-clamp-2.mb-3")
                summary = await summary_elem.inner_text() if summary_elem else ""
                summary = summary.strip()

                # 소스 및 시간 추출 (첫 번째 줄에 있음)
                source = ""
                time_str = ""
                first_line = await card.query_selector(".flex.items-center.gap-2.mb-2")
                if first_line:
                    first_text = await first_line.inner_text()
                    parts = first_text.split("·")
                    if len(parts) >= 2:
                        source = parts[0].strip()
                        time_str = parts[1].strip()
                    elif parts:
                        source = parts[0].strip()

                # 중요도 추출 (HIGH, MEDIUM, LOW)
                importance = ""
                importance_badge = await card.query_selector("[class*='bg-red-500'], [class*='bg-yellow-500'], [class*='bg-green-500']")
                if importance_badge:
                    importance = await importance_badge.inner_text()
                    importance = importance.strip()

                # 감정 추출 (긍정, 부정, 중립)
                sentiment = ""
                sentiment_badges = await card.query_selector_all(".flex.items-center.gap-2.flex-wrap span, .flex.items-center.gap-2.flex-wrap div")
                for badge in sentiment_badges:
                    text = await badge.inner_text()
                    if text.strip() in ["긍정", "부정", "중립"]:
                        sentiment = text.strip()
                        break

                # 관련 티커 추출
                tickers = []
                ticker_elems = await card.query_selector_all("[class*='change-positive'], [class*='change-negative'], [class*='change-neutral']")
                for ticker_elem in ticker_elems:
                    ticker_text = await ticker_elem.inner_text()
                    ticker_text = ticker_text.strip()
                    if ticker_text and "." in ticker_text:  # AMZN.US 형식
                        tickers.append(ticker_text)

                if title:
                    item: NewsItem = {
                        "title": title,
                        "summary": summary,
                        "source": source,
                        "time": time_str,
                        "importance": importance,
                        "sentiment": sentiment,
                        "tickers": tickers
                    }
                    news_items.append(item)

            except Exception as e:
                continue

        await browser.close()

    return news_items


def format_news_report(news_items: list[NewsItem]) -> str:
    """뉴스 리포트를 포맷팅합니다."""
    if not news_items:
        return "뉴스를 찾을 수 없습니다."

    lines = [
        "📰 BlackQuant 글로벌 뉴스 요약",
        f"수집 시간: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"총 {len(news_items)}건",
        "",
        "=" * 70,
        ""
    ]

    for i, item in enumerate(news_items, 1):
        # 중요도/감정 이모지
        imp_emoji = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(item["importance"], "⚪")
        sent_emoji = {"긍정": "📈", "부정": "📉", "중립": "➡️"}.get(item["sentiment"], "")

        lines.append(f"[{i}] {imp_emoji} {item['title']}")
        lines.append(f"    📍 {item['source']} · {item['time']} {sent_emoji}")

        if item['summary']:
            # 요약이 너무 길면 자르기
            summary = item['summary'][:150] + "..." if len(item['summary']) > 150 else item['summary']
            lines.append(f"    📝 {summary}")

        if item['tickers']:
            lines.append(f"    🏷️ {', '.join(item['tickers'])}")

        lines.append("")

    return "\n".join(lines)


def format_telegram(news_items: list[NewsItem]) -> str:
    """텔레그램용 간단한 포맷"""
    if not news_items:
        return "뉴스 없음"

    lines = [
        f"📰 글로벌 뉴스 ({datetime.now().strftime('%H:%M')})",
        ""
    ]

    for i, item in enumerate(news_items, 1):
        imp = {"HIGH": "🔴", "MEDIUM": "🟡"}.get(item["importance"], "")
        sent = {"긍정": "↑", "부정": "↓"}.get(item["sentiment"], "")

        ticker_str = f" [{item['tickers'][0]}]" if item['tickers'] else ""
        lines.append(f"{imp}{sent} {item['title'][:60]}{ticker_str}")

    return "\n".join(lines)


def format_markdown(news_items: list[NewsItem]) -> str:
    """Obsidian/GitHub wiki 호환 마크다운 포맷 (백링크 지원)"""
    if not news_items:
        return "# Global News\n\nNo news found."

    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - __import__('datetime').timedelta(days=1)).strftime("%Y-%m-%d")

    lines = [
        "---",
        f"date: {today}",
        "type: news",
        f"tags: [news, market, daily]",
        "---",
        "",
        f"# Global News - {today}",
        "",
        f"> 수집 시간: {datetime.now().strftime('%Y-%m-%d %H:%M')}  ",
        f"> 총 {len(news_items)}건",
        "",
        "## Headlines",
        "",
    ]

    # 티커별 그룹핑을 위한 딕셔너리
    ticker_news: dict[str, list[str]] = {}

    for i, item in enumerate(news_items, 1):
        imp_tag = {"HIGH": "🔴 HIGH", "MEDIUM": "🟡 MED", "LOW": "🟢 LOW"}.get(item["importance"], "")
        sent_tag = {"긍정": "📈", "부정": "📉", "중립": "➡️"}.get(item["sentiment"], "")

        # 티커를 백링크로 변환
        ticker_links = [f"[[{t.replace('.US', '').replace('.HK', '')}]]" for t in item["tickers"]]
        ticker_str = " ".join(ticker_links) if ticker_links else ""

        lines.append(f"### {i}. {item['title']}")
        lines.append("")
        lines.append(f"- **Source**: {item['source']} · {item['time']}")
        lines.append(f"- **Importance**: {imp_tag} {sent_tag}")
        if ticker_str:
            lines.append(f"- **Tickers**: {ticker_str}")
        lines.append("")
        if item['summary']:
            lines.append(f"> {item['summary']}")
            lines.append("")

        # 티커별 뉴스 수집
        for t in item["tickers"]:
            ticker_key = t.replace('.US', '').replace('.HK', '')
            if ticker_key not in ticker_news:
                ticker_news[ticker_key] = []
            ticker_news[ticker_key].append(item['title'][:50])

    # Related Links 섹션
    lines.append("---")
    lines.append("")
    lines.append("## Related")
    lines.append("")
    lines.append(f"- [[{yesterday}|어제 뉴스]]")
    lines.append(f"- [[Daily Market Snapshot - {today}|오늘 시황]]")

    if ticker_news:
        lines.append("")
        lines.append("### By Ticker")
        for ticker, titles in list(ticker_news.items())[:10]:
            lines.append(f"- [[{ticker}]]: {len(titles)}건")

    return "\n".join(lines)


async def main_async(args: argparse.Namespace) -> int:
    """비동기 메인 함수"""
    news_items = await crawl_blackquant_news(
        limit=args.limit,
        headless=not args.visible,
        important_only=args.important
    )

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(news_items, f, ensure_ascii=False, indent=2)
        print(f"\n결과가 {args.output}에 저장되었습니다.")

    if args.markdown:
        import os
        os.makedirs(os.path.dirname(args.markdown) or ".", exist_ok=True)
        md_content = format_markdown(news_items)
        with open(args.markdown, "w", encoding="utf-8") as f:
            f.write(md_content)
        print(f"\n마크다운이 {args.markdown}에 저장되었습니다.")

    if args.telegram:
        report = format_telegram(news_items)
    elif args.markdown:
        report = f"마크다운 저장 완료: {args.markdown}"
    else:
        report = format_news_report(news_items)

    print("\n" + report)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="BlackQuant 뉴스룸 크롤러")
    parser.add_argument("--limit", type=int, default=10, help="가져올 뉴스 개수 (기본: 10)")
    parser.add_argument("--output", "-o", type=str, help="JSON 출력 파일 경로")
    parser.add_argument("--markdown", "-m", type=str, help="마크다운 출력 파일 경로")
    parser.add_argument("--visible", action="store_true", help="브라우저 창 표시 (디버그용)")
    parser.add_argument("--important", action="store_true", help="중요 뉴스만 필터링")
    parser.add_argument("--telegram", action="store_true", help="텔레그램용 간단한 포맷")
    args = parser.parse_args()

    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
