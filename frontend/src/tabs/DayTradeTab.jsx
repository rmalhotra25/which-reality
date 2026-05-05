import { useState } from 'react'
import { api } from '../api'

const CONFIDENCE_COLORS = {
  high:   { bg: '#071a0a', border: '#276749', text: '#68d391', badge: '#0d2218' },
  medium: { bg: '#1a1400', border: '#b7791f', text: '#f6e05e', badge: '#2d2200' },
  low:    { bg: '#1a1209', border: '#744210', text: '#f6ad55', badge: '#2d1a09' },
}

const TIMEFRAME_COLORS = {
  intraday:  { bg: '#0a1220', border: '#2b6cb0', text: '#63b3ed' },
  'intraday (same day)': { bg: '#0a1220', border: '#2b6cb0', text: '#63b3ed' },
  swing:     { bg: '#1a0a1f', border: '#6b46c1', text: '#b794f4' },
  '2-3 day': { bg: '#1a0a1f', border: '#6b46c1', text: '#b794f4' },
  '2-3 day swing': { bg: '#1a0a1f', border: '#6b46c1', text: '#b794f4' },
}

function badge(label, colors) {
  return (
    <span style={{
      padding: '3px 10px', fontSize: '11px', fontWeight: 700,
      background: colors.bg ?? '#1a1f2e',
      border: `1px solid ${colors.border ?? '#2d3748'}`,
      color: colors.text ?? '#a0aec0',
      borderRadius: '20px', whiteSpace: 'nowrap',
    }}>
      {label}
    </span>
  )
}

const s = {
  header: { marginBottom: '24px' },
  title: { fontSize: '20px', fontWeight: 700, color: '#e2e8f0', marginBottom: '4px' },
  subtitle: { fontSize: '13px', color: '#718096' },

  toolbar: {
    display: 'flex', alignItems: 'center', gap: '12px',
    marginBottom: '20px', flexWrap: 'wrap',
  },
  scanBtn: (loading) => ({
    padding: '10px 24px',
    background: loading ? '#2d3748' : '#2b6cb0',
    color: loading ? '#718096' : '#fff',
    border: 'none', borderRadius: '8px',
    cursor: loading ? 'not-allowed' : 'pointer',
    fontSize: '14px', fontWeight: 700,
  }),
  dataNote: {
    fontSize: '11px', color: '#4a5568', fontStyle: 'italic',
  },
  scannedNote: { fontSize: '12px', color: '#718096' },

  error: {
    color: '#fc8181', background: '#2d1515',
    border: '1px solid #742a2a', borderRadius: '8px',
    padding: '14px 16px', fontSize: '14px', marginBottom: '20px',
  },

  emptyState: {
    background: '#131825', border: '1px solid #2d3748',
    borderRadius: '12px', padding: '48px',
    textAlign: 'center', color: '#718096', fontSize: '14px',
  },

  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))',
    gap: '16px',
  },

  card: (conf) => {
    const c = CONFIDENCE_COLORS[conf] ?? CONFIDENCE_COLORS.medium
    return {
      background: c.bg,
      border: `1px solid ${c.border}`,
      borderRadius: '12px', overflow: 'hidden',
    }
  },

  cardHeader: (conf) => {
    const c = CONFIDENCE_COLORS[conf] ?? CONFIDENCE_COLORS.medium
    return {
      background: c.badge,
      borderBottom: `1px solid ${c.border}`,
      padding: '14px 16px',
      display: 'flex', alignItems: 'center',
      justifyContent: 'space-between', gap: '10px',
    }
  },

  ticker: { fontSize: '26px', fontWeight: 900, color: '#e2e8f0' },
  badges: { display: 'flex', gap: '6px', flexWrap: 'wrap', alignItems: 'center' },

  cardBody: { padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px' },

  statsGrid: {
    display: 'grid', gridTemplateColumns: '1fr 1fr 1fr',
    gap: '8px',
  },
  statBox: {
    background: 'rgba(0,0,0,0.3)', borderRadius: '6px',
    padding: '8px 10px',
  },
  statLabel: {
    fontSize: '10px', color: '#718096',
    textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600,
  },
  statValue: (conf) => ({
    fontSize: '14px', fontWeight: 700, marginTop: '2px',
    color: CONFIDENCE_COLORS[conf]?.text ?? '#e2e8f0',
  }),

  rrBox: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    background: 'rgba(0,0,0,0.3)', borderRadius: '6px', padding: '8px 12px',
  },
  rrLabel: { fontSize: '11px', color: '#718096', fontWeight: 600 },
  rrValue: { fontSize: '16px', fontWeight: 800, color: '#e2e8f0' },

  catalystBox: {
    fontSize: '12px', color: '#90cdf4',
    background: 'rgba(43,108,176,0.08)',
    border: '1px solid rgba(43,108,176,0.2)',
    borderRadius: '6px', padding: '8px 10px', lineHeight: 1.5,
  },

  reasoning: {
    fontSize: '13px', color: '#a0aec0', lineHeight: 1.65,
  },

  disclaimer: { fontSize: '11px', color: '#4a5568', marginTop: '16px' },

  moversWrap: { marginTop: '28px' },
  moversTitle: {
    fontSize: '12px', color: '#4a5568', fontWeight: 600,
    textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '10px',
  },
  moversGrid: {
    display: 'flex', flexWrap: 'wrap', gap: '8px',
  },
  moverChip: (dir) => ({
    padding: '5px 12px', fontSize: '12px', fontWeight: 600,
    background: dir === 'up' ? '#071a0a' : '#1f0a0a',
    border: `1px solid ${dir === 'up' ? '#276749' : '#742a2a'}`,
    color: dir === 'up' ? '#68d391' : '#fc8181',
    borderRadius: '20px',
  }),
}

function PlayCard({ play }) {
  const conf = (play.confidence || 'medium').toLowerCase()
  const tf = (play.timeframe || '').toLowerCase()
  const tfColors = TIMEFRAME_COLORS[tf] ?? TIMEFRAME_COLORS.swing
  const dirLong = play.direction === 'long'

  return (
    <div style={s.card(conf)}>
      <div style={s.cardHeader(conf)}>
        <span style={s.ticker}>{play.ticker}</span>
        <div style={s.badges}>
          {badge(dirLong ? '▲ LONG' : '▼ SHORT', {
            bg: dirLong ? '#071a0a' : '#1f0a0a',
            border: dirLong ? '#276749' : '#742a2a',
            text: dirLong ? '#68d391' : '#fc8181',
          })}
          {badge(play.setup || 'Setup', {
            bg: CONFIDENCE_COLORS[conf].badge,
            border: CONFIDENCE_COLORS[conf].border,
            text: CONFIDENCE_COLORS[conf].text,
          })}
          {badge(tf || 'intraday', tfColors)}
        </div>
      </div>

      <div style={s.cardBody}>
        {/* Entry / Target / Stop */}
        <div style={s.statsGrid}>
          <div style={s.statBox}>
            <div style={s.statLabel}>Entry Zone</div>
            <div style={{ fontSize: '13px', fontWeight: 700, color: '#e2e8f0', marginTop: '2px' }}>
              {play.entry_zone || '—'}
            </div>
          </div>
          <div style={s.statBox}>
            <div style={s.statLabel}>Target</div>
            <div style={s.statValue(conf)}>{play.target || '—'}</div>
          </div>
          <div style={s.statBox}>
            <div style={s.statLabel}>Stop Loss</div>
            <div style={{ fontSize: '13px', fontWeight: 700, color: '#fc8181', marginTop: '2px' }}>
              {play.stop_loss || '—'}
            </div>
          </div>
        </div>

        {/* Risk/Reward */}
        {play.risk_reward && (
          <div style={s.rrBox}>
            <span style={s.rrLabel}>Risk / Reward</span>
            <span style={s.rrValue}>{play.risk_reward}</span>
          </div>
        )}

        {/* Catalyst */}
        {play.catalyst && (
          <div style={s.catalystBox}>
            ⚡ {play.catalyst}
          </div>
        )}

        {/* Reasoning */}
        {play.reasoning && (
          <div style={s.reasoning}>{play.reasoning}</div>
        )}
      </div>
    </div>
  )
}

export default function DayTradeTab() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)
  const [scannedAt, setScannedAt] = useState(null)

  const runScan = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.scanner.scan()
      setResult(data)
      setScannedAt(new Date())
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const plays = result?.plays ?? []
  const movers = result?.top_movers ?? []

  return (
    <div>
      <div style={s.header}>
        <div style={s.title}>⚡ Day Trade Scanner</div>
        <div style={s.subtitle}>
          Scans today's top movers and uses AI to surface the highest-confidence intraday and swing plays.
        </div>
      </div>

      <div style={s.toolbar}>
        <button style={s.scanBtn(loading)} onClick={runScan} disabled={loading}>
          {loading ? '⏳ Scanning movers…' : '⚡ Run Scan'}
        </button>
        {scannedAt && (
          <span style={s.scannedNote}>
            Last scan: {scannedAt.toLocaleTimeString()}
            {result?.candidates_scanned != null && ` · ${result.candidates_scanned} movers screened`}
          </span>
        )}
        {result?.data_note && (
          <span style={s.dataNote}>{result.data_note}</span>
        )}
      </div>

      {error && <div style={s.error}>⚠ {error}</div>}

      {!result && !loading && (
        <div style={s.emptyState}>
          Click <strong>Run Scan</strong> to scan today's top movers and find high-confidence plays.
          <br />
          <small style={{ color: '#4a5568', display: 'block', marginTop: '8px' }}>
            Best used during market hours (9:30am – 4pm ET). Data is 15-minute delayed on the free plan.
          </small>
        </div>
      )}

      {plays.length > 0 && (
        <>
          <div style={s.grid}>
            {plays.map((play, i) => (
              <PlayCard key={`${play.ticker}-${i}`} play={play} />
            ))}
          </div>

          <div style={s.disclaimer}>
            AI analysis only — not financial advice. Always verify entries with your broker and use your own risk management.
            Data is 15-minute delayed on the free Polygon.io plan.
          </div>
        </>
      )}

      {plays.length === 0 && result && !loading && (
        <div style={s.emptyState}>
          No high-confidence plays found in this scan.
          Try again during active market hours when volume is higher.
        </div>
      )}

      {movers.length > 0 && (
        <div style={s.moversWrap}>
          <div style={s.moversTitle}>All screened movers ({movers.length})</div>
          <div style={s.moversGrid}>
            {movers.map((m) => (
              <span key={m.ticker} style={s.moverChip(m.direction)}>
                {m.ticker} {m.change_pct >= 0 ? '+' : ''}{m.change_pct}%
                &nbsp;·&nbsp;{m.vol_ratio}x vol
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
