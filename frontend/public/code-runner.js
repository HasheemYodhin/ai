// The worker inherits the opaque origin and CSP of the sandboxed iframe.
function runPython() {
  self.onmessage = async ({ data: { code, stdin } }) => {
    try {
      const indexURL = 'https://cdn.jsdelivr.net/pyodide/v314.0.8/full/'
      importScripts(indexURL + 'pyodide.js')
      const python = await self.loadPyodide({ indexURL })
      const input = stdin ? stdin.replace(/\r\n/g, '\n').replace(/\n$/, '').split('\n') : []
      let stdout = ''
      let stderr = ''
      let remaining = 64000
      let truncated = false
      const capture = (text, append) => {
        const line = text + '\n'
        append(line.slice(0, remaining))
        truncated ||= line.length > remaining
        remaining = Math.max(0, remaining - line.length)
      }
      python.setStdin({ stdin: () => input.shift() ?? null })
      python.setStdout({ batched: text => capture(text, line => { stdout += line }) })
      python.setStderr({ batched: text => capture(text, line => { stderr += line }) })
      self.postMessage({ type: 'ready' })
      const started = performance.now()
      let exitCode = 0
      try {
        const value = python.runPython(code)
        if (value instanceof python.ffi.PyProxy) value.destroy()
      } catch (error) {
        exitCode = 1
        capture(String(error), line => { stderr += line })
      }
      self.postMessage({
        type: 'result',
        result: { exitCode, stdout, stderr, truncated, timedOut: false, durationMs: Math.round(performance.now() - started) },
      })
    } catch {
      self.postMessage({ type: 'error' })
    }
  }
}

window.addEventListener('message', event => {
  if (event.source !== window.parent || event.origin !== window.location.origin || !event.ports[0]) return
  const [port] = event.ports
  try {
    const source = URL.createObjectURL(new Blob([`(${runPython.toString()})()`], { type: 'text/javascript' }))
    const worker = new Worker(source)
    URL.revokeObjectURL(source)
    worker.onmessage = ({ data }) => {
      port.postMessage(data)
      if (data.type !== 'ready') worker.terminate()
    }
    worker.onerror = () => {
      port.postMessage({ type: 'error' })
      worker.terminate()
    }
    worker.postMessage(event.data)
  } catch {
    port.postMessage({ type: 'error' })
  }
})
