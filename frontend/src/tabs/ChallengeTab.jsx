import { useState, useEffect } from 'react'
import { api } from '../api'

const C = {
  bg: '#0f1117', card: '#1a1f2e', bdr: '#2d3748',
  text: '#e2e8f0', muted: '#718096', sub: '#a0aec0', faint: '#4a5568',
  green: '#68d391', yellow: '#ecc94b', red: '#fc8181', blue: '#63b3ed',
  accent: '#48bb78',
}

const fmt$ = v => v == null ? '-' : `$${Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
const fmtPnl = v => v == null ? '-' : `${v >= 0 ? '+' : '-'}${fmt$(Math.abs(v))}`
const fmtDate = d => d ? new Date(d).toLocaleDateString() : '-'

const inputStyle = {
  background: '#0f1117', border: `1px solid ${C.bdr}`, borderRadius: '6px',
  color: C.text, padding: '7px 10px', fontSize: '13px', width: '100%',
}
const labelStyle = { fontSize: '11px', color: C.muted, display: 'block', marginBottom: '4px', fontWeight: 600 }
const btnStyle = {
  padding: '8px 18px', background: '#2b6cb0', color: '#fff', border: 'none',
  borderRadius: '6px', cursor: 'pointer', fontSize: '13px', fontWeight: 600,
}
const btnSmall = { ...btnStyle, padding: '5px 12px', fontSize: '12px' }

function Field({ label, children }) {
  return (
    <div>
      <label style={labelStyle}>{label}</label>
      {children}
    </div>
  )
}

function SectionHeader({ title, subtitle }) {
  return (
    <div style={{ marginBottom: '16px' }}>
      <h2 style={{ fontSize: '18px', fontWeight: 800, color: C.text, margin: 0 }}>{title}</h2>
      {subtitle && <p style={{ fontSize: '12px', color: C.muted, margin: '4px 0 0' }}>{subtitle}</p>}
    </div>
  )
}

function StatBox({ label, value, color, sub }) {
  return (
    <div style={{ background: '#0f1117', border: `1px solid ${C.bdr}`, borderRadius: '8px', padding: '12px 16px' }}>
      <div style={{ fontSize: '11px', color: C.muted }}>{label}</div>
      <div style={{ fontSize: '20px', fontWeight: 700, color: color || C.text }}>{value}</div>
      {sub && <div style={{ fontSize: '11px', color: C.faint, marginTop: '2px' }}>{sub}</div>}
    </div>
  )
}

// ── Setup ─────────────────────────────────────────────────────────────────────

function SetupCard({ onInit, busy }) {
  const today = new Date().toISOString().slice(0, 10)
  const [form, setForm] = useState({
    start_date: today, starting_capital: 1000,
    risk_per_trade_pct: 5, max_open_risk_pct: 20, pause_drawdown_pct: 40,
  })
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  return (
    <div style={{ background: C.card, border: `1px solid ${C.bdr}`, borderRadius: '12px', padding: '24px', maxWidth: '560px' }}>
      <div style={{ fontSize: '18px', fontWeight: 800, color: C.text, marginBottom: '6px' }}>Start the Challenge</div>
      <p style={{ fontSize: '13px', color: C.muted, margin: '0 0 18px' }}>
        A separate account, tracked on its own ledger. Stage 1 runs from your starting
        capital to 10x that amount. Money you add later never counts as trading progress.
      </p>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
        <Field label="Start date">
          <input type="date" style={inputStyle} value={form.start_date} onChange={e => set('start_date', e.target.value)} />
        </Field>
        <Field label="Starting capital ($)">
          <input type="number" style={inputStyle} value={form.starting_capital} onChange={e => set('starting_capital', e.target.value)} />
        </Field>
        <Field label="Risk per trade (%)">
          <input type="number" style={inputStyle} value={form.risk_per_trade_pct} onChange={e => set('risk_per_trade_pct', e.target.value)} />
        </Field>
        <Field label="Max total open risk (%)">
          <input type="number" style={inputStyle} value={form.max_open_risk_pct} onChange={e => set('max_open_risk_pct', e.target.value)} />
        </Field>
        <Field label="Pause at drawdown (%)">
          <input type="number" style={inputStyle} value={form.pause_drawdown_pct} onChange={e => set('pause_drawdown_pct', e.target.value)} />
        </Field>
      </div>
      <div style={{ fontSize: '12px', color: C.faint, marginTop: '12px' }}>
        Target for Stage 1: {fmt$(Number(form.starting_capital || 0) * 10)}. The risk
        percentages drive warnings in the trade form. They warn, they never block.
      </div>
      <button
        style={{ ...btnStyle, marginTop: '16px' }}
        disabled={busy}
        onClick={() => onInit({
          start_date: form.start_date,
          starting_capital: Number(form.starting_capital),
          risk_per_trade_pct: Number(form.risk_per_trade_pct),
          max_open_risk_pct: Number(form.max_open_risk_pct),
          pause_drawdown_pct: Number(form.pause_drawdown_pct),
        })}
      >
        Start Challenge
      </button>
    </div>
  )
}

// ── Equity curve ──────────────────────────────────────────────────────────────

function EquityCurve({ snapshots, currentTradingEquity, target }) {
  const pts = [...(snapshots || [])].reverse()
    .map(s => ({ t: s.taken_at, v: s.trading_equity }))
  if (currentTradingEquity != null) pts.push({ t: 'now', v: currentTradingEquity })

  if (pts.length < 2) {
    return (
      <div style={{ background: C.card, border: `1px solid ${C.bdr}`, borderRadius: '10px', padding: '24px', textAlign: 'center', color: C.muted, fontSize: '13px' }}>
        Not enough snapshots yet. Use Take Snapshot to start the curve.
      </div>
    )
  }

  const W = 900, H = 190, PAD = 34
  const values = pts.map(p => p.v)
  const maxV = Math.max(...values, target || 0) * 1.05
  const minV = Math.min(...values, 0)
  const x = i => PAD + (i / (pts.length - 1)) * (W - PAD * 2)
  const y = v => H - PAD - ((v - minV) / (maxV - minV || 1)) * (H - PAD * 2)
  const line = pts.map((p, i) => `${x(i)},${y(p.v)}`).join(' ')
  const targetY = target != null ? y(target) : null

  return (
    <div style={{ background: C.card, border: `1px solid ${C.bdr}`, borderRadius: '10px', padding: '16px' }}>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto', display: 'block' }}>
        {targetY != null && (
          <>
            <line x1={PAD} x2={W - PAD} y1={targetY} y2={targetY} stroke={C.yellow} strokeWidth="1" strokeDasharray="6 4" />
            <text x={W - PAD} y={targetY - 6} fill={C.yellow} fontSize="12" textAnchor="end">Target {fmt$(target)}</text>
          </>
        )}
        <polyline points={line} fill="none" stroke={C.blue} strokeWidth="2" />
        {pts.map((p, i) => (
          <circle key={i} cx={x(i)} cy={y(p.v)} r="3" fill={C.blue} />
        ))}
        <text x={PAD} y={H - 10} fill={C.muted} fontSize="11">{fmtDate(pts[0].t === 'now' ? null : pts[0].t)}</text>
        <text x={W - PAD} y={H - 10} fill={C.muted} fontSize="11" textAnchor="end">{fmt$(currentTradingEquity)}</text>
      </svg>
    </div>
  )
}

// ── Forms ─────────────────────────────────────────────────────────────────────

function CashFlowForm({ onSubmit }) {
  const [form, setForm] = useState({ flow_type: 'deposit', amount: '', note: '' })
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))
  return (
    <div style={{ background: C.card, border: `1px solid ${C.bdr}`, borderRadius: '10px', padding: '18px' }}>
      <div style={{ fontSize: '14px', fontWeight: 700, color: C.text, marginBottom: '12px' }}>Add Cash Flow</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '10px' }}>
        <Field label="Type">
          <select style={inputStyle} value={form.flow_type} onChange={e => set('flow_type', e.target.value)}>
            <option value="deposit">Deposit</option>
            <option value="withdrawal">Withdrawal</option>
            <option value="dividend">Dividend</option>
            <option value="interest">Interest</option>
            <option value="fee">Fee</option>
            <option value="adjustment">Adjustment (signed)</option>
          </select>
        </Field>
        <Field label="Amount ($)">
          <input type="number" style={inputStyle} value={form.amount} onChange={e => set('amount', e.target.value)} />
        </Field>
        <Field label="Note">
          <input type="text" style={inputStyle} value={form.note} onChange={e => set('note', e.target.value)} />
        </Field>
      </div>
      <div style={{ fontSize: '11px', color: C.faint, marginTop: '8px' }}>
        Deposits, withdrawals, and adjustments never change trading progress. Dividends and interest count as earnings.
      </div>
      <button
        style={{ ...btnSmall, marginTop: '12px' }}
        onClick={() => {
          if (!form.amount) return
          onSubmit({ flow_type: form.flow_type, amount: Number(form.amount), note: form.note || null })
          setForm({ flow_type: 'deposit', amount: '', note: '' })
        }}
      >
        Record Cash Flow
      </button>
    </div>
  )
}

function AddTradeForm({ state, onSubmit, prefill }) {
  const [form, setForm] = useState({
    asset_kind: 'stock', side: 'long', symbol: '', underlying: '', quantity: '',
    multiplier: 1, entry_price: '', current_price: '', fees_open: '',
    planned_max_loss: '', target_price: '', stop_price: '', expiry_date: '',
    setup_key: '', thesis: '', invalidation: '', legs_note: '', notes: '',
  })

  useEffect(() => {
    if (!prefill) return
    setForm(f => ({
      ...f,
      asset_kind: prefill.asset_kind || f.asset_kind,
      side: prefill.side || f.side,
      symbol: prefill.symbol || '',
      underlying: prefill.underlying || '',
      quantity: prefill.quantity ?? '',
      multiplier: prefill.multiplier ?? (prefill.asset_kind === 'stock' ? 1 : 100),
      entry_price: prefill.entry_price ?? '',
      planned_max_loss: prefill.planned_max_loss ?? '',
      target_price: prefill.target_price ?? '',
      stop_price: prefill.stop_price ?? '',
      expiry_date: prefill.expiry_date || '',
      setup_key: prefill.setup_key || '',
      legs_note: prefill.legs_note || '',
    }))
  }, [prefill])
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))
  const setKind = kind => setForm(f => ({ ...f, asset_kind: kind, multiplier: kind === 'stock' ? 1 : 100 }))

  const qty = Number(form.quantity) || 0
  const entry = Number(form.entry_price) || 0
  const mult = Number(form.multiplier) || 0
  const fees = Number(form.fees_open) || 0
  const planned = form.planned_max_loss === '' ? null : Number(form.planned_max_loss)
  const gross = qty * entry * mult
  const requiredCash = form.side === 'long' ? gross + fees : (planned || 0)

  const caps = state.risk_caps || {}
  const warnings = []
  if ((qty > 0 && entry > 0) && requiredCash > (state.cash || 0)) {
    warnings.push(`This trade needs about ${fmt$(requiredCash)} but the account holds ${fmt$(state.cash)} in cash.`)
  }
  if (form.asset_kind !== 'stock' && planned == null) {
    warnings.push('No planned max loss. Option and spread trades need one so open risk and R can be tracked.')
  }
  if (planned != null && caps.per_trade_cap != null && planned > caps.per_trade_cap) {
    warnings.push(`Planned max loss ${fmt$(planned)} is above your per-trade cap of ${fmt$(caps.per_trade_cap)} (${caps.risk_per_trade_pct}% of trading equity).`)
  }
  if (planned != null && caps.open_risk_cap != null && (state.open_risk || 0) + planned > caps.open_risk_cap) {
    warnings.push(`Open risk after this trade would be ${fmt$((state.open_risk || 0) + planned)}, above your cap of ${fmt$(caps.open_risk_cap)} (${caps.max_open_risk_pct}% of trading equity).`)
  }

  return (
    <div style={{ background: C.card, border: `1px solid ${C.bdr}`, borderRadius: '10px', padding: '18px' }}>
      <div style={{ fontSize: '14px', fontWeight: 700, color: C.text, marginBottom: '12px' }}>Add Trade</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: '10px' }}>
        <Field label="Asset kind">
          <select style={inputStyle} value={form.asset_kind} onChange={e => setKind(e.target.value)}>
            <option value="stock">Stock</option>
            <option value="call">Call</option>
            <option value="put">Put</option>
            <option value="spread">Spread</option>
          </select>
        </Field>
        <Field label="Side">
          <select style={inputStyle} value={form.side} onChange={e => set('side', e.target.value)}>
            <option value="long">Long</option>
            <option value="short">Short</option>
          </select>
        </Field>
        <Field label="Symbol">
          <input type="text" style={inputStyle} value={form.symbol} onChange={e => set('symbol', e.target.value)} placeholder="MSFT" />
        </Field>
        <Field label="Underlying (optional)">
          <input type="text" style={inputStyle} value={form.underlying} onChange={e => set('underlying', e.target.value)} />
        </Field>
        <Field label="Quantity">
          <input type="number" style={inputStyle} value={form.quantity} onChange={e => set('quantity', e.target.value)} />
        </Field>
        <Field label="Multiplier">
          <input type="number" style={inputStyle} value={form.multiplier} onChange={e => set('multiplier', e.target.value)} />
        </Field>
        <Field label="Entry price ($)">
          <input type="number" style={inputStyle} value={form.entry_price} onChange={e => set('entry_price', e.target.value)} />
        </Field>
        <Field label="Mark now ($) (optional)">
          <input type="number" style={inputStyle} value={form.current_price} onChange={e => set('current_price', e.target.value)} />
        </Field>
        <Field label="Open fees ($)">
          <input type="number" style={inputStyle} value={form.fees_open} onChange={e => set('fees_open', e.target.value)} />
        </Field>
        <Field label="Planned max loss ($)">
          <input type="number" style={inputStyle} value={form.planned_max_loss} onChange={e => set('planned_max_loss', e.target.value)} />
        </Field>
        <Field label="Target price ($)">
          <input type="number" style={inputStyle} value={form.target_price} onChange={e => set('target_price', e.target.value)} />
        </Field>
        <Field label="Stop price ($)">
          <input type="number" style={inputStyle} value={form.stop_price} onChange={e => set('stop_price', e.target.value)} />
        </Field>
        <Field label="Expiry date (options)">
          <input type="date" style={inputStyle} value={form.expiry_date} onChange={e => set('expiry_date', e.target.value)} />
        </Field>
        <Field label="Setup link (Setup Alert or Directional candidate)">
          <input type="text" style={inputStyle} value={form.setup_key} onChange={e => set('setup_key', e.target.value)} placeholder="quality_pullback" />
        </Field>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '10px', marginTop: '10px' }}>
        <Field label="Thesis">
          <input type="text" style={inputStyle} value={form.thesis} onChange={e => set('thesis', e.target.value)} />
        </Field>
        <Field label="Invalidation">
          <input type="text" style={inputStyle} value={form.invalidation} onChange={e => set('invalidation', e.target.value)} />
        </Field>
        <Field label="Spread legs (for spreads)">
          <input type="text" style={inputStyle} value={form.legs_note} onChange={e => set('legs_note', e.target.value)} placeholder="Long 520C / short 530C, Nov 13" />
        </Field>
        <Field label="Notes">
          <input type="text" style={inputStyle} value={form.notes} onChange={e => set('notes', e.target.value)} />
        </Field>
      </div>

      {warnings.length > 0 && (
        <div style={{ background: '#2d2410', border: `1px solid ${C.yellow}`, borderRadius: '8px', padding: '10px 14px', marginTop: '12px' }}>
          {warnings.map((w, i) => (
            <div key={i} style={{ fontSize: '12px', color: C.yellow }}>Warning: {w}</div>
          ))}
          <div style={{ fontSize: '11px', color: C.faint, marginTop: '4px' }}>Warnings only. The trade can still be recorded.</div>
        </div>
      )}

      <button
        style={{ ...btnSmall, marginTop: '12px' }}
        onClick={() => {
          if (!form.symbol || !qty || !entry) return
          onSubmit({
            asset_kind: form.asset_kind, side: form.side,
            symbol: form.symbol.toUpperCase(),
            underlying: form.underlying ? form.underlying.toUpperCase() : null,
            quantity: qty, multiplier: mult, entry_price: entry,
            current_price: form.current_price === '' ? null : Number(form.current_price),
            fees_open: fees,
            planned_max_loss: planned,
            target_price: form.target_price === '' ? null : Number(form.target_price),
            stop_price: form.stop_price === '' ? null : Number(form.stop_price),
            expiry_date: form.expiry_date === '' ? null : form.expiry_date,
            setup_key: form.setup_key || null, thesis: form.thesis || null,
            invalidation: form.invalidation || null, legs_note: form.legs_note || null,
            notes: form.notes || null,
          })
        }}
      >
        Record Trade
      </button>
    </div>
  )
}

// ── Alerts ────────────────────────────────────────────────────────────────────

const SEVERITY_COLORS = {
  opportunity: C.green, info: C.blue, warning: C.yellow, action: C.red,
}

function AlertsSection({ alerts, unread, busy, telegramConfigured, onRefresh, onStatus, onUse, onTest }) {
  const visible = (alerts || []).filter(a => a.status !== 'dismissed')
  const [testMsg, setTestMsg] = useState(null)
  const [testing, setTesting] = useState(false)

  async function handleTest() {
    setTesting(true)
    try {
      const r = await onTest()
      if (r && r.sent) setTestMsg('Test alert sent. Check your Telegram.')
      else if (r && r.telegram_configured) setTestMsg('Telegram is configured, but the test send failed. Check the bot token and chat ID.')
      else setTestMsg('Telegram is not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to enable phone alerts.')
    } catch (e) {
      setTestMsg(`Test alert failed: ${e.message}`)
    } finally {
      setTesting(false)
    }
  }

  return (
    <section>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '10px', marginBottom: '12px' }}>
        <div>
          <h2 style={{ fontSize: '18px', fontWeight: 800, color: C.text, margin: 0 }}>
            Alerts{unread > 0 ? ` (${unread} unread)` : ''}
          </h2>
          <p style={{ fontSize: '12px', color: C.muted, margin: '4px 0 0' }}>
            Opportunities sized to your risk budget, positions that need review, milestones.
            {telegramConfigured
              ? ' Phone alerts: on. New alerts are also sent to your Telegram.'
              : ' Phone alerts: off, set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to enable.'}
          </p>
        </div>
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          <button style={btnStyle} disabled={busy} onClick={onRefresh}>Check for Alerts</button>
          <button style={btnStyle} disabled={testing} onClick={handleTest}>Send Test Alert</button>
        </div>
      </div>
      {testMsg && (
        <div style={{ fontSize: '12px', color: C.sub, marginBottom: '12px' }}>{testMsg}</div>
      )}
      {visible.length === 0 ? (
        <div style={{ background: C.card, border: `1px solid ${C.bdr}`, borderRadius: '10px', padding: '20px', textAlign: 'center', color: C.muted, fontSize: '13px' }}>
          No alerts. Nothing fits the risk budget right now, and no position needs review.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {visible.map(a => {
            const color = SEVERITY_COLORS[a.severity] || C.blue
            const canUse = (a.alert_type === 'eligible_setup' || a.alert_type === 'eligible_directional') && a.data
            return (
              <div
                key={a.id}
                style={{
                  background: C.card, border: `1px solid ${C.bdr}`, borderLeft: `3px solid ${color}`,
                  borderRadius: '8px', padding: '12px 16px', opacity: a.status === 'read' ? 0.65 : 1,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
                  <span style={{ padding: '2px 8px', border: `1px solid ${color}`, borderRadius: '4px', color, fontSize: '10px', fontWeight: 700, textTransform: 'uppercase' }}>
                    {a.severity}
                  </span>
                  {a.ticker && <span style={{ fontWeight: 700, color: C.blue, fontSize: '13px' }}>{a.ticker}</span>}
                  <span style={{ fontWeight: 700, color: C.text, fontSize: '13px' }}>{a.title}</span>
                  <span style={{ fontSize: '11px', color: C.faint, marginLeft: 'auto' }}>
                    {a.created_at ? new Date(a.created_at).toLocaleString() : ''}
                  </span>
                </div>
                {a.body && <div style={{ fontSize: '12px', color: C.sub, marginTop: '6px' }}>{a.body}</div>}
                <div style={{ display: 'flex', gap: '8px', marginTop: '10px', flexWrap: 'wrap' }}>
                  {canUse && (
                    <button style={{ ...btnSmall, background: '#276749' }} onClick={() => onUse(a)}>
                      Use in Trade Form
                    </button>
                  )}
                  {a.status === 'unread' && (
                    <button style={btnSmall} onClick={() => onStatus(a.id, 'read')}>Mark Read</button>
                  )}
                  <button
                    style={{ ...btnSmall, background: 'transparent', border: `1px solid ${C.bdr}`, color: C.sub }}
                    onClick={() => onStatus(a.id, 'dismissed')}
                  >
                    Dismiss
                  </button>
                  {a.status !== 'unread' && (
                    <span style={{ fontSize: '11px', color: C.faint, alignSelf: 'center' }}>{a.status}</span>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}

// ── Trade tables ──────────────────────────────────────────────────────────────

const thStyle = { textAlign: 'left', padding: '8px 12px', borderBottom: `1px solid ${C.bdr}`, color: C.muted, fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.04em', fontWeight: 600 }
const tdStyle = { padding: '10px 12px', color: C.sub }

function OpenTradeRow({ trade, onMark, onClose }) {
  const [mark, setMark] = useState('')
  const [exit, setExit] = useState('')
  const [closeFees, setCloseFees] = useState('')
  const pnlColor = v => v == null ? C.sub : v >= 0 ? C.green : C.red

  return (
    <tr style={{ borderBottom: `1px solid #1a1f2e` }}>
      <td style={{ ...tdStyle, color: C.blue, fontWeight: 700 }}>{trade.symbol}</td>
      <td style={tdStyle}>{trade.asset_kind} / {trade.side}</td>
      <td style={tdStyle}>{trade.quantity}</td>
      <td style={tdStyle}>{fmt$(trade.entry_price)}</td>
      <td style={tdStyle}>{trade.stop_price != null ? fmt$(trade.stop_price) : '-'}</td>
      <td style={tdStyle}>
        {fmt$(trade.mark_price)}
        <span style={{ fontSize: '10px', color: C.faint, marginLeft: '6px' }}>{trade.mark_source}</span>
      </td>
      <td style={tdStyle}>{fmt$(trade.value)}</td>
      <td style={{ ...tdStyle, color: pnlColor(trade.unrealized_pnl) }}>{fmtPnl(trade.unrealized_pnl)}</td>
      <td style={tdStyle}>{trade.planned_max_loss != null ? fmt$(trade.planned_max_loss) : '-'}</td>
      <td style={tdStyle}>{trade.expiry_date || '-'}</td>
      <td style={tdStyle}>
        <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', alignItems: 'center' }}>
          <input type="number" placeholder="Mark" value={mark} onChange={e => setMark(e.target.value)}
            style={{ ...inputStyle, width: '76px', padding: '5px 8px' }} />
          <button style={btnSmall} onClick={() => { if (mark !== '') { onMark(trade.id, Number(mark)); setMark('') } }}>Set mark</button>
          <input type="number" placeholder="Exit" value={exit} onChange={e => setExit(e.target.value)}
            style={{ ...inputStyle, width: '76px', padding: '5px 8px' }} />
          <input type="number" placeholder="Fees" value={closeFees} onChange={e => setCloseFees(e.target.value)}
            style={{ ...inputStyle, width: '64px', padding: '5px 8px' }} />
          <button
            style={{ ...btnSmall, background: '#276749' }}
            onClick={() => { if (exit !== '') onClose(trade.id, { exit_price: Number(exit), fees_close: Number(closeFees) || 0 }) }}
          >
            Close
          </button>
        </div>
      </td>
    </tr>
  )
}

function OpenTrades({ trades, onMark, onClose }) {
  return (
    <section>
      <SectionHeader title="Open Trades" subtitle="Marked manually, from a live stock price, or at entry until marked" />
      {trades.length === 0 ? (
        <div style={{ background: C.card, border: `1px solid ${C.bdr}`, borderRadius: '10px', padding: '24px', textAlign: 'center', color: C.muted, fontSize: '13px' }}>
          No open trades.
        </div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
            <thead>
              <tr>{['Symbol', 'Kind / Side', 'Qty', 'Entry', 'Stop', 'Mark', 'Value', 'Unrealized', 'Max Loss', 'Expiry', 'Actions'].map(h => <th key={h} style={thStyle}>{h}</th>)}</tr>
            </thead>
            <tbody>
              {trades.map(t => <OpenTradeRow key={t.id} trade={t} onMark={onMark} onClose={onClose} />)}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function ClosedTrades({ trades }) {
  const pnlColor = v => v == null ? C.sub : v >= 0 ? C.green : C.red
  return (
    <section>
      <SectionHeader title="Closed Trades" subtitle="Realized results, graded in dollars and in R where a max loss was planned" />
      {trades.length === 0 ? (
        <div style={{ background: C.card, border: `1px solid ${C.bdr}`, borderRadius: '10px', padding: '24px', textAlign: 'center', color: C.muted, fontSize: '13px' }}>
          No closed trades yet.
        </div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
            <thead>
              <tr>{['Symbol', 'Kind / Side', 'Qty', 'Entry', 'Exit', 'Realized', 'R', 'Setup', 'Closed'].map(h => <th key={h} style={thStyle}>{h}</th>)}</tr>
            </thead>
            <tbody>
              {[...trades].reverse().map(t => (
                <tr key={t.id} style={{ borderBottom: `1px solid #1a1f2e` }}>
                  <td style={{ ...tdStyle, color: C.blue, fontWeight: 700 }}>{t.symbol}</td>
                  <td style={tdStyle}>{t.asset_kind} / {t.side}</td>
                  <td style={tdStyle}>{t.quantity}</td>
                  <td style={tdStyle}>{fmt$(t.entry_price)}</td>
                  <td style={tdStyle}>{fmt$(t.exit_price)}</td>
                  <td style={{ ...tdStyle, color: pnlColor(t.realized_pnl), fontWeight: 700 }}>{fmtPnl(t.realized_pnl)}</td>
                  <td style={tdStyle}>{t.r_multiple != null ? `${t.r_multiple}R` : '-'}</td>
                  <td style={tdStyle}>{t.setup_key || '-'}</td>
                  <td style={tdStyle}>{fmtDate(t.closed_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

// ── Main tab ──────────────────────────────────────────────────────────────────

export default function ChallengeTab() {
  const [state, setState] = useState(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [prefill, setPrefill] = useState(null)

  async function load() {
    try {
      const s = await api.challenge.getState()
      setState(s)
      setError(null)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  async function act(fn) {
    setBusy(true)
    try {
      await fn()
      await load()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: '60px', color: C.muted }}>
        <div style={{ fontSize: '32px', marginBottom: '12px' }}>🏆</div>
        <div>Loading challenge...</div>
      </div>
    )
  }

  const stage = state?.current_stage
  const progress = state?.progress
  const caps = state?.risk_caps || {}
  const sb = state?.scoreboard || {}

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '32px', maxWidth: '960px' }}>
      <div style={{ background: 'linear-gradient(135deg,#1a2744 0%,#1a1f2e 100%)', border: `1px solid ${C.blue}33`, borderRadius: '12px', padding: '20px 24px' }}>
        <div style={{ fontSize: '24px', fontWeight: 800, color: C.text }}>The Challenge</div>
        <div style={{ fontSize: '13px', color: C.muted, marginTop: '4px' }}>
          One separate account, one honest ledger. Each stage targets 10x its start.
        </div>
      </div>

      {error && (
        <div style={{ background: '#2d1515', border: `1px solid ${C.red}`, borderRadius: '10px', padding: '16px', color: C.red }}>
          {error}
        </div>
      )}

      {state?.initialized && (
        <AlertsSection
          alerts={state.alerts}
          unread={state.unread_alert_count || 0}
          busy={busy}
          telegramConfigured={!!state.telegram_configured}
          onTest={() => api.challenge.testAlert()}
          onRefresh={() => act(async () => setState(await api.challenge.refreshAlerts()))}
          onStatus={(id, status) => act(() => api.challenge.setAlertStatus(id, status))}
          onUse={a => {
            setPrefill({ ...a.data, _alert: a.id })
            act(() => api.challenge.setAlertStatus(a.id, 'acted'))
          }}
        />
      )}

      {!state?.initialized ? (
        <SetupCard busy={busy} onInit={body => act(async () => setState(await api.challenge.initAccount(body)))} />
      ) : (
        <>
          {/* Stage header */}
          <div style={{ background: C.card, border: `1px solid ${C.bdr}`, borderRadius: '12px', padding: '20px 24px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '12px' }}>
              <div>
                <div style={{ fontSize: '12px', color: C.muted, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  Stage {stage?.stage_number}: {fmt$(stage?.starting_equity)} to {fmt$(stage?.target)}
                </div>
                <div style={{ fontSize: '34px', fontWeight: 800, color: C.text, marginTop: '4px' }}>
                  {fmt$(state.trading_equity)}
                  {progress?.multiple != null && (
                    <span style={{ fontSize: '16px', color: C.blue, marginLeft: '12px' }}>{progress.multiple}x</span>
                  )}
                </div>
                <div style={{ fontSize: '12px', color: C.muted }}>Trading equity (added money excluded)</div>
              </div>
              <button style={btnStyle} disabled={busy} onClick={() => act(async () => setState(await api.challenge.snapshot()))}>
                Take Snapshot
              </button>
            </div>
            <div style={{ background: '#0f1117', borderRadius: '6px', height: '14px', marginTop: '16px', overflow: 'hidden' }}>
              <div style={{ width: `${progress?.log_progress_pct || 0}%`, height: '100%', background: C.blue, borderRadius: '6px' }} />
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', color: C.muted, marginTop: '6px' }}>
              <span>{progress?.log_progress_pct || 0}% of the way (log scale)</span>
              <span>{fmt$(progress?.remaining)} to go</span>
            </div>
            {caps.paused && (
              <div style={{ background: '#2d1515', border: `1px solid ${C.red}`, borderRadius: '8px', padding: '10px 14px', marginTop: '12px', fontSize: '12px', color: C.red }}>
                Drawdown is at or past your {caps.pause_drawdown_pct}% pause line. Your rule says stop and review before new trades.
              </div>
            )}
          </div>

          {/* Metrics */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: '12px' }}>
            <StatBox label="Cash" value={fmt$(state.cash)} color={C.blue} />
            <StatBox label="Open Position Value" value={fmt$(state.open_value)} />
            <StatBox
              label="Open Risk"
              value={fmt$(state.open_risk)}
              color={caps.open_risk_cap != null && state.open_risk > caps.open_risk_cap ? C.red : C.yellow}
              sub={caps.open_risk_cap != null ? `cap ${fmt$(caps.open_risk_cap)} (${caps.max_open_risk_pct}% of trading equity)` : null}
            />
            <StatBox
              label="Drawdown From Peak"
              value={`${fmt$(state.drawdown)} (${state.drawdown_pct}%)`}
              color={state.drawdown > 0 ? C.red : C.text}
              sub={`peak ${fmt$(state.peak_trading_equity)}, pause at ${caps.pause_drawdown_pct}%`}
            />
            <StatBox
              label="Net Trading P and L"
              value={fmtPnl(state.trading_pnl)}
              color={state.trading_pnl >= 0 ? C.green : C.red}
            />
          </div>

          <section>
            <SectionHeader title="Trading Equity Curve" subtitle="Snapshots only, plus the current value. Deposits never lift this line." />
            <EquityCurve snapshots={state.snapshots} currentTradingEquity={state.trading_equity} target={stage?.target} />
          </section>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
            <AddTradeForm state={state} prefill={prefill} onSubmit={body => act(() => api.challenge.addTrade(body))} />
            <CashFlowForm onSubmit={body => act(() => api.challenge.addCashFlow(body))} />
          </div>

          <OpenTrades
            trades={state.open_trades || []}
            onMark={(id, price) => act(() => api.challenge.updateMark(id, price))}
            onClose={(id, body) => act(() => api.challenge.closeTrade(id, body))}
          />

          <section>
            <SectionHeader title="Scoreboard" subtitle="Closed challenge trades only" />
            <div style={{ background: C.card, border: `1px solid ${C.bdr}`, borderRadius: '12px', padding: '18px 20px' }}>
              {sb.count === 0 ? (
                <div style={{ fontSize: '12px', color: C.muted, fontStyle: 'italic' }}>No closed trades yet.</div>
              ) : (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))', gap: '12px' }}>
                  <StatBox label="Trades" value={sb.count} />
                  <StatBox label="Wins / Losses" value={`${sb.wins} / ${sb.losses}`} />
                  <StatBox label="Total P and L" value={fmtPnl(sb.total_pnl)} color={sb.total_pnl >= 0 ? C.green : C.red} />
                  <StatBox label="Expectancy" value={fmtPnl(sb.expectancy)} color={sb.expectancy >= 0 ? C.green : C.red} />
                  <StatBox label="Expectancy (R)" value={sb.expectancy_r != null ? `${sb.expectancy_r}R` : '-'} />
                  <StatBox label="Profit Factor" value={sb.profit_factor != null ? sb.profit_factor.toFixed(2) : '-'} />
                  <StatBox label="Avg Win" value={fmtPnl(sb.avg_win)} color={C.green} />
                  <StatBox label="Avg Loss" value={fmtPnl(sb.avg_loss)} color={C.red} />
                  <StatBox label="Best" value={fmtPnl(sb.best)} color={C.green} />
                  <StatBox label="Worst" value={fmtPnl(sb.worst)} color={C.red} />
                  <StatBox label="Losing Streak" value={sb.losing_streak} color={sb.losing_streak > 0 ? C.red : C.text} />
                </div>
              )}
            </div>
          </section>

          <ClosedTrades trades={state.closed_trades || []} />

          <section>
            <SectionHeader title="Cash Flows" subtitle="Every dollar in or out, outside of trades" />
            {(state.cash_flows || []).length === 0 ? (
              <div style={{ fontSize: '13px', color: C.muted }}>None recorded.</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                {[...state.cash_flows].reverse().slice(0, 20).map(f => (
                  <div key={f.id} style={{ background: C.card, border: `1px solid ${C.bdr}`, borderRadius: '8px', padding: '8px 14px', display: 'flex', justifyContent: 'space-between', fontSize: '12px' }}>
                    <span style={{ color: C.sub }}>{fmtDate(f.occurred_at)} · {f.flow_type}{f.note ? ` · ${f.note}` : ''}</span>
                    <span style={{ color: f.amount >= 0 ? C.green : C.red, fontWeight: 700 }}>{fmtPnl(f.amount)}</span>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section>
            <SectionHeader title="Stage History" subtitle="Graduated stages stay on the record" />
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {(state.stages || []).map(s => (
                <div key={s.id} style={{ background: C.card, border: `1px solid ${C.bdr}`, borderRadius: '8px', padding: '10px 16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '13px', flexWrap: 'wrap', gap: '8px' }}>
                  <span style={{ color: C.text, fontWeight: 700 }}>Stage {s.stage_number}</span>
                  <span style={{ color: C.muted }}>{fmt$(s.starting_equity)} to {fmt$(s.target)}</span>
                  <span style={{ color: C.muted }}>{fmtDate(s.start_date)}{s.end_date ? ` to ${fmtDate(s.end_date)}` : ''}</span>
                  <span style={{
                    padding: '2px 8px', borderRadius: '4px', fontSize: '11px', fontWeight: 600,
                    border: `1px solid ${s.status === 'graduated' ? C.green : C.blue}`,
                    color: s.status === 'graduated' ? C.green : C.blue,
                  }}>
                    {s.status}{s.status === 'graduated' && s.ending_equity != null ? ` at ${fmt$(s.ending_equity)}` : ''}
                  </span>
                </div>
              ))}
            </div>
          </section>

          <div style={{ fontSize: '11px', color: C.faint, fontStyle: 'italic' }}>
            Note on marks: option marks are manual in this version. The current data plan provides delayed
            option data without live quotes, so enter option marks from your broker. Stock marks use a live
            price when no manual mark is set, and fall back to the entry price when no price is available.
          </div>
        </>
      )}
    </div>
  )
}
