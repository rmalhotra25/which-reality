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

const S = {
  card: {
    background: '#131825', border: '1px solid #2d3748', borderRadius: '12px',
    padding: '20px',
  },
  header: { display: 'flex', flexWrap: 'wrap', alignItems: 'baseline', gap: '10px' },
  name: { fontSize: '20px', fontWeight: 800, color: '#e2e8f0' },
  ticker: { fontSize: '14px', color: '#a0aec0', fontWeight: 700 },
  price: { fontSize: '26px', fontWeight: 800, color: '#e2e8f0' },
  badge: (tone) => ({
    fontSize: '22px', fontWeight: 800, letterSpacing: '0.01em',
    color: tone === 'buy_big' ? '#68d391' : tone === 'buy_small' ? '#63b3ed'
      : tone === 'hold' ? '#f6e05e' : '#fc8181',
    lineHeight: 1.2,
  }),
  reason: { fontSize: '15px', color: '#e2e8f0', lineHeight: 1.5, marginTop: '8px' },
  ownLine: { fontSize: '13px', color: '#a0aec0', lineHeight: 1.6, marginTop: '6px' },
  note: { fontSize: '12px', color: '#718096', lineHeight: 1.5 },
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
  if (v == null) return '—'
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
        <div style={S.note}>Answer unavailable: {answer.reason}</div>
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

  return (
    <div style={S.card}>
      <div style={S.header}>
        <span style={S.name}>{answer.name}</span>
        <span style={S.ticker}>{answer.ticker}</span>
        <span style={S.price}>${answer.price}</span>
      </div>
      <div style={{ ...S.badge(rec.tier), marginTop: '12px' }}>{rec.label}</div>
      <div style={S.reason}>{rec.reason}</div>
      <div style={S.ownLine}>{rec.if_you_own_it}</div>
      <div style={S.ownLine}>{rec.if_you_dont_own_it}</div>
      {rec.blocked_by && rec.blocked_by.length > 0 && (
        <div style={{ ...S.note, marginTop: '8px' }}>Held back: {rec.blocked_by.join('; ')}</div>
      )}

      <div style={S.grid}>
        <div style={S.evidence}>
          <div style={S.evidenceTitle}>Price and trend</div>
          <div style={S.evidenceLine}>
            ${price.current}
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
