import { useEffect, useState } from 'react'

export interface AsyncState<T> {
  data: T | null
  error: string | null
  loading: boolean
}

/** Run an async loader whenever deps change. Ignores results from stale runs. */
export function useAsync<T>(load: () => Promise<T>, deps: unknown[]): AsyncState<T> {
  const [state, setState] = useState<AsyncState<T>>({ data: null, error: null, loading: true })
  useEffect(() => {
    let current = true
    setState((s) => ({ ...s, loading: true, error: null }))
    load()
      .then((data) => current && setState({ data, error: null, loading: false }))
      .catch((e: Error) => current && setState({ data: null, error: e.message, loading: false }))
    return () => {
      current = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return state
}
