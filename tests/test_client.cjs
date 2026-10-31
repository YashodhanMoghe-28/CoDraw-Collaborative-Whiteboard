// Headless JS logic checks with simulated browser APIs; not a rendering test.
// Optional developer check: node tests/test_client.cjs
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const html=fs.readFileSync(path.join(__dirname,'../index.html'),'utf8');
const source=html.match(/<script>([\s\S]*?)<\/script>/)[1];
const elements=new Map(),timers=[],intervals=[],sockets=[],storage=new Map();
function element(id){if(!elements.has(id))elements.set(id,{value:id==='color'?'#2563eb':id==='width'?'4':'',textContent:'',style:{},classList:{toggle(){}},setAttribute(){},replaceChildren(){},append(){},click(){},setPointerCapture(){},getBoundingClientRect(){return {left:0,top:0,width:1000,height:600}},getContext(){return new Proxy({},{get:(t,k)=>t[k]||(()=>{}),set:(t,k,v)=>(t[k]=v,true)})}});return elements.get(id)}
class WebSocket{constructor(url){this.url=url;this.readyState=1;this.sent=[];sockets.push(this)}send(s){this.sent.push(JSON.parse(s))}close(){this.readyState=3;if(this.onclose)this.onclose()}}
const ctx={document:{getElementById:element,createElement:()=>element('new-'+Math.random())},sessionStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},location:{search:'',protocol:'http:',origin:'http://localhost:8765'},URL,URLSearchParams,WebSocket,console,confirm:()=>true,setTimeout:fn=>(timers.push(fn),timers.length),clearTimeout:()=>{},setInterval:fn=>intervals.push(fn)};
vm.createContext(ctx);vm.runInContext(source,ctx);
const ws=sockets[0];ws.onopen();
const message=m=>ws.onmessage({data:JSON.stringify(m)});
message({type:'INIT',entries:[]});
message({type:'STATUS',ready:true,leader:3,node_id:1,role:'follower',clients:1,hash:'hash',nodes:[{id:1,url:'http://localhost:8765',online:true,role:'follower'},{id:2,url:'http://localhost:8766',online:true,role:'follower'}],events:[]});
const c=element('board');c.onpointerdown({pointerId:1,clientX:10,clientY:20});c.onpointermove({pointerId:1,clientX:30,clientY:40});c.onpointerup({pointerId:1});
assert.equal(ws.sent.length,1);assert.equal(ws.sent[0].op.kind,'STROKE');assert.equal(element('pending').textContent,1);
const entry={...ws.sent[0].op,seq:1,session:'s'};message({type:'COMMIT',entry});message({type:'COMMIT',entry});
assert.equal(element('committed').textContent,1);assert.equal(element('pending').textContent,0);
element('clear').onclick();assert.equal(ws.sent.at(-1).op.kind,'CLEAR');
// Failed connection chooses a discovered alternate, then retries same operation ID.
const pendingID=ws.sent.at(-1).op.op_id;ws.close();timers.at(-1)();const ws2=sockets.at(-1);
assert.equal(ws2.url,'ws://localhost:8766/ws');ws2.onopen();
ws2.onmessage({data:JSON.stringify({type:'STATUS',ready:true,leader:2,node_id:2,role:'leader',clients:1,hash:'hash',nodes:[],events:[]})});
intervals[0]();assert.equal(ws2.sent[0].op.op_id,pendingID);
ws2.onmessage({data:JSON.stringify({type:'INIT',entries:[entry,{...ws2.sent[0].op,seq:2,session:'s2'}]})});
assert.equal(element('committed').textContent,2);assert.equal(element('pending').textContent,0);
assert.equal(JSON.parse(storage.get('codraw-pending')).length,0);
console.log('PASS: stroke input, confirmation, duplicate delivery, clear, discovered endpoint failover, retry ID, snapshot replay, pending persistence.');
