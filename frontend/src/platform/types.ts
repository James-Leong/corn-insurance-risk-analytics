export type BusinessRecord = { id: string; version: number; status: string; created_at?: string; [key: string]: unknown }
export type SessionUser = { id: string; username: string; display_name?: string; name?: string; role: 'operator' | 'reviewer' | 'customer'; customer_id?: string; permissions?: string[] }
export type Workspace = {
  revision: number; execution_mode: string; as_of: string;
  projects: BusinessRecord[]; product: BusinessRecord; applications: BusinessRecord[]; policies: BusinessRecord[];
  reinsurance: BusinessRecord[]; plans: BusinessRecord[]; executions: BusinessRecord[]; hedges: BusinessRecord[];
  allocations: BusinessRecord[]; fixings: BusinessRecord[]; claims: BusinessRecord[]; payables: BusinessRecord[];
  payments: BusinessRecord[]; recoveries: BusinessRecord[]; reconciliations: BusinessRecord[];
  tasks: BusinessRecord[]; audit_events: BusinessRecord[]; [key: string]: unknown;
}
export type Column = { key: string; label: string; format?: 'number' | 'money' | 'date' | 'status' | 'tons' | 'percent'; secondary?: string; width?: string }
export type Choice = { value: string; label: string }
export type FormField = { key: string; label: string; type?: 'text' | 'number' | 'date' | 'datetime-local' | 'select' | 'textarea' | 'checkbox'; options?: Choice[]; value?: unknown; required?: boolean; min?: number; max?: number; step?: string; help?: string; readonly?: boolean }
export type CommandForm = { title: string; description: string; command: string; target?: BusinessRecord; fields: FormField[]; submitLabel?: string; note?: string; map?: (values: Record<string, unknown>) => Record<string, unknown> }
export type DataSeries = { id: string; name: string; unit: string; source_id?: string; source?: string; status?: string; frequency?: string; description?: string; category?: string; [key: string]: unknown }
export type Observation = { date: string; value: number | null; source_published_at?: string; first_seen_at?: string; release_id?: string; quality_flag?: string; [key: string]: unknown }
