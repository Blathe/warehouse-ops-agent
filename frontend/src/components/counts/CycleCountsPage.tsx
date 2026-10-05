import { ClipboardCheckIcon, MapPinIcon, RefreshCwIcon, RotateCcwIcon } from 'lucide-react'
import { useCallback, useEffect, useState, type FormEvent } from 'react'

import { COUNT_FILTERS, COUNT_STATUS, formatVariance } from '@/components/counts/status'
import { formatTime } from '@/components/tasks/status'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  acceptCycleCount,
  getCycleCounts,
  requestRecount,
  simulateCycleCount,
  type CountFilter,
  type CycleCount,
  type CycleCountRun,
} from '@/lib/api'
import { cn } from '@/lib/utils'

const EMPTY_TEXT: Record<CountFilter, string> = {
  open: 'No open discrepancies. Run a cycle count to check some locations.',
  resolved: 'Nothing resolved yet.',
  all: 'No cycle counts yet.',
}

interface CycleCountsPageProps {
  supervisor: string // recorded as who accepted or asked for the recount
  onShowOnMap: (location: string) => void
  onChange?: (event: CountEvent) => void // so the app can refresh the map and log activity
  refreshKey?: number
}

export type CountEvent =
  | { kind: 'counted'; run: CycleCountRun }
  | { kind: 'accepted' | 'recount'; count: CycleCount }

// Cycle counts: run a (simulated) count, then accept or recount each discrepancy it opens.
export function CycleCountsPage({
  supervisor,
  onShowOnMap,
  onChange,
  refreshKey = 0,
}: CycleCountsPageProps) {
  const [filter, setFilter] = useState<CountFilter>('open')
  const [counts, setCounts] = useState<CycleCount[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [lastRun, setLastRun] = useState<CycleCountRun | null>(null)
  const [counting, setCounting] = useState(false)

  const load = useCallback(() => {
    getCycleCounts(filter)
      .then((loaded) => {
        setCounts(loaded)
        setError(null)
      })
      .catch((e: Error) => setError(e.message))
  }, [filter])

  useEffect(load, [load, refreshKey])

  function runCount() {
    setCounting(true)
    simulateCycleCount()
      .then((run) => {
        setLastRun(run)
        onChange?.({ kind: 'counted', run })
        load()
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setCounting(false))
  }

  function resolved(kind: 'accepted' | 'recount', count: CycleCount) {
    onChange?.({ kind, count })
    load()
  }

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Cycle counts</h2>
          <p className="text-sm text-muted-foreground">
            When a count doesn't match the system, a discrepancy opens here for a supervisor.
          </p>
        </div>
        <div className="flex gap-2">
          <Button size="sm" onClick={runCount} disabled={counting}>
            <ClipboardCheckIcon />
            {counting ? 'Counting...' : 'Simulate cycle count'}
          </Button>
          <Button variant="outline" size="sm" onClick={load}>
            <RefreshCwIcon />
            Refresh
          </Button>
        </div>
      </div>

      {lastRun && (
        <p role="status" className="rounded-lg bg-muted px-3 py-2 text-sm">
          Counted {lastRun.counted} locations: {lastRun.matched} matched,{' '}
          {lastRun.discrepancies.length === 1
            ? '1 discrepancy opened.'
            : `${lastRun.discrepancies.length} discrepancies opened.`}
        </p>
      )}

      <div role="group" aria-label="Filter counts" className="flex flex-wrap gap-1">
        {COUNT_FILTERS.map(({ value, label }) => (
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

      {error && <p className="text-sm text-destructive">{error}</p>}
      {counts === null ? (
        !error && <p className="text-sm text-muted-foreground">Loading counts...</p>
      ) : counts.length === 0 ? (
        <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
          {EMPTY_TEXT[filter]}
        </p>
      ) : (
        <ul className="flex flex-col gap-3" aria-label="Cycle counts">
          {counts.map((count) => (
            <CountCard
              key={count.id}
              count={count}
              supervisor={supervisor}
              onShowOnMap={onShowOnMap}
              onResolved={resolved}
            />
          ))}
        </ul>
      )}
    </div>
  )
}

function CountCard({
  count,
  supervisor,
  onShowOnMap,
  onResolved,
}: {
  count: CycleCount
  supervisor: string
  onShowOnMap: (location: string) => void
  onResolved: (kind: 'accepted' | 'recount', count: CycleCount) => void
}) {
  const [accepting, setAccepting] = useState(false)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const status = COUNT_STATUS[count.status]
  const open = count.status === 'DISCREPANCY'

  function act(kind: 'accepted' | 'recount', request: () => Promise<CycleCount>) {
    setBusy(true)
    setError(null)
    request()
      .then((updated) => onResolved(kind, updated))
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false))
  }

  function onAccept(event: FormEvent) {
    event.preventDefault()
    if (!reason.trim()) return
    act('accepted', () => acceptCycleCount(count.id, supervisor, reason.trim()))
  }

  return (
    <li
      aria-label={`Count at ${count.location}`}
      className={cn(
        'flex flex-col gap-3 rounded-xl border bg-card p-4 text-card-foreground',
        open && 'border-orange-300 dark:border-orange-800',
      )}
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 flex-col gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold">{count.location}</span>
            <Badge className={status.badge}>{status.label}</Badge>
            {count.variance !== 0 && (
              <Badge
                variant="outline"
                className={count.variance < 0 ? 'text-red-700 dark:text-red-400' : 'text-emerald-700 dark:text-emerald-400'}
              >
                {formatVariance(count.variance)}
              </Badge>
            )}
          </div>
          <p className="text-sm">
            <span className="font-medium">SKU {count.sku_code}</span>
            <span className="text-muted-foreground"> · {count.description}</span>
          </p>
          <p className="text-sm">
            System <span className="font-medium">{count.system_qty}</span> · Counted{' '}
            <span className="font-medium">{count.counted_qty}</span>
            {count.lpn && <span className="text-xs text-muted-foreground"> ({count.lpn})</span>}
            <span className="text-xs text-muted-foreground"> · case of {count.case_qty}</span>
          </p>
          <p className="text-xs text-muted-foreground">
            Counted by {count.counted_by}, {formatTime(count.counted_at)}
            {count.resolved_by &&
              ` · ${count.status === 'ACCEPTED' ? 'Accepted' : 'Recount requested'} by ${count.resolved_by}`}
            {count.resolution_reason && `: "${count.resolution_reason}"`}
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          className="shrink-0"
          onClick={() => onShowOnMap(count.location.replace(/-\d$/, '-1'))}
        >
          <MapPinIcon />
          Show on map
        </Button>
      </div>

      {open && !accepting && (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" disabled={busy} onClick={() => setAccepting(true)}>
            Accept count
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() => act('recount', () => requestRecount(count.id, supervisor))}
          >
            <RotateCcwIcon />
            Recount
          </Button>
        </div>
      )}
      {open && accepting && (
        <form onSubmit={onAccept} className="flex flex-wrap items-center gap-2">
          <Input
            autoFocus
            aria-label="Reason for accepting"
            placeholder="Why does the count stand? (required)"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            className="h-8 min-w-60 flex-1"
          />
          <Button size="sm" type="submit" disabled={busy || !reason.trim()}>
            Adjust system to {count.counted_qty}
          </Button>
          <Button size="sm" variant="ghost" type="button" onClick={() => setAccepting(false)}>
            Cancel
          </Button>
        </form>
      )}
      {error && <p className="text-sm text-destructive">{error}</p>}
    </li>
  )
}
