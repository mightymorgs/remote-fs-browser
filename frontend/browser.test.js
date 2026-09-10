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

test('scan displays DNS, NetBIOS and IP together, including identical names', async () => {
  function element(tag, text) {
    return { text, children: [], append(...children) { this.children.push(...children) },
      replaceChildren(...children) { this.children = children } }
  }
  const state = {
    el: element, button: () => element(), showView() {},
    devices: element(), scanNotes: element(),
    async discover() {
      this.deviceList = browser.devicesFrom({ hosts: [
        { host: '192.0.2.1', dns_name: 'NAS', netbios_name: 'NAS', name: 'NAS', protocols: ['smb'] },
        { host: '192.0.2.2', protocols: ['nfs'] }
      ] })
    }
  }
  await browser.scanNetwork.call(state)
  assert.deepEqual(state.devices.children[0].children[1].children.map(node => node.text),
    ['DNS: NAS', 'NetBIOS: NAS', 'IP: 192.0.2.1'])
  assert.deepEqual(state.devices.children[1].children[1].children.map(node => node.text), ['IP: 192.0.2.2'])
})
