export interface BrowserCodeResult {
  exitCode: number | null
  stdout: string
  stderr: string
  timedOut: boolean
  truncated?: boolean
  durationMs: number
  phase?: 'compile' | 'run'
}

export function runBrowserPython(code: string, stdin: string, signal: AbortSignal): Promise<BrowserCodeResult> {
  signal.throwIfAborted()
  const encoder = new TextEncoder()
  if (encoder.encode(code).length > 100_000 || encoder.encode(stdin).length > 32_000) {
    throw new Error('Python input is too large. Use up to 100 KB of code and 32 KB of standard input.')
  }

  return new Promise((resolve, reject) => {
    const frame = document.createElement('iframe')
    frame.hidden = true
    frame.sandbox.add('allow-scripts')
    frame.referrerPolicy = 'no-referrer'
    frame.src = '/code-runner.html'
    const channel = new MessageChannel()
    let timer = window.setTimeout(() => fail('Could not load Python. Check your connection and try again.'), 45_000)

    const cleanup = () => {
      window.clearTimeout(timer)
      signal.removeEventListener('abort', onAbort)
      channel.port1.close()
      channel.port2.close()
      frame.remove()
    }
    const fail = (message: string) => {
      cleanup()
      reject(new Error(message))
    }
    const onAbort = () => {
      cleanup()
      reject(signal.reason)
    }
    signal.addEventListener('abort', onAbort, { once: true })
    channel.port1.onmessage = ({ data }) => {
      if (data?.type === 'ready') {
        window.clearTimeout(timer)
        timer = window.setTimeout(() => {
          cleanup()
          resolve({ exitCode: null, stdout: '', stderr: '', timedOut: true, durationMs: 5000 })
        }, 5000)
      } else if (data?.type === 'result') {
        cleanup()
        resolve(data.result)
      } else {
        fail('Could not start Python in this browser. Check your connection and try again.')
      }
    }
    frame.addEventListener('load', () => {
      frame.contentWindow?.postMessage({ code, stdin }, '*', [channel.port2])
    }, { once: true })
    document.body.append(frame)
  })
}
