import { ChevronRightIcon } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import type { ToolTrace } from '@/lib/api'

// A collapsed list of the tools the agent called for one reply, so a supervisor
// can check where an answer came from.
export function ToolCalls({ calls }: { calls: ToolTrace[] }) {
  if (calls.length === 0) return null
  return (
    <Collapsible className="text-xs text-muted-foreground">
      <CollapsibleTrigger className="group flex items-center gap-1 hover:text-foreground">
        <ChevronRightIcon className="size-3 transition-transform group-data-[state=open]:rotate-90" />
        {calls.length === 1 ? '1 tool call' : `${calls.length} tool calls`}
      </CollapsibleTrigger>
      <CollapsibleContent>
        <ul className="mt-2 flex flex-col gap-2 border-l pl-3">
          {calls.map((call, index) => (
            <li key={index} className="flex flex-col gap-1">
              <div className="flex flex-wrap items-center gap-1.5">
                <code className="font-medium text-foreground">{call.tool}</code>
                {!call.ok && <Badge variant="destructive">error</Badge>}
                {call.approval !== 'n/a' && <Badge variant="secondary">{call.approval}</Badge>}
              </div>
              <code className="break-all">{JSON.stringify(call.input)}</code>
              <span className="break-all">{call.summary}</span>
            </li>
          ))}
        </ul>
      </CollapsibleContent>
    </Collapsible>
  )
}
