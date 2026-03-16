export default function Pagination({ page, totalPages, totalItems, pageSize, onPageChange, onPageSizeChange, pageSizeOptions }) {
  return (
    <div className="flex items-center justify-between pt-3 text-xs text-gray-500">
      <div className="flex items-center gap-2">
        <span>Show</span>
        <select
          value={pageSize}
          onChange={(e) => onPageSizeChange(Number(e.target.value))}
          className="border rounded px-1.5 py-1 text-xs bg-white"
        >
          {pageSizeOptions.map((n) => (
            <option key={n} value={n}>{n}</option>
          ))}
        </select>
        <span>of {totalItems}</span>
      </div>
      <div className="flex items-center gap-1">
        <button
          onClick={() => onPageChange(0)}
          disabled={page === 0}
          className="px-2 py-1 border rounded disabled:opacity-30 hover:bg-gray-50"
        >&laquo;</button>
        <button
          onClick={() => onPageChange(page - 1)}
          disabled={page === 0}
          className="px-2 py-1 border rounded disabled:opacity-30 hover:bg-gray-50"
        >&lsaquo;</button>
        <span className="px-2">{page + 1} / {totalPages}</span>
        <button
          onClick={() => onPageChange(page + 1)}
          disabled={page >= totalPages - 1}
          className="px-2 py-1 border rounded disabled:opacity-30 hover:bg-gray-50"
        >&rsaquo;</button>
        <button
          onClick={() => onPageChange(totalPages - 1)}
          disabled={page >= totalPages - 1}
          className="px-2 py-1 border rounded disabled:opacity-30 hover:bg-gray-50"
        >&raquo;</button>
      </div>
    </div>
  );
}
