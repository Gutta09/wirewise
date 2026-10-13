import { useRef, useState } from 'react'
import { Card, ErrorState } from './Primitives'
import { label } from '../format'

export function ImportPanel({ onImport, organizationName }) {
  const inputRef = useRef(null)
  const [file, setFile] = useState(null)
  const [busy, setBusy] = useState(false)
  const [summary, setSummary] = useState(null)
  const [error, setError] = useState(null)

  async function handleSubmit(event) {
    event.preventDefault()
    if (!file || busy) return
    setBusy(true)
    setError(null)
    setSummary(null)
    try {
      setSummary(await onImport(file))
      setFile(null)
      if (inputRef.current) inputRef.current.value = ''
    } catch (caught) {
      setError(caught.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card
      title="Import a bank statement"
      subtitle={`CSV columns: date, description, amount, type, reference — imported into ${organizationName}.`}
    >
      <form className="upload" onSubmit={handleSubmit}>
        <input
          ref={inputRef}
          type="file"
          accept=".csv,text/csv"
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          disabled={busy}
        />
        <button type="submit" className="button" disabled={!file || busy}>
          {busy ? 'Importing…' : 'Upload statement'}
        </button>
      </form>

      {error ? <ErrorState error={error} /> : null}
      {summary ? <ImportSummary summary={summary} /> : null}
    </Card>
  )
}

function ImportSummary({ summary }) {
  const statuses = Object.entries(summary.status_counts ?? {})
  return (
    <div className="summary">
      <div className="summary__figures">
        <Figure value={summary.imported} caption="rows imported" tone="good" />
        <Figure value={summary.duplicates} caption="duplicates skipped" tone="warn" />
        <Figure value={summary.errors.length} caption="rows with errors" tone="bad" />
        <Figure value={summary.rows_read} caption="rows read" />
      </div>

      {statuses.length > 0 ? (
        <p className="summary__statuses">
          {statuses.map(([status, count]) => (
            <span key={status} className="chip">
              {count} {label(status).toLowerCase()}
            </span>
          ))}
        </p>
      ) : null}

      {summary.errors.length > 0 ? (
        <details open>
          <summary>{summary.errors.length} row error(s)</summary>
          <ul className="issues">
            {summary.errors.map((item, index) => (
              <li key={`${item.line}-${index}`}>
                <span className="issues__line">Line {item.line}</span> {item.message}
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      {summary.duplicate_rows.length > 0 ? (
        <details>
          <summary>{summary.duplicate_rows.length} duplicate row(s)</summary>
          <ul className="issues">
            {summary.duplicate_rows.map((item, index) => (
              <li key={`${item.line}-${index}`}>
                <span className="issues__line">Line {item.line}</span>{' '}
                <code>{item.bank_reference}</code> — {item.reason}
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      {summary.imported === 0 && summary.errors.length === 0 && summary.duplicates === 0 ? (
        <p className="state state--empty">The file had no rows to import.</p>
      ) : null}
    </div>
  )
}

function Figure({ value, caption, tone }) {
  return (
    <div className={`figure${tone ? ` figure--${tone}` : ''}`}>
      <strong>{value}</strong>
      <span>{caption}</span>
    </div>
  )
}
