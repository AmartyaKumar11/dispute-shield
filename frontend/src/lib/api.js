import axios from 'axios'

const api = axios.create({
  baseURL: 'http://localhost:8000',
  timeout: 120000,
})

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

export default api
