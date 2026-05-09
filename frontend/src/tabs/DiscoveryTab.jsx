import { useState, useEffect, useRef } from 'react'

const API = import.meta.env.VITE_API_URL || ''

// ── Styles ─────────────────────────────────────────────────────────────────
const S = {
  page: {
    minHeight: '100vh',
    background: '#0f1117',
    color: '#e2e8f0',
    fontFamily: "'Inter', sans-serif",
    padding: '0 0 60px',
  },
  hero: {
    background: 'linear-gradient(135deg, #0d1f3c 0%, #1a0a2e 50%, #0d1f3c 100%)',
    borderBottom: '1px solid #2d3748',
    padding: '28px 20px 24px',
    textAlign: 'center',
  },
  heroTitle: {
    fontSize: '22px',
    fontWeight: 800,
    color: '#fff',
    margin: '0 0 4px',
    letterSpacing: '-0.3px',
  },
  heroSub: {
    fontSize: '13px',
    color: '#718096',
    margin: '0 0 18px',
  },
  scanBtn: {
    background: 'linear-gradient(135deg, #6c63ff, #a855f7)',
    color: '#fff',
    border: 'none',
    borderRadius: '10px',
    padding: '11px 28px',
    fontSize: '14px',
    fontWeight: 700,
    cursor: 'pointer',
    letterSpacing: '0.3px',
  },
  scanBtnDisabled: {
    background: '#2d3748',
    color: '#718096',
    border: 'none',
    borderRadius: '10px',
    padding: '11px 28px',
    fontSize: '14px',
    fontWeight: 700,
    cursor: 'not-allowed',
  },
  statusRow: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '10px',
    marginTop: '14px',
    fontSize: '12px',
    color: '#718096',
  },
  progressWrap: {
    width: '220px',
    height: '4px',
    background: '#2d3748',
    borderRadius: '2px',
    overflow: 'hidden',
  },
  progressBar: (pct) => ({
    width: `${Math.round(pct * 100)}%`,
    height: '100%',
    background: 'linear-gradient(90deg, #6c63ff, #a855f7)',
    borderRadius: '2px',
    transition: 'width 0.4s ease',
  }),
  section: {
    padding: '24px 16px 8px',
    maxWidth: '800px',
    margin: '0 auto',
  },
  sectionHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: '10px',
    marginBottom: '16px',
  },
  sectionTitle: {
    fontSize: '17px',
    fontWeight: 800,
    color: '#fff',
    margin: 0,
  },
  sectionBadge: (color) => ({
    background: color,
    color: '#fff',
    borderRadius: '6px',
    padding: '2px 9px',
    fontSize: '11px',
    fontWeight: 700,
    letterSpacing: '0.4px',
  }),
  sectionDesc: {
    fontSize: '12px',
    color: '#718096',
    marginBottom: '14px',
    lineHeight: 1.5,
  },
  card: {
    background: '#1a202c',
    borderRadius: '14px',
    border: '1px solid #2d3748',
    marginBottom: '14px',
    overflow: 'hidden',
  },
  cardHeader: {
    padding: '14px 16px 10px',
    borderBottom: '1px solid #2d3748',
    display: 'flex',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    gap: '10px',
  },
  cardTicker: {
    fontSize: '18px',
    fontWeight: 800,
    color: '#fff',
    letterSpacing: '-0.3px',
  },
  cardName: {
    fontSize: '12px',
    color: '#718096',
    marginTop: '1px',
  },
  cardSector: {
    fontSize: '11px',
    color: '#4a5568',
    background: '#2d3748',
    borderRadius: '5px',
    padding: '2px 7px',
    whiteSpace: 'nowrap',
  },
  cardBody: {
    padding: '12px 16px',
  },
  thesis: {
    fontSize: '13px',
    color: '#cbd5e0',
    lineHeight: 1.6,
    marginBottom: '12px',
  },
  metrics: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: '8px',
    marginBottom: '12px',
  },
  metric: {
    background: '#2d3748',
    borderRadius: '7px',
    padding: '5px 10px',
    fontSize: '11px',
    color: '#a0aec0',
    display: 'flex',
    flexDirection: 'column',
    gap: '1px',
  },
  metricLabel: {
    color: '#718096',
    fontSize: '10px',
  },
  metricValue: {
    color: '#e2e8f0',
    fontWeight: 700,
    fontSize: '12px',
  },
  catalystBox: {
    background: 'rgba(108,99,255,0.08)',
    borderLeft: '3px solid #6c63ff',
    borderRadius: '0 6px 6px 0',
    padding: '8px 10px',
    marginBottom: '8px',
  },
  catalystLabel: {
    fontSize: '10px',
    color: '#6c63ff',
    fontWeight: 700,
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
    marginBottom: '2px',
  },
  catalystText: {
    fontSize: '12px',
    color: '#a0aec0',
    lineHeight: 1.4,
  },
  riskBox: {
    background: 'rgba(252,129,74,0.07)',
    borderLeft: '3px solid #fc814a',
    borderRadius: '0 6px 6px 0',
    padding: '8px 10px',
  },
  riskLabel: {
    fontSize: '10px',
    color: '#fc814a',
    fontWeight: 700,
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
    marginBottom: '2px',
  },
  riskText: {
    fontSize: '12px',
    color: '#a0aec0',
    lineHeight: 1.4,
  },
  keyMetricBadge: {
    display: 'inline-block',
    background: 'rgba(104,211,145,0.12)',
    color: '#68d391',
    borderRadius: '6px',
    padding: '3px 9px',
    fontSize: '11px',
    fontWeight: 700,
    marginBottom: '10px',
  },
  emptyState: {
    textAlign: 'center',
    padding: '40px 20px',
    color: '#718096',
    fontSize: '14px',
  },
  scanNote: {
    fontSize: '12px',
    color: '#718096',
    textAlign: 'center',
    padding: '12px 20px 0',
    lineHeight: 1.5,
  },
}

// ── Subcomponents ──────────────────────────────────────────────────────────

function MetricChip({ label, value }) {
  if (!value && value !== 0) return null
  return (
    <div style={S.metric}>
      <span style={S.metricLabel}>{label}</span>
      <span style={S.metricValue}>{value}</span>
    </div>
  )
}

function PickCard({ pick }) {
  const mc = pick.market_cap_b > 0 ? `$${pick.market_cap_b}B` : null
  const revG = pick.revenue_growth_pct !== 0 ? `${pick.revenue_growth_pct > 0 ? '+' : ''}${pick.revenue_growth_pct}%` : null
  const gm = pick.gross_margin_pct > 0 ? `${pick.gross_margin_pct}%` : null
  const pe = pick.pe ? `${pick.pe}x` : null
  const ps = pick.ps ? `${pick.ps}x` : null
  const roe = pick.roe_pct !== 0 ? `${pick.roe_pct}%` : null

  return (
    <div style={S.card}>
      <div style={S.cardHeader}>
        <div>
          <div style={S.cardTicker}>{pick.ticker}</div>
          <div style={S.cardName}>{pick.name}</div>
        </div>
        {pick.sector && <div style={S.cardSector}>{pick.sector}</div>}
      </div>
      <div style={S.cardBody}>
        {pick.key_metric && (
          <div style={S.keyMetricBadge}>⭐ {pick.key_metric}</div>
        )}
        <p style={S.thesis}>{pick.thesis}</p>
        <div style={S.metrics}>
          {mc && <MetricChip label="Mkt Cap" value={mc} />}
          {revG && <MetricChip label="Rev Growth" value={revG} />}
          {gm && <MetricChip label="Gross Margin" value={gm} />}
          {pe && <MetricChip label="P/E" value={pe} />}
          {ps && <MetricChip label="P/S" value={ps} />}
          {roe && <MetricChip label="ROE" value={roe} />}
        </div>
        {pick.catalyst && (
          <div style={S.catalystBox}>
            <div style={S.catalystLabel}>🚀 Catalyst</div>
            <div style={S.catalystText}>{pick.catalyst}</div>
          </div>
        )}
        {pick.risk && (
          <div style={{ ...S.riskBox, marginTop: '8px' }}>
            <div style={S.riskLabel}>⚠️ Risk</div>
            <div style={S.riskText}>{pick.risk}</div>
          </div>
        )}
      </div>
    </div>
  )
}

function SectionHeader({ emoji, title, badge, badgeColor, desc }) {
  return (
    <>
      <div style={S.sectionHeader}>
        <h2 style={S.sectionTitle}>{emoji} {title}</h2>
        <span style={S.sectionBadge(badgeColor)}>{badge}</span>
      </div>
      <p style={S.sectionDesc}>{desc}</p>
    </>
  )
}

// ── Main Tab ───────────────────────────────────────────────────────────────

export default function DiscoveryTab() {
  const [state, setState] = useState(null)
  const [loading, setLoading] = useState(true)
  const pollRef = useRef(null)

  const fetchState = async () => {
    try {
      const res = await fetch(`${API}/api/discovery`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setState(data)
      return data.status
    } catch (e) {
      console.error('Discovery fetch error:', e)
      return 'error'
    } finally {
      setLoading(false)
    }
  }

  const startPolling = () => {
    if (pollRef.current) return
    pollRef.current = setInterval(async () => {
      const status = await fetchState()
      if (status !== 'scanning') {
        clearInterval(pollRef.current)
        pollRef.current = null
      }
    }, 4000)
  }

  useEffect(() => {
    fetchState().then((status) => {
      if (status === 'scanning') startPolling()
    })
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [])

  const handleScan = async () => {
    try {
      await fetch(`${API}/api/discovery/scan`, { method: 'POST' })
      setState((prev) => ({ ...prev, status: 'scanning', progress: 0 }))
      startPolling()
    } catch (e) {
      console.error('Scan trigger error:', e)
    }
  }

  const isScanning = state?.status === 'scanning'
  const hasResults = state?.status === 'ready' && state?.results
  const generatedAt = state?.generated_at
    ? new Date(state.generated_at).toLocaleString()
    : null

  return (
    <div style={S.page}>
      {/* Hero */}
      <div style={S.hero}>
        <h1 style={S.heroTitle}>🔭 Stock Discovery</h1>
        <p style={S.heroSub}>
          Scanning {state?.results?.universe_size || '~300'} tickers for life-changing opportunities
        </p>
        <button
          style={isScanning ? S.scanBtnDisabled : S.scanBtn}
          onClick={handleScan}
          disabled={isScanning}
        >
          {isScanning ? '⏳ Scanning...' : '🚀 Run Discovery Scan'}
        </button>
        {isScanning && (
          <div style={S.statusRow}>
            <div style={S.progressWrap}>
              <div style={S.progressBar(state?.progress || 0)} />
            </div>
            <span>{Math.round((state?.progress || 0) * 100)}%</span>
          </div>
        )}
        {!isScanning && generatedAt && (
          <div style={S.statusRow}>
            <span>Last scan: {generatedAt}</span>
            {state?.results && (
              <span>· {state.results.fundamentals_fetched} companies analyzed</span>
            )}
          </div>
        )}
        {!isScanning && !hasResults && !loading && (
          <p style={S.scanNote}>
            Click "Run Discovery Scan" to analyze ~300 stocks across all sectors.<br />
            Takes ~5–7 minutes. Results are cached for 24 hours.
          </p>
        )}
      </div>

      {/* Scanning placeholder */}
      {isScanning && !hasResults && (
        <div style={S.emptyState}>
          <div style={{ fontSize: '32px', marginBottom: '12px' }}>🔍</div>
          <div style={{ fontWeight: 700, color: '#e2e8f0', marginBottom: '6px' }}>
            Scanning the market...
          </div>
          <div>Fetching fundamentals, scoring companies, and writing AI theses.</div>
          <div style={{ marginTop: '6px' }}>This takes 5–7 minutes. Hang tight.</div>
        </div>
      )}

      {/* Error */}
      {state?.status === 'error' && (
        <div style={{ ...S.emptyState, color: '#fc8181' }}>
          ⚠️ Scan failed: {state.error || 'Unknown error'}. Try again.
        </div>
      )}

      {/* Results */}
      {hasResults && (
        <>
          {/* Next Compounders */}
          <div style={S.section}>
            <SectionHeader
              emoji="🚀"
              title="Next Compounder"
              badge="High Growth"
              badgeColor="linear-gradient(135deg,#6c63ff,#a855f7)"
              desc="High-growth companies with dominant market positions and scalable business models — the profile of NVDA, TSLA, and PLTR before they became household names."
            />
            {state.results.compounders.length === 0 ? (
              <div style={S.emptyState}>No compounder picks found in this scan.</div>
            ) : (
              state.results.compounders.map((pick) => (
                <PickCard key={pick.ticker} pick={pick} />
              ))
            )}
          </div>

          <div style={{ height: '8px', background: '#0f1117' }} />

          {/* Sleeper Picks */}
          <div style={S.section}>
            <SectionHeader
              emoji="💎"
              title="Sleeper Picks"
              badge="Hidden Value"
              badgeColor="linear-gradient(135deg,#38b2ac,#4299e1)"
              desc="Profitable, under-the-radar companies with strong moats and growing earnings that Wall Street hasn't fully discovered yet."
            />
            {state.results.sleepers.length === 0 ? (
              <div style={S.emptyState}>No sleeper picks found in this scan.</div>
            ) : (
              state.results.sleepers.map((pick) => (
                <PickCard key={pick.ticker} pick={pick} />
              ))
            )}
          </div>
        </>
      )}
    </div>
  )
}
