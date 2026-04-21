import { useState } from 'react'
import TabNav from './components/TabNav'
import OptionsTab from './tabs/OptionsTab'
import WheelTab from './tabs/WheelTab'
import LongTermTab from './tabs/LongTermTab'
import StockLookupTab from './tabs/StockLookupTab'

const TABS = [
  { id: 'options', label: '📈 Options Trading' },
  { id: 'wheel', label: '🔄 Wheel Strategy' },
  { id: 'longterm', label: '🌱 Growth & Income' },
  { id: 'lookup', label: '🔍 Stock Lookup' },
]

const styles = {
  app: {
    minHeight: '100vh',
    background: '#0f1117',
    color: '#e2e8f0',
  },
  header: {
    background: 'linear-gradient(135deg, #1a1f2e 0%, #16213e 100%)',
    borderBottom: '1px solid #2d3748',
    padding: '16px 24px',
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
  },
  logo: {
    fontSize: '22px',
    fontWeight: 700,
    color: '#63b3ed',
    letterSpacing: '-0.5px',
  },
  subtitle: {
    fontSize: '12px',
    color: '#718096',
    marginTop: '2px',
  },
  content: {
    maxWidth: '1400px',
    margin: '0 auto',
    padding: '24px 16px',
  },
}

export default function App() {
  const [activeTab, setActiveTab] = useState('options')

  return (
    <div style={styles.app}>
      <header style={styles.header}>
        <div>
          <div style={styles.logo}>TradeIQ</div>
          <div style={styles.subtitle}>AI-powered trading recommendations</div>
        </div>
      </header>
      <TabNav tabs={TABS} activeTab={activeTab} onTabChange={setActiveTab} />
      <main style={styles.content}>
        {activeTab === 'options' && <OptionsTab />}
        {activeTab === 'wheel' && <WheelTab />}
        {activeTab === 'longterm' && <LongTermTab />}
        {activeTab === 'lookup' && <StockLookupTab />}
      </main>
    </div>
  )
}
