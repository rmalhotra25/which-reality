import { useState, useEffect, useCallback } from 'react'
import { api } from '../api'
import { useRefreshPoller } from '../hooks/useRefreshPoller'
import LastUpdated from '../components/LastUpdated'
import AccountWidget from '../components/AccountWidget'
import WheelCard from '../wheel/WheelCard'
import PositionTracker from '../wheel/PositionTracker'
import WheelCustomAnalysis from '../wheel/WheelCustomAnalysis'

const s = {
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '24px',
    flexWrap: 'wrap',
    gap: '12px',
  },
  title: { fontSize: '20px', fontWeight: 700, color: '#e2e8f0' },
  btnRow: {
    display: 'flex',
    gap: '8px',
    alignItems: 'center',
    flexWrap: 'wrap',
  },
  refreshBtn: {
    padding: '8px 16px',
    background: '#2b6cb0',
    color: '#fff',
    border: 'none',
    borderRadius: '6px',
    cursor: 'pointer',
    fontSize: '13px',
    fontWeight: 500,
  },
  exportBtn: {
    padding: '8px 14px',
    background: 'transparent',
    color: '#68d391',
    border: '1px solid #276749',
    borderRadius: '6px',
    cursor: 'pointer',
    fontSize: '12px',
    fontWeight: 500,
  },
  sectionTitle: {
    fontSize: '15px',
    fontWeight: 600,
    color: '#a0aec0',
    marginBottom: '16px',
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
  },
  divider: {
    border: 'none',
    borderTop: '1px solid #2d3748',
    margin: '32px 0',
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(420px, 1fr))',
    gap: '16px',
  },
  empty: { color: '#718096', textAlign: 'center', padding: '32px', fontSize: '14px' },
  error: { color: '#fc8181', padding: '16px', fontSize: '14px' },
  showClosedBtn: {
    padding: '6px 14px',
    background: 'transparent',
    border: '1px solid #2d3748',
    borderRadius: '6px',
    color: '#718096',
    cursor: 'pointer',
    fontSize: '12px',
    marginBottom: '16px',
  },
}

const scannerStyles = {
  section: { marginBottom: '8px' },
  header: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', flexWrap: 'wrap', gap: '8px' },
  sectionTitle: { fontSize: '15px', fontWeight: 600, color: '#a0aec0', display: 'flex', alignItems: 'center', gap: '8px' },
  meta: { fontSize: '12px', color: '#718096' },
  refreshBtn: { padding: '6px 14px', background: '#2b6cb0', color: '#fff', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '12px' },
  tabRow: { display: 'flex', gap: '8px', marginBottom: '16px' },
  tab: (active) => ({
    padding: '6px 14px', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '12px', fontWeight: 500,
    background: active ? '#2d3748' : 'transparent', color: active ? '#e2e8f0' : '#718096',
  }),
  card: {
    background: '#1a1f2e', border: '1px solid #2d3748', borderRadius: '8px',
    padding: '14px 16px', marginBottom: '10px',
  },
  cardHeader: { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '8px' },
  ticker: { fontSize: '16px', fontWeight: 700, color: '#63b3ed' },
  score: { fontSize: '13px', fontWeight: 600, color: '#68d391' },
  grid2: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px 16px', fontSize: '12px', color: '#a0aec0', marginBottom: '8px' },
  label: { color: '#718096' },
  flagRow: { display: 'flex', flexWrap: 'wrap', gap: '6px', marginTop: '6px' },
  flag: (color) => ({
    fontSize: '11px', padding: '2px 8px', borderRadius: '10px',
    background: color === 'red' ? '#2d1515' : color === 'yellow' ? '#2d2615' : color === 'green' ? '#1a2d1a' : '#1a2234',
    color: color === 'red' ? '#fc8181' : color === 'yellow' ? '#f6e05e' : color === 'green' ? '#68d391' : '#a0aec0',
    border: `1px solid ${color === 'red' ? '#742a2a' : color === 'yellow' ? '#744210' : color === 'green' ? '#276749' : '#2d3748'}`,
  }),
  formula: { fontSize: '10px', color: '#4a5568', marginTop: '6px', fontFamily: 'monospace', wordBreak: 'break-all' },
  excludedRow: { fontSize: '12px', color: '#718096', padding: '6px 0', borderBottom: '1px solid #1a1f2e', display: 'flex', justifyContent: 'space-between' },
  emptyNote: { color: '#4a5568', fontSize: '13px', padding: '24px 0', textAlign: 'center' },
  showMoreBtn: { padding: '6px 14px', background: 'transparent', border: '1px solid #2d3748', borderRadius: '6px', color: '#718096', cursor: 'pointer', fontSize: '12px', marginTop: '8px' },
}

function PutCandidateCard({ c, rank }) {
  const pct = (v, d = 2) => v != null ? `${(v * 100).toFixed(d)}%` : 'n/a'
  const fmt = (v, d = 2) => v != null ? v.toFixed(d) : 'n/a'
  const penalties = c.penalties || []
  return (
    <div style={scannerStyles.card}>
      <div style={scannerStyles.cardHeader}>
        <div>
          <span style={{ ...scannerStyles.ticker }}>{rank}. {c.ticker}</span>
          <span style={{ marginLeft: '8px', fontSize: '12px', color: '#718096' }}>
            ${c.current_price?.toFixed(2)} &middot; {c.trend_state === 'above_200ma' ? '▲ above 200MA' : c.trend_state === 'below_200ma' ? '▼ below 200MA' : ''}
          </span>
        </div>
        <span style={scannerStyles.score}>score: {c.rank_score?.toFixed(7)}</span>
      </div>

      <div style={scannerStyles.grid2}>
        <span><span style={scannerStyles.label}>Strike: </span>${c.strike}</span>
        <span><span style={scannerStyles.label}>Expiry: </span>{c.expiry} ({c.dte}d)</span>
        <span><span style={scannerStyles.label}>Mid: </span>${fmt(c.mid_premium)} ({c.bid}/{c.ask})</span>
        <span><span style={scannerStyles.label}>$/day on capital: </span>{pct(c.raw_pppd, 4)}</span>
        <span><span style={scannerStyles.label}>IV: </span>{c.iv_pct?.toFixed(1)}%
          {c.iv_percentile != null && <span style={{ color: '#718096' }}> (p{c.iv_percentile?.toFixed(0)}{c.iv_pct_source === 'historical' ? ' approx' : ''})</span>}
        </span>
        <span><span style={scannerStyles.label}>Delta: </span>{fmt(c.delta_abs)} ({c.assignment_chance_pct}% asgn)</span>
        <span><span style={scannerStyles.label}>OI / Vol: </span>{c.open_interest} / {c.volume}</span>
        <span><span style={scannerStyles.label}>Spread: </span>{c.spread_pct?.toFixed(1)}% of mid</span>
      </div>

      <div style={scannerStyles.flagRow}>
        {c.earnings_in_window && <span style={scannerStyles.flag('red')}>earnings in window</span>}
        {penalties.map((p, i) => <span key={i} style={scannerStyles.flag('yellow')}>{p.reason} x{p.multiplier}</span>)}
        <span style={scannerStyles.flag(c.quality_verdict === 'PASS' ? 'green' : c.quality_verdict === 'FAIL' ? 'red' : 'neutral')}>
          {c.quality_verdict}{c.quant_score != null ? ` (${c.quant_score})` : ''}
        </span>
        {c.data_source && <span style={scannerStyles.flag('neutral')}>{c.data_source}</span>}
      </div>
      <div style={scannerStyles.formula}>formula: {c.ranking_formula}</div>
    </div>
  )
}

function CallCandidateCard({ c, rank }) {
  const fmt = (v, d = 2) => v != null ? v.toFixed(d) : 'n/a'
  return (
    <div style={scannerStyles.card}>
      <div style={scannerStyles.cardHeader}>
        <div>
          <span style={scannerStyles.ticker}>{rank}. {c.ticker}</span>
          <span style={{ marginLeft: '8px', fontSize: '12px', color: '#718096' }}>
            ${c.current_price?.toFixed(2)}{c.cost_basis ? ` · basis $${c.cost_basis.toFixed(2)}` : ''}
          </span>
        </div>
        <span style={scannerStyles.score}>score: {c.rank_score?.toFixed(7)}</span>
      </div>
      <div style={scannerStyles.grid2}>
        <span><span style={{ color: '#718096' }}>Strike: </span>${c.strike} (+{c.upside_to_strike_pct}%)</span>
        <span><span style={{ color: '#718096' }}>Expiry: </span>{c.expiry} ({c.dte}d)</span>
        <span><span style={{ color: '#718096' }}>Mid: </span>${fmt(c.mid_premium)} ({c.bid}/{c.ask})</span>
        <span><span style={{ color: '#718096' }}>$/day on stock: </span>{(c.raw_pppd * 100).toFixed(4)}%</span>
        <span><span style={{ color: '#718096' }}>IV: </span>{c.iv_pct?.toFixed(1)}%</span>
        <span><span style={{ color: '#718096' }}>Delta: </span>{fmt(c.delta)} ({c.call_away_chance_pct}% call-away)</span>
        <span><span style={{ color: '#718096' }}>OI / Vol: </span>{c.open_interest} / {c.volume}</span>
        <span><span style={{ color: '#718096' }}>Spread: </span>{c.spread_pct?.toFixed(1)}% of mid</span>
      </div>
      <div style={scannerStyles.flagRow}>
        {c.early_assignment_risk && (
          <span style={scannerStyles.flag('red')}>ex-div {c.ex_dividend_date} (early assignment risk)</span>
        )}
        {c.data_source && <span style={scannerStyles.flag('neutral')}>{c.data_source}</span>}
      </div>
    </div>
  )
}

function ScannerSection({ data, loading, refreshing, onRefresh, showCallCandidates, setShowCallCandidates, showExcluded, setShowExcluded }) {
  const [showAllExcluded, setShowAllExcluded] = useState(false)
  const puts = data?.puts
  const calls = data?.calls

  const putCandidates = puts?.candidates || []
  const putExcluded = puts?.excluded || []
  const callCandidates = calls?.candidates || []
  const callExcluded = calls?.excluded || []

  const excluded = showCallCandidates ? callExcluded : putExcluded
  const excVisible = showAllExcluded ? excluded : excluded.slice(0, 10)

  const runAt = puts?.run_at || calls?.run_at
  const universeSize = puts?.universe_size || calls?.universe_size

  return (
    <div style={scannerStyles.section}>
      <div style={scannerStyles.header}>
        <div>
          <div style={scannerStyles.sectionTitle}>
            <span>🔍</span> Wheel Scanner
            {putCandidates.length > 0 && (
              <span style={{ background: '#1a2d1a', color: '#68d391', fontSize: '11px', padding: '1px 8px', borderRadius: '10px', border: '1px solid #276749' }}>
                {putCandidates.length} candidates
              </span>
            )}
          </div>
          {runAt && (
            <div style={scannerStyles.meta}>
              Last scan: {new Date(runAt).toLocaleString()} &middot; universe: {universeSize}
            </div>
          )}
          {!runAt && !loading && (
            <div style={scannerStyles.meta}>No scan results yet. Click Scan Universe to run.</div>
          )}
        </div>
        <button style={scannerStyles.refreshBtn} onClick={onRefresh} disabled={refreshing}>
          {refreshing ? '⏳ Scanning...' : '▶ Scan Universe'}
        </button>
      </div>

      {loading && <div style={scannerStyles.emptyNote}>Loading scanner results...</div>}

      {!loading && data?.has_data && (
        <>
          <div style={scannerStyles.tabRow}>
            <button style={scannerStyles.tab(!showCallCandidates)} onClick={() => setShowCallCandidates(false)}>
              Puts ({putCandidates.length})
            </button>
            <button style={scannerStyles.tab(showCallCandidates)} onClick={() => setShowCallCandidates(true)}>
              Covered Calls ({callCandidates.length})
            </button>
          </div>

          {!showCallCandidates && (
            putCandidates.length === 0
              ? <div style={scannerStyles.emptyNote}>No put candidates passed all filters.</div>
              : putCandidates.map((c, i) => <PutCandidateCard key={c.ticker} c={c} rank={i + 1} />)
          )}

          {showCallCandidates && (
            callCandidates.length === 0
              ? <div style={scannerStyles.emptyNote}>No covered call candidates passed all filters.</div>
              : callCandidates.map((c, i) => <CallCandidateCard key={c.ticker} c={c} rank={i + 1} />)
          )}

          <button style={scannerStyles.showMoreBtn} onClick={() => setShowExcluded(!showExcluded)}>
            {showExcluded ? '▲ Hide' : '▼ Show'} excluded ({excluded.length})
          </button>

          {showExcluded && (
            <div style={{ marginTop: '8px' }}>
              {excVisible.map((e) => (
                <div key={e.ticker} style={scannerStyles.excludedRow}>
                  <span style={{ fontWeight: 600, color: '#a0aec0' }}>{e.ticker}</span>
                  <span>{e.reason}{e.spread_pct != null ? ` (spread ${e.spread_pct}%)` : ''}{e.open_interest != null ? ` (OI ${e.open_interest})` : ''}</span>
                </div>
              ))}
              {excluded.length > 10 && (
                <button style={scannerStyles.showMoreBtn} onClick={() => setShowAllExcluded(!showAllExcluded)}>
                  {showAllExcluded ? '▲ Show fewer' : `▼ Show all ${excluded.length}`}
                </button>
              )}
            </div>
          )}
        </>
      )}
    </div>
  )
}

function downloadJson(data, filename) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

// ---------------------------------------------------------------------------
// Covered Calls section (moved from the former Covered Calls tab, stage 3
// cleanup). Same endpoints, inputs and outputs: api.coveredCalls.analyze
// for the income generator and api.coveredCalls.weeklyAnalyze for the
// weekly scanner below it.
// ---------------------------------------------------------------------------

const WEEKLY_TICKERS = ['SPY', 'QQQ', 'AAPL', 'MSFT', 'NVDA', 'TSLA', 'AMZN', 'COIN', 'PLTR', 'AMD', 'META']

const TIER_BADGE = {
  aggressive: { color: '#fc8181', label: 'Aggressive' },
  balanced:   { color: '#f6e05e', label: 'Balanced' },
  conservative: { color: '#68d391', label: 'Conservative' },
}

function WeeklyScanner() {
  const [ticker, setTicker] = useState('')
  const [costBasis, setCostBasis] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)

  const analyze = async (sym) => {
    const symbol = (sym || ticker).trim().toUpperCase()
    if (!symbol) return
    setTicker(symbol)
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const cb = costBasis ? parseFloat(costBasis) : null
      const data = await api.coveredCalls.weeklyAnalyze(symbol, cb)
      setResult(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const rec = result
  const badge = rec ? TIER_BADGE[rec.recommended_tier] : null
  const tiers = rec?.tiers ?? {}

  return (
    <div style={{ marginTop: '40px', paddingTop: '32px', borderTop: '1px solid #2d3748' }}>
      <div style={{ marginBottom: '20px' }}>
        <div style={{ fontSize: '18px', fontWeight: 700, color: '#e2e8f0', marginBottom: '4px' }}>
          📆 This Week's Options Scanner
        </div>
        <div style={{ fontSize: '13px', color: '#718096' }}>
          AI analyzes live news + this week's option chain and tells you exactly what to sell by Friday
        </div>
      </div>

      <div style={{ display: 'flex', gap: '10px', marginBottom: '12px', alignItems: 'flex-end', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          <div style={{ fontSize: '11px', color: '#718096', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Ticker</div>
          <input
            style={{ width: '120px', padding: '10px 14px', background: '#1a1f2e', border: '1px solid #2d3748', borderRadius: '8px', color: '#e2e8f0', fontSize: '16px', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', outline: 'none' }}
            value={ticker}
            onChange={(e) => setTicker(e.target.value.toUpperCase())}
            onKeyDown={(e) => e.key === 'Enter' && analyze()}
            placeholder="AAPL"
            maxLength={6}
          />
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          <div style={{ fontSize: '11px', color: '#718096', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Cost Basis / share (optional)</div>
          <input
            style={{ width: '130px', padding: '10px 14px', background: '#1a1f2e', border: '1px solid #2d3748', borderRadius: '8px', color: '#e2e8f0', fontSize: '14px', outline: 'none' }}
            type="number" step="0.01" min="0"
            value={costBasis}
            onChange={(e) => setCostBasis(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && analyze()}
            placeholder="e.g. 185.00"
          />
        </div>
        <button
          style={{ padding: '10px 22px', background: loading ? '#2d3748' : '#276749', color: loading ? '#718096' : '#fff', border: 'none', borderRadius: '8px', cursor: loading ? 'not-allowed' : 'pointer', fontSize: '14px', fontWeight: 600, alignSelf: 'flex-end', whiteSpace: 'nowrap' }}
          onClick={() => analyze()}
          disabled={loading || !ticker.trim()}
        >
          {loading ? '⏳ Analyzing...' : '📆 Analyze This Week'}
        </button>
      </div>

      <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', marginBottom: '8px' }}>
        {WEEKLY_TICKERS.map((sym) => (
          <button key={sym} style={{ padding: '4px 11px', background: '#1a1f2e', border: '1px solid #2d3748', borderRadius: '20px', color: '#a0aec0', fontSize: '12px', fontWeight: 600, cursor: 'pointer' }} onClick={() => analyze(sym)}>{sym}</button>
        ))}
      </div>
      <div style={{ fontSize: '12px', color: '#4a5568', marginBottom: '20px' }}>
        Best for stocks with weekly options — SPY, QQQ, large-cap tech, etc.
      </div>

      {error && (
        <div style={{ color: '#fc8181', padding: '14px 16px', background: '#2d1515', border: '1px solid #742a2a', borderRadius: '8px', fontSize: '14px', marginBottom: '20px' }}>
          ⚠ {error}
        </div>
      )}

      {rec && (
        <div>
          {/* Header bar */}
          <div style={{ display: 'flex', gap: '20px', flexWrap: 'wrap', alignItems: 'center', background: '#1a1f2e', border: '1px solid #2d3748', borderRadius: '8px', padding: '12px 16px', marginBottom: '16px', fontSize: '13px', color: '#a0aec0' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
              <div style={{ fontSize: '10px', color: '#718096', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 }}>Ticker</div>
              <div style={{ fontSize: '14px', fontWeight: 700, color: '#e2e8f0' }}>{rec.ticker}</div>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
              <div style={{ fontSize: '10px', color: '#718096', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 }}>Price</div>
              <div style={{ fontSize: '14px', fontWeight: 700, color: '#e2e8f0' }}>{ccFmt(rec.current_price)}</div>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
              <div style={{ fontSize: '10px', color: '#718096', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 }}>Expiry</div>
              <div style={{ fontSize: '14px', fontWeight: 700, color: '#e2e8f0' }}>{rec.expiry} ({rec.dte}d)</div>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
              <div style={{ fontSize: '10px', color: '#718096', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 }}>ATM IV</div>
              <div style={{ fontSize: '14px', fontWeight: 700, color: '#e2e8f0' }}>{rec.atm_iv_pct ?? '—'}%</div>
            </div>
            {rec.iv_rank?.iv_rank != null && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                <div style={{ fontSize: '10px', color: '#718096', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 }}>IV Rank</div>
                <div style={{ fontSize: '14px', fontWeight: 700, color: rec.iv_rank.iv_rank >= 50 ? '#68d391' : rec.iv_rank.iv_rank < 25 ? '#fc8181' : '#fbd38d' }}>
                  {rec.iv_rank.iv_rank}<span style={{ fontSize: '10px', color: '#718096', marginLeft: '3px' }}>/ 100</span>
                </div>
              </div>
            )}
          </div>

          {rec.data_source === 'last_trade' && (
            <div style={{ fontSize: '12px', color: '#4a5568', marginBottom: '12px' }}>
              ℹ Markets closed — using last-trade prices. Live bid/ask available during market hours.
            </div>
          )}

          {/* Risk flag */}
          {rec.risk_flag && (
            <div style={{ fontSize: '13px', color: '#f6e05e', background: '#2d2200', border: '1px solid #b7791f', borderRadius: '8px', padding: '10px 14px', marginBottom: '16px' }}>
              ⚠ {rec.risk_flag}
            </div>
          )}

          {/* Main recommendation card */}
          <div style={{ background: '#0d2218', border: `2px solid ${badge?.color ?? '#68d391'}`, borderRadius: '12px', padding: '20px', marginBottom: '16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '14px' }}>
              <span style={{ fontSize: '22px', fontWeight: 800, color: badge?.color ?? '#68d391' }}>{ccFmt(rec.strike)} Call</span>
              {badge && (
                <span style={{ fontSize: '11px', fontWeight: 700, color: badge.color, background: 'rgba(0,0,0,0.4)', border: `1px solid ${badge.color}`, borderRadius: '12px', padding: '2px 10px', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                  {badge.label}
                </span>
              )}
              <span style={{ marginLeft: 'auto', fontSize: '22px', fontWeight: 800, color: '#68d391' }}>{ccFmt(rec.premium_per_contract)}</span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '8px', marginBottom: '16px' }}>
              <div style={{ background: 'rgba(0,0,0,0.3)', borderRadius: '6px', padding: '8px 10px' }}>
                <div style={{ fontSize: '10px', color: '#718096', textTransform: 'uppercase', fontWeight: 600 }}>Strike</div>
                <div style={{ fontSize: '14px', fontWeight: 700, color: '#e2e8f0', marginTop: '2px' }}>{ccFmt(rec.strike)}</div>
              </div>
              <div style={{ background: 'rgba(0,0,0,0.3)', borderRadius: '6px', padding: '8px 10px' }}>
                <div style={{ fontSize: '10px', color: '#718096', textTransform: 'uppercase', fontWeight: 600 }}>Call-Away Chance</div>
                <div style={{ fontSize: '14px', fontWeight: 700, color: '#e2e8f0', marginTop: '2px' }}>{rec.call_away_chance_pct ?? '—'}%</div>
              </div>
              <div style={{ background: 'rgba(0,0,0,0.3)', borderRadius: '6px', padding: '8px 10px' }}>
                <div style={{ fontSize: '10px', color: '#718096', textTransform: 'uppercase', fontWeight: 600 }}>Weekly Yield</div>
                <div style={{ fontSize: '14px', fontWeight: 700, color: '#e2e8f0', marginTop: '2px' }}>{rec.weekly_yield_pct ?? '—'}%</div>
              </div>
            </div>

            {rec.recommendation && (
              <div style={{ marginBottom: '12px' }}>
                <div style={{ fontSize: '10px', color: '#718096', textTransform: 'uppercase', fontWeight: 600, letterSpacing: '0.05em', marginBottom: '5px' }}>AI Recommendation</div>
                <div style={{ fontSize: '14px', color: '#cbd5e0', lineHeight: 1.6 }}>{rec.recommendation}</div>
              </div>
            )}

            {rec.news_impact && (
              <div style={{ marginBottom: '12px' }}>
                <div style={{ fontSize: '10px', color: '#718096', textTransform: 'uppercase', fontWeight: 600, letterSpacing: '0.05em', marginBottom: '5px' }}>This Week's News</div>
                <div style={{ fontSize: '13px', color: '#90cdf4', lineHeight: 1.5, fontStyle: 'italic' }}>{rec.news_impact}</div>
              </div>
            )}

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
              {rec.if_called && (
                <div style={{ background: 'rgba(0,0,0,0.3)', borderRadius: '8px', padding: '10px 12px' }}>
                  <div style={{ fontSize: '10px', color: '#718096', textTransform: 'uppercase', fontWeight: 600, marginBottom: '4px' }}>If shares get called away</div>
                  <div style={{ fontSize: '12px', color: '#cbd5e0', lineHeight: 1.5 }}>{rec.if_called}</div>
                </div>
              )}
              {rec.if_not_called && (
                <div style={{ background: 'rgba(0,0,0,0.3)', borderRadius: '8px', padding: '10px 12px' }}>
                  <div style={{ fontSize: '10px', color: '#718096', textTransform: 'uppercase', fontWeight: 600, marginBottom: '4px' }}>If shares stay below strike</div>
                  <div style={{ fontSize: '12px', color: '#cbd5e0', lineHeight: 1.5 }}>{rec.if_not_called}</div>
                </div>
              )}
            </div>
          </div>

          {/* Tier cards for balanced + conservative */}
          {(tiers.balanced || tiers.conservative) && (
            <div style={{ marginBottom: '12px' }}>
              <div style={{ fontSize: '11px', color: '#718096', textTransform: 'uppercase', fontWeight: 600, letterSpacing: '0.05em', marginBottom: '10px' }}>Other Options This Week</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                {['balanced', 'conservative'].map((tierKey) => {
                  const t = tiers[tierKey]
                  if (!t) return null
                  const b = TIER_BADGE[tierKey]
                  const isRec = rec.recommended_tier === tierKey
                  const bgColor = tierKey === 'balanced' ? '#1a1400' : '#071410'
                  const borderColor = isRec ? b.color : (tierKey === 'balanced' ? '#b7791f44' : '#27674944')
                  return (
                    <div key={tierKey} style={{ background: bgColor, border: `1px solid ${borderColor}`, borderRadius: '10px', padding: '14px 16px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '10px' }}>
                        <span style={{ fontSize: '16px', fontWeight: 800, color: b.color }}>{ccFmt(t.strike)} Call</span>
                        <span style={{ fontSize: '11px', fontWeight: 700, color: b.color, background: 'rgba(0,0,0,0.4)', border: `1px solid ${b.color}`, borderRadius: '12px', padding: '2px 10px', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{b.label}</span>
                        {isRec && <span style={{ fontSize: '10px', color: b.color, fontWeight: 700, marginLeft: 'auto' }}>← AI Pick</span>}
                        <span style={{ fontSize: '16px', fontWeight: 800, color: '#68d391', marginLeft: isRec ? '0' : 'auto' }}>{ccFmt(t.premium_per_contract)}</span>
                      </div>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '8px' }}>
                        <div style={{ background: 'rgba(0,0,0,0.3)', borderRadius: '6px', padding: '7px 10px' }}>
                          <div style={{ fontSize: '10px', color: '#718096', textTransform: 'uppercase', fontWeight: 600 }}>Strike</div>
                          <div style={{ fontSize: '13px', fontWeight: 700, color: '#e2e8f0', marginTop: '2px' }}>{ccFmt(t.strike)}</div>
                        </div>
                        <div style={{ background: 'rgba(0,0,0,0.3)', borderRadius: '6px', padding: '7px 10px' }}>
                          <div style={{ fontSize: '10px', color: '#718096', textTransform: 'uppercase', fontWeight: 600 }}>Premium</div>
                          <div style={{ fontSize: '13px', fontWeight: 700, color: '#e2e8f0', marginTop: '2px' }}>{ccFmt(t.mid_premium)} mid</div>
                        </div>
                        <div style={{ background: 'rgba(0,0,0,0.3)', borderRadius: '6px', padding: '7px 10px' }}>
                          <div style={{ fontSize: '10px', color: '#718096', textTransform: 'uppercase', fontWeight: 600 }}>Call-Away</div>
                          <div style={{ fontSize: '13px', fontWeight: 700, color: '#e2e8f0', marginTop: '2px' }}>{t.call_away_chance_pct}%</div>
                        </div>
                        <div style={{ background: 'rgba(0,0,0,0.3)', borderRadius: '6px', padding: '7px 10px' }}>
                          <div style={{ fontSize: '10px', color: '#718096', textTransform: 'uppercase', fontWeight: 600 }}>Weekly Yield</div>
                          <div style={{ fontSize: '13px', fontWeight: 700, color: '#e2e8f0', marginTop: '2px' }}>{t.pct_of_stock_weekly}%</div>
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          <div style={{ fontSize: '11px', color: '#4a5568' }}>
            AI analysis using live news + options data — not financial advice. Verify quotes with your broker before trading.
          </div>
        </div>
      )}
    </div>
  )
}

const TIER_CONFIG = {
  aggressive: {
    label: 'Aggressive',
    sublabel: 'Highest income · Shares likely sold',
    borderColor: '#c53030',
    bg: '#1f0a0a',
    headerBg: '#3a1212',
    accentColor: '#fc8181',
    icon: '🔴',
  },
  balanced: {
    label: 'Balanced',
    sublabel: 'Good income · Moderate risk',
    borderColor: '#b7791f',
    bg: '#1a1400',
    headerBg: '#2d2200',
    accentColor: '#f6e05e',
    icon: '🟡',
  },
  conservative: {
    label: 'Conservative',
    sublabel: 'Keep shares · Lower premium',
    borderColor: '#276749',
    bg: '#071410',
    headerBg: '#0d2218',
    accentColor: '#68d391',
    icon: '🟢',
  },
}

const QUICK_TICKERS = ['AMZN', 'SCHD', 'VTI', 'QQQM', 'QQQ', 'AAPL', 'MSFT', 'NVDA', 'TSLA', 'COIN', 'PLTR']

const ccStyles = {
  header: { marginBottom: '24px' },
  title: { fontSize: '20px', fontWeight: 700, color: '#e2e8f0', marginBottom: '4px' },
  subtitle: { fontSize: '13px', color: '#718096' },
  formRow: {
    display: 'flex',
    gap: '10px',
    marginBottom: '16px',
    alignItems: 'flex-end',
    flexWrap: 'wrap',
  },
  inputGroup: { display: 'flex', flexDirection: 'column', gap: '4px' },
  label: { fontSize: '11px', color: '#718096', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em' },
  tickerInput: {
    width: '120px',
    padding: '10px 14px',
    background: '#1a1f2e',
    border: '1px solid #2d3748',
    borderRadius: '8px',
    color: '#e2e8f0',
    fontSize: '16px',
    fontWeight: 700,
    textTransform: 'uppercase',
    letterSpacing: '0.08em',
    outline: 'none',
  },
  costInput: {
    width: '130px',
    padding: '10px 14px',
    background: '#1a1f2e',
    border: '1px solid #2d3748',
    borderRadius: '8px',
    color: '#e2e8f0',
    fontSize: '14px',
    outline: 'none',
  },
  generateBtn: (loading) => ({
    padding: '10px 22px',
    background: loading ? '#2d3748' : '#2b6cb0',
    color: loading ? '#718096' : '#fff',
    border: 'none',
    borderRadius: '8px',
    cursor: loading ? 'not-allowed' : 'pointer',
    fontSize: '14px',
    fontWeight: 600,
    alignSelf: 'flex-end',
    whiteSpace: 'nowrap',
  }),
  quickRow: { display: 'flex', gap: '6px', flexWrap: 'wrap', marginBottom: '8px' },
  chip: {
    padding: '4px 11px',
    background: '#1a1f2e',
    border: '1px solid #2d3748',
    borderRadius: '20px',
    color: '#a0aec0',
    fontSize: '12px',
    fontWeight: 600,
    cursor: 'pointer',
  },
  hint: { fontSize: '12px', color: '#4a5568', marginBottom: '24px' },
  error: { color: '#fc8181', padding: '14px 16px', background: '#2d1515', border: '1px solid #742a2a', borderRadius: '8px', fontSize: '14px', marginBottom: '20px' },
  metaBar: {
    display: 'flex',
    gap: '20px',
    flexWrap: 'wrap',
    alignItems: 'center',
    background: '#1a1f2e',
    border: '1px solid #2d3748',
    borderRadius: '8px',
    padding: '12px 16px',
    marginBottom: '20px',
    fontSize: '13px',
    color: '#a0aec0',
  },
  metaItem: { display: 'flex', flexDirection: 'column', gap: '2px' },
  metaLabel: { fontSize: '10px', color: '#718096', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 },
  metaValue: { fontSize: '14px', fontWeight: 700, color: '#e2e8f0' },
  ivNote: { fontSize: '13px', color: '#90cdf4', fontStyle: 'italic', flex: 1 },
  tiersGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))',
    gap: '16px',
    marginBottom: '20px',
  },
  tierCard: (cfg) => ({
    background: cfg.bg,
    border: `1px solid ${cfg.borderColor}`,
    borderRadius: '12px',
    overflow: 'hidden',
  }),
  tierHeader: (cfg) => ({
    background: cfg.headerBg,
    borderBottom: `1px solid ${cfg.borderColor}`,
    padding: '14px 16px',
    display: 'flex',
    alignItems: 'center',
    gap: '10px',
  }),
  tierIcon: { fontSize: '20px' },
  tierLabelGroup: { flex: 1 },
  tierLabel: (cfg) => ({ fontSize: '16px', fontWeight: 700, color: cfg.accentColor }),
  tierSublabel: { fontSize: '11px', color: '#718096', marginTop: '1px' },
  premiumBig: (cfg) => ({
    fontSize: '22px',
    fontWeight: 800,
    color: cfg.accentColor,
    textAlign: 'right',
  }),
  premiumLabel: { fontSize: '10px', color: '#718096', textAlign: 'right', marginTop: '1px' },
  tierBody: { padding: '16px' },
  section: { marginBottom: '14px' },
  sectionLabel: {
    fontSize: '10px',
    color: '#718096',
    textTransform: 'uppercase',
    letterSpacing: '0.06em',
    fontWeight: 600,
    marginBottom: '5px',
  },
  sectionText: { fontSize: '13px', color: '#cbd5e0', lineHeight: 1.6 },
  statsRow: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: '8px',
    marginBottom: '14px',
  },
  statBox: {
    background: 'rgba(0,0,0,0.3)',
    borderRadius: '6px',
    padding: '8px 10px',
  },
  statLabel: { fontSize: '10px', color: '#718096', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 },
  statValue: { fontSize: '14px', fontWeight: 700, color: '#e2e8f0', marginTop: '2px' },
  bestFor: (cfg) => ({
    fontSize: '12px',
    color: cfg.accentColor,
    fontStyle: 'italic',
    padding: '8px 10px',
    background: 'rgba(0,0,0,0.3)',
    borderRadius: '6px',
    lineHeight: 1.5,
  }),
  thinWarning: {
    fontSize: '12px',
    color: '#f6e05e',
    background: '#2d2200',
    border: '1px solid #b7791f',
    borderRadius: '6px',
    padding: '6px 10px',
    marginTop: '10px',
  },
  disclaimer: { fontSize: '11px', color: '#4a5568', marginTop: '16px' },
  dataSourceNote: { fontSize: '12px', color: '#4a5568', marginTop: '4px' },
  statPill: {
    display: 'flex',
    flexDirection: 'column',
    gap: '2px',
  },
  statVal: { fontSize: '14px', fontWeight: 700, color: '#e2e8f0' },
}

function ccFmt(val) {
  if (val == null) return '—'
  return `$${Number(val).toFixed(2)}`
}

function TierCard({ tier, data, cfg }) {
  if (!data) return null
  const rawTier = tier    // 'aggressive' | 'balanced' | 'conservative'

  return (
    <div style={ccStyles.tierCard(cfg)}>
      <div style={ccStyles.tierHeader(cfg)}>
        <span style={ccStyles.tierIcon}>{cfg.icon}</span>
        <div style={ccStyles.tierLabelGroup}>
          <div style={ccStyles.tierLabel(cfg)}>{cfg.label}</div>
          <div style={ccStyles.tierSublabel}>{cfg.sublabel}</div>
        </div>
        <div>
          <div style={ccStyles.premiumBig(cfg)}>{ccFmt(data.premium_per_contract)}</div>
          <div style={ccStyles.premiumLabel}>per contract</div>
        </div>
      </div>

      <div style={ccStyles.tierBody}>
        {/* Key stats */}
        <div style={ccStyles.statsRow}>
          <div style={ccStyles.statBox}>
            <div style={ccStyles.statLabel}>Strike</div>
            <div style={ccStyles.statValue}>{ccFmt(data.strike)}</div>
          </div>
          <div style={ccStyles.statBox}>
            <div style={ccStyles.statLabel}>Expiry</div>
            <div style={ccStyles.statValue}>{data.expiry} ({data.dte}d)</div>
          </div>
          <div style={ccStyles.statBox}>
            <div style={ccStyles.statLabel}>Call-Away Chance</div>
            <div style={ccStyles.statValue}>{data.call_away_chance_pct ?? '—'}%</div>
          </div>
          <div style={ccStyles.statBox}>
            <div style={ccStyles.statLabel}>Weekly Yield</div>
            <div style={ccStyles.statValue}>{data.pct_of_stock_weekly ?? '—'}%</div>
          </div>
        </div>

        {/* AI plain-English explanation */}
        {data.premium_plain && (
          <div style={ccStyles.section}>
            <div style={ccStyles.sectionLabel}>What you collect</div>
            <div style={ccStyles.sectionText}>{data.premium_plain}</div>
          </div>
        )}

        {data.callaway_plain && (
          <div style={ccStyles.section}>
            <div style={ccStyles.sectionLabel}>Chance of losing shares</div>
            <div style={ccStyles.sectionText}>{data.callaway_plain}</div>
          </div>
        )}

        {data.if_called_plain && (
          <div style={ccStyles.section}>
            <div style={ccStyles.sectionLabel}>If your shares get called away</div>
            <div style={ccStyles.sectionText}>{data.if_called_plain}</div>
          </div>
        )}

        {data.if_not_called_plain && (
          <div style={ccStyles.section}>
            <div style={ccStyles.sectionLabel}>If shares stay below strike</div>
            <div style={ccStyles.sectionText}>{data.if_not_called_plain}</div>
          </div>
        )}

        {data.best_for && (
          <div style={ccStyles.bestFor(cfg)}>Best for: {data.best_for}</div>
        )}

        {data.thin_market_note && (
          <div style={ccStyles.thinWarning}>⚠ {data.thin_market_note}</div>
        )}

        {data.below_threshold && !data.thin_market_note && (
          <div style={ccStyles.thinWarning}>
            ⚠ Premium is below 0.3%/week — options are thin on {rawTier} strikes this week
          </div>
        )}
      </div>
    </div>
  )
}

function CoveredCallAnalyzer() {
  const [ticker, setTicker] = useState('')
  const [costBasis, setCostBasis] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)

  const generate = async (sym) => {
    const symbol = (sym || ticker).trim().toUpperCase()
    if (!symbol) return
    setTicker(symbol)
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const cb = costBasis ? parseFloat(costBasis) : null
      const data = await api.coveredCalls.analyze(symbol, cb)
      setResult(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const handleKey = (e) => {
    if (e.key === 'Enter') generate()
  }

  const tiers = result?.tiers ?? []
  const tierMap = {}
  tiers.forEach((t) => { tierMap[t.tier] = t })

  return (
    <div>
      <div style={ccStyles.header}>
        <div style={ccStyles.title}>Covered Call Income Generator</div>
        <div style={ccStyles.subtitle}>
          Own 100 shares? Generate three call strategies to earn income — works with weekly and monthly options.
        </div>
      </div>

      <div style={ccStyles.formRow}>
        <div style={ccStyles.inputGroup}>
          <div style={ccStyles.label}>Ticker</div>
          <input
            style={ccStyles.tickerInput}
            value={ticker}
            onChange={(e) => setTicker(e.target.value.toUpperCase())}
            onKeyDown={handleKey}
            placeholder="SCHD"
            maxLength={6}
          />
        </div>
        <div style={ccStyles.inputGroup}>
          <div style={ccStyles.label}>Cost Basis / share (optional)</div>
          <input
            style={ccStyles.costInput}
            type="number"
            step="0.01"
            min="0"
            value={costBasis}
            onChange={(e) => setCostBasis(e.target.value)}
            onKeyDown={handleKey}
            placeholder="e.g. 28.50"
          />
        </div>
        <button
          style={ccStyles.generateBtn(loading)}
          onClick={() => generate()}
          disabled={loading || !ticker.trim()}
        >
          {loading ? '⏳ Analyzing...' : '📊 Generate Calls'}
        </button>
      </div>

      <div style={ccStyles.quickRow}>
        {QUICK_TICKERS.map((sym) => (
          <button key={sym} style={ccStyles.chip} onClick={() => generate(sym)}>{sym}</button>
        ))}
      </div>
      <div style={ccStyles.hint}>Click a ticker above or type your own — works for stocks and ETFs</div>

      {error && <div style={ccStyles.error}>⚠ {error}</div>}

      {result && (
        <>
          {/* Meta bar */}
          <div style={ccStyles.metaBar}>
            <div style={ccStyles.metaItem}>
              <div style={ccStyles.metaLabel}>Ticker</div>
              <div style={ccStyles.metaValue}>{result.ticker}</div>
            </div>
            <div style={ccStyles.metaItem}>
              <div style={ccStyles.metaLabel}>Current Price</div>
              <div style={ccStyles.metaValue}>{ccFmt(result.current_price)}</div>
            </div>
            <div style={ccStyles.metaItem}>
              <div style={ccStyles.metaLabel}>Expiry</div>
              <div style={ccStyles.metaValue}>{result.expiry} ({result.dte}d)</div>
            </div>
            <div style={ccStyles.metaItem}>
              <div style={ccStyles.metaLabel}>Option Cycle</div>
              <div style={{
                ...ccStyles.metaValue,
                color: result.options_type === 'monthly' ? '#f6e05e' : '#68d391',
                fontSize: '13px',
                fontWeight: 700,
              }}>
                {result.options_type === 'monthly' ? '📅 Monthly' : '📆 Weekly'}
              </div>
            </div>
            <div style={ccStyles.metaItem}>
              <div style={ccStyles.metaLabel}>ATM IV</div>
              <div style={ccStyles.metaValue}>{result.atm_iv_pct ?? '—'}%</div>
            </div>
            {result.iv_rank?.iv_rank != null && (
              <div style={ccStyles.statPill}>
                <span style={ccStyles.statLabel}>IV Rank</span>
                <span style={{
                  ...ccStyles.statVal,
                  color: result.iv_rank.iv_rank >= 50 ? '#68d391' : result.iv_rank.iv_rank < 25 ? '#fc8181' : '#fbd38d'
                }}>
                  {result.iv_rank.iv_rank}
                  <span style={{ fontSize:'10px', color:'#718096', marginLeft:'3px' }}>/ 100</span>
                </span>
              </div>
            )}
            {result.iv_environment && (
              <div style={ccStyles.ivNote}>{result.iv_environment}</div>
            )}
          </div>

          {result.iv_rank?.label === 'high' && (
            <div style={{ fontSize:'12px', color:'#68d391', padding:'4px 0' }}>
              🔥 IV Rank {result.iv_rank.iv_rank} — premium is historically rich. Good time to sell calls.
            </div>
          )}
          {result.iv_rank?.label === 'low' && (
            <div style={{ fontSize:'12px', color:'#fc8181', padding:'4px 0' }}>
              ❄️ IV Rank {result.iv_rank.iv_rank} — premium is historically cheap. Consider waiting for higher IV.
            </div>
          )}

          {result.options_type === 'monthly' && (
            <div style={{ ...ccStyles.dataSourceNote, color: '#f6e05e', marginBottom: '8px' }}>
              📅 {result.ticker} uses monthly options — no weekly options are listed for this ticker.
              These strategies expire on {result.expiry}.
            </div>
          )}
          {result.data_source === 'last_trade' && (
            <div style={ccStyles.dataSourceNote}>
              ℹ Markets closed — using last-trade prices. Live bid/ask available during market hours.
            </div>
          )}
          {result.data_source === 'synthetic_bs' && (
            <div style={{ ...ccStyles.dataSourceNote, color: '#fbd38d', background: '#2d2000', border: '1px solid #b7791f', borderRadius: '6px', padding: '8px 12px' }}>
              🧮 Live options data unavailable — premiums are estimated using Black-Scholes with {result.atm_iv_pct}% historical volatility. Verify actual quotes with your broker before trading.
            </div>
          )}

          {/* Three tier cards */}
          <div style={ccStyles.tiersGrid}>
            {['aggressive', 'balanced', 'conservative'].map((tier) => (
              <TierCard
                key={tier}
                tier={tier}
                data={tierMap[tier]}
                cfg={TIER_CONFIG[tier]}
              />
            ))}
          </div>

          <div style={ccStyles.disclaimer}>
            AI analysis only — not financial advice. Verify strikes and premiums with your broker before trading.
          </div>
        </>
      )}

      <WeeklyScanner />
    </div>
  )
}

export default function WheelTab() {
  const [recs, setRecs] = useState([])
  const [positions, setPositions] = useState([])
  const [account, setAccount] = useState(null)
  const [loading, setLoading] = useState(true)
  const [loadingPositions, setLoadingPositions] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [error, setError] = useState(null)
  const [showClosed, setShowClosed] = useState(false)
  const [scannerData, setScannerData] = useState(null)
  const [scannerLoading, setScannerLoading] = useState(false)
  const [scannerRefreshing, setScannerRefreshing] = useState(false)
  const [showCallCandidates, setShowCallCandidates] = useState(false)
  const [showExcluded, setShowExcluded] = useState(false)

  const loadRecs = async () => {
    setLoading(true)
    try {
      const data = await api.wheel.getRecommendations()
      setRecs(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const loadScanner = async () => {
    setScannerLoading(true)
    try {
      const data = await api.wheel.getScannerCandidates()
      setScannerData(data)
    } catch (e) {
      // scanner cache miss is non-fatal
    } finally {
      setScannerLoading(false)
    }
  }

  const handleScannerRefresh = async () => {
    setScannerRefreshing(true)
    try {
      await api.wheel.refreshScanner()
      // Poll until results appear
      const poll = setInterval(async () => {
        const status = await api.wheel.getScannerStatus().catch(() => null)
        if (status && status.state !== 'running') {
          clearInterval(poll)
          setScannerRefreshing(false)
          loadScanner()
        }
      }, 3000)
      setTimeout(() => { clearInterval(poll); setScannerRefreshing(false) }, 120000)
    } catch (e) {
      setScannerRefreshing(false)
    }
  }

  const loadPositions = useCallback(async () => {
    setLoadingPositions(true)
    try {
      const data = await api.wheel.getPositions(showClosed)
      setPositions(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoadingPositions(false)
    }
  }, [showClosed])

  useEffect(() => { loadRecs() }, [])
  useEffect(() => { loadPositions() }, [loadPositions])
  useEffect(() => { api.account.getBalance().then(setAccount).catch(() => {}) }, [])
  useEffect(() => { loadScanner() }, [])

  const wheelFetchFn = useCallback(() => api.wheel.getRecommendations(), [])
  const { start: startPolling } = useRefreshPoller(
    wheelFetchFn,
    (data) => { setRecs(data) },
    setError,
    'wheel'
  )

  const handleRefresh = async () => {
    setRefreshing(true)
    try {
      await api.wheel.refresh()
      startPolling(recs[0]?.run_at, () => setRefreshing(false))
    } catch (e) {
      setError(e.message)
      setRefreshing(false)
    }
  }

  const handleExport = async () => {
    setExporting(true)
    try {
      const data = await api.wheel.exportPositions()
      const date = new Date().toISOString().slice(0, 10)
      downloadJson(data, `wheel-positions-${date}.json`)
    } catch (e) {
      setError(e.message)
    } finally {
      setExporting(false)
    }
  }

  const handleAccepted = (newPosition) => {
    setPositions((prev) => [newPosition, ...prev])
    setRecs((prev) =>
      prev.map((r) => (r.id === newPosition.recommendation_id ? { ...r, accepted: true } : r))
    )
  }

  const handlePositionUpdated = (updated) => {
    setPositions((prev) => prev.map((p) => (p.id === updated.id ? updated : p)))
  }

  const lastRunAt = recs[0]?.run_at
  const activePositions = positions.filter((p) => p.status !== 'closed')
  const closedPositions = positions.filter((p) => p.status === 'closed')

  return (
    <div>
      <AccountWidget showSizing />
      <WheelCustomAnalysis />

      <div style={s.header}>
        <div>
          <div style={s.title}>Wheel Strategy</div>
          <LastUpdated timestamp={lastRunAt} loading={loading} />
        </div>
        <div style={s.btnRow}>
          {positions.length > 0 && (
            <button style={s.exportBtn} onClick={handleExport} disabled={exporting} title="Download all positions as JSON backup">
              {exporting ? '⏳' : '⬇'} Backup Positions
            </button>
          )}
          <button style={s.refreshBtn} onClick={handleRefresh} disabled={refreshing}>
            {refreshing ? '⏳ Analyzing...' : '↻ Run Analysis'}
          </button>
        </div>
      </div>

      {error && <div style={s.error}>Error: {error}</div>}

      {/* Scanner candidates section */}
      <ScannerSection
        data={scannerData}
        loading={scannerLoading}
        refreshing={scannerRefreshing}
        onRefresh={handleScannerRefresh}
        showCallCandidates={showCallCandidates}
        setShowCallCandidates={setShowCallCandidates}
        showExcluded={showExcluded}
        setShowExcluded={setShowExcluded}
      />

      <hr style={s.divider} />

      {/* AI wheel recommendations */}
      <div style={s.sectionTitle}>
        <span>🎯</span> AI Put-Selling Candidates
      </div>

      {!loading && recs.length === 0 && !error && (
        <div style={s.empty}>
          No recommendations yet. Click "Run Analysis" to identify wheel candidates.
          <br />
          <small style={{ color: '#4a5568', marginTop: '8px', display: 'block' }}>
            Looks for high IV-rank stocks with strong support for cash-secured put selling
          </small>
        </div>
      )}

      <div style={s.grid}>
        {recs.map((rec) => (
          <WheelCard key={rec.id} rec={rec} account={account} onAccepted={handleAccepted} />
        ))}
      </div>

      <hr style={s.divider} />

      {/* Tracked positions */}
      <div style={{ ...s.sectionTitle, marginBottom: '8px' }}>
        <span>📊</span> Tracked Positions
        {activePositions.length > 0 && (
          <span style={{
            background: '#2d3748',
            color: '#a0aec0',
            borderRadius: '10px',
            padding: '1px 8px',
            fontSize: '11px',
          }}>
            {activePositions.length} active
          </span>
        )}
      </div>

      {!loadingPositions && activePositions.length === 0 && (
        <div style={s.empty}>
          No active positions. Accept a recommendation above to start tracking a wheel trade.
        </div>
      )}

      <div style={s.grid}>
        {activePositions.map((pos) => (
          <PositionTracker
            key={pos.id}
            position={pos}
            onUpdated={handlePositionUpdated}
          />
        ))}
      </div>

      {/* Closed positions toggle */}
      {closedPositions.length > 0 && (
        <button style={s.showClosedBtn} onClick={() => setShowClosed(!showClosed)}>
          {showClosed ? '▲ Hide' : '▼ Show'} {closedPositions.length} closed position{closedPositions.length !== 1 ? 's' : ''}
        </button>
      )}
      {showClosed && (
        <div style={{ ...s.grid, opacity: 0.6 }}>
          {closedPositions.map((pos) => (
            <PositionTracker
              key={pos.id}
              position={pos}
              onUpdated={handlePositionUpdated}
            />
          ))}
        </div>
      )}

      <hr style={s.divider} />

      {/* Covered Calls: income generator + weekly scanner */}
      <CoveredCallAnalyzer />
    </div>
  )
}
