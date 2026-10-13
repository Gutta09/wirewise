import { label } from '../format'

export function StatusPill({ status }) {
  return <span className={`pill pill--${status}`}>{label(status)}</span>
}

export function Spinner({ children = 'Loading…' }) {
  return (
    <p className="state state--loading" role="status">
      <span className="spinner" aria-hidden="true" />
      {children}
    </p>
  )
}

export function EmptyState({ children }) {
  return <p className="state state--empty">{children}</p>
}

export function ErrorState({ error, onRetry }) {
  return (
    <p className="state state--error" role="alert">
      <strong>Something went wrong.</strong> {error}
      {onRetry ? (
        <button type="button" className="button button--ghost" onClick={onRetry}>
          Try again
        </button>
      ) : null}
    </p>
  )
}

export function Card({ title, subtitle, actions, children }) {
  return (
    <section className="card">
      <header className="card__header">
        <div>
          <h2>{title}</h2>
          {subtitle ? <p className="card__subtitle">{subtitle}</p> : null}
        </div>
        {actions}
      </header>
      {children}
    </section>
  )
}
