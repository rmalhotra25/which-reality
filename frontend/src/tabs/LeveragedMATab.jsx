import { useState, useEffect, useCallback, useRef } from 'react'

const API = import.meta.env.VITE_API_URL || ''
const REFRESH_MS = 5 * 60 * 1000  // 5-minute auto-refresh

const DIRECTION_META = {
  trend_follow:    { label: 'Trend Follow',    color: '#63b3ed', bg: '#1a2a3a' },
  mean_reversion:  { label: 'Mean Reversion',  color: '#f6ad55', bg: '#2a1f0f' },
}

const SIGNAL_COLORS = {
  'RISK-ON':       '#68d391',
  'RISK-OFF':      '#fc8181',
  'BUY SETUP':     '#68d391',
  'EXIT SETUP':    '#fc8181',
}

const BACKTEST_PAIRS = [
  { asset_key: 'TQQQ_QQQ',   label: 'TQQQ / QQQ' },
  { asset_key: 'SPXL_SPY',   label: 'SPXL / SPY' },
  { asset_key: 'SOXL_SOXX',  label: 'SOXL / SOXX' },
  { asset_key: 'TNA_IWM',    label: 'TNA / IWM' },
  { asset_key: 'UPRO_SPY',   label: 'UPRO / SPY' },
]

// ─── Styles ──────────────────────────────────────────────────────────────────

const s = {
  page: { maxWidth: 1100, margin: '0 auto' },
  header: { display: 'flex', alignItems: 'center', gap: 12, marginBottom: 24, flexWrap: 'wrap' },
  title: { fontSize: 22, fontWeight: 700, color: '#e2e8f0', margin: 0 },
  subtitle: { fontSize: 13, color: '#718096', marginTop: 2 },
  refreshBtn: {
    marginLeft: 'auto', padding: '6px 14px', background: '#2b6cb0', color: '#fff',
    border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 13, fontWeight: 600,
  },
  runBtn: {
    padding: '6px 14px', background: '#276749', color: '#fff',
    border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 13, fontWeight: 600,
  },
  section: { marginBottom: 32 },
  sectionTitle: { fontSize: 13, fontWeight: 700, color: '#a0aec0', letterSpacing: '0.08em', marginBottom: 12, textTransform: 'uppercase' },
  table: { width: '100%', borderCollapse: 'collapse', fontSize: 13 },
  th: { padding: '8px 10px', textAlign: 'left', color: '#718096', fontWeight: 600, borderBottom: '1px solid #2d3748', fontSize: 11, letterSpacing: '0.06em', textTransform: 'uppercase' },
  td: { padding: '10px 10px', borderBottom: '1px solid #1a202c', verticalAlign: 'middle' },
  badge: (color, bg) => ({
    display: 'inline-block', padding: '2px 8px', borderRadius: 4,
    fontSize: 11, fontWeight: 700, color, background: bg, letterSpacing: '0.05em',
  }),
  pill: (color) => ({
    display: 'inline-block', padding: '1px 7px', borderRadius: 3,
    fontSize: 11, fontWeight: 600, color, background: color + '22',
  }),
  crossingRow: { background: '#12201a' },
  card: { background: '#1a1f2e', border: '1px solid #2d3748', borderRadius: 8, padding: '16px 20px', marginBottom: 16 },
  errorBox: { background: '#2d1515', border: '1px solid #742a2a', borderRadius: 8, padding: 16, color: '#fc8181', marginBottom: 16 },
  infoBox: { background: '#1a1f2e', border: '1px solid #2d3748', borderRadius: 8, padding: 16, color: '#a0aec0', marginBottom: 16, fontSize: 13 },
  noData: { color: '#4a5568', fontStyle: 'italic', fontSize: 12 },
  spinner: {
    display: 'inline-block', width: 14, height: 14,
    border: '2px solid #2d3748', borderTopColor: '#63b3ed',
    borderRadius: '50%', animation: 'spin 0.8s linear infinite',
  },
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function fmt(n, decimals = 2) {
  if (n == null) return '—'
  return typeof n === 'number' ? n.toFixed(decimals) : n
}

function fmtPct(n) {
  if (n == null) return '—'
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(2)}%`
}

function fmtPrice(n) {
  if (n == null) return '—'
  return `$${n.toFixed(2)}`
}

function SideChip({ side }) {
  if (!side) return <span style={s.noData}>—</span>
  const color = side === 'above' ? '#68d391' : '#fc8181'
  return <span style={s.pill(color)}>{side.toUpperCase()}</span>
}

function SignalBadge({ label, today }) {
  if (!label) return <span style={s.noData}>—</span>
  const color = SIGNAL_COLORS[label] || '#a0aec0'
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
      <span style={s.badge(color, color + '22')}>{label}</span>
      {today && <span style={{ fontSize: 11, color: '#68d391', fontWeight: 700 }}>TODAY</span>}
    </span>
  )
}

function DistPill({ pct }) {
  if (pct == null) return <span style={s.noData}>—</span>
  const color = pct >= 0 ? '#68d391' : '#fc8181'
  return <span style={{ color, fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>{fmtPct(pct)}</span>
}

// ─── Main Tab ────────────────────────────────────────────────────────────────

export default function LeveragedMATab() {
  const [signals, setSignals] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [triggering, setTriggering] = useState(false)
  const [lastUpdated, setLastUpdated] = useState(null)
  const [activeSection, setActiveSection] = useState('dashboard')  // 'dashboard' | 'backtest'
  const timerRef = useRef(null)

  const fetchSignals = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/leveraged-ma/signals`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setSignals(data)
      setError(null)
      setLastUpdated(new Date())
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchSignals()
    timerRef.current = setInterval(fetchSignals, REFRESH_MS)
    return () => clearInterval(timerRef.current)
  }, [fetchSignals])

  const handleRefresh = useCallback(() => {
    setLoading(true)
    fetchSignals()
  }, [fetchSignals])

  const handleRunDaily = useCallback(async () => {
    setTriggering(true)
    try {
      const res = await fetch(`${API}/api/leveraged-ma/run-daily`, { method: 'POST' })
      const data = await res.json()
      if (data.status === 'started') {
        // Poll until the engine finishes (it's fast — just SMA math on 5 tickers)
        setTimeout(() => { fetchSignals(); setTriggering(false) }, 8000)
      } else {
        setTriggering(false)
      }
    } catch {
      setTriggering(false)
    }
  }, [fetchSignals])

  const crossingsToday = signals?.filter(r => r.crossed_today) ?? []
  const neverRun = signals?.some(r => r.never_run) ?? false

  return (
    <div style={s.page}>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>

      <div style={s.header}>
        <div>
          <h2 style={s.title}>Leveraged MA Signals</h2>
          <div style={s.subtitle}>
            200-day SMA crossings on underlying ETFs → trend-follow & mean-reversion signals for leveraged ETFs
          </div>
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
          {lastUpdated && (
            <span style={{ fontSize: 11, color: '#4a5568' }}>
              Updated {lastUpdated.toLocaleTimeString()}
            </span>
          )}
          <button style={s.runBtn} onClick={handleRunDaily} disabled={triggering}>
            {triggering ? 'Running…' : '▶ Run Signal Engine'}
          </button>
          <button style={s.refreshBtn} onClick={handleRefresh} disabled={loading}>
            {loading ? '…' : '↻ Refresh'}
          </button>
        </div>
      </div>

      {/* Section nav */}
      <div style={{ display: 'flex', gap: 2, marginBottom: 24, borderBottom: '1px solid #2d3748' }}>
        {[['dashboard', 'Live Dashboard'], ['backtest', 'Backtest']].map(([id, label]) => (
          <button
            key={id}
            onClick={() => setActiveSection(id)}
            style={{
              padding: '8px 16px', border: 'none', cursor: 'pointer', fontSize: 13, fontWeight: 600,
              background: 'none', borderBottom: activeSection === id ? '2px solid #63b3ed' : '2px solid transparent',
              color: activeSection === id ? '#63b3ed' : '#718096',
              marginBottom: -1,
            }}
          >{label}</button>
        ))}
      </div>

      {error && <div style={s.errorBox}>Error loading signals: {error}</div>}

      {activeSection === 'dashboard' && (
        <Dashboard
          signals={signals}
          loading={loading}
          crossingsToday={crossingsToday}
          neverRun={neverRun}
          onRunDaily={handleRunDaily}
          triggering={triggering}
        />
      )}

      {activeSection === 'backtest' && <BacktestPanel />}
    </div>
  )
}

// ─── Dashboard ────────────────────────────────────────────────────────────────

function Dashboard({ signals, loading, crossingsToday, neverRun, onRunDaily, triggering }) {
  if (loading && !signals) {
    return <div style={s.infoBox}><span style={s.spinner} /> Loading signals…</div>
  }

  if (neverRun || !signals?.length) {
    return (
      <div style={s.infoBox}>
        <div style={{ marginBottom: 8, fontWeight: 600 }}>Signal engine has not run yet.</div>
        <div style={{ marginBottom: 12, fontSize: 12 }}>
          Click "Run Signal Engine" to compute today's 200-day SMA crossings for all 5 pairs.
          After the first run, the scheduler fires daily at 17:00 ET (after market close).
        </div>
        <button style={s.runBtn} onClick={onRunDaily} disabled={triggering}>
          {triggering ? 'Running…' : '▶ Run Now'}
        </button>
      </div>
    )
  }

  return (
    <>
      {crossingsToday.length > 0 && (
        <div style={{ ...s.card, border: '1px solid #276749', background: '#071a0a', marginBottom: 24 }}>
          <div style={{ ...s.sectionTitle, color: '#68d391' }}>⚡ TODAY'S CROSSINGS ({crossingsToday.length})</div>
          {crossingsToday.map(r => (
            <CrossingAlert key={`${r.asset_key}_${r.direction}`} r={r} />
          ))}
        </div>
      )}

      <div style={s.section}>
        <div style={s.sectionTitle}>All Pairs — Live State</div>
        <div style={{ overflowX: 'auto' }}>
          <table style={s.table}>
            <thead>
              <tr>
                <th style={s.th}>Leveraged</th>
                <th style={s.th}>Underlying</th>
                <th style={s.th}>Direction</th>
                <th style={s.th}>Current Price</th>
                <th style={s.th}>200-Day SMA</th>
                <th style={s.th}>% from SMA</th>
                <th style={s.th}>Side</th>
                <th style={s.th}>Active Signal</th>
                <th style={s.th}>Last Cross</th>
              </tr>
            </thead>
            <tbody>
              {signals.map(r => {
                const meta = DIRECTION_META[r.direction] || {}
                const isCrossing = r.crossed_today
                return (
                  <tr
                    key={`${r.asset_key}_${r.direction}`}
                    style={isCrossing ? s.crossingRow : undefined}
                  >
                    <td style={s.td}>
                      <div style={{ fontWeight: 700, color: '#e2e8f0' }}>{r.leveraged}</div>
                      <div style={{ fontSize: 11, color: '#4a5568' }}>{r.leverage_multiple}x</div>
                    </td>
                    <td style={s.td}>
                      <div style={{ fontWeight: 600, color: '#a0aec0' }}>{r.underlying}</div>
                      {r.underlying_change_pct != null && (
                        <div style={{ fontSize: 11, color: r.underlying_change_pct >= 0 ? '#68d391' : '#fc8181' }}>
                          {fmtPct(r.underlying_change_pct)} today
                        </div>
                      )}
                    </td>
                    <td style={s.td}>
                      <span style={{ ...s.badge(meta.color || '#a0aec0', meta.bg || '#1a1f2e') }}>
                        {meta.label || r.direction}
                      </span>
                    </td>
                    <td style={{ ...s.td, fontVariantNumeric: 'tabular-nums' }}>
                      <div>{fmtPrice(r.live_underlying_price)}</div>
                      <div style={{ fontSize: 11, color: '#4a5568' }}>{r.underlying}</div>
                    </td>
                    <td style={{ ...s.td, fontVariantNumeric: 'tabular-nums' }}>
                      {r.sma ? fmtPrice(r.sma) : <span style={s.noData}>—</span>}
                    </td>
                    <td style={s.td}><DistPill pct={r.live_dist_pct} /></td>
                    <td style={s.td}><SideChip side={r.live_side || r.last_side} /></td>
                    <td style={s.td}>
                      <SignalBadge label={r.signal_label} today={r.crossed_today} />
                    </td>
                    <td style={s.td}>
                      {r.last_cross_at
                        ? <span style={{ fontSize: 11, color: '#718096' }}>{r.last_cross_at.slice(0, 10)}</span>
                        : <span style={s.noData}>—</span>
                      }
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div style={{ fontSize: 11, color: '#4a5568', marginTop: 8 }}>
        Live prices refresh every 5 minutes. SMA recomputes once daily via the signal engine (Mon–Fri at 17:00 ET).
        Crossings only flag when side changes vs. last daily close — not every day a ticker stays on one side.
      </div>
    </>
  )
}

function CrossingAlert({ r }) {
  const meta = DIRECTION_META[r.direction] || {}
  const signalColor = SIGNAL_COLORS[r.signal_label] || '#a0aec0'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 0', borderBottom: '1px solid #0f2a1a', flexWrap: 'wrap' }}>
      <span style={{ fontWeight: 700, color: '#e2e8f0', minWidth: 50 }}>{r.leveraged}</span>
      <span style={{ color: '#718096', fontSize: 12 }}>via {r.underlying}</span>
      <span style={{ ...s.badge(meta.color || '#a0aec0', meta.bg || '#1a1f2e') }}>{meta.label}</span>
      <span style={{ ...s.badge(signalColor, signalColor + '22'), fontSize: 13 }}>{r.signal_label}</span>
      {r.live_underlying_price && r.sma && (
        <span style={{ fontSize: 12, color: '#a0aec0' }}>
          {r.underlying} @ {fmtPrice(r.live_underlying_price)} vs SMA {fmtPrice(r.sma)} ({fmtPct(r.live_dist_pct)})
        </span>
      )}
    </div>
  )
}

// ─── Backtest Panel ───────────────────────────────────────────────────────────

function BacktestPanel() {
  const [assetKey, setAssetKey] = useState('TQQQ_QQQ')
  const [direction, setDirection] = useState('trend_follow')
  const [maPeriod, setMaPeriod] = useState(200)
  const [thresholdPct, setThresholdPct] = useState(0)
  const [result, setResult] = useState(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState(null)

  const runBacktest = async () => {
    setRunning(true)
    setError(null)
    setResult(null)
    try {
      const params = new URLSearchParams({
        asset_key: assetKey,
        direction,
        ma_period: maPeriod,
        threshold_pct: thresholdPct,
      })
      const res = await fetch(`${API}/api/leveraged-ma/backtest?${params}`)
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`)
      setResult(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setRunning(false)
    }
  }

  const inputStyle = {
    background: '#0f1117', border: '1px solid #2d3748', color: '#e2e8f0',
    padding: '6px 10px', borderRadius: 6, fontSize: 13, width: '100%',
  }
  const labelStyle = { fontSize: 11, color: '#718096', fontWeight: 600, marginBottom: 4, display: 'block', letterSpacing: '0.06em', textTransform: 'uppercase' }

  return (
    <div>
      <div style={s.infoBox}>
        <strong style={{ color: '#e2e8f0' }}>How it works:</strong> Signals come from the <em>underlying</em> ETF
        crossing its SMA. Returns are the <em>leveraged</em> ETF's actual closing prices — no simulated leverage applied.
        Sub-period breakdowns call out 2018 Q4, 2020, and 2022 specifically so a strategy that only looks good in a bull
        run is visible as such. ETFs launched circa 2010, so the 2007–2009 crisis period usually shows no data.
      </div>

      <div style={{ ...s.card, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 16 }}>
        <div>
          <label style={labelStyle}>Pair</label>
          <select style={inputStyle} value={assetKey} onChange={e => setAssetKey(e.target.value)}>
            {BACKTEST_PAIRS.map(p => <option key={p.asset_key} value={p.asset_key}>{p.label}</option>)}
          </select>
        </div>
        <div>
          <label style={labelStyle}>Direction</label>
          <select style={inputStyle} value={direction} onChange={e => setDirection(e.target.value)}>
            <option value="trend_follow">Trend Follow</option>
            <option value="mean_reversion">Mean Reversion</option>
          </select>
        </div>
        <div>
          <label style={labelStyle}>MA Period</label>
          <input style={inputStyle} type="number" min={20} max={300} value={maPeriod} onChange={e => setMaPeriod(Number(e.target.value))} />
        </div>
        <div>
          <label style={labelStyle}>Threshold %</label>
          <input style={inputStyle} type="number" min={-10} max={10} step={0.5} value={thresholdPct} onChange={e => setThresholdPct(Number(e.target.value))} />
        </div>
        <div style={{ display: 'flex', alignItems: 'flex-end' }}>
          <button
            onClick={runBacktest}
            disabled={running}
            style={{ ...s.runBtn, width: '100%', padding: '8px 14px' }}
          >
            {running ? 'Running…' : 'Run Backtest'}
          </button>
        </div>
      </div>

      {error && <div style={s.errorBox}>{error}</div>}
      {running && <div style={s.infoBox}><span style={s.spinner} /> Fetching ~12 years of history and computing signals…</div>}
      {result && <BacktestResults result={result} />}
    </div>
  )
}

function BacktestResults({ result }) {
  const [showTrades, setShowTrades] = useState(false)

  const statTile = (label, value, color) => (
    <div style={{ background: '#0f1117', border: '1px solid #2d3748', borderRadius: 8, padding: '12px 16px', minWidth: 120 }}>
      <div style={{ fontSize: 11, color: '#718096', fontWeight: 600, letterSpacing: '0.06em', marginBottom: 6, textTransform: 'uppercase' }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 800, color: color || '#e2e8f0', fontVariantNumeric: 'tabular-nums' }}>{value}</div>
    </div>
  )

  const fullColor = (result.full_period?.total_return_pct ?? 0) >= 0 ? '#68d391' : '#fc8181'

  return (
    <div style={s.section}>
      <div style={{ ...s.sectionTitle, marginTop: 8 }}>
        {result.leveraged} / {result.underlying} · {result.direction === 'trend_follow' ? 'Trend Follow' : 'Mean Reversion'} · {result.ma_period}-day SMA
        {result.threshold_pct !== 0 && ` · ${result.threshold_pct}% band`}
      </div>
      <div style={{ fontSize: 11, color: '#4a5568', marginBottom: 16 }}>
        Data: {result.data_start} → {result.data_end} · {result.total_crossings} crossings detected
      </div>

      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 24 }}>
        {statTile('Total Return', result.full_period?.total_return_pct != null ? fmtPct(result.full_period.total_return_pct) : '—', fullColor)}
        {statTile('Max Drawdown', result.full_period?.max_drawdown_pct != null ? `-${result.full_period.max_drawdown_pct.toFixed(1)}%` : '—', '#fc8181')}
        {statTile('Calmar Ratio', result.full_period?.calmar_ratio != null ? fmt(result.full_period.calmar_ratio) : '—')}
        {statTile('# Trades', result.full_period?.num_trades ?? 0)}
        {statTile('Win Rate', result.full_period?.win_rate_pct != null ? `${result.full_period.win_rate_pct}%` : '—')}
      </div>

      <div style={{ ...s.sectionTitle }}>Sub-period Breakdown</div>
      <div style={{ overflowX: 'auto', marginBottom: 24 }}>
        <table style={s.table}>
          <thead>
            <tr>
              <th style={s.th}>Period</th>
              <th style={s.th}>Total Return</th>
              <th style={s.th}>Max Drawdown</th>
              <th style={s.th}>Calmar</th>
              <th style={s.th}># Trades</th>
              <th style={s.th}>Win Rate</th>
              <th style={s.th}>Note</th>
            </tr>
          </thead>
          <tbody>
            {result.sub_periods.map(p => {
              const retColor = p.total_return_pct == null ? '#718096' : p.total_return_pct >= 0 ? '#68d391' : '#fc8181'
              return (
                <tr key={p.period}>
                  <td style={{ ...s.td, fontWeight: 600, color: '#e2e8f0' }}>{p.period}</td>
                  <td style={{ ...s.td, color: retColor, fontVariantNumeric: 'tabular-nums' }}>
                    {p.total_return_pct != null ? fmtPct(p.total_return_pct) : '—'}
                  </td>
                  <td style={{ ...s.td, color: p.max_drawdown_pct ? '#fc8181' : '#4a5568', fontVariantNumeric: 'tabular-nums' }}>
                    {p.max_drawdown_pct != null ? `-${p.max_drawdown_pct.toFixed(1)}%` : '—'}
                  </td>
                  <td style={{ ...s.td, fontVariantNumeric: 'tabular-nums' }}>{p.calmar_ratio != null ? fmt(p.calmar_ratio) : '—'}</td>
                  <td style={s.td}>{p.num_trades}</td>
                  <td style={s.td}>{p.win_rate_pct != null ? `${p.win_rate_pct}%` : '—'}</td>
                  <td style={{ ...s.td, fontSize: 11, color: '#718096' }}>{p.note || ''}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {result.trades?.length > 0 && (
        <div>
          <button
            onClick={() => setShowTrades(t => !t)}
            style={{ ...s.refreshBtn, marginBottom: 12 }}
          >
            {showTrades ? 'Hide' : 'Show'} All Trades ({result.trades.length})
          </button>
          {showTrades && (
            <div style={{ overflowX: 'auto', maxHeight: 400, overflowY: 'auto' }}>
              <table style={s.table}>
                <thead>
                  <tr>
                    <th style={s.th}>Entry Date</th>
                    <th style={s.th}>Exit Date</th>
                    <th style={s.th}>Entry Price</th>
                    <th style={s.th}>Exit Price</th>
                    <th style={s.th}>Return</th>
                    <th style={s.th}>Days Held</th>
                  </tr>
                </thead>
                <tbody>
                  {result.trades.map((t, i) => {
                    const color = t.return_pct >= 0 ? '#68d391' : '#fc8181'
                    return (
                      <tr key={i}>
                        <td style={s.td}>{t.entry_date}</td>
                        <td style={s.td}>
                          {t.exit_date}
                          {t.open_position && <span style={{ marginLeft: 4, fontSize: 10, color: '#f6ad55' }}>OPEN</span>}
                        </td>
                        <td style={{ ...s.td, fontVariantNumeric: 'tabular-nums' }}>{fmtPrice(t.entry_price)}</td>
                        <td style={{ ...s.td, fontVariantNumeric: 'tabular-nums' }}>{fmtPrice(t.exit_price)}</td>
                        <td style={{ ...s.td, color, fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>{fmtPct(t.return_pct)}</td>
                        <td style={s.td}>{t.days_held}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
