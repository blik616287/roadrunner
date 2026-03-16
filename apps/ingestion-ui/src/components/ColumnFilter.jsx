import { useState, useRef, useEffect } from 'react';

export default function ColumnFilter({ columnKey, value, options, onChange }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState(value || '');
  const ref = useRef(null);

  useEffect(() => { setText(value || ''); }, [value]);

  useEffect(() => {
    const handler = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const apply = (val) => {
    onChange(columnKey, val);
    setOpen(false);
  };

  return (
    <span className="relative inline-block ml-1" ref={ref}>
      <button
        onClick={(e) => { e.stopPropagation(); setOpen(!open); }}
        className={`text-xs ${value ? 'text-blue-600' : 'text-gray-400'} hover:text-blue-600`}
        title="Filter"
      >
        &#9660;
      </button>
      {open && (
        <div className="absolute top-full left-0 mt-1 bg-white border rounded shadow-lg z-50 min-w-[160px] p-2">
          <input
            type="text"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') apply(text); }}
            placeholder="Filter..."
            className="w-full text-xs border rounded px-2 py-1 mb-1"
            autoFocus
          />
          {options && options.length > 0 && (
            <div className="max-h-32 overflow-y-auto border-t mt-1 pt-1">
              {options.map((opt) => (
                <button
                  key={opt}
                  onClick={() => { setText(opt); apply(opt); }}
                  className={`block w-full text-left text-xs px-2 py-0.5 rounded hover:bg-blue-50 ${
                    value === opt ? 'bg-blue-100 font-medium' : ''
                  }`}
                >
                  {opt}
                </button>
              ))}
            </div>
          )}
          <div className="flex gap-1 mt-1 border-t pt-1">
            <button
              onClick={() => apply(text)}
              className="text-xs px-2 py-0.5 bg-blue-600 text-white rounded hover:bg-blue-700"
            >
              Apply
            </button>
            <button
              onClick={() => { setText(''); apply(''); }}
              className="text-xs px-2 py-0.5 bg-gray-200 rounded hover:bg-gray-300"
            >
              Clear
            </button>
          </div>
        </div>
      )}
    </span>
  );
}
