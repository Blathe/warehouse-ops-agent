import { SearchIcon } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router'
import { toast } from 'sonner'

import { ActivityPanel } from '@/components/activity/ActivityPanel'
import {
  activityFromCompletion,
  activityFromTurn,
  activityNote,
  locationsInTurn,
  type ActivityItem,
} from '@/components/activity/activity'
import { notifyActivity } from '@/components/activity/notify'
import { AgentLogPage } from '@/components/agentlog/AgentLogPage'
import { Chat } from '@/components/chat/Chat'
import { CycleCountsPage, type CountEvent } from '@/components/counts/CycleCountsPage'
import { formatVariance } from '@/components/counts/status'
import { FloorMapPage } from '@/components/floor/FloorMapPage'
import { AppSidebar } from '@/components/layout/AppSidebar'
import { CommandPalette } from '@/components/layout/CommandPalette'
import { SettingsMenu } from '@/components/layout/SettingsMenu'
import { Page } from '@/components/layout/Page'
import { PAGES } from '@/components/layout/pages'
import { OverviewPage } from '@/components/overview/OverviewPage'
import { ThemeToggle } from '@/components/layout/ThemeToggle'
import { TasksPage } from '@/components/tasks/TasksPage'
import { WorkspaceLayout } from '@/components/workspace/WorkspaceLayout'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { SidebarInset, SidebarProvider, SidebarTrigger } from '@/components/ui/sidebar'
import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import {
  getCycleCounts,
  getModels,
  getTasks,
  tickSimulation,
  type AgentTurn,
  type ModelOption,
} from '@/lib/api'
import { SHORTCUT_LABEL } from '@/lib/shortcut'
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
  const [view, setView] = useState<'chat' | 'activity'>('chat') // only used on narrow screens
  const [activity, setActivity] = useState<ActivityItem[]>([])
  const [highlight, setHighlight] = useState<string[]>([])
  const [selectedBay, setSelectedBay] = useState<string | null>(null)
  const [mapVersion, setMapVersion] = useState(0)
  const [activeTasks, setActiveTasks] = useState<number | null>(null)
  const [openCounts, setOpenCounts] = useState<number | null>(null)
  const [simulating, setSimulating] = useState(false)
  const [paletteOpen, setPaletteOpen] = useState(false)
  // The page being shown, readable from callbacks that outlive the render that created them.
  const pathnameRef = useRef(pathname)
  useEffect(() => {
    pathnameRef.current = pathname
  }, [pathname])

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
          const item = activityFromCompletion(completed)
          setActivity((current) => [...current, item])
          notifyActivity(item)
          setMapVersion((version) => version + 1)
        })
        .catch((error: Error) => {
          setSimulating(false)
          const item = activityNote('Crew simulation stopped', error.message, 'error')
          setActivity((current) => [...current, item])
          notifyActivity(item)
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
    navigate('/floor-map')
  }

  // From the Cycle counts page: log it and refresh the map, whose bays show open counts.
  // useCallback keeps the same function between renders (it only uses state setters), so
  // the page doesn't reload its counts every time the app re-renders.
  const handleCountEvent = useCallback((event: CountEvent) => {
    const item = countActivity(event)
    setActivity((current) => [...current, item])
    notifyActivity(item)
    if (event.kind !== 'investigated') setMapVersion((version) => version + 1)
  }, [])

  function changeModel(id: string) {
    setModel(id)
    save(MODEL_KEY, id)
  }

  // Called by the chat after every agent response: log what it did, point the map at
  // the bays involved (the move's destination first) and reload the map's stock.
  function handleTurn(turn: AgentTurn) {
    const items = activityFromTurn(turn)
    setActivity((current) => [...current, ...items])
    // Toast the outcome of a replenishment decision, and a nudge if the agent is waiting on
    // an approval while the supervisor is on another page. Plain lookups stay quiet.
    items.filter((item) => item.title.startsWith('Replenishment')).forEach(notifyActivity)
    if (turn.pending.length > 0 && !pathnameRef.current.startsWith('/workspace')) {
      toast.warning('The agent needs your approval', {
        description: items.find((i) => i.title === 'Waiting for your approval')?.detail,
        action: { label: 'Review', onClick: () => navigate('/workspace') },
      })
    }
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
              className: 'rounded-full bg-status-task px-1.5 text-[11px] leading-4 text-white',
            },
            '/counts': {
              count: openCounts ?? 0,
              label: `${openCounts} open`,
              className: 'rounded-full bg-status-count px-1.5 text-[11px] leading-4 text-neutral-950',
            },
          }}
          footer={
            <SettingsMenu
              supervisor={supervisor}
              onSupervisorChange={setSupervisor}
              onSupervisorCommit={() => save(NAME_KEY, supervisor.trim() || 'Supervisor')}
              models={models}
              model={model}
              onModelChange={changeModel}
              simulating={simulating}
              onToggleSimulation={() => setSimulating((on) => !on)}
            />
          }
        />
        <SidebarInset className="h-dvh min-h-0 overflow-hidden">
          <header className="flex h-12 shrink-0 items-center gap-2 border-b px-3">
            <SidebarTrigger />
            <Separator orientation="vertical" className="mr-1 h-4" />
            <h1 className="text-sm font-semibold">{pageTitle}</h1>
            <div className="ml-auto flex items-center gap-1">
              {onWorkspace && (
                <nav className="flex gap-1 lg:hidden" aria-label="View">
                  {(['chat', 'activity'] as const).map((v) => (
                    <Button
                      key={v}
                      size="sm"
                      variant={view === v ? 'secondary' : 'ghost'}
                      aria-pressed={view === v}
                      onClick={() => setView(v)}
                    >
                      {v === 'chat' ? 'Chat' : 'Activity'}
                    </Button>
                  ))}
                </nav>
              )}
              {simulating && (
                <Button
                  variant="ghost"
                  size="sm"
                  aria-label="Stop the crew simulation"
                  title="The simulated crew is finishing approved tasks. Click to stop."
                  onClick={() => setSimulating(false)}
                >
                  <span aria-hidden className="size-2 animate-pulse rounded-full bg-status-ok" />
                  <span className="hidden sm:inline">Crew running</span>
                </Button>
              )}
              <Button
                variant="outline"
                size="sm"
                className="text-muted-foreground"
                aria-label="Open the command palette"
                onClick={() => setPaletteOpen(true)}
              >
                <SearchIcon />
                <span className="hidden sm:inline">Search</span>
                <kbd className="hidden rounded border px-1 text-[10px] font-medium sm:inline">{SHORTCUT_LABEL}</kbd>
              </Button>
              <ThemeToggle />
            </div>
          </header>

          {/* The workspace stays mounted (just hidden) on other pages, so the conversation
              survives moving around the app. */}
          <div className={cn('flex min-h-0 flex-1 flex-col', !onWorkspace && 'hidden')}>
            <WorkspaceLayout
              view={view}
              chat={
                <Chat
                  supervisor={supervisor.trim() || 'Supervisor'}
                  model={model}
                  modelLabels={labels}
                  onTurn={handleTurn}
                />
              }
              activity={
                <ActivityPanel
                  items={activity}
                  highlight={highlight}
                  onClear={() => setActivity([])}
                  onShowOnMap={showOnMap}
                />
              }
            />
          </div>

          {/* The other pages mount only while shown, so they load fresh each time. */}
          <Routes>
            <Route path="/" element={<Navigate to="/overview" replace />} />
            <Route path="/workspace" element={null} />
            <Route
              path="/overview"
              element={
                <Page>
                  <OverviewPage onShowOnMap={showOnMap} refreshKey={mapVersion} />
                </Page>
              }
            />
            <Route
              path="/floor-map"
              element={
                <Page>
                  <FloorMapPage
                    refreshKey={mapVersion}
                    highlight={highlight}
                    selected={selectedBay}
                    onSelect={setSelectedBay}
                  />
                </Page>
              }
            />
            <Route
              path="/tasks"
              element={
                <Page>
                  <TasksPage onShowOnMap={showOnMap} refreshKey={mapVersion} />
                </Page>
              }
            />
            <Route
              path="/counts"
              element={
                <Page>
                  <CycleCountsPage
                    supervisor={supervisor.trim() || 'Supervisor'}
                    onShowOnMap={showOnMap}
                    onChange={handleCountEvent}
                    refreshKey={mapVersion}
                  />
                </Page>
              }
            />
            <Route
              path="/agent-log"
              element={
                <Page>
                  <AgentLogPage refreshKey={mapVersion} />
                </Page>
              }
            />
            <Route path="*" element={<Navigate to="/overview" replace />} />
          </Routes>
        </SidebarInset>
      </SidebarProvider>
      <CommandPalette
        open={paletteOpen}
        onOpenChange={setPaletteOpen}
        onShowOnMap={showOnMap}
        simulating={simulating}
        onToggleSimulation={() => setSimulating((on) => !on)}
      />
      <Toaster position="bottom-right" />
    </TooltipProvider>
  )
}
