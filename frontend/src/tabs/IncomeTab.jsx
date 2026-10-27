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
  const [divError, setDivError] = useState(null)
  const [cefError, setCefError] = useState(null)
  const [scanRunning, setScanRunning] = useState(false)
  const [refreshing, setRefreshing] = useState(false)

  const [startCap, setStartCap]     = useState(61000)
  const [weeklyDca, setWeeklyDca]   = useState(500)
  // Monthly contribution slider for the income projection, $100-$2,000/month.
  const [monthly, setMonthly]       = useState(500)
  const [projData, setProjData]     = useState(null)
  const [projLoading, setProjLoading] = useState(false)

  async function loadData(startingCapital = startCap, wdca = weeklyDca) {
    setLoading(true); setDivError(null); setCefError(null); setScanRunning(false)
    // Load the two sources independently: one failing must not kill the
    // whole tab, and a cold cache returns 202 scan_running, not data.
    const [divRes, cefRes] = await Promise.allSettled([
      api.dividendPath.recommend(startingCapital, wdca),
      api.cef.scan(),
    ])
    if (divRes.status === 'fulfilled') {
      if (divRes.value?.status === 'scan_running') {
        setScanRunning(true)
        setDivError('Dividend scan is running in the background. Try again shortly.')
      } else {
        setDivData(divRes.value)
      }
    } else {
      setDivError(divRes.reason?.message || 'Dividend data failed to load.')
    }
    if (cefRes.status === 'fulfilled') {
      if (cefRes.value?.status === 'scan_running') {
        setScanRunning(true)
        setCefError('CEF scan is running in the background. Try again shortly.')
      } else {
        setCefData(cefRes.value)
      }
    } else {
      setCefError(cefRes.reason?.message || 'CEF data failed to load.')
    }
    setLoading(false)
  }

  useEffect(() => { loadData() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Re-project from the cached portfolio whenever the slider or the
  // starting capital changes. The backend reuses its own projection
  // model and assumptions, so the slider never invents its own math.
  useEffect(() => {
    if (!divData) return
    setProjLoading(true)
    const t = setTimeout(async () => {
      try {
        const p = await api.dividendPath.project(startCap, monthly)
        if (p?.status === 'scan_running') {
          setProjData(null)
          setScanRunning(true)
        } else if (p?.projection) {
          setProjData(p)
        }
      } catch (e) {
        // Keep the last good projection on screen; the base data is intact.
      } finally {
        setProjLoading(false)
      }
    }, 400)
    return () => clearTimeout(t)
  }, [monthly, startCap, divData]) // eslint-disable-line react-hooks/exhaustive-deps

  async function handleRefresh() {
    setRefreshing(true)
    try {
      await Promise.allSettled([
        api.dividendPath.refresh(startCap, weeklyDca),
        api.cef.refresh(),
      ])
      // Give backends a moment to start, then reload
      await new Promise(r => setTimeout(r, 1200))
      await loadData()
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

  // The displayed projection is the slider projection when available, and
  // falls back to the base scan projection. Every access is guarded, so a
  // missing dividend payload can never crash this tab again.
  const display = projData || divData
  const assumptions = display?.projection_assumptions
  const goalLabel = g => (g ? `${g.month_label} (Year ${g.year})` : 'Not in 10 years')
  const incomeAt = (snaps, month) => {
    if (!snaps || snaps.length === 0) return null
    const exact = snaps.find(s => s.month === month)
    if (exact) return exact.monthly_income
    const before = snaps.filter(s => s.month <= month)
    return (before[before.length - 1] || snaps[snaps.length - 1]).monthly_income
  }

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

      {scanRunning && (
        <div style={{ background: '#1a2744', border: `1px solid ${C.blue}`, borderRadius: '10px', padding: '16px', color: C.blue }}>
          Scan running in the background. Your last saved results will show below once they are ready. Try Refresh in a moment.
        </div>
      )}
      {divError && !scanRunning && (
        <div style={{ background: '#2d1515', border: `1px solid ${C.red}`, borderRadius: '10px', padding: '16px', color: C.red }}>
          Dividend data: {divError}
        </div>
      )}
      {cefError && !scanRunning && (
        <div style={{ background: '#2d1515', border: `1px solid ${C.red}`, borderRadius: '10px', padding: '16px', color: C.red }}>
          CEF data: {cefError}
        </div>
      )}

      {loading && !divData && !cefData && (
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

      {/* Path to $1,000/month projection, driven by the slider */}
      {display?.projection_assumptions && (
        <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: '12px', padding: '20px' }}>
          <h2 style={{ fontSize: '17px', fontWeight: 800, color: C.text, margin: '0 0 4px' }}>Path to $1,000/month, then $2,000/month</h2>
          <p style={{ fontSize: '12px', color: C.muted, margin: '0 0 16px' }}>
            Move the slider to see what a different monthly contribution does. Projections, not guarantees.
          </p>

          <div style={{ marginBottom: '16px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '6px' }}>
              <label style={{ fontSize: '13px', fontWeight: 700, color: C.text }}>Monthly contribution</label>
              <span style={{ fontSize: '18px', fontWeight: 800, color: C.green }}>{fmt$(monthly)} / month</span>
            </div>
            <input
              type="range" min={100} max={2000} step={50} value={monthly}
              onChange={e => setMonthly(Number(e.target.value))}
              style={{ width: '100%', accentColor: '#48bb78' }}
              aria-label="Monthly contribution"
            />
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: C.muted }}>
              <span>$100 / month</span>
              <span>$2,000 / month</span>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(165px, 1fr))', gap: '12px' }}>
            <StatBox label="Mo. income at 1y (base)" value={fmt$d(incomeAt(display?.projection, 12))} color={C.green} />
            <StatBox label="Mo. income at 5y (base)" value={fmt$d(incomeAt(display?.projection, 60))} color={C.green} />
            <StatBox label="Mo. income at 10y (base)" value={fmt$d(incomeAt(display?.projection, 120))} color={C.green} />
            <StatBox label="Mo. income at 10y (bear)" value={fmt$d(incomeAt(display?.projection_bear, 120))} color={C.yellow} />
            <StatBox label="$1,000/mo goal (base)" value={goalLabel(display?.reached_goal_at)} color={C.green} />
            <StatBox label="$2,000/mo goal (base)" value={goalLabel(display?.reached_goal_at_2000)} color={C.green} />
            <StatBox label="$1,000/mo goal (bear)" value={goalLabel(display?.reached_goal_at_bear)} color={C.yellow} />
            <StatBox label="$2,000/mo goal (bear)" value={goalLabel(display?.reached_goal_at_bear_2000)} color={C.yellow} />
          </div>
          {projLoading && <p style={{ fontSize: '12px', color: C.muted, margin: '12px 0 0' }}>Updating projection...</p>}
          <p style={{ fontSize: '12px', color: C.muted, margin: '12px 0 0', lineHeight: 1.5 }}>
            10-year projection. Starting yield {assumptions?.starting_yield_pct}%, dividend growth {assumptions?.base_dividend_growth_pct}% base / {assumptions?.bear_dividend_growth_pct}% bear, ${assumptions?.monthly_contribution}/month added. {assumptions?.excluded_note} Projections assume the same portfolio and yields as the scan above, and are not guarantees.
          </p>

          {portfolio.length > 0 && (
            <div style={{ marginTop: '16px', borderTop: `1px solid ${C.bdr}`, paddingTop: '12px' }}>
              <div style={{ fontSize: '12px', fontWeight: 700, color: C.text, marginBottom: '8px' }}>Where the {fmt$(monthly)} / month goes</div>
              {portfolio.map(h => (
                <div key={h.ticker} style={{ display: 'flex', justifyContent: 'space-between', gap: '10px', fontSize: '12px', color: C.sub, padding: '3px 0' }}>
                  <span><b style={{ color: C.text }}>{h.ticker}</b> {h.name} ({h.allocation_pct}% at {fmtP(h.annual_yield_pct)} yield)</span>
                  <span style={{ whiteSpace: 'nowrap' }}>{fmt$d(monthly * (h.allocation_pct || 0) / 100)} / mo</span>
                </div>
              ))}
            </div>
          )}
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

      {!loading && !divData && !cefData && !divError && !cefError && (
        <div style={{ textAlign: 'center', padding: '40px', color: C.muted }}>
          No income data. Click Refresh to run a scan.
        </div>
      )}
    </div>
  )
}
