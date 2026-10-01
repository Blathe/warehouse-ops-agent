import type { ActivityItem, Tone } from '@/components/activity/activity'
import { cn } from '@/lib/utils'

const DOT: Record<Tone, string> = {
  info: 'bg-muted-foreground/50',
  success: 'bg-emerald-500',
  warning: 'bg-amber-400',
  error: 'bg-red-500',
}

// What the agent has done in this session, newest first.
export function ActivityFeed({ items }: { items: ActivityItem[] }) {
  if (items.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        Tool calls and approvals will show up here as you chat.
      </p>
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
