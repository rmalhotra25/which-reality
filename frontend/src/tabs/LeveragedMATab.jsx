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

function PositionBadge({ position }) {
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
      {isIn ? '▲ IN TQQQ' : '● IN CASH'}
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
    try {
      const res = await fetch(`${API}/api/leveraged-ma/run-daily`, { method: 'POST' })
      const data = await res.json()
      if (data.status === 'started') {
        setTimeout(() => { fetchSignals(); setTriggering(false) }, 9000)
      } else {
        setTriggering(false)
      }
    } catch { setTriggering(false) }
  }

  const signalsToday = signals?.filter(r => r.signal_today) ?? []
  const neverRun = signals?.some(r => r.never_run) ?? false

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
              <PositionBadge position={r.confirmed_position} />
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
                <td style={s.td}><PositionBadge position={r.confirmed_position} /></td>
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
                        <PositionBadge position={r.last_signal_side} />
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
  { asset_key: 'SPXL_SPY',   label: 'SPXL / SPY'   },
  { asset_key: 'SOXL_SOXX',  label: 'SOXL / SOXX'  },
  { asset_key: 'TNA_IWM',    label: 'TNA / IWM'    },
  { asset_key: 'UPRO_SPY',   label: 'UPRO / SPY'   },
]

function BacktestPanel() {
  const [assetKey, setAssetKey] = useState('TQQQ_QQQ')
  const [maPeriod, setMaPeriod] = useState(161)
  const [entryBuffer, setEntryBuffer] = useState(1.0)
  const [exitBuffer, setExitBuffer] = useState(-2.5)
  const [cashApy, setCashApy] = useState(4.5)
  const [apyMeta, setApyMeta] = useState(null)
  const [result, setResult] = useState(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState(null)

  // Fetch recommended APY on mount
  useEffect(() => {
    fetch(`${API}/api/leveraged-ma/cash-apy`)
      .then(r => r.json())
      .then(data => {
        setCashApy(data.apy_pct)
        setApyMeta(data)
      })
      .catch(() => {})
  }, [])

  const runBacktest = async () => {
    setRunning(true); setError(null); setResult(null)
    try {
      const p = new URLSearchParams({ asset_key: assetKey, ma_period: maPeriod, entry_buffer_pct: entryBuffer, exit_buffer_pct: exitBuffer, cash_apy_pct: cashApy })
      const res = await fetch(`${API}/api/leveraged-ma/backtest?${p}`)
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`)
      setResult(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setRunning(false)
    }
  }

  const inputStyle = { background: '#0f1117', border: '1px solid #2d3748', color: '#e2e8f0', padding: '6px 10px', borderRadius: 6, fontSize: 13, width: '100%' }
  const labelStyle = { fontSize: 11, color: '#718096', fontWeight: 600, marginBottom: 4, display: 'block', letterSpacing: '0.06em', textTransform: 'uppercase' }

  return (
    <div>
      <div style={s.infoBox}>
        <strong style={{ color: '#e2e8f0' }}>How it works:</strong> The underlying ETF (QQQ, SPY, etc.) must stay {'>'} entry buffer above its
        SMA for {' '}<strong>3 consecutive closes</strong> to trigger a buy into the leveraged ETF. It must stay {'<'} exit buffer below the SMA
        for 3 consecutive closes to exit. When out, capital earns the cash APY below.
        Returns use <em>actual</em> leveraged ETF closing prices — no simulated leverage.
      </div>

      <div style={{ ...s.card, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 16, marginBottom: 16 }}>
        <div>
          <label style={labelStyle}>Pair</label>
          <select style={inputStyle} value={assetKey} onChange={e => setAssetKey(e.target.value)}>
            {BACKTEST_PAIRS.map(p => <option key={p.asset_key} value={p.asset_key}>{p.label}</option>)}
          </select>
        </div>
        <div>
          <label style={labelStyle}>MA Period (days)</label>
          <input style={inputStyle} type="number" min={20} max={300} value={maPeriod} onChange={e => setMaPeriod(Number(e.target.value))} />
        </div>
        <div>
          <label style={labelStyle}>Entry Buffer %</label>
          <input style={inputStyle} type="number" min={0} max={10} step={0.5} value={entryBuffer} onChange={e => setEntryBuffer(Number(e.target.value))} />
        </div>
        <div>
          <label style={labelStyle}>Exit Buffer %</label>
          <input style={inputStyle} type="number" min={-15} max={0} step={0.5} value={exitBuffer} onChange={e => setExitBuffer(Number(e.target.value))} />
        </div>
        <div>
          <label style={labelStyle}>
            Cash APY %
            {apyMeta?.is_live && <span style={{ color: '#68d391', marginLeft: 6 }}>● live</span>}
          </label>
          <input style={inputStyle} type="number" min={0} max={20} step={0.1} value={cashApy} onChange={e => setCashApy(Number(e.target.value))} />
          {apyMeta && (
            <div style={{ fontSize: 10, color: '#4a5568', marginTop: 3 }}>{apyMeta.source}</div>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'flex-end' }}>
          <button onClick={runBacktest} disabled={running} style={{ ...s.runBtn, width: '100%', padding: '8px 14px' }}>
            {running ? 'Running…' : 'Run Backtest'}
          </button>
        </div>
      </div>

      {error && <div style={s.errorBox}>{error}</div>}
      {running && <div style={s.infoBox}><span style={s.spinner} /> Fetching ~12 years of history and simulating…</div>}
      {result && <BacktestResults result={result} />}
    </div>
  )
}

// ─── Backtest Results ─────────────────────────────────────────────────────────

function BacktestResults({ result }) {
  const [showSignals, setShowSignals] = useState(false)

  const tile = (label, value, color) => (
    <div style={{ background: '#0f1117', border: '1px solid #2d3748', borderRadius: 8, padding: '12px 16px', minWidth: 130 }}>
      <div style={{ fontSize: 10, color: '#718096', fontWeight: 600, letterSpacing: '0.06em', marginBottom: 5, textTransform: 'uppercase' }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 800, color: color || '#e2e8f0', fontVariantNumeric: 'tabular-nums' }}>{value ?? '—'}</div>
    </div>
  )

  const f = result.full_period
  const bnh = result.buy_hold
  const retColor = n => n == null ? '#e2e8f0' : n >= 0 ? '#68d391' : '#fc8181'

  return (
    <div>
      <div style={{ fontSize: 11, color: '#4a5568', marginBottom: 12 }}>
        {result.leveraged} / {result.underlying} · {result.ma_period}d SMA ·
        entry {result.entry_buffer_pct >= 0 ? '+' : ''}{result.entry_buffer_pct}% ·
        exit {result.exit_buffer_pct}% · cash {result.cash_apy_pct}% APY ·
        {result.data_start} → {result.data_end} ·
        {result.n_signals} signals ·
        {result.days_in_pct}% in / {result.days_out_pct}% cash
      </div>

      {/* Strategy vs Buy-and-Hold tiles */}
      <div style={{ display: 'flex', gap: 24, marginBottom: 20, flexWrap: 'wrap' }}>
        <div>
          <div style={s.sectionTitle}>Strategy (with confirmation + cash yield)</div>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            {tile('Total Return', f?.total_return_pct != null ? fmtPct(f.total_return_pct) : '—', retColor(f?.total_return_pct))}
            {tile('CAGR', f?.cagr_pct != null ? `${f.cagr_pct}%` : '—', retColor(f?.cagr_pct))}
            {tile('Max Drawdown', f?.max_drawdown_pct != null ? `-${f.max_drawdown_pct}%` : '—', '#fc8181')}
            {tile('Calmar', f?.calmar_ratio != null ? fmt(f.calmar_ratio) : '—')}
          </div>
        </div>
        <div>
          <div style={s.sectionTitle}>Buy &amp; Hold {result.leveraged}</div>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            {tile('Total Return', bnh?.total_return_pct != null ? fmtPct(bnh.total_return_pct) : '—', retColor(bnh?.total_return_pct))}
            {tile('CAGR', bnh?.cagr_pct != null ? `${bnh.cagr_pct}%` : '—', retColor(bnh?.cagr_pct))}
            {tile('Max Drawdown', bnh?.max_drawdown_pct != null ? `-${bnh.max_drawdown_pct}%` : '—', '#fc8181')}
            {tile('Calmar', bnh?.calmar_ratio != null ? fmt(bnh.calmar_ratio) : '—')}
          </div>
        </div>
      </div>

      {/* Equity Curve Chart */}
      {result.chart && <EquityCurveChart chart={result.chart} leveraged={result.leveraged} />}

      {/* Sub-period breakdown */}
      <div style={{ ...s.sectionTitle, marginTop: 24 }}>Sub-period Breakdown</div>
      <div style={{ overflowX: 'auto', marginBottom: 20 }}>
        <table style={s.table}>
          <thead>
            <tr>
              <th style={s.th}>Period</th>
              <th style={s.th}>Total Return</th>
              <th style={s.th}>Max Drawdown</th>
              <th style={s.th}>Calmar</th>
              <th style={s.th}>Days</th>
              <th style={s.th}>Note</th>
            </tr>
          </thead>
          <tbody>
            {result.sub_periods.map(p => (
              <tr key={p.period}>
                <td style={{ ...s.td, fontWeight: 600, color: '#e2e8f0' }}>{p.period}</td>
                <td style={{ ...s.td, color: retColor(p.total_return_pct), fontVariantNumeric: 'tabular-nums' }}>
                  {p.total_return_pct != null ? fmtPct(p.total_return_pct) : '—'}
                </td>
                <td style={{ ...s.td, color: p.max_drawdown_pct ? '#fc8181' : '#4a5568', fontVariantNumeric: 'tabular-nums' }}>
                  {p.max_drawdown_pct != null ? `-${p.max_drawdown_pct}%` : '—'}
                </td>
                <td style={s.td}>{p.calmar_ratio != null ? fmt(p.calmar_ratio) : '—'}</td>
                <td style={s.td}>{p.n_trading_days ?? '—'}</td>
                <td style={{ ...s.td, fontSize: 11, color: '#718096' }}>{p.note || ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Signal dates */}
      {result.signal_dates?.length > 0 && (
        <div>
          <button onClick={() => setShowSignals(v => !v)} style={s.refreshBtn}>
            {showSignals ? 'Hide' : 'Show'} Signal History ({result.signal_dates.length})
          </button>
          {showSignals && (
            <div style={{ maxHeight: 260, overflowY: 'auto', marginTop: 10 }}>
              <table style={s.table}>
                <thead><tr><th style={s.th}>Date</th><th style={s.th}>Position Change</th></tr></thead>
                <tbody>
                  {result.signal_dates.map((sd, i) => (
                    <tr key={i}>
                      <td style={s.td}>{sd.date}</td>
                      <td style={s.td}><PositionBadge position={sd.position} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Equity Curve Chart (inline SVG) ─────────────────────────────────────────

function EquityCurveChart({ chart, leveraged }) {
  const W = 700, H = 220, PAD = { top: 12, right: 12, bottom: 28, left: 52 }
  const iW = W - PAD.left - PAD.right
  const iH = H - PAD.top - PAD.bottom

  const strategy = chart.strategy
  const bnh      = chart.buy_hold
  const dates    = chart.dates
  const inPos    = chart.in_position
  const n        = strategy.length

  if (n < 2) return null

  const allVals = [...strategy, ...bnh]
  const minV = Math.min(...allVals)
  const maxV = Math.max(...allVals)
  const vRange = maxV - minV || 1

  const xScale = i => PAD.left + (i / (n - 1)) * iW
  const yScale = v => PAD.top + iH - ((v - minV) / vRange) * iH

  const toPath = arr => arr.map((v, i) => `${i === 0 ? 'M' : 'L'}${xScale(i).toFixed(1)},${yScale(v).toFixed(1)}`).join(' ')

  // Background bands: green when in position
  const bands = []
  let bandStart = null
  for (let i = 0; i < n; i++) {
    if (inPos[i] && bandStart === null) bandStart = i
    if (!inPos[i] && bandStart !== null) {
      bands.push([bandStart, i - 1])
      bandStart = null
    }
  }
  if (bandStart !== null) bands.push([bandStart, n - 1])

  // Y-axis ticks
  const tickCount = 4
  const yTicks = Array.from({ length: tickCount + 1 }, (_, i) => minV + (vRange / tickCount) * i)

  // X-axis labels (first/last/mid)
  const xLabels = [0, Math.floor(n / 2), n - 1].map(i => ({ i, label: dates[i]?.slice(0, 7) }))

  return (
    <div style={{ overflowX: 'auto', marginBottom: 16 }}>
      <div style={{ ...s.sectionTitle }}>Equity Curve (Strategy vs {leveraged} Buy &amp; Hold)</div>
      <svg width={W} height={H} style={{ display: 'block', maxWidth: '100%' }}>
        {/* IN-position background bands */}
        {bands.map(([s_, e_], idx) => (
          <rect
            key={idx}
            x={xScale(s_)} y={PAD.top}
            width={xScale(e_) - xScale(s_)} height={iH}
            fill="#68d391" fillOpacity={0.07}
          />
        ))}

        {/* Grid lines */}
        {yTicks.map((v, i) => (
          <line key={i} x1={PAD.left} x2={PAD.left + iW} y1={yScale(v)} y2={yScale(v)}
            stroke="#2d3748" strokeWidth={0.5} />
        ))}

        {/* BnH line (gray dashed) */}
        <path d={toPath(bnh)} fill="none" stroke="#718096" strokeWidth={1.2} strokeDasharray="4,3" />

        {/* Strategy line (blue) */}
        <path d={toPath(strategy)} fill="none" stroke="#63b3ed" strokeWidth={1.8} />

        {/* Y-axis labels */}
        {yTicks.map((v, i) => (
          <text key={i} x={PAD.left - 6} y={yScale(v) + 4} textAnchor="end"
            fontSize={9} fill="#718096" fontFamily="monospace">
            {v.toFixed(1)}x
          </text>
        ))}

        {/* X-axis labels */}
        {xLabels.map(({ i, label }) => (
          <text key={i} x={xScale(i)} y={H - 4} textAnchor="middle"
            fontSize={9} fill="#718096" fontFamily="monospace">
            {label}
          </text>
        ))}

        {/* Axes */}
        <line x1={PAD.left} x2={PAD.left} y1={PAD.top} y2={PAD.top + iH} stroke="#4a5568" />
        <line x1={PAD.left} x2={PAD.left + iW} y1={PAD.top + iH} y2={PAD.top + iH} stroke="#4a5568" />

        {/* Legend */}
        <line x1={PAD.left + 4} x2={PAD.left + 18} y1={PAD.top + 10} y2={PAD.top + 10} stroke="#63b3ed" strokeWidth={2} />
        <text x={PAD.left + 22} y={PAD.top + 14} fontSize={9} fill="#a0aec0" fontFamily="sans-serif">Strategy</text>
        <line x1={PAD.left + 75} x2={PAD.left + 89} y1={PAD.top + 10} y2={PAD.top + 10} stroke="#718096" strokeWidth={1.5} strokeDasharray="4,3" />
        <text x={PAD.left + 93} y={PAD.top + 14} fontSize={9} fill="#a0aec0" fontFamily="sans-serif">Buy &amp; Hold</text>
        <rect x={PAD.left + 170} y={PAD.top + 4} width={10} height={10} fill="#68d391" fillOpacity={0.25} />
        <text x={PAD.left + 184} y={PAD.top + 14} fontSize={9} fill="#a0aec0" fontFamily="sans-serif">In ETF</text>
      </svg>
    </div>
  )
}
