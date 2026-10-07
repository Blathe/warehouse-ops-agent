import { PauseIcon, PlayIcon, Trash2Icon } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router'

import { ActivityFeed } from '@/components/activity/ActivityFeed'
import {
  activityFromCompletion,
  activityFromTurn,
  activityNote,
  locationsInTurn,
  type ActivityItem,
} from '@/components/activity/activity'
import { AgentLogPage } from '@/components/agentlog/AgentLogPage'
import { Chat } from '@/components/chat/Chat'
import { CycleCountsPage, type CountEvent } from '@/components/counts/CycleCountsPage'
import { formatVariance } from '@/components/counts/status'
import { FloorMap } from '@/components/floor/FloorMap'
import { AppSidebar } from '@/components/layout/AppSidebar'
import { PAGES } from '@/components/layout/pages'
import { ModelPicker } from '@/components/ModelPicker'
import { TasksPage } from '@/components/tasks/TasksPage'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Separator } from '@/components/ui/separator'
import { SidebarInset, SidebarProvider, SidebarTrigger } from '@/components/ui/sidebar'
import { TooltipProvider } from '@/components/ui/tooltip'
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
  const navigate = useNavigate()
  const { pathname } = useLocation()
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
    navigate('/workspace')
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

  const pageTitle = PAGES.find((p) => pathname.startsWith(p.path))?.title ?? 'Warehouse Ops Agent'
  const onWorkspace = pathname.startsWith('/workspace')

  return (
    // Tooltips show page names when the sidebar is collapsed to icons.
    <TooltipProvider>
      <SidebarProvider>
        <AppSidebar
          badges={{
            '/tasks': {
              count: activeTasks ?? 0,
              label: `${activeTasks} active`,
              className: 'rounded-full bg-blue-600 px-1.5 text-[11px] leading-4 text-white',
            },
            '/counts': {
              count: openCounts ?? 0,
              label: `${openCounts} open`,
              className: 'rounded-full bg-orange-500 px-1.5 text-[11px] leading-4 text-white',
            },
          }}
          footer={
            <div className="flex flex-col gap-3 p-1 text-xs text-muted-foreground">
              <Button
                size="sm"
                variant={simulating ? 'secondary' : 'outline'}
                aria-pressed={simulating}
                title="Simulate the warehouse crew finishing one approved task every 5 seconds"
                onClick={() => setSimulating((on) => !on)}
                className="justify-start"
              >
                {simulating ? <PauseIcon /> : <PlayIcon />}
                Simulate crew
                {simulating && (
                  <span aria-hidden className="ml-auto size-2 animate-pulse rounded-full bg-emerald-500" />
                )}
              </Button>
              {model && models.length > 0 && (
                <label className="flex flex-col gap-1">
                  Chat model
                  <ModelPicker models={models} value={model} onChange={changeModel} />
                </label>
              )}
              <label className="flex flex-col gap-1">
                Approving as
                <Input
                  aria-label="Supervisor name"
                  value={supervisor}
                  onChange={(event) => setSupervisor(event.target.value)}
                  onBlur={() => save(NAME_KEY, supervisor.trim() || 'Supervisor')}
                  className="h-8"
                />
              </label>
            </div>
          }
        />
        <SidebarInset className="h-dvh min-h-0 overflow-hidden">
          <header className="flex h-12 shrink-0 items-center gap-2 border-b px-3">
            <SidebarTrigger />
            <Separator orientation="vertical" className="mr-1 h-4" />
            <h1 className="text-sm font-semibold">{pageTitle}</h1>
            {onWorkspace && (
              <nav className="ml-auto flex gap-1 lg:hidden" aria-label="View">
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
            )}
          </header>

          {/* The workspace stays mounted (just hidden) on other pages, so the conversation
              survives moving around the app. Large screens: chat and the right-hand column share
              the width 50/50. Narrow screens show chat or map one at a time. */}
          <div className={cn('flex min-h-0 flex-1', !onWorkspace && 'hidden')}>
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
          </div>

          {/* The other pages mount only while shown, so they load fresh each time. */}
          <Routes>
            <Route path="/" element={<Navigate to="/workspace" replace />} />
            <Route path="/workspace" element={null} />
            <Route
              path="/tasks"
              element={
                <div className="min-h-0 flex-1 overflow-y-auto p-4">
                  <TasksPage onShowOnMap={showOnMap} refreshKey={mapVersion} />
                </div>
              }
            />
            <Route
              path="/counts"
              element={
                <div className="min-h-0 flex-1 overflow-y-auto p-4">
                  <CycleCountsPage
                    supervisor={supervisor.trim() || 'Supervisor'}
                    onShowOnMap={showOnMap}
                    onChange={handleCountEvent}
                    refreshKey={mapVersion}
                  />
                </div>
              }
            />
            <Route
              path="/agent-log"
              element={
                <div className="min-h-0 flex-1 overflow-y-auto p-4">
                  <AgentLogPage refreshKey={mapVersion} />
                </div>
              }
            />
            <Route path="*" element={<Navigate to="/workspace" replace />} />
          </Routes>
        </SidebarInset>
      </SidebarProvider>
    </TooltipProvider>
  )
}
