import { useEffect, useRef, useState } from 'react'

function prefersReducedMotion(): boolean {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

// Counts up from 0 to ``target`` when first shown, and from the old number to the new one when
// it changes. Skips the animation for people who ask their system to reduce motion.
export function useCountUp(target: number, durationMs = 700): number {
  const [value, setValue] = useState(() => (prefersReducedMotion() ? target : 0))
  const shown = useRef(value) // the number on screen, where the next animation starts

  useEffect(() => {
    if (prefersReducedMotion()) {
      shown.current = target
      setValue(target)
      return
    }
    const from = shown.current
    const start = performance.now()
    let frame = 0
    function tick(now: number) {
      const progress = Math.min(1, (now - start) / durationMs)
      const eased = 1 - (1 - progress) ** 3 // fast at first, settling at the end
      shown.current = Math.round(from + (target - from) * eased)
      setValue(shown.current)
      if (progress < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [target, durationMs])

  return value
}
