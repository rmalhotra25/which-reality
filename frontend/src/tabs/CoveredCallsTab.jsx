import { useState } from 'react'
import { api } from '../api'

const S = {
  card: { background: '#1a202c', border: '1px solid #2d3748', borderRadius: '8px', padding: '16px', marginBottom: '12px' },
  note: { fontSize: '13px', color: '#a0aec0', lineHeight: '1.5' },
  input: { padding: '8px', background: '#0f1520', color: '#e2e8f0', border: '1px solid #2d3748', borderRadius: '6px' },
  button: { padding: '8px 16px', background: '#2b6cb0', color: '#fff', border: 'none', borderRadius: '6px', cursor: 'pointer' },
  summary: { cursor: 'pointer', fontWeight: 700, color: '#e2e8f0' },
}

function val(v) {
  return v === null || v === undefined ? 'Missing' : v
}

function PickCard({ pick, fallback }) {
  if (!pick) return (
    <div style={S.card}>
      <div style={S.note}>No listed strike for this tier on this expiry.</div>
    </div>
  )
  return (
    <div style={S.card}>
      <div style={{ fontSize: '16px', fontWeight: 800, color: '#e2e8f0' }}>{pick.label}</div>
      {fallback && (
        <div style={{ ...S.note, color: '#f6e05e' }}>
          Nearest listed strike to this delta band was used, because no strike fell inside the band.
        </div>
      )}
      <div style={{ marginTop: '8px', fontSize: '15px', color: '#e2e8f0' }}>
        Strike ${val(pick.strike)}, expiry {val(pick.expiry)} ({val(pick.dte)} days). Bid ${val(pick.bid_per_share)} per share, ${val(pick.premium_per_contract)} per contract.
      </div>
      <div style={S.note}>
        Premium yield {val(pick.premium_yield_pct)}%, annualized {val(pick.annualized_yield_pct)}%. Breakeven ${val(pick.breakeven)}.
        Distance to strike {val(pick.distance_to_strike_pct)}%. Delta {val(pick.delta)} (rough assignment-risk proxy, not a probability guarantee).
      </div>
      <div style={S.note}>
        Theta {val(pick.theta_seller)}, IV {val(pick.iv_pct)}%, open interest {val(pick.open_interest)}, spread ${val(pick.spread_per_share)} ({val(pick.spread_pct)}%).
      </div>
      <div style={S.note}>
        {pick.called_line} {pick.not_called_line}
      </div>
      {pick.contracts_covered > 0 && (
        <div style={S.note}>
          For {pick.contracts_covered} covered contract(s): ${val(pick.total_premium_for_shares)} total premium at the bid.
        </div>
      )}
      {pick.cost_basis !== null && pick.cost_basis !== undefined && (
        <div style={S.note}>Cost basis entered: ${val(pick.cost_basis)} per share.</div>
      )}
    </div>
  )
}

function Chart({ history, price, picks }) {
  if (!history || history.length < 2) return null
  const strikes = ['aggressive', 'middle', 'conservative'].map((k) => picks[k]?.strike).filter((v) => v !== null && v !== undefined)
  const values = [...history.map((p) => p.close), price, ...strikes].filter((v) => v !== null && v !== undefined)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1
  const w = 640
  const h = 200
  const x = (i) => (i / (history.length - 1)) * w
  const y = (v) => h - ((v - min) / range) * h
  const points = history.map((p, i) => `${x(i)},${y(p.close)}`).join(' ')
  return (
    <div style={S.card}>
      <div style={{ fontWeight: 700, color: '#e2e8f0', marginBottom: '8px' }}>Price vs the three strikes</div>
      <svg width="100%" viewBox={`0 0 ${w} ${h}`} style={{ background: '#0f1520', borderRadius: '6px' }}>
        <polyline points={points} fill="none" stroke="#63b3ed" strokeWidth="2" />
        {strikes.map((s, i) => (
          <line key={i} x1="0" x2={w} y1={y(s)} y2={y(s)} stroke={['#fc8181', '#f6e05e', '#68d391'][i]} strokeWidth="1.5" strokeDasharray="6 4" />
        ))}
        <line x1="0" x2={w} y1={y(price)} y2={y(price)} stroke="#e2e8f0" strokeWidth="1" strokeDasharray="2 3" />
      </svg>
      <div style={S.note}>
        Blue line: last 6 months of closes. Dashed lines, top to bottom by strike: aggressive (red), middle (yellow), conservative (green). White dotted line: current price ${val(price)}.
      </div>
    </div>
  )
}

export default function CoveredCallsTab() {
  const [ticker, setTicker] = useState('')
  const [shares, setShares] = useState(100)
  const [costBasis, setCostBasis] = useState('')
  const [expiry, setExpiry] = useState('')
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  async function run(selectedExpiry) {
    const t = ticker.trim().toUpperCase()
    if (!t) return
    setLoading(true)
    setError(null)
    try {
      const data = await api.coveredCallPicks.get(t, { expiry: selectedExpiry || undefined, shares, costBasis: costBasis === '' ? undefined : costBasis })
      setResult(data)
      setExpiry(data.selected_expiry || '')
    } catch (e) {
      setError(e.message)
      setResult(null)
    } finally {
      setLoading(false)
    }
  }

  const picks = result?.picks || {}
  return (
    <div>
      <div style={{ ...S.card, display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
        <input style={S.input} value={ticker} onChange={(e) => setTicker(e.target.value)} placeholder="Ticker, e.g. AAPL" />
        <input style={S.input} type="number" value={shares} onChange={(e) => setShares(Number(e.target.value))} placeholder="Shares owned" title="Shares owned" />
        <input style={S.input} type="number" value={costBasis} onChange={(e) => setCostBasis(e.target.value)} placeholder="Cost basis (optional)" title="Cost basis per share, optional" />
        {result?.expiries?.length > 0 && (
          <select style={S.input} value={expiry} onChange={(e) => { setExpiry(e.target.value); run(e.target.value) }}>
            {result.expiries.map((e) => (
              <option key={e.expiry} value={e.expiry}>{e.expiry} ({e.dte} days)</option>
            ))}
          </select>
        )}
        <button style={S.button} onClick={() => run('')} disabled={loading}>{loading ? 'Loading...' : 'Get covered call picks'}</button>
      </div>

      {error && <div style={{ ...S.card, color: '#fc8181' }}>{error}</div>}

      {result && !result.available && (
        <div style={S.card}>
          <div style={{ color: '#fc8181', fontWeight: 700 }}>Covered call picks unavailable</div>
          <div style={S.note}>{result.reason}</div>
        </div>
      )}

      {result && result.available && (
        <>
          <div style={S.card}>
            <div style={{ fontSize: '16px', fontWeight: 800, color: '#e2e8f0' }}>
              {result.ticker} at ${val(result.price)}, expiry {val(result.selected_expiry)} ({val(result.selected_dte)} days)
            </div>
            <div style={S.note}>
              Chain source: {val(result.chain_source)}. {result.chain_delay_note || 'Live quotes where the source provides them.'} Premiums are per contract (x100 shares).
              A covered call caps upside and does not protect against a falling stock. Assignment means shares are called away at the strike.
              Delta is a rough assignment-risk proxy, not a probability guarantee.
            </div>
          </div>

          <PickCard pick={picks.aggressive} fallback={result.band_fallback_tiers?.includes('aggressive')} />
          <PickCard pick={picks.middle} fallback={result.band_fallback_tiers?.includes('middle')} />
          <PickCard pick={picks.conservative} fallback={result.band_fallback_tiers?.includes('conservative')} />

          <div style={S.card}>
            <div style={{ fontWeight: 700, color: '#e2e8f0', marginBottom: '8px' }}>Strike ladder: premium yield vs delta</div>
            <table style={{ width: '100%', fontSize: '13px', color: '#e2e8f0', borderCollapse: 'collapse' }}>
              <thead><tr><th align="left">Tier</th><th align="left">Strike</th><th align="left">Bid</th><th align="left">Yield</th><th align="left">Annualized</th><th align="left">Delta</th></tr></thead>
              <tbody>
                {['aggressive', 'middle', 'conservative'].map((k) => (
                  <tr key={k}>
                    <td>{k}</td>
                    <td>{picks[k] ? `$${picks[k].strike}` : 'Missing'}</td>
                    <td>{picks[k] ? `$${picks[k].bid_per_share}` : 'Missing'}</td>
                    <td>{picks[k] ? `${picks[k].premium_yield_pct}%` : 'Missing'}</td>
                    <td>{picks[k] ? `${picks[k].annualized_yield_pct}%` : 'Missing'}</td>
                    <td>{picks[k] ? picks[k].delta : 'Missing'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div style={S.note}>Higher premium usually means a strike closer to the price and a higher chance of being called away. Lower premium usually means more room to run and less chance of assignment.</div>
          </div>

          <Chart history={result.history} price={result.price} picks={picks} />
          {result.history_note && <div style={S.card}><div style={S.note}>{result.history_note}</div></div>}

          <details style={S.card}>
            <summary style={S.summary}>Full Greeks, chain source, and news</summary>
            <div style={{ marginTop: '8px' }}>
              {['aggressive', 'middle', 'conservative'].map((k) => picks[k] && (
                <div key={k} style={S.note}>
                  {k}: delta {val(picks[k].delta)}, theta {val(picks[k].theta_seller)}, gamma {val(picks[k].gamma)}, vega {val(picks[k].vega)}, IV {val(picks[k].iv_pct)}%, open interest {val(picks[k].open_interest)}, spread ${val(picks[k].spread_per_share)}.
                </div>
              ))}
              <div style={S.note}>Chain source: {val(result.chain_source)}. {result.chain_delay_note || ''} Expiries source: {val(result.expiries_source)}.</div>
              <div style={{ ...S.note, marginTop: '8px' }}>{result.news_note}</div>
              {(result.news || []).length === 0 && <div style={S.note}>{result.news_error || 'No recent headlines found.'}</div>}
              {(result.news || []).map((n, i) => (
                <div key={i} style={S.note}>
                  {n.published_at ? `${n.published_at.slice(0, 10)}: ` : ''}{n.title} {n.publisher ? `(${n.publisher})` : ''}
                </div>
              ))}
            </div>
          </details>
        </>
      )}
    </div>
  )
}
