import { useState, Component } from 'react'
import TabNav from './components/TabNav'
import MarketBanner from './components/MarketBanner'
import OptionsTab from './tabs/OptionsTab'
import WheelTab from './tabs/WheelTab'
import CoveredCallsTab from './tabs/CoveredCallsTab'
import MarketPulseTab from './tabs/MarketPulseTab'
import StockTriggersTab from './tabs/StockTriggersTab'
import LeveragedMATab from './tabs/LeveragedMATab'
import AlertsTab from './tabs/AlertsTab'
import BuyHoldTab from './tabs/BuyHoldTab'
import IncomeTab from './tabs/IncomeTab'
import BookTab from './tabs/BookTab'

const TABS = [
  { id: 'pulse',        label: '⚡ Today' },
  { id: 'buyhold',      label: '📊 Buy and Hold' },
  { id: 'wheel',        label: '🔄 Wheel Strategy' },
  { id: 'options',      label: '📈 Directional' },
  { id: 'levma',        label: '📡 Leveraged Signals' },
  { id: 'income',       label: '💵 Income' },
  { id: 'book',         label: '📖 Book' },
  { id: 'alerts',       label: '🔔 Setup Alerts' },
  { id: 'triggers',     label: '🎯 Stock Triggers' },
  { id: 'coveredcalls', label: '💰 Covered Calls' },
]

class TabErrorBoundary extends Component {
  constructor(props) { super(props); this.state = { error: null } }
  static getDerivedStateFromError(e) { return { error: e } }
  render() {
    if (this.state.error) return (
      <div style={{ padding: '32px', color: '#fc8181', background: '#2d1515', borderRadius: '8px', margin: '24px' }}>
        <strong>Something went wrong rendering this tab.</strong>
        <div style={{ fontSize: '12px', marginTop: '8px', color: '#a0aec0' }}>
          {this.state.error?.message || 'Unknown error'}
        </div>
        <button
          onClick={() => this.setState({ error: null })}
          style={{ marginTop: '12px', padding: '6px 16px', background: '#2b6cb0', color: '#fff', border: 'none', borderRadius: '6px', cursor: 'pointer' }}
        >
          Retry
        </button>
      </div>
    )
    return this.props.children
  }
}

const styles = {
  app: {
    minHeight: '100vh',
    background: '#0f1117',
    color: '#e2e8f0',
    display: 'flex',
    flexDirection: 'column',
  },
  header: {
    background: 'linear-gradient(135deg, #1a1f2e 0%, #16213e 100%)',
    borderBottom: '1px solid #2d3748',
    padding: '12px 20px',
    display: 'flex',
    alignItems: 'center',
    gap: '14px',
    flexShrink: 0,
  },
  logoGroup: { display: 'flex', flexDirection: 'column' },
  logo: {
    fontSize: '22px',
    fontWeight: 700,
    color: '#63b3ed',
    letterSpacing: '-0.5px',
  },
  subtitle: {
    fontSize: '12px',
    color: '#718096',
    marginTop: '1px',
  },
  activeLabel: {
    marginLeft: 'auto',
    fontSize: '13px',
    fontWeight: 600,
    color: '#a0aec0',
    whiteSpace: 'nowrap',
  },
  content: {
    flex: 1,
    padding: '24px',
    overflowY: 'auto',
  },
}

export default function App() {
  const [activeTab, setActiveTab] = useState('pulse')
  const [menuOpen, setMenuOpen] = useState(false)

  const activeLabel = TABS.find(t => t.id === activeTab)?.label ?? ''

  return (
    <div style={styles.app}>
      <header style={styles.header}>
        <TabNav
          tabs={TABS}
          activeTab={activeTab}
          onTabChange={setActiveTab}
          open={menuOpen}
          onToggle={setMenuOpen}
        />
        <div style={styles.logoGroup}>
          <div style={styles.logo}>TradeIQ</div>
          <div style={styles.subtitle}>AI-powered trading recommendations</div>
        </div>
        <span style={styles.activeLabel}>{activeLabel}</span>
      </header>

      <MarketBanner />

      <main style={styles.content}>
        <TabErrorBoundary key={activeTab}>
          {activeTab === 'pulse'        && <MarketPulseTab />}
          {activeTab === 'options'      && <OptionsTab />}
          {activeTab === 'wheel'        && <WheelTab />}
          {activeTab === 'coveredcalls' && <CoveredCallsTab />}
          {activeTab === 'buyhold'      && <BuyHoldTab />}
          {activeTab === 'income'       && <IncomeTab />}
          {activeTab === 'book'         && <BookTab />}
          {activeTab === 'triggers'     && <StockTriggersTab />}
          {activeTab === 'levma'        && <LeveragedMATab />}
          {activeTab === 'alerts'       && <AlertsTab />}
        </TabErrorBoundary>
      </main>
    </div>
  )
}
