import { Lock } from 'lucide-react'

/**
 * Shown in place of a page whose backend endpoints are admin-only, so regular
 * users get an explanation instead of a usable-looking form that fails with
 * "Administrator access is required" or a raw 403.
 */
export function AdminOnlyNotice({ feature }: { feature: string }) {
  return (
    <div className="flex h-full items-center justify-center p-8">
      <div className="max-w-sm text-center">
        <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-surface-tertiary dark:bg-surface-dark-tertiary">
          <Lock className="h-5 w-5 text-text-secondary dark:text-text-dark-secondary" aria-hidden="true" />
        </div>
        <h2 className="text-sm font-semibold text-text-primary dark:text-text-dark-primary">{feature} is for the workspace owner</h2>
        <p className="mt-1.5 text-xs text-text-secondary dark:text-text-dark-secondary">
          It can run commands and change settings on the Dabba server, so only the workspace owner
          (the first account created on this server) can use it.
        </p>
      </div>
    </div>
  )
}
