import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import vm from 'node:vm'
const scope={window:{innerWidth:1280},URLSearchParams,TextDecoder,Blob,crypto:globalThis.crypto,setTimeout,clearTimeout}
vm.runInNewContext(readFileSync(new URL('../src/remote_fs_browser/web/manager.js',import.meta.url),'utf8'),scope)
class Logic {setState(value){Object.assign(this.state,value)}}
const Manager=scope.window.createRemoteFsManager(Logic,{createRef:()=>({})})
function manager(){const instance=new Manager();instance.sessions=new Map();instance.auth=new Map();instance.say=()=>{};return instance}

test('manual local, SMB and NFS descriptors preserve actual backend and path',()=>{
 const m=manager()
 for(const descriptor of [{type:'local',root:'/srv/files',path:'/a/b'},{type:'smb',host:'192.0.2.1',share:'files',path:'/a/b',credential_id:'saved'},{type:'nfs',host:'nas',export:'/data',version:3,path:'/a/b'}]){
  const place=m.fromDescriptor(descriptor)
  assert.equal(m.currentPath(place),'/a/b')
  assert.equal(place.descriptor.type,descriptor.type)
  assert.equal(place.descriptor.host,descriptor.host)
 }
})

test('multi-selection cut copies to the destination before deleting each source',async()=>{
 const m=manager(),calls=[]
 const source=m.fromDescriptor({type:'smb',host:'nas',share:'files',path:'/source'})
 m.state.place=m.fromDescriptor({type:'local',root:'/srv',path:'/target'})
 m.state.session={id:'target'};m.state.clipboard={place:source,names:['one','two'],cut:true}
 m.sessionFor=async()=>({id:'source'});m.api=async(...args)=>calls.push(JSON.parse(JSON.stringify(args)));m.refresh=async()=>{}
 await m.paste()
 assert.deepEqual(calls.map(c=>c[0]),['/sessions/source/copy','/sessions/source/entry?path=%2Fsource%2Fone&recursive=true','/sessions/source/copy','/sessions/source/entry?path=%2Fsource%2Ftwo&recursive=true'])
 assert.deepEqual(calls[0][1],{source:'/source/one',destination:'/target/one',target_session:'target'})
 assert.equal(m.state.clipboard,null)
})

test('failed cross-backend copy never deletes the original and retains remaining clipboard',async()=>{
 const m=manager(),calls=[]
 m.state.place=m.fromDescriptor({type:'local',root:'/srv'})
 m.state.session={id:'target'};m.state.clipboard={place:m.state.place,names:['one'],cut:true}
 m.sessionFor=async()=>({id:'source'});m.refresh=async()=>{}
 m.api=async path=>{calls.push(path);throw new Error('disk full')}
 await assert.rejects(m.paste(),/disk full/)
 assert.deepEqual(calls,['/sessions/source/copy']);assert.equal(m.state.clipboard.names[0],'one')
})

test('scanner follows server pagination and retains DNS, NetBIOS and IP together',async()=>{
 const m=manager(),offsets=[];m.state.ranges='192.0.2.0/23'
 m.api=async(path,body)=>{offsets.push(body.offset);return {hosts:[{host:'192.0.2.5',dns_name:'nas.example',netbios_name:'NAS',protocols:['smb','nfs']}],scan_offset:body.offset,scanned:body.offset?254:256,total_addresses:510,next_offset:body.offset?null:256,notes:[]}}
 await m.startScan()
 assert.deepEqual(offsets,[0,256]);assert.equal(m.state.devices.length,2)
 assert.equal(m.state.devices[0].dns,'nas.example');assert.equal(m.state.devices[0].netbios,'NAS');assert.equal(m.state.devices[0].ip,'192.0.2.5')
 assert.equal(m.state.probed,510);assert.equal(m.state.scan,'done')
})

test('ZIP estimates and submissions use server bytes, selected store and actual paths',async()=>{
 const m=manager(),calls=[];m.state.session={id:'source'}
 m.api=async(path,body)=>{calls.push([path,body]);return path.endsWith('estimate')?{total:17,needed:2048,stores:[{id:'scratch',free:9999}]}:{}}
 m.pollJobs=async()=>{}
 await m.openZip([{name:'folder',path:'/real/folder',type:'directory'}])
 assert.equal(m.zipTotal(),17);assert.equal(m.zipNeeded(),2048)
 m.state.zip.split='custom';m.state.zip.custom='1';m.state.zip.unit='MB'
 await m.confirmZip()
 assert.equal(calls[1][1].store,'scratch');assert.equal(calls[1][1].part_size,1048576)
 assert.equal(calls[1][1].paths[0],'/real/folder')
})

test('context menu dismisses before running an enabled action and preserves selection',()=>{
 const m=manager();m.state.menu={kind:'file',x:1,y:1};m.state.selected=['alpha.txt']
 let called=false
 m.items=()=>[{label:'Upload files here',on:true,run:()=>{called=true;assert.equal(m.state.menu,null);assert.deepEqual(m.state.selected,['alpha.txt'])}}]
 m.renderVals().menuItems[0].run()
 assert.equal(called,true)
})

test('narrow viewport sidebar overlays the list and closes when navigating',()=>{
 const m=manager();m.state.width=390;m.state.collapsed=false
 const open=m.renderVals();assert.equal(open.mobileRailOpen,true)
 m.state.collapsed=true;assert.equal(m.renderVals().listCols,open.listCols)
 m.state.collapsed=false;m.goTo(m.fromDescriptor({type:'local',root:'/tmp/files'}))
 assert.equal(m.state.collapsed,true)
})


test('direct downloads work on HTTP origins without crypto.randomUUID',async()=>{
 const httpScope={...scope,window:{innerWidth:1280},crypto:{getRandomValues:globalThis.crypto.getRandomValues.bind(globalThis.crypto)}}
 vm.runInNewContext(readFileSync(new URL('../src/remote_fs_browser/web/manager.js',import.meta.url),'utf8'),httpScope)
 const HttpManager=httpScope.window.createRemoteFsManager(Logic,{createRef:()=>({})})
 const m=new HttpManager();m.state.place=m.fromDescriptor({type:'smb',host:'nas',share:'files',path:'/repo'})
 m.sessionFor=async()=>({id:'session'})
 await m.startBatch([{name:'README.md',path:'/repo/README.md',size:42}])
 assert.equal(m.state.view,'transfers')
 assert.equal(m.state.transfers.length,1)
 assert.match(m.state.transfers[0].id,/^[0-9a-f]{32}$/)
 assert.equal(m.state.transfers[0].parts[0].relative,'/repo/README.md')
 assert.equal(m.state.transfers[0].status,'ready')
})

test('configured endpoints keep their identity when opening and saving folders',()=>{
 const m=manager()
 for(const type of ['rclone','libvirt']){
  const place=m.fromDescriptor({type,endpoint:'approved',path:'/folder'})
  assert.equal(place.descriptor.type,type)
  assert.equal(place.descriptor.endpoint,'approved')
  assert.equal(place.host,`${type}://approved`)
  assert.equal(m.currentPath(place),'/folder')
 }
})

test('saving a cloud connection uses provider fields and opens its credential-free descriptor',async()=>{
 const m=manager(),calls=[]
 m.state.cloud={label:'S3 archive',provider:'s3',options:{secret_access_key:'secret'}}
 m.state.cloudProviders=[{id:'s3',fields:[{name:'secret_access_key',secret:true,default:''},{name:'region',default:'us-east-1'}]}]
 m.api=async(...args)=>{calls.push(args);return {id:'cloud-test',endpoint:'cloud-test',type:'rclone',provider:'s3',label:'S3 archive',root:'/',read_only:false}}
 m.reloadRemotes=async()=>{};m.sessionFor=async place=>{assert.equal(place.descriptor.endpoint,'cloud-test');assert.equal(place.descriptor.secret_access_key,undefined)}
 m.goTo=place=>{assert.equal(place.descriptor.type,'rclone')}
 await m.saveCloud()
 assert.equal(calls[0][0],'/remotes');assert.equal(calls[0][1].options.region,'us-east-1')
 assert.equal(m.state.cloud.options,undefined);assert.equal(m.state.cloudBusy,false)
})

test('cloud clipboard paste retains the source connection and targets the visible folder',async()=>{
 const m=manager(),calls=[]
 const source=m.fromDescriptor({type:'rclone',endpoint:'cloud-one',path:'/photos'})
 m.state.place=m.fromDescriptor({type:'rclone',endpoint:'cloud-two',path:'/backup'})
 m.state.session={id:'target'};m.state.clipboard={place:source,names:['album'],cut:false}
 m.sessionFor=async place=>{assert.equal(place.descriptor.endpoint,'cloud-one');m.state.place=m.fromDescriptor({type:'rclone',endpoint:'cloud-three',path:'/elsewhere'});return {id:'source'}}
 m.api=async(...args)=>calls.push(args);m.refresh=async()=>{}
 await m.paste()
 assert.deepEqual(JSON.parse(JSON.stringify(calls[0][1])),{source:'/photos/album',destination:'/backup/album',target_session:'target'})
 assert.equal(calls.length,1);assert.equal(m.state.clipboard.names[0],'album')
})

test('mount option appears only for SMB, NFS and cloud locations when the service allows mounts',()=>{
 const m=manager()
 const smb=m.fromDescriptor({type:'smb',host:'192.0.2.1',share:'Projects',path:'/'}),local=m.fromDescriptor({type:'local',root:'/srv'})
 m.state.mountInfo={enabled:false,mounts:[]}
 assert.equal(m.mountable(smb),false)
 m.state.mountInfo={enabled:true,available:true,mounts:[]}
 assert.equal(m.mountable(smb),true)
 assert.equal(m.mountable(m.fromDescriptor({type:'rclone',endpoint:'cloud-1'})),true)
 assert.equal(m.mountable(m.fromDescriptor({type:'nfs',host:'nas',export:'/srv',version:4})),true)
 assert.equal(m.mountable(local),false)
})

test('rubber-band selection picks the rows it crosses in visible order',()=>{
 const m=manager()
 m.state.listing=[{name:'b.txt',type:'file'},{name:'a.txt',type:'file'},{name:'docs',type:'directory'},{name:'c.txt',type:'file'}]
 // visible(): docs, a.txt, b.txt, c.txt at 0, 40, 80, 120
 const tops=[0,40,80,120],heights=[40,40,40,40]
 assert.deepEqual([...m.bandHits(tops,heights,50,95)],['a.txt','b.txt'])
 assert.deepEqual([...m.bandHits(tops,heights,-10,5)],['docs'])
 assert.deepEqual([...m.bandHits(tops,heights,160,200)],[])
})

test('the read-only badge needs a connected read-only location, and a failed load says why',async()=>{
 const m=manager();m.navigation=0
 m.state.place=m.fromDescriptor({type:'kubernetes',endpoint:'k3s',path:'/apps/Volumes/archive'})
 m.state.session=null;m.state.loading=true
 assert.equal(m.renderVals().readOnly,false)
 m.state.session={id:'s',operations:['list','stat','read'],descriptor:{type:'kubernetes'}}
 m.state.loading=false
 assert.equal(m.renderVals().readOnly,true)
 m.sessionFor=async()=>({id:'s',operations:['list'],descriptor:{type:'kubernetes'}})
 m.api=async()=>{const error=new Error('Pod web is using this volume; browse it under that pod');error.status=422;throw error}
 await assert.rejects(m.loadPlace(m.state.place))
 const view=m.renderVals()
 assert.equal(view.readOnly,false)
 assert.equal(view.emptyTitle,"Couldn't open this folder")
 assert.match(view.emptyHint,/Pod web is using this volume/)
})

test('a volume that is still attaching is retried until it opens',async()=>{
 const m=manager(),notes=[];m.navigation=0
 const realTimeout=scope.setTimeout;scope.setTimeout=(fn)=>realTimeout(fn,0)
 try {
  let calls=0
  m.sessionFor=async()=>({id:'s',operations:['list'],descriptor:{type:'kubernetes'}})
  m.api=async()=>{calls++;if(calls<3){notes.push(m.state.loadNote);const error=new Error('Attaching the volume; this can take up to a minute');error.status=503;throw error}return {entries:[{name:'old',path:'/old',type:'directory'}]}}
  await m.loadPlace(m.fromDescriptor({type:'kubernetes',endpoint:'k3s',path:'/apps/Volumes/archive'}))
  assert.equal(calls,3)
  assert.equal(m.state.listing[0].name,'old')
  assert.equal(m.state.loadError,null)
  assert.equal(m.state.loadNote,null)
 } finally {scope.setTimeout=realTimeout}
})

test('Kubernetes rows show their own kind and configured clusters appear in the sidebar',()=>{
 const m=manager()
 assert.equal(m.kindOf({name:'archive',type:'directory',capacity:1,kind:'Longhorn volume · not mounted'}),'Longhorn volume · not mounted')
 assert.equal(m.kindOf({name:'pool',type:'directory',capacity:1}),'Storage pool')
 m.state.endpoints=[{type:'kubernetes',endpoint:'k3s',label:'k3s'},{type:'rclone',endpoint:'c',label:'cloud'}]
 const view=m.renderVals()
 assert.equal(view.hasEndpoints,true)
 assert.deepEqual(view.endpointSidebar.map(e=>e.label),['k3s · Kubernetes'])
})

test('only the latest preview opens, so a slow earlier read never offers stale text to save',async()=>{
 const m=manager(),opened=[]
 m.state.place=m.fromDescriptor({type:'kubernetes',endpoint:'k3s',path:'/apps/web/app/etc'})
 m.state.session={id:'s',operations:['read','write'],descriptor:{type:'kubernetes'}}
 let release
 const gate=new Promise(done=>release=done)
 let calls=0
 m.api=async()=>{calls++;if(calls===1)await gate;return {size:3}}
 const realFetch=scope.fetch
 scope.fetch=async()=>({ok:true,body:{getReader:()=>{let sent=false;return {read:async()=>sent?{done:true}:(sent=true,{value:new TextEncoder().encode('new'),done:false}),cancel:async()=>{}}}}})
 const realDocument=scope.document
 scope.document={createElement:tag=>{const el={tag,children:[],append(...c){this.children.push(...c)},setAttribute(){},showModal(){opened.push(this)},close(){},remove(){},addEventListener(){},style:{}};return el},body:{append(){}}}
 try {
  const first=m.preview({name:'app.conf',path:'/apps/web/app/etc/app.conf'})
  await m.preview({name:'app.conf',path:'/apps/web/app/etc/app.conf'})
  release();await first
  assert.equal(opened.length,1)
 } finally {scope.fetch=realFetch;scope.document=realDocument}
})
