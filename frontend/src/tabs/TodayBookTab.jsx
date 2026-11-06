import { useEffect, useState } from 'react'
import { api } from '../api'

// Today's Book: the daily landing view. Calm, plain language first,
// precise numbers second. No order execution, no gamification.
// LIVE items are ranked by code; SHADOW items are research only and
// are never sized. Option quotes are delayed; the card says so.

const card = {
  background: '#131825',
  border: '1px solid #2d3748',
  borderRadius: '12px',
  padding: '18px 20px',
  marginBottom: '12px',
}

const muted = { color: '#a0aec0', fontSize: '13px', lineHeight: 1.5 }
const label = { color: '#718096', fontSize: '11px', fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase' }

function money(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return `$${Number(n).toLocaleString('en-US', { maximumFractionDigits: 0 })}`
}

function money2(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return `$${Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function badge(text, colors) {
  return (
    <span style={{
      padding: '3px 10px', fontSize: '11px', fontWeight: 700, borderRadius: '20px',
      whiteSpace: 'nowrap', background: colors.bg, border: `1px solid ${colors.border}`,
      color: colors.text,
    }}>{text}</span>
  )
}

const LIVE = { bg: '#071a0a', border: '#276749', text: '#68d391' }
const SHADOW = { bg: '#1a1400', border: '#b7791f', text: '#f6e05e' }
const BLOCKED = { bg: '#2d1515', border: '#742a2a', text: '#fc8181' }

function Num({ label: l, value, sub }) {
  return (
    <div>
      <div style={label}>{l}</div>
      <div style={{ fontSize: '17px', fontWeight: 700, color: '#e2e8f0', marginTop: '2px' }}>{value}</div>
      {sub && <div style={{ fontSize: '11px', color: '#718096', marginTop: '1px' }}>{sub}</div>}
    </div>
  )
}

function ItemCard({ item }) {
  const quote = item.bid != null && item.ask != null
    ? `${money2(item.bid)} / ${money2(item.ask)}`
    : item.bid != null
      ? `${money2(item.bid)} bid`
      : item.mid != null
        ? `${money2(item.mid)} mid (not tradable)`
        : '—'
  return (
    <div style={{ ...card, borderLeft: '3px solid #276749' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: '10px', alignItems: 'flex-start', flexWrap: 'wrap' }}>
        <div style={{ fontSize: '17px', fontWeight: 700, color: '#e2e8f0' }}>{item.title}</div>
        <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
          {badge('LIVE', LIVE)}
          {item.kind === 'wheel' && badge('Wheel', { bg: '#0a1220', border: '#2b6cb0', text: '#63b3ed' })}
          {item.kind === 'covered_call' && badge('Covered call', { bg: '#0a1220', border: '#2b6cb0', text: '#63b3ed' })}
          {item.kind === 'setup_alert' && badge(item.setup_name || 'Setup alert', { bg: '#1a0a1f', border: '#6b46c1', text: '#b794f4' })}
        </div>
      </div>

      <p style={{ ...muted, margin: '10px 0 0', fontSize: '14px', color: '#cbd5e0' }}>{item.explanation}</p>
      {item.explanation_source === 'claude' && (
        <div style={{ fontSize: '11px', color: '#718096', marginTop: '4px' }}>Explained by Claude, from the numbers above. Claude did not choose or size this trade.</div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: '14px', marginTop: '16px' }}>
        <Num label="Strike" value={item.strike != null ? `$${item.strike}` : '—'} sub={item.expiry ? `Exp ${item.expiry}${item.dte ? ` · ${item.dte}d` : ''}` : null} />
        <Num label="Delta" value={item.delta != null ? Math.abs(item.delta).toFixed(2) : '—'} sub="Rough assignment proxy" />
        <Num label="Bid / Ask" value={quote} sub="Delayed ~15 min" />
        <Num label="Contracts" value={item.contracts} sub={`${item.premium_net_per_contract != null ? money(item.premium_net_total) : '—'} premium after spread haircut`} />
        <Num label="Dollars at risk" value={money(item.risk_dollars)} sub={`${money(item.capital_at_risk)} capital tied up`} />
      </div>

      <div style={{ marginTop: '14px', fontSize: '13px', lineHeight: 1.55, color: '#cbd5e0' }}>
        <div><strong style={{ color: '#e2e8f0' }}>Risk:</strong> {item.risk_text}</div>
        <div style={{ marginTop: '4px' }}><strong style={{ color: '#e2e8f0' }}>What would invalidate it:</strong> {item.invalidation_text}</div>
      </div>
      {item.delay_note && <div style={{ fontSize: '11px', color: '#718096', marginTop: '10px' }}>{item.delay_note}</div>}
    </div>
  )
}

function ScoreStrip({ scoreboard, onGoToBook }) {
  if (!scoreboard) return null
  const tiles = []
  const push = (t) => { if (t) tiles.push(t) }
  push(scoreboard.wheel)
  push(scoreboard.directional)
  ;(scoreboard.alerts || []).forEach(push)
  push(scoreboard.champions)
  return (
    <div style={card}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
        <div style={{ fontSize: '15px', fontWeight: 700, color: '#e2e8f0' }}>Is this working? The Book scoreboard</div>
        <button onClick={onGoToBook} style={{ background: 'none', border: 'none', color: '#63b3ed', cursor: 'pointer', fontSize: '13px', fontWeight: 600 }}>Open full Book →</button>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '12px', marginTop: '12px' }}>
        {tiles.map((t, i) => (
          <div key={i} style={{ background: '#0f1117', border: '1px solid #2d3748', borderRadius: '8px', padding: '10px 12px' }}>
            <div style={{ fontSize: '12px', fontWeight: 700, color: '#cbd5e0' }}>{t.source}</div>
            <div style={{ fontSize: '12px', color: '#a0aec0', marginTop: '4px' }}>
              {t.not_enough
                ? `${t.settled_count || 0} settled so far, not enough to judge yet.`
                : `${t.settled_count} settled · ${t.win_rate_pct}% win rate${t.expectancy_dollars != null ? ` · ${money(t.expectancy_dollars)} avg` : ''}${t.expectancy_pct != null ? ` · ${t.expectancy_pct}% avg` : ''}`}
            </div>
            {t.preliminary && <div style={{ fontSize: '11px', color: '#718096', marginTop: '4px' }}>Preliminary, fewer than 30 settled outcomes.</div>}
          </div>
        ))}
      </div>
    </div>
  )
}

export default function TodayBookTab({ onGoToBook }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [claudeOn, setClaudeOn] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [form, setForm] = useState({ account_equity: '', risk_pct: '', max_heat_pct: '', covered_call_tickers: '' })
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState('')

  const load = async (withClaude) => {
    setLoading(true)
    setError(null)
    try {
      const d = await api.today.get(withClaude)
      setData(d)
      setForm({
        account_equity: String(d.settings.account_equity),
        risk_pct: String(d.settings.risk_pct),
        max_heat_pct: String(d.settings.max_heat_pct),
        covered_call_tickers: (d.settings.covered_call_tickers || []).join(', '),
      })
    } catch (e) {
      setError(e.message || 'Could not load Today\u2019s Book.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load(false) }, [])

  const saveSettings = async () => {
    setSaving(true)
    setSaved('')
    try {
      const body = {
        account_equity: Number(form.account_equity),
        risk_pct: Number(form.risk_pct),
        max_heat_pct: Number(form.max_heat_pct),
        covered_call_tickers: form.covered_call_tickers.split(',').map((t) => t.trim()).filter(Boolean),
      }
      await api.today.saveSettings(body)
      setSaved('Saved. The book re-sized against the new settings.')
      await load(claudeOn)
    } catch (e) {
      setSaved(`Could not save: ${e.message || 'unknown error'}`)
    } finally {
      setSaving(false)
    }
  }

  if (loading && !data) {
    return <div style={{ padding: '48px', textAlign: 'center', color: '#718096' }}>Loading today\u2019s book…</div>
  }
  if (error && !data) {
    return (
      <div style={{ ...card, textAlign: 'center' }}>
        <strong style={{ color: '#fc8181' }}>Today\u2019s Book could not load.</strong>
        <div style={muted}>{error}</div>
        <button onClick={() => load(claudeOn)} style={{ marginTop: '12px', padding: '8px 18px', background: '#2b6cb0', color: '#fff', border: 'none', borderRadius: '6px', cursor: 'pointer' }}>Retry</button>
      </div>
    )
  }

  const rb = data.risk_bar
  const brake = rb.drawdown_brake === 'paused'
    ? badge('Entries paused: drawdown brake', BLOCKED)
    : rb.drawdown_brake === 'reduced'
      ? badge('Risk halved: drawdown brake', SHADOW)
      : badge('No drawdown brake', LIVE)

  return (
    <div style={{ maxWidth: '860px', margin: '0 auto' }}>
      <div style={{ marginBottom: '16px' }}>
        <h1 style={{ fontSize: '24px', fontWeight: 800, color: '#e2e8f0', margin: '0 0 4px', letterSpacing: '-0.5px' }}>Today\u2019s Book</h1>
        <div style={muted}>The best setups for today, in plain language. Signals use yesterday\u2019s close; entries are modeled at the next open. This is decision support, not an order.</div>
        <div style={{ fontSize: '12px', color: '#718096', marginTop: '6px' }}>{data.data_note}</div>
      </div>

      <div style={{ ...card, background: '#0f1a12', borderColor: '#276749' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
          <div style={label}>Portfolio risk</div>
          {brake}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '14px', marginTop: '12px' }}>
          <Num label="Account size" value={money(rb.account_equity)} sub={`Peak ${money(rb.peak_equity)}`} />
          <Num label="Current heat" value={money(rb.current_heat_dollars)} sub={`${rb.current_heat_pct}% of account`} />
          <Num label="Remaining capacity" value={money(rb.remaining_capacity_dollars)} sub={`Heat limit ${money(rb.heat_cap_dollars)}`} />
          <Num label="Open positions" value={`${rb.open_positions} / ${rb.max_positions}`} sub={`Risk per trade ${rb.risk_pct}%`} />
          <Num label="Drawdown" value={`${rb.drawdown_pct}%`} sub={rb.drawdown_brake === 'none' ? 'Below the 10% brake' : rb.drawdown_brake === 'reduced' ? 'Risk halved at 10%' : 'Paused at 15%'} />
        </div>
        <div style={{ display: 'flex', gap: '8px', marginTop: '16px', flexWrap: 'wrap' }}>
          <button onClick={() => load(claudeOn)} style={{ padding: '7px 14px', background: '#2b6cb0', color: '#fff', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '13px' }}>Refresh</button>
          <button
            onClick={() => { const next = !claudeOn; setClaudeOn(next); load(next) }}
            style={{ padding: '7px 14px', background: claudeOn ? '#276749' : '#1a1f2e', color: '#e2e8f0', border: '1px solid #2d3748', borderRadius: '6px', cursor: 'pointer', fontSize: '13px' }}
          >
            {claudeOn ? 'Claude explanations on' : 'Explain in plain words (Claude)'}
          </button>
          <button onClick={() => setSettingsOpen((v) => !v)} style={{ padding: '7px 14px', background: '#1a1f2e', color: '#e2e8f0', border: '1px solid #2d3748', borderRadius: '6px', cursor: 'pointer', fontSize: '13px' }}>
            {settingsOpen ? 'Hide settings' : 'Account settings'}
          </button>
        </div>
        {settingsOpen && (
          <div style={{ marginTop: '16px', borderTop: '1px solid #2d3748', paddingTop: '14px', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '12px' }}>
            <label style={muted}>Account size ($)
              <input value={form.account_equity} onChange={(e) => setForm({ ...form, account_equity: e.target.value })} style={{ display: 'block', width: '100%', marginTop: '4px', padding: '8px', background: '#0f1117', color: '#e2e8f0', border: '1px solid #2d3748', borderRadius: '6px' }} />
            </label>
            <label style={muted}>Risk per trade (%)
              <input value={form.risk_pct} onChange={(e) => setForm({ ...form, risk_pct: e.target.value })} style={{ display: 'block', width: '100%', marginTop: '4px', padding: '8px', background: '#0f1117', color: '#e2e8f0', border: '1px solid #2d3748', borderRadius: '6px' }} />
            </label>
            <label style={muted}>Max heat (%)
              <input value={form.max_heat_pct} onChange={(e) => setForm({ ...form, max_heat_pct: e.target.value })} style={{ display: 'block', width: '100%', marginTop: '4px', padding: '8px', background: '#0f1117', color: '#e2e8f0', border: '1px solid #2d3748', borderRadius: '6px' }} />
            </label>
            <label style={muted}>Covered call tickers (shares owned, comma separated)
              <input value={form.covered_call_tickers} onChange={(e) => setForm({ ...form, covered_call_tickers: e.target.value })} placeholder="e.g. MSFT, AAPL" style={{ display: 'block', width: '100%', marginTop: '4px', padding: '8px', background: '#0f1117', color: '#e2e8f0', border: '1px solid #2d3748', borderRadius: '6px' }} />
            </label>
            <div style={{ display: 'flex', alignItems: 'flex-end', gap: '10px' }}>
              <button onClick={saveSettings} disabled={saving} style={{ padding: '8px 16px', background: '#276749', color: '#fff', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '13px' }}>{saving ? 'Saving…' : 'Save settings'}</button>
              {saved && <span style={{ fontSize: '12px', color: '#a0aec0' }}>{saved}</span>}
            </div>
          </div>
        )}
      </div>

      {data.items.length === 0 ? (
        <div style={{ ...card, textAlign: 'center', padding: '32px' }}>
          <div style={{ fontSize: '16px', fontWeight: 700, color: '#e2e8f0' }}>No setups qualify today.</div>
          <div style={{ ...muted, marginTop: '6px' }}>That is a valid answer, not a failure. The book says nothing rather than forcing a trade.</div>
        </div>
      ) : (
        data.items.map((item) => <ItemCard key={`${item.kind}-${item.ticker}-${item.strike}`} item={item} />)
      )}

      {data.blocked.length > 0 && (
        <div style={card}>
          <div style={{ fontSize: '15px', fontWeight: 700, color: '#e2e8f0', marginBottom: '8px' }}>Blocked by risk limits</div>
          {data.blocked.map((b, i) => (
            <div key={i} style={{ display: 'flex', gap: '8px', alignItems: 'center', marginTop: '8px', flexWrap: 'wrap' }}>
              {badge('Blocked', BLOCKED)}
              <span style={{ fontSize: '13px', color: '#cbd5e0' }}><strong>{b.ticker}</strong>, {b.title}</span>
              <span style={{ fontSize: '12px', color: '#a0aec0' }}>{b.blocked_text}</span>
            </div>
          ))}
        </div>
      )}

      {data.unavailable.length > 0 && (
        <div style={card}>
          <div style={{ fontSize: '15px', fontWeight: 700, color: '#e2e8f0', marginBottom: '8px' }}>Covered calls we could not price</div>
          {data.unavailable.map((u, i) => (
            <div key={i} style={{ fontSize: '13px', color: '#a0aec0', marginTop: '6px' }}>
              <strong style={{ color: '#cbd5e0' }}>{u.ticker}:</strong> {u.unavailable_reason || 'No tradable call could be priced.'}
            </div>
          ))}
        </div>
      )}

      {data.research_only.length > 0 && (
        <details style={{ ...card, background: '#131825' }}>
          <summary style={{ cursor: 'pointer', fontSize: '15px', fontWeight: 700, color: '#e2e8f0' }}>
            Research only ({data.research_only.length}) — SHADOW setups, not sized
          </summary>
          <div style={{ marginTop: '12px' }}>
            {data.research_only.map((r, i) => (
              <div key={i} style={{ display: 'flex', gap: '8px', alignItems: 'flex-start', marginTop: '10px', flexWrap: 'wrap' }}>
                {badge('SHADOW', SHADOW)}
                <div>
                  <div style={{ fontSize: '13px', color: '#cbd5e0' }}><strong>{r.ticker}</strong>, {r.title}</div>
                  <div style={{ fontSize: '12px', color: '#a0aec0', marginTop: '2px' }}>{r.explanation}</div>
                  {r.blocked_text && <div style={{ fontSize: '12px', color: '#718096', marginTop: '2px' }}>{r.blocked_text}</div>}
                </div>
              </div>
            ))}
          </div>
        </details>
      )}

      <ScoreStrip scoreboard={data.scoreboard} onGoToBook={onGoToBook} />
      <div style={{ fontSize: '11px', color: '#718096', textAlign: 'center', margin: '8px 0 24px' }}>
        Generated {new Date(data.generated_at).toLocaleString()}. Decision support only, no live orders.
      </div>
    </div>
  )
}
