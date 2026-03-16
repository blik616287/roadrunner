import { useState, useMemo, useCallback } from 'react';

export default function useFilter(items, storageKey) {
  const stored = storageKey
    ? JSON.parse(localStorage.getItem(`filters:${storageKey}`) || '{}')
    : {};
  const [filters, setFilters] = useState(stored);

  const setFilter = useCallback((key, value) => {
    setFilters((prev) => {
      const next = { ...prev };
      if (value === '' || value == null) {
        delete next[key];
      } else {
        next[key] = value;
      }
      if (storageKey) localStorage.setItem(`filters:${storageKey}`, JSON.stringify(next));
      return next;
    });
  }, [storageKey]);

  const clearFilters = useCallback(() => {
    setFilters({});
    if (storageKey) localStorage.removeItem(`filters:${storageKey}`);
  }, [storageKey]);

  const filtered = useMemo(() => {
    const keys = Object.keys(filters);
    if (!keys.length) return items;
    return items.filter((item) =>
      keys.every((key) => {
        const filterVal = filters[key].toLowerCase();
        const itemVal = String(item[key] ?? '').toLowerCase();
        return itemVal.includes(filterVal);
      }),
    );
  }, [items, filters]);

  const activeCount = Object.keys(filters).length;

  return { filtered, filters, setFilter, clearFilters, activeCount };
}
