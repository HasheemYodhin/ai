import { cn } from '@/lib/utils'

const LEVELS: Record<string, number> = { low: 1, medium: 2, high: 3, xhigh: 4, max: 5 }

/** A tiffin-style stack of five compartments, filled from the bottom by tier. */
export function TierStack({ tier, className }: { tier: string; className?: string }) {
  const level = LEVELS[tier] ?? 2
  return (
    <span
      role="img"
      aria-label={`Tier: ${tier}`}
      title={`Tier: ${tier}`}
      className={cn('inline-flex flex-col-reverse gap-px w-2.5 flex-shrink-0', className)}
    >
      {[1, 2, 3, 4, 5].map(i => (
        <span
          key={i}
          className={cn(
            'h-[2px] rounded-[1px] bg-current',
            i > level && 'opacity-25'
          )}
        />
      ))}
    </span>
  )
}
