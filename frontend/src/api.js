const BASE = import.meta.env.VITE_API_BASE ?? ''

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

export const api = {
  options: {
    getRecommendations: () => request('/api/options/recommendations'),
    refresh: () => request('/api/options/refresh', { method: 'POST' }),
    getDirectional: () => request('/api/options/directional'),
    refreshDirectional: () => request('/api/options/directional/refresh', { method: 'POST' }),
  },
  wheel: {
    getRecommendations: () => request('/api/wheel/recommendations'),
    acceptRecommendation: (id, body) =>
      request(`/api/wheel/recommendations/${id}/accept`, { method: 'POST', body }),
    getPositions: (includeClosed = false) =>
      request(`/api/wheel/positions?include_closed=${includeClosed}`),
    getPosition: (id) => request(`/api/wheel/positions/${id}`),
    updateStatus: (id, body) =>
      request(`/api/wheel/positions/${id}/status`, { method: 'PATCH', body }),
    getCallSuggestion: (id) => request(`/api/wheel/positions/${id}/call-suggestion`),
    refreshCallSuggestion: (id) =>
      request(`/api/wheel/positions/${id}/call-suggestion/refresh`, { method: 'POST' }),
    refresh: () => request('/api/wheel/refresh', { method: 'POST' }),
    customAnalyze: (ticker) =>
      request('/api/wheel/custom-analyze', { method: 'POST', body: { ticker } }),
    exportPositions: () => request('/api/wheel/positions/export'),
    getRollAlert: (id) => request(`/api/wheel/positions/${id}/roll-alert`),
    getRollSuggestion: (id) => request(`/api/wheel/positions/${id}/roll-suggestion`, { method: 'POST' }),
    getScannerCandidates: () => request('/api/wheel/scanner/candidates'),
    refreshScanner: () => request('/api/wheel/scanner/refresh', { method: 'POST' }),
    getScannerStatus: () => request('/api/wheel/scanner/status'),
  },
  market: {
    getContext: (refresh = false) => request(`/api/market/context${refresh ? '?refresh=true' : ''}`),
  },
  account: {
    getBalance: () => request('/api/account'),
    deposit: (amount, note) => request('/api/account/deposit', { method: 'POST', body: { amount, note } }),
    setBalance: (balance, note) => request('/api/account', { method: 'PATCH', body: { balance, note } }),
    getTransactions: () => request('/api/account/transactions'),
  },
  performance: {
    getSummary: () => request('/api/performance/summary'),
  },
  watchlist: {
    list: () => request('/api/watchlist'),
    add: (ticker, notes = '') => request('/api/watchlist', { method: 'POST', body: { ticker, notes } }),
    remove: (ticker) => request(`/api/watchlist/${ticker}`, { method: 'DELETE' }),
    score: (ticker) => request(`/api/watchlist/${ticker}/score`, { method: 'POST' }),
    quickScore: (ticker) => request(`/api/watchlist/${ticker}/quick-score`, { method: 'POST' }),
  },
  champions: {
    get: () => request('/api/champions'),
    refresh: () => request('/api/champions/refresh', { method: 'POST' }),
  },
  coveredCalls: {
    analyze: (ticker, costBasis = null) =>
      request('/api/covered-calls/analyze', {
        method: 'POST',
        body: { ticker, cost_basis: costBasis },
      }),
    weeklyAnalyze: (ticker, costBasis = null) =>
      request('/api/covered-calls/weekly-analyze', {
        method: 'POST',
        body: { ticker, cost_basis: costBasis },
      }),
  },
  scanner: {
    scan: () => request('/api/scanner/scan'),
    marketStatus: () => request('/api/scanner/market-status'),
  },
  flow: {
    scan: () => request('/api/flow/scan'),
  },
  alerts: {
    getToday: () => request('/api/alerts/today'),
    getRegistry: () => request('/api/alerts/registry'),
    getStats: () => request('/api/alerts/stats'),
    getJournal: (setupKey) => request(`/api/alerts/journal${setupKey ? `?setup_key=${setupKey}` : ''}`),
    setStatus: (key, status) => request(`/api/alerts/registry/${key}/status`, { method: 'POST', body: { status } }),
    triggerRun: () => request('/api/alerts/run', { method: 'POST' }),
    triggerOutcomeJob: () => request('/api/alerts/outcome-job', { method: 'POST' }),
  },
  getStatus: () => request('/api/status'),
  discovery: {
    get: () => request('/api/discovery'),
  },
  dcf: {
    get: (ticker) => request(`/api/dcf/${encodeURIComponent(ticker)}`),
  },
  cef: {
    scan: () => request('/api/cef/scan'),
    refresh: () => request('/api/cef/refresh', { method: 'POST' }),
  },
  dividendPath: {
    recommend: (startCap = 61000, weeklyDca = 500) =>
      request(`/api/dividend-path/recommend?starting_capital=${startCap}&weekly_dca=${weeklyDca}`),
    refresh: (startCap = 61000, weeklyDca = 500) =>
      request(`/api/dividend-path/refresh?starting_capital=${startCap}&weekly_dca=${weeklyDca}`, { method: 'POST' }),
  },
  twelveStep: {
    getData: (ticker) => request(`/api/twelve-step/data/${encodeURIComponent(ticker)}`),
    screener: (filters) => request('/api/twelve-step/screener', { method: 'POST', body: filters }),
  },
}
