/**
 * 与后端 FastAPI 交互的 axios 客户端
 * - Vite dev proxy 把 /api 转到 http://127.0.0.1:8000
 */
import axios from 'axios'

export const api = axios.create({
  baseURL: '/api',
  timeout: 15_000,
  headers: { 'Content-Type': 'application/json' },
})

// ── Users ─────────────────────────────────────
export const UsersAPI = {
  create: (username: string, display_name?: string, avg_level?: string) =>
    api.post('/users', { username, display_name, avg_level }).then(r => r.data),
  get: (id: number) => api.get(`/users/${id}`).then(r => r.data),
  byName: (username: string) => api.get(`/users/by-username/${username}`).then(r => r.data),
}

// ── Solves ────────────────────────────────────
export const SolvesAPI = {
  start: (user_id: number, scramble?: string) =>
    api.post('/solves/start', { user_id, scramble }).then(r => r.data),
  addMove: (cube_id: number, move: string, timestamp_ms?: number) =>
    api.post(`/solves/${cube_id}/moves`, { move, timestamp_ms }).then(r => r.data),
  finish: (cube_id: number) => api.post(`/solves/${cube_id}/finish`).then(r => r.data),
}

// ── Sessions ──────────────────────────────────
export const SessionsAPI = {
  list: (user_id: number) => api.get('/sessions', { params: { user_id } }).then(r => r.data),
  get: (id: number) => api.get(`/sessions/${id}`).then(r => r.data),
  close: (id: number) => api.post(`/sessions/${id}/close`).then(r => r.data),
  aggregate: (id: number) => api.post(`/sessions/${id}/aggregate`).then(r => r.data),
  generateTraining: (id: number, run_ai = false) =>
    api.post(`/sessions/${id}/generate-training`, null, { params: { run_ai } }).then(r => r.data),
}

// ── Training Tasks ───────────────────────────
export const TrainingAPI = {
  today: (user_id: number) => api.get('/training/today', { params: { user_id } }).then(r => r.data),
  markDone: (id: number, result: object) =>
    api.post(`/training/${id}/done`, { result }).then(r => r.data),
  skip: (id: number) => api.post(`/training/${id}/skip`).then(r => r.data),
}

// ── Formulas ─────────────────────────────────
export const FormulasAPI = {
  sets: () => api.get('/formulas/sets').then(r => r.data),
  set: (code: string) => api.get(`/formulas/sets/${code}`).then(r => r.data),
  search: (q: string, set?: string) =>
    api.get('/formulas/search', { params: { q, set } }).then(r => r.data),
  seed: (only?: string, use_cache = true) =>
    api.post('/formulas/seed', null, { params: { only, use_cache } }).then(r => r.data),
}

// ── Dashboard ────────────────────────────────
export const DashboardAPI = {
  today: (user_id: number) => api.get('/dashboard/today', { params: { user_id } }).then(r => r.data),
  recommendGoal: (user_id: number) =>
    api.post('/dashboard/recommend-goal', null, { params: { user_id } }).then(r => r.data),
}

// ── AI ───────────────────────────────────────
export const AIAPI = {
  analyze: (session_id: number, user_level = '未指定') =>
    api.post(`/ai/sessions/${session_id}/analyze`, null, { params: { user_level } }).then(r => r.data),
  latest: (session_id: number) => api.get(`/ai/sessions/${session_id}/latest`).then(r => r.data),
}
