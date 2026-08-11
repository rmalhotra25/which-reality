import { useState, useEffect, useCallback } from 'react'

const API = '/api/dividend-path'

// ─── Palette ────────────────────────────────────────────────────────────────
const C = {
  bg:       '#0f1117',
  card:     '#1a1f2e',
  cardBdr:  '#2d3748',
  accent:   '#48bb78',   // green — income / growth
  accentB:  '#63b3ed',   // blue  — info / ETF
  gold:     '#ecc94b',   // gold  — milestone
  muted:    '#718096',
  text:     '#e2e8f0',
  subtext:  '#a0aec0',
  red:      '#fc8181',
  reit:     '#9f7aea',   // purple — REIT
  arist:    '#f6ad55',   // orange — Aristocrat
  etf:      '#63b3ed',   // blue   — ETF
}

const CAT_COLOR = { etf: C.etf, aristocrat: C.arist, reit: C.reit }
const CAT_LABEL = { etf: 'ETF', aristocrat: 'Dividend Aristocrat', reit: 'REIT / BDC' }

// ─── Helpers ─────────────────────────────────────────────────────────────────
const fmt$ = (v) => `$${Number(v || 0).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`
const fmt$d = (v) => `$${Number(v || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
const fmtPct = (v) => `${Number(v || 0).toFixed(2)}%`

// ─── Timeline mini chart (SVG sparkline) ─────────────────────────────────────
function IncomeSparkline({ data, goalLine = 1000 }) {
  if (!data || data.length < 2) return null
  const W = 500, H = 100, PAD = 8
  const months = data.map(d => d.month)
  const incomes = data.map(d => d.monthly_income)
  const maxInc = Math.max(...incomes, goalLine * 1.1)
  const minMo = months[0], maxMo = months[months.length - 1]

  const xScale = (m) => PAD + ((m - minMo) / Math.max(maxMo - minMo, 1)) * (W - PAD * 2)
  const yScale = (v) => H - PAD - (v / maxInc) * (H - PAD * 2)

  const pathD = data.map((d, i) =>
    `${i === 0 ? 'M' : 'L'}${xScale(d.month).toFixed(1)},${yScale(d.monthly_income).toFixed(1)}`
  ).join(' ')

  const goalY = yScale(goalLine)
  const areaD = `${pathD} L${xScale(maxMo)},${H - PAD} L${xScale(minMo)},${H - PAD} Z`

  // Find milestone where goal is reached
  const goalPoint = data.find(d => d.monthly_income >= goalLine)

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: '90px' }}>
      <defs>
        <linearGradient id="incGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={C.accent} stopOpacity="0.4" />
          <stop offset="100%" stopColor={C.accent} stopOpacity="0" />
        </linearGradient>
      </defs>
      {/* Goal line */}
      <line x1={PAD} y1={goalY} x2={W - PAD} y2={goalY} stroke={C.gold} strokeWidth="1" strokeDasharray="4 3" />
      <text x={W - PAD - 2} y={goalY - 3} fontSize="9" fill={C.gold} textAnchor="end">$1K/mo goal</text>
      {/* Area */}
      <path d={areaD} fill="url(#incGrad)" />
      {/* Line */}
      <path d={pathD} fill="none" stroke={C.accent} strokeWidth="2" strokeLinejoin="round" />
      {/* Milestone dot */}
      {goalPoint && (
        <circle cx={xScale(goalPoint.month)} cy={yScale(goalPoint.monthly_income)} r="4"
          fill={C.gold} stroke="#fff" strokeWidth="1.5" />
      )}
    </svg>
  )
}

// ─── Score pill ──────────────────────────────────────────────────────────────
function ScoreBadge({ score }) {
  const color = score >= 75 ? C.accent : score >= 55 ? C.accentB : C.muted
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px',
      background: `${color}22`, border: `1px solid ${color}55`, borderRadius: '6px',
      padding: '2px 8px', fontSize: '12px', fontWeight: 700, color }}>
      {score}
    </span>
  )
}

// ─── Allocation bar ──────────────────────────────────────────────────────────
function AllocBar({ portfolio }) {
  if (!portfolio?.length) return null
  return (
    <div style={{ display: 'flex', height: '10px', borderRadius: '6px', overflow: 'hidden', gap: '2px' }}>
      {portfolio.map(h => (
        <div key={h.ticker}
          title={`${h.ticker} ${h.allocation_pct}%`}
          style={{ flex: h.allocation_pct, background: CAT_COLOR[h.category] || C.muted, minWidth: '2px' }} />
      ))}
    </div>
  )
}

// ─── Holding card ────────────────────────────────────────────────────────────
function HoldingCard({ holding, capitalAmount }) {
  const catColor = CAT_COLOR[holding.category] || C.muted
  const invested = capitalAmount ? (capitalAmount * holding.allocation_pct / 100) : 0
  const shares = invested && holding.price > 0 ? (invested / holding.price).toFixed(2) : '—'
  const monthlyIncome = invested && holding.annual_yield_pct > 0
    ? invested * holding.annual_yield_pct / 100 / 12 : 0

  return (
    <div style={{ background: C.card, border: `1px solid ${C.cardBdr}`, borderRadius: '12px',
      padding: '16px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '18px', fontWeight: 700, color: C.text }}>{holding.ticker}</span>
            <span style={{ fontSize: '11px', fontWeight: 600, color: catColor,
              background: `${catColor}22`, border: `1px solid ${catColor}44`,
              borderRadius: '4px', padding: '1px 6px' }}>
              {CAT_LABEL[holding.category] || holding.category}
            </span>
          </div>
          <div style={{ fontSize: '12px', color: C.muted, marginTop: '2px' }}>{holding.name}</div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: '22px', fontWeight: 700, color: catColor }}>{holding.allocation_pct}%</div>
          <div style={{ fontSize: '11px', color: C.muted }}>allocation</div>
        </div>
      </div>

      {/* Metrics grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px 12px' }}>
        <Metric label="Price" value={fmt$d(holding.price)} />
        <Metric label="Annual Yield" value={fmtPct(holding.annual_yield_pct)} color={C.accent} />
        <Metric label="Div Growth (1Y)" value={`${holding.div_growth_pct > 0 ? '+' : ''}${holding.div_growth_pct?.toFixed(1)}%`}
          color={holding.div_growth_pct >= 0 ? C.accent : C.red} />
        <Metric label="Div Payments" value={`${holding.streak_payments} tracked`} />
        <Metric label="52W High" value={fmt$d(holding.high_52w)} />
        <Metric label="Drawdown" value={`-${holding.drawdown_from_high_pct?.toFixed(1)}%`}
          color={holding.drawdown_from_high_pct > 20 ? C.red : C.subtext} />
      </div>

      {/* Score */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <ScoreBadge score={holding.score} />
        <span style={{ fontSize: '11px', color: C.muted }}>quality score</span>
      </div>

      {/* Invested amount breakdown */}
      {invested > 0 && (
        <div style={{ borderTop: `1px solid ${C.cardBdr}`, paddingTop: '8px',
          display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '6px' }}>
          <Metric label="Invest" value={fmt$(invested)} color={catColor} />
          <Metric label="Shares" value={shares} />
          <Metric label="Mo. Income" value={fmt$d(monthlyIncome)} color={C.accent} />
        </div>
      )}
    </div>
  )
}

function Metric({ label, value, color }) {
  return (
    <div>
      <div style={{ fontSize: '11px', color: C.muted }}>{label}</div>
      <div style={{ fontSize: '13px', fontWeight: 600, color: color || C.text }}>{value}</div>
    </div>
  )
}

// ─── Projection table ─────────────────────────────────────────────────────────
function ProjectionTable({ snapshots, goalMonthly = 1000 }) {
  if (!snapshots?.length) return null
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
        <thead>
          <tr style={{ borderBottom: `1px solid ${C.cardBdr}` }}>
            {['Period', 'Portfolio Value', 'Monthly Income', 'Annual Income', 'Total Invested', 'Gain', 'Yield on Cost'].map(h => (
              <th key={h} style={{ padding: '8px 12px', textAlign: 'right', color: C.muted,
                fontWeight: 600, whiteSpace: 'nowrap', ':first-child': { textAlign: 'left' } }}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {snapshots.map((row, i) => {
            const isGoal = row.monthly_income >= goalMonthly
            return (
              <tr key={i} style={{
                borderBottom: `1px solid ${C.cardBdr}22`,
                background: isGoal ? `${C.gold}10` : 'transparent',
              }}>
                <td style={{ padding: '7px 12px', color: C.text, whiteSpace: 'nowrap' }}>
                  {isGoal && <span style={{ marginRight: '6px' }}>🎯</span>}
                  Yr {row.year} Mo {row.month_of_year}
                </td>
                <td style={{ padding: '7px 12px', textAlign: 'right', color: C.accentB }}>{fmt$(row.portfolio_value)}</td>
                <td style={{ padding: '7px 12px', textAlign: 'right', color: isGoal ? C.gold : C.accent, fontWeight: isGoal ? 700 : 400 }}>
                  {fmt$d(row.monthly_income)}
                </td>
                <td style={{ padding: '7px 12px', textAlign: 'right', color: C.accent }}>{fmt$(row.annual_income)}</td>
                <td style={{ padding: '7px 12px', textAlign: 'right', color: C.muted }}>{fmt$(row.total_contributed)}</td>
                <td style={{ padding: '7px 12px', textAlign: 'right', color: row.growth >= 0 ? C.accent : C.red }}>
                  {row.growth >= 0 ? '+' : ''}{fmt$(row.growth)}
                </td>
                <td style={{ padding: '7px 12px', textAlign: 'right', color: C.subtext }}>{row.yield_on_cost?.toFixed(2)}%</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ─── Lump Sum Panel ───────────────────────────────────────────────────────────
function LumpSumPanel({ portfolio, startingCapital, weeklyDca }) {
  const [amount, setAmount] = useState('')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const handleSubmit = async (e) => {
    e.preventDefault()
    const val = parseFloat(amount.replace(/,/g, ''))
    if (!val || val <= 0) return
    setLoading(true); setError(null)
    try {
      const resp = await fetch(`${API}/lump-sum`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lump_amount: val, starting_capital: startingCapital, weekly_dca: weeklyDca }),
      })
      if (!resp.ok) throw new Error((await resp.json()).detail || 'Error')
      setResult(await resp.json())
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ background: C.card, border: `1px solid ${C.gold}55`, borderRadius: '12px', padding: '20px' }}>
      <div style={{ fontSize: '16px', fontWeight: 700, color: C.gold, marginBottom: '4px' }}>💰 Lump Sum Allocator</div>
      <div style={{ fontSize: '13px', color: C.muted, marginBottom: '16px' }}>
        Got a bonus or windfall? Enter the amount and we'll show you exactly how to deploy it across your portfolio.
      </div>
      <form onSubmit={handleSubmit} style={{ display: 'flex', gap: '10px', alignItems: 'flex-end', flexWrap: 'wrap' }}>
        <div>
          <label style={{ fontSize: '12px', color: C.muted, display: 'block', marginBottom: '4px' }}>Lump Sum Amount ($)</label>
          <input
            type="text"
            value={amount}
            onChange={e => setAmount(e.target.value)}
            placeholder="e.g. 5000"
            style={{ background: '#0f1117', border: `1px solid ${C.cardBdr}`, borderRadius: '6px',
              padding: '8px 12px', color: C.text, fontSize: '14px', width: '160px' }}
          />
        </div>
        <button type="submit" disabled={loading || !amount}
          style={{ padding: '8px 20px', background: loading ? C.muted : C.gold, color: '#000',
            border: 'none', borderRadius: '6px', fontWeight: 700, cursor: loading ? 'not-allowed' : 'pointer',
            fontSize: '14px' }}>
          {loading ? 'Calculating…' : 'Allocate'}
        </button>
      </form>
      {error && <div style={{ color: C.red, marginTop: '10px', fontSize: '13px' }}>{error}</div>}

      {result && (
        <div style={{ marginTop: '20px' }}>
          <div style={{ display: 'flex', gap: '20px', marginBottom: '16px', flexWrap: 'wrap' }}>
            <StatBox label="Total Deployed" value={fmt$(result.lump_amount)} color={C.gold} />
            <StatBox label="Added Monthly Income" value={fmt$d(result.total_added_monthly_income)} color={C.accent} />
            <StatBox label="Added Annual Income" value={fmt$(result.total_added_annual_income)} color={C.accent} />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '10px' }}>
            {result.allocation.map(a => (
              <div key={a.ticker} style={{ background: '#0f1117', border: `1px solid ${C.cardBdr}`,
                borderRadius: '8px', padding: '12px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontWeight: 700, color: C.text }}>{a.ticker}</span>
                  <span style={{ fontSize: '11px', color: CAT_COLOR[a.category] || C.muted,
                    background: `${CAT_COLOR[a.category] || C.muted}22`, padding: '1px 6px', borderRadius: '4px' }}>
                    {a.allocation_pct}%
                  </span>
                </div>
                <div style={{ fontSize: '12px', color: C.muted }}>{a.name}</div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px', marginTop: '4px' }}>
                  <Metric label="Deploy" value={fmt$(a.lump_amount)} color={C.gold} />
                  <Metric label="Shares" value={a.shares_to_buy?.toFixed(3)} />
                  <Metric label="Yield" value={fmtPct(a.annual_yield_pct)} color={C.accent} />
                  <Metric label="Added Mo. Income" value={fmt$d(a.added_monthly_income)} color={C.accent} />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function StatBox({ label, value, color }) {
  return (
    <div style={{ background: '#0f1117', border: `1px solid ${C.cardBdr}`, borderRadius: '8px', padding: '12px 16px' }}>
      <div style={{ fontSize: '11px', color: C.muted }}>{label}</div>
      <div style={{ fontSize: '20px', fontWeight: 700, color: color || C.text }}>{value}</div>
    </div>
  )
}

// ─── Main tab ─────────────────────────────────────────────────────────────────
export default function DividendPathTab() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [showAll, setShowAll] = useState(false)
  const [showProjection, setShowProjection] = useState(false)
  const [startingCapital, setStartingCapital] = useState(61000)
  const [weeklyDca, setWeeklyDca] = useState(500)

  const load = useCallback(async (force = false) => {
    setLoading(true); setError(null)
    try {
      const url = `${API}/recommend?starting_capital=${startingCapital}&weekly_dca=${weeklyDca}${force ? '&force=true' : ''}`
      const resp = await fetch(url)
      if (!resp.ok) throw new Error((await resp.json()).detail || `HTTP ${resp.status}`)
      setData(await resp.json())
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [startingCapital, weeklyDca])

  useEffect(() => { load() }, [load])

  const goalMonth = data?.reached_goal_at
  const monthlyContrib = Math.round(weeklyDca * 52 / 12)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div style={{ background: 'linear-gradient(135deg, #1a2744 0%, #1a1f2e 100%)',
        border: `1px solid ${C.accentB}33`, borderRadius: '12px', padding: '20px 24px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '16px' }}>
          <div>
            <div style={{ fontSize: '22px', fontWeight: 700, color: C.text }}>📈 Dividend Income Path</div>
            <div style={{ fontSize: '13px', color: C.muted, marginTop: '4px' }}>
              Safety-first portfolio engineered to reach <strong style={{ color: C.gold }}>$1,000/month</strong> in passive dividend income
              via DRIP + weekly DCA.
            </div>
          </div>
          <button onClick={() => load(true)} disabled={loading}
            style={{ padding: '8px 16px', background: C.accentB, color: '#000',
              border: 'none', borderRadius: '8px', fontWeight: 700, cursor: loading ? 'not-allowed' : 'pointer',
              fontSize: '13px', opacity: loading ? 0.6 : 1 }}>
            {loading ? '⟳ Scanning…' : '⟳ Refresh'}
          </button>
        </div>

        {/* Input row */}
        <div style={{ display: 'flex', gap: '16px', marginTop: '16px', flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <div>
            <label style={{ fontSize: '11px', color: C.muted, display: 'block', marginBottom: '4px' }}>Starting Capital ($)</label>
            <input type="number" value={startingCapital}
              onChange={e => setStartingCapital(Number(e.target.value))}
              style={{ background: '#0f1117', border: `1px solid ${C.cardBdr}`, borderRadius: '6px',
                padding: '7px 10px', color: C.text, fontSize: '14px', width: '130px' }} />
          </div>
          <div>
            <label style={{ fontSize: '11px', color: C.muted, display: 'block', marginBottom: '4px' }}>Weekly DCA ($)</label>
            <input type="number" value={weeklyDca}
              onChange={e => setWeeklyDca(Number(e.target.value))}
              style={{ background: '#0f1117', border: `1px solid ${C.cardBdr}`, borderRadius: '6px',
                padding: '7px 10px', color: C.text, fontSize: '14px', width: '110px' }} />
          </div>
          <button onClick={() => load(false)} disabled={loading}
            style={{ padding: '7px 16px', background: C.accent, color: '#000',
              border: 'none', borderRadius: '6px', fontWeight: 700, cursor: loading ? 'not-allowed' : 'pointer',
              fontSize: '13px' }}>
            Apply
          </button>
          <div style={{ fontSize: '12px', color: C.muted, alignSelf: 'center' }}>
            ≈ {fmt$(monthlyContrib)}/month contributed
          </div>
        </div>
      </div>

      {/* ── Error ──────────────────────────────────────────────────────── */}
      {error && (
        <div style={{ background: '#2d1515', border: `1px solid ${C.red}`, borderRadius: '10px',
          padding: '16px', color: C.red }}>
          {error}
        </div>
      )}

      {/* ── Loading ────────────────────────────────────────────────────── */}
      {loading && !data && (
        <div style={{ textAlign: 'center', padding: '60px', color: C.muted }}>
          <div style={{ fontSize: '32px', marginBottom: '12px' }}>📊</div>
          <div>Analyzing dividend universe and building your income path…</div>
          <div style={{ fontSize: '12px', marginTop: '6px' }}>This may take 30-60 seconds on first load.</div>
        </div>
      )}

      {data && (
        <>
          {/* ── Goal Summary ─────────────────────────────────────────────── */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: '12px' }}>
            <StatBox label="Starting Capital" value={fmt$(startingCapital)} color={C.accentB} />
            <StatBox label="Monthly DCA" value={fmt$(monthlyContrib)} color={C.accentB} />
            <StatBox label="Blended Yield" value={fmtPct(data.blended_yield_pct)} color={C.accent} />
            <StatBox label="Starting Mo. Income" value={fmt$d(data.starting_monthly_income)} color={C.accent} />
            {goalMonth ? (
              <StatBox label="🎯 Goal Reached"
                value={`Yr ${goalMonth.year}, Mo ${goalMonth.month}`}
                color={C.gold} />
            ) : (
              <StatBox label="Goal Status" value="30Y+ horizon" color={C.muted} />
            )}
          </div>

          {/* ── Allocation Bar ──────────────────────────────────────────── */}
          <div style={{ background: C.card, border: `1px solid ${C.cardBdr}`, borderRadius: '12px', padding: '16px 20px' }}>
            <div style={{ fontSize: '14px', fontWeight: 600, color: C.text, marginBottom: '12px' }}>Portfolio Allocation</div>
            <AllocBar portfolio={data.portfolio} />
            <div style={{ display: 'flex', gap: '16px', marginTop: '10px', flexWrap: 'wrap' }}>
              {data.portfolio?.map(h => (
                <div key={h.ticker} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <span style={{ width: '10px', height: '10px', borderRadius: '2px',
                    background: CAT_COLOR[h.category] || C.muted, display: 'inline-block' }} />
                  <span style={{ fontSize: '12px', color: C.subtext }}>{h.ticker} {h.allocation_pct}%</span>
                </div>
              ))}
            </div>
          </div>

          {/* ── Income Chart ─────────────────────────────────────────────── */}
          <div style={{ background: C.card, border: `1px solid ${C.cardBdr}`, borderRadius: '12px', padding: '16px 20px' }}>
            <div style={{ fontSize: '14px', fontWeight: 600, color: C.text, marginBottom: '4px' }}>Income Growth Trajectory</div>
            <div style={{ fontSize: '12px', color: C.muted, marginBottom: '10px' }}>
              Monthly dividend income over time (DRIP + ${weeklyDca}/week DCA)
            </div>
            <IncomeSparkline data={data.projection} goalLine={1000} />
          </div>

          {/* ── Portfolio Cards ───────────────────────────────────────────── */}
          <div>
            <div style={{ fontSize: '16px', fontWeight: 700, color: C.text, marginBottom: '12px' }}>
              Recommended Portfolio — 6 Holdings
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: '14px' }}>
              {data.portfolio?.map(h => (
                <HoldingCard key={h.ticker} holding={h} capitalAmount={startingCapital} />
              ))}
            </div>
          </div>

          {/* ── Lump Sum ──────────────────────────────────────────────────── */}
          <LumpSumPanel portfolio={data.portfolio} startingCapital={startingCapital} weeklyDca={weeklyDca} />

          {/* ── Projection Table ──────────────────────────────────────────── */}
          <div style={{ background: C.card, border: `1px solid ${C.cardBdr}`, borderRadius: '12px', overflow: 'hidden' }}>
            <div style={{ padding: '16px 20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <div style={{ fontSize: '14px', fontWeight: 600, color: C.text }}>DRIP + DCA Projection</div>
                <div style={{ fontSize: '12px', color: C.muted, marginTop: '2px' }}>
                  Every 6-month snapshot — assumes {fmtPct(data.blended_yield_pct)} blended yield, 5% annual price appreciation, DRIP reinvestment
                </div>
              </div>
              <button onClick={() => setShowProjection(s => !s)}
                style={{ padding: '6px 14px', background: 'transparent', border: `1px solid ${C.cardBdr}`,
                  borderRadius: '6px', color: C.subtext, cursor: 'pointer', fontSize: '13px' }}>
                {showProjection ? 'Hide' : 'Show Projection'}
              </button>
            </div>
            {showProjection && (
              <div style={{ borderTop: `1px solid ${C.cardBdr}` }}>
                <ProjectionTable snapshots={data.projection} goalMonthly={1000} />
              </div>
            )}
          </div>

          {/* ── Top Candidates ────────────────────────────────────────────── */}
          {data.top_candidates?.length > 0 && (
            <div style={{ background: C.card, border: `1px solid ${C.cardBdr}`, borderRadius: '12px', overflow: 'hidden' }}>
              <div style={{ padding: '16px 20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ fontSize: '14px', fontWeight: 600, color: C.text }}>
                  Full Ranked Candidates ({data.scored_count} scored)
                </div>
                <button onClick={() => setShowAll(s => !s)}
                  style={{ padding: '6px 14px', background: 'transparent', border: `1px solid ${C.cardBdr}`,
                    borderRadius: '6px', color: C.subtext, cursor: 'pointer', fontSize: '13px' }}>
                  {showAll ? 'Collapse' : 'View All'}
                </button>
              </div>
              {showAll && (
                <div style={{ borderTop: `1px solid ${C.cardBdr}`, overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
                    <thead>
                      <tr style={{ borderBottom: `1px solid ${C.cardBdr}` }}>
                        {['#', 'Ticker', 'Name', 'Category', 'Score', 'Yield', 'Div Growth', 'Streak', 'Drawdown'].map(h => (
                          <th key={h} style={{ padding: '8px 12px', textAlign: h === 'Name' || h === '#' || h === 'Ticker' || h === 'Category' ? 'left' : 'right',
                            color: C.muted, fontWeight: 600, whiteSpace: 'nowrap' }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {data.top_candidates.map((c, i) => (
                        <tr key={c.ticker} style={{ borderBottom: `1px solid ${C.cardBdr}22` }}>
                          <td style={{ padding: '7px 12px', color: C.muted }}>{i + 1}</td>
                          <td style={{ padding: '7px 12px', fontWeight: 700, color: C.text }}>{c.ticker}</td>
                          <td style={{ padding: '7px 12px', color: C.subtext }}>{c.name}</td>
                          <td style={{ padding: '7px 12px' }}>
                            <span style={{ fontSize: '11px', color: CAT_COLOR[c.category],
                              background: `${CAT_COLOR[c.category]}22`, padding: '1px 6px', borderRadius: '4px' }}>
                              {CAT_LABEL[c.category] || c.category}
                            </span>
                          </td>
                          <td style={{ padding: '7px 12px', textAlign: 'right' }}><ScoreBadge score={c.score} /></td>
                          <td style={{ padding: '7px 12px', textAlign: 'right', color: C.accent }}>{fmtPct(c.annual_yield_pct)}</td>
                          <td style={{ padding: '7px 12px', textAlign: 'right', color: c.div_growth_pct >= 0 ? C.accent : C.red }}>
                            {c.div_growth_pct > 0 ? '+' : ''}{c.div_growth_pct?.toFixed(1)}%
                          </td>
                          <td style={{ padding: '7px 12px', textAlign: 'right', color: C.subtext }}>{c.streak_payments}</td>
                          <td style={{ padding: '7px 12px', textAlign: 'right', color: c.drawdown_from_high_pct > 20 ? C.red : C.subtext }}>
                            -{c.drawdown_from_high_pct?.toFixed(1)}%
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {/* ── Footer ────────────────────────────────────────────────────── */}
          <div style={{ fontSize: '12px', color: C.muted, textAlign: 'center', paddingBottom: '8px' }}>
            Price and dividend data via Polygon. Projections assume constant DRIP reinvestment, 5% annual price appreciation,
            and dividend growth per historical rate. Past performance does not guarantee future results.
            Scanned {data.scanned_at ? new Date(data.scanned_at).toLocaleString() : '—'}.
          </div>
        </>
      )}
    </div>
  )
}
