import { useState } from 'react'
import { api } from '../api'
import GradeChip from '../components/GradeChip'
import ScoreBar from '../components/ScoreBar'
import TradingViewWidget from '../components/TradingViewWidget'

const s = {
  header: { marginBottom: '24px' },
  title: { fontSize: '20px', fontWeight: 700, color: '#e2e8f0', marginBottom: '4px' },
  subtitle: { fontSize: '13px', color: '#718096' },
  searchRow: {
    display: 'flex',
    gap: '10px',
    marginBottom: '28px',
    alignItems: 'center',
    flexWrap: 'wrap',
  },
  input: {
    flex: '1',
    minWidth: '160px',
    maxWidth: '220px',
    padding: '10px 14px',
    background: '#1a1f2e',
    border: '1px solid #2d3748',
    borderRadius: '8px',
    color: '#e2e8f0',
    fontSize: '16px',
    fontWeight: 700,
    textTransform: 'uppercase',
    letterSpacing: '0.08em',
    outline: 'none',
  },
  analyzeBtn: (loading) => ({
    padding: '10px 22px',
    background: loading ? '#2d3748' : '#2b6cb0',
    color: loading ? '#718096' : '#fff',
    border: 'none',
    borderRadius: '8px',
    cursor: loading ? 'not-allowed' : 'pointer',
    fontSize: '14px',
    fontWeight: 600,
    whiteSpace: 'nowrap',
  }),
  error: { color: '#fc8181', padding: '16px', fontSize: '14px', marginBottom: '16px' },
  card: {
    background: '#1a1f2e',
    border: '1px solid #2d3748',
    borderRadius: '12px',
    padding: '24px',
    display: 'flex',
    flexDirection: 'column',
    gap: '20px',
    maxWidth: '860px',
  },
  cardHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    flexWrap: 'wrap',
    gap: '12px',
  },
  tickerRow: { display: 'flex', alignItems: 'center', gap: '14px', flexWrap: 'wrap' },
  ticker: { fontSize: '28px', fontWeight: 800, color: '#90cdf4' },
  price: { fontSize: '22px', fontWeight: 700, color: '#e2e8f0' },
  ratingBadge: (rating) => ({
    display: 'inline-flex',
    alignItems: 'center',
    padding: '6px 16px',
    borderRadius: '6px',
    fontSize: '15px',
    fontWeight: 800,
    letterSpacing: '0.08em',
    background:
      rating === 'BUY' ? '#1a3a2a' :
      rating === 'SELL' ? '#3a1a1a' : '#2a2a1a',
    color:
      rating === 'BUY' ? '#68d391' :
      rating === 'SELL' ? '#fc8181' : '#f6e05e',
    border: `1px solid ${
      rating === 'BUY' ? '#276749' :
      rating === 'SELL' ? '#742a2a' : '#744210'
    }`,
  }),
  conviction: (level) => ({
    fontSize: '11px',
    fontWeight: 700,
    padding: '3px 10px',
    borderRadius: '4px',
    letterSpacing: '0.06em',
    background: level === 'HIGH' ? '#1a2f2a' : level === 'MEDIUM' ? '#1a2a3a' : '#2d3748',
    color: level === 'HIGH' ? '#68d391' : level === 'MEDIUM' ? '#63b3ed' : '#a0aec0',
    border: `1px solid ${level === 'HIGH' ? '#276749' : level === 'MEDIUM' ? '#2b6cb0' : '#4a5568'}`,
  }),
  sectionLabel: {
    fontSize: '11px',
    color: '#718096',
    textTransform: 'uppercase',
    letterSpacing: '0.06em',
    marginBottom: '10px',
    fontWeight: 600,
  },
  horizonGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))',
    gap: '14px',
  },
  horizonCard: (direction) => ({
    background: direction === 'bullish' ? '#0d1f18' : direction === 'bearish' ? '#1f0d0d' : '#0d0d1f',
    border: `1px solid ${direction === 'bullish' ? '#276749' : direction === 'bearish' ? '#742a2a' : '#2b6cb0'}`,
    borderRadius: '8px',
    padding: '14px 16px',
  }),
  horizonLabel: (direction) => ({
    fontSize: '11px',
    fontWeight: 700,
    textTransform: 'uppercase',
    letterSpacing: '0.06em',
    color: direction === 'bullish' ? '#68d391' : direction === 'bearish' ? '#fc8181' : '#63b3ed',
    marginBottom: '6px',
  }),
  horizonTarget: { fontSize: '22px', fontWeight: 800, color: '#e2e8f0', marginBottom: '4px' },
  horizonTimeframe: { fontSize: '12px', color: '#a0aec0', marginBottom: '8px' },
  horizonCatalyst: { fontSize: '13px', color: '#a0aec0', lineHeight: 1.5 },
  levelsGrid: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: '14px',
  },
  levelBox: (type) => ({
    background: type === 'support' ? '#0d1a12' : '#1a0d0d',
    border: `1px solid ${type === 'support' ? '#276749' : '#742a2a'}`,
    borderRadius: '8px',
    padding: '12px 14px',
  }),
  levelTitle: (type) => ({
    fontSize: '11px',
    fontWeight: 700,
    textTransform: 'uppercase',
    letterSpacing: '0.06em',
    color: type === 'support' ? '#68d391' : '#fc8181',
    marginBottom: '8px',
  }),
  levelItem: (type) => ({
    fontSize: '15px',
    fontWeight: 600,
    color: type === 'support' ? '#9ae6b4' : '#feb2b2',
    padding: '3px 0',
  }),
  bulletList: { listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: '6px' },
  bulletItem: (type) => ({
    fontSize: '13px',
    color: type === 'upside' ? '#9ae6b4' : '#feb2b2',
    paddingLeft: '16px',
    position: 'relative',
    lineHeight: 1.5,
  }),
  bulletDot: (type) => ({
    position: 'absolute',
    left: 0,
    color: type === 'upside' ? '#68d391' : '#fc8181',
    fontWeight: 700,
  }),
  catalystsGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
    gap: '14px',
  },
  catalystBox: (type) => ({
    background: type === 'upside' ? '#0d1a12' : '#1a0d0d',
    border: `1px solid ${type === 'upside' ? '#276749' : '#742a2a'}`,
    borderRadius: '8px',
    padding: '14px 16px',
  }),
  techSummary: {
    fontSize: '13px',
    color: '#a0aec0',
    lineHeight: 1.7,
    background: '#0d1117',
    border: '1px solid #2d3748',
    borderRadius: '8px',
    padding: '14px 16px',
  },
  explanation: { fontSize: '14px', color: '#cbd5e0', lineHeight: 1.7 },
  hint: { fontSize: '13px', color: '#4a5568', marginTop: '8px' },
  popularRow: { display: 'flex', gap: '8px', flexWrap: 'wrap', marginBottom: '8px' },
  chip: {
    padding: '4px 12px',
    background: '#2d3748',
    border: '1px solid #4a5568',
    borderRadius: '20px',
    color: '#a0aec0',
    fontSize: '12px',
    fontWeight: 600,
    cursor: 'pointer',
  },
}

const POPULAR = ['AAPL', 'NVDA', 'TSLA', 'MSFT', 'AMZN', 'GOOGL', 'META', 'CRWD', 'COIN', 'PLTR']

function fmt(val) {
  if (val == null) return '—'
  return `$${Number(val).toFixed(2)}`
}

export default function StockLookupTab() {
  const [ticker, setTicker] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)

  const analyze = async (sym) => {
    const symbol = (sym || ticker).trim().toUpperCase()
    if (!symbol) return
    setTicker(symbol)
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const data = await api.lookup.analyze(symbol)
      setResult(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const handleKey = (e) => {
    if (e.key === 'Enter') analyze()
  }

  return (
    <div>
      <div style={s.header}>
        <div style={s.title}>Stock Lookup</div>
        <div style={s.subtitle}>Enter any S&P 500 or NASDAQ ticker for an AI-powered buy/sell analysis</div>
      </div>

      <div style={s.searchRow}>
        <input
          style={s.input}
          value={ticker}
          onChange={(e) => setTicker(e.target.value.toUpperCase())}
          onKeyDown={handleKey}
          placeholder="e.g. AAPL"
          maxLength={10}
          autoFocus
        />
        <button
          style={s.analyzeBtn(loading)}
          onClick={() => analyze()}
          disabled={loading || !ticker.trim()}
        >
          {loading ? '⏳ Analyzing...' : '🔍 Analyze'}
        </button>
      </div>

      <div style={s.popularRow}>
        {POPULAR.map((sym) => (
          <button key={sym} style={s.chip} onClick={() => analyze(sym)}>
            {sym}
          </button>
        ))}
      </div>
      <div style={s.hint}>Click a ticker above or type your own</div>

      {error && <div style={s.error}>⚠ {error}</div>}

      {result && (
        <div style={s.card}>
          {/* Header row */}
          <div style={s.cardHeader}>
            <div style={s.tickerRow}>
              <span style={s.ticker}>{result.ticker}</span>
              <span style={s.price}>{fmt(result.current_price)}</span>
              <span style={s.ratingBadge(result.rating)}>{result.rating}</span>
              {result.conviction && (
                <span style={s.conviction(result.conviction)}>{result.conviction} conviction</span>
              )}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <GradeChip grade={result.grade} />
            </div>
          </div>

          {/* Confidence score */}
          <div>
            <div style={s.sectionLabel}>Confidence Score</div>
            <ScoreBar score={result.score} />
          </div>

          {/* Chart */}
          <TradingViewWidget ticker={result.ticker} />

          {/* Short + Long term */}
          <div>
            <div style={s.sectionLabel}>Price Outlook</div>
            <div style={s.horizonGrid}>
              {result.short_term && (
                <div style={s.horizonCard(result.short_term.direction)}>
                  <div style={s.horizonLabel(result.short_term.direction)}>
                    Short-Term · {result.short_term.timeframe}
                  </div>
                  <div style={s.horizonTarget}>{fmt(result.short_term.price_target)}</div>
                  <div style={s.horizonCatalyst}>{result.short_term.catalyst}</div>
                </div>
              )}
              {result.long_term && (
                <div style={s.horizonCard(result.long_term.direction)}>
                  <div style={s.horizonLabel(result.long_term.direction)}>
                    Long-Term · {result.long_term.timeframe}
                  </div>
                  <div style={s.horizonTarget}>{fmt(result.long_term.price_target)}</div>
                  <div style={s.horizonCatalyst}>{result.long_term.thesis}</div>
                </div>
              )}
            </div>
          </div>

          {/* Key levels */}
          {(result.support_levels?.length || result.resistance_levels?.length) && (
            <div>
              <div style={s.sectionLabel}>Key Price Levels</div>
              <div style={s.levelsGrid}>
                <div style={s.levelBox('support')}>
                  <div style={s.levelTitle('support')}>Support</div>
                  {(result.support_levels || []).map((lvl, i) => (
                    <div key={i} style={s.levelItem('support')}>{fmt(lvl)}</div>
                  ))}
                </div>
                <div style={s.levelBox('resistance')}>
                  <div style={s.levelTitle('resistance')}>Resistance</div>
                  {(result.resistance_levels || []).map((lvl, i) => (
                    <div key={i} style={s.levelItem('resistance')}>{fmt(lvl)}</div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* Catalysts & Risks */}
          {(result.upside_catalysts?.length || result.risks?.length) && (
            <div>
              <div style={s.sectionLabel}>Catalysts & Risks</div>
              <div style={s.catalystsGrid}>
                {result.upside_catalysts?.length > 0 && (
                  <div style={s.catalystBox('upside')}>
                    <div style={{ ...s.levelTitle('support'), marginBottom: '8px' }}>Upside Catalysts</div>
                    <ul style={s.bulletList}>
                      {result.upside_catalysts.map((c, i) => (
                        <li key={i} style={s.bulletItem('upside')}>
                          <span style={s.bulletDot('upside')}>▲</span> {c}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {result.risks?.length > 0 && (
                  <div style={s.catalystBox('risk')}>
                    <div style={{ ...s.levelTitle('resistance'), marginBottom: '8px' }}>Key Risks</div>
                    <ul style={s.bulletList}>
                      {result.risks.map((r, i) => (
                        <li key={i} style={s.bulletItem('risk')}>
                          <span style={s.bulletDot('risk')}>▼</span> {r}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Technical summary */}
          {result.technical_summary && (
            <div>
              <div style={s.sectionLabel}>Technical Summary</div>
              <div style={s.techSummary}>{result.technical_summary}</div>
            </div>
          )}

          {/* Overall thesis */}
          {result.explanation && (
            <div>
              <div style={s.sectionLabel}>Overall Thesis</div>
              <p style={s.explanation}>{result.explanation}</p>
            </div>
          )}

          <div style={{ fontSize: '11px', color: '#4a5568' }}>
            AI analysis only — not financial advice. Always verify with your broker before trading.
          </div>
        </div>
      )}
    </div>
  )
}
