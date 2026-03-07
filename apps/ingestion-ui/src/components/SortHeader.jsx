export default function SortHeader({ label, sortKey, currentKey, currentDir, onToggle }) {
  const active = currentKey === sortKey;
  const arrow = active ? (currentDir === 'asc' ? ' \u25B2' : ' \u25BC') : '';
  return (
    <th
      className="py-2 pr-3 font-medium cursor-pointer select-none hover:text-gray-700"
      onClick={() => onToggle(sortKey)}
    >
      {label}{arrow}
    </th>
  );
}
