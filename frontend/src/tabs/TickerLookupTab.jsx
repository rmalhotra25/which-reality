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
        Ticker Lookup is a query. It runs the same rule registry check the alert engine runs,
        for one ticker, at the data timestamp shown. Same ticker, same data timestamp, same
        answer as the live run would give. No alert fires, no journal row is created, no
        notification is sent, and a passing setup is a rule result, not a trade recommendation.
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

      {result && (
        <>
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

          <div style={S.card}>
            <div style={S.sectionLabel}>Rule registry check</div>
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

          <div style={S.card}>
            <div style={S.sectionLabel}>Listed option chain, nearest 21 DTE</div>
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
