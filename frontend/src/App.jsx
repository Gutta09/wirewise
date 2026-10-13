import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import { ImportPanel } from './components/ImportPanel'
import { LineItemPanel } from './components/LineItemPanel'
import { OrganizationSwitcher } from './components/OrganizationSwitcher'
import { ErrorState, Spinner } from './components/Primitives'
import { TransactionTable } from './components/TransactionTable'

const STORED_ORGANIZATION = 'wirewise.organization'

export default function App() {
  const [organizations, setOrganizations] = useState([])
  const [organization, setOrganization] = useState(
    () => window.localStorage.getItem(STORED_ORGANIZATION) ?? null,
  )
  const [bootError, setBootError] = useState(null)
  const [booting, setBooting] = useState(true)

  const [transactions, setTransactions] = useState([])
  const [lineItems, setLineItems] = useState([])
  const [dataLoading, setDataLoading] = useState(false)
  const [dataError, setDataError] = useState(null)

  const [pendingAction, setPendingAction] = useState(null)
  const [actionError, setActionError] = useState(null)
  const [filter, setFilter] = useState('all')

  const loadOrganizations = useCallback(async () => {
    setBooting(true)
    setBootError(null)
    try {
      const found = await api.organizations()
      setOrganizations(found)
      setOrganization((current) =>
        current && found.some((item) => item.slug === current) ? current : found[0]?.slug ?? null,
      )
    } catch (caught) {
      setBootError(caught.message)
    } finally {
      setBooting(false)
    }
  }, [])

  const loadData = useCallback(async (slug) => {
    if (!slug) return
    setDataLoading(true)
    setDataError(null)
    try {
      const [nextTransactions, nextLineItems] = await Promise.all([
        api.transactions(slug),
        api.lineItems(slug),
      ])
      setTransactions(nextTransactions)
      setLineItems(nextLineItems)
    } catch (caught) {
      setDataError(caught.message)
      setTransactions([])
      setLineItems([])
    } finally {
      setDataLoading(false)
    }
  }, [])

  useEffect(() => {
    loadOrganizations()
  }, [loadOrganizations])

  useEffect(() => {
    if (!organization) return
    window.localStorage.setItem(STORED_ORGANIZATION, organization)
    setActionError(null)
    loadData(organization)
  }, [organization, loadData])

  /** Every action refreshes both tables, so the UI never shows stale amounts. */
  async function runAction(key, work) {
    if (pendingAction) return
    setPendingAction(key)
    setActionError(null)
    try {
      await work()
    } catch (caught) {
      setActionError(caught.message)
    } finally {
      setPendingAction(null)
      await loadData(organization)
    }
  }

  // Only a slug confirmed against the loaded list counts as a usable organization:
  // a slug remembered from localStorage must not put the upload form on screen
  // before we know the organization still exists.
  const current = organizations.find((item) => item.slug === organization)

  return (
    <div className="app">
      <header className="masthead">
        <div className="masthead__brand">
          <span className="logo" aria-hidden="true">
            ⇄
          </span>
          <div>
            <h1>Wirewise</h1>
            <p>Capital call reconciliation for fund administrators</p>
          </div>
        </div>
        <OrganizationSwitcher
          organizations={organizations}
          value={organization}
          onChange={setOrganization}
          disabled={booting || Boolean(pendingAction)}
        />
      </header>

      <main>
        {booting ? <Spinner>Loading organizations…</Spinner> : null}
        {bootError ? <ErrorState error={bootError} onRetry={loadOrganizations} /> : null}

        {!booting && !bootError && organizations.length === 0 ? (
          <p className="state state--empty">
            No organizations found. Run <code>python manage.py seed_demo</code> and reload.
          </p>
        ) : null}

        {current ? (
          <>
            <ImportPanel
              organizationName={current.name}
              onImport={async (file) => {
                const summary = await api.importStatement(organization, file)
                await loadData(organization)
                return summary
              }}
            />

            {actionError ? <ErrorState error={actionError} /> : null}

            <TransactionTable
              transactions={transactions}
              loading={dataLoading}
              error={dataError}
              onRetry={() => loadData(organization)}
              pendingAction={pendingAction}
              filter={filter}
              onFilterChange={setFilter}
              onApprove={(matchId) =>
                runAction(`approve:${matchId}`, () => api.approveMatch(organization, matchId))
              }
              onReject={(matchId) =>
                runAction(`reject:${matchId}`, () => api.rejectMatch(organization, matchId))
              }
              onIgnore={(transactionId) =>
                runAction(`ignore:${transactionId}`, () =>
                  api.ignoreTransaction(organization, transactionId),
                )
              }
            />

            <LineItemPanel
              lineItems={lineItems}
              loading={dataLoading}
              error={dataError}
              onRetry={() => loadData(organization)}
            />
          </>
        ) : null}
      </main>

      <footer className="footer">
        Viewing <strong>{current?.name ?? '—'}</strong>. Every request is scoped with the{' '}
        <code>X-Organization</code> header.
      </footer>
    </div>
  )
}
