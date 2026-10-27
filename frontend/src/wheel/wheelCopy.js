/**
 * Plain-language copy for the Wheel tab honesty notes.
 *
 * Pure functions, no imports, no JSX, so they can be unit tested with
 * plain node. Every string here is written for a novice: short sentences,
 * no jargon, and every line says what it means for the person's money.
 */

export const EV_NOTE_STYLE = "evNote";

/**
 * The honesty note shown on every put candidate card that shows the
 * expected value number, in both modes. The number is the average gain
 * or loss if the trade were run many times. It assumes the stock drops
 * 10% and the seller ends up owning the shares, and it does not count
 * rolling the trade to avoid that, so it reads worse than it may turn
 * out. A negative number is not a prediction of a loss, and a positive
 * number is not a promise of profit. The rank is relative: a trade can
 * rank above worse trades while still showing a negative number.
 */
export function evNote(mode, evPerContract) {
  const assumption =
    "This number assumes the stock drops 10% and you end up owning it. " +
    "It does not count rolling the trade to avoid that, so it looks worse than it may turn out.";
  const nextStep =
    mode === "harvest"
      ? " In this mode the goal is to never end up owning the shares, so the plan is to roll the trade before that happens."
      : " If you do end up owning the shares, the next step is selling covered calls against them.";
  if (evPerContract != null && evPerContract < 0) {
    return (
      "A negative number means that, on this math, what you could lose " +
      "outweighs what you collect. It still ranks above worse trades, but " +
      "it is not a promise of profit. " +
      assumption +
      nextStep
    );
  }
  return (
    "This number is the average gain or loss if you ran this trade many " +
    "times, for one trade covering 100 shares. A positive number is not a " +
    "promise of profit. " +
    assumption +
    nextStep
  );
}

/**
 * The thin-scan explanation for harvest mode, shown when a scan returns
 * zero or only a few candidates. Harvest mode skips any stock it does
 * not have enough history on, so early scans can come back thin. That
 * is the filter working, not a bug.
 */
export function harvestThinScanNote(count) {
  if (!count) {
    return (
      "No names passed the filters. Harvest mode only keeps stocks that are " +
      "rising, with option prices high for that stock, no earnings coming up, " +
      "and a low chance of ending up owning the shares. It also skips any " +
      "stock it does not have enough history on, so early scans may come back " +
      "with few or no names. That is the filter working, not a bug."
    );
  }
  return (
    "Only a few names passed the filters. Harvest mode skips any stock it " +
    "does not have enough history on, so early scans may come back with few " +
    "names. That is the filter working, not a bug."
  );
}

/** True when a harvest scan is thin enough to deserve the explanation. */
export function isThinHarvestScan(mode, candidateCount) {
  return mode === "harvest" && (candidateCount || 0) <= 3;
}

/**
 * Plain-words version of a scanner exclusion reason code. Unknown codes
 * are passed through unchanged so nothing is hidden.
 */
const PLAIN_REASONS = {
  earnings_in_window: "earnings coming up before the option ends",
  below_ma200: "stock below its 200-day average, or trend unknown",
  iv_too_low: "option prices too low, or not enough price history",
  no_low_delta_tier: "no low-risk put available",
  no_30delta_tier: "no standard put available",
  spread_too_wide: "gap between buy and sell price too wide",
  insufficient_liquidity: "not enough trading in this option",
  no_options_data: "no option data found",
  incomplete_tier_data: "option data incomplete",
  no_call_tier: "no call available",
  no_executable_bid: "no bid, so no sale price (last trade not used)",
};

export function plainExclusionReason(reason) {
  if (!reason) return "no reason given";
  const key = String(reason).split(":")[0].trim();
  if (PLAIN_REASONS[key]) return PLAIN_REASONS[key];
  if (key === "data_error" || key === "exception") return "could not read the data";
  return String(reason);
}

/**
 * Group excluded candidates by plain reason, most common first.
 * Returns [{ label, count }].
 */
export function exclusionSummary(excluded) {
  const counts = new Map();
  for (const e of excluded || []) {
    const label = plainExclusionReason(e && e.reason);
    counts.set(label, (counts.get(label) || 0) + 1);
  }
  return [...counts.entries()]
    .map(([label, count]) => ({ label, count }))
    .sort((a, b) => b.count - a.count);
}
