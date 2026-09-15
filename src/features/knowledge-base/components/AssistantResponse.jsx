function AnswerTable({ block }) {
  const columns = Array.isArray(block.columns) ? block.columns : [];
  const rows = Array.isArray(block.rows) ? block.rows : [];
  if (!columns.length) return null;
  return <div className="rag-answer-table-wrap"><table><thead><tr>{columns.map((column, index) => <th key={column.key || index}>{column.label || column}</th>)}</tr></thead><tbody>{rows.map((row, rowIndex) => <tr key={row.id || rowIndex}>{columns.map((column, columnIndex) => {
    const key = column.key || column;
    return <td key={`${key}-${columnIndex}`}>{Array.isArray(row) ? row[columnIndex] : row[key]}</td>;
  })}</tr>)}</tbody></table></div>;
}

function InlineContent({ segments, fallback }) {
  if (!Array.isArray(segments)) return fallback;
  return segments.map((segment, index) => segment.emphasis
    ? <strong key={segment.id || index}>{segment.text}</strong>
    : <span key={segment.id || index}>{segment.text}</span>);
}

function AnswerBlock({ block }) {
  if (typeof block === 'string') return <p>{block}</p>;
  if (!block || typeof block !== 'object') return null;
  if (block.type === 'table') return <AnswerTable block={block} />;
  if (block.type === 'list') {
    const List = block.ordered ? 'ol' : 'ul';
    return <List>{(block.items || []).map((item, index) => <li key={item.id || index}>{item.text || item}</li>)}</List>;
  }
  if (block.type === 'heading') return <h4>{block.text}</h4>;
  return <p><InlineContent segments={block.segments} fallback={block.text || block.content || ''} /></p>;
}

export function AssistantResponse({ content }) {
  if (typeof content === 'string') return <div className="rag-answer-copy">{content.split('\n').filter(Boolean).map((paragraph, index) => <p key={index}>{paragraph}</p>)}</div>;
  const blocks = Array.isArray(content) ? content : content?.blocks;
  if (!Array.isArray(blocks)) return null;
  return <div className="rag-answer-copy">{blocks.map((block, index) => <AnswerBlock block={block} key={block.id || index} />)}</div>;
}
