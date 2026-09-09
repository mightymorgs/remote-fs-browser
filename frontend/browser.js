/** Backend-neutral custom element. Properties stay in memory; no stored credentials. */
export class RemoteFsClient {
  constructor(baseUrl, headers = () => ({})) { this.baseUrl = baseUrl.replace(/\/$/, ''); this.headers = headers }
  async request(path, { method = 'GET', body, signal, raw = false } = {}) {
    const response = await fetch(this.baseUrl + path, { method, signal, headers: { ...this.headers(), ...(body ? { 'Content-Type': 'application/json' } : {}) }, ...(body ? { body: JSON.stringify(body) } : {}) })
    if (!response.ok) { const error = new Error((await response.json().catch(() => ({}))).detail || `Request failed (${response.status})`); error.status = response.status; throw error }
    return raw ? response : response.json()
  }
  discover(scan = false) { return this.request(`/discover?scan=${scan}`) }
  shares(type, host, credentials) { return this.request('/discover', { method: 'POST', body: { type, host, credentials } }) }
  connect(descriptor, credentials) { return this.request('/sessions', { method: 'POST', body: { descriptor, credentials } }) }
  list(id, path) { return this.request(`/sessions/${encodeURIComponent(id)}/list?${new URLSearchParams({ path })}`) }
  stat(id, path) { return this.request(`/sessions/${encodeURIComponent(id)}/stat?${new URLSearchParams({ path })}`) }
  descriptor(id, path) { return this.request(`/sessions/${encodeURIComponent(id)}/descriptor?${new URLSearchParams({ path })}`) }
  file(id, path, range) { return fetch(`${this.baseUrl}/sessions/${encodeURIComponent(id)}/file?${new URLSearchParams({ path })}`, { headers: { ...this.headers(), ...(range ? { Range: range } : {}) } }) }
  close(id) { return this.request(`/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' }) }
  saved() { return this.request('/saved') }
  save(descriptor, credentials, label) { return this.request('/saved', { method: 'POST', body: { descriptor, credentials, label } }) }
  forget(id) { return this.request(`/saved/${encodeURIComponent(id)}`, { method: 'DELETE' }) }
}

export class RemoteFsBrowser extends HTMLElement {
  constructor() {
    super(); this.attachShadow({ mode: 'open' }); this.path = '/'; this.session = null; this.generation = 0
  }
  connectedCallback() { this.render() }
  disconnectedCallback() { this.generation++; void this.close(); this.credentials = undefined }
  async close() {
    const id = this.session; this.session = null
    if (id && this.client) await this.client.close(id).catch(() => {})
  }
  element(tag, text, attrs = {}) {
    const node = document.createElement(tag); if (text) node.textContent = text
    Object.assign(node, attrs); return node
  }
  button(text, action) { const node = this.element('button', text, { type: 'button' }); node.onclick = action; return node }
  input(label, type = 'text') {
    const wrapper = this.element('label', label), input = this.element('input', '', { type })
    wrapper.append(input); this.form.append(wrapper); return input
  }
  render() {
    this.shadowRoot.replaceChildren()
    const style = this.element('style', `:host{display:block;font:15px system-ui;color:#172230;max-width:850px}section{border:1px solid #ccd5df;border-radius:14px;padding:22px;background:#fff}h2{margin-top:0}button,input,select{font:inherit;padding:9px 12px;border:1px solid #c4cdd7;border-radius:7px;background:white;color:inherit}button{cursor:pointer}button:hover{background:#edf5f9}button:disabled{opacity:.5;cursor:wait}label{display:grid;gap:6px}form{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}nav{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0}.entries{max-height:360px;overflow:auto;border-block:1px solid #ddd}.entry{display:flex;align-items:center;gap:16px;padding:8px}.entry button{flex:1;text-align:left;border:0}.meta{color:#607080;font-size:12px}.status{min-height:24px;margin:12px 0}code{overflow-wrap:anywhere}.primary{background:#165d79;color:white}details{flex:1 1 200px;margin:4px 0}summary{cursor:pointer;font-weight:600;margin-bottom:6px}details button{display:block;width:100%;text-align:left;margin-bottom:6px}details p{margin:0}`)
    const section = this.element('section'); section.append(this.element('h2', 'Choose storage'))
    section.append(this.element('p', this.getAttribute('mode') === 'browse' ? 'Browse folders and download files visible to this host.' : 'Browse storage visible to the remote host. Select a folder to return its location.'))
    this.form = this.element('form'); this.form.onsubmit = event => event.preventDefault()
    this.type = this.element('select'); this.type.setAttribute('aria-label','Storage type')
    for (const [value, label] of [['local','This machine'],['smb','SMB'],['nfs','NFS']]) this.type.append(this.element('option', label, { value }))
    this.form.append(this.type)
    this.version = this.element('select'); this.version.setAttribute('aria-label','NFS version')
    for (const value of ['4','3']) this.version.append(this.element('option', `NFSv${value}`, { value }))
    this.form.append(this.version)
    this.host = this.input('Server hostname / IP')
    this.location = this.input('Root, share or export')
    this.username = this.input('Username (SMB)')
    this.password = this.input('Password (SMB)', 'password')
    this.remember = this.input('Remember this location', 'checkbox'); this.remember.checked = true
    this.type.onchange = () => { this.remember.parentElement.hidden = this.type.value === 'local' }
    this.type.onchange()
    this.form.append(this.button('Discover', () => this.discover()), this.button('Connect', () => this.connect()))
    this.status = this.element('div', '', { className: 'status' }); this.status.setAttribute('role','status')
    this.locations = this.element('nav'); this.locations.setAttribute('aria-label','Discovered locations')
    this.nav = this.element('nav'); this.entries = this.element('div','',{ className:'entries' })
    this.entries.setAttribute('aria-label','Folder entries')
    this.selected = this.element('code','/')
    this.choose = this.button('Select this folder', () => this.select()); this.choose.className = 'primary'; this.choose.disabled = true; this.choose.hidden = this.getAttribute('mode') === 'browse'
    section.append(this.form, this.locations, this.status, this.nav, this.entries, this.selected, this.choose, this.button('Disconnect', () => this.disconnect()))
    this.shadowRoot.append(style, section)
  }
  async action(fn) {
    if (!this.client) { this.status.textContent = 'Set the component client property first.'; return }
    this.status.textContent = 'Loading…'
    for (const b of this.shadowRoot.querySelectorAll('button,input,select')) b.disabled = true
    try { await fn(); this.status.textContent = this.notes() }
    catch (error) { this.status.textContent = error.message; this.dispatchEvent(new CustomEvent('browser-error',{ detail: error })) }
    finally { for (const b of this.shadowRoot.querySelectorAll('button,input,select')) b.disabled = false; this.choose.disabled = !this.session }
  }
  notes() {
    const notes = []
    if (this.truncated) notes.push('Listing limit reached. Select a narrower folder or raise the service limit.')
    if (this.skipped) notes.push(`${this.skipped} entries hidden (unsupported names).`)
    return notes.join(' ')
  }
  async discover(scan) {
    await this.action(async () => {
      this.locations.replaceChildren()
      if (this.type.value === 'local' || !this.host.value) {
        const result = await this.client.discover(scan ?? this.type.value !== 'local')
        if (result.groups) await this.tree(result.groups)
        else {
          for (const root of result.roots) this.locations.append(this.button(root.root, () => { this.type.value = 'local'; this.location.value = root.root }))
          for (const host of result.hosts) this.locations.append(this.button(`${host.host} (${host.protocols.join(', ')})`, () => { this.host.value = host.host; this.type.value = host.protocols[0] }))
        }
        for (const note of result.notes || []) this.locations.append(this.element('p', note, { className: 'meta' }))
      } else {
        const result = await this.client.shares(this.type.value, this.host.value, { username: this.username.value, password: this.password.value })
        for (const location of (result.shares || result.exports || [])) {
          const name = typeof location === 'string' ? location : location.name
          this.locations.append(this.button(name, () => { this.location.value = name }))
        }
        if (!(result.shares || result.exports || []).length) this.locations.append(this.element('p', 'No locations reported. Enter a share/export manually.'))
      }
    })
  }
  async tree(groups) {
    this.savedBlock = this.element('details'); this.savedBlock.open = true
    this.locations.append(this.savedBlock)
    await this.renderSaved()
    for (const group of groups) {
      if (!group.items.length && !group.hint) continue
      const details = this.element('details'); details.open = true
      details.append(this.element('summary', group.label))
      for (const item of group.items) details.append(this.button(item.label, () => this.pick(item)))
      if (!group.items.length && group.hint) details.append(this.element('p', group.hint, { className: 'meta' }))
      this.locations.append(details)
    }
  }
  async renderSaved() {
    const block = this.savedBlock
    if (!block) return
    const result = await this.client.saved().catch(() => ({ locations: [] }))
    block.replaceChildren(this.element('summary', 'Saved'))
    block.hidden = !result.locations.length
    for (const record of result.locations) {
      const row = this.element('div', '', { className: 'entry' })
      row.append(this.button(record.label, () => this.open(record)), this.button('Forget', () => this.action(async () => { await this.client.forget(record.id); await this.renderSaved() })))
      block.append(row)
    }
  }
  async open(record) {
    await this.action(async () => {
      await this.close()
      const d = record.descriptor
      this.type.value = d.type; this.type.onchange(); this.host.value = d.host || ''; this.location.value = d.share || d.export || d.root || ''
      if (d.version) this.version.value = String(d.version)
      this.descriptor = { ...d, credential_id: record.id }; this.credentials = {}
      const generation = this.generation
      const result = await this.client.connect(this.descriptor, {})
      if (generation !== this.generation) { await this.client.close(result.id); return }
      this.session = result.id; await this.show(d.path || '/')
    })
  }
  pick(item) {
    this.type.value = item.type
    if (item.type === 'local') { this.location.value = item.root; void this.connect(); return }
    this.host.value = item.host; this.location.value = ''
    void this.discover()
  }
  async connect() {
    await this.action(async () => {
      await this.close()
      this.descriptor = this.type.value === 'local' ? { type:'local', root:this.location.value } : this.type.value === 'smb' ? { type:'smb', host:this.host.value, share:this.location.value } : { type:'nfs', host:this.host.value, export:this.location.value, version:Number(this.version.value) }
      this.credentials = { username: this.username.value, password: this.password.value }
      const generation = this.generation
      const result = await this.client.connect(this.descriptor, this.credentials)
      if (generation !== this.generation) { await this.client.close(result.id); return }
      this.session = result.id; await this.show('/')
      if (this.remember.checked && this.type.value !== 'local' && !this.storeCredentials) {
        const saved = await this.client.save(this.descriptor, this.credentials).catch(() => null)
        if (saved) { this.descriptor.credential_id = saved.id; await this.renderSaved() }
      }
    })
  }
  async show(path) {
    const generation = this.generation
    let result
    try { result = await this.client.list(this.session, path) }
    catch (error) {
      if (generation !== this.generation || !this.isConnected) return
      if (![404,410].includes(error.status)) throw error
      this.status.textContent = 'Reconnecting…'
      const opened = await this.client.connect(this.descriptor, this.credentials)
      if (generation !== this.generation || !this.isConnected) { await this.client.close(opened.id); return }
      this.session = opened.id
      result = await this.client.list(this.session, path)
    }
    if (generation !== this.generation || !this.isConnected) { await this.close(); return }
    this.path = path; this.truncated = result.truncated; this.skipped = result.skipped || 0; this.selected.textContent = path
    this.entries.replaceChildren(); this.nav.replaceChildren()
    this.nav.append(this.button('↑ Parent', () => this.action(() => this.show(path.replace(/\/[^/]+\/?$/, '') || '/'))), this.button('Refresh', () => this.action(() => this.show(path))))
    for (const item of result.entries) {
      const row = this.element('div','',{ className:'entry' })
      row.append(item.type === 'directory' ? this.button(`📁 ${item.name}`, () => this.action(() => this.show(item.path))) : this.element('span',item.name))
      row.append(this.element('span', item.type === 'directory' ? 'Folder' : `${item.size ?? '—'} bytes`, { className:'meta' }))
      if (item.modified) row.append(this.element('time',item.modified,{ className:'meta' }))
      if (item.type === 'file' && this.download) row.append(this.button('Download', () => this.download(this.session, item)))
      this.entries.append(row)
    }
    if (!result.entries.length) this.entries.append(this.element('p','This folder is empty.'))
  }
  async select() {
    await this.action(async () => {
      const descriptor = await this.client.descriptor(this.session,this.path)
      if (descriptor.type === 'smb' && this.storeCredentials) descriptor.credential_id = await this.storeCredentials(this.credentials)
      else if (descriptor.type !== 'local' && this.remember.checked) {
        const saved = await this.client.save(descriptor, this.credentials).catch(() => null)
        if (saved) { descriptor.credential_id = saved.id; await this.renderSaved() }
      }
      await this.close(); this.credentials = undefined; this.password.value = ''
      this.dispatchEvent(new CustomEvent('path-selected',{ detail:descriptor,bubbles:true,composed:true }))
    })
  }
  async disconnect() { await this.close(); this.credentials = undefined; this.password.value = ''; this.choose.disabled = true; this.entries.replaceChildren(); this.status.textContent = 'Disconnected.' }
}
if (!customElements.get('remote-fs-browser')) customElements.define('remote-fs-browser', RemoteFsBrowser)
