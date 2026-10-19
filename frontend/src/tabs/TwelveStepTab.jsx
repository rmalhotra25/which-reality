import { useState, useCallback, useMemo } from 'react'
import { api } from '../api'

// ─── Palette ──────────────────────────────────────────────────────────────────
const C = {
  bg: '#0f1117', card: '#1a1f2e', cardAlt: '#141824',
  border: '#2d3748', borderLight: '#3d4f6b',
  text: '#e2e8f0', muted: '#718096', faint: '#4a5568',
  accent: '#63b3ed', accentDim: '#2b4c6f',
  green: '#68d391', greenDim: '#1a3a26', greenBorder: '#2d5a3a',
  yellow: '#f6e05e', yellowDim: '#3a3000', yellowBorder: '#5a4a00',
  red: '#fc8181', redDim: '#3a1515', redBorder: '#5a2020',
  purple: '#b794f4', purpleDim: '#2d1f4a',
}

// ─── Step definitions ─────────────────────────────────────────────────────────
const STEPS = [
  {
    num: 1, title: 'Shares Outstanding', icon: '📊',
    brief: 'Is management returning value (buybacks) or diluting shareholders?',
    detail: 'Companies that consistently buy back shares treat shareholders as partners. Constant share issuance erodes your ownership stake.',
    metric: 'Share count trend (annual)',
  },
  {
    num: 2, title: 'Revenue Growth', icon: '📈',
    brief: 'Is the top line growing consistently year over year?',
    detail: 'Revenue growth is the engine. We want consistent double-digit growth or at least steady improvement in the trend.',
    metric: 'YoY revenue growth %',
  },
  {
    num: 3, title: 'Gross Margin', icon: '💎',
    brief: 'Does the company keep most of what it earns per sale?',
    detail: 'High gross margins (>40%) indicate pricing power and/or low cost of goods. This is the hallmark of quality businesses.',
    metric: 'Gross profit / Revenue',
  },
  {
    num: 4, title: 'Operating Margin', icon: '⚙️',
    brief: 'Is the business operationally profitable after all costs?',
    detail: 'Operating margin shows how well management converts revenue into profit before interest and taxes. Positive and growing is the goal.',
    metric: 'Operating income / Revenue',
  },
  {
    num: 5, title: 'Net Income', icon: '💵',
    brief: 'Is the bottom line positive and growing?',
    detail: 'Net income is the ultimate profitability check. Growth companies may be negative here temporarily — assess the trend.',
    metric: 'Net income (absolute + trend)',
  },
  {
    num: 6, title: 'Free Cash Flow', icon: '💰',
    brief: 'Is the business generating real cash after capex? (Never auto-fails)',
    detail: 'FCF is Tom Nash\'s most important metric — the "real" profit. Even great growth companies may have negative FCF while investing heavily. Never dismiss a stock on this alone.',
    metric: 'Operating cash flow − Capex',
    neverFails: true,
  },
  {
    num: 7, title: 'Debt Level', icon: '🏦',
    brief: 'Is the debt load manageable relative to cash generation?',
    detail: 'Total debt < 3× annual FCF is comfortable. Above 5× becomes dangerous, especially if rates rise or growth slows.',
    metric: 'Total debt / Annual FCF',
  },
  {
    num: 8, title: 'Cash vs Debt', icon: '🛡️',
    brief: 'Does the company hold more cash than it owes?',
    detail: 'A net cash position (cash > debt) is a fortress balance sheet. It means the business can self-fund, make acquisitions, or weather downturns.',
    metric: 'Cash − Total debt',
  },
  {
    num: 9, title: 'Revenue vs Expense Growth', icon: '📉',
    brief: 'Is revenue growing faster than costs? (Operating leverage)',
    detail: 'When revenue grows faster than costs, margins expand — that\'s the sign of a scalable business. The opposite means margin compression.',
    metric: 'Revenue growth % vs cost growth %',
  },
  {
    num: 10, title: 'PEG Ratio', icon: '🎯',
    brief: 'Are you paying a fair price relative to the company\'s growth?',
    detail: 'PEG = P/E ÷ growth rate. Below 1.5 is generally attractive. Above 3 means you\'re paying a steep premium for growth that may not materialise.',
    metric: 'P/E ÷ Revenue/EPS growth rate',
  },
  {
    num: 11, title: 'Competitive Moat', icon: '🏰',
    brief: 'What durable advantages protect this business from competitors?',
    detail: 'Select the moat factors that genuinely apply. Strong moats sustain high margins and ROICs over decades. Be honest — not every checkbox deserves a tick.',
    metric: 'Manual assessment',
  },
  {
    num: 12, title: 'Intrinsic Value (DCF)', icon: '🔮',
    brief: 'What is the stock worth, and is it trading at a discount?',
    detail: 'A 5-year discounted cash flow with terminal value. Aim for a 30%+ margin of safety. Inputs are estimates — tweak growth rate and discount rate to stress-test.',
    metric: 'DCF per share vs current price',
  },
]

const MOAT_FACTORS = [
  { id: 'brand', label: 'Brand Power', desc: 'Customers pay a premium for the name' },
  { id: 'network', label: 'Network Effects', desc: 'More users → more valuable (e.g. social, payments)' },
  { id: 'switching', label: 'Switching Costs', desc: 'High pain or cost for customers to leave' },
  { id: 'patents', label: 'Patents / IP', desc: 'Protected technology or unique IP portfolio' },
  { id: 'cost', label: 'Cost Leadership', desc: 'Structurally lowest-cost producer' },
  { id: 'regulatory', label: 'Regulatory Moat', desc: 'Licenses, approvals, or market access barriers' },
  { id: 'scale', label: 'Economies of Scale', desc: 'Fixed costs spread over massive volume' },
  { id: 'lock_in', label: 'Customer Lock-in', desc: 'Long-term contracts or data dependency' },
]

const SECTORS = [
  'Technology', 'Healthcare', 'Financials', 'Consumer Discretionary',
  'Industrials', 'Communication Services', 'Consumer Staples',
  'Energy', 'Real Estate', 'Materials', 'Utilities',
]

const STORAGE_KEY = 'twelve_step_analyses_v1'

// ─── DCF Math ─────────────────────────────────────────────────────────────────
function computeDCFPerShare(avgRevenue, fwdGrowthRate, fcfMarginPct, discountRate, shares, netCash) {
  if (!avgRevenue || !fcfMarginPct || !discountRate || !shares || shares <= 0) return null
  if (discountRate <= 4) return null
  const g = fwdGrowthRate / 100
  const fcfM = fcfMarginPct / 100
  const dr = discountRate / 100
  let pv = 0
  let rev = avgRevenue
  for (let t = 1; t <= 5; t++) {
    rev *= (1 + g)
    pv += (rev * fcfM) / Math.pow(1 + dr, t)
  }
  const terminal = (rev * fcfM * 1.04) / (dr - 0.04) / Math.pow(1 + dr, 5)
  return (pv + terminal + (netCash || 0)) / shares
}

function computeImpliedGrowth(targetPrice, avgRevenue, fcfMarginPct, discountRate, shares, netCash) {
  if (!targetPrice || !avgRevenue || !fcfMarginPct || !shares) return null
  let lo = -30, hi = 100
  for (let i = 0; i < 60; i++) {
    const mid = (lo + hi) / 2
    const val = computeDCFPerShare(avgRevenue, mid, fcfMarginPct, discountRate, shares, netCash)
    if (val === null) return null
    if (val > targetPrice) hi = mid
    else lo = mid
  }
  return (lo + hi) / 2
}

// ─── Auto-evaluation logic ────────────────────────────────────────────────────
function evaluateStep(num, data) {
  const annual = data.annual || []
  const ttm = data.ttm || {}

  const annualDesc = (years) => annual.slice(0, years).map(y => y.period).join(', ')

  if (num === 1) {
    const rows = annual.filter(r => r.shares != null).slice(0, 4)
    if (rows.length < 2) return { status: 'warn', reason: 'Insufficient share count history', details: {} }
    const newest = rows[0].shares, oldest = rows[rows.length - 1].shares
    const years = rows.length - 1
    const annualChange = ((newest - oldest) / oldest / years) * 100
    if (annualChange <= -0.5) return { status: 'pass', reason: `Share count shrinking ${Math.abs(annualChange).toFixed(1)}%/yr — buybacks in progress`, details: { annualChange } }
    if (annualChange <= 2) return { status: 'warn', reason: `Mild dilution: +${annualChange.toFixed(1)}%/yr`, details: { annualChange } }
    return { status: 'fail', reason: `Heavy dilution: +${annualChange.toFixed(1)}%/yr`, details: { annualChange } }
  }

  if (num === 2) {
    const g = ttm.revenue_growth_yoy
    if (g == null) return { status: 'warn', reason: 'Revenue growth data unavailable', details: {} }
    const pct = g * 100
    if (pct >= 10) return { status: 'pass', reason: `Strong growth: +${pct.toFixed(1)}% YoY`, details: { pct } }
    if (pct >= 0) return { status: 'warn', reason: `Slow growth: +${pct.toFixed(1)}% YoY`, details: { pct } }
    return { status: 'fail', reason: `Revenue declining: ${pct.toFixed(1)}% YoY`, details: { pct } }
  }

  if (num === 3) {
    const gm = ttm.gross_margin
    if (gm == null) {
      const row = annual[0]
      if (row && row.revenue && row.gross_profit) {
        const pct = (row.gross_profit / row.revenue) * 100
        if (pct >= 40) return { status: 'pass', reason: `Excellent gross margin: ${pct.toFixed(1)}%`, details: { pct } }
        if (pct >= 25) return { status: 'warn', reason: `Moderate gross margin: ${pct.toFixed(1)}%`, details: { pct } }
        return { status: 'fail', reason: `Low gross margin: ${pct.toFixed(1)}%`, details: { pct } }
      }
      return { status: 'warn', reason: 'Gross margin data unavailable', details: {} }
    }
    if (gm >= 40) return { status: 'pass', reason: `Excellent gross margin: ${gm.toFixed(1)}%`, details: { gm } }
    if (gm >= 25) return { status: 'warn', reason: `Moderate gross margin: ${gm.toFixed(1)}%`, details: { gm } }
    return { status: 'fail', reason: `Low gross margin: ${gm.toFixed(1)}%`, details: { gm } }
  }

  if (num === 4) {
    const om = ttm.operating_margin
    if (om == null) return { status: 'warn', reason: 'Operating margin data unavailable', details: {} }
    if (om >= 15) return { status: 'pass', reason: `Strong operating margin: ${om.toFixed(1)}%`, details: { om } }
    if (om >= 5) return { status: 'warn', reason: `Thin operating margin: ${om.toFixed(1)}%`, details: { om } }
    return { status: 'fail', reason: `Negative/near-zero operating margin: ${om.toFixed(1)}%`, details: { om } }
  }

  if (num === 5) {
    const rows = annual.filter(r => r.net_income != null).slice(0, 3)
    if (!rows.length) {
      const nm = ttm.net_margin
      if (nm == null) return { status: 'warn', reason: 'Net income data unavailable', details: {} }
      if (nm > 0) return { status: 'pass', reason: `Profitable: ${nm.toFixed(1)}% net margin`, details: {} }
      return { status: 'fail', reason: `Net loss: ${nm.toFixed(1)}% net margin`, details: {} }
    }
    const positive = rows.filter(r => r.net_income > 0).length
    const trend = rows.length >= 2 ? rows[0].net_income - rows[rows.length - 1].net_income : 0
    if (positive === rows.length && trend >= 0) return { status: 'pass', reason: `Profitable and growing (${annualDesc(rows.length)})`, details: {} }
    if (positive > 0) return { status: 'warn', reason: `Mixed profitability — ${positive}/${rows.length} profitable years`, details: {} }
    return { status: 'fail', reason: 'Net losses across all available years', details: {} }
  }

  if (num === 6) {
    const rows = annual.filter(r => r.free_cash_flow != null).slice(0, 3)
    if (!rows.length) {
      const fcfM = ttm.fcf_margin
      if (fcfM == null) return { status: 'warn', reason: 'FCF data unavailable — review separately', details: {} }
      if (fcfM > 0) return { status: 'pass', reason: `Positive FCF margin: ${fcfM.toFixed(1)}%`, details: {} }
      return { status: 'warn', reason: `Negative FCF margin: ${fcfM.toFixed(1)}%. Acceptable if reinvesting heavily.`, details: {} }
    }
    const positive = rows.filter(r => r.free_cash_flow > 0).length
    if (positive === rows.length) return { status: 'pass', reason: `Consistently FCF positive (${annualDesc(rows.length)})`, details: {} }
    return { status: 'warn', reason: `FCF occasionally negative — common in high-growth phase`, details: {} }
  }

  if (num === 7) {
    const row = annual.find(r => r.total_debt != null && r.free_cash_flow != null)
    if (!row) return { status: 'warn', reason: 'Debt/FCF data unavailable', details: {} }
    if (row.free_cash_flow <= 0) return { status: 'warn', reason: `FCF negative — debt ratio unmeasurable`, details: {} }
    const ratio = row.total_debt / row.free_cash_flow
    if (ratio < 3) return { status: 'pass', reason: `Debt is ${ratio.toFixed(1)}× FCF — comfortable`, details: { ratio } }
    if (ratio < 5) return { status: 'warn', reason: `Debt is ${ratio.toFixed(1)}× FCF — elevated`, details: { ratio } }
    return { status: 'fail', reason: `Debt is ${ratio.toFixed(1)}× FCF — dangerous`, details: { ratio } }
  }

  if (num === 8) {
    const row = annual.find(r => r.cash != null && r.total_debt != null)
    if (!row) return { status: 'warn', reason: 'Balance sheet data unavailable', details: {} }
    const netCash = row.cash - row.total_debt
    const fmt = (v) => v >= 1e9 ? `$${(v / 1e9).toFixed(1)}B` : `$${(v / 1e6).toFixed(0)}M`
    if (netCash >= 0) return { status: 'pass', reason: `Net cash positive: ${fmt(netCash)}`, details: { netCash } }
    const pct = Math.abs(netCash) / (data.market_cap || 1) * 100
    if (pct < 20) return { status: 'warn', reason: `Modest net debt: ${fmt(Math.abs(netCash))} (${pct.toFixed(0)}% of mkt cap)`, details: { netCash } }
    return { status: 'fail', reason: `Heavy net debt: ${fmt(Math.abs(netCash))} (${pct.toFixed(0)}% of mkt cap)`, details: { netCash } }
  }

  if (num === 9) {
    const rows = annual.filter(r =>
      r.revenue != null && r.cost_of_revenue != null
    ).slice(0, 3)
    if (rows.length < 2) {
      const revG = ttm.revenue_growth_yoy
      const om = (ttm.operating_margin || 0)
      const prevOm = annual[0]?.operating_income && annual[0]?.revenue
        ? (annual[0].operating_income / annual[0].revenue * 100)
        : null
      if (revG != null && prevOm != null) {
        if (om > prevOm) return { status: 'pass', reason: `Margins expanding — operating leverage at work`, details: {} }
        return { status: 'warn', reason: `Margins compressing — expenses outpacing revenue`, details: {} }
      }
      return { status: 'warn', reason: 'Insufficient data to compare revenue vs cost growth', details: {} }
    }
    const newest = rows[0], oldest = rows[rows.length - 1]
    const revGrowth = (newest.revenue - oldest.revenue) / oldest.revenue
    const costGrowth = ((newest.cost_of_revenue) - (oldest.cost_of_revenue)) / (oldest.cost_of_revenue)
    if (revGrowth > costGrowth + 0.01) return { status: 'pass', reason: `Revenue +${(revGrowth * 100).toFixed(0)}% vs costs +${(costGrowth * 100).toFixed(0)}% — expanding margins`, details: {} }
    if (revGrowth >= costGrowth - 0.01) return { status: 'warn', reason: `Revenue and costs growing at similar rate`, details: {} }
    return { status: 'fail', reason: `Costs +${(costGrowth * 100).toFixed(0)}% outpacing revenue +${(revGrowth * 100).toFixed(0)}%`, details: {} }
  }

  if (num === 10) {
    const pe = ttm.pe
    const growthRaw = ttm.revenue_growth_yoy ?? ttm.revenue_growth_5y
    if (!pe || pe <= 0) return { status: 'warn', reason: 'No positive P/E — cannot compute PEG', details: {} }
    if (!growthRaw) return { status: 'warn', reason: 'Growth rate unavailable for PEG', details: {} }
    const growth = Math.abs(growthRaw * 100)
    if (growth < 1) return { status: 'warn', reason: 'Near-zero growth makes PEG unreliable', details: {} }
    const peg = pe / growth
    if (peg < 1.5) return { status: 'pass', reason: `PEG ${peg.toFixed(2)} — attractive price for the growth`, details: { peg, pe, growth } }
    if (peg < 3) return { status: 'warn', reason: `PEG ${peg.toFixed(2)} — moderate premium`, details: { peg, pe, growth } }
    return { status: 'fail', reason: `PEG ${peg.toFixed(2)} — expensive vs growth rate`, details: { peg, pe, growth } }
  }

  return { status: null, reason: 'Manual assessment required', details: {} }
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function fmtNum(v, decimals = 1) {
  if (v == null || isNaN(v)) return '—'
  if (Math.abs(v) >= 1e12) return `${(v / 1e12).toFixed(decimals)}T`
  if (Math.abs(v) >= 1e9) return `${(v / 1e9).toFixed(decimals)}B`
  if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(decimals)}M`
  if (Math.abs(v) >= 1e3) return `${(v / 1e3).toFixed(decimals)}K`
  return v.toFixed(decimals)
}

function statusColor(s) {
  if (s === 'pass') return C.green
  if (s === 'fail') return C.red
  if (s === 'warn') return C.yellow
  return C.muted
}
function statusBg(s) {
  if (s === 'pass') return C.greenDim
  if (s === 'fail') return C.redDim
  if (s === 'warn') return C.yellowDim
  return '#1a1f2e'
}
function statusBorder(s) {
  if (s === 'pass') return C.greenBorder
  if (s === 'fail') return C.redBorder
  if (s === 'warn') return C.yellowBorder
  return C.border
}
function statusIcon(s) {
  if (s === 'pass') return '✓'
  if (s === 'fail') return '✗'
  if (s === 'warn') return '~'
  return '○'
}

function loadAnalyses() {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]') } catch { return [] }
}
function saveAnalysis(analysis) {
  try {
    const all = loadAnalyses().filter(a => a.id !== analysis.id)
    all.unshift(analysis)
    localStorage.setItem(STORAGE_KEY, JSON.stringify(all.slice(0, 20)))
  } catch { /* noop */ }
}

// ─── Mini components ──────────────────────────────────────────────────────────
function Chip({ label, color = C.muted, bg = C.card, border = C.border }) {
  return (
    <span style={{
      display: 'inline-block', padding: '2px 8px', borderRadius: '12px',
      fontSize: '11px', fontWeight: 600, color, background: bg,
      border: `1px solid ${border}`, whiteSpace: 'nowrap',
    }}>{label}</span>
  )
}

function StatusBadge({ status }) {
  if (!status) return <Chip label="○ Pending" />
  const labels = { pass: '✓ Pass', fail: '✗ Fail', warn: '~ Caution', skip: '→ Skip' }
  return (
    <Chip
      label={labels[status] || status}
      color={statusColor(status)}
      bg={statusBg(status)}
      border={statusBorder(status)}
    />
  )
}

function MetricRow({ label, value, sub, highlight }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', padding: '8px 0', borderBottom: `1px solid ${C.border}` }}>
      <span style={{ color: C.muted, fontSize: '13px' }}>{label}</span>
      <div style={{ textAlign: 'right' }}>
        <span style={{ color: highlight || C.text, fontWeight: 600, fontSize: '14px' }}>{value}</span>
        {sub && <div style={{ color: C.faint, fontSize: '11px' }}>{sub}</div>}
      </div>
    </div>
  )
}

function AnnualTable({ annual, keys, labels, formatter, colorFn }) {
  if (!annual || !annual.length) return <p style={{ color: C.muted, fontSize: '13px' }}>No historical data available.</p>
  const rows = annual.slice(0, 5)
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
        <thead>
          <tr style={{ color: C.muted }}>
            <th style={{ textAlign: 'left', padding: '4px 8px', borderBottom: `1px solid ${C.border}` }}>Year</th>
            {keys.map((k, i) => (
              <th key={k} style={{ textAlign: 'right', padding: '4px 8px', borderBottom: `1px solid ${C.border}` }}>{labels[i]}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(r => (
            <tr key={r.period}>
              <td style={{ padding: '4px 8px', color: C.muted, borderBottom: `1px solid ${C.border}` }}>{r.period}</td>
              {keys.map(k => {
                const val = r[k]
                const color = colorFn ? colorFn(k, val) : C.text
                return (
                  <td key={k} style={{ padding: '4px 8px', textAlign: 'right', color, borderBottom: `1px solid ${C.border}`, fontVariantNumeric: 'tabular-nums' }}>
                    {val == null ? '—' : (formatter ? formatter(k, val) : fmtNum(val))}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ─── Step data renderers ──────────────────────────────────────────────────────
function Step1Data({ data }) {
  const rows = (data.annual || []).filter(r => r.shares != null).slice(0, 5)
  const ttmShares = data.shares_outstanding
  return (
    <div>
      {ttmShares && (
        <MetricRow label="Current shares outstanding" value={`${fmtNum(ttmShares * 1e6, 2)} shares`} />
      )}
      <AnnualTable
        annual={rows}
        keys={['shares']}
        labels={['Diluted shares']}
        formatter={(k, v) => fmtNum(v, 2)}
        colorFn={(k, v) => C.text}
      />
    </div>
  )
}

function Step2Data({ data }) {
  const g = data.ttm?.revenue_growth_yoy
  const g5 = data.ttm?.revenue_growth_5y
  return (
    <div>
      {g != null && <MetricRow label="TTM Revenue Growth YoY" value={`${(g * 100).toFixed(1)}%`} highlight={g >= 0.10 ? C.green : g >= 0 ? C.yellow : C.red} />}
      {g5 != null && <MetricRow label="5-Year Revenue CAGR" value={`${(g5 * 100).toFixed(1)}%`} />}
      <AnnualTable
        annual={data.annual}
        keys={['revenue']}
        labels={['Revenue']}
        formatter={(k, v) => `$${fmtNum(v)}`}
      />
    </div>
  )
}

function Step3Data({ data }) {
  const gm = data.ttm?.gross_margin
  return (
    <div>
      {gm != null && <MetricRow label="TTM Gross Margin" value={`${gm.toFixed(1)}%`} highlight={gm >= 40 ? C.green : gm >= 25 ? C.yellow : C.red} />}
      <AnnualTable
        annual={data.annual}
        keys={['revenue', 'gross_profit']}
        labels={['Revenue', 'Gross Profit']}
        formatter={(k, v) => `$${fmtNum(v)}`}
      />
    </div>
  )
}

function Step4Data({ data }) {
  const om = data.ttm?.operating_margin
  return (
    <div>
      {om != null && <MetricRow label="TTM Operating Margin" value={`${om.toFixed(1)}%`} highlight={om >= 15 ? C.green : om >= 5 ? C.yellow : C.red} />}
      <AnnualTable
        annual={data.annual}
        keys={['revenue', 'operating_income']}
        labels={['Revenue', 'Operating Income']}
        formatter={(k, v) => `$${fmtNum(v)}`}
        colorFn={(k, v) => k === 'operating_income' ? (v > 0 ? C.green : C.red) : C.text}
      />
    </div>
  )
}

function Step5Data({ data }) {
  const nm = data.ttm?.net_margin
  return (
    <div>
      {nm != null && <MetricRow label="TTM Net Margin" value={`${nm.toFixed(1)}%`} highlight={nm > 0 ? C.green : C.red} />}
      <AnnualTable
        annual={data.annual}
        keys={['revenue', 'net_income']}
        labels={['Revenue', 'Net Income']}
        formatter={(k, v) => `$${fmtNum(v)}`}
        colorFn={(k, v) => k === 'net_income' ? (v > 0 ? C.green : C.red) : C.text}
      />
    </div>
  )
}

function Step6Data({ data }) {
  const fcfM = data.ttm?.fcf_margin
  const fcf = data.ttm?.free_cash_flow
  return (
    <div>
      {fcfM != null && <MetricRow label="TTM FCF Margin" value={`${fcfM.toFixed(1)}%`} highlight={fcfM > 0 ? C.green : C.yellow} />}
      {fcf != null && <MetricRow label="TTM Free Cash Flow" value={`$${fmtNum(fcf)}`} highlight={fcf > 0 ? C.green : C.yellow} />}
      <AnnualTable
        annual={data.annual}
        keys={['operating_cash_flow', 'capex', 'free_cash_flow']}
        labels={['Op. Cash Flow', 'Capex', 'FCF']}
        formatter={(k, v) => `$${fmtNum(v)}`}
        colorFn={(k, v) => k === 'free_cash_flow' ? (v > 0 ? C.green : C.yellow) : C.text}
      />
    </div>
  )
}

function Step7Data({ data }) {
  return (
    <div>
      <AnnualTable
        annual={data.annual}
        keys={['free_cash_flow', 'total_debt']}
        labels={['FCF', 'Total Debt']}
        formatter={(k, v) => `$${fmtNum(v)}`}
        colorFn={(k, v) => k === 'free_cash_flow' ? (v > 0 ? C.green : C.yellow) : C.text}
      />
    </div>
  )
}

function Step8Data({ data }) {
  return (
    <div>
      <AnnualTable
        annual={data.annual}
        keys={['cash', 'total_debt']}
        labels={['Cash', 'Total Debt']}
        formatter={(k, v) => `$${fmtNum(v)}`}
        colorFn={(k, v) => {
          if (k === 'cash') return C.green
          return C.text
        }}
      />
    </div>
  )
}

function Step9Data({ data }) {
  return (
    <div>
      <AnnualTable
        annual={data.annual}
        keys={['revenue', 'cost_of_revenue']}
        labels={['Revenue', 'Cost of Revenue']}
        formatter={(k, v) => `$${fmtNum(v)}`}
      />
    </div>
  )
}

function Step10Data({ data }) {
  const pe = data.ttm?.pe
  const g = data.ttm?.revenue_growth_yoy ?? data.ttm?.revenue_growth_5y
  const peg = pe && g && Math.abs(g * 100) > 0.5 ? pe / Math.abs(g * 100) : null
  const eps5y = data.ttm?.eps_growth_5y
  return (
    <div>
      {pe != null && <MetricRow label="P/E Ratio (TTM)" value={pe > 0 ? pe.toFixed(1) : 'N/A (negative earnings)'} highlight={pe > 0 && pe < 30 ? C.green : pe > 0 ? C.yellow : C.red} />}
      {g != null && <MetricRow label="Revenue Growth YoY" value={`${(g * 100).toFixed(1)}%`} />}
      {eps5y != null && <MetricRow label="EPS Growth 5Y" value={`${(eps5y * 100).toFixed(1)}%`} />}
      {peg != null && <MetricRow label="PEG Ratio" value={peg.toFixed(2)} highlight={peg < 1.5 ? C.green : peg < 3 ? C.yellow : C.red} />}
    </div>
  )
}

function Step11Data({ moatFactors, setMoatFactors }) {
  return (
    <div>
      <p style={{ color: C.muted, fontSize: '13px', marginBottom: '12px' }}>
        Select all moat factors that genuinely apply. Be conservative — only check if you can articulate why this specific company benefits.
      </p>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
        {MOAT_FACTORS.map(f => {
          const checked = moatFactors.includes(f.id)
          return (
            <label
              key={f.id}
              onClick={() => setMoatFactors(prev => checked ? prev.filter(x => x !== f.id) : [...prev, f.id])}
              style={{
                display: 'flex', gap: '10px', alignItems: 'flex-start',
                padding: '10px 12px', borderRadius: '8px', cursor: 'pointer',
                background: checked ? C.accentDim : C.cardAlt,
                border: `1px solid ${checked ? C.accent : C.border}`,
              }}
            >
              <span style={{ color: checked ? C.accent : C.faint, fontSize: '16px', flexShrink: 0, marginTop: '1px' }}>
                {checked ? '☑' : '☐'}
              </span>
              <div>
                <div style={{ color: checked ? C.accent : C.text, fontSize: '13px', fontWeight: 600 }}>{f.label}</div>
                <div style={{ color: C.muted, fontSize: '11px', marginTop: '2px' }}>{f.desc}</div>
              </div>
            </label>
          )
        })}
      </div>
      <div style={{ marginTop: '12px', padding: '10px', background: C.cardAlt, borderRadius: '6px', border: `1px solid ${C.border}` }}>
        <span style={{ color: C.muted, fontSize: '12px' }}>Selected: </span>
        <span style={{ color: moatFactors.length >= 3 ? C.green : moatFactors.length >= 1 ? C.yellow : C.red, fontWeight: 600, fontSize: '13px' }}>
          {moatFactors.length} / {MOAT_FACTORS.length} factors
        </span>
        <span style={{ color: C.muted, fontSize: '12px' }}>
          {moatFactors.length >= 3 ? ' — Strong moat' : moatFactors.length >= 1 ? ' — Partial moat' : ' — No clear moat'}
        </span>
      </div>
    </div>
  )
}

function Step12Data({ data, dcfInputs, setDcfInputs, dcfResult }) {
  const latestAnnual = (data.annual || [])[0] || {}
  const price = data.current_price

  return (
    <div>
      <p style={{ color: C.muted, fontSize: '12px', marginBottom: '12px' }}>
        Adjust the inputs below. Pre-filled from fetched data — modify to match your conviction.
      </p>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginBottom: '16px' }}>
        {[
          { key: 'avgRevenue', label: 'Last Annual Revenue ($)', step: 1e8, hint: 'Use the most recent annual revenue' },
          { key: 'fcfMarginPct', label: 'FCF Margin % (forward)', step: 0.5, hint: 'Expected FCF / Revenue %' },
          { key: 'growthRate', label: 'Revenue Growth % (5yr fwd)', step: 0.5, hint: 'Conservative annual growth rate' },
          { key: 'discountRate', label: 'Discount Rate % (WACC)', step: 0.5, hint: 'Typically 8–12%' },
          { key: 'shares', label: 'Diluted Shares Outstanding', step: 1e7, hint: 'Current diluted shares' },
          { key: 'netCash', label: 'Net Cash ($)', step: 1e8, hint: 'Cash minus total debt' },
        ].map(({ key, label, step, hint }) => (
          <div key={key}>
            <label style={{ color: C.muted, fontSize: '11px', display: 'block', marginBottom: '4px' }}>{label}</label>
            <input
              type="number"
              value={dcfInputs[key] ?? ''}
              step={step}
              onChange={e => setDcfInputs(prev => ({ ...prev, [key]: parseFloat(e.target.value) || 0 }))}
              style={{
                width: '100%', padding: '6px 8px', background: C.cardAlt,
                border: `1px solid ${C.border}`, borderRadius: '6px',
                color: C.text, fontSize: '12px', outline: 'none',
              }}
            />
            <div style={{ color: C.faint, fontSize: '10px', marginTop: '2px' }}>{hint}</div>
          </div>
        ))}
      </div>

      {dcfResult && (
        <div style={{ padding: '16px', background: C.cardAlt, borderRadius: '8px', border: `1px solid ${C.border}` }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
            <div>
              <div style={{ color: C.muted, fontSize: '11px' }}>Intrinsic Value / Share</div>
              <div style={{ color: C.accent, fontSize: '24px', fontWeight: 700 }}>
                ${dcfResult.intrinsic.toFixed(2)}
              </div>
            </div>
            <div>
              <div style={{ color: C.muted, fontSize: '11px' }}>Current Price</div>
              <div style={{ color: C.text, fontSize: '24px', fontWeight: 700 }}>
                ${price?.toFixed(2) ?? '—'}
              </div>
            </div>
          </div>
          {price && (
            <div style={{ marginTop: '12px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                <span style={{ color: C.muted, fontSize: '12px' }}>Margin of Safety</span>
                <span style={{
                  fontWeight: 700, fontSize: '14px',
                  color: dcfResult.mos > 30 ? C.green : dcfResult.mos > 0 ? C.yellow : C.red,
                }}>
                  {dcfResult.mos > 0 ? `+${dcfResult.mos.toFixed(0)}%` : `${dcfResult.mos.toFixed(0)}%`}
                </span>
              </div>
              <div style={{ height: '6px', background: C.border, borderRadius: '3px' }}>
                <div style={{
                  height: '100%', borderRadius: '3px',
                  width: `${Math.min(Math.max(dcfResult.mos, 0), 100)}%`,
                  background: dcfResult.mos > 30 ? C.green : dcfResult.mos > 0 ? C.yellow : C.red,
                  transition: 'width 0.3s',
                }} />
              </div>
            </div>
          )}
          {dcfResult.impliedGrowth != null && (
            <div style={{ marginTop: '12px', padding: '8px', background: C.card, borderRadius: '6px' }}>
              <span style={{ color: C.muted, fontSize: '12px' }}>
                Reverse DCF: market is pricing in{' '}
                <strong style={{ color: C.accent }}>{dcfResult.impliedGrowth.toFixed(1)}%</strong>
                {' '}annual revenue growth for 5 years
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Main Component ────────────────────────────────────────────────────────────
export default function TwelveStepTab() {
  const [view, setView] = useState('landing') // 'landing' | 'screener' | 'wizard'
  const [tickerInput, setTickerInput] = useState('')
  const [ticker, setTicker] = useState('')
  const [tickerData, setTickerData] = useState(null)
  const [loadingData, setLoadingData] = useState(false)
  const [dataError, setDataError] = useState(null)
  const [currentStep, setCurrentStep] = useState(1)
  const [stepResults, setStepResults] = useState({}) // {1: {status, notes}, ...}
  const [moatFactors, setMoatFactors] = useState([])
  const [dcfInputs, setDcfInputs] = useState({})
  const [savedAnalyses, setSavedAnalyses] = useState(loadAnalyses)
  const [screenerResults, setScreenerResults] = useState(null)
  const [screenerLoading, setScreenerLoading] = useState(false)
  const [screenerError, setScreenerError] = useState(null)
  const [screenerFilters, setScreenerFilters] = useState({
    market_cap_min: 1000000000,
    sector: '',
    min_volume: 200000,
    limit: 40,
  })

  const autoEvals = useMemo(() => {
    if (!tickerData) return {}
    const evals = {}
    for (let i = 1; i <= 10; i++) {
      evals[i] = evaluateStep(i, tickerData)
    }
    return evals
  }, [tickerData])

  const failCount = useMemo(() => {
    let count = 0
    for (let i = 1; i <= 9; i++) {
      const res = stepResults[i]
      const status = res?.status ?? autoEvals[i]?.status
      if (status === 'fail') count++
    }
    return count
  }, [stepResults, autoEvals])

  const isOffIsland = failCount >= 3 && currentStep > 9

  const dcfResult = useMemo(() => {
    const { avgRevenue, fcfMarginPct, growthRate, discountRate, shares, netCash } = dcfInputs
    if (!avgRevenue || !fcfMarginPct || !discountRate || !shares) return null
    const intrinsic = computeDCFPerShare(avgRevenue, growthRate, fcfMarginPct, discountRate, shares, netCash)
    if (intrinsic === null) return null
    const price = tickerData?.current_price
    const mos = price ? ((intrinsic - price) / price) * 100 : null
    const impliedGrowth = price
      ? computeImpliedGrowth(price, avgRevenue, fcfMarginPct, discountRate, shares, netCash)
      : null
    return { intrinsic, mos, impliedGrowth }
  }, [dcfInputs, tickerData])

  const initDcfInputs = useCallback((data) => {
    const annual = (data.annual || [])[0] || {}
    const ttm = data.ttm || {}
    const rev = annual.revenue || 0
    const fcfM = ttm.fcf_margin != null ? ttm.fcf_margin : (annual.free_cash_flow && annual.revenue ? (annual.free_cash_flow / annual.revenue) * 100 : 15)
    const shares = data.shares_outstanding ? data.shares_outstanding * 1e6 : (annual.shares || 1e9)
    const cash = annual.cash || 0
    const debt = annual.total_debt || 0
    const netCash = cash - debt
    const growthRate = ttm.revenue_growth_yoy != null ? Math.max(Math.min(ttm.revenue_growth_yoy * 100, 50), -10) : 10
    setDcfInputs({
      avgRevenue: rev,
      fcfMarginPct: Math.max(fcfM, 1),
      growthRate,
      discountRate: 10,
      shares,
      netCash,
    })
  }, [])

  async function startAnalysis(sym) {
    const t = sym.toUpperCase().trim()
    if (!t) return
    setTicker(t)
    setView('wizard')
    setCurrentStep(1)
    setStepResults({})
    setMoatFactors([])
    setDcfInputs({})
    setTickerData(null)
    setDataError(null)
    setLoadingData(true)
    try {
      const data = await api.twelveStep.getData(t)
      setTickerData(data)
      initDcfInputs(data)
    } catch (e) {
      setDataError(e.message)
    } finally {
      setLoadingData(false)
    }
  }

  async function runScreener() {
    setScreenerLoading(true)
    setScreenerError(null)
    try {
      const res = await api.twelveStep.screener({
        ...screenerFilters,
        sector: screenerFilters.sector || null,
      })
      if (res.status === 'no_key') {
        setScreenerError('FMP_API_KEY not configured. Add it to your .env file to enable the screener.')
        setScreenerResults([])
      } else {
        setScreenerResults(res.results || [])
      }
    } catch (e) {
      setScreenerError(e.message)
    } finally {
      setScreenerLoading(false)
    }
  }

  function setStepStatus(step, status) {
    setStepResults(prev => ({ ...prev, [step]: { ...prev[step], status } }))
  }
  function setStepNotes(step, notes) {
    setStepResults(prev => ({ ...prev, [step]: { ...prev[step], notes } }))
  }

  function getEffectiveStatus(step) {
    return stepResults[step]?.status ?? autoEvals[step]?.status ?? null
  }

  function finishAnalysis() {
    const analysis = {
      id: `${ticker}-${Date.now()}`,
      ticker,
      date: new Date().toISOString().slice(0, 10),
      company_name: tickerData?.company_name || ticker,
      stepResults,
      moatFactors,
      dcfResult,
      failCount,
    }
    saveAnalysis(analysis)
    setSavedAnalyses(loadAnalyses())
  }

  function computeVerdict() {
    let passes = 0, warns = 0, fails = 0
    for (let i = 1; i <= 12; i++) {
      const s = getEffectiveStatus(i)
      if (s === 'pass') passes++
      else if (s === 'warn') warns++
      else if (s === 'fail') fails++
    }
    const mos = dcfResult?.mos
    const moatStrong = moatFactors.length >= 3
    if (passes >= 9 && (mos == null || mos >= 20) && moatStrong) return 'BUY'
    if (passes >= 7 && fails <= 2) return 'WATCH'
    return 'AVOID'
  }

  const step = STEPS[currentStep - 1]

  // ── Landing ──────────────────────────────────────────────────────────────────
  if (view === 'landing') {
    return (
      <div style={{ maxWidth: '860px', margin: '0 auto' }}>
        <div style={{ marginBottom: '24px' }}>
          <h1 style={{ color: C.text, fontSize: '22px', fontWeight: 700, margin: 0 }}>12 Step Stock Analysis</h1>
          <p style={{ color: C.muted, fontSize: '13px', marginTop: '6px' }}>
            Tom Nash's systematic framework for separating quality businesses from pretenders.
          </p>
        </div>

        {/* Ticker input */}
        <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: '12px', padding: '20px', marginBottom: '16px' }}>
          <h3 style={{ color: C.text, fontSize: '15px', fontWeight: 600, margin: '0 0 12px' }}>Analyze a Stock</h3>
          <div style={{ display: 'flex', gap: '10px' }}>
            <input
              value={tickerInput}
              onChange={e => setTickerInput(e.target.value.toUpperCase())}
              onKeyDown={e => e.key === 'Enter' && tickerInput && startAnalysis(tickerInput)}
              placeholder="e.g. AAPL, NVDA, MSFT"
              style={{
                flex: 1, padding: '10px 14px', background: C.cardAlt,
                border: `1px solid ${C.border}`, borderRadius: '8px',
                color: C.text, fontSize: '14px', outline: 'none',
              }}
            />
            <button
              onClick={() => tickerInput && startAnalysis(tickerInput)}
              disabled={!tickerInput}
              style={{
                padding: '10px 20px', background: C.accent, color: '#0f1117',
                border: 'none', borderRadius: '8px', fontWeight: 700, fontSize: '14px',
                cursor: tickerInput ? 'pointer' : 'not-allowed', opacity: tickerInput ? 1 : 0.5,
              }}
            >
              Start Analysis →
            </button>
          </div>
        </div>

        {/* Screener CTA */}
        <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: '12px', padding: '20px', marginBottom: '24px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <h3 style={{ color: C.text, fontSize: '15px', fontWeight: 600, margin: 0 }}>Find Candidates with Screener</h3>
              <p style={{ color: C.muted, fontSize: '12px', margin: '4px 0 0' }}>
                Pre-screen US stocks by market cap and sector, then run the 12 steps on any result.
              </p>
            </div>
            <button
              onClick={() => setView('screener')}
              style={{
                padding: '8px 18px', background: C.cardAlt, color: C.accent,
                border: `1px solid ${C.accent}`, borderRadius: '8px',
                fontWeight: 600, fontSize: '13px', cursor: 'pointer',
              }}
            >
              Open Screener
            </button>
          </div>
        </div>

        {/* Step overview */}
        <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: '12px', padding: '20px', marginBottom: '24px' }}>
          <h3 style={{ color: C.text, fontSize: '14px', fontWeight: 600, margin: '0 0 12px' }}>The 12 Steps at a Glance</h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '8px' }}>
            {STEPS.map(s => (
              <div key={s.num} style={{ display: 'flex', gap: '8px', alignItems: 'flex-start', padding: '8px', background: C.cardAlt, borderRadius: '6px' }}>
                <span style={{ color: C.faint, fontSize: '11px', fontWeight: 700, minWidth: '18px' }}>{s.num}.</span>
                <div>
                  <div style={{ color: C.text, fontSize: '12px', fontWeight: 600 }}>{s.icon} {s.title}</div>
                  {s.neverFails && <span style={{ color: C.yellow, fontSize: '10px' }}>never auto-fails</span>}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Recent analyses */}
        {savedAnalyses.length > 0 && (
          <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: '12px', padding: '20px' }}>
            <h3 style={{ color: C.text, fontSize: '14px', fontWeight: 600, margin: '0 0 12px' }}>Recent Analyses</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {savedAnalyses.slice(0, 8).map(a => {
                let passes = 0, fails = 0
                for (let i = 1; i <= 12; i++) {
                  const s = a.stepResults?.[i]?.status
                  if (s === 'pass') passes++
                  if (s === 'fail') fails++
                }
                return (
                  <div
                    key={a.id}
                    onClick={() => startAnalysis(a.ticker)}
                    style={{
                      display: 'flex', alignItems: 'center', gap: '12px',
                      padding: '10px 12px', background: C.cardAlt, borderRadius: '8px',
                      cursor: 'pointer', border: `1px solid ${C.border}`,
                    }}
                  >
                    <span style={{ color: C.accent, fontWeight: 700, fontSize: '14px', minWidth: '56px' }}>{a.ticker}</span>
                    <span style={{ color: C.muted, fontSize: '12px', flex: 1 }}>{a.company_name}</span>
                    <span style={{ color: C.muted, fontSize: '11px' }}>{a.date}</span>
                    {passes > 0 && <Chip label={`${passes} pass`} color={C.green} bg={C.greenDim} border={C.greenBorder} />}
                    {fails > 0 && <Chip label={`${fails} fail`} color={C.red} bg={C.redDim} border={C.redBorder} />}
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </div>
    )
  }

  // ── Screener ──────────────────────────────────────────────────────────────────
  if (view === 'screener') {
    return (
      <div style={{ maxWidth: '1000px', margin: '0 auto' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '20px' }}>
          <button onClick={() => setView('landing')} style={{ background: 'none', border: 'none', color: C.muted, cursor: 'pointer', fontSize: '13px' }}>← Back</button>
          <h2 style={{ color: C.text, fontSize: '18px', fontWeight: 700, margin: 0 }}>Stock Screener</h2>
        </div>

        {/* Filters */}
        <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: '12px', padding: '16px', marginBottom: '16px' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px', alignItems: 'end' }}>
            <div>
              <label style={{ color: C.muted, fontSize: '11px', display: 'block', marginBottom: '4px' }}>Min Market Cap</label>
              <select
                value={screenerFilters.market_cap_min}
                onChange={e => setScreenerFilters(p => ({ ...p, market_cap_min: Number(e.target.value) }))}
                style={{ width: '100%', padding: '8px', background: C.cardAlt, border: `1px solid ${C.border}`, borderRadius: '6px', color: C.text, fontSize: '12px' }}
              >
                <option value={500000000}>$500M (Small)</option>
                <option value={1000000000}>$1B (Mid)</option>
                <option value={10000000000}>$10B (Large)</option>
                <option value={100000000000}>$100B (Mega)</option>
              </select>
            </div>
            <div>
              <label style={{ color: C.muted, fontSize: '11px', display: 'block', marginBottom: '4px' }}>Sector</label>
              <select
                value={screenerFilters.sector}
                onChange={e => setScreenerFilters(p => ({ ...p, sector: e.target.value }))}
                style={{ width: '100%', padding: '8px', background: C.cardAlt, border: `1px solid ${C.border}`, borderRadius: '6px', color: C.text, fontSize: '12px' }}
              >
                <option value="">All Sectors</option>
                {SECTORS.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div>
              <label style={{ color: C.muted, fontSize: '11px', display: 'block', marginBottom: '4px' }}>Results</label>
              <select
                value={screenerFilters.limit}
                onChange={e => setScreenerFilters(p => ({ ...p, limit: Number(e.target.value) }))}
                style={{ width: '100%', padding: '8px', background: C.cardAlt, border: `1px solid ${C.border}`, borderRadius: '6px', color: C.text, fontSize: '12px' }}
              >
                <option value={20}>20 stocks</option>
                <option value={40}>40 stocks</option>
              </select>
            </div>
            <button
              onClick={runScreener}
              disabled={screenerLoading}
              style={{
                padding: '9px 16px', background: C.accent, color: '#0f1117',
                border: 'none', borderRadius: '8px', fontWeight: 700, fontSize: '13px',
                cursor: screenerLoading ? 'not-allowed' : 'pointer', opacity: screenerLoading ? 0.7 : 1,
              }}
            >
              {screenerLoading ? 'Screening…' : 'Run Screener'}
            </button>
          </div>
        </div>

        {screenerError && (
          <div style={{ padding: '12px 16px', background: C.redDim, border: `1px solid ${C.redBorder}`, borderRadius: '8px', color: C.red, fontSize: '13px', marginBottom: '12px' }}>
            {screenerError}
          </div>
        )}

        {screenerResults && screenerResults.length === 0 && !screenerError && (
          <div style={{ padding: '16px', color: C.muted, textAlign: 'center' }}>No results. Try loosening the filters.</div>
        )}

        {screenerResults && screenerResults.length > 0 && (
          <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: '12px', overflow: 'hidden' }}>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
                <thead>
                  <tr style={{ background: C.cardAlt }}>
                    {['Ticker', 'Company', 'Price', 'Mkt Cap', 'Rev Growth', 'Gross Margin', 'Op Margin', 'FCF Margin', 'P/E', ''].map(h => (
                      <th key={h} style={{ padding: '10px 12px', textAlign: h === '' || h === 'Company' ? 'left' : 'right', color: C.muted, fontWeight: 600, borderBottom: `1px solid ${C.border}`, whiteSpace: 'nowrap' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {screenerResults.map(r => (
                    <tr key={r.ticker} style={{ borderBottom: `1px solid ${C.border}` }}>
                      <td style={{ padding: '10px 12px', color: C.accent, fontWeight: 700 }}>{r.ticker}</td>
                      <td style={{ padding: '10px 12px', color: C.text, maxWidth: '160px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.name}</td>
                      <td style={{ padding: '10px 12px', textAlign: 'right', color: C.text, fontVariantNumeric: 'tabular-nums' }}>${r.price?.toFixed(2) ?? '—'}</td>
                      <td style={{ padding: '10px 12px', textAlign: 'right', color: C.muted }}>{r.market_cap ? `$${fmtNum(r.market_cap)}` : '—'}</td>
                      <td style={{ padding: '10px 12px', textAlign: 'right', color: r.revenue_growth > 0.1 ? C.green : r.revenue_growth > 0 ? C.yellow : C.red }}>
                        {r.revenue_growth != null ? `${(r.revenue_growth * 100).toFixed(1)}%` : '—'}
                      </td>
                      <td style={{ padding: '10px 12px', textAlign: 'right', color: r.gross_margin > 0.4 ? C.green : r.gross_margin > 0.25 ? C.yellow : C.text }}>
                        {r.gross_margin != null ? `${(r.gross_margin * 100).toFixed(1)}%` : '—'}
                      </td>
                      <td style={{ padding: '10px 12px', textAlign: 'right', color: r.operating_margin > 0.15 ? C.green : r.operating_margin > 0.05 ? C.yellow : C.red }}>
                        {r.operating_margin != null ? `${(r.operating_margin * 100).toFixed(1)}%` : '—'}
                      </td>
                      <td style={{ padding: '10px 12px', textAlign: 'right', color: r.fcf_margin > 0.1 ? C.green : r.fcf_margin > 0 ? C.yellow : C.red }}>
                        {r.fcf_margin != null ? `${(r.fcf_margin * 100).toFixed(1)}%` : '—'}
                      </td>
                      <td style={{ padding: '10px 12px', textAlign: 'right', color: r.pe > 0 && r.pe < 25 ? C.green : C.text }}>
                        {r.pe != null && r.pe > 0 ? r.pe.toFixed(1) : '—'}
                      </td>
                      <td style={{ padding: '10px 12px' }}>
                        <button
                          onClick={() => { setView('wizard'); startAnalysis(r.ticker) }}
                          style={{ padding: '4px 12px', background: C.accentDim, color: C.accent, border: `1px solid ${C.accent}`, borderRadius: '6px', cursor: 'pointer', fontSize: '11px', fontWeight: 600 }}
                        >
                          Analyze →
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    )
  }

  // ── Wizard ────────────────────────────────────────────────────────────────────
  const autoEval = autoEvals[currentStep]
  const effectiveStatus = getEffectiveStatus(currentStep)
  const isVerdict = currentStep === 13

  const verdict = isVerdict ? computeVerdict() : null

  const verdictColor = verdict === 'BUY' ? C.green : verdict === 'WATCH' ? C.yellow : C.red
  const verdictBg = verdict === 'BUY' ? C.greenDim : verdict === 'WATCH' ? C.yellowDim : C.redDim

  return (
    <div style={{ maxWidth: '860px', margin: '0 auto' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '16px' }}>
        <button
          onClick={() => setView('landing')}
          style={{ background: 'none', border: 'none', color: C.muted, cursor: 'pointer', fontSize: '13px' }}
        >
          ← Back
        </button>
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <span style={{ color: C.accent, fontSize: '20px', fontWeight: 700 }}>{ticker}</span>
            {tickerData && (
              <>
                <span style={{ color: C.text, fontSize: '14px' }}>{tickerData.company_name}</span>
                {tickerData.sector && <Chip label={tickerData.sector} />}
                {tickerData.current_price && (
                  <span style={{ color: C.text, fontSize: '14px', fontWeight: 600, marginLeft: 'auto' }}>
                    ${tickerData.current_price.toFixed(2)}
                  </span>
                )}
              </>
            )}
          </div>
        </div>
      </div>

      {/* Progress bar */}
      <div style={{ display: 'flex', gap: '3px', marginBottom: '20px', padding: '12px', background: C.card, borderRadius: '10px', border: `1px solid ${C.border}` }}>
        {STEPS.map(s => {
          const st = getEffectiveStatus(s.num)
          const isActive = currentStep === s.num
          return (
            <button
              key={s.num}
              onClick={() => setCurrentStep(s.num)}
              title={s.title}
              style={{
                flex: 1, padding: '6px 4px', borderRadius: '5px', cursor: 'pointer',
                border: isActive ? `2px solid ${C.accent}` : '2px solid transparent',
                background: st ? statusBg(st) : C.cardAlt,
                display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '2px',
              }}
            >
              <span style={{ fontSize: '9px', color: isActive ? C.accent : C.faint, fontWeight: 700 }}>{s.num}</span>
              <span style={{ fontSize: '10px', color: st ? statusColor(st) : C.faint }}>{st ? statusIcon(st) : '○'}</span>
            </button>
          )
        })}
        <button
          key="verdict"
          onClick={() => setCurrentStep(13)}
          title="Verdict"
          style={{
            flex: 1, padding: '6px 4px', borderRadius: '5px', cursor: 'pointer',
            border: currentStep === 13 ? `2px solid ${C.accent}` : '2px solid transparent',
            background: currentStep === 13 ? C.accentDim : C.cardAlt,
            display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '2px',
          }}
        >
          <span style={{ fontSize: '9px', color: currentStep === 13 ? C.accent : C.faint, fontWeight: 700 }}>✦</span>
          <span style={{ fontSize: '10px', color: currentStep === 13 ? C.accent : C.faint }}>V</span>
        </button>
      </div>

      {/* Off-Island warning */}
      {failCount >= 3 && currentStep <= 9 && (
        <div style={{ padding: '10px 14px', background: C.redDim, border: `1px solid ${C.redBorder}`, borderRadius: '8px', marginBottom: '12px', fontSize: '12px', color: C.red }}>
          ⚠ <strong>Off-Island Warning</strong> — {failCount} fails so far.
          Tom Nash recommends stopping at 3+ failures in the first 9 steps.
          You can continue anyway — scroll through to step 13 for the verdict.
        </div>
      )}

      {/* Loading / error */}
      {loadingData && (
        <div style={{ padding: '32px', textAlign: 'center', color: C.muted }}>
          Loading data for {ticker}…
        </div>
      )}
      {dataError && (
        <div style={{ padding: '12px 16px', background: C.redDim, border: `1px solid ${C.redBorder}`, borderRadius: '8px', color: C.red, fontSize: '13px', marginBottom: '12px' }}>
          {dataError}
        </div>
      )}

      {/* Verdict view */}
      {isVerdict && (
        <div>
          <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: '12px', padding: '20px', marginBottom: '16px' }}>
            <h2 style={{ color: C.text, fontSize: '18px', fontWeight: 700, margin: '0 0 16px' }}>Final Verdict: {ticker}</h2>
            {verdict && (
              <div style={{ display: 'flex', alignItems: 'center', gap: '16px', padding: '16px', background: verdictBg, borderRadius: '10px', border: `1px solid ${statusBorder(verdict === 'BUY' ? 'pass' : verdict === 'WATCH' ? 'warn' : 'fail')}`, marginBottom: '20px' }}>
                <div style={{ fontSize: '40px', lineHeight: 1 }}>
                  {verdict === 'BUY' ? '🟢' : verdict === 'WATCH' ? '🟡' : '🔴'}
                </div>
                <div>
                  <div style={{ color: verdictColor, fontSize: '24px', fontWeight: 800 }}>{verdict}</div>
                  <div style={{ color: C.muted, fontSize: '12px', marginTop: '2px' }}>
                    {verdict === 'BUY' && 'Strong fundamentals, moat, and margin of safety — worth a position'}
                    {verdict === 'WATCH' && 'Mostly passes but some concerns — add to watchlist and monitor'}
                    {verdict === 'AVOID' && 'Too many red flags or overvalued — pass on this one'}
                  </div>
                </div>
              </div>
            )}

            {/* Step summary table */}
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px', marginBottom: '16px' }}>
              <thead>
                <tr style={{ background: C.cardAlt }}>
                  <th style={{ padding: '6px 10px', textAlign: 'left', color: C.muted, borderBottom: `1px solid ${C.border}` }}>#</th>
                  <th style={{ padding: '6px 10px', textAlign: 'left', color: C.muted, borderBottom: `1px solid ${C.border}` }}>Step</th>
                  <th style={{ padding: '6px 10px', textAlign: 'left', color: C.muted, borderBottom: `1px solid ${C.border}` }}>Assessment</th>
                  <th style={{ padding: '6px 10px', textAlign: 'left', color: C.muted, borderBottom: `1px solid ${C.border}` }}>Notes</th>
                </tr>
              </thead>
              <tbody>
                {STEPS.map(s => {
                  const st = getEffectiveStatus(s.num)
                  const reason = autoEvals[s.num]?.reason || (s.num === 11 ? `${moatFactors.length} moat factors` : '—')
                  const notes = stepResults[s.num]?.notes || ''
                  return (
                    <tr key={s.num} style={{ borderBottom: `1px solid ${C.border}`, background: st ? statusBg(st) + '55' : 'transparent' }}>
                      <td style={{ padding: '7px 10px', color: C.faint }}>{s.num}</td>
                      <td style={{ padding: '7px 10px', color: C.text, fontWeight: 500 }}>{s.icon} {s.title}</td>
                      <td style={{ padding: '7px 10px' }}><StatusBadge status={st} /></td>
                      <td style={{ padding: '7px 10px', color: C.muted, fontSize: '11px' }}>{notes || reason}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>

            {/* DCF summary */}
            {dcfResult && (
              <div style={{ padding: '12px 16px', background: C.cardAlt, borderRadius: '8px', border: `1px solid ${C.border}`, marginBottom: '12px' }}>
                <div style={{ display: 'flex', gap: '24px', flexWrap: 'wrap' }}>
                  <div>
                    <div style={{ color: C.muted, fontSize: '11px' }}>Intrinsic Value</div>
                    <div style={{ color: C.accent, fontSize: '18px', fontWeight: 700 }}>${dcfResult.intrinsic.toFixed(2)}</div>
                  </div>
                  <div>
                    <div style={{ color: C.muted, fontSize: '11px' }}>Current Price</div>
                    <div style={{ color: C.text, fontSize: '18px', fontWeight: 700 }}>${tickerData?.current_price?.toFixed(2) ?? '—'}</div>
                  </div>
                  <div>
                    <div style={{ color: C.muted, fontSize: '11px' }}>Margin of Safety</div>
                    <div style={{
                      fontSize: '18px', fontWeight: 700,
                      color: dcfResult.mos > 30 ? C.green : dcfResult.mos > 0 ? C.yellow : C.red,
                    }}>
                      {dcfResult.mos != null ? `${dcfResult.mos > 0 ? '+' : ''}${dcfResult.mos.toFixed(0)}%` : '—'}
                    </div>
                  </div>
                  <div>
                    <div style={{ color: C.muted, fontSize: '11px' }}>Moat Factors</div>
                    <div style={{ fontSize: '18px', fontWeight: 700, color: moatFactors.length >= 3 ? C.green : moatFactors.length >= 1 ? C.yellow : C.red }}>
                      {moatFactors.length} / {MOAT_FACTORS.length}
                    </div>
                  </div>
                </div>
              </div>
            )}

            <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
              <button
                onClick={finishAnalysis}
                style={{ padding: '8px 20px', background: C.accentDim, color: C.accent, border: `1px solid ${C.accent}`, borderRadius: '8px', fontWeight: 600, fontSize: '13px', cursor: 'pointer' }}
              >
                Save Analysis
              </button>
              <button
                onClick={() => setView('landing')}
                style={{ padding: '8px 20px', background: C.cardAlt, color: C.text, border: `1px solid ${C.border}`, borderRadius: '8px', fontWeight: 600, fontSize: '13px', cursor: 'pointer' }}
              >
                New Analysis
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Step card */}
      {!isVerdict && step && (
        <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: '12px', padding: '20px' }}>
          {/* Step header */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '12px' }}>
            <div style={{
              width: '40px', height: '40px', borderRadius: '50%',
              background: effectiveStatus ? statusBg(effectiveStatus) : C.cardAlt,
              border: `2px solid ${effectiveStatus ? statusColor(effectiveStatus) : C.border}`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: '18px', flexShrink: 0,
            }}>
              {step.icon}
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ color: C.muted, fontSize: '11px', fontWeight: 600 }}>STEP {step.num}/12</span>
                {step.neverFails && <Chip label="never auto-fails" color={C.yellow} bg={C.yellowDim} border={C.yellowBorder} />}
              </div>
              <h2 style={{ color: C.text, fontSize: '17px', fontWeight: 700, margin: '2px 0 0' }}>{step.title}</h2>
            </div>
            <StatusBadge status={effectiveStatus} />
          </div>

          <p style={{ color: C.muted, fontSize: '13px', margin: '0 0 4px' }}>{step.brief}</p>
          <p style={{ color: C.faint, fontSize: '12px', margin: '0 0 16px' }}>{step.detail}</p>

          {/* Auto-eval result */}
          {autoEval && autoEval.status && (
            <div style={{
              padding: '10px 14px', borderRadius: '8px', marginBottom: '14px',
              background: statusBg(autoEval.status),
              border: `1px solid ${statusBorder(autoEval.status)}`,
              display: 'flex', alignItems: 'center', gap: '8px',
            }}>
              <span style={{ color: statusColor(autoEval.status), fontWeight: 700 }}>{statusIcon(autoEval.status)}</span>
              <span style={{ color: statusColor(autoEval.status), fontSize: '13px' }}>Auto: {autoEval.reason}</span>
            </div>
          )}

          {/* Step-specific data */}
          <div style={{ marginBottom: '16px' }}>
            {loadingData
              ? <div style={{ color: C.muted, fontSize: '13px', padding: '12px 0' }}>Loading data…</div>
              : !tickerData
              ? null
              : currentStep === 1 ? <Step1Data data={tickerData} />
              : currentStep === 2 ? <Step2Data data={tickerData} />
              : currentStep === 3 ? <Step3Data data={tickerData} />
              : currentStep === 4 ? <Step4Data data={tickerData} />
              : currentStep === 5 ? <Step5Data data={tickerData} />
              : currentStep === 6 ? <Step6Data data={tickerData} />
              : currentStep === 7 ? <Step7Data data={tickerData} />
              : currentStep === 8 ? <Step8Data data={tickerData} />
              : currentStep === 9 ? <Step9Data data={tickerData} />
              : currentStep === 10 ? <Step10Data data={tickerData} />
              : currentStep === 11 ? <Step11Data moatFactors={moatFactors} setMoatFactors={setMoatFactors} />
              : currentStep === 12 ? <Step12Data data={tickerData} dcfInputs={dcfInputs} setDcfInputs={setDcfInputs} dcfResult={dcfResult} />
              : null
            }
          </div>

          {/* Manual override */}
          <div style={{ borderTop: `1px solid ${C.border}`, paddingTop: '14px', marginBottom: '14px' }}>
            <p style={{ color: C.muted, fontSize: '11px', margin: '0 0 8px' }}>
              {currentStep <= 10 ? 'Override auto-assessment:' : 'Your assessment:'}
            </p>
            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
              {['pass', 'warn', 'fail', ...(currentStep === 6 ? [] : ['skip'])].map(s => (
                <button
                  key={s}
                  onClick={() => setStepStatus(currentStep, stepResults[currentStep]?.status === s ? undefined : s)}
                  style={{
                    padding: '6px 16px', borderRadius: '6px', cursor: 'pointer',
                    fontWeight: 600, fontSize: '12px',
                    background: stepResults[currentStep]?.status === s ? statusBg(s) : C.cardAlt,
                    color: stepResults[currentStep]?.status === s ? statusColor(s) : C.muted,
                    border: `1px solid ${stepResults[currentStep]?.status === s ? statusBorder(s) : C.border}`,
                  }}
                >
                  {s === 'pass' ? '✓ Pass' : s === 'fail' ? '✗ Fail' : s === 'warn' ? '~ Caution' : '→ Skip'}
                </button>
              ))}
            </div>
          </div>

          {/* Notes */}
          <textarea
            value={stepResults[currentStep]?.notes || ''}
            onChange={e => setStepNotes(currentStep, e.target.value)}
            placeholder="Add notes… (optional)"
            rows={2}
            style={{
              width: '100%', padding: '8px 10px', background: C.cardAlt,
              border: `1px solid ${C.border}`, borderRadius: '6px',
              color: C.text, fontSize: '12px', resize: 'vertical', outline: 'none',
              boxSizing: 'border-box', marginBottom: '14px',
            }}
          />

          {/* Navigation */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <button
              onClick={() => setCurrentStep(s => Math.max(1, s - 1))}
              disabled={currentStep === 1}
              style={{
                padding: '8px 20px', background: C.cardAlt, color: C.text,
                border: `1px solid ${C.border}`, borderRadius: '8px',
                fontWeight: 600, fontSize: '13px', cursor: currentStep === 1 ? 'not-allowed' : 'pointer',
                opacity: currentStep === 1 ? 0.4 : 1,
              }}
            >
              ← Back
            </button>

            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
              {failCount > 0 && currentStep <= 9 && (
                <span style={{ color: C.red, fontSize: '11px' }}>{failCount} fail{failCount !== 1 ? 's' : ''}</span>
              )}
              <button
                onClick={() => setCurrentStep(s => Math.min(13, s + 1))}
                style={{
                  padding: '8px 24px',
                  background: currentStep === 12 ? C.green : C.accent,
                  color: '#0f1117',
                  border: 'none', borderRadius: '8px', fontWeight: 700, fontSize: '13px', cursor: 'pointer',
                }}
              >
                {currentStep === 12 ? 'View Verdict →' : 'Next →'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
