// Parses the Markdown the language model writes into plain blocks
// (tables, lists, headings, paragraphs) for safe React rendering.
const TABLE_ROW = /^\s*\|.*\|\s*$/;
const TABLE_RULE = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;
const BULLET = /^\s*[-*•]\s+(.*)$/;
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/;
const HEADING = /^\s*#{1,6}\s+(.*)$/;
const cells = (line) => line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((cell) => cell.trim());

export function parseMarkdown(text) {
  const lines = String(text).split('\n');
  const blocks = [];
  for (let i = 0; i < lines.length;) {
    const line = lines[i];
    if (!line.trim()) { i += 1; continue; }
    if (TABLE_ROW.test(line) && i + 1 < lines.length && TABLE_RULE.test(lines[i + 1])) {
      const head = cells(line);
      const rows = [];
      i += 2;
      while (i < lines.length && TABLE_ROW.test(lines[i])) { rows.push(cells(lines[i])); i += 1; }
      blocks.push({ type: 'table', head, rows });
      continue;
    }
    const list = BULLET.test(line) ? BULLET : NUMBERED.test(line) ? NUMBERED : null;
    if (list) {
      const items = [];
      while (i < lines.length && list.test(lines[i])) { items.push(lines[i].match(list)[1]); i += 1; }
      blocks.push({ type: 'list', ordered: list === NUMBERED, items });
      continue;
    }
    const heading = line.match(HEADING);
    blocks.push(heading ? { type: 'heading', text: heading[1] } : { type: 'paragraph', text: line });
    i += 1;
  }
  return blocks;
}

