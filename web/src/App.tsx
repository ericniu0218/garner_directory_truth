import { useState } from 'react'
import { api } from './api'
import { useAsync } from './useAsync'
import { QueueView } from './QueueView'
import { SearchView } from './SearchView'
import { ModelView } from './ModelView'

type Tab = 'queue' | 'search' | 'model'

const tabs: { id: Tab; label: string }[] = [
  { id: 'queue', label: 'Review queue' },
  { id: 'search', label: 'Find a doctor' },
  { id: 'model', label: 'How well it works' },
]

export default function App() {
  const [tab, setTab] = useState<Tab>('queue')
  const specialties = useAsync(api.specialties, [])

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <h1>Directory Truth</h1>
          <p className="tagline">Which provider listings are probably out of date, and which to check first.</p>
        </div>
        <nav aria-label="Views">
          {tabs.map((t) => (
            <button
              key={t.id}
              className={t.id === tab ? 'tab active' : 'tab'}
              aria-current={t.id === tab ? 'page' : undefined}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </header>
      <main>
        {tab === 'queue' && <QueueView specialties={specialties.data ?? []} />}
        {tab === 'search' && <SearchView specialties={specialties.data ?? []} />}
        {tab === 'model' && <ModelView />}
      </main>
      <footer>
        Independent demo built on public CMS Medicare data (New York). Not affiliated with any company.
        Scores are estimates, not verified facts.
      </footer>
    </div>
  )
}
