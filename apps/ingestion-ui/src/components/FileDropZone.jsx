import { useState, useCallback } from 'react';

const ARCHIVE_EXTS = ['.tar.gz', '.tgz', '.zip'];

function isArchive(name) {
  return ARCHIVE_EXTS.some((ext) => name.toLowerCase().endsWith(ext));
}

/** Recursively read a dropped directory entry, returning [{file, path}]. */
function readEntry(entry, basePath = '') {
  return new Promise((resolve) => {
    if (entry.isFile) {
      entry.file((file) => {
        const path = basePath ? `${basePath}/${entry.name}` : entry.name;
        resolve([{ file, path }]);
      });
    } else if (entry.isDirectory) {
      const reader = entry.createReader();
      const all = [];
      const readBatch = () => {
        reader.readEntries((entries) => {
          if (!entries.length) {
            Promise.all(all).then((arrs) => resolve(arrs.flat()));
            return;
          }
          const dir = basePath ? `${basePath}/${entry.name}` : entry.name;
          for (const e of entries) all.push(readEntry(e, dir));
          readBatch();
        });
      };
      readBatch();
    } else {
      resolve([]);
    }
  });
}

/** Extract files with paths from a drop event. */
async function getDroppedFiles(dataTransfer) {
  const items = dataTransfer.items;
  if (!items) return [...dataTransfer.files].map((f) => ({ file: f, path: f.name }));

  const entries = [];
  for (let i = 0; i < items.length; i++) {
    const entry = items[i].webkitGetAsEntry?.();
    if (entry) entries.push(entry);
  }
  if (!entries.length) return [...dataTransfer.files].map((f) => ({ file: f, path: f.name }));

  const results = await Promise.all(entries.map((e) => readEntry(e)));
  return results.flat();
}

export default function FileDropZone({ onUpload, disabled }) {
  const [dragOver, setDragOver] = useState(false);

  const processFiles = useCallback(
    (fileList) => {
      if (!fileList.length || disabled) return;
      for (const { file, path } of fileList) {
        const type = isArchive(file.name) ? 'codebase' : 'document';
        onUpload(file, type, path);
      }
    },
    [onUpload, disabled]
  );

  const onDrop = async (e) => {
    e.preventDefault();
    setDragOver(false);
    const files = await getDroppedFiles(e.dataTransfer);
    processFiles(files);
  };

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
      onDragLeave={() => setDragOver(false)}
      onDrop={onDrop}
      className={`border-2 border-dashed rounded-lg p-10 text-center transition-colors ${
        dragOver ? 'border-blue-500 bg-blue-50' : 'border-gray-300 bg-white'
      } ${disabled ? 'opacity-50 pointer-events-none' : 'cursor-pointer'}`}
      onClick={() => {
        if (disabled) return;
        const input = document.createElement('input');
        input.type = 'file';
        input.multiple = true;
        input.onchange = (e) => {
          const files = [...e.target.files].map((f) => ({
            file: f,
            path: f.webkitRelativePath || f.name,
          }));
          processFiles(files);
        };
        input.click();
      }}
    >
      <div className="text-gray-500">
        <p className="text-lg font-medium">Drop files or folders here, or click to browse</p>
        <p className="text-sm mt-1">
          Documents: PDF, MD, TXT, RST, HTML &mdash; Archives: tar.gz, zip (codebase)
        </p>
      </div>
    </div>
  );
}
