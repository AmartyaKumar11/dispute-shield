import axios from 'axios'

const api = axios.create({
  // Use 127.0.0.1 — Windows localhost often resolves to ::1 while uvicorn binds IPv4 only.
  baseURL: 'http://127.0.0.1:8000',
  timeout: 120000,
})

export function apiErrorMessage(err) {
  if (err.response?.data?.detail) {
    const d = err.response.data.detail
    return typeof d === 'string' ? d : JSON.stringify(d)
  }
  if (err.code === 'ECONNABORTED') return 'Request timed out — try again'
  if (err.message === 'Network Error') {
    return 'Cannot reach backend at http://127.0.0.1:8000 — is uvicorn running?'
  }
  return err.message || 'Request failed'
}

export async function getDisputes(params = {}) {
  const { data } = await api.get('/api/disputes', { params })
  return data
}

export async function getDispute(id) {
  const { data } = await api.get(`/api/disputes/${id}`)
  return data
}

export async function getMetrics() {
  const { data } = await api.get('/api/metrics/summary')
  return data
}

export async function seedDisputes() {
  const { data } = await api.post('/api/seed/create-test-disputes')
  return data
}

export async function retryDispute(id) {
  const { data } = await api.post(`/api/disputes/${id}/retry`)
  return data
}

export async function forceSubmitDispute(id) {
  const { data } = await api.post(`/api/disputes/${id}/force-submit`)
  return data
}

export async function acceptDispute(id) {
  const { data } = await api.post(`/api/disputes/${id}/accept`)
  return data
}

export async function getRisks() {
  const { data } = await api.get('/api/risks')
  return data
}

export async function getRiskSummary() {
  const { data } = await api.get('/api/risks/summary')
  return data
}

export async function getIntelligence() {
  const { data } = await api.get('/api/intelligence/insights')
  return data
}

export async function getEvaluation() {
  const { data } = await api.get('/api/evaluation/report')
  return data
}

export async function getModelsInfo() {
  const { data } = await api.get('/api/models/info')
  return data
}

export async function sendTestEmail(payload) {
  const { data } = await api.post('/api/test/send-email', payload)
  return data
}

export async function createShiprocketOrder(payload) {
  const { data } = await api.post('/api/test/create-shiprocket-order', payload)
  return data
}

export async function sendResolutionOffer(disputeId, message) {
  const { data } = await api.post(`/api/disputes/${disputeId}/send-resolution-offer`, {
    message: message || undefined,
  })
  return data
}

export default api
