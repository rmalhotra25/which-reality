import { useState, useEffect, useCallback } from 'react'
import { api } from '../api'
import { useRefreshPoller } from '../hooks/useRefreshPoller'
import LastUpdated from '../components/LastUpdated'
import AccountWidget from '../components/AccountWidget'
import WheelCard from '../wheel/WheelCard'
import PositionTracker from '../wheel/PositionTracker'
import WheelCustomAnalysis from '../wheel/WheelCustomAnalysis'

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
  btnRow: {
    display: 'flex',
    gap: '8px',
    alignItems: 'center',
    flexWrap: 'wrap',
  },
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
  exportBtn: {
    padding: '8px 14px',
    background: 'transparent',
    color: '#68d391',
    border: '1px solid #276749',
    borderRadius: '6px',
    cursor: 'pointer',
    fontSize: '12px',
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

const scannerStyles = {
  section: { marginBottom: '8px' },
  header: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', flexWrap: 'wrap', gap: '8px' },
  sectionTitle: { fontSize: '15px', fontWeight: 600, color: '#a0aec0', display: 'flex', alignItems: 'center', gap: '8px' },
  meta: { fontSize: '12px', color: '#718096' },
  refreshBtn: { padding: '6px 14px', background: '#2b6cb0', color: '#fff', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '12px' },
  tabRow: { display: 'flex', gap: '8px', marginBottom: '16px' },
  tab: (active) => ({
    padding: '6px 14px', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '12px', fontWeight: 500,
    background: active ? '#2d3748' : 'transparent', color: active ? '#e2e8f0' : '#718096',
  }),
  card: {
    background: '#1a1f2e', border: '1px solid #2d3748', borderRadius: '8px',
    padding: '14px 16px', marginBottom: '10px',
  },
  cardHeader: { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '8px' },
  ticker: { fontSize: '16px', fontWeight: 700, color: '#63b3ed' },
  score: { fontSize: '13px', fontWeight: 600, color: '#68d391' },
  grid2: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px 16px', fontSize: '12px', color: '#a0aec0', marginBottom: '8px' },
  label: { color: '#718096' },
  flagRow: { display: 'flex', flexWrap: 'wrap', gap: '6px', marginTop: '6px' },
  flag: (color) => ({
    fontSize: '11px', padding: '2px 8px', borderRadius: '10px',
    background: color === 'red' ? '#2d1515' : color === 'yellow' ? '#2d2615' : color === 'green' ? '#1a2d1a' : '#1a2234',
    color: color === 'red' ? '#fc8181' : color === 'yellow' ? '#f6e05e' : color === 'green' ? '#68d391' : '#a0aec0',
    border: `1px solid ${color === 'red' ? '#742a2a' : color === 'yellow' ? '#744210' : color === 'green' ? '#276749' : '#2d3748'}`,
  }),
  formula: { fontSize: '10px', color: '#4a5568', marginTop: '6px', fontFamily: 'monospace', wordBreak: 'break-all' },
  excludedRow: { fontSize: '12px', color: '#718096', padding: '6px 0', borderBottom: '1px solid #1a1f2e', display: 'flex', justifyContent: 'space-between' },
  emptyNote: { color: '#4a5568', fontSize: '13px', padding: '24px 0', textAlign: 'center' },
  showMoreBtn: { padding: '6px 14px', background: 'transparent', border: '1px solid #2d3748', borderRadius: '6px', color: '#718096', cursor: 'pointer', fontSize: '12px', marginTop: '8px' },
}

function PutCandidateCard({ c, rank }) {
  const pct = (v, d = 2) => v != null ? `${(v * 100).toFixed(d)}%` : 'n/a'
  const fmt = (v, d = 2) => v != null ? v.toFixed(d) : 'n/a'
  const penalties = c.penalties || []
  return (
    <div style={scannerStyles.card}>
      <div style={scannerStyles.cardHeader}>
        <div>
          <span style={{ ...scannerStyles.ticker }}>{rank}. {c.ticker}</span>
          <span style={{ marginLeft: '8px', fontSize: '12px', color: '#718096' }}>
            ${c.current_price?.toFixed(2)} &middot; {c.trend_state === 'above_200ma' ? '▲ above 200MA' : c.trend_state === 'below_200ma' ? '▼ below 200MA' : ''}
          </span>
        </div>
        <span style={scannerStyles.score}>score: {c.rank_score?.toFixed(7)}</span>
      </div>

      <div style={scannerStyles.grid2}>
        <span><span style={scannerStyles.label}>Strike: </span>${c.strike}</span>
        <span><span style={scannerStyles.label}>Expiry: </span>{c.expiry} ({c.dte}d)</span>
        <span><span style={scannerStyles.label}>Mid: </span>${fmt(c.mid_premium)} ({c.bid}/{c.ask})</span>
        <span><span style={scannerStyles.label}>$/day on capital: </span>{pct(c.raw_pppd, 4)}</span>
        <span><span style={scannerStyles.label}>IV: </span>{c.iv_pct?.toFixed(1)}%
          {c.iv_percentile != null && <span style={{ color: '#718096' }}> (p{c.iv_percentile?.toFixed(0)}{c.iv_pct_source === 'historical' ? ' approx' : ''})</span>}
        </span>
        <span><span style={scannerStyles.label}>Delta: </span>{fmt(c.delta_abs)} ({c.assignment_chance_pct}% asgn)</span>
        <span><span style={scannerStyles.label}>OI / Vol: </span>{c.open_interest} / {c.volume}</span>
        <span><span style={scannerStyles.label}>Spread: </span>{c.spread_pct?.toFixed(1)}% of mid</span>
      </div>

      <div style={scannerStyles.flagRow}>
        {c.earnings_in_window && <span style={scannerStyles.flag('red')}>earnings in window</span>}
        {penalties.map((p, i) => <span key={i} style={scannerStyles.flag('yellow')}>{p.reason} x{p.multiplier}</span>)}
        <span style={scannerStyles.flag(c.quality_verdict === 'PASS' ? 'green' : c.quality_verdict === 'FAIL' ? 'red' : 'neutral')}>
          {c.quality_verdict}{c.quant_score != null ? ` (${c.quant_score})` : ''}
        </span>
        {c.data_source && <span style={scannerStyles.flag('neutral')}>{c.data_source}</span>}
      </div>
      <div style={scannerStyles.formula}>formula: {c.ranking_formula}</div>
    </div>
  )
}

function CallCandidateCard({ c, rank }) {
  const fmt = (v, d = 2) => v != null ? v.toFixed(d) : 'n/a'
  return (
    <div style={scannerStyles.card}>
      <div style={scannerStyles.cardHeader}>
        <div>
          <span style={scannerStyles.ticker}>{rank}. {c.ticker}</span>
          <span style={{ marginLeft: '8px', fontSize: '12px', color: '#718096' }}>
            ${c.current_price?.toFixed(2)}{c.cost_basis ? ` · basis $${c.cost_basis.toFixed(2)}` : ''}
          </span>
        </div>
        <span style={scannerStyles.score}>score: {c.rank_score?.toFixed(7)}</span>
      </div>
      <div style={scannerStyles.grid2}>
        <span><span style={{ color: '#718096' }}>Strike: </span>${c.strike} (+{c.upside_to_strike_pct}%)</span>
        <span><span style={{ color: '#718096' }}>Expiry: </span>{c.expiry} ({c.dte}d)</span>
        <span><span style={{ color: '#718096' }}>Mid: </span>${fmt(c.mid_premium)} ({c.bid}/{c.ask})</span>
        <span><span style={{ color: '#718096' }}>$/day on stock: </span>{(c.raw_pppd * 100).toFixed(4)}%</span>
        <span><span style={{ color: '#718096' }}>IV: </span>{c.iv_pct?.toFixed(1)}%</span>
        <span><span style={{ color: '#718096' }}>Delta: </span>{fmt(c.delta)} ({c.call_away_chance_pct}% call-away)</span>
        <span><span style={{ color: '#718096' }}>OI / Vol: </span>{c.open_interest} / {c.volume}</span>
        <span><span style={{ color: '#718096' }}>Spread: </span>{c.spread_pct?.toFixed(1)}% of mid</span>
      </div>
      <div style={scannerStyles.flagRow}>
        {c.early_assignment_risk && (
          <span style={scannerStyles.flag('red')}>ex-div {c.ex_dividend_date} (early assignment risk)</span>
        )}
        {c.data_source && <span style={scannerStyles.flag('neutral')}>{c.data_source}</span>}
      </div>
    </div>
  )
}

function ScannerSection({ data, loading, refreshing, onRefresh, showCallCandidates, setShowCallCandidates, showExcluded, setShowExcluded }) {
  const [showAllExcluded, setShowAllExcluded] = useState(false)
  const puts = data?.puts
  const calls = data?.calls

  const putCandidates = puts?.candidates || []
  const putExcluded = puts?.excluded || []
  const callCandidates = calls?.candidates || []
  const callExcluded = calls?.excluded || []

  const excluded = showCallCandidates ? callExcluded : putExcluded
  const excVisible = showAllExcluded ? excluded : excluded.slice(0, 10)

  const runAt = puts?.run_at || calls?.run_at
  const universeSize = puts?.universe_size || calls?.universe_size

  return (
    <div style={scannerStyles.section}>
      <div style={scannerStyles.header}>
        <div>
          <div style={scannerStyles.sectionTitle}>
            <span>🔍</span> Wheel Scanner
            {putCandidates.length > 0 && (
              <span style={{ background: '#1a2d1a', color: '#68d391', fontSize: '11px', padding: '1px 8px', borderRadius: '10px', border: '1px solid #276749' }}>
                {putCandidates.length} candidates
              </span>
            )}
          </div>
          {runAt && (
            <div style={scannerStyles.meta}>
              Last scan: {new Date(runAt).toLocaleString()} &middot; universe: {universeSize}
            </div>
          )}
          {!runAt && !loading && (
            <div style={scannerStyles.meta}>No scan results yet. Click Scan Universe to run.</div>
          )}
        </div>
        <button style={scannerStyles.refreshBtn} onClick={onRefresh} disabled={refreshing}>
          {refreshing ? '⏳ Scanning...' : '▶ Scan Universe'}
        </button>
      </div>

      {loading && <div style={scannerStyles.emptyNote}>Loading scanner results...</div>}

      {!loading && data?.has_data && (
        <>
          <div style={scannerStyles.tabRow}>
            <button style={scannerStyles.tab(!showCallCandidates)} onClick={() => setShowCallCandidates(false)}>
              Puts ({putCandidates.length})
            </button>
            <button style={scannerStyles.tab(showCallCandidates)} onClick={() => setShowCallCandidates(true)}>
              Covered Calls ({callCandidates.length})
            </button>
          </div>

          {!showCallCandidates && (
            putCandidates.length === 0
              ? <div style={scannerStyles.emptyNote}>No put candidates passed all filters.</div>
              : putCandidates.map((c, i) => <PutCandidateCard key={c.ticker} c={c} rank={i + 1} />)
          )}

          {showCallCandidates && (
            callCandidates.length === 0
              ? <div style={scannerStyles.emptyNote}>No covered call candidates passed all filters.</div>
              : callCandidates.map((c, i) => <CallCandidateCard key={c.ticker} c={c} rank={i + 1} />)
          )}

          <button style={scannerStyles.showMoreBtn} onClick={() => setShowExcluded(!showExcluded)}>
            {showExcluded ? '▲ Hide' : '▼ Show'} excluded ({excluded.length})
          </button>

          {showExcluded && (
            <div style={{ marginTop: '8px' }}>
              {excVisible.map((e) => (
                <div key={e.ticker} style={scannerStyles.excludedRow}>
                  <span style={{ fontWeight: 600, color: '#a0aec0' }}>{e.ticker}</span>
                  <span>{e.reason}{e.spread_pct != null ? ` (spread ${e.spread_pct}%)` : ''}{e.open_interest != null ? ` (OI ${e.open_interest})` : ''}</span>
                </div>
              ))}
              {excluded.length > 10 && (
                <button style={scannerStyles.showMoreBtn} onClick={() => setShowAllExcluded(!showAllExcluded)}>
                  {showAllExcluded ? '▲ Show fewer' : `▼ Show all ${excluded.length}`}
                </button>
              )}
            </div>
          )}
        </>
      )}
    </div>
  )
}

function downloadJson(data, filename) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export default function WheelTab() {
  const [recs, setRecs] = useState([])
  const [positions, setPositions] = useState([])
  const [account, setAccount] = useState(null)
  const [loading, setLoading] = useState(true)
  const [loadingPositions, setLoadingPositions] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [error, setError] = useState(null)
  const [showClosed, setShowClosed] = useState(false)
  const [scannerData, setScannerData] = useState(null)
  const [scannerLoading, setScannerLoading] = useState(false)
  const [scannerRefreshing, setScannerRefreshing] = useState(false)
  const [showCallCandidates, setShowCallCandidates] = useState(false)
  const [showExcluded, setShowExcluded] = useState(false)

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

  const loadScanner = async () => {
    setScannerLoading(true)
    try {
      const data = await api.wheel.getScannerCandidates()
      setScannerData(data)
    } catch (e) {
      // scanner cache miss is non-fatal
    } finally {
      setScannerLoading(false)
    }
  }

  const handleScannerRefresh = async () => {
    setScannerRefreshing(true)
    try {
      await api.wheel.refreshScanner()
      // Poll until results appear
      const poll = setInterval(async () => {
        const status = await api.wheel.getScannerStatus().catch(() => null)
        if (status && status.state !== 'running') {
          clearInterval(poll)
          setScannerRefreshing(false)
          loadScanner()
        }
      }, 3000)
      setTimeout(() => { clearInterval(poll); setScannerRefreshing(false) }, 120000)
    } catch (e) {
      setScannerRefreshing(false)
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
  useEffect(() => { api.account.getBalance().then(setAccount).catch(() => {}) }, [])
  useEffect(() => { loadScanner() }, [])

  const wheelFetchFn = useCallback(() => api.wheel.getRecommendations(), [])
  const { start: startPolling } = useRefreshPoller(
    wheelFetchFn,
    (data) => { setRecs(data) },
    setError,
    'wheel'
  )

  const handleRefresh = async () => {
    setRefreshing(true)
    try {
      await api.wheel.refresh()
      startPolling(recs[0]?.run_at, () => setRefreshing(false))
    } catch (e) {
      setError(e.message)
      setRefreshing(false)
    }
  }

  const handleExport = async () => {
    setExporting(true)
    try {
      const data = await api.wheel.exportPositions()
      const date = new Date().toISOString().slice(0, 10)
      downloadJson(data, `wheel-positions-${date}.json`)
    } catch (e) {
      setError(e.message)
    } finally {
      setExporting(false)
    }
  }

  const handleAccepted = (newPosition) => {
    setPositions((prev) => [newPosition, ...prev])
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
      <AccountWidget showSizing />
      <WheelCustomAnalysis />

      <div style={s.header}>
        <div>
          <div style={s.title}>Wheel Strategy</div>
          <LastUpdated timestamp={lastRunAt} loading={loading} />
        </div>
        <div style={s.btnRow}>
          {positions.length > 0 && (
            <button style={s.exportBtn} onClick={handleExport} disabled={exporting} title="Download all positions as JSON backup">
              {exporting ? '⏳' : '⬇'} Backup Positions
            </button>
          )}
          <button style={s.refreshBtn} onClick={handleRefresh} disabled={refreshing}>
            {refreshing ? '⏳ Analyzing...' : '↻ Run Analysis'}
          </button>
        </div>
      </div>

      {error && <div style={s.error}>Error: {error}</div>}

      {/* Scanner candidates section */}
      <ScannerSection
        data={scannerData}
        loading={scannerLoading}
        refreshing={scannerRefreshing}
        onRefresh={handleScannerRefresh}
        showCallCandidates={showCallCandidates}
        setShowCallCandidates={setShowCallCandidates}
        showExcluded={showExcluded}
        setShowExcluded={setShowExcluded}
      />

      <hr style={s.divider} />

      {/* AI wheel recommendations */}
      <div style={s.sectionTitle}>
        <span>🎯</span> AI Put-Selling Candidates
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
          <WheelCard key={rec.id} rec={rec} account={account} onAccepted={handleAccepted} />
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
