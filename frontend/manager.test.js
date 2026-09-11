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
