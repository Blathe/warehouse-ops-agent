import type { ReactNode } from 'react'
import { useDefaultLayout } from 'react-resizable-panels'

import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from '@/components/ui/resizable'
import { useMediaQuery } from '@/hooks/use-media-query'
import { cn } from '@/lib/utils'

interface WorkspaceLayoutProps {
  chat: ReactNode
  activity: ReactNode
  view: 'chat' | 'activity' // which one a narrow screen shows
}

// Browser storage can be unavailable (private mode), so never let it throw.
const layoutStorage = {
  getItem(key: string): string | null {
    try {
      return localStorage.getItem(key)
    } catch {
      return null
    }
  },
  setItem(key: string, value: string): void {
    try {
      localStorage.setItem(key, value)
    } catch {
      // The split just isn't remembered.
    }
  },
}

// Chat and the agent's activity side by side. On a wide screen the divider between them can be
// dragged (or moved with the arrow keys) and the position is remembered; on a narrow screen they
// take turns.
export function WorkspaceLayout({ chat, activity, view }: WorkspaceLayoutProps) {
  const wide = useMediaQuery('(min-width: 1024px)')
  const { defaultLayout, onLayoutChanged } = useDefaultLayout({
    id: 'warehouse-ops.workspace',
    storage: layoutStorage,
  })

  if (!wide) {
    return (
      <div className="flex min-h-0 flex-1 flex-col">
        <section aria-label="Chat" className={cn('min-h-0 flex-1 flex-col', view === 'chat' ? 'flex' : 'hidden')}>
          {chat}
        </section>
        <div className={cn('min-h-0 flex-1', view === 'activity' ? 'block' : 'hidden')}>{activity}</div>
      </div>
    )
  }

  return (
    <ResizablePanelGroup
      orientation="horizontal"
      defaultLayout={defaultLayout}
      onLayoutChanged={onLayoutChanged}
      className="min-h-0 flex-1"
    >
      <ResizablePanel id="chat" minSize="35%" defaultSize="65%">
        <section aria-label="Chat" className="flex h-full min-h-0 flex-col">
          {chat}
        </section>
      </ResizablePanel>
      <ResizableHandle withHandle aria-label="Resize chat and activity" />
      <ResizablePanel id="activity" minSize="20%" maxSize="50%" defaultSize="35%">
        {activity}
      </ResizablePanel>
    </ResizablePanelGroup>
  )
}
