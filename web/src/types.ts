export type Confidence = 'verified' | 'corrected' | 'high' | 'medium' | 'low' | 'unscored'
export type Outcome = 'confirmed' | 'moved' | 'closed' | 'unreachable'

export interface Reason {
  code: string
  text: string
}

export interface Provider {
  npi: string
  name: string
  credentials: string | null
  entity_code: string
  specialty: string
  street1: string | null
  street2: string | null
  city: string | null
  state: string | null
  zip5: string | null
  data_year: number
  medicare_patients: number | null
  tenure_years: number
  p_stale: number | null
  p_move: number | null
  risk_pct: number | null
  expected_patients_affected: number | null
  reasons: Reason[]
  confidence: Confidence
  last_verified_at: string | null
  last_outcome: Outcome | null
  corrected_street: string | null
  corrected_city: string | null
  corrected_zip: string | null
}

export interface HistoryRow {
  data_year: number
  street1: string | null
  city: string | null
  zip5: string | null
  medicare_patients: number | null
  moved_next_year: boolean | null
}

export interface Verification {
  id: number
  outcome: Outcome
  new_street: string | null
  new_city: string | null
  new_zip: string | null
  new_phone: string | null
  accepting_new_patients: boolean | null
  notes: string | null
  source: string
  created_at: string
}

export interface ProviderDetail {
  provider: Provider
  history: HistoryRow[]
  verifications: Verification[]
}

export interface VerificationInput {
  outcome: Outcome
  new_street?: string | null
  new_city?: string | null
  new_zip?: string | null
  new_phone?: string | null
  accepting_new_patients?: boolean | null
  notes?: string | null
  source: 'manual' | 'simulated'
}

export interface ParsedNote {
  outcome: Outcome
  new_street: string | null
  new_city: string | null
  new_zip: string | null
  new_phone: string | null
  accepting_new_patients: boolean | null
  confidence: 'high' | 'low'
  evidence: string
}

export interface CapturePoint {
  review_fraction: number
  reviewed: number
  precision: number
  recall: number
  lift: number
}

export interface ModelMetrics {
  rows?: number
  positives?: number
  base_rate?: number
  roc_auc: number
  average_precision?: number
  capture: CapturePoint[]
  calibration?: { predicted: number; observed: number; n: number }[]
  patient_weighted_capture?: {
    review_fraction: number
    share_of_affected_patients: number
    volume_only_baseline: number
    random_baseline: number
  }[]
  patients_50_plus?: { rows: number; base_rate: number; roc_auc: number; capture: CapturePoint[] }
}

export interface MetricsResponse {
  model_version: string
  created_at: string
  metrics: {
    states: string[]
    train_years: number[]
    test_years: number[]
    served_model: string
    labels: Record<string, string>
    targets: Record<string, { train_rows: number; models: Record<string, ModelMetrics> }>
  }
}

export interface Specialty {
  specialty: string
  count: number
}
