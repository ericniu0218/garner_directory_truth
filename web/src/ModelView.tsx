import { api } from './api'
import { num, pct } from './format'
import type { ModelMetrics } from './types'
import { useAsync } from './useAsync'

const modelNames: Record<string, string> = {
  gradient_boosting: 'Gradient boosting (served)',
  logistic_regression: 'Logistic regression',
  baseline_fewest_patients: 'Rule: fewest patients first',
  baseline_moved_recently: 'Rule: moved recently first',
}

function at(m: ModelMetrics, fraction: number) {
  return m.capture.find((c) => c.review_fraction === fraction)
}

/** Share of stale listings found (y) against share of listings reviewed (x). */
function CaptureChart({ models }: { models: Record<string, ModelMetrics> }) {
  const w = 520, h = 300, pad = 44
  const x = (v: number) => pad + v * (w - pad - 12)
  const y = (v: number) => h - pad - v * (h - pad - 12)
  const series = [
    { key: 'gradient_boosting', cls: 'line-model', label: 'Model' },
    { key: 'baseline_fewest_patients', cls: 'line-rule', label: 'Rule: fewest patients' },
  ]
  const path = (m: ModelMetrics) =>
    [[0, 0], ...m.capture.map((c) => [c.review_fraction, c.recall])]
      .map(([px, py], i) => `${i ? 'L' : 'M'}${x(px)},${y(py)}`)
      .join(' ')
  return (
    <svg viewBox={`0 0 ${w} ${h}`} role="img" aria-label="Share of stale listings found by share reviewed">
      {[0, 0.25, 0.5, 0.75, 1].map((t) => (
        <g key={t}>
          <line className="grid-line" x1={x(0)} x2={x(0.5)} y1={y(t)} y2={y(t)} />
          <text className="axis" x={x(0) - 8} y={y(t) + 4} textAnchor="end">{pct(t)}</text>
        </g>
      ))}
      {[0, 0.1, 0.2, 0.3, 0.4, 0.5].map((t) => (
        <text key={t} className="axis" x={x(t)} y={h - pad + 18} textAnchor="middle">{pct(t)}</text>
      ))}
      <line className="line-random" x1={x(0)} y1={y(0)} x2={x(0.5)} y2={y(0.5)} />
      {series.map((s) => models[s.key] && <path key={s.key} className={s.cls} d={path(models[s.key])} />)}
      <text className="axis" x={(x(0) + x(0.5)) / 2} y={h - 6} textAnchor="middle">Share of listings reviewed</text>
      <text className="axis" x={x(0.5) + 6} y={y(0.5) + 4}>Random</text>
      {series.map((s) => {
        const last = models[s.key] && at(models[s.key], 0.5)
        return last && (
          <text key={s.key} className={`axis ${s.cls}-label`} x={x(0.5) + 6} y={y(last.recall) + (s.key === 'gradient_boosting' ? -2 : 12)}>
            {s.label}
          </text>
        )
      })}
    </svg>
  )
}

export function ModelView() {
  const res = useAsync(api.metrics, [])
  if (res.error) return <p className="error">Could not load model results: {res.error}</p>
  if (!res.data) return <p className="hint">Loading…</p>
  const m = res.data.metrics
  const stale = m.targets.stale.models
  const moved = m.targets.moved.models
  const served = stale.gradient_boosting
  const top10 = at(served, 0.1)!
  const rule10 = at(stale.baseline_fewest_patients, 0.1)!
  const robust = served.patients_50_plus
  const robust10 = robust && robust.capture.find((c) => c.review_fraction === 0.1)
  const weighted = served.patient_weighted_capture?.find((c) => c.review_fraction === 0.1)

  return (
    <section className="narrow">
      <h2>How well it works</h2>
      <p>
        Backtest on {m.states.join(', ')} providers. The model was trained on {m.train_years[0]}–
        {m.train_years[m.train_years.length - 1]} and tested on {m.test_years.join(' and ')}, years it never
        saw. “Stale” means that a year later the provider’s address had changed or the provider no longer
        appeared in Medicare billing data.
      </p>

      <div className="stats">
        <div className="stat">
          <div className="stat-value">{pct(top10.precision)}</div>
          <div className="stat-label">of the model’s top 10% went stale, against {pct(served.base_rate)} overall</div>
        </div>
        <div className="stat">
          <div className="stat-value">{top10.lift.toFixed(1)}×</div>
          <div className="stat-label">better than random review ({rule10.lift.toFixed(1)}× for the best simple rule)</div>
        </div>
        <div className="stat">
          <div className="stat-value">{pct(top10.recall)}</div>
          <div className="stat-label">of all stale listings found by reviewing 10%</div>
        </div>
      </div>

      <h3>Stale listings found as more are reviewed</h3>
      <div className="chart">
        <CaptureChart models={stale} />
      </div>

      <h3>Comparison (reviewing the top 10%)</h3>
      <table>
        <thead>
          <tr>
            <th>Approach</th>
            <th className="n">Stale: precision</th>
            <th className="n">Stale: lift</th>
            <th className="n">Moved only: lift</th>
          </tr>
        </thead>
        <tbody>
          {Object.keys(modelNames).map((key) => (
            <tr key={key}>
              <td>{modelNames[key]}</td>
              <td className="n">{pct(at(stale[key], 0.1)?.precision, 1)}</td>
              <td className="n">{at(stale[key], 0.1)?.lift.toFixed(2)}×</td>
              <td className="n">{at(moved[key], 0.1)?.lift.toFixed(2)}×</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>Is the predicted chance accurate?</h3>
      <table className="compact">
        <thead>
          <tr>
            <th>Risk group</th>
            <th className="n">Predicted</th>
            <th className="n">Actually went stale</th>
            <th className="n">Listings</th>
          </tr>
        </thead>
        <tbody>
          {served.calibration?.map((c, i) => (
            <tr key={i}>
              <td>{i + 1} of {served.calibration!.length}</td>
              <td className="n">{pct(c.predicted, 1)}</td>
              <td className="n">{pct(c.observed, 1)}</td>
              <td className="n">{num(c.n)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>What this does not show</h3>
      <ul className="reasons">
        <li>
          The label is a proxy. “Not in next year’s billing data” includes providers who simply saw fewer
          than 11 Medicare patients. {robust && robust10 && (
            <>Among providers with 50 or more patients the model is weaker: {robust10.lift.toFixed(1)}× better
            than random, on a {pct(robust.base_rate, 1)} base rate.</>
          )}
        </li>
        <li>
          Predicting a change of address alone is hard from public data: {at(moved.gradient_boosting, 0.1)?.lift.toFixed(1)}×
          better than random. Claims data may carry stronger signals; this project has no way to test that.
        </li>
        {weighted && (
          <li>
            Ordering the queue by patients affected finds {pct(weighted.share_of_affected_patients)} of
            affected patients in the first 10% of calls. Simply calling the busiest providers first finds{' '}
            {pct(weighted.volume_only_baseline)}, so most of that comes from patient volume, not the model.
          </li>
        )}
        <li>Addresses come from a federal registry that providers update themselves, so it can lag reality.</li>
      </ul>
      <p className="muted small">Model run {res.data.model_version}</p>
    </section>
  )
}
