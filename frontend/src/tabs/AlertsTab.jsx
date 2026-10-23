import { useState, useEffect } from 'react'
import { api } from '../api'

// ── Styles ──────────────────────────────────────────────────────────────────

const S = {
  root: { display: 'flex', flexDirection: 'column', gap: '24px' },
  row: { display: 'flex', gap: '16px', flexWrap: 'wrap', alignItems: 'flex-start' },
  section: { display: 'flex', flexDirection: 'column', gap: '12px' },
  sectionLabel: {
    fontSize: '11px', fontWeight: 700, letterSpacing: '0.08em',
    color: '#718096', textTransform: 'uppercase', marginBottom: '2px',
  },
  card: (accent) => ({
    background: '#131825',
    border: `1px solid ${accent || '#2d3748'}`,
    borderRadius: '10px',
    padding: '14px 16px',
  }),
  tickerBig: {
    fontSize: '18px', fontWeight: 800, color: '#e2e8f0', letterSpacing: '-0.5px',
  },
  setupName: { fontSize: '12px', color: '#718096', marginTop: '1px' },
  summary: { fontSize: '13px', color: '#a0aec0', marginTop: '8px', lineHeight: 1.5 },
  pill: (bg, border, text) => ({
    display: 'inline-block', padding: '2px 9px', borderRadius: '20px', fontSize: '10px',
    fontWeight: 700, letterSpacing: '0.05em',
    background: bg, border: `1px solid ${border}`, color: text,
  }),
  metaRow: {
    display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center', marginTop: '8px',
  },
  stat: {
    display: 'flex', flexDirection: 'column', gap: '2px',
  },
  statLabel: { fontSize: '10px', color: '#4a5568', textTransform: 'uppercase', letterSpacing: '0.06em' },
  statValue: { fontSize: '15px', fontWeight: 700, color: '#e2e8f0' },
  empty: {
    background: '#131825', border: '1px solid #2d3748', borderRadius: '10px',
    padding: '32px', textAlign: 'center', color: '#718096', fontSize: '14px',
  },
  tableWrap: { overflowX: 'auto' },
  table: {
    width: '100%', borderCollapse: 'collapse', fontSize: '12px',
  },
  th: {
    padding: '8px 10px', textAlign: 'left', color: '#4a5568', fontWeight: 600,
    borderBottom: '1px solid #1e2535', whiteSpace: 'nowrap',
    textTransform: 'uppercase', fontSize: '10px', letterSpacing: '0.06em',
  },
  td: {
    padding: '8px 10px', borderBottom: '1px solid #1a1f2e', color: '#a0aec0',
    verticalAlign: 'top',
  },
  error: {
    background: '#2d1515', border: '1px solid #742a2a', borderRadius: '10px',
    padding: '16px', color: '#fc8181', fontSize: '13px',
  },
  runMeta: {
    background: '#0f1520', border: '1px solid #1e2535', borderRadius: '8px',
    padding: '10px 14px', fontSize: '11px', color: '#4a5568',
    display: 'flex', gap: '16px', flexWrap: 'wrap',
  },
  runMetaItem: { display: 'flex', flexDirection: 'column', gap: '1px' },
  runMetaLabel: { fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.06em' },
  runMetaVal: { fontWeight: 700, color: '#718096' },
  condBox: {
    background: '#0f1520', border: '1px solid #1e2535', borderRadius: '6px',
    padding: '8px 10px', fontSize: '11px', color: '#718096', marginTop: '8px',
    fontFamily: 'monospace', lineHeight: 1.6,
  },
  toggleBtn: {
    background: 'none', border: 'none', color: '#4299e1', fontSize: '11px',
    cursor: 'pointer', padding: 0, marginTop: '4px',
  },
}

// ── Status pill ──────────────────────────────────────────────────────────────

function StatusPill({ status }) {
  if (status === 'LIVE')   return <span style={S.pill('#071a0a','#276749','#68d391')}>LIVE</span>
  if (status === 'SHADOW') return <span style={S.pill('#1a0a1f','#6b46c1','#b794f4')}>SHADOW (untested)</span>
  if (status === 'RETIRED') return <span style={S.pill('#1a1a1a','#4a5568','#718096')}>RETIRED</span>
  return <span style={S.pill('#1a1f2e','#2d3748','#a0aec0')}>{status}</span>
}

// ── Alert card ───────────────────────────────────────────────────────────────

function AlertCard({ alert }) {
  const [showCond, setShowCond] = useState(false)
  const isShadow = alert.setup_status === 'SHADOW'
  const accent = isShadow ? '#553c9a' : '#276749'
  const bg = isShadow ? '#110d1f' : '#071a0a'

  const condEntries = Object.entries(alert.conditions || {})

  return (
    <div style={{ ...S.card(accent), background: bg }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '12px' }}>
        <div>
          <div style={S.tickerBig}>{alert.ticker}</div>
          <div style={S.setupName}>{alert.setup_name}</div>
        </div>
        <StatusPill status={alert.setup_status} />
      </div>

      {alert.action_summary && (
        <div style={S.summary}>{alert.action_summary}</div>
      )}

      <div style={S.metaRow}>
        {alert.entry_price != null && (
          <div style={S.stat}>
            <span style={S.statLabel}>Entry</span>
            <span style={S.statValue}>${alert.entry_price.toFixed(2)}</span>
          </div>
        )}
        {alert.invalidation_price != null && (
          <div style={S.stat}>
            <span style={S.statLabel}>Stop</span>
            <span style={{ ...S.statValue, color: '#fc8181' }}>${alert.invalidation_price.toFixed(2)}</span>
          </div>
        )}
        {alert.target_price != null && (
          <div style={S.stat}>
            <span style={S.statLabel}>Target</span>
            <span style={{ ...S.statValue, color: '#68d391' }}>${alert.target_price.toFixed(2)}</span>
          </div>
        )}
        {alert.max_loss != null && (
          <div style={S.stat}>
            <span style={S.statLabel}>Max Loss</span>
            <span style={{ ...S.statValue, color: '#f6ad55' }}>${alert.max_loss.toFixed(2)}</span>
          </div>
        )}
        {alert.iv_percentile != null && (
          <div style={S.stat}>
            <span style={S.statLabel}>IV %ile</span>
            <span style={S.statValue}>{alert.iv_percentile.toFixed(0)}</span>
          </div>
        )}
      </div>

      {/* Options-specific fields */}
      {alert.contract_type && (
        <div style={{ ...S.metaRow, marginTop: '6px' }}>
          <span style={S.pill('#1a1400','#b7791f','#f6e05e')}>
            {alert.contract_type} ${alert.strike?.toFixed(0)} exp {alert.expiry}
          </span>
          {alert.premium != null && (
            <span style={{ fontSize: '12px', color: '#a0aec0' }}>
              ~${alert.premium.toFixed(2)} credit
            </span>
          )}
          {alert.max_loss_per_contract != null && (
            <span style={{ fontSize: '12px', color: '#fc8181' }}>
              max loss ${alert.max_loss_per_contract.toFixed(0)}/contract
            </span>
          )}
        </div>
      )}

      {alert.invalidation_text && (
        <div style={{ fontSize: '11px', color: '#4a5568', marginTop: '8px' }}>
          {alert.invalidation_text}
        </div>
      )}

      {condEntries.length > 0 && (
        <>
          <button style={S.toggleBtn} onClick={() => setShowCond(v => !v)}>
            {showCond ? 'hide conditions' : 'show conditions'}
          </button>
          {showCond && (
            <div style={S.condBox}>
              {condEntries.map(([k, v]) => (
                <div key={k}>
                  <span style={{ color: '#4a5568' }}>{k}: </span>
                  <span style={{ color: typeof v === 'boolean' ? (v ? '#68d391' : '#fc8181') : '#e2e8f0' }}>
                    {typeof v === 'boolean' ? (v ? 'true' : 'false') : String(v ?? '—')}
                  </span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}

// ── Registry row ─────────────────────────────────────────────────────────────

function RegistryRow({ setup }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <tr>
        <td style={S.td}><strong style={{ color: '#e2e8f0' }}>{setup.name}</strong></td>
        <td style={S.td}>{setup.job.replace('_', ' ')}</td>
        <td style={S.td}><StatusPill status={setup.status} /></td>
        <td style={S.td}>
          {setup.backtest_verdict
            ? <span style={{ color: setup.backtest_verdict === 'PASSES' ? '#68d391' : '#b794f4' }}>{setup.backtest_verdict}</span>
            : <span style={{ color: '#4a5568' }}>none</span>
          }
        </td>
        <td style={S.td}>
          {setup.backtest_data_source
            ? <span style={{ color: setup.backtest_data_source.startsWith('REAL') ? '#68d391' : '#fc8181' }}>
                {setup.backtest_data_source.substring(0, 40)}{setup.backtest_data_source.length > 40 ? '...' : ''}
              </span>
            : <span style={{ color: '#4a5568' }}>none</span>
          }
        </td>
        <td style={S.td}>
          <button style={S.toggleBtn} onClick={() => setOpen(v => !v)}>
            {open ? 'hide' : 'recipe'}
          </button>
        </td>
      </tr>
      {open && (
        <tr>
          <td colSpan={6} style={{ ...S.td, background: '#0f1520' }}>
            <pre style={{ margin: 0, fontSize: '11px', color: '#a0aec0', whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>
              {setup.recipe}
            </pre>
          </td>
        </tr>
      )}
    </>
  )
}

// ── Stats table ───────────────────────────────────────────────────────────────

function StatsTable({ stats }) {
  if (!stats?.length) return (
    <div style={S.empty}>No journal statistics yet.</div>
  )
  return (
    <div style={S.tableWrap}>
      <table style={S.table}>
        <thead>
          <tr>
            {['Setup','Label','Fired','Closed','Open','Win %','Expectancy','PF'].map(h => (
              <th key={h} style={S.th}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {stats.map((s, i) => (
            <tr key={i}>
              <td style={S.td}><strong style={{ color: '#e2e8f0' }}>{s.setup_name}</strong></td>
              <td style={S.td}><StatusPill status={s.setup_status_label} /></td>
              <td style={S.td}>{s.alerts_fired}</td>
              <td style={S.td}>{s.alerts_closed}</td>
              <td style={S.td}>{s.alerts_open}</td>
              <td style={S.td}>{s.win_rate_pct != null ? `${s.win_rate_pct}%` : '—'}</td>
              <td style={S.td}>
                {s.expectancy_pct != null
                  ? <span style={{ color: s.expectancy_pct >= 0 ? '#68d391' : '#fc8181' }}>
                      {s.expectancy_pct >= 0 ? '+' : ''}{s.expectancy_pct}%
                    </span>
                  : '—'
                }
              </td>
              <td style={S.td}>{s.profit_factor != null ? s.profit_factor : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Main tab ──────────────────────────────────────────────────────────────────

export default function AlertsTab() {
  const [today, setToday] = useState(null)
  const [registry, setRegistry] = useState(null)
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [view, setView] = useState('alerts') // alerts | registry | stats
  const [running, setRunning] = useState(false)

  useEffect(() => {
    setLoading(true)
    Promise.all([
      api.alerts.getToday(),
      api.alerts.getRegistry(),
      api.alerts.getStats(),
    ]).then(([t, r, s]) => {
      setToday(t)
      setRegistry(r)
      setStats(s)
      setLoading(false)
    }).catch(e => {
      setError(e.message)
      setLoading(false)
    })
  }, [])

  const triggerRun = async () => {
    setRunning(true)
    try {
      const result = await api.alerts.triggerRun()
      // Refresh today's alerts after the run
      const t = await api.alerts.getToday()
      setToday(t)
    } catch (e) {
      setError(e.message)
    } finally {
      setRunning(false)
    }
  }

  if (loading) return <div style={S.empty}>Loading alerts...</div>
  if (error) return <div style={S.error}>Error: {error}</div>

  const liveAlerts = today?.live_alerts || []
  const shadowAlerts = today?.shadow_alerts || []
  const suppressed = today?.suppressed_candidates || []
  const runMeta = today?.last_run

  const navBtn = (id, label) => (
    <button
      key={id}
      onClick={() => setView(id)}
      style={{
        padding: '6px 14px', borderRadius: '6px', fontSize: '12px', fontWeight: 600,
        cursor: 'pointer', border: 'none',
        background: view === id ? '#2b6cb0' : '#1a1f2e',
        color: view === id ? '#fff' : '#718096',
      }}
    >
      {label}
    </button>
  )

  return (
    <div style={S.root}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
        <h2 style={{ margin: 0, fontSize: '18px', fontWeight: 800, color: '#e2e8f0' }}>
          Setup Alerts
        </h2>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          {[navBtn('alerts','Today'), navBtn('registry','Registry'), navBtn('stats','Journal Stats')]}
          <button
            onClick={triggerRun}
            disabled={running}
            style={{
              padding: '6px 14px', borderRadius: '6px', fontSize: '12px', fontWeight: 600,
              cursor: running ? 'not-allowed' : 'pointer', border: '1px solid #2b6cb0',
              background: 'transparent', color: running ? '#4a5568' : '#4299e1',
            }}
          >
            {running ? 'Running...' : 'Run Now'}
          </button>
        </div>
      </div>

      {/* Engine health */}
      {runMeta && (
        <div style={S.runMeta}>
          {[
            ['Last run', new Date(runMeta.ran_at).toLocaleString()],
            ['Tickers', runMeta.tickers_evaluated],
            ['LIVE alerts', runMeta.alerts_fired],
            ['Shadow hits', runMeta.shadow_hits],
            ['Suppressed', runMeta.suppressed],
            ['Duration', `${runMeta.duration_seconds}s`],
          ].map(([l, v]) => (
            <div key={l} style={S.runMetaItem}>
              <span style={S.runMetaLabel}>{l}</span>
              <span style={S.runMetaVal}>{v}</span>
            </div>
          ))}
        </div>
      )}

      {/* Today's alerts view */}
      {view === 'alerts' && (
        <div style={S.section}>
          {liveAlerts.length === 0 && shadowAlerts.length === 0 && (
            <div style={S.empty}>
              No setups qualify today
              {today?.last_run
                ? ` (${(today.last_run.tickers_evaluated || 0).toLocaleString()} tickers evaluated)`
                : ''
              }
            </div>
          )}

          {liveAlerts.length > 0 && (
            <div style={S.section}>
              <div style={S.sectionLabel}>Live Alerts ({liveAlerts.length})</div>
              {liveAlerts.map(a => <AlertCard key={a.id} alert={a} />)}
            </div>
          )}

          {shadowAlerts.length > 0 && (
            <div style={S.section}>
              <div style={{ ...S.sectionLabel, color: '#553c9a' }}>
                Shadow Hits ({shadowAlerts.length}) -- untested setups, for observation only
              </div>
              {shadowAlerts.map(a => <AlertCard key={a.id} alert={a} />)}
            </div>
          )}

          {suppressed.length > 0 && (
            <div style={S.section}>
              <div style={S.sectionLabel}>Suppressed Candidates ({suppressed.length})</div>
              {suppressed.map(a => (
                <div key={a.id} style={{ ...S.card('#4a5568'), background: '#0f1117' }}>
                  <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
                    <span style={{ fontWeight: 700, color: '#718096' }}>{a.ticker}</span>
                    <span style={{ fontSize: '12px', color: '#4a5568' }}>{a.setup_name}</span>
                    <span style={{ fontSize: '11px', color: '#fc8181', marginLeft: 'auto' }}>
                      {a.suppressed_reason}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Registry view */}
      {view === 'registry' && (
        <div style={S.section}>
          <div style={S.tableWrap}>
            <table style={S.table}>
              <thead>
                <tr>
                  {['Setup','Job','Status','Verdict','Data Source','Recipe'].map(h => (
                    <th key={h} style={S.th}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(registry || []).map(s => <RegistryRow key={s.setup_key} setup={s} />)}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Stats view */}
      {view === 'stats' && (
        <div style={S.section}>
          <StatsTable stats={stats} />
        </div>
      )}
    </div>
  )
}
