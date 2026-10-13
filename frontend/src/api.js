const BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(message, status, payload) {
    super(message)
    this.status = status
    this.payload = payload
  }
}

function messageFrom(payload, status) {
  if (!payload) return `Request failed (${status})`
  if (typeof payload === 'string') return payload
  if (payload.detail) return payload.detail
  if (Array.isArray(payload)) return payload.join(' ')
  const first = Object.values(payload)[0]
  return Array.isArray(first) ? first[0] : String(first ?? `Request failed (${status})`)
}

async function request(path, { method = 'GET', organization, body } = {}) {
  const headers = {}
  if (organization) headers['X-Organization'] = organization

  let response
  try {
    response = await fetch(`${BASE_URL}${path}`, { method, headers, body })
  } catch (cause) {
    throw new ApiError('Could not reach the Wirewise API. Is the backend running?', 0, null)
  }

  const text = await response.text()
  let payload = null
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = text
    }
  }
  if (!response.ok) {
    throw new ApiError(messageFrom(payload, response.status), response.status, payload)
  }
  return payload
}

export const api = {
  organizations: () => request('/organizations'),
  transactions: (organization) => request('/transactions', { organization }),
  lineItems: (organization) => request('/line-items', { organization }),
  importStatement: (organization, file) => {
    const body = new FormData()
    body.append('file', file)
    return request('/imports', { method: 'POST', organization, body })
  },
  approveMatch: (organization, matchId) =>
    request(`/matches/${matchId}/approve`, { method: 'POST', organization }),
  rejectMatch: (organization, matchId) =>
    request(`/matches/${matchId}/reject`, { method: 'POST', organization }),
  ignoreTransaction: (organization, transactionId) =>
    request(`/transactions/${transactionId}/ignore`, { method: 'POST', organization }),
}
