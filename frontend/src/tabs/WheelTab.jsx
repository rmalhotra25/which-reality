import { useState, useEffect, useCallback } from 'react'
import { api } from '../api'
import { useRefreshPoller } from '../hooks/useRefreshPoller'
import LastUpdated from '../components/LastUpdated'
import WheelCard from '../wheel/WheelCard'
import PositionTracker from '../wheel/PositionTracker'

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
  sectionTitle: {
    fontSize: '15px',
    fontWeight: 600,
    color: '#a0aec0',
    marginBottom: '16px',
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
  },
  divider: {
    border: 'none',
    borderTop: '1px solid #2d3748',
    margin: '32px 0',
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(420px, 1fr))',
    gap: '16px',
  },
  empty: { color: '#718096', textAlign: 'center', padding: '32px', fontSize: '14px' },
  error: { color: '#fc8181', padding: '16px', fontSize: '14px' },
  showClosedBtn: {
    padding: '6px 14px',
    background: 'transparent',
    border: '1px solid #2d3748',
    borderRadius: '6px',
    color: '#718096',
    cursor: 'pointer',
    fontSize: '12px',
    marginBottom: '16px',
  },
}

export default function WheelTab() {
  const [recs, setRecs] = useState([])
  const [positions, setPositions] = useState([])
  const [loading, setLoading] = useState(true)
  const [loadingPositions, setLoadingPositions] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState(null)
  const [showClosed, setShowClosed] = useState(false)

  const loadRecs = async () => {
    setLoading(true)
    try {
      const data = await api.wheel.getRecommendations()
      setRecs(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const loadPositions = useCallback(async () => {
    setLoadingPositions(true)
    try {
      const data = await api.wheel.getPositions(showClosed)
      setPositions(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoadingPositions(false)
    }
  }, [showClosed])

  useEffect(() => { loadRecs() }, [])
  useEffect(() => { loadPositions() }, [loadPositions])

  const wheelFetchFn = useCallback(() => api.wheel.getRecommendations(), [])
  const { start: startPolling } = useRefreshPoller(wheelFetchFn, (data) => {
    setRecs(data)
    setRefreshing(false)
  })

  const handleRefresh = async () => {
    setRefreshing(true)
    try {
      await api.wheel.refresh()
      startPolling(recs[0]?.run_at)
    } catch (e) {
      setError(e.message)
      setRefreshing(false)
    }
  }

  const handleAccepted = (newPosition) => {
    setPositions((prev) => [newPosition, ...prev])
    // Mark the recommendation as accepted in local state
    setRecs((prev) =>
      prev.map((r) => (r.id === newPosition.recommendation_id ? { ...r, accepted: true } : r))
    )
  }

  const handlePositionUpdated = (updated) => {
    setPositions((prev) => prev.map((p) => (p.id === updated.id ? updated : p)))
  }

  const lastRunAt = recs[0]?.run_at
  const activePositions = positions.filter((p) => p.status !== 'closed')
  const closedPositions = positions.filter((p) => p.status === 'closed')

  return (
    <div>
      <div style={s.header}>
        <div>
          <div style={s.title}>Wheel Strategy</div>
          <LastUpdated timestamp={lastRunAt} loading={loading} />
        </div>
        <button style={s.refreshBtn} onClick={handleRefresh} disabled={refreshing}>
          {refreshing ? '⏳ Analyzing...' : '↻ Run Analysis'}
        </button>
      </div>

      {error && <div style={s.error}>Error: {error}</div>}

      {/* New recommendations */}
      <div style={s.sectionTitle}>
        <span>🎯</span> Put-Selling Candidates
      </div>

      {!loading && recs.length === 0 && !error && (
        <div style={s.empty}>
          No recommendations yet. Click "Run Analysis" to identify wheel candidates.
          <br />
          <small style={{ color: '#4a5568', marginTop: '8px', display: 'block' }}>
            Looks for high IV-rank stocks with strong support for cash-secured put selling
          </small>
        </div>
      )}

      <div style={s.grid}>
        {recs.map((rec) => (
          <WheelCard key={rec.id} rec={rec} onAccepted={handleAccepted} />
        ))}
      </div>

      <hr style={s.divider} />

      {/* Tracked positions */}
      <div style={{ ...s.sectionTitle, marginBottom: '8px' }}>
        <span>📊</span> Tracked Positions
        {activePositions.length > 0 && (
          <span style={{
            background: '#2d3748',
            color: '#a0aec0',
            borderRadius: '10px',
            padding: '1px 8px',
            fontSize: '11px',
          }}>
            {activePositions.length} active
          </span>
        )}
      </div>

      {!loadingPositions && activePositions.length === 0 && (
        <div style={s.empty}>
          No active positions. Accept a recommendation above to start tracking a wheel trade.
        </div>
      )}

      <div style={s.grid}>
        {activePositions.map((pos) => (
          <PositionTracker
            key={pos.id}
            position={pos}
            onUpdated={handlePositionUpdated}
          />
        ))}
      </div>

      {/* Closed positions toggle */}
      {closedPositions.length > 0 && (
        <button style={s.showClosedBtn} onClick={() => setShowClosed(!showClosed)}>
          {showClosed ? '▲ Hide' : '▼ Show'} {closedPositions.length} closed position{closedPositions.length !== 1 ? 's' : ''}
        </button>
      )}
      {showClosed && (
        <div style={{ ...s.grid, opacity: 0.6 }}>
          {closedPositions.map((pos) => (
            <PositionTracker
              key={pos.id}
              position={pos}
              onUpdated={handlePositionUpdated}
            />
          ))}
        </div>
      )}
    </div>
  )
}
