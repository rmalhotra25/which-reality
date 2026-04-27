const styles = {
  nav: {
    width: '200px',
    flexShrink: 0,
    background: '#1a1f2e',
    borderRight: '1px solid #2d3748',
    display: 'flex',
    flexDirection: 'column',
    padding: '16px 0',
    minHeight: '100%',
  },
  tab: (active) => ({
    display: 'flex',
    alignItems: 'center',
    gap: '10px',
    padding: '11px 20px',
    cursor: 'pointer',
    fontSize: '14px',
    fontWeight: active ? 600 : 400,
    color: active ? '#e2e8f0' : '#718096',
    background: active ? 'rgba(99,179,237,0.1)' : 'none',
    borderLeft: active ? '3px solid #63b3ed' : '3px solid transparent',
    border: 'none',
    borderLeftStyle: 'solid',
    borderLeftWidth: '3px',
    borderLeftColor: active ? '#63b3ed' : 'transparent',
    width: '100%',
    textAlign: 'left',
    transition: 'all 0.15s',
    whiteSpace: 'nowrap',
  }),
}

export default function TabNav({ tabs, activeTab, onTabChange }) {
  return (
    <nav style={styles.nav}>
      {tabs.map((tab) => (
        <button
          key={tab.id}
          style={styles.tab(activeTab === tab.id)}
          onClick={() => onTabChange(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </nav>
  )
}
