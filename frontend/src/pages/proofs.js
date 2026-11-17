import {store} from '../stores/entities.js';
import {session} from '../stores/session.js';
import {proofsAPI} from '../api/entities.js';
import {table} from '../components/common/table.js';
import {esc,formObject} from '../utils/html.js';
import {message} from '../hooks/action.js';
const GENESIS='0'.repeat(64);
async function sha256hex(text){
 if(!window.crypto?.subtle)throw new Error('当前浏览器环境不支持摘要计算，请手工填写分段 JSON');
 const buf=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text));
 return [...new Uint8Array(buf)].map(b=>b.toString(16).padStart(2,'0')).join('');
}
function chainText(c){
 if(!c)return '';
 let t=`接齐至 ${c.proven_tip}`;
 if(c.first_gap!=null)t+=`，首个缺段 ${c.first_gap}`;
 if(c.break_position!=null)t+=`，位置 ${c.break_position} 前序摘要断裂`;
 if(c.staged)t+=`，暂存 ${c.staged} 段`;
 if(c.fork_position!=null)t+=`，与原主在位置 ${c.fork_position} 分叉`;
 return t;
}
export function proofsPage(){
 const s=store.proofStatus||{version:0,nodes:[]};
 return `<div class="section-title"><h2>节点日志链状态</h2><span>证明版本 v${s.version}</span></div>${table(['节点','已接齐至','暂存段','首个缺段','分叉位置','声明提交点'],s.nodes.map(n=>[esc(n.node),n.proven_tip,n.staged,n.first_gap??'—',n.fork_position??'—',n.committed_position??'—']))}<section class="split"><div><h2>录入分段证明</h2><p>每段含位置、任期、内容与前序摘要，并声明原主提交点。乱序或缺段的批次先暂存，接齐后才参与判定；同批任一冲突整批拒绝。写入中断后用同一批次键重试，不会重复收录。</p><p class="big-note">先接齐，再采信。</p></div>${session.role!=='viewer'?`<form id="proof-form"><label>节点<select name="node_name">${store.nodes.map(n=>`<option value="${esc(n.name)}">${esc(n.name)}</option>`).join('')}</select></label><label>批次键<input name="batch_key" value="batch-${Date.now()}" required pattern="[a-zA-Z0-9_-]+" minlength="8" maxlength="80"></label><div class="fields"><label>原主声明提交点<input name="committed_position" type="number" min="0" value="0" required></label><label>提交摘要<input name="committed_digest" maxlength="64" placeholder="提交点为 0 时可留空"></label></div><label>分段 JSON<textarea name="segments" rows="7" required placeholder='[{"position":1,"term":6,"content":"log-1","prev_digest":"${GENESIS}"}]'></textarea></label><div class="toolbar"><button type="button" class="secondary" id="fill-demo">填入演示分段</button><button type="submit">校验并落盘 →</button></div></form>`:'<p class="readonly">观察员可查看链状态与已落盘批次。</p>'}</section><h2>已落盘批次</h2>${table(['批次键','节点','段数','版本','时间'],store.proofs.map(b=>[esc(b.batch_key),esc(b.node_name),b.segment_count,'v'+b.version,esc((b.created_at||'').replace('T',' ').slice(0,19))]))}`;
}
export function bindProofs(render){
 const f=document.querySelector('#proof-form');
 document.querySelector('#fill-demo')?.addEventListener('click',async()=>{
  try{
   const node=f.elements.node_name.value;
   const st=(store.proofStatus.nodes||[]).find(n=>n.node===node);
   const term=store.nodes.find(n=>n.name===node)?.term||6;
   let prev=st?.tip_digest||GENESIS;const start=(st?.proven_tip||0)+1;const segs=[];
   for(let p=start;p<start+3;p++){const content=`log-${p}`;const digest=await sha256hex(`${prev}|${p}|${term}|${content}`);segs.push({position:p,term,content,prev_digest:prev});prev=digest;}
   f.elements.segments.value=JSON.stringify(segs,null,1);
   f.elements.committed_position.value=segs[segs.length-1].position;
   f.elements.committed_digest.value=prev;
   message('已按当前链顶生成演示分段，可直接提交，或改内容制造分叉');
  }catch(e){message(e.message,true);}
 });
 f?.addEventListener('submit',async e=>{
  e.preventDefault();
  const d=formObject(f);let segments;
  try{segments=JSON.parse(d.segments);if(!Array.isArray(segments)||!segments.length)throw 0;}
  catch{message('分段 JSON 无法解析，请检查格式',true);return;}
  const body={batch_key:d.batch_key,node_name:d.node_name,committed_position:Number(d.committed_position)||0,committed_digest:d.committed_digest||'',segments};
  const b=f.querySelector('button[type=submit]');b.disabled=true;
  try{
   const out=await proofsAPI.create(body);
   await render();
   message(out.deduplicated?`批次 ${out.batch.batch_key} 此前已落盘（版本 v${out.batch.version}），未重复收录`:`批次已落盘为版本 v${out.batch.version}；${chainText(out.chain)}`);
  }catch(err){message(err.message,true);b.disabled=false;}
 });
}
