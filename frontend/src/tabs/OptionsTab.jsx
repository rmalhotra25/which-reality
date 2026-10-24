import { useState, useEffect, useCallback } from 'react'
import { api } from '../api'

// ---------------------------------------------------------------------------
// Regime banner
// ---------------------------------------------------------------------------
const REGIME_CONFIG = {
  GREEN:   { bg: '#1a3a1a', border: '#276749', color: '#68d391', label: 'Market regime: GREEN' },
  YELLOW:  { bg: '#3a3200', border: '#b7791f', color: '#f6e05e', label: 'Market regime: YELLOW (caution)' },
  RED:     { bg: '#3a1a1a', border: '#c53030', color: '#fc8181', label: 'Market regime: RED (suppressed)' },
  UNKNOWN: { bg: '#1a1f2e', border: '#4a5568', color: '#a0aec0', label: 'Market regime: UNKNOWN' },
}

function RegimeBanner({ verdict, dataComplete, suppressedReason }) {
  const cfg = REGIME_CONFIG[verdict] || REGIME_CONFIG.UNKNOWN
  const showSuppressMsg = !dataComplete || verdict === 'UNKNOWN' || verdict === 'RED'
  return (
    <div style={{
      background: cfg.bg,
      border: `1px solid ${cfg.border}`,
      borderRadius: 8,
      padding: '10px 16px',
      marginBottom: 20,
      display: 'flex',
      flexDirection: 'column',
      gap: 4,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{
          width: 10, height: 10, borderRadius: '50%',
          background: cfg.color, flexShrink: 0,
        }} />
        <span style={{ color: cfg.color, fontWeight: 700, fontSize: 13 }}>{cfg.label}</span>
      </div>
      {showSuppressMsg && (
        <div style={{ color: '#a0aec0', fontSize: 12, paddingLeft: 20 }}>
          {suppressedReason
            || 'New long-premium recommendations suspended until market conditions improve.'}
        </div>
      )}
      {verdict === 'YELLOW' && (
        <div style={{ color: '#f6e05e', fontSize: 12, paddingLeft: 20 }}>
          Recommendations shown with a caution flag. In a downtrend, puts are favoured and calls are against-regime.
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Badge atoms
// ---------------------------------------------------------------------------
function IVCrushBadge({ earningsDays }) {
  return (
    <span style={{
      background: '#c53030', color: '#fff',
      borderRadius: 4, padding: '2px 8px', fontSize: 11, fontWeight: 700,
      letterSpacing: '0.03em',
    }}>
      IV CRUSH RISK{earningsDays != null ? ` (${earningsDays}d)` : ''}
    </span>
  )
}

function AgainstRegimeBadge() {
  return (
    <span style={{
      background: '#3a3200', color: '#f6e05e', border: '1px solid #b7791f',
      borderRadius: 4, padding: '2px 8px', fontSize: 11, fontWeight: 600,
    }}>
      AGAINST REGIME
    </span>
  )
}

function AiUnavailableBadge() {
  return (
    <span style={{
      background: '#2d2d2d', color: '#718096', border: '1px solid #4a5568',
      borderRadius: 4, padding: '2px 8px', fontSize: 11,
    }}>
      AI unavailable
    </span>
  )
}

// Risk tier comes from real P(profit) only (backend). Reward-to-risk is
// shown beside it as context and never changes the tier.
const TIER_CONFIG = {
  lower:    { label: 'Lower risk',  bg: '#1a3a1a', border: '#276749', color: '#68d391' },
  balanced: { label: 'Balanced',    bg: '#1a2f4a', border: '#2b6cb0', color: '#90cdf4' },
  higher:   { label: 'Higher risk', bg: '#3a2a1a', border: '#9c4221', color: '#f6ad55' },
}

function TierBadge({ tier }) {
  const cfg = TIER_CONFIG[tier]
  if (!cfg) return null
  return (
    <span style={{
      background: cfg.bg, color: cfg.color, border: `1px solid ${cfg.border}`,
      borderRadius: 4, padding: '2px 8px', fontSize: 11, fontWeight: 700,
      letterSpacing: '0.03em',
    }}>
      {cfg.label.toUpperCase()}
    </span>
  )
}

function FitsChallengeBadge() {
  return (
    <span style={{
      background: '#2a1a3a', color: '#d6bcfa', border: '1px solid #6b46c1',
      borderRadius: 4, padding: '2px 8px', fontSize: 11, fontWeight: 700,
      letterSpacing: '0.03em',
    }}>
      FITS CHALLENGE
    </span>
  )
}

function FavoursPutBadge() {
  return (
    <span style={{
      background: '#1a3a2a', color: '#68d391', border: '1px solid #2f855a',
      borderRadius: 4, padding: '2px 8px', fontSize: 11, fontWeight: 700,
      letterSpacing: '0.03em',
    }}>
      FAVOURS PUTS
    </span>
  )
}

function PutSpreadBadge() {
  return (
    <span style={{
      background: '#2a1a3a', color: '#d6bcfa', border: '1px solid #6b46c1',
      borderRadius: 4, padding: '2px 8px', fontSize: 11, fontWeight: 700,
      letterSpacing: '0.03em',
    }}>
      BEAR SPREAD
    </span>
  )
}

// Premium source label: a last-trade or fair-value premium is never
// presented as a live quote.
function premiumSourceLabel(source) {
  if (source === 'ask') return 'Ask (buy price)'
  if (source === 'last trade') return 'Last trade, 15-min delayed, not a live quote'
  if (source === 'fair value') return 'Fair value estimate, not a live quote'
  return null
}

// ---------------------------------------------------------------------------
// Ranking formula row
// ---------------------------------------------------------------------------
const COMPONENT_LABELS = {
  prob_score:       { label: 'Probability', desc: 'P(profit) x 100 (diagnostic)' },
  rr_score:         { label: 'Reward/Risk', desc: 'single R/R, scaled (diagnostic)' },
  iv_context_score: { label: 'IV Context',  desc: 'IV percentile (diagnostic)' },
  trend_score:      { label: 'Trend',       desc: 'MA50 + MA200 alignment (diagnostic)' },
}

function ScoreBar({ value, max = 100 }) {
  if (value == null) {
    return <span style={{ color: '#718096', fontSize: 12, minWidth: 28, textAlign: 'right' }}>n/a</span>
  }
  const pct = Math.max(0, Math.min(100, (value / max) * 100))
  const color = pct >= 70 ? '#68d391' : pct >= 40 ? '#f6e05e' : '#fc8181'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1 }}>
      <div style={{ flex: 1, background: '#2d3748', borderRadius: 3, height: 6 }}>
        <div style={{ width: `${pct}%`, background: color, borderRadius: 3, height: '100%', transition: 'width 0.3s' }} />
      </div>
      <span style={{ color: '#e2e8f0', fontSize: 12, minWidth: 28, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{value}</span>
    </div>
  )
}

function RankingPanel({ c }) {
  const components = c.ranking_components || {}
  const evPerDollar = c.ev_per_dollar_risked ?? c.score
  return (
    <div style={{ background: '#111827', border: '1px solid #2d3748', borderRadius: 8, padding: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 4 }}>
        <span style={{ color: '#a0aec0', fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          Expected value (EV per $ risked)
        </span>
        <span style={{ color: '#e2e8f0', fontWeight: 800, fontSize: 18 }}>
          {evPerDollar != null ? `${evPerDollar >= 0 ? '+' : ''}${evPerDollar.toFixed(2)}` : 'n/a'}
        </span>
      </div>
      <div style={{ color: '#718096', fontSize: 11, marginBottom: 10 }}>
        {c.ev_dollars != null
          ? `EV per contract: ${c.ev_dollars >= 0 ? '+' : ''}$${c.ev_dollars.toFixed(0)}`
          : 'EV per contract: n/a'}
        {'  |  spread unknown (no live quotes)'}
      </div>
      {Object.entries(COMPONENT_LABELS).map(([key, meta]) => (
        <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
          <span style={{ color: '#718096', fontSize: 11, minWidth: 80 }}>{meta.label}</span>
          <ScoreBar value={c[key] ?? components[key]} />
          <span style={{ color: '#4a5568', fontSize: 10, minWidth: 100 }}>{meta.desc}</span>
        </div>
      ))}
      <div style={{ color: '#4a5568', fontSize: 10, marginTop: 8, fontFamily: 'monospace', lineHeight: 1.5 }}>
        {components.formula || ''}
      </div>
      <div style={{ color: '#4a5568', fontSize: 10, marginTop: 4, lineHeight: 1.5 }}>
        {c.iv_history_building
          ? 'IV history building: IV score hidden, no placeholder used'
          : c.iv_percentile != null
            ? `IV pct: ${c.iv_percentile}%`
            : c.iv_percentile_available === false ? 'IV pct: no data' : ''}
        {c.ranking_components?.reward_risk != null
          ? `  |  R/R: ${c.ranking_components.reward_risk.toFixed(2)}x (payoff at target / |payoff at stop|)`
          : ''}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Four numbers panel
// ---------------------------------------------------------------------------
function FourNumbers({ c }) {
  const rows = [
    {
      label: 'Expected move',
      value: c.expected_move_dollars != null
        ? `$${c.expected_move_dollars.toFixed(2)} (${c.expected_move_pct?.toFixed(1)}%)`
        : 'n/a',
      note: `vs. target $${c.underlying_target?.toFixed(2) ?? '?'} / stop $${c.underlying_stop?.toFixed(2) ?? '?'}`,
    },
    {
      label: 'Max loss / contract',
      value: c.max_loss_per_contract != null
        ? `$${c.max_loss_per_contract.toFixed(0)}`
        : 'n/a',
      note: `Buy ${c.option_type} $${c.strike} exp ${c.expiry} @ $${c.entry_premium?.toFixed(2) ?? '?'}`,
    },
    {
      label: 'Payoff at target',
      value: c.payoff_at_target != null
        ? `${c.payoff_at_target >= 0 ? '+' : ''}$${c.payoff_at_target.toFixed(0)}`
        : 'n/a',
      positive: c.payoff_at_target > 0,
    },
    {
      label: 'Payoff at stop (premium -50% rule)',
      value: c.payoff_at_stop != null
        ? `${c.payoff_at_stop >= 0 ? '+' : ''}$${c.payoff_at_stop.toFixed(0)}`
        : 'n/a',
      note: 'stop = stock level where the option is worth 50% of premium, at least one expected move away; at unchanged: -$' + (c.max_loss_per_contract?.toFixed(0) ?? '?') + ' (full loss)',
      positive: false,
    },
  ]
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
      {rows.map((r) => (
        <div key={r.label} style={{
          background: '#111827', border: '1px solid #2d3748', borderRadius: 6, padding: '10px 12px',
        }}>
          <div style={{ color: '#718096', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 4 }}>{r.label}</div>
          <div style={{ color: r.positive ? '#68d391' : r.positive === false ? '#fc8181' : '#e2e8f0', fontWeight: 700, fontSize: 15, fontVariantNumeric: 'tabular-nums' }}>
            {r.value}
          </div>
          {r.note && <div style={{ color: '#4a5568', fontSize: 10, marginTop: 3 }}>{r.note}</div>}
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Evidence section
// ---------------------------------------------------------------------------
function EvidenceSection({ c }) {
  const hasEvidence = c.momentum_score_raw != null || c.flow_signals
  if (!hasEvidence) return null
  return (
    <div style={{ background: '#111827', border: '1px solid #2d3748', borderRadius: 8, padding: '10px 14px' }}>
      <div style={{ color: '#4a5568', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>
        Untested context (not a ranking input)
      </div>
      {c.momentum_score_raw != null && (
        <div style={{ color: '#a0aec0', fontSize: 12, marginBottom: 4 }}>
          Momentum convergence: {c.momentum_score_raw.toFixed(1)} pts
        </div>
      )}
      {c.flow_signals && Array.isArray(c.flow_signals) && c.flow_signals.length > 0 && (
        <div style={{ color: '#a0aec0', fontSize: 12 }}>
          Flow signals: {c.flow_signals.map((s) => s.signal || s.type || JSON.stringify(s)).join(', ')}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Candidate card
// ---------------------------------------------------------------------------
function CandidateCard({ c, isYellow }) {
  const [showTradingView, setShowTradingView] = useState(false)
  const callStyle = { background: '#1a3a2a', color: '#68d391', border: '1px solid #2f855a' }
  const putStyle  = { background: '#3a1a1a', color: '#fc8181', border: '1px solid #c53030' }
  const optStyle  = c.option_type === 'CALL' ? callStyle : putStyle
  const comps = c.ranking_components || {}
  // In a BEAR regime puts are favoured, not against-regime, so the
  // badge is suppressed for them.
  const favoursPut = c.option_type === 'PUT' && comps.regime_favours_put
  const showAgainst = isYellow && !favoursPut
  const isSpread = comps.put_variant === 'bear_spread'
  const spread = comps.spread || null
  const plainCopy = comps.put_plain_copy || null
  const premiumLabel = premiumSourceLabel(comps.premium_source)
  const invalidation = c.underlying_stop != null
    ? `Exit if the stock closes ${c.option_type === 'PUT' ? 'above' : 'below'} $${c.underlying_stop.toFixed(2)}`
    : null

  return (
    <div style={{
      background: '#1a1f2e',
      border: `1px solid ${isYellow ? '#b7791f' : '#2d3748'}`,
      borderRadius: 12,
      padding: 20,
      display: 'flex',
      flexDirection: 'column',
      gap: 14,
    }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 22, fontWeight: 800, color: '#90cdf4' }}>{c.ticker}</span>
          {c.rank && (
            <span style={{ background: '#2d3748', color: '#a0aec0', borderRadius: 4, padding: '2px 8px', fontSize: 11, fontWeight: 600 }}>
              #{c.rank}
            </span>
          )}
          <span style={{ ...optStyle, borderRadius: 4, padding: '3px 10px', fontSize: 12, fontWeight: 700 }}>
            {c.option_type}
          </span>
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
          {c.risk_tier && <TierBadge tier={c.risk_tier} />}
          {c.fits_challenge && <FitsChallengeBadge />}
          {favoursPut && <FavoursPutBadge />}
          {isSpread && <PutSpreadBadge />}
          {c.iv_crush_risk && <IVCrushBadge earningsDays={c.earnings_days_away} />}
          {showAgainst && <AgainstRegimeBadge />}
          {c.ai_available === false && <AiUnavailableBadge />}
        </div>
      </div>

      {/* Price context */}
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
        {[
          { label: 'Price', val: c.current_price?.toFixed(2) },
          { label: 'Expiry', val: c.expiry },
          { label: 'DTE', val: c.dte != null ? `${c.dte}` : null },
          { label: 'Premium source', val: premiumLabel },
          { label: 'Entry', val: c.underlying_entry?.toFixed(2) },
          { label: 'Target', val: c.underlying_target?.toFixed(2) },
          { label: 'Stop', val: c.underlying_stop?.toFixed(2) },
          { label: 'ATM IV', val: c.atm_iv_pct != null ? `${c.atm_iv_pct.toFixed(1)}%` : null },
          { label: 'Contract IV', val: c.contract_iv_pct != null ? `${c.contract_iv_pct.toFixed(1)}%` : (c.iv_source === 'atm_fallback' && c.atm_iv_pct != null ? 'ATM fallback' : null) },
          { label: 'Delta (finish past strike)', val: c.delta_abs != null ? c.delta_abs.toFixed(2) : null },
          { label: 'P(profit)', val: c.prob_profit != null ? `${Math.round(c.prob_profit * 100)}%` : null },
          { label: 'P(touch target, approx)', val: c.prob_touch_target != null ? `${Math.round(c.prob_touch_target * 100)}%` : null },
          { label: 'P(touch stop, approx)', val: c.prob_touch_stop != null ? `${Math.round(c.prob_touch_stop * 100)}%` : null },
          { label: 'EV / contract', val: c.ev_dollars != null ? `${c.ev_dollars >= 0 ? '+' : ''}$${c.ev_dollars.toFixed(0)}` : null },
          { label: 'EV per $ risked', val: c.ev_per_dollar_risked != null ? `${c.ev_per_dollar_risked >= 0 ? '+' : ''}${c.ev_per_dollar_risked.toFixed(2)}` : null },
          { label: 'Reward/Risk', val: c.reward_risk != null ? `${c.reward_risk.toFixed(1)}x` : null },
          { label: 'Earnings', val: c.earnings_date ? `${c.earnings_date}${c.earnings_days_away != null ? ` (${c.earnings_days_away}d)` : ''}` : (c.earnings_in_window === false ? 'none in window' : null) },
        ].filter(x => x.val != null).map(({ label, val }) => (
          <div key={label}>
            <span style={{ color: '#4a5568', fontSize: 10, textTransform: 'uppercase' }}>{label} </span>
            <span style={{ color: '#e2e8f0', fontSize: 13, fontWeight: 600 }}>{val}</span>
          </div>
        ))}
      </div>

      {/* Ranking formula */}
      <RankingPanel c={c} />

      {/* Four numbers */}
      <FourNumbers c={c} />

      {/* Invalidation: puts fail when the stock closes ABOVE the stop */}
      {invalidation && (
        <div style={{ color: '#f6ad55', fontSize: 12 }}>
          {invalidation}
        </div>
      )}

      {/* Bear spread detail and plain-language put copy */}
      {isSpread && spread && (
        <div style={{ background: '#111827', border: '1px solid #2d3748', borderRadius: 8, padding: '10px 14px' }}>
          <div style={{ color: '#a0aec0', fontSize: 12, lineHeight: 1.6 }}>
            Bear spread: buy the ${spread.long_strike} put, sell the ${spread.short_strike} put.
            Net cost ${spread.net_debit.toFixed(2)} per share.
            Most you can lose: ${spread.max_loss.toFixed(0)} per contract.
            Most you can gain: ${spread.max_gain.toFixed(0)} per contract.
            Break-even: stock below ${spread.breakeven.toFixed(2)} at expiry.
          </div>
          {comps.put_iv_route && (
            <div style={{ color: '#718096', fontSize: 11, marginTop: 4 }}>{comps.put_iv_route}</div>
          )}
        </div>
      )}
      {plainCopy && Array.isArray(plainCopy) && (
        <div style={{ background: '#0f1623', border: '1px solid #2d3748', borderRadius: 8, padding: '10px 14px' }}>
          <div style={{ color: '#718096', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 }}>
            What this means for your money
          </div>
          {plainCopy.map((line, i) => (
            <div key={i} style={{ color: '#cbd5e0', fontSize: 13, lineHeight: 1.6, marginBottom: 4 }}>{line}</div>
          ))}
        </div>
      )}
      {comps.red_regime_put_allowed && (
        <div style={{ color: '#f6e05e', fontSize: 12 }}>
          Volatile market: puts allowed only as a hedge or speculation, calls are suppressed.
        </div>
      )}

      {/* AI explanation */}
      {c.ai_available !== false && c.ai_explanation && (
        <div style={{ background: '#0f1623', border: '1px solid #2d3748', borderRadius: 8, padding: '10px 14px' }}>
          <div style={{ color: '#718096', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 }}>
            Analysis
          </div>
          <div style={{ color: '#cbd5e0', fontSize: 13, lineHeight: 1.6 }}>{c.ai_explanation}</div>
        </div>
      )}

      {/* Untested evidence */}
      <EvidenceSection c={c} />

      {/* Chart toggle */}
      <button
        onClick={() => setShowTradingView(v => !v)}
        style={{
          background: 'none', border: '1px solid #2d3748', color: '#718096',
          borderRadius: 6, padding: '6px 12px', cursor: 'pointer', fontSize: 12,
          alignSelf: 'flex-start',
        }}
      >
        {showTradingView ? 'Hide chart' : 'Show chart'}
      </button>
      {showTradingView && (
        <div style={{ height: 300, borderRadius: 8, overflow: 'hidden' }}>
          <iframe
            src={`https://s.tradingview.com/widgetembed/?frameElementId=tv_${c.ticker}&symbol=${c.ticker}&interval=D&theme=dark&style=1&locale=en&enable_publishing=false&allow_symbol_change=false`}
            style={{ width: '100%', height: '100%', border: 'none' }}
            title={`${c.ticker} chart`}
          />
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Suppressed section
// ---------------------------------------------------------------------------
function SuppressedSection({ items }) {
  const [expanded, setExpanded] = useState(false)
  if (!items || items.length === 0) return null
  return (
    <div style={{ marginTop: 24 }}>
      <button
        onClick={() => setExpanded(v => !v)}
        style={{
          background: 'none', border: '1px solid #2d3748', color: '#4a5568',
          borderRadius: 6, padding: '6px 14px', cursor: 'pointer', fontSize: 12, marginBottom: 12,
        }}
      >
        {expanded ? 'Hide' : 'Show'} {items.length} suppressed candidate{items.length !== 1 ? 's' : ''}
      </button>
      {expanded && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {items.map((c) => (
            <div key={c.ticker + c.option_type} style={{
              background: '#111827', border: '1px solid #2d3748', borderRadius: 8,
              padding: '12px 16px', display: 'flex', justifyContent: 'space-between',
              alignItems: 'flex-start', flexWrap: 'wrap', gap: 8,
            }}>
              <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                <span style={{ color: '#718096', fontWeight: 700, fontSize: 15 }}>{c.ticker}</span>
                <span style={{
                  borderRadius: 4, padding: '2px 8px', fontSize: 11, fontWeight: 700,
                  background: c.option_type === 'CALL' ? '#1a3a2a' : '#3a1a1a',
                  color: c.option_type === 'CALL' ? '#68d391' : '#fc8181',
                }}>
                  {c.option_type}
                </span>
                <span style={{ color: '#4a5568', fontSize: 12 }}>EV/$: {c.score != null ? c.score.toFixed(2) : 'n/a'}</span>
              </div>
              <span style={{ color: '#4a5568', fontSize: 12, maxWidth: 400 }}>
                Suppressed: {c.suppressed_reason || 'regime gate'}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------
function EmptyState({ onRefresh, refreshing }) {
  return (
    <div style={{ textAlign: 'center', padding: '60px 20px', color: '#4a5568' }}>
      <div style={{ fontSize: 40, marginBottom: 12 }}>--</div>
      <div style={{ fontSize: 14, marginBottom: 20, color: '#718096' }}>
        No directional candidates yet. Run an analysis to populate results.
      </div>
      <button
        onClick={onRefresh}
        disabled={refreshing}
        style={{
          padding: '10px 24px', background: '#2b6cb0', color: '#fff',
          border: 'none', borderRadius: 8, cursor: refreshing ? 'default' : 'pointer',
          fontSize: 14, fontWeight: 600, opacity: refreshing ? 0.7 : 1,
        }}
      >
        {refreshing ? 'Running analysis...' : 'Run first analysis'}
      </button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main tab
// ---------------------------------------------------------------------------
export default function OptionsTab() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [refreshing, setRefreshing] = useState(false)
  const [pollCount, setPollCount] = useState(0)
  const [tierFilter, setTierFilter] = useState('all')

  const load = useCallback(async () => {
    try {
      const result = await api.options.getDirectional()
      setData(result)
      setError(null)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  // Poll for results after a refresh
  useEffect(() => {
    if (!refreshing) return
    const id = setInterval(async () => {
      try {
        const result = await api.options.getDirectional()
        const newRunAt = result?.run_at
        if (newRunAt && newRunAt !== data?.run_at) {
          setData(result)
          setRefreshing(false)
          clearInterval(id)
        }
        setPollCount(c => c + 1)
        if (pollCount > 30) {
          setRefreshing(false)
          clearInterval(id)
        }
      } catch (e) {
        // ignore poll errors
      }
    }, 3000)
    return () => clearInterval(id)
  }, [refreshing, data?.run_at, pollCount])

  const handleRefresh = async () => {
    setRefreshing(true)
    setPollCount(0)
    try {
      await api.options.refreshDirectional()
    } catch (e) {
      setError(e.message)
      setRefreshing(false)
    }
  }

  if (loading) {
    return (
      <div style={{ color: '#718096', padding: 40, textAlign: 'center' }}>
        Loading directional candidates...
      </div>
    )
  }

  if (error) {
    return (
      <div style={{ color: '#fc8181', padding: 40, textAlign: 'center' }}>
        Error: {error}
        <button onClick={load} style={{ marginLeft: 12, color: '#90cdf4', background: 'none', border: 'none', cursor: 'pointer' }}>
          Retry
        </button>
      </div>
    )
  }

  const verdict = data?.regime || 'UNKNOWN'
  const dataComplete = data?.data_complete ?? false
  const candidates = data?.candidates || []
  const visibleCandidates = tierFilter === 'all'
    ? candidates
    : candidates.filter((c) => c.risk_tier === tierFilter)
  const suppressed = data?.suppressed || []
  const isYellow = verdict === 'YELLOW'
  const runAt = data?.run_at

  // Find the suppressed reason from first suppressed item
  const suppressedReason = suppressed[0]?.suppressed_reason

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20, flexWrap: 'wrap', gap: 12 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 700, color: '#e2e8f0' }}>Directional Options</div>
          {runAt && (
            <div style={{ color: '#4a5568', fontSize: 11, marginTop: 2 }}>
              Last run: {new Date(runAt).toLocaleString()}
            </div>
          )}
        </div>
        <button
          onClick={handleRefresh}
          disabled={refreshing}
          style={{
            padding: '8px 16px', background: refreshing ? '#2d3748' : '#2b6cb0',
            color: '#fff', border: 'none', borderRadius: 6,
            cursor: refreshing ? 'default' : 'pointer', fontSize: 13, fontWeight: 500,
          }}
        >
          {refreshing ? 'Running...' : 'Refresh analysis'}
        </button>
      </div>

      {/* Regime banner */}
      <RegimeBanner
        verdict={verdict}
        dataComplete={dataComplete}
        suppressedReason={suppressedReason}
      />

      {/* No data */}
      {candidates.length === 0 && suppressed.length === 0 && (
        <EmptyState onRefresh={handleRefresh} refreshing={refreshing} />
      )}

      {/* Active candidates */}
      {candidates.length > 0 && (
        <div>
          <div style={{ color: '#718096', fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 12 }}>
            {visibleCandidates.length} of {candidates.length} ranked candidate{candidates.length !== 1 ? 's' : ''} sorted by EV per $ risked
          </div>
          {/* Risk tier filter (client-side; order within the view is unchanged) */}
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 16 }}>
            {[
              { key: 'all', label: 'All' },
              { key: 'lower', label: 'Lower risk' },
              { key: 'balanced', label: 'Balanced' },
              { key: 'higher', label: 'Higher risk' },
            ].map(({ key, label }) => (
              <button
                key={key}
                onClick={() => setTierFilter(key)}
                style={{
                  padding: '6px 14px', borderRadius: 999, fontSize: 12, fontWeight: 600,
                  cursor: 'pointer',
                  background: tierFilter === key ? '#2b6cb0' : '#1a1f2e',
                  color: tierFilter === key ? '#fff' : '#a0aec0',
                  border: `1px solid ${tierFilter === key ? '#2b6cb0' : '#2d3748'}`,
                }}
              >
                {label}
              </button>
            ))}
          </div>
          {visibleCandidates.length === 0 ? (
            <div style={{ color: '#718096', fontSize: 13, padding: '12px 0' }}>
              No candidates in this tier in the latest run.
            </div>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(440px, 1fr))', gap: 16 }}>
              {visibleCandidates.map((c) => (
                <CandidateCard key={`${c.ticker}-${c.option_type}`} c={c} isYellow={isYellow} />
              ))}
            </div>
          )}
        </div>
      )}

      {/* Suppressed section */}
      {(candidates.length > 0 || suppressed.length > 0) && (
        <SuppressedSection items={suppressed} />
      )}
    </div>
  )
}
