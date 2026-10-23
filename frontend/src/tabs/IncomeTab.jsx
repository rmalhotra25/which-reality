import { useState, useEffect } from 'react'
import { api } from '../api'

const C = {
  bg: '#0f1117', card: '#1a1f2e', bdr: '#2d3748',
  text: '#e2e8f0', muted: '#718096', sub: '#a0aec0', faint: '#4a5568',
  green: '#68d391', yellow: '#ecc94b', red: '#fc8181', blue: '#63b3ed',
  accent: '#48bb78', gold: '#ecc94b',
  reit: '#9f7aea', arist: '#f6ad55', etf: '#63b3ed', custom: '#ed8936', cef: '#fc814a',
}

const DIV_CAT_COLOR = { etf: C.etf, aristocrat: C.arist, reit: C.reit, custom: C.custom }
const DIV_CAT_LABEL = { etf: 'ETF', aristocrat: 'Dividend Aristocrat', reit: 'REIT / BDC', custom: 'Custom' }

const FREQ_LABEL = { 1: 'Annual', 2: 'Semi-Annual', 4: 'Quarterly', 12: 'Monthly', 52: 'Weekly' }

const fmt$  = v => `$${Number(v || 0).toLocaleString('en-US', { maximumFractionDigits: 0 })}`
const fmt$d = v => `$${Number(v || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
const fmtP  = v => v != null ? `${Number(v).toFixed(2)}%` : '—'

function Chip({ label, color, bg }) {
  return (
    <span style={{ fontSize: '11px', fontWeight: 600, color: color || C.text, background: bg || `${color}22`, border: `1px solid ${color || C.faint}44`, borderRadius: '4px', padding: '1px 6px' }}>
      {label}
    </span>
  )
}

function Metric({ label, value, color }) {
  return (
    <div>
      <div style={{ fontSize: '10px', color: C.muted }}>{label}</div>
      <div style={{ fontSize: '12px', fontWeight: 600, color: color || C.text }}>{value ?? '—'}</div>
    </div>
  )
}

// ── Dividend stock row ─────────────────────────────────────────────────────
function DividendRow({ h, capital }) {
  const cc = DIV_CAT_COLOR[h.category] || C.custom
  const invested = h.dollar_amount ?? (capital * (h.allocation_pct || 0) / 100)
  const moIncome = invested && h.annual_yield_pct > 0 ? invested * h.annual_yield_pct / 100 / 12 : 0

  return (
    <div style={{ background: C.card, border: `1px solid ${C.bdr}`, borderRadius: '12px', padding: '14px 16px', marginBottom: '8px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '10px', marginBottom: '10px' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
            <span style={{ fontSize: '16px', fontWeight: 700, color: C.text }}>{h.ticker}</span>
            <Chip label={DIV_CAT_LABEL[h.category] || h.category} color={cc} />
          </div>
          <div style={{ fontSize: '12px', color: C.muted, marginTop: '2px' }}>{h.name}</div>
        </div>
        <div style={{ textAlign: 'right', flexShrink: 0 }}>
          <div style={{ fontSize: '16px', fontWeight: 700, color: cc }}>{fmt$(invested)}</div>
          <div style={{ fontSize: '11px', color: C.muted }}>allocated</div>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(100px, 1fr))', gap: '8px 12px' }}>
        <Metric label="Trailing Yield"  value={fmtP(h.annual_yield_pct)} color={C.green} />
        <Metric label="Forward Yield"   value="—" />
        <Metric label="Payout Ratio"    value="—" />
        <Metric label="Div Growth (1Y)" value={h.div_growth_pct != null ? `${h.div_growth_pct >= 0 ? '+' : ''}${h.div_growth_pct.toFixed(1)}%` : '—'} color={h.div_growth_pct >= 0 ? C.green : C.red} />
        <Metric label="Streak"          value={h.streak_payments > 0 ? `${h.streak_payments} pmts` : '—'} />
        <Metric label="Frequency"       value="—" />
        <Metric label="Mo. Income"      value={moIncome > 0 ? fmt$d(moIncome) : '—'} color={C.accent} />
        {h.score != null && <Metric label="Score" value={`${h.score}/100`} />}
      </div>
      {h.error && <div style={{ marginTop: '8px', fontSize: '11px', color: C.red }}>⚠ {h.error}</div>}
    </div>
  )
}

// ── CEF row ────────────────────────────────────────────────────────────────
function CefRow({ cef }) {
  const freqLabel = FREQ_LABEL[cef.div_frequency] || `${cef.div_frequency}x/yr`
  const moIncome = cef.monthly_div != null ? cef.monthly_div : (cef.annual_yield_pct && cef.price > 0 ? cef.price * cef.annual_yield_pct / 100 / 12 : null)

  return (
    <div style={{ background: C.card, border: `1px solid ${C.cef}44`, borderRadius: '12px', padding: '14px 16px', marginBottom: '8px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '10px', marginBottom: '10px' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
            <span style={{ fontSize: '16px', fontWeight: 700, color: C.text }}>{cef.ticker}</span>
            <Chip label="CEF" color={C.cef} />
            {cef.score > 0 && <Chip label={`Score ${Math.round(cef.score)}`} color={C.sub} bg="#ffffff10" />}
          </div>
          <div style={{ fontSize: '12px', color: C.muted, marginTop: '2px' }}>
            {cef.price > 0 && <span>${cef.price.toFixed(2)}</span>}
            {cef.high_52w && <span style={{ color: C.faint, marginLeft: '8px' }}>52w Hi ${cef.high_52w.toFixed(2)}</span>}
          </div>
        </div>
        {cef.pct_below_52w_high != null && (
          <div style={{ textAlign: 'right', flexShrink: 0 }}>
            <div style={{ fontSize: '14px', fontWeight: 700, color: cef.pct_below_52w_high > 15 ? C.red : C.yellow }}>
              -{cef.pct_below_52w_high}%
            </div>
            <div style={{ fontSize: '11px', color: C.muted }}>below 52w hi</div>
          </div>
        )}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(100px, 1fr))', gap: '8px 12px', marginBottom: '8px' }}>
        <Metric label="Trailing Yield"  value={fmtP(cef.annual_yield_pct)} color={C.green} />
        <Metric label="Yield 6mo Ago"   value={fmtP(cef.yield_6m_ago_pct)} />
        <Metric label="Payout Ratio"    value="—" />
        <Metric label="Div Streak"      value={cef.dividend_streak_months > 0 ? `${cef.dividend_streak_months}mo` : '—'} />
        <Metric label="Frequency"       value={freqLabel} />
        <Metric label="Mo. Income"      value={moIncome != null ? fmt$d(moIncome) : '—'} color={C.accent} />
      </div>

      {/* NAV discount — no NAV data available from current data sources */}
      <div style={{ borderTop: `1px solid ${C.bdr}`, paddingTop: '8px', fontSize: '11px', color: C.faint }}>
        NAV discount/premium: no NAV data available from current data sources
      </div>
    </div>
  )
}

// ── Summary stats bar ──────────────────────────────────────────────────────
function StatBox({ label, value, color }) {
  return (
    <div style={{ background: '#0f1117', border: `1px solid ${C.bdr}`, borderRadius: '8px', padding: '12px 16px' }}>
      <div style={{ fontSize: '11px', color: C.muted }}>{label}</div>
      <div style={{ fontSize: '20px', fontWeight: 700, color: color || C.text }}>{value}</div>
    </div>
  )
}

// ── Main tab ──────────────────────────────────────────────────────────────
export default function IncomeTab() {
  const [divData, setDivData]   = useState(null)
  const [cefData, setCefData]   = useState(null)
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState(null)
  const [refreshing, setRefreshing] = useState(false)

  const [startCap, setStartCap]     = useState(61000)
  const [weeklyDca, setWeeklyDca]   = useState(500)

  async function loadData(startingCapital = startCap, wdca = weeklyDca) {
    setLoading(true); setError(null)
    try {
      const [div, cef] = await Promise.all([
        api.dividendPath.recommend(startingCapital, wdca),
        api.cef.scan(),
      ])
      setDivData(div)
      setCefData(cef)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadData() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  async function handleRefresh() {
    setRefreshing(true)
    try {
      await Promise.all([
        api.dividendPath.refresh(startCap, weeklyDca),
        api.cef.refresh(),
      ])
      // Give backends a moment to start, then reload
      await new Promise(r => setTimeout(r, 1200))
      await loadData()
    } catch (e) {
      setError(e.message)
    } finally {
      setRefreshing(false)
    }
  }

  const portfolio = divData?.portfolio || []
  const cefResults = cefData?.top || []
  const totalMoIncome = portfolio.reduce((sum, h) => {
    const invested = h.dollar_amount ?? (startCap * (h.allocation_pct || 0) / 100)
    return sum + (invested && h.annual_yield_pct > 0 ? invested * h.annual_yield_pct / 100 / 12 : 0)
  }, 0)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>

      {/* Header */}
      <div style={{ background: 'linear-gradient(135deg,#1a2744 0%,#1a1f2e 100%)', border: `1px solid ${C.blue}33`, borderRadius: '12px', padding: '20px 24px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '16px' }}>
          <div>
            <div style={{ fontSize: '22px', fontWeight: 700, color: C.text }}>Income</div>
            <div style={{ fontSize: '13px', color: C.muted, marginTop: '4px' }}>
              Dividend portfolio and top CEF candidates in one view.
            </div>
          </div>
          <button
            onClick={handleRefresh}
            disabled={loading || refreshing}
            style={{ padding: '8px 16px', background: C.blue, color: '#000', border: 'none', borderRadius: '8px', fontWeight: 700, cursor: loading || refreshing ? 'not-allowed' : 'pointer', fontSize: '13px', opacity: loading || refreshing ? 0.6 : 1 }}
          >
            {refreshing ? 'Refreshing...' : 'Refresh'}
          </button>
        </div>

        <div style={{ display: 'flex', gap: '16px', marginTop: '16px', flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <div>
            <label style={{ fontSize: '11px', color: C.muted, display: 'block', marginBottom: '4px' }}>Starting Capital ($)</label>
            <input
              type="number" value={startCap}
              onChange={e => setStartCap(Number(e.target.value))}
              style={{ background: '#0f1117', border: `1px solid ${C.bdr}`, borderRadius: '6px', padding: '7px 10px', color: C.text, fontSize: '14px', width: '130px' }}
            />
          </div>
          <div>
            <label style={{ fontSize: '11px', color: C.muted, display: 'block', marginBottom: '4px' }}>Weekly DCA ($)</label>
            <input
              type="number" value={weeklyDca}
              onChange={e => setWeeklyDca(Number(e.target.value))}
              style={{ background: '#0f1117', border: `1px solid ${C.bdr}`, borderRadius: '6px', padding: '7px 10px', color: C.text, fontSize: '14px', width: '110px' }}
            />
          </div>
          <button
            onClick={() => loadData(startCap, weeklyDca)}
            disabled={loading}
            style={{ padding: '7px 16px', background: C.accent, color: '#000', border: 'none', borderRadius: '6px', fontWeight: 700, cursor: loading ? 'not-allowed' : 'pointer', fontSize: '13px' }}
          >
            Apply
          </button>
        </div>
      </div>

      {error && (
        <div style={{ background: '#2d1515', border: `1px solid ${C.red}`, borderRadius: '10px', padding: '16px', color: C.red }}>
          {error}
        </div>
      )}

      {loading && !divData && (
        <div style={{ textAlign: 'center', padding: '60px', color: C.muted }}>
          <div style={{ fontSize: '32px', marginBottom: '12px' }}>📊</div>
          <div>Loading income data...</div>
        </div>
      )}

      {/* Summary stats */}
      {divData && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(165px, 1fr))', gap: '12px' }}>
          <StatBox label="Starting Capital"     value={fmt$(startCap)}                          color={C.blue} />
          <StatBox label="Blended Yield"        value={fmtP(divData.blended_yield_pct)}         color={C.green} />
          <StatBox label="Starting Mo. Income"  value={fmt$d(totalMoIncome)}                    color={C.green} />
          <StatBox label="Dividend Holdings"    value={portfolio.length}                         />
          <StatBox label="Top CEFs"             value={cefResults.length}                        color={C.cef} />
        </div>
      )}

      {/* Dividend holdings */}
      {portfolio.length > 0 && (
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
            <h2 style={{ fontSize: '17px', fontWeight: 800, color: C.text, margin: 0 }}>Dividend Portfolio</h2>
            <span style={{ background: C.green, color: '#000', borderRadius: '6px', padding: '2px 9px', fontSize: '11px', fontWeight: 700 }}>
              {portfolio.length} holdings
            </span>
          </div>
          {portfolio.map(h => (
            <DividendRow key={h.ticker} h={h} capital={startCap} />
          ))}
        </div>
      )}

      {/* CEF top candidates */}
      {cefResults.length > 0 && (
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '6px' }}>
            <h2 style={{ fontSize: '17px', fontWeight: 800, color: C.text, margin: 0 }}>CEF Candidates</h2>
            <span style={{ background: C.cef, color: '#000', borderRadius: '6px', padding: '2px 9px', fontSize: '11px', fontWeight: 700 }}>
              Top {cefResults.length}
            </span>
          </div>
          <p style={{ fontSize: '12px', color: C.muted, marginBottom: '12px', lineHeight: 1.5 }}>
            Closed-end funds scored by distribution yield, streak consistency, and yield momentum.
          </p>
          {cefResults.map(cef => (
            <CefRow key={cef.ticker} cef={cef} />
          ))}
        </div>
      )}

      {!loading && !divData && !error && (
        <div style={{ textAlign: 'center', padding: '40px', color: C.muted }}>
          No income data. Click Refresh to run a scan.
        </div>
      )}
    </div>
  )
}
