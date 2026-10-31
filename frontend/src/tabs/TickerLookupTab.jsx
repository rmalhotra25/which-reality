import { useState } from 'react'
import { api } from '../api'

// Ticker Lookup tab: a query, not a trade. Type a ticker, get the same
// rule registry check the alert engine would run for that ticker, at
// the data timestamp shown. No alert is fired, no journal row is
// created, no notification is sent. A passing setup shows the rule
// result for that ticker at that time, not an instruction to trade.

const S = {
  root: { display: 'flex', flexDirection: 'column', gap: '16px' },
  banner: {
    background: '#131825', border: '1px solid #2d3748', borderRadius: '10px',
    padding: '12px 16px', fontSize: '13px', color: '#a0aec0', lineHeight: 1.5,
  },
  form: { display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' },
  input: {
    padding: '9px 12px', fontSize: '15px', fontWeight: 700, letterSpacing: '0.05em',
    background: '#0f1520', border: '1px solid #2d3748', borderRadius: '8px',
    color: '#e2e8f0', width: '160px', textTransform: 'uppercase',
  },
  button: {
    padding: '9px 18px', background: '#2b6cb0', color: '#fff', border: 'none',
    borderRadius: '8px', cursor: 'pointer', fontSize: '14px', fontWeight: 700,
  },
  check: { fontSize: '13px', color: '#a0aec0', display: 'flex', gap: '6px', alignItems: 'center' },
  error: {
    background: '#2d1515', border: '1px solid #742a2a', borderRadius: '10px',
    padding: '16px', color: '#fc8181', fontSize: '13px',
  },
  card: {
    background: '#131825', border: '1px solid #2d3748', borderRadius: '10px',
    padding: '16px',
  },
  sectionLabel: {
    fontSize: '11px', fontWeight: 700, letterSpacing: '0.08em',
    color: '#718096', textTransform: 'uppercase', marginBottom: '8px',
  },
  tickerBig: { fontSize: '20px', fontWeight: 800, color: '#e2e8f0' },
  priceBig: { fontSize: '26px', fontWeight: 800, color: '#e2e8f0' },
  meta: { fontSize: '12px', color: '#718096', marginTop: '4px' },
  grid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '12px' },
  stat: { display: 'flex', flexDirection: 'column', gap: '2px' },
  statLabel: { fontSize: '10px', color: '#4a5568', textTransform: 'uppercase', letterSpacing: '0.06em' },
  statValue: { fontSize: '15px', fontWeight: 700, color: '#e2e8f0' },
  statSub: { fontSize: '11px', color: '#718096' },
  pill: (bg, border, text) => ({
    display: 'inline-block', padding: '2px 9px', borderRadius: '20px', fontSize: '10px',
    fontWeight: 700, letterSpacing: '0.05em',
    background: bg, border: `1px solid ${border}`, color: text,
  }),
  table: { width: '100%', borderCollapse: 'collapse', fontSize: '12px' },
  th: {
    padding: '8px 10px', textAlign: 'left', color: '#4a5568', fontWeight: 600,
    borderBottom: '1px solid #1e2535', whiteSpace: 'nowrap',
    textTransform: 'uppercase', fontSize: '10px', letterSpacing: '0.06em',
  },
  td: { padding: '8px 10px', borderBottom: '1px solid #1a1f2e', color: '#a0aec0', verticalAlign: 'top' },
  condBox: {
    background: '#0f1520', border: '1px solid #1e2535', borderRadius: '6px',
    padding: '8px 10px', fontSize: '11px', color: '#718096', marginTop: '8px',
    fontFamily: 'monospace', lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
  },
  ruleBox: {
    background: '#0f1520', border: '1px solid #2b6cb0', borderRadius: '8px',
    padding: '12px 14px', fontSize: '13px', color: '#a0aec0', lineHeight: 1.6, marginTop: '8px',
  },
  verdictCard: (tone) => ({
    background: tone === 'buy' ? '#12261a' : tone === 'wait' ? '#16233a' : tone === 'avoid' ? '#2d1515' : '#1d1a12',
    border: tone === 'buy' ? '1px solid #276749' : tone === 'wait' ? '1px solid #2b6cb0' : tone === 'avoid' ? '1px solid #742a2a' : '1px solid #975a16',
    borderRadius: '12px', padding: '20px',
  }),
  verdictBig: (tone) => ({
    fontSize: '30px', fontWeight: 800, letterSpacing: '0.01em',
    color: tone === 'buy' ? '#68d391' : tone === 'wait' ? '#90cdf4' : tone === 'avoid' ? '#fc8181' : '#f6e05e', lineHeight: 1.2,
  }),
  verdictReason: { fontSize: '15px', color: '#e2e8f0', lineHeight: 1.5, marginTop: '8px' },
  verdictList: { fontSize: '13px', color: '#a0aec0', lineHeight: 1.7, margin: '10px 0 0', paddingLeft: '18px' },
  verdictNote: { fontSize: '13px', color: '#a0aec0', lineHeight: 1.5, marginTop: '12px' },
  optionRow: {
    display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
    gap: '12px', marginTop: '16px',
  },
  optionBox: {
    background: '#131825', border: '1px solid #2d3748', borderRadius: '10px', padding: '14px',
  },
  optionTitle: (tone) => ({
    fontSize: '17px', fontWeight: 800,
    color: tone === 'buy' ? '#68d391' : tone === 'sell' ? '#68d391' : '#a0aec0',
  }),
  optionLine: { fontSize: '13px', color: '#e2e8f0', lineHeight: 1.6, marginTop: '6px' },
  optionSub: { fontSize: '12px', color: '#718096', lineHeight: 1.5, marginTop: '6px' },
  details: {
    background: '#131825', border: '1px solid #2d3748', borderRadius: '10px', padding: '16px',
  },
  summary: { fontSize: '12px', fontWeight: 700, letterSpacing: '0.08em', color: '#a0aec0', textTransform: 'uppercase', cursor: 'pointer' },
  note: { fontSize: '12px', color: '#718096', lineHeight: 1.5 },
}

function val(v) {
  if (v === null || v === undefined) return 'unknown'
  if (typeof v === 'boolean') return v ? 'yes' : 'no'
  if (typeof v === 'number') return String(v)
  return String(v)
}

function ResultPill({ result, status }) {
  if (result === 'pass') return <span style={S.pill('#15301f', '#276749', '#68d391')}>PASS ({status})</span>
  if (result === 'suppressed') return <span style={S.pill('#3d2f10', '#975a16', '#f6e05e')}>SUPPRESSED ({status})</span>
  if (result === 'not_evaluated') return <span style={S.pill('#1a202c', '#4a5568', '#a0aec0')}>NOT EVALUATED ({status})</span>
  return <span style={S.pill('#2d1515', '#742a2a', '#fc8181')}>FAIL ({status})</span>
}

function ChainTable({ rows, side }) {
  if (!rows || rows.length === 0) return <div style={S.note}>No {side} rows.</div>
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={S.table}>
        <thead>
          <tr>
            <th>Strike</th><th>Expiry</th><th>DTE</th><th>Bid</th><th>Ask</th>
            <th>Mid</th><th>Price source</th><th>Delta</th><th>IV %</th><th>OI</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td>${val(r.strike)}</td><td>{val(r.expiry)}</td><td>{val(r.dte)}</td>
              <td>${val(r.bid)}</td><td>${val(r.ask)}</td><td>${val(r.mid)}</td>
              <td>{val(r.price_source)}</td><td>{r.delta != null ? Number(r.delta).toFixed(2) : 'unknown'}</td>
              <td>{val(r.iv_pct)}</td><td>{val(r.open_interest)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function TickerLookupTab() {
  const [ticker, setTicker] = useState('')
  const [explain, setExplain] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  async function runLookup(e) {
    e.preventDefault()
    const t = ticker.trim().toUpperCase()
    if (!t) return
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const data = await api.lookup.get(t, explain)
      setResult(data)
    } catch (err) {
      setError(err.message || 'Lookup failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={S.root}>
      <div style={S.banner}>
        Type a ticker, get a clear answer first: Buy Now, Wait for Entry, Avoid for Now, or Cannot Judge,
        plus Sell the Put or Don't Sell a Put, and Buy the Call or Don't Buy the Call. The long-term
        lane comes first: is this a strong company, and is it undervalued on a 3 to 5 year view?
        A timing Avoid for Now is not a verdict on the company, and the long-term lane never
        changes the put or call answer. Buy Now
        keeps the strict setup rule. Wait for Entry shows the trigger price, the invalidation,
        the drop and news context, and a dated fundamental snapshot when one exists, so you can
        judge a dip instead of only being told today is not a buy. The answer comes from the
        same rule registry check the alert engine runs, for one ticker, at the data timestamp
        shown, plus the latest company news and the next earnings date. No alert fires, no
        journal row is created, no notification is sent. The full rule check and the full
        option chain are below, closed by default, for anyone who wants the audit trail.
      </div>

      <form onSubmit={runLookup} style={S.form}>
        <input
          style={S.input}
          value={ticker}
          onChange={(e) => setTicker(e.target.value)}
          placeholder="TICKER"
          maxLength={12}
          aria-label="Ticker"
        />
        <button style={S.button} type="submit" disabled={loading}>
          {loading ? 'Looking up...' : 'Look up'}
        </button>
        <label style={S.check}>
          <input type="checkbox" checked={explain} onChange={(e) => setExplain(e.target.checked)} />
          Plain-language explanation (Claude, optional)
        </label>
      </form>

      {error && (
        <div style={S.error}>
          <strong>Lookup failed.</strong>
          <div style={{ marginTop: '6px' }}>{error}</div>
          <div style={{ marginTop: '6px', color: '#a0aec0' }}>
            Unknown ticker, no data, or no listed options returns a named reason, not a guessed result.
          </div>
        </div>
      )}

      {result && result.verdict && (
        <>
          {result.verdict.longterm && (
            <div style={S.card}>
              <div style={S.sectionLabel}>Long term, 3 to 5 years (separate from timing)</div>
              <div style={{ fontSize: '22px', fontWeight: 800, color: '#e2e8f0' }}>
                {result.verdict.longterm.label}
              </div>
              <div style={S.verdictReason}>{result.verdict.longterm.reason}</div>
              {result.verdict.longterm.bridge_line && (
                <div style={{ fontSize: '15px', fontWeight: 700, color: '#68d391', marginTop: '8px' }}>
                  {result.verdict.longterm.bridge_line}
                  {result.verdict.longterm.bridge_entry && (
                    <span style={{ fontWeight: 400, color: '#a0aec0' }}>
                      {' '}Pullback ${val(result.verdict.longterm.bridge_entry.pullback_price)}
                      {result.verdict.longterm.bridge_entry.breakout_price != null && (
                        <span> or a close above ${val(result.verdict.longterm.bridge_entry.breakout_price)}</span>
                      )}
                      {result.verdict.longterm.bridge_entry.buy_zone && (
                        <span> | Buy zone ${val(result.verdict.longterm.bridge_entry.buy_zone[0])} to ${val(result.verdict.longterm.bridge_entry.buy_zone[1])}</span>
                      )}
                      {result.verdict.longterm.bridge_entry.invalidation_price != null && (
                        <span> | Wrong if it closes below ${val(result.verdict.longterm.bridge_entry.invalidation_price)}</span>
                      )}
                    </span>
                  )}
                </div>
              )}
              {result.verdict.longterm.quality && result.verdict.longterm.quality.status === 'verified' && (
                <div style={{ ...S.note, marginTop: '8px' }}>
                  Quality, screener {val(result.verdict.longterm.quality.run_date)}: composite {val(result.verdict.longterm.quality.composite)} ({val(result.verdict.longterm.quality.label)}), revenue CAGR 3y {val(result.verdict.longterm.quality.rev_cagr_3y_pct)}%, FCF margin avg 3y {val(result.verdict.longterm.quality.fcf_margin_avg_3y_pct)}%, ROIC {val(result.verdict.longterm.quality.roic_pct)}%, operating margin {val(result.verdict.longterm.quality.operating_margin_pct)}%, EV/EBITDA {val(result.verdict.longterm.quality.ev_to_ebitda)}x.
                </div>
              )}
              {result.verdict.longterm.quality && result.verdict.longterm.quality.status !== 'verified' && (
                <div style={{ ...S.note, marginTop: '8px' }}>{val(result.verdict.longterm.quality.note)}</div>
              )}
              {result.verdict.longterm.dcf && (
                <>
                  <div style={{ ...S.grid, marginTop: '12px' }}>
                    <div style={S.stat}>
                      <span style={S.statLabel}>Bear fair value</span>
                      <span style={S.statValue}>${val(result.verdict.longterm.dcf.fair_value.bear)}</span>
                      <span style={S.statSub}>{val(result.verdict.longterm.dcf.upside_pct.bear)}% vs today</span>
                    </div>
                    <div style={S.stat}>
                      <span style={S.statLabel}>Base fair value</span>
                      <span style={S.statValue}>${val(result.verdict.longterm.dcf.fair_value.base)}</span>
                      <span style={S.statSub}>{val(result.verdict.longterm.dcf.upside_pct.base)}% vs today</span>
                    </div>
                    <div style={S.stat}>
                      <span style={S.statLabel}>Bull fair value</span>
                      <span style={S.statValue}>${val(result.verdict.longterm.dcf.fair_value.bull)}</span>
                      <span style={S.statSub}>{val(result.verdict.longterm.dcf.upside_pct.bull)}% vs today</span>
                    </div>
                    <div style={S.stat}>
                      <span style={S.statLabel}>Reverse DCF</span>
                      <span style={S.statValue}>{val(result.verdict.longterm.dcf.reverse_dcf_implied_growth_pct)}%</span>
                      <span style={S.statSub}>growth the market is already pricing in</span>
                    </div>
                  </div>
                  {result.verdict.longterm.wacc && (
                    <div style={{ ...S.note, marginTop: '8px' }}>
                      WACC {val(result.verdict.longterm.wacc.wacc_pct)}% (risk free {val(result.verdict.longterm.wacc.risk_free_pct)}%, source: {val(result.verdict.longterm.wacc.risk_free_source)}).
                      {result.verdict.longterm.dcf.exit_multiple_check && result.verdict.longterm.dcf.exit_multiple_check.fair_value != null && (
                        <span> Exit-multiple cross-check: ${val(result.verdict.longterm.dcf.exit_multiple_check.fair_value)} vs Gordon ${val(result.verdict.longterm.dcf.exit_multiple_check.gordon_fair_value)} ({val(result.verdict.longterm.dcf.exit_multiple_check.disagreement_pct)}%{result.verdict.longterm.dcf.exit_multiple_check.wide_disagreement ? ', wide disagreement, neither method is picked' : ''}).</span>
                      )}
                      {result.verdict.longterm.dcf.exit_multiple_check && result.verdict.longterm.dcf.exit_multiple_check.fair_value == null && (
                        <span> Exit-multiple cross-check unavailable: {val(result.verdict.longterm.dcf.exit_multiple_check.note)}</span>
                      )}
                    </div>
                  )}
                  {result.verdict.longterm.dcf.wacc_sensitivity && result.verdict.longterm.dcf.wacc_sensitivity.length > 0 && (
                    <div style={{ ...S.note, marginTop: '8px' }}>
                      WACC sensitivity (base fair value): {result.verdict.longterm.dcf.wacc_sensitivity.map((r, i) => (
                        <span key={i}>{i > 0 ? ' | ' : ''}{val(r.wacc_pct)}% WACC: ${val(r.base.price)}</span>
                      ))}
                    </div>
                  )}
                </>
              )}
              {result.verdict.longterm.notes && result.verdict.longterm.notes.map((n, i) => (
                <div key={i} style={{ ...S.note, marginTop: '6px' }}>{n}</div>
              ))}
              <div style={{ ...S.note, marginTop: '8px' }}>
                This lane does not change the put or call answer below. A strong, undervalued company can keep falling, so weekly options stay gated by timing, earnings, and SPY.
              </div>
            </div>
          )}

          <div style={S.verdictCard(result.verdict.stock.decision === 'buy' ? 'buy' : result.verdict.stock.decision === 'wait' ? 'wait' : result.verdict.stock.decision === 'avoid' ? 'avoid' : 'hold')}>
            <div style={S.verdictBig(result.verdict.stock.decision === 'buy' ? 'buy' : result.verdict.stock.decision === 'wait' ? 'wait' : result.verdict.stock.decision === 'avoid' ? 'avoid' : 'hold')}>
              {result.verdict.stock.decision === 'avoid' ? 'AVOID FOR NOW' : result.verdict.stock.label}
            </div>
            <div style={S.verdictReason}>{result.verdict.stock.reason}</div>
            <div style={{ fontSize: '15px', color: '#e2e8f0', marginTop: '6px' }}>
              {result.ticker} at ${val(result.price)}
              {result.verdict.stock.invalidation_price != null && (
                <span> | Wrong if it closes below ${val(result.verdict.stock.invalidation_price)}</span>
              )}
            </div>
            <ul style={S.verdictList}>
              {result.verdict.stock.reasons.map((r, i) => <li key={i}>{r}</li>)}
            </ul>
            <div style={S.verdictNote}>What would change this: {result.verdict.stock.what_would_change}</div>
            <div style={S.verdictNote}>{result.verdict.stock.positive_note}</div>

            <div style={S.optionRow}>
              <div style={S.optionBox}>
                <div style={S.optionTitle(result.verdict.put.decision === 'sell' ? 'sell' : 'hold')}>
                  {result.verdict.put.label}
                </div>
                <div style={S.optionLine}>{result.verdict.put.reason}</div>
                {result.verdict.put.decision === 'sell' && (
                  <>
                    <div style={S.optionSub}>
                      Strike ${val(result.verdict.put.strike)} | Expiry {val(result.verdict.put.expiry)} ({val(result.verdict.put.dte)} days) |
                      Premium ${val(result.verdict.put.premium_per_contract)} per contract (bid)
                    </div>
                    <div style={S.optionSub}>
                      Breakeven ${val(result.verdict.put.breakeven)} | You buy at ${val(result.verdict.put.assignment_price)} if assigned |
                      Most you can lose ${val(result.verdict.put.max_loss_per_contract)} per contract |
                      Cushion {val(result.verdict.put.cushion_pct)}%
                      {result.verdict.put.earnings_before_expiry != null && (
                        <span> | Earnings before expiry: {result.verdict.put.earnings_before_expiry ? 'yes' : 'no'}</span>
                      )}
                    </div>
                    <div style={S.optionSub}>{result.verdict.put.why}</div>
                  </>
                )}
              </div>
              <div style={S.optionBox}>
                <div style={S.optionTitle(result.verdict.call.decision === 'buy' ? 'buy' : 'hold')}>
                  {result.verdict.call.label}
                </div>
                <div style={S.optionLine}>{result.verdict.call.reason}</div>
                {result.verdict.call.decision === 'buy' && (
                  <>
                    <div style={S.optionSub}>
                      Strike ${val(result.verdict.call.strike)} | Expiry {val(result.verdict.call.expiry)} ({val(result.verdict.call.dte)} days) |
                      Premium ${val(result.verdict.call.premium_per_contract)} per contract ({val(result.verdict.call.premium_source)})
                    </div>
                    <div style={S.optionSub}>
                      Breakeven ${val(result.verdict.call.breakeven)} | Most you can lose ${val(result.verdict.call.max_loss_per_contract)} per contract |
                      Wrong if the stock closes below ${val(result.verdict.call.invalidation_price)}
                    </div>
                    <div style={S.optionSub}>{result.verdict.call.why}</div>
                  </>
                )}
              </div>
            </div>
          </div>

          {result.verdict.stock.entry_plan && (
            <div style={S.card}>
              <div style={S.sectionLabel}>Wait for Entry plan</div>
              <div style={{ ...S.note, marginTop: '6px' }}>
                <strong style={{ color: '#e2e8f0' }}>Trigger: </strong>
                Pullback to ${val(result.verdict.stock.entry_plan.pullback_price)}
                {result.verdict.stock.entry_plan.distance_to_pullback_pct != null && (
                  <span> ({val(result.verdict.stock.entry_plan.distance_to_pullback_pct)}% from today)</span>
                )}
                {result.verdict.stock.entry_plan.breakout_price != null && (
                  <span> or a close above ${val(result.verdict.stock.entry_plan.breakout_price)}
                  {result.verdict.stock.entry_plan.distance_to_breakout_pct != null && (
                    <span> ({val(result.verdict.stock.entry_plan.distance_to_breakout_pct)}% away)</span>
                  )}</span>
                )}
                {result.verdict.stock.entry_plan.buy_zone && (
                  <span> | Buy zone ${val(result.verdict.stock.entry_plan.buy_zone[0])} to ${val(result.verdict.stock.entry_plan.buy_zone[1])}</span>
                )}
              </div>
              <div style={{ ...S.note, marginTop: '6px' }}>
                <strong style={{ color: '#e2e8f0' }}>Wrong if: </strong>
                {result.verdict.stock.entry_plan.what_flips_to_avoid}
              </div>
              <div style={{ ...S.note, marginTop: '6px' }}>
                <strong style={{ color: '#e2e8f0' }}>What flips it to Buy Now: </strong>
                {result.verdict.stock.entry_plan.what_flips_to_buy}
              </div>
              {result.verdict.stock.entry_plan.blocker && (
                <div style={{ ...S.note, marginTop: '6px' }}>
                  <strong style={{ color: '#e2e8f0' }}>Blocker today: </strong>
                  {result.verdict.stock.entry_plan.blocker}
                </div>
              )}
              <div style={{ ...S.note, marginTop: '6px' }}>
                <strong style={{ color: '#e2e8f0' }}>Drop context: </strong>
                Day {val(result.verdict.stock.entry_plan.drop_context.day_change_pct)}% |
                vs 50-day {val(result.verdict.stock.entry_plan.drop_context.price_vs_ma50_pct)}% |
                vs 200-day {val(result.verdict.stock.entry_plan.drop_context.price_vs_ma200_pct)}% |
                RSI {val(result.verdict.stock.entry_plan.drop_context.rsi)} |
                Volume {val(result.verdict.stock.entry_plan.drop_context.volume_ratio_vs_20d)}x the 20-day average
              </div>
              <div style={{ ...S.note, marginTop: '6px' }}>
                <strong style={{ color: '#e2e8f0' }}>News ({val(result.verdict.stock.entry_plan.news_context.category)}): </strong>
                {result.verdict.stock.entry_plan.news_context.title || 'No headline verified. '}
                {result.verdict.stock.entry_plan.news_context.note}
              </div>
              <div style={{ ...S.note, marginTop: '6px' }}>
                <strong style={{ color: '#e2e8f0' }}>Fundamentals: </strong>
                {result.verdict.stock.entry_plan.fundamentals.status === 'verified' ? (
                  <span>
                    Screener {val(result.verdict.stock.entry_plan.fundamentals.run_date)}: composite {val(result.verdict.stock.entry_plan.fundamentals.composite)} ({val(result.verdict.stock.entry_plan.fundamentals.label)}), smoothed Rule of 40 {val(result.verdict.stock.entry_plan.fundamentals.smoothed_rule_of_40)}, revenue CAGR 3y {val(result.verdict.stock.entry_plan.fundamentals.rev_cagr_3y_pct)}%, FCF margin avg 3y {val(result.verdict.stock.entry_plan.fundamentals.fcf_margin_avg_3y_pct)}%, operating margin {val(result.verdict.stock.entry_plan.fundamentals.operating_margin_pct)}%.
                  </span>
                ) : (
                  <span>{val(result.verdict.stock.entry_plan.fundamentals.note)}</span>
                )}
              </div>
              {result.verdict.stock.entry_plan.notes.map((n, i) => (
                <div key={i} style={{ ...S.note, marginTop: '6px' }}>{n}</div>
              ))}
              <div style={{ ...S.note, marginTop: '6px' }}>
                A dip is not automatically a bargain. This plan shows the trigger and the invalidation, it does not say to buy today.
              </div>
            </div>
          )}

          <div style={S.card}>
            <div style={S.sectionLabel}>Why, in plain language</div>
            <div style={{ ...S.note, marginTop: '6px' }}>
              <strong style={{ color: '#e2e8f0' }}>What supported this: </strong>
              {result.verdict.conviction.supports.length > 0
                ? result.verdict.conviction.supports.join(' ')
                : 'Nothing supported a buy today.'}
            </div>
            <div style={{ ...S.note, marginTop: '6px' }}>
              <strong style={{ color: '#e2e8f0' }}>What was against it: </strong>
              {result.verdict.conviction.against.length > 0
                ? result.verdict.conviction.against.join(' ')
                : 'Nothing was against it.'}
            </div>
            <div style={{ ...S.note, marginTop: '6px' }}>
              <strong style={{ color: '#e2e8f0' }}>What was missing: </strong>
              {result.verdict.conviction.missing.join(' ')}
            </div>
            <div style={{ ...S.note, marginTop: '10px' }}>
              <strong style={{ color: '#e2e8f0' }}>News: </strong>
              {result.news ? result.news.note : 'No fresh company news could be verified.'}
              {result.news && result.news.latest && result.news.latest.published_date && (
                <span> ({val(result.news.latest.published_date)}, {val(result.news.latest.publisher)})</span>
              )}
            </div>
            <div style={{ ...S.note, marginTop: '6px' }}>
              <strong style={{ color: '#e2e8f0' }}>Earnings: </strong>
              {result.verdict.earnings.anticipated_date
                ? `Next report ${val(result.verdict.earnings.anticipated_date)}, ${val(result.verdict.earnings.days_away)} days away. `
                : 'Next earnings date is unknown. '}
              No consensus estimate and no reported beat or miss is available, so nothing is guessed there.
            </div>
          </div>

          <div style={S.card}>
            <div style={{ display: 'flex', gap: '16px', alignItems: 'baseline', flexWrap: 'wrap' }}>
              <span style={S.tickerBig}>{result.ticker}</span>
              <span style={S.priceBig}>${val(result.price)}</span>
              {result.cached && <span style={S.pill('#3d2f10', '#975a16', '#f6e05e')}>CACHED</span>}
            </div>
            <div style={S.meta}>
              Price source: {val(result.price_source)} | Data timestamp: {val(result.data_timestamp)} |
              Fetched: {val(result.fetched_at)}
            </div>
            <div style={{ ...S.grid, marginTop: '14px' }}>
              <div style={S.stat}>
                <span style={S.statLabel}>vs 50-day MA</span>
                <span style={S.statValue}>{val(result.trend.price_vs_ma50_pct)}%</span>
                <span style={S.statSub}>MA50 ${val(result.trend.ma50)}, {val(result.trend.ma50_direction)}</span>
              </div>
              <div style={S.stat}>
                <span style={S.statLabel}>vs 200-day MA</span>
                <span style={S.statValue}>{val(result.trend.price_vs_ma200_pct)}%</span>
                <span style={S.statSub}>MA200 ${val(result.trend.ma200)}, {val(result.trend.ma200_direction)}</span>
              </div>
              <div style={S.stat}>
                <span style={S.statLabel}>Quality score</span>
                <span style={S.statValue}>{val(result.quality.composite)} ({val(result.quality.grade)})</span>
                <span style={S.statSub}>
                  trend {val(result.quality.components.trend)}, RSI {val(result.quality.components.rsi)},
                  volume {val(result.quality.components.volume)}
                </span>
              </div>
              <div style={S.stat}>
                <span style={S.statLabel}>Earnings</span>
                <span style={S.statValue}>{val(result.earnings.earnings_date)}</span>
                <span style={S.statSub}>
                  {result.earnings.status === 'earnings_unknown'
                    ? 'earnings_unknown: fail-closed'
                    : `${val(result.earnings.earnings_days)} days away, ${val(result.earnings.source)}`}
                </span>
              </div>
              <div style={S.stat}>
                <span style={S.statLabel}>IV rank</span>
                <span style={S.statValue}>{val(result.iv.iv_percentile)}</span>
                <span style={S.statSub}>{val(result.iv.source)}</span>
              </div>
              <div style={S.stat}>
                <span style={S.statLabel}>SPY gate</span>
                <span style={S.statValue}>{val(result.spy_gate.gate)}</span>
                <span style={S.statSub}>{val(result.spy_gate.spy_vs_200ma_pct)}% vs 200-day</span>
              </div>
            </div>
            <div style={{ ...S.note, marginTop: '10px' }}>{result.quality.note}</div>
          </div>

          <details style={S.details}>
            <summary style={S.summary}>Rule registry check, full detail (closed by default)</summary>
            <div style={{ marginTop: '12px' }}>
            {result.setups.map((s) => (
              <div key={s.setup_key} style={{ marginBottom: '16px' }}>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
                  <strong style={{ fontSize: '14px', color: '#e2e8f0' }}>{s.setup_name}</strong>
                  <ResultPill result={s.rule_result} status={s.status} />
                  <span style={{ fontSize: '11px', color: '#718096' }}>{s.rule_key}</span>
                </div>
                {s.suppressed_reason && (
                  <div style={{ ...S.note, marginTop: '6px' }}>Suppressed: {s.suppressed_reason}</div>
                )}
                {s.note && <div style={{ ...S.note, marginTop: '6px' }}>{s.note}</div>}
                {s.conditions && Object.keys(s.conditions).length > 0 && (
                  <div style={S.condBox}>
                    {Object.entries(s.conditions).map(([k, v]) => `${k}: ${val(v)}`).join('\n')}
                  </div>
                )}
                {s.action && (
                  <div style={S.ruleBox}>
                    <strong style={{ color: '#e2e8f0' }}>Rule result, not a trade recommendation:</strong>
                    <div style={{ marginTop: '6px' }}>{s.action.action_summary}</div>
                    <div style={{ marginTop: '6px' }}>
                      Action {val(s.action.action)} | Entry ${val(s.action.entry_price)} ({val(s.action.entry_source)}) |
                      Invalidation ${val(s.action.invalidation_price)} |
                      Target {s.action.target_price != null ? `$${s.action.target_price}` : (s.action.exit_rule || 'none')} |
                      Expiry {val(s.action.expiry)}
                    </div>
                    <div style={{ marginTop: '6px' }}>
                      Size: {val(s.action.position_size_shares ?? s.action.position_size_contracts)}
                      {' '}{s.action.position_size_shares != null ? 'shares' : 'contracts'}
                      {' '}({val(s.action.sizing_source)}) | Risk ${val(s.action.risk_dollars)}
                      {' '}({val(s.action.risk_pct_actual)}% of ${val(s.action.account_equity)}, {val(s.action.equity_source)})
                    </div>
                    {s.action.strike != null && (
                      <div style={{ marginTop: '6px' }}>
                        Strike ${val(s.action.strike)} | Premium ${val(s.action.premium)} (listed bid) |
                        Max loss ${val(s.action.max_loss_per_contract)} per contract
                      </div>
                    )}
                    <div style={{ marginTop: '6px' }}>{val(s.action.invalidation_text)}</div>
                  </div>
                )}
              </div>
            ))}
            </div>
          </details>

          <details style={S.details}>
            <summary style={S.summary}>Listed option chain, nearest 21 DTE (closed by default)</summary>
            <div style={{ marginTop: '12px' }}>
            {result.chain.available ? (
              <>
                <div style={{ ...S.note, marginBottom: '10px' }}>
                  Source: {val(result.chain.source)} | Fetched: {val(result.chain.fetched_at)} |
                  Bids and asks are listed quotes; a row with no bid has price source no_executable_bid.
                </div>
                <div style={{ ...S.sectionLabel, marginTop: '12px' }}>Puts</div>
                <ChainTable rows={result.chain.puts} side="put" />
                <div style={{ ...S.sectionLabel, marginTop: '12px' }}>Calls</div>
                <ChainTable rows={result.chain.calls} side="call" />
              </>
            ) : (
              <div style={S.note}>
                No listed chain: {val(result.chain.error)}. The options result is suppressed with that
                named reason instead of a guessed price.
              </div>
            )}
            </div>
          </details>

          <div style={S.card}>
            <div style={S.sectionLabel}>
              Explanation ({result.explanation_source === 'claude' ? 'Claude, plain language only' : 'quant fallback'})
            </div>
            <div style={{ fontSize: '13px', color: '#a0aec0', lineHeight: 1.6 }}>{result.explanation}</div>
            <div style={{ ...S.note, marginTop: '10px' }}>{result.disclaimer}</div>
          </div>
        </>
      )}
    </div>
  )
}
