import type { Confidence, Provider } from './types'

export const pct = (v: number | null | undefined, digits = 0) =>
  v == null ? '–' : `${(v * 100).toFixed(digits)}%`

export const num = (v: number | null | undefined) =>
  v == null ? '–' : Math.round(v).toLocaleString()

export function address(p: Pick<Provider, 'street1' | 'street2' | 'city' | 'state' | 'zip5'>): string {
  const line1 = [p.street1, p.street2].filter(Boolean).join(', ')
  const line2 = [p.city, [p.state, p.zip5].filter(Boolean).join(' ')].filter(Boolean).join(', ')
  return [line1, line2].filter(Boolean).join(' · ')
}

export const confidenceLabel: Record<Confidence, string> = {
  verified: 'Verified',
  corrected: 'Address corrected',
  high: 'Likely current',
  medium: 'Check before visiting',
  low: 'May be out of date',
  unscored: 'Not scored',
}
