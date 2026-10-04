const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
class Element{constructor(){this.style={};this.listeners={};this.children=[]}setAttribute(){}addEventListener(k,f){this.listeners[k]=f}prepend(e){this.children.unshift(e)}append(e){this.children.push(e)}}
const form=new Element(),requests=[],events=[];
const context={document:{readyState:'complete',querySelector:s=>s.startsWith('form')?form:null,createElement:()=>new Element(),addEventListener(){}},window:{dispatchEvent:e=>events.push(e)},Event:class{constructor(type){this.type=type}},TOKEN:'test',fetch:(url,opts)=>new Promise((resolve,reject)=>requests.push({url,body:JSON.parse(opts.body),resolve,reject})),setTimeout(){},clearTimeout(){}};
vm.runInNewContext(fs.readFileSync(__dirname+'/trading-control-ui.js','utf8'),context);
const flush=()=>new Promise(setImmediate),button=form.children[0];
function respond(enabled){requests.at(-1).resolve({ok:true,json:async()=>({enabled})})}
(async()=>{
 assert.equal(button.disabled,true);assert.equal(requests[0].body.action,'status');respond(true);await flush();assert.equal(button.textContent,'매매 중지');
 button.listeners.click();button.listeners.click();assert.equal(requests.length,2);assert.equal(requests.at(-1).body.action,'pause');assert.equal(button.disabled,true);respond(false);await flush();assert.equal(button.textContent,'매매 시작');
 button.listeners.click();assert.equal(requests.at(-1).body.action,'resume');respond(true);await flush();assert.equal(button.textContent,'매매 중지');
 button.listeners.click();requests.at(-1).reject(Error());await flush();assert.equal(button.textContent,'매매 상태 확인');button.listeners.click();assert.equal(requests.at(-1).body.action,'status');respond(false);await flush();assert.equal(button.textContent,'매매 시작');
 assert.equal(events.length,4);console.log('PASS: stop/start, server-confirmed labels, duplicate click guard, failure reconciliation');
})().catch(e=>{console.error(e);process.exitCode=1});
