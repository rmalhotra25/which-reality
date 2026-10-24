import { useState, useEffect } from 'react'
import { api } from '../api'

const C = {
  bg: '#0f1117', card: '#1a1f2e', bdr: '#2d3748',
  text: '#e2e8f0', muted: '#718096', sub: '#a0aec0', faint: '#4a5568',
  green: '#68d391', yellow: '#ecc94b', red: '#fc8181', blue: '#63b3ed',
  accent: '#48bb78',
}

const fmt$ = v => `$${Number(v || 0).toLocaleString('en-US', { maximumFractionDigits: 0 })}`
const fmtP = v => v != null ? `${Number(v).toFixed(1)}%` : '—'
const fmtPSign = v => v != null ? `${v >= 0 ? '+' : ''}${Number(v).toFixed(1)}%` : '—'
const fmtDollarsSigned = v => v != null ? `${v >= 0 ? '+' : '-'}$${Math.abs(Number(v)).toLocaleString('en-US', { maximumFractionDigits: 0 })}` : '—'

// ── Scoreboard ────────────────────────────────────────────────────────────────

function ScoreboardTile({ tile }) {
  const notEnough = tile.not_enough
  const statColor = v => v == null ? C.sub : v >= 0 ? C.green : C.red

  return (
    <div style={{ background: C.card, border: `1px solid ${C.bdr}`, borderRadius: '12px', padding: '18px 20px' }}>
      <div style={{ fontSize: '14px', fontWeight: 700, color: C.text, marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
        {tile.source}
        {tile.status_label && (
          <span style={{
            fontSize: '10px', fontWeight: 700, letterSpacing: '0.05em',
            color: tile.status_label === 'LIVE' ? C.green : C.yellow,
            border: `1px solid ${tile.status_label === 'LIVE' ? C.green : C.yellow}`,
            borderRadius: '4px', padding: '1px 6px',
          }}>
            {tile.status_label}
          </span>
        )}
      </div>

      {notEnough ? (
        <div style={{ fontSize: '12px', color: C.muted, fontStyle: 'italic' }}>
          Not enough settled outcomes yet ({tile.settled_count} settled — need 5)
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))', gap: '10px' }}>
          <Stat label="Recs Made"     value={tile.recs_made} />
          <Stat label="Settled"       value={tile.settled_count} />
          <Stat label="Win Rate"      value={fmtP(tile.win_rate_pct)}    color={tile.win_rate_pct >= 50 ? C.green : C.red} />
          <Stat label="Expectancy"    value={tile.expectancy_pct != null ? fmtPSign(tile.expectancy_pct) : fmtDollarsSigned(tile.expectancy_dollars)} color={tile.expectancy_pct != null ? statColor(tile.expectancy_pct) : statColor(tile.expectancy_dollars)} />
          <Stat label="Profit Factor" value={tile.profit_factor != null ? tile.profit_factor.toFixed(2) : '—'} color={tile.profit_factor >= 1 ? C.green : C.red} />
        </div>
      )}

      {tile.preliminary && (
        <div style={{ fontSize: '11px', color: C.muted, fontStyle: 'italic', marginTop: '10px' }}>
          Preliminary: {tile.confidence_note || 'based on few settled outcomes, treat these stats as early evidence.'}
        </div>
      )}

      {tile.last_settled_at ? (
        <div style={{ fontSize: '11px', color: C.faint, marginTop: '10px' }}>
          Last settlement: {new Date(tile.last_settled_at).toLocaleString()}
        </div>
      ) : tile.source === 'Champions Daily Picks' ? (
        <div style={{ fontSize: '11px', color: C.faint, marginTop: '10px' }}>
          Last settlement: none yet
        </div>
      ) : null}

      {tile.by_strategy && (
        <div style={{ marginTop: '12px', paddingTop: '12px', borderTop: `1px solid ${C.bdr}` }}>
          <div style={{ fontSize: '11px', color: C.muted, marginBottom: '8px', fontWeight: 600 }}>BY STRATEGY</div>
          <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
            {Object.entries(tile.by_strategy).map(([strat, s]) => (
              <div key={strat} style={{ background: '#0f1117', border: `1px solid ${C.bdr}`, borderRadius: '8px', padding: '8px 12px', minWidth: '120px' }}>
                <div style={{ fontSize: '11px', color: C.sub, fontWeight: 700, textTransform: 'uppercase', marginBottom: '4px' }}>{strat}</div>
                <div style={{ fontSize: '11px', color: C.muted }}>{s.picks_made} picks / {s.settled_count} settled</div>
                {s.horizon_days && <div style={{ fontSize: '11px', color: C.faint }}>Horizon: {s.horizon_days}d</div>}
                {s.settled_count >= 5 && <div style={{ fontSize: '12px', color: s.win_rate_pct >= 50 ? C.green : C.red, marginTop: '2px' }}>{fmtP(s.win_rate_pct)} win rate</div>}
                {s.settled_count < 5 && s.settled_count > 0 && <div style={{ fontSize: '11px', color: C.faint, fontStyle: 'italic' }}>need more settled</div>}
              </div>
            ))}
          </div>
          <div style={{ fontSize: '11px', color: C.faint, marginTop: '8px' }}>
            Settlement rule: time-based (no targets or stops emitted). Champions picks close at the strategy horizon.
          </div>
        </div>
      )}
    </div>
  )
}

function Stat({ label, value, color }) {
  return (
    <div>
      <div style={{ fontSize: '10px', color: C.muted }}>{label}</div>
      <div style={{ fontSize: '18px', fontWeight: 700, color: color || C.text }}>{value ?? '—'}</div>
    </div>
  )
}

function Scoreboard({ data }) {
  if (!data) return null

  const alertTiles = (data.alerts || []).filter(t => t.setup_key !== 'directional_options')
  const directional = data.directional
  const champions = data.champions
  const wheel = data.wheel

  return (
    <section>
      <SectionHeader title="Scoreboard" subtitle="Every advice source, graded from records — no hand-entered numbers" />

      <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
        {wheel && <ScoreboardTile tile={wheel} />}
        {directional && <ScoreboardTile tile={directional} />}
        {champions && <ScoreboardTile tile={champions} />}
        {alertTiles.map(t => (
          <ScoreboardTile key={`${t.setup_key}-${t.status_label}`} tile={t} />
        ))}
      </div>
    </section>
  )
}

// ── Open Positions ────────────────────────────────────────────────────────────

const STATUS_LABELS = {
  put_active: 'Selling Put', assigned: 'Owns Shares',
  call_active: 'Selling Call', closed: 'Closed',
}
const STATUS_COLORS = {
  put_active: C.blue, assigned: C.yellow,
  call_active: C.green, closed: C.muted,
}

function OpenPositions({ perfData, accountData }) {
  const active = perfData?.active_positions || []
  const balance = accountData?.balance
  const atRisk = accountData?.capital_at_risk
  const available = accountData?.available_capital

  return (
    <section>
      <SectionHeader title="Open Positions" subtitle="Current wheel strategy positions and account balance" />

      {(balance != null) && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: '12px', marginBottom: '16px' }}>
          <StatBox label="Account Balance"    value={fmt$(balance)}    color={C.blue} />
          <StatBox label="Capital at Risk"    value={fmt$(atRisk)}     color={C.yellow} />
          <StatBox label="Available Capital"  value={fmt$(available)}  color={C.green} />
        </div>
      )}

      {active.length === 0 ? (
        <div style={{ background: C.card, border: `1px solid ${C.bdr}`, borderRadius: '10px', padding: '32px', textAlign: 'center', color: C.muted, fontSize: '13px' }}>
          No open positions.
        </div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
            <thead>
              <tr>
                {['Ticker', 'Status', 'Put Strike', 'Expiry', 'Premium Rcvd', 'Capital at Risk', 'Opened'].map(h => (
                  <th key={h} style={{ textAlign: 'left', padding: '8px 12px', borderBottom: `1px solid ${C.bdr}`, color: C.muted, fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.04em', fontWeight: 600 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {active.map((p, i) => (
                <tr key={p.id} style={{ background: i % 2 === 0 ? '#0d1117' : C.card, borderBottom: `1px solid #1a1f2e` }}>
                  <td style={{ padding: '10px 12px', color: C.blue, fontWeight: 700 }}>{p.ticker}</td>
                  <td style={{ padding: '10px 12px' }}>
                    <span style={{ padding: '2px 8px', border: `1px solid ${STATUS_COLORS[p.status] || C.bdr}`, borderRadius: '4px', color: STATUS_COLORS[p.status] || C.muted, fontSize: '11px', fontWeight: 600 }}>
                      {STATUS_LABELS[p.status] || p.status}
                    </span>
                  </td>
                  <td style={{ padding: '10px 12px', color: C.sub }}>{p.put_strike ? `$${p.put_strike}` : '—'}</td>
                  <td style={{ padding: '10px 12px', color: C.sub }}>{p.put_expiry || '—'}</td>
                  <td style={{ padding: '10px 12px', color: C.green }}>{p.put_premium_rcvd ? `$${p.put_premium_rcvd}` : '—'}</td>
                  <td style={{ padding: '10px 12px', color: C.sub }}>{p.capital_at_risk ? `$${p.capital_at_risk.toLocaleString()}` : '—'}</td>
                  <td style={{ padding: '10px 12px', color: C.sub }}>{p.put_opened_at ? new Date(p.put_opened_at).toLocaleDateString() : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function StatBox({ label, value, color }) {
  return (
    <div style={{ background: '#0f1117', border: `1px solid ${C.bdr}`, borderRadius: '8px', padding: '12px 16px' }}>
      <div style={{ fontSize: '11px', color: C.muted }}>{label}</div>
      <div style={{ fontSize: '20px', fontWeight: 700, color: color || C.text }}>{value}</div>
    </div>
  )
}

// ── Watchlist ─────────────────────────────────────────────────────────────────

function WatchlistSection({ items }) {
  return (
    <section>
      <SectionHeader title="Watchlist" subtitle="Backend-backed — one list, every screen" />
      {items.length === 0 ? (
        <div style={{ background: C.card, border: `1px solid ${C.bdr}`, borderRadius: '10px', padding: '32px', textAlign: 'center', color: C.muted, fontSize: '13px' }}>
          No tickers on your watchlist yet. Add them from Stock Triggers.
        </div>
      ) : (
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          {items.map(item => (
            <div key={item.ticker} style={{ background: C.card, border: `1px solid ${C.bdr}`, borderRadius: '8px', padding: '8px 14px' }}>
              <span style={{ fontWeight: 700, color: C.text, fontSize: '14px' }}>{item.ticker}</span>
              {item.best_strategy && (
                <span style={{ fontSize: '11px', color: C.muted, marginLeft: '8px' }}>{item.best_strategy}</span>
              )}
              {item.last_scored && (
                <span style={{ fontSize: '11px', color: C.faint, marginLeft: '8px' }}>scored {new Date(item.last_scored).toLocaleDateString()}</span>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

// ── Income Calendar ───────────────────────────────────────────────────────────

const MONTH_NAMES = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

function IncomeCalendar({ calData }) {
  if (!calData) return null

  const payments = calData.payments || []

  // Group by month
  const byMonth = {}
  for (const p of payments) {
    const d = new Date(p.projected_ex_date)
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
    if (!byMonth[key]) byMonth[key] = { label: `${MONTH_NAMES[d.getMonth()]} ${d.getFullYear()}`, items: [] }
    byMonth[key].items.push(p)
  }

  const months = Object.entries(byMonth).sort(([a], [b]) => a.localeCompare(b))

  return (
    <section>
      <SectionHeader
        title="Income Calendar"
        subtitle="Projected dividend and distribution ex-dates for the next 90 days — all dates are projections"
      />
      {payments.length === 0 ? (
        <div style={{ background: C.card, border: `1px solid ${C.bdr}`, borderRadius: '10px', padding: '32px', textAlign: 'center', color: C.muted, fontSize: '13px' }}>
          No dividend data found for current watchlist and held names. Add dividend-paying stocks to your watchlist to see projections here.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {months.map(([key, { label, items }]) => (
            <div key={key}>
              <div style={{ fontSize: '13px', fontWeight: 700, color: C.sub, marginBottom: '8px', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{label}</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                {items.map((p, i) => (
                  <div key={i} style={{ background: C.card, border: `1px solid ${C.bdr}`, borderRadius: '8px', padding: '10px 16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                      <span style={{ fontWeight: 700, color: C.text, fontSize: '14px', minWidth: '60px' }}>{p.ticker}</span>
                      <span style={{ fontSize: '12px', color: C.muted }}>Ex-date: {p.projected_ex_date}</span>
                      <span style={{ fontSize: '11px', color: C.faint, background: '#ffffff0a', border: `1px solid ${C.faint}33`, borderRadius: '4px', padding: '1px 6px' }}>PROJECTION</span>
                    </div>
                    <div style={{ textAlign: 'right' }}>
                      <div style={{ fontSize: '14px', fontWeight: 700, color: C.green }}>${p.amount_per_share.toFixed(4)}/share</div>
                      <div style={{ fontSize: '11px', color: C.muted }}>{p.freq_per_year}x/yr</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
          <div style={{ fontSize: '11px', color: C.faint, fontStyle: 'italic' }}>
            {calData.note}
          </div>
        </div>
      )}
    </section>
  )
}

// ── Section header ────────────────────────────────────────────────────────────

function SectionHeader({ title, subtitle }) {
  return (
    <div style={{ marginBottom: '16px' }}>
      <h2 style={{ fontSize: '18px', fontWeight: 800, color: C.text, margin: 0 }}>{title}</h2>
      {subtitle && <p style={{ fontSize: '12px', color: C.muted, margin: '4px 0 0' }}>{subtitle}</p>}
    </div>
  )
}

// ── Main tab ──────────────────────────────────────────────────────────────────

export default function BookTab() {
  const [scoreboard, setScoreboard] = useState(null)
  const [perfData, setPerfData] = useState(null)
  const [accountData, setAccountData] = useState(null)
  const [watchlist, setWatchlist] = useState([])
  const [calData, setCalData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const [sb, perf, acct, wl, cal] = await Promise.all([
          api.book.scoreboard(),
          api.performance.getSummary(),
          api.account.getBalance(),
          api.watchlist.list(),
          api.book.incomeCalendar(),
        ])
        setScoreboard(sb)
        setPerfData(perf)
        setAccountData(acct)
        setWatchlist(wl)
        setCalData(cal)
      } catch (e) {
        setError(e.message)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '40px', maxWidth: '960px' }}>

      {/* Header */}
      <div style={{ background: 'linear-gradient(135deg,#1a2744 0%,#1a1f2e 100%)', border: `1px solid ${C.blue}33`, borderRadius: '12px', padding: '20px 24px' }}>
        <div style={{ fontSize: '24px', fontWeight: 800, color: C.text }}>The Book</div>
        <div style={{ fontSize: '13px', color: C.muted, marginTop: '4px' }}>
          One watchlist, open positions, full scoreboard, income calendar.
        </div>
      </div>

      {error && (
        <div style={{ background: '#2d1515', border: `1px solid ${C.red}`, borderRadius: '10px', padding: '16px', color: C.red }}>
          {error}
        </div>
      )}

      {loading ? (
        <div style={{ textAlign: 'center', padding: '60px', color: C.muted }}>
          <div style={{ fontSize: '32px', marginBottom: '12px' }}>📖</div>
          <div>Loading book data...</div>
        </div>
      ) : (
        <>
          <Scoreboard data={scoreboard} />
          <OpenPositions perfData={perfData} accountData={accountData} />
          <WatchlistSection items={watchlist} />
          <IncomeCalendar calData={calData} />
        </>
      )}
    </div>
  )
}
