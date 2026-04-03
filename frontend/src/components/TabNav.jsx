const styles = {
  nav: {
    background: '#1a1f2e',
    borderBottom: '1px solid #2d3748',
    display: 'flex',
    padding: '0 24px',
  },
  tab: (active) => ({
    padding: '14px 20px',
    cursor: 'pointer',
    fontSize: '14px',
    fontWeight: active ? 600 : 400,
    color: active ? '#63b3ed' : '#718096',
    borderBottom: active ? '2px solid #63b3ed' : '2px solid transparent',
    background: 'none',
    border: 'none',
    borderBottomStyle: 'solid',
    borderBottomWidth: '2px',
    borderBottomColor: active ? '#63b3ed' : 'transparent',
    transition: 'all 0.2s',
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
