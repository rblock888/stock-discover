# Stock Discovery Tool Idea

Build a stock discovery tool that looks for the kind of setup that can produce a big rerating, not just a cheap stock. The core idea is to rank stocks by a mix of fundamentals, price action, catalysts, dilution risk, insider activity, and social attention.

## Goal

Find stocks that have the ingredients for a major move:
- Improving business fundamentals.
- Strong relative strength and volume.
- A believable catalyst.
- Low dilution or financing risk.
- Insider buying or ownership support.
- Growing attention on Reddit and other social channels.

The tool should not try to predict exact winners. It should surface a small watchlist of names that deserve deeper review.

## What happened with LWLG

LWLG is a good example of why this matters. It fell to about $0.89 in April 2025 and later reached $10.60 by April 10, 2026, showing the kind of rerating the tool should try to identify earlier.

## Main scoring buckets

Use a weighted score instead of a binary screener:

- Fundamentals: 30%
- Momentum / relative strength: 25%
- Catalyst quality and timing: 20%
- Insider activity and capital structure: 15%
- Reddit / social sentiment: 10%

This makes the output explainable and prevents the tool from relying on one noisy signal.

## Data to pull

### Fundamentals
- Revenue growth.
- Revenue acceleration.
- Gross margin trend.
- Cash balance and cash runway.
- Debt.
- Shares outstanding.
- Dilution history.

### Market behavior
- Price trend.
- 52-week highs.
- Relative strength versus the market.
- Volume expansion.
- Breakouts above moving averages.

### Catalysts
- Earnings dates.
- Guidance changes.
- Product launches.
- Regulatory events.
- Contract wins.
- Major filings or press releases.

### Insider and structure
- Form 4 insider buys and sells.
- Insider ownership.
- Float size.
- Reverse split history.
- Warrants, convertibles, and other dilution risk.

### Reddit and sentiment
- Mention count over time.
- Sentiment score.
- Mention acceleration.
- Unique subreddits discussing the ticker.
- After-hours mention spikes.

## How Reddit should be used

Reddit should be a sentiment and attention layer, not the main signal. It is most useful when a stock already has improving fundamentals or a catalyst, and Reddit helps show that the market is starting to notice.

Good signal = rising mentions + positive tone + real price/volume confirmation.
Bad signal = hype without fundamentals or repeated spam in one community.

## Suggested pipeline

1. Build a stock universe.
2. Filter out illiquid or obviously low-quality names.
3. Pull financial data and filing data.
4. Parse insider transactions and dilution signals.
5. Compute technical momentum metrics.
6. Pull Reddit data and score sentiment.
7. Combine everything into one weighted score.
8. Rank the names and show the reasons.
9. Alert only when multiple signals align.

## Practical filters

Start with filters like:
- Market cap within a chosen range.
- Enough average daily volume.
- Revenue growth above a threshold.
- No severe dilution red flags.
- Recent or upcoming catalyst.
- Positive relative strength.
- Improving Reddit attention.

## Output format

For each stock, the tool should show:
- Ticker.
- Total score.
- Fundamental score.
- Momentum score.
- Catalyst score.
- Insider score.
- Reddit sentiment score.
- Short explanation of why it ranked high.

## Important warning

The tool should not chase low-priced stocks just because they are cheap. Many low-priced names are cheap because of weak business quality, dilution, or weak investor demand. The best approach is to find stocks where business improvement, market attention, and catalyst timing are all moving in the same direction.

## First version recommendation

For v1, keep it simple:
- Use fundamentals, technicals, insider buying, and Reddit sentiment.
- Ignore overly complex AI predictions at first.
- Store daily snapshots so you can detect change over time.
- Add alerts only for names that improve across several buckets at once.

The best tool is a ranked watchlist generator, not a magic stock picker.
