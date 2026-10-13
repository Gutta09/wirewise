export function OrganizationSwitcher({ organizations, value, onChange, disabled }) {
  return (
    <label className="switcher">
      <span className="switcher__label">Organization</span>
      <select
        value={value ?? ''}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled || organizations.length === 0}
      >
        {organizations.length === 0 ? <option value="">No organizations</option> : null}
        {organizations.map((organization) => (
          <option key={organization.slug} value={organization.slug}>
            {organization.name}
          </option>
        ))}
      </select>
    </label>
  )
}
