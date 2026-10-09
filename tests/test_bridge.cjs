/* Functional DOM + MCP host mock. This is NOT native rendering evidence. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname,'../plugins/progress-panel/panel.html'),'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
class Element {
  constructor(tag) {this.tag=tag;this.children=[];this.dataset={};this.attrs={};this.hidden=false;this._text='';this.style={setProperty:(k,v)=>{this.attrs[k]=v;}};}
  get textContent() {return this._text + this.children.map(x=>x.textContent).join('');}
  set textContent(v) {this._text=String(v);this.children=[];}
  append(...nodes) {for (const node of nodes) this.children.push(...(node.tag==='fragment'?node.children:[node]));}
  replaceChildren(...nodes) {this.children=[];this._text='';this.append(...nodes);}
  setAttribute(key,value) {this.attrs[key]=value;}
}
function fixture(standalone=false,language='en') {
  const ids={};for (const m of html.matchAll(/<[^>]*\bid="([^"]+)"[^>]*>/g)) {ids[m[1]]=new Element('element');ids[m[1]].hidden=/\bhidden\b/.test(m[0]);}
  const listeners=new Map(), docListeners=new Map(), messages=[], timers=new Map();let next=1;
  const doc={hidden:false,documentElement:new Element('html'),getElementById:id=>ids[id],createElement:tag=>new Element(tag),createDocumentFragment:()=>new Element('fragment'),addEventListener:(n,f)=>docListeners.set(n,f)};
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
    visibility(hidden){doc.hidden=hidden;docListeners.get('visibilitychange')();},
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
    assert.match(f.ids.connection.textContent,/live updates unavailable/);assert.equal(f.timers.size,0);
  });
  await check('error reconnect preserves last stage and bounded retry',async()=>{
    const f=fixture();await connect(f);
    f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result()});f.run(2500);
    const call=f.messages.at(-1).message;
    f.emit({jsonrpc:'2.0',id:call.id,error:{code:-1,message:'no'}});await settle();
    assert.match(f.ids.connection.textContent,/Reconnecting/);assert.equal(f.ids.stages.children.length,2);
    assert.equal([...f.timers.values()][0].ms,5000);
    f.run(5000);const retry=f.messages.at(-1).message;
    f.emit({jsonrpc:'2.0',id:retry.id,result:result(sample(2),false)});await settle();
    assert.match(f.ids.connection.textContent,/Connected/);assert.equal([...f.timers.values()][0].ms,2500);
  });
  await check('same-revision success recovers transport and base polling without rewriting snapshot',async()=>{
    const f=fixture();await connect(f);const original=sample(2);
    f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(original)});
    const title=f.ids.title.textContent, stages=f.ids.stages.textContent, timestamp=f.ids.updated.title;
    f.run(2500);let call=f.messages.at(-1).message;
    f.emit({jsonrpc:'2.0',id:call.id,error:{code:-1,message:'disconnected'}});await settle();
    assert.match(f.ids.connection.textContent,/Reconnecting/);assert.equal([...f.timers.values()][0].ms,5000);
    f.run(5000);call=f.messages.at(-1).message;
    const changed=sample(2);changed.title='Changed';changed.stages[0].status='completed';changed.updated_at='2026-10-08T09:30:00+00:00';
    f.emit({jsonrpc:'2.0',id:call.id,result:result(changed,false)});await settle();
    assert.match(f.ids.connection.textContent,/Connected/);assert.equal(f.ids.connection.dataset.kind,'');
    assert.equal([...f.timers.values()][0].ms,2500);
    assert.equal(f.ids.title.textContent,title);assert.equal(f.ids.stages.textContent,stages);assert.equal(f.ids.updated.title,timestamp);
    f.run(2500);call=f.messages.at(-1).message;
    f.emit({jsonrpc:'2.0',id:call.id,error:{code:-1}});await settle();
    assert.equal([...f.timers.values()][0].ms,5000);
    const stale=sample(1);
    f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(stale,false)});
    assert.match(f.ids.connection.textContent,/Reconnecting/);assert.equal([...f.timers.values()][0].ms,5000);
    f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(changed,false)});
    assert.match(f.ids.connection.textContent,/Connected/);assert.equal([...f.timers.values()][0].ms,2500);
    assert.equal(f.ids.title.textContent,title);assert.equal(f.ids.stages.textContent,stages);assert.equal(f.ids.updated.title,timestamp);
  });
  await check('incoming notification during polling cannot start an overlapping request',async()=>{
    const f=fixture();await connect(f);
    f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result()});f.run(2500);
    const call=f.messages.at(-1).message;
    f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(sample(2))});
    assert.equal(f.timers.size,1);assert.equal([...f.timers.values()][0].ms,4000);
    f.emit({jsonrpc:'2.0',id:call.id,result:result(sample(1),false)});await settle();
    assert.equal([...f.timers.values()][0].ms,2500);
  });
  await check('standalone and unavailable bridge state are honest',async()=>{
    const standalone=fixture(true);assert.match(standalone.ids.connection.textContent,/standalone browser is not connected/);assert.equal(standalone.messages.length,0);
    const f=fixture();f.run(4000);await settle();assert.match(f.ids.connection.textContent,/did not connect the panel/);assert.equal(f.timers.size,0);
  });
  await check('hidden view suspends polling and teardown clears timers',async()=>{
    const f=fixture();await connect(f);f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result()});
    f.visibility(true);assert.equal(f.timers.size,0);f.visibility(false);assert.equal(f.timers.size,1);
    f.emit({jsonrpc:'2.0',id:90,method:'ui/resource-teardown',params:{}});
    assert.equal(f.messages.at(-1).message.id,90);assert.equal(f.timers.size,0);
    f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(sample(9))});assert.equal(f.timers.size,0);
  });
  await check('host ping and teardown ids may collide with an outstanding poll id',async()=>{
    const f=fixture();await connect(f);f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result()});f.run(2500);
    const poll=f.messages.at(-1).message;
    f.emit({jsonrpc:'2.0',id:poll.id,method:'ping',params:{}});
    assert.equal(f.messages.at(-1).message.id,poll.id);assert.ok('result' in f.messages.at(-1).message);
    assert.equal([...f.timers.values()][0].ms,4000);
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
    assert.equal([...f.timers.values()][0].ms,4000);
    f.emit({jsonrpc:'2.0',id:poll.id,result:result(sample(2),false)});await settle();
    assert.equal([...f.timers.values()][0].ms,2500);
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
  await check('completed historical state has age without active-stale notice; failures preserve last state',async()=>{
    const completed=fixture();await connect(completed);completed.advance(86400000);
    const old=sample();old.stages.forEach(s=>s.status='completed');
    completed.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result(old)});
    assert.match(completed.ids.updated.textContent,/1 day ago/);assert.equal(completed.ids.freshness.hidden,true);
    const f=fixture();await connect(f);f.advance(86400000);
    f.emit({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result()});
    const stages=f.ids.stages.textContent;f.run(2500);const call=f.messages.at(-1).message;
    f.advance(86400000);f.emit({jsonrpc:'2.0',id:call.id,error:{code:-1}});await settle();
    assert.match(f.ids.connection.textContent,/Reconnecting/);assert.match(f.ids.updated.textContent,/2 days ago/);
    assert.equal(f.ids.freshness.hidden,false);assert.equal(f.ids.stages.textContent,stages);
    assert.equal(f.timers.size,1); // Existing backoff only; no separate age timer.
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
      assert.equal(f.ids.freshness.textContent,ru?'Этапы не обновлялись 2 минуты или дольше. Работа может продолжаться.':'Stages have not been updated for 2 minutes or longer. Work may still be continuing.');
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
  console.log('Bridge mock: '+count+' tests passed. Native host rendering NOT VERIFIED.');
}
tests().catch(error=>{console.error(error);process.exitCode=1;});
