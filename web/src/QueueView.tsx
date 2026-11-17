import { useState } from 'react'
import { api } from './api'
import { address, num, pct } from './format'
import type { Specialty } from './types'
import { useAsync } from './useAsync'
import { ProviderPanel } from './ProviderPanel'

export function QueueView({ specialties }: { specialties: Specialty[] }) {
  const [specialty, setSpecialty] = useState('')
  const [sort, setSort] = useState('impact')
  const [selected, setSelected] = useState<string | null>(null)
  const [version, setVersion] = useState(0) // bump to reload after a verification
  const queue = useAsync(() => api.queue({ specialty, sort, limit: 50 }), [specialty, sort, version])

  return (
    <div className="split">
      <section className="list-pane">
        <div className="pane-head">
          <h2>Listings to verify next</h2>
          <p className="hint">
            Clinicians in the riskiest 30% of listings with no check in the last 180 days, ordered by
            how many patients a wrong listing would affect.
          </p>
          <div className="filters">
            <label>
              Specialty
              <select value={specialty} onChange={(e) => setSpecialty(e.target.value)}>
                <option value="">All specialties</option>
                {specialties.map((s) => (
                  <option key={s.specialty} value={s.specialty}>{s.specialty}</option>
                ))}
              </select>
            </label>
            <label>
              Order by
              <select value={sort} onChange={(e) => setSort(e.target.value)}>
                <option value="impact">Patients affected</option>
                <option value="risk">Chance it is out of date</option>
              </select>
            </label>
          </div>
        </div>

        {queue.error && <p className="error">Could not load the queue: {queue.error}</p>}
        {queue.loading && !queue.data && <p className="hint">Loading…</p>}
        {queue.data && queue.data.length === 0 && <p className="hint">Nothing to verify for this filter.</p>}
        {queue.data && queue.data.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Provider</th>
                <th className="n">Chance out of date</th>
                <th className="n">Medicare patients</th>
                <th>Why it is flagged</th>
              </tr>
            </thead>
            <tbody>
              {queue.data.map((p) => (
                <tr
                  key={p.npi}
                  className={p.npi === selected ? 'row selected' : 'row'}
                  onClick={() => setSelected(p.npi)}
                  tabIndex={0}
                  onKeyDown={(e) => e.key === 'Enter' && setSelected(p.npi)}
                >
                  <td>
                    <strong>{p.name}</strong>
                    {p.credentials && <span className="muted"> {p.credentials}</span>}
                    <div className="muted">{p.specialty}</div>
                    <div className="muted">{address(p)}</div>
                  </td>
                  <td className="n">{pct(p.p_stale)}</td>
                  <td className="n">{num(p.medicare_patients)}</td>
                  <td>
                    {p.reasons.length === 0 && <span className="muted">Combination of smaller signals</span>}
                    {p.reasons.map((r) => (
                      <div key={r.code}>{r.text}</div>
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      <aside className="detail-pane">
        {selected ? (
          <ProviderPanel
            key={selected}
            npi={selected}
            onVerified={() => {
              setVersion((v) => v + 1)
              setSelected(null)
            }}
          />
        ) : (
          <p className="hint">Select a listing to see its history and record a check.</p>
        )}
      </aside>
    </div>
  )
}
