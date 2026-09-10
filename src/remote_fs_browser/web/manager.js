// Manager implementation for the supplied DC layout. No simulated filesystem data.
window.createRemoteFsManager = function(DCLogic, React) {

const KINDS = {
  exr: 'OpenEXR image', mov: 'QuickTime movie', txt: 'Plain text', csv: 'CSV document',
  log: 'Log file', sha256: 'Checksum file'
}

class Component extends DCLogic {
  state = {collapsed:window.innerWidth<700,view:'browse',selected:[],anchor:null,filter:'',sort:{key:'name',dir:1},clipboard:null,menu:null,toast:null,ranges:'',scan:'idle',probed:0,scanTotal:0,devices:[],mapped:[],roots:[],width:window.innerWidth,place:{host:'',share:'',folders:[]},creds:[],transfers:[],stores:[],pins:[],listing:[],session:null}
  filterRef = React.createRef()
  toView(view) {
    this.setState({ view: this.state.view === view ? 'browse' : view, menu: null })
  }
  upOne() {if(this.state.place.folders.length)this.goTo({...this.state.place,folders:this.state.place.folders.slice(0,-1)})}
  async componentDidMount() {
    this.sessions = new Map(); this.auth = new Map(); this.navigation = 0
    this.onResize = () => this.setState({width:window.innerWidth})
    this.onResize(); window.addEventListener('resize', this.onResize)
    this.onError = event => { event.preventDefault(); this.say(event.reason?.message || 'Operation failed') }
    window.addEventListener('unhandledrejection', this.onError)
    this.onKey = event => {
      const meta = event.metaKey || event.ctrlKey, key = event.key.toLowerCase()
      if (document.querySelector('dialog[open]')) return
      if (key === 'escape') return this.setState({menu:null,prompt:null,zip:null,confirm:null,keys:false,view:'browse',selected:[]})
      if (event.target.closest('input,textarea,select,[contenteditable]')) return
      if (!meta) return
      if (['d','s','n','q','/','a','c','x','v','backspace'].includes(key)) event.preventDefault()
      if (key === 'd') this.toView('transfers')
      if (key === 's') this.toView('scan')
      if (key === 'n') event.shiftKey ? this.newFolder() : this.toView('add')
      if (key === 'q' && event.shiftKey) this.setState({signout:true})
      if (key === '/') this.setState({keys:!this.state.keys})
      if (key === 'a') this.selectAll(true)
      if (key === 'c' || key === 'x') this.copy(key === 'x')
      if (key === 'v') this.paste()
      if (key === 'backspace') this.remove()
    }
    document.addEventListener('keydown', this.onKey)
    const [discovery] = await Promise.all([this.api('/discover'), this.reloadSaved(), this.pollJobs()])
    this.setState({roots:discovery.roots, ranges:discovery.scan_ranges.join(', '), scan:'idle'})
    if (discovery.roots.length) this.goTo(this.fromDescriptor(discovery.roots[0]))
    this.pollTimer = setInterval(() => {if (!document.hidden) this.pollJobs().catch(() => {})}, 5000)
  }
  componentWillUnmount() {
    clearInterval(this.pollTimer); clearTimeout(this.toastTimer); this.scanCancelled = true
    window.removeEventListener('resize',this.onResize); window.removeEventListener('unhandledrejection',this.onError)
    document.removeEventListener('keydown',this.onKey)
  }
  get writable() {return ['write','mkdir','rename','delete','copy'].some(op=>this.can(op))}
  bytes(size) {
    if (size == null) return '—'
    const units = ['B', 'KB', 'MB', 'GB', 'TB']
    let value = size, unit = 0
    while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit++ }
    return `${unit === 0 ? value : value.toFixed(value < 10 ? 2 : 1)} ${units[unit]}`
  }
  kindOf(entry) {
    if (entry.type === 'directory') return 'Folder'
    return KINDS[entry.name.split('.').pop().toLowerCase()] || 'Document'
  }
  /** Each share, export or root has its own listing; folders below it get a derived one. */
  entries() {return this.state.listing || []}
  visible() {
    const filter = this.state.filter.trim().toLowerCase()
    const list = this.entries().filter(entry => !filter || entry.name.toLowerCase().includes(filter))
    const { key, dir } = this.state.sort
    return [...list].sort((a, b) => {
      if (a.type !== b.type) return a.type === 'directory' ? -1 : 1
      if (key === 'size') return ((a.size || 0) - (b.size || 0)) * dir
      if (key === 'date') return ((a.modifiedTime||0)-(b.modifiedTime||0))*dir
      return a.name.localeCompare(b.name) * dir
    })
  }

  /* ---------- selection ---------- */
  clickRow(entry, event) {
    event.stopPropagation()
    const rows = this.visible().map(item => item.name)
    const meta = event.metaKey || event.ctrlKey
    let selected = this.state.selected
    const anchor = rows.includes(this.state.anchor) ? this.state.anchor : null
    if (event.shiftKey && anchor) {
      const from = rows.indexOf(anchor), to = rows.indexOf(entry.name)
      const range = rows.slice(Math.min(from, to), Math.max(from, to) + 1)
      // Shift-clicking a ticked row clears the whole run; shift-clicking an unticked one adds it.
      selected = selected.includes(entry.name)
        ? selected.filter(name => !range.includes(name))
        : [...new Set([...selected, ...range])]
      this.setState({ selected, anchor: entry.name, menu: null })
      return
    }
    if (true) {
      // A plain click ticks the row: selecting is the primary act here, not opening.
      selected = selected.includes(entry.name) ? selected.filter(name => name !== entry.name) : [...selected, entry.name]
    }
    this.setState({ selected, anchor: entry.name, menu: null })
  }
  toggleRow(entry, event) {
    if (event && event.stopPropagation) event.stopPropagation()
    const selected = this.state.selected.includes(entry.name)
      ? this.state.selected.filter(name => name !== entry.name)
      : [...this.state.selected, entry.name]
    this.setState({ selected, anchor: entry.name })
  }
  selectAll(on) { this.setState({ selected: on ? this.visible().map(item => item.name) : [] }) }

  /* ---------- actions ---------- */
  say(text) {
    clearTimeout(this.toastTimer)
    this.setState({ toast: text })
    this.toastTimer = setTimeout(() => this.setState({ toast: null }), 3200)
  }
  names() { return this.state.selected }
  copy(cut) {
    if(!this.names().length)return
    if(!this.can(cut?'rename':'read'))return this.say('This operation is not permitted')
    this.setState({clipboard:{names:[...this.names()],place:{...this.state.place,folders:[...this.state.place.folders]},cut},menu:null})
  }
  async paste() {
    const clip=this.state.clipboard, target=this.state.session
    if(!clip||!target)return
    const source=await this.sessionFor(clip.place)
    let done=0
    try {
      for(const name of clip.names) {
        const src=this.childPath(name,clip.place),dest=this.childPath(name)
        if(clip.cut&&source.id===target.id)await this.api(`/sessions/${source.id}/rename`,{source:src,destination:dest})
        else {
          await this.api(`/sessions/${source.id}/copy`,{source:src,destination:dest,target_session:target.id})
          if(clip.cut)await this.api(`/sessions/${source.id}/entry?${new URLSearchParams({path:src,recursive:'true'})}`,undefined,'DELETE')
        }
        done++
      }
    } finally {
      if(clip.cut)this.setState({clipboard:done===clip.names.length?null:{...clip,names:clip.names.slice(done)}})
      await this.refresh()
    }
  }
  async remove() {
    const names=[...this.names()], session=this.state.session,place=this.state.place
    if(!names.length||!this.can('delete'))return
    if(!await this.dialog('Delete selection',`Permanently delete ${names.length} item(s), including folder contents?`,null,'Delete'))return
    this.setState({menu:null})
    try {for(const name of names)await this.api(`/sessions/${session.id}/entry?${new URLSearchParams({path:this.childPath(name,place),recursive:'true'})}`,undefined,'DELETE')}
    finally {this.setState({selected:[]});await this.refresh()}
  }
  download() {
    const picked = this.names().map(name => this.entries().find(entry => entry.name === name)).filter(Boolean)
    if (!picked.length) return
    const folders = picked.filter(entry => entry.type === 'directory')
    // Loose files stream straight from the share; only folders need packing.
    if (!folders.length) { this.setState({ menu: null }); this.startBatch(picked); return }
    this.openZip(picked)
  }
  /** Any selection can be packed instead — useful on a slow link, even for one big file. */
  async openZip(picked) {
    const estimate=await this.api('/downloads/estimate',{session:this.state.session.id,paths:picked.map(e=>e.path)})
    if(!estimate.stores.length)return this.say('No staging stores configured on this service')
    this.setState({stores:estimate.stores,menu:null,zip:{picked,session:this.state.session.id,split:'2',store:0,custom:'40',unit:'MB',...estimate}})
  }
  zipTotal() {return this.state.zip?.total||0}
  zipName(picked) {
    if (picked.length === 1) return `${picked[0].name}.zip`
    return 'selection.zip'
  }
  /** A zip is staged before it streams, so the store needs the payload plus ~2% of index and headroom. */
  zipNeeded() {return this.state.zip?.needed||0}
  zipLimit(zip = this.state.zip) {
    if (!zip || zip.split === 'none') return 0
    if (zip.split !== 'custom') return Number(zip.split) * 1073741824
    const value = parseFloat(zip.custom)
    if (!value || value <= 0) return 0
    return Math.round(value * (zip.unit === 'GB' ? 1073741824 : 1048576))
  }
  zipPartCount(zip = this.state.zip) {
    const limit = this.zipLimit(zip)
    return limit ? Math.max(1, Math.ceil(this.zipNeeded(zip.picked) / limit)) : 1
  }
  async confirmZip() {
    const zip=this.state.zip;if(!zip)return
    const limit=this.zipLimit(zip)
    if(zip.split==='custom'&&(!Number.isFinite(limit)||limit<1048576))throw new Error('Minimum part size is 1 MB')
    await this.api('/downloads',{session:zip.session,paths:zip.picked.map(e=>e.path),store:this.state.stores[zip.store].id,part_size:limit})
    this.setState({zip:null,view:'transfers'});await this.pollJobs()
  }
  alreadyGrabbed(path, queuedToo) {
    for (const job of this.state.transfers) {
      if (job.purged) continue
      const index = job.parts.findIndex(part => part.path === path && (queuedToo || part.downloaded))
      if (index >= 0) return { job, index }
    }
    return null
  }
  async startBatch(picked,force=false) {
    const place=this.state.place,session=await this.sessionFor(place)
    const parts=picked.map(e=>({name:e.name,size:e.size,path:this.pathOf(place)+'/'+e.name,relative:e.path,place,downloaded:false}))
    if(!force){const done=parts.map(p=>this.alreadyGrabbed(p.path)).find(Boolean);if(done)return this.setState({confirm:{jobId:done.job.id,index:done.index}})}
    if(force){const existing=parts.map(p=>this.alreadyGrabbed(p.path,true)).find(Boolean);if(existing){this.setState({view:'transfers',confirm:null});return this.grabPart(existing.job,existing.index,true)}}
    const fresh=parts.filter(p=>!this.alreadyGrabbed(p.path,true))
    if(!fresh.length){this.setState({view:'transfers'});return}
    const total=fresh.reduce((n,p)=>n+p.size,0)
    this.setState({transfers:[{id:crypto.randomUUID(),kind:'files',name:fresh.length===1?fresh[0].name:`${fresh.length} files`,parts:fresh,total,packed:total,stage:'ready',status:'ready',open:true,purged:false,store:'Streamed from source'},...this.state.transfers],view:'transfers',confirm:null})
  }
  componentDidUpdate() {
    if (this.state.place !== this.loadedPlace) {
      this.loadedPlace = this.state.place
      if (this.state.place.descriptor) this.loadPlace(this.state.place).catch(() => {})
    }
  }
  readyParts(job) {return job.stage==='ready'?job.parts.length:job.stage==='packing'?job.parts.filter(p=>p.ready).length:0}
  stagedOf(job) {return job.staged||0}
  freeOf(store) {return store.free}
  async setTransfer(id,status) {await this.api(`/downloads/${id}`,{action:status==='paused'?'pause':'resume'});await this.pollJobs()}
  toggleJob(id) {
    this.setState({ transfers: this.state.transfers.map(job => job.id === id ? { ...job, open: !job.open } : job) })
  }
  /** Re-downloading an already-fetched part asks first, so nobody ends up with three copies. */
  async grabPart(job,index,force=false) {
    if(job.purged||index>=this.readyParts(job))return
    if(job.parts[index].downloaded&&!force)return this.setState({confirm:{jobId:job.id,index}})
    const part=job.parts[index]
    let url=`/api/downloads/${job.id}/parts/${index}`
    if(job.kind==='files'){const session=await this.sessionFor(part.place);url=`/api/sessions/${session.id}/file?${new URLSearchParams({path:part.relative})}`}
    const link=document.createElement('a');link.href=url;link.download=part.name;document.body.append(link);link.click();link.remove()
    this.setState({confirm:null,transfers:this.state.transfers.map(j=>j.id===job.id?{...j,parts:j.parts.map((p,i)=>i===index?{...p,downloaded:true}:p)}:j)})
    this.say('Handed to the browser. Check its download manager for completion.')
  }
  grabAll(job) {
    const ready = this.readyParts(job)
    const pending = job.parts.filter((part, index) => index < ready && !part.downloaded).length
    this.setState({ transfers: this.state.transfers.map(item => item.id === job.id ? { ...item, open: true } : item) })
    this.say(pending
      ? `${pending} link${pending === 1 ? '' : 's'} ready below — open them one at a time. Browsers cap same-origin transfers at six and prompt before a burst of automatic downloads.`
      : 'Everything ready has been downloaded already.')
  }
  async purgeJob(job) {
    const pending=job.parts.filter(p=>!p.downloaded).length
    if(!await this.dialog('Purge staged download',`${this.bytes(job.staged)} will be freed.${pending?` ${pending} parts have not been handed to the browser.`:''} Active downloads may be interrupted.`,null,'Purge'))return
    const result=await this.api(`/downloads/${job.id}`,undefined,'DELETE');this.say(`Freed ${this.bytes(result.freed)}`);await this.pollJobs()
  }
  async dropTransfer(id) {const job=this.state.transfers.find(j=>j.id===id);if(job.kind==='zip'){if(!job.purged)return this.purgeJob(job);await this.api(`/downloads/${id}`,{action:'forget'})}this.setState({transfers:this.state.transfers.filter(j=>j.id!==id)})}
  async clearFinished() {for(const job of this.state.transfers.filter(j=>j.purged&&j.kind==='zip'))await this.api(`/downloads/${job.id}`,{action:'forget'});await this.pollJobs()}
  place(event) {
    return { x: Math.min(event.clientX, window.innerWidth - 244), y: Math.min(event.clientY, window.innerHeight - 300) }
  }
  openDeviceMenu(event, device) {
    event.preventDefault(); event.stopPropagation()
    this.setState({ menu: { ...this.place(event), kind: 'device', device } })
  }
  openMountMenu(event, host) {
    event.preventDefault(); event.stopPropagation()
    this.setState({ menu: { ...this.place(event), kind: 'mount', host } })
  }
  async forgetCreds(key) {
    const host=this.state.mapped.find(h=>h.key===key)
    if(host?.credential_id)await this.api(`/credentials/${host.credential_id}`,undefined,'DELETE')
    this.setState({mapped:this.state.mapped.map(h=>h.key===key?{...h,credential_id:undefined,creds:'session'}:h),menu:null})
    await this.reloadSaved()
  }
  copyText(text, what) {
    if (navigator.clipboard) navigator.clipboard.writeText(text).catch(() => this.say('Clipboard access was denied'))
    this.setState({ menu: null })
    this.say(`${what} copied: ${text}`)
  }
  deviceItems(device) {
    const key = `${device.protocol.toLowerCase()}:${device.ip}`
    const mapped = this.state.mapped.find(host => host.key === key)
    const stored = mapped && (mapped.creds === 'stored' || mapped.creds === 'shared')
    const rows = [
      { label: mapped ? 'Remap' : 'Map', keys: '', on: true, run: () => this.askDevice(device) },
      { label: 'Map as a different user…', keys: '', on: device.protocol === 'SMB', run: () => this.askDevice(device) },
      { divider: true },
      { label: 'Copy IP address', keys: '', on: true, run: () => this.copyText(device.ip, 'IP address') },
      { label: 'Copy DNS name', keys: '', on: !!device.dns, run: () => this.copyText(device.dns || '', 'DNS name') },
      { label: 'Copy NetBIOS name', keys: '', on: !!device.netbios, run: () => this.copyText(device.netbios || '', 'NetBIOS name') }
    ]
    if (mapped) {
      rows.push({ divider: true })
      rows.push({ label: 'Forget stored credentials', keys: '', on: stored, run: () => this.forgetCreds(key, mapped.label) })
      rows.push({ label: 'Unmount', keys: '', on: true, run: () => { this.setState({ menu: null }); this.unmount(mapped) } })
    }
    return rows
  }
  mountItems(host) {
    const stored = host.creds === 'stored' || host.creds === 'shared'
    return [
      { label: `List ${host.protocol === 'NFS' ? 'exports' : 'shares'}`, keys: '', on: true, run: () => this.refreshHost(host) },
      { label: 'Reconnect as a different user…', keys: '', on: host.protocol === 'SMB', run: () => this.askDevice({ protocol: host.protocol, ip: host.ip, dns: host.label, netbios: null }) },
      { divider: true },
      { label: 'Copy IP address', keys: '', on: true, run: () => this.copyText(host.ip, 'IP address') },
      { label: stored ? 'Forget stored credentials' : 'No stored credentials', keys: '', on: stored, run: () => this.forgetCreds(host.key, host.label) },
      { divider: true },
      { label: 'Unmount', keys: '', on: true, run: () => { this.setState({ menu: null }); this.unmount(host) } }
    ]
  }
  openMenu(event, entry) {
    event.preventDefault(); event.stopPropagation()
    let selected = this.state.selected
    if (entry && !selected.includes(entry.name)) selected = [entry.name]
    if (!entry) selected = []
    const x = Math.min(event.clientX, window.innerWidth - 232)
    const y = Math.min(event.clientY, window.innerHeight - 340)
    this.setState({ selected, anchor: entry ? entry.name : null, menu: { x, y, kind: 'file', target: entry ? entry.name : null } })
  }
  items() {
    const entries=this.names().map(name=>this.entries().find(e=>e.name===name)).filter(Boolean),one=entries.length===1?entries[0]:null
    const rows=[]
    if(one)rows.push({label:one.type==='directory'?'Open':'Open in preview',on:this.can(one.type==='directory'?'list':'read'),run:()=>one.type==='directory'?this.goTo({...this.state.place,folders:[...this.state.place.folders,one.name]}):this.preview(one)})
    if(entries.length)rows.push({label:'Download',on:this.can('read'),run:()=>this.download()},{label:'Download as multi-part zip…',on:this.can('read'),run:()=>this.openZip(entries)},{divider:true},{label:'Copy',on:this.can('copy'),run:()=>this.copy(false)},{label:'Cut',on:this.can('rename'),run:()=>this.copy(true)})
    rows.push({label:'Paste',on:!!this.state.clipboard&&this.can('write'),run:()=>this.paste()},{divider:true},{label:'New folder',on:this.can('mkdir'),run:()=>this.newFolder()},{label:'New text file',on:this.can('write'),run:()=>this.newFile()},{label:'Upload files here',on:this.can('write'),run:()=>this.upload()})
    if(one)rows.push({label:'Rename',on:this.can('rename'),run:()=>this.renameEntry(one)})
    const place=one?.type==='directory'?{...this.state.place,folders:[...this.state.place.folders,one.name]}:this.state.place
    rows.push({label:'Shortlist folder',on:!!place.descriptor&&this.state.savedAvailable,run:()=>this.pin(place,one?.name||place.share)})
    if(entries.length)rows.push({divider:true},{label:'Delete',on:this.can('delete'),run:()=>this.remove()},{label:'Get info',on:this.can('stat'),run:()=>this.info(entries)})
    return rows
  }
  async startScan() {
    if(this.state.scan==='running')return
    const scanId=this.scanId=(this.scanId||0)+1
    this.scanCancelled=false
    const ranges=this.state.ranges.split(/[,\s]+/).filter(Boolean)
    this.setState({scan:'running',devices:[],probed:0,scanTotal:0})
    let offset=0, devices=[]
    try {
      do {
        const data=await this.api('/discover',{ranges,offset})
        if(scanId!==this.scanId)return
        if(this.scanCancelled)break
        const found=data.hosts.flatMap(host=>host.protocols.map(protocol=>({ip:host.host,dns:host.dns_name,netbios:host.netbios_name,protocol:protocol.toUpperCase()})))
        for(const device of found)if(!devices.some(d=>d.ip===device.ip&&d.protocol===device.protocol))devices.push(device)
        this.setState({devices:[...devices],probed:data.scan_offset+data.scanned,scanTotal:data.total_addresses,scanNotes:data.notes.join(' ')})
        offset=data.next_offset
      } while(offset!==null && !this.scanCancelled)
      this.setState({scan:this.scanCancelled?'stopped':'done'})
    } catch(error) {if(scanId===this.scanId)this.setState({scan:'stopped'});throw error}
  }
  cancelScan() {this.scanId=(this.scanId||0)+1;this.scanCancelled=true;this.setState({scan:'stopped'})}
  askDevice(device) {
    const saved=this.state.creds.find(c=>c.host===device.ip.toLowerCase())
    this.setState({menu:null,prompt:{device,username:'',password:'',domain:'',version:'4',export:'',store:false,credId:saved?.id||'new'}})
  }
  setPrompt(key, value) { this.setState({ prompt: { ...this.state.prompt, [key]: value } }) }
  async submitPrompt() {
    const prompt=this.state.prompt
    if(!prompt)return
    const credentials=prompt.credId==='new'?{username:prompt.username,password:prompt.password,domain:prompt.domain}:null
    await this.mapDevice(prompt.device,{...prompt,credentials,credential_id:prompt.credId==='new'?undefined:prompt.credId})
    this.setState({prompt:null})
  }
  async mapDevice(device, options={}) {
    const type=device.protocol.toLowerCase(),key=`${type}:${device.ip}`
    let credential_id=options.credential_id
    const typed=(options.export||options.share||'').trim()
    let shares
    if(typed)shares=[typed]
    else {
      const data=await this.api('/discover',{host:device.ip,type,credentials:options.credentials,credential_id})
      shares=type==='smb'?data.shares.map(row=>typeof row==='string'?row:row.name):data.exports
      if(data.truncated)this.say('The server returned a partial share list. Add a path manually if needed.')
    }
    if(!shares?.length)throw new Error('No shares or exports returned. Enter the share or export path manually.')
    for(const [cacheKey,session] of this.sessions)if(session.descriptor.host===device.ip&&session.descriptor.type===type){await this.api(`/sessions/${session.id}`,undefined,'DELETE').catch(()=>{});this.sessions.delete(cacheKey)}
    if(options.credentials)this.auth.set(key,options.credentials)
    if(typed){
      const descriptor={type,host:device.ip,...(type==='smb'?{share:typed}:{export:typed,version:Number(options.version||4)}),...(credential_id?{credential_id}:{})}
      await this.sessionFor(this.fromDescriptor(descriptor))
    }
    if(type==='smb'&&options.store&&options.credentials) {
      credential_id=(await this.api('/credentials',{host:device.ip,credentials:options.credentials})).id
      await this.reloadSaved()
    }
    const host={key,label:device.dns||device.netbios||device.ip,ip:device.ip,protocol:device.protocol,shares,version:Number(options.version||4),credential_id,creds:credential_id?'stored':type==='nfs'?'none':'session',user:options.credentials?.username||'',active:null}
    this.setState({mapped:[...this.state.mapped.filter(h=>h.key!==key),host],view:'browse',collapsed:false})
    if(typed)await this.openShare(host,typed)
  }
  pathOf(place) {
    const tail = [place.share, ...place.folders].filter(Boolean).join('/')
    return place.host ? `${place.host}/${tail}`.replace(/([^:])\/\//g, '$1/') : '/' + tail.replace(/^\/+/, '')
  }
  goTo(place) {this.setState({place,selected:[],filter:'',view:'browse',menu:null})}
  async pin(place,label) {
    if(!place.descriptor) return this.say('Open this folder before adding it to the shortlist')
    const descriptor={...place.descriptor,path:this.currentPath(place)}
    await this.api('/saved',{descriptor, label,credentials:this.auth.get(`${descriptor.type}:${descriptor.host}`)})
    await this.reloadSaved(); this.setState({menu:null})
  }
  async unpin(pin) {await this.api(`/saved/${pin.id}`,undefined,'DELETE'); await this.reloadSaved();this.setState({menu:null})}
  openPinMenu(event, pin) {
    event.preventDefault(); event.stopPropagation()
    this.setState({ menu: { ...this.place(event), kind: 'pin', pin } })
  }
  openShareMenu(event, host, name) {
    event.preventDefault(); event.stopPropagation()
    this.setState({ menu: { ...this.place(event), kind: 'share', host, share: name } })
  }
  pinItems(pin) {
    return [
      { label: 'Open', keys: '', on: true, run: () => { this.setState({ menu: null }); this.goTo(pin.place, `Reopened ${pin.label}.`) } },
      { label: 'Copy path', keys: '', on: true, run: () => this.copyText(this.pathOf(pin.place), 'Path') },
      { divider: true },
      { label: 'Forget', keys: '', on: true, run: () => this.unpin(pin) }
    ]
  }
  shareItems(host, name) {
    const place = this.fromDescriptor({type:host.protocol.toLowerCase(),host:host.ip,...(host.protocol==='SMB'?{share:name}:{export:name,version:host.version||4}),credential_id:host.credential_id})
    return [
      { label: 'Open', keys: '', on: true, run: () => { this.setState({ menu: null }); this.openShare(host, name) } },
      { label: `Shortlist ${host.protocol === 'NFS' ? 'export' : 'share'}`, keys: '', on: true, run: () => this.pin(place, name.replace(/^\//, '').split('/').pop()) },
      { label: 'Copy path', keys: '', on: true, run: () => this.copyText(this.pathOf(place), 'Path') },
      { divider: true },
      { label: `Unmount ${host.label}`, keys: '', on: true, run: () => { this.setState({ menu: null }); this.unmount(host) } }
    ]
  }
  async refreshHost(host) {
    this.setState({menu:null})
    const data=await this.api('/discover',{type:host.protocol.toLowerCase(),host:host.ip,credential_id:host.credential_id,credentials:this.auth.get(host.key)})
    const shares=host.protocol==='SMB'?data.shares.map(row=>typeof row==='string'?row:row.name):data.exports
    if(!shares.length)return this.say('No share/export list returned. Existing manual locations are still available.')
    this.setState({mapped:this.state.mapped.map(h=>h.key===host.key?{...h,shares}:h)})
  }
  async unmount(host) {
    for(const [key,session] of this.sessions)if(session.descriptor.host===host.ip) {
      await this.api(`/sessions/${session.id}`,undefined,'DELETE').catch(()=>{})
      this.sessions.delete(key)
    }
    this.auth.delete(host.key)
    this.setState({mapped:this.state.mapped.filter(h=>h.key!==host.key),menu:null,selected:[]})
    if(this.state.place.descriptor?.host===host.ip)this.setState({place:{host:'',share:'',folders:[]},listing:[],session:null})
  }
  openShare(host,name) {
    const descriptor={type:host.protocol.toLowerCase(),host:host.ip,...(host.protocol==='SMB'?{share:name}:{export:name,version:host.version||4})}
    if(host.credential_id)descriptor.credential_id=host.credential_id
    this.setState({mapped:this.state.mapped.map(h=>({...h,active:h.key===host.key?name:null}))})
    this.goTo(this.fromDescriptor(descriptor))
  }
  renderVals() {
    const rows = this.visible()
    const all = this.entries()
    const selected = this.state.selected
    const entries = selected.map(name => this.entries().find(entry => entry.name === name)).filter(Boolean)
    const total = entries.reduce((sum, entry) => sum + (entry.size || 0), 0)
    const write = this.writable
    const clip = this.state.clipboard
    const menu = this.state.menu
    const prompt = this.state.prompt
    const scanning = this.state.view === 'scan'
    const showing = this.state.view === 'browse'
    const busy = scanning && this.state.scan === 'running'
    const DEVICES = this.state.devices, STORES = this.state.stores
    const shown = DEVICES
    const railItem = (label, active) => ({ bg: active ? '#e3ebfb' : 'transparent', dot: active ? '#3f6fd1' : '#6a727c' })

    const pane = this.state.width - (this.state.collapsed ? 56 : 272)
    const roomy = this.state.width >= 1040
    const showKind = pane >= 820
    const wideScan = pane >= 820
    const showDate = pane >= 560

    return {
      roomy, tight: !roomy, showKind, showDate, wideScan, narrowScan: !wideScan,
      deviceCols: wideScan
        ? 'minmax(150px,1.4fr) minmax(90px,.8fr) 116px 70px 96px 78px'
        : 'minmax(140px,1.6fr) minmax(84px,.8fr) 112px 74px',
      listCols: showKind
        ? '32px minmax(0,1fr) 100px 108px 128px 64px'
        : showDate
          ? '32px minmax(0,1fr) 92px 124px 64px'
          : pane<600?'32px minmax(0,1fr) 56px 52px':'32px minmax(0,1fr) 92px 64px',
      overflowMenu: event => this.setState({menu:{...this.place(event),kind:'toolbar'}}),
      collapsed: this.state.collapsed,
      expanded: !this.state.collapsed,
      railWidth: this.state.collapsed ? '56px' : '272px',
      toggleRail: () => this.setState({ collapsed: !this.state.collapsed }),
      toggleAdd: () => this.toView('add'),
      railIcons: [
        { title: 'Shortlist', ...railItem('', false), open: () => this.setState({ collapsed: false }) },
        { title: 'This machine', ...railItem('', false), open: () => this.setState({ collapsed: false }) },
        { title: 'Network', ...railItem('', this.state.place.descriptor?.type!=='local'), open: () => this.setState({ collapsed: false }) },
        { title: 'Scan network', ...railItem('', false), open: () => this.setState({ view: 'scan', collapsed: false }) }
      ],
      hasPins: this.state.pins.length > 0,
      noPins: this.state.pins.length === 0,
      shortlist: this.state.pins.map(pin => ({
        label: pin.label,
        where: this.pathOf(pin.place),
        open: () => this.goTo(pin.place, `Reopened ${pin.label} — ${this.pathOf(pin.place)}.`),
        menu: event => this.openPinMenu(event, pin),
        forget: event => { event.stopPropagation(); this.unpin(pin) }
      })),
      localRoots: this.state.roots.map(root => ({label:root.root,
        ...railItem('', this.state.place.descriptor?.root===root.root),
        open:()=>this.goTo(this.fromDescriptor(root))})),
      hosts: this.state.mapped.map(host => ({
        label: host.label, ip: host.ip, protocol: host.protocol,
        ...railItem('', !!host.active),
        open: () => this.refreshHost(host),
        unmountTitle: `Unmount ${host.label}`,
        unmount: event => { event.stopPropagation(); this.unmount(host) },
        menu: event => this.openMountMenu(event, host),
        credsMark: host.creds === 'shared' ? 'shared' : host.creds === 'stored' ? 'saved' : '',
        credsTitle: host.creds === 'shared'
          ? `Credentials saved and shared with other users of this service${host.user ? ` (${host.user})` : ''}`
          : host.creds === 'stored'
            ? `Credentials saved for your account only${host.user ? ` (${host.user})` : ''}`
            : host.protocol === 'NFS' ? 'No credentials — AUTH_SYS' : 'Session only — not saved',
        shares: host.shares.map(name => ({
          name, ...railItem('', host.active === name),
          open: () => this.openShare(host, name),
          menu: event => this.openShareMenu(event, host, name)
        }))
      })),

      browsing: true,
      crumbs: [this.state.place.host, this.state.place.share, ...this.state.place.folders]
        .filter(Boolean)
        .map((text, index, all) => {
          const last = index === all.length - 1
          return {
            text, sep: index > 0,
            color: last ? '#1c2024' : '#6a727c',
            weight: last ? '500' : '400',
            flex: index < 2 ? '0 1 auto' : 'none',
            go: () => this.goTo({...this.state.place,folders:this.state.place.folders.slice(0,Math.max(0,index-(this.state.place.host?1:0)))})
          }
        }),
      goUp: () => this.upOne(),
      filterRef: this.filterRef,
      keysOpen: !!this.state.keys,
      toggleKeys: () => this.setState({ keys: !this.state.keys }),
      closeKeys: () => this.setState({ keys: false }),
      shortcuts: [
        ['⌘/Ctrl + D', 'Downloads — press again to return'],
        ['⌘/Ctrl + S', 'Scan network — press again to return'],
        ['⌘/Ctrl + N', 'Add a location — press again to return'],
        ['⌘/Ctrl + ⇧ + Q', 'Sign out'],
        ['⌘/Ctrl + A', 'Select everything in this folder'],
        ['Shift-tick', 'Select a range'],
        ['⌘/Ctrl-tick', 'Add or remove one'],
        ['⌘/Ctrl + C / X / V', 'Copy, cut, paste'],
        ['⌘/Ctrl + ⌫', 'Delete selection'],
        ['Esc', 'Close the pane, or clear the selection'],
        ['⌘/Ctrl + /', 'This list']
      ].map(([keys, what]) => ({ keys, what })),
      refresh: () => this.refresh(),
      newFolder: () => this.newFolder(),
      herePinned: this.state.pins.some(pin => this.pathOf(pin.place) === this.pathOf(this.state.place)),
      herePinGlyph: this.state.pins.some(pin => this.pathOf(pin.place) === this.pathOf(this.state.place)) ? '★' : '☆',
      herePinLabel: this.state.pins.some(pin => this.pathOf(pin.place) === this.pathOf(this.state.place)) ? 'Shortlisted' : 'Shortlist folder',
      herePinBg: this.state.pins.some(pin => this.pathOf(pin.place) === this.pathOf(this.state.place)) ? '#eef2fb' : 'rgba(255,255,255,.75)',
      herePinLine: this.state.pins.some(pin => this.pathOf(pin.place) === this.pathOf(this.state.place)) ? '#b6c6e8' : '#d5d9df',
      herePinInk: this.state.pins.some(pin => this.pathOf(pin.place) === this.pathOf(this.state.place)) ? '#22417d' : '#1c2024',
      pinFolder: () => {
        const existing = this.state.pins.find(pin => this.pathOf(pin.place) === this.pathOf(this.state.place))
        if (existing) return this.unpin(existing)
        const here = this.state.place.folders[this.state.place.folders.length - 1] || this.state.place.share || 'this folder'
        this.pin(this.state.place, here)
      },
      filter: this.state.filter,
      setFilter: event => this.setState({ filter: event.target.value, selected: [] }),
      empty: !rows.length,
      emptyTitle: this.state.loading ? 'Loading…' : this.state.filter ? `Nothing matches “${this.state.filter}”.` : this.state.session ? 'This folder is empty.' : 'Choose a location to begin.',
      emptyHint: this.state.filter ? 'Clear the filter to see every entry in this folder.' : '',

      allSelected: rows.length > 0 && selected.length === rows.length,
      allTickBg: selected.length ? '#3f6fd1' : '#fff',
      allTickLine: selected.length ? '#2b57ae' : '#c0c5cc',
      allTickInk: selected.length ? '#fff' : 'transparent',
      allTickGlyph: selected.length && selected.length < rows.length ? '–' : '✓',
      toggleAll: event => {
        event.stopPropagation()
        this.selectAll(!(rows.length > 0 && selected.length === rows.length))
      },
      sortName: () => this.setState({ sort: { key: 'name', dir: this.state.sort.key === 'name' ? -this.state.sort.dir : 1 } }),
      sortSize: () => this.setState({ sort: { key: 'size', dir: this.state.sort.key === 'size' ? -this.state.sort.dir : -1 } }),
      sortDate: () => this.setState({ sort: { key: 'date', dir: this.state.sort.key === 'date' ? -this.state.sort.dir : 1 } }),
      nameArrow: this.state.sort.key === 'name' ? (this.state.sort.dir > 0 ? '↑' : '↓') : '',
      sizeArrow: this.state.sort.key === 'size' ? (this.state.sort.dir > 0 ? '↑' : '↓') : '',
      dateArrow: this.state.sort.key === 'date' ? (this.state.sort.dir > 0 ? '↑' : '↓') : '',

      rows: rows.map(entry => {
        const on = selected.includes(entry.name)
        const cutting = clip?.cut && clip.names.includes(entry.name)
        return {
          name: entry.name, selected: on,
          size: entry.type === 'directory' ? '—' : this.bytes(entry.size),
          kind: this.kindOf(entry),
          modified: showKind ? entry.modified : entry.modified.replace(/ \d{4},/, ''),
          dot: entry.type === 'directory' ? '#3f6fd1' : '#c0c5cc',
          bg: on ? '#e3ebfb' : 'transparent',
          hoverBg: on ? '#dde7fa' : '#eef2fb',
          title: `${entry.name}\n${this.kindOf(entry)} · ${entry.type === 'directory' ? 'folder — downloads as a zip' : this.bytes(entry.size)}\nModified ${entry.modified}\n${entry.type === 'directory' ? 'Click to open · tick to select · ☆ to shortlist' : 'Tick to select · right-click for actions'}`,
          opacity: cutting ? '.5' : '1',
          // The row navigates; the tick box is the only selector.
          click: event => {
            event.stopPropagation()
            if (entry.type === 'directory') {
              this.setState({ selected: [], filter: '', menu: null, place: { ...this.state.place, folders: [...this.state.place.folders, entry.name] } })
              return
            }
            this.setState({ menu: null })
            this.preview(entry)
          },
          pinned: this.state.pins.some(pin => this.pathOf(pin.place) === this.pathOf({ ...this.state.place, folders: [...this.state.place.folders, entry.name] })),
          pinGlyph: this.state.pins.some(pin => this.pathOf(pin.place) === this.pathOf({ ...this.state.place, folders: [...this.state.place.folders, entry.name] })) ? '★' : '☆',
          pinInk: this.state.pins.some(pin => this.pathOf(pin.place) === this.pathOf({ ...this.state.place, folders: [...this.state.place.folders, entry.name] })) ? '#3f6fd1' : '#a8b0ba',
          pinTitle: entry.type === 'directory' ? `Shortlist ${entry.name}` : '',
          isDir: entry.type === 'directory',
          isFile: entry.type !== 'directory',
          grabTitle: `Download ${entry.name} (${this.bytes(entry.size)}) — right-click to zip it in parts instead`,
          grab: event => { event.stopPropagation(); this.startBatch([entry]) },
          pin: event => {
            event.stopPropagation()
            const target = { ...this.state.place, folders: [...this.state.place.folders, entry.name] }
            const existing = this.state.pins.find(pin => this.pathOf(pin.place) === this.pathOf(target))
            if (existing) return this.unpin(existing)
            this.pin(target, entry.name)
          },
          tickBg: on ? '#3f6fd1' : '#fff',
          tickLine: on ? '#2b57ae' : '#c0c5cc',
          tickInk: on ? '#fff' : 'transparent',
          check: event => {
            event.stopPropagation()
            if (event.shiftKey || event.metaKey || event.ctrlKey) return this.clickRow(entry, event)
            this.toggleRow(entry, event)
          },
          open: () => {
            if (entry.type !== 'directory') return this.preview(entry)
            this.setState({ selected: [], filter: '', place: { ...this.state.place, folders: [...this.state.place.folders, entry.name] } })
            this.say(`Opened ${entry.name}.`)
          },
          menu: event => this.openMenu(event, entry)
        }
      }),
      stop: event => event.stopPropagation(),
      onBackgroundClick: () => this.setState({ selected: [], menu: null }),
      onBackgroundMenu: event => this.openMenu(event, null),

      anySelected: selected.length > 0,
      selectionLabel: `${selected.length} selected`,
      selectionBytes: total ? this.bytes(total) : '',
      clearSelection: () => this.setState({ selected: [] }),
      selectionActions: [
        { label: entries.some(entry => entry.type === 'directory') ? 'Download as zip' : selected.length > 1 ? `Download ${selected.length} files` : 'Download', on: this.can('read'), run: () => this.download() },
        { label: 'Zip…', on: this.can('read'), run: () => this.openZip(entries) },
        { label: 'Copy', on: this.can('copy'), run: () => this.copy(false) },
        { label: 'Cut', on: this.can('rename'), run: () => this.copy(true) },
        { label: clip ? `Paste (${clip.names.length})` : 'Paste', on: !!clip && this.can('write'), run: () => this.paste() },
        { label: 'Delete', on: this.can('delete'), run: () => this.remove(), danger: true }
      ].map(action => ({
        label: action.label, run: action.run, disabled: !action.on,
        opacity: action.on ? '1' : '.45',
        bg: 'rgba(255,255,255,.85)',
        line: action.danger && action.on ? '#e6bdb5' : '#c9d5ee',
        ink: action.danger && action.on ? '#7e2c20' : '#22417d'
      })),

      countLabel: this.state.loading ? 'Loading…' : this.state.filter ? `${rows.length} of ${all.length} items` : `${all.length} items`,
      clipboardLabel: clip ? `${clip.names.length} item${clip.names.length === 1 ? '' : 's'} on the clipboard (${clip.cut ? 'cut' : 'copy'})` : '',
      readOnly: !write,

      scanning, scanBusy: busy, scanIdle: !busy,
      openScan: () => this.toView('scan'),
      closeScan: () => this.setState({ view: 'browse' }),
      startScan: () => this.startScan(),
      cancelScan: () => this.cancelScan(),
      scanButton: this.state.scan === 'done' ? 'Rescan' : this.state.scan === 'stopped' ? 'Restart scan' : 'Start scan',
      ranges: this.state.ranges,
      setRanges: event => this.setState({ ranges: event.target.value }),
      scanPercent: `${this.state.scanTotal ? Math.min(100,Math.round(this.state.probed / this.state.scanTotal * 100)) : 0}%`,
      scanStatus: this.state.scan === 'idle' ? 'Ready to scan permitted ranges' : `${this.state.scan === 'running' ? 'Scanning' : this.state.scan === 'stopped' ? 'Stopped' : 'Scanned'} addresses 1–${this.state.probed} of ${this.state.scanTotal}`,
      scanFound: `${DEVICES.length} services found`,
      scanBatch: this.state.scanNotes || 'Scans run in batches of up to 256 addresses',
      devices: shown.map(device => {
        const state = this.state.mapped.find(host => host.key === `${device.protocol.toLowerCase()}:${device.ip}`)
        const creds = device.protocol === 'NFS' ? 'none' : state?.creds || 'ask'
        const label = { shared: 'Shared', stored: 'Stored', session: 'Session only', none: 'AUTH_SYS', ask: 'Not saved' }[creds]
        return {
        credsLabel: label,
        credsInk: creds === 'shared' || creds === 'stored' ? '#22417d' : '#6a727c',
        credsBg: creds === 'shared' || creds === 'stored' ? '#eaf0fc' : 'transparent',
        credsLine: creds === 'shared' || creds === 'stored' ? '#cfdcf6' : '#e2e5ea',
        credsTitle: creds === 'shared' ? 'Credentials saved and reusable by any user of this service'
          : creds === 'stored' ? 'Credentials saved for your account only'
          : creds === 'session' ? 'Held in memory for this session only'
          : creds === 'none' ? 'NFS sends no credentials — AUTH_SYS UID/GID of the service account'
          : 'You will be asked when mapping',
        menu: event => this.openDeviceMenu(event, device),
        dns: device.dns || '—', netbios: device.netbios || '—', ip: device.ip, protocol: device.protocol,
        nameInk: device.dns ? '#1c2024' : '#9aa1ab',
        netbiosInk: device.netbios ? '#4d545c' : '#9aa1ab',
        dot: device.protocol === 'SMB' ? '#3f6fd1' : '#6a8fd8',
        map: () => this.askDevice(device)
      }}),

      promptOpen: !!prompt,
      promptSmb: prompt?.device.protocol === 'SMB',
      promptNfs: prompt?.device.protocol === 'NFS',
      promptEyebrow: prompt ? (prompt.device.protocol === 'SMB' ? 'SMB sign-in' : 'NFS export') : '',
      promptHost: prompt ? (prompt.device.dns || prompt.device.netbios || prompt.device.ip) : '',
      promptAddress: prompt ? `${prompt.device.protocol.toLowerCase()}://${prompt.device.ip}${prompt.device.protocol === 'SMB' ? ' · port 445' : ' · mountd discovery'}` : '',
      promptNote: prompt
        ? prompt.device.protocol === 'SMB'
          ? 'NTLM over SMB2/3 on port 445. A domain is applied as DOMAIN\\username. Credentials are held in memory for this session only or encrypted on this host when you select Save credentials.'
          : 'NFS sends no credentials: access uses the service account\'s AUTH_SYS UID/GID. NFSv4-only servers may not list their exports, so an absolute path can be entered here.'
        : '',
      promptSubmit: prompt
        ? (prompt.device.protocol !== 'SMB' ? 'List exports' : prompt.credId === 'new' ? 'Sign in and list shares' : 'Use saved credentials')
        : '',
      promptUser: prompt?.username || '',
      promptPass: prompt?.password || '',
      promptDomain: prompt?.domain || '',
      promptVersion: prompt?.version || '4',
      promptExport: prompt?.export || '',
      // Typing new credentials deselects whatever saved card was picked.
      setPromptUser: event => this.setState({ prompt: { ...prompt, username: event.target.value, credId: 'new' } }),
      setPromptPass: event => this.setState({ prompt: { ...prompt, password: event.target.value, credId: 'new' } }),
      setPromptDomain: event => this.setState({ prompt: { ...prompt, domain: event.target.value, credId: 'new' } }),
      setPromptVersion: event => this.setPrompt('version', event.target.value),
      setPromptExport: event => this.setPrompt('export', event.target.value),
      promptCredId: prompt?.credId || 'new',
      promptNewCreds: prompt?.device.protocol === 'SMB' && prompt.credId === 'new',
      promptSavedCred: prompt?.device.protocol === 'SMB' && prompt.credId !== 'new',
      setPromptCred: event => this.setPrompt('credId', event.target.value),
      noSavedCreds: !this.state.creds.some(cred=>!prompt||cred.host===prompt.device.ip.toLowerCase()),
      credOptions: this.state.creds.filter(cred=>!prompt||cred.host===prompt.device.ip.toLowerCase()).map(cred => {
        const on = prompt?.credId === cred.id
        return {
          who: `${cred.domain ? `${cred.domain}\\` : ''}${cred.username}`,
          note: cred.note,
          bg: on ? '#eef2fb' : '#fff',
          line: on ? '#3f6fd1' : '#e2e5ea',
          tickBg: on ? '#3f6fd1' : '#fff',
          tickLine: on ? '#2b57ae' : '#c0c5cc',
          tickInk: on ? '#fff' : 'transparent',
          pick: () => this.setPrompt('credId', cred.id)
        }
      }),
      savedCredNote: prompt && prompt.credId !== 'new'
        ? (() => {
          const cred = this.state.creds.find(item => item.id === prompt.credId)
          return cred ? `Signing in as ${cred.domain ? `${cred.domain}\\` : ''}${cred.username}. The password is read from the encrypted store — it is never shown.` : ''
        })()
        : '',
      promptStore: !!prompt?.store,
      promptShared: !!prompt?.shared,
      storeTickBg: prompt?.store ? '#3f6fd1' : '#fff',
      storeTickLine: prompt?.store ? '#2b57ae' : '#c0c5cc',
      storeTickInk: prompt?.store ? '#fff' : 'transparent',
      sharedTickBg: prompt?.shared ? '#3f6fd1' : '#fff',
      sharedTickLine: prompt?.shared ? '#2b57ae' : '#c0c5cc',
      sharedTickInk: prompt?.shared ? '#fff' : 'transparent',
      sharedCursor: prompt?.store ? 'pointer' : 'not-allowed',
      sharedOpacity: prompt?.store ? '1' : '.5',
      togglePromptStore: () => this.setPrompt('store', !prompt.store),
      closePrompt: () => this.setState({ prompt: null }),
      submitPrompt: event => { if (event && event.preventDefault) event.preventDefault(); this.submitPrompt() },

      zipOpen: !!this.state.zip,
      zipName: this.state.zip ? this.zipName(this.state.zip.picked) : '',
      zipSize: this.state.zip ? this.bytes(this.zipTotal(this.state.zip.picked)) : '',
      zipContents: this.state.zip
        ? (() => {
          const picked = this.state.zip.picked
          const dirs = picked.filter(entry => entry.type === 'directory').length
          const head = `${picked.length} item${picked.length === 1 ? '' : 's'}`
          return dirs ? `${head} · ${dirs} folder${dirs === 1 ? '' : 's'} walked recursively` : head
        })()
        : '',
      zipParts: this.state.zip
        ? (this.state.zip.split === 'none'
          ? 'One ZIP file, staged before downloading'
          : this.zipLimit() === 0
            ? 'Enter a part size above zero'
            : `Up to ${this.zipPartCount()} parts of ${this.bytes(this.zipLimit())} · name.zip.001, .002 … each part supports resume. Join all parts in order before opening the ZIP.`)
        : '',
      zipCustom: this.state.zip?.split === 'custom',
      zipCustomValue: this.state.zip?.custom || '',
      setZipCustom: event => this.setState({ zip: { ...this.state.zip, split: 'custom', custom: event.target.value } }),
      zipUnits: ['MB', 'GB'].map(unit => ({
        label: unit,
        bg: this.state.zip?.unit === unit ? '#3f6fd1' : '#fff',
        ink: this.state.zip?.unit === unit ? '#fff' : '#4d545c',
        line: this.state.zip?.unit === unit ? '#2b57ae' : '#c8ccd3',
        pick: () => this.setState({ zip: { ...this.state.zip, unit, split: 'custom' } })
      })),
      zipStores: STORES.map((store, index) => {
        const needed = this.state.zip ? this.zipNeeded(this.state.zip.picked) : 0
        const fits = needed <= store.free
        const on = this.state.zip?.store === index
        return {
          label: store.label, path: store.path,
          free: `${this.bytes(store.free)} free of ${this.bytes(store.total)}`,
          verdict: fits ? `Fits — ${this.bytes(store.free - needed)} left after` : `Too small by ${this.bytes(needed - store.free)}`,
          verdictInk: fits ? '#2f7d55' : '#7e2c20',
          usedWidth: `${Math.min(100, Math.round((store.total - store.free) / store.total * 100))}%`,
          needWidth: `${Math.min(100 - Math.round((store.total - store.free) / store.total * 100), Math.round(needed / store.total * 100))}%`,
          needBar: fits ? '#3f6fd1' : '#b4402f',
          bg: on ? '#eef2fb' : '#fff',
          line: on ? '#3f6fd1' : '#e2e5ea',
          tickBg: on ? '#3f6fd1' : '#fff',
          tickLine: on ? '#2b57ae' : '#c0c5cc',
          tickInk: on ? '#fff' : 'transparent',
          pick: () => this.setState({ zip: { ...this.state.zip, store: index } })
        }
      }),
      zipNeeded: this.state.zip ? this.bytes(this.zipNeeded(this.state.zip.picked)) : '',
      zipFits: this.state.zip ? this.zipNeeded(this.state.zip.picked) <= STORES[this.state.zip.store].free : true,
      zipBlocked: this.state.zip ? this.zipNeeded(this.state.zip.picked) > STORES[this.state.zip.store].free : false,
      zipStartBg: this.state.zip && this.zipNeeded(this.state.zip.picked) > STORES[this.state.zip.store].free ? '#a8b0ba' : '#3f6fd1',
      zipStartLine: this.state.zip && this.zipNeeded(this.state.zip.picked) > STORES[this.state.zip.store].free ? '#98a0aa' : '#2b57ae',
      zipSplits: ['none', '1', '2', '4', 'custom'].map(value => ({
        label: value === 'none' ? 'Single file' : value === 'custom' ? 'Custom' : `${value} GB parts`,
        bg: this.state.zip?.split === value ? '#3f6fd1' : 'rgba(255,255,255,.9)',
        ink: this.state.zip?.split === value ? '#fff' : '#1c2024',
        line: this.state.zip?.split === value ? '#2b57ae' : '#c8ccd3',
        pick: () => this.setState({ zip: { ...this.state.zip, split: value } })
      })),
      closeZip: () => this.setState({ zip: null }),
      confirmZip: event => { if (event && event.preventDefault) event.preventDefault(); this.confirmZip() },

      addView: this.state.view === 'add',
      addType: this.state.addType || 'smb',
      addLocal: (this.state.addType || 'smb') === 'local',
      addSmb: (this.state.addType || 'smb') === 'smb',
      addNfs: (this.state.addType || 'smb') === 'nfs',
      addTypes: [
        { value: 'local', label: 'This machine' },
        { value: 'smb', label: 'SMB share' },
        { value: 'nfs', label: 'NFS export' }
      ].map(option => ({
        label: option.label,
        bg: (this.state.addType || 'smb') === option.value ? '#3f6fd1' : '#fff',
        ink: (this.state.addType || 'smb') === option.value ? '#fff' : '#1c2024',
        line: (this.state.addType || 'smb') === option.value ? '#2b57ae' : '#c8ccd3',
        pick: () => this.setState({ addType: option.value })
      })),
      addNote: (this.state.addType || 'smb') === 'smb'
        ? 'NTLM over SMB2/3 on port 445. A domain is applied as DOMAIN\\username, and IPv6 literals are not supported — use an IPv4 address.'
        : (this.state.addType || 'smb') === 'nfs'
          ? 'No credentials: access uses the service account\'s AUTH_SYS UID/GID. NFSv4-only servers may not list exports, so enter the absolute path.'
          : 'Only roots the service policy permits can be opened.',
      addConnect: () => this.addLocation(),
      addDiscover: () => this.addLocation(true),
      addRoot: this.state.add?.root || '',
      setAddRoot: event => this.setState({add:{...this.state.add,root:event.target.value}}),
      addHost: this.state.add?.host || '',
      setAddHost: event => this.setState({add:{...this.state.add,host:event.target.value}}),
      addShare: this.state.add?.share || '',
      setAddShare: event => this.setState({add:{...this.state.add,share:event.target.value}}),
      addUsername: this.state.add?.username || '',
      setAddUsername: event => this.setState({add:{...this.state.add,username:event.target.value}}),
      addPassword: this.state.add?.password || '',
      setAddPassword: event => this.setState({add:{...this.state.add,password:event.target.value}}),
      addDomain: this.state.add?.domain || '',
      setAddDomain: event => this.setState({add:{...this.state.add,domain:event.target.value}}),
      addExport: this.state.add?.export || '',
      setAddExport: event => this.setState({add:{...this.state.add,export:event.target.value}}),
      addVersion: this.state.add?.version || '4',
      setAddVersion: event => this.setState({add:{...this.state.add,version:event.target.value}}),
      closeAdd: () => this.setState({ view: 'browse' }),

      signoutOpen: !!this.state.signout,
      askSignout: () => this.setState({ signout: true, menu: null }),
      closeSignout: () => this.setState({ signout: false }),
      doSignout: () => this.signout(),

      transfersView: this.state.view === 'transfers',
      dlPad: roomy ? '8px 12px' : '0 9px',
      dlBg: this.state.view === 'transfers' ? '#e3ebfb' : this.state.transfers.length ? '#eef2fb' : 'rgba(255,255,255,.75)',
      dlLine: this.state.view === 'transfers' || this.state.transfers.length ? '#b6c6e8' : '#d5d9df',
      dlInk: this.state.view === 'transfers' || this.state.transfers.length ? '#22417d' : '#4d545c',
      trayToggle: () => this.toView('transfers'),
      closeTransfers: () => this.setState({ view: 'browse' }),
      trayCount: this.state.transfers.filter(job => !job.purged).length || this.state.transfers.length,
      hasTransfers: this.state.transfers.length > 0,
      noTransfers: this.state.transfers.length === 0,
      transfersTitle: this.state.transfers.length && this.state.transfers.every(job => job.kind === 'files')
        ? 'Files queued for download'
        : 'Zips being prepared and downloaded',
      packingCount: `${this.state.transfers.filter(job => job.stage === 'packing').length} packing`,
      readyCount: `${this.state.transfers.filter(job => job.stage === 'ready' && job.parts.some(part => !part.downloaded)).length} ready to download`,
      stagedTotal: `${this.bytes(this.state.transfers.reduce((sum, job) => sum + this.stagedOf(job), 0))} staged`,
      storeUse: STORES.map(store => {
        const staged = this.state.transfers.filter(job => job.store === store.label).reduce((sum, job) => sum + this.stagedOf(job), 0)
        const free = this.freeOf(store)
        return {
          path: store.path,
          staged: staged ? `${this.bytes(staged)} staged` : 'nothing staged',
          free: `${this.bytes(free)} free of ${this.bytes(store.total)}`,
          usedWidth: `${Math.min(100, Math.round((store.total - store.free) / store.total * 100))}%`,
          stagedWidth: `${Math.min(100, Math.round(staged / store.total * 100))}%`,
          low: free < store.total * 0.05,
          freeInk: free < store.total * 0.05 ? '#7e2c20' : '#6a727c'
        }
      }),
      clearFinished: () => this.clearFinished(),
      transfers: this.state.transfers.map(job => {
        const percent = job.total ? Math.min(100,Math.round(job.packed / job.total * 100)) : job.stage==='ready'?100:0
        const ready = this.readyParts(job)
        const grabbed = job.parts.filter(part => part.downloaded).length
        const remaining = job.stage === 'packing' && job.status === 'running' && job.speed
          ? Math.round((job.total - job.packed) / job.speed) : null
        const staged = this.stagedOf(job)
        const allGrabbed = job.stage === 'ready' && grabbed === job.parts.length
        return {
          name: job.name,
          stageLabel: job.error ? `Failed: ${job.error}` : job.purged ? 'Purged' : job.stage === 'packing' ? (job.status === 'paused' ? 'Packing paused' : 'Packing') : allGrabbed ? 'Handed to browser' : 'Ready to download',
          stageInk: job.purged ? '#6a727c' : job.stage === 'packing' ? '#22417d' : allGrabbed ? '#2f7d55' : '#22417d',
          stageBg: job.purged ? '#f0f1f4' : allGrabbed && !job.purged ? '#e8f4ec' : '#eaf0fc',
          packShown: job.stage === 'packing',
          percent: `${percent}%`,
          bar: job.status === 'paused' ? '#a8b0ba' : '#3f6fd1',
          progress: `${this.bytes(job.packed)} of ${this.bytes(job.total)} packed`,
          rate: job.status === 'paused'
            ? 'Paused — packing resumes where it stopped'
            : remaining != null ? `${this.bytes(job.speed)}/s · ${remaining > 60 ? `${Math.round(remaining / 60)} min` : `${remaining}s`} left` : 'Starting…',
          pauseLabel: job.status === 'paused' ? 'Resume packing' : 'Pause packing',
          pauseShown: job.stage === 'packing' && !job.purged,
          summary: job.kind === 'files'
            ? `${grabbed} of ${job.parts.length} file${job.parts.length === 1 ? '' : 's'} handed to browser · ${this.bytes(job.total)} total`
            : `${grabbed} of ${job.parts.length} part${job.parts.length === 1 ? '' : 's'} handed to browser · ${ready} ready`,
          store: job.kind === 'files' ? 'streamed from the share — nothing staged' : `staged on ${job.store}`,
          stagedNote: job.kind === 'files' ? '' : job.purged ? 'Staged parts removed from the store' : `${this.bytes(staged)} still staged`,
          listLabelShown: job.parts.length > 1,
          grabAllShown: !job.purged && ready > grabbed && !(job.kind === 'files' && job.parts.length === 1),
          grabAllLabel: job.kind === 'files' ? 'Show file links' : 'Show ready part links',
          grabAll: () => this.grabAll(job),
          purgeShown: job.kind !== 'files' && !job.purged,
          purgeLabel: allGrabbed ? `Purge staged parts (frees ${this.bytes(staged)})` : `Purge anyway (frees ${this.bytes(staged)})`,
          purgeInk: allGrabbed ? '#1c2024' : '#7e2c20',
          purge: () => this.purgeJob(job),
          listLabel: job.open ? 'Hide parts' : `Show ${job.parts.length} part${job.parts.length === 1 ? '' : 's'}`,
          open: job.open,
          toggle: () => this.toggleJob(job.id),
          parts: job.parts.map((part, index) => ({
            label: part.name || `${job.name}.${String(index + 1).padStart(3, '0')}`,
            linkInk: job.purged ? '#a8b0ba' : index < ready ? '#3f6fd1' : '#a8b0ba',
            linkCursor: !job.purged && index < ready ? 'pointer' : 'default',
            linkLine: !job.purged && index < ready ? 'underline' : 'none',
            size: this.bytes(part.size),
            state: job.purged ? 'purged' : part.downloaded ? 'handed off' : index < ready ? 'ready' : 'packing',
            stateLabel: job.purged ? 'purged' : part.downloaded ? 'handed off' : index < ready ? 'ready' : 'packing…',
            stateInk: part.downloaded && !job.purged ? '#2f7d55' : '#6a727c',
            action: part.downloaded ? 'Again' : 'Download',
            actionInk: part.downloaded ? '#6a727c' : '#22417d',
            actionShown: !job.purged && index < ready,
            grab: () => this.grabPart(job, index, false)
          })),
          drop: () => this.dropTransfer(job.id),
          pause: () => this.setTransfer(job.id, job.status === 'paused' ? 'running' : 'paused')
        }
      }),
      confirmOpen: !!this.state.confirm,
      confirmName: this.state.confirm
        ? (() => {
          const job = this.state.transfers.find(item => item.id === this.state.confirm.jobId)
          if (!job) return ''
          const part = job.parts[this.state.confirm.index]
          return part?.name || `${job.name}.${String(this.state.confirm.index + 1).padStart(3, '0')}`
        })()
        : '',
      closeConfirm: () => this.setState({ confirm: null }),
      confirmAgain: () => {
        const pending = this.state.confirm.picked
        if (pending) return this.startBatch(pending, true)
        const job = this.state.transfers.find(item => item.id === this.state.confirm.jobId)
        if (job) this.grabPart(job, this.state.confirm.index, true)
      },

      menuOpen: !!menu,
      menuX: menu ? `${menu.x}px` : '0px',
      menuY: menu ? `${menu.y}px` : '0px',
      closeMenu: () => this.setState({ menu: null }),
      menuItems: (menu?.kind === 'toolbar' ? [{label:'New folder',on:this.can('mkdir'),run:()=>this.newFolder()},{label:'Upload files',on:this.can('write'),run:()=>this.upload()},{label:'Sign out',on:true,run:()=>this.setState({signout:true,menu:null})}] : menu?.kind === 'device' ? this.deviceItems(menu.device)
        : menu?.kind === 'mount' ? this.mountItems(menu.host)
        : menu?.kind === 'pin' ? this.pinItems(menu.pin)
        : menu?.kind === 'share' ? this.shareItems(menu.host, menu.share)
        : this.items()).map(item => item.divider ? { divider: true, action: false } : {
        divider: false, action: true, label: item.label, keys: item.keys, run: item.on ? item.run : () => {},
        ink: item.on ? '#1c2024' : '#9aa1ab', opacity: item.on ? '1' : '.6',
        cursor: item.on ? 'pointer' : 'default', hoverBg: item.on ? '#eef2fb' : 'transparent'
      }),
      sessionLabel: this.state.session ? this.state.session.descriptor.type.toUpperCase() + ' · Connected' : 'No connection',
      disconnect: () => this.disconnect(),
      uploadStatus: this.state.upload, cancelUpload: () => this.uploadRequest?.abort(),
      toast: this.state.toast
    }
  }  async api(path, body, method = body === undefined ? 'GET' : 'POST') {
    const response = await fetch('/api' + path, {method, credentials:'same-origin', headers:body === undefined ? {} : {'Content-Type':'application/json'}, body:body === undefined ? undefined : JSON.stringify(body)})
    if (!response.ok) {
      const data = await response.json().catch(() => ({}))
      const error = new Error(data.detail || `Request failed (${response.status})`)
      error.status = response.status
      if (response.status === 401) parent.location.href='/'
      this.say(error.message)
      throw error
    }
    return response.json()
  }
  can(operation) {return !!this.state.session?.operations.includes(operation)}
  fromDescriptor(descriptor) {
    const {path='/', credential_id, ...base} = descriptor
    const clean = base.type === 'local' ? {type:'local',root:base.root} : base.type === 'smb' ? {type:'smb',host:base.host,share:base.share} : {type:'nfs',host:base.host,export:base.export,version:base.version||4}
    if (credential_id) clean.credential_id = credential_id
    return {host:base.type === 'local' ? '' : `${base.type}://${base.host}`, share:base.root || base.share || base.export, folders:path.split('/').filter(Boolean), descriptor:clean}
  }
  currentPath(place=this.state.place) {return '/' + place.folders.join('/')}
  childPath(name, place=this.state.place) {return (this.currentPath(place).replace(/\/$/,'') + '/' + name)}
  async sessionFor(place, fresh=false) {
    const descriptor = place.descriptor
    if (!descriptor) throw new Error('Open a location first')
    const key = JSON.stringify(descriptor)
    if (!fresh && this.sessions.has(key)) return this.sessions.get(key)
    const session = await this.api('/sessions', {descriptor,credentials:this.auth.get(`${descriptor.type}:${descriptor.host}`)})
    this.sessions.set(key,session)
    return session
  }
  async loadPlace(place) {
    const generation = ++this.navigation
    this.setState({listing:[], session:null, loading:true})
    try {
      let session = await this.sessionFor(place), data
      try {data=await this.api(`/sessions/${session.id}/list?${new URLSearchParams({path:this.currentPath(place)})}`)}
      catch(error) {
        if (![404,410].includes(error.status)) throw error
        session=await this.sessionFor(place,true)
        data=await this.api(`/sessions/${session.id}/list?${new URLSearchParams({path:this.currentPath(place)})}`)
      }
      if (generation !== this.navigation) return
      this.setState({session, listing:data.entries.map(row=>({...row, modifiedTime:row.modified ? new Date(typeof row.modified === 'number' ? row.modified*1000 : row.modified).getTime() : 0, modified:row.modified ? new Date(typeof row.modified === 'number' ? row.modified*1000 : row.modified).toLocaleString() : '—'})), loading:false})
      if (data.truncated || data.skipped) this.say(`Listing incomplete: ${data.skipped} excluded entries${data.truncated ? '; entry limit reached' : ''}.`)
    } catch(error) {if(generation===this.navigation)this.setState({loading:false}); throw error}
  }
  refresh() {if(this.state.place.descriptor)return this.loadPlace(this.state.place)}
  async reloadSaved() {
    const [pins,credentials]=await Promise.all([this.api('/saved'),this.api('/credentials')])
    this.setState({pins:pins.locations.map(pin=>({...pin,place:this.fromDescriptor({...pin.descriptor,credential_id:pin.has_credentials?pin.id:undefined})})), creds:credentials.credentials.map(row=>({...row,note:`Saved for ${row.host}`})), savedAvailable:pins.available})
  }
  async addLocation(discover=false) {
    const type=this.state.addType||'smb', values=this.state.add||{}
    if(type==='local')return this.goTo(this.fromDescriptor({type,root:values.root||''}))
    await this.mapDevice({protocol:type.toUpperCase(),ip:values.host||''},{credentials:type==='smb'?{username:values.username||'',password:values.password||'',domain:values.domain||''}:undefined,share:discover?'':values.share,export:discover?'':values.export,version:values.version||4})
    this.setState({add:{}})
  }
  async newFolder() {
    if(!this.can('mkdir'))return this.say('Folder creation is not permitted')
    const name=await this.dialog('New folder','Folder name','Untitled folder','Create')
    if(!name)return
    this.validName(name)
    await this.api(`/sessions/${this.state.session.id}/mkdir`,{path:this.childPath(name)})
    await this.refresh()
  }
  validName(name) {if(!name.trim()||name==='.'||name==='..'||/[\\/:\x00]/.test(name))throw new Error('Use a name without slashes, colons or traversal')}
  async newFile() {
    const name=await this.dialog('New text file','File name','Untitled.txt','Create');if(!name)return;this.validName(name)
    const path=this.childPath(name);await this.uploadBlob(this.state.session.id,path,new Blob(['']))
    await this.refresh();await this.preview(this.entries().find(e=>e.path===path)||{name,path})
  }
  async renameEntry(entry) {
    const name=await this.dialog('Rename',entry.name,entry.name,'Rename')
    if(!name||name===entry.name)return
    this.validName(name)
    await this.api(`/sessions/${this.state.session.id}/rename`,{source:entry.path,destination:this.childPath(name)})
    await this.refresh()
  }
  dialog(title,message,value=null,action='OK') {
    this.setState({menu:null})
    return new Promise(resolve=>{
      const dialog=document.createElement('dialog');dialog.className='manager-dialog'
      const form=document.createElement('form');form.method='dialog'
      const heading=document.createElement('h2');heading.textContent=title
      const text=document.createElement('p');text.textContent=message
      form.append(heading,text)
      let input
      if(value!==null){input=document.createElement('input');input.value=value;input.required=true;input.setAttribute('aria-label',message);form.append(input)}
      const buttons=document.createElement('div');buttons.className='dialog-buttons'
      const cancel=document.createElement('button');cancel.type='button';cancel.textContent='Cancel';cancel.onclick=()=>dialog.close()
      const ok=document.createElement('button');ok.textContent=action;ok.className='primary'
      buttons.append(cancel,ok);form.append(buttons);dialog.append(form);document.body.append(dialog)
      form.onsubmit=e=>{e.preventDefault();dialog.close('ok')}
      dialog.onclose=()=>{const result=dialog.returnValue==='ok'?(input?input.value:true):null;dialog.remove();resolve(result)}
      dialog.showModal();input?.select()
    })
  }
  async preview(entry) {
    const session=this.state.session
    const info=await this.api(`/sessions/${session.id}/stat?${new URLSearchParams({path:entry.path})}`)
    if(info.size>1048576)return this.say('Preview is limited to 1 MiB. Download this file to open it locally.')
    const response=await fetch(`/api/sessions/${session.id}/file?${new URLSearchParams({path:entry.path})}`)
    if(!response.ok)throw new Error('Unable to read the file')
    const reader=response.body.getReader(), chunks=[];let size=0
    try {while(true){const {value,done}=await reader.read();if(done)break;size+=value.length;if(size>1048576)throw new Error('File grew beyond the preview limit');chunks.push(value)}}finally{await reader.cancel()}
    const bytes=new Uint8Array(size);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length}
    let text
    try {text=new TextDecoder('utf-8',{fatal:true}).decode(bytes);if(text.includes('\0'))throw new Error()}
    catch{return this.say('This is a binary file. Download it to open it locally.')}
    const dialog=document.createElement('dialog');dialog.className='manager-dialog editor'
    const title=document.createElement('h2');title.textContent=entry.name
    const area=document.createElement('textarea');area.value=text;area.setAttribute('aria-label','File contents');area.readOnly=!this.can('write')
    const controls=document.createElement('div');controls.className='dialog-buttons'
    const close=document.createElement('button');close.textContent='Close';close.onclick=()=>dialog.close()
    const save=document.createElement('button');save.textContent='Save';save.disabled=area.readOnly
    save.onclick=async()=>{save.disabled=true;try{await this.uploadBlob(session.id,entry.path,new Blob([area.value]),true);dialog.close();await this.refresh()}catch(error){this.say(error.message);save.disabled=false}}
    controls.append(close,save);dialog.append(title,area,controls);document.body.append(dialog);dialog.onclose=()=>dialog.remove();dialog.showModal()
  }
  uploadBlob(id,path,file,overwrite=false) {
    return new Promise((resolve,reject)=>{
      const xhr=new XMLHttpRequest();this.uploadRequest=xhr
      xhr.open('PUT',`/api/sessions/${id}/file?${new URLSearchParams({path,overwrite:String(overwrite)})}`)
      xhr.upload.onprogress=e=>this.setState({upload:`Uploading ${file.name||path}: ${this.bytes(e.loaded)}${e.lengthComputable?' / '+this.bytes(e.total):''}`})
      xhr.onload=()=>{this.setState({upload:null});this.uploadRequest=null;if(xhr.status>=200&&xhr.status<300)resolve();else{let message='Upload failed';try{message=JSON.parse(xhr.responseText).detail}catch{}reject(new Error(message))}}
      xhr.onerror=xhr.onabort=()=>{this.setState({upload:null});this.uploadRequest=null;reject(new Error('Upload interrupted; destination was not replaced'))}
      xhr.send(file)
    })
  }
  upload() {
    if(!this.can('write'))return
    const input=document.createElement('input');input.type='file';input.multiple=true
    const session=this.state.session,place=this.state.place
    input.onchange=async()=>{try{for(const file of input.files){if(file.size>session.max_write_bytes)throw new Error(`${file.name} exceeds the upload limit`);const existing=this.entries().some(e=>e.name===file.name);if(existing&&!await this.dialog('Replace file',`Replace ${file.name}?`,null,'Replace'))continue;await this.uploadBlob(session.id,this.childPath(file.name,place),file,existing)}}finally{await this.refresh()}}
    input.click()
  }
  async info(entries) {
    const rows=await Promise.all(entries.map(e=>this.api(`/sessions/${this.state.session.id}/stat?${new URLSearchParams({path:e.path})}`)))
    await this.dialog('Get info',rows.map(e=>`${e.path} · ${e.type} · ${this.bytes(e.size)} · ${e.modified||'—'}`).join('\n'))
  }
  async pollJobs() {
    if(this.polling)return
    this.polling=true
    try {
      const data=await this.api('/downloads')
      this.setState({stores:data.stores, transfers:[...this.state.transfers.filter(j=>j.kind==='files'),...data.jobs.map(job=>({...job,open:this.state.transfers.find(j=>j.id===job.id)?.open??true}))]})
    }finally{this.polling=false}
  }
  async disconnect() {
    const session=this.state.session
    if(session){await this.api(`/sessions/${session.id}`,undefined,'DELETE');for(const [key,value] of this.sessions)if(value.id===session.id)this.sessions.delete(key)}
    this.setState({place:{host:'',share:'',folders:[]},listing:[],selected:[],session:null})
  }
  async signout() {await this.api('/login',undefined,'DELETE');this.auth.clear();parent.location.reload()}

}

return Component
}
