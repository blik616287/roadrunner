import { useState, useMemo, useCallback } from 'react';

export default function useSort(items, storageKey, defaultKey = null, defaultDir = 'asc', nameKey = 'fileName') {
  const stored = storageKey ? JSON.parse(localStorage.getItem(`sort:${storageKey}`) || 'null') : null;

  const [sortKey, setSortKey] = useState(stored?.key ?? defaultKey);
  const [sortDir, setSortDir] = useState(stored?.dir ?? defaultDir);

  const persist = useCallback((key, dir) => {
    if (storageKey) {
      localStorage.setItem(`sort:${storageKey}`, JSON.stringify({ key, dir }));
    }
  }, [storageKey]);

  const toggle = (key) => {
    if (sortKey === key) {
      const next = sortDir === 'asc' ? 'desc' : 'asc';
      setSortDir(next);
      persist(key, next);
    } else {
      setSortKey(key);
      setSortDir('asc');
      persist(key, 'asc');
    }
  };

  const sorted = useMemo(() => {
    if (!sortKey) return items;
    return [...items].sort((a, b) => {
      let av = a[sortKey];
      let bv = b[sortKey];
      if (av == null) av = '';
      if (bv == null) bv = '';
      if (typeof av === 'string') av = av.toLowerCase();
      if (typeof bv === 'string') bv = bv.toLowerCase();
      if (av < bv) return sortDir === 'asc' ? -1 : 1;
      if (av > bv) return sortDir === 'asc' ? 1 : -1;
      // Tiebreaker: alphabetical by name
      const an = (a[nameKey] || '').toLowerCase();
      const bn = (b[nameKey] || '').toLowerCase();
      if (an < bn) return -1;
      if (an > bn) return 1;
      return 0;
    });
  }, [items, sortKey, sortDir, nameKey]);

  return { sorted, sortKey, sortDir, toggle };
}
