import { useEffect, useRef, useState } from 'react'
import { api } from '../api'

// AI Picks: an ideas-only research surface, visually and logically
// separate from Today's Book and every rule-based tab. Nothing here
// is backtested, nothing is LIVE, and nothing here ever feeds the
// Book scoreboard. Every idea carries an AI-GENERATED badge and the
// disclaimer at the top of this view.

const card = {
  background: '#131825',
  border: '1px solid #2d3748',
  borderRadius: '12px',
  padding: '18px 20px',
  marginBottom: '12px',
}

const muted = { color: '#a0aec0', fontSize: '13px', lineHeight: 1.5 }
const label = { color: '#718096', fontSize: '11px', fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase' }

const AI_BADGE = { bg: '#2a1a3d', border: '#805ad5', text: '#d6bcfa' }
const BUY = { bg: '#071a0a', border: '#276749', text: '#68d391' }
const SELL = { bg: '#2d1515', border: '#742a2a', text: '#fc8181' }

function money(n, digits = 2) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return `$${Number(n).toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })}`
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

function fmtDate(iso) {
  if (!iso) return '—'
  try { return new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) } catch { return '—' }
}

function OptionIdeaCard({ idea }) {
  const action = `${idea.action === 'buy' ? 'Buy' : 'Sell'} a ${idea.option_type}`
  return (
    <div style={card}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
        <div style={{ fontSize: '18px', fontWeight: 800, color: '#e2e8f0' }}>
          {idea.ticker} <span style={{ fontWeight: 500, color: '#a0aec0', fontSize: '14px' }}>{action} ${idea.strike} {idea.option_type}</span>
        </div>
        <div style={{ display: 'flex', gap: '6px' }}>
          {badge(idea.action === 'buy' ? 'BUY' : 'SELL', idea.action === 'buy' ? BUY : SELL)}
          {badge('AI-GENERATED IDEA', AI_BADGE)}
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: '12px', marginTop: '14px' }}>
        <div><div style={label}>Strike</div><div style={{ fontSize: '17px', fontWeight: 700, color: '#e2e8f0' }}>${idea.strike}</div></div>
        <div><div style={label}>Expiry</div><div style={{ fontSize: '17px', fontWeight: 700, color: '#e2e8f0' }}>{idea.expiry || '—'}</div></div>
        <div><div style={label}>Buy in at</div><div style={{ fontSize: '17px', fontWeight: 700, color: '#e2e8f0' }}>{money(idea.entry_price)}</div></div>
        <div><div style={label}>Get out at</div><div style={{ fontSize: '17px', fontWeight: 700, color: '#e2e8f0' }}>{money(idea.exit_price)}</div></div>
        <div><div style={label}>Stop</div><div style={{ fontSize: '17px', fontWeight: 700, color: '#e2e8f0' }}>{money(idea.stop_price)}</div></div>
        <div><div style={label}>Underlying ref</div><div style={{ fontSize: '17px', fontWeight: 700, color: '#e2e8f0' }}>{money(idea.reference_price)}</div><div style={{ fontSize: '11px', color: '#718096' }}>{idea.price_source === 'polygon' ? 'Polygon price' : 'Price unavailable'}</div></div>
      </div>
      {idea.plan_text && <p style={{ ...muted, marginTop: '14px' }}><strong style={{ color: '#e2e8f0' }}>Plan: </strong>{idea.plan_text}</p>}
      {idea.reasoning && <p style={muted}><strong style={{ color: '#e2e8f0' }}>Why: </strong>{idea.reasoning}</p>}
      {idea.key_risks?.length > 0 && <p style={muted}><strong style={{ color: '#e2e8f0' }}>Risks: </strong>{idea.key_risks.join(' · ')}</p>}
    </div>
  )
}

function LongTermCard({ idea }) {
  const priceLabel = idea.price_source === 'polygon'
    ? 'Polygon price'
    : idea.price_source === 'ai_claimed'
      ? 'Price as claimed by the model, not verified'
      : 'Price unavailable'
  return (
    <div style={card}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
        <div style={{ fontSize: '18px', fontWeight: 800, color: '#e2e8f0' }}>
          {idea.ticker} <span style={{ fontWeight: 500, color: '#a0aec0', fontSize: '14px' }}>{idea.company_name}</span>
        </div>
        <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
          <span style={{ fontSize: '17px', fontWeight: 700, color: '#e2e8f0' }}>{money(idea.current_price)}</span>
          {badge('AI-GENERATED IDEA', AI_BADGE)}
        </div>
      </div>
      <div style={{ fontSize: '11px', color: '#718096', marginTop: '2px' }}>{priceLabel}</div>
      {idea.thesis && <p style={{ ...muted, marginTop: '10px' }}>{idea.thesis}</p>}
      {idea.upside_case && <p style={muted}><strong style={{ color: '#e2e8f0' }}>Upside case: </strong>{idea.upside_case}</p>}
      {idea.key_risks?.length > 0 && <p style={muted}><strong style={{ color: '#e2e8f0' }}>Key risks: </strong>{idea.key_risks.join(' · ')}</p>}
    </div>
  )
}

const DEFAULT_TICKERS = 'MSFT, NVDA, AAPL, AMZN, META, GOOGL, TSLA, AMD, PLTR, XOM'

export default function AIPicksTab() {
  const [run, setRun] = useState(null)
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState(null)
  const [tickers, setTickers] = useState(DEFAULT_TICKERS)
  const pollRef = useRef(null)

  async function load() {
    try {
      const data = await api.aiPicks.latest()
      setRun(data.run)
      setGenerating(Boolean(data.generating))
      return data
    } catch (e) {
      setError(e?.message || 'Could not load AI Picks.')
      return null
    }
  }

  useEffect(() => {
    load()
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (generating) {
      pollRef.current = setInterval(async () => {
        const data = await load()
        if (data && !data.generating) clearInterval(pollRef.current)
      }, 5000)
      return () => clearInterval(pollRef.current)
    }
    return undefined
  }, [generating])

  async function generate() {
    setError(null)
    const list = tickers.split(/[,\s]+/).map((t) => t.trim().toUpperCase()).filter(Boolean)
    if (list.length === 0) {
      setError('Enter at least one ticker to generate ideas for.')
      return
    }
    try {
      await api.aiPicks.generate(list)
      setGenerating(true)
      setRun((r) => (r ? { ...r, status: 'generating' } : r))
    } catch (e) {
      setError(e?.message || 'Generation could not start.')
    }
  }

  const optionsIdeas = run?.options_ideas || []
  const longTermIdeas = run?.long_term_ideas || []

  return (
    <div style={{ padding: '20px', maxWidth: '900px', margin: '0 auto' }}>
      <div style={{ marginBottom: '16px' }}>
        <h1 style={{ margin: 0, fontSize: '22px', color: '#e2e8f0' }}>🤖 AI Picks</h1>
        <p style={{ ...muted, marginTop: '4px' }}>
          Ideas from Claude, grounded in delayed Polygon prices, charts, and headlines. Separate from the rule-based system.
        </p>
      </div>

      <div style={{
        background: '#2a1a3d', border: '1px solid #805ad5', borderRadius: '12px',
        padding: '14px 18px', marginBottom: '16px', color: '#d6bcfa', fontSize: '14px', lineHeight: 1.5,
      }}>
        <strong>These are AI-generated ideas only. They are not based on the app's backtested rules and are not recommendations.</strong>
        <div style={{ marginTop: '6px', fontSize: '13px', color: '#b794f4' }}>
          {run?.data_note || 'Prices and chain data are delayed about 15 minutes. Suggested strikes are AI proposals, not verified tradable prices. Check the live chain before acting on any idea.'}
        </div>
      </div>

      <div style={{ ...card, display: 'flex', gap: '10px', flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <div style={{ flex: '1 1 320px' }}>
          <div style={label}>Tickers for options ideas (comma separated)</div>
          <input
            value={tickers}
            onChange={(e) => setTickers(e.target.value)}
            style={{ width: '100%', marginTop: '6px', padding: '9px 10px', borderRadius: '8px', border: '1px solid #4a5568', background: '#1a202c', color: '#e2e8f0', fontSize: '14px' }}
            placeholder={DEFAULT_TICKERS}
          />
        </div>
        <button
          onClick={generate}
          disabled={generating}
          style={{
            padding: '10px 18px', borderRadius: '8px', border: 'none',
            background: generating ? '#4a5568' : '#805ad5', color: '#fff',
            fontWeight: 700, fontSize: '14px', cursor: generating ? 'default' : 'pointer',
          }}
        >
          {generating ? 'Generating…' : 'Generate new ideas'}
        </button>
      </div>

      {error && <div style={{ color: '#fc8181', fontSize: '13px', marginBottom: '12px' }}>{error}</div>}
      {run?.status === 'failed' && <div style={{ color: '#fc8181', fontSize: '13px', marginBottom: '12px' }}>Generation failed: {run.error || 'unknown error'}. Try again.</div>}
      {run?.parse_error && <div style={{ color: '#f6e05e', fontSize: '13px', marginBottom: '12px' }}>The model returned partial results: {run.parse_error}</div>}
      {generating && <p style={muted}>Claude is reviewing the charts and headlines. This takes about a minute.</p>}

      {!run && !generating && (
        <p style={muted}>No ideas yet. Press “Generate new ideas” and Claude will review the tickers above.</p>
      )}

      {run && (
        <div style={{ fontSize: '12px', color: '#718096', marginBottom: '16px' }}>
          Generated {fmtDate(run.created_at)} · Tickers: {(run.tickers || []).join(', ')}
        </div>
      )}

      {optionsIdeas.length > 0 && (
        <>
          <h2 style={{ color: '#e2e8f0', fontSize: '16px', margin: '20px 0 10px' }}>Options ideas</h2>
          {optionsIdeas.map((idea, i) => <OptionIdeaCard key={`${idea.ticker}-${idea.strike}-${i}`} idea={idea} />)}
        </>
      )}

      {longTermIdeas.length > 0 && (
        <>
          <h2 style={{ color: '#e2e8f0', fontSize: '16px', margin: '20px 0 10px' }}>Long-term stock ideas · multi-year hold</h2>
          {longTermIdeas.map((idea, i) => <LongTermCard key={`${idea.ticker}-${i}`} idea={idea} />)}
        </>
      )}

      {run && run.status === 'completed' && optionsIdeas.length === 0 && longTermIdeas.length === 0 && (
        <p style={muted}>Claude returned no usable ideas this time. Try generating again, or with different tickers.</p>
      )}
    </div>
  )
}
