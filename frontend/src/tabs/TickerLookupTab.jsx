import { useEffect, useState } from 'react'
import { api } from '../api'
import AnswerSection from './AnswerSection'
import StorySection from './StorySection'

// Ticker Lookup tab: a query, not a trade. Type a ticker, get the same
// rule registry check the alert engine would run for that ticker, at
// the data timestamp shown. No alert is fired, no journal row is
// created, no notification is sent. A passing setup shows the rule
// result for that ticker at that time, not an instruction to trade.

const S = {
  root: { display: 'flex', flexDirection: 'column', gap: '16px' },
  form: { display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' },
  input: {
    padding: '9px 12px', fontSize: '15px', fontWeight: 700, letterSpacing: '0.05em',
    background: '#0f1520', border: '1px solid #2d3748', borderRadius: '8px',
    color: '#e2e8f0', width: '160px', textTransform: 'uppercase',
  },
  button: {
    padding: '9px 18px', background: '#2b6cb0', color: '#fff', border: 'none',
    borderRadius: '8px', cursor: 'pointer', fontSize: '14px', fontWeight: 700,
  },
  check: { fontSize: '13px', color: '#a0aec0', display: 'flex', gap: '6px', alignItems: 'center' },
  error: {
    background: '#2d1515', border: '1px solid #742a2a', borderRadius: '10px',
    padding: '16px', color: '#fc8181', fontSize: '13px',
  },
  card: {
    background: '#131825', border: '1px solid #2d3748', borderRadius: '10px',
    padding: '16px',
  },
  sectionLabel: {
    fontSize: '11px', fontWeight: 700, letterSpacing: '0.08em',
    color: '#718096', textTransform: 'uppercase', marginBottom: '8px',
  },
  tickerBig: { fontSize: '20px', fontWeight: 800, color: '#e2e8f0' },
  priceBig: { fontSize: '26px', fontWeight: 800, color: '#e2e8f0' },
  meta: { fontSize: '12px', color: '#718096', marginTop: '4px' },
  grid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '12px' },
  stat: { display: 'flex', flexDirection: 'column', gap: '2px' },
  statLabel: { fontSize: '10px', color: '#4a5568', textTransform: 'uppercase', letterSpacing: '0.06em' },
  statValue: { fontSize: '15px', fontWeight: 700, color: '#e2e8f0' },
  statSub: { fontSize: '11px', color: '#718096' },
  pill: (bg, border, text) => ({
    display: 'inline-block', padding: '2px 9px', borderRadius: '20px', fontSize: '10px',
    fontWeight: 700, letterSpacing: '0.05em',
    background: bg, border: `1px solid ${border}`, color: text,
  }),
  table: { width: '100%', borderCollapse: 'collapse', fontSize: '12px' },
  th: {
    padding: '8px 10px', textAlign: 'left', color: '#4a5568', fontWeight: 600,
    borderBottom: '1px solid #1e2535', whiteSpace: 'nowrap',
    textTransform: 'uppercase', fontSize: '10px', letterSpacing: '0.06em',
  },
  td: { padding: '8px 10px', borderBottom: '1px solid #1a1f2e', color: '#a0aec0', verticalAlign: 'top' },
  condBox: {
    background: '#0f1520', border: '1px solid #1e2535', borderRadius: '6px',
    padding: '8px 10px', fontSize: '11px', color: '#718096', marginTop: '8px',
    fontFamily: 'monospace', lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
  },
  ruleBox: {
    background: '#0f1520', border: '1px solid #2b6cb0', borderRadius: '8px',
    padding: '12px 14px', fontSize: '13px', color: '#a0aec0', lineHeight: 1.6, marginTop: '8px',
  },
  verdictCard: (tone) => ({
    background: tone === 'buy' ? '#12261a' : tone === 'wait' ? '#16233a' : tone === 'avoid' ? '#2d1515' : '#1d1a12',
    border: tone === 'buy' ? '1px solid #276749' : tone === 'wait' ? '1px solid #2b6cb0' : tone === 'avoid' ? '1px solid #742a2a' : '1px solid #975a16',
    borderRadius: '12px', padding: '20px',
  }),
  verdictBig: (tone) => ({
    fontSize: '30px', fontWeight: 800, letterSpacing: '0.01em',
    color: tone === 'buy' ? '#68d391' : tone === 'wait' ? '#90cdf4' : tone === 'avoid' ? '#fc8181' : '#f6e05e', lineHeight: 1.2,
  }),
  verdictReason: { fontSize: '15px', color: '#e2e8f0', lineHeight: 1.5, marginTop: '8px' },
  verdictList: { fontSize: '13px', color: '#a0aec0', lineHeight: 1.7, margin: '10px 0 0', paddingLeft: '18px' },
  verdictNote: { fontSize: '13px', color: '#a0aec0', lineHeight: 1.5, marginTop: '12px' },
  optionRow: {
    display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
    gap: '12px', marginTop: '16px',
  },
  optionBox: {
    background: '#131825', border: '1px solid #2d3748', borderRadius: '10px', padding: '14px',
  },
  optionTitle: (tone) => ({
    fontSize: '17px', fontWeight: 800,
    color: tone === 'buy' ? '#68d391' : tone === 'sell' ? '#68d391' : '#a0aec0',
  }),
  optionLine: { fontSize: '13px', color: '#e2e8f0', lineHeight: 1.6, marginTop: '6px' },
  optionSub: { fontSize: '12px', color: '#718096', lineHeight: 1.5, marginTop: '6px' },
  details: {
    background: '#131825', border: '1px solid #2d3748', borderRadius: '10px', padding: '16px',
  },
  summary: { fontSize: '12px', fontWeight: 700, letterSpacing: '0.08em', color: '#a0aec0', textTransform: 'uppercase', cursor: 'pointer' },
  note: { fontSize: '12px', color: '#718096', lineHeight: 1.5 },
}

function val(v) {
  if (v === null || v === undefined) return 'unknown'
  if (typeof v === 'boolean') return v ? 'yes' : 'no'
  if (typeof v === 'number') return String(v)
  return String(v)
}

function fmtPct(v) {
  if (v === null || v === undefined) return 'unknown'
  const n = Number(v)
  if (Number.isNaN(n)) return String(v)
  return n.toFixed(1)
}

function ResultPill({ result, status }) {
  if (result === 'pass') return <span style={S.pill('#15301f', '#276749', '#68d391')}>PASS ({status})</span>
  if (result === 'suppressed') return <span style={S.pill('#3d2f10', '#975a16', '#f6e05e')}>SUPPRESSED ({status})</span>
  if (result === 'not_evaluated') return <span style={S.pill('#1a202c', '#4a5568', '#a0aec0')}>NOT EVALUATED ({status})</span>
  return <span style={S.pill('#2d1515', '#742a2a', '#fc8181')}>FAIL ({status})</span>
}

function ChainTable({ rows, side }) {
  if (!rows || rows.length === 0) return <div style={S.note}>No {side} rows.</div>
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={S.table}>
        <thead>
          <tr>
            <th>Strike</th><th>Expiry</th><th>DTE</th><th>Bid</th><th>Ask</th>
            <th>Mid</th><th>Price source</th><th>Delta</th><th>IV %</th><th>OI</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td>${val(r.strike)}</td><td>{val(r.expiry)}</td><td>{val(r.dte)}</td>
              <td>${val(r.bid)}</td><td>${val(r.ask)}</td><td>${val(r.mid)}</td>
              <td>{val(r.price_source)}</td><td>{r.delta != null ? Number(r.delta).toFixed(2) : 'unknown'}</td>
              <td>{val(r.iv_pct)}</td><td>{val(r.open_interest)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function plainVerdictLabel(decision, label) {
  if (decision === 'buy') return 'Buy now'
  if (decision === 'wait') return 'Wait for entry'
  if (decision === 'avoid') return 'Avoid for now'
  if (decision === 'cannot_judge') return 'Cannot judge'
  return label || 'Unknown'
}

function trendLine(trend, price) {
  if (!trend) return `Price $${val(price)}`
  const part = (above, ma, direction, label) =>
    above == null
      ? `${label} average unknown`
      : `${above ? 'above' : 'below'} its ${label} average of $${val(ma)} (${val(direction)})`
  return `Price $${val(price)}, ${part(trend.above_ma50, trend.ma50, trend.ma50_direction, '50-day')} and ${part(trend.above_ma200, trend.ma200, trend.ma200_direction, '200-day')}`
}

function dcfPresentationFor(longterm, price) {
  if (!longterm || !longterm.dcf) return null
  if (longterm.dcf_presentation) return longterm.dcf_presentation
  const dcf = longterm.dcf
  const wide = !!(dcf.exit_multiple_check && dcf.exit_multiple_check.wide_disagreement)
  const implied = dcf.reverse_dcf_implied_growth_pct
  const high = implied != null && Number(implied) > 25
  const unreliable = wide || high
  const base = dcf.fair_value.base
  let warning = null
  if (unreliable) {
    warning = `DCF is not a reliable price anchor for this name. Do not treat $${base} as an intrinsic value.`
    if (longterm.verdict === 'weak') {
      warning += ` Treat it as overvalued on current cash flows, not as an $${base} intrinsic value.`
    }
  }
  return {
    bear: dcf.fair_value.bear,
    base,
    bull: dcf.fair_value.bull,
    range_label: `$${dcf.fair_value.bear} to $${dcf.fair_value.bull}`,
    framing: `On today's cash flows, this DCF says $${base}, market is $${price}, so the market is paying for growth not yet in cash flows. This is not a price target.`,
    unreliable,
    high_implied_growth: high,
    wide_terminal_disagreement: wide,
    implied_growth_pct: implied,
    warning,
    inputs_line: `Revenue $${val(dcf.revenue_millions)}M, FCF $${val(dcf.fcf_millions)}M (${fmtPct(dcf.fcf_margin_pct)}% margin), revenue growth ${fmtPct(dcf.revenue_growth_pct)}%, WACC ${longterm.wacc ? val(longterm.wacc.wacc_pct) : 'unknown'}%.`,
    exit_multiple_fair_value: dcf.exit_multiple_check ? dcf.exit_multiple_check.fair_value : null,
    gordon_fair_value: dcf.exit_multiple_check ? dcf.exit_multiple_check.gordon_fair_value : null,
    disagreement_pct: dcf.exit_multiple_check ? dcf.exit_multiple_check.disagreement_pct : null,
  }
}

function DcfFraming({ longterm, price }) {
  const p = dcfPresentationFor(longterm, price)
  if (!p) return null
  return (
    <>
      <div style={{ ...S.note, marginTop: '8px', color: '#e2e8f0', fontSize: '13px' }}>{p.framing}</div>
      {p.warning && (
        <div style={{ ...S.note, marginTop: '6px', color: '#f6e05e', fontSize: '13px' }}>{p.warning}</div>
      )}
    </>
  )
}

function DcfSummary({ longterm, price }) {
  const p = dcfPresentationFor(longterm, price)
  if (!p) return null
  return (
    <div>
      <div style={{ fontSize: '15px', fontWeight: 700, color: '#e2e8f0' }}>
        DCF base ${val(p.base)} (bear ${val(p.bear)} to bull ${val(p.bull)})
      </div>
      <DcfFraming longterm={longterm} price={price} />
      <div style={S.note}>Inputs: {p.inputs_line}</div>
    </div>
  )
}

function methodLine(method) {
  if (!method || method.status !== 'ok' || !method.fair_value) return null
  return `base $${val(method.fair_value.base)} (bear $${val(method.fair_value.bear)} to bull $${val(method.fair_value.bull)})`
}

function greekLine(g) {
  if (!g) return 'Greeks: Missing'
  const fmt = (v) => (v === null || v === undefined ? 'Missing' : Number(v).toFixed(2))
  return `Delta ${fmt(g.delta)}, gamma ${fmt(g.gamma)}, vega ${fmt(g.vega)}, theta ${fmt(g.theta_seller)} per day`
}

function DcfMethodsSummary({ longterm, price }) {
  const p = dcfPresentationFor(longterm, price)
  const methods = longterm && longterm.dcf_methods
  if (!p && !methods) return null
  return (
    <div>
      {p && (
        <div style={{ fontSize: '15px', fontWeight: 700, color: '#e2e8f0' }}>
          Statements anchor: DCF base ${val(p.base)} (bear ${val(p.bear)} to bull ${val(p.bull)}){longterm && longterm.verdict === 'weak' ? ', overvalued on current cash flows.' : '.'}
        </div>
      )}
      {p && (<DcfFraming longterm={longterm} price={price} />)}
      {methods && (
        <>
          <div style={S.note}>Forward scenarios: {methodLine(methods.forward) || 'Missing, see details.'}</div>
          <div style={S.note}>Normalized: {methodLine(methods.normalized) || 'Missing, see details.'}</div>
          <div style={S.note}>
            Sum of parts: {methods.sum_of_parts && methods.sum_of_parts.status === 'ok'
              ? `operating ${methodLine(methods.sum_of_parts)}; future upside: ${methods.sum_of_parts.upside && methods.sum_of_parts.upside.status === 'supplied' ? `$${val(methods.sum_of_parts.upside.per_share)} per share, separate` : 'Missing'}`
              : 'Missing, no segment data from a wired source.'}
          </div>
          <details style={{ marginTop: '8px' }}>
            <summary style={S.summary}>DCF method assumptions</summary>
            <div style={{ marginTop: '8px' }}>
              {p && (<div style={S.note}>Statements anchor inputs: {p.inputs_line}</div>)}
              {methods.forward && (<div style={S.note}>Forward scenarios: {methods.forward.assumptions || methods.forward.reason}</div>)}
              {methods.normalized && (<div style={S.note}>Normalized: {methods.normalized.assumptions || methods.normalized.reason} Risk free source: {val(methods.normalized.risk_free_source)}.</div>)}
              {methods.sum_of_parts && (<div style={S.note}>Sum of parts: {methods.sum_of_parts.reason || methods.sum_of_parts.framing} Operating total is never blended with future upside.</div>)}
              {methods.sum_of_parts && methods.sum_of_parts.segments && methods.sum_of_parts.segments.length > 0 && (
                <div style={S.note}>Segments: {methods.sum_of_parts.segments.map((s) => `${val(s.name)} $${val(s.fair_value_millions.base)}M base`).join(', ')}.</div>
              )}
              {methods.note && (<div style={S.note}>{methods.note}</div>)}
            </div>
          </details>
        </>
      )}
      {!methods && p && (<div style={S.note}>Inputs: {p.inputs_line}</div>)}
    </div>
  )
}

function StrategyLine({ strategy, label }) {
  if (!strategy) return null
  if (strategy.status !== 'ok') return (<div style={S.note}>{label}: Missing, {val(strategy.reason)}</div>)
  if (label === 'Best call' || label === 'Best put') {
    return (<div style={S.note}>{label}: buy ${val(strategy.strike)} strike, expiry {val(strategy.expiry)}, cost ${val(strategy.premium_per_contract)} per contract, breakeven ${val(strategy.breakeven)}, {val(strategy.key_greek)}.</div>)
  }
  if (label === 'Straddle') {
    return (<div style={S.note}>Straddle: ${val(strategy.strike)} strike, expiry {val(strategy.expiry)}, cost ${val(strategy.total_cost_per_contract)} per contract, breakevens ${val(strategy.lower_breakeven)} to ${val(strategy.upper_breakeven)}, {val(strategy.key_greek)}.</div>)
  }
  return (<div style={S.note}>Iron condor: short ${val(strategy.short_put_strike)} put and ${val(strategy.short_call_strike)} call, expiry {val(strategy.expiry)}, credit ${val(strategy.net_credit_per_contract)} per contract, max loss ${val(strategy.max_loss_per_contract)}, {val(strategy.key_greek)}.</div>)
}

function OptionStrategiesSummary({ strategies }) {
  if (!strategies) {
    return (<div style={S.note}>Options Strategies: unavailable, no strategies data was returned.</div>)
  }
  if (!strategies.available) {
    return (
      <div>
        <div style={S.note}>Options Strategies: unavailable, {val(strategies.reason)}</div>
        {strategies.chain_source && (
          <div style={S.note}>Chain source: {val(strategies.chain_source)}{strategies.chain_source === 'cboe_delayed' ? ' (delayed quotes, about 15 minutes delayed)' : ''}.</div>
        )}
      </div>
    )
  }
  return (
    <div>
      <div style={S.note}>Options Strategies, expiry {val(strategies.expiry)} ({val(strategies.dte)} days, nearest to 21 days). Model-ranked opportunity, not a prediction or guarantee.</div>
      {strategies.chain_source && (
        <div style={S.note}>Chain source: {val(strategies.chain_source)}{strategies.chain_source === 'cboe_delayed' ? ' (delayed quotes, about 15 minutes delayed)' : ''}.</div>
      )}
      <StrategyLine strategy={strategies.best_call} label="Best call" />
      <StrategyLine strategy={strategies.best_put} label="Best put" />
      <StrategyLine strategy={strategies.straddle} label="Straddle" />
      <StrategyLine strategy={strategies.iron_condor} label="Iron condor" />
      <details style={{ marginTop: '8px' }}>
        <summary style={S.summary}>Strategy Greeks, breakevens, and ranking inputs</summary>
        <div style={{ marginTop: '8px' }}>
          {strategies.best_call && strategies.best_call.status === 'ok' && (
            <div style={S.note}>Best call: {greekLine(strategies.best_call.greeks)}. Breakeven ${val(strategies.best_call.breakeven)}, max loss ${val(strategies.best_call.max_loss_per_contract)} per contract. Rank score {val(strategies.best_call.ranking.score)}: {val(strategies.best_call.ranking.score_weights)} Breakeven distance {val(strategies.best_call.ranking.breakeven_distance_pct)}%, payoff at expected move ${val(strategies.best_call.ranking.payoff_at_expected_move_per_contract)} per contract, IV {val(strategies.best_call.ranking.iv_pct)}%, spread {val(strategies.best_call.ranking.spread_pct)}%, open interest {val(strategies.best_call.ranking.open_interest)}.</div>
          )}
          {strategies.best_put && strategies.best_put.status === 'ok' && (
            <div style={S.note}>Best put: {greekLine(strategies.best_put.greeks)}. Breakeven ${val(strategies.best_put.breakeven)}, max loss ${val(strategies.best_put.max_loss_per_contract)} per contract. Rank score {val(strategies.best_put.ranking.score)}: {val(strategies.best_put.ranking.score_weights)} Breakeven distance {val(strategies.best_put.ranking.breakeven_distance_pct)}%, payoff at expected move ${val(strategies.best_put.ranking.payoff_at_expected_move_per_contract)} per contract, IV {val(strategies.best_put.ranking.iv_pct)}%, spread {val(strategies.best_put.ranking.spread_pct)}%, open interest {val(strategies.best_put.ranking.open_interest)}.</div>
          )}
          {strategies.straddle && strategies.straddle.status === 'ok' && (
            <div style={S.note}>Straddle: {greekLine(strategies.straddle.greeks)}. Breakevens ${val(strategies.straddle.lower_breakeven)} to ${val(strategies.straddle.upper_breakeven)}, cost ${val(strategies.straddle.total_cost_per_contract)} per contract. Rank score {val(strategies.straddle.ranking.score)}: {val(strategies.straddle.ranking.score_weights)} Expected move ${val(strategies.straddle.ranking.expected_move)}, expected move divided by cost {val(strategies.straddle.ranking.expected_move_divided_by_cost)}.</div>
          )}
          {strategies.iron_condor && strategies.iron_condor.status === 'ok' && (
            <div style={S.note}>Iron condor: {greekLine(strategies.iron_condor.greeks)}. Breakevens ${val(strategies.iron_condor.lower_breakeven)} to ${val(strategies.iron_condor.upper_breakeven)}, widths put ${val(strategies.iron_condor.put_width)} and call ${val(strategies.iron_condor.call_width)}, net credit ${val(strategies.iron_condor.net_credit_per_contract)} per contract, max loss ${val(strategies.iron_condor.max_loss_per_contract)} per contract. Rank score {val(strategies.iron_condor.ranking.score)}: {val(strategies.iron_condor.ranking.score_weights)} Short deltas put {val(strategies.iron_condor.ranking.short_put_delta_abs)} and call {val(strategies.iron_condor.ranking.short_call_delta_abs)}, range {val(strategies.iron_condor.ranking.range_pct)}%.</div>
          )}
          <div style={S.note}>{val(strategies.selection_note)} Chain source: {val(strategies.chain_source)}. On a yfinance fallback chain, delta and theta are Black-Scholes estimates from IV, and gamma and vega read Missing. This section does not change verdict put or call gating.</div>
        </div>
      </details>
    </div>
  )
}

function OptionSummary({ option }) {
  if (!option) return null
  return (
    <div style={{ ...S.note, marginTop: '6px', color: '#e2e8f0', fontSize: '13px' }}>
      <strong>{option.label}:</strong> {option.reason}
      {option.decision === 'sell' && (
        <span> Strike ${val(option.strike)}, expiry {val(option.expiry)}, premium ${val(option.premium_per_contract)} per contract, breakeven ${val(option.breakeven)}.</span>
      )}
      {option.decision === 'buy' && (
        <span> Strike ${val(option.strike)}, expiry {val(option.expiry)}, premium ${val(option.premium_per_contract)} per contract, breakeven ${val(option.breakeven)}.</span>
      )}
    </div>
  )
}

function ProposalRow({ proposal, onAlign, adjustScore, setAdjustScore }) {
  if (!proposal) return null
  const hasScore = proposal.proposed_score !== null && proposal.proposed_score !== undefined
  return (
    <div style={{ ...S.optionBox, marginTop: '12px' }}>
      <div style={{ fontSize: '15px', fontWeight: 800, color: '#e2e8f0' }}>
        {proposal.name}: {hasScore ? `${proposal.proposed_score} (${proposal.proposed_label})` : proposal.proposed_label}
        {proposal.alignment_status && proposal.alignment_status !== 'unaligned' && (
          <span style={{ ...S.pill('#15301f', '#276749', '#68d391'), marginLeft: '8px' }}>
            {proposal.alignment_status.toUpperCase()}
            {proposal.aligned_score !== null && proposal.aligned_score !== undefined && ` -> ${proposal.aligned_score}`}
          </span>
        )}
        {proposal.alignment_status === 'unaligned' && (
          <span style={{ ...S.pill('#3d2f10', '#975a16', '#f6e05e'), marginLeft: '8px' }}>AWAITING YOUR ALIGNMENT</span>
        )}
      </div>
      <ul style={S.verdictList}>
        {(proposal.evidence || []).map((ev, i) => <li key={i}>{ev}</li>)}
      </ul>
      <div style={S.note}>Source: {val(proposal.source)} | Confidence: {val(proposal.confidence)}</div>
      {proposal.missing && proposal.missing.length > 0 && (
        <div style={S.note}>Missing, not guessed: {proposal.missing.join(', ')}</div>
      )}
      <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginTop: '8px', alignItems: 'center' }}>
        <button style={S.button} type="button" onClick={() => onAlign(proposal.key, { action: 'accept' })}>Accept</button>
        {hasScore && (
          <>
            <select
              value={adjustScore}
              onChange={(e) => setAdjustScore(e.target.value)}
              style={{ padding: '8px', background: '#0f1520', color: '#e2e8f0', border: '1px solid #2d3748', borderRadius: '8px' }}
              aria-label={`Adjusted score for ${proposal.name}`}
            >
              <option value="0">0</option>
              <option value="5">5</option>
              <option value="10">10</option>
            </select>
            <button style={S.button} type="button" onClick={() => onAlign(proposal.key, { action: 'adjust', score: Number(adjustScore) })}>Adjust score</button>
          </>
        )}
        <button style={S.button} type="button" onClick={() => onAlign(proposal.key, { action: 'missing' })}>Mark missing</button>
      </div>
    </div>
  )
}

function CompanySnapshot({ story, loading, error, price }) {
  if (loading) {
    return (
      <div style={S.card}>
        <div style={S.sectionLabel}>Company snapshot</div>
        <div style={S.note}>Loading the company overview…</div>
      </div>
    )
  }
  if (error) {
    return (
      <div style={S.card}>
        <div style={S.sectionLabel}>Company snapshot</div>
        <div style={{ ...S.note, color: '#fc8181' }}>{error}</div>
      </div>
    )
  }
  if (!story || story.status !== 'ok') {
    return (
      <div style={S.card}>
        <div style={S.sectionLabel}>Company snapshot</div>
        <div style={S.note}>
          Company overview unavailable{story && story.reason ? `: ${story.reason}` : ''}.
        </div>
      </div>
    )
  }
  const insights = story.insights || null
  const displayPrice = story.price ?? price
  return (
    <div style={S.card}>
      <div style={S.sectionLabel}>Company snapshot</div>
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'baseline', gap: '8px' }}>
        <span style={{ fontSize: '20px', fontWeight: 800, color: '#e2e8f0' }}>{story.name}</span>
        <span style={{ fontSize: '14px', color: '#a0aec0', fontWeight: 700 }}>{story.ticker}</span>
        <span style={{
          fontSize: '13px', fontWeight: 800, color: '#1a202c',
          background: story.grade === 'A' || story.grade === 'B' ? '#68d391' : story.grade === 'C' ? '#f6e05e' : '#fc8181',
          borderRadius: '6px', padding: '2px 8px',
        }}>Grade {story.grade}</span>
        {displayPrice != null ? (
          <span style={{ fontSize: '18px', fontWeight: 800, color: '#e2e8f0' }}>${displayPrice}</span>
        ) : (
          <span style={{ fontSize: '14px', fontWeight: 700, color: '#a0aec0' }}>price unavailable</span>
        )}
      </div>
      {story.earnings_date && (
        <div style={{ ...S.note, marginTop: '4px' }}>Next earnings: {story.earnings_date}</div>
      )}
      {story.earnings_unknown && (
        <div style={{ ...S.note, marginTop: '4px' }}>Next earnings date unknown.</div>
      )}
      {insights ? (
        <div style={{ marginTop: '10px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <div style={S.note}><strong style={{ color: '#e2e8f0' }}>What it does: </strong>{insights.business}</div>
          <div style={S.note}><strong style={{ color: '#e2e8f0' }}>Growth story: </strong>{insights.growth_story}</div>
          <div style={S.note}><strong style={{ color: '#e2e8f0' }}>Biggest risk: </strong>{insights.biggest_risk}</div>
          <div style={S.note}><strong style={{ color: '#e2e8f0' }}>Moat: </strong>{insights.moat}</div>
        </div>
      ) : (
        <div style={{ ...S.note, marginTop: '8px' }}>{story.story_line}</div>
      )}
    </div>
  )
}

function TopStocks({ onPick }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    api.topStocks.get()
      .then((d) => { if (!cancelled) { setData(d); setLoading(false) } })
      .catch((err) => {
        if (!cancelled) {
          setError(err.message || 'Top stocks failed to load')
          setLoading(false)
        }
      })
    return () => { cancelled = true }
  }, [])

  if (loading) {
    return (
      <div style={S.card}>
        <div style={S.sectionLabel}>Top stocks to consider</div>
        <div style={S.note}>Loading the top stocks…</div>
      </div>
    )
  }
  if (error || !data || data.status !== 'ok') {
    return (
      <div style={S.card}>
        <div style={S.sectionLabel}>Top stocks to consider</div>
        <div style={S.note}>
          Top stocks unavailable{error ? `: ${error}` : ''}. You can still search any ticker below.
        </div>
      </div>
    )
  }
  const items = data.items || []
  if (items.length === 0) {
    return (
      <div style={S.card}>
        <div style={S.sectionLabel}>Top stocks to consider</div>
        <div style={S.note}>
          No stock in the universe qualifies as grade A or B with a Buy or Hold recommendation
          right now. You can still search any ticker below.
        </div>
      </div>
    )
  }
  return (
    <div style={S.card}>
      <div style={S.sectionLabel}>Top stocks to consider</div>
      <div style={{ ...S.note, marginBottom: '10px' }}>
        Grade A first, then B, from the quality screener universe. Click one to see why it
        grades that way and why it is recommended to buy now.
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {items.map((item) => (
          <button
            key={item.ticker}
            type="button"
            onClick={() => onPick(item.ticker)}
            style={{
              textAlign: 'left', cursor: 'pointer', background: '#0f1520',
              border: '1px solid #2d3748', borderRadius: '10px', padding: '12px 14px',
              color: '#e2e8f0',
            }}
          >
            <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'baseline', gap: '8px' }}>
              <span style={{ fontSize: '16px', fontWeight: 800 }}>{item.ticker}</span>
              <span style={{ fontSize: '13px', color: '#a0aec0' }}>{item.name}</span>
              <span style={{
                fontSize: '12px', fontWeight: 800, color: '#1a202c',
                background: item.grade === 'A' ? '#68d391' : '#63b3ed',
                borderRadius: '6px', padding: '2px 8px',
              }}>Grade {item.grade}</span>
              <span style={{
                fontSize: '13px', fontWeight: 800,
                color: item.tier === 'buy_big' ? '#68d391'
                  : item.tier === 'buy_small' ? '#63b3ed' : '#f6e05e',
              }}>{item.tier_label}</span>
              {item.price != null && (
                <span style={{ fontSize: '15px', fontWeight: 800 }}>${item.price}</span>
              )}
            </div>
            {item.growth_story && (
              <div style={{ ...S.note, marginTop: '6px' }}>{item.growth_story}</div>
            )}
            {item.catalyst && item.catalyst.title && (
              <div style={{ ...S.note, marginTop: '4px' }}>
                Why now: {item.catalyst.title}
                {item.catalyst.age_hours != null && (
                  <span> ({Math.round(item.catalyst.age_hours)}h ago)</span>
                )}
                .
              </div>
            )}
          </button>
        ))}
      </div>
      {data.note && (
        <div style={{ ...S.note, marginTop: '10px' }}>{data.note}</div>
      )}
    </div>
  )
}

export default function TickerLookupTab() {
  const [ticker, setTicker] = useState('')
  const [explain, setExplain] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)
  const [ondemand, setOndemand] = useState(null)
  const [ondemandLoading, setOndemandLoading] = useState(false)
  const [ondemandError, setOndemandError] = useState(null)
  const [alignActions, setAlignActions] = useState({})
  const [adjustScores, setAdjustScores] = useState({ moat: '5', ceo: '5' })
  // Company Story, fetched once per lookup and shared by the
  // snapshot card and the Story section below, so the page makes
  // one Story call, not two.
  const [story, setStory] = useState(null)
  const [storyLoading, setStoryLoading] = useState(false)
  const [storyError, setStoryError] = useState(null)
  // One toggle for everything below the snapshot: the timing
  // verdict, the long-term lane, the DCA plan, the Story panels,
  // the options sections, and the on-demand review. Closed by
  // default, in both the simple and the full view.
  const [showDetail, setShowDetail] = useState(false)
  const [simpleView, setSimpleView] = useState(() => {
    try {
      return localStorage.getItem('ticker_lookup_simple_view') !== 'full'
    } catch (err) {
      return true
    }
  })

  function toggleView() {
    const next = !simpleView
    setSimpleView(next)
    try {
      localStorage.setItem('ticker_lookup_simple_view', next ? 'simple' : 'full')
    } catch (err) {
      // View preference is a convenience, not a requirement.
    }
  }

  async function runLookup(e) {
    e.preventDefault()
    const t = ticker.trim().toUpperCase()
    if (!t) return
    await doLookup(t)
  }

  // The lookup body, split out so a Top 5 row can load a ticker
  // exactly as if the user had typed it: same Answer block, same
  // snapshot, same Full detail toggle below.
  async function doLookup(t) {
    setTicker(t)
    setLoading(true)
    setError(null)
    setResult(null)
    setOndemand(null)
    setOndemandError(null)
    setAlignActions({})
    setStory(null)
    setStoryLoading(false)
    setStoryError(null)
    setShowDetail(false)
    try {
      const data = await api.lookup.get(t, explain)
      setResult(data)
    } catch (err) {
      setError(err.message || 'Lookup failed')
    } finally {
      setLoading(false)
    }
  }

  function pickTopStock(t) {
    const upper = (t || '').toUpperCase()
    if (!upper) return
    doLookup(upper)
  }

  // Fetch the Story once per lookup result. The snapshot card and
  // the Story section below both read this one fetch.
  useEffect(() => {
    if (!result || !result.ticker) return
    let cancelled = false
    setStory(null)
    setStoryLoading(true)
    setStoryError(null)
    api.story.get(result.ticker)
      .then((data) => {
        if (!cancelled) {
          setStory(data)
          setStoryLoading(false)
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setStoryError(err.message || 'Story failed to load')
          setStoryLoading(false)
        }
      })
    return () => { cancelled = true }
  }, [result])

  function ondemandStorageKey(t, runDate) {
    return `ondemand_alignment_${t}_${runDate || 'today'}`
  }

  async function applyStoredAlignment(data) {
    try {
      const stored = localStorage.getItem(ondemandStorageKey(data.ticker, data.run_date))
      if (!stored) return data
      const actions = JSON.parse(stored)
      if (!actions || Object.keys(actions).length === 0) return data
      const aligned = await api.lookup.alignOndemand(data.ticker, { proposals: data.proposals, actions })
      setAlignActions(actions)
      return { ...data, proposals: aligned.proposals, alignment: { status: aligned.status, provisional: aligned.provisional, audit_trail: aligned.audit_trail } }
    } catch (err) {
      return data
    }
  }

  async function runOndemand() {
    if (!result) return
    const t = result.ticker
    setOndemandLoading(true)
    setOndemandError(null)
    try {
      const data = await api.lookup.getOndemand(t)
      const merged = await applyStoredAlignment(data)
      setOndemand(merged)
    } catch (err) {
      setOndemandError(err.message || 'On-demand review failed')
    } finally {
      setOndemandLoading(false)
    }
  }

  async function alignProposal(key, action) {
    if (!ondemand) return
    const actions = { ...alignActions, [key]: action }
    setAlignActions(actions)
    try {
      localStorage.setItem(ondemandStorageKey(ondemand.ticker, ondemand.run_date), JSON.stringify(actions))
    } catch (err) {
      // Local storage is a convenience, not a requirement. Alignment still applies this session.
    }
    try {
      const aligned = await api.lookup.alignOndemand(ondemand.ticker, { proposals: ondemand.proposals, actions })
      setOndemand({ ...ondemand, proposals: aligned.proposals, alignment: { status: aligned.status, provisional: aligned.provisional, audit_trail: aligned.audit_trail } })
    } catch (err) {
      setOndemandError(err.message || 'Alignment failed')
    }
  }

  return (
    <div style={S.root}>
      <TopStocks onPick={pickTopStock} />

      <form onSubmit={runLookup} style={S.form}>
        <input
          style={S.input}
          value={ticker}
          onChange={(e) => setTicker(e.target.value)}
          placeholder="TICKER"
          maxLength={12}
          aria-label="Ticker"
        />
        <button style={S.button} type="submit" disabled={loading}>
          {loading ? 'Looking up...' : 'Look up'}
        </button>
        <label style={S.check}>
          <input type="checkbox" checked={explain} onChange={(e) => setExplain(e.target.checked)} />
          Plain-language explanation (Claude, optional)
        </label>
      </form>

      {error && (
        <div style={S.error}>
          <strong>Lookup failed.</strong>
          <div style={{ marginTop: '6px' }}>{error}</div>
          <div style={{ marginTop: '6px', color: '#a0aec0' }}>
            Unknown ticker, no data, or no listed options returns a named reason, not a guessed result.
          </div>
        </div>
      )}

      {result && result.verdict && (
        <div style={S.card}>
          <button style={S.button} type="button" onClick={toggleView}>
            {simpleView ? 'Show full expanded view' : 'Back to simple view'}
          </button>
          <div style={{ ...S.note, marginTop: '8px' }}>
            The answer comes first, then one company snapshot. Everything else, the timing verdict, the
            long-term lane, the DCA plan, the Story panels, and the options sections, sits behind one
            Full detail toggle below, in both views.
          </div>
        </div>
      )}

      {result && result.verdict && simpleView && (
        <>
          <AnswerSection ticker={result.ticker} />

          <CompanySnapshot story={story} loading={storyLoading} error={storyError} price={result.price} />

          <button style={S.button} type="button" onClick={() => setShowDetail(!showDetail)}>
            {showDetail ? 'Hide full detail' : 'Show full detail'}
          </button>

          {showDetail && (
            <>

          <div style={S.verdictCard(result.verdict.stock.decision === 'buy' ? 'buy' : result.verdict.stock.decision === 'wait' ? 'wait' : result.verdict.stock.decision === 'avoid' ? 'avoid' : 'hold')}>
            <div style={S.verdictBig(result.verdict.stock.decision === 'buy' ? 'buy' : result.verdict.stock.decision === 'wait' ? 'wait' : result.verdict.stock.decision === 'avoid' ? 'avoid' : 'hold')}>
              {plainVerdictLabel(result.verdict.stock.decision, result.verdict.stock.label)}
            </div>
            <div style={{ fontSize: '15px', color: '#e2e8f0', marginTop: '6px' }}>{trendLine(result.trend, result.price)}</div>
            <div style={S.verdictReason}>{result.verdict.stock.reason}</div>
            <div style={S.verdictNote}>What would change this: {result.verdict.stock.what_would_change}</div>
          </div>

          <StorySection ticker={result.ticker} storyData={story} storyLoading={storyLoading} storyError={storyError} />

          <details style={S.details}>
            <summary style={S.summary}>Short-term: trend, setup, trigger, invalidation</summary>
            <div style={{ marginTop: '12px' }}>
              {result.verdict.stock.entry_plan && (
                <>
                  <div style={S.note}>
                    Trigger: {result.verdict.stock.entry_plan.trigger_50d_wording === 'recovery' ? 'Recovery to' : 'Pullback to'} ${val(result.verdict.stock.entry_plan.pullback_price)}
                    {result.verdict.stock.entry_plan.breakout_price != null && (
                      <span> or a close above ${val(result.verdict.stock.entry_plan.breakout_price)}</span>
                    )}
                    {result.verdict.stock.entry_plan.buy_zone && (
                      <span> | Buy zone ${val(result.verdict.stock.entry_plan.buy_zone[0])} to ${val(result.verdict.stock.entry_plan.buy_zone[1])}</span>
                    )}
                  </div>
                  <div style={{ ...S.note, marginTop: '6px' }}>Wrong if: {result.verdict.stock.entry_plan.what_flips_to_avoid}</div>
                  {result.verdict.stock.entry_plan.blocker && (
                    <div style={{ ...S.note, marginTop: '6px' }}>Blocker today: {result.verdict.stock.entry_plan.blocker}</div>
                  )}
                </>
              )}
              {!result.verdict.stock.entry_plan && (
                <div style={S.note}>No entry plan today. See the timing verdict above for the blocker.</div>
              )}
            </div>
          </details>

          <details style={S.details}>
            <summary style={S.summary}>Long-term: quality, DCF summary, DCA decision</summary>
            <div style={{ marginTop: '12px' }}>
              {result.verdict.longterm && (
                <>
                  <div style={{ fontSize: '15px', fontWeight: 700, color: '#e2e8f0' }}>{val(result.verdict.longterm.label)}: {result.verdict.longterm.reason}</div>
                  {result.verdict.longterm.bridge_line && (
                    <div style={{ ...S.note, marginTop: '6px', color: '#68d391' }}>{result.verdict.longterm.bridge_line}</div>
                  )}
                  <div style={{ marginTop: '10px' }}>
                    <DcfMethodsSummary longterm={result.verdict.longterm} price={result.price} />
                  </div>
                </>
              )}
              {result.verdict.dca && (
                <div style={{ marginTop: '10px' }}>
                  <div style={{ fontSize: '15px', fontWeight: 700, color: '#e2e8f0' }}>{result.verdict.dca.label}</div>
                  <div style={S.note}>{result.verdict.dca.basis_note}</div>
                  <div style={{ ...S.note, marginTop: '6px' }}>Pause rule: {result.verdict.dca.pause_rule}</div>
                </div>
              )}
              {!result.verdict.dca && (
                <div style={{ ...S.note, marginTop: '10px' }}>No DCA plan here, because quality is not verified or the trend is broken.</div>
              )}
            </div>
          </details>

          <details style={S.details}>
            <summary style={S.summary}>Options: put and call, selected strike only</summary>
            <div style={{ marginTop: '12px' }}>
              <OptionSummary option={result.verdict.put} />
              <OptionSummary option={result.verdict.call} />
              <div style={{ ...S.note, marginTop: '8px' }}>The full option chain is in the full expanded view, closed by default.</div>
            </div>
          </details>

          <div style={S.card}>
            <div style={S.sectionLabel}>Options Strategies: best call, best put, straddle, iron condor</div>
            <div style={{ marginTop: '6px' }}>
              <OptionStrategiesSummary strategies={result.verdict.option_strategies} />
            </div>
          </div>

          <details style={S.details}>
            <summary style={S.summary}>Show details: conviction, news, earnings, market</summary>
            <div style={{ marginTop: '12px' }}>
              <div style={S.note}>
                <strong style={{ color: '#e2e8f0' }}>What supported this: </strong>
                {result.verdict.conviction.supports.length > 0 ? result.verdict.conviction.supports.join(' ') : 'Nothing supported a buy today.'}
              </div>
              <div style={{ ...S.note, marginTop: '6px' }}>
                <strong style={{ color: '#e2e8f0' }}>What was against it: </strong>
                {result.verdict.conviction.against.length > 0 ? result.verdict.conviction.against.join(' ') : 'Nothing was against it.'}
              </div>
              <div style={{ ...S.note, marginTop: '6px' }}>
                <strong style={{ color: '#e2e8f0' }}>What was missing: </strong>
                {result.verdict.conviction.missing.join(' ')}
              </div>
              <div style={{ ...S.note, marginTop: '6px' }}>
                <strong style={{ color: '#e2e8f0' }}>News: </strong>
                {result.news ? result.news.note : 'No fresh company news could be verified.'}
              </div>
              <div style={{ ...S.note, marginTop: '6px' }}>
                <strong style={{ color: '#e2e8f0' }}>Earnings: </strong>
                {result.verdict.earnings.anticipated_date
                  ? `Next report ${val(result.verdict.earnings.anticipated_date)}, ${val(result.verdict.earnings.days_away)} days away. `
                  : 'Next earnings date is unknown. '}
                No consensus estimate and no reported beat or miss is available, so nothing is guessed there.
              </div>
              <div style={{ ...S.note, marginTop: '6px' }}>
                IV rank {val(result.iv.iv_percentile)} | SPY gate {val(result.spy_gate.gate)} ({val(result.spy_gate.spy_vs_200ma_pct)}% vs 200-day) |
                Price source {val(result.price_source)} | Data timestamp {val(result.data_timestamp)}
              </div>
              <div style={{ ...S.note, marginTop: '8px' }}>
                Full setup conditions and the full option chain are in the full expanded view, not repeated here.
              </div>
            </div>
          </details>

          <div style={S.card}>
            <div style={S.sectionLabel}>On-demand review, live, for any ticker</div>
            <div style={S.note}>
              {result.verdict.longterm && result.verdict.longterm.verdict === 'not_verified'
                ? 'The long-term lane above reads NOT VERIFIED, because this ticker is not in the 2026-10-26 quality screener snapshot. Run a live review below. It is dated, labelled live, and shown alongside the snapshot result, which it does not overwrite.'
                : 'Run a live review alongside the snapshot result above, for comparison. The live review does not overwrite the snapshot lane.'}
            </div>
            <button style={{ ...S.button, marginTop: '10px' }} type="button" onClick={runOndemand} disabled={ondemandLoading}>
              {ondemandLoading ? 'Running live review...' : 'Run on-demand review'}
            </button>
            {ondemandError && (
              <div style={{ ...S.note, marginTop: '8px', color: '#fc8181' }}>{ondemandError}</div>
            )}
          </div>

          {ondemand && (
            <>
              <div style={S.verdictCard('hold')}>
                <div style={S.verdictBig('hold')}>{val(ondemand.dca_decision.label)}</div>
                <div style={{ fontSize: '15px', color: '#e2e8f0', marginTop: '6px' }}>
                  {trendLine(ondemand.short_term, ondemand.short_term.price)}
                </div>
                <div style={S.verdictReason}>{ondemand.dca_decision.reason}</div>
                <div style={S.verdictReason}>{val(ondemand.longterm.label)}: {ondemand.longterm.reason}</div>
                {ondemand.alignment && ondemand.alignment.provisional && (
                  <div style={{ ...S.note, marginTop: '6px', color: '#f6e05e' }}>
                    AI-proposed, awaiting your alignment: verdicts that depend on the proposals are provisional, not final.
                  </div>
                )}
              </div>

              <details style={S.details}>
                <summary style={S.summary}>On-demand short-term: trend, setup, trigger, invalidation</summary>
                <div style={{ marginTop: '12px' }}>
                  <div style={S.note}>{ondemand.short_term.trend_note}</div>
                  <div style={{ ...S.note, marginTop: '6px' }}>
                    Pullback ${val(ondemand.short_term.pullback_price)} | Breakout ${val(ondemand.short_term.breakout_price)} |
                    Invalidation ${val(ondemand.short_term.invalidation_price)} |
                    SPY above 200-day: {val(ondemand.short_term.spy_above_200)} |
                    Earnings in {val(ondemand.short_term.earnings_days)} days ({val(ondemand.short_term.earnings_status)})
                  </div>
                  {ondemand.short_term.setup_names && ondemand.short_term.setup_names.length > 0 && (
                    <div style={S.note}>Setups present: {ondemand.short_term.setup_names.join(', ')}</div>
                  )}
                </div>
              </details>

              <details style={S.details}>
                <summary style={S.summary}>On-demand long-term: quality, DCF summary, DCA decision</summary>
                <div style={{ marginTop: '12px' }}>
                  {ondemand.live_quality && ondemand.live_quality.status === 'verified' && (
                    <div style={S.note}>
                      Live quality: composite {fmtPct(ondemand.live_quality.composite)} ({val(ondemand.live_quality.label)}),
                      revenue CAGR 3y {fmtPct(ondemand.live_quality.rev_cagr_3y_pct)}%,
                      FCF margin avg 3y {fmtPct(ondemand.live_quality.fcf_margin_avg_3y_pct)}%,
                      ROIC {fmtPct(ondemand.live_quality.roic_pct)}%, operating margin {fmtPct(ondemand.live_quality.operating_margin_pct)}%.
                    </div>
                  )}
                  <div style={{ marginTop: '10px' }}>
                    <DcfMethodsSummary longterm={ondemand.longterm} price={ondemand.short_term.price} />
                  </div>
                  {ondemand.dca_decision.trigger && (
                    <div style={S.note}>Trigger: {ondemand.dca_decision.trigger}{ondemand.dca_decision.trigger_price != null && (<span> at ${val(ondemand.dca_decision.trigger_price)}</span>)}</div>
                  )}
                  {ondemand.dca_decision.killing_parameters && ondemand.dca_decision.killing_parameters.length > 0 && (
                    <div style={S.note}>Killing parameters: {ondemand.dca_decision.killing_parameters.join('; ')}</div>
                  )}
                  {ondemand.statements_note && (
                    <div style={S.note}>{ondemand.statements_note}</div>
                  )}
                  {ondemand.statements_source && (
                    <div style={S.note}>Statements source: {ondemand.statements_source === 'yfinance_annual' ? 'yfinance annual, fallback because Polygon SEC returned no revenue or free cash flow' : 'Polygon SEC'}.</div>
                  )}
                </div>
              </details>

              <details style={S.details}>
                <summary style={S.summary}>On-demand options: put and call, selected strike only</summary>
                <div style={{ marginTop: '12px' }}>
                  <div style={S.note}>
                    Timing decision: {val(result.verdict.stock.label)}. Put and call gating is unchanged: timing, earnings, and SPY, exactly as in the timing card in the full view. The on-demand review never unlocks a weekly put or call.
                  </div>
                  <OptionSummary option={result.verdict.put} />
                  <OptionSummary option={result.verdict.call} />
                </div>
              </details>

              <div style={S.card}>
                <div style={S.sectionLabel}>On-demand Options Strategies: best call, best put, straddle, iron condor</div>
                <div style={{ marginTop: '6px' }}>
                  <OptionStrategiesSummary strategies={ondemand.option_strategies} />
                </div>
              </div>

              <details style={S.details}>
                <summary style={S.summary}>Show details: AI proposals and alignment</summary>
                <div style={{ marginTop: '12px' }}>
                  <div style={S.note}>
                    These are evidence-based proposals, not quant decisions for options. Until you align an assumption, the long-term and DCA verdicts that depend on it stay provisional, not final.
                  </div>
                  {ondemand.proposals && ['moat', 'ceo', 'market_size'].map((key) => (
                    <ProposalRow
                      key={key}
                      proposal={ondemand.proposals[key] ? { ...ondemand.proposals[key], key } : null}
                      onAlign={alignProposal}
                      adjustScore={adjustScores[key] || '5'}
                      setAdjustScore={(v) => setAdjustScores({ ...adjustScores, [key]: v })}
                    />
                  ))}
                  {ondemand.alignment && ondemand.alignment.audit_trail && ondemand.alignment.audit_trail.length > 0 && (
                    <div style={{ ...S.note, marginTop: '10px' }}>
                      Audit trail: {ondemand.alignment.audit_trail.map((a) => `${a.key}: proposed ${val(a.proposed_score)} -> aligned ${val(a.aligned_score)} (${val(a.alignment_status)})`).join(' | ')}
                    </div>
                  )}
                </div>
              </details>
            </>
          )}
            </>
          )}
        </>
      )}

      {result && result.verdict && !simpleView && (
        <>
          <AnswerSection ticker={result.ticker} />

          <CompanySnapshot story={story} loading={storyLoading} error={storyError} price={result.price} />

          <button style={S.button} type="button" onClick={() => setShowDetail(!showDetail)}>
            {showDetail ? 'Hide full detail' : 'Show full detail'}
          </button>

          {showDetail && (
            <>
          {result.summary && (
            <div style={S.card}>
              <div style={S.sectionLabel}>In plain language</div>
              <div style={{ fontSize: '15px', color: '#e2e8f0', lineHeight: 1.6 }}>{result.summary}</div>
            </div>
          )}
          <StorySection ticker={result.ticker} storyData={story} storyLoading={storyLoading} storyError={storyError} />
          {result.verdict.dca && (
            <div style={S.card}>
              <div style={S.sectionLabel}>Long-term accumulation, not a timed trade</div>
              <div style={{ fontSize: '22px', fontWeight: 800, color: '#68d391' }}>
                {result.verdict.dca.label}
              </div>
              <div style={{ ...S.note, marginTop: '6px', color: '#e2e8f0', fontSize: '13px' }}>
                Basis: {result.verdict.dca.basis}
              </div>
              <div style={{ ...S.note, marginTop: '6px' }}>{result.verdict.dca.basis_note}</div>
              <ul style={S.verdictList}>
                {result.verdict.dca.pieces.map((p, i) => (
                  <li key={i}>
                    Piece {p.order}: {p.condition}
                    {p.price != null && (<span> at ${val(p.price)}</span>)}
                    {p.detail && (<span> ({p.detail})</span>)}
                  </li>
                ))}
              </ul>
              {result.verdict.dca.dip_note && (
                <div style={{ ...S.note, marginTop: '6px' }}>{result.verdict.dca.dip_note}</div>
              )}
              <div style={{ ...S.note, marginTop: '6px' }}>
                <strong style={{ color: '#e2e8f0' }}>Pause rule: </strong>
                {result.verdict.dca.pause_rule}
              </div>
              {result.verdict.dca.earnings_note && (
                <div style={{ ...S.note, marginTop: '6px' }}>{result.verdict.dca.earnings_note}</div>
              )}
              <div style={{ ...S.note, marginTop: '6px' }}>{result.verdict.dca.note}</div>
              <div style={{ ...S.note, marginTop: '6px' }}>
                This DCA lane does not change the put or call answer below, and it is not a timed entry price.
              </div>
            </div>
          )}
          {result.verdict.longterm && (
            <div style={S.card}>
              <div style={S.sectionLabel}>Long term, 3 to 5 years (separate from timing)</div>
              <div style={{ fontSize: '22px', fontWeight: 800, color: '#e2e8f0' }}>
                {result.verdict.longterm.label}
              </div>
              <div style={S.verdictReason}>{result.verdict.longterm.reason}</div>
              {result.verdict.longterm.bridge_line && (
                <div style={{ fontSize: '15px', fontWeight: 700, color: '#68d391', marginTop: '8px' }}>
                  {result.verdict.longterm.bridge_line}
                  {result.verdict.longterm.bridge_entry && (
                    <span style={{ fontWeight: 400, color: '#a0aec0' }}>
                      {' '}Pullback ${val(result.verdict.longterm.bridge_entry.pullback_price)}
                      {result.verdict.longterm.bridge_entry.breakout_price != null && (
                        <span> or a close above ${val(result.verdict.longterm.bridge_entry.breakout_price)}</span>
                      )}
                      {result.verdict.longterm.bridge_entry.buy_zone && (
                        <span> | Buy zone ${val(result.verdict.longterm.bridge_entry.buy_zone[0])} to ${val(result.verdict.longterm.bridge_entry.buy_zone[1])}</span>
                      )}
                      {result.verdict.longterm.bridge_entry.invalidation_price != null && (
                        <span> | Wrong if it closes below ${val(result.verdict.longterm.bridge_entry.invalidation_price)}</span>
                      )}
                    </span>
                  )}
                </div>
              )}
              {result.verdict.longterm.quality && result.verdict.longterm.quality.status === 'verified' && (
                <div style={{ ...S.note, marginTop: '8px' }}>
                  Quality, screener {val(result.verdict.longterm.quality.run_date)}: composite {fmtPct(result.verdict.longterm.quality.composite)} ({val(result.verdict.longterm.quality.label)}), revenue CAGR 3y {fmtPct(result.verdict.longterm.quality.rev_cagr_3y_pct)}%, FCF margin avg 3y {fmtPct(result.verdict.longterm.quality.fcf_margin_avg_3y_pct)}%, ROIC {fmtPct(result.verdict.longterm.quality.roic_pct)}%, operating margin {fmtPct(result.verdict.longterm.quality.operating_margin_pct)}%, EV/EBITDA {val(result.verdict.longterm.quality.ev_to_ebitda)}x.
                </div>
              )}
              {result.verdict.longterm.quality && result.verdict.longterm.quality.status !== 'verified' && (
                <div style={{ ...S.note, marginTop: '8px' }}>{val(result.verdict.longterm.quality.note)}</div>
              )}
              {result.verdict.longterm.dcf && (
                <>
                  <DcfFraming longterm={result.verdict.longterm} price={result.price} />
                  <div style={{ ...S.grid, marginTop: '12px' }}>
                    <div style={S.stat}>
                      <span style={S.statLabel}>Bear fair value</span>
                      <span style={S.statValue}>${val(result.verdict.longterm.dcf.fair_value.bear)}</span>
                      <span style={S.statSub}>{fmtPct(result.verdict.longterm.dcf.upside_pct.bear)}% vs today</span>
                    </div>
                    <div style={S.stat}>
                      <span style={S.statLabel}>Base fair value</span>
                      <span style={S.statValue}>${val(result.verdict.longterm.dcf.fair_value.base)}</span>
                      <span style={S.statSub}>{fmtPct(result.verdict.longterm.dcf.upside_pct.base)}% vs today</span>
                    </div>
                    <div style={S.stat}>
                      <span style={S.statLabel}>Bull fair value</span>
                      <span style={S.statValue}>${val(result.verdict.longterm.dcf.fair_value.bull)}</span>
                      <span style={S.statSub}>{fmtPct(result.verdict.longterm.dcf.upside_pct.bull)}% vs today</span>
                    </div>
                    <div style={S.stat}>
                      <span style={S.statLabel}>Reverse DCF</span>
                      <span style={S.statValue}>{fmtPct(result.verdict.longterm.dcf.reverse_dcf_implied_growth_pct)}%</span>
                      <span style={S.statSub}>growth the market is already pricing in</span>
                    </div>
                  </div>
                  {result.verdict.longterm.wacc && (
                    <div style={{ ...S.note, marginTop: '8px' }}>
                      WACC {val(result.verdict.longterm.wacc.wacc_pct)}% (risk free {val(result.verdict.longterm.wacc.risk_free_pct)}%, source: {val(result.verdict.longterm.wacc.risk_free_source)}).
                      {result.verdict.longterm.dcf.exit_multiple_check && result.verdict.longterm.dcf.exit_multiple_check.fair_value != null && (
                        <span> Exit-multiple cross-check: ${val(result.verdict.longterm.dcf.exit_multiple_check.fair_value)} vs Gordon ${val(result.verdict.longterm.dcf.exit_multiple_check.gordon_fair_value)} ({fmtPct(result.verdict.longterm.dcf.exit_multiple_check.disagreement_pct)}%{result.verdict.longterm.dcf.exit_multiple_check.wide_disagreement ? ', wide disagreement, neither method is picked' : ''}).</span>
                      )}
                      {result.verdict.longterm.dcf.exit_multiple_check && result.verdict.longterm.dcf.exit_multiple_check.fair_value == null && (
                        <span> Exit-multiple cross-check unavailable: {val(result.verdict.longterm.dcf.exit_multiple_check.note)}</span>
                      )}
                    </div>
                  )}
                  {result.verdict.longterm.dcf.wacc_sensitivity && result.verdict.longterm.dcf.wacc_sensitivity.length > 0 && (
                    <div style={{ ...S.note, marginTop: '8px' }}>
                      WACC sensitivity (base fair value): {result.verdict.longterm.dcf.wacc_sensitivity.map((r, i) => (
                        <span key={i}>{i > 0 ? ' | ' : ''}{val(r.wacc_pct)}% WACC: ${val(r.base.price)}</span>
                      ))}
                    </div>
                  )}
                </>
              )}
              {result.verdict.longterm.notes && result.verdict.longterm.notes.map((n, i) => (
                <div key={i} style={{ ...S.note, marginTop: '6px' }}>{n}</div>
              ))}
              <div style={{ ...S.note, marginTop: '8px' }}>
                This lane does not change the put or call answer below. A strong, undervalued company can keep falling, so weekly options stay gated by timing, earnings, and SPY.
              </div>
            </div>
          )}

          <div style={S.card}>
            <div style={S.sectionLabel}>On-demand review, live, for any ticker</div>
            <div style={S.note}>
              {result.verdict.longterm && result.verdict.longterm.verdict === 'not_verified'
                ? 'The long-term lane above reads NOT VERIFIED, because this ticker is not in the 2026-10-26 quality screener snapshot. Run a live review below. It is dated, labelled live, and shown alongside the snapshot result, which it does not overwrite.'
                : 'Run a live review alongside the snapshot result above, for comparison. The live review does not overwrite the snapshot lane.'}
            </div>
            <button style={{ ...S.button, marginTop: '10px' }} type="button" onClick={runOndemand} disabled={ondemandLoading}>
              {ondemandLoading ? 'Running live review...' : 'Run on-demand review'}
            </button>
            {ondemandError && (
              <div style={{ ...S.note, marginTop: '8px', color: '#fc8181' }}>{ondemandError}</div>
            )}
          </div>

          {ondemand && (
            <>
              <div style={S.card}>
                <div style={S.sectionLabel}>On-demand review, in plain language</div>
                <div style={{ fontSize: '15px', color: '#e2e8f0', lineHeight: 1.6 }}>{ondemand.summary}</div>
                <div style={{ ...S.note, marginTop: '6px' }}>
                  Live review, {val(ondemand.run_date)}, source: live_on_demand. Snapshot long-term above is unchanged, and the two can be compared.
                </div>
                {ondemand.alignment && ondemand.alignment.provisional && (
                  <div style={{ ...S.note, marginTop: '6px', color: '#f6e05e' }}>
                    AI-proposed, awaiting your alignment: the long-term and DCA verdicts below that depend on the proposals are provisional, not final, until you accept, adjust, or mark each assumption missing.
                  </div>
                )}
              </div>

              <div style={S.card}>
                <div style={S.sectionLabel}>Short-term trend and setup, live</div>
                <div style={{ fontSize: '22px', fontWeight: 800, color: '#e2e8f0' }}>
                  Trend: {val(ondemand.short_term.trend)} | Setup: {ondemand.short_term.setup_present ? 'present' : 'absent'}
                </div>
                <div style={{ ...S.note, marginTop: '6px', color: '#e2e8f0', fontSize: '13px' }}>{ondemand.short_term.trend_note}</div>
                <div style={{ ...S.note, marginTop: '6px' }}>
                  Price ${val(ondemand.short_term.price)} | 50-day ${val(ondemand.short_term.ma50)} ({val(ondemand.short_term.ma50_direction)}) | 200-day ${val(ondemand.short_term.ma200)} ({val(ondemand.short_term.ma200_direction)})
                </div>
                {ondemand.short_term.setup_names && ondemand.short_term.setup_names.length > 0 && (
                  <div style={S.note}>Setups present: {ondemand.short_term.setup_names.join(', ')}</div>
                )}
                <div style={S.note}>
                  Pullback ${val(ondemand.short_term.pullback_price)} | Breakout ${val(ondemand.short_term.breakout_price)} | SPY above 200-day: {val(ondemand.short_term.spy_above_200)} | Earnings in {val(ondemand.short_term.earnings_days)} days ({val(ondemand.short_term.earnings_status)})
                </div>
                <div style={S.note}>{ondemand.short_term.note}</div>
              </div>

              <div style={S.card}>
                <div style={S.sectionLabel}>Long-term fundamentals and potential, live</div>
                <div style={{ fontSize: '22px', fontWeight: 800, color: '#e2e8f0' }}>{val(ondemand.longterm.label)}</div>
                <div style={{ ...S.note, marginTop: '6px', color: '#e2e8f0', fontSize: '13px' }}>{ondemand.longterm.reason}</div>
                {ondemand.live_quality && ondemand.live_quality.status === 'verified' && (
                  <div style={{ ...S.note, marginTop: '6px' }}>
                    Live quality, {val(ondemand.live_quality.run_date)}: composite {fmtPct(ondemand.live_quality.composite)} ({val(ondemand.live_quality.label)}), revenue CAGR 3y {fmtPct(ondemand.live_quality.rev_cagr_3y_pct)}%, FCF margin avg 3y {fmtPct(ondemand.live_quality.fcf_margin_avg_3y_pct)}%, ROIC {fmtPct(ondemand.live_quality.roic_pct)}%, operating margin {fmtPct(ondemand.live_quality.operating_margin_pct)}%, smoothed Rule of 40 {fmtPct(ondemand.live_quality.smoothed_rule_of_40)}, EV/EBITDA {val(ondemand.live_quality.ev_to_ebitda)}x.
                  </div>
                )}
                {ondemand.live_quality && ondemand.live_quality.status !== 'verified' && (
                  <div style={{ ...S.note, marginTop: '6px' }}>{val(ondemand.live_quality.note)}</div>
                )}
                {ondemand.live_quality && ondemand.live_quality.short_pct != null && (
                  <div style={S.note}>
                    Short interest {val(ondemand.live_quality.short_pct)}%: Nash Step 3 kill above 10%: {ondemand.live_quality.kills && ondemand.live_quality.kills.short_interest_nash_kill_above_10 ? 'yes, kill' : 'no'} | Screener v2 kill above 20%: {ondemand.live_quality.kills && ondemand.live_quality.kills.short_interest_screener_kill_above_20 ? 'yes, kill' : 'no'}.
                  </div>
                )}
                {ondemand.live_quality && ondemand.live_quality.missing && ondemand.live_quality.missing.length > 0 && (
                  <div style={S.note}>Missing, not scored as 0: {ondemand.live_quality.missing.join(', ')}</div>
                )}
                {ondemand.live_quality && ondemand.live_quality.kills && (
                  <div style={S.note}>
                    Nash kills: market cap at least $1B: {val(ondemand.live_quality.kills.market_cap_at_least_1b)} | FCF positive: {val(ondemand.live_quality.kills.fcf_positive)} | cash over debt: {val(ondemand.live_quality.kills.cash_over_debt)} | operating margin at least 20%: {val(ondemand.live_quality.kills.operating_margin_at_least_20)} | fewer than 2 misses: {val(ondemand.live_quality.kills.fewer_than_2_misses)}.
                  </div>
                )}
                {ondemand.longterm.dcf && (
                  <>
                  <DcfFraming longterm={ondemand.longterm} price={ondemand.short_term.price} />
                  <div style={{ ...S.grid, marginTop: '10px' }}>
                    <div style={S.stat}><span style={S.statLabel}>DCF bear</span><span style={S.statValue}>${val(ondemand.longterm.dcf.fair_value.bear)}</span></div>
                    <div style={S.stat}><span style={S.statLabel}>DCF base</span><span style={S.statValue}>${val(ondemand.longterm.dcf.fair_value.base)}</span></div>
                    <div style={S.stat}><span style={S.statLabel}>DCF bull</span><span style={S.statValue}>${val(ondemand.longterm.dcf.fair_value.bull)}</span></div>
                  </div>
                  </>
                )}
                {ondemand.longterm.wacc && (
                  <div style={S.note}>WACC {val(ondemand.longterm.wacc.wacc_pct)}% (risk free {val(ondemand.longterm.wacc.risk_free_pct)}%, source: {val(ondemand.longterm.wacc.risk_free_source)}).</div>
                )}
                {ondemand.longterm.bridge_line && (
                  <div style={S.note}>{ondemand.longterm.bridge_line}</div>
                )}
                {ondemand.statements_note && (
                  <div style={S.note}>{ondemand.statements_note}</div>
                )}
                {ondemand.statements_source && (
                  <div style={S.note}>Statements source: {ondemand.statements_source === 'yfinance_annual' ? 'yfinance annual, fallback because Polygon SEC returned no revenue or free cash flow' : 'Polygon SEC'}.</div>
                )}
              </div>

              <div style={S.card}>
                <div style={S.sectionLabel}>DCA decision, live</div>
                <div style={{ fontSize: '22px', fontWeight: 800, color: '#68d391' }}>{val(ondemand.dca_decision.label)}</div>
                <div style={{ ...S.note, marginTop: '6px', color: '#e2e8f0', fontSize: '13px' }}>{ondemand.dca_decision.reason}</div>
                {ondemand.dca_decision.trigger && (
                  <div style={S.note}>Trigger: {ondemand.dca_decision.trigger}{ondemand.dca_decision.trigger_price != null && (<span> at ${val(ondemand.dca_decision.trigger_price)}</span>)}</div>
                )}
                {ondemand.dca_decision.killing_parameters && ondemand.dca_decision.killing_parameters.length > 0 && (
                  <div style={S.note}>Killing parameters: {ondemand.dca_decision.killing_parameters.join('; ')}</div>
                )}
                {ondemand.dca_decision.missing && ondemand.dca_decision.missing.length > 0 && (
                  <div style={S.note}>Missing: {ondemand.dca_decision.missing.join(', ')}</div>
                )}
                {ondemand.dca_decision.plan && ondemand.dca_decision.plan.pieces && (
                  <ul style={S.verdictList}>
                    {ondemand.dca_decision.plan.pieces.map((p, i) => (
                      <li key={i}>Piece {p.order}: {p.condition}{p.price != null && (<span> at ${val(p.price)}</span>)}{p.detail && (<span> ({p.detail})</span>)}</li>
                    ))}
                  </ul>
                )}
                <div style={S.note}>Pieces are guidance, not sized orders. Pause rule: stop adding if it closes below the 200-day average.</div>
                <div style={S.note}>This DCA decision does not change the put or call answer, and it is not a timed entry price.</div>
              </div>

              <div style={S.card}>
                <div style={S.sectionLabel}>Timing options, unchanged gating</div>
                <div style={S.note}>
                  Timing decision: {val(result.verdict.stock.label)}. Put and call gating is unchanged: timing, earnings, and SPY, exactly as in the timing card below. The on-demand review never unlocks a weekly put or call.
                </div>
              </div>

              <div style={S.card}>
                <div style={S.sectionLabel}>AI proposals: moat, CEO, and market size, plus your alignment</div>
                <div style={S.note}>
                  These are evidence-based proposals, not quant decisions for options. Until you align an assumption, the long-term and DCA verdicts that depend on it stay provisional, not final. Aligned scores lock with an audit trail, saved per ticker on this device. For the full manual checklist, use the Nash 12-step wizard, Steps 4, 5, 9, and 10.
                </div>
                {ondemand.proposals && ['moat', 'ceo', 'market_size'].map((key) => (
                  <ProposalRow
                    key={key}
                    proposal={ondemand.proposals[key] ? { ...ondemand.proposals[key], key } : null}
                    onAlign={alignProposal}
                    adjustScore={adjustScores[key] || '5'}
                    setAdjustScore={(v) => setAdjustScores({ ...adjustScores, [key]: v })}
                  />
                ))}
                {ondemand.alignment && ondemand.alignment.audit_trail && ondemand.alignment.audit_trail.length > 0 && (
                  <div style={{ ...S.note, marginTop: '10px' }}>
                    Audit trail: {ondemand.alignment.audit_trail.map((a) => `${a.key}: proposed ${val(a.proposed_score)} -> aligned ${val(a.aligned_score)} (${val(a.alignment_status)})`).join(' | ')}
                  </div>
                )}
                <div style={S.note}>Alignment status: {val(ondemand.alignment && ondemand.alignment.status)}</div>
              </div>
            </>
          )}

          <div style={S.verdictCard(result.verdict.stock.decision === 'buy' ? 'buy' : result.verdict.stock.decision === 'wait' ? 'wait' : result.verdict.stock.decision === 'avoid' ? 'avoid' : 'hold')}>
            <div style={S.verdictBig(result.verdict.stock.decision === 'buy' ? 'buy' : result.verdict.stock.decision === 'wait' ? 'wait' : result.verdict.stock.decision === 'avoid' ? 'avoid' : 'hold')}>
              {result.verdict.stock.decision === 'avoid' ? 'AVOID FOR NOW' : result.verdict.stock.label}
            </div>
            <div style={S.verdictReason}>{result.verdict.stock.reason}</div>
            {result.verdict.stock.plain_explanation && (
              <div style={S.verdictNote}>{result.verdict.stock.plain_explanation}</div>
            )}
            <div style={{ fontSize: '15px', color: '#e2e8f0', marginTop: '6px' }}>
              {result.ticker} at ${val(result.price)}
              {result.verdict.stock.invalidation_price != null && (
                <span> | Wrong if it closes below ${val(result.verdict.stock.invalidation_price)}</span>
              )}
            </div>
            <ul style={S.verdictList}>
              {result.verdict.stock.reasons.map((r, i) => <li key={i}>{r}</li>)}
            </ul>
            <div style={S.verdictNote}>What would change this: {result.verdict.stock.what_would_change}</div>
            <div style={S.verdictNote}>{result.verdict.stock.positive_note}</div>

            <div style={S.optionRow}>
              <div style={S.optionBox}>
                <div style={S.optionTitle(result.verdict.put.decision === 'sell' ? 'sell' : 'hold')}>
                  {result.verdict.put.label}
                </div>
                <div style={S.optionLine}>{result.verdict.put.reason}</div>
                {result.verdict.put.decision === 'sell' && (
                  <>
                    <div style={S.optionSub}>
                      Strike ${val(result.verdict.put.strike)} | Expiry {val(result.verdict.put.expiry)} ({val(result.verdict.put.dte)} days) |
                      Premium ${val(result.verdict.put.premium_per_contract)} per contract (bid)
                    </div>
                    <div style={S.optionSub}>
                      Breakeven ${val(result.verdict.put.breakeven)} | You buy at ${val(result.verdict.put.assignment_price)} if assigned |
                      Most you can lose ${val(result.verdict.put.max_loss_per_contract)} per contract |
                      Cushion {val(result.verdict.put.cushion_pct)}%
                      {result.verdict.put.earnings_before_expiry != null && (
                        <span> | Earnings before expiry: {result.verdict.put.earnings_before_expiry ? 'yes' : 'no'}</span>
                      )}
                    </div>
                    <div style={S.optionSub}>{result.verdict.put.why}</div>
                  </>
                )}
              </div>
              <div style={S.optionBox}>
                <div style={S.optionTitle(result.verdict.call.decision === 'buy' ? 'buy' : 'hold')}>
                  {result.verdict.call.label}
                </div>
                <div style={S.optionLine}>{result.verdict.call.reason}</div>
                {result.verdict.call.decision === 'buy' && (
                  <>
                    <div style={S.optionSub}>
                      Strike ${val(result.verdict.call.strike)} | Expiry {val(result.verdict.call.expiry)} ({val(result.verdict.call.dte)} days) |
                      Premium ${val(result.verdict.call.premium_per_contract)} per contract ({val(result.verdict.call.premium_source)})
                    </div>
                    <div style={S.optionSub}>
                      Breakeven ${val(result.verdict.call.breakeven)} | Most you can lose ${val(result.verdict.call.max_loss_per_contract)} per contract |
                      Wrong if the stock closes below ${val(result.verdict.call.invalidation_price)}
                    </div>
                    <div style={S.optionSub}>{result.verdict.call.why}</div>
                  </>
                )}
              </div>
            </div>
          </div>

          <div style={S.card}>
            <div style={S.sectionLabel}>Options Strategies: best call, best put, straddle, iron condor</div>
            <div style={{ marginTop: '6px' }}>
              <OptionStrategiesSummary strategies={result.verdict.option_strategies} />
            </div>
          </div>

          {result.verdict.stock.entry_plan && (
            <div style={S.card}>
              <div style={S.sectionLabel}>Wait for Entry plan</div>
              <div style={{ ...S.note, marginTop: '6px' }}>
                <strong style={{ color: '#e2e8f0' }}>Trigger: </strong>
                {result.verdict.stock.entry_plan.trigger_50d_wording === 'recovery' ? 'Recovery to' : 'Pullback to'} ${val(result.verdict.stock.entry_plan.pullback_price)}
                {result.verdict.stock.entry_plan.distance_to_pullback_pct != null && (
                  <span> ({val(result.verdict.stock.entry_plan.distance_to_pullback_pct)}% from today)</span>
                )}
                {result.verdict.stock.entry_plan.breakout_price != null && (
                  <span> or a close above ${val(result.verdict.stock.entry_plan.breakout_price)}
                  {result.verdict.stock.entry_plan.distance_to_breakout_pct != null && (
                    <span> ({val(result.verdict.stock.entry_plan.distance_to_breakout_pct)}% away)</span>
                  )}</span>
                )}
                {result.verdict.stock.entry_plan.buy_zone && (
                  <span> | Buy zone ${val(result.verdict.stock.entry_plan.buy_zone[0])} to ${val(result.verdict.stock.entry_plan.buy_zone[1])}</span>
                )}
              </div>
              <div style={{ ...S.note, marginTop: '6px' }}>
                <strong style={{ color: '#e2e8f0' }}>Wrong if: </strong>
                {result.verdict.stock.entry_plan.what_flips_to_avoid}
              </div>
              <div style={{ ...S.note, marginTop: '6px' }}>
                <strong style={{ color: '#e2e8f0' }}>What flips it to Buy Now: </strong>
                {result.verdict.stock.entry_plan.what_flips_to_buy}
              </div>
              {result.verdict.stock.entry_plan.blocker && (
                <div style={{ ...S.note, marginTop: '6px' }}>
                  <strong style={{ color: '#e2e8f0' }}>Blocker today: </strong>
                  {result.verdict.stock.entry_plan.blocker}
                </div>
              )}
              <div style={{ ...S.note, marginTop: '6px' }}>
                <strong style={{ color: '#e2e8f0' }}>Drop context: </strong>
                Day {val(result.verdict.stock.entry_plan.drop_context.day_change_pct)}% |
                vs 50-day {val(result.verdict.stock.entry_plan.drop_context.price_vs_ma50_pct)}% |
                vs 200-day {val(result.verdict.stock.entry_plan.drop_context.price_vs_ma200_pct)}% |
                RSI {val(result.verdict.stock.entry_plan.drop_context.rsi)} |
                Volume {val(result.verdict.stock.entry_plan.drop_context.volume_ratio_vs_20d)}x the 20-day average
              </div>
              <div style={{ ...S.note, marginTop: '6px' }}>
                <strong style={{ color: '#e2e8f0' }}>News ({val(result.verdict.stock.entry_plan.news_context.category)}): </strong>
                {result.verdict.stock.entry_plan.news_context.title || 'No headline verified. '}
                {result.verdict.stock.entry_plan.news_context.note}
              </div>
              <div style={{ ...S.note, marginTop: '6px' }}>
                <strong style={{ color: '#e2e8f0' }}>Fundamentals: </strong>
                {result.verdict.stock.entry_plan.fundamentals.status === 'verified' ? (
                  <span>
                    Screener {val(result.verdict.stock.entry_plan.fundamentals.run_date)}: composite {val(result.verdict.stock.entry_plan.fundamentals.composite)} ({val(result.verdict.stock.entry_plan.fundamentals.label)}), smoothed Rule of 40 {val(result.verdict.stock.entry_plan.fundamentals.smoothed_rule_of_40)}, revenue CAGR 3y {val(result.verdict.stock.entry_plan.fundamentals.rev_cagr_3y_pct)}%, FCF margin avg 3y {val(result.verdict.stock.entry_plan.fundamentals.fcf_margin_avg_3y_pct)}%, operating margin {val(result.verdict.stock.entry_plan.fundamentals.operating_margin_pct)}%.
                  </span>
                ) : (
                  <span>{val(result.verdict.stock.entry_plan.fundamentals.note)}</span>
                )}
              </div>
              {result.verdict.stock.entry_plan.notes.map((n, i) => (
                <div key={i} style={{ ...S.note, marginTop: '6px' }}>{n}</div>
              ))}
              <div style={{ ...S.note, marginTop: '6px' }}>
                A dip is not automatically a bargain. This plan shows the trigger and the invalidation, it does not say to buy today.
              </div>
            </div>
          )}

          <div style={S.card}>
            <div style={S.sectionLabel}>Why, in plain language</div>
            <div style={{ ...S.note, marginTop: '6px' }}>
              <strong style={{ color: '#e2e8f0' }}>What supported this: </strong>
              {result.verdict.conviction.supports.length > 0
                ? result.verdict.conviction.supports.join(' ')
                : 'Nothing supported a buy today.'}
            </div>
            <div style={{ ...S.note, marginTop: '6px' }}>
              <strong style={{ color: '#e2e8f0' }}>What was against it: </strong>
              {result.verdict.conviction.against.length > 0
                ? result.verdict.conviction.against.join(' ')
                : 'Nothing was against it.'}
            </div>
            <div style={{ ...S.note, marginTop: '6px' }}>
              <strong style={{ color: '#e2e8f0' }}>What was missing: </strong>
              {result.verdict.conviction.missing.join(' ')}
            </div>
            <div style={{ ...S.note, marginTop: '10px' }}>
              <strong style={{ color: '#e2e8f0' }}>News: </strong>
              {result.news ? result.news.note : 'No fresh company news could be verified.'}
              {result.news && result.news.latest && result.news.latest.published_date && (
                <span> ({val(result.news.latest.published_date)}, {val(result.news.latest.publisher)})</span>
              )}
            </div>
            <div style={{ ...S.note, marginTop: '6px' }}>
              <strong style={{ color: '#e2e8f0' }}>Earnings: </strong>
              {result.verdict.earnings.anticipated_date
                ? `Next report ${val(result.verdict.earnings.anticipated_date)}, ${val(result.verdict.earnings.days_away)} days away. `
                : 'Next earnings date is unknown. '}
              No consensus estimate and no reported beat or miss is available, so nothing is guessed there.
            </div>
          </div>

          <div style={S.card}>
            <div style={{ display: 'flex', gap: '16px', alignItems: 'baseline', flexWrap: 'wrap' }}>
              <span style={S.tickerBig}>{result.ticker}</span>
              <span style={S.priceBig}>${val(result.price)}</span>
              {result.cached && <span style={S.pill('#3d2f10', '#975a16', '#f6e05e')}>CACHED</span>}
            </div>
            <div style={S.meta}>
              Price source: {val(result.price_source)} | Data timestamp: {val(result.data_timestamp)} |
              Fetched: {val(result.fetched_at)}
            </div>
            <div style={{ ...S.grid, marginTop: '14px' }}>
              <div style={S.stat}>
                <span style={S.statLabel}>vs 50-day MA</span>
                <span style={S.statValue}>{val(result.trend.price_vs_ma50_pct)}%</span>
                <span style={S.statSub}>MA50 ${val(result.trend.ma50)}, {val(result.trend.ma50_direction)}</span>
              </div>
              <div style={S.stat}>
                <span style={S.statLabel}>vs 200-day MA</span>
                <span style={S.statValue}>{val(result.trend.price_vs_ma200_pct)}%</span>
                <span style={S.statSub}>MA200 ${val(result.trend.ma200)}, {val(result.trend.ma200_direction)}</span>
              </div>
              <div style={S.stat}>
                <span style={S.statLabel}>Quality score</span>
                <span style={S.statValue}>{val(result.quality.composite)} ({val(result.quality.grade)})</span>
                <span style={S.statSub}>
                  trend {val(result.quality.components.trend)}, RSI {val(result.quality.components.rsi)},
                  volume {val(result.quality.components.volume)}
                </span>
              </div>
              <div style={S.stat}>
                <span style={S.statLabel}>Earnings</span>
                <span style={S.statValue}>{val(result.earnings.earnings_date)}</span>
                <span style={S.statSub}>
                  {result.earnings.status === 'earnings_unknown'
                    ? 'earnings_unknown: fail-closed'
                    : `${val(result.earnings.earnings_days)} days away, ${val(result.earnings.source)}`}
                </span>
              </div>
              <div style={S.stat}>
                <span style={S.statLabel}>IV rank</span>
                <span style={S.statValue}>{val(result.iv.iv_percentile)}</span>
                <span style={S.statSub}>{val(result.iv.source)}</span>
              </div>
              <div style={S.stat}>
                <span style={S.statLabel}>SPY gate</span>
                <span style={S.statValue}>{val(result.spy_gate.gate)}</span>
                <span style={S.statSub}>{val(result.spy_gate.spy_vs_200ma_pct)}% vs 200-day</span>
              </div>
            </div>
            <div style={{ ...S.note, marginTop: '10px' }}>{result.quality.note}</div>
          </div>

          <details style={S.details}>
            <summary style={S.summary}>Rule registry check, full detail (closed by default)</summary>
            <div style={{ marginTop: '12px' }}>
            {result.setups.map((s) => (
              <div key={s.setup_key} style={{ marginBottom: '16px' }}>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
                  <strong style={{ fontSize: '14px', color: '#e2e8f0' }}>{s.setup_name}</strong>
                  <ResultPill result={s.rule_result} status={s.status} />
                  <span style={{ fontSize: '11px', color: '#718096' }}>{s.rule_key}</span>
                </div>
                {s.suppressed_reason && (
                  <div style={{ ...S.note, marginTop: '6px' }}>Suppressed: {s.suppressed_reason}</div>
                )}
                {s.note && <div style={{ ...S.note, marginTop: '6px' }}>{s.note}</div>}
                {s.conditions && Object.keys(s.conditions).length > 0 && (
                  <div style={S.condBox}>
                    {Object.entries(s.conditions).map(([k, v]) => `${k}: ${val(v)}`).join('\n')}
                  </div>
                )}
                {s.action && (
                  <div style={S.ruleBox}>
                    <strong style={{ color: '#e2e8f0' }}>Rule result, not a trade recommendation:</strong>
                    <div style={{ marginTop: '6px' }}>{s.action.action_summary}</div>
                    <div style={{ marginTop: '6px' }}>
                      Action {val(s.action.action)} | Entry ${val(s.action.entry_price)} ({val(s.action.entry_source)}) |
                      Invalidation ${val(s.action.invalidation_price)} |
                      Target {s.action.target_price != null ? `$${s.action.target_price}` : (s.action.exit_rule || 'none')} |
                      Expiry {val(s.action.expiry)}
                    </div>
                    <div style={{ marginTop: '6px' }}>
                      Size: {val(s.action.position_size_shares ?? s.action.position_size_contracts)}
                      {' '}{s.action.position_size_shares != null ? 'shares' : 'contracts'}
                      {' '}({val(s.action.sizing_source)}) | Risk ${val(s.action.risk_dollars)}
                      {' '}({val(s.action.risk_pct_actual)}% of ${val(s.action.account_equity)}, {val(s.action.equity_source)})
                    </div>
                    {s.action.strike != null && (
                      <div style={{ marginTop: '6px' }}>
                        Strike ${val(s.action.strike)} | Premium ${val(s.action.premium)} (listed bid) |
                        Max loss ${val(s.action.max_loss_per_contract)} per contract
                      </div>
                    )}
                    <div style={{ marginTop: '6px' }}>{val(s.action.invalidation_text)}</div>
                  </div>
                )}
              </div>
            ))}
            </div>
          </details>

          <details style={S.details}>
            <summary style={S.summary}>Listed option chain, nearest 21 DTE (closed by default)</summary>
            <div style={{ marginTop: '12px' }}>
            {result.chain.available ? (
              <>
                <div style={{ ...S.note, marginBottom: '10px' }}>
                  Source: {val(result.chain.source)} | Fetched: {val(result.chain.fetched_at)} |
                  Bids and asks are listed quotes; a row with no bid has price source no_executable_bid.
                </div>
                <div style={{ ...S.sectionLabel, marginTop: '12px' }}>Puts</div>
                <ChainTable rows={result.chain.puts} side="put" />
                <div style={{ ...S.sectionLabel, marginTop: '12px' }}>Calls</div>
                <ChainTable rows={result.chain.calls} side="call" />
              </>
            ) : (
              <div style={S.note}>
                No listed chain: {val(result.chain.error)}. The options result is suppressed with that
                named reason instead of a guessed price.
              </div>
            )}
            </div>
          </details>

          <div style={S.card}>
            <div style={S.sectionLabel}>
              Explanation ({result.explanation_source === 'claude' ? 'Claude, plain language only' : 'quant fallback'})
            </div>
            <div style={{ fontSize: '13px', color: '#a0aec0', lineHeight: 1.6 }}>{result.explanation}</div>
            <div style={{ ...S.note, marginTop: '10px' }}>{result.disclaimer}</div>
          </div>
            </>
          )}
        </>
      )}
    </div>
  )
}
