export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    cache: init?.cache ?? ((init?.method || 'GET').toUpperCase() === 'GET' ? 'no-store' : undefined),
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {})
    }
  })
  if (!res.ok) {
    const raw = await res.text()
    let message = raw || `Erro HTTP ${res.status}`
    try {
      const parsed = JSON.parse(raw)
      if (typeof parsed?.detail === 'string') {
        message = parsed.detail
      } else if (Array.isArray(parsed?.detail)) {
        message = parsed.detail.map((item: any) => {
          const loc = Array.isArray(item?.loc) ? item.loc.filter((x: any) => x !== 'body').join(' > ') : ''
          return `${loc ? `${loc}: ` : ''}${item?.msg || 'Dados inválidos'}`
        }).join(' | ')
      }
    } catch {
      // mantém o texto original
    }
    throw new Error(message)
  }
  return res.json()
}

export function query(params: Record<string, string | number | undefined | null>) {
  const qs = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') qs.set(k, String(v))
  })
  return qs.toString()
}
