import { useState, useEffect } from 'react'
import TwelveStepTab from './TwelveStepTab'
import { api } from '../api'

const C = {
  bg: '#0f1117', card: '#1a1f2e', bdr: '#2d3748',
  text: '#e2e8f0', muted: '#718096', sub: '#a0aec0', faint: '#4a5568',
  accent: '#63b3ed', green: '#68d391', yellow: '#f6e05e', red: '#fc8181',
  purple: '#a855f7', orange: '#ed8936',
}

const STORAGE_KEY = 'twelve_step_analyses_v1'

function loadWizardResult(ticker) {
  try {
    const all = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')
    return all.filter(a => a.ticker === ticker).sort((a, b) => b.date.localeCompare(a.date))[0] || null
  } catch { return null }
}

function computeVerdictFromSaved(a) {
  if (!a) return null
  const { stepResults = {}, moatFactors = [], dcfResult } = a
  let passes = 0, fails = 0
  for (let i = 1; i <= 12; i++) {
    const s = stepResults[i]?.status
    if (s === 'pass') passes++
    if (s === 'fail') fails++
  }
  const mos = dcfResult?.mos
  const moatStrong = moatFactors.length >= 3
  if (passes >= 9 && (mos == null || mos >= 20) && moatStrong) return 'BUY'
  if (passes >= 7 && fails <= 2) return 'WATCH'
  return 'AVOID'
}

const VERDICT_COLORS = { BUY: C.green, WATCH: C.yellow, AVOID: C.red }

function fmt$(v) {
  if (v == null) return '—'
  if (v >= 1000) return `$${(v / 1000).toFixed(1)}T`
  return `$${Math.round(v)}M`
}

function fmtPrice(p) {
  if (p == null) return null
  if (p >= 1000) return `$${p.toLocaleString('en-US', { maximumFractionDigits: 0 })}`
  if (p >= 100) return `$${Math.round(p)}`
  if (p >= 10) return `$${p.toFixed(1)}`
  return `$${p.toFixed(2)}`
}

// ── Detail panel – shown inline below a candidate card ──────────────────────
function DetailPanel({ pick, onRunWizard }) {
  const [dcfData, setDcfData] = useState(null)
  const [dcfLoading, setDcfLoading] = useState(false)
  const [dcfError, setDcfError] = useState(null)
  const [wizardResult, setWizardResult] = useState(() => loadWizardResult(pick.ticker))

  useEffect(() => {
    setDcfLoading(true)
    setDcfError(null)
    api.dcf.get(pick.ticker)
      .then(setDcfData)
      .catch(e => setDcfError(e.message))
      .finally(() => setDcfLoading(false))
    // Refresh wizard result from localStorage each time panel opens
    setWizardResult(loadWizardResult(pick.ticker))
  }, [pick.ticker])

  const verdict = computeVerdictFromSaved(wizardResult)
  const verdictColor = verdict ? VERDICT_COLORS[verdict] : C.muted
  const bearCase = wizardResult?.stepResults?.[11]?.notes?.trim()
  const moatNotes = wizardResult?.moatFactors || []

  const pctBelow = dcfData?.pct_below_52w_high ?? pick.pct_below_52w_high
  const beta = dcfData?.beta ?? pick.beta
  const nextEarnings = dcfData?.next_earnings_days

  const dcf = dcfData || pick // use discovery DCF as fallback while loading

  return (
    <div style={{ background: '#111827', border: `1px solid ${C.bdr}`, borderTop: 'none', borderRadius: '0 0 14px 14px', padding: '16px' }}>

      {/* 12-Step verdict (from localStorage) */}
      <div style={{ marginBottom: '14px' }}>
        <div style={{ fontSize: '11px', color: C.muted, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '6px' }}>
          12-Step Verdict
        </div>
        {wizardResult ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
            <span style={{ fontSize: '16px', fontWeight: 800, color: verdictColor, background: `${verdictColor}18`, border: `1px solid ${verdictColor}44`, borderRadius: '8px', padding: '3px 12px' }}>
              {verdict}
            </span>
            <span style={{ fontSize: '12px', color: C.sub }}>{wizardResult.date}</span>
            {moatNotes.length > 0 && (
              <span style={{ fontSize: '11px', color: C.accent, background: `${C.accent}15`, borderRadius: '5px', padding: '2px 7px' }}>
                {moatNotes.length} moat factor{moatNotes.length !== 1 ? 's' : ''}
              </span>
            )}
          </div>
        ) : (
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <span style={{ fontSize: '12px', color: C.faint }}>No wizard result yet</span>
            <button
              onClick={onRunWizard}
              style={{ padding: '4px 12px', background: C.accent, color: '#000', border: 'none', borderRadius: '6px', fontWeight: 700, cursor: 'pointer', fontSize: '12px' }}
            >
              Run 12 Step Analysis
            </button>
          </div>
        )}
      </div>

      {/* Scorecard summary */}
      {wizardResult && (
        <div style={{ marginBottom: '14px' }}>
          <div style={{ fontSize: '11px', color: C.muted, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '6px' }}>
            Scorecard
          </div>
          <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
            {[...Array(12)].map((_, i) => {
              const step = i + 1
              const status = wizardResult.stepResults?.[step]?.status
              const color = status === 'pass' ? C.green : status === 'fail' ? C.red : status === 'warn' ? C.yellow : C.faint
              return (
                <div key={step} title={`Step ${step}`} style={{ width: '22px', height: '22px', borderRadius: '4px', background: `${color}22`, border: `1px solid ${color}66`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '9px', color, fontWeight: 700 }}>
                  {step}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* DCF bear/base/bull */}
      <div style={{ marginBottom: '14px' }}>
        <div style={{ fontSize: '11px', color: C.muted, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '6px' }}>
          DCF Intrinsic Value
          {dcf.current_price && <span style={{ fontWeight: 400, textTransform: 'none', marginLeft: '6px', color: C.faint }}>current {fmtPrice(dcf.current_price)}</span>}
        </div>
        {dcfLoading && <div style={{ fontSize: '12px', color: C.muted }}>Loading fresh DCF...</div>}
        {dcfError && <div style={{ fontSize: '12px', color: C.red }}>DCF unavailable: {dcfError}</div>}
        {!dcfLoading && (
          <div style={{ display: 'flex', gap: '6px' }}>
            {[
              { label: 'Bear', val: dcf.dcf_bear, price: dcf.dcf_bear_price, upside: dcf.dcf_bear_upside, color: C.red },
              { label: 'Base', val: dcf.dcf_base, price: dcf.dcf_base_price, upside: dcf.dcf_base_upside, color: C.orange },
              { label: 'Bull', val: dcf.dcf_bull, price: dcf.dcf_bull_price, upside: dcf.dcf_bull_upside, color: C.green },
            ].map(s => (
              <div key={s.label} style={{ flex: 1, background: C.card, borderRadius: '8px', padding: '8px 6px', textAlign: 'center', borderTop: `2px solid ${s.color}` }}>
                <div style={{ fontSize: '10px', color: C.muted, marginBottom: '3px' }}>{s.label}</div>
                <div style={{ fontSize: '12px', fontWeight: 700, color: s.color }}>{fmt$(s.val)}</div>
                {fmtPrice(s.price) && <div style={{ fontSize: '11px', fontWeight: 700, color: C.text }}>{fmtPrice(s.price)}</div>}
                <div style={{ fontSize: '11px', color: (s.upside ?? 0) >= 0 ? C.green : C.red }}>
                  {s.upside != null ? `${s.upside >= 0 ? '+' : ''}${s.upside}%` : '—'}
                </div>
              </div>
            ))}
          </div>
        )}
        {dcfData?.recommendation && (
          <div style={{ marginTop: '8px', fontSize: '11px', color: C.sub }}>
            DCF recommendation: <span style={{ fontWeight: 700, color: C.text }}>{dcfData.recommendation}</span>
            {dcfData.wacc_pct && <span style={{ color: C.faint, marginLeft: '8px' }}>WACC {dcfData.wacc_pct}%</span>}
          </div>
        )}
      </div>

      {/* Price context + beta + earnings */}
      <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginBottom: '14px' }}>
        {pctBelow != null && (
          <div style={{ background: C.card, borderRadius: '7px', padding: '6px 10px', fontSize: '11px' }}>
            <div style={{ color: C.muted, fontSize: '10px' }}>Below 52w High</div>
            <div style={{ color: pctBelow > 20 ? C.red : pctBelow > 10 ? C.yellow : C.green, fontWeight: 700 }}>
              -{pctBelow}%
            </div>
          </div>
        )}
        {beta != null && (
          <div style={{ background: C.card, borderRadius: '7px', padding: '6px 10px', fontSize: '11px' }}>
            <div style={{ color: C.muted, fontSize: '10px' }}>Beta</div>
            <div style={{ color: C.text, fontWeight: 700 }}>{beta}</div>
          </div>
        )}
        {nextEarnings != null && (
          <div style={{ background: C.card, borderRadius: '7px', padding: '6px 10px', fontSize: '11px' }}>
            <div style={{ color: C.muted, fontSize: '10px' }}>Next Earnings</div>
            <div style={{ color: nextEarnings <= 14 ? C.yellow : C.text, fontWeight: 700 }}>in {nextEarnings}d</div>
          </div>
        )}
        {nextEarnings == null && dcfData && (
          <div style={{ background: C.card, borderRadius: '7px', padding: '6px 10px', fontSize: '11px' }}>
            <div style={{ color: C.muted, fontSize: '10px' }}>Next Earnings</div>
            <div style={{ color: C.faint }}>not in 30-day window</div>
          </div>
        )}
      </div>

      {/* "What would change my mind" – Step 11 bear case */}
      <div style={{ marginBottom: '10px' }}>
        <div style={{ fontSize: '11px', color: '#fc814a', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '4px' }}>
          What would change my mind
        </div>
        {bearCase ? (
          <div style={{ background: 'rgba(252,129,74,0.07)', borderLeft: '3px solid #fc814a', borderRadius: '0 6px 6px 0', padding: '8px 10px', fontSize: '12px', color: C.sub, lineHeight: 1.5 }}>
            {bearCase}
          </div>
        ) : (
          <div style={{ fontSize: '12px', color: C.faint, fontStyle: 'italic' }}>
            {wizardResult ? 'No bear case captured in Step 11 yet.' : 'Run the 12 Step wizard to record a bear case for this stock.'}
          </div>
        )}
      </div>

      {/* Run 12 Step button */}
      {wizardResult && (
        <button
          onClick={onRunWizard}
          style={{ marginTop: '6px', padding: '7px 18px', background: C.accent, color: '#000', border: 'none', borderRadius: '8px', fontWeight: 700, cursor: 'pointer', fontSize: '13px' }}
        >
          Re-run 12 Step Analysis
        </button>
      )}
    </div>
  )
}

// ── Candidate card ─────────────────────────────────────────────────────────
function CandidateCard({ pick, expanded, onToggle, onRunWizard }) {
  const mc = pick.market_cap_b > 0 ? `$${pick.market_cap_b}B` : null
  const revG = pick.revenue_growth_pct !== 0 ? `${pick.revenue_growth_pct > 0 ? '+' : ''}${pick.revenue_growth_pct}%` : null
  const gm = pick.gross_margin_pct > 0 ? `${pick.gross_margin_pct}%` : null
  const pe = pick.pe ? `${pick.pe}x` : null
  const score = pick.discovery_score != null ? Math.round(pick.discovery_score) : null

  return (
    <div style={{ marginBottom: '2px' }}>
      {/* Header row – always visible */}
      <div
        onClick={onToggle}
        style={{ background: C.card, border: `1px solid ${C.bdr}`, borderRadius: expanded ? '14px 14px 0 0' : '14px', borderBottom: expanded ? `1px solid ${C.bdr}` : undefined, padding: '14px 16px', cursor: 'pointer', display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '10px' }}
      >
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
            <span style={{ fontSize: '18px', fontWeight: 800, color: C.text }}>{pick.ticker}</span>
            {pick.sector && <span style={{ fontSize: '11px', color: C.faint, background: C.bdr, borderRadius: '5px', padding: '2px 7px' }}>{pick.sector}</span>}
            {score != null && (
              <span style={{ fontSize: '11px', fontWeight: 700, color: C.purple, background: `${C.purple}18`, borderRadius: '5px', padding: '2px 7px' }}>
                Score {score}
              </span>
            )}
            {pick.long_term_rec && (
              <span style={{ fontSize: '11px', fontWeight: 700, color: pick.long_term_rec === 'Strong Buy' || pick.long_term_rec === 'Buy' ? C.green : C.yellow, background: '#ffffff10', borderRadius: '5px', padding: '2px 7px' }}>
                {pick.long_term_rec}
              </span>
            )}
          </div>
          <div style={{ fontSize: '12px', color: C.muted, marginTop: '2px' }}>{pick.name}</div>
          <div style={{ display: 'flex', gap: '6px', marginTop: '8px', flexWrap: 'wrap' }}>
            {mc && <MetricChip label="Mkt Cap" value={mc} />}
            {revG && <MetricChip label="Rev Growth" value={revG} color={pick.revenue_growth_pct > 0 ? C.green : C.red} />}
            {gm && <MetricChip label="Gross Margin" value={gm} />}
            {pe && <MetricChip label="P/E" value={pe} />}
            {pick.pct_below_52w_high != null && <MetricChip label="Below 52w Hi" value={`-${pick.pct_below_52w_high}%`} color={pick.pct_below_52w_high > 20 ? C.red : C.yellow} />}
          </div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '6px', flexShrink: 0 }}>
          <button
            onClick={e => { e.stopPropagation(); onRunWizard() }}
            style={{ padding: '6px 14px', background: 'linear-gradient(135deg,#6c63ff,#a855f7)', color: '#fff', border: 'none', borderRadius: '7px', fontWeight: 700, cursor: 'pointer', fontSize: '12px', whiteSpace: 'nowrap' }}
          >
            Run 12 Step
          </button>
          <span style={{ fontSize: '12px', color: C.faint }}>{expanded ? '▲ Close' : '▼ Details'}</span>
        </div>
      </div>

      {/* Expandable detail panel */}
      {expanded && <DetailPanel pick={pick} onRunWizard={onRunWizard} />}
    </div>
  )
}

function MetricChip({ label, value, color }) {
  return (
    <div style={{ background: C.bdr, borderRadius: '6px', padding: '4px 8px', fontSize: '11px', display: 'flex', flexDirection: 'column', gap: '1px' }}>
      <span style={{ color: C.faint, fontSize: '10px' }}>{label}</span>
      <span style={{ color: color || C.text, fontWeight: 700 }}>{value}</span>
    </div>
  )
}

// ── Section of candidates ──────────────────────────────────────────────────
function CandidateSection({ title, badge, badgeColor, desc, picks, expandedId, onToggle, onRunWizard }) {
  if (!picks?.length) return null
  return (
    <div style={{ marginBottom: '24px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '6px' }}>
        <h2 style={{ fontSize: '17px', fontWeight: 800, color: C.text, margin: 0 }}>{title}</h2>
        <span style={{ background: badgeColor, color: '#fff', borderRadius: '6px', padding: '2px 9px', fontSize: '11px', fontWeight: 700 }}>{badge}</span>
      </div>
      <p style={{ fontSize: '12px', color: C.muted, marginBottom: '12px', lineHeight: 1.5 }}>{desc}</p>
      {picks.map(pick => (
        <CandidateCard
          key={pick.ticker}
          pick={pick}
          expanded={expandedId === pick.ticker}
          onToggle={() => onToggle(pick.ticker)}
          onRunWizard={() => onRunWizard(pick.ticker)}
        />
      ))}
    </div>
  )
}

// ── Main tab ──────────────────────────────────────────────────────────────
export default function BuyHoldTab() {
  const [view, setView] = useState('candidates')
  const [wizardTicker, setWizardTicker] = useState(null)
  const [discovery, setDiscovery] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [expandedId, setExpandedId] = useState(null)

  useEffect(() => {
    setLoading(true)
    api.discovery.get()
      .then(setDiscovery)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  function handleRunWizard(ticker) {
    setWizardTicker(ticker)
    setView('wizard')
  }

  function handleBack() {
    setView('candidates')
    setExpandedId(null)
  }

  function handleToggle(ticker) {
    setExpandedId(prev => prev === ticker ? null : ticker)
  }

  if (view === 'wizard') {
    return (
      <TwelveStepTab
        key={wizardTicker}
        initialTicker={wizardTicker}
        onBack={handleBack}
      />
    )
  }

  const hasResults = discovery?.status === 'ready' && discovery?.results
  const isScanning = discovery?.status === 'scanning'
  const generatedAt = discovery?.generated_at
    ? new Date(discovery.generated_at).toLocaleString()
    : null

  return (
    <div style={{ minHeight: '100vh', background: C.bg, color: C.text, fontFamily: "'Inter', sans-serif", padding: '0 0 60px' }}>

      {/* Hero */}
      <div style={{ background: 'linear-gradient(135deg,#0d1f3c 0%,#1a0a2e 50%,#0d1f3c 100%)', borderBottom: `1px solid ${C.bdr}`, padding: '28px 20px 24px', textAlign: 'center' }}>
        <h1 style={{ fontSize: '22px', fontWeight: 800, color: '#fff', margin: '0 0 4px', letterSpacing: '-0.3px' }}>
          Buy and Hold
        </h1>
        <p style={{ fontSize: '13px', color: C.muted, margin: '0 0 18px' }}>
          Discovery candidates + 12-Step deep-dive analysis
        </p>
        {loading && <div style={{ fontSize: '13px', color: C.muted }}>Loading cached results...</div>}
        {!loading && !hasResults && !isScanning && (
          <p style={{ fontSize: '12px', color: C.muted, lineHeight: 1.5 }}>
            No discovery results yet. Open the Discovery screen and run a scan, then come back.
          </p>
        )}
        {!loading && generatedAt && (
          <div style={{ fontSize: '12px', color: C.faint }}>
            Last scan: {generatedAt}
            {discovery?.results?.fundamentals_fetched && <span> · {discovery.results.fundamentals_fetched} companies analyzed</span>}
          </div>
        )}
        {isScanning && (
          <div style={{ fontSize: '12px', color: C.yellow }}>Discovery scan in progress...</div>
        )}
        {error && <div style={{ fontSize: '12px', color: C.red }}>Error: {error}</div>}
      </div>

      {/* Candidates */}
      {hasResults && (
        <div style={{ padding: '24px 16px 8px', maxWidth: '800px', margin: '0 auto' }}>
          {discovery.results.claude_fallback && (
            <div style={{ background: '#2d2000', border: '1px solid #b7791f', borderRadius: '8px', padding: '10px 14px', fontSize: '13px', color: '#fbd38d', marginBottom: '16px' }}>
              AI thesis generation failed on last scan — showing top-ranked candidates by quant score.
            </div>
          )}
          <CandidateSection
            title="Next Compounders"
            badge="High Growth"
            badgeColor="linear-gradient(135deg,#6c63ff,#a855f7)"
            desc="High-growth companies with dominant market positions and scalable business models."
            picks={discovery.results.compounders}
            expandedId={expandedId}
            onToggle={handleToggle}
            onRunWizard={handleRunWizard}
          />
          <CandidateSection
            title="Sleeper Picks"
            badge="Hidden Value"
            badgeColor="linear-gradient(135deg,#38b2ac,#4299e1)"
            desc="Profitable, under-the-radar companies with strong moats and growing earnings."
            picks={discovery.results.sleepers}
            expandedId={expandedId}
            onToggle={handleToggle}
            onRunWizard={handleRunWizard}
          />
        </div>
      )}
    </div>
  )
}
