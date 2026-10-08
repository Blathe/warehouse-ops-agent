import { ArrowRightIcon, CircleCheckBigIcon, MapPinIcon, RefreshCwIcon } from 'lucide-react'
import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { Link } from 'react-router'

import { EmptyState } from '@/components/layout/EmptyState'
import { ShortPicksChart, ZoneHealthChart } from '@/components/overview/charts'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useCountUp } from '@/hooks/use-count-up'
import { getOverview, type OverviewData, type UrgentNeed } from '@/lib/api'
import { cn } from '@/lib/utils'

interface OverviewPageProps {
  onShowOnMap: (location: string) => void // pick face code to show on the floor map
  refreshKey?: number // change it to reload, e.g. after the agent or the crew changes something
}

// The first thing a supervisor sees: what is wrong right now, and where to go to fix it.
export function OverviewPage({ onShowOnMap, refreshKey = 0 }: OverviewPageProps) {
  const [data, setData] = useState<OverviewData | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    getOverview()
      .then((loaded) => {
        setData(loaded)
        setError(null)
      })
      .catch((e: Error) => setError(e.message))
  }, [])

  useEffect(load, [load, refreshKey])

  return (
    <div className="flex w-full flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Overview</h2>
          <p className="text-sm text-muted-foreground">
            {data ? `Warehouse status as of ${formatAsOf(data.as_of)}` : 'Warehouse status'}
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={load}>
          <RefreshCwIcon />
          Refresh
        </Button>
      </div>

      {error ? (
        <p className="text-sm text-destructive">Couldn't load the overview: {error}</p>
      ) : !data ? (
        <OverviewSkeleton />
      ) : (
        <>
          <section aria-label="Key numbers" className="grid grid-cols-2 gap-3 lg:grid-cols-3">
            <Tile label="Empty pick faces" value={data.empty_faces} tone="empty" to="/workspace" />
            <Tile label="Low pick faces" value={data.low_faces} tone="low" to="/workspace" />
            <Tile label="Short picks, 24h" value={data.short_picks_24h} tone="agent" to="/workspace" />
            <Tile
              label="Awaiting approval"
              value={data.tasks_awaiting_approval}
              tone="low"
              to="/tasks"
            />
            <Tile label="Approved, in progress" value={data.tasks_approved} tone="task" to="/tasks" />
            <Tile
              label="Open count discrepancies"
              value={data.open_discrepancies}
              tone="count"
              to="/counts"
            />
          </section>

          <div className="grid gap-4 lg:grid-cols-2">
            <Panel title="Pick face health by zone">
              <ZoneHealthChart zones={data.zones} />
            </Panel>
            <Panel title="Short picks, last 24 hours">
              <ShortPicksChart buckets={data.short_picks_by_hour} />
            </Panel>
          </div>

          <Panel title="Needs attention" hint="Pick faces to refill, most urgent first">
            {data.urgent_needs.length === 0 ? (
              <EmptyState icon={CircleCheckBigIcon} title="Nothing urgent">
                Every pick face that needs stock already has a task.
              </EmptyState>
            ) : (
              <ul className="flex flex-col divide-y" aria-label="Urgent pick faces">
                {data.urgent_needs.map((need) => (
                  <NeedRow key={need.location} need={need} onShowOnMap={onShowOnMap} />
                ))}
              </ul>
            )}
          </Panel>
        </>
      )}
    </div>
  )
}

// Warehouse local time has no offset, so format it as written.
function formatAsOf(iso: string): string {
  return new Date(iso).toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

const TONE_DOT = {
  empty: 'bg-status-empty',
  low: 'bg-status-low',
  task: 'bg-status-task',
  agent: 'bg-status-agent',
  count: 'bg-status-count',
}

function Tile({
  label,
  value,
  tone,
  to,
}: {
  label: string
  value: number
  tone: keyof typeof TONE_DOT
  to: string
}) {
  const shown = useCountUp(value)
  return (
    <Link
      to={to}
      className="group flex flex-col gap-2 rounded-xl border bg-card p-4 text-card-foreground transition-colors hover:bg-accent/50"
    >
      <span className="flex items-center gap-2 text-xs text-muted-foreground">
        <span aria-hidden className={cn('size-2 rounded-full', TONE_DOT[tone])} />
        {label}
      </span>
      <span className="flex items-end justify-between">
        <span className="text-3xl font-semibold tabular-nums">{shown.toLocaleString()}</span>
        <ArrowRightIcon
          aria-hidden
          className="size-4 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100"
        />
      </span>
    </Link>
  )
}

function Panel({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-4 rounded-xl border bg-card p-4 text-card-foreground">
      <div>
        <h3 className="text-sm font-semibold">{title}</h3>
        {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      </div>
      {children}
    </section>
  )
}

function NeedRow({
  need,
  onShowOnMap,
}: {
  need: UrgentNeed
  onShowOnMap: (location: string) => void
}) {
  const empty = need.on_hand === 0
  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-2 py-3 first:pt-0 last:pb-0">
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <p className="truncate text-sm">
          <span className="font-medium">{need.location}</span>
          <span className="text-muted-foreground">
            {' '}
            · SKU {need.sku_code} · {need.description}
          </span>
        </p>
        <p className="text-xs text-muted-foreground">
          {empty ? 'Empty' : `${need.on_hand} on hand`} · min {need.min_qty}
          {need.suggested_qty > 0 ? ` · suggested refill ${need.suggested_qty}` : ' · no reserve stock'}
        </p>
      </div>
      <div className="flex items-center gap-3">
        <div
          aria-hidden
          className="h-1.5 w-24 overflow-hidden rounded-full bg-muted"
          title={`${need.on_hand} of max ${need.max_qty}`}
        >
          <div
            className={cn('h-full rounded-full', empty ? 'bg-status-empty' : 'bg-status-low')}
            style={{ width: `${Math.min(100, (need.on_hand / need.max_qty) * 100)}%` }}
          />
        </div>
        <Button
          variant="outline"
          size="xs"
          aria-label={`Show ${need.location} on the map`}
          onClick={() => onShowOnMap(need.location)}
        >
          <MapPinIcon />
          Map
        </Button>
      </div>
    </li>
  )
}

function OverviewSkeleton() {
  return (
    <div className="flex flex-col gap-6" role="status" aria-label="Loading overview">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-[88px] rounded-xl" />
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Skeleton className="h-52 rounded-xl" />
        <Skeleton className="h-52 rounded-xl" />
      </div>
      <Skeleton className="h-64 rounded-xl" />
    </div>
  )
}
