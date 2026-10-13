import { Card, EmptyState, ErrorState, Spinner, StatusPill } from './Primitives'
import { date, money } from '../format'

const FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'suggested', label: 'Suggested' },
  { key: 'needs_review', label: 'Needs review' },
  { key: 'reconciled', label: 'Reconciled' },
  { key: 'ignored', label: 'Ignored' },
]

export function TransactionTable({
  transactions,
  loading,
  error,
  onRetry,
  onApprove,
  onReject,
  onIgnore,
  pendingAction,
  filter,
  onFilterChange,
}) {
  const visible =
    filter === 'all' ? transactions : transactions.filter((item) => item.status === filter)

  const counts = transactions.reduce((accumulator, item) => {
    accumulator[item.status] = (accumulator[item.status] ?? 0) + 1
    return accumulator
  }, {})

  return (
    <Card
      title="Bank transactions"
      subtitle="Newest first. Approving a suggestion funds its line item."
      actions={
        <div className="filters" role="group" aria-label="Filter transactions">
          {FILTERS.map((option) => (
            <button
              key={option.key}
              type="button"
              className={`filter${filter === option.key ? ' filter--active' : ''}`}
              onClick={() => onFilterChange(option.key)}
            >
              {option.label}
              <span className="filter__count">
                {option.key === 'all' ? transactions.length : counts[option.key] ?? 0}
              </span>
            </button>
          ))}
        </div>
      }
    >
      {loading ? <Spinner>Loading transactions…</Spinner> : null}
      {error ? <ErrorState error={error} onRetry={onRetry} /> : null}
      {!loading && !error && transactions.length === 0 ? (
        <EmptyState>No transactions yet. Import a bank statement CSV above.</EmptyState>
      ) : null}
      {!loading && !error && transactions.length > 0 && visible.length === 0 ? (
        <EmptyState>No transactions with this status.</EmptyState>
      ) : null}

      {visible.length > 0 ? (
        <div className="table-scroll">
          <table className="table table--transactions">
            <thead>
              <tr>
                <th>Date</th>
                <th>Description</th>
                <th className="numeric">Amount</th>
                <th>Status</th>
                <th>Suggested line item</th>
                <th>Why</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((transaction) => (
                <TransactionRow
                  key={transaction.id}
                  transaction={transaction}
                  onApprove={onApprove}
                  onReject={onReject}
                  onIgnore={onIgnore}
                  pendingAction={pendingAction}
                />
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </Card>
  )
}

function TransactionRow({ transaction, onApprove, onReject, onIgnore, pendingAction }) {
  const live = transaction.matches.filter((match) => match.status !== 'rejected')
  const matches = live.length > 0 ? live : transaction.matches
  const canIgnore = transaction.available_actions.includes('ignore')
  const ignoreKey = `ignore:${transaction.id}`

  return (
    <tr>
      <td className="nowrap">{date(transaction.date)}</td>
      <td className="description">
        {transaction.description}
        <span className="block muted small">
          <code>{transaction.bank_reference}</code> · line {transaction.source_line_number}
        </span>
      </td>
      <td className={`numeric ${transaction.type === 'debit' ? 'negative' : ''}`}>
        {money(transaction.amount)}
        <span className="block muted small">{transaction.type}</span>
      </td>
      <td>
        <StatusPill status={transaction.status} />
      </td>
      <td>
        {matches.length === 0 ? (
          <span className="muted">—</span>
        ) : (
          matches.map((match) => (
            <div key={match.id} className="suggestion">
              <strong>{match.line_item.investor_name}</strong>
              <span className="block">
                <code>{match.line_item.expected_wire_reference}</code>{' '}
                <span className="muted small">
                  remaining {money(match.line_item.amount_remaining)}
                </span>
              </span>
              {match.status !== 'proposed' ? (
                <span className="block">
                  <StatusPill status={match.status} />
                </span>
              ) : null}
            </div>
          ))
        )}
      </td>
      <td className="reason">
        {matches.map((match) => (
          <p key={match.id}>{match.reason}</p>
        ))}
        {/* The transaction-level reason only adds something when it is not already
            spelled out by a match (no match at all, a debit, or an approval note). */}
        {transaction.status_reason &&
        !matches.some((match) => match.reason === transaction.status_reason) ? (
          <p className="muted">{transaction.status_reason}</p>
        ) : null}
      </td>
      <td className="actions">
        {matches
          .filter((match) => match.status === 'proposed')
          .map((match) => {
            const approveKey = `approve:${match.id}`
            const rejectKey = `reject:${match.id}`
            return (
              <div key={match.id} className="actions__group">
                <button
                  type="button"
                  className="button button--small"
                  disabled={Boolean(pendingAction)}
                  onClick={() => onApprove(match.id)}
                >
                  {pendingAction === approveKey ? 'Approving…' : 'Approve'}
                </button>
                <button
                  type="button"
                  className="button button--small button--ghost"
                  disabled={Boolean(pendingAction)}
                  onClick={() => onReject(match.id)}
                >
                  {pendingAction === rejectKey ? 'Rejecting…' : 'Reject'}
                </button>
              </div>
            )
          })}
        {canIgnore ? (
          <button
            type="button"
            className="button button--small button--ghost"
            disabled={Boolean(pendingAction)}
            onClick={() => onIgnore(transaction.id)}
          >
            {pendingAction === ignoreKey ? 'Ignoring…' : 'Ignore'}
          </button>
        ) : null}
        {!canIgnore && matches.every((match) => match.status !== 'proposed') ? (
          <span className="muted small">No actions</span>
        ) : null}
      </td>
    </tr>
  )
}
