import { useState, useEffect } from 'react'
import { api } from '../api'
import GradeChip from '../components/GradeChip'
import ScoreBar from '../components/ScoreBar'
import TradingViewWidget from '../components/TradingViewWidget'
import LastUpdated from '../components/LastUpdated'

const s = {
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '24px',
    flexWrap: 'wrap',
    gap: '12px',
  },
  title: { fontSize: '20px', fontWeight: 700, color: '#e2e8f0' },
  refreshBtn: {
    padding: '8px 16px',
    background: '#2b6cb0',
    color: '#fff',
    border: 'none',
    borderRadius: '6px',
    cursor: 'pointer',
    fontSize: '13px',
    fontWeight: 500,
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(420px, 1fr))',
    gap: '16px',
  },
  card: {
    background: '#1a1f2e',
    border: '1px solid #2d3748',
    borderRadius: '12px',
    padding: '20px',
    display: 'flex',
    flexDirection: 'column',
    gap: '14px',
  },
  cardHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
  },
  ticker: { fontSize: '22px', fontWeight: 800, color: '#90cdf4' },
  rankBadge: {
    background: '#2d3748',
    color: '#a0aec0',
    borderRadius: '4px',
    padding: '2px 8px',
    fontSize: '11px',
    fontWeight: 600,
  },
  optionBadge: (type) => ({
    display: 'inline-block',
    padding: '3px 10px',
    borderRadius: '4px',
    fontSize: '12px',
    fontWeight: 700,
    background: type === 'CALL' ? '#1a3a2a' : '#3a1a1a',
    color: type === 'CALL' ? '#68d391' : '#fc8181',
    border: `1px solid ${type === 'CALL' ? '#2f855a' : '#c53030'}`,
  }),
  table: { width: '100%', borderCollapse: 'collapse', fontSize: '13px' },
  td: { padding: '5px 0', color: '#a0aec0', width: '50%' },
  tdVal: { padding: '5px 0', color: '#e2e8f0', fontWeight: 600, textAlign: 'right' },
  explanation: { fontSize: '13px', color: '#a0aec0', lineHeight: 1.6 },
  scoreRow: { display: 'flex', alignItems: 'center', gap: '12px' },
  empty: { color: '#718096', textAlign: 'center', padding: '48px', fontSize: '14px' },
  error: { color: '#fc8181', textAlign: 'center', padding: '24px', fontSize: '14px' },
}

function fmt(val, prefix = '$') {
  if (val == null) return '—'
  return `${prefix}${Number(val).toFixed(2)}`
}

export default function OptionsTab() {
  const [recs, setRecs] = useState([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState(null)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.options.getRecommendations()
      setRecs(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const handleRefresh = async () => {
    setRefreshing(true)
    try {
      await api.options.refresh()
      // Poll for new data after ~30s
      setTimeout(load, 30000)
      setError(null)
    } catch (e) {
      setError(e.message)
    } finally {
      setRefreshing(false)
    }
  }

  const lastRunAt = recs[0]?.run_at

  return (
    <div>
      <div style={s.header}>
        <div>
          <div style={s.title}>Options Trade Recommendations</div>
          <LastUpdated timestamp={lastRunAt} loading={loading} />
        </div>
        <button style={s.refreshBtn} onClick={handleRefresh} disabled={refreshing}>
          {refreshing ? 'Queued...' : '↻ Run Analysis'}
        </button>
      </div>

      {error && <div style={s.error}>Error: {error}</div>}

      {!loading && recs.length === 0 && !error && (
        <div style={s.empty}>
          No recommendations yet. Click "Run Analysis" to generate your first set of recommendations.
          <br />
          <small style={{ color: '#4a5568', marginTop: '8px', display: 'block' }}>
            Scheduled runs: 9:00 AM, 9:45 AM, 12:00 PM, 3:00 PM, 6:00 PM Eastern
          </small>
        </div>
      )}

      <div style={s.grid}>
        {recs.map((rec) => (
          <div key={rec.id} style={s.card}>
            <div style={s.cardHeader}>
              <div>
                <span style={s.ticker}>{rec.ticker}</span>
                {rec.option_type && (
                  <span style={{ marginLeft: '10px', ...s.optionBadge(rec.option_type) }}>
                    {rec.option_type}
                  </span>
                )}
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={s.rankBadge}>#{rec.rank}</span>
                <GradeChip grade={rec.grade} />
              </div>
            </div>

            <div>
              <div style={{ fontSize: '11px', color: '#718096', marginBottom: '4px' }}>CONVICTION SCORE</div>
              <ScoreBar score={rec.score} />
            </div>

            <TradingViewWidget ticker={rec.ticker} />

            <table style={s.table}>
              <tbody>
                <tr>
                  <td style={s.td}>Strike</td>
                  <td style={s.tdVal}>{fmt(rec.strike)}</td>
                  <td style={s.td}>Expiry</td>
                  <td style={s.tdVal}>{rec.expiry || '—'}</td>
                </tr>
                <tr>
                  <td style={s.td}>Entry</td>
                  <td style={{ ...s.tdVal, color: '#68d391' }}>{fmt(rec.entry_price)}</td>
                  <td style={s.td}>Target Exit</td>
                  <td style={{ ...s.tdVal, color: '#63b3ed' }}>{fmt(rec.exit_price)}</td>
                </tr>
                <tr>
                  <td style={s.td}>Stop Loss</td>
                  <td style={{ ...s.tdVal, color: '#fc8181' }}>{fmt(rec.stop_loss)}</td>
                  <td style={s.td}>R/R</td>
                  <td style={s.tdVal}>
                    {rec.entry_price && rec.exit_price && rec.stop_loss
                      ? `${((rec.exit_price - rec.entry_price) / (rec.entry_price - rec.stop_loss)).toFixed(1)}x`
                      : '—'}
                  </td>
                </tr>
              </tbody>
            </table>

            <div>
              <div style={{ fontSize: '11px', color: '#718096', marginBottom: '6px' }}>ANALYSIS</div>
              <p style={s.explanation}>{rec.explanation}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
