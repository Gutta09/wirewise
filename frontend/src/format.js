const moneyFormatter = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

// Amounts arrive from the API as decimal strings. They are only ever turned into
// numbers here, for display.
export function money(value) {
  if (value === null || value === undefined || value === '') return '—'
  const amount = Number(value)
  if (Number.isNaN(amount)) return String(value)
  const formatted = moneyFormatter.format(Math.abs(amount))
  return amount < 0 ? `(${formatted})` : formatted
}

export function date(value) {
  if (!value) return '—'
  const [year, month, day] = value.split('-')
  return `${day}/${month}/${year}`
}

const LABELS = {
  suggested: 'Suggested',
  needs_review: 'Needs review',
  reconciled: 'Reconciled',
  ignored: 'Ignored',
  open: 'Open',
  partially_funded: 'Partially funded',
  funded: 'Funded',
  proposed: 'Proposed',
  approved: 'Approved',
  rejected: 'Rejected',
  not_synced: 'Not synced',
  synced: 'Synced',
  sync_failed: 'Sync failed',
}

export function label(value) {
  return LABELS[value] ?? value
}
