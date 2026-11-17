import type { Confidence } from './types'
import { confidenceLabel } from './format'

export function Badge({ confidence }: { confidence: Confidence }) {
  return <span className={`badge badge-${confidence}`}>{confidenceLabel[confidence]}</span>
}
