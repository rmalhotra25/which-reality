import { useEffect, useState } from 'react'
import { api } from '../api'

// Answer block, shown at the top of the ticker lookup. One
// recommendation in plain words (Buy Big, Buy Small, Hold, Sell)
// with the evidence behind it: price and trend, analyst view,
// news and catalysts, insider activity, and the roadmap. The
// recommendation is framed conditionally, because TradeIQ does
// not track what the user owns: every tier carries an "if you
// own it" line and an "if you don't own it" line. The data is
// fetched automatically when the ticker changes, so the answer
// is the first thing on the page, not behind a button.
//
// Visuals first, words as support: the verdict is a big colored
// badge, the price has a sparkline, and the four gauges below it
// (trend, valuation, catalyst, insiders) are small visuals with
// one caption line each. The evidence cards and the conditional
// lines stay below as supporting words.

const TIER_COLORS = {
  buy_big: '#68d391',
  buy_small: '#63b3ed',
  hold: '#f6e05e',
  sell: '#fc8181',
}

const S = {
  card: {
    background: '#131825', border: '1px solid #2d3748', borderRadius: '12px',
    padding: '20px',
  },
  header: { display: 'flex', flexWrap: 'wrap', alignItems: 'baseline', gap: '10px' },
  name: { fontSize: '20px', fontWeight: 800, color: '#e2e8f0' },
  ticker: { fontSize: '14px', color: '#a0aec0', fontWeight: 700 },
  price: { fontSize: '26px', fontWeight: 800, color: '#e2e8f0' },
  badgeBlock: (tone) => ({
    display: 'inline-block', fontSize: '24px', fontWeight: 800,
    letterSpacing: '0.01em', color: '#1a202c',
    background: TIER_COLORS[tone] || '#a0aec0',
    borderRadius: '10px', padding: '8px 16px', marginTop: '12px',
    lineHeight: 1.2,
  }),
  reason: { fontSize: '15px', color: '#e2e8f0', lineHeight: 1.5, marginTop: '10px' },
  ownLine: { fontSize: '13px', color: '#a0aec0', lineHeight: 1.6, marginTop: '6px' },
  note: { fontSize: '12px', color: '#718096', lineHeight: 1.5 },
  gaugeGrid: {
    display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
    gap: '12px', marginTop: '16px',
  },
  gauge: {
    background: '#0f1520', border: '1px solid #2d3748', borderRadius: '10px',
    padding: '12px',
  },
  gaugeTitle: {
    fontSize: '11px', fontWeight: 700, letterSpacing: '0.08em',
    color: '#718096', textTransform: 'uppercase', marginBottom: '8px',
  },
  gaugeCaption: { fontSize: '12px', color: '#a0aec0', lineHeight: 1.5, marginTop: '6px' },
  gaugeValue: { fontSize: '16px', fontWeight: 800, color: '#e2e8f0' },
  grid: {
    display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
    gap: '12px', marginTop: '16px',
  },
  evidence: {
    background: '#0f1520', border: '1px solid #2d3748', borderRadius: '10px',
    padding: '14px',
  },
  evidenceTitle: {
    fontSize: '11px', fontWeight: 700, letterSpacing: '0.08em',
    color: '#718096', textTransform: 'uppercase', marginBottom: '8px',
  },
  evidenceLine: { fontSize: '13px', color: '#e2e8f0', lineHeight: 1.6 },
  evidenceSub: { fontSize: '12px', color: '#a0aec0', lineHeight: 1.5, marginTop: '4px' },
}

function money(v) {
  if (v == null) return 'n/a'
  if (Math.abs(v) >= 1e9) return `$${(v / 1e9).toFixed(1)}B`
  if (Math.abs(v) >= 1e6) return `$${(v / 1e6).toFixed(1)}M`
  if (Math.abs(v) >= 1e3) return `$${(v / 1e3).toFixed(1)}K`
  return `$${v}`
}

function trendWord(above) {
  if (above === true) return 'above'
  if (above === false) return 'below'
  return 'unknown vs'
}

function dotColor(above) {
  if (above === true) return '#68d391'
  if (above === false) return '#fc8181'
  return '#718096'
}

// Sparkline of the last 30 settled closes, inline SVG, no library.
// Green when the last close is above the first, red when below.
// The 50-day and 200-day averages draw as faint dashed reference
// lines when they are present, clamped to the chart.
function Sparkline({ closes, ma50, ma200 }) {
  if (!closes || closes.length < 2) {
    return <div style={S.note}>Price history unavailable.</div>
  }
  const w = 100
  const h = 40
  const lo = Math.min(...closes)
  const hi = Math.max(...closes)
  const span = hi - lo || 1
  const x = (i) => (i / (closes.length - 1)) * w
  const y = (v) => h - ((v - lo) / span) * h
  const points = closes.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')
  const up = closes[closes.length - 1] >= closes[0]
  const color = up ? '#68d391' : '#fc8181'
  const clampY = (v) => Math.max(0, Math.min(h, y(v)))
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none"
      style={{ width: '100%', height: '48px', display: 'block' }}
      aria-label="Price over the last 30 sessions">
      {ma50 != null && (
        <line x1="0" x2={w} y1={clampY(ma50)} y2={clampY(ma50)}
          stroke="#63b3ed" strokeWidth="0.6" strokeDasharray="3 2" opacity="0.7" />
      )}
      {ma200 != null && (
        <line x1="0" x2={w} y1={clampY(ma200)} y2={clampY(ma200)}
          stroke="#f6e05e" strokeWidth="0.6" strokeDasharray="3 2" opacity="0.7" />
      )}
      <polyline points={points} fill="none" stroke={color}
        strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  )
}

// Horizontal position bar, 0 to 100, with a marker dot at pct.
// Renders nothing but a grey track when pct is null.
function PositionBar({ pct }) {
  if (pct == null) {
    return (
      <div>
        <div style={{ height: '8px', borderRadius: '4px', background: '#2d3748' }} />
        <div style={{ ...S.gaugeCaption, color: '#718096' }}>52-week range unavailable.</div>
      </div>
    )
  }
  const clamped = Math.max(0, Math.min(100, pct))
  return (
    <div>
      <div style={{ position: 'relative', height: '8px', borderRadius: '4px', background: '#2d3748' }}>
        <div style={{
          position: 'absolute', left: `${clamped}%`, top: '-3px',
          width: '14px', height: '14px', borderRadius: '50%',
          background: '#e2e8f0', transform: 'translateX(-50%)',
        }} />
      </div>
      <div style={S.gaugeCaption}>{clamped}% up the 52-week range.</div>
    </div>
  )
}

// Valuation bar: price, DCF base, and analyst mean as markers on
// one shared scale. Falls back to price vs analyst mean when the
// DCF is null, and to a plain note when nothing is available.
function ValuationBar({ price, dcfBase, mean }) {
  const marks = []
  if (price != null) marks.push({ label: 'Price', value: price, color: '#e2e8f0' })
  if (dcfBase != null) marks.push({ label: 'DCF', value: dcfBase, color: '#68d391' })
  if (mean != null) marks.push({ label: 'Analyst', value: mean, color: '#63b3ed' })
  if (marks.length === 0) {
    return <div style={{ ...S.gaugeCaption, color: '#718096' }}>Valuation unavailable.</div>
  }
  const values = marks.map((m) => m.value)
  let lo = Math.min(...values)
  let hi = Math.max(...values)
  if (hi - lo < 1e-9) { lo -= 1; hi += 1 }
  const pos = (v) => ((v - lo) / (hi - lo)) * 100
  return (
    <div>
      <div style={{ position: 'relative', height: '8px', borderRadius: '4px', background: '#2d3748' }}>
        {marks.map((m) => (
          <div key={m.label} title={`${m.label} $${m.value}`} style={{
            position: 'absolute', left: `${pos(m.value)}%`, top: '-3px',
            width: '14px', height: '14px', borderRadius: '50%',
            background: m.color, transform: 'translateX(-50%)',
          }} />
        ))}
      </div>
      <div style={S.gaugeCaption}>
        {marks.map((m) => `${m.label} $${m.value}`).join('  |  ')}.
      </div>
    </div>
  )
}

// Analyst target range bar: low to high, with the mean and the
// current price marked. Renders a plain note when no targets exist.
function TargetRangeBar({ low, mean, high, price }) {
  if (low == null || high == null || mean == null) {
    return <div style={{ ...S.evidenceSub, color: '#718096' }}>No analyst price target could be verified.</div>
  }
  let lo = low
  let hi = high
  if (hi - lo < 1e-9) { lo -= 1; hi += 1 }
  const pos = (v) => Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100))
  return (
    <div>
      <div style={{ position: 'relative', height: '8px', borderRadius: '4px', background: '#2d3748', marginTop: '8px' }}>
        <div style={{
          position: 'absolute', left: `${pos(mean)}%`, top: '-3px',
          width: '14px', height: '14px', borderRadius: '50%',
          background: '#63b3ed', transform: 'translateX(-50%)',
        }} title={`Analyst mean $${mean}`} />
        {price != null && (
          <div style={{
            position: 'absolute', left: `${pos(price)}%`, top: '-3px',
            width: '14px', height: '14px', borderRadius: '50%',
            background: '#e2e8f0', border: '2px solid #1a202c', transform: 'translateX(-50%)',
          }} title={`Price $${price}`} />
        )}
      </div>
      <div style={S.evidenceSub}>
        Low ${low}, mean ${mean}, high ${high}
        {price != null && <span>, price ${price} marked white</span>}.
      </div>
    </div>
  )
}

export default function AnswerSection({ ticker }) {
  const [answer, setAnswer] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!ticker) return
    let cancelled = false
    setLoading(true)
    setError(null)
    setAnswer(null)
    api.recommendation.get(ticker)
      .then((data) => { if (!cancelled) setAnswer(data) })
      .catch((err) => { if (!cancelled) setError(err.message || 'Answer failed to load') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [ticker])

  if (!ticker) return null
  if (loading) {
    return (
      <div style={S.card}>
        <div style={S.note}>Loading the answer…</div>
      </div>
    )
  }
  if (error) {
    return (
      <div style={S.card}>
        <div style={{ ...S.note, color: '#fc8181' }}>Answer unavailable: {error}</div>
      </div>
    )
  }
  if (!answer) return null
  if (answer.status === 'unavailable') {
    return (
      <div style={S.card}>
        <div style={{ ...S.note, color: '#fc8181' }}>Answer unavailable: {answer.reason}</div>
      </div>
    )
  }

  const rec = answer.recommendation || {}
  const ev = answer.evidence || {}
  const price = ev.price || {}
  const analyst = ev.analyst || {}
  const news = ev.news || {}
  const insider = ev.insider || {}
  const roadmap = ev.roadmap || {}
  const ins = insider.summary || {}

  const analystLine = analyst.mean != null
    ? `Analysts see $${analyst.mean} on average (low $${analyst.low}, high $${analyst.high}), ${analyst.mean_vs_now_pct != null ? `${analyst.mean_vs_now_pct > 0 ? '+' : ''}${analyst.mean_vs_now_pct}% vs today` : ''}.`
    : 'No analyst price target could be verified.'
  const analystCounts = analyst.total != null
    ? `${analyst.buy} buy, ${analyst.hold} hold, ${analyst.sell} sell out of ${analyst.total} analysts.`
    : null

  const catalystLines = (news.catalysts || []).map((c) => `${c.title} (${Math.round(c.age_hours)}h ago)`)
  const headwindLines = (news.headwinds || []).map((h) => h.title)
  const freshCatalyst = (news.catalysts || []).find((c) => c.age_hours <= 48) || null

  const insiderLine = ins.signal === 'quiet'
    ? 'No open-market insider trades in the last 90 days.'
    : ins.signal === 'buying'
      ? `Insiders are buying: ${ins.buys.count} buys worth ${money(ins.buys.value)} vs ${ins.sells.count} sells worth ${money(ins.sells.value)} in 90 days.`
      : ins.signal === 'selling'
        ? `Insiders are selling: ${ins.sells.count} sells worth ${money(ins.sells.value)} vs ${ins.buys.count} buys worth ${money(ins.buys.value)} in 90 days.`
        : `Insiders are mixed: ${ins.buys.count} buys worth ${money(ins.buys.value)}, ${ins.sells.count} sells worth ${money(ins.sells.value)} in 90 days.`
  const insider10b5Note = ins.sell_10b5_value != null && ins.sells.value > 0
    && ins.sell_10b5_value >= ins.sells.value * 0.5
    ? `Most of that selling (${money(ins.sell_10b5_value)}) was under pre-arranged 10b5-1 plans, which is routine and not a signal on its own.`
    : null

  const buyValue = (ins.buys && ins.buys.value) || 0
  const sellValue = (ins.sells && ins.sells.value) || 0
  const insiderTotal = buyValue + sellValue
  const buyShare = insiderTotal > 0 ? (buyValue / insiderTotal) * 100 : null

  return (
    <div style={S.card}>
      <div style={S.header}>
        <span style={S.name}>{answer.name}</span>
        <span style={S.ticker}>{answer.ticker}</span>
        {answer.price != null ? (
          <span style={S.price}>${answer.price}</span>
        ) : (
          <span style={{ fontSize: '14px', fontWeight: 700, color: '#a0aec0' }}>price unavailable</span>
        )}
      </div>
      <div style={S.badgeBlock(rec.tier)}>{rec.label}</div>
      <div style={{ marginTop: '14px' }}>
        <Sparkline closes={answer.price_history || []} ma50={price.ma50} ma200={price.ma200} />
        <div style={{ ...S.note, marginTop: '4px' }}>
          Last 30 sessions
          {price.ma50 != null && <span>, blue dashed is the 50-day</span>}
          {price.ma200 != null && <span>, yellow dashed is the 200-day</span>}
          .
        </div>
      </div>
      <div style={S.reason}>{rec.reason}</div>
      <div style={S.ownLine}>{rec.if_you_own_it}</div>
      <div style={S.ownLine}>{rec.if_you_dont_own_it}</div>
      {rec.blocked_by && rec.blocked_by.length > 0 && (
        <div style={{ ...S.note, marginTop: '8px' }}>Held back: {rec.blocked_by.join('; ')}</div>
      )}

      <div style={S.gaugeGrid}>
        <div style={S.gauge}>
          <div style={S.gaugeTitle}>Trend</div>
          <PositionBar pct={price.week52 ? price.week52.position_pct : null} />
          <div style={{ display: 'flex', gap: '12px', marginTop: '8px' }}>
            <span style={{ fontSize: '12px', color: '#a0aec0' }}>
              <span style={{ display: 'inline-block', width: '10px', height: '10px', borderRadius: '50%', background: dotColor(price.above_ma50), marginRight: '4px' }} />
              50-day {trendWord(price.above_ma50)}
            </span>
            <span style={{ fontSize: '12px', color: '#a0aec0' }}>
              <span style={{ display: 'inline-block', width: '10px', height: '10px', borderRadius: '50%', background: dotColor(price.above_ma200), marginRight: '4px' }} />
              200-day {trendWord(price.above_ma200)}
            </span>
          </div>
        </div>

        <div style={S.gauge}>
          <div style={S.gaugeTitle}>Valuation</div>
          <ValuationBar price={answer.price} dcfBase={analyst.dcf_base} mean={analyst.mean} />
          {analyst.dcf_base != null && (
            <div style={S.gaugeCaption}>
              DCF base ${analyst.dcf_base}
              {analyst.dcf_bear != null && analyst.dcf_bull != null && (
                <span> (bear ${analyst.dcf_bear} to bull ${analyst.dcf_bull})</span>
              )}
              .
            </div>
          )}
        </div>

        <div style={S.gauge}>
          <div style={S.gaugeTitle}>Catalyst</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{
              display: 'inline-block', width: '14px', height: '14px',
              borderRadius: '50%',
              background: freshCatalyst ? '#68d391' : '#718096',
            }} />
            <span style={S.gaugeValue}>{freshCatalyst ? 'Fresh' : 'None fresh'}</span>
          </div>
          <div style={S.gaugeCaption}>
            {freshCatalyst ? freshCatalyst.title : 'No direct catalyst in the last 48 hours.'}
          </div>
        </div>

        <div style={S.gauge}>
          <div style={S.gaugeTitle}>Insiders</div>
          {buyShare == null ? (
            <div style={{ ...S.gaugeCaption, color: '#718096' }}>No open-market insider trades in 90 days.</div>
          ) : (
            <div>
              <div style={{ display: 'flex', height: '8px', borderRadius: '4px', overflow: 'hidden' }}>
                <div style={{ width: `${buyShare}%`, background: '#68d391' }} />
                <div style={{ width: `${100 - buyShare}%`, background: '#fc8181' }} />
              </div>
              <div style={S.gaugeCaption}>
                {ins.signal === 'quiet' ? 'No signal.' : `Signal: ${ins.signal}. `}
                Buys {money(buyValue)}, sells {money(sellValue)}.
              </div>
            </div>
          )}
        </div>
      </div>

      <div style={S.grid}>
        <div style={S.evidence}>
          <div style={S.evidenceTitle}>Price and trend</div>
          <div style={S.evidenceLine}>
            {price.current != null ? `$${price.current}` : 'Price unavailable'}
            {price.ma50 != null && (
              <span>, {trendWord(price.above_ma50)} its 50-day average of ${price.ma50}</span>
            )}
            {price.ma200 != null && (
              <span> and {trendWord(price.above_ma200)} its 200-day average of ${price.ma200}</span>
            )}
            .
          </div>
          {price.week52 && (
            <div style={S.evidenceSub}>
              52-week range ${price.week52.low} to ${price.week52.high}
              {price.week52.position_pct != null && (
                <span>, now {price.week52.position_pct}% up the range</span>
              )}
              .
            </div>
          )}
        </div>

        <div style={S.evidence}>
          <div style={S.evidenceTitle}>Analyst view</div>
          <div style={S.evidenceLine}>{analystLine}</div>
          <TargetRangeBar low={analyst.low} mean={analyst.mean} high={analyst.high} price={answer.price} />
          {analystCounts && <div style={S.evidenceSub}>{analystCounts}</div>}
          {analyst.dcf_base != null && (
            <div style={S.evidenceSub}>
              DCF base ${analyst.dcf_base}
              {analyst.dcf_bear != null && analyst.dcf_bull != null && (
                <span> (bear ${analyst.dcf_bear} to bull ${analyst.dcf_bull})</span>
              )}
              .
            </div>
          )}
        </div>

        <div style={S.evidence}>
          <div style={S.evidenceTitle}>News and catalysts</div>
          {catalystLines.length > 0 ? (
            <div style={S.evidenceLine}>Catalysts: {catalystLines.join('; ')}.</div>
          ) : (
            <div style={S.evidenceLine}>No fresh catalyst in the last 7 days.</div>
          )}
          {headwindLines.length > 0 ? (
            <div style={S.evidenceSub}>Headwinds: {headwindLines.join('; ')}.</div>
          ) : (
            <div style={S.evidenceSub}>No headwinds flagged.</div>
          )}
          {(news.catalysts || []).length > 0 && (
            <div style={S.evidenceSub}>{(news.catalysts || [])[0].detail}</div>
          )}
        </div>

        <div style={S.evidence}>
          <div style={S.evidenceTitle}>Insider activity</div>
          <div style={S.evidenceLine}>{insiderLine}</div>
          {insider10b5Note && (
            <div style={S.evidenceSub}>{insider10b5Note}</div>
          )}
          {insider.source && (
            <div style={S.evidenceSub}>Source: {insider.source === 'edgar' ? 'SEC Form 4 filings' : 'yfinance'}.</div>
          )}
          {(ins.notable || []).length > 0 && (
            <div style={S.evidenceSub}>
              Largest: {(ins.notable || []).slice(0, 2).map((n) => `${n.insider || 'An insider'} ${n.code === 'P' ? 'bought' : 'sold'} ${money(n.value)}`).join('; ')}.
            </div>
          )}
        </div>
      </div>

      <div style={{ ...S.note, marginTop: '14px' }}>
        Roadmap: {roadmap.grade ? `Story grade ${roadmap.grade}` : 'grade unknown'}
        {roadmap.longterm_verdict ? `, long-term lane ${roadmap.longterm_verdict}` : ''}
        {roadmap.earnings_date ? `, next earnings ${roadmap.earnings_date}` : ', next earnings date unknown'}
        .
      </div>
      {roadmap.what_would_change && (
        <div style={{ ...S.note, marginTop: '4px' }}>{roadmap.what_would_change}</div>
      )}
      {answer.notes && answer.notes.length > 0 && (
        <div style={{ ...S.note, marginTop: '8px' }}>{answer.notes.join(' ')}</div>
      )}
    </div>
  )
}
