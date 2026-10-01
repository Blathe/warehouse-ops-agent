import { useEffect, useState } from 'react'

import { Chat } from '@/components/chat/Chat'
import { ModelPicker } from '@/components/ModelPicker'
import { Input } from '@/components/ui/input'
import { getModels, type ModelOption } from '@/lib/api'

const NAME_KEY = 'warehouse-ops.supervisor'
const MODEL_KEY = 'warehouse-ops.model'

// Browser storage can be unavailable (private mode, blocked site data), so never let it throw.
function load(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function save(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    // Not remembered between visits, which is fine.
  }
}

export default function App() {
  const [supervisor, setSupervisor] = useState(() => load(NAME_KEY) || 'Supervisor')
  const [models, setModels] = useState<ModelOption[]>([])
  const [model, setModel] = useState<string | null>(null)

  // useEffect runs after the first render; the empty [] means "only once", like an
  // OnInitializedAsync in Blazor. It loads the model list from the backend.
  useEffect(() => {
    getModels()
      .then(({ default: fallback, models }) => {
        setModels(models)
        const saved = load(MODEL_KEY)
        setModel(models.some((m) => m.id === saved) ? saved : fallback)
      })
      .catch(() => {
        // Backend not reachable yet: hide the picker and let the backend pick its default.
      })
  }, [])

  function changeModel(id: string) {
    setModel(id)
    save(MODEL_KEY, id)
  }

  const labels = Object.fromEntries(models.map((m) => [m.id, m.label]))

  return (
    <div className="flex h-dvh flex-col bg-background text-foreground">
      <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b px-4 py-3">
        <div>
          <h1 className="text-base font-semibold">Warehouse Ops Agent</h1>
          <p className="text-xs text-muted-foreground">Short picks and replenishment</p>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
          {model && models.length > 0 && (
            <ModelPicker models={models} value={model} onChange={changeModel} />
          )}
          <label className="flex items-center gap-2">
            Approving as
            <Input
              aria-label="Supervisor name"
              value={supervisor}
              onChange={(event) => setSupervisor(event.target.value)}
              onBlur={() => save(NAME_KEY, supervisor.trim() || 'Supervisor')}
              className="h-8 w-36"
            />
          </label>
        </div>
      </header>
      <Chat supervisor={supervisor.trim() || 'Supervisor'} model={model} modelLabels={labels} />
    </div>
  )
}
