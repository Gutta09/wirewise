import { Card, EmptyState, ErrorState, Spinner, StatusPill } from './Primitives'
import { money } from '../format'

export function LineItemPanel({ lineItems, loading, error, onRetry }) {
  const totals = lineItems.reduce(
    (accumulator, item) => ({
      called: accumulator.called + Number(item.amount_called),
      funded: accumulator.funded + Number(item.amount_funded),
      remaining: accumulator.remaining + Number(item.amount_remaining),
    }),
    { called: 0, funded: 0, remaining: 0 },
  )

  return (
    <Card title="Capital call line items" subtitle="One LP's share of one capital call.">
      {loading ? <Spinner>Loading line items…</Spinner> : null}
      {error ? <ErrorState error={error} onRetry={onRetry} /> : null}
      {!loading && !error && lineItems.length === 0 ? (
        <EmptyState>No line items yet. Run <code>python manage.py seed_demo</code>.</EmptyState>
      ) : null}

      {!loading && !error && lineItems.length > 0 ? (
        <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th>Call</th>
                <th>Investor entity</th>
                <th>Reference</th>
                <th className="numeric">Called</th>
                <th className="numeric">Funded</th>
                <th className="numeric">Remaining</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {lineItems.map((item) => (
                <tr key={item.id}>
                  <td>
                    <span className="muted">#{item.capital_call.sequence}</span>
                    <span className="block muted small">due {item.capital_call.due_date}</span>
                  </td>
                  <td>{item.investor_entity.name}</td>
                  <td>
                    <code>{item.expected_wire_reference}</code>
                  </td>
                  <td className="numeric">{money(item.amount_called)}</td>
                  <td className="numeric">{money(item.amount_funded)}</td>
                  <td className="numeric strong">{money(item.amount_remaining)}</td>
                  <td>
                    <StatusPill status={item.status} />
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td colSpan={3}>{lineItems.length} line items</td>
                <td className="numeric">{money(totals.called)}</td>
                <td className="numeric">{money(totals.funded)}</td>
                <td className="numeric strong">{money(totals.remaining)}</td>
                <td />
              </tr>
            </tfoot>
          </table>
        </div>
      ) : null}
    </Card>
  )
}
