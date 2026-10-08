import { ActivityIcon } from 'lucide-react'

import type { ActivityItem, Tone } from '@/components/activity/activity'
import { EmptyState } from '@/components/layout/EmptyState'
import { cn } from '@/lib/utils'

const DOT: Record<Tone, string> = {
  info: 'bg-muted-foreground/50',
  success: 'bg-status-ok',
  warning: 'bg-status-low',
  error: 'bg-status-empty',
}

// What the agent has done in this session, newest first.
export function ActivityFeed({ items }: { items: ActivityItem[] }) {
  if (items.length === 0) {
    return (
      <EmptyState icon={ActivityIcon} title="No activity yet">
        Tool calls and approvals will show up here as you chat.
      </EmptyState>
    )
  }
  return (
    <ol className="flex flex-col gap-2.5" aria-label="Agent activity">
      {[...items].reverse().map((item) => (
        <li key={item.id} className="flex gap-2.5 text-sm">
          <span className={cn('mt-1.5 size-2 shrink-0 rounded-full', DOT[item.tone])} />
          <div className="min-w-0">
            <p className="font-medium">
              {item.title}
              <span className="ml-2 text-xs font-normal text-muted-foreground">
                {item.at.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </span>
            </p>
            {item.detail && (
              <p className="break-words text-xs text-muted-foreground">{item.detail}</p>
            )}
          </div>
        </li>
      ))}
    </ol>
  )
}
