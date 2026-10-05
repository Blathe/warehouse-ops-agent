import { useEffect, useState } from 'react'

import { Spinner } from '@/components/ui/spinner'

const ZONE_AISLES: Record<string, number> = { A: 4, B: 3, C: 3 }

// A plausible location code, e.g. A-03-17-2, for the "Counting ..." line.
function randomLocation(): string {
  const zones = Object.keys(ZONE_AISLES)
  const zone = zones[Math.floor(Math.random() * zones.length)]
  const aisle = 1 + Math.floor(Math.random() * ZONE_AISLES[zone])
  const bay = 1 + Math.floor(Math.random() * 40)
  const level = 1 + Math.floor(Math.random() * 3)
  return `${zone}-${String(aisle).padStart(2, '0')}-${String(bay).padStart(2, '0')}-${level}`
}

// Shown while the simulated clerk counts: a bar that fills over `durationMs` and the
// location being counted, changing a few times a second.
export function CountingProgress({ durationMs }: { durationMs: number }) {
  const [location, setLocation] = useState(randomLocation)

  useEffect(() => {
    const timer = setInterval(() => setLocation(randomLocation()), 250)
    return () => clearInterval(timer)
  }, [])

  return (
    <div
      role="status"
      aria-label="Cycle count in progress"
      className="flex flex-col gap-2 rounded-lg border bg-card px-4 py-3 text-sm"
    >
      <div className="flex items-center gap-2">
        <Spinner />
        <span>
          Counting <span className="font-mono">{location}</span>...
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full bg-primary"
          style={{ animation: `count-progress ${durationMs}ms linear forwards` }}
        />
      </div>
    </div>
  )
}
