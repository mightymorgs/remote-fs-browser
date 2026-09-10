/**
 * Backend-neutral custom element — Daylight UI.
 * Public API is unchanged from the original frontend/browser.js:
 *   properties: client, download(id, item), storeCredentials(credentials)
 *   attributes: mode="browse"|"select", signout (renders a Sign out button)
 *   methods:    render(), discover(scan), disconnect()
 *   events:     path-selected, browser-error, sign-out
 * Properties stay in memory; no stored credentials.
 */
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

const STYLE = `
:host{
  --accent:#3f6fd1; --accent-ink:#22417d; --accent-line:#b6c6e8; --accent-wash:#eef2fb; --accent-sel:#e3ebfb;
  --ink:#1c2024; --muted:#4d545c; --dim:#6a727c; --line:#dcdfe4; --hair:#f0f1f4;
  --glass:rgba(255,255,255,.66); --glass-chrome:rgba(251,251,252,.62); --glass-rail:rgba(244,245,247,.55);
  --blur:blur(24px) saturate(1.6);
  --mono:ui-monospace,SFMono-Regular,SF Mono,Menlo,Consolas,monospace;
  display:block; height:100%; min-height:0;
  font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; color:var(--ink);
  background:linear-gradient(140deg,#e7ecf5 0%,#f4f2ef 46%,#e4edf1 100%);
}
*{box-sizing:border-box}
.app{height:100%;display:grid;grid-template-columns:288px minmax(0,1fr);min-height:0;position:relative}

button,input,select{font:inherit;color:var(--ink)}
button{cursor:pointer}
button:disabled,input:disabled,select:disabled{opacity:.55;cursor:progress}
.btn{font-size:14px;padding:8px 13px;border:1px solid #d5d9df;border-radius:8px;background:rgba(255,255,255,.75)}
.btn:hover:not(:disabled){background:#fff}
.btn.primary{background:var(--accent);border-color:#2b57ae;color:#fff;font-weight:500}
.btn.primary:hover:not(:disabled){background:#3563c4}
.btn.quiet{background:transparent;border-color:transparent;color:var(--dim)}
.btn.quiet:hover:not(:disabled){background:#e9ecf1;color:var(--ink)}
.btn.icon{width:34px;height:34px;padding:0;font-size:15px;color:var(--muted)}
input[type=text],input[type=password],input[type=search],select{
  width:100%;padding:8px 11px;border:1px solid #c8ccd3;border-radius:8px;background:rgba(255,255,255,.85);
}
input:focus-visible,select:focus-visible,button:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
label.field{display:grid;gap:6px;font-size:12px;color:var(--dim)}
label.check{display:flex;align-items:center;gap:9px;font-size:13px;color:var(--muted)}
label.check input{width:15px;height:15px;accent-color:var(--accent)}
code,.mono{font-family:var(--mono)}
.eyebrow{font:500 11px var(--mono);letter-spacing:.09em;text-transform:uppercase;color:var(--dim)}

/* ---- sidebar ---- */
aside{
  background:var(--glass-rail);backdrop-filter:var(--blur);-webkit-backdrop-filter:var(--blur);
  border-right:1px solid rgba(226,229,234,.8);display:flex;flex-direction:column;padding:14px 0;min-height:0;
}
.brand{display:flex;align-items:center;gap:9px;padding:2px 16px 14px;min-width:0}
.mark{width:18px;height:15px;border-radius:3px;background:var(--accent);flex:none}
.brand span{font:500 12px var(--mono);color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.rail{flex:1;min-height:0;overflow-y:auto;overflow-x:hidden;display:flex;flex-direction:column;gap:16px;padding-bottom:8px}
.group{display:flex;flex-direction:column;gap:2px}
.group>.eyebrow{padding:0 16px 6px}
.src{display:flex;align-items:center;gap:10px;margin:0 8px;padding:9px 8px;border:0;border-radius:8px;background:transparent;text-align:left;width:auto;min-height:40px}
.src:hover:not(:disabled){background:#e9ecf1}
.src[aria-current=true]{background:var(--accent-sel)}
.src .dot{width:14px;height:12px;border-radius:2px;background:var(--dim);flex:none}
.src[aria-current=true] .dot{background:var(--accent)}
.src .label{flex:1;min-width:0;font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.src .label.path{font-family:var(--mono)}
.src.stacked{align-items:flex-start;padding-top:8px;padding-bottom:8px}
.src .stack{display:flex;flex-direction:column;flex:1;min-width:0;gap:1px}
.src .stack .label{width:100%}
.src .stack .where{font:11.5px/1.45 var(--mono);color:var(--dim);white-space:normal;overflow-wrap:anywhere}
.src .tag{font:11px var(--mono);color:var(--dim);flex:none}
.src.sub{margin-left:26px}
.src.sub .dot{width:11px;height:10px;background:var(--accent-line)}
.src.sub[aria-current=true] .dot{background:var(--accent)}
.src.sub .label{font-size:13.5px;color:var(--muted)}
.hint{margin:4px 16px 0;font-size:12px;color:var(--dim);text-wrap:pretty}
.hint.tight{margin:0;font-size:12px}
form [data-for][hidden]{display:none}
.saved-row{display:flex;align-items:flex-start;gap:4px;position:relative}
.saved-row .src{flex:1;min-width:0;padding-right:64px}
.forget{position:absolute;top:6px;right:10px;font-size:12px;padding:5px 8px;border:1px solid #d5d9df;border-radius:7px;
  background:rgba(255,255,255,.9);color:var(--muted);opacity:0;pointer-events:none;transition:opacity .12s ease}
.saved-row:hover .forget,.saved-row:focus-within .forget{opacity:1;pointer-events:auto}
.forget:hover:not(:disabled){background:#fff;color:var(--ink)}
.rail-foot{margin-top:auto;padding:12px 10px;border-top:1px solid rgba(226,229,234,.8);display:flex;flex-direction:column;gap:8px;max-height:min(66vh,560px);overflow-y:auto;overflow-x:hidden}
.rail-foot .btn{width:100%;text-align:left}

/* ---- connect form ---- */
form{display:flex;flex-direction:column;gap:10px;padding:2px 0 4px}
form[hidden]{display:none}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.pair label.field{min-width:0}

/* ---- pane ---- */
.pane{display:flex;flex-direction:column;min-width:0;min-height:0}
.chrome{display:flex;align-items:center;gap:10px;padding:12px 16px;border-bottom:1px solid rgba(230,232,236,.85);
  background:var(--glass-chrome);backdrop-filter:var(--blur);-webkit-backdrop-filter:var(--blur)}
.crumbs{flex:1;min-width:0;display:flex;align-items:center;gap:6px;font:14px var(--mono);overflow:hidden;white-space:nowrap}
.crumbs button{border:0;background:transparent;padding:0;font:inherit;color:var(--dim)}
.crumbs button:hover:not(:disabled){color:var(--accent)}
.crumbs .sep{color:#c0c5cc}
.crumbs .here{color:var(--ink);font-weight:500;overflow:hidden;text-overflow:ellipsis}
.sheet-toggle{display:none}
.thead,.row{display:grid;grid-template-columns:minmax(0,1fr) 110px 180px 112px;gap:16px;align-items:center}
.thead{padding:9px 20px;border-bottom:1px solid rgba(230,232,236,.85);background:rgba(248,249,250,.66);
  backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);font:500 11px var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--dim)}
.thead .size,.row .size{text-align:right}
.list{flex:1;min-height:0;overflow:auto;background:var(--glass);backdrop-filter:blur(20px) saturate(1.4);-webkit-backdrop-filter:blur(20px) saturate(1.4)}
.row{padding:11px 20px;border:0;border-bottom:1px solid var(--hair);background:transparent;width:100%;text-align:left;min-height:44px}
.row:hover:not(:disabled){background:#f6f8fc}
.row.plain{cursor:default}
.nm{display:flex;align-items:center;gap:11px;min-width:0}
.nm .dot{width:15px;height:13px;border-radius:2.5px;background:#c0c5cc;flex:none}
.nm.dir .dot{background:var(--accent)}
.nm .stack{display:flex;flex-direction:column;min-width:0}
.nm .name{font-size:14.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.nm .sub{display:none;font:12px var(--mono);color:var(--dim)}
.nm .sub-date{display:none}
.row .size,.row .mod{font:13px var(--mono);color:var(--dim)}
.row .act{display:flex;justify-content:flex-end}
.row .act .btn{font-size:13px;padding:5px 11px;border-radius:7px}
.row .act .btn:hover:not(:disabled){background:var(--accent-wash);border-color:var(--accent-line)}
.row .chev{color:#c0c5cc}

.scan{flex:1;min-height:0;overflow:auto;padding:20px;display:flex;flex-direction:column;gap:16px;
  background:var(--glass);backdrop-filter:blur(20px) saturate(1.4);-webkit-backdrop-filter:blur(20px) saturate(1.4)}
.scan[hidden]{display:none}
.scan-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}
.scan-title{display:flex;flex-direction:column;gap:3px;min-width:0}
.scan-title strong{font-size:17px;font-weight:600}
.scan-title span{font-size:13px;color:var(--muted);text-wrap:pretty}
.devices{display:flex;flex-direction:column;gap:8px;max-width:640px}
.device{display:flex;align-items:center;gap:12px;width:100%;min-height:52px;padding:12px 14px;text-align:left;
  border:1px solid #e2e5ea;border-radius:11px;background:rgba(255,255,255,.8)}
.device:hover:not(:disabled){border-color:var(--accent-line);background:#fff}
.device .dot{width:15px;height:13px;border-radius:2.5px;background:var(--accent);flex:none}
.device .name{flex:1;min-width:0;font:14.5px var(--mono);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.device .tag{font:11px var(--mono);color:var(--dim);border:1px solid #d5d9df;border-radius:999px;padding:3px 9px;flex:none}
.scan-notes{display:flex;flex-direction:column;gap:6px;max-width:640px}
.scan-notes p{margin:0;font-size:12px;color:var(--dim);text-wrap:pretty}
.modal{position:absolute;inset:0;z-index:5;display:grid;place-items:center;background:rgba(20,24,30,.3)}
.modal[hidden]{display:none}
.modal .sheet{width:min(390px,calc(100% - 32px));display:flex;flex-direction:column;gap:14px;padding:22px;
  background:#fff;border:1px solid var(--line);border-radius:14px;box-shadow:0 18px 44px rgba(20,24,30,.2)}
.modal .lede{display:flex;flex-direction:column;gap:4px}
.modal .lede strong{font:16px var(--mono);font-weight:600}
.modal .lede span{font-size:12.5px;color:var(--dim);text-wrap:pretty}
.modal .sheet-acts{display:flex;justify-content:flex-end;gap:9px;margin-top:2px}
.blank{display:flex;flex-direction:column;align-items:flex-start;gap:8px;padding:34px 20px}
.blank .box{width:26px;height:22px;border-radius:4px;border:1.5px dashed #c0c5cc}
.blank strong{font-size:15px;font-weight:500}
.blank span{font-size:13px;color:var(--dim)}
.skeleton{padding:16px 20px;display:flex;flex-direction:column;gap:9px}
.skeleton i{height:13px;border-radius:4px;background:#e6e8ec;animation:rfb-pulse 1.4s ease-in-out infinite}
.skeleton i:nth-child(2){width:52%;animation-delay:.2s}.skeleton i:nth-child(1){width:70%}.skeleton i:nth-child(3){width:61%;animation-delay:.4s}
@keyframes rfb-pulse{0%,100%{opacity:.35}50%{opacity:.8}}
.notice{display:flex;gap:12px;margin:14px 20px;padding:14px;border-radius:10px;border:1px solid var(--accent-line);background:var(--accent-wash)}
.notice .bar{width:4px;border-radius:2px;background:var(--accent);flex:none}
.notice .body{display:flex;flex-direction:column;gap:5px;min-width:0}
.notice strong{font-size:14.5px;font-weight:500;color:var(--accent-ink)}
.notice span{font-size:13px;color:var(--accent-ink);text-wrap:pretty}
.notice.bad{border-color:#f0c9c4;background:#fdf1ef}
.notice.bad .bar{background:#b4402f}.notice.bad strong,.notice.bad span{color:#7e2c20}
.notice .row-actions{display:flex;gap:9px;margin-top:4px}

.foot{display:flex;align-items:center;gap:12px;padding:10px 20px;border-top:1px solid rgba(230,232,236,.85);
  background:var(--glass-chrome);backdrop-filter:var(--blur);-webkit-backdrop-filter:var(--blur);flex-wrap:wrap}
.foot .count{font-size:13px;color:var(--muted)}
.pill{font-size:12.5px;color:#8a5a12;background:#fdf3e0;border:1px solid #f0dcb4;padding:4px 10px;border-radius:999px}
.pill[hidden]{display:none}
.session{font:13px var(--mono);color:var(--dim)}
.foot [data-disconnect]{margin-left:auto}
.picker{display:flex;flex-direction:column;gap:10px;padding:14px 20px;border-top:1px solid rgba(230,232,236,.85);
  background:rgba(248,249,250,.66);backdrop-filter:var(--blur);-webkit-backdrop-filter:var(--blur)}
.picker[hidden]{display:none}
.picker .out{display:flex;align-items:flex-start;gap:12px}
.picker pre{flex:1;min-width:0;margin:0;font:13px/1.55 var(--mono);background:rgba(255,255,255,.85);
  border:1px solid #e2e5ea;border-radius:9px;padding:12px 14px;max-height:110px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere}
.picker .acts{display:flex;flex-direction:column;gap:8px}
.picker .acts .btn{white-space:nowrap;padding:10px 16px}

/* ---- tablet ---- */
@media (max-width:1100px){
  .app{grid-template-columns:244px minmax(0,1fr)}
  .thead,.row{grid-template-columns:minmax(0,1fr) 150px 104px}
  .thead .size,.row .size{display:none}
  .nm .sub{display:block}
  .btn{min-height:44px}.btn.icon{width:44px;height:44px}
  .src{min-height:44px}
  .session{display:none}
}
/* ---- mobile: sidebar becomes a sources sheet ---- */
@media (max-width:720px){
  .app{grid-template-columns:minmax(0,1fr)}
  aside{border-right:0}
  .app[data-view=browse] aside{display:none}
  .app[data-view=sources] .pane{display:none}
  .sheet-toggle{display:inline-flex;align-items:center;gap:6px;color:var(--accent)}
  .chrome{flex-wrap:wrap;padding:12px}
  [data-shortlist]{order:3;width:100%}
  .crumbs{font-size:13px}
  .thead{display:none}
  .row{grid-template-columns:minmax(0,1fr) auto;gap:12px;padding:13px 14px}
  .row .mod{display:none}
  .nm .sub-date{display:inline}
  .nm .name{font-size:15.5px}
  .picker,.foot{padding-bottom:20px}
  .picker .out{flex-direction:column}
  .picker .acts{flex-direction:row;width:100%}
  .picker .acts .btn{flex:1;min-height:48px}
}
`

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
  get mode() { return this.getAttribute('mode') === 'select' ? 'select' : 'browse' }

  render() {
    const select = this.mode === 'select'
    this.shadowRoot.innerHTML = `<style>${STYLE}</style>
<div class="app" part="app" data-view="sources">
  <aside>
    <div class="brand"><span class="mark"></span><span data-host>Choose storage</span></div>
    <div class="rail">
      <div class="group" data-saved hidden>
        <p class="eyebrow">Shortlist</p>
        <div data-saved-list></div>
      </div>
      <div class="group" data-locations>
        <p class="eyebrow">Locations</p>
        <p class="hint">Sign in, then discover the roots, shares and exports this host can see.</p>
      </div>
    </div>
    <div class="rail-foot">
      <button type="button" class="btn" data-scan-btn>Scan network</button>
      ${select ? '' : '<button type="button" class="btn" data-add aria-expanded="false">+ Add a location</button>'}
      <form ${select ? '' : 'hidden'} data-form>
        <p class="eyebrow">${select ? 'Connect to' : 'SMB or NFS details'}</p>
        <label class="field">Type
          <select data-type aria-label="Storage type">
            <option value="local">This machine</option>
            <option value="smb">SMB share</option>
            <option value="nfs">NFS export</option>
          </select>
        </label>

        <label class="field" data-for="local">Root folder on this host
          <input type="text" data-root placeholder="/srv/media" autocomplete="off">
        </label>

        <label class="field" data-for="smb nfs">Server hostname / IP
          <input type="text" data-host-input placeholder="nas.example" autocomplete="off">
        </label>

        <label class="field" data-for="smb">Share name
          <input type="text" data-share placeholder="Projects" autocomplete="off">
        </label>
        <div class="pair" data-for="smb">
          <label class="field">Username<input type="text" data-username placeholder="media-reader" autocomplete="off"></label>
          <label class="field">Password<input type="password" data-password autocomplete="off"></label>
        </div>
        <label class="field" data-for="smb">Domain (optional)
          <input type="text" data-domain placeholder="WORKGROUP" autocomplete="off">
        </label>
        <p class="hint tight" data-for="smb">NTLM over SMB2/3 on port 445. A domain here is applied as <code>DOMAIN\\username</code>.</p>

        <label class="field" data-for="nfs">Export path
          <input type="text" data-export placeholder="/exports/media" autocomplete="off">
        </label>
        <label class="field" data-for="nfs">NFS version
          <select data-version aria-label="NFS version"><option value="4">NFSv4</option><option value="3">NFSv3</option></select>
        </label>
        <p class="hint tight" data-for="nfs">No credentials: access uses the service account's AUTH_SYS UID/GID. NFSv4-only servers may not list exports — enter the absolute path.</p>

        <div class="pair">
          <button type="button" class="btn" data-discover data-for="smb nfs">Discover</button>
          <button type="button" class="btn primary" data-connect>Connect</button>
        </div>
      </form>
    </div>
  </aside>

  <div class="pane">
    <div class="chrome">
      <button type="button" class="btn sheet-toggle" data-sheet>‹ Sources</button>
      <button type="button" class="btn icon" data-up title="Parent folder" aria-label="Parent folder">‹</button>
      <nav class="crumbs" data-crumbs aria-label="Current path"><span class="here">No location connected</span></nav>
      <button type="button" class="btn" data-shortlist disabled>Save folder to shortlist</button>
      <button type="button" class="btn icon" data-refresh title="Refresh" aria-label="Refresh">↻</button>
      ${this.hasAttribute('signout') ? '<button type="button" class="btn" data-signout>Sign out</button>' : ''}
    </div>
    <div class="thead" data-thead aria-hidden="true"><span>Name</span><span class="size">Size</span><span class="mod">Modified</span><span></span></div>
    <div class="list" data-list role="list" aria-label="Folder entries"></div>
    <section class="scan" data-scan hidden aria-label="Network scan">
      <div class="scan-head">
        <div class="scan-title">
          <p class="eyebrow">Network scan</p>
          <strong>Devices on this network</strong>
          <span>Pick a device to map a share or export from it. Nothing is mounted on this host.</span>
        </div>
        <button type="button" class="btn" data-scan-close>Close</button>
      </div>
      <div class="devices" data-devices></div>
      <div class="scan-notes" data-scan-notes></div>
    </section>
    <div class="picker" data-picker ${select ? '' : 'hidden'}>
      <p class="eyebrow">Descriptor</p>
      <div class="out">
        <pre data-descriptor>Connect and choose a folder.</pre>
        <div class="acts">
          <button type="button" class="btn primary" data-select disabled>Select this folder</button>
          <button type="button" class="btn" data-copy>Copy descriptor</button>
        </div>
      </div>
    </div>
    <div class="foot">
      <span class="count" data-count>Not connected</span>
      <span class="pill" data-pill hidden></span>
      <span class="session" data-session></span>
      <button type="button" class="btn" data-disconnect>Disconnect</button>
    </div>
  </div>

  <div class="modal" data-modal hidden>
    <form class="sheet" data-modal-form>
      <div class="lede">
        <p class="eyebrow">SMB sign-in</p>
        <strong data-modal-host>nas.example</strong>
        <span>NTLM over SMB2/3 on port 445. Credentials are held in memory for this session only.</span>
      </div>
      <label class="field">Username<input type="text" data-modal-user autocomplete="off"></label>
      <label class="field">Password<input type="password" data-modal-pass autocomplete="off"></label>
      <label class="field">Domain (optional)<input type="text" data-modal-domain placeholder="WORKGROUP" autocomplete="off"></label>
      <div class="sheet-acts">
        <button type="button" class="btn" data-modal-cancel>Cancel</button>
        <button type="submit" class="btn primary">List shares</button>
      </div>
    </form>
  </div>
</div>`

    const q = selector => this.shadowRoot.querySelector(selector)
    this.app = q('.app')
    this.form = q('[data-form]')
    this.type = q('[data-type]'); this.version = q('[data-version]')
    this.host = q('[data-host-input]')
    this.root = q('[data-root]'); this.share = q('[data-share]'); this.export = q('[data-export]')
    this.username = q('[data-username]'); this.password = q('[data-password]'); this.domain = q('[data-domain]')
    this.savedBlock = q('[data-saved]'); this.savedList = q('[data-saved-list]')
    this.locations = q('[data-locations]'); this.hostLabel = q('[data-host]')
    this.list = q('[data-list]'); this.crumbs = q('[data-crumbs]')
    this.count = q('[data-count]'); this.pill = q('[data-pill]'); this.sessionLabel = q('[data-session]')
    this.picker = q('[data-picker]'); this.descriptorOut = q('[data-descriptor]')
    this.choose = q('[data-select]'); this.shortlist = q('[data-shortlist]')
    this.thead = q('[data-thead]'); this.scan = q('[data-scan]'); this.devices = q('[data-devices]')
    this.scanNotes = q('[data-scan-notes]'); this.modal = q('[data-modal]')

    this.type.onchange = () => {
      for (const node of this.shadowRoot.querySelectorAll('form [data-for]')) {
        node.hidden = !node.dataset.for.split(' ').includes(this.type.value)
      }
    }
    this.type.onchange()
    q('[data-discover]').onclick = () => this.discover()
    q('[data-connect]').onclick = () => this.connect()
    const add = this.addButton = q('[data-add]')
    if (add) add.onclick = () => {
      const open = this.form.hidden
      this.form.hidden = !open
      add.setAttribute('aria-expanded', String(open))
      add.textContent = open ? '− Cancel' : '+ Add a location'
      if (!open) return
      if (this.type.value === 'local') { this.type.value = 'smb'; this.type.onchange() }
      this.host.focus()
      const foot = this.shadowRoot.querySelector('.rail-foot')
      foot.scrollTop = foot.scrollHeight
    }
    q('[data-up]').onclick = () => this.back()
    q('[data-refresh]').onclick = () => this.session && this.action(() => this.show(this.path))
    q('[data-disconnect]').onclick = () => this.disconnect()
    q('[data-sheet]').onclick = () => { this.app.dataset.view = 'sources' }
    q('[data-scan-btn]').onclick = () => this.scanNetwork()
    q('[data-scan-close]').onclick = () => this.showView('files')
    q('[data-modal-cancel]').onclick = () => this.closeModal(null)
    this.modal.onclick = event => { if (event.target === this.modal) this.closeModal(null) }
    this.modal.onkeydown = event => { if (event.key === 'Escape') { event.stopPropagation(); this.closeModal(null) } }
    q('[data-modal-form]').onsubmit = event => {
      event.preventDefault()
      this.closeModal({ username: q('[data-modal-user]').value, password: q('[data-modal-pass]').value, domain: q('[data-modal-domain]').value })
    }
    if (q('[data-signout]')) q('[data-signout]').onclick = () => this.dispatchEvent(new CustomEvent('sign-out', { bubbles: true, composed: true }))
    this.choose.onclick = () => this.select()
    q('[data-copy]').onclick = () => this.copyDescriptor()
    this.shortlist.onclick = () => this.saveToShortlist()
    this.entries = []
  }

  /* ---------- helpers ---------- */
  el(tag, text, className) {
    const node = document.createElement(tag)
    if (text != null) node.textContent = text
    if (className) node.className = className
    return node
  }
  button(text, action, className = 'btn') {
    const node = this.el('button', text, className); node.type = 'button'; node.onclick = action; return node
  }
  where(descriptor = {}) {
    const folder = descriptor.path && descriptor.path !== '/' ? descriptor.path : ''
    if (descriptor.type === 'smb') return `SMB · smb://${descriptor.host}/${descriptor.share}${folder}`
    if (descriptor.type === 'nfs') return `NFSv${descriptor.version ?? 4} · nfs://${descriptor.host}${this.absolute(descriptor.export ?? '')}${folder}`
    return `Local · ${descriptor.root ?? ''}${folder}`
  }
  field() { return this.type.value === 'local' ? this.root : this.type.value === 'smb' ? this.share : this.export }
  /** clean_descriptor rejects a relative export, so force the leading slash. */
  absolute(value) { return value && !value.startsWith('/') ? '/' + value : value }
  target() { return this.field().value || this.host.value }
  creds() {
    if (this.type.value !== 'smb') return {}
    const credentials = { username: this.username.value, password: this.password.value }
    if (this.domain.value) credentials.domain = this.domain.value
    return credentials
  }
  bytes(size) {
    if (size == null) return '—'
    const units = ['B', 'KB', 'MB', 'GB', 'TB']
    let value = size, unit = 0
    while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit++ }
    return `${unit === 0 ? value : value.toFixed(value < 10 ? 2 : 1)} ${units[unit]}`
  }
  when(iso) {
    if (!iso) return 'unknown'
    const date = new Date(iso)
    if (Number.isNaN(date.getTime())) return iso
    return date.toLocaleString(undefined, { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
  }
  setStatus(text) { this.count.textContent = text }
  showNotice(kind, title, detail, actions = []) {
    this.list.replaceChildren()
    const notice = this.el('div', null, `notice ${kind}`)
    notice.append(this.el('div', null, 'bar'))
    const body = this.el('div', null, 'body')
    body.append(this.el('strong', title))
    if (detail) body.append(this.el('span', detail))
    if (actions.length) {
      const bar = this.el('div', null, 'row-actions')
      for (const [label, action] of actions) bar.append(this.button(label, action))
      body.append(bar)
    }
    notice.append(body); this.list.append(notice)
  }
  skeleton(message) {
    this.list.replaceChildren()
    if (message) { const p = this.el('p', message, 'hint'); p.style.margin = '16px 20px 0'; this.list.append(p) }
    const box = this.el('div', null, 'skeleton')
    box.append(this.el('i'), this.el('i'), this.el('i'))
    this.list.append(box)
  }

  async action(fn) {
    if (!this.client) { this.setStatus('Set the component client property first.'); return }
    const controls = this.shadowRoot.querySelectorAll('button,input,select')
    for (const control of controls) control.disabled = true
    try { await fn(); this.notes() }
    catch (error) {
      this.showNotice('bad', error.status ? `${error.status} — ${error.message}` : error.message, null,
        [['Retry', () => this.session ? this.action(() => this.show(this.path)) : this.connect()]])
      this.setStatus('Request failed')
      this.dispatchEvent(new CustomEvent('browser-error', { detail: error }))
    }
    finally {
      for (const control of controls) control.disabled = false
      this.choose.disabled = !this.session
      this.shortlist.disabled = !this.session || this.shortlistAvailable === false
    }
  }
  notes() {
    const notes = []
    if (this.truncated) notes.push('Listing limit reached — narrow the folder or raise max_entries')
    if (this.skipped) notes.push(`${this.skipped} entries hidden (unsupported names)`)
    this.pill.textContent = notes.join(' · ')
    this.pill.hidden = !notes.length
  }

  /* ---------- discovery ---------- */
  /** Startup: local roots only. Network devices come from an explicit scan. */
  async discover(scan) {
    await this.action(async () => {
      const result = await this.client.discover(scan ?? false)
      this.roots = this.rootsFrom(result)
      if (scan) { this.deviceList = this.devicesFrom(result); this.notesList = result.notes || [] }
      await this.renderSaved()
      this.renderRail()
    })
  }
  rootsFrom(result) {
    if (result.groups) return result.groups.flatMap(group => group.items.filter(item => item.type === 'local'))
    return (result.roots || []).map(root => ({ type: 'local', label: root.root, root: root.root }))
  }
  /** One entry per host+protocol: a mapped location is always one or the other. */
  devicesFrom(result) {
    const hosts = result.groups
      ? result.groups.flatMap(group => group.items.filter(item => item.host))
      : (result.hosts || [])
    return hosts.flatMap(host => {
      const protocols = host.protocols?.length ? host.protocols : [host.type]
      return protocols.filter(Boolean).map(protocol => ({ type: protocol, host: host.host, label: host.label || host.name || host.host }))
    })
  }
  /** The scan is a view of its own: devices to map, with the scan's own bounds noted there. */
  async scanNetwork() {
    this.showView('scan')
    this.devices.replaceChildren()
    this.scanNotes.replaceChildren(this.el('p', 'Probing permitted ranges…'))
    await this.discover(true)
    this.devices.replaceChildren()
    for (const device of this.deviceList || []) {
      const node = this.button('', () => this.mapDevice(device), 'device')
      node.append(this.el('span', null, 'dot'), this.el('span', device.label === device.host ? device.host : `${device.label} (${device.host})`, 'name'), this.el('span', device.type.toUpperCase(), 'tag'))
      this.devices.append(node)
    }
    if (!(this.deviceList || []).length) {
      const blank = this.el('div', null, 'blank')
      blank.append(this.el('div', null, 'box'), this.el('strong', 'No devices answered.'),
        this.el('span', 'Discovery only probes explicitly permitted ranges. Add the host by hand instead.'))
      this.devices.append(blank)
    }
    this.scanNotes.replaceChildren()
    for (const note of this.notesList || []) this.scanNotes.append(this.el('p', note))
  }
  /** SMB devices ask for credentials first; NFS has none to ask for. */
  async mapDevice(device) {
    this.type.value = device.type; this.type.onchange()
    this.host.value = device.host
    if (device.type === 'smb') {
      const credentials = await this.askCredentials(device.host)
      if (!credentials) return
      this.username.value = credentials.username
      this.password.value = credentials.password
      this.domain.value = credentials.domain || ''
    }
    this.rememberHost(device)
    this.showView('files')
    await this.loadShares(device)
  }
  askCredentials(host) {
    const q = selector => this.shadowRoot.querySelector(selector)
    q('[data-modal-host]').textContent = host
    q('[data-modal-user]').value = this.username.value
    q('[data-modal-pass]').value = ''
    q('[data-modal-domain]').value = this.domain.value
    this.modal.hidden = false
    q('[data-modal-user]').focus()
    return new Promise(resolve => { this.modalResolve = resolve })
  }
  closeModal(value) {
    this.modal.hidden = true
    const resolve = this.modalResolve; this.modalResolve = null
    if (resolve) resolve(value)
  }
  showView(view) {
    this.view = view
    const files = view === 'files'
    this.scan.hidden = files
    this.list.hidden = !files
    this.thead.hidden = !files
  }
  /** Mapped hosts persist in the rail; the rail never shows raw scan output. */
  rememberHost(device) {
    this.mapped = this.mapped || []
    if (!this.mapped.some(item => item.type === device.type && item.host === device.host)) {
      this.mapped = [...this.mapped, { type: device.type, host: device.host, label: device.host }]
    }
    this.renderRail()
  }
  /** Enumerate one host's shares/exports and hang them under that host in the rail. */
  async loadShares(item) {
    await this.action(async () => {
      this.activeHost = item.host; this.activeType = item.type
      this.hostShares = this.hostShares || {}
      const result = await this.client.shares(item.type, item.host, this.creds())
      const found = result.shares || result.exports || []
      this.hostShares[`${item.type}:${item.host}`] = found
        .map(location => (typeof location === 'string' ? location : location.name))
        .map(name => (item.type === 'nfs' ? this.absolute(name) : name))
      await this.close()
      this.entries = []; this.pill.hidden = true; this.sessionLabel.textContent = ''
      this.choose.disabled = true; this.shortlist.disabled = true
      this.crumbs.replaceChildren(this.el('span', `${item.type}://${item.host}`, 'here'))
      this.setStatus(`${item.type === 'nfs' ? 'Exports' : 'Shares'} on ${item.host}`)
      this.renderRail()
      this.prompt(`Choose ${item.type === 'nfs' ? 'an export' : 'a share'}`, `Pick one of the ${item.type === 'nfs' ? 'exports' : 'shares'} listed under ${item.host}, or enter it by hand under “Add a location”.`)
    })
  }
  renderRail() {
    this.locations.replaceChildren()
    const groups = [
      { label: 'This machine', items: this.roots || [] },
      { label: 'Network', items: this.mapped || [] }
    ]
    for (const group of groups) {
      if (!group.items.length) continue
      this.locations.append(this.el('p', group.label, 'eyebrow'))
      for (const item of group.items) {
        const local = item.type === 'local'
        const connected = this.session && this.descriptor?.type === item.type && this.descriptor?.host === item.host
        const active = local
          ? this.session && this.descriptor?.type === 'local' && this.descriptor.root === item.root
          : connected || (!this.session && this.activeHost === item.host && this.activeType === item.type)
        const node = this.source(item.label, local, () => this.pick(item), local ? undefined : item.type.toUpperCase())
        if (active) node.setAttribute('aria-current', 'true')
        this.locations.append(node)
        if (local) continue
        const key = `${item.type}:${item.host}`
        for (const name of (this.hostShares?.[key] || [])) {
          const share = this.source(name, false, () => this.openShare(item, name), undefined, 'src sub')
          const open = this.session && this.descriptor?.type === item.type && this.descriptor?.host === item.host && (this.descriptor.share || this.descriptor.export) === name
          if (open) share.setAttribute('aria-current', 'true')
          this.locations.append(share)
        }
        if (this.hostShares?.[key]?.length === 0) this.locations.append(this.el('p', `No ${item.type === 'nfs' ? 'exports' : 'shares'} reported. Enter one by hand under “Add a location”.`, 'hint'))
      }
    }
    if (!(this.roots || []).length && !(this.mapped || []).length) {
      this.locations.append(this.el('p', 'Nothing mapped yet. Scan the network or add a location by hand.', 'hint'))
    }
  }
  openShare(item, name) {
    this.type.value = item.type; this.type.onchange()
    this.host.value = item.host
    this.field().value = item.type === 'nfs' ? this.absolute(name) : name
    void this.connect()
  }
  source(label, path, action, tag, className = 'src') {
    const node = this.button('', action, className)
    node.append(this.el('span', null, 'dot'), this.el('span', label, `label${path ? ' path' : ''}`))
    if (tag) node.append(this.el('span', tag, 'tag'))
    return node
  }
  prompt(title, detail) {
    this.list.replaceChildren()
    const blank = this.el('div', null, 'blank')
    blank.append(this.el('div', null, 'box'), this.el('strong', title), this.el('span', detail))
    this.list.append(blank)
  }
  async renderSaved() {
    const result = await this.client.saved().catch(() => ({ locations: [], available: false }))
    this.shortlistAvailable = result.available !== false
    if (!this.shortlistAvailable) this.shortlist.title = 'This service runs without a saved-locations store, so folders cannot be shortlisted.'
    this.savedList.replaceChildren()
    this.savedBlock.hidden = !result.locations.length
    for (const record of result.locations) {
      const row = this.el('div', null, 'saved-row')
      const node = this.button('', () => this.open(record), 'src stacked')
      const stack = this.el('span', null, 'stack')
      const place = this.where(record.descriptor)
      const name = this.el('span', record.label, 'label')
      stack.append(name, this.el('span', place, 'where'))
      node.title = `${record.label}\n${place}`
      node.append(this.el('span', null, 'dot'), stack)
      row.append(node, this.button('Forget', () => this.action(async () => { await this.client.forget(record.id); await this.renderSaved() }), 'forget'))
      this.savedList.append(row)
    }
  }

  /* ---------- sessions ---------- */
  async open(record) {
    await this.action(async () => {
      await this.close()
      const d = record.descriptor
      this.type.value = d.type; this.type.onchange()
      this.host.value = d.host || ''
      this.root.value = d.root || ''; this.share.value = d.share || ''; this.export.value = d.export || ''
      if (d.version) this.version.value = String(d.version)
      this.descriptor = { ...d, credential_id: record.id }; this.credentials = {}
      this.skeleton(`Connecting to ${record.label}…`)
      const generation = this.generation
      const result = await this.client.connect(this.descriptor, {})
      if (generation !== this.generation) { await this.client.close(result.id); return }
      this.session = result.id; await this.show(d.path || '/')
    })
  }
  pick(item) {
    this.type.value = item.type; this.type.onchange()
    if (item.type === 'local') { this.root.value = item.root; void this.connect(); return }
    this.host.value = item.host; this.share.value = ''; this.export.value = ''
    if (this.hostShares?.[`${item.type}:${item.host}`]) { this.activeHost = item.host; this.activeType = item.type; this.renderRail(); return }
    void this.loadShares(item)
  }
  async connect() {
    await this.action(async () => {
      await this.close()
      this.descriptor = this.type.value === 'local' ? { type: 'local', root: this.root.value }
        : this.type.value === 'smb' ? { type: 'smb', host: this.host.value, share: this.share.value }
          : { type: 'nfs', host: this.host.value, export: this.absolute(this.export.value), version: Number(this.version.value) }
      this.credentials = this.creds()
      this.skeleton(`Connecting to ${this.target()}…`)
      const generation = this.generation
      const result = await this.client.connect(this.descriptor, this.credentials)
      if (generation !== this.generation) { await this.client.close(result.id); return }
      this.session = result.id
      if (this.descriptor.host) this.rememberHost({ type: this.descriptor.type, host: this.descriptor.host })
      this.form.hidden = this.mode !== 'select'
      if (this.addButton) { this.addButton.setAttribute('aria-expanded', 'false'); this.addButton.textContent = '+ Add a location' }
      await this.show('/')
    })
  }

  /* ---------- listing ---------- */
  async show(path) {
    const generation = this.generation
    let result
    try { result = await this.client.list(this.session, path) }
    catch (error) {
      if (generation !== this.generation || !this.isConnected) return
      if (![404, 410].includes(error.status)) throw error
      this.showNotice('', 'Session expired — reconnecting…', `Reopening the same location and returning you to ${path}.`)
      const opened = await this.client.connect(this.descriptor, this.credentials)
      if (generation !== this.generation || !this.isConnected) { await this.client.close(opened.id); return }
      this.session = opened.id
      result = await this.client.list(this.session, path)
    }
    if (generation !== this.generation || !this.isConnected) { await this.close(); return }
    this.path = path; this.truncated = result.truncated; this.skipped = result.skipped || 0
    this.entries = result.entries
    this.app.dataset.view = 'browse'
    this.showView('files')
    this.sessionLabel.textContent = `${this.descriptor?.type ?? ''} · session ${String(this.session).slice(0, 4)}`
    this.renderCrumbs(path)
    this.renderEntries()
    this.renderRail()
    if (this.mode === 'select') void this.previewDescriptor()
  }
  /** Back: up one folder, then out of the share, then out of the location. */
  back() {
    if (this.session && this.path !== '/') return this.action(() => this.show(this.path.replace(/\/[^/]+\/?$/, '') || '/'))
    if (this.session && this.descriptor?.type !== 'local') return this.leaveShare()
    return this.disconnect()
  }
  /** Drop the session but keep the host selected, so the rail's share list is the next step up. */
  async leaveShare() {
    const host = this.descriptor?.host
    const type = this.descriptor?.type
    await this.close()
    this.entries = []; this.pill.hidden = true; this.sessionLabel.textContent = ''
    this.choose.disabled = true
    this.crumbs.replaceChildren(this.el('span', type === 'nfs' ? `nfs://${host}` : `smb://${host}`, 'here'))
    this.setStatus(`Shares on ${host}`)
    this.app.dataset.view = 'sources'
    this.activeHost = host; this.activeType = type
    if (this.hostShares?.[`${type}:${host}`]) { this.renderRail(); this.prompt('Choose a share', `Pick one of the shares listed under ${host}.`) }
    else await this.loadShares({ type, host })
  }
  renderCrumbs(path) {
    const descriptor = this.descriptor || {}
    this.crumbs.replaceChildren()
    const parts = path.split('/').filter(Boolean)
    const crumb = (text, action) => { const node = this.button(text, action); node.className = ''; return node }
    if (descriptor.type === 'local') {
      this.crumbs.append(crumb(descriptor.root || '/', () => this.action(() => this.show('/'))))
    } else {
      const scheme = descriptor.type === 'nfs' ? 'nfs://' : 'smb://'
      this.crumbs.append(crumb(scheme + (descriptor.host || ''), () => this.leaveShare()))
      const share = descriptor.share || (descriptor.export ? descriptor.export.replace(/^\//, '') : '')
      if (share) {
        this.crumbs.append(this.el('span', '/', 'sep'))
        this.crumbs.append(crumb(share, () => this.action(() => this.show('/'))))
      }
    }
    parts.forEach((part, index) => {
      this.crumbs.append(this.el('span', '/', 'sep'))
      if (index === parts.length - 1) { this.crumbs.append(this.el('span', part, 'here')); return }
      const target = '/' + parts.slice(0, index + 1).join('/')
      const node = this.button(part, () => this.action(() => this.show(target)))
      node.className = ''
      this.crumbs.append(node)
    })
  }
  renderEntries() {
    const rows = this.entries
    this.list.replaceChildren()
    this.setStatus(`${rows.length} item${rows.length === 1 ? '' : 's'}`)
    if (!rows.length) {
      const blank = this.el('div', null, 'blank')
      blank.append(this.el('div', null, 'box'),
        this.el('strong', 'This folder is empty.'),
        this.el('span', `Nothing readable at ${this.path}.`))
      if (this.path !== '/') blank.append(this.button('↑ Go to parent', () => this.action(() => this.show(this.path.replace(/\/[^/]+\/?$/, '') || '/'))))
      this.list.append(blank)
      return
    }
    for (const item of rows) {
      const directory = item.type === 'directory'
      const row = this.el(directory ? 'button' : 'div', null, 'row' + (directory ? '' : ' plain'))
      if (directory) { row.type = 'button'; row.onclick = () => this.action(() => this.show(item.path)) }
      row.setAttribute('role', 'listitem')
      const name = this.el('span', null, `nm${directory ? ' dir' : ''}`)
      const stack = this.el('span', null, 'stack')
      const sub = this.el('span', null, 'sub')
      sub.append(this.el('span', directory ? 'Folder' : this.bytes(item.size)))
      sub.append(this.el('span', ` · ${this.when(item.modified)}`, 'sub-date'))
      stack.append(this.el('span', item.name, 'name'), sub)
      name.append(this.el('span', null, 'dot'), stack)
      row.append(name,
        this.el('span', directory ? '—' : this.bytes(item.size), 'size'),
        this.el('span', this.when(item.modified), 'mod'))
      const act = this.el('span', null, 'act')
      if (!directory && this.download) act.append(this.button('Download', event => { event.stopPropagation(); this.download(this.session, item) }))
      else if (directory) act.append(this.el('span', '›', 'chev'))
      row.append(act)
      this.list.append(row)
    }
  }
  /** Pin the folder being viewed to the shortlist (POST /saved). */
  async saveToShortlist() {
    await this.action(async () => {
      const descriptor = await this.client.descriptor(this.session, this.path)
      const saved = await this.client.save(descriptor, this.credentials, this.shortlistLabel(descriptor))
      if (saved?.id) this.descriptor.credential_id = saved.id
      await this.renderSaved()
      this.renderRail()
      this.setStatus('Saved to shortlist.')
    })
  }
  /** Title is the folder being saved; where() supplies the protocol and full path. */
  shortlistLabel(descriptor) {
    const place = descriptor.share || descriptor.export || descriptor.root || ''
    const folder = (descriptor.path && descriptor.path !== '/' ? descriptor.path : this.path)
    const leaf = folder.split('/').filter(Boolean).pop()
    return leaf || place.split('/').filter(Boolean).pop() || place
  }

  /* ---------- selection ---------- */
  async previewDescriptor() {
    const pending = await this.client.descriptor(this.session, this.path).catch(() => null)
    this.pendingDescriptor = pending
    this.descriptorOut.textContent = pending ? JSON.stringify(pending) : 'Descriptor unavailable for this folder.'
    this.choose.disabled = !pending
  }
  async copyDescriptor() {
    const text = this.descriptorOut.textContent
    if (navigator.clipboard) await navigator.clipboard.writeText(text).catch(() => {})
    this.setStatus('Descriptor copied.')
  }
  async select() {
    await this.action(async () => {
      const descriptor = await this.client.descriptor(this.session, this.path)
      if (descriptor.type === 'smb' && this.storeCredentials) descriptor.credential_id = await this.storeCredentials(this.credentials)
      await this.close(); this.credentials = undefined; this.password.value = ''
      this.descriptorOut.textContent = JSON.stringify(descriptor, null, 2)
      this.setStatus('Folder selected.')
      this.dispatchEvent(new CustomEvent('path-selected', { detail: descriptor, bubbles: true, composed: true }))
    })
  }
  async disconnect() {
    await this.close(); this.credentials = undefined; this.password.value = ''
    this.choose.disabled = true; this.entries = []
    this.list.replaceChildren()
    this.crumbs.replaceChildren(this.el('span', 'No location connected', 'here'))
    this.sessionLabel.textContent = ''; this.pill.hidden = true
    this.app.dataset.view = 'sources'
    this.descriptor = undefined; this.activeHost = undefined
    this.renderRail()
    this.setStatus('Disconnected.')
  }
}
if (!customElements.get('remote-fs-browser')) customElements.define('remote-fs-browser', RemoteFsBrowser)
