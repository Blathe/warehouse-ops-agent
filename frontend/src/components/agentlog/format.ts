import type { Approval, LogSource } from '@/lib/api'

export const SOURCES: { value: LogSource; label: string }[] = [
  { value: 'CHAT', label: 'Chat' },
  { value: 'INVESTIGATOR', label: 'Investigator' },
  { value: 'MCP', label: 'MCP client' },
]

export const SOURCE_BADGE: Record<LogSource, string> = {
  CHAT: 'bg-blue-100 text-blue-900 dark:bg-blue-950 dark:text-blue-200',
  INVESTIGATOR: 'bg-violet-100 text-violet-900 dark:bg-violet-950 dark:text-violet-200',
  MCP: 'bg-muted text-muted-foreground',
}

export const APPROVALS: { value: Approval; label: string }[] = [
  { value: 'approved', label: 'Approved' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'n/a', label: 'No approval needed' },
]

// Only writes need approval, so "n/a" gets no badge.
export const APPROVAL_BADGE: Partial<Record<Approval, { label: string; className: string }>> = {
  approved: {
    label: 'Approved',
    className: 'bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200',
  },
  rejected: {
    label: 'Rejected',
    className: 'bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-200',
  },
}

export function sourceLabel(source: LogSource): string {
  return SOURCES.find((s) => s.value === source)?.label ?? source
}

// Single requests cost fractions of a cent, so show four decimals.
export function formatCost(usd: number): string {
  return `$${usd.toFixed(4)}`
}

export function formatTokens(count: number): string {
  if (count >= 1_000_000) return `${(count / 1_000_000).toFixed(2)}M`
  return count >= 10_000 ? `${(count / 1000).toFixed(1)}k` : count.toLocaleString()
}

export function formatDuration(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`
}

// Times are warehouse local time with no offset, so format them as written.
export function formatStamp(iso: string): string {
  return new Date(iso).toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    second: '2-digit',
  })
}

// Investigations log as "investigation:<id>"; chats and MCP connections are random ids.
export function sessionTitle(sessionId: string, source: LogSource): string {
  const investigation = /^investigation:(\d+)$/.exec(sessionId)
  if (investigation) return `Investigation #${investigation[1]}`
  const short = sessionId.slice(0, 8)
  return source === 'MCP' ? `MCP session ${short}` : `Conversation ${short}`
}

// A date input gives "2026-06-01"; the backend wants warehouse local time.
export function startOfDay(date: string): string | undefined {
  return date ? `${date}T00:00:00` : undefined
}

export function endOfDay(date: string): string | undefined {
  return date ? `${date}T23:59:59` : undefined
}
