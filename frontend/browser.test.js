import assert from 'node:assert/strict'
import test from 'node:test'

globalThis.HTMLElement = class {}
globalThis.customElements = { get: () => true }
const { RemoteFsBrowser } = await import('./browser.js')
const browser = RemoteFsBrowser.prototype

test('scan prefers names and preserves connection addresses for both API shapes', () => {
  const named = { type: 'smb', host: '192.0.2.1', label: 'nas.office' }
  assert.deepEqual(browser.devicesFrom({ groups: [{ items: [named] }] }), [named])
  assert.deepEqual(browser.devicesFrom({ hosts: [
    { host: named.host, name: named.label, protocols: ['smb', 'nfs'] },
    { host: '192.0.2.2', protocols: ['smb'] }
  ] }), [named, { ...named, type: 'nfs' }, { type: 'smb', host: '192.0.2.2', label: '192.0.2.2' }])
})

test('mapping a discovered device retains its name in the sidebar', () => {
  const state = { renderRail() {} }
  browser.rememberHost.call(state, { type: 'smb', host: '192.0.2.1', label: 'nas.office' })
  assert.deepEqual(state.mapped, [{ type: 'smb', host: '192.0.2.1', label: 'nas.office' }])
})
