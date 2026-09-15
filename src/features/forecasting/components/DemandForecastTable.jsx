export function DemandForecastTable({ columns, rows, emptyState, className = '' }) {
  if (!rows?.length) return emptyState;
  return <div className={`demand-approved-table-wrap ${className}`.trim()}><table className="demand-approved-table"><thead><tr>{columns.map((column) => <th key={column.key}>{column.label}</th>)}</tr></thead><tbody>{rows.map((row) => <tr key={row.id}>{columns.map((column) => <td key={column.key}>{column.render ? column.render(row) : row[column.key]}</td>)}</tr>)}</tbody></table></div>;
}
