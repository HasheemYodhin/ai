/**
 * Hand a sample prompt from the landing page to the guest chat at /try.
 * It fills the message box once; it is never sent automatically.
 *
 * Reading and clearing are separate: React may run a state initializer twice
 * (Strict Mode), so the page reads with `peekGuestPrefill` and clears with
 * `clearGuestPrefill` in an effect after it mounts.
 */
const GUEST_PREFILL_KEY = 'dabba-guest-prefill'

export function setGuestPrefill(prompt: string): void {
  try { sessionStorage.setItem(GUEST_PREFILL_KEY, prompt) } catch { /* storage blocked */ }
}

export function peekGuestPrefill(): string {
  try {
    return (sessionStorage.getItem(GUEST_PREFILL_KEY) ?? '').slice(0, 8000)
  } catch {
    return ''
  }
}

export function clearGuestPrefill(): void {
  try { sessionStorage.removeItem(GUEST_PREFILL_KEY) } catch { /* storage blocked */ }
}
