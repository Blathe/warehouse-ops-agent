import { ArrowRightIcon, MapPinIcon, RefreshCwIcon } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'

import { formatTime, TASK_FILTERS, TASK_STATUS, zoneName } from '@/components/tasks/status'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { getTasks, type ReplenishmentTask, type TaskFilter } from '@/lib/api'
import { cn } from '@/lib/utils'

const EMPTY_TEXT: Record<TaskFilter, string> = {
  active: 'No active tasks. Ask the agent what needs replenishing, then approve a move.',
  done: 'No finished tasks yet.',
  rejected: 'No rejected tasks.',
  all: 'No replenishment tasks yet.',
}

interface TasksPageProps {
  onShowOnMap: (location: string) => void // pick face code to show on the floor map
  refreshKey?: number // change it to reload, e.g. when the simulated crew finishes a task
}

// Every replenishment task in one place: what is being moved, where, why and who approved it.
export function TasksPage({ onShowOnMap, refreshKey = 0 }: TasksPageProps) {
  const [filter, setFilter] = useState<TaskFilter>('active')
  const [tasks, setTasks] = useState<ReplenishmentTask[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    getTasks(filter)
      .then((loaded) => {
        setTasks(loaded)
        setError(null)
      })
      .catch((e: Error) => setError(e.message))
  }, [filter])

  // Runs when the page opens and whenever the filter or refreshKey changes; Refresh calls load too.
  useEffect(load, [load, refreshKey])

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Replenishment tasks</h2>
          <p className="text-sm text-muted-foreground">
            Stock moves from reserve to pick faces. New ones are approved in the chat.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={load}>
          <RefreshCwIcon />
          Refresh
        </Button>
      </div>

      <div role="group" aria-label="Filter tasks" className="flex flex-wrap gap-1">
        {TASK_FILTERS.map(({ value, label }) => (
          <Button
            key={value}
            size="sm"
            variant={filter === value ? 'secondary' : 'ghost'}
            aria-pressed={filter === value}
            onClick={() => setFilter(value)}
          >
            {label}
          </Button>
        ))}
      </div>

      {error ? (
        <p className="text-sm text-destructive">Couldn't load the tasks: {error}</p>
      ) : tasks === null ? (
        <p className="text-sm text-muted-foreground">Loading tasks...</p>
      ) : tasks.length === 0 ? (
        <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
          {EMPTY_TEXT[filter]}
        </p>
      ) : (
        <ul className="flex flex-col gap-3" aria-label="Tasks">
          {tasks.map((task) => (
            <TaskCard key={task.task_id} task={task} onShowOnMap={onShowOnMap} />
          ))}
        </ul>
      )}
    </div>
  )
}

function TaskCard({
  task,
  onShowOnMap,
}: {
  task: ReplenishmentTask
  onShowOnMap: (location: string) => void
}) {
  const status = TASK_STATUS[task.status]
  const decision =
    task.approved_by &&
    `${task.status === 'REJECTED' ? 'Rejected' : 'Approved'} by ${task.approved_by}`
  return (
    <li
      aria-label={`Task #${task.task_id}`}
      className={cn(
        'flex flex-col gap-3 rounded-xl border bg-card p-4 text-card-foreground sm:flex-row sm:items-start sm:justify-between',
        task.status === 'PROPOSED' && 'border-status-low/50',
      )}
    >
      <div className="flex min-w-0 flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-semibold">Task #{task.task_id}</span>
          <Badge className={status.badge}>{status.label}</Badge>
          <Badge variant="outline">{zoneName(task.to_location)}</Badge>
        </div>
        <p className="text-sm">
          <span className="font-medium">SKU {task.sku_code}</span>
          <span className="text-muted-foreground"> · {task.description}</span>
        </p>
        <p className="flex flex-wrap items-center gap-x-2 text-sm">
          <span className="font-medium">Move {task.qty}</span>
          <span className="flex items-center gap-1 text-muted-foreground">
            {task.from_location}
            <ArrowRightIcon className="size-3.5" aria-label="to" />
            {task.to_location}
          </span>
          {task.lpn && <span className="text-xs text-muted-foreground">({task.lpn})</span>}
        </p>
        <p className="text-sm text-muted-foreground">{task.reason}</p>
        <p className="text-xs text-muted-foreground">
          Created by {task.created_by}, {formatTime(task.created_at)}
          {decision && ` · ${decision}`}
        </p>
      </div>
      <Button
        variant="outline"
        size="sm"
        className="shrink-0"
        onClick={() => onShowOnMap(task.to_location)}
      >
        <MapPinIcon />
        Show on map
      </Button>
    </li>
  )
}
