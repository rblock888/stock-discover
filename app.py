"""Stock Discovery Tool — Streamlit Web App."""

import streamlit as st
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

import config
import fundamentals
import momentum
import catalysts
import insiders
import reddit_sentiment
import scorer
import universe_builder

st.set_page_config(page_title="Stock Discovery", page_icon="📊", layout="wide")

st.title("Stock Discovery Tool")
st.caption("Auto-discovers and scores stocks for multi-signal rerating potential")

# --- Sidebar config ---
with st.sidebar:
    st.header("Settings")
    top_n = st.slider("Show top N results", 5, 50, config.TOP_N)
    skip_filter = st.checkbox("Skip universe filters", value=False)
    st.divider()

    st.subheader("Weights")
    w_fund = st.slider("Fundamentals", 0, 100, 30)
    w_mom = st.slider("Momentum", 0, 100, 25)
    w_cat = st.slider("Catalyst", 0, 100, 20)
    w_ins = st.slider("Insider", 0, 100, 15)
    w_sent = st.slider("Sentiment", 0, 100, 10)

    total_w = w_fund + w_mom + w_cat + w_ins + w_sent
    if total_w > 0:
        config.WEIGHTS = {
            "fundamentals": w_fund / total_w,
            "momentum": w_mom / total_w,
            "catalyst": w_cat / total_w,
            "insider": w_ins / total_w,
            "sentiment": w_sent / total_w,
        }
    st.caption(f"Normalized to {total_w} → 100%")

    st.divider()
    st.subheader("Filters")
    config.MIN_PRICE = st.number_input("Min price ($)", value=0.50, step=0.25)
    config.MAX_PRICE = st.number_input("Max price ($)", value=50.0, step=5.0)
    config.MIN_AVG_VOLUME = st.number_input("Min avg volume", value=100_000, step=50_000)

    st.divider()
    st.subheader("Discovery Sources")
    use_yahoo = st.checkbox("Yahoo Finance screeners", value=True)
    use_finviz = st.checkbox("Finviz screener", value=True)
    use_reddit = st.checkbox("Reddit trending", value=True)
    use_sec = st.checkbox("SEC insider buys", value=True)
    use_rss = st.checkbox("RSS feeds (news/filings)", value=True)

# --- Mode selection ---
tab_auto, tab_manual = st.tabs(["🔍 Auto-Discovery", "📝 Manual Tickers"])

with tab_manual:
    ticker_input = st.text_area(
        "Enter tickers (comma or space separated)",
        value="LWLG, ASTS, RKLB, LUNR, IONQ, RGTI, SOUN, BBAI, HIMS, SOFI",
        height=68,
    )
    run_manual = st.button("Run Manual Scan", type="primary", use_container_width=True)

with tab_auto:
    st.markdown("""
    Auto-discovery pulls candidates from multiple sources:
    - **Yahoo Finance** — daily gainers, most active, small-cap movers
    - **Finviz** — screened by fundamentals (revenue growth, volume, market cap)
    - **Reddit** — trending tickers across finance subreddits
    - **SEC EDGAR** — recent insider purchase filings
    - **RSS feeds** — PR Newswire, GlobeNewsWire, SEC filings

    Tickers found in **multiple sources** are prioritized.
    """)
    run_auto = st.button("🚀 Run Auto-Discovery", type="primary", use_container_width=True)


def parse_tickers(text: str) -> list:
    tickers = []
    for part in text.replace(",", " ").replace("\n", " ").split():
        t = part.strip().upper()
        if t and t.isalpha():
            tickers.append(t)
    return list(dict.fromkeys(tickers))


def filter_ticker(ticker: str) -> tuple:
    import yfinance as yf
    try:
        stock = yf.Ticker(ticker)
        info = stock.info or {}
        price = info.get("currentPrice") or info.get("regularMarketPrice") or 0
        avg_vol = info.get("averageVolume") or 0
        mcap = info.get("marketCap") or 0

        if price < config.MIN_PRICE or price > config.MAX_PRICE:
            return ticker, False, f"Price ${price:.2f}"
        if avg_vol < config.MIN_AVG_VOLUME:
            return ticker, False, f"Volume {avg_vol:,.0f}"
        if mcap < config.MIN_MARKET_CAP:
            return ticker, False, f"MCap ${mcap/1e6:.0f}M"
        return ticker, True, "OK"
    except Exception:
        return ticker, False, "Error"


def score_single(ticker: str) -> tuple:
    bucket_scores = {
        "fundamentals": fundamentals.score(ticker),
        "momentum": momentum.score(ticker),
        "catalyst": catalysts.score(ticker),
        "insider": insiders.score(ticker),
        "sentiment": reddit_sentiment.score(ticker),
    }
    result = scorer.composite_score(bucket_scores)
    return ticker, result


def run_scoring(tickers: list, skip_filter: bool = False):
    """Filter and score a list of tickers, display results."""
    if not tickers:
        st.warning("No tickers to score.")
        return

    # --- Filter phase ---
    if not skip_filter:
        with st.status(f"Filtering {len(tickers)} tickers...", expanded=False) as status:
            filtered = []
            removed = []
            with ThreadPoolExecutor(max_workers=5) as pool:
                futures = {pool.submit(filter_ticker, t): t for t in tickers}
                for future in as_completed(futures):
                    t, passed, reason = future.result()
                    if passed:
                        filtered.append(t)
                    else:
                        removed.append(f"{t} ({reason})")
            if removed:
                st.write(f"Removed: {', '.join(removed[:20])}")
            status.update(label=f"{len(filtered)}/{len(tickers)} passed filters", state="complete")
        tickers = filtered

    if not tickers:
        st.warning("No tickers passed filters.")
        return

    # --- Scoring phase ---
    results = {}
    progress = st.progress(0, text="Scoring tickers...")
    done = 0

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(score_single, t): t for t in tickers}
        for future in as_completed(futures):
            ticker, result = future.result()
            results[ticker] = result
            done += 1
            progress.progress(done / len(tickers), text=f"Scored {done}/{len(tickers)}: {ticker}")

    progress.empty()

    # --- Results ---
    ranked = scorer.rank_results(results)

    table_data = []
    for ticker, result in ranked[:top_n]:
        bd = result["breakdown"]
        table_data.append({
            "Ticker": ticker,
            "Score": result["composite"],
            "Fundamentals": bd["fundamentals"]["raw"],
            "Momentum": bd["momentum"]["raw"],
            "Catalyst": bd["catalyst"]["raw"],
            "Insider": bd["insider"]["raw"],
            "Sentiment": bd["sentiment"]["raw"],
            "Signals ≥60": result["signals_above_60"],
            "Alert": "🚨" if result["multi_signal_alert"] else "",
        })

    df = pd.DataFrame(table_data)

    alerts = [r for r in table_data if r["Alert"]]
    if alerts:
        st.success(f"🚨 **{len(alerts)} multi-signal alert(s):** {', '.join(r['Ticker'] for r in alerts)}")

    st.subheader(f"Top {min(top_n, len(ranked))} Stocks")

    def color_score(val):
        if isinstance(val, (int, float)):
            if val >= 75:
                return "background-color: #1a7a1a; color: white"
            elif val >= 60:
                return "background-color: #2d8a2d; color: white"
            elif val >= 40:
                return "background-color: #b8860b; color: white"
            else:
                return "background-color: #8b0000; color: white"
        return ""

    score_cols = ["Score", "Fundamentals", "Momentum", "Catalyst", "Insider", "Sentiment"]
    styled = df.style.applymap(color_score, subset=score_cols).format(
        {col: "{:.1f}" for col in score_cols}
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)

    # Detailed cards
    st.subheader("Detailed Breakdown")
    for ticker, result in ranked[:top_n]:
        bd = result["breakdown"]
        alert_text = " 🚨 MULTI-SIGNAL ALERT" if result["multi_signal_alert"] else ""
        with st.expander(f"**{ticker}** — {result['composite']}/100 ({result['signals_above_60']}/5 signals){alert_text}"):
            cols = st.columns(5)
            for i, (bucket, data) in enumerate(bd.items()):
                with cols[i]:
                    st.metric(
                        label=bucket.title(),
                        value=f"{data['raw']:.0f}",
                        delta=f"x{data['weight']:.0f}%",
                    )
                    if data.get("components"):
                        for k, v in data["components"].items():
                            st.caption(f"**{k}:** {v}")


# --- Execute based on mode ---
if run_auto:
    with st.status("🔍 Discovering tickers from multiple sources...", expanded=True) as status:
        log_container = st.empty()
        logs = []

        def log_callback(msg):
            logs.append(msg)
            log_container.text("\n".join(logs))

        universe = universe_builder.build_universe(
            use_yahoo=use_yahoo,
            use_finviz=use_finviz,
            use_reddit=use_reddit,
            use_sec=use_sec,
            use_rss=use_rss,
            callback=log_callback,
        )

        tickers = universe["tickers"]
        source_counts = universe["source_counts"]

        # Show source breakdown
        multi_source = [t for t, c in source_counts.items() if c >= 2]
        log_callback(f"\n  Total unique tickers: {universe['total']}")
        if multi_source:
            log_callback(f"  Multi-source tickers: {', '.join(multi_source[:20])}")

        status.update(
            label=f"Found {universe['total']} tickers from {len(universe['sources'])} sources",
            state="complete",
        )

    if tickers:
        st.info(f"Discovered **{len(tickers)}** tickers. Scoring top candidates...")
        run_scoring(tickers, skip_filter=skip_filter)
    else:
        st.warning("No tickers discovered. Try enabling more sources.")

if run_manual:
    tickers = parse_tickers(ticker_input)
    if not tickers:
        st.error("No valid tickers entered.")
    else:
        run_scoring(tickers, skip_filter=skip_filter)
