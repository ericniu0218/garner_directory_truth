import { useState, type FormEvent } from 'react'
import { api } from './api'
import { Badge } from './Badge'
import { address } from './format'
import type { Provider, Specialty } from './types'

export function SearchView({ specialties }: { specialties: Specialty[] }) {
  const [zip, setZip] = useState('10016')
  const [specialty, setSpecialty] = useState('Cardiology')
  const [results, setResults] = useState<Provider[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function search(e: FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      setResults(await api.search({ zip, specialty, limit: 30 }))
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="narrow">
      <h2>Find a doctor</h2>
      <p className="hint">
        What a member would see: each listing says how much to trust the address before making the trip.
      </p>
      <form className="filters" onSubmit={search}>
        <label>
          ZIP code (or first digits)
          <input value={zip} onChange={(e) => setZip(e.target.value)} inputMode="numeric" maxLength={5} />
        </label>
        <label>
          Specialty
          <select value={specialty} onChange={(e) => setSpecialty(e.target.value)}>
            <option value="">Any</option>
            {specialties.map((s) => (
              <option key={s.specialty} value={s.specialty}>{s.specialty}</option>
            ))}
          </select>
        </label>
        <button type="submit" disabled={loading}>{loading ? 'Searching…' : 'Search'}</button>
      </form>

      {error && <p className="error">Search failed: {error}</p>}
      {results && results.length === 0 && <p className="hint">No providers match. Try fewer ZIP digits.</p>}
      {results && results.length > 0 && (
        <ul className="cards">
          {results.map((p) => (
            <li key={p.npi} className="card">
              <div>
                <strong>{p.name}</strong>
                {p.credentials && <span className="muted"> {p.credentials}</span>}
                <div className="muted">{p.specialty}</div>
                {p.last_outcome === 'moved' && p.corrected_street ? (
                  <>
                    <div>{[p.corrected_street, p.corrected_city, p.corrected_zip].filter(Boolean).join(', ')}</div>
                    <div className="muted small">Previously listed at {address(p)}</div>
                  </>
                ) : (
                  <div>{address(p)}</div>
                )}
              </div>
              <div className="card-side">
                <Badge confidence={p.confidence} />
                <div className="muted small">
                  {p.last_verified_at
                    ? `Checked ${new Date(p.last_verified_at).toLocaleDateString()}`
                    : p.reasons[0]?.text ?? 'Not yet checked by a person'}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
