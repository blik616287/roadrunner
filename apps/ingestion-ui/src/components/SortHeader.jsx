export default function SortHeader({ label, sortKey, currentKey, currentDir, onToggle, children }) {
  const active = currentKey === sortKey;
  const arrow = active ? (currentDir === 'asc' ? ' \u25B2' : ' \u25BC') : '';
  return (
    <th className="py-2 pr-3 font-medium select-none">
      <span className="cursor-pointer hover:text-gray-700" onClick={() => onToggle(sortKey)}>
        {label}{arrow}
      </span>
      {children}
    </th>
  );
}
