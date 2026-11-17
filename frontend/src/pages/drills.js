import {store} from '../stores/entities.js';
import {session} from '../stores/session.js';
import {drillsAPI} from '../api/entities.js';
import {table} from '../components/common/table.js';
import {badge} from '../components/common/status.js';
import {esc,formObject} from '../utils/html.js';
import {action} from '../hooks/action.js';
export function drillsPage(){return `<section class="split compact"><div><h2>提交一次演练</h2><p>节点与剧本在提交瞬间冻结。后台计算后，查看判定依据和导出结果。</p></div>${session.role!=='viewer'?`<form id="drill-form"><label>故障剧本<select name="scenario_id">${store.scenarios.map(s=>`<option value="${s.id}">${esc(s.name)}</option>`).join('')}</select></label><label>演练标签<input name="label" value="晚班切主核验" required maxlength="120"></label><button type="submit">冻结快照并入队 →</button></form>`:'<p class="readonly">观察员可复核下方记录。</p>'}</section><div class="section-title"><h2>最近演练记录</h2><button class="secondary" id="refresh">刷新状态</button></div>${table(['编号','演练','执行状态','决策','证据'],store.drills.map(d=>[d.id,esc(d.label),badge(d.status),d.result?.decision==='approved'?'允许切主':d.result?.decision==='blocked'?'安全阻断':'待计算',`<a href="#detail/${d.id}">查看记录 →</a>`]))}`;}
export function bindDrills(render){document.querySelector('#refresh').onclick=render;action(document.querySelector('#drill-form'),async f=>{const d=formObject(f);d.scenario_id=Number(d.scenario_id);const job=await drillsAPI.create(d);location.hash='#detail/'+job.id;});}
