import { useEffect, useState } from 'react'

import { ActivityFeed } from '@/components/activity/ActivityFeed'
import { activityFromTurn, locationsInTurn, type ActivityItem } from '@/components/activity/activity'
import { Chat } from '@/components/chat/Chat'
import { FloorMap } from '@/components/floor/FloorMap'
import { ModelPicker } from '@/components/ModelPicker'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { getModels, type AgentTurn, type ModelOption } from '@/lib/api'
import { cn } from '@/lib/utils'

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
  const [view, setView] = useState<'chat' | 'map'>('chat') // only used on narrow screens
  const [activity, setActivity] = useState<ActivityItem[]>([])
  const [highlight, setHighlight] = useState<string[]>([])
  const [selectedBay, setSelectedBay] = useState<string | null>(null)
  const [mapVersion, setMapVersion] = useState(0)

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

  // Called by the chat after every agent response: log what it did, point the map at
  // the bays involved (the move's destination first) and reload the map's stock.
  function handleTurn(turn: AgentTurn) {
    setActivity((current) => [...current, ...activityFromTurn(turn)])
    const locations = locationsInTurn(turn)
    setHighlight(locations)
    if (locations.length > 0) setSelectedBay(locations[0])
    setMapVersion((version) => version + 1)
  }

  const labels = Object.fromEntries(models.map((m) => [m.id, m.label]))

  return (
    <div className="flex h-dvh flex-col bg-background text-foreground">
      <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b px-4 py-3">
        <div>
          <h1 className="text-base font-semibold">Warehouse Ops Agent</h1>
          <p className="text-xs text-muted-foreground">Short picks and replenishment</p>
        </div>
        <nav className="flex gap-1 lg:hidden" aria-label="View">
          {(['chat', 'map'] as const).map((v) => (
            <Button
              key={v}
              size="sm"
              variant={view === v ? 'secondary' : 'ghost'}
              aria-pressed={view === v}
              onClick={() => setView(v)}
            >
              {v === 'chat' ? 'Chat' : 'Floor map'}
            </Button>
          ))}
        </nav>
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
      {/* Wide screens: chat on the left, map and activity on the right. Narrow screens
          show one at a time; both stay mounted so switching loses nothing. */}
      <main className="flex min-h-0 flex-1">
        <section
          aria-label="Chat"
          className={cn(
            'min-h-0 flex-col lg:flex lg:w-[440px] lg:shrink-0 lg:border-r xl:w-[480px]',
            view === 'chat' ? 'flex flex-1 lg:flex-none' : 'hidden',
          )}
        >
          <Chat
            supervisor={supervisor.trim() || 'Supervisor'}
            model={model}
            modelLabels={labels}
            onTurn={handleTurn}
          />
        </section>
        <aside
          className={cn(
            'min-h-0 min-w-0 flex-1 flex-col gap-6 overflow-y-auto p-4 lg:flex',
            view === 'map' ? 'flex' : 'hidden',
          )}
        >
          <section aria-labelledby="floor-map-heading" className="flex flex-col gap-3">
            <h2 id="floor-map-heading" className="text-sm font-semibold">
              Floor map
            </h2>
            <FloorMap
              refreshKey={mapVersion}
              highlight={highlight}
              selected={selectedBay}
              onSelect={setSelectedBay}
            />
          </section>
          <section aria-labelledby="activity-heading" className="flex flex-col gap-3">
            <h2 id="activity-heading" className="text-sm font-semibold">
              Agent activity
            </h2>
            <ActivityFeed items={activity} />
          </section>
        </aside>
      </main>
    </div>
  )
}
