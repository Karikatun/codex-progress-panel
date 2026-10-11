/* Functional DOM + MCP host mock. This is NOT native rendering evidence. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const os = require('node:os');
const {spawn} = require('node:child_process');
const readline = require('node:readline');
const html = fs.readFileSync(path.join(__dirname,'../plugins/progress-panel/panel.html'),'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
class Element {
  constructor(tag) {this.tag=tag;this.children=[];this.dataset={};this.attrs={};this.hidden=false;this._text='';this.textWrites=0;this.style={setProperty:(k,v)=>{this.attrs[k]=v;}};}
  get textContent() {return this._text + this.children.map(x=>x.textContent).join('');}
  set textContent(v) {this._text=String(v);this.children=[];this.textWrites++;}
  append(...nodes) {for (const node of nodes) for (const child of node.tag==='fragment'?[...node.children]:[node]) this.insertBefore(child,null);}
  insertBefore(node,before) {node.remove();const index=before===null?this.children.length:this.children.indexOf(before);assert.ok(index>=0);this.children.splice(index,0,node);node.parentNode=this;}
  remove() {if(this.parentNode){const index=this.parentNode.children.indexOf(this);this.parentNode.children.splice(index,1);this.parentNode=null;}}
  replaceChildren(...nodes) {this.children=[];this._text='';this.append(...nodes);}
  setAttribute(key,value) {this.attrs[key]=value;}
}
function fixture(standalone=false,language='en') {
  const ids={};for (const m of html.matchAll(/<[^>]*\bid="([^"]+)"[^>]*>/g)) {
    const element=ids[m[1]]=new Element('element');element.hidden=/\bhidden\b/.test(m[0]);
    for (const attr of m[0].matchAll(/([\w-]+)="([^"]*)"/g)) element.attrs[attr[1]]=attr[2];
  }
  const listeners=new Map(), docListeners=new Map(), messages=[], timers=new Map();let next=1;
  const doc={hidden:false,documentElement:new Element('html'),getElementById:id=>ids[id],createElement:tag=>new Element(tag),createDocumentFragment:()=>new Element('fragment'),addEventListener:(n,f)=>docListeners.set(n,f),removeEventListener:n=>docListeners.delete(n)};
  doc.documentElement.lang=language;
  const parent={postMessage:(m,origin)=>messages.push({message:m,origin})};
  const win={parent,addEventListener:(n,f)=>listeners.set(n,f),removeEventListener:n=>listeners.delete(n)};
  if(standalone) win.parent=win;
  let now=Date.parse('2026-10-07T09:30:00+00:00');
  class Clock extends Date {static now(){return now;}}
  const context=vm.createContext({window:win,document:doc,console,Intl,Date:Clock,Map,Promise,Error,Object,String,Number,Array,CSS:{supports:(_k,v)=>/^#[a-f0-9]{3,8}$/i.test(v)},setTimeout:(f,ms)=>{const id=next++;timers.set(id,{f,ms});return id;},clearTimeout:id=>timers.delete(id)});
  // Bound synchronous startup while allowing headroom on shared CI runners.
  vm.runInContext(script,context,{timeout:10000});
  return {ids,doc,messages,timers,parent,
    emit(data,source=parent,origin='https://host.example'){listeners.get('message')?.({data,source,origin});},
    run(ms){const [id,entry]=[...timers].find(([,x])=>x.ms===ms)||[];assert.ok(entry,'Expected timer '+ms);timers.delete(id);entry.f();},
    visibility(hidden){doc.hidden=hidden;docListeners.get('visibilitychange')?.();},
    pagehide(){listeners.get('pagehide')?.();},
    transportTimers(){return [...timers.values()].filter(x=>x.ms<=15000);},
    advance(ms){now+=ms;},now(){return now;}
  };
}
const settle=()=>new Promise(resolve=>setImmediate(resolve));
function sample(revision=1,task='task-one') {return {task_id:task,revision,finalized:false,finalized_at:null,title:'Панель',current:'Проверка',blocker:'',actor:'Основной агент',updated_at:'2026-10-07T09:30:00+00:00',stages:[{id:'build',title:'Сборка',status:'running',actor:'Исполнитель',detail:'Работа идёт'},{id:'test',title:'Проверка',status:'pending',actor:'',detail:''}]};}
const readToken='a'.repeat(64);
function result(state=sample(),withToken=true) {return {structuredContent:{state},_meta:withToken?{read_token:readToken}:{}};}
async function connect(f) {
  const init=f.messages[0].message;
  assert.equal(init.method,'ui/initialize');assert.equal(f.messages.length,1);
  f.emit({jsonrpc:'2.0',id:init.id,result:{protocolVersion:'2026-01-26',hostCapabilities:{serverTools:{}},hostContext:{theme:'dark',styles:{variables:{'--color-text-primary':'#eee'}}}}});
  await settle();
  assert.equal(f.messages[1].message.method,'ui/notifications/initialized');
  assert.equal(f.doc.documentElement.dataset.theme,'dark');
}
async function realMcp(body) {
  const area=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'plan-bridge-')));
  const process=spawn('python3',['-B',path.join(__dirname,'../plugins/progress-panel/server.py'),'--data-dir',path.join(area,'state')],{stdio:['pipe','pipe','pipe']});
  const lines=readline.createInterface({input:process.stdout}),queue=[],waiting=[];let seq=0,stderr='';
  process.stderr.on('data',data=>{stderr+=data;});
  lines.on('line',line=>{const accept=waiting.shift();if(accept) accept(line);else queue.push(line);});
  const exit=new Promise((resolve,reject)=>{process.on('error',reject);process.on('close',code=>resolve(code));});
  async function request(method,params={}) {
    const id=++seq;process.stdin.write(JSON.stringify({jsonrpc:'2.0',id,method,params})+'\n');
    const reply=await new Promise((resolve,reject)=>{const timeout=setTimeout(()=>reject(new Error('Real MCP deadline '+stderr)),4000);
      const accept=line=>{clearTimeout(timeout);resolve(JSON.parse(line));};if(queue.length) accept(queue.shift());else waiting.push(accept);});
    assert.equal(reply.id,id);assert.equal(reply.error,undefined);return reply.result;
  }
  try {
    await request('initialize',{protocolVersion:'2025-11-25',capabilities:{},clientInfo:{name:'bridge-contract',version:'1'}});
    process.stdin.write(JSON.stringify({jsonrpc:'2.0',method:'notifications/initialized'})+'\n');
    await body((name,args)=>request('tools/call',{name,arguments:args}));
  } finally {process.stdin.end();assert.equal(await exit,0,stderr);lines.close();fs.rmSync(area,{recursive:true,force:true});}
}
async function tests() {
  let count=0;
  async function check(name,body) {await body();count++;console.log('ok '+name);}
  await check('handshake then empty panel; no polling before task binding',async()=>{
    const f=fixture();await connect(f);
    f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(null,false)});
    assert.equal(f.ids.empty.hidden,false);assert.equal(f.timers.size,0);
  });
  await check('literal XSS rendering and task-scoped read-only polling',async()=>{
    const f=fixture();await connect(f);const s=sample();s.title='<script>alert(1)</script>';s.stages[0].title='<img onerror=alert(1)>';
    f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(s)});
    assert.equal(f.ids.title.textContent,s.title);assert.equal(f.ids.stages.children.length,2);
    assert.ok(f.ids.stages.textContent.includes('<img onerror=alert(1)>'));
    assert.equal(f.ids.stages.children[0].dataset.status,'running');
    f.run(2500);const call=f.messages.at(-1).message;
    assert.equal(call.method,'tools/call');assert.equal(call.params.name,'get_progress');
    assert.equal(call.params.arguments.task_id,'task-one');assert.equal(call.params.arguments.read_token,readToken);
    assert.deepEqual(Object.keys(call.params.arguments).sort(),['read_token','task_id']);
    const newer=sample(2);newer.stages[0].status='completed';
    f.emit({jsonrpc:'2.0',id:call.id,result:result(newer,false)});await settle();
    assert.equal(f.ids.stages.children[0].dataset.status,'completed');
    assert.ok(f.messages.filter(x=>x.message.method==='tools/call').every(x=>x.message.params.name==='get_progress'));
  });
  await check('foreign source, foreign task and stale replies cannot replace state',async()=>{
    const f=fixture();await connect(f);
    f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(sample(3))});
    const old=sample(2);old.title='Old';f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(old)});
    const foreign=sample(9,'other-task');foreign.title='Other';
    f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(foreign)});
    f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(foreign)},{});
    assert.equal(f.ids.title.textContent,'Панель');
  });
  await check('read capability missing exposes snapshot limitation',async()=>{
    const f=fixture();await connect(f);
    f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(sample(),false)});
    assert.match(f.ids.connection.textContent,/live updates unavailable/);assert.equal(f.transportTimers().length,0);
    assert.equal(f.timers.size,1);assert.equal([...f.timers.values()][0].ms,120000);
  });
  await check('error reconnect preserves last stage and bounded retry',async()=>{
    const f=fixture();await connect(f);
    f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result()});f.run(2500);
    const call=f.messages.at(-1).message;
    f.emit({jsonrpc:'2.0',id:call.id,error:{code:-1,message:'no'}});await settle();
    assert.match(f.ids.connection.textContent,/Reconnecting/);assert.equal(f.ids.stages.children.length,2);
    assert.equal(f.transportTimers()[0].ms,5000);
    f.run(5000);const retry=f.messages.at(-1).message;
    f.emit({jsonrpc:'2.0',id:retry.id,result:result(sample(2),false)});await settle();
    assert.match(f.ids.connection.textContent,/Connected/);assert.equal(f.transportTimers()[0].ms,2500);
  });
  await check('same-revision success recovers transport and base polling without rewriting snapshot',async()=>{
    const f=fixture();await connect(f);const original=sample(2);
    f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(original)});
    const title=f.ids.title.textContent, stages=f.ids.stages.textContent, timestamp=f.ids.updated.title;
    f.run(2500);let call=f.messages.at(-1).message;
    f.emit({jsonrpc:'2.0',id:call.id,error:{code:-1,message:'disconnected'}});await settle();
    assert.match(f.ids.connection.textContent,/Reconnecting/);assert.equal(f.transportTimers()[0].ms,5000);
    f.run(5000);call=f.messages.at(-1).message;
    const changed=sample(2);changed.title='Changed';changed.stages[0].status='completed';changed.updated_at='2026-10-08T09:30:00+00:00';
    f.emit({jsonrpc:'2.0',id:call.id,result:result(changed,false)});await settle();
    assert.match(f.ids.connection.textContent,/Connected/);assert.equal(f.ids.connection.dataset.kind,'');
    assert.equal(f.transportTimers()[0].ms,2500);
    assert.equal(f.ids.title.textContent,title);assert.equal(f.ids.stages.textContent,stages);assert.equal(f.ids.updated.title,timestamp);
    f.run(2500);call=f.messages.at(-1).message;
    f.emit({jsonrpc:'2.0',id:call.id,error:{code:-1}});await settle();
    assert.equal(f.transportTimers()[0].ms,5000);
    const stale=sample(1);
    f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(stale,false)});
    assert.match(f.ids.connection.textContent,/Reconnecting/);assert.equal(f.transportTimers()[0].ms,5000);
    f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(changed,false)});
    assert.match(f.ids.connection.textContent,/Connected/);assert.equal(f.transportTimers()[0].ms,2500);
    assert.equal(f.ids.title.textContent,title);assert.equal(f.ids.stages.textContent,stages);assert.equal(f.ids.updated.title,timestamp);
  });
  await check('incoming notification during polling cannot start an overlapping request',async()=>{
    const f=fixture();await connect(f);
    f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result()});f.run(2500);
    const call=f.messages.at(-1).message;
    f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(sample(2))});
    assert.equal(f.transportTimers().length,1);assert.equal(f.transportTimers()[0].ms,4000);
    f.emit({jsonrpc:'2.0',id:call.id,result:result(sample(1),false)});await settle();
    assert.equal(f.transportTimers()[0].ms,2500);
  });
  await check('standalone and unavailable bridge state are honest',async()=>{
    const standalone=fixture(true);assert.match(standalone.ids.connection.textContent,/standalone browser is not connected/);assert.equal(standalone.messages.length,0);
    const f=fixture();f.run(4000);await settle();assert.match(f.ids.connection.textContent,/did not connect the panel/);assert.equal(f.timers.size,0);
  });
  await check('hidden view suspends polling and teardown clears timers',async()=>{
    const f=fixture();await connect(f);f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result()});
    f.visibility(true);assert.equal(f.timers.size,0);f.visibility(false);assert.equal(f.timers.size,2);
    f.emit({jsonrpc:'2.0',id:90,method:'ui/resource-teardown',params:{}});
    assert.equal(f.messages.at(-1).message.id,90);assert.equal(f.timers.size,0);
    f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(sample(9))});assert.equal(f.timers.size,0);
  });
  await check('host ping and teardown ids may collide with an outstanding poll id',async()=>{
    const f=fixture();await connect(f);f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result()});f.run(2500);
    const poll=f.messages.at(-1).message;
    f.emit({jsonrpc:'2.0',id:poll.id,method:'ping',params:{}});
    assert.equal(f.messages.at(-1).message.id,poll.id);assert.ok('result' in f.messages.at(-1).message);
    assert.equal(f.transportTimers()[0].ms,4000);
    f.emit({jsonrpc:'2.0',id:poll.id,method:'ui/resource-teardown',params:{}});await settle();
    assert.equal(f.messages.at(-1).message.id,poll.id);assert.ok('result' in f.messages.at(-1).message);
    assert.equal(f.timers.size,0);
    const calls=f.messages.filter(x=>x.message.method==='tools/call').length;
    f.visibility(false);f.emit({jsonrpc:'2.0',id:poll.id,result:result(sample(3))});await settle();
    assert.equal(f.timers.size,0);assert.equal(f.messages.filter(x=>x.message.method==='tools/call').length,calls);
  });
  await check('malformed response cannot consume an outstanding request',async()=>{
    const f=fixture();await connect(f);f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result()});f.run(2500);
    const poll=f.messages.at(-1).message;
    f.emit({jsonrpc:'2.0',id:poll.id,result:result(sample(2)),error:{code:-1}});await settle();
    assert.equal(f.transportTimers()[0].ms,4000);
    f.emit({jsonrpc:'2.0',id:poll.id,result:result(sample(2),false)});await settle();
    assert.equal(f.transportTimers()[0].ms,2500);
  });
  await check('astral Unicode matches codepoint limits for every display text field',async()=>{
    const cases=[[null,'title',240],[null,'actor',600],[null,'current',600],[null,'blocker',600],['stage','title',240],['stage','actor',160],['stage','detail',600]];
    for (const [scope,key,limit] of cases) {
      const f=fixture();await connect(f);const s=sample();(scope?s.stages[0]:s)[key]='😀'.repeat(limit);
      f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(s)});
      assert.match(f.ids.connection.textContent,/Connected/);assert.equal(f.ids.stages.children.length,2);
      const title=f.ids.title.textContent, stageText=f.ids.stages.textContent;
      const invalid=sample(2);(scope?invalid.stages[0]:invalid)[key]='😀'.repeat(limit+1);
      f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(invalid)});
      assert.match(f.ids.connection.textContent,/Could not read/);
      assert.equal(f.ids.title.textContent,title);assert.equal(f.ids.stages.textContent,stageText);
    }
    const f=fixture();await connect(f);const s=sample();s.title='😀'.repeat(121);
    f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(s)});assert.equal(f.ids.title.textContent,s.title);
  });
  await check('same-revision polls advance content age and threshold stale active work',async()=>{
    const f=fixture();await connect(f);
    f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result()});
    assert.equal(f.ids.freshness.hidden,true);assert.match(f.ids.updated.textContent,/0 seconds ago/);
    f.advance(119000);f.run(2500);let call=f.messages.at(-1).message;
    f.emit({jsonrpc:'2.0',id:call.id,result:result(sample(),false)});await settle();
    assert.equal(f.ids.freshness.hidden,true);assert.match(f.ids.updated.textContent,/1 minute ago/);
    f.advance(1000);f.run(2500);call=f.messages.at(-1).message;
    f.emit({jsonrpc:'2.0',id:call.id,result:result(sample(),false)});await settle();
    assert.equal(f.ids.freshness.hidden,false);assert.match(f.ids.freshness.textContent,/Work may still be continuing/);
    assert.match(f.ids.updated.textContent,/2 minutes ago/);assert.match(f.ids.connection.textContent,/Connected/);
    assert.equal(f.ids.stages.children[0].dataset.status,'running');
    f.advance(86400000);f.run(2500);call=f.messages.at(-1).message;
    f.emit({jsonrpc:'2.0',id:call.id,result:result(sample(),false)});await settle();
    assert.match(f.ids.updated.textContent,/1 day ago/);assert.equal(f.ids.freshness.hidden,false);
    const fresh=sample(2);fresh.updated_at=new Date(f.now()).toISOString();
    f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(fresh,false)});
    assert.equal(f.ids.freshness.hidden,true);assert.match(f.ids.updated.textContent,/0 seconds ago/);
  });
  await check('completed but unfinished historical state is stale; failures preserve last state',async()=>{
    const completed=fixture();await connect(completed);completed.advance(86400000);
    const old=sample();old.stages.forEach(s=>s.status='completed');
    completed.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(old)});
    assert.match(completed.ids.updated.textContent,/1 day ago/);assert.equal(completed.ids.freshness.hidden,false);
    assert.equal(completed.ids.main.dataset.observation,'stale');
    const f=fixture();await connect(f);f.advance(86400000);
    f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result()});
    const stages=f.ids.stages.textContent;f.run(2500);const call=f.messages.at(-1).message;
    f.advance(86400000);f.emit({jsonrpc:'2.0',id:call.id,error:{code:-1}});await settle();
    assert.match(f.ids.connection.textContent,/Reconnecting/);assert.match(f.ids.updated.textContent,/2 days ago/);
    assert.equal(f.ids.freshness.hidden,false);assert.equal(f.ids.stages.textContent,stages);
    assert.equal(f.timers.size,1); // Past the age boundary: only the backoff remains.
    f.emit({jsonrpc:'2.0',id:90,method:'ui/resource-teardown',params:{}});await settle();
    assert.equal(f.timers.size,0);const count=f.messages.length;f.advance(86400000);f.visibility(false);
    assert.equal(f.timers.size,0);assert.equal(f.messages.length,count);
  });
  await check('finished widget freezes timestamps, binding and polling despite late replies',async()=>{
    const f=fixture();await connect(f);
    f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result()});f.run(2500);
    const poll=f.messages.at(-1).message;
    const final=sample(2);final.finalized=true;final.finalized_at=final.updated_at;
    final.stages[0].status='blocked';final.blocker='Нужен ответ';
    f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(final)});await settle();
    assert.equal(f.timers.size,0);assert.match(f.ids.connection.textContent,/Execution result finalized/);
    const timestamp=f.ids.updated.textContent, title=f.ids.title.textContent, stages=f.ids.stages.textContent;
    const late=sample(99);late.title='Поздний ответ';
    f.emit({jsonrpc:'2.0',id:poll.id,result:result(late)});
    f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(late)});
    f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:{isError:true}});
    f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(sample(100,'execution-b'))});
    f.advance(86400000);f.visibility(true);f.visibility(false);await settle();
    assert.equal(f.timers.size,0);assert.equal(f.ids.updated.textContent,timestamp);
    assert.equal(f.ids.title.textContent,title);assert.equal(f.ids.stages.textContent,stages);
    assert.equal(f.ids.freshness.hidden,true);
    const b=fixture();await connect(b);b.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(sample(1,'execution-b'))});
    b.run(2500);assert.equal(b.messages.at(-1).message.params.arguments.task_id,'execution-b');
  });
  await check('same revision cannot rewrite content or timestamps; frozen reopen does not poll',async()=>{
    const f=fixture();await connect(f);f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result()});
    const counterfeit=sample();counterfeit.title='Changed';counterfeit.updated_at='2026-10-08T09:30:00+00:00';
    f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(counterfeit)});
    assert.equal(f.ids.title.textContent,'Панель');assert.equal(f.ids.updated.title,sample().updated_at);
    const reopened=fixture();await connect(reopened);const final=sample(2);final.finalized=true;final.finalized_at=final.updated_at;
    reopened.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(final)});
    assert.equal(reopened.timers.size,0);assert.match(reopened.ids.updated.textContent,/Finalized/);
  });
  await check('default English and configured Russian cover labels, accessibility, messages and relative dates without translating task data',async()=>{
    for (const language of ['en','ru']) {
      const ru=language==='ru', f=fixture(false,language);
      assert.equal(f.doc.documentElement.lang,language);
      assert.equal(f.doc.title,ru?'Этапы задачи':'Task stages');
      assert.equal(f.ids.main.attrs['aria-label'],ru?'Ход работы':'Work progress');
      assert.equal(f.ids.eyebrow.textContent,ru?'Ход работы':'Work progress');
      assert.equal(f.ids.current.attrs['aria-label'],ru?'Текущая работа':'Current work');
      assert.equal(f.ids.blocker.attrs['aria-label'],ru?'Препятствие':'Blocker');
      assert.equal(f.ids.stages.attrs['aria-label'],ru?'Этапы':'Stages');
      assert.equal(f.ids['current-label'].textContent,ru?'Сейчас':'Now');
      assert.equal(f.ids['blocker-title'].textContent,ru?'Работа приостановлена':'Work is paused');
      assert.equal(f.ids['empty-title'].textContent,ru?'План ещё не привязан':'No plan is linked yet');
      assert.equal(f.ids['empty-text'].textContent,ru?'После открытия панели для этой задачи здесь появятся этапы и текущая работа.':'Open the panel for this task to see its stages and current work.');
      assert.equal(f.ids.connection.textContent,ru?'Подключение к панели…':'Connecting to the panel…');
      await connect(f);
      f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(null,false)});
      assert.equal(f.ids.connection.textContent,ru?'Ожидание плана':'Waiting for a plan');
      const task=sample();task.actor='';task.blocker='Keep this blocker';
      task.stages=['pending','running','blocked','completed'].map((status,index)=>({id:'stage-'+index,title:'Исходный текст '+index,status,actor:'',detail:''}));
      f.advance(120000);
      f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(task,false)});
      assert.equal(f.ids.title.textContent,task.title);assert.equal(f.ids['current-text'].textContent,task.current);
      assert.equal(f.ids['blocker-text'].textContent,task.blocker);
      const expected=ru?['Ожидает','В работе','Приостановлен','Завершён']:['Pending','In progress','Blocked','Completed'];
      for(let index=0;index<4;index++) {
        const top=f.ids.stages.children[index].children[1].children[0];
        assert.equal(top.children[0].textContent,task.stages[index].title);
        assert.equal(top.children[1].textContent,expected[index]);
      }
      assert.equal(f.ids.actor.textContent,ru?'Исполнитель не указан':'Actor not specified');
      assert.equal(f.ids.connection.textContent,ru?'Получен снимок; живое обновление недоступно':'Snapshot received; live updates unavailable');
      assert.match(f.ids.updated.textContent,ru?/Обновлено 2 минуты назад/:/Updated 2 minutes ago/);
      assert.equal(f.ids.freshness.textContent,(ru?'Подтверждённых обновлений нет 2 минуты или дольше. Работа может продолжаться; итог не зафиксирован. Последнее подтверждённое обновление: ':'No confirmed update for 2 minutes or longer. Work may still be continuing; the result is not finalized. Last confirmed update: ')+task.updated_at);
      f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:{isError:true}});
      assert.equal(f.ids.connection.textContent,ru?'Не удалось прочитать этапы. Ожидание следующего обновления…':'Could not read task stages. Waiting for the next update…');
      const standalone=fixture(true,language);assert.match(standalone.ids.connection.textContent,ru?/Обычный браузер не подключён/:/standalone browser is not connected/);
      const unavailable=fixture(false,language);unavailable.run(4000);await settle();
      assert.match(unavailable.ids.connection.textContent,ru?/не подключило панель/:/did not connect the panel/);
    }
  });
  await check('host locale changes cannot alter resource language or restart finalized polling',async()=>{
    for(const language of ['en','ru']) {
      const f=fixture(false,language);await connect(f);
      const final=sample(2);final.finalized=true;final.finalized_at=final.updated_at;
      f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(final)});
      const connection=f.ids.connection.textContent,timestamp=f.ids.updated.textContent,statuses=f.ids.stages.textContent,calls=f.messages.length;
      f.emit({jsonrpc:'2.0',method:'ui/notifications/host-context-changed',params:{locale:language==='en'?'ru-RU':'en-US',theme:'light'}});
      f.visibility(true);f.visibility(false);await settle();
      assert.equal(f.doc.documentElement.lang,language);assert.equal(f.ids.connection.textContent,connection);
      assert.equal(f.ids.updated.textContent,timestamp);assert.equal(f.ids.stages.textContent,statuses);
      assert.equal(f.timers.size,0);assert.equal(f.messages.length,calls);
      assert.match(timestamp,language==='ru'?/Зафиксировано/:/Finalized/);
    }
    const invalid=fixture(true,'fr');assert.equal(invalid.doc.documentElement.lang,'en');assert.equal(invalid.doc.title,'Task stages');
  });
  await check('snapshot-only unfinished work ages locally without writes or repeated timers',async()=>{
    const f=fixture();await connect(f);const s=sample();s.stages.forEach(stage=>stage.status='completed');
    f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(s,false)});
    const messages=f.messages.length,stages=f.ids.stages.textContent;
    assert.equal(f.ids.main.dataset.observation,'unavailable');assert.equal(f.ids.freshness.hidden,true);
    f.advance(120000);f.run(120000);
    assert.equal(f.ids.freshness.hidden,false);assert.ok(f.ids.freshness.textContent.includes(s.updated_at));
    assert.match(f.ids.freshness.textContent,/result is not finalized/);assert.equal(f.ids.stages.textContent,stages);
    assert.equal(f.messages.length,messages);assert.equal(f.timers.size,0);
    f.advance(86400000);f.visibility(true);f.visibility(false);
    assert.match(f.ids.updated.textContent,/1 day ago/);assert.equal(f.timers.size,0);
  });
  await check('same revision can attach a read capability without refreshing confirmed data',async()=>{
    const f=fixture();await connect(f);const s=sample();
    f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(s,false)});
    f.advance(180000);
    const same=sample();same.title='Unconfirmed replacement';same.updated_at=new Date(f.now()).toISOString();
    f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(same)});
    assert.equal(f.ids.title.textContent,s.title);assert.equal(f.ids.updated.title,s.updated_at);
    assert.equal(f.ids.main.dataset.observation,'stale');assert.match(f.ids.connection.textContent,/Connected.*Stale/);
    assert.equal(f.transportTimers()[0].ms,2500);f.run(2500);
    assert.equal(f.messages.at(-1).message.params.arguments.read_token,readToken);
  });
  await check('old widget reconnects after restart while same-revision data stays stale',async()=>{
    const f=fixture();await connect(f);f.advance(3600000);
    f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result()});
    const snapshot=f.ids.stages.textContent,timestamp=f.ids.updated.title;
    assert.equal(f.ids.main.dataset.observation,'stale');
    f.run(2500);let call=f.messages.at(-1).message;
    f.emit({jsonrpc:'2.0',id:call.id,error:{code:-32603,message:'server unavailable'}});await settle();
    assert.equal(f.ids.main.dataset.observation,'unavailable');assert.equal(f.ids.updated.title,timestamp);
    f.run(5000);call=f.messages.at(-1).message;
    f.emit({jsonrpc:'2.0',id:call.id,result:result(sample(),false)});await settle();
    assert.equal(f.ids.main.dataset.observation,'stale');assert.equal(f.ids.stages.textContent,snapshot);
    assert.equal(f.ids.updated.title,timestamp);assert.equal(f.ids.freshness.hidden,false);
    const newer=sample(2);newer.updated_at=new Date(f.now()).toISOString();
    f.run(2500);call=f.messages.at(-1).message;
    f.emit({jsonrpc:'2.0',id:call.id,result:result(newer,false)});await settle();
    assert.equal(f.ids.main.dataset.observation,'live');assert.equal(f.ids.freshness.hidden,true);
    assert.equal(f.ids.updated.title,newer.updated_at);
  });
  await check('read timeout and late reply cannot fake recovery; matched retry preserves old age',async()=>{
    const f=fixture();await connect(f);f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result()});
    f.run(2500);const expired=f.messages.at(-1).message;f.advance(180000);f.run(4000);await settle();
    assert.equal(f.ids.main.dataset.observation,'unavailable');assert.equal(f.ids.freshness.hidden,false);
    f.emit({jsonrpc:'2.0',id:expired.id,result:result(sample(9))});await settle();
    assert.equal(f.ids.main.dataset.observation,'unavailable');assert.equal(f.ids.updated.title,sample().updated_at);
    f.run(5000);const retry=f.messages.at(-1).message;
    f.emit({jsonrpc:'2.0',id:retry.id,result:result(sample(),false)});await settle();
    assert.equal(f.ids.main.dataset.observation,'stale');assert.equal(f.ids.updated.title,sample().updated_at);
    assert.equal(f.transportTimers()[0].ms,2500);
  });
  await check('foreign origin cannot replace agents or consume a correlated read',async()=>{
    const f=fixture();await connect(f);f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result()});f.run(2500);
    const poll=f.messages.at(-1).message,foreign=sample(2);foreign.stages[0].agents=[{id:'foreign',actor:'Foreign',status:'running'}];
    f.emit({jsonrpc:'2.0',id:poll.id,result:result(foreign)},f.parent,'https://untrusted.example');
    f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(foreign)},f.parent,'https://untrusted.example');
    assert.equal(f.ids.stages.textContent.includes('Foreign'),false);assert.equal(f.transportTimers()[0].ms,4000);
    f.emit({jsonrpc:'2.0',id:poll.id,result:result(sample(),false)});await settle();assert.equal(f.transportTimers()[0].ms,2500);
  });
  await check('Stop or silence before finish never changes stage or finalization',async()=>{
    const f=fixture();await connect(f);f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result()});
    f.advance(120000);f.run(120000);
    assert.equal(f.ids.main.dataset.observation,'stale');assert.equal(f.ids.stages.children[0].dataset.status,'running');
    assert.match(f.ids.freshness.textContent,/not finalized/);
    const before=f.messages.length;f.pagehide();await settle();assert.equal(f.timers.size,0);
    f.visibility(false);f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(sample(9))});
    assert.equal(f.messages.length,before);assert.equal(f.ids.main.dataset.observation,'stale');
    assert.ok(f.messages.filter(x=>x.message.method==='tools/call').every(x=>x.message.params.name==='get_progress'));
    const reopened=fixture();await connect(reopened);reopened.advance(120000);
    reopened.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result()});
    assert.equal(reopened.ids.main.dataset.observation,'stale');assert.equal(reopened.ids.stages.children[0].dataset.status,'running');
  });
  await check('four independent agents are semantic stage-associated text and do not complete their stage',async()=>{
    for (const language of ['en','ru']) {
      const f=fixture(false,language);await connect(f);const s=sample();
      s.stages[0].agents=['running','completed','pending','blocked'].map((status,index)=>({id:'agent-'+index,actor:'Agent '+index,status,detail:'Current work '+index}));
      f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(s)});
      const stage=f.ids.stages.children[0],list=stage.children[1].children.at(-1);
      assert.equal(stage.dataset.status,'running');assert.equal(list.tag,'ul');assert.equal(list.children.length,4);
      assert.equal(list.attrs['aria-label'],(language==='ru'?'Агенты':'Agents')+' · '+s.stages[0].title);
      for (let index=0;index<4;index++) {
        const agent=list.children[index];assert.equal(agent.tag,'li');assert.equal(agent.dataset.status,s.stages[0].agents[index].status);
        assert.ok(agent.textContent.includes('Agent '+index));assert.ok(agent.textContent.includes('Current work '+index));
      }
      const newer=sample(2);newer.stages[0].agents=s.stages[0].agents.map(a=>({...a,status:'completed'}));
      f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(newer)});
      assert.equal(f.ids.stages.children[0].dataset.status,'running');assert.equal(f.ids.main.dataset.observation,'live');
    }
  });
  await check('legacy omitted agents and empty agents render no empty group; large legacy state remains readable',async()=>{
    const f=fixture();await connect(f);const legacy=sample();
    legacy.stages=Array.from({length:32},(_,index)=>({id:'s'+index,title:'😀'.repeat(240),status:'completed',actor:'😀'.repeat(160),detail:'😀'.repeat(600)}));
    assert.ok(Buffer.byteLength(JSON.stringify(legacy))>65536);
    f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(legacy)});
    assert.equal(f.ids.stages.children.length,32);assert.equal(f.ids.main.dataset.observation,'live');
    assert.equal(f.ids.stages.children[0].children[1].children.some(x=>x.tag==='ul'),false);
    const empty=sample(2);empty.stages[0].agents=[];
    f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(empty)});
    assert.equal(f.ids.stages.children[0].children[1].children.some(x=>x.tag==='ul'),false);
  });
  await check('agent Unicode limits and literal markup survive without HTML interpretation',async()=>{
    const f=fixture();await connect(f);const s=sample();
    s.stages[0].agents=[{id:'build',actor:'😀'.repeat(160),status:'running',detail:'漢'.repeat(580)+'<img onerror=bad()>'}];
    f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(s)});
    assert.equal(f.ids.main.dataset.observation,'live');assert.ok(f.ids.stages.textContent.includes(s.stages[0].agents[0].detail));
    const literal=s.stages[0].agents[0].detail;
    for (const field of ['actor','detail']) {
      const invalid=sample(2);invalid.stages[0].agents=[{id:'safe',actor:'Agent',status:'running',detail:''}];
      invalid.stages[0].agents[0][field]='😀'.repeat(field==='actor'?161:601);
      f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(invalid)});
      assert.equal(f.ids.main.dataset.observation,'unavailable');assert.ok(f.ids.stages.textContent.includes(literal));
    }
  });
  await check('unsafe, unknown and oversized agent/state shapes preserve last confirmed snapshot',async()=>{
    const mutations=[
      s=>{s.extra='unknown';},s=>{s.task_id=123;},s=>{s.title=' ';},s=>{s.current='bad\u0000';},s=>{s.actor='bad\ud800';},
      s=>{s.revision=1.5;},s=>{s.finalized='true';},s=>{s.finalized_at=s.updated_at;},s=>{s.updated_at='bad';},
      s=>{s.stages[0].extra='unknown';},s=>{s.stages[1].id=s.stages[0].id;},s=>{s.stages[0].status=['running'];},
      s=>{s.stages[0].agents={};},s=>{s.stages[0].agents=null;},s=>{s.stages[0].agents=Array.from({length:9},(_,i)=>({id:'a'+i,actor:'Agent',status:'running'}));},
      s=>{s.stages[0].agents=[{id:'../unsafe',actor:'Agent',status:'running'}];},s=>{s.stages[0].agents=[{id:123,actor:'Agent',status:'running'}];},
      s=>{s.stages[0].agents=[{id:'safe',actor:' ',status:'running'}];},s=>{s.stages[0].agents=[{id:'safe',actor:'Agent',status:'finished'}];},
      s=>{s.stages[0].agents=[{id:'safe',actor:'Agent',status:'running',detail:null}];},s=>{s.stages[0].agents=[{id:'safe',actor:'Agent',status:'running',extra:true}];},
      s=>{s.stages[0].agents=[{id:'safe',actor:'Agent\u0001',status:'running'}];},s=>{s.stages[0].agents=[{id:'safe',actor:'Agent',status:'running',detail:'bad\udfff'}];},
      s=>{s.stages[0].agents=[{id:'same',actor:'One',status:'running'}];s.stages[1].agents=[{id:'same',actor:'Two',status:'pending'}];},
      s=>{s.stages[0].agents=[[]];},s=>{s.stages[0].agents=[{id:'safe',status:'running'}];}
    ];
    for (const mutate of mutations) {
      const f=fixture();await connect(f);f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result()});
      const title=f.ids.title.textContent,stages=f.ids.stages.textContent,timestamp=f.ids.updated.title;
      const invalid=sample(2);mutate(invalid);
      f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(invalid)});
      assert.equal(f.ids.main.dataset.observation,'unavailable');assert.equal(f.ids.title.textContent,title);
      assert.equal(f.ids.stages.textContent,stages);assert.equal(f.ids.updated.title,timestamp);
    }
  });
  await check('status announcements are atomic, unchanged polls are quiet, and future-clock timers stay bounded',async()=>{
    const f=fixture();await connect(f);f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result()});
    assert.equal(f.ids.connection.attrs.role,'status');assert.equal(f.ids.connection.attrs['aria-live'],'polite');
    assert.equal(f.ids.connection.attrs['aria-atomic'],'true');assert.equal(f.ids.freshness.attrs['aria-atomic'],'true');
    const writes=f.ids.connection.textWrites;f.run(2500);const call=f.messages.at(-1).message;
    f.emit({jsonrpc:'2.0',id:call.id,result:result(sample(),false)});await settle();assert.equal(f.ids.connection.textWrites,writes);
    const future=sample(2);future.updated_at='2099-01-01T00:00:00Z';
    f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(future,false)});
    assert.ok([...f.timers.values()].every(x=>x.ms<=120000));
    assert.equal(/<(button|input|select|textarea)\b/.test(html),false); // Read-only content has no keyboard-only operation.
  });
  await check('real MCP plan reconciliation preserves keyed UI identity, history and four assignments',async()=>{
    for(const language of ['en','ru']) await realMcp(async call=>{
      const fields={title:'Active execution',actor:'Root',current:'Work continues',blocker:'',stages:[
        {id:'done',title:'Confirmed work',status:'completed',detail:'Historical proof'},
        {id:'work',title:'Current work',status:'running',agents:Array.from({length:4},(_,i)=>({id:'assignment-'+i,actor:'Worker '+i,status:'running',detail:'Actual assignment'}))},
        {id:'pending',title:'No longer needed',status:'pending'}]};
      const created=(await call('create_progress',{task_id:'same-execution',...fields})).structuredContent;
      const writing={task_id:'same-execution',write_token:created.write_token};
        const f=fixture(false,language);await connect(f);
        const opened=await call('open_progress_panel',{task_id:'same-execution',read_token:created.read_token});
        f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:opened});
        const workRow=f.ids.stages.children.find(row=>row.dataset.id==='work');
        const agentRows=[...workRow.children[1].children.at(-1).children];
        const latest=opened.structuredContent.state;
        const changed=await call('update_progress',{...writing,expected_revision:latest.revision,...fields,
          stages:[fields.stages[1],{id:'added-'+language,title:'New authorized work',status:'pending'}],plan_change:{summary:'Changed scope <img onerror=bad()>'}});
        assert.equal(changed.isError,undefined);
        f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:changed});
        assert.equal(f.ids.stages.children.length,2);assert.equal(f.ids.stages.children[0],workRow);
        assert.deepEqual(workRow.children[1].children.at(-1).children,agentRows);
        assert.equal(f.ids.stages.textContent.includes('Historical proof'),false);
        assert.equal(f.ids.stages.textContent.includes('No longer needed'),false);
        assert.equal(f.ids['plan-change'].hidden,false);
        assert.equal(f.ids['plan-change'].textContent,(language==='ru'?'План обновлён':'Plan updated')+' · Changed scope <img onerror=bad()>');
        const current=changed.structuredContent.state;
        const renamed=await call('update_progress',{...writing,expected_revision:current.revision,patch:{stages:[{id:'work',title:'Renamed unchanged work'}]}});
        f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:renamed});
        assert.equal(f.ids.stages.children[0],workRow);assert.equal(workRow.dataset.status,'running');
    });
  });
  await check('retired audit and malformed plan metadata never enter or replace active UI',async()=>{
    const plan={revision:1,changed_at:sample().updated_at,summary:'Changed scope',retired_stages:[{stage:{id:'old',title:'Old work',status:'completed',actor:'Root',detail:'Confirmed evidence'},retired_revision:1,retired_at:sample().updated_at}]};
    for(const mutate of [s=>{s.plan=null;},s=>{s.plan.extra=true;},s=>{s.plan.summary='x'.repeat(601);},
      s=>{s.plan.retired_stages.push(s.plan.retired_stages[0]);},s=>{s.plan.retired_stages[0].stage.id='build';},
      s=>{s.plan.retired_stages=Array.from({length:33},(_,i)=>({...s.plan.retired_stages[0],stage:{...s.plan.retired_stages[0].stage,id:'retired-'+i}}));},
      s=>{s.plan.revision=4;},s=>{s.plan.retired_stages[0].retired_revision=2;},s=>{s.plan.retired_stages[0].stage.agents=[{id:'a',actor:'Worker',status:'running'}];},
      s=>{s.stages[0].status='cancelled';}]) {
      const f=fixture();await connect(f);const valid=sample(2);valid.plan=structuredClone(plan);
      f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(valid)});
      const row=f.ids.stages.children[0],notice=f.ids['plan-change'].textContent;
      const invalid=sample(3);invalid.plan=structuredClone(plan);mutate(invalid);
      f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(invalid)});
      assert.equal(f.ids.main.dataset.observation,'unavailable');assert.equal(f.ids.stages.children[0],row);
      assert.equal(f.ids['plan-change'].textContent,notice);assert.equal(f.ids.stages.textContent.includes('Confirmed evidence'),false);
    }
    const f=fixture(false,'ru');await connect(f);const cancelled=sample();cancelled.stages[0].agents=[{id:'a',actor:'Worker',status:'cancelled',detail:'Cancellation confirmed'}];
    f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(cancelled)});
    assert.ok(f.ids.stages.textContent.includes('Отменён'));assert.equal(f.ids.stages.children[0].dataset.status,'running');
  });
  await check('each plan revision adds one localized accessibility event without repeated progress announcements',async()=>{
    for (const language of ['en','ru']) {
      const f=fixture(false,language);await connect(f);
      const initial=sample(2);initial.plan={revision:1,changed_at:initial.updated_at,summary:'',retired_stages:[]};
      f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(initial)});
      const log=f.ids['plan-announcements'],label=language==='ru'?'План обновлён':'Plan updated';
      assert.equal(log.attrs.role,'log');assert.equal(log.attrs['aria-live'],'polite');assert.equal(log.attrs['aria-relevant'],'additions');
      assert.equal(log.attrs['aria-atomic'],'false');assert.equal(log.attrs['aria-label'],language==='ru'?'Изменения плана':'Plan changes');
      assert.equal(log.children.length,1);const first=log.children[0];assert.equal(first.textContent,label);
      const build=f.ids.stages.children[0],test=f.ids.stages.children[1];
      const reordered=structuredClone(initial);reordered.revision=3;reordered.plan.revision=2;reordered.stages.reverse();
      f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(reordered)});
      assert.equal(log.children.length,2);const second=log.children[1];assert.notEqual(second,first);assert.equal(second.textContent,label);
      assert.deepEqual(f.ids.stages.children,[test,build]);
      const visibleWrites=f.ids['plan-change'].textWrites;
      f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(reordered)});
      assert.deepEqual(log.children,[first,second]);
      const progress=structuredClone(reordered);progress.revision=4;progress.current='Continue current work';progress.stages[0].detail='Verified unaffected result';
      f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(progress)});
      assert.deepEqual(log.children,[first,second]);assert.equal(f.ids['plan-change'].textWrites,visibleWrites);
      const refined=structuredClone(progress);refined.revision=5;refined.plan.revision=3;refined.plan.summary='<img onerror=bad()> 新しい要件';
      f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(refined)});
      assert.equal(log.children.length,2);assert.equal(log.children[0],second);const third=log.children[1];
      assert.notEqual(third,second);assert.equal(third.textContent,label+' · '+refined.plan.summary);assert.equal(third.children.length,0);
      assert.equal(f.ids['plan-change'].textContent,third.textContent);assert.deepEqual(f.ids.stages.children,[test,build]);
      const foreign=structuredClone(refined);foreign.task_id='foreign-execution';foreign.revision=6;foreign.plan.revision=4;
      f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(foreign)});
      assert.deepEqual(log.children,[second,third]);
      f.run(2500);const poll=f.messages.at(-1).message;
      assert.equal(poll.params.name,'get_progress');assert.equal(poll.params.arguments.task_id,initial.task_id);
      f.emit({jsonrpc:'2.0',id:poll.id,result:result(refined,false)});await settle();
      assert.deepEqual(log.children,[second,third]);assert.deepEqual(f.ids.stages.children,[test,build]);
    }
  });
  console.log('Bridge + real MCP: '+count+' tests passed. Native host rendering NOT VERIFIED.');
}
tests().catch(error=>{console.error(error);process.exitCode=1;});
