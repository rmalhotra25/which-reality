import { useState, useCallback, useMemo, useEffect, useRef } from 'react'
import { api } from '../api'

// ─── Palette (kept from the previous version of this tab) ───────────────────
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

// ─── Nash 12 steps, in order ─────────────────────────────────────────────────
const STEPS = [
  { num: 1, title: 'Find the secular trend', icon: '🌊', brief: 'Start with the future, not a ticker. Identify where a new game is being played, then find who sells the picks and shovels.', detail: 'Prefer companies built for the trend from day one, not old businesses retrofitting. Skip entirely: small caps, Chinese companies, commodities, airlines, seasonal businesses, startups.' },
  { num: 2, title: 'Sanity check', icon: '🧭', brief: 'The No-Nonsense Rule: revenue growing, profitable, more cash than debt.', detail: 'At least 2 of 3 yes, plus a written justification if any answer is no. Valid reasons: an infrastructure company that genuinely needs leverage, or a clear path to profitability.' },
  { num: 3, title: 'Pre-screen', icon: '⚡', brief: '30 seconds to 5 minutes. Most companies die here.', detail: 'Six checkboxes, all required, plus instant kills. Rule of 40 is guidance only: 40 is perfect, below 40 is a pass, north of 100 shuts everybody up. It is not a pass or fail bar.' },
  { num: 4, title: 'Define the business', icon: '📝', brief: 'Prove you understand it before touching the numbers.', detail: 'Buying one share is buying the whole business. If you cannot explain it cleanly, you do not understand it yet.' },
  { num: 5, title: 'Market potential', icon: '🌍', brief: 'Great tech in a tiny market is a bad investment.', detail: 'It must sell into a broad market, and the market must be big enough to support the growth you are betting on.' },
  { num: 6, title: '125-point scorecard', icon: '🏅', brief: 'A player card for the stock, using last twelve months data.', detail: '13 categories, 0, 5, or 10 points each, auto-summed out of 130 and labelled the framework 125-point scorecard. Bands: 100-130 Exceptional, 75-99 Watchlist, below 75 no-go. This step never hard-fails alone.' },
  { num: 7, title: 'Revenue engine and 5-year history', icon: '📊', brief: 'CEOs overhype, the numbers do not. Understand how the money gets made first.', detail: 'Read income from operations, not net income. Whenever you see adjusted EBITDA, be skeptical.' },
  { num: 8, title: 'Loan Officer Test', icon: '🏦', brief: 'Read the balance sheet like a banker deciding whether to lend this company money.', detail: 'Debt is prison, cash is freedom. Interest coverage at least 4x, solvency at least 2:1 (3:1 ideal), current ratio at least 1.0, debt-to-equity below 4x.' },
  { num: 9, title: 'Competitive moat', icon: '🏰', brief: 'Without a moat, revenue growth is irrelevant.', detail: 'At least one moat selected, and the 20-engineers test answered no: a competitor could not copy this business in a year with 20 engineers per engineer of yours.' },
  { num: 10, title: 'Management', icon: '👤', brief: 'No investment unless amazed by the CEO.', detail: 'At least 6 of 8 checklist items, and no red flags. Bozos hire bozos, superstars hire superstars.' },
  { num: 11, title: 'Destroy the thesis', icon: '💥', brief: 'By now you like this stock, which is exactly when you are most dangerous to yourself.', detail: 'Try to kill the thesis. Any red flag fails the step, and you must be able to live with the bear case.' },
  { num: 12, title: 'Valuation', icon: '🎯', brief: 'You can get the thesis 100% right and still lose money if you overpay.', detail: 'Reverse DCF implied growth, a 5-year DCF at 8%, 10%, and 12% with 4% terminal growth fixed, and PEG bands: under 1 undervalued, around 1 fair, over 2 very expensive.' },
]

const FIVE_RULES = [
  'Great company, fair price. Business quality first, valuation second.',
  'Cash is fact. Profit is an accountant opinion.',
  'Blend the story and the numbers. One without the other does not cut it.',
  'Probable over possible. Bet on what is likely, not on what could happen.',
  'Avoid losers first. Even the best investors are only right about 60% of the time.',
]

const TREND_CHECKS = [
  'Real demand and paying customers',
  'Sustainable revenue and earnings growth',
  'A moat, not a commodity',
  'Regulatory or government tailwinds',
  'Adoption visible in the real world',
]

const PRESCREEN_CHECKS = [
  'Positive free cash flow for the past 4 to 6 quarters',
  'Net cash positive for the past 4 to 6 quarters',
  'Revenue growing 10% or more',
  'An actual moat',
  'A CEO and team with a track record',
  'No major regulatory or legal overhang',
]

const PRESCREEN_KILLS = [
  { id: 'marketCap', label: 'Market cap under $1 billion' },
  { id: 'short', label: 'Short interest above 10%' },
  { id: 'debt', label: 'More debt than cash, even by a dollar' },
  { id: 'opMargin', label: 'Operating margin below 20%' },
  { id: 'revFalling', label: 'Revenue growth below 10% and falling' },
  { id: 'misses', label: '2 or more earnings misses in the last 4 quarters' },
  { id: 'young', label: 'Less than 10 years old, counted from founding' },
]

const MARKET_CHECKS = [
  'It sells into a broad market, not a niche',
  'I checked the market size myself instead of trusting an analyst report',
  'The market is big enough to support the growth I am betting on',
]

const SCORECARD = [
  { label: 'Cash vs debt', zero: 'More debt than cash', five: 'More cash than debt', ten: '2x+ cash vs debt' },
  { label: 'Revenue growth', zero: 'Below 10%', five: '10 to 20%', ten: 'Above 20%' },
  { label: 'Operating margin', zero: 'Below 10%', five: '10 to 25%', ten: 'Above 25%' },
  { label: 'Short interest', zero: 'Above 10%', five: '5 to 10%', ten: 'Below 5%' },
  { label: 'Institutional ownership', zero: 'Below 30%', five: '30 to 60%', ten: 'Above 60%' },
  { label: 'Revenue growing faster than expenses', zero: 'No', five: null, ten: 'Yes' },
  { label: '5-year return vs S&P 500', zero: 'Underperformed', five: 'Beat by 10 to 20%', ten: 'Beat by 20%+' },
  { label: 'Moat', zero: 'None', five: 'Weak', ten: 'Strong' },
  { label: 'CEO', zero: 'Clown', five: 'Decent', ten: 'Superstar' },
  { label: 'Recession proof, pricing power', zero: 'None', five: 'Some', ten: 'Strong' },
  { label: 'Secular trend', zero: 'Disrupted', five: 'Somewhat on trend', ten: 'Exactly on trend' },
  { label: 'Culture and mission', zero: 'None', five: 'Some', ten: 'Strong' },
  { label: 'Talent', zero: 'Low', five: 'Medium', ten: 'High' },
]

const MOATS = [
  { id: 'network', label: 'Network effects', desc: 'YouTube, Meta: more users make it more valuable' },
  { id: 'technology', label: 'Technology and patents', desc: 'NVIDIA chips, Palantir Foundry' },
  { id: 'switching', label: 'Switching costs', desc: 'Salesforce, SAP: painful to leave' },
  { id: 'scale', label: 'Scale', desc: 'Walmart, Costco: fixed costs spread over massive volume' },
  { id: 'regulation', label: 'Regulation', desc: 'Defense contracting, healthcare barriers' },
  { id: 'brand', label: 'Brand', desc: 'Apple, Coca-Cola: customers pay for the name' },
]

const MGMT_CHECKS = [
  'Track record of execution: revenue growth, better margins, innovation on their watch',
  'Skin in the game: buying stock on the open market, not just options',
  '10+ years in the role, ideally the founder',
  'Disciplined capital allocation on buybacks, debt, and acquisitions',
  'Straight answers even when they do not look good',
  'Consistent earnings beats',
  'The kind of leader great people want to work for',
  'Results, not excuses',
]

const MGMT_RED_FLAGS = ['Clown CEO', 'Co-CEO structure', 'Acquisition shopping spree']

const BEAR_RED_FLAGS = [
  'Declining margins',
  'Insiders selling hard while the stock runs',
  'The hype trap: nonstop media hype, weak fundamentals, constant share sales to raise cash',
  'Fraud or accounting scandal, even a suspicion',
  'Auditor change',
  'Revenue spiking while inventory piles up',
  'Over-expansion or acquisition spree',
]

const SECTORS = [
  'Technology', 'Healthcare', 'Financials', 'Consumer Discretionary',
  'Industrials', 'Communication Services', 'Consumer Staples',
  'Energy', 'Real Estate', 'Materials', 'Utilities',
]

const STORAGE_KEY = 'twelve_step_analyses_v1'

// ─── Units ──────────────────────────────────────────────────────────────────
// Finnhub growth and margin fields arrive as PERCENT (12 means 12%), the same
// convention discovery_engine.py and dcf_service.py use (they divide by 100).
// Never multiply a Finnhub ttm field by 100 here. The screener table below is
// different: FMP returns decimals, so its * 100 stays.
export function computeDCFPerShare(avgRevenue, fwdGrowthRate, fcfMarginPct, discountRate, shares, netCash) {
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

export function dcfGrowthRate(ttm) {
  const g = ttm?.revenue_growth_yoy
  return g != null ? Math.max(Math.min(g, 50), -10) : 10
}

export function dcfShares(data) {
  const annual = (data.annual || [])[0] || {}
  if (data.shares_outstanding) return data.shares_outstanding * 1e6
  return annual.shares || null
}

// ─── Nash verdict, pure so it is testable ────────────────────────────────────
// Survivor only if every step passes and the scorecard is at least 75.
// Step 6 never hard-fails alone, so it is not in failedSteps, but a score
// below 75 still produces the no-go banner and blocks Survivor.
export function decideVerdict(failedSteps, scorecardTotal) {
  if (failedSteps.length === 0 && scorecardTotal >= 75) return 'SURVIVOR'
  return 'OFF_ISLAND'
}

export function scorecardBand(total) {
  if (total >= 100) return 'Exceptional'
  if (total >= 75) return 'Watchlist'
  return 'no-go'
}

export function pegBand(peg) {
  if (peg == null) return null
  if (peg < 1) return 'undervalued'
  if (peg <= 2) return 'fair'
  return 'very expensive'
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function fmtNum(v, decimals = 1) {
  if (v == null || isNaN(v)) return '-'
  if (Math.abs(v) >= 1e12) return `${(v / 1e12).toFixed(decimals)}T`
  if (Math.abs(v) >= 1e9) return `${(v / 1e9).toFixed(decimals)}B`
  if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(decimals)}M`
  if (Math.abs(v) >= 1e3) return `${(v / 1e3).toFixed(decimals)}K`
  return v.toFixed(decimals)
}

function numOrNull(v) {
  const n = parseFloat(v)
  return isNaN(n) ? null : n
}

function statusColor(s) {
  if (s === 'pass') return C.green
  if (s === 'fail') return C.red
  return C.muted
}
function statusBg(s) {
  if (s === 'pass') return C.greenDim
  if (s === 'fail') return C.redDim
  return '#1a1f2e'
}
function statusBorder(s) {
  if (s === 'pass') return C.greenBorder
  if (s === 'fail') return C.redBorder
  return C.border
}
function statusIcon(s) {
  if (s === 'pass') return '✓'
  if (s === 'fail') return '✗'
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
function deleteAnalysis(id) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(loadAnalyses().filter(a => a.id !== id)))
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
  const labels = { pass: '✓ Pass', fail: '✗ Fail' }
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

const inputStyle = {
  width: '100%', padding: '8px 10px', background: C.cardAlt,
  border: `1px solid ${C.border}`, borderRadius: '6px',
  color: C.text, fontSize: '13px', outline: 'none', boxSizing: 'border-box',
}

function Field({ label, hint, children, fromScreener }) {
  return (
    <div>
      <label style={{ color: C.muted, fontSize: '11px', display: 'block', marginBottom: '4px' }}>
        {label} {fromScreener && <span style={{ color: C.accent, fontSize: '10px' }}>from screener</span>}
      </label>
      {children}
      {hint && <div style={{ color: C.faint, fontSize: '10px', marginTop: '2px' }}>{hint}</div>}
    </div>
  )
}

function TextInput({ value, onChange, placeholder, type = 'text', step }) {
  return (
    <input
      type={type} step={step} value={value ?? ''} placeholder={placeholder}
      onChange={e => onChange(e.target.value)}
      style={inputStyle}
    />
  )
}

function CheckRow({ checked, onToggle, label, danger }) {
  return (
    <label
      onClick={e => { e.preventDefault(); onToggle() }}
      style={{
        display: 'flex', gap: '10px', alignItems: 'flex-start',
        padding: '9px 12px', borderRadius: '8px', cursor: 'pointer',
        background: checked ? (danger ? C.redDim : C.accentDim) : C.cardAlt,
        border: `1px solid ${checked ? (danger ? C.redBorder : C.accent) : C.border}`,
        marginBottom: '6px',
      }}
    >
      <span style={{ color: checked ? (danger ? C.red : C.accent) : C.faint, fontSize: '16px', flexShrink: 0 }}>{checked ? '☑' : '☐'}</span>
      <span style={{ color: checked ? (danger ? C.red : C.text) : C.text, fontSize: '13px' }}>{label}</span>
    </label>
  )
}

function YesNo({ value, onChange, yesLabel = 'Yes', noLabel = 'No' }) {
  return (
    <div style={{ display: 'flex', gap: '8px' }}>
      {[{ v: true, label: yesLabel }, { v: false, label: noLabel }].map(o => (
        <button
          key={o.label}
          onClick={() => onChange(value === o.v ? null : o.v)}
          style={{
            padding: '6px 16px', borderRadius: '6px', cursor: 'pointer', fontWeight: 600, fontSize: '12px',
            background: value === o.v ? C.accentDim : C.cardAlt,
            color: value === o.v ? C.accent : C.muted,
            border: `1px solid ${value === o.v ? C.accent : C.border}`,
          }}
        >{o.label}</button>
      ))}
    </div>
  )
}

// ─── Form model ───────────────────────────────────────────────────────────────
function emptyYearRow(year) {
  return { year, revenue: '', operatingIncome: '', fcf: '', cash: '', debt: '' }
}

export function defaultForm() {
  return {
    s1: { trend: '', checks: [false, false, false, false, false], marketStory: '', becoming: '' },
    s2: { revGrown: null, profitable: null, moreCash: null, justification: '' },
    s3: {
      checks: [false, false, false, false, false, false],
      revGrowth: '', fcfMargin: '', expenseGrowth: '',
      kills: { marketCap: false, short: false, debt: false, opMargin: false, revFalling: false, misses: false, young: false },
      marketCap: '', shortInterest: '', operatingMargin: '', foundedYear: '',
    },
    s4: { company: '', provides: '', helps: '', achieve: '', charges: '', pain: '', whoPain: '', whyUs: '', canExplain: false },
    s5: { checks: [false, false, false], marketSource: '', marketSize: '' },
    s6: { scores: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0] },
    s7: { segments: '', years: [emptyYearRow(''), emptyYearRow(''), emptyYearRow(''), emptyYearRow(''), emptyYearRow('')], certified: false },
    s8: { operatingIncome: '', interestExpense: '', totalAssets: '', totalLiabilities: '', currentAssets: '', currentLiabilities: '', equity: '', peerNotes: '' },
    s9: { moats: [], moatTrend: '', whyChoose: '', whyStay: '', engineers: null, marginProves: null },
    s10: { ceo: '', checks: [false, false, false, false, false, false, false, false], redFlags: [false, false, false] },
    s11: { reasons: ['', '', ''], bearCase: '', redFlags: [false, false, false, false, false, false, false], canLive: null },
    s12: { price: '', shares: '', avgRevenue: '', revGrowth: '', fcfMargin: '', trimmedGrowth: '', netCash: '', forwardPE: '', epsGrowth: '', peerPE: '', priceToSales: '', industryPS: '', certified: false },
    after: { whyOwn: '', whatWouldSell: '' },
    fromScreener: null,
  }
}

// Each evaluation returns pass true, false, or null for pending (nothing
// entered yet for that step). The verdict converts pending to fail.
export function evaluateNashStep(num, form) {
  const f = form
  const nonEmpty = v => v != null && String(v).trim() !== ''
  if (num === 1) {
    if (!nonEmpty(f.s1.trend) && f.s1.checks.every(c => !c) && !nonEmpty(f.s1.marketStory) && !nonEmpty(f.s1.becoming)) return { pass: null, reason: 'Not started' }
    if (!f.s1.checks.every(Boolean)) return { pass: false, reason: 'All five trend checkboxes are required' }
    if (!nonEmpty(f.s1.trend) || !nonEmpty(f.s1.marketStory) || !nonEmpty(f.s1.becoming)) return { pass: false, reason: 'Trend name and both story fields are required' }
    return { pass: true, reason: 'All five trend checks and both story fields are complete' }
  }
  if (num === 2) {
    const answers = [f.s2.revGrown, f.s2.profitable, f.s2.moreCash]
    if (answers.every(a => a === null)) return { pass: null, reason: 'Not started' }
    const yes = answers.filter(a => a === true).length
    if (yes < 2) return { pass: false, reason: `Only ${yes} of 3 yes, need at least 2` }
    if (yes < 3 && !nonEmpty(f.s2.justification)) return { pass: false, reason: 'A justification is required when any answer is no' }
    return { pass: true, reason: `${yes} of 3 yes, with justification where needed` }
  }
  if (num === 3) {
    if (f.s3.checks.every(c => !c) && Object.values(f.s3.kills).every(c => !c)) return { pass: null, reason: 'Not started' }
    const kill = PRESCREEN_KILLS.find(k => f.s3.kills[k.id])
    if (kill) return { pass: false, reason: `Instant kill: ${kill.label}` }
    if (!f.s3.checks.every(Boolean)) return { pass: false, reason: 'All six pre-screen checkboxes are required' }
    return { pass: true, reason: 'All six checks, no instant kill' }
  }
  if (num === 4) {
    const parts = [f.s4.company, f.s4.provides, f.s4.helps, f.s4.achieve, f.s4.charges, f.s4.pain, f.s4.whoPain, f.s4.whyUs]
    if (parts.every(p => !nonEmpty(p)) && !f.s4.canExplain) return { pass: null, reason: 'Not started' }
    if (parts.some(p => !nonEmpty(p))) return { pass: false, reason: 'Sentence builder and all three pain questions are required' }
    if (!f.s4.canExplain) return { pass: false, reason: 'Self-certification is required: I can explain this business cleanly' }
    return { pass: true, reason: 'Business sentence complete, pain questions answered, certified' }
  }
  if (num === 5) {
    if (f.s5.checks.every(c => !c)) return { pass: null, reason: 'Not started' }
    if (!f.s5.checks.every(Boolean)) return { pass: false, reason: 'All three market checkboxes are required' }
    return { pass: true, reason: 'All three market checks complete' }
  }
  if (num === 6) {
    const total = f.s6.scores.reduce((a, b) => a + (b || 0), 0)
    return { pass: null, reason: `Score ${total} / 130, ${scorecardBand(total)}`, total }
  }
  if (num === 7) {
    if (!nonEmpty(f.s7.segments) && f.s7.years.every(y => !nonEmpty(y.revenue)) && !f.s7.certified) return { pass: null, reason: 'Not started' }
    if (!f.s7.certified) return { pass: false, reason: 'Self-certification is required after reviewing the auto-flags' }
    return { pass: true, reason: '5-year history reviewed and certified' }
  }
  if (num === 8) {
    const vals = [f.s8.operatingIncome, f.s8.interestExpense, f.s8.totalAssets, f.s8.totalLiabilities, f.s8.currentAssets, f.s8.currentLiabilities, f.s8.equity]
    if (vals.every(v => !nonEmpty(v))) return { pass: null, reason: 'Not started' }
    const ratios = loanOfficerRatios(f.s8)
    if (!ratios) return { pass: false, reason: 'All Loan Officer inputs are required to compute the four ratios' }
    const failed = []
    if (ratios.coverage < 4) failed.push('interest coverage below 4x')
    if (ratios.solvency < 2) failed.push('solvency below 2:1')
    if (ratios.current < 1) failed.push('current ratio below 1.0')
    if (ratios.debtEquity >= 4) failed.push('debt-to-equity at or above 4x')
    if (failed.length) return { pass: false, reason: failed.join(', ') }
    return { pass: true, reason: 'All four Loan Officer ratios pass' }
  }
  if (num === 9) {
    if (f.s9.moats.length === 0 && f.s9.engineers === null) return { pass: null, reason: 'Not started' }
    if (f.s9.moats.length < 1) return { pass: false, reason: 'At least one moat must be selected' }
    if (f.s9.engineers !== false) return { pass: false, reason: '20-engineers test must be answered no for a real moat' }
    return { pass: true, reason: `${f.s9.moats.length} moat(s), 20-engineers test answered no` }
  }
  if (num === 10) {
    if (f.s10.checks.every(c => !c) && f.s10.redFlags.every(c => !c) && !nonEmpty(f.s10.ceo)) return { pass: null, reason: 'Not started' }
    if (f.s10.redFlags.some(Boolean)) return { pass: false, reason: 'A management red flag is checked' }
    const count = f.s10.checks.filter(Boolean).length
    if (count < 6) return { pass: false, reason: `Only ${count} of 8 management checks, need at least 6` }
    return { pass: true, reason: `${count} of 8 management checks, no red flags` }
  }
  if (num === 11) {
    if (!nonEmpty(f.s11.bearCase) && f.s11.redFlags.every(c => !c) && f.s11.canLive === null) return { pass: null, reason: 'Not started' }
    if (f.s11.redFlags.some(Boolean)) return { pass: false, reason: 'A bear-case red flag is checked' }
    if (!nonEmpty(f.s11.bearCase)) return { pass: false, reason: 'A written bear case is required' }
    if (f.s11.canLive !== true) return { pass: false, reason: 'Can I live with the bear case must be yes' }
    return { pass: true, reason: 'Bear case written, no red flags, can live with it' }
  }
  if (num === 12) {
    if (!f.s12.certified) return { pass: null, reason: 'Not started' }
    return { pass: true, reason: 'Certified: valuation works even in the bear case' }
  }
  return { pass: null, reason: 'Unknown step' }
}

export function loanOfficerRatios(s8) {
  const oi = numOrNull(s8.operatingIncome)
  const ie = numOrNull(s8.interestExpense)
  const ta = numOrNull(s8.totalAssets)
  const tl = numOrNull(s8.totalLiabilities)
  const ca = numOrNull(s8.currentAssets)
  const cl = numOrNull(s8.currentLiabilities)
  const eq = numOrNull(s8.equity)
  if ([oi, ie, ta, tl, ca, cl, eq].some(v => v === null)) return null
  if (tl === 0 || cl === 0 || eq === 0) return null
  return {
    coverage: ie === 0 ? (oi > 0 ? Infinity : 0) : oi / ie,
    solvency: ta / tl,
    current: ca / cl,
    debtEquity: tl / eq,
  }
}

export function fiveYearFlags(years) {
  const rows = years.filter(y => numOrNull(y.revenue) != null).map(y => ({
    ...y, revenue: numOrNull(y.revenue), operatingIncome: numOrNull(y.operatingIncome),
    fcf: numOrNull(y.fcf), cash: numOrNull(y.cash), debt: numOrNull(y.debt),
  }))
  if (rows.length < 2) return []
  const chronological = [...rows].reverse()
  const flags = []
  const revGrowing = chronological.every((r, i) => i === 0 || r.revenue > chronological[i - 1].revenue)
  flags.push(revGrowing ? 'Revenue growing every year' : 'Revenue did not grow every year')
  const margins = chronological.map(r => (r.operatingIncome != null && r.revenue ? r.operatingIncome / r.revenue : null)).filter(m => m != null)
  if (margins.length >= 2) {
    flags.push(margins[margins.length - 1] >= margins[0] ? 'Operating margin expanding' : 'Operating margin contracting')
  }
  const fcfs = chronological.map(r => r.fcf).filter(v => v != null)
  if (fcfs.length) {
    flags.push(fcfs.every(v => v > 0) ? 'Free cash flow positive every year shown' : 'Free cash flow not positive every year shown')
    if (fcfs.length >= 2) flags.push(fcfs[fcfs.length - 1] >= fcfs[0] ? 'Free cash flow rising' : 'Free cash flow falling')
  }
  const cashDebt = chronological.filter(r => r.cash != null && r.debt != null)
  if (cashDebt.length) {
    flags.push(cashDebt.every(r => r.cash > r.debt) ? 'Cash greater than debt every year shown' : 'Cash not greater than debt every year shown')
  }
  return flags
}

// ─── Step renderers ───────────────────────────────────────────────────────────
function renderStep(num, ctx) {
  const { form, setStep, toggleList, toggleKill, setScore, setYear, toggleMoat, toggleFlag, tickerData } = ctx
  const f = form
  const scr = form.fromScreener
  const grid = { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', marginBottom: '12px' }
  const fullGrid = { display: 'grid', gridTemplateColumns: '1fr', gap: '10px', marginBottom: '12px' }

  if (num === 1) {
    return (
      <div>
        <div style={fullGrid}>
          <Field label="Trend name"><TextInput value={f.s1.trend} onChange={v => setStep('s1', { trend: v })} placeholder="e.g. AI infrastructure" /></Field>
        </div>
        <p style={{ color: C.muted, fontSize: '12px' }}>All five are required to pass:</p>
        {TREND_CHECKS.map((label, i) => (
          <CheckRow key={label} checked={f.s1.checks[i]} onToggle={() => toggleList('s1', 'checks', i)} label={label} />
        ))}
        <div style={{ ...fullGrid, marginTop: '12px' }}>
          <Field label="The market's story about this company"><textarea value={f.s1.marketStory} onChange={e => setStep('s1', { marketStory: e.target.value })} rows={2} style={{ ...inputStyle, resize: 'vertical' }} /></Field>
          <Field label="What the company is becoming"><textarea value={f.s1.becoming} onChange={e => setStep('s1', { becoming: e.target.value })} rows={2} style={{ ...inputStyle, resize: 'vertical' }} /></Field>
        </div>
        <p style={{ color: C.faint, fontSize: '12px' }}>The gap between the two stories is the edge. No gap, no edge.</p>
      </div>
    )
  }

  if (num === 2) {
    const questions = [
      { key: 'revGrown', label: 'Revenue has grown for the past few years' },
      { key: 'profitable', label: 'The company is profitable' },
      { key: 'moreCash', label: 'It has more cash than debt' },
    ]
    return (
      <div>
        {tickerData?.ttm && (
          <div style={{ marginBottom: '12px' }}>
            {tickerData.ttm.revenue_growth_yoy != null && <MetricRow label="TTM revenue growth" value={`${tickerData.ttm.revenue_growth_yoy.toFixed(1)}%`} />}
            {tickerData.ttm.net_margin != null && <MetricRow label="TTM net margin" value={`${tickerData.ttm.net_margin.toFixed(1)}%`} />}
          </div>
        )}
        {questions.map(q => (
          <div key={q.key} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0', borderBottom: `1px solid ${C.border}` }}>
            <span style={{ color: C.text, fontSize: '13px' }}>{q.label}</span>
            <YesNo value={f.s2[q.key]} onChange={v => setStep('s2', { [q.key]: v })} />
          </div>
        ))}
        <div style={{ marginTop: '12px' }}>
          <Field label="If one answer is no, justify it here" hint="Valid reasons: an infrastructure company that genuinely needs leverage, or a clear path to profitability. Anything else is a fail.">
            <textarea value={f.s2.justification} onChange={e => setStep('s2', { justification: e.target.value })} rows={2} style={{ ...inputStyle, resize: 'vertical' }} />
          </Field>
        </div>
      </div>
    )
  }

  if (num === 3) {
    const revG = numOrNull(f.s3.revGrowth)
    const fcfM = numOrNull(f.s3.fcfMargin)
    const expG = numOrNull(f.s3.expenseGrowth)
    const rule40 = revG != null && fcfM != null ? revG + fcfM : null
    return (
      <div>
        <div style={grid}>
          <Field label="Revenue growth %" fromScreener={!!scr}><TextInput type="number" step="0.5" value={f.s3.revGrowth} onChange={v => setStep('s3', { revGrowth: v })} /></Field>
          <Field label="FCF margin %" fromScreener={!!scr}><TextInput type="number" step="0.5" value={f.s3.fcfMargin} onChange={v => setStep('s3', { fcfMargin: v })} /></Field>
          <Field label="Expense growth %"><TextInput type="number" step="0.5" value={f.s3.expenseGrowth} onChange={v => setStep('s3', { expenseGrowth: v })} /></Field>
          <Field label="Operating margin %" fromScreener={!!scr}><TextInput type="number" step="0.5" value={f.s3.operatingMargin} onChange={v => setStep('s3', { operatingMargin: v })} /></Field>
          <Field label="Market cap ($)"><TextInput type="number" value={f.s3.marketCap} onChange={v => setStep('s3', { marketCap: v })} /></Field>
          <Field label="Short interest %"><TextInput type="number" step="0.5" value={f.s3.shortInterest} onChange={v => setStep('s3', { shortInterest: v })} /></Field>
          <Field label="Founded year"><TextInput type="number" value={f.s3.foundedYear} onChange={v => setStep('s3', { foundedYear: v })} /></Field>
        </div>
        {rule40 != null && (
          <div style={{ padding: '10px 14px', background: C.cardAlt, borderRadius: '8px', border: `1px solid ${C.border}`, marginBottom: '12px' }}>
            <span style={{ color: C.muted, fontSize: '12px' }}>Rule of 40: </span>
            <span style={{ color: C.accent, fontWeight: 700 }}>{rule40.toFixed(1)}</span>
            <span style={{ color: C.muted, fontSize: '12px' }}> (40 is perfect, below 40 is a pass, north of 100 shuts everybody up. Guidance only, not a pass or fail bar.)</span>
          </div>
        )}
        {revG != null && expG != null && (
          <div style={{ color: revG > expG ? C.green : C.red, fontSize: '12px', marginBottom: '12px' }}>
            {revG > expG ? 'Revenue is growing faster than expenses.' : 'Revenue is not growing faster than expenses.'}
          </div>
        )}
        <p style={{ color: C.muted, fontSize: '12px' }}>All six are required:</p>
        {PRESCREEN_CHECKS.map((label, i) => (
          <CheckRow key={label} checked={f.s3.checks[i]} onToggle={() => toggleList('s3', 'checks', i)} label={label} />
        ))}
        <p style={{ color: C.red, fontSize: '12px', marginTop: '12px' }}>Instant kills: any one checked fails this step.</p>
        {PRESCREEN_KILLS.map(k => (
          <CheckRow key={k.id} checked={f.s3.kills[k.id]} onToggle={() => toggleKill(k.id)} label={k.label} danger />
        ))}
      </div>
    )
  }

  if (num === 4) {
    const sentence = `${f.s4.company || '[Company]'} provides ${f.s4.provides || '[X]'} that helps ${f.s4.helps || '[Y]'} achieve ${f.s4.achieve || '[Z]'}, and charges ${f.s4.charges || '[revenue model]'}.`
    return (
      <div>
        <div style={grid}>
          <Field label="Company"><TextInput value={f.s4.company} onChange={v => setStep('s4', { company: v })} /></Field>
          <Field label="Provides (X)"><TextInput value={f.s4.provides} onChange={v => setStep('s4', { provides: v })} /></Field>
          <Field label="Helps (Y)"><TextInput value={f.s4.helps} onChange={v => setStep('s4', { helps: v })} /></Field>
          <Field label="Achieve (Z)"><TextInput value={f.s4.achieve} onChange={v => setStep('s4', { achieve: v })} /></Field>
          <Field label="Charges (revenue model)"><TextInput value={f.s4.charges} onChange={v => setStep('s4', { charges: v })} /></Field>
        </div>
        <div style={{ padding: '12px', background: C.cardAlt, borderRadius: '8px', border: `1px solid ${C.border}`, marginBottom: '12px', color: C.text, fontSize: '13px' }}>{sentence}</div>
        <div style={fullGrid}>
          <Field label="What pain are we curing"><textarea value={f.s4.pain} onChange={e => setStep('s4', { pain: e.target.value })} rows={2} style={{ ...inputStyle, resize: 'vertical' }} /></Field>
          <Field label="Who is in pain and why"><textarea value={f.s4.whoPain} onChange={e => setStep('s4', { whoPain: e.target.value })} rows={2} style={{ ...inputStyle, resize: 'vertical' }} /></Field>
          <Field label="Why will the customer come to us and not the competitor"><textarea value={f.s4.whyUs} onChange={e => setStep('s4', { whyUs: e.target.value })} rows={2} style={{ ...inputStyle, resize: 'vertical' }} /></Field>
        </div>
        <CheckRow checked={f.s4.canExplain} onToggle={() => setStep('s4', { canExplain: !f.s4.canExplain })} label="I can explain this business cleanly." />
      </div>
    )
  }

  if (num === 5) {
    return (
      <div>
        {MARKET_CHECKS.map((label, i) => (
          <CheckRow key={label} checked={f.s5.checks[i]} onToggle={() => toggleList('s5', 'checks', i)} label={label} />
        ))}
        <div style={{ ...grid, marginTop: '12px' }}>
          <Field label="Market size source (for check 2)"><TextInput value={f.s5.marketSource} onChange={v => setStep('s5', { marketSource: v })} placeholder="Source you checked yourself" /></Field>
          <Field label="Estimated total market size ($)"><TextInput type="number" value={f.s5.marketSize} onChange={v => setStep('s5', { marketSize: v })} /></Field>
        </div>
      </div>
    )
  }

  if (num === 6) {
    const total = f.s6.scores.reduce((a, b) => a + (b || 0), 0)
    return (
      <div>
        <div style={{ padding: '12px 14px', background: C.cardAlt, borderRadius: '8px', border: `1px solid ${C.border}`, marginBottom: '12px' }}>
          <span style={{ color: C.muted, fontSize: '12px' }}>Total: </span>
          <span style={{ color: C.accent, fontWeight: 700, fontSize: '16px' }}>{total} / 130</span>
          <span style={{ color: C.muted, fontSize: '12px' }}> (labelled the framework 125-point scorecard) - {scorecardBand(total)}</span>
        </div>
        <p style={{ color: C.muted, fontSize: '12px' }}>Score categories 8 to 13 as harshly as you can. Category 6 is 0 or 10 only.</p>
        {SCORECARD.map((cat, i) => (
          <div key={cat.label} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0', borderBottom: `1px solid ${C.border}`, flexWrap: 'wrap', gap: '8px' }}>
            <div style={{ flex: 1, minWidth: '180px' }}>
              <div style={{ color: C.text, fontSize: '13px' }}>{i + 1}. {cat.label}</div>
              <div style={{ color: C.faint, fontSize: '11px' }}>0: {cat.zero}{cat.five ? ` | 5: ${cat.five}` : ''} | 10: {cat.ten}</div>
            </div>
            <div style={{ display: 'flex', gap: '6px' }}>
              {[0, 5, 10].filter(v => v !== 5 || cat.five != null).map(v => (
                <button
                  key={v}
                  onClick={() => setScore(i, v)}
                  style={{
                    padding: '6px 12px', borderRadius: '6px', cursor: 'pointer', fontWeight: 600, fontSize: '12px',
                    background: f.s6.scores[i] === v ? C.accentDim : C.cardAlt,
                    color: f.s6.scores[i] === v ? C.accent : C.muted,
                    border: `1px solid ${f.s6.scores[i] === v ? C.accent : C.border}`,
                  }}
                >{v}</button>
              ))}
            </div>
          </div>
        ))}
      </div>
    )
  }

  return null
}

function renderStepLater(num, ctx) {
  const { form, setStep, setYear, toggleMoat, toggleFlag, tickerData } = ctx
  const f = form
  const grid = { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', marginBottom: '12px' }
  const fullGrid = { display: 'grid', gridTemplateColumns: '1fr', gap: '10px', marginBottom: '12px' }

  if (num === 7) {
    const flags = fiveYearFlags(f.s7.years)
    return (
      <div>
        <div style={fullGrid}>
          <Field label="Which segments drive revenue and how the company wins customers"><textarea value={f.s7.segments} onChange={e => setStep('s7', { segments: e.target.value })} rows={2} style={{ ...inputStyle, resize: 'vertical' }} /></Field>
        </div>
        <div style={{ overflowX: 'auto', marginBottom: '12px' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
            <thead>
              <tr style={{ color: C.muted }}>
                {['Year', 'Revenue', 'Operating income', 'Operating margin', 'Free cash flow', 'Cash', 'Debt'].map(h => (
                  <th key={h} style={{ textAlign: h === 'Year' ? 'left' : 'right', padding: '4px 8px', borderBottom: `1px solid ${C.border}` }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {f.s7.years.map((row, i) => {
                const rev = numOrNull(row.revenue)
                const oi = numOrNull(row.operatingIncome)
                const margin = rev && oi != null ? (oi / rev * 100).toFixed(1) + '%' : '-'
                return (
                  <tr key={i} style={{ borderBottom: `1px solid ${C.border}` }}>
                    <td style={{ padding: '4px' }}><input value={row.year} onChange={e => setYear(i, 'year', e.target.value)} placeholder="Year" style={{ ...inputStyle, padding: '4px 6px', fontSize: '12px' }} /></td>
                    {['revenue', 'operatingIncome', 'fcf', 'cash', 'debt'].map(k => (
                      <td key={k} style={{ padding: '4px' }}><input type="number" value={row[k]} onChange={e => setYear(i, k, e.target.value)} style={{ ...inputStyle, padding: '4px 6px', fontSize: '12px', textAlign: 'right' }} /></td>
                    ))}
                    <td style={{ padding: '4px 8px', textAlign: 'right', color: C.muted }}>{margin}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        {flags.length > 0 && (
          <div style={{ padding: '10px 14px', background: C.cardAlt, borderRadius: '8px', border: `1px solid ${C.border}`, marginBottom: '12px' }}>
            {flags.map(fl => <div key={fl} style={{ color: C.muted, fontSize: '12px' }}>- {fl}</div>)}
          </div>
        )}
        <CheckRow checked={f.s7.certified} onToggle={() => setStep('s7', { certified: !f.s7.certified })} label="The 5-year history supports the thesis." />
      </div>
    )
  }

  if (num === 8) {
    const ratios = loanOfficerRatios(f.s8)
    return (
      <div>
        <div style={grid}>
          <Field label="Operating income"><TextInput type="number" value={f.s8.operatingIncome} onChange={v => setStep('s8', { operatingIncome: v })} /></Field>
          <Field label="Interest expense"><TextInput type="number" value={f.s8.interestExpense} onChange={v => setStep('s8', { interestExpense: v })} /></Field>
          <Field label="Total assets (excluding goodwill)"><TextInput type="number" value={f.s8.totalAssets} onChange={v => setStep('s8', { totalAssets: v })} /></Field>
          <Field label="Total liabilities"><TextInput type="number" value={f.s8.totalLiabilities} onChange={v => setStep('s8', { totalLiabilities: v })} /></Field>
          <Field label="Current assets"><TextInput type="number" value={f.s8.currentAssets} onChange={v => setStep('s8', { currentAssets: v })} /></Field>
          <Field label="Current liabilities"><TextInput type="number" value={f.s8.currentLiabilities} onChange={v => setStep('s8', { currentLiabilities: v })} /></Field>
          <Field label="Shareholders equity"><TextInput type="number" value={f.s8.equity} onChange={v => setStep('s8', { equity: v })} /></Field>
        </div>
        {ratios && (
          <div style={{ marginBottom: '12px' }}>
            <MetricRow label="Interest coverage (target 4x to 10x)" value={ratios.coverage === Infinity ? 'No interest expense' : `${ratios.coverage.toFixed(2)}x`} highlight={ratios.coverage >= 4 ? C.green : C.red} />
            <MetricRow label="Solvency (minimum 2:1, ideal 3:1)" value={`${ratios.solvency.toFixed(2)}:1`} highlight={ratios.solvency >= 2 ? C.green : C.red} />
            <MetricRow label="Current ratio (must be 1.0+)" value={ratios.current.toFixed(2)} highlight={ratios.current >= 1 ? C.green : C.red} />
            <MetricRow label="Debt-to-equity (4x+ is a red flag)" value={`${ratios.debtEquity.toFixed(2)}x`} highlight={ratios.debtEquity < 4 ? C.green : C.red} />
          </div>
        )}
        <Field label="Peer comparison notes" hint="Some industries, for example retail with inventory, naturally look less liquid."><textarea value={f.s8.peerNotes} onChange={e => setStep('s8', { peerNotes: e.target.value })} rows={2} style={{ ...inputStyle, resize: 'vertical' }} /></Field>
      </div>
    )
  }

  if (num === 9) {
    const opMargin = numOrNull(f.s3.operatingMargin) ?? tickerData?.ttm?.operating_margin ?? null
    return (
      <div>
        <p style={{ color: C.muted, fontSize: '13px', marginBottom: '12px' }}>Select the moats that genuinely apply. Be conservative.</p>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginBottom: '12px' }}>
          {MOATS.map(m => {
            const checked = f.s9.moats.includes(m.id)
            return (
              <label
                key={m.id}
                onClick={() => toggleMoat(m.id)}
                style={{
                  display: 'flex', gap: '10px', alignItems: 'flex-start',
                  padding: '10px 12px', borderRadius: '8px', cursor: 'pointer',
                  background: checked ? C.accentDim : C.cardAlt,
                  border: `1px solid ${checked ? C.accent : C.border}`,
                }}
              >
                <span style={{ color: checked ? C.accent : C.faint, fontSize: '16px', flexShrink: 0 }}>{checked ? '☑' : '☐'}</span>
                <div>
                  <div style={{ color: checked ? C.accent : C.text, fontSize: '13px', fontWeight: 600 }}>{m.label}</div>
                  <div style={{ color: C.muted, fontSize: '11px', marginTop: '2px' }}>{m.desc}</div>
                </div>
              </label>
            )
          })}
        </div>
        <div style={fullGrid}>
          <Field label="Is the moat getting stronger or weaker over time"><TextInput value={f.s9.moatTrend} onChange={v => setStep('s9', { moatTrend: v })} placeholder="Stronger or weaker, and why" /></Field>
          <Field label="Why do customers choose this business"><textarea value={f.s9.whyChoose} onChange={e => setStep('s9', { whyChoose: e.target.value })} rows={2} style={{ ...inputStyle, resize: 'vertical' }} /></Field>
          <Field label="Why do they stay, and will they come back for 10 years"><textarea value={f.s9.whyStay} onChange={e => setStep('s9', { whyStay: e.target.value })} rows={2} style={{ ...inputStyle, resize: 'vertical' }} /></Field>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0', borderBottom: `1px solid ${C.border}` }}>
          <span style={{ color: C.text, fontSize: '13px' }}>20-engineers test: could a competitor copy this business in a year?</span>
          <YesNo value={f.s9.engineers} onChange={v => setStep('s9', { engineers: v })} />
        </div>
        <p style={{ color: C.faint, fontSize: '11px' }}>Answer no for a real moat. Answer yes fails this step.</p>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0' }}>
          <span style={{ color: C.text, fontSize: '13px' }}>Does the operating margin prove pricing power? {opMargin != null ? `(operating margin ${opMargin.toFixed(1)}%)` : ''}</span>
          <YesNo value={f.s9.marginProves} onChange={v => setStep('s9', { marginProves: v })} />
        </div>
      </div>
    )
  }

  if (num === 10) {
    return (
      <div>
        <div style={{ marginBottom: '12px' }}>
          <Field label="CEO name"><TextInput value={f.s10.ceo} onChange={v => setStep('s10', { ceo: v })} /></Field>
        </div>
        <p style={{ color: C.muted, fontSize: '12px' }}>At least 6 of 8 required:</p>
        {MGMT_CHECKS.map((label, i) => (
          <CheckRow key={label} checked={f.s10.checks[i]} onToggle={() => toggleList('s10', 'checks', i)} label={label} />
        ))}
        <p style={{ color: C.red, fontSize: '12px', marginTop: '12px' }}>Red flags: any one checked fails this step.</p>
        {MGMT_RED_FLAGS.map((label, i) => (
          <CheckRow key={label} checked={f.s10.redFlags[i]} onToggle={() => toggleList('s10', 'redFlags', i)} label={label} danger />
        ))}
      </div>
    )
  }

  if (num === 11) {
    return (
      <div>
        <p style={{ color: C.muted, fontSize: '13px' }}>List 3 reasons your thesis is wrong, then write the bear case in plain words. Read the bearish analysis on Seeking Alpha before you finish this step.</p>
        <div style={fullGrid}>
          {f.s11.reasons.map((r, i) => (
            <Field key={i} label={`Reason my thesis is wrong ${i + 1}`}><TextInput value={r} onChange={v => setStep('s11', { reasons: f.s11.reasons.map((x, j) => j === i ? v : x) })} /></Field>
          ))}
          <Field label="Bear case, in plain words"><textarea value={f.s11.bearCase} onChange={e => setStep('s11', { bearCase: e.target.value })} rows={3} style={{ ...inputStyle, resize: 'vertical' }} /></Field>
        </div>
        <p style={{ color: C.red, fontSize: '12px' }}>Red flags: any one checked fails this step.</p>
        {BEAR_RED_FLAGS.map((label, i) => (
          <CheckRow key={label} checked={f.s11.redFlags[i]} onToggle={() => toggleList('s11', 'redFlags', i)} label={label} danger />
        ))}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0', marginTop: '8px' }}>
          <span style={{ color: C.text, fontSize: '13px' }}>Can I live with the bear case?</span>
          <YesNo value={f.s11.canLive} onChange={v => setStep('s11', { canLive: v })} />
        </div>
      </div>
    )
  }

  if (num === 12) {
    const s12 = f.s12
    const avgRev = numOrNull(s12.avgRevenue)
    const fcfM = numOrNull(s12.fcfMargin)
    const growth = numOrNull(s12.trimmedGrowth)
    const shares = numOrNull(s12.shares)
    const netCash = numOrNull(s12.netCash) || 0
    const price = numOrNull(s12.price)
    const dcfCases = avgRev && fcfM != null && growth != null && shares
      ? [8, 10, 12].map(dr => ({ dr, value: computeDCFPerShare(avgRev, growth, fcfM, dr, shares, netCash) }))
      : null
    const implied = price && avgRev && fcfM != null && shares
      ? computeImpliedGrowth(price, avgRev, fcfM, 10, shares, netCash)
      : null
    const fwdPE = numOrNull(s12.forwardPE)
    const epsG = numOrNull(s12.epsGrowth)
    const peg = fwdPE != null && epsG ? fwdPE / epsG : null
    return (
      <div>
        {price == null && (
          <div style={{ padding: '10px 14px', background: C.redDim, border: `1px solid ${C.redBorder}`, borderRadius: '8px', color: C.red, fontSize: '12px', marginBottom: '12px' }}>
            Price unavailable: no live price could be fetched. The verdict can still be completed from your inputs, but DCF values vs price are blocked. The 52-week low is never used as a substitute price.
          </div>
        )}
        <p style={{ color: C.muted, fontSize: '12px' }}>Part 1: reverse DCF. Given today price, what annual growth is the market already assuming? If the price only makes sense with heroic growth assumptions, that is your answer.</p>
        <div style={grid}>
          <Field label="Current price"><TextInput type="number" step="0.01" value={s12.price} onChange={v => setStep('s12', { price: v })} /></Field>
          <Field label="Shares outstanding"><TextInput type="number" value={s12.shares} onChange={v => setStep('s12', { shares: v })} /></Field>
        </div>
        {implied != null && (
          <div style={{ padding: '10px 14px', background: C.cardAlt, borderRadius: '8px', border: `1px solid ${C.border}`, marginBottom: '12px' }}>
            <span style={{ color: C.muted, fontSize: '12px' }}>Reverse DCF at a 10% discount rate: market is pricing in </span>
            <span style={{ color: C.accent, fontWeight: 700 }}>{implied.toFixed(1)}%</span>
            <span style={{ color: C.muted, fontSize: '12px' }}> annual revenue growth for 5 years.</span>
          </div>
        )}
        <p style={{ color: C.muted, fontSize: '12px' }}>Part 2: 5-year DCF. Terminal value at 4% growth, fixed. Add cash, subtract debt, divide by shares.</p>
        <div style={grid}>
          <Field label="3-year average revenue"><TextInput type="number" value={s12.avgRevenue} onChange={v => setStep('s12', { avgRevenue: v })} /></Field>
          <Field label="Revenue growth % (trimmed forward rate)"><TextInput type="number" step="0.5" value={s12.trimmedGrowth} onChange={v => setStep('s12', { trimmedGrowth: v })} /></Field>
          <Field label="FCF margin %"><TextInput type="number" step="0.5" value={s12.fcfMargin} onChange={v => setStep('s12', { fcfMargin: v })} /></Field>
          <Field label="Net cash (cash minus debt)"><TextInput type="number" value={s12.netCash} onChange={v => setStep('s12', { netCash: v })} /></Field>
        </div>
        {dcfCases && (
          <div style={{ marginBottom: '12px' }}>
            {dcfCases.map(c => (
              <MetricRow key={c.dr} label={`DCF per share at ${c.dr}% discount (${c.dr === 8 ? 'bull' : c.dr === 10 ? 'base' : 'bear'})`} value={c.value != null ? `$${c.value.toFixed(2)}` : '-'} highlight={price != null && c.value != null && c.value > price ? C.green : C.red} />
            ))}
            <p style={{ color: C.faint, fontSize: '11px' }}>Even the bear case has to look attractive.</p>
          </div>
        )}
        <p style={{ color: C.muted, fontSize: '12px' }}>Part 3: the right multiple.</p>
        <div style={grid}>
          <Field label="Forward P/E"><TextInput type="number" step="0.1" value={s12.forwardPE} onChange={v => setStep('s12', { forwardPE: v })} /></Field>
          <Field label="EPS growth rate %"><TextInput type="number" step="0.5" value={s12.epsGrowth} onChange={v => setStep('s12', { epsGrowth: v })} /></Field>
          <Field label="Peer average forward P/E (mature, hardware, banks)"><TextInput type="number" step="0.1" value={s12.peerPE} onChange={v => setStep('s12', { peerPE: v })} /></Field>
          <Field label="Price-to-sales (early growth, not yet profitable)"><TextInput type="number" step="0.1" value={s12.priceToSales} onChange={v => setStep('s12', { priceToSales: v })} /></Field>
          <Field label="Industry average price-to-sales"><TextInput type="number" step="0.1" value={s12.industryPS} onChange={v => setStep('s12', { industryPS: v })} /></Field>
        </div>
        {peg != null && (
          <div style={{ padding: '10px 14px', background: C.cardAlt, borderRadius: '8px', border: `1px solid ${C.border}`, marginBottom: '12px' }}>
            <span style={{ color: C.muted, fontSize: '12px' }}>PEG: </span>
            <span style={{ color: C.accent, fontWeight: 700 }}>{peg.toFixed(2)}</span>
            <span style={{ color: C.muted, fontSize: '12px' }}> - {pegBand(peg)} (under 1 undervalued, around 1 fair, over 2 very expensive).</span>
          </div>
        )}
        <CheckRow checked={s12.certified} onToggle={() => setStep('s12', { certified: !s12.certified })} label="The valuation works even in the bear case." />
      </div>
    )
  }

  return null
}

// ─── Main Component ────────────────────────────────────────────────────────────
export default function TwelveStepTab({ initialTicker = null, onBack = null }) {
  const [view, setView] = useState('landing')
  const [tickerInput, setTickerInput] = useState('')
  const [ticker, setTicker] = useState('')
  const [tickerData, setTickerData] = useState(null)
  const [loadingData, setLoadingData] = useState(false)
  const [dataError, setDataError] = useState(null)
  const [currentStep, setCurrentStep] = useState(1)
  const [form, setForm] = useState(defaultForm)
  const [savedAnalyses, setSavedAnalyses] = useState(loadAnalyses)
  const [screenerResults, setScreenerResults] = useState(null)
  const [screenerLoading, setScreenerLoading] = useState(false)
  const [screenerError, setScreenerError] = useState(null)
  const [screenerOmitted, setScreenerOmitted] = useState([])
  const [screenerAsOf, setScreenerAsOf] = useState(null)
  const [sortKey, setSortKey] = useState('rule_of_40')
  const [sortDir, setSortDir] = useState(-1)
  const [screenerFilters, setScreenerFilters] = useState({
    market_cap_min: 1000000000,
    sector: '',
    min_volume: 200000,
    limit: 100,
    fcf_positive: true,
    net_cash_positive: true,
    revenue_growth_min: 10,
    short_interest_max: 10,
    operating_margin_min: 20,
    earnings_misses_max: 1,
    exclude_china: true,
    exclude_airlines: true,
    exclude_commodities: true,
  })

  const _initDone = useRef(false)
  useEffect(() => {
    if (initialTicker && !_initDone.current) {
      _initDone.current = true
      startAnalysis(initialTicker)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function setStep(key, patch) {
    setForm(prev => ({ ...prev, [key]: { ...prev[key], ...patch } }))
  }
  function toggleList(stepKey, listKey, index) {
    setForm(prev => {
      const list = prev[stepKey][listKey].map((v, i) => i === index ? !v : v)
      return { ...prev, [stepKey]: { ...prev[stepKey], [listKey]: list } }
    })
  }
  function toggleKill(id) {
    setForm(prev => ({ ...prev, s3: { ...prev.s3, kills: { ...prev.s3.kills, [id]: !prev.s3.kills[id] } } }))
  }
  function setScore(index, value) {
    setForm(prev => ({ ...prev, s6: { scores: prev.s6.scores.map((v, i) => i === index ? value : v) } }))
  }
  function setYear(index, field, value) {
    setForm(prev => ({ ...prev, s7: { years: prev.s7.years.map((y, i) => i === index ? { ...y, [field]: value } : y) } }))
  }
  function toggleMoat(id) {
    setForm(prev => {
      const moats = prev.s9.moats.includes(id) ? prev.s9.moats.filter(m => m !== id) : [...prev.s9.moats, id]
      return { ...prev, s9: { ...prev.s9, moats } }
    })
  }

  const ctx = { form, setStep, toggleList, toggleKill, setScore, setYear, toggleMoat, toggleFlag: toggleList, tickerData }

  const evals = useMemo(() => {
    const out = {}
    for (let i = 1; i <= 12; i++) out[i] = evaluateNashStep(i, form)
    return out
  }, [form])

  const scorecardTotal = useMemo(() => form.s6.scores.reduce((a, b) => a + (b || 0), 0), [form])
  const scoreBand = scorecardBand(scorecardTotal)
  const failedSteps = useMemo(() => {
    const failed = []
    for (let i = 1; i <= 12; i++) {
      if (i === 6) continue
      if (evals[i]?.pass !== true) failed.push(i)
    }
    return failed
  }, [evals])
  const failedNow = failedSteps.filter(n => evals[n]?.pass === false)
  const verdict = decideVerdict(failedSteps, scorecardTotal)

  const dcfCases = useMemo(() => {
    const s12 = form.s12
    const avgRev = numOrNull(s12.avgRevenue)
    const fcfM = numOrNull(s12.fcfMargin)
    const growth = numOrNull(s12.trimmedGrowth)
    const shares = numOrNull(s12.shares)
    const netCash = numOrNull(s12.netCash) || 0
    if (!avgRev || fcfM == null || growth == null || !shares) return null
    return [8, 10, 12].map(dr => ({ dr, value: computeDCFPerShare(avgRev, growth, fcfM, dr, shares, netCash) }))
  }, [form])

  function buildPrefilledForm(data, screenerRow) {
    const next = defaultForm()
    const ttm = data.ttm || {}
    const annual = data.annual || []
    const scr = screenerRow || null
    next.fromScreener = scr ? { ticker: scr.ticker, name: scr.name } : null
    next.s4.company = data.company_name || ''
    next.s3.revGrowth = scr?.revenue_growth != null ? (scr.revenue_growth * 100).toFixed(1) : (ttm.revenue_growth_yoy != null ? String(ttm.revenue_growth_yoy) : '')
    next.s3.fcfMargin = scr?.fcf_margin != null ? (scr.fcf_margin * 100).toFixed(1) : (ttm.fcf_margin != null ? String(ttm.fcf_margin) : '')
    next.s3.operatingMargin = scr?.operating_margin != null ? (scr.operating_margin * 100).toFixed(1) : (ttm.operating_margin != null ? String(ttm.operating_margin) : '')
    next.s3.marketCap = data.market_cap != null ? String(data.market_cap) : (scr?.market_cap != null ? String(scr.market_cap) : '')
    // 5-year history, oldest first for reading.
    const chronological = [...annual].reverse().slice(-5)
    next.s7.years = chronological.map(r => ({
      year: r.period || '', revenue: r.revenue ?? '', operatingIncome: r.operating_income ?? '',
      fcf: r.free_cash_flow ?? '', cash: r.cash ?? '', debt: r.total_debt ?? '',
    }))
    while (next.s7.years.length < 5) next.s7.years.push(emptyYearRow(''))
    const latest = annual[0] || {}
    const revenues = annual.slice(0, 3).map(r => r.revenue).filter(v => v != null)
    const avgRevenue = revenues.length ? revenues.reduce((a, b) => a + b, 0) / revenues.length : (latest.revenue || '')
    const annualFcfMargin = latest.free_cash_flow != null && latest.revenue ? (latest.free_cash_flow / latest.revenue) * 100 : null
    next.s12.price = data.current_price != null ? String(data.current_price) : ''
    next.s12.shares = dcfShares(data) != null ? String(dcfShares(data)) : ''
    next.s12.avgRevenue = avgRevenue !== '' ? String(avgRevenue) : ''
    next.s12.trimmedGrowth = String(dcfGrowthRate(ttm))
    next.s12.fcfMargin = next.s3.fcfMargin || (annualFcfMargin != null ? annualFcfMargin.toFixed(1) : '')
    next.s12.revGrowth = next.s3.revGrowth
    next.s12.netCash = latest.cash != null && latest.total_debt != null ? String(latest.cash - latest.total_debt) : ''
    next.s12.forwardPE = ttm.pe != null ? String(ttm.pe) : ''
    next.s12.epsGrowth = ttm.eps_growth_5y != null ? String(ttm.eps_growth_5y) : ''
    return next
  }

  async function startAnalysis(sym, screenerRow = null, savedForm = null) {
    const t = sym.toUpperCase().trim()
    if (!t) return
    setTicker(t)
    setView('wizard')
    setCurrentStep(1)
    setTickerData(null)
    setDataError(null)
    setLoadingData(true)
    try {
      const data = await api.twelveStep.getData(t)
      setTickerData(data)
      if (savedForm) {
        setForm({ ...defaultForm(), ...savedForm })
      } else {
        setForm(buildPrefilledForm(data, screenerRow))
      }
    } catch (e) {
      setDataError(e.message)
      if (savedForm) setForm({ ...defaultForm(), ...savedForm })
      else setForm(defaultForm())
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
        setScreenerError('FMP_API_KEY not configured. Add it to your .env file to enable the screener. Manual ticker entry still works.')
        setScreenerResults([])
        setScreenerOmitted([])
      } else {
        setScreenerResults(res.results || [])
        setScreenerOmitted(res.filters_omitted || [])
        setScreenerAsOf(new Date().toLocaleString())
      }
    } catch (e) {
      setScreenerError(e.message)
      setScreenerResults([])
    } finally {
      setScreenerLoading(false)
    }
  }

  function sortedResults() {
    if (!screenerResults) return []
    const rows = [...screenerResults]
    rows.sort((a, b) => {
      const av = a[sortKey], bv = b[sortKey]
      if (av == null && bv == null) return 0
      if (av == null) return 1
      if (bv == null) return -1
      if (typeof av === 'string') return av.localeCompare(bv) * sortDir
      return (av - bv) * sortDir
    })
    return rows
  }

  function finishAnalysis() {
    const analysis = {
      id: `${ticker}-${Date.now()}`,
      ticker,
      date: new Date().toISOString().slice(0, 10),
      company_name: tickerData?.company_name || ticker,
      form,
      scorecardTotal,
      scoreBand,
      verdict,
      failedSteps,
    }
    saveAnalysis(analysis)
    setSavedAnalyses(loadAnalyses())
  }

  function duplicateAnalysis(a) {
    const copy = { ...a, id: `${a.ticker}-${Date.now()}`, date: new Date().toISOString().slice(0, 10) }
    saveAnalysis(copy)
    setSavedAnalyses(loadAnalyses())
  }

  function removeAnalysis(id) {
    deleteAnalysis(id)
    setSavedAnalyses(loadAnalyses())
  }

  const step = STEPS[currentStep - 1]
  const isVerdict = currentStep === 13
  const currentEval = !isVerdict ? evals[currentStep] : null
  const currentStatus = !isVerdict ? (currentEval?.pass === true ? 'pass' : currentEval?.pass === false ? 'fail' : null) : null

  // ── Landing ──────────────────────────────────────────────────────────────────
  if (view === 'landing') {
    return (
      <div style={{ maxWidth: '860px', margin: '0 auto' }}>
        <div style={{ marginBottom: '24px' }}>
          <h1 style={{ color: C.text, fontSize: '22px', fontWeight: 700, margin: 0 }}>12 Step Stock Analysis</h1>
          <p style={{ color: C.muted, fontSize: '13px', marginTop: '6px' }}>
            Tom Nash 12-step stock research framework. It works like Survivor: fail any step and the company is off the island.
          </p>
        </div>

        <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: '12px', padding: '20px', marginBottom: '16px' }}>
          <h3 style={{ color: C.text, fontSize: '15px', fontWeight: 600, margin: '0 0 12px' }}>Analyze a Stock</h3>
          <div style={{ display: 'flex', gap: '10px' }}>
            <input
              value={tickerInput}
              onChange={e => setTickerInput(e.target.value.toUpperCase())}
              onKeyDown={e => e.key === 'Enter' && tickerInput && startAnalysis(tickerInput)}
              placeholder="e.g. AAPL, NVDA, MSFT"
              style={{ flex: 1, padding: '10px 14px', background: C.cardAlt, border: `1px solid ${C.border}`, borderRadius: '8px', color: C.text, fontSize: '14px', outline: 'none' }}
            />
            <button
              onClick={() => tickerInput && startAnalysis(tickerInput)}
              disabled={!tickerInput}
              style={{ padding: '10px 20px', background: C.accent, color: '#0f1117', border: 'none', borderRadius: '8px', fontWeight: 700, fontSize: '14px', cursor: tickerInput ? 'pointer' : 'not-allowed', opacity: tickerInput ? 1 : 0.5 }}
            >
              Start Analysis →
            </button>
          </div>
        </div>

        <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: '12px', padding: '20px', marginBottom: '16px' }}>
          <h3 style={{ color: C.text, fontSize: '15px', fontWeight: 600, margin: '0 0 8px' }}>The five rules</h3>
          {FIVE_RULES.map((r, i) => <div key={i} style={{ color: C.muted, fontSize: '13px', padding: '3px 0' }}>{i + 1}. {r}</div>)}
        </div>

        <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: '12px', padding: '20px', marginBottom: '24px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <h3 style={{ color: C.text, fontSize: '15px', fontWeight: 600, margin: 0 }}>Find Candidates with Screener</h3>
              <p style={{ color: C.muted, fontSize: '12px', margin: '4px 0 0' }}>
                Nash Step 3 pre-screen: FCF positive, net cash positive, revenue growth at least 10%, market cap at least $1B, short interest at most 10%, operating margin at least 20%, US-listed. Results are a starting point: verify against the 10-K before trusting them.
              </p>
            </div>
            <button
              onClick={() => setView('screener')}
              style={{ padding: '8px 18px', background: C.cardAlt, color: C.accent, border: `1px solid ${C.accent}`, borderRadius: '8px', fontWeight: 600, fontSize: '13px', cursor: 'pointer', marginLeft: '12px', flexShrink: 0 }}
            >
              Open Screener
            </button>
          </div>
        </div>

        <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: '12px', padding: '20px', marginBottom: '24px' }}>
          <h3 style={{ color: C.text, fontSize: '14px', fontWeight: 600, margin: '0 0 12px' }}>The 12 Steps at a Glance</h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '8px' }}>
            {STEPS.map(s => (
              <div key={s.num} style={{ display: 'flex', gap: '8px', alignItems: 'flex-start', padding: '8px', background: C.cardAlt, borderRadius: '6px' }}>
                <span style={{ color: C.faint, fontSize: '11px', fontWeight: 700, minWidth: '18px' }}>{s.num}.</span>
                <div>
                  <div style={{ color: C.text, fontSize: '12px', fontWeight: 600 }}>{s.icon} {s.title}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {savedAnalyses.length > 0 && (
          <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: '12px', padding: '20px' }}>
            <h3 style={{ color: C.text, fontSize: '14px', fontWeight: 600, margin: '0 0 12px' }}>Saved Analyses</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {savedAnalyses.slice(0, 20).map(a => {
                const isLegacy = !a.form
                const vLabel = isLegacy ? 'Legacy format' : (a.verdict === 'SURVIVOR' ? 'Survives all 12' : 'Off the island')
                return (
                  <div key={a.id} style={{ display: 'flex', alignItems: 'center', gap: '12px', padding: '10px 12px', background: C.cardAlt, borderRadius: '8px', border: `1px solid ${C.border}` }}>
                    <span
                      onClick={() => a.form ? startAnalysis(a.ticker, null, a.form) : startAnalysis(a.ticker)}
                      style={{ color: C.accent, fontWeight: 700, fontSize: '14px', minWidth: '56px', cursor: 'pointer' }}
                    >{a.ticker}</span>
                    <span style={{ color: C.muted, fontSize: '12px', flex: 1 }}>{a.company_name || ''} {a.date ? `(${a.date})` : ''}</span>
                    <Chip label={vLabel} color={a.verdict === 'SURVIVOR' ? C.green : C.red} bg={a.verdict === 'SURVIVOR' ? C.greenDim : C.redDim} border={a.verdict === 'SURVIVOR' ? C.greenBorder : C.redBorder} />
                    <button onClick={() => duplicateAnalysis(a)} style={{ background: 'none', border: 'none', color: C.muted, cursor: 'pointer', fontSize: '12px' }}>Duplicate</button>
                    <button onClick={() => removeAnalysis(a.id)} style={{ background: 'none', border: 'none', color: C.red, cursor: 'pointer', fontSize: '12px' }}>Delete</button>
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
    const numField = (key, label, stepVal = 1) => (
      <div>
        <label style={{ color: C.muted, fontSize: '11px', display: 'block', marginBottom: '4px' }}>{label}</label>
        <input
          type="number" step={stepVal} value={screenerFilters[key]}
          onChange={e => setScreenerFilters(p => ({ ...p, [key]: parseFloat(e.target.value) || 0 }))}
          style={{ width: '100%', padding: '8px', background: C.cardAlt, border: `1px solid ${C.border}`, borderRadius: '6px', color: C.text, fontSize: '12px' }}
        />
      </div>
    )
    const toggleField = (key, label) => (
      <label style={{ display: 'flex', gap: '8px', alignItems: 'center', color: C.text, fontSize: '12px', cursor: 'pointer' }}>
        <input type="checkbox" checked={screenerFilters[key]} onChange={e => setScreenerFilters(p => ({ ...p, [key]: e.target.checked }))} />
        {label}
      </label>
    )
    const columns = [
      { key: 'ticker', label: 'Ticker' }, { key: 'name', label: 'Company' }, { key: 'price', label: 'Price' },
      { key: 'market_cap', label: 'Mkt Cap' }, { key: 'revenue_growth', label: 'Rev Growth' },
      { key: 'fcf_margin', label: 'FCF Margin' }, { key: 'rule_of_40', label: 'Rule of 40' },
      { key: 'operating_margin', label: 'Op Margin' }, { key: 'short_interest', label: 'Short Interest' },
    ]
    const fmtPct = (decimal) => decimal != null ? `${(decimal * 100).toFixed(1)}%` : '-'
    return (
      <div style={{ maxWidth: '1000px', margin: '0 auto' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '20px' }}>
          <button onClick={() => onBack ? onBack() : setView('landing')} style={{ background: 'none', border: 'none', color: C.muted, cursor: 'pointer', fontSize: '13px' }}>← Back</button>
          <h2 style={{ color: C.text, fontSize: '18px', fontWeight: 700, margin: 0 }}>Stock Screener (Nash Step 3)</h2>
        </div>

        <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: '12px', padding: '16px', marginBottom: '16px' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px', alignItems: 'end' }}>
            {numField('market_cap_min', 'Min Market Cap ($)')}
            {numField('revenue_growth_min', 'Min Revenue Growth %', 0.5)}
            {numField('operating_margin_min', 'Min Operating Margin %', 0.5)}
            {numField('short_interest_max', 'Max Short Interest %', 0.5)}
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
            {numField('min_volume', 'Min Volume')}
            {numField('limit', 'Results (max 100)')}
            <button
              onClick={runScreener}
              disabled={screenerLoading}
              style={{ padding: '9px 16px', background: C.accent, color: '#0f1117', border: 'none', borderRadius: '8px', fontWeight: 700, fontSize: '13px', cursor: screenerLoading ? 'not-allowed' : 'pointer', opacity: screenerLoading ? 0.7 : 1 }}
            >
              {screenerLoading ? 'Screening…' : 'Run Scan'}
            </button>
          </div>
          <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap', marginTop: '12px' }}>
            {toggleField('fcf_positive', 'FCF positive')}
            {toggleField('net_cash_positive', 'Net cash positive (verify in Step 3, not supplied by screener data)')}
            {toggleField('exclude_china', 'Exclude China (country filter)')}
            {toggleField('exclude_airlines', 'Exclude airlines')}
            {toggleField('exclude_commodities', 'Exclude commodity producers')}
          </div>
          <p style={{ color: C.faint, fontSize: '11px', marginTop: '10px' }}>
            Fewer than 2 earnings misses in the last 4 quarters is a Nash filter, but the free screener data does not supply earnings surprise history, so it is omitted and must be checked manually in Step 3. Short interest and net cash are likewise not supplied by the screener data and are shown as not supplied in the results.
          </p>
        </div>

        {screenerError && (
          <div style={{ padding: '12px 16px', background: C.redDim, border: `1px solid ${C.redBorder}`, borderRadius: '8px', color: C.red, fontSize: '13px', marginBottom: '12px' }}>
            {screenerError}
          </div>
        )}

        {screenerAsOf && screenerResults && (
          <p style={{ color: C.faint, fontSize: '11px' }}>Data as of {screenerAsOf}. Screener data is a starting point: verify against the 10-K before trusting it. {screenerOmitted.length > 0 && `Filters not supplied by the data: ${screenerOmitted.join(', ')}.`}</p>
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
                    {columns.map(c => (
                      <th
                        key={c.key}
                        onClick={() => { if (sortKey === c.key) setSortDir(d => -d); else { setSortKey(c.key); setSortDir(-1) } }}
                        style={{ padding: '10px 12px', textAlign: c.key === 'ticker' || c.key === 'name' ? 'left' : 'right', color: C.muted, fontWeight: 600, borderBottom: `1px solid ${C.border}`, whiteSpace: 'nowrap', cursor: 'pointer' }}
                      >{c.label}{sortKey === c.key ? (sortDir === -1 ? ' ↓' : ' ↑') : ''}</th>
                    ))}
                    <th style={{ padding: '10px 12px', color: C.muted, borderBottom: `1px solid ${C.border}` }}></th>
                  </tr>
                </thead>
                <tbody>
                  {sortedResults().map(r => (
                    <tr key={r.ticker} style={{ borderBottom: `1px solid ${C.border}` }}>
                      <td style={{ padding: '10px 12px', color: C.accent, fontWeight: 700 }}>{r.ticker}</td>
                      <td style={{ padding: '10px 12px', color: C.text, maxWidth: '160px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.name}</td>
                      <td style={{ padding: '10px 12px', textAlign: 'right', color: C.text, fontVariantNumeric: 'tabular-nums' }}>${r.price?.toFixed(2) ?? '-'}</td>
                      <td style={{ padding: '10px 12px', textAlign: 'right', color: C.muted }}>{r.market_cap ? `$${fmtNum(r.market_cap)}` : '-'}</td>
                      <td style={{ padding: '10px 12px', textAlign: 'right', color: C.text }}>{fmtPct(r.revenue_growth)}</td>
                      <td style={{ padding: '10px 12px', textAlign: 'right', color: C.text }}>{fmtPct(r.fcf_margin)}</td>
                      <td style={{ padding: '10px 12px', textAlign: 'right', color: C.accent, fontWeight: 600 }}>{r.rule_of_40 != null ? r.rule_of_40.toFixed(1) : '-'}</td>
                      <td style={{ padding: '10px 12px', textAlign: 'right', color: C.text }}>{fmtPct(r.operating_margin)}</td>
                      <td style={{ padding: '10px 12px', textAlign: 'right', color: C.faint }}>not supplied</td>
                      <td style={{ padding: '10px 12px' }}>
                        <button
                          onClick={() => startAnalysis(r.ticker, r)}
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
  return (
    <div style={{ maxWidth: '860px', margin: '0 auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '16px' }}>
        <button
          onClick={() => onBack ? onBack() : setView('landing')}
          style={{ background: 'none', border: 'none', color: C.muted, cursor: 'pointer', fontSize: '13px' }}
        >
          ← Back
        </button>
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
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
            {form.fromScreener && <Chip label="from screener" color={C.accent} bg={C.accentDim} border={C.accent} />}
          </div>
        </div>
      </div>

      <div style={{ display: 'flex', gap: '3px', marginBottom: '20px', padding: '12px', background: C.card, borderRadius: '10px', border: `1px solid ${C.border}` }}>
        {STEPS.map(s => {
          const ev = evals[s.num]
          const st = s.num === 6 ? null : (ev?.pass === true ? 'pass' : ev?.pass === false ? 'fail' : null)
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
              <span style={{ fontSize: '10px', color: st ? statusColor(st) : C.faint }}>{s.num === 6 ? `${scorecardTotal}` : (st ? statusIcon(st) : '○')}</span>
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

      {failedNow.length > 0 && !isVerdict && (
        <div style={{ padding: '10px 14px', background: C.redDim, border: `1px solid ${C.redBorder}`, borderRadius: '8px', marginBottom: '12px', fontSize: '12px', color: C.red }}>
          <strong>Off the island</strong> - failed step{failedNow.length !== 1 ? 's' : ''}: {failedNow.map(n => `Step ${n}: ${STEPS[n - 1].title}`).join(', ')}.
          Continue anyway: use Next to finish the scorecard for learning. The final verdict will still list every failure.
        </div>
      )}

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

      {isVerdict && (
        <div>
          <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: '12px', padding: '20px', marginBottom: '16px' }}>
            <h2 style={{ color: C.text, fontSize: '18px', fontWeight: 700, margin: '0 0 16px' }}>Final Verdict: {ticker}</h2>
            {verdict === 'SURVIVOR' ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: '16px', padding: '16px', background: C.greenDim, borderRadius: '10px', border: `1px solid ${C.greenBorder}`, marginBottom: '20px' }}>
                <div style={{ fontSize: '40px', lineHeight: 1 }}>🟢</div>
                <div>
                  <div style={{ color: C.green, fontSize: '24px', fontWeight: 800 }}>Survives all 12</div>
                  <div style={{ color: C.muted, fontSize: '12px', marginTop: '2px' }}>A company you could own for 20 years. Scorecard {scorecardTotal} / 130, {scoreBand}.</div>
                </div>
              </div>
            ) : (
              <div style={{ display: 'flex', alignItems: 'center', gap: '16px', padding: '16px', background: C.redDim, borderRadius: '10px', border: `1px solid ${C.redBorder}`, marginBottom: '20px' }}>
                <div style={{ fontSize: '40px', lineHeight: 1 }}>🔴</div>
                <div>
                  <div style={{ color: C.red, fontSize: '24px', fontWeight: 800 }}>Off the island</div>
                  <div style={{ color: C.muted, fontSize: '12px', marginTop: '2px' }}>
                    Failed step{failedSteps.length !== 1 ? 's' : ''}: {failedSteps.map(n => `Step ${n}: ${STEPS[n - 1].title}`).join(', ')}.
                    Scorecard {scorecardTotal} / 130, {scoreBand}.
                  </div>
                </div>
              </div>
            )}
            {scorecardTotal < 75 && (
              <div style={{ padding: '10px 14px', background: C.redDim, border: `1px solid ${C.redBorder}`, borderRadius: '8px', marginBottom: '16px', fontSize: '12px', color: C.red }}>
                <strong>No-go:</strong> scorecard below 75, regardless of the step list.
              </div>
            )}

            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px', marginBottom: '16px' }}>
              <thead>
                <tr style={{ background: C.cardAlt }}>
                  <th style={{ padding: '6px 10px', textAlign: 'left', color: C.muted, borderBottom: `1px solid ${C.border}` }}>#</th>
                  <th style={{ padding: '6px 10px', textAlign: 'left', color: C.muted, borderBottom: `1px solid ${C.border}` }}>Step</th>
                  <th style={{ padding: '6px 10px', textAlign: 'left', color: C.muted, borderBottom: `1px solid ${C.border}` }}>Assessment</th>
                  <th style={{ padding: '6px 10px', textAlign: 'left', color: C.muted, borderBottom: `1px solid ${C.border}` }}>Detail</th>
                </tr>
              </thead>
              <tbody>
                {STEPS.map(s => {
                  const ev = evals[s.num]
                  const st = s.num === 6 ? null : (ev?.pass === true ? 'pass' : 'fail')
                  return (
                    <tr key={s.num} style={{ borderBottom: `1px solid ${C.border}`, background: st ? statusBg(st) + '55' : 'transparent' }}>
                      <td style={{ padding: '7px 10px', color: C.faint }}>{s.num}</td>
                      <td style={{ padding: '7px 10px', color: C.text, fontWeight: 500 }}>{s.icon} {s.title}</td>
                      <td style={{ padding: '7px 10px' }}>{s.num === 6 ? <Chip label={`${scorecardTotal} / 130, ${scoreBand}`} /> : <StatusBadge status={st} />}</td>
                      <td style={{ padding: '7px 10px', color: C.muted, fontSize: '11px' }}>{ev?.reason || '-'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>

            {dcfCases && (
              <div style={{ padding: '12px 16px', background: C.cardAlt, borderRadius: '8px', border: `1px solid ${C.border}`, marginBottom: '12px' }}>
                <div style={{ display: 'flex', gap: '24px', flexWrap: 'wrap' }}>
                  {dcfCases.map(c => (
                    <div key={c.dr}>
                      <div style={{ color: C.muted, fontSize: '11px' }}>DCF at {c.dr}% ({c.dr === 8 ? 'bull' : c.dr === 10 ? 'base' : 'bear'})</div>
                      <div style={{ color: C.accent, fontSize: '18px', fontWeight: 700 }}>${c.value != null ? c.value.toFixed(2) : '-'}</div>
                    </div>
                  ))}
                  <div>
                    <div style={{ color: C.muted, fontSize: '11px' }}>Current Price</div>
                    <div style={{ color: C.text, fontSize: '18px', fontWeight: 700 }}>${tickerData?.current_price?.toFixed(2) ?? form.s12.price ?? '-'}</div>
                  </div>
                </div>
              </div>
            )}

            <div style={{ background: C.cardAlt, borderRadius: '8px', border: `1px solid ${C.border}`, padding: '16px', marginBottom: '16px' }}>
              <h3 style={{ color: C.text, fontSize: '14px', fontWeight: 600, margin: '0 0 8px' }}>After the 12 steps</h3>
              <p style={{ color: C.muted, fontSize: '12px', margin: '0 0 8px' }}>Buy slowly: a fixed amount, on a fixed date, automated. Never lump sum.</p>
              <p style={{ color: C.muted, fontSize: '12px', margin: '0 0 8px' }}>Write your exit before you buy. Fraud means out immediately. A slowly breaking thesis means selling gradually over about 18 months. Price moves are never a reason.</p>
              <p style={{ color: C.muted, fontSize: '12px', margin: '0 0 12px' }}>Check it every quarter: listen to the earnings call, re-run the scorecard once a year. When the stock drops, ask only whether anything meaningful changed about the business.</p>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '10px' }}>
                <Field label="Why I own it"><textarea value={form.after.whyOwn} onChange={e => setStep('after', { whyOwn: e.target.value })} rows={2} style={{ ...inputStyle, resize: 'vertical' }} /></Field>
                <Field label="What would make me sell"><textarea value={form.after.whatWouldSell} onChange={e => setStep('after', { whatWouldSell: e.target.value })} rows={2} style={{ ...inputStyle, resize: 'vertical' }} /></Field>
              </div>
            </div>

            <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
              <button
                onClick={finishAnalysis}
                style={{ padding: '8px 20px', background: C.accentDim, color: C.accent, border: `1px solid ${C.accent}`, borderRadius: '8px', fontWeight: 600, fontSize: '13px', cursor: 'pointer' }}
              >
                Save Analysis
              </button>
              <button
                onClick={() => onBack ? onBack() : setView('landing')}
                style={{ padding: '8px 20px', background: C.cardAlt, color: C.text, border: `1px solid ${C.border}`, borderRadius: '8px', fontWeight: 600, fontSize: '13px', cursor: 'pointer' }}
              >
                {onBack ? '← Back to Candidates' : 'New Analysis'}
              </button>
            </div>
          </div>
        </div>
      )}

      {!isVerdict && step && (
        <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: '12px', padding: '20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '12px' }}>
            <div style={{
              width: '40px', height: '40px', borderRadius: '50%',
              background: currentStatus ? statusBg(currentStatus) : C.cardAlt,
              border: `2px solid ${currentStatus ? statusColor(currentStatus) : C.border}`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: '18px', flexShrink: 0,
            }}>
              {step.icon}
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ color: C.muted, fontSize: '11px', fontWeight: 600 }}>STEP {step.num}/12</span>
                {step.num === 6 && <Chip label={`${scorecardTotal} / 130, ${scoreBand}`} />}
              </div>
              <h2 style={{ color: C.text, fontSize: '17px', fontWeight: 700, margin: '2px 0 0' }}>{step.title}</h2>
            </div>
            {step.num === 6 ? <Chip label={`${scorecardTotal} / 130`} /> : <StatusBadge status={currentStatus} />}
          </div>

          <p style={{ color: C.muted, fontSize: '13px', margin: '0 0 4px' }}>{step.brief}</p>
          <p style={{ color: C.faint, fontSize: '12px', margin: '0 0 16px' }}>{step.detail}</p>

          {currentEval && currentEval.pass === false && (
            <div style={{ padding: '10px 14px', borderRadius: '8px', marginBottom: '14px', background: C.redDim, border: `1px solid ${C.redBorder}`, display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ color: C.red, fontWeight: 700 }}>✗</span>
              <span style={{ color: C.red, fontSize: '13px' }}>Off the island at this step: {currentEval.reason}. Continue anyway with Next to finish the scorecard for learning.</span>
            </div>
          )}
          {currentEval && currentEval.pass === true && (
            <div style={{ padding: '10px 14px', borderRadius: '8px', marginBottom: '14px', background: C.greenDim, border: `1px solid ${C.greenBorder}`, display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ color: C.green, fontWeight: 700 }}>✓</span>
              <span style={{ color: C.green, fontSize: '13px' }}>{currentEval.reason}</span>
            </div>
          )}

          <div style={{ marginBottom: '16px' }}>
            {loadingData
              ? <div style={{ color: C.muted, fontSize: '13px', padding: '12px 0' }}>Loading data…</div>
              : currentStep <= 6 ? renderStep(currentStep, ctx) : renderStepLater(currentStep, ctx)
            }
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <button
              onClick={() => setCurrentStep(s => Math.max(1, s - 1))}
              disabled={currentStep === 1}
              style={{ padding: '8px 20px', background: C.cardAlt, color: C.text, border: `1px solid ${C.border}`, borderRadius: '8px', fontWeight: 600, fontSize: '13px', cursor: currentStep === 1 ? 'not-allowed' : 'pointer', opacity: currentStep === 1 ? 0.4 : 1 }}
            >
              ← Back
            </button>
            <button
              onClick={() => setCurrentStep(s => Math.min(13, s + 1))}
              style={{ padding: '8px 24px', background: currentStep === 12 ? C.green : C.accent, color: '#0f1117', border: 'none', borderRadius: '8px', fontWeight: 700, fontSize: '13px', cursor: 'pointer' }}
            >
              {currentStep === 12 ? 'View Verdict →' : 'Next →'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
