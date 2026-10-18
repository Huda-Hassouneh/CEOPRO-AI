export function MarketIntelligenceTable({ columns, rows, emptyState, className = '' }) {
  if (!rows?.length) return emptyState;
  return <div className={`market-main-table-wrap ${className}`.trim()}><table className="market-main-table"><thead><tr>{columns.map((column) => <th key={column.key}>{column.label}</th>)}</tr></thead><tbody>{rows.map((row) => <tr key={row.id}>{columns.map((column) => <td key={column.key} className={column.className || ''}>{column.render ? column.render(row) : row[column.key]}</td>)}</tr>)}</tbody></table></div>;
}
