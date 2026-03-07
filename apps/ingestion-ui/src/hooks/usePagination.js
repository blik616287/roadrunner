import { useState, useMemo } from 'react';

const PAGE_SIZE_OPTIONS = [10, 25, 50, 100];

export default function usePagination(items, storageKey) {
  const stored = storageKey ? JSON.parse(localStorage.getItem(`pageSize:${storageKey}`) || 'null') : null;
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(stored || 10);

  const totalPages = Math.max(1, Math.ceil(items.length / pageSize));
  const safePage = Math.min(page, totalPages - 1);

  const paged = useMemo(
    () => items.slice(safePage * pageSize, (safePage + 1) * pageSize),
    [items, safePage, pageSize],
  );

  const changePageSize = (size) => {
    setPageSize(size);
    setPage(0);
    if (storageKey) localStorage.setItem(`pageSize:${storageKey}`, String(size));
  };

  return {
    paged,
    page: safePage,
    pageSize,
    totalPages,
    totalItems: items.length,
    setPage,
    changePageSize,
    PAGE_SIZE_OPTIONS,
  };
}
