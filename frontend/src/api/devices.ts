/** 智能魔方设备管理 */
import { api } from './client'

export interface Device {
  id: number
  brand: string | null
  model: string | null
  mac_address: string | null
  nickname: string | null
  protocol: string
  adapter: string
  battery_pct: number | null
  state: string
  last_event_at: number | null
  paired_at: number | null
  last_sync_at: number | null
}

export const DevicesAPI = {
  list: (user_id: number) => api.get<Device[]>('/devices', { params: { user_id } }).then(r => r.data),
  create: (user_id: number, body: {
    brand: string; mac_address?: string | null; model?: string | null;
    nickname?: string | null; protocol?: string; adapter?: string;
  }) => api.post<Device>('/devices', body, { params: { user_id } }).then(r => r.data),
  update: (user_id: number, id: number, body: { nickname?: string; model?: string }) =>
    api.patch<Device>(`/devices/${id}`, body, { params: { user_id } }).then(r => r.data),
  delete: (user_id: number, id: number) =>
    api.delete(`/devices/${id}`, { params: { user_id } }).then(r => r.data),
  connect:    (user_id: number, id: number) => api.post(`/devices/${id}/connect`,    null, { params: { user_id } }).then(r => r.data),
  scramble:   (user_id: number, id: number) => api.post(`/devices/${id}/scramble`,   null, { params: { user_id } }).then(r => r.data),
  inspect:    (user_id: number, id: number, duration_ms = 15000) =>
    api.post(`/devices/${id}/inspect`, null, { params: { user_id, duration_ms } }).then(r => r.data),
  start:      (user_id: number, id: number) => api.post(`/devices/${id}/start`,      null, { params: { user_id } }).then(r => r.data),
  stop:       (user_id: number, id: number) => api.post(`/devices/${id}/stop`,       null, { params: { user_id } }).then(r => r.data),
  reset:      (user_id: number, id: number) => api.post(`/devices/${id}/reset`,      null, { params: { user_id } }).then(r => r.data),
  applyMove:  (user_id: number, id: number, move: string) =>
    api.post(`/devices/${id}/apply-move`, { move }, { params: { user_id } }).then(r => r.data),
}
