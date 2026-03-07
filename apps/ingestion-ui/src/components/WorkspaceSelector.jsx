import { useWorkspace } from '../hooks/useWorkspaceContext';
import { useWorkspaces } from '../hooks/useWorkspaces';

export default function WorkspaceSelector() {
  const { workspace, switchWorkspace } = useWorkspace();
  const { workspaces } = useWorkspaces();

  const names = workspaces.map((w) => w.name);
  if (!names.includes(workspace)) names.push(workspace);

  return (
    <div className="flex items-center gap-3">
      <label className="text-sm font-medium text-gray-500 whitespace-nowrap">Workspace</label>
      <select
        value={workspace}
        onChange={(e) => switchWorkspace(e.target.value)}
        className="bg-white text-gray-900 text-sm rounded px-3 py-1.5 border border-gray-300 focus:border-blue-500 focus:outline-none min-w-[180px]"
      >
        {names.map((n) => (
          <option key={n} value={n}>{n}</option>
        ))}
      </select>
    </div>
  );
}
