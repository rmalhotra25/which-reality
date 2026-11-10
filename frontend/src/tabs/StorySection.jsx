import { useState } from 'react'
import { api } from '../api'

// Company Story section, shown inside the ticker lookup. A read-only
// explainer: no trade call, no sizing, no LIVE label. The data is
// fetched lazily on first expand so the lookup itself stays fast.

const S = {
  card: {
    background: '#131825', border: '1px solid #2d3748', borderRadius: '10px',
    padding: '16px',
  },
  button: {
    padding: '9px 18px', background: '#2b6cb0', color: '#fff', border: 'none',
    borderRadius: '8px', cursor: 'pointer', fontSize: '14px', fontWeight: 700,
  },
  note: { fontSize: '12px', color: '#a0aec0', lineHeight: 1.5 },
  panelTitle: { fontSize: '16px', fontWeight: 800, color: '#e2e8f0' },
  grid: {
    display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
    gap: '12px', marginTop: '12px',
  },
  panel: {
    background: '#0f1520', border: '1px solid #2d3748', borderRadius: '10px',
    padding: '14px',
  },
  barRow: { display: 'flex', alignItems: 'center', gap: '8px', marginTop: '6px' },
  barLabel: { width: '52px', fontSize: '13px', color: '#e2e8f0', fontWeight: 700 },
  barTrack: { flex: 1, background: '#2d3748', borderRadius: '4px', height: '10px', overflow: 'hidden' },
  barFill: (pct) => ({ width: `${Math.max(2, Math.min(100, pct))}%`, background: '#4299e1', height: '10px' }),
  barPct: { width: '44px', textAlign: 'right', fontSize: '13px', color: '#a0aec0' },
  gauge: { fontSize: '13px', color: '#e2e8f0', marginTop: '8px' },
  gaugeLabel: { fontWeight: 800 },
  gaugeBasis: { color: '#a0aec0', fontSize: '12px' },
}

function money(v) {
  if (v == null) return '—'
  if (Math.abs(v) >= 1e9) return `$${(v / 1e9).toFixed(1)}B`
  if (Math.abs(v) >= 1e6) return `$${(v / 1e6).toFixed(0)}M`
  return `$${v}`
}

function Dots({ n, tone }) {
  const count = Math.max(1, Math.min(3, n || 1))
  const filled = '●'.repeat(count)
  const empty = '○'.repeat(3 - count)
  const color = tone === 'bad' ? '#fc8181' : count >= 3 ? '#68d391' : count === 2 ? '#f6e05e' : '#a0aec0'
  return <span style={{ color, letterSpacing: '2px' }}>{filled}{empty}</span>
}

export default function StorySection({ ticker }) {
  const [open, setOpen] = useState(false)
  const [story, setStory] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  async function toggle() {
    const next = !open
    setOpen(next)
    if (next && !story && !loading) {
      setLoading(true)
      setError(null)
      try {
        const data = await api.story.get(ticker)
        setStory(data)
      } catch (err) {
        setError(err.message || 'Story failed to load')
      } finally {
        setLoading(false)
      }
    }
  }

  return (
    <div style={S.card}>
      <button style={S.button} type="button" onClick={toggle}>
        {open ? 'Hide company overview' : 'View company overview'}
      </button>
      {!open && (
        <div style={{ ...S.note, marginTop: '8px' }}>
          A plain-language profile of the company: market position, revenue mix, growth, and outlook. Read-only, no trade call.
        </div>
      )}
      {open && loading && <div style={{ ...S.note, marginTop: '12px' }}>Loading the story…</div>}
      {open && error && <div style={{ ...S.note, marginTop: '12px', color: '#fc8181' }}>{error}</div>}
      {open && story && story.status === 'unavailable' && (
        <div style={{ ...S.note, marginTop: '12px' }}>Story unavailable: {story.reason}</div>
      )}
      {open && story && story.status === 'ok' && (
        <div style={{ marginTop: '12px' }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'baseline', gap: '8px' }}>
            <span style={{ fontSize: '20px', fontWeight: 800, color: '#e2e8f0' }}>{story.name}</span>
            <span style={{ fontSize: '14px', color: '#a0aec0', fontWeight: 700 }}>{story.ticker}</span>
            <span style={{
              fontSize: '13px', fontWeight: 800, color: '#1a202c',
              background: story.grade === 'A' || story.grade === 'B' ? '#68d391' : story.grade === 'C' ? '#f6e05e' : '#fc8181',
              borderRadius: '6px', padding: '2px 8px',
            }}>Grade {story.grade}</span>
            <span style={{ fontSize: '18px', fontWeight: 800, color: '#e2e8f0' }}>${story.price}</span>
          </div>
          <div style={{ ...S.note, marginTop: '4px' }}>{story.grade_reason}</div>
          {story.earnings_date && (
            <div style={{ ...S.note, marginTop: '4px' }}>Next earnings: {story.earnings_date}</div>
          )}
          {story.earnings_unknown && (
            <div style={{ ...S.note, marginTop: '4px' }}>Next earnings date unknown.</div>
          )}
          {story.week52 && (
            <div style={{ marginTop: '8px' }}>
              <div style={{ ...S.note }}>52-week range ${story.week52.low} to ${story.week52.high}</div>
              <div style={{ ...S.barTrack, marginTop: '4px', position: 'relative' }}>
                <div style={{ position: 'absolute', left: `${story.week52.position_pct}%`, top: 0, bottom: 0, width: '3px', background: '#fff' }} />
              </div>
            </div>
          )}
          <div style={{ fontSize: '15px', color: '#e2e8f0', lineHeight: 1.6, marginTop: '12px' }}>
            {story.story_line}
          </div>
          {story.consistency_note && (
            <div style={{ ...S.note, marginTop: '8px', color: '#f6e05e' }}>{story.consistency_note}</div>
          )}

          <div style={S.grid}>
            <div style={S.panel}>
              <div style={S.panelTitle}>Market position</div>
              {story.peers ? (
                <div style={{ marginTop: '8px' }}>
                  <div style={S.note}>{story.industry || story.sector || ''} · share of combined market value, top peers</div>
                  {story.peers.map((p) => (
                    <div key={p.ticker} style={S.barRow}>
                      <span style={{ ...S.barLabel, color: p.is_subject ? '#4299e1' : '#e2e8f0' }}>{p.ticker}</span>
                      <div style={S.barTrack}><div style={S.barFill(p.share_pct)} /></div>
                      <span style={S.barPct}>{p.share_pct}%</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div style={{ ...S.note, marginTop: '8px' }}>Peer shares unavailable.</div>
              )}
              <div style={{ marginTop: '12px' }}>
                {Object.entries(story.gauges).map(([key, g]) => (
                  <div key={key} style={S.gauge}>
                    <span style={S.gaugeLabel}>{({ growth: 'Growth', margins: 'Margins', debt: 'Debt', price: 'Valuation' })[key] || key}: {g.label}</span>
                    <span style={S.gaugeBasis}> · {g.basis}</span>
                  </div>
                ))}
              </div>
            </div>

            <div style={S.panel}>
              <div style={S.panelTitle}>Revenue mix</div>
              {story.segments ? (
                <>
                  <div style={{ ...S.note, marginTop: '4px' }}>Revenue mix, {story.segments.as_of || ''}</div>
                  {story.segments.product && story.segments.product.length > 0 && (
                    <div style={{ marginTop: '8px' }}>
                      <div style={{ fontSize: '13px', fontWeight: 700, color: '#e2e8f0' }}>By segment</div>
                      {story.segments.product.map((s) => (
                        <div key={s.name} style={S.barRow}>
                          <span style={{ ...S.barLabel, width: '110px' }}>{s.name}</span>
                          <div style={S.barTrack}><div style={S.barFill(s.pct)} /></div>
                          <span style={S.barPct}>{s.pct}%{s.growth_pct != null ? ` (+${Math.round(s.growth_pct)}%)` : ''}</span>
                        </div>
                      ))}
                    </div>
                  )}
                  {story.segments.region && story.segments.region.length > 0 && (
                    <div style={{ marginTop: '8px' }}>
                      <div style={{ fontSize: '13px', fontWeight: 700, color: '#e2e8f0' }}>By geography</div>
                      {story.segments.region.map((s) => (
                        <div key={s.name} style={S.barRow}>
                          <span style={{ ...S.barLabel, width: '110px' }}>{s.name}</span>
                          <div style={S.barTrack}><div style={S.barFill(s.pct)} /></div>
                          <span style={S.barPct}>{s.pct}%{s.growth_pct != null ? ` (+${Math.round(s.growth_pct)}%)` : ''}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              ) : (
                <div style={{ ...S.note, marginTop: '8px' }}>Segment data unavailable from FMP, so no mix is shown rather than a guessed one.</div>
              )}
            </div>

            <div style={S.panel}>
              <div style={S.panelTitle}>Growth and profitability</div>
              <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap', marginTop: '8px' }}>
                {story.growth.multiple_text && (
                  <div><div style={{ fontSize: '20px', fontWeight: 800, color: '#68d391' }}>{story.growth.multiple_text.split(' ')[0]}</div>
                  <div style={S.note}>{story.growth.multiple_text.split(' ').slice(1).join(' ')}</div></div>
                )}
                {story.growth.gross_margin_pct != null && (
                  <div><div style={{ fontSize: '20px', fontWeight: 800, color: '#e2e8f0' }}>{story.growth.gross_margin_pct}%</div>
                  <div style={S.note}>gross margin</div></div>
                )}
                {story.growth.eps_ttm != null && (
                  <div><div style={{ fontSize: '20px', fontWeight: 800, color: '#e2e8f0' }}>${story.growth.eps_ttm}</div>
                  <div style={S.note}>earnings per share, trailing 12 months</div></div>
                )}
              </div>
              <div style={{ display: 'flex', alignItems: 'flex-end', gap: '6px', marginTop: '14px', height: '120px' }}>
                {story.growth.bars.map((b) => {
                  const max = Math.max(...story.growth.bars.map((x) => x.revenue))
                  const h = Math.max(6, Math.round((b.revenue / max) * 110))
                  return (
                    <div key={b.year} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '2px' }}>
                      <span style={{ fontSize: '11px', color: '#a0aec0' }}>{money(b.revenue)}</span>
                      <div style={{
                        width: '100%', height: `${h}px`, borderRadius: '4px 4px 0 0',
                        background: b.estimated ? 'repeating-linear-gradient(45deg, #2b6cb0, #2b6cb0 4px, #1a365d 4px, #1a365d 8px)' : '#2b6cb0',
                      }} />
                      <span style={{ fontSize: '11px', color: '#a0aec0' }}>{b.year}{b.estimated ? 'e' : ''}</span>
                      {b.growth_pct != null && (
                        <span style={{ fontSize: '11px', color: '#68d391' }}>+{Math.round(b.growth_pct)}%</span>
                      )}
                    </div>
                  )
                })}
              </div>
              <div style={{ ...S.note, marginTop: '6px' }}>Solid bars are reported results; hatched bars are analyst estimates.</div>
            </div>

            <div style={S.panel}>
              <div style={S.panelTitle}>Outlook</div>
              {story.targets ? (
                <>
                  <div style={{ ...S.note, marginTop: '4px' }}>Analyst price targets</div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '13px', color: '#a0aec0', marginTop: '8px' }}>
                    <span>${story.targets.low} low</span>
                    <span style={{ color: '#4299e1', fontWeight: 800 }}>${story.targets.mean} mean target</span>
                    <span>${story.targets.high} high</span>
                  </div>
                  <div style={{ ...S.barTrack, marginTop: '4px', position: 'relative' }}>
                    <div style={{ position: 'absolute', left: `${Math.max(0, Math.min(100, ((story.targets.now - story.targets.low) / (story.targets.high - story.targets.low)) * 100))}%`, top: 0, bottom: 0, width: '3px', background: '#fff' }} />
                  </div>
                  <div style={{ ...S.note, marginTop: '4px' }}>Now ${story.targets.now}. Mean target is {story.targets.mean_vs_now_pct}% {story.targets.mean_vs_now_pct >= 0 ? 'above' : 'below'} today.</div>
                  {story.targets.analysts && (
                    <div style={{ display: 'flex', marginTop: '8px', borderRadius: '6px', overflow: 'hidden', fontSize: '12px', fontWeight: 700 }}>
                      <div style={{ flex: story.targets.analysts.buy, background: '#38a169', color: '#fff', padding: '4px 6px' }}>{story.targets.analysts.buy} Buy</div>
                      <div style={{ flex: story.targets.analysts.hold, background: '#4a5568', color: '#fff', padding: '4px 6px' }}>{story.targets.analysts.hold} Hold</div>
                      <div style={{ flex: Math.max(1, story.targets.analysts.sell), background: '#e53e3e', color: '#fff', padding: '4px 6px' }}>{story.targets.analysts.sell} Sell</div>
                    </div>
                  )}
                  {story.targets.dcf_base != null && (
                    <div style={{ ...S.note, marginTop: '8px' }}>
                      DCF fair value, base case: ${story.targets.dcf_base} a share. This is the same DCF as the long-term card, shown next to the analyst mean so the two anchors can be compared.
                    </div>
                  )}
                </>
              ) : (
                <div style={{ ...S.note, marginTop: '8px' }}>Analyst targets unavailable.</div>
              )}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginTop: '12px' }}>
                <div>
                  <div style={{ fontSize: '13px', fontWeight: 700, color: '#68d391' }}>Tailwinds</div>
                  {story.tailwinds.map((t) => (
                    <div key={t.title} style={{ ...S.note, marginTop: '6px', color: '#e2e8f0' }}>
                      <strong>{t.title}</strong> · {t.detail} <Dots n={t.strength} />
                    </div>
                  ))}
                  {story.tailwinds.length === 0 && <div style={S.note}>None flagged by the rules.</div>}
                </div>
                <div>
                  <div style={{ fontSize: '13px', fontWeight: 700, color: '#fc8181' }}>Headwinds</div>
                  {story.headwinds.map((t) => (
                    <div key={t.title} style={{ ...S.note, marginTop: '6px', color: '#e2e8f0' }}>
                      <strong>{t.title}</strong> · {t.detail} <Dots n={t.strength} tone="bad" />
                    </div>
                  ))}
                  {story.headwinds.length === 0 && <div style={S.note}>None flagged by the rules.</div>}
                </div>
              </div>
              <div style={{ ...S.note, marginTop: '12px', color: '#e2e8f0' }}>{story.what_would_change}</div>
              <div style={{ ...S.note, marginTop: '8px' }}>
                Long-term assessment: {story.longterm_verdict || 'unavailable'}. See the long-term card below for the DCF detail.
              </div>
            </div>
          </div>
          {story.notes && story.notes.length > 0 && (
            <div style={{ ...S.note, marginTop: '12px' }}>
              Notes: {story.notes.join(' ')}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
