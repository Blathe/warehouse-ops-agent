import { ChevronRightIcon, RotateCwIcon, SparklesIcon } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Spinner } from '@/components/ui/spinner'
import type { Cause, Investigation } from '@/lib/api'
import { cn } from '@/lib/utils'

const LIKELIHOOD: Record<Cause['likelihood'], { label: string; badge: string }> = {
  high: { label: 'Likely', badge: 'bg-status-count-soft text-status-count-ink' },
  medium: { label: 'Possible', badge: 'bg-status-low-soft text-status-low-ink' },
  low: { label: 'Unlikely', badge: 'bg-muted text-muted-foreground' },
}

interface InvestigationPanelProps {
  investigation: Investigation
  defaultOpen: boolean // expanded for open discrepancies, collapsed once resolved
  onRetry?: () => void // shown when it failed and can be run again
}

// The AI's explanation of a discrepancy: summary, likely causes with evidence, next steps.
export function InvestigationPanel({ investigation, defaultOpen, onRetry }: InvestigationPanelProps) {
  if (investigation.status === 'RUNNING') {
    return (
      <p className="flex items-center gap-2 rounded-lg bg-muted px-3 py-2 text-sm" role="status">
        <Spinner />
        AI is investigating this discrepancy...
      </p>
    )
  }

  if (investigation.status === 'FAILED') {
    return (
      <div className="flex flex-wrap items-center gap-2 rounded-lg bg-muted px-3 py-2 text-sm">
        <span className="text-destructive">Investigation failed: {investigation.error}</span>
        {onRetry && (
          <Button size="xs" variant="outline" onClick={onRetry}>
            <RotateCwIcon />
            Try again
          </Button>
        )}
      </div>
    )
  }

  return (
    <Collapsible defaultOpen={defaultOpen} className="rounded-lg bg-muted/60 px-3 py-2 text-sm">
      <CollapsibleTrigger className="group flex w-full items-center gap-1.5 text-left font-medium">
        <ChevronRightIcon className="size-3.5 shrink-0 transition-transform group-data-[state=open]:rotate-90" />
        <SparklesIcon className="size-3.5 shrink-0 text-status-agent" />
        AI investigation
      </CollapsibleTrigger>
      <CollapsibleContent className="flex flex-col gap-3 pt-2">
        <p>{investigation.summary}</p>

        {investigation.causes.length > 0 && (
          <ol className="flex flex-col gap-2" aria-label="Likely causes">
            {investigation.causes.map((cause, index) => (
              <li key={index} className="flex flex-col gap-1">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge className={LIKELIHOOD[cause.likelihood].badge}>
                    {LIKELIHOOD[cause.likelihood].label}
                  </Badge>
                  <span className="font-medium">{cause.cause}</span>
                </div>
                <ul className="ml-4 list-disc text-xs text-muted-foreground">
                  {cause.evidence.map((fact, i) => (
                    <li key={i}>{fact}</li>
                  ))}
                </ul>
              </li>
            ))}
          </ol>
        )}

        {investigation.next_steps.length > 0 && (
          <div>
            <h4 className="text-xs font-medium text-muted-foreground">Next steps</h4>
            <ol className={cn('ml-4 list-decimal')} aria-label="Next steps">
              {investigation.next_steps.map((step, index) => (
                <li key={index}>{step}</li>
              ))}
            </ol>
          </div>
        )}

        <p className="text-xs text-muted-foreground">
          {investigation.model} · {investigation.tool_calls}{' '}
          {investigation.tool_calls === 1 ? 'lookup' : 'lookups'}
        </p>
      </CollapsibleContent>
    </Collapsible>
  )
}
