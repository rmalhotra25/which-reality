import { useState } from 'react'

const API = import.meta.env.VITE_API_URL || ''

const RECO_CONFIG = {
  'Strong Buy': { bg: '#1a3a2a', border: '#2f855a', color: '#68d391', icon: '🚀' },
  'Buy':        { bg: '#0a1628', border: '#2b6cb0', color: '#90cdf4', icon: '↑' },
  'Hold':       { bg: '#2d2a00', border: '#b7791f', color: '#fbd38d', icon: '⟷' },
  'Pass':       { bg: '#3a1a1a', border: '#c53030', color: '#fc8181', icon: '✕' },
}

function RecoChip({ rec }) {
  const c = RECO_CONFIG[rec] || RECO_CONFIG['Hold']
  return (
    <div style={{
      display: 'inline-flex', alignItems: 'center', gap: '6px',
      padding: '7px 16px',
      background: c.bg, border: `1px solid ${c.border}`,
      borderRadius: '8px', color: c.color,
      fontSize: '14px', fontWeight: 700,
    }}>
      {c.icon} {rec}
    </div>
  )
}

function MetricPill({ label, value }) {
  return (
    <div style={{
      background: '#0f1117', border: '1px solid #2d3748',
      borderRadius: '6px', padding: '6px 10px', textAlign: 'center',
      minWidth: '60px',
    }}>
      <div style={{ fontSize: '10px', color: '#718096', marginBottom: '2px' }}>{label}</div>
      <div style={{ fontSize: '13px', fontWeight: 700, color: '#e2e8f0' }}>{value}</div>
    </div>
  )
}

function ScenarioCard({ label, price, upside, g1Pct, fcfPct, highlight }) {
  const up = upside ?? 0
  return (
    <div style={{
      flex: '1', minWidth: '110px',
      background: highlight ? '#0d2112' : '#161b27',
      border: `1px solid ${highlight ? '#2f855a' : '#2d3748'}`,
      borderRadius: '10px', padding: '14px 12px',
      textAlign: 'center',
    }}>
      <div style={{
        fontSize: '11px', color: '#718096',
        fontWeight: 600, letterSpacing: '0.08em', marginBottom: '8px',
      }}>
        {label}
      </div>
      {price != null && (
        <div style={{
          fontSize: '20px', fontWeight: 800,
          color: label === 'BULL' ? '#68d391' : label === 'BEAR' ? '#fc8181' : '#90cdf4',
          marginBottom: '2px',
        }}>
          ${price.toLocaleString()}
        </div>
      )}
      <div style={{
        fontSize: '14px', fontWeight: 700,
        color: up >= 0 ? '#68d391' : '#fc8181',
        marginBottom: '8px',
      }}>
        {upside != null ? `${up > 0 ? '+' : ''}${up}%` : '—'}
      </div>
      <div style={{ fontSize: '11px', color: '#718096', lineHeight: 1.5 }}>
        <div>Rev growth yr1-5: {g1Pct}%</div>
        <div>FCF margin: {fcfPct}%</div>
      </div>
    </div>
  )
}

export default function DcfTab() {
  const [ticker, setTicker] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  async function analyze() {
    const t = ticker.trim().toUpperCase()
    if (!t) return
    setLoading(true)
    setResult(null)
    setError(null)
    try {
      const resp = await fetch(`${API}/api/dcf/${encodeURIComponent(t)}`)
      const body = await resp.json().catch(() => ({}))
      if (!resp.ok) throw new Error(body.detail || `Error ${resp.status}`)
      setResult(body)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  function handleKey(e) {
    if (e.key === 'Enter') analyze()
  }

  const r = result

  return (
    <div style={{ maxWidth: '860px' }}>
      <div style={{ marginBottom: '20px' }}>
        <h2 style={{ fontSize: '20px', fontWeight: 700, color: '#e2e8f0', margin: '0 0 4px' }}>
          🧮 DCF Valuation
        </h2>
        <p style={{ fontSize: '13px', color: '#718096', margin: 0 }}>
          CAPM-derived WACC · Reverse DCF (what growth the market is pricing in) · Claude-set scenario parameters
        </p>
      </div>

      <div style={{ display: 'flex', gap: '10px', marginBottom: '28px', alignItems: 'center', flexWrap: 'wrap' }}>
        <input
          value={ticker}
          onChange={e => setTicker(e.target.value.toUpperCase())}
          onKeyDown={handleKey}
          placeholder="e.g. AAPL"
          style={{
            flex: '1', minWidth: '140px', maxWidth: '200px',
            padding: '10px 14px',
            background: '#1a1f2e', border: '1px solid #2d3748',
            borderRadius: '8px', color: '#e2e8f0',
            fontSize: '16px', fontWeight: 700,
            textTransform: 'uppercase', letterSpacing: '0.08em', outline: 'none',
          }}
        />
        <button
          onClick={analyze}
          disabled={loading || !ticker.trim()}
          style={{
            padding: '10px 24px',
            background: loading || !ticker.trim() ? '#2d3748' : '#2b6cb0',
            color: loading || !ticker.trim() ? '#718096' : '#fff',
            border: 'none', borderRadius: '8px',
            cursor: loading || !ticker.trim() ? 'not-allowed' : 'pointer',
            fontSize: '14px', fontWeight: 600,
            transition: 'background 0.15s',
          }}
        >
          {loading ? 'Analyzing…' : 'Analyze'}
        </button>
      </div>

      {error && (
        <div style={{
          color: '#fc8181', padding: '14px 16px',
          background: '#2d1515', border: '1px solid #742a2a',
          borderRadius: '8px', marginBottom: '16px', fontSize: '14px',
        }}>
          {error}
        </div>
      )}

      {loading && (
        <div style={{ color: '#a0aec0', textAlign: 'center', padding: '60px 24px', fontSize: '14px' }}>
          <div style={{ fontSize: '28px', marginBottom: '12px' }}>🧮</div>
          Fetching fundamentals and asking Claude to set scenario parameters…
        </div>
      )}

      {r && (
        <div style={{
          background: '#1a1f2e', border: '1px solid #2d3748',
          borderRadius: '12px', padding: '24px',
          display: 'flex', flexDirection: 'column', gap: '22px',
        }}>
          {/* Header */}
          <div style={{
            display: 'flex', justifyContent: 'space-between',
            alignItems: 'flex-start', flexWrap: 'wrap', gap: '10px',
          }}>
            <div>
              <div style={{ fontSize: '26px', fontWeight: 800, color: '#90cdf4' }}>{r.ticker}</div>
              <div style={{ fontSize: '14px', color: '#a0aec0', marginTop: '2px' }}>
                {r.name} · {r.sector}
              </div>
            </div>
            <RecoChip rec={r.recommendation} />
          </div>

          {/* Market context pills */}
          <div>
            <div style={{ fontSize: '11px', color: '#718096', fontWeight: 600, letterSpacing: '0.08em', marginBottom: '8px' }}>
              MARKET CONTEXT
            </div>
            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
              <MetricPill label="Price" value={r.current_price != null ? `$${r.current_price}` : '—'} />
              <MetricPill label="Mkt Cap" value={`$${r.market_cap_b}B`} />
              <MetricPill label="Rev Growth" value={`${r.revenue_growth_pct}%`} />
              <MetricPill label="Gross Margin" value={`${r.gross_margin_pct}%`} />
              <MetricPill label="FCF Margin" value={`${r.fcf_margin_pct}%`} />
              <MetricPill label="P/E" value={r.pe ?? '—'} />
              <MetricPill label="P/S" value={r.ps ?? '—'} />
              <MetricPill label="Beta" value={r.beta ?? '—'} />
              <MetricPill label="WACC" value={`${r.wacc_pct}%`} />
            </div>
          </div>

          {/* Reverse DCF */}
          <div style={{
            background: '#0f1117', border: '1px solid #2d3748',
            borderRadius: '8px', padding: '14px 16px',
          }}>
            <div style={{
              fontSize: '11px', color: '#718096', fontWeight: 600,
              letterSpacing: '0.08em', marginBottom: '6px',
            }}>
              REVERSE DCF — GROWTH RATE THE MARKET IS CURRENTLY PRICING IN
            </div>
            <div style={{ fontSize: '24px', fontWeight: 800, color: '#fbd38d' }}>
              {r.implied_growth_pct}% / year
            </div>
            <div style={{ fontSize: '12px', color: '#a0aec0', marginTop: '4px', lineHeight: 1.6 }}>
              At today's market cap of ${r.market_cap_b}B, investors are implying {r.implied_growth_pct}% annual revenue growth
              over the next decade. Our base case DCF implies{' '}
              {r.dcf_base_upside != null
                ? <span style={{ color: r.dcf_base_upside >= 0 ? '#68d391' : '#fc8181', fontWeight: 700 }}>
                    {r.dcf_base_upside > 0 ? '+' : ''}{r.dcf_base_upside}% {r.dcf_base_upside >= 0 ? 'upside' : 'downside'}
                  </span>
                : 'unknown upside'
              }.
            </div>
          </div>

          {/* DCF scenarios */}
          <div>
            <div style={{
              fontSize: '11px', color: '#718096', fontWeight: 600,
              letterSpacing: '0.08em', marginBottom: '10px',
            }}>
              DCF SCENARIOS
              <span style={{
                marginLeft: '8px', padding: '1px 7px',
                background: r.used_claude_params ? '#0a1628' : '#1a1a1a',
                color: r.used_claude_params ? '#4299e1' : '#718096',
                border: `1px solid ${r.used_claude_params ? '#2b6cb0' : '#2d3748'}`,
                borderRadius: '4px', fontSize: '10px',
              }}>
                {r.used_claude_params ? 'Claude parameters' : 'mechanical fallback'}
              </span>
            </div>
            <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
              <ScenarioCard
                label="BULL"
                price={r.dcf_bull_price}
                upside={r.dcf_bull_upside}
                g1Pct={r.bull_g1_pct}
                fcfPct={r.bull_fcf_pct}
              />
              <ScenarioCard
                label="BASE"
                price={r.dcf_base_price}
                upside={r.dcf_base_upside}
                g1Pct={r.base_g1_pct}
                fcfPct={r.base_fcf_pct}
                highlight
              />
              <ScenarioCard
                label="BEAR"
                price={r.dcf_bear_price}
                upside={r.dcf_bear_upside}
                g1Pct={r.bear_g1_pct}
                fcfPct={r.bear_fcf_pct}
              />
            </div>
          </div>

          {/* Claude reasoning */}
          {r.scenario_reasoning && (
            <div style={{
              background: '#0a1628', border: '1px solid #2b6cb0',
              borderRadius: '8px', padding: '14px 16px',
            }}>
              <div style={{
                fontSize: '11px', color: '#4299e1', fontWeight: 600,
                letterSpacing: '0.08em', marginBottom: '6px',
              }}>
                CLAUDE'S REASONING
                {r.scenario_confidence && (
                  <span style={{
                    marginLeft: '8px', padding: '1px 7px',
                    background: '#1a3a5a', color: '#90cdf4',
                    borderRadius: '4px', fontSize: '10px', textTransform: 'uppercase',
                  }}>
                    {r.scenario_confidence} confidence
                  </span>
                )}
              </div>
              <p style={{ fontSize: '13px', color: '#a0aec0', margin: 0, lineHeight: 1.6 }}>
                {r.scenario_reasoning}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
