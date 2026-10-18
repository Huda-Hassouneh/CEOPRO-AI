import { useI18n } from '../../../app/providers/I18nProvider.jsx';

export default function Table({ 
  columns = [],
  data = [],
  className = '',
  ariaLabel,
  emptyMessage,
  ...props
}) {
  const { t } = useI18n();
  const empty = emptyMessage || t('common.noData');
  const label = ariaLabel || t('common.dataTable');
  const tableStyle = {
    width: '100%',
    borderCollapse: 'collapse',
    textAlign: 'start',
    fontFamily: 'var(--ceopro-font-family)',
    fontSize: '14px',
  };

  const thStyle = {
    padding: 'var(--ceopro-space-3) var(--ceopro-space-4)',
    backgroundColor: 'var(--ceopro-surface-soft)',
    color: 'var(--ceopro-text-secondary)',
    fontWeight: '600',
    borderBottom: '1px solid var(--ceopro-border)',
    fontSize: '12px',
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
  };

  const tdStyle = {
    padding: 'var(--ceopro-space-4)',
    borderBottom: '1px solid var(--ceopro-border-soft)',
    color: 'var(--ceopro-text-primary)',
  };

  return (
    // Focusable so keyboard users can scroll a table that is wider than the screen.
    <div tabIndex={0} role="region" aria-label={label} style={{ width: '100%', overflowX: 'auto', background: 'var(--ceopro-surface)', borderRadius: 'var(--ceopro-radius-md)', border: '1px solid var(--ceopro-border)' }}>
      <table className={`ceopro-table ${className}`.trim()} style={tableStyle} aria-label={label} {...props}>
        <thead>
          <tr>
            {columns.map((col, index) => (
              <th key={index} scope="col" style={thStyle}>{col.header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.length > 0 ? (
            data.map((row, rowIndex) => (
              <tr
                key={rowIndex}
                onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'var(--ceopro-surface-soft)'}
                onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'transparent'}
                style={{ transition: 'background-color 150ms ease' }}
              >
                {columns.map((col, colIndex) => (
                  <td key={colIndex} style={tdStyle}>
                    {col.render ? col.render(row) : row[col.accessor]}
                  </td>
                ))}
              </tr>
            ))
          ) : (
            <tr>
              <td colSpan={columns.length} role="status" aria-label={empty} style={{ textAlign: 'center', padding: 'var(--ceopro-space-6)', color: 'var(--ceopro-text-muted)' }}>
                {empty}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}