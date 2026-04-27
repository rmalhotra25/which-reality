import { useState, useEffect } from 'react'
import GradeChip from '../components/GradeChip'
import ScoreBar from '../components/ScoreBar'
import DualScorePanel from '../components/DualScorePanel'
import TradingViewWidget from '../components/TradingViewWidget'
import AcceptModal from './AcceptModal'
import { api } from '../api'

const s = {
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
  table: { width: '100%', borderCollapse: 'collapse', fontSize: '13px' },
  td: { padding: '5px 0', color: '#a0aec0', width: '50%' },
  tdVal: { padding: '5px 0', color: '#e2e8f0', fontWeight: 600, textAlign: 'right' },
  explanation: { fontSize: '13px', color: '#a0aec0', lineHeight: 1.6 },
  acceptedBadge: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '4px',
    padding: '6px 14px',
    background: '#1a3a2a',
    color: '#68d391',
    border: '1px solid #2f855a',
    borderRadius: '6px',
    fontSize: '13px',
    fontWeight: 600,
  },
  acceptBtn: {
    padding: '8px 20px',
    background: '#276749',
    color: '#c6f6d5',
    border: '1px solid #2f855a',
    borderRadius: '6px',
    cursor: 'pointer',
    fontSize: '13px',
    fontWeight: 600,
    width: '100%',
  },
}

const sizingStyle = (isOver) => ({
  background: isOver ? '#1a0a0a' : '#0a1f12',
  border: `1px solid ${isOver ? '#742a2a' : '#276749'}`,
  borderRadius: '6px', padding: '7px 10px',
  fontSize: '12px', color: isOver ? '#fc8181' : '#68d391',
  marginTop: '-4px',
})

export default function WheelCard({ rec, onAccepted }) {
  const [showModal, setShowModal] = useState(false)
  const [account, setAccount] = useState(null)

  useEffect(() => {
    api.account.getBalance().then(setAccount).catch(() => {})
  }, [])

  const capitalRequired = rec.put_strike ? rec.put_strike * 100 : null
  const isOverLimit = account && capitalRequired && capitalRequired > account.max_single_position
  const pctOfAccount = account && capitalRequired && account.balance > 0
    ? Math.round((capitalRequired / account.balance) * 100)
    : null

  return (
    <div style={s.card}>
      <div style={s.cardHeader}>
        <span style={s.ticker}>{rec.ticker}</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={s.rankBadge}>#{rec.rank}</span>
          <GradeChip grade={rec.grade} />
        </div>
      </div>

      {rec.combined_score != null ? (
        <div>
          <div style={{ fontSize: '11px', color: '#718096', marginBottom: '4px' }}>CONFIDENCE SCORE</div>
          <DualScorePanel
            quantScore={rec.quant_score}
            qualScore={rec.qual_score}
            combinedScore={rec.combined_score}
          />
        </div>
      ) : (
        <div>
          <div style={{ fontSize: '11px', color: '#718096', marginBottom: '4px' }}>CONVICTION SCORE</div>
          <ScoreBar score={rec.score} />
        </div>
      )}

      <TradingViewWidget ticker={rec.ticker} />

      <table style={s.table}>
        <tbody>
          <tr>
            <td style={s.td}>Suggested Put Strike</td>
            <td style={{ ...s.tdVal, color: '#fc8181' }}>
              {rec.put_strike ? `$${rec.put_strike}` : '—'}
            </td>
            <td style={s.td}>Expiry</td>
            <td style={s.tdVal}>{rec.put_expiry || '—'}</td>
          </tr>
          <tr>
            <td style={s.td}>Premium / Contract</td>
            <td style={{ ...s.tdVal, color: '#68d391' }}>
              {rec.put_premium ? `$${rec.put_premium}` : '—'}
            </td>
            <td style={s.td}>IV Rank</td>
            <td style={s.tdVal}>{rec.iv_rank ? `${rec.iv_rank}` : '—'}</td>
          </tr>
          {(rec.pct_otm != null || rec.breakeven != null) && (
            <tr>
              <td style={s.td}>% OTM</td>
              <td style={s.tdVal}>{rec.pct_otm != null ? `${rec.pct_otm}%` : '—'}</td>
              <td style={s.td}>Breakeven</td>
              <td style={{ ...s.tdVal, color: '#fbd38d' }}>
                {rec.breakeven != null ? `$${Number(rec.breakeven).toFixed(2)}` : '—'}
              </td>
            </tr>
          )}
        </tbody>
      </table>

      {capitalRequired && account && (
        <div style={sizingStyle(isOverLimit)}>
          {isOverLimit
            ? `⚠ This trade requires ~$${capitalRequired.toLocaleString()} (${pctOfAccount}% of your account) — exceeds your ${account.max_position_pct}% position limit of $${account.max_single_position.toLocaleString()}. Consider skipping or reducing size.`
            : `✓ Capital required: ~$${capitalRequired.toLocaleString()} (${pctOfAccount}% of account) — within your $${account.max_single_position.toLocaleString()} position limit.`
          }
        </div>
      )}

      <div>
        <div style={{ fontSize: '11px', color: '#718096', marginBottom: '6px' }}>WHY THIS STOCK</div>
        <p style={s.explanation}>{rec.explanation}</p>
      </div>

      {rec.accepted ? (
        <div style={s.acceptedBadge}>✓ Accepted — tracking in positions below</div>
      ) : (
        <button style={s.acceptBtn} onClick={() => setShowModal(true)}>
          ✓ Accept &amp; Track This Trade
        </button>
      )}

      {showModal && (
        <AcceptModal
          rec={rec}
          onClose={() => setShowModal(false)}
          onAccepted={(pos) => {
            setShowModal(false)
            onAccepted(pos)
          }}
        />
      )}
    </div>
  )
}
