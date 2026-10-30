import type { BusinessRecord, SessionUser, Workspace } from './types'
const sessionKey = 'grainguard.session.v2'
let token = sessionStorage.getItem(sessionKey) || ''
export const hasSession = () => !!token
export function clearSession() { token = ''; sessionStorage.removeItem(sessionKey) }
export async function request<T>(path: string, body?: unknown, method?: string): Promise<T> {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 45000)
  try {
    const response = await fetch(`/api/v2${path}`, {
      method: method || (body === undefined ? 'GET' : 'POST'),
      headers: { ...(body === undefined ? {} : { 'Content-Type': 'application/json' }), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }), signal: controller.signal,
    })
    const data = await response.json().catch(() => null)
    if (!response.ok) {
      if (response.status === 401) clearSession()
      const detail = data?.detail
      throw new Error(typeof detail === 'string' ? detail : detail?.message || data?.message || `请求未完成（HTTP ${response.status}）`)
    }
    return data as T
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw new Error('请求超时。业务请求可能已受理，请刷新或查单确认后再操作。')
    throw error instanceof Error ? error : new Error('服务连接失败，请检查网络后重试。')
  } finally { clearTimeout(timeout) }
}
export const platformApi = {
  async login(username: string, password: string) {
    const result = await request<{ token: string; user: SessionUser }>('/session', { username, password })
    token = result.token; sessionStorage.setItem(sessionKey, token); return result.user
  },
  logout: () => request<void>('/session', undefined, 'DELETE'),
  session: () => request<{ user: SessionUser }>('/session'),
  workspace: (projectId: string) => request<Workspace>(`/workspace?project_id=${encodeURIComponent(projectId)}`),
  command: (command: string, projectId: string, payload: Record<string, unknown>, target?: BusinessRecord, requestId?: string) => request<{ snapshot: Workspace; result: unknown; message: string }>('/workspace/commands', {
    request_id: requestId || crypto.randomUUID(), command, project_id: projectId, payload,
    ...(target ? { target_id: target.id, expected_version: target.version } : {}),
  }),
}
export function downloadCsv(name: string, columns: { key: string; label: string }[], records: Record<string, unknown>[]) {
  const escape = (value: unknown) => { let s = value == null ? '' : typeof value === 'object' ? JSON.stringify(value) : String(value); if (/^[=+@\-]/.test(s)) s = `'${s}`; return `"${s.replace(/"/g, '""')}"` }
  const content = '\ufeff' + [columns.map(c => escape(c.label)).join(','), ...records.map(r => columns.map(c => escape(r[c.key])).join(','))].join('\r\n')
  const anchor = document.createElement('a'); anchor.href = URL.createObjectURL(new Blob([content], { type: 'text/csv;charset=utf-8' })); anchor.download = `${name}.csv`; anchor.click(); setTimeout(() => URL.revokeObjectURL(anchor.href), 1000)
}
