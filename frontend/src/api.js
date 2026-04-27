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
  },
  longterm: {
    getRecommendations: () => request('/api/longterm/recommendations'),
    refresh: () => request('/api/longterm/refresh', { method: 'POST' }),
  },
  lookup: {
    analyze: (ticker) => request('/api/lookup/analyze', { method: 'POST', body: { ticker } }),
  },
  getStatus: () => request('/api/status'),
}
