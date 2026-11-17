import {api} from '../api/client.js';
import {session} from '../stores/session.js';
import {action} from '../hooks/action.js';
export function loginPage(){return `<div class="login"><section><p class="eyebrow">HENGSHI / DATABASE RELIABILITY</p><h1>值班交接，<br>从一次可复查<br>的演练开始。</h1><p>在切主之前，先验证法定票数、旧主隔离与日志差距。</p><div class="boundary">受控演练模型 · 所有选主结果只保存为演练记录</div></section><form id="login"><h2>值班账号</h2><label>账号<input name="email" type="email" value="operator@hengshi.local" required></label><label>密码<input name="password" type="password" value="Drill2026!" required></label><button type="submit">进入演练册 →</button><p>admin / operator / viewer @hengshi.local<br>演示密码 Drill2026!</p><div id="notice" hidden></div></form></div>`;}
export function bindLogin(){action(document.querySelector('#login'),async form=>{session.save(await api('/auth/login',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(form)))}));location.hash='#nodes';});}
