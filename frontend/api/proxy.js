// Vercel serverless proxy: the website calls /api/* on its own domain, and this forwards the request to the twin API
// (a private Hugging Face Space). The Space token stays on the server (env HF_TOKEN) and never reaches the browser.
//   TWIN_API_URL  e.g. https://<user>-<space>.hf.space   (no trailing slash)
//   HF_TOKEN      a Hugging Face read token for the private Space (leave empty if the Space is public)
// In local development Vite proxies /api to http://127.0.0.1:8000 instead, and this file is not used.
export default async function handler(req, res) {
  const base = process.env.TWIN_API_URL
  if (!base) {
    res.status(500).json({ detail: 'TWIN_API_URL is not set on the Vercel project.' })
    return
  }
  // /api/now -> rewrite (vercel.json) -> /api/proxy?path=now ; keep only safe path characters
  const path = String(req.query.path || '').replace(/^\/+/, '').replace(/[^A-Za-z0-9/_.-]/g, '')
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(req.query)) {
    if (k === 'path') continue
    for (const item of Array.isArray(v) ? v : [v]) qs.append(k, item)
  }
  const url = `${base}/api/${path}${qs.toString() ? `?${qs}` : ''}`
  const headers = { accept: 'application/json' }
  if (process.env.HF_TOKEN) headers.authorization = `Bearer ${process.env.HF_TOKEN}`
  const init = { method: req.method, headers }
  if (req.method !== 'GET' && req.method !== 'HEAD') {
    headers['content-type'] = 'application/json'
    init.body = typeof req.body === 'string' ? req.body : JSON.stringify(req.body ?? {})
  }
  try {
    const r = await fetch(url, init)
    const text = await r.text()
    res.status(r.status)
    res.setHeader('content-type', r.headers.get('content-type') || 'application/json')
    res.setHeader('cache-control', 'no-store')
    res.send(text)
  } catch (err) {
    // a sleeping Space takes ~1 min to wake up; the site keeps polling and recovers by itself
    res.status(503).json({ detail: `The twin API is waking up or unreachable (${err.message}).` })
  }
}
