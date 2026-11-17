import { useState, type FormEvent } from 'react'
import { api } from './api'
import { Badge } from './Badge'
import { address, num, pct } from './format'
import type { Outcome, ParsedNote, VerificationInput } from './types'
import { useAsync } from './useAsync'

const outcomes: { value: Outcome; label: string }[] = [
  { value: 'confirmed', label: 'Still at this address' },
  { value: 'moved', label: 'Moved to a new address' },
  { value: 'closed', label: 'No longer practicing here' },
  { value: 'unreachable', label: 'Could not reach the office' },
]

const emptyForm = {
  outcome: 'confirmed' as Outcome,
  new_street: '',
  new_city: '',
  new_zip: '',
  new_phone: '',
  accepting: '' as '' | 'yes' | 'no',
  notes: '',
}

export function ProviderPanel({ npi, onVerified }: { npi: string; onVerified: () => void }) {
  const detail = useAsync(() => api.detail(npi), [npi])
  const [form, setForm] = useState(emptyForm)
  const [parsed, setParsed] = useState<ParsedNote | null>(null)
  const [parsing, setParsing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (detail.error) return <p className="error">Could not load this provider: {detail.error}</p>
  if (!detail.data) return <p className="hint">Loading…</p>
  const { provider: p, history, verifications } = detail.data

  async function parseNote() {
    setParsing(true)
    setError(null)
    try {
      const result = await api.parseNote(form.notes)
      setParsed(result)
      // Fill the form with the suggestion. Nothing is saved until the reviewer submits.
      setForm((f) => ({
        ...f,
        outcome: result.outcome,
        new_street: result.new_street ?? '',
        new_city: result.new_city ?? '',
        new_zip: result.new_zip ?? '',
        new_phone: result.new_phone ?? '',
        accepting: result.accepting_new_patients == null ? '' : result.accepting_new_patients ? 'yes' : 'no',
      }))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setParsing(false)
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault()
    setSaving(true)
    setError(null)
    const body: VerificationInput = {
      outcome: form.outcome,
      new_street: form.new_street || null,
      new_city: form.new_city || null,
      new_zip: form.new_zip || null,
      new_phone: form.new_phone || null,
      accepting_new_patients: form.accepting === '' ? null : form.accepting === 'yes',
      notes: form.notes || null,
      source: 'simulated', // this demo never calls real offices
    }
    try {
      await api.verify(npi, body)
      onVerified()
    } catch (e) {
      setError((e as Error).message)
      setSaving(false)
    }
  }

  const set = <K extends keyof typeof emptyForm>(key: K, value: (typeof emptyForm)[K]) =>
    setForm((f) => ({ ...f, [key]: value }))

  return (
    <div className="panel">
      <h2>
        {p.name} {p.credentials && <span className="muted">{p.credentials}</span>}
      </h2>
      <p className="muted">{p.specialty} · NPI {p.npi}</p>
      <p>{address(p)}</p>
      <p>
        <Badge confidence={p.confidence} />{' '}
        <span className="muted">
          {pct(p.p_stale)} chance out of date within a year · {num(p.medicare_patients)} Medicare patients
        </span>
      </p>
      {p.reasons.length > 0 && (
        <ul className="reasons">
          {p.reasons.map((r) => (
            <li key={r.code}>{r.text}</li>
          ))}
        </ul>
      )}

      <h3>Address history</h3>
      <table className="compact">
        <thead>
          <tr>
            <th>Year</th>
            <th>Address on file</th>
            <th className="n">Patients</th>
          </tr>
        </thead>
        <tbody>
          {history.map((h, i) => {
            const changed = i > 0 && (h.street1 !== history[i - 1].street1 || h.zip5 !== history[i - 1].zip5)
            return (
              <tr key={h.data_year} className={changed ? 'changed' : undefined}>
                <td>{h.data_year}</td>
                <td>
                  {[h.street1, h.city, h.zip5].filter(Boolean).join(', ')}
                  {changed && <span className="tag">changed</span>}
                </td>
                <td className="n">{num(h.medicare_patients)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>

      <h3>Record a check</h3>
      <form onSubmit={submit}>
        <label>
          Call notes
          <textarea
            rows={3}
            value={form.notes}
            onChange={(e) => set('notes', e.target.value)}
            placeholder="e.g. Front desk said Dr. Lee moved to 200 5th Ave in March, still taking new patients"
          />
        </label>
        <button type="button" className="secondary" onClick={parseNote} disabled={parsing || !form.notes.trim()}>
          {parsing ? 'Reading note…' : 'Fill form from notes'}
        </button>
        {parsed && (
          <p className={parsed.confidence === 'low' ? 'notice warn' : 'notice'}>
            Suggested from your note{parsed.confidence === 'low' && ' (low confidence, check carefully)'}: “
            {parsed.evidence}”. Review the fields below before saving.
          </p>
        )}

        <fieldset>
          <legend>Outcome</legend>
          {outcomes.map((o) => (
            <label key={o.value} className="radio">
              <input
                type="radio"
                name="outcome"
                checked={form.outcome === o.value}
                onChange={() => set('outcome', o.value)}
              />
              {o.label}
            </label>
          ))}
        </fieldset>

        {form.outcome === 'moved' && (
          <div className="grid">
            <label>
              New street
              <input value={form.new_street} onChange={(e) => set('new_street', e.target.value)} required />
            </label>
            <label>
              City
              <input value={form.new_city} onChange={(e) => set('new_city', e.target.value)} />
            </label>
            <label>
              ZIP
              <input value={form.new_zip} onChange={(e) => set('new_zip', e.target.value)} />
            </label>
            <label>
              Phone
              <input value={form.new_phone} onChange={(e) => set('new_phone', e.target.value)} />
            </label>
          </div>
        )}
        <label>
          Accepting new patients
          <select value={form.accepting} onChange={(e) => set('accepting', e.target.value as '' | 'yes' | 'no')}>
            <option value="">Not stated</option>
            <option value="yes">Yes</option>
            <option value="no">No</option>
          </select>
        </label>

        {error && <p className="error">{error}</p>}
        <button type="submit" disabled={saving}>
          {saving ? 'Saving…' : 'Save check'}
        </button>
        <p className="muted small">Checks in this demo are saved as simulated. No real office is contacted.</p>
      </form>

      {verifications.length > 0 && (
        <>
          <h3>Past checks</h3>
          <ul className="reasons">
            {verifications.map((v) => (
              <li key={v.id}>
                {new Date(v.created_at).toLocaleDateString()} · {v.outcome}
                {v.new_street && ` → ${[v.new_street, v.new_city, v.new_zip].filter(Boolean).join(', ')}`}
                <span className="muted"> ({v.source})</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}
