import type {
  MetricsResponse, ParsedNote, Provider, ProviderDetail, Specialty, Verification, VerificationInput,
} from './types'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init)
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(body?.error ?? `Request failed (${res.status})`)
  }
  return res.json() as Promise<T>
}

function query(params: Record<string, string | number | undefined>): string {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== '') q.set(k, String(v))
  }
  const s = q.toString()
  return s ? `?${s}` : ''
}

export const api = {
  specialties: () => request<Specialty[]>('/api/specialties'),
  queue: (p: { specialty?: string; sort?: string; limit?: number }) =>
    request<Provider[]>(`/api/queue${query(p)}`),
  search: (p: { zip?: string; specialty?: string; q?: string; limit?: number }) =>
    request<Provider[]>(`/api/providers${query(p)}`),
  detail: (npi: string) => request<ProviderDetail>(`/api/providers/${npi}`),
  verify: (npi: string, body: VerificationInput) =>
    request<Verification>(`/api/providers/${npi}/verifications`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  parseNote: (note: string) =>
    request<ParsedNote>('/api/parse-note', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ note }),
    }),
  metrics: () => request<MetricsResponse>('/api/metrics'),
}
