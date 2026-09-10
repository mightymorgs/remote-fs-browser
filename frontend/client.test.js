import assert from 'node:assert/strict'
import test from 'node:test'

globalThis.HTMLElement = class {}
globalThis.customElements = { get: () => true }
const { RemoteFsClient } = await import('./browser.js')

test('client auth and raw downloads preserve caller authentication and cancellation', async t => {
  const calls = []
  const response = { ok: true, json: async () => ({ hostname: 'test' }) }
  t.mock.method(globalThis, 'fetch', async (...args) => { calls.push(args); return response })
  const client = new RemoteFsClient('/storage/api/', () => ({ Authorization: 'Bearer test' }), { credentials: 'include' })
  await client.login('tester', 'secret')
  assert.equal(calls[0][0], '/storage/api/login')
  assert.deepEqual(JSON.parse(calls[0][1].body), { username: 'tester', password: 'secret' })
  await client.loginStatus()
  await client.logout()
  assert.equal(calls[2][1].method, 'DELETE')
  const signal = new AbortController().signal
  assert.equal(await client.file('a/b', '/with space', 'bytes=0-9', { signal }), response)
  assert.equal(await client.downloadPart('job/id', 0, 'bytes=10-', { signal }), response)
  assert.equal(calls[4][0], '/storage/api/downloads/job%2Fid/parts/0')
  for (const [, options] of calls) {
    assert.equal(options.credentials, 'include')
    assert.equal(options.headers.Authorization, 'Bearer test')
  }
  assert.equal(calls[3][1].signal, signal)
  assert.equal(calls[4][1].headers.Range, 'bytes=10-')
})

test('stored credential discovery and file/archive operations use the API contract', async t => {
  const calls = []
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push([url, options.method, options.body && JSON.parse(options.body)])
    return { ok: true, json: async () => ({}) }
  })
  const c = new RemoteFsClient('/api')
  await c.shares('smb', 'nas', undefined, 'stored')
  await c.mkdir('sid', '/folder')
  await c.rename('sid', '/a', '/b')
  await c.copy('sid', '/a', '/b', 'target')
  await c.hostCredentials()
  await c.saveHostCredentials('nas', { username: 'user', password: 'secret' })
  await c.forgetHostCredentials('cred/id')
  await c.downloads()
  await c.estimateDownload('sid', ['/a'])
  await c.createDownload('sid', ['/a'], 'Downloads', 1048576)
  await c.controlDownload('job/id', 'pause')
  await c.controlDownload('job/id', 'resume')
  await c.purgeDownload('job/id')
  await c.controlDownload('job/id', 'forget')
  assert.deepEqual(calls[0], ['/api/discover', 'POST', { type: 'smb', host: 'nas', credential_id: 'stored' }])
  assert.deepEqual(calls[3][2], { source: '/a', destination: '/b', target_session: 'target' })
  assert.deepEqual(calls[6], ['/api/credentials/cred%2Fid', 'DELETE', undefined])
  assert.deepEqual(calls[9][2], { session: 'sid', paths: ['/a'], store: 'Downloads', part_size: 1048576 })
  assert.deepEqual(calls.slice(10).map(row => row.slice(1)), [['POST', { action: 'pause' }], ['POST', { action: 'resume' }], ['DELETE', undefined], ['POST', { action: 'forget' }]])
})

test('uploads use configured credentials and preserve progress and abort behavior', async t => {
  let xhr
  class Upload {
    constructor() { xhr = this; this.upload = {}; this.headers = {} }
    open(method, url) { this.method = method; this.url = url }
    setRequestHeader(name, value) { this.headers[name] = value }
    send(file) { this.file = file }
    abort() { this.onabort(); this.onloadend() }
  }
  const prior = globalThis.XMLHttpRequest
  globalThis.XMLHttpRequest = Upload
  t.after(() => { if (prior === undefined) delete globalThis.XMLHttpRequest; else globalThis.XMLHttpRequest = prior })
  const c = new RemoteFsClient('/api', () => ({ Authorization: 'Bearer test' }), { credentials: 'include' })
  const progress = []
  const upload = c.upload('sid', '/a', { size: 10 }, { progress: (...values) => progress.push(values) })
  assert.equal(xhr.withCredentials, true)
  assert.equal(xhr.headers.Authorization, 'Bearer test')
  xhr.upload.onprogress({ loaded: 5, total: 10 })
  xhr.status = 200; xhr.responseText = '{"written":10}'; xhr.onload(); xhr.onloadend()
  assert.deepEqual(await upload, { written: 10 })
  assert.deepEqual(progress, [[5, 10]])
  const controller = new AbortController()
  const cancelled = c.upload('sid', '/a', { size: 10 }, { signal: controller.signal })
  controller.abort()
  await assert.rejects(cancelled, /Upload cancelled/)
})
