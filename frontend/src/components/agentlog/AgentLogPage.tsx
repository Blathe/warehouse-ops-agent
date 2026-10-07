import { ChevronRightIcon, RefreshCwIcon } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'

import { StepList, ToolCallRow } from '@/components/agentlog/LogRows'
import {
  APPROVALS,
  SOURCE_BADGE,
  SOURCES,
  endOfDay,
  formatCost,
  formatStamp,
  formatTokens,
  sessionTitle,
  sourceLabel,
  startOfDay,
} from '@/components/agentlog/format'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { NativeSelect } from '@/components/ui/native-select'
import {
  getAgentCalls,
  getAgentLogSummary,
  getAgentSessions,
  getSessionSteps,
  type Approval,
  type LogFilters,
  type LogSource,
  type LogStep,
  type LogSummary,
  type SessionSummary,
  type ToolCallEntry,
} from '@/lib/api'
import { cn } from '@/lib/utils'

const PAGE_SIZE = 50

interface AgentLogPageProps {
  refreshKey?: number // change it to reload, e.g. after the agent has answered
}

// Everything the agent did, with what it cost: grouped by conversation, or as one flat list.
export function AgentLogPage({ refreshKey = 0 }: AgentLogPageProps) {
  const [view, setView] = useState<'sessions' | 'calls'>('sessions')
  const [source, setSource] = useState<LogSource | ''>('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [tool, setTool] = useState('')
  const [approval, setApproval] = useState<Approval | ''>('')

  const [summary, setSummary] = useState<LogSummary | null>(null)
  const [sessions, setSessions] = useState<SessionSummary[] | null>(null)
  const [calls, setCalls] = useState<ToolCallEntry[] | null>(null)
  const [hasMore, setHasMore] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // The totals at the top follow the source and date filters (cost lives on requests, so the
  // tool and approval filters only narrow the flat list).
  const range: LogFilters = {
    source: source || undefined,
    since: startOfDay(from),
    until: endOfDay(to),
  }
  const rangeKey = JSON.stringify(range)

  const load = useCallback(() => {
    const filters: LogFilters = JSON.parse(rangeKey)
    const rows =
      view === 'sessions'
        ? getAgentSessions(filters).then((loaded) => setSessions(loaded))
        : getAgentCalls({
            ...filters,
            tool: tool.trim() || undefined,
            approval: approval || undefined,
            limit: PAGE_SIZE,
          }).then((loaded) => {
            setCalls(loaded)
            setHasMore(loaded.length === PAGE_SIZE)
          })
    Promise.all([getAgentLogSummary(filters).then(setSummary), rows])
      .then(() => setError(null))
      .catch((e: Error) => setError(e.message))
  }, [rangeKey, view, tool, approval])

  useEffect(load, [load, refreshKey])

  function loadMore() {
    const last = calls?.[calls.length - 1]
    if (!last) return
    getAgentCalls({
      ...(JSON.parse(rangeKey) as LogFilters),
      tool: tool.trim() || undefined,
      approval: approval || undefined,
      before_id: last.id,
      limit: PAGE_SIZE,
    })
      .then((more) => {
        setCalls((current) => [...(current ?? []), ...more])
        setHasMore(more.length === PAGE_SIZE)
      })
      .catch((e: Error) => setError(e.message))
  }

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Agent log</h2>
          <p className="text-sm text-muted-foreground">
            Every Claude request and tool call, with what it cost.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={load}>
          <RefreshCwIcon />
          Refresh
        </Button>
      </div>

      <SummaryCards summary={summary} />

      <div className="flex flex-wrap items-end gap-3">
        <div role="group" aria-label="View" className="flex gap-1">
          {(
            [
              ['sessions', 'Sessions'],
              ['calls', 'All calls'],
            ] as const
          ).map(([value, label]) => (
            <Button
              key={value}
              size="sm"
              variant={view === value ? 'secondary' : 'ghost'}
              aria-pressed={view === value}
              onClick={() => setView(value)}
            >
              {label}
            </Button>
          ))}
        </div>
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          Source
          <NativeSelect
            size="sm"
            value={source}
            onChange={(e) => setSource(e.target.value as LogSource | '')}
          >
            <option value="">All sources</option>
            {SOURCES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </NativeSelect>
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          From
          <Input
            type="date"
            value={from}
            max={to || undefined}
            onChange={(e) => setFrom(e.target.value)}
            className="h-7 w-36"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          To
          <Input
            type="date"
            value={to}
            min={from || undefined}
            onChange={(e) => setTo(e.target.value)}
            className="h-7 w-36"
          />
        </label>
        {view === 'calls' && (
          <>
            <label className="flex flex-col gap-1 text-xs text-muted-foreground">
              Tool
              <Input
                value={tool}
                placeholder="e.g. find_stock"
                onChange={(e) => setTool(e.target.value)}
                className="h-7 w-44"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-muted-foreground">
              Approval
              <NativeSelect
                size="sm"
                value={approval}
                onChange={(e) => setApproval(e.target.value as Approval | '')}
              >
                <option value="">Any</option>
                {APPROVALS.map((a) => (
                  <option key={a.value} value={a.value}>
                    {a.label}
                  </option>
                ))}
              </NativeSelect>
            </label>
          </>
        )}
      </div>

      {error ? (
        <p className="text-sm text-destructive">Couldn't load the agent log: {error}</p>
      ) : view === 'sessions' ? (
        <SessionList sessions={sessions} />
      ) : (
        <CallList calls={calls} hasMore={hasMore} onLoadMore={loadMore} />
      )}
    </div>
  )
}

function SummaryCards({ summary }: { summary: LogSummary | null }) {
  if (!summary) return <p className="text-sm text-muted-foreground">Loading totals...</p>
  const stats = [
    { label: 'Claude requests', value: summary.model_calls.toLocaleString() },
    { label: 'Tool calls', value: summary.tool_calls.toLocaleString() },
    { label: 'Sessions', value: summary.sessions.toLocaleString() },
    {
      label: 'Tokens in / out',
      value: `${formatTokens(summary.input_tokens)} / ${formatTokens(summary.output_tokens)}`,
    },
  ]
  return (
    <section aria-label="Totals" className="flex flex-col gap-3 rounded-xl border bg-card p-4">
      <div className="flex flex-wrap items-end gap-x-8 gap-y-3">
        <div>
          <p className="text-xs text-muted-foreground">Total cost</p>
          <p className="text-3xl font-semibold tabular-nums" aria-label="Total cost">
            {formatCost(summary.total_cost_usd)}
          </p>
        </div>
        {stats.map((stat) => (
          <div key={stat.label}>
            <p className="text-xs text-muted-foreground">{stat.label}</p>
            <p className="text-lg font-medium tabular-nums">{stat.value}</p>
          </div>
        ))}
      </div>
      {(summary.by_model.length > 0 || summary.by_source.length > 0) && (
        <p className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
          {summary.by_source.map((b) => (
            <span key={b.key}>
              {sourceLabel(b.key as LogSource)} {formatCost(b.cost_usd)}
            </span>
          ))}
          <span aria-hidden>·</span>
          {summary.by_model.map((b) => (
            <span key={b.key}>
              {b.key} {formatCost(b.cost_usd)}
            </span>
          ))}
        </p>
      )}
    </section>
  )
}

function SessionList({ sessions }: { sessions: SessionSummary[] | null }) {
  if (sessions === null) return <p className="text-sm text-muted-foreground">Loading sessions...</p>
  if (sessions.length === 0) {
    return (
      <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
        Nothing logged yet. Chat with the agent or investigate a cycle count and it will show up
        here.
      </p>
    )
  }
  return (
    <ul className="flex flex-col gap-2" aria-label="Sessions">
      {sessions.map((s) => (
        <SessionRow key={s.session_id} session={s} />
      ))}
    </ul>
  )
}

function SessionRow({ session }: { session: SessionSummary }) {
  const [open, setOpen] = useState(false)
  const [steps, setSteps] = useState<LogStep[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const title = sessionTitle(session.session_id, session.source)

  function toggle() {
    const next = !open
    setOpen(next)
    if (next && steps === null) {
      getSessionSteps(session.session_id)
        .then(setSteps)
        .catch((e: Error) => setError(e.message))
    }
  }

  return (
    <li className="rounded-xl border bg-card text-card-foreground">
      <button
        type="button"
        aria-expanded={open}
        aria-label={title}
        onClick={toggle}
        className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 text-left"
      >
        <ChevronRightIcon
          className={cn('size-4 shrink-0 transition-transform', open && 'rotate-90')}
          aria-hidden
        />
        <span className="font-medium">{title}</span>
        <Badge className={SOURCE_BADGE[session.source]}>{sourceLabel(session.source)}</Badge>
        {session.rejected > 0 && (
          <Badge className="bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-200">
            {session.rejected} rejected
          </Badge>
        )}
        <span className="text-xs text-muted-foreground">{formatStamp(session.started_at)}</span>
        <span className="text-xs text-muted-foreground">
          {session.model_calls} requests · {session.tool_calls} tool calls
        </span>
        <span className="ml-auto text-sm font-medium tabular-nums">
          {formatCost(session.cost_usd)}
        </span>
      </button>
      {open && (
        <div className="border-t px-4 py-3">
          {error ? (
            <p className="text-sm text-destructive">Couldn't load this session: {error}</p>
          ) : steps === null ? (
            <p className="text-sm text-muted-foreground">Loading...</p>
          ) : (
            <StepList steps={steps} />
          )}
        </div>
      )}
    </li>
  )
}

function CallList({
  calls,
  hasMore,
  onLoadMore,
}: {
  calls: ToolCallEntry[] | null
  hasMore: boolean
  onLoadMore: () => void
}) {
  if (calls === null) return <p className="text-sm text-muted-foreground">Loading calls...</p>
  if (calls.length === 0) {
    return (
      <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
        No tool calls match these filters.
      </p>
    )
  }
  // Several calls can come from one request. Show its cost on the first one listed and mark
  // the rest, so adding up the column doesn't count a request twice.
  const seen = new Set<number>()
  return (
    <div className="flex flex-col gap-3">
      <ul className="flex flex-col gap-1.5" aria-label="Tool calls">
        {calls.map((call) => {
          let note: string | undefined
          if (call.model_call_id !== null && call.model_call_cost_usd !== null) {
            note = seen.has(call.model_call_id)
              ? 'same request'
              : `request ${formatCost(call.model_call_cost_usd)}`
            seen.add(call.model_call_id)
          }
          return <ToolCallRow key={call.id} call={call} note={note} showSession />
        })}
      </ul>
      {hasMore && (
        <Button variant="outline" size="sm" className="self-center" onClick={onLoadMore}>
          Load more
        </Button>
      )}
    </div>
  )
}
