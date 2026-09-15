export function collectChanges(before, after, prefix = '') {
  return Object.keys(after).filter(key => !['version', 'updatedAt'].includes(key)).flatMap(key => {
    const path = prefix ? `${prefix}.${key}` : key;
    if (JSON.stringify(before?.[key]) === JSON.stringify(after[key])) return [];
    if (after[key] && typeof after[key] === 'object' && !Array.isArray(after[key])) return collectChanges(before?.[key], after[key], path);
    return [{ key: path, before: before?.[key] ?? null, after: after[key] }];
  });
}
