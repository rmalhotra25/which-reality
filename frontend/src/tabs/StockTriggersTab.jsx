import { useState, useEffect, useRef } from 'react'

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

// ─── Watchlist storage ────────────────────────────────────────────────────────
const WL_KEY = 'trigger_watchlist'
const PORT_KEY = 'trigger_portfolio'

function loadWatchlist() {
  try { return JSON.parse(localStorage.getItem(WL_KEY) || '[]') } catch { return [] }
}
function saveWatchlist(wl) {
  try { localStorage.setItem(WL_KEY, JSON.stringify(wl)) } catch {}
}
function loadPortfolio() {
  try { return JSON.parse(localStorage.getItem(PORT_KEY) || '[]') } catch { return [] }
}
function savePortfolio(p) {
  try { localStorage.setItem(PORT_KEY, JSON.stringify(p)) } catch {}
}

function isStale(item) {
  if (!item.lastChecked) return true
  const last = new Date(item.lastChecked)
  const now = new Date()
  const diffHours = (now - last) / 36e5
  return last.toDateString() !== now.toDateString() || diffHours > 6
}

function relativeTime(iso) {
  if (!iso) return ''
  const diff = (Date.now() - new Date(iso)) / 1000
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`
  return `${Math.round(diff / 86400)}d ago`
}

function shortDate(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

// ─── Sub-tab nav ──────────────────────────────────────────────────────────────
function SubTabs({ active, onChange, watchlistCount, upgradeCount }) {
  const tabs = [
    { id: 'analysis', label: '🔍 Analysis' },
    { id: 'top_rated', label: '⭐ Top Rated' },
    { id: 'watchlist', label: `👁 Watchlist${watchlistCount ? ` (${watchlistCount})` : ''}${upgradeCount ? ` 🔥${upgradeCount}` : ''}` },
  ]
  return (
    <div style={{ display: 'flex', gap: '4px', marginBottom: '24px', borderBottom: '1px solid #2d3748', paddingBottom: '0' }}>
      {tabs.map(t => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          style={{
            padding: '8px 18px',
            background: active === t.id ? '#1a1f2e' : 'transparent',
            color: active === t.id ? '#90cdf4' : '#718096',
            border: active === t.id ? '1px solid #2d3748' : '1px solid transparent',
            borderBottom: active === t.id ? '1px solid #1a1f2e' : '1px solid transparent',
            borderRadius: '8px 8px 0 0',
            cursor: 'pointer',
            fontSize: '13px',
            fontWeight: active === t.id ? 700 : 400,
            marginBottom: '-1px',
            transition: 'all 0.15s',
          }}
        >
          {t.label}
        </button>
      ))}
    </div>
  )
}

// ─── Upgrade alert banner ─────────────────────────────────────────────────────
function UpgradeAlerts({ upgrades, onAnalyze, onDismiss }) {
  if (!upgrades.length) return null
  return (
    <div style={{
      background: '#0a2218', border: '2px solid #276749',
      borderRadius: '12px', padding: '16px 20px', marginBottom: '20px',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
        <span style={{ fontSize: '20px' }}>🚀</span>
        <span style={{ fontSize: '15px', fontWeight: 800, color: '#48bb78' }}>
          Watchlist Upgrades — Confirm your entry
        </span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {upgrades.map(u => {
          const cfg = ACTION_CONFIG[u.action] || ACTION_CONFIG['WATCH']
          return (
            <div key={u.ticker} style={{
              display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap',
              padding: '10px 14px',
              background: cfg.bg, border: `1px solid ${cfg.border}`, borderRadius: '8px',
            }}>
              <span style={{ fontSize: '18px', fontWeight: 900, color: '#e2e8f0', minWidth: '56px' }}>{u.ticker}</span>
              <span style={{ fontSize: '12px', color: '#718096' }}>was WATCH →</span>
              <span style={{
                padding: '3px 10px', fontSize: '12px', fontWeight: 800, borderRadius: '6px',
                background: cfg.badge, color: cfg.badgeText,
              }}>
                {cfg.icon} {u.action}
              </span>
              <span style={{ fontSize: '13px', fontWeight: 700, color: cfg.color }}>
                Score {u.score}/8
              </span>
              <div style={{ marginLeft: 'auto', display: 'flex', gap: '8px' }}>
                <button
                  onClick={() => onAnalyze(u.ticker)}
                  style={{ padding: '5px 14px', background: cfg.badge, color: cfg.badgeText, border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '12px', fontWeight: 700 }}
                >
                  View Analysis
                </button>
                <button
                  onClick={() => onDismiss(u.ticker)}
                  style={{ padding: '5px 10px', background: 'transparent', color: '#4a5568', border: '1px solid #2d3748', borderRadius: '6px', cursor: 'pointer', fontSize: '12px' }}
                >
                  Dismiss
                </button>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ─── Watchlist section ────────────────────────────────────────────────────────
function WatchlistSection({ watchlist, refreshProgress, onAnalyze, onRemove, onRefreshAll }) {
  if (!watchlist.length) {
    return (
      <div style={{ color: '#4a5568', textAlign: 'center', padding: '40px 24px', fontSize: '13px' }}>
        <div style={{ fontSize: '28px', marginBottom: '10px' }}>👁</div>
        No stocks in your watchlist yet.<br />
        Analyze a stock and click <strong style={{ color: '#fbd38d' }}>+ Add to Watchlist</strong> when it scores WATCH.
      </div>
    )
  }

  const staleCount = watchlist.filter(isStale).length
  const anyLoading = Object.values(refreshProgress).includes('loading')

  return (
    <div style={{ marginBottom: '24px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px', flexWrap: 'wrap', gap: '8px' }}>
        <div>
          <span style={{ fontSize: '11px', color: '#718096', fontWeight: 600, letterSpacing: '0.08em' }}>
            TRIGGER WATCHLIST — catching the falling knife
          </span>
          {anyLoading && (
            <span style={{ marginLeft: '10px', fontSize: '11px', color: '#b7791f' }}>
              ⟳ Refreshing analysis…
            </span>
          )}
        </div>
        {staleCount > 0 && !anyLoading && (
          <button
            onClick={onRefreshAll}
            style={{ padding: '4px 12px', background: '#2d2000', color: '#fbd38d', border: '1px solid #b7791f', borderRadius: '6px', cursor: 'pointer', fontSize: '11px', fontWeight: 600 }}
          >
            ⟳ Refresh {staleCount} stale
          </button>
        )}
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {watchlist.map(item => {
          const displayAction = item.currentAction || item.actionAtAdd
          const displayScore = item.currentScore ?? item.scoreAtAdd
          const cfg = ACTION_CONFIG[displayAction] || ACTION_CONFIG['WATCH']
          const prog = refreshProgress[item.ticker]
          const isLoading = prog === 'loading'
          const isError = prog === 'error'
          const upgraded = item.upgradedFrom === 'WATCH' &&
            (item.currentAction === 'SMALL BUY' || item.currentAction === 'STRONG BUY')
          const deteriorated = item.currentScore != null && item.currentScore < item.scoreAtAdd
          const scoreChanged = item.currentScore != null && item.currentScore !== item.scoreAtAdd

          return (
            <div key={item.ticker} style={{
              display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap',
              padding: '10px 14px',
              background: upgraded ? cfg.bg : '#1a1f2e',
              border: `1px solid ${upgraded ? cfg.border : '#2d3748'}`,
              borderRadius: '8px',
              opacity: isLoading ? 0.7 : 1,
            }}>
              <span style={{ fontSize: '15px', fontWeight: 800, color: '#e2e8f0', minWidth: '52px' }}>
                {item.ticker}
              </span>
              <span style={{
                padding: '3px 10px', fontSize: '11px', fontWeight: 700, borderRadius: '6px',
                background: cfg.badge, color: cfg.badgeText,
              }}>
                {isLoading ? '⟳' : cfg.icon} {displayScore}/8 {displayAction}
              </span>
              {scoreChanged && !isLoading && (
                <span style={{ fontSize: '11px', color: upgraded ? '#48bb78' : deteriorated ? '#fc8181' : '#718096' }}>
                  {upgraded ? '↑ upgraded' : deteriorated ? '↓ deteriorated' : ''}
                  {` (was ${item.scoreAtAdd}/8)`}
                </span>
              )}
              <span style={{ fontSize: '11px', color: '#4a5568' }}>
                Added {shortDate(item.addedAt)}
                {item.lastChecked && ` · checked ${relativeTime(item.lastChecked)}`}
              </span>
              {isError && (
                <span style={{ fontSize: '11px', color: '#fc8181' }}>⚠ refresh failed</span>
              )}
              <div style={{ marginLeft: 'auto', display: 'flex', gap: '6px', flexShrink: 0 }}>
                <button
                  onClick={() => onAnalyze(item.ticker)}
                  disabled={isLoading}
                  style={{ padding: '4px 12px', background: '#2b6cb0', color: '#fff', border: 'none', borderRadius: '6px', cursor: isLoading ? 'not-allowed' : 'pointer', fontSize: '11px', fontWeight: 600 }}
                >
                  Analyze
                </button>
                <button
                  onClick={() => onRemove(item.ticker)}
                  style={{ padding: '4px 10px', background: 'transparent', color: '#4a5568', border: '1px solid #2d3748', borderRadius: '6px', cursor: 'pointer', fontSize: '11px' }}
                >
                  ×
                </button>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
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
      <div style={{ textAlign: 'center', flexShrink: 0 }}>
        <div style={{
          width: '80px', height: '80px', borderRadius: '50%',
          background: cfg.badge, display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center',
        }}>
          <span style={{ fontSize: '28px', fontWeight: 900, color: cfg.badgeText, lineHeight: 1 }}>{score}</span>
          <span style={{ fontSize: '11px', color: cfg.badgeText, opacity: 0.8 }}>/8</span>
        </div>
        <div style={{ fontSize: '10px', color: '#718096', marginTop: '4px' }}>TRIGGER SCORE</div>
      </div>

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

      <div style={{ flex: 1, minWidth: '160px' }}>
        <div style={{ height: '8px', background: '#1a1f2e', borderRadius: '4px', overflow: 'hidden' }}>
          <div style={{ width: `${(score / 8) * 100}%`, height: '100%', background: cfg.badge, borderRadius: '4px', transition: 'width 0.4s ease' }} />
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '4px', fontSize: '10px', color: '#4a5568' }}>
          <span>0</span><span>WATCH 3</span><span>BUY 5</span><span>STRONG 7</span><span>8</span>
        </div>
      </div>
    </div>
  )
}

// ─── Black-Scholes helpers for Put Selling Card ──────────────────────────────
function normCdf(x) {
  const sign = x < 0 ? -1 : 1
  const t = 1.0 / (1.0 + 0.3275911 * Math.abs(x))
  const y = 1.0 - (((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x))
  return 0.5 * (1.0 + sign * y)
}

function bsAssignmentProb(S, K, T, iv) {
  if (T <= 0 || iv <= 0 || S <= 0 || K <= 0) return 0
  const d2 = (Math.log(S / K) + (-0.5 * iv * iv) * T) / (iv * Math.sqrt(T))
  return Math.round(normCdf(-d2) * 1000) / 10
}

function bsPutPremium(S, K, T, iv, r = 0.045) {
  if (T <= 0 || iv <= 0 || S <= 0 || K <= 0) return null
  const d1 = (Math.log(S / K) + (r + 0.5 * iv * iv) * T) / (iv * Math.sqrt(T))
  const d2 = d1 - iv * Math.sqrt(T)
  const put = K * Math.exp(-r * T) * normCdf(-d2) - S * normCdf(-d1)
  const mid = Math.round(Math.max(put, 0.01) * 100) / 100
  return { mid, low: Math.round(mid * 0.80 * 100) / 100, high: Math.round(mid * 1.20 * 100) / 100 }
}

function getThirdFriday(year, month) {
  const firstDay = new Date(year, month, 1)
  const dow = firstDay.getDay()
  const daysToFri = (5 - dow + 7) % 7
  return new Date(year, month, 1 + daysToFri + 14)
}

function computePutRec(r) {
  const S = r.current_price
  if (!S || S < 10) return null

  const bearPrice = r.dcf_bear_price
  const p10 = r.monte_carlo?.per_share?.p10
  const bearCasePositive = bearPrice != null && bearPrice > S

  const strikeA = S * 0.90
  const candidates = [strikeA]
  if (!bearCasePositive && bearPrice != null && bearPrice * 0.90 < S) candidates.push(bearPrice * 0.90)
  if (p10 != null && p10 < S && p10 > 0) candidates.push(p10)

  const valid = candidates.filter(c => c > 0 && c < S)
  if (!valid.length) return null
  const strike = Math.round(Math.max(...valid))

  // Monthly expirations — next 5
  const today = new Date(); today.setHours(0, 0, 0, 0)
  const expirations = []
  let m = today.getMonth(), y = today.getFullYear()
  while (expirations.length < 5) {
    const exp = getThirdFriday(y, m); exp.setHours(0, 0, 0, 0)
    const dte = Math.round((exp - today) / 86400000)
    if (dte > 10) expirations.push({ date: exp, dte })
    m++; if (m > 11) { m = 0; y++ }
  }

  const earningsLimit = r.earnings_days != null ? r.earnings_days - 14 : null
  const validExps = expirations.filter(e => earningsLimit == null || e.dte < earningsLimit)
  if (!validExps.length) return { earningsBlocked: true }

  const sel = validExps.reduce((b, c) => Math.abs(c.dte - 35) < Math.abs(b.dte - 35) ? c : b)
  const T = sel.dte / 365

  const beta = r.beta || 1.0
  const iv = beta < 0.9 ? 0.25 : beta < 1.3 ? 0.35 : beta < 1.8 ? 0.45 : 0.60

  const assignProb = bsAssignmentProb(S, strike, T, iv)
  const keptProb = Math.round((100 - assignProb) * 10) / 10
  const prem = bsPutPremium(S, strike, T, iv)
  const capital = strike * 100
  const effectiveCost = prem ? Math.round((strike - prem.mid) * 100) / 100 : strike
  const monthlyReturn = prem ? Math.round((prem.mid / capital) * (30 / sel.dte) * 1000) / 10 : null
  const annualReturn = prem ? Math.round((prem.mid / capital) * (365 / sel.dte) * 1000) / 10 : null

  const median = r.monte_carlo?.per_share?.median
  const basePrice = r.dcf_base_price
  const bearReturn = bearPrice != null ? Math.round((bearPrice / effectiveCost - 1) * 1000) / 10 : null
  const medianReturn = median != null ? Math.round((median / effectiveCost - 1) * 1000) / 10 : null
  const baseReturn = basePrice != null ? Math.round((basePrice / effectiveCost - 1) * 1000) / 10 : null

  const expStr = sel.date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })

  return {
    earningsBlocked: false,
    strike, expStr, dte: sel.dte, iv, beta,
    assignProb, keptProb, prem, capital,
    effectiveCost, monthlyReturn, annualReturn,
    bearReturn, medianReturn, baseReturn,
    bearPrice, median, basePrice,
    bearCasePositive,
    checks: {
      earningsClear: r.earnings_days == null || r.earnings_days > sel.dte + 14,
      scoreGood: r.trigger_score >= 5,
      bearAboveStrike: bearPrice != null && bearPrice > strike,
      discountToDcf: median != null && effectiveCost < median,
    },
  }
}

function PutSellingCard({ r }) {
  const S = r.current_price
  const score = r.trigger_score
  const earningsDays = r.earnings_days

  if (score == null || score < 4) return null
  if (!S || S < 10) return null

  if (earningsDays != null && earningsDays <= 14) {
    const earningsMsg = earningsDays === 0 ? 'today or tomorrow' : `in ${earningsDays} day${earningsDays === 1 ? '' : 's'}`
    return (
      <div style={{ background: '#1a0f00', border: '1px solid #744210', borderRadius: '10px', padding: '16px 20px' }}>
        <div style={{ fontSize: '12px', fontWeight: 700, color: '#fbd38d', letterSpacing: '0.08em', marginBottom: '6px' }}>💰 PUT SELLING OPPORTUNITY</div>
        <div style={{ fontSize: '13px', color: '#ed8936' }}>
          ⚠️ Earnings {earningsMsg} — wait until after earnings to sell puts.
        </div>
      </div>
    )
  }

  const rec = computePutRec(r)
  if (!rec) return null

  if (rec.earningsBlocked) {
    return (
      <div style={{ background: '#1a0f00', border: '1px solid #744210', borderRadius: '10px', padding: '16px 20px' }}>
        <div style={{ fontSize: '12px', fontWeight: 700, color: '#fbd38d', letterSpacing: '0.08em', marginBottom: '6px' }}>💰 PUT SELLING OPPORTUNITY</div>
        <div style={{ fontSize: '13px', color: '#ed8936' }}>
          ⚠️ Earnings too close — no clean expiration available. Wait until after earnings to sell puts.
        </div>
      </div>
    )
  }

  const { strike, expStr, dte, assignProb, keptProb, prem, capital, effectiveCost,
          monthlyReturn, annualReturn, bearReturn, medianReturn, baseReturn,
          bearPrice, median, basePrice, bearCasePositive, checks, beta, iv } = rec

  const allGreen = checks.earningsClear && checks.scoreGood && checks.bearAboveStrike && checks.discountToDcf
  const fmt = (n, dec = 1) => n != null ? (n > 0 ? `+${n.toFixed(dec)}%` : `${n.toFixed(dec)}%`) : '—'
  const returnColor = n => n == null ? '#a0aec0' : n >= 0 ? '#68d391' : '#fc8181'
  const Check = ({ ok, label }) => (
    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', color: ok ? '#68d391' : '#fc8181' }}>
      <span>{ok ? '✅' : '❌'}</span>
      <span>{label}</span>
    </div>
  )

  return (
    <div style={{ background: '#071420', border: '1px solid #2b4c7e', borderRadius: '12px', padding: '20px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
      {/* Header */}
      <div>
        <div style={{ fontSize: '12px', fontWeight: 700, color: '#63b3ed', letterSpacing: '0.08em', marginBottom: '4px' }}>💰 PUT SELLING OPPORTUNITY</div>
        <div style={{ fontSize: '12px', color: '#718096' }}>Sell a put to collect income while waiting for your thesis to play out</div>
      </div>

      {/* Section 1 — The Trade */}
      <div style={{ background: '#0a1a2e', borderRadius: '8px', padding: '14px 16px' }}>
        <div style={{ fontSize: '11px', color: '#718096', fontWeight: 600, letterSpacing: '0.08em', marginBottom: '8px' }}>THE TRADE</div>
        <div style={{ fontSize: '20px', fontWeight: 800, color: '#90cdf4', letterSpacing: '0.02em' }}>
          {r.ticker} PUT ${strike} exp {expStr} ({dte} days)
        </div>
        {beta > 1.8 && (
          <div style={{ fontSize: '11px', color: '#fbd38d', marginTop: '6px' }}>
            High-volatility stock (beta {beta?.toFixed(2)}) — using {Math.round(iv * 100)}% IV estimate
          </div>
        )}
      </div>

      {/* Section 2 — Income */}
      <div>
        <div style={{ fontSize: '11px', color: '#718096', fontWeight: 600, letterSpacing: '0.08em', marginBottom: '10px' }}>INCOME</div>
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          {[
            { label: 'Est. Premium', value: prem ? `$${prem.low}–$${prem.high}` : '—' },
            { label: 'Capital Required', value: `$${capital.toLocaleString()}` },
            { label: 'Monthly Return', value: monthlyReturn != null ? `${monthlyReturn}%` : '—' },
            { label: 'Annualized', value: annualReturn != null ? `${annualReturn}%` : '—' },
          ].map(({ label, value }) => (
            <div key={label} style={{ background: '#0f1117', border: '1px solid #2d3748', borderRadius: '6px', padding: '8px 12px', textAlign: 'center', minWidth: '80px' }}>
              <div style={{ fontSize: '10px', color: '#718096', marginBottom: '2px' }}>{label}</div>
              <div style={{ fontSize: '14px', fontWeight: 700, color: '#e2e8f0' }}>{value}</div>
            </div>
          ))}
        </div>
        <div style={{ fontSize: '11px', color: '#718096', marginTop: '6px' }}>
          Verify actual bid/ask in your broker before placing order
        </div>
      </div>

      {/* Section 3 — Probabilities */}
      <div>
        <div style={{ fontSize: '11px', color: '#718096', fontWeight: 600, letterSpacing: '0.08em', marginBottom: '10px' }}>PROBABILITIES</div>
        <div style={{ background: '#0f1117', border: '1px solid #2d3748', borderRadius: '8px', padding: '12px 14px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
            <span style={{ fontSize: '13px', color: '#68d391', fontWeight: 600 }}>{keptProb}% keep full premium</span>
            <span style={{ fontSize: '13px', color: '#fc8181', fontWeight: 600 }}>{assignProb}% assignment</span>
          </div>
          <div style={{ height: '8px', background: '#2d3748', borderRadius: '4px', overflow: 'hidden' }}>
            <div style={{ height: '100%', width: `${keptProb}%`, background: 'linear-gradient(90deg, #2f855a, #68d391)', borderRadius: '4px' }} />
          </div>
        </div>
      </div>

      {/* Section 4 — If Assigned */}
      <div>
        <div style={{ fontSize: '11px', color: '#718096', fontWeight: 600, letterSpacing: '0.08em', marginBottom: '10px' }}>IF ASSIGNED</div>
        <div style={{ background: '#0f1117', border: '1px solid #2d3748', borderRadius: '8px', padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <div style={{ fontSize: '13px', color: '#a0aec0' }}>
            Effective cost basis: <span style={{ color: '#e2e8f0', fontWeight: 700 }}>${effectiveCost.toFixed(2)}</span>
            <span style={{ fontSize: '11px', color: '#718096', marginLeft: '6px' }}>(strike ${strike} − premium ${prem?.mid ?? '—'})</span>
          </div>
          {[
            { label: 'vs Bear case', value: bearReturn, price: bearPrice, extra: bearCasePositive ? ' (bear case is positive)' : '' },
            { label: 'vs Median DCF', value: medianReturn, price: median, extra: '' },
            { label: 'vs Base case', value: baseReturn, price: basePrice, extra: '' },
          ].map(({ label, value, price, extra }) => (
            <div key={label} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderTop: '1px solid #1a2030', paddingTop: '8px' }}>
              <span style={{ fontSize: '12px', color: '#718096' }}>{label}{extra && <span style={{ color: '#a0aec0' }}>{extra}</span>}</span>
              <div style={{ textAlign: 'right' }}>
                <span style={{ fontSize: '14px', fontWeight: 700, color: returnColor(value) }}>{fmt(value)}</span>
                {price != null && <span style={{ fontSize: '11px', color: '#718096', marginLeft: '6px' }}>(${price.toFixed(2)})</span>}
              </div>
            </div>
          ))}
          {bearReturn != null && bearReturn >= 0 && (
            <div style={{ fontSize: '12px', color: '#68d391', borderTop: '1px solid #1a2030', paddingTop: '8px' }}>
              ✅ Profitable even in worst case scenario
            </div>
          )}
        </div>
      </div>

      {/* Section 5 — Checklist */}
      <div>
        <div style={{ fontSize: '11px', color: '#718096', fontWeight: 600, letterSpacing: '0.08em', marginBottom: '10px' }}>SETUP CHECKLIST</div>
        <div style={{ background: '#0f1117', border: `1px solid ${allGreen ? '#276749' : '#4a3000'}`, borderRadius: '8px', padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <Check ok={checks.earningsClear} label="Earnings clear (>14 days after expiry)" />
          <Check ok={checks.scoreGood} label={`Trigger score 5/8 or higher (current: ${score}/8)`} />
          <Check ok={checks.bearAboveStrike} label={`Bear case above strike (bear: $${bearPrice?.toFixed(2) ?? '—'} vs strike: $${strike})`} />
          <Check ok={checks.discountToDcf} label={`Assignment at discount to DCF median ($${effectiveCost.toFixed(2)} vs $${median?.toFixed(2) ?? '—'})`} />
          {allGreen ? (
            <div style={{ fontSize: '13px', fontWeight: 700, color: '#68d391', borderTop: '1px solid #1a2030', paddingTop: '10px' }}>
              ✅ Clean setup — proceed with confidence
            </div>
          ) : (
            <div style={{ fontSize: '12px', color: '#fbd38d', borderTop: '1px solid #1a2030', paddingTop: '10px' }}>
              ⚠️ Review flagged items before trading
            </div>
          )}
        </div>
      </div>

      {/* Disclaimer */}
      <div style={{ fontSize: '11px', color: '#4a5568', lineHeight: 1.6, borderTop: '1px solid #1a2030', paddingTop: '12px' }}>
        Premium estimates are approximations using Black-Scholes. Verify actual bid/ask in your broker before trading.
        Options involve risk of loss. Only sell cash-secured puts.
      </div>
    </div>
  )
}

// ─── Score breakdown ──────────────────────────────────────────────────────────
function ScoreBreakdown({ breakdown }) {
  if (!breakdown) return null
  const items = [breakdown.monte_carlo, breakdown.ma, breakdown.earnings, breakdown.bear, breakdown.base].filter(Boolean)
  return (
    <div style={{ background: '#0f1117', border: '1px solid #2d3748', borderRadius: '10px', padding: '16px 20px' }}>
      <div style={{ fontSize: '11px', color: '#718096', fontWeight: 600, letterSpacing: '0.08em', marginBottom: '12px' }}>POINT BREAKDOWN</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {items.map((item, i) => {
          const earned = item.earned
          const isWarning = item.warning
          const dotColor = earned === null ? '#4a5568' : earned === item.max ? '#68d391' : earned > 0 ? '#fbd38d' : isWarning ? '#ed8936' : '#fc8181'
          return (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <div style={{ display: 'flex', gap: '3px', flexShrink: 0 }}>
                {Array.from({ length: item.max }).map((_, j) => (
                  <div key={j} style={{ width: '10px', height: '10px', borderRadius: '50%', background: earned !== null && j < earned ? dotColor : '#2d3748', border: `1px solid ${dotColor}` }} />
                ))}
              </div>
              <span style={{ fontSize: '12px', color: '#718096', minWidth: '90px', flexShrink: 0 }}>{item.label}</span>
              <span style={{ fontSize: '12px', color: isWarning ? '#ed8936' : earned ? '#e2e8f0' : '#718096' }}>{item.detail}</span>
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

// ─── MA status ────────────────────────────────────────────────────────────────
function MaStatusCard({ ma50, aboveMa, crossover5d, currentPrice }) {
  if (ma50 == null) return null
  const color = crossover5d ? '#48bb78' : aboveMa ? '#68d391' : '#fc8181'
  const bg = crossover5d ? '#0a2218' : aboveMa ? '#0a1a10' : '#2d1515'
  const border = crossover5d ? '#276749' : aboveMa ? '#2f855a' : '#742a2a'
  return (
    <div style={{ background: bg, border: `1px solid ${border}`, borderRadius: '8px', padding: '12px 16px' }}>
      <div style={{ fontSize: '11px', color: '#718096', fontWeight: 600, letterSpacing: '0.08em', marginBottom: '6px' }}>50-DAY MOVING AVERAGE</div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
        <span style={{ fontSize: '16px', fontWeight: 700, color }}>
          {crossover5d ? '🚀 Golden cross (last 5 days)' : aboveMa ? '↑ Above MA' : '↓ Below MA'}
        </span>
        <span style={{ fontSize: '13px', color: '#a0aec0' }}>
          MA: ${ma50.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          {currentPrice && ` · Price: $${currentPrice.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
        </span>
        {currentPrice && ma50 && (
          <span style={{ fontSize: '12px', color }}>({((currentPrice - ma50) / ma50 * 100).toFixed(1)}% vs MA)</span>
        )}
      </div>
    </div>
  )
}

// ─── Bear protection ──────────────────────────────────────────────────────────
function BearProtectionCard({ level, bearUpside }) {
  if (!level) return null
  const cfg = PROTECTION_CONFIG[level] || PROTECTION_CONFIG.moderate
  return (
    <div style={{ background: cfg.bg, border: `1px solid ${cfg.border}`, borderRadius: '8px', padding: '12px 16px' }}>
      <div style={{ fontSize: '11px', color: '#718096', fontWeight: 600, letterSpacing: '0.08em', marginBottom: '4px' }}>BEAR CASE PROTECTION</div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
        <span style={{ fontSize: '16px', fontWeight: 700, color: cfg.color }}>{cfg.label}</span>
        {bearUpside != null && <span style={{ fontSize: '13px', color: '#a0aec0' }}>Bear case: <span style={{ color: cfg.color, fontWeight: 600 }}>{bearUpside > 0 ? '+' : ''}{bearUpside}%</span></span>}
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
    <div style={{ marginBottom: '20px' }}>
      <div style={{ fontSize: '11px', color: '#718096', fontWeight: 600, letterSpacing: '0.08em', marginBottom: '10px' }}>
        RECENTLY ANALYZED — ranked by score
      </div>
      <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
        {sorted.map(s => {
          const cfg = ACTION_CONFIG[s.action] || ACTION_CONFIG['WATCH']
          const isActive = s.ticker === selected
          return (
            <div key={s.ticker} onClick={() => onSelect(s.ticker)} style={{
              display: 'flex', alignItems: 'center', gap: '6px',
              padding: '6px 10px 6px 12px',
              background: isActive ? cfg.badge : '#1a1f2e',
              border: `1px solid ${isActive ? cfg.border : '#2d3748'}`,
              borderRadius: '8px', cursor: 'pointer', transition: 'all 0.15s',
            }}>
              <span style={{ fontSize: '13px', fontWeight: 700, color: isActive ? cfg.badgeText : '#e2e8f0' }}>{s.ticker}</span>
              <span style={{ fontSize: '11px', fontWeight: 700, padding: '1px 6px', borderRadius: '4px', background: cfg.badge, color: cfg.badgeText }}>
                {s.blocked ? '⛔' : s.score}/8
              </span>
              <span onClick={e => { e.stopPropagation(); onRemove(s.ticker) }} style={{ fontSize: '11px', color: '#4a5568', cursor: 'pointer', marginLeft: '2px', lineHeight: 1 }} title="Remove">×</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ─── DCF sub-components ───────────────────────────────────────────────────────
function MetricPill({ label, value }) {
  return (
    <div style={{ background: '#0f1117', border: '1px solid #2d3748', borderRadius: '6px', padding: '6px 10px', textAlign: 'center', minWidth: '60px' }}>
      <div style={{ fontSize: '10px', color: '#718096', marginBottom: '2px' }}>{label}</div>
      <div style={{ fontSize: '13px', fontWeight: 700, color: '#e2e8f0' }}>{value}</div>
    </div>
  )
}

function ScenarioCard({ label, price, upside, g1Pct, fcfPct, highlight }) {
  const up = upside ?? 0
  return (
    <div style={{ flex: '1', minWidth: '110px', background: highlight ? '#0d2112' : '#161b27', border: `1px solid ${highlight ? '#2f855a' : '#2d3748'}`, borderRadius: '10px', padding: '14px 12px', textAlign: 'center' }}>
      <div style={{ fontSize: '11px', color: '#718096', fontWeight: 600, letterSpacing: '0.08em', marginBottom: '8px' }}>{label}</div>
      {price != null && <div style={{ fontSize: '20px', fontWeight: 800, marginBottom: '2px', color: label === 'BULL' ? '#68d391' : label === 'BEAR' ? '#fc8181' : '#90cdf4' }}>${price.toLocaleString()}</div>}
      <div style={{ fontSize: '14px', fontWeight: 700, color: up >= 0 ? '#68d391' : '#fc8181', marginBottom: '8px' }}>{upside != null ? `${up > 0 ? '+' : ''}${up}%` : '—'}</div>
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
              return <div key={i} title={`$${bar.x} — ${bar.count} simulations`} style={{ flex: 1, height: `${heightPct}%`, minHeight: bar.count > 0 ? '2px' : '0', background: isCurrentBin ? '#f6e05e' : '#2b6cb0', opacity: 0.85, borderRadius: '1px 1px 0 0' }} />
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

// ─── Top Rated scanner ────────────────────────────────────────────────────────
function TopRatedCard({ stock, onAnalyze }) {
  const cfg = ACTION_CONFIG[stock.action] || ACTION_CONFIG['WATCH']
  const mc = stock.monte_carlo || {}
  const prob = mc.prob_undervalued_pct

  return (
    <div style={{
      background: cfg.bg, border: `1px solid ${cfg.border}`,
      borderRadius: '10px', padding: '16px 18px',
      display: 'flex', alignItems: 'flex-start', gap: '14px', flexWrap: 'wrap',
    }}>
      {/* Score circle */}
      <div style={{ textAlign: 'center', flexShrink: 0 }}>
        <div style={{
          width: '52px', height: '52px', borderRadius: '50%',
          background: cfg.badge, display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center',
        }}>
          <span style={{ fontSize: '20px', fontWeight: 900, color: cfg.badgeText, lineHeight: 1 }}>{stock.score}</span>
          <span style={{ fontSize: '10px', color: cfg.badgeText, opacity: 0.8 }}>/8</span>
        </div>
      </div>

      {/* Main info */}
      <div style={{ flex: 1, minWidth: '200px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '18px', fontWeight: 900, color: '#e2e8f0' }}>{stock.ticker}</span>
          {stock.name && stock.name !== stock.ticker && (
            <span style={{ fontSize: '12px', color: '#718096' }}>{stock.name}</span>
          )}
          <span style={{
            padding: '2px 8px', fontSize: '11px', fontWeight: 700, borderRadius: '4px',
            background: cfg.badge, color: cfg.badgeText,
          }}>
            {cfg.icon} {stock.action}
          </span>
          {stock.blocked && (
            <span style={{ padding: '2px 8px', fontSize: '10px', color: '#ed8936', border: '1px solid #c05621', borderRadius: '4px' }}>
              ⛔ Earnings in {stock.earnings_days}d
            </span>
          )}
        </div>

        <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', fontSize: '12px', color: '#a0aec0', marginBottom: '8px' }}>
          {stock.current_price != null && <span>Price: <strong style={{ color: '#e2e8f0' }}>${stock.current_price.toLocaleString()}</strong></span>}
          {stock.market_cap_b != null && <span>Mkt Cap: <strong style={{ color: '#e2e8f0' }}>${stock.market_cap_b}B</strong></span>}
          {stock.revenue_growth_pct != null && <span>Rev Growth: <strong style={{ color: stock.revenue_growth_pct > 0 ? '#68d391' : '#fc8181' }}>{stock.revenue_growth_pct > 0 ? '+' : ''}{stock.revenue_growth_pct}%</strong></span>}
          {stock.dcf_base_upside != null && <span>Base Upside: <strong style={{ color: stock.dcf_base_upside > 0 ? '#68d391' : '#fc8181' }}>{stock.dcf_base_upside > 0 ? '+' : ''}{stock.dcf_base_upside}%</strong></span>}
          {prob != null && <span>MC: <strong style={{ color: prob >= 85 ? '#68d391' : prob >= 70 ? '#fbd38d' : '#a0aec0' }}>{prob}%</strong></span>}
        </div>

        {/* Mini breakdown */}
        {stock.breakdown && (
          <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
            {[
              { key: 'monte_carlo', label: 'MC' },
              { key: 'ma', label: 'MA' },
              { key: 'earnings', label: 'Earn' },
              { key: 'bear', label: 'Bear' },
              { key: 'base', label: 'Base' },
            ].map(({ key, label }) => {
              const item = stock.breakdown[key] || {}
              const earned = item.earned
              const dotColor = earned === null ? '#4a5568' : earned === item.max ? '#68d391' : earned > 0 ? '#fbd38d' : '#fc8181'
              return (
                <div key={key} style={{ display: 'flex', alignItems: 'center', gap: '3px' }}>
                  <div style={{ width: '7px', height: '7px', borderRadius: '50%', background: dotColor }} />
                  <span style={{ fontSize: '10px', color: '#718096' }}>{label}</span>
                  <span style={{ fontSize: '10px', color: dotColor, fontWeight: 700 }}>
                    {earned === null ? '—' : `${earned}/${item.max}`}
                  </span>
                </div>
              )
            })}
          </div>
        )}
      </div>

      <button
        onClick={() => onAnalyze(stock.ticker)}
        style={{
          padding: '7px 16px', background: '#2b6cb0', color: '#fff',
          border: 'none', borderRadius: '7px', cursor: 'pointer',
          fontSize: '12px', fontWeight: 600, flexShrink: 0, alignSelf: 'flex-start',
        }}
      >
        Full Analysis →
      </button>
    </div>
  )
}

function NearTriggerCard({ stock, onAnalyze }) {
  return (
    <div style={{
      background: '#1a1f2e', border: '1px solid #2d3748',
      borderRadius: '10px', padding: '14px 16px',
      display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap',
    }}>
      <div style={{
        width: '40px', height: '40px', borderRadius: '50%',
        background: '#b7791f', display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center', flexShrink: 0,
      }}>
        <span style={{ fontSize: '16px', fontWeight: 900, color: '#fefcbf', lineHeight: 1 }}>{stock.score}</span>
        <span style={{ fontSize: '9px', color: '#fefcbf', opacity: 0.8 }}>/8</span>
      </div>

      <div style={{ flex: 1, minWidth: '150px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '2px' }}>
          <span style={{ fontSize: '15px', fontWeight: 800, color: '#e2e8f0' }}>{stock.ticker}</span>
          {stock.name && stock.name !== stock.ticker && (
            <span style={{ fontSize: '11px', color: '#718096' }}>{stock.name}</span>
          )}
        </div>
        {stock.near_trigger_message && (
          <div style={{ fontSize: '12px', color: '#fbd38d' }}>
            ⚡ {stock.near_trigger_message}
          </div>
        )}
      </div>

      <button
        onClick={() => onAnalyze(stock.ticker)}
        style={{
          padding: '5px 14px', background: 'transparent', color: '#90cdf4',
          border: '1px solid #2b6cb0', borderRadius: '6px', cursor: 'pointer',
          fontSize: '11px', fontWeight: 600, flexShrink: 0,
        }}
      >
        Analyze →
      </button>
    </div>
  )
}

function TopRatedTab({ onAnalyze }) {
  const [data, setData] = useState(null)
  const [status, setStatus] = useState(null)
  const [refreshing, setRefreshing] = useState(false)
  const pollRef = useRef(null)

  const fetchResults = async () => {
    try {
      const resp = await fetch(`${API}/api/top-rated/results`)
      const body = await resp.json().catch(() => ({}))
      if (body.scanning) {
        startPolling()
      } else {
        setData(body)
        stopPolling()
      }
    } catch (e) {
      console.error('Top rated fetch error', e)
    }
  }

  const fetchStatus = async () => {
    try {
      const resp = await fetch(`${API}/api/top-rated/status`)
      const body = await resp.json().catch(() => ({}))
      setStatus(body)
      if (body.status === 'complete' || body.status === 'error' || !body.status) {
        stopPolling()
        if (body.status === 'complete') fetchResults()
      }
    } catch {}
  }

  const startPolling = () => {
    if (pollRef.current) return
    pollRef.current = setInterval(fetchStatus, 3000)
  }

  const stopPolling = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }

  useEffect(() => {
    fetchResults()
    fetchStatus()
    return () => stopPolling()
  }, []) // eslint-disable-line

  const handleRefresh = async () => {
    setRefreshing(true)
    setData(null)
    try {
      await fetch(`${API}/api/top-rated/refresh`, { method: 'POST' })
      startPolling()
    } catch {}
    setRefreshing(false)
  }

  const isRunning = status?.status === 'running'
  const phase = status?.phase || ''
  const phasePct = isRunning ? (
    phase === 'stage1_price_volume' ? 10 :
    phase === 'stage1_fundamentals' ? (10 + ((status?.current || 0) / Math.max(status?.total || 1, 1)) * 40) :
    phase === 'stage2_scoring' ? (50 + ((status?.current || 0) / Math.max(status?.total || 1, 1)) * 45) :
    95
  ) : 0

  const phaseLabel = {
    init: 'Initializing…',
    stage1_price_volume: 'Stage 1 · Fetching price & volume…',
    stage1_fundamentals: `Stage 1 · Fetching fundamentals… (${status?.current || 0}/${status?.total || '?'})`,
    stage2_scoring: `Stage 2 · Scoring… ${status?.current_ticker ? `· ${status.current_ticker}` : ''} (${status?.current || 0}/${status?.total || '?'})`,
    done: 'Complete',
  }[phase] || phase

  return (
    <div>
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: '16px', flexWrap: 'wrap', gap: '10px' }}>
        <div>
          <p style={{ fontSize: '13px', color: '#718096', margin: '0 0 4px' }}>
            S&P 500 + Nasdaq 100 · Two-stage funnel · 7/8 trigger score required
          </p>
          {data?.scanned_at && (
            <div style={{ fontSize: '11px', color: '#4a5568' }}>
              Last scan: {relativeTime(data.scanned_at)}
              {data.universe_count && ` · ${data.universe_count} tickers → ${data.stage1b_survivors} passed filters → ${data.stage2_scored} scored`}
            </div>
          )}
          {status?.last_cached_at && !data?.scanned_at && (
            <div style={{ fontSize: '11px', color: '#4a5568' }}>
              Cache: {relativeTime(status.last_cached_at)}
            </div>
          )}
        </div>
        <button
          onClick={handleRefresh}
          disabled={isRunning || refreshing}
          style={{
            padding: '7px 16px',
            background: isRunning || refreshing ? '#2d3748' : '#1a3a2a',
            color: isRunning || refreshing ? '#718096' : '#68d391',
            border: `1px solid ${isRunning || refreshing ? '#2d3748' : '#2f855a'}`,
            borderRadius: '7px', cursor: isRunning || refreshing ? 'not-allowed' : 'pointer',
            fontSize: '12px', fontWeight: 600,
          }}
        >
          {isRunning ? '⟳ Scanning…' : '⟳ Refresh Scan'}
        </button>
      </div>

      {/* Progress bar */}
      {isRunning && (
        <div style={{ marginBottom: '20px' }}>
          <div style={{ fontSize: '12px', color: '#fbd38d', marginBottom: '6px' }}>{phaseLabel}</div>
          <div style={{ height: '6px', background: '#1a1f2e', borderRadius: '3px', overflow: 'hidden' }}>
            <div style={{
              width: `${phasePct}%`, height: '100%',
              background: 'linear-gradient(90deg, #276749, #48bb78)',
              borderRadius: '3px', transition: 'width 0.5s ease',
            }} />
          </div>
        </div>
      )}

      {/* Status error */}
      {status?.status === 'error' && (
        <div style={{ color: '#fc8181', padding: '12px 16px', background: '#2d1515', border: '1px solid #742a2a', borderRadius: '8px', marginBottom: '16px', fontSize: '13px' }}>
          Scan error: {status.error}
        </div>
      )}

      {/* No data yet */}
      {!data && !isRunning && !status?.error && (
        <div style={{ color: '#4a5568', textAlign: 'center', padding: '60px 24px', fontSize: '13px' }}>
          <div style={{ fontSize: '32px', marginBottom: '12px' }}>⭐</div>
          No scan results yet. Click <strong style={{ color: '#68d391' }}>Refresh Scan</strong> to run the first scan.
          <br /><span style={{ fontSize: '11px', marginTop: '8px', display: 'block' }}>Scans run automatically at 10 AM Eastern on trading days.</span>
        </div>
      )}

      {/* Results */}
      {data && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          {/* Top Rated section */}
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
              <span style={{ fontSize: '13px', fontWeight: 700, color: '#48bb78', letterSpacing: '0.06em' }}>
                ⭐ TOP RATED — 7/8 TRIGGER SCORE
              </span>
              <span style={{ fontSize: '12px', color: '#4a5568' }}>({data.top_rated?.length || 0} stocks)</span>
            </div>
            {data.top_rated?.length > 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                {data.top_rated.map(s => (
                  <TopRatedCard key={s.ticker} stock={s} onAnalyze={t => onAnalyze(t)} />
                ))}
              </div>
            ) : (
              <div style={{ color: '#4a5568', padding: '20px 16px', background: '#0f1117', border: '1px solid #2d3748', borderRadius: '8px', fontSize: '13px', textAlign: 'center' }}>
                No stocks reached 7/8 this scan. Check Near Trigger for close candidates.
              </div>
            )}
          </div>

          {/* Near Trigger section */}
          {data.near_trigger?.length > 0 && (
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
                <span style={{ fontSize: '13px', fontWeight: 700, color: '#fbd38d', letterSpacing: '0.06em' }}>
                  ⚡ NEAR TRIGGER — 6/8 (one criterion away)
                </span>
                <span style={{ fontSize: '12px', color: '#4a5568' }}>({data.near_trigger.length})</span>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {data.near_trigger.map(s => (
                  <NearTriggerCard key={s.ticker} stock={s} onAnalyze={t => onAnalyze(t)} />
                ))}
              </div>
            </div>
          )}

          {/* Scan stats */}
          <div style={{ background: '#0f1117', border: '1px solid #2d3748', borderRadius: '8px', padding: '14px 16px' }}>
            <div style={{ fontSize: '11px', color: '#718096', fontWeight: 600, letterSpacing: '0.08em', marginBottom: '10px' }}>SCAN EFFICIENCY</div>
            <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap', fontSize: '12px' }}>
              <span>Universe: <strong style={{ color: '#e2e8f0' }}>{data.universe_count}</strong></span>
              <span>After price/vol: <strong style={{ color: '#e2e8f0' }}>{data.stage1a_survivors}</strong></span>
              <span>After fundamentals: <strong style={{ color: '#e2e8f0' }}>{data.stage1b_survivors}</strong></span>
              <span>Scored: <strong style={{ color: '#e2e8f0' }}>{data.stage2_scored}</strong></span>
              <span>MC skipped: <strong style={{ color: '#4a5568' }}>{data.skipped_mc_count}</strong></span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Analysis tab ─────────────────────────────────────────────────────────────
function AnalysisTab({ watchlist, addToWatchlist, removeFromWatchlist }) {
  const [ticker, setTicker] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [selectedTicker, setSelectedTicker] = useState(null)
  const [portfolio, setPortfolio] = useState(loadPortfolio)

  // Listen for cross-tab navigation (Top Rated / Watchlist → Analysis)
  useEffect(() => {
    const handler = e => {
      if (e.detail) {
        setTicker(e.detail)
        analyze(e.detail)
      }
    }
    window.addEventListener('analyze-ticker', handler)
    return () => window.removeEventListener('analyze-ticker', handler)
  }, []) // eslint-disable-line

  const r = result
  const inWatchlist = r && watchlist.some(w => w.ticker === r.ticker)
  const isWatch = r && r.trigger_action === 'WATCH'

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
      setPortfolio(prev => {
        const filtered = prev.filter(p => p.ticker !== sym)
        const entry = { ticker: sym, score: body.trigger_score, action: body.trigger_action, blocked: body.trigger_blocked }
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
    setPortfolio(prev => { const next = prev.filter(p => p.ticker !== sym); savePortfolio(next); return next })
    if (selectedTicker === sym) { setSelectedTicker(null); setResult(null) }
  }

  function handleKey(e) { if (e.key === 'Enter') analyze() }

  return (
    <div>
      <PortfolioSummary
        portfolio={portfolio}
        selected={selectedTicker}
        onSelect={sym => { setTicker(sym); analyze(sym) }}
        onRemove={removeFromPortfolio}
      />

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
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '10px' }}>
            <div>
              <div style={{ fontSize: '26px', fontWeight: 800, color: '#90cdf4' }}>{r.ticker}</div>
              <div style={{ fontSize: '14px', color: '#a0aec0', marginTop: '2px' }}>{r.name} · {r.sector}</div>
            </div>
            <RecoChip rec={r.recommendation} />
          </div>

          <TriggerBadge
            score={r.trigger_score}
            action={r.trigger_action}
            blocked={r.trigger_blocked}
            suggestedSize={r.suggested_position_size}
          />

          {isWatch && (
            <div style={{
              display: 'flex', alignItems: 'center', gap: '12px',
              padding: '12px 16px',
              background: '#2d2000', border: '1px solid #b7791f', borderRadius: '8px',
            }}>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: '13px', fontWeight: 700, color: '#fbd38d' }}>
                  👁 This stock is a WATCH — not ready yet
                </div>
                <div style={{ fontSize: '12px', color: '#718096', marginTop: '2px' }}>
                  Add to your watchlist. When it scores 5+ (SMALL BUY or STRONG BUY) you'll get an alert at the top of the Watchlist tab.
                </div>
              </div>
              {inWatchlist ? (
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
                  <span style={{ fontSize: '12px', color: '#68d391', fontWeight: 600 }}>✓ In watchlist</span>
                  <button
                    onClick={() => removeFromWatchlist(r.ticker)}
                    style={{ padding: '5px 10px', background: 'transparent', color: '#4a5568', border: '1px solid #2d3748', borderRadius: '6px', cursor: 'pointer', fontSize: '11px' }}
                  >
                    Remove
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => addToWatchlist(r)}
                  style={{ padding: '8px 18px', background: '#b7791f', color: '#fefcbf', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '13px', fontWeight: 700, flexShrink: 0 }}
                >
                  + Add to Watchlist
                </button>
              )}
            </div>
          )}

          <ScoreBreakdown breakdown={r.trigger_breakdown} />

          <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
            <div style={{ flex: 1, minWidth: '240px' }}>
              <MaStatusCard ma50={r.ma50} aboveMa={r.above_ma} crossover5d={r.crossover_5d} currentPrice={r.current_price} />
            </div>
            <div style={{ flex: 1, minWidth: '240px' }}>
              <BearProtectionCard level={r.bear_protection_level} bearUpside={r.dcf_bear_upside} />
            </div>
          </div>

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

          <PutSellingCard r={r} />

          <div style={{ borderTop: '1px solid #2d3748', paddingTop: '20px' }}>
            <div style={{ fontSize: '11px', color: '#718096', fontWeight: 600, letterSpacing: '0.08em', marginBottom: '16px' }}>
              FULL DCF ANALYSIS — CAPM WACC · Reverse DCF · Monte Carlo (10,000 simulations)
            </div>

            <div style={{ marginBottom: '16px' }}>
              <div style={{ fontSize: '11px', color: '#718096', fontWeight: 600, letterSpacing: '0.08em', marginBottom: '8px' }}>MARKET CONTEXT</div>
              <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                <MetricPill label="Price" value={r.current_price != null ? `$${r.current_price}` : '—'} />
                <MetricPill label="Mkt Cap" value={`$${r.market_cap_b}B`} />
                <MetricPill label="Rev Growth" value={`${r.revenue_growth_pct}%`} />
                {r.gross_margin_note === 'reported' ? (
                  <MetricPill label="Gross Margin" value={`${r.gross_margin_pct}%`} />
                ) : (
                  <div
                    title="⚠️ Gross margin data unavailable or unreliable from data source. FCF margin assumptions derived from operating margin and sector benchmarks."
                    style={{
                      background: '#0f1117', border: '1px solid #744210',
                      borderRadius: '6px', padding: '6px 10px', textAlign: 'center',
                      minWidth: '60px', cursor: 'help',
                    }}
                  >
                    <div style={{ fontSize: '10px', color: '#718096', marginBottom: '2px' }}>Gross Margin</div>
                    <div style={{ fontSize: '13px', fontWeight: 700, color: '#fbd38d' }}>N/A ⚠</div>
                  </div>
                )}
                <MetricPill label="FCF Margin" value={`${r.fcf_margin_pct}%`} />
                <MetricPill label="P/E" value={r.pe ?? '—'} />
                <MetricPill label="P/S" value={r.ps ?? '—'} />
                <MetricPill label="Beta" value={r.beta ?? '—'} />
                <MetricPill label="WACC" value={`${r.wacc_pct}%`} />
              </div>
            </div>

            <div style={{ background: '#0f1117', border: '1px solid #2d3748', borderRadius: '8px', padding: '14px 16px', marginBottom: '16px' }}>
              <div style={{ fontSize: '11px', color: '#718096', fontWeight: 600, letterSpacing: '0.08em', marginBottom: '6px' }}>REVERSE DCF — GROWTH RATE THE MARKET IS CURRENTLY PRICING IN</div>
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

            <div style={{ marginBottom: '16px' }}>
              <MonteCarloSection mc={r.monte_carlo} currentPrice={r.current_price} />
            </div>

            <div style={{ marginBottom: '16px' }}>
              <div style={{ fontSize: '11px', color: '#718096', fontWeight: 600, letterSpacing: '0.08em', marginBottom: '10px' }}>
                DCF SCENARIOS
                <span style={{ marginLeft: '8px', padding: '1px 7px', background: r.used_claude_params ? '#0a1628' : '#1a1a1a', color: r.used_claude_params ? '#4299e1' : '#718096', border: `1px solid ${r.used_claude_params ? '#2b6cb0' : '#2d3748'}`, borderRadius: '4px', fontSize: '10px' }}>
                  {r.used_claude_params ? 'Claude parameters' : 'mechanical fallback'}
                </span>
              </div>
              <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                <ScenarioCard label="BULL" price={r.dcf_bull_price} upside={r.dcf_bull_upside} g1Pct={r.bull_g1_pct} fcfPct={r.bull_fcf_pct} />
                <ScenarioCard label="BASE" price={r.dcf_base_price} upside={r.dcf_base_upside} g1Pct={r.base_g1_pct} fcfPct={r.base_fcf_pct} highlight />
                <ScenarioCard label="BEAR" price={r.dcf_bear_price} upside={r.dcf_bear_upside} g1Pct={r.bear_g1_pct} fcfPct={r.bear_fcf_pct} />
              </div>
            </div>

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

// ─── Main tab ─────────────────────────────────────────────────────────────────
export default function StockTriggersTab() {
  const [activeSubTab, setActiveSubTab] = useState('analysis')

  const [watchlist, setWatchlist] = useState(loadWatchlist)
  const [refreshProgress, setRefreshProgress] = useState({})
  const [upgrades, setUpgrades] = useState([])
  const [dismissedUpgrades, setDismissedUpgrades] = useState([])
  const didAutoRefresh = useRef(false)

  useEffect(() => {
    if (didAutoRefresh.current) return
    didAutoRefresh.current = true
    const stale = watchlist.filter(isStale)
    if (stale.length > 0) refreshItems(stale)
  }, []) // eslint-disable-line

  async function refreshItems(items) {
    const prog = {}
    items.forEach(it => { prog[it.ticker] = 'loading' })
    setRefreshProgress(prev => ({ ...prev, ...prog }))

    const newUpgrades = []

    await Promise.allSettled(items.map(async item => {
      try {
        const resp = await fetch(`${API}/api/triggers/${encodeURIComponent(item.ticker)}`)
        const body = await resp.json().catch(() => ({}))
        if (!resp.ok) throw new Error(body.detail || `Error ${resp.status}`)

        const prevAction = item.currentAction || item.actionAtAdd
        const wasWatch = prevAction === 'WATCH'
        const nowBetter = body.trigger_action === 'SMALL BUY' || body.trigger_action === 'STRONG BUY'

        setWatchlist(prev => {
          const next = prev.map(w => {
            if (w.ticker !== item.ticker) return w
            return {
              ...w,
              currentScore: body.trigger_score,
              currentAction: body.trigger_action,
              currentBlocked: body.trigger_blocked,
              upgradedFrom: (wasWatch && nowBetter) ? 'WATCH' : w.upgradedFrom,
              lastChecked: new Date().toISOString(),
              refreshError: null,
            }
          })
          saveWatchlist(next)
          return next
        })

        if (wasWatch && nowBetter) {
          newUpgrades.push({ ticker: item.ticker, action: body.trigger_action, score: body.trigger_score })
        }
        setRefreshProgress(prev => ({ ...prev, [item.ticker]: 'done' }))
      } catch (e) {
        setWatchlist(prev => {
          const next = prev.map(w => w.ticker !== item.ticker ? w : {
            ...w, lastChecked: new Date().toISOString(), refreshError: e.message,
          })
          saveWatchlist(next)
          return next
        })
        setRefreshProgress(prev => ({ ...prev, [item.ticker]: 'error' }))
      }
    }))

    if (newUpgrades.length) setUpgrades(prev => [...prev, ...newUpgrades])
  }

  function addToWatchlist(r) {
    setWatchlist(prev => {
      if (prev.some(w => w.ticker === r.ticker)) return prev
      const entry = {
        ticker: r.ticker,
        scoreAtAdd: r.trigger_score,
        actionAtAdd: r.trigger_action,
        addedAt: new Date().toISOString(),
        currentScore: null,
        currentAction: null,
        upgradedFrom: null,
        lastChecked: null,
        refreshError: null,
      }
      const next = [...prev, entry]
      saveWatchlist(next)
      return next
    })
  }

  function removeFromWatchlist(sym) {
    setWatchlist(prev => {
      const next = prev.filter(w => w.ticker !== sym)
      saveWatchlist(next)
      return next
    })
    setRefreshProgress(prev => { const n = { ...prev }; delete n[sym]; return n })
    setUpgrades(prev => prev.filter(u => u.ticker !== sym))
  }

  function dismissUpgrade(sym) {
    setDismissedUpgrades(prev => [...prev, sym])
  }

  const visibleUpgrades = upgrades.filter(u => !dismissedUpgrades.includes(u.ticker))

  // Called from Top Rated or Watchlist to jump to Analysis tab for a ticker
  function jumpToAnalysis(ticker) {
    setActiveSubTab('analysis')
    // Small delay so tab switch renders first
    setTimeout(() => {
      window.dispatchEvent(new CustomEvent('analyze-ticker', { detail: ticker }))
    }, 50)
  }

  return (
    <div style={{ maxWidth: '900px' }}>
      <div style={{ marginBottom: '16px' }}>
        <h2 style={{ fontSize: '20px', fontWeight: 700, color: '#e2e8f0', margin: '0 0 4px' }}>
          🎯 Stock Triggers
        </h2>
        <p style={{ fontSize: '13px', color: '#718096', margin: 0 }}>
          DCF · Monte Carlo · 50-day MA crossover · Earnings calendar · 0–8 point trigger score
        </p>
      </div>

      <SubTabs
        active={activeSubTab}
        onChange={setActiveSubTab}
        watchlistCount={watchlist.length}
        upgradeCount={visibleUpgrades.length}
      />

      {activeSubTab === 'analysis' && (
        <AnalysisTab
          watchlist={watchlist}
          addToWatchlist={addToWatchlist}
          removeFromWatchlist={removeFromWatchlist}
        />
      )}

      {activeSubTab === 'top_rated' && (
        <TopRatedTab onAnalyze={jumpToAnalysis} />
      )}

      {activeSubTab === 'watchlist' && (
        <div>
          <UpgradeAlerts
            upgrades={visibleUpgrades}
            onAnalyze={ticker => { jumpToAnalysis(ticker) }}
            onDismiss={dismissUpgrade}
          />
          <WatchlistSection
            watchlist={watchlist}
            refreshProgress={refreshProgress}
            onAnalyze={ticker => { jumpToAnalysis(ticker) }}
            onRemove={removeFromWatchlist}
            onRefreshAll={() => refreshItems(watchlist.filter(isStale))}
          />
        </div>
      )}
    </div>
  )
}
