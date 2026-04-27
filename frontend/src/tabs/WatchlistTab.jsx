import { useState, useEffect } from 'react'
import { api } from '../api'
import GradeChip from '../components/GradeChip'
import ScoreBar from '../components/ScoreBar'

const STRATEGY_LABELS = {
  wheel: '🔄 Wheel',
  options: '📈 Options',
  longterm: '🌱 Long-Term',
  'long-term': '🌱 Long-Term',
}

const s = {
  page: { display: 'flex', flexDirection: 'column', gap: '24px' },
  title: { fontSize: '20px', fontWeight: 700, color: '#e2e8f0', marginBottom: '4px' },
  subtitle: { fontSize: '13px', color: '#718096' },
  addRow: { display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' },
  input: {
    padding: '10px 14px', background: '#1a1f2e',
    border: '1px solid #2d3748', borderRadius: '8px',
    color: '#e2e8f0', fontSize: '16px', fontWeight: 700,
    textTransform: 'uppercase', letterSpacing: '0.08em',
    outline: 'none', width: '140px',
  },
  noteInput: {
    flex: 1, minWidth: '180px',
    padding: '10px 14px', background: '#1a1f2e',
    border: '1px solid #2d3748', borderRadius: '8px',
    color: '#a0aec0', fontSize: '13px', outline: 'none',
  },
  addBtn: {
    padding: '10px 20px', background: '#276749',
    color: '#fff', border: 'none', borderRadius: '8px',
    cursor: 'pointer', fontSize: '14px', fontWeight: 600,
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
    gap: '14px',
  },
  card: (hasWarning) => ({
    background: '#131825',
    border: `1px solid ${hasWarning ? '#744210' : '#2d3748'}`,
    borderRadius: '12px', padding: '18px',
    display: 'flex', flexDirection: 'column', gap: '12px',
  }),
  cardHeader: { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' },
  ticker: { fontSize: '22px', fontWeight: 800, color: '#90cdf4' },
  addedDate: { fontSize: '11px', color: '#4a5568' },
  scoreRow: { display: 'flex', gap: '6px', flexWrap: 'wrap', alignItems: 'center' },
  stratLabel: {
    fontSize: '10px', color: '#718096',
    textTransform: 'uppercase', letterSpacing: '0.04em',
    minWidth: '70px',
  },
  bestBadge: (strat) => ({
    padding: '3px 10px',
    background: strat === 'wheel' ? '#0a1f12' : strat === 'options' ? '#0a1220' : '#0f1f0a',
    border: `1px solid ${strat === 'wheel' ? '#276749' : strat === 'options' ? '#2b6cb0' : '#276749'}`,
    borderRadius: '4px',
    color: strat === 'wheel' ? '#68d391' : strat === 'options' ? '#63b3ed' : '#9ae6b4',
    fontSize: '11px', fontWeight: 700,
  }),
  warning: {
    background: '#1a1209', border: '1px solid #744210',
    borderRadius: '6px', padding: '8px 10px',
    fontSize: '12px', color: '#f6ad55',
  },
  summary: { fontSize: '13px', color: '#a0aec0', lineHeight: 1.6 },
  notes: { fontSize: '12px', color: '#4a5568', fontStyle: 'italic' },
  lastScored: { fontSize: '11px', color: '#4a5568' },
  btnRow: { display: 'flex', gap: '6px', marginTop: '4px' },
  scoreBtn: {
    padding: '6px 14px', background: '#1a1f2e',
    border: '1px solid #2d3748', borderRadius: '6px',
    color: '#a0aec0', cursor: 'pointer', fontSize: '12px',
  },
  removeBtn: {
    padding: '6px 10px', background: 'transparent',
    border: '1px solid #4a5568', borderRadius: '6px',
    color: '#718096', cursor: 'pointer', fontSize: '12px',
  },
  empty: {
    background: '#131825', border: '1px solid #2d3748',
    borderRadius: '10px', padding: '40px',
    textAlign: 'center', color: '#718096', fontSize: '14px',
  },
  error: { color: '#fc8181', fontSize: '13px' },
}

function WatchlistCard({ item, onScore, onRemove, scoring }) {
  const hasWarning = !!item.earnings_warning
  const strategies = [
    { key: 'wheel', score: item.wheel_score, grade: item.wheel_grade },
    { key: 'options', score: item.options_score, grade: item.options_grade },
    { key: 'longterm', score: item.longterm_score, grade: item.longterm_grade },
  ].filter(s => s.score != null)

  return (
    <div style={s.card(hasWarning)}>
      <div style={s.cardHeader}>
        <div>
          <div style={s.ticker}>{item.ticker}</div>
          <div style={s.addedDate}>Added {new Date(item.added_at).toLocaleDateString()}</div>
        </div>
        {item.best_strategy && (
          <span style={s.bestBadge(item.best_strategy)}>
            Best: {STRATEGY_LABELS[item.best_strategy] || item.best_strategy}
          </span>
        )}
      </div>

      {hasWarning && (
        <div style={s.warning}>{item.earnings_warning}</div>
      )}

      {strategies.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {strategies.map(({ key, score, grade }) => (
            <div key={key} style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <span style={s.stratLabel}>{STRATEGY_LABELS[key] || key}</span>
              <div style={{ flex: 1 }}><ScoreBar score={score} /></div>
              <GradeChip grade={grade} />
            </div>
          ))}
        </div>
      )}

      {item.score_summary && (
        <div style={s.summary}>{item.score_summary}</div>
      )}

      {item.notes && <div style={s.notes}>Note: {item.notes}</div>}

      {item.last_scored && (
        <div style={s.lastScored}>
          Last scored: {new Date(item.last_scored).toLocaleString()}
        </div>
      )}

      <div style={s.btnRow}>
        <button style={s.scoreBtn} onClick={() => onScore(item.ticker)} disabled={scoring}>
          {scoring ? '⏳ Analyzing…' : item.last_scored ? '↻ Refresh Score' : '▶ Score This Stock'}
        </button>
        <button style={s.removeBtn} onClick={() => onRemove(item.ticker)} title="Remove from watchlist">
          ✕ Remove
        </button>
      </div>
    </div>
  )
}

export default function WatchlistTab() {
  const [items, setItems] = useState([])
  const [ticker, setTicker] = useState('')
  const [notes, setNotes] = useState('')
  const [loading, setLoading] = useState(true)
  const [adding, setAdding] = useState(false)
  const [scoring, setScoring] = useState({}) // { ticker: true/false }
  const [error, setError] = useState(null)

  const load = async () => {
    try {
      const data = await api.watchlist.list()
      setItems(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const handleAdd = async () => {
    const sym = ticker.trim().toUpperCase()
    if (!sym) return
    setAdding(true)
    setError(null)
    try {
      const item = await api.watchlist.add(sym, notes)
      setItems(prev => [item, ...prev])
      setTicker('')
      setNotes('')
    } catch (e) {
      setError(e.message)
    } finally {
      setAdding(false)
    }
  }

  const handleScore = async (sym) => {
    setScoring(prev => ({ ...prev, [sym]: true }))
    try {
      const updated = await api.watchlist.score(sym)
      setItems(prev => prev.map(i => i.ticker === sym ? updated : i))
    } catch (e) {
      setError(e.message)
    } finally {
      setScoring(prev => ({ ...prev, [sym]: false }))
    }
  }

  const handleRemove = async (sym) => {
    try {
      await api.watchlist.remove(sym)
      setItems(prev => prev.filter(i => i.ticker !== sym))
    } catch (e) {
      setError(e.message)
    }
  }

  return (
    <div style={s.page}>
      <div>
        <div style={s.title}>Watchlist</div>
        <div style={s.subtitle}>
          Add any stock to score it across all three strategies simultaneously — wheel, options, and long-term
        </div>
      </div>

      <div style={s.addRow}>
        <input
          style={s.input}
          value={ticker}
          onChange={e => setTicker(e.target.value.toUpperCase())}
          onKeyDown={e => e.key === 'Enter' && handleAdd()}
          placeholder="AAPL"
          maxLength={5}
        />
        <input
          style={s.noteInput}
          value={notes}
          onChange={e => setNotes(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleAdd()}
          placeholder="Optional note (e.g. 'watching for breakout')"
          maxLength={200}
        />
        <button style={s.addBtn} onClick={handleAdd} disabled={adding || !ticker.trim()}>
          {adding ? '⏳' : '+ Add to Watchlist'}
        </button>
      </div>

      {error && <div style={s.error}>⚠ {error}</div>}

      {!loading && items.length === 0 && !error && (
        <div style={s.empty}>
          Your watchlist is empty. Add tickers above to score them across all strategies.
          <br />
          <small style={{ color: '#4a5568', display: 'block', marginTop: '8px' }}>
            Great for keeping an eye on stocks before committing to a trade
          </small>
        </div>
      )}

      <div style={s.grid}>
        {items.map(item => (
          <WatchlistCard
            key={item.ticker}
            item={item}
            onScore={handleScore}
            onRemove={handleRemove}
            scoring={!!scoring[item.ticker]}
          />
        ))}
      </div>
    </div>
  )
}
