import { useState, useEffect, useCallback, useRef } from 'react'

const API = import.meta.env.VITE_API_URL || ''
const REFRESH_MS = 5 * 60 * 1000   // 5-minute live-price refresh

// ─── Styles ──────────────────────────────────────────────────────────────────

const s = {
  page:        { maxWidth: 1100, margin: '0 auto' },
  header:      { display: 'flex', alignItems: 'flex-start', gap: 12, marginBottom: 20, flexWrap: 'wrap' },
  title:       { fontSize: 22, fontWeight: 700, color: '#e2e8f0', margin: 0 },
  subtitle:    { fontSize: 13, color: '#718096', marginTop: 3 },
  paramRow:    { fontSize: 11, color: '#4a5568', marginTop: 4 },
  btnRow:      { marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center', flexShrink: 0 },
  refreshBtn:  { padding: '6px 14px', background: '#2b6cb0', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 13, fontWeight: 600 },
  runBtn:      { padding: '6px 14px', background: '#276749', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 13, fontWeight: 600 },
  tabBar:      { display: 'flex', gap: 2, marginBottom: 24, borderBottom: '1px solid #2d3748' },
  card:        { background: '#1a1f2e', border: '1px solid #2d3748', borderRadius: 8, padding: '16px 20px', marginBottom: 16 },
  alertCard:   { background: '#071a0a', border: '1px solid #276749', borderRadius: 8, padding: '14px 18px', marginBottom: 20 },
  errorBox:    { background: '#2d1515', border: '1px solid #742a2a', borderRadius: 8, padding: 14, color: '#fc8181', marginBottom: 16 },
  infoBox:     { background: '#1a1f2e', border: '1px solid #2d3748', borderRadius: 8, padding: 16, color: '#a0aec0', marginBottom: 16, fontSize: 13 },
  sectionTitle: { fontSize: 11, fontWeight: 700, color: '#a0aec0', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 10 },
  table:       { width: '100%', borderCollapse: 'collapse', fontSize: 13 },
  th:          { padding: '7px 10px', textAlign: 'left', color: '#718096', fontWeight: 600, borderBottom: '1px solid #2d3748', fontSize: 11, letterSpacing: '0.06em', textTransform: 'uppercase' },
  td:          { padding: '12px 10px', borderBottom: '1px solid #1a202c', verticalAlign: 'middle' },
  noData:      { color: '#4a5568', fontStyle: 'italic', fontSize: 12 },
  spinner:     { display: 'inline-block', width: 14, height: 14, border: '2px solid #2d3748', borderTopColor: '#63b3ed', borderRadius: '50%', animation: 'spin 0.8s linear infinite' },
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const fmt  = (n, d = 2) => n == null ? '—' : Number(n).toFixed(d)
const fmtPct = n => n == null ? '—' : `${n > 0 ? '+' : ''}${Number(n).toFixed(2)}%`
const fmtPrice = n => n == null ? '—' : `$${Number(n).toFixed(2)}`

function PositionBadge({ position, ticker }) {
  if (!position) return <span style={s.noData}>—</span>
  const isIn = position === 'in'
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5,
      padding: '3px 10px', borderRadius: 5, fontWeight: 700, fontSize: 12,
      background: isIn ? '#071a0a' : '#1a1010',
      color: isIn ? '#68d391' : '#fc8181',
      border: `1px solid ${isIn ? '#276749' : '#742a2a'}`,
    }}>
      {isIn ? `▲ IN ${ticker || 'ETF'}` : '● IN CASH'}
    </span>
  )
}

function TriggerPill({ trigger }) {
  if (!trigger) return <span style={s.noData}>—</span>
  const map = {
    buy_zone:  { label: 'BUY ZONE',  color: '#68d391', bg: '#07200d' },
    sell_zone: { label: 'SELL ZONE', color: '#fc8181', bg: '#200707' },
    neutral:   { label: 'NEUTRAL',   color: '#a0aec0', bg: '#1a202c' },
  }
  const m = map[trigger] || map.neutral
  return (
    <span style={{ padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 700, color: m.color, background: m.bg }}>
      {m.label}
    </span>
  )
}

function DistPill({ pct }) {
  if (pct == null) return <span style={s.noData}>—</span>
  const color = pct >= 0 ? '#68d391' : '#fc8181'
  return <span style={{ color, fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>{fmtPct(pct)}</span>
}

function PendingProgress({ signal, days, required }) {
  if (!signal) return <span style={{ color: '#4a5568', fontSize: 11 }}>No pending signal</span>
  const isBuy = signal === 'buy'
  const color = isBuy ? '#68d391' : '#fc8181'
  const pct = Math.min(100, (days / required) * 100)
  return (
    <div>
      <div style={{ fontSize: 11, color, fontWeight: 600, marginBottom: 4 }}>
        {isBuy ? '🔼 BUY building' : '🔽 SELL building'} — {days}/{required} days
      </div>
      <div style={{ height: 4, background: '#2d3748', borderRadius: 2, width: 80 }}>
        <div style={{ height: '100%', borderRadius: 2, background: color, width: `${pct}%`, transition: 'width 0.3s' }} />
      </div>
    </div>
  )
}

// ─── Main Tab ────────────────────────────────────────────────────────────────

export default function LeveragedMATab() {
  const [signals, setSignals] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [triggering, setTriggering] = useState(false)
  const [lastUpdated, setLastUpdated] = useState(null)
  const [activeSection, setActiveSection] = useState('dashboard')
  const timerRef = useRef(null)

  const fetchSignals = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/leveraged-ma/signals`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setSignals(await res.json())
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

  const handleRefresh = () => { setLoading(true); fetchSignals() }

  const handleRunDaily = async () => {
    setTriggering(true)
    setError(null)
    try {
      const res = await fetch(`${API}/api/leveraged-ma/run-daily`, { method: 'POST' })
      const data = await res.json()
      if (data.status === 'already_running') {
        setError('Engine is already running — refreshing in 15 seconds.')
        setTimeout(() => { fetchSignals(); setTriggering(false) }, 15000)
        return
      }
      // Poll /run-daily/status until the thread finishes
      const poll = async (attempts = 0) => {
        if (attempts > 20) { setError('Engine timed out — check Render logs.'); setTriggering(false); return }
        try {
          const s = await fetch(`${API}/api/leveraged-ma/run-daily/status`)
          const st = await s.json()
          if (st.running) { setTimeout(() => poll(attempts + 1), 2000); return }
          if (st.error) setError(`Signal engine error: ${st.error}`)
          await fetchSignals()
        } catch { await fetchSignals() }
        setTriggering(false)
      }
      setTimeout(() => poll(), 2000)
    } catch (e) {
      setError(`Failed to start engine: ${e.message}`)
      setTriggering(false)
    }
  }

  const signalsToday = signals?.filter(r => r.signal_today) ?? []
  // Only block the whole table if ALL pairs have never run
  const neverRun = signals?.length > 0 && signals.every(r => r.never_run)

  return (
    <div style={s.page}>
      <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>

      <div style={s.header}>
        <div>
          <h2 style={s.title}>Leveraged MA Signals</h2>
          <div style={s.subtitle}>161-day SMA crossover · {'>'}+1% entry buffer · {'<'}−2.5% exit buffer · 3-day confirmation</div>
          <div style={s.paramRow}>
            Signal fires only when underlying stays in trigger zone for 3 consecutive closes.
            Capital earns T-bill yield (SGOV) when out of the leveraged ETF.
          </div>
        </div>
        <div style={s.btnRow}>
          {lastUpdated && <span style={{ fontSize: 11, color: '#4a5568' }}>Updated {lastUpdated.toLocaleTimeString()}</span>}
          <button style={s.runBtn} onClick={handleRunDaily} disabled={triggering}>
            {triggering ? 'Running…' : '▶ Run Signal Engine'}
          </button>
          <button style={s.refreshBtn} onClick={handleRefresh} disabled={loading}>
            {loading ? '…' : '↻ Refresh'}
          </button>
        </div>
      </div>

      <div style={s.tabBar}>
        {[['dashboard', 'Live Dashboard'], ['backtest', 'Backtest']].map(([id, label]) => (
          <button key={id} onClick={() => setActiveSection(id)} style={{
            padding: '8px 16px', border: 'none', cursor: 'pointer', fontSize: 13, fontWeight: 600,
            background: 'none', borderBottom: activeSection === id ? '2px solid #63b3ed' : '2px solid transparent',
            color: activeSection === id ? '#63b3ed' : '#718096', marginBottom: -1,
          }}>{label}</button>
        ))}
      </div>

      {error && <div style={s.errorBox}>Error: {error}</div>}

      {activeSection === 'dashboard' && (
        <Dashboard
          signals={signals}
          loading={loading}
          signalsToday={signalsToday}
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

function Dashboard({ signals, loading, signalsToday, neverRun, onRunDaily, triggering }) {
  if (loading && !signals) {
    return <div style={s.infoBox}><span style={s.spinner} /> Loading signals…</div>
  }
  if (neverRun || !signals?.length) {
    return (
      <div style={s.infoBox}>
        <div style={{ marginBottom: 8, fontWeight: 600, color: '#e2e8f0' }}>Signal engine has not run yet.</div>
        <div style={{ marginBottom: 12, fontSize: 12 }}>
          Click "Run Signal Engine" to compute the first 161-day SMA crossing check for all 5 pairs.
          After that, the scheduler fires automatically Mon–Fri at 17:00 ET.
        </div>
        <button style={s.runBtn} onClick={onRunDaily} disabled={triggering}>
          {triggering ? 'Running…' : '▶ Run Now'}
        </button>
      </div>
    )
  }

  return (
    <>
      {signalsToday.length > 0 && (
        <div style={s.alertCard}>
          <div style={{ ...s.sectionTitle, color: '#68d391' }}>⚡ SIGNAL FIRED TODAY ({signalsToday.length})</div>
          {signalsToday.map(r => (
            <div key={r.asset_key} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 0', flexWrap: 'wrap' }}>
              <span style={{ fontWeight: 700, color: '#e2e8f0' }}>{r.leveraged}</span>
              <span style={{ color: '#718096', fontSize: 12 }}>via {r.underlying}</span>
              <PositionBadge position={r.confirmed_position} ticker={r.leveraged} />
              {r.live_dist_pct != null && (
                <span style={{ fontSize: 12, color: '#a0aec0' }}>
                  {r.underlying} {fmtPct(r.live_dist_pct)} from SMA
                </span>
              )}
            </div>
          ))}
        </div>
      )}

      <div style={{ overflowX: 'auto' }}>
        <table style={s.table}>
          <thead>
            <tr>
              <th style={s.th}>Pair</th>
              <th style={s.th}>Position</th>
              <th style={s.th}>Live Trigger Zone</th>
              <th style={s.th}>% from SMA</th>
              <th style={s.th}>Underlying Price</th>
              <th style={s.th}>161-Day SMA</th>
              <th style={s.th}>Pending Signal</th>
              <th style={s.th}>Last Signal</th>
            </tr>
          </thead>
          <tbody>
            {signals.map(r => (
              <tr key={r.asset_key} style={r.signal_today ? { background: '#0d1a10' } : undefined}>
                <td style={s.td}>
                  <div style={{ fontWeight: 700, color: '#e2e8f0' }}>{r.leveraged}</div>
                  <div style={{ fontSize: 11, color: '#718096' }}>{r.underlying} · {r.ma_period}d SMA · {r.leverage_multiple}x</div>
                </td>
                <td style={s.td}><PositionBadge position={r.confirmed_position} ticker={r.leveraged} /></td>
                <td style={s.td}><TriggerPill trigger={r.live_trigger} /></td>
                <td style={s.td}><DistPill pct={r.live_dist_pct} /></td>
                <td style={{ ...s.td, fontVariantNumeric: 'tabular-nums' }}>
                  <div>{fmtPrice(r.live_underlying_price)}</div>
                  {r.underlying_change_pct != null && (
                    <div style={{ fontSize: 11, color: r.underlying_change_pct >= 0 ? '#68d391' : '#fc8181' }}>
                      {fmtPct(r.underlying_change_pct)} today
                    </div>
                  )}
                </td>
                <td style={{ ...s.td, fontVariantNumeric: 'tabular-nums', color: '#a0aec0' }}>
                  {r.sma ? fmtPrice(r.sma) : <span style={s.noData}>—</span>}
                </td>
                <td style={s.td}>
                  <PendingProgress
                    signal={r.pending_signal}
                    days={r.pending_days}
                    required={r.confirmation_days_required}
                  />
                </td>
                <td style={s.td}>
                  {r.last_signal_date
                    ? <div>
                        <div style={{ fontSize: 11, color: '#718096' }}>{r.last_signal_date.slice(0, 10)}</div>
                        <PositionBadge position={r.last_signal_side} ticker={r.leveraged} />
                      </div>
                    : <span style={s.noData}>—</span>
                  }
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div style={{ fontSize: 11, color: '#4a5568', marginTop: 10 }}>
        Live prices refresh every 5 minutes. SMA and position state update once daily (Mon–Fri 17:00 ET after close).
        Entry: {'>'}+1% above SMA for 3 consecutive days. Exit: {'<'}−2.5% below SMA for 3 consecutive days.
      </div>
    </>
  )
}

// ─── Backtest Panel ───────────────────────────────────────────────────────────

const BACKTEST_PAIRS = [
  { asset_key: 'TQQQ_QQQ',   label: 'TQQQ / QQQ'  },
  { asset_key: 'SPXL_SPY',   label: 'SPXL / SPY'  },
  { asset_key: 'SOXL_SOXX',  label: 'SOXL / SOXX' },
  { asset_key: 'TNA_IWM',    label: 'TNA / IWM'   },
  { asset_key: 'UPRO_SPY',   label: 'UPRO / SPY'  },
]

function BacktestPanel() {
  const [pair, setPair]         = useState('TQQQ_QQQ')
  const [maPeriod, setMaPeriod] = useState(161)
  const [entryBuf, setEntryBuf] = useState(1.0)
  const [exitBuf, setExitBuf]   = useState(-2.5)
  const [cashApy, setCashApy]   = useState(null)   // null = loading from /cash-apy
  const [cashApyLive, setCashApyLive] = useState(false)
  const [cashApyLabel, setCashApyLabel] = useState('')
  const [result, setResult]     = useState(null)
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState(null)

  // Pre-populate cash APY from live endpoint
  useEffect(() => {
    fetch(`${API}/api/leveraged-ma/cash-apy`)
      .then(r => r.json())
      .then(d => {
        setCashApy(d.apy_pct ?? 4.5)
        setCashApyLive(d.is_live ?? false)
        setCashApyLabel(d.source ?? '')
      })
      .catch(() => setCashApy(4.5))
  }, [])

  const run = async () => {
    setLoading(true); setError(null); setResult(null)
    try {
      const params = new URLSearchParams({
        asset_key: pair,
        ma_period: maPeriod,
        entry_buffer_pct: entryBuf,
        exit_buffer_pct: exitBuf,
        cash_apy_pct: cashApy ?? 4.5,
      })
      const res = await fetch(`${API}/api/leveraged-ma/backtest?${params}`)
      if (!res.ok) { const d = await res.json(); throw new Error(d.detail || `HTTP ${res.status}`) }
      setResult(await res.json())
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }

  const inputStyle = { background: '#1a1f2e', border: '1px solid #2d3748', borderRadius: 4, color: '#e2e8f0', padding: '5px 8px', fontSize: 13, width: 80 }
  const labelStyle = { fontSize: 11, color: '#718096', marginBottom: 3 }

  return (
    <div>
      {/* Controls */}
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'flex-end', marginBottom: 20 }}>
        <div>
          <div style={labelStyle}>Pair</div>
          <select value={pair} onChange={e => setPair(e.target.value)}
            style={{ ...inputStyle, width: 'auto' }}>
            {BACKTEST_PAIRS.map(p => <option key={p.asset_key} value={p.asset_key}>{p.label}</option>)}
          </select>
        </div>
        <div>
          <div style={labelStyle}>SMA Period</div>
          <input type="number" value={maPeriod} onChange={e => setMaPeriod(+e.target.value)} style={inputStyle} min={20} max={300} />
        </div>
        <div>
          <div style={labelStyle}>Entry Buffer %</div>
          <input type="number" value={entryBuf} onChange={e => setEntryBuf(+e.target.value)} style={inputStyle} step={0.1} />
        </div>
        <div>
          <div style={labelStyle}>Exit Buffer %</div>
          <input type="number" value={exitBuf} onChange={e => setExitBuf(+e.target.value)} style={inputStyle} step={0.1} />
        </div>
        <div>
          <div style={labelStyle}>
            Cash APY %{' '}
            {cashApyLive
              ? <span style={{ color: '#68d391', fontSize: 10 }}>● live ({cashApyLabel})</span>
              : <span style={{ color: '#718096', fontSize: 10 }}>○ fallback</span>
            }
          </div>
          <input type="number" value={cashApy ?? ''} onChange={e => setCashApy(+e.target.value)} style={inputStyle} step={0.1} min={0} max={20} />
        </div>
        <button onClick={run} disabled={loading || cashApy === null}
          style={{ padding: '6px 18px', background: '#2b6cb0', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 13, fontWeight: 600 }}>
          {loading ? 'Running…' : '▶ Run Backtest'}
        </button>
      </div>

      {error && <div style={s.errorBox}>{error}</div>}
      {loading && <div style={s.infoBox}><span style={s.spinner} /> Running backtest…</div>}

      {result && <BacktestResult r={result} />}
    </div>
  )
}

function StatBox({ label, value, sub, highlight }) {
  return (
    <div style={{ background: '#1a1f2e', border: `1px solid ${highlight ? '#276749' : '#2d3748'}`, borderRadius: 8, padding: '12px 16px', minWidth: 120 }}>
      <div style={{ fontSize: 11, color: '#718096', marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 700, color: highlight ? '#68d391' : '#e2e8f0', fontVariantNumeric: 'tabular-nums' }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: '#4a5568', marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

function BacktestResult({ r }) {
  const fp = r.full_period || {}
  const bh = r.buy_hold || {}
  const chart = r.chart || {}

  // Build inline SVG equity curve
  const dates   = chart.dates   || []
  const strat   = chart.strategy || []
  const bnh     = chart.buy_hold || []
  const inPos   = chart.in_position || []

  const W = 700, H = 180, PAD = { t: 10, r: 10, b: 24, l: 44 }
  const IW = W - PAD.l - PAD.r
  const IH = H - PAD.t - PAD.b

  const allVals = [...strat, ...bnh].filter(Boolean)
  const minV = Math.min(...allVals) * 0.98
  const maxV = Math.max(...allVals) * 1.02
  const n = strat.length

  const px = i => PAD.l + (i / (n - 1)) * IW
  const py = v => PAD.t + IH - ((v - minV) / (maxV - minV)) * IH

  // Green bands for IN position
  const bands = []
  let bandStart = null
  for (let i = 0; i < inPos.length; i++) {
    if (inPos[i] && bandStart === null) bandStart = i
    if (!inPos[i] && bandStart !== null) {
      bands.push([bandStart, i - 1]); bandStart = null
    }
  }
  if (bandStart !== null) bands.push([bandStart, inPos.length - 1])

  const polyline = pts => pts.map(([x, y]) => `${x},${y}`).join(' ')
  const stratPts = strat.map((v, i) => [px(i), py(v)])
  const bnhPts   = bnh.map((v, i) => [px(i), py(v)])

  // X-axis year labels
  const yearLabels = []
  let lastYear = null
  dates.forEach((d, i) => {
    const yr = d?.slice(0, 4)
    if (yr && yr !== lastYear) { yearLabels.push({ i, yr }); lastYear = yr }
  })

  const yTicks = [minV, (minV + maxV) / 2, maxV].map(v => ({ v, y: py(v), label: `${((v - 1) * 100).toFixed(0)}%` }))

  return (
    <div>
      {/* Summary stats */}
      <div style={{ ...s.sectionTitle, marginBottom: 12 }}>Full Period ({fp.data_start} → {fp.data_end})</div>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 20 }}>
        <StatBox label="Strategy Return" value={fp.total_return_pct != null ? `${fp.total_return_pct > 0 ? '+' : ''}${fp.total_return_pct}%` : '—'} highlight />
        <StatBox label="Buy & Hold Return" value={bh.total_return_pct != null ? `${bh.total_return_pct > 0 ? '+' : ''}${bh.total_return_pct}%` : '—'} />
        <StatBox label="Strategy CAGR" value={fp.cagr_pct != null ? `${fp.cagr_pct}%` : '—'} />
        <StatBox label="B&H CAGR" value={bh.cagr_pct != null ? `${bh.cagr_pct}%` : '—'} />
        <StatBox label="Max Drawdown" value={fp.max_drawdown_pct != null ? `-${fp.max_drawdown_pct}%` : '—'} />
        <StatBox label="Calmar Ratio" value={fp.calmar_ratio ?? '—'} />
        <StatBox label="Days IN" value={r.days_in_pct != null ? `${r.days_in_pct}%` : '—'} sub={`${r.n_signals} signals`} />
        <StatBox label="Cash APY" value={`${r.cash_apy_pct}%`} sub="when OUT" />
      </div>

      {/* Equity curve SVG */}
      {n > 1 && (
        <div style={{ marginBottom: 20, overflowX: 'auto' }}>
          <svg width={W} height={H} style={{ display: 'block', background: '#111620', borderRadius: 6 }}>
            {/* IN bands */}
            {bands.map(([a, b], idx) => (
              <rect key={idx}
                x={px(a)} y={PAD.t} width={px(b) - px(a)} height={IH}
                fill="#071a0a" opacity={0.6} />
            ))}
            {/* Grid */}
            {yTicks.map(({ y, label }, i) => (
              <g key={i}>
                <line x1={PAD.l} y1={y} x2={W - PAD.r} y2={y} stroke="#1e2435" strokeWidth={1} />
                <text x={PAD.l - 4} y={y + 4} textAnchor="end" fontSize={9} fill="#4a5568">{label}</text>
              </g>
            ))}
            {/* B&H line (gray dashed) */}
            <polyline points={polyline(bnhPts)} fill="none" stroke="#4a5568" strokeWidth={1.5} strokeDasharray="4,3" />
            {/* Strategy line (blue) */}
            <polyline points={polyline(stratPts)} fill="none" stroke="#63b3ed" strokeWidth={2} />
            {/* X-axis year labels */}
            {yearLabels.slice(0, 10).map(({ i, yr }) => (
              <text key={yr} x={px(i)} y={H - 4} textAnchor="middle" fontSize={9} fill="#4a5568">{yr}</text>
            ))}
            {/* Legend */}
            <line x1={W - 120} y1={16} x2={W - 105} y2={16} stroke="#63b3ed" strokeWidth={2} />
            <text x={W - 102} y={20} fontSize={9} fill="#a0aec0">Strategy</text>
            <line x1={W - 60} y1={16} x2={W - 45} y2={16} stroke="#4a5568" strokeWidth={1.5} strokeDasharray="4,3" />
            <text x={W - 42} y={20} fontSize={9} fill="#a0aec0">B&H</text>
          </svg>
          <div style={{ fontSize: 10, color: '#4a5568', marginTop: 4 }}>Green bands = IN leveraged ETF. Dashed = Buy & Hold underlying.</div>
        </div>
      )}

      {/* Sub-periods */}
      <div style={s.sectionTitle}>Stress-Test Periods</div>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 16 }}>
        {(r.sub_periods || []).map((sp, i) => (
          <div key={i} style={{ background: '#1a1f2e', border: '1px solid #2d3748', borderRadius: 8, padding: '12px 16px', minWidth: 180 }}>
            <div style={{ fontSize: 11, color: '#a0aec0', fontWeight: 700, marginBottom: 8 }}>{sp.period}</div>
            {sp.note
              ? <div style={{ fontSize: 11, color: '#4a5568', fontStyle: 'italic' }}>{sp.note}</div>
              : <>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 4 }}>
                    <span style={{ color: '#718096' }}>Strategy</span>
                    <span style={{ fontWeight: 700, color: sp.total_return_pct >= 0 ? '#68d391' : '#fc8181' }}>
                      {sp.total_return_pct > 0 ? '+' : ''}{sp.total_return_pct}%
                    </span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
                    <span style={{ color: '#718096' }}>Buy & Hold</span>
                    <span style={{ fontWeight: 700, color: '#a0aec0' }}>
                      {bh.total_return_pct > 0 ? '+' : ''}{sp.total_return_pct}%
                    </span>
                  </div>
                  {sp.max_drawdown_pct != null && (
                    <div style={{ fontSize: 10, color: '#4a5568', marginTop: 6 }}>Max DD: -{sp.max_drawdown_pct}%</div>
                  )}
                </>
            }
          </div>
        ))}
      </div>
    </div>
  )
}
