import { ClipboardCheckIcon, MapPinIcon, RefreshCwIcon, RotateCcwIcon } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'

import { EmptyState } from '@/components/layout/EmptyState'
import { CountingProgress } from '@/components/counts/CountingProgress'
import { InvestigationPanel } from '@/components/counts/InvestigationPanel'
import { COUNT_FILTERS, COUNT_STATUS, formatVariance } from '@/components/counts/status'
import { formatTime } from '@/components/tasks/status'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  acceptCycleCount,
  getCycleCounts,
  investigateAgain,
  requestRecount,
  simulateCycleCount,
  type CountFilter,
  type CycleCount,
  type CycleCountRun,
} from '@/lib/api'
import { cn } from '@/lib/utils'

const COUNT_DURATION_MS = 4000 // how long the simulated clerk takes, for the progress bar
const POLL_MS = 2500 // how often to check on running investigations

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
  countDurationMs?: number // tests shorten these two
  pollMs?: number
}

export type CountEvent =
  | { kind: 'counted'; run: CycleCountRun }
  | { kind: 'accepted' | 'recount' | 'investigated'; count: CycleCount }

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

// Cycle counts: run a (simulated) count, then accept or recount each discrepancy it opens.
export function CycleCountsPage({
  supervisor,
  onShowOnMap,
  onChange,
  refreshKey = 0,
  countDurationMs = COUNT_DURATION_MS,
  pollMs = POLL_MS,
}: CycleCountsPageProps) {
  const [filter, setFilter] = useState<CountFilter>('open')
  const [counts, setCounts] = useState<CycleCount[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [lastRun, setLastRun] = useState<CycleCountRun | null>(null)
  const [counting, setCounting] = useState(false)
  // Investigation status per count as last seen, to notice when one finishes.
  const seen = useRef(new Map<number, string>())

  const load = useCallback(() => {
    getCycleCounts(filter)
      .then((loaded) => {
        for (const count of loaded) {
          const status = count.investigation?.status
          if (seen.current.get(count.id) === 'RUNNING' && status && status !== 'RUNNING') {
            onChange?.({ kind: 'investigated', count })
          }
          if (status) seen.current.set(count.id, status)
        }
        setCounts(loaded)
        setError(null)
      })
      .catch((e: Error) => setError(e.message))
  }, [filter, onChange])

  useEffect(load, [load, refreshKey])

  // While any investigation is still running, check again in a moment.
  const running = counts?.some((c) => c.investigation?.status === 'RUNNING') ?? false
  useEffect(() => {
    if (!running) return
    const timer = setTimeout(load, pollMs)
    return () => clearTimeout(timer)
  }, [running, counts, load, pollMs])

  function runCount() {
    setCounting(true)
    setLastRun(null)
    // The count itself is instant; wait a few seconds so it feels like a clerk walking the aisles.
    Promise.all([simulateCycleCount(), wait(countDurationMs)])
      .then(([run]) => {
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

  function retry(count: CycleCount) {
    investigateAgain(count.id)
      .then(load)
      .catch((e: Error) => setError(e.message))
  }

  return (
    <div className="flex w-full flex-col gap-4">
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

      {counting && <CountingProgress durationMs={countDurationMs} />}
      {lastRun && (
        <p role="status" className="rounded-lg bg-muted px-3 py-2 text-sm">
          Counted {lastRun.counted} locations: {lastRun.matched} matched,{' '}
          {lastRun.discrepancies.length === 1
            ? '1 discrepancy opened.'
            : `${lastRun.discrepancies.length} discrepancies opened.`}
          {lastRun.discrepancies.length > 0 && ' The AI is investigating each one.'}
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
        <EmptyState icon={ClipboardCheckIcon} title="No counts here">
          {EMPTY_TEXT[filter]}
        </EmptyState>
      ) : (
        <ul className="flex flex-col gap-3" aria-label="Cycle counts">
          {counts.map((count) => (
            <CountCard
              key={count.id}
              count={count}
              supervisor={supervisor}
              onShowOnMap={onShowOnMap}
              onResolved={resolved}
              onRetry={() => retry(count)}
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
  onRetry,
}: {
  count: CycleCount
  supervisor: string
  onShowOnMap: (location: string) => void
  onResolved: (kind: 'accepted' | 'recount', count: CycleCount) => void
  onRetry: () => void
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
        open && 'border-status-count/50',
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
                className={count.variance < 0 ? 'text-status-empty-ink' : 'text-status-ok-ink'}
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

      {count.investigation && (
        <InvestigationPanel
          investigation={count.investigation}
          defaultOpen={open}
          onRetry={open ? onRetry : undefined}
        />
      )}

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
