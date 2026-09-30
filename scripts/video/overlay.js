// Injected into recorded pages only: a visible pointer, click ripples and keycap badges.
// The app itself is unchanged; these elements exist so a silent video shows what the hands are doing.
(() => {
  if (window.__rfsOverlay || location.protocol === 'file:') return
  window.__rfsOverlay = true
  const css = `
  #rfs-cursor{position:fixed;left:0;top:0;width:22px;height:22px;z-index:2147483647;pointer-events:none;transform:translate(-3px,-2px);
    transition:opacity .2s;filter:drop-shadow(0 2px 3px rgba(0,0,0,.35))}
  .rfs-ripple{position:fixed;z-index:2147483646;pointer-events:none;width:14px;height:14px;margin:-7px 0 0 -7px;border-radius:50%;
    border:2.5px solid rgba(63,111,209,.9);background:rgba(63,111,209,.18);animation:rfs-ripple .55s ease-out forwards}
  .rfs-ripple.right{border-color:rgba(214,120,40,.95);background:rgba(214,120,40,.18)}
  @keyframes rfs-ripple{to{transform:scale(3.4);opacity:0}}
  #rfs-keys{position:fixed;right:22px;bottom:70px;z-index:2147483647;pointer-events:none;display:flex;gap:8px;align-items:center;
    font:600 17px system-ui,-apple-system,"Segoe UI",sans-serif;color:#1c2024;opacity:0;transform:translateY(6px);transition:opacity .18s,transform .18s}
  #rfs-keys.on{opacity:1;transform:none}
  #rfs-keys kbd{font:inherit;min-width:34px;text-align:center;padding:7px 11px;border-radius:9px;background:#fff;border:1px solid #cfd5df;
    box-shadow:0 2px 0 #cfd5df,0 8px 22px rgba(20,24,30,.16)}
  #rfs-keys span{font-weight:500;color:#4d545c;font-size:15px}`
  const svg = '<svg viewBox="0 0 22 22" width="22" height="22"><path d="M3 2 L3 18 L7.2 14.2 L10 20.5 L12.8 19.3 L10.1 13.2 L15.8 13.2 Z" fill="#111" stroke="#fff" stroke-width="1.4" stroke-linejoin="round"/></svg>'
  let cursor, keys, hideTimer
  const mount = () => {
    const host = document.querySelector('dialog[open]') || document.body
    if (!host) return
    for (const el of [cursor, keys]) if (el.parentNode !== host) host.append(el)
    const style = document.getElementById('rfs-overlay-style')
    if (style && style.parentNode !== document.head) document.head.append(style)
  }
  const init = () => {
    const style = document.createElement('style'); style.id = 'rfs-overlay-style'; style.textContent = css; document.head.append(style)
    cursor = document.createElement('div'); cursor.id = 'rfs-cursor'; cursor.innerHTML = svg
    keys = document.createElement('div'); keys.id = 'rfs-keys'
    const start = window.__rfsPointer || { x: innerWidth * 0.62, y: innerHeight * 0.55 }
    cursor.style.left = start.x + 'px'; cursor.style.top = start.y + 'px'
    mount()
    // Modal <dialog>s live in the top layer; the pointer must follow them there to stay visible.
    new MutationObserver(mount).observe(document.documentElement, { subtree: true, childList: true, attributes: true, attributeFilter: ['open'] })
  }
  const ripple = (x, y, right) => {
    const r = document.createElement('div'); r.className = 'rfs-ripple' + (right ? ' right' : '')
    r.style.left = x + 'px'; r.style.top = y + 'px'
    ;(document.querySelector('dialog[open]') || document.body).append(r)
    setTimeout(() => r.remove(), 600)
  }
  window.__rfsKeys = (parts, note, ms = 1500) => {
    keys.innerHTML = parts.map(p => `<kbd>${p}</kbd>`).join('<span>+</span>') + (note ? `<span>${note}</span>` : '')
    keys.classList.add('on'); clearTimeout(hideTimer)
    hideTimer = setTimeout(() => keys.classList.remove('on'), ms)
  }
  addEventListener('mousemove', e => {
    if (!cursor) return
    cursor.style.left = e.clientX + 'px'; cursor.style.top = e.clientY + 'px'
  }, true)
  addEventListener('mousedown', e => {
    ripple(e.clientX, e.clientY, e.button === 2)
    const mods = [e.metaKey && '⌘', e.ctrlKey && 'Ctrl', e.shiftKey && '⇧ Shift', e.altKey && '⌥'].filter(Boolean)
    if (e.button === 2) window.__rfsKeys(['Right-click'], '', 1300)
    else if (mods.length) window.__rfsKeys([...mods], 'click', 1400)
  }, true)
  if (document.readyState === 'loading') addEventListener('DOMContentLoaded', init); else init()
})()
