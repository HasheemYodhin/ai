// Apply the saved theme before paint.
try {
  var d = document.documentElement
  var t = localStorage.getItem('dabba-theme') || (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark')
  d.classList.add(t === 'light' ? 'light' : 'dark')
  // Saved accent color (written by Settings), so there is no flash of the default.
  var a = JSON.parse(localStorage.getItem('dabba-accent') || 'null')
  if (a) for (var k in a) d.style.setProperty(k, a[k])
} catch { /* Theme storage may be unavailable. */ }
