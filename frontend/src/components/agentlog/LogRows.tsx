import { ChevronRightIcon, WrenchIcon } from 'lucide-react'
import { useState } from 'react'

import {
  APPROVAL_BADGE,
  formatCost,
  formatDuration,
  formatStamp,
  formatTokens,
} from '@/components/agentlog/format'
import { Badge } from '@/components/ui/badge'
import type { LogStep, ModelCallEntry, ToolCallEntry } from '@/lib/api'
import { cn } from '@/lib/utils'

// Results are stored as JSON text; errors and rejections are plain sentences.
function prettyResult(text: string): string {
  try {
    return JSON.stringify(JSON.parse(text), null, 2)
  } catch {
    return text
  }
}

// One tool call. Click it to see the arguments it was given and what came back.
export function ToolCallRow({
  call,
  note,
  showSession = false,
}: {
  call: ToolCallEntry
  note?: string // shown at the right, e.g. the response's cost or "same response"
  showSession?: boolean
}) {
  const [open, setOpen] = useState(false)
  const approval = APPROVAL_BADGE[call.approval]
  return (
    <li className="rounded-lg border bg-card text-card-foreground">
      <button
        type="button"
        aria-expanded={open}
        aria-label={`${call.tool} at ${formatStamp(call.ts)}`}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-left text-sm"
      >
        <ChevronRightIcon
          className={cn('size-3.5 shrink-0 transition-transform', open && 'rotate-90')}
          aria-hidden
        />
        <span className="flex items-center gap-1 text-xs text-muted-foreground">
          <WrenchIcon className="size-3" aria-hidden />
          Tool call
        </span>
        <span className="font-mono font-medium">{call.tool}</span>
        {approval && <Badge className={approval.className}>{approval.label}</Badge>}
        <span className="text-xs text-muted-foreground">{formatStamp(call.ts)}</span>
        <span className="text-xs text-muted-foreground">{formatDuration(call.duration_ms)}</span>
        {showSession && (
          <span className="text-xs text-muted-foreground">{call.session_id.slice(0, 18)}</span>
        )}
        {note && <span className="ml-auto text-xs tabular-nums text-muted-foreground">{note}</span>}
      </button>
      {open && (
        <div className="flex flex-col gap-2 border-t px-3 py-2 text-xs">
          <div>
            <p className="font-medium">Arguments</p>
            <pre className="mt-1 overflow-x-auto rounded bg-muted p-2">
              {JSON.stringify(call.args, null, 2)}
            </pre>
          </div>
          <div>
            <p className="font-medium">Result</p>
            {call.result === null ? (
              <p className="mt-1 break-words text-muted-foreground">{call.result_summary}</p>
            ) : (
              <pre className="mt-1 max-h-72 overflow-auto rounded bg-muted p-2">
                {prettyResult(call.result)}
              </pre>
            )}
          </div>
        </div>
      )}
    </li>
  )
}

// What Claude did in this response, from the tool calls that came with it.
function responseHint(call: ModelCallEntry, toolCount: number): string | null {
  if (toolCount > 0) return `requested ${toolCount} ${toolCount === 1 ? 'tool' : 'tools'}`
  return call.stop_reason === 'end_turn' ? 'final answer' : null
}

function ResponseHeader({ call, toolCount }: { call: ModelCallEntry; toolCount: number }) {
  const hint = responseHint(call, toolCount)
  return (
    <p className="flex flex-wrap items-center gap-x-3 text-xs text-muted-foreground">
      <span className="font-medium text-foreground">Claude response</span>
      {hint && <span>{hint}</span>}
      <span>{call.model}</span>
      <span>
        {formatTokens(call.input_tokens)} in / {formatTokens(call.output_tokens)} out
      </span>
      <span>{formatDuration(call.duration_ms)}</span>
      <span className="ml-auto font-medium tabular-nums text-foreground">
        {formatCost(call.cost_usd)}
      </span>
    </p>
  )
}

// A session in order: each response with the tool calls it asked for underneath, so a response
// that asked for several tools shows its cost once.
export function StepList({ steps }: { steps: LogStep[] }) {
  return (
    <ol className="flex flex-col gap-3" aria-label="Steps">
      {steps.map((step, index) => (
        <li key={step.model_call?.id ?? `call-${step.tool_calls[0]?.id ?? index}`}>
          {step.model_call && (
            <ResponseHeader call={step.model_call} toolCount={step.tool_calls.length} />
          )}
          {step.tool_calls.length > 0 ? (
            <ul className="mt-1.5 flex flex-col gap-1.5 border-l-2 pl-3">
              {step.tool_calls.map((call) => (
                <ToolCallRow key={call.id} call={call} />
              ))}
            </ul>
          ) : null}
        </li>
      ))}
    </ol>
  )
}
