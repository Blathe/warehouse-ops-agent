import { PauseIcon, PlayIcon, Trash2Icon } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'

import { ActivityFeed } from '@/components/activity/ActivityFeed'
import {
  activityFromCompletion,
  activityFromTurn,
  activityNote,
  locationsInTurn,
  type ActivityItem,
} from '@/components/activity/activity'
import { Chat } from '@/components/chat/Chat'
import { CycleCountsPage, type CountEvent } from '@/components/counts/CycleCountsPage'
import { formatVariance } from '@/components/counts/status'
import { FloorMap } from '@/components/floor/FloorMap'
import { ModelPicker } from '@/components/ModelPicker'
import { TasksPage } from '@/components/tasks/TasksPage'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  getCycleCounts,
  getModels,
  getTasks,
  tickSimulation,
  type AgentTurn,
  type ModelOption,
} from '@/lib/api'
import { cn } from '@/lib/utils'

const NAME_KEY = 'warehouse-ops.supervisor'
const MODEL_KEY = 'warehouse-ops.model'
const CREW_TICK_MS = 5000 // how often the simulated crew finishes a task

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

function countActivity(event: CountEvent): ActivityItem {
  if (event.kind === 'counted') {
    const opened = event.run.discrepancies.length
    return activityNote(
      'Cycle count finished',
      `${event.run.counted} locations counted, ${opened} discrepancies opened`,
      opened > 0 ? 'warning' : 'success',
    )
  }
  const { count } = event
  if (event.kind === 'investigated') {
    const done = count.investigation?.status === 'DONE'
    return activityNote(
      done ? `AI investigated ${count.location}` : `AI investigation failed at ${count.location}`,
      (done ? count.investigation?.summary : count.investigation?.error) ?? '',
      done ? 'info' : 'error',
    )
  }
  return activityNote(
    event.kind === 'accepted'
      ? `Count accepted at ${count.location}`
      : `Recount requested at ${count.location}`,
    `${formatVariance(count.variance)} × SKU ${count.sku_code}` +
      (count.resolution_reason ? `: ${count.resolution_reason}` : ''),
    event.kind === 'accepted' ? 'success' : 'info',
  )
}

export default function App() {
  const [supervisor, setSupervisor] = useState(() => load(NAME_KEY) || 'Supervisor')
  const [models, setModels] = useState<ModelOption[]>([])
  const [model, setModel] = useState<string | null>(null)
  const [page, setPage] = useState<'workspace' | 'tasks' | 'counts'>('workspace')
  const [view, setView] = useState<'chat' | 'map'>('chat') // only used on narrow screens
  const [activity, setActivity] = useState<ActivityItem[]>([])
  const [highlight, setHighlight] = useState<string[]>([])
  const [selectedBay, setSelectedBay] = useState<string | null>(null)
  const [mapVersion, setMapVersion] = useState(0)
  const [activeTasks, setActiveTasks] = useState<number | null>(null)
  const [openCounts, setOpenCounts] = useState<number | null>(null)
  const [simulating, setSimulating] = useState(false)

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

  // The count on the Tasks tab: loaded at start and again after every agent turn,
  // since an approval can create a task.
  useEffect(() => {
    getTasks('active')
      .then((tasks) => setActiveTasks(tasks.length))
      .catch(() => setActiveTasks(null))
    getCycleCounts('open')
      .then((counts) => setOpenCounts(counts.filter((c) => c.status === 'DISCREPANCY').length))
      .catch(() => setOpenCounts(null))
  }, [mapVersion])

  // Simulated floor crew: while it is on, ask the backend to finish the oldest approved task
  // every few seconds. The map, task count and Tasks page reload when one is finished.
  // The cleanup function stops the timer when the toggle turns off (or the page closes).
  useEffect(() => {
    if (!simulating) return
    let inFlight = false // never send a tick while the previous one is still running
    const timer = setInterval(() => {
      if (inFlight) return
      inFlight = true
      tickSimulation()
        .then(({ completed }) => {
          if (!completed) return
          setActivity((current) => [...current, activityFromCompletion(completed)])
          setMapVersion((version) => version + 1)
        })
        .catch((error: Error) => {
          setSimulating(false)
          setActivity((current) => [
            ...current,
            activityNote('Crew simulation stopped', error.message, 'error'),
          ])
        })
        .finally(() => {
          inFlight = false
        })
    }, CREW_TICK_MS)
    return () => clearInterval(timer)
  }, [simulating])

  // From a task card: go back to the workspace with that bay selected on the map.
  function showOnMap(location: string) {
    setHighlight([location])
    setSelectedBay(location)
    setView('map')
    setPage('workspace')
  }

  // From the Cycle counts page: log it and refresh the map, whose bays show open counts.
  // useCallback keeps the same function between renders (it only uses state setters), so
  // the page doesn't reload its counts every time the app re-renders.
  const handleCountEvent = useCallback((event: CountEvent) => {
    setActivity((current) => [...current, countActivity(event)])
    if (event.kind !== 'investigated') setMapVersion((version) => version + 1)
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
        <nav className="flex gap-1" aria-label="Page">
          <Button
            size="sm"
            variant={page === 'workspace' ? 'secondary' : 'ghost'}
            aria-pressed={page === 'workspace'}
            onClick={() => setPage('workspace')}
          >
            Workspace
          </Button>
          <Button
            size="sm"
            variant={page === 'tasks' ? 'secondary' : 'ghost'}
            aria-pressed={page === 'tasks'}
            onClick={() => setPage('tasks')}
          >
            Tasks
            {activeTasks !== null && activeTasks > 0 && (
              <span
                aria-label={`${activeTasks} active`}
                className="ml-1 rounded-full bg-blue-600 px-1.5 text-[11px] leading-4 text-white"
              >
                {activeTasks}
              </span>
            )}
          </Button>
          <Button
            size="sm"
            variant={page === 'counts' ? 'secondary' : 'ghost'}
            aria-pressed={page === 'counts'}
            onClick={() => setPage('counts')}
          >
            Cycle counts
            {openCounts !== null && openCounts > 0 && (
              <span
                aria-label={`${openCounts} open`}
                className="ml-1 rounded-full bg-orange-500 px-1.5 text-[11px] leading-4 text-white"
              >
                {openCounts}
              </span>
            )}
          </Button>
        </nav>
        <nav className={cn('flex gap-1 lg:hidden', page !== 'workspace' && 'hidden')} aria-label="View">
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
          <Button
            size="sm"
            variant={simulating ? 'secondary' : 'outline'}
            aria-pressed={simulating}
            title="Simulate the warehouse crew finishing one approved task every 5 seconds"
            onClick={() => setSimulating((on) => !on)}
          >
            {simulating ? <PauseIcon /> : <PlayIcon />}
            Simulate crew
            {simulating && (
              <span aria-hidden className="ml-1 size-2 animate-pulse rounded-full bg-emerald-500" />
            )}
          </Button>
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
      {/* Large screens: chat and the right-hand column share the width 50/50; the right
          column is the floor map with the agent activity panel under it. Narrow screens show
          chat or map one at a time; both stay mounted so switching loses nothing. */}
      <main className={cn('flex min-h-0 flex-1', page !== 'workspace' && 'hidden')}>
        <section
          aria-label="Chat"
          className={cn(
            'min-h-0 flex-col lg:flex lg:w-1/2 lg:shrink-0 lg:border-r',
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
        {/* On narrow screens this column scrolls as one page; on large screens the map scrolls
            on its own and the activity panel keeps a fixed height underneath. */}
        <aside
          className={cn(
            'min-h-0 min-w-0 flex-1 flex-col overflow-y-auto lg:flex lg:overflow-hidden',
            view === 'map' ? 'flex' : 'hidden',
          )}
        >
          <section
            aria-labelledby="floor-map-heading"
            className="flex flex-col gap-3 p-4 lg:min-h-0 lg:flex-1 lg:overflow-y-auto"
          >
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
          <section
            aria-labelledby="activity-heading"
            className="flex flex-col gap-3 border-t p-4 lg:h-64 lg:shrink-0 lg:overflow-y-auto"
          >
            <div className="flex items-center justify-between gap-2">
              <h2 id="activity-heading" className="text-sm font-semibold">
                Agent activity
              </h2>
              {activity.length > 0 && (
                <Button
                  variant="ghost"
                  size="xs"
                  aria-label="Clear agent activity"
                  onClick={() => setActivity([])}
                >
                  <Trash2Icon />
                  Clear
                </Button>
              )}
            </div>
            <ActivityFeed items={activity} />
          </section>
        </aside>
      </main>
      {/* Mounted only while shown, so it loads fresh each time it is opened. */}
      {page === 'tasks' && (
        <main className="min-h-0 flex-1 overflow-y-auto p-4">
          <TasksPage onShowOnMap={showOnMap} refreshKey={mapVersion} />
        </main>
      )}
      {page === 'counts' && (
        <main className="min-h-0 flex-1 overflow-y-auto p-4">
          <CycleCountsPage
            supervisor={supervisor.trim() || 'Supervisor'}
            onShowOnMap={showOnMap}
            onChange={handleCountEvent}
            refreshKey={mapVersion}
          />
        </main>
      )}
    </div>
  )
}
