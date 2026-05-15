import { useState } from 'react'

const API = import.meta.env.VITE_API_URL || ''

// ─── Action config ────────────────────────────────────────────────────────────
const ACTION_CONFIG = {
  'STRONG BUY': { bg: '#0a2218', border: '#276749', color: '#48bb78', badge: '#276749', badgeText: '#c6f6d5', icon: '🚀' },
  'SMALL BUY':  { bg: '#0a1a0a', border: '#2f855a', color: '#68d391', badge: '#2f855a', badgeText: '#c6f6d5', icon: '↑' },
  'WATCH':      { bg: '#2d2000', border: '#b7791f', color: '#fbd38d', badge: '#b7791f', badgeText: '#fefcbf', icon: '👁' },
  'PASS':       { bg: '#2d1515', border: '#742a2a', color: '#fc8181', badge: '#742a2a', badgeText: '#fed7d7', icon: '✕' },
  'BLOCKED':    { bg: '#2d1800', border: '#c05621', color: '#ed8936', badge: '#c05621', badgeText: '#feebc8', icon: '⛔' },
}

const PROTECTION_CONFIG = {
  low:      { color: '#68d391', bg: '#0a2218', border: '#2f855a', label: 'Protected downside' },
  moderate: { color: '#fbd38d', bg: '#2d2000', border: '#b7791f', label: 'Moderate downside risk' },
  high:     { color: '#fc8181', bg: '#2d1515', border: '#742a2a', label: 'High downside risk — position size accordingly' },
}

// ─── Score badge ──────────────────────────────────────────────────────────────
function TriggerBadge({ score, action, blocked, suggestedSize }) {
  const cfg = ACTION_CONFIG[action] || ACTION_CONFIG['WATCH']
  return (
    <div style={{
      background: cfg.bg, border: `2px solid ${cfg.border}`,
      borderRadius: '12px', padding: '20px 24px',
      display: 'flex', alignItems: 'center', gap: '20px', flexWrap: 'wrap',
    }}>
      {/* Score circle */}
      <div style={{ textAlign: 'center', flexShrink: 0 }}>
        <div style={{
          width: '80px', height: '80px', borderRadius: '50%',
          background: cfg.badge, display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center',
        }}>
          <span style={{ fontSize: '28px', fontWeight: 900, color: cfg.badgeText, lineHeight: 1 }}>
            {score}
          </span>
          <span style={{ fontSize: '11px', color: cfg.badgeText, opacity: 0.8 }}>/8</span>
        </div>
        <div style={{ fontSize: '10px', color: '#718096', marginTop: '4px' }}>TRIGGER SCORE</div>
      </div>

      {/* Action label + size */}
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
          <span style={{ fontSize: '22px' }}>{cfg.icon}</span>
          <span style={{ fontSize: '22px', fontWeight: 900, color: cfg.color }}>{action}</span>
        </div>
        {blocked && (
          <div style={{ fontSize: '13px', color: '#ed8936', fontWeight: 600 }}>
            Earnings within 14 days — wait for post-earnings entry
          </div>
        )}
        {suggestedSize && (
          <div style={{
            display: 'inline-flex', alignItems: 'center', gap: '6px',
            padding: '5px 12px', background: cfg.badge, borderRadius: '6px',
            fontSize: '13px', fontWeight: 700, color: cfg.badgeText,
          }}>
            Suggested position: {suggestedSize}
          </div>
        )}
        {!blocked && !suggestedSize && action !== 'PASS' && (
          <div style={{ fontSize: '12px', color: '#718096' }}>Monitor — not enough conviction yet</div>
        )}
      </div>

      {/* Score bar */}
      <div style={{ flex: 1, minWidth: '160px' }}>
        <div style={{ height: '8px', background: '#1a1f2e', borderRadius: '4px', overflow: 'hidden' }}>
          <div style={{
            width: `${(score / 8) * 100}%`, height: '100%',
            background: cfg.badge, borderRadius: '4px',
            transition: 'width 0.4s ease',
          }} />
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '4px', fontSize: '10px', color: '#4a5568' }}>
          <span>0</span><span>WATCH 3</span><span>BUY 5</span><span>STRONG 7</span><span>8</span>
        </div>
      </div>
    </div>
  )
}

// ─── Score breakdown ──────────────────────────────────────────────────────────
function ScoreBreakdown({ breakdown }) {
  if (!breakdown) return null
  const items = [
    breakdown.monte_carlo,
    breakdown.ma,
    breakdown.earnings,
    breakdown.bear,
    breakdown.base,
  ].filter(Boolean)

  return (
    <div style={{ background: '#0f1117', border: '1px solid #2d3748', borderRadius: '10px', padding: '16px 20px' }}>
      <div style={{ fontSize: '11px', color: '#718096', fontWeight: 600, letterSpacing: '0.08em', marginBottom: '12px' }}>
        POINT BREAKDOWN
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {items.map((item, i) => {
          const earned = item.earned
          const isWarning = item.warning
          const dotColor = earned === null ? '#4a5568'
            : earned === item.max ? '#68d391'
            : earned > 0 ? '#fbd38d'
            : isWarning ? '#ed8936'
            : '#fc8181'
          return (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              {/* Points earned */}
              <div style={{ display: 'flex', gap: '3px', flexShrink: 0 }}>
                {Array.from({ length: item.max }).map((_, j) => (
                  <div key={j} style={{
                    width: '10px', height: '10px', borderRadius: '50%',
                    background: earned !== null && j < earned ? dotColor : '#2d3748',
                    border: `1px solid ${dotColor}`,
                  }} />
                ))}
              </div>
              {/* Label */}
              <span style={{ fontSize: '12px', color: '#718096', minWidth: '90px', flexShrink: 0 }}>
                {item.label}
              </span>
              {/* Detail */}
              <span style={{ fontSize: '12px', color: isWarning ? '#ed8936' : earned ? '#e2e8f0' : '#718096' }}>
                {item.detail}
              </span>
              {/* Earned badge */}
              <span style={{ marginLeft: 'auto', fontSize: '11px', fontWeight: 700, color: dotColor, flexShrink: 0 }}>
                {earned === null ? '—' : `+${earned}`}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ─── MA status card ───────────────────────────────────────────────────────────
function MaStatusCard({ ma50, aboveMa, crossover5d, currentPrice }) {
  if (ma50 == null) return null
  const isAbove = aboveMa
  const color = crossover5d ? '#48bb78' : isAbove ? '#68d391' : '#fc8181'
  const bg = crossover5d ? '#0a2218' : isAbove ? '#0a1a10' : '#2d1515'
  const border = crossover5d ? '#276749' : isAbove ? '#2f855a' : '#742a2a'
  return (
    <div style={{ background: bg, border: `1px solid ${border}`, borderRadius: '8px', padding: '12px 16px' }}>
      <div style={{ fontSize: '11px', color: '#718096', fontWeight: 600, letterSpacing: '0.08em', marginBottom: '6px' }}>
        50-DAY MOVING AVERAGE
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
        <span style={{ fontSize: '16px', fontWeight: 700, color }}>
          {crossover5d ? '🚀 Golden cross (last 5 days)' : isAbove ? '↑ Above MA' : '↓ Below MA'}
        </span>
        <span style={{ fontSize: '13px', color: '#a0aec0' }}>
          MA: ${ma50.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          {currentPrice && ` · Price: $${currentPrice.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
        </span>
        {currentPrice && ma50 && (
          <span style={{ fontSize: '12px', color }}>
            ({((currentPrice - ma50) / ma50 * 100).toFixed(1)}% vs MA)
          </span>
        )}
      </div>
    </div>
  )
}

// ─── Bear protection card ─────────────────────────────────────────────────────
function BearProtectionCard({ level, label, bearUpside }) {
  if (!level) return null
  const cfg = PROTECTION_CONFIG[level] || PROTECTION_CONFIG.moderate
  return (
    <div style={{ background: cfg.bg, border: `1px solid ${cfg.border}`, borderRadius: '8px', padding: '12px 16px' }}>
      <div style={{ fontSize: '11px', color: '#718096', fontWeight: 600, letterSpacing: '0.08em', marginBottom: '4px' }}>
        BEAR CASE PROTECTION
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
        <span style={{ fontSize: '16px', fontWeight: 700, color: cfg.color }}>{cfg.label}</span>
        {bearUpside != null && (
          <span style={{ fontSize: '13px', color: '#a0aec0' }}>
            Bear case: <span style={{ color: cfg.color, fontWeight: 600 }}>{bearUpside > 0 ? '+' : ''}{bearUpside}%</span>
          </span>
        )}
      </div>
    </div>
  )
}

// ─── Portfolio summary ────────────────────────────────────────────────────────
function PortfolioSummary({ portfolio, selected, onSelect, onRemove }) {
  if (!portfolio.length) return null
  const sorted = [...portfolio].sort((a, b) => {
    if (a.blocked && !b.blocked) return 1
    if (!a.blocked && b.blocked) return -1
    return b.score - a.score
  })
  return (
    <div style={{ marginBottom: '24px' }}>
      <div style={{ fontSize: '11px', color: '#718096', fontWeight: 600, letterSpacing: '0.08em', marginBottom: '10px' }}>
        PORTFOLIO WATCHLIST — ranked by trigger score
      </div>
      <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
        {sorted.map(s => {
          const cfg = ACTION_CONFIG[s.action] || ACTION_CONFIG['WATCH']
          const isActive = s.ticker === selected
          return (
            <div
              key={s.ticker}
              onClick={() => onSelect(s.ticker)}
              style={{
                display: 'flex', alignItems: 'center', gap: '6px',
                padding: '6px 10px 6px 12px',
                background: isActive ? cfg.badge : '#1a1f2e',
                border: `1px solid ${isActive ? cfg.border : '#2d3748'}`,
                borderRadius: '8px', cursor: 'pointer',
                transition: 'all 0.15s',
              }}
            >
              <span style={{ fontSize: '13px', fontWeight: 700, color: isActive ? cfg.badgeText : '#e2e8f0' }}>
                {s.ticker}
              </span>
              <span style={{
                fontSize: '11px', fontWeight: 700,
                padding: '1px 6px', borderRadius: '4px',
                background: cfg.badge, color: cfg.badgeText,
              }}>
                {s.blocked ? '⛔' : s.score}/8
              </span>
              <span
                onClick={e => { e.stopPropagation(); onRemove(s.ticker) }}
                style={{ fontSize: '11px', color: '#4a5568', cursor: 'pointer', marginLeft: '2px', lineHeight: 1 }}
                title="Remove"
              >×</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ─── DCF sub-components (preserved from DCF tab) ─────────────────────────────
function MetricPill({ label, value }) {
  return (
    <div style={{
      background: '#0f1117', border: '1px solid #2d3748',
      borderRadius: '6px', padding: '6px 10px', textAlign: 'center', minWidth: '60px',
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
      borderRadius: '10px', padding: '14px 12px', textAlign: 'center',
    }}>
      <div style={{ fontSize: '11px', color: '#718096', fontWeight: 600, letterSpacing: '0.08em', marginBottom: '8px' }}>
        {label}
      </div>
      {price != null && (
        <div style={{
          fontSize: '20px', fontWeight: 800, marginBottom: '2px',
          color: label === 'BULL' ? '#68d391' : label === 'BEAR' ? '#fc8181' : '#90cdf4',
        }}>
          ${price.toLocaleString()}
        </div>
      )}
      <div style={{ fontSize: '14px', fontWeight: 700, color: up >= 0 ? '#68d391' : '#fc8181', marginBottom: '8px' }}>
        {upside != null ? `${up > 0 ? '+' : ''}${up}%` : '—'}
      </div>
      <div style={{ fontSize: '11px', color: '#718096', lineHeight: 1.5 }}>
        <div>Rev growth yr1-5: {g1Pct}%</div>
        <div>FCF margin: {fcfPct}%</div>
      </div>
    </div>
  )
}

function MonteCarloSection({ mc, currentPrice }) {
  if (!mc || mc.prob_undervalued_pct == null) return null
  const ps = mc.per_share
  const prob = mc.prob_undervalued_pct
  const probColor = prob >= 60 ? '#68d391' : prob >= 40 ? '#fbd38d' : '#fc8181'
  const probBg    = prob >= 60 ? '#0a2218' : prob >= 40 ? '#2d2000' : '#2d1515'
  const probBorder = prob >= 60 ? '#276749' : prob >= 40 ? '#b7791f' : '#742a2a'
  const allVals = [ps.p10, ps.p25, ps.median, ps.p75, ps.p90, currentPrice].filter(Boolean)
  const barMin = Math.min(...allVals) * 0.92
  const barMax = Math.max(...allVals) * 1.08
  const pct = v => `${Math.max(0, Math.min(100, (v - barMin) / (barMax - barMin) * 100)).toFixed(1)}%`
  const hist = mc.histogram || []
  const maxCount = hist.length ? Math.max(...hist.map(h => h.count)) : 1
  return (
    <div style={{ background: '#0f1117', border: '1px solid #2d3748', borderRadius: '10px', padding: '18px 20px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <span style={{ fontSize: '11px', color: '#718096', fontWeight: 600, letterSpacing: '0.08em' }}>MONTE CARLO DCF</span>
          <span style={{ marginLeft: '8px', fontSize: '11px', color: '#4a5568' }}>{mc.n_simulations?.toLocaleString()} simulations</span>
        </div>
      </div>
      <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap', alignItems: 'flex-start' }}>
        <div style={{ padding: '16px 20px', minWidth: '130px', textAlign: 'center', background: probBg, border: `1px solid ${probBorder}`, borderRadius: '10px', flexShrink: 0 }}>
          <div style={{ fontSize: '36px', fontWeight: 900, color: probColor, lineHeight: 1 }}>{prob}%</div>
          <div style={{ fontSize: '11px', color: '#a0aec0', marginTop: '6px', lineHeight: 1.4 }}>chance stock is<br />undervalued today</div>
        </div>
        <div style={{ flex: 1, minWidth: '220px' }}>
          <div style={{ fontSize: '11px', color: '#718096', marginBottom: '10px', fontWeight: 600 }}>INTRINSIC VALUE RANGE (PER SHARE)</div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
            {[['p10','10th'],['p25','25th'],['median','50th'],['p75','75th'],['p90','90th']].map(([k,label]) => (
              <div key={k} style={{ textAlign: 'center' }}>
                <div style={{ fontSize: '10px', color: '#4a5568', marginBottom: '2px' }}>{label}</div>
                <div style={{ fontSize: '13px', fontWeight: 700, color: k === 'median' ? '#90cdf4' : '#e2e8f0' }}>${ps[k]?.toLocaleString()}</div>
              </div>
            ))}
          </div>
          <div style={{ position: 'relative', height: '24px', background: '#1a1f2e', borderRadius: '4px', overflow: 'visible' }}>
            <div style={{ position: 'absolute', left: pct(ps.p25), width: `calc(${pct(ps.p75)} - ${pct(ps.p25)})`, top: '4px', height: '16px', background: '#2b6cb0', borderRadius: '3px', opacity: 0.6 }} />
            <div style={{ position: 'absolute', left: pct(ps.p10), width: `calc(${pct(ps.p90)} - ${pct(ps.p10)})`, top: '11px', height: '2px', background: '#4a5568' }} />
            <div style={{ position: 'absolute', left: pct(ps.median), top: '2px', width: '2px', height: '20px', background: '#90cdf4', transform: 'translateX(-1px)' }} />
            {currentPrice && <div style={{ position: 'absolute', left: pct(currentPrice), top: '2px', width: '2px', height: '20px', background: '#f6e05e', transform: 'translateX(-1px)' }} />}
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '4px', fontSize: '10px', color: '#4a5568' }}>
            <span>◼ IQR (p25–p75)</span>
            {currentPrice && <span style={{ color: '#f6e05e' }}>▲ Current ${currentPrice}</span>}
            <span style={{ color: '#90cdf4' }}>| Median</span>
          </div>
        </div>
      </div>
      {hist.length > 0 && (
        <div>
          <div style={{ fontSize: '10px', color: '#4a5568', marginBottom: '6px' }}>Distribution of {mc.n_simulations?.toLocaleString()} simulated intrinsic values (per share)</div>
          <div style={{ display: 'flex', alignItems: 'flex-end', gap: '1px', height: '48px' }}>
            {hist.map((bar, i) => {
              const heightPct = maxCount > 0 ? (bar.count / maxCount) * 100 : 0
              const isCurrentBin = currentPrice && bar.x <= currentPrice && (hist[i+1]?.x || Infinity) > currentPrice
              return (
                <div key={i} title={`$${bar.x} — ${bar.count} simulations`} style={{ flex: 1, height: `${heightPct}%`, minHeight: bar.count > 0 ? '2px' : '0', background: isCurrentBin ? '#f6e05e' : '#2b6cb0', opacity: 0.85, borderRadius: '1px 1px 0 0' }} />
              )
            })}
          </div>
          <div style={{ fontSize: '9px', color: '#4a5568', marginTop: '3px', textAlign: 'center' }}>
            {currentPrice && <span style={{ color: '#f6e05e' }}>■ Current price bin  </span>}■ DCF value distribution
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Main tab ─────────────────────────────────────────────────────────────────
const RECO_CONFIG = {
  'Strong Buy': { bg: '#1a3a2a', border: '#2f855a', color: '#68d391', icon: '🚀' },
  'Buy':        { bg: '#0a1628', border: '#2b6cb0', color: '#90cdf4', icon: '↑' },
  'Hold':       { bg: '#2d2a00', border: '#b7791f', color: '#fbd38d', icon: '⟷' },
  'Pass':       { bg: '#3a1a1a', border: '#c53030', color: '#fc8181', icon: '✕' },
}

function RecoChip({ rec }) {
  const c = RECO_CONFIG[rec] || RECO_CONFIG['Hold']
  return (
    <div style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', padding: '7px 16px', background: c.bg, border: `1px solid ${c.border}`, borderRadius: '8px', color: c.color, fontSize: '14px', fontWeight: 700 }}>
      {c.icon} {rec}
    </div>
  )
}

function loadPortfolio() {
  try { return JSON.parse(localStorage.getItem('trigger_portfolio') || '[]') } catch { return [] }
}
function savePortfolio(p) {
  try { localStorage.setItem('trigger_portfolio', JSON.stringify(p)) } catch {}
}

export default function StockTriggersTab() {
  const [ticker, setTicker] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [selectedTicker, setSelectedTicker] = useState(null)
  const [portfolio, setPortfolio] = useState(loadPortfolio)

  async function analyze(t) {
    const sym = (t || ticker).trim().toUpperCase()
    if (!sym) return
    setLoading(true)
    setResult(null)
    setError(null)
    setSelectedTicker(sym)
    try {
      const resp = await fetch(`${API}/api/triggers/${encodeURIComponent(sym)}`)
      const body = await resp.json().catch(() => ({}))
      if (!resp.ok) throw new Error(body.detail || `Error ${resp.status}`)
      setResult(body)
      // Upsert into portfolio
      setPortfolio(prev => {
        const filtered = prev.filter(p => p.ticker !== sym)
        const entry = {
          ticker: sym,
          score: body.trigger_score,
          action: body.trigger_action,
          blocked: body.trigger_blocked,
        }
        const next = [...filtered, entry].sort((a, b) => {
          if (a.blocked && !b.blocked) return 1
          if (!a.blocked && b.blocked) return -1
          return b.score - a.score
        })
        savePortfolio(next)
        return next
      })
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  function removeFromPortfolio(sym) {
    setPortfolio(prev => {
      const next = prev.filter(p => p.ticker !== sym)
      savePortfolio(next)
      return next
    })
    if (selectedTicker === sym) {
      setSelectedTicker(null)
      setResult(null)
    }
  }

  function handleKey(e) { if (e.key === 'Enter') analyze() }

  const r = result

  return (
    <div style={{ maxWidth: '900px' }}>
      {/* Header */}
      <div style={{ marginBottom: '20px' }}>
        <h2 style={{ fontSize: '20px', fontWeight: 700, color: '#e2e8f0', margin: '0 0 4px' }}>
          🎯 Stock Triggers
        </h2>
        <p style={{ fontSize: '13px', color: '#718096', margin: 0 }}>
          DCF · Monte Carlo · 50-day MA crossover · Earnings calendar · 0–8 point trigger score
        </p>
      </div>

      {/* Portfolio summary */}
      <PortfolioSummary
        portfolio={portfolio}
        selected={selectedTicker}
        onSelect={sym => { setTicker(sym); analyze(sym) }}
        onRemove={removeFromPortfolio}
      />

      {/* Search */}
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
          onClick={() => analyze()}
          disabled={loading || !ticker.trim()}
          style={{
            padding: '10px 24px',
            background: loading || !ticker.trim() ? '#2d3748' : '#276749',
            color: loading || !ticker.trim() ? '#718096' : '#c6f6d5',
            border: 'none', borderRadius: '8px',
            cursor: loading || !ticker.trim() ? 'not-allowed' : 'pointer',
            fontSize: '14px', fontWeight: 600, transition: 'background 0.15s',
          }}
        >
          {loading ? 'Analyzing…' : 'Run Trigger Analysis'}
        </button>
      </div>

      {error && (
        <div style={{ color: '#fc8181', padding: '14px 16px', background: '#2d1515', border: '1px solid #742a2a', borderRadius: '8px', marginBottom: '16px', fontSize: '14px' }}>
          {error}
        </div>
      )}

      {loading && (
        <div style={{ color: '#a0aec0', textAlign: 'center', padding: '60px 24px', fontSize: '14px' }}>
          <div style={{ fontSize: '28px', marginBottom: '12px' }}>🎯</div>
          Running DCF, Monte Carlo, 50-day MA, earnings check…
        </div>
      )}

      {r && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>

          {/* ── Stock header ── */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '10px' }}>
            <div>
              <div style={{ fontSize: '26px', fontWeight: 800, color: '#90cdf4' }}>{r.ticker}</div>
              <div style={{ fontSize: '14px', color: '#a0aec0', marginTop: '2px' }}>{r.name} · {r.sector}</div>
            </div>
            <RecoChip rec={r.recommendation} />
          </div>

          {/* ── Trigger badge ── */}
          <TriggerBadge
            score={r.trigger_score}
            action={r.trigger_action}
            blocked={r.trigger_blocked}
            suggestedSize={r.suggested_position_size}
          />

          {/* ── Score breakdown ── */}
          <ScoreBreakdown breakdown={r.trigger_breakdown} />

          {/* ── MA + Bear protection side-by-side ── */}
          <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
            <div style={{ flex: 1, minWidth: '240px' }}>
              <MaStatusCard
                ma50={r.ma50}
                aboveMa={r.above_ma}
                crossover5d={r.crossover_5d}
                currentPrice={r.current_price}
              />
            </div>
            <div style={{ flex: 1, minWidth: '240px' }}>
              <BearProtectionCard
                level={r.bear_protection_level}
                label={r.bear_protection_label}
                bearUpside={r.dcf_bear_upside}
              />
            </div>
          </div>

          {/* ── Earnings warning ── */}
          {r.earnings_days != null && r.earnings_days <= 14 && (
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: '10px', padding: '12px 16px', background: '#2d1800', border: '1px solid #c05621', borderRadius: '8px' }}>
              <span style={{ fontSize: '18px', lineHeight: 1, flexShrink: 0 }}>⚠️</span>
              <div>
                <div style={{ fontSize: '13px', fontWeight: 700, color: '#ed8936' }}>
                  Earnings in {r.earnings_days === 0 ? 'today or tomorrow' : `${r.earnings_days} day${r.earnings_days === 1 ? '' : 's'}`} — elevated IV risk
                </div>
                <div style={{ fontSize: '12px', color: '#c05621', marginTop: '2px' }}>
                  Trigger blocked. Consider waiting until after earnings to enter this trade.
                </div>
              </div>
            </div>
          )}

          {/* ─────────────────── DCF SECTION (preserved exactly) ─────────────── */}
          <div style={{ borderTop: '1px solid #2d3748', paddingTop: '20px' }}>
            <div style={{ fontSize: '11px', color: '#718096', fontWeight: 600, letterSpacing: '0.08em', marginBottom: '16px' }}>
              FULL DCF ANALYSIS — CAPM WACC · Reverse DCF · Monte Carlo (10,000 simulations)
            </div>

            {/* Market context */}
            <div style={{ marginBottom: '16px' }}>
              <div style={{ fontSize: '11px', color: '#718096', fontWeight: 600, letterSpacing: '0.08em', marginBottom: '8px' }}>MARKET CONTEXT</div>
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
            <div style={{ background: '#0f1117', border: '1px solid #2d3748', borderRadius: '8px', padding: '14px 16px', marginBottom: '16px' }}>
              <div style={{ fontSize: '11px', color: '#718096', fontWeight: 600, letterSpacing: '0.08em', marginBottom: '6px' }}>
                REVERSE DCF — GROWTH RATE THE MARKET IS CURRENTLY PRICING IN
              </div>
              <div style={{ fontSize: '24px', fontWeight: 800, color: '#fbd38d' }}>{r.implied_growth_pct}% / year</div>
              <div style={{ fontSize: '12px', color: '#a0aec0', marginTop: '4px', lineHeight: 1.6 }}>
                At today's market cap of ${r.market_cap_b}B, investors are implying {r.implied_growth_pct}% annual revenue growth over the next decade. Our base case DCF implies{' '}
                {r.dcf_base_upside != null
                  ? <span style={{ color: r.dcf_base_upside >= 0 ? '#68d391' : '#fc8181', fontWeight: 700 }}>
                      {r.dcf_base_upside > 0 ? '+' : ''}{r.dcf_base_upside}% {r.dcf_base_upside >= 0 ? 'upside' : 'downside'}
                    </span>
                  : 'unknown upside'
                }.
              </div>
            </div>

            {/* Monte Carlo */}
            <div style={{ marginBottom: '16px' }}>
              <MonteCarloSection mc={r.monte_carlo} currentPrice={r.current_price} />
            </div>

            {/* DCF Scenarios */}
            <div style={{ marginBottom: '16px' }}>
              <div style={{ fontSize: '11px', color: '#718096', fontWeight: 600, letterSpacing: '0.08em', marginBottom: '10px' }}>
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
                <ScenarioCard label="BULL" price={r.dcf_bull_price} upside={r.dcf_bull_upside} g1Pct={r.bull_g1_pct} fcfPct={r.bull_fcf_pct} />
                <ScenarioCard label="BASE" price={r.dcf_base_price} upside={r.dcf_base_upside} g1Pct={r.base_g1_pct} fcfPct={r.base_fcf_pct} highlight />
                <ScenarioCard label="BEAR" price={r.dcf_bear_price} upside={r.dcf_bear_upside} g1Pct={r.bear_g1_pct} fcfPct={r.bear_fcf_pct} />
              </div>
            </div>

            {/* Claude reasoning */}
            {r.scenario_reasoning && (
              <div style={{ background: '#0a1628', border: '1px solid #2b6cb0', borderRadius: '8px', padding: '14px 16px' }}>
                <div style={{ fontSize: '11px', color: '#4299e1', fontWeight: 600, letterSpacing: '0.08em', marginBottom: '6px' }}>
                  CLAUDE'S REASONING
                  {r.scenario_confidence && (
                    <span style={{ marginLeft: '8px', padding: '1px 7px', background: '#1a3a5a', color: '#90cdf4', borderRadius: '4px', fontSize: '10px', textTransform: 'uppercase' }}>
                      {r.scenario_confidence} confidence
                    </span>
                  )}
                </div>
                <p style={{ fontSize: '13px', color: '#a0aec0', margin: 0, lineHeight: 1.6 }}>{r.scenario_reasoning}</p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
