"""
Web dashboard for multi-account HideMyEmail generation.
Includes: Apple ID login + 2FA, per-account Start/Stop/Resume controls.
"""

import logging

from aiohttp import web


logger = logging.getLogger(__name__)


DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HideMyEmail Generator</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #0a0a1a; --card: rgba(255,255,255,0.025);
            --border: rgba(255,255,255,0.06); --border-h: rgba(255,255,255,0.12);
            --t1: #e2e8f0; --t2: #94a3b8; --tm: #64748b;
            --ok: #22c55e; --warn: #eab308; --err: #ef4444;
            --accent: #6366f1;
            --grad: linear-gradient(90deg,#6366f1,#8b5cf6);
            --grad-c: linear-gradient(90deg,#06b6d4,#22d3ee);
        }
        *{margin:0;padding:0;box-sizing:border-box}
        body{font-family:'Inter',-apple-system,sans-serif;background:var(--bg);color:var(--t1);
            min-height:100vh;padding:1.25rem;
            background-image:radial-gradient(ellipse at 20% 0%,rgba(99,102,241,.07) 0%,transparent 50%),
            radial-gradient(ellipse at 80% 100%,rgba(139,92,246,.05) 0%,transparent 50%)}
        .container{max-width:820px;margin:0 auto}

        /* Header */
        .header{display:flex;align-items:center;justify-content:space-between;
            margin-bottom:1rem;padding-bottom:.75rem;border-bottom:1px solid var(--border);flex-wrap:wrap;gap:.5rem}
        .header h1{font-size:1.2rem;font-weight:700;
            background:linear-gradient(135deg,#e2e8f0,#a78bfa);
            -webkit-background-clip:text;-webkit-text-fill-color:transparent}
        .hdr-btns{display:flex;gap:.4rem;align-items:center;flex-wrap:wrap}

        /* Summary */
        .summary{background:var(--card);border:1px solid var(--border);border-radius:12px;
            padding:.85rem 1rem;margin-bottom:1rem;display:flex;align-items:center;gap:1rem}
        .sum-nums{font-family:'JetBrains Mono',monospace;font-size:1.1rem;font-weight:700;min-width:80px}
        .sum-bar{flex:1;height:8px;background:rgba(255,255,255,.05);border-radius:99px;overflow:hidden}
        .sum-fill{height:100%;border-radius:99px;background:var(--grad);transition:width .5s}
        .sum-label{font-size:.68rem;color:var(--tm);text-transform:uppercase;letter-spacing:.06em}

        /* Account card */
        .acct{background:var(--card);border:1px solid var(--border);border-radius:12px;
            margin-bottom:.7rem;border-left:3px solid var(--tm);overflow:hidden;transition:border-color .2s}
        .acct:hover{border-color:var(--border-h)}
        .acct-body{padding:.8rem 1rem}

        /* Row 1: name, controls, status, fp */
        .acct-r1{display:flex;align-items:center;gap:.5rem;margin-bottom:.55rem;flex-wrap:wrap}
        .acct-name{font-size:.82rem;font-weight:600;overflow:hidden;text-overflow:ellipsis;
            white-space:nowrap;max-width:220px}
        .acct-ctrl{display:flex;gap:.25rem;align-items:center;margin-left:auto}
        .cnt-input{width:56px;background:rgba(255,255,255,.05);border:1px solid var(--border);
            border-radius:5px;color:var(--t1);font-family:'JetBrains Mono',monospace;
            font-size:.75rem;padding:.22rem .35rem;text-align:center;outline:none;
            transition:border-color .15s}
        .cnt-input:focus{border-color:var(--accent)}
        .cnt-input:disabled{opacity:.35;cursor:not-allowed}
        .cb{padding:.22rem .5rem;border-radius:5px;border:1px solid var(--border);
            font-size:.68rem;cursor:pointer;font-family:'Inter',sans-serif;font-weight:600;
            transition:all .15s;line-height:1.2}
        .cb:active{transform:scale(.95)}
        .cb:disabled{opacity:.4;cursor:not-allowed}
        .cb.start{background:rgba(34,197,94,.1);border-color:rgba(34,197,94,.3);color:var(--ok)}
        .cb.start:hover:not(:disabled){background:rgba(34,197,94,.2)}
        .cb.stop{background:rgba(239,68,68,.1);border-color:rgba(239,68,68,.3);color:var(--err)}
        .cb.stop:hover{background:rgba(239,68,68,.2)}
        .cb.resume{background:rgba(99,102,241,.1);border-color:rgba(99,102,241,.3);color:#818cf8}
        .cb.resume:hover{background:rgba(99,102,241,.2)}
        .cb.mini{padding:.22rem .35rem;font-size:.6rem}
        .badge{display:inline-flex;align-items:center;gap:.3rem;padding:.12rem .45rem;
            border-radius:99px;font-size:.62rem;font-weight:600;text-transform:uppercase;
            letter-spacing:.04em;background:rgba(255,255,255,.04);border:1px solid var(--border)}
        .dot{width:6px;height:6px;border-radius:50%;background:var(--tm);flex-shrink:0}
        .dot.generating{background:var(--ok);animation:pulse 1.5s ease-in-out infinite}
        .dot.short_cooldown{background:#6366f1}
        .dot.long_cooldown{background:var(--warn);animation:pulse 2s ease-in-out infinite}
        .dot.rotating{background:#6366f1;animation:spin 1s linear infinite}
        .dot.done{background:var(--ok)} .dot.error{background:var(--err)}
        .dot.stopped{background:var(--warn)} .dot.idle{background:var(--tm)}
        .dot.requires_2fa{background:#f59e0b;animation:pulse 1s ease-in-out infinite}
        .dot.unauthenticated{background:var(--tm)}
        .dot.authenticated{background:var(--ok)}
        @keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
        @keyframes spin{from{transform:rotate(0)}to{transform:rotate(360deg)}}
        .acct-fp{font-family:'JetBrains Mono',monospace;font-size:.68rem;color:#6366f1;
            background:rgba(99,102,241,.08);border:1px solid rgba(99,102,241,.15);
            padding:.1rem .4rem;border-radius:5px;margin-left:auto}

        /* Bars */
        .acct-bars{display:flex;gap:.75rem;align-items:center;margin-bottom:.4rem;flex-wrap:wrap}
        .bg{display:flex;align-items:center;gap:.35rem;flex:1;min-width:170px}
        .bl{font-size:.62rem;color:var(--tm);min-width:32px}
        .bt{flex:1;height:7px;background:rgba(255,255,255,.05);border-radius:99px;overflow:hidden}
        .bf{height:100%;border-radius:99px;background:var(--grad);transition:width .4s}
        .bf.cy{background:var(--grad-c)}
        .bn{font-family:'JetBrains Mono',monospace;font-size:.72rem;font-weight:600;
            min-width:42px;text-align:right}

        /* Cooldown */
        .acct-cd{display:none;align-items:center;gap:.35rem;margin-bottom:.4rem;
            font-family:'JetBrains Mono',monospace;font-size:.82rem;font-weight:600;color:var(--warn)}
        .acct-cd.vis{display:flex}

        /* Auth row (2FA) */
        .auth-row{display:flex;align-items:center;gap:.4rem;margin-bottom:.4rem;
            padding:.4rem .5rem;border-radius:6px;background:rgba(245,158,11,.06);
            border:1px solid rgba(245,158,11,.15)}
        .auth-row input{width:90px;background:rgba(255,255,255,.05);border:1px solid var(--border);
            border-radius:5px;color:var(--t1);font-family:'JetBrains Mono',monospace;
            font-size:.82rem;padding:.25rem .4rem;text-align:center;outline:none;
            letter-spacing:.15em}
        .auth-row input:focus{border-color:var(--accent)}
        .auth-row .cb{font-size:.7rem}
        .auth-label{font-size:.7rem;color:var(--warn)}
        .auth-del{font-size:.62rem;color:var(--tm);cursor:pointer;margin-left:auto}
        .auth-del:hover{color:var(--err)}

        /* Footer */
        .acct-ft{display:flex;align-items:center;justify-content:space-between;
            padding-top:.3rem;border-top:1px solid var(--border)}
        .etog{font-size:.72rem;color:var(--t2);cursor:pointer;user-select:none;transition:color .15s}
        .etog:hover{color:var(--t1)}
        .acct-err{font-size:.68rem;color:var(--tm)}
        .acct-err.has{color:var(--err)}
        .cpb{background:none;border:1px solid var(--border);color:var(--tm);
            padding:.12rem .35rem;border-radius:4px;font-size:.62rem;cursor:pointer;
            font-family:'Inter',sans-serif;transition:all .15s;margin-left:.4rem}
        .cpb:hover{border-color:#6366f1;color:var(--t1)}
        .cpb.ok{border-color:var(--ok);color:var(--ok)}

        /* Email list */
        .elist{display:none;padding:.4rem 1rem .6rem;border-top:1px solid var(--border);
            max-height:200px;overflow-y:auto;scrollbar-width:thin;
            scrollbar-color:rgba(255,255,255,.08) transparent}
        .elist::-webkit-scrollbar{width:3px}
        .elist::-webkit-scrollbar-thumb{background:rgba(255,255,255,.08);border-radius:2px}
        .elist.open{display:block}
        .ei{font-family:'JetBrains Mono',monospace;font-size:.7rem;padding:.18rem 0;color:var(--t2)}
        .ei:nth-child(even){color:var(--t1)}
        .eix{color:var(--tm);display:inline-block;min-width:22px;text-align:right;margin-right:.35rem}

        /* Message */
        .acct-msg{font-size:.7rem;color:var(--tm);padding:.25rem 0;min-height:1rem;
            overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

        /* Buttons */
        .btn{background:rgba(255,255,255,.05);border:1px solid var(--border);color:var(--t2);
            padding:.3rem .6rem;border-radius:6px;font-size:.7rem;cursor:pointer;
            font-family:'Inter',sans-serif;transition:all .15s}
        .btn:hover{background:rgba(99,102,241,.1);border-color:#6366f1;color:var(--t1)}
        .btn.ok{background:rgba(34,197,94,.1);border-color:var(--ok);color:var(--ok)}
        .btn.add{background:rgba(99,102,241,.1);border-color:rgba(99,102,241,.3);color:#818cf8}
        .btn.add:hover{background:rgba(99,102,241,.2)}

        /* Modal */
        .modal-bg{display:none;position:fixed;top:0;left:0;right:0;bottom:0;
            background:rgba(0,0,0,.6);backdrop-filter:blur(4px);z-index:100;
            justify-content:center;align-items:center}
        .modal-bg.open{display:flex}
        .modal{background:#12122a;border:1px solid var(--border);border-radius:14px;
            padding:1.5rem;width:380px;max-width:90vw;box-shadow:0 20px 60px rgba(0,0,0,.5)}
        .modal h2{font-size:1rem;font-weight:700;margin-bottom:1rem;
            background:linear-gradient(135deg,#e2e8f0,#a78bfa);
            -webkit-background-clip:text;-webkit-text-fill-color:transparent}
        .modal-field{margin-bottom:.75rem}
        .modal-field label{display:block;font-size:.7rem;color:var(--t2);margin-bottom:.25rem;font-weight:500}
        .modal-field input,.modal-field select{width:100%;background:rgba(255,255,255,.04);
            border:1px solid var(--border);border-radius:6px;color:var(--t1);
            font-family:'Inter',sans-serif;font-size:.82rem;padding:.45rem .6rem;outline:none;
            transition:border-color .15s}
        .modal-field input:focus,.modal-field select:focus{border-color:var(--accent)}
        .modal-field select{cursor:pointer}
        .modal-field select option{background:#12122a}
        .modal-actions{display:flex;gap:.5rem;margin-top:1rem}
        .modal-actions .btn{flex:1;text-align:center;padding:.5rem;font-size:.82rem;font-weight:600}
        .modal-msg{font-size:.72rem;margin-top:.5rem;min-height:1rem}
        .modal-msg.err{color:var(--err)}
        .modal-msg.ok{color:var(--ok)}
        .modal-msg.warn{color:var(--warn)}

        @media(max-width:520px){
            .acct-bars{flex-direction:column;gap:.35rem}
            .bg{min-width:100%}
            .acct-name{max-width:140px}
            .acct-r1{gap:.35rem}
        }
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>🔒 HideMyEmail Generator</h1>
        <div class="hdr-btns">
            <button class="btn add" onclick="openModal()">➕ Add Account</button>
            <button class="btn" onclick="startAll()">▶ Start All</button>
            <button class="btn" onclick="stopAll()">⏹ Stop All</button>
            <button class="btn" id="cpa" onclick="copyAll()">Copy All</button>
        </div>
    </div>
    <div class="summary">
        <div>
            <div class="sum-nums" id="sn">0 / 0</div>
            <div class="sum-label" id="sl">0 accounts</div>
        </div>
        <div class="sum-bar"><div class="sum-fill" id="sb" style="width:0%"></div></div>
    </div>
    <div id="ac"></div>
</div>

<!-- Login Modal -->
<div class="modal-bg" id="modal">
    <div class="modal">
        <h2 id="modal-title">🍎 Add Apple Account</h2>
        <!-- Step 1: Login -->
        <div id="step-login">
            <div class="modal-field">
                <label>Apple ID</label>
                <input type="email" id="m-aid" placeholder="your@icloud.com" autocomplete="username">
            </div>
            <div class="modal-field">
                <label>Password</label>
                <input type="password" id="m-pw" placeholder="••••••••" autocomplete="current-password">
            </div>
            <div class="modal-field">
                <label>Region</label>
                <select id="m-domain">
                    <option value="cn">🇨🇳 China (iCloud.com.cn)</option>
                    <option value="com">🌍 Global (iCloud.com)</option>
                </select>
            </div>
            <div class="modal-actions">
                <button class="btn" onclick="closeModal()">Cancel</button>
                <button class="btn add" id="m-login-btn" onclick="doLogin()">🔐 Login</button>
            </div>
        </div>
        <!-- Step 2: 2FA -->
        <div id="step-2fa" style="display:none">
            <p style="font-size:.78rem;color:var(--t2);margin-bottom:.75rem">
                Enter the 6-digit verification code from your trusted device.
            </p>
            <div class="modal-field">
                <label>Verification Code</label>
                <input type="text" id="m-code" maxlength="6" placeholder="000000"
                    style="letter-spacing:.3em;text-align:center;font-size:1.1rem;font-family:'JetBrains Mono',monospace"
                    autocomplete="one-time-code">
            </div>
            <div class="modal-actions">
                <button class="btn" onclick="closeModal()">Cancel</button>
                <button class="btn add" id="m-2fa-btn" onclick="doVerify()">✓ Verify</button>
            </div>
        </div>
        <div class="modal-msg" id="m-msg"></div>
    </div>
</div>

<script>
const C=['#6366f1','#8b5cf6','#06b6d4','#10b981','#f59e0b','#ef4444','#ec4899','#14b8a6'];
const SL={idle:'Idle',generating:'Generating',short_cooldown:'Cooldown',
    long_cooldown:'Long Cooldown',rotating:'Rotating',done:'Done',
    error:'Error',stopped:'Stopped'};
const RUNNING=['generating','short_cooldown','long_cooldown','rotating'];
const AUTH_OK='authenticated';

let S={accounts:[],total_target:0,total_completed:0};
let init=false, openE={}, cardCount=0;
let modalAppleId='';

// ── Card creation ──
function mk(a,i){
    const c=C[i%C.length], d=document.createElement('div');
    d.className='acct'; d.id='a'+i; d.style.borderLeftColor=c;
    d.innerHTML=`
    <div class="acct-body">
        <div class="acct-r1">
            <span class="acct-name" style="color:${c}">📧 ${a.account}</span>
            <div class="acct-ctrl" id="ctrl${i}">
                <label style="font-size:0.65rem;color:var(--t2)">目标</label>
                <input type="number" class="cnt-input" id="ci${i}" value="5" min="1" max="9999" style="width:48px;" title="生成数量">
                <label style="font-size:0.65rem;color:var(--t2);margin-left:3px">间隔(min)</label>
                <input type="number" class="cnt-input" id="itv${i}" value="45" min="1" max="999" style="width:42px;" title="轮次间隔">
                <button class="cb start" id="go${i}" onclick="goA(${i})">▶ Start</button>
                <button class="cb stop" id="sp${i}" onclick="spA(${i})" style="display:none">⏹ Stop</button>
                <button class="cb resume" id="rs${i}" onclick="rsA(${i})" style="display:none" title="Resume: 继续由于 Stop 暂停的进度">▶ Resume</button>
                <button class="cb start mini" id="rt${i}" onclick="goA(${i})" style="display:none" title="Restart: 进度清零，并按照输入框新值重新开始此账号任务">↺ Restart</button>
            </div>
            <span class="badge"><span class="dot" id="d${i}"></span> <span id="s${i}">Idle</span></span>
            <span class="acct-fp" id="f${i}">—</span>
            <span class="auth-del" id="del${i}" onclick="removeA(${i})" style="display:none" title="删除此账号">✕</span>
        </div>
        <!-- 2FA inline -->
        <div class="auth-row" id="2fa${i}" style="display:none">
            <span class="auth-label">🔑 2FA:</span>
            <input type="text" id="code${i}" maxlength="6" placeholder="000000" autocomplete="one-time-code">
            <button class="cb start" onclick="verify2fa(${i})">Verify</button>
            <span class="auth-del" onclick="removeA(${i})">✕ Remove</span>
        </div>
        <div class="acct-bars" id="bars${i}" style="display:none">
            <div class="bg" style="min-width:60px;flex:none">
                <span class="bl">Total</span>
                <span class="bn" id="nTot${i}" style="text-align:left;color:var(--t1)">0</span>
            </div>
            <div class="bg">
                <span class="bl">Target</span>
                <div class="bt"><div class="bf" id="b${i}" style="width:0%"></div></div>
                <span class="bn" id="n${i}">0/0</span>
            </div>
            <div class="bg">
                <span class="bl">Cycle</span>
                <div class="bt"><div class="bf cy" id="c${i}" style="width:0%"></div></div>
                <span class="bn" id="cn${i}">0/5</span>
            </div>
        </div>
        <div class="acct-cd" id="cd${i}">⏳ <span id="ct${i}">00:00</span></div>
        <div class="acct-msg" id="m${i}"></div>
        <div class="acct-ft" id="ft${i}" style="display:none">
            <span>
                <span class="etog" onclick="te(${i})"><span id="ar${i}">▸</span> <span id="el${i}">Emails (0)</span></span>
                <button class="cpb" id="cp${i}" onclick="cpA(${i})">copy</button>
            </span>
            <span class="acct-err" id="er${i}">0 errors</span>
        </div>
    </div>
    <div class="elist" id="e${i}"></div>`;
    return d;
}

// ── Card update ──
function up(a,i){
    const auth=a.auth_status||'unauthenticated';
    const needsAuth=auth!==AUTH_OK;
    const needs2fa=auth==='requires_2fa';

    // Status dot + text
    const dot=gid('d'+i);
    if(dot){
        if(needsAuth) dot.className='dot '+auth;
        else dot.className='dot '+(a.status||'idle');
    }
    const statusText=needsAuth?(needs2fa?'2FA Required':'Not Logged In'):(SL[a.status]||a.status);
    st('s'+i, statusText);

    // 2FA row
    sh('2fa'+i, needs2fa);

    // Hide controls if not authenticated
    const isAuth=!needsAuth;
    const run=isAuth && RUNNING.includes(a.status);
    const stopped=isAuth && a.status==='stopped';
    const idle=isAuth && ['idle','done','error'].includes(a.status);
    const canResume=stopped && a.completed<a.target;

    // Buttons
    sh('go'+i, idle); sh('sp'+i, run); sh('rs'+i, canResume); sh('rt'+i, stopped);
    const ci=gid('ci'+i); if(ci){ci.disabled=run||needsAuth; if(needsAuth)ci.style.display='none'; else ci.style.display='';}
    const itv=gid('itv'+i); if(itv){itv.disabled=run||needsAuth; if(needsAuth)itv.style.display='none'; else itv.style.display='';}
    if(run && a.target>0 && ci) ci.value=a.target;
    if(run && a.interval && itv) itv.value=a.interval;

    // Disable start if not authenticated
    const goBtn=gid('go'+i); if(goBtn) goBtn.disabled=needsAuth;
    const l1=ci?.previousElementSibling; if(l1) l1.style.display=needsAuth?'none':'';
    const l2=itv?.previousElementSibling; if(l2) l2.style.display=needsAuth?'none':'';

    // Show bars/footer only after started
    const started=a.target>0 && isAuth;
    sh('bars'+i, isAuth); sh('ft'+i, isAuth);

    // Totals
    st('nTot'+i, a.emails?a.emails.length:0);

    // Fingerprint
    st('f'+i, isAuth?(a.fingerprint||'—'):'—');

    // Delete button — show when not running
    sh('del'+i, isAuth && !run);

    // Progress
    const p=a.target>0?(a.completed/a.target*100):0;
    sw('b'+i,p); st('n'+i, started?a.completed+'/'+a.target:'—');

    // Cycle
    const cp=a.cycle_size>0?(a.success_in_cycle/a.cycle_size*100):0;
    sw('c'+i,cp); st('cn'+i, a.success_in_cycle+'/'+a.cycle_size);

    // Cooldown
    const cdEl=gid('cd'+i);
    if(a.cooldown_end>0){
        const r=Math.max(0,a.cooldown_end-Date.now()/1000);
        if(r>0){const m=Math.floor(r/60),s=Math.floor(r%60);
            st('ct'+i,m+':'+String(s).padStart(2,'0'));
            cdEl.classList.add('vis');
        } else cdEl.classList.remove('vis');
    } else cdEl.classList.remove('vis');

    // Message
    st('m'+i, a.message||'');

    // Errors
    const errEl=gid('er'+i);
    if(errEl){errEl.textContent=a.errors+' error'+(a.errors!==1?'s':'');
        errEl.className='acct-err'+(a.errors>0?' has':'');}

    // Email label
    st('el'+i,'Emails ('+(a.emails?a.emails.length:0)+')');

    // Emails (if open)
    if(openE[i]&&a.emails){
        const el=gid('e'+i);
        if(el&&el._c!==a.emails.length){
            el._c=a.emails.length;
            el.innerHTML=a.emails.slice().reverse().map((e,j)=>{
                const n=a.emails.length-j;
                return `<div class="ei" style="display:flex;justify-content:space-between"><span><span class="eix">${n}.</span>${e.email}</span><span style="font-size:0.65rem;color:var(--tm)">${e.time||''}</span></div>`;
            }).join('');
        }
    }
}

// ── Helpers ──
function gid(id){return document.getElementById(id)}
function st(id,t){const e=gid(id);if(e)e.textContent=t}
function sw(id,p){const e=gid(id);if(e)e.style.width=Math.min(100,p)+'%'}
function sh(id,v){const e=gid(id);if(e)e.style.display=v?'':'none'}

function te(i){
    openE[i]=!openE[i];
    const el=gid('e'+i), ar=gid('ar'+i);
    if(el){el.classList.toggle('open',openE[i]); ar.textContent=openE[i]?'▾':'▸';
        if(openE[i]){el._c=-1; if(S.accounts[i]) up(S.accounts[i],i);}}
}

// ── Modal ──
function openModal(){
    gid('modal').classList.add('open');
    gid('step-login').style.display='';
    gid('step-2fa').style.display='none';
    gid('m-msg').textContent='';
    gid('m-msg').className='modal-msg';
    gid('m-aid').value=''; gid('m-pw').value=''; gid('m-code').value='';
    gid('modal-title').textContent='🍎 Add Apple Account';
    modalAppleId='';
    gid('m-aid').focus();
}
function closeModal(){gid('modal').classList.remove('open');}

async function doLogin(){
    const aid=gid('m-aid').value.trim();
    const pw=gid('m-pw').value;
    const domain=gid('m-domain').value;
    if(!aid||!pw){mmsg('Please enter Apple ID and password','err');return;}
    const btn=gid('m-login-btn'); btn.disabled=true; btn.textContent='⏳ Logging in...';
    mmsg('Authenticating via SRP...','warn');
    try{
        const r=await fetch('/api/accounts/add',{method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({apple_id:aid,password:pw,domain:domain})});
        const d=await r.json();
        if(d.result==='ok'){
            mmsg('✓ Login successful!','ok');
            setTimeout(()=>{closeModal();poll();},800);
        } else if(d.result==='2fa_required'){
            modalAppleId=aid;
            gid('step-login').style.display='none';
            gid('step-2fa').style.display='';
            gid('modal-title').textContent='🔐 Enter 2FA Code';
            mmsg('Check your trusted device for the code','warn');
            gid('m-code').focus();
            poll(); // refresh cards to show new account
        } else {
            mmsg(d.result||'Login failed','err');
        }
    }catch(e){mmsg('Network error: '+e.message,'err');}
    finally{btn.disabled=false; btn.textContent='🔐 Login';}
}

async function doVerify(){
    const code=gid('m-code').value.trim();
    if(!code||code.length<6){mmsg('Enter the 6-digit code','err');return;}
    const btn=gid('m-2fa-btn'); btn.disabled=true; btn.textContent='⏳ Verifying...';
    mmsg('Verifying code...','warn');
    try{
        const r=await fetch('/api/accounts/'+encodeURIComponent(modalAppleId)+'/verify-2fa',{
            method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({code:code})});
        const d=await r.json();
        if(d.result==='ok'){
            mmsg('✓ Verified! Account ready.','ok');
            setTimeout(()=>{closeModal();poll();},800);
        } else {
            mmsg(d.result||'Verification failed','err');
        }
    }catch(e){mmsg('Network error: '+e.message,'err');}
    finally{btn.disabled=false; btn.textContent='✓ Verify';}
}
function mmsg(t,cls){const e=gid('m-msg');e.textContent=t;e.className='modal-msg '+cls;}

// ── Inline 2FA verify ──
async function verify2fa(i){
    const a=S.accounts[i]; if(!a)return;
    const code=gid('code'+i).value.trim();
    if(!code||code.length<6)return;
    try{
        const r=await fetch('/api/accounts/'+encodeURIComponent(a.account)+'/verify-2fa',{
            method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({code:code})});
        const d=await r.json();
        if(d.result==='ok') poll();
        else alert(d.result||'Failed');
    }catch(e){alert(e.message);}
}

// ── Remove account ──
async function removeA(i){
    const a=S.accounts[i]; if(!a)return;
    if(!confirm('Remove '+a.account+'? Session files will be deleted.'))return;
    await fetch('/api/accounts/'+encodeURIComponent(a.account)+'/remove',{method:'POST'});
    init=false; cardCount=0; poll();
}

// ── Generation API ──
async function goA(i){
    try {
        const a=S.accounts[i], c=parseInt(gid('ci'+i).value), itv=parseInt(gid('itv'+i).value)||45;
        if(!c||c<1){gid('ci'+i).focus();return;}
        const r=await fetch('/api/accounts/'+encodeURIComponent(a.account)+'/start',
            {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({count:c,interval:itv})});
        const d=await r.json();
        if(d.result && d.result!=='ok') alert(d.result);
        poll();
    } catch(e) {
        alert('Error: ' + e.message);
    }
}
async function spA(i){
    try {
        const a=S.accounts[i];
        await fetch('/api/accounts/'+encodeURIComponent(a.account)+'/stop',{method:'POST'});
        poll();
    } catch(e) {
        alert('Error: ' + e.message);
    }
}
async function rsA(i){
    try {
        const a=S.accounts[i];
        const r=await fetch('/api/accounts/'+encodeURIComponent(a.account)+'/resume',{method:'POST'});
        const d=await r.json();
        if(d.result && d.result!=='ok') alert(d.result);
        poll();
    } catch(e) {
        alert('Error: ' + e.message);
    }
}
function cpA(i){
    const a=S.accounts[i];
    if(!a||!a.emails||!a.emails.length)return;
    navigator.clipboard.writeText(a.emails.map(e=>e.email).join('\n')).then(()=>{
        const b=gid('cp'+i);b.textContent='✓';b.classList.add('ok');
        setTimeout(()=>{b.textContent='copy';b.classList.remove('ok')},1500);
    });
}
function copyAll(){
    const all=S.accounts.flatMap(a=>a.emails||[]);
    if(!all.length)return;
    navigator.clipboard.writeText(all.map(e=>e.email).join('\n')).then(()=>{
        const b=gid('cpa');b.textContent='Copied!';b.classList.add('ok');
        setTimeout(()=>{b.textContent='Copy All';b.classList.remove('ok')},2000);
    });
}
async function startAll(){
    for(let i=0;i<S.accounts.length;i++){
        const a=S.accounts[i];
        if(a.auth_status===AUTH_OK && ['idle','done','error','stopped'].includes(a.status)){
            const c=parseInt(gid('ci'+i).value);
            if(c&&c>0) await goA(i);
        }
    }
}
async function stopAll(){
    for(let i=0;i<S.accounts.length;i++){
        if(RUNNING.includes(S.accounts[i].status)) await spA(i);
    }
}

// ── Polling ──
async function poll(){
    try{
        const r=await fetch('/api/status'); S=await r.json();
        // Rebuild cards if count changed
        if(S.accounts.length!==cardCount){
            const c=gid('ac'); c.innerHTML='';
            S.accounts.forEach((a,i)=>c.appendChild(mk(a,i)));
            cardCount=S.accounts.length;
            init=true;
        }
        // Summary
        const p=S.total_target>0?(S.total_completed/S.total_target*100):0;
        st('sn', S.total_completed+' / '+S.total_target);
        sw('sb', p);
        const ac=S.accounts.length;
        const authed=S.accounts.filter(a=>a.auth_status===AUTH_OK).length;
        const g=S.accounts.filter(a=>RUNNING.includes(a.status)).length;
        const dn=S.accounts.filter(a=>a.status==='done').length;
        let ps=[]; if(authed)ps.push(authed+' logged in'); if(g)ps.push(g+' active');
        if(dn)ps.push(dn+' done');
        st('sl', ac+' account'+(ac!==1?'s':'')+(ps.length?' · '+ps.join(' · '):''));

        S.accounts.forEach((a,i)=>up(a,i));
    }catch(e){console.error('Poll failed:',e)}
}

setInterval(poll,2000);
setInterval(()=>{if(S.accounts)S.accounts.forEach((a,i)=>up(a,i))},1000);
poll();
</script>
</body>
</html>
"""




async def _json_api(handler_name: str, action, *, error_key: str = "result", error_value=None):
    try:
        return await action()
    except web.HTTPException as exc:
        logger.warning("API handler %s raised HTTPException: %s", handler_name, exc)
        if callable(error_value):
            payload = error_value(exc)
        elif error_value is not None:
            payload = error_value
        else:
            message = exc.text or exc.reason or str(exc)
            payload = {error_key: f"Server error: {message}"}
        return web.json_response(payload, status=exc.status)
    except Exception as exc:
        logger.exception("API handler %s failed", handler_name)
        if callable(error_value):
            payload = error_value(exc)
        elif error_value is not None:
            payload = error_value
        else:
            payload = {error_key: f"Server error: {exc}"}
        return web.json_response(payload, status=500)

async def handle_index(request):
    return web.Response(text=DASHBOARD_HTML, content_type="text/html")


async def handle_status(request):
    async def _action():
        manager = request.app["manager"]
        return web.json_response(manager.to_dict())

    return await _json_api("handle_status", _action, error_value=lambda exc: {"error": f"Server error: {exc}"})


async def handle_add_account(request):
    async def _action():
        data = await request.json()
        apple_id = data.get("apple_id", "").strip()
        password = data.get("password", "")
        domain = data.get("domain", "cn")

        if not apple_id or not password:
            return web.json_response({"result": "Apple ID and password required"})

        manager = request.app["manager"]
        result = await manager.add_account(apple_id, password, domain)
        return web.json_response({"result": result})

    return await _json_api("handle_add_account", _action)


async def handle_verify_2fa(request):
    async def _action():
        apple_id = request.match_info["account"]
        data = await request.json()
        code = data.get("code", "").strip()

        if not code:
            return web.json_response({"result": "Code required"})

        manager = request.app["manager"]
        result = await manager.verify_2fa(apple_id, code)
        return web.json_response({"result": result})

    return await _json_api("handle_verify_2fa", _action)


async def handle_remove(request):
    async def _action():
        apple_id = request.match_info["account"]
        manager = request.app["manager"]
        ok = await manager.remove_account(apple_id)
        return web.json_response({"ok": ok})

    return await _json_api("handle_remove", _action, error_value=lambda exc: {"ok": False, "error": f"Server error: {exc}"})


async def handle_start(request):
    async def _action():
        apple_id = request.match_info["account"]
        data = await request.json()
        count = int(data.get("count", 5))
        interval = int(data.get("interval", 45))
        manager = request.app["manager"]
        result = await manager.start_account(apple_id, count, interval)
        return web.json_response({"result": result})

    return await _json_api("handle_start", _action)


async def handle_stop(request):
    async def _action():
        apple_id = request.match_info["account"]
        manager = request.app["manager"]
        ok = await manager.stop_account(apple_id)
        return web.json_response({"ok": ok})

    return await _json_api("handle_stop", _action, error_value=lambda exc: {"ok": False, "error": f"Server error: {exc}"})


async def handle_resume(request):
    async def _action():
        apple_id = request.match_info["account"]
        manager = request.app["manager"]
        result = await manager.resume_account(apple_id)
        return web.json_response({"result": result})

    return await _json_api("handle_resume", _action)


async def start_server(manager, port: int):
    app = web.Application()
    app["manager"] = manager
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/status", handle_status)
    app.router.add_post("/api/accounts/add", handle_add_account)
    app.router.add_post("/api/accounts/{account}/verify-2fa", handle_verify_2fa)
    app.router.add_post("/api/accounts/{account}/remove", handle_remove)
    app.router.add_post("/api/accounts/{account}/start", handle_start)
    app.router.add_post("/api/accounts/{account}/stop", handle_stop)
    app.router.add_post("/api/accounts/{account}/resume", handle_resume)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    return runner
