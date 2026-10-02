import type { TaskFilter, TaskStatus } from '@/lib/api'

// Labels and colors for task statuses. Blue for approved matches the "open task" ring on the map.
export const TASK_STATUS: Record<TaskStatus, { label: string; badge: string }> = {
  PROPOSED: {
    label: 'Awaiting approval',
    badge: 'bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200',
  },
  APPROVED: {
    label: 'Approved',
    badge: 'bg-blue-100 text-blue-900 dark:bg-blue-950 dark:text-blue-200',
  },
  DONE: {
    label: 'Done',
    badge: 'bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200',
  },
  REJECTED: { label: 'Rejected', badge: 'bg-muted text-muted-foreground' },
}

export const TASK_FILTERS: { value: TaskFilter; label: string }[] = [
  { value: 'active', label: 'Active' },
  { value: 'done', label: 'Done' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'all', label: 'All' },
]

const ZONE_NAMES: Record<string, string> = {
  A: 'Zone A',
  B: 'Zone B',
  C: 'Zone C',
}

// Location codes start with the zone letter, e.g. A-03-12-1.
export function zoneName(location: string): string {
  return ZONE_NAMES[location[0]] ?? 'Other'
}

// Times are warehouse local time with no offset, so format them as written.
export function formatTime(iso: string): string {
  return new Date(iso).toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}
