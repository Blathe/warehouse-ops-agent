import { useState } from 'react'

import { Chat } from '@/components/chat/Chat'
import { Input } from '@/components/ui/input'

const NAME_KEY = 'warehouse-ops.supervisor'

// Browser storage can be unavailable (private mode, blocked site data), so never let it throw.
function loadName(): string {
  try {
    return localStorage.getItem(NAME_KEY) || 'Supervisor'
  } catch {
    return 'Supervisor'
  }
}

function saveName(name: string) {
  try {
    localStorage.setItem(NAME_KEY, name)
  } catch {
    // Not remembered between visits, which is fine.
  }
}

export default function App() {
  const [supervisor, setSupervisor] = useState(loadName)

  return (
    <div className="flex h-dvh flex-col bg-background text-foreground">
      <header className="flex items-center justify-between gap-4 border-b px-4 py-3">
        <div>
          <h1 className="text-base font-semibold">Warehouse Ops Agent</h1>
          <p className="text-xs text-muted-foreground">Short picks and replenishment</p>
        </div>
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          Approving as
          <Input
            aria-label="Supervisor name"
            value={supervisor}
            onChange={(event) => setSupervisor(event.target.value)}
            onBlur={() => saveName(supervisor.trim() || 'Supervisor')}
            className="h-8 w-36"
          />
        </label>
      </header>
      <Chat supervisor={supervisor.trim() || 'Supervisor'} />
    </div>
  )
}
