"""
Web dashboard for multi-account HideMyEmail generation.
Each account has individual start/stop/resume controls.
"""

from aiohttp import web


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
            margin-bottom:1rem;padding-bottom:.75rem;border-bottom:1px solid var(--border)}
        .header h1{font-size:1.2rem;font-weight:700;
            background:linear-gradient(135deg,#e2e8f0,#a78bfa);
            -webkit-background-clip:text;-webkit-text-fill-color:transparent}
        .hdr-btns{display:flex;gap:.4rem;align-items:center}

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
        .cb.start{background:rgba(34,197,94,.1);border-color:rgba(34,197,94,.3);color:var(--ok)}
        .cb.start:hover{background:rgba(34,197,94,.2)}
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

<script>
const C=['#6366f1','#8b5cf6','#06b6d4','#10b981','#f59e0b','#ef4444','#ec4899','#14b8a6'];
const SL={idle:'Idle',generating:'Generating',short_cooldown:'Cooldown',
    long_cooldown:'Long Cooldown',rotating:'Rotating',done:'Done',
    error:'Error',stopped:'Stopped'};
const RUNNING=['generating','short_cooldown','long_cooldown','rotating'];

let S={accounts:[],total_target:0,total_completed:0};
let init=false, openE={};

function mk(a,i){
    const c=C[i%C.length], d=document.createElement('div');
    d.className='acct'; d.id='a'+i; d.style.borderLeftColor=c;
    d.innerHTML=`
    <div class="acct-body">
        <div class="acct-r1">
            <span class="acct-name" style="color:${c}">📧 ${a.account}</span>
            <div class="acct-ctrl">
                <input type="number" class="cnt-input" id="ci${i}" value="5" min="1" max="9999" placeholder="#">
                <button class="cb start" id="go${i}" onclick="goA(${i})">▶ Start</button>
                <button class="cb stop" id="sp${i}" onclick="spA(${i})" style="display:none">⏹ Stop</button>
                <button class="cb resume" id="rs${i}" onclick="rsA(${i})" style="display:none">▶ Resume</button>
                <button class="cb start mini" id="rt${i}" onclick="goA(${i})" style="display:none" title="Restart from scratch">↺</button>
            </div>
            <span class="badge"><span class="dot" id="d${i}"></span> <span id="s${i}">Idle</span></span>
            <span class="acct-fp" id="f${i}">—</span>
        </div>
        <div class="acct-bars" id="bars${i}" style="display:none">
            <div class="bg">
                <span class="bl">Total</span>
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

function up(a,i){
    // Status
    const dot=gid('d'+i); if(dot) dot.className='dot '+a.status;
    st('s'+i, SL[a.status]||a.status);

    // Buttons
    const run=RUNNING.includes(a.status);
    const stopped=a.status==='stopped';
    const idle=['idle','done','error'].includes(a.status);
    const canResume=stopped && a.completed<a.target;

    sh('go'+i, idle);           // Start when idle/done/error
    sh('sp'+i, run);            // Stop when running
    sh('rs'+i, canResume);      // Resume when stopped
    sh('rt'+i, stopped);        // Restart (mini) when stopped

    const ci=gid('ci'+i);
    if(ci) ci.disabled=run;
    // Sync input with target when running
    if(run && a.target>0 && ci) ci.value=a.target;

    // Show bars/footer only after started
    const started=a.target>0;
    sh('bars'+i, started);
    sh('ft'+i, started);

    // Fingerprint
    st('f'+i, a.fingerprint||'—');

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
                return `<div class="ei"><span class="eix">${n}.</span>${e}</div>`;
            }).join('');
        }
    }
}

// Helpers
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

// API calls
async function goA(i){
    const a=S.accounts[i], c=parseInt(gid('ci'+i).value);
    if(!c||c<1){gid('ci'+i).focus();return;}
    await fetch('/api/accounts/'+encodeURIComponent(a.account)+'/start',
        {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({count:c})});
    poll();
}
async function spA(i){
    const a=S.accounts[i];
    await fetch('/api/accounts/'+encodeURIComponent(a.account)+'/stop',{method:'POST'});
    poll();
}
async function rsA(i){
    const a=S.accounts[i];
    await fetch('/api/accounts/'+encodeURIComponent(a.account)+'/resume',{method:'POST'});
    poll();
}
function cpA(i){
    const a=S.accounts[i];
    if(!a||!a.emails||!a.emails.length)return;
    navigator.clipboard.writeText(a.emails.join('\n')).then(()=>{
        const b=gid('cp'+i);b.textContent='✓';b.classList.add('ok');
        setTimeout(()=>{b.textContent='copy';b.classList.remove('ok')},1500);
    });
}
function copyAll(){
    const all=S.accounts.flatMap(a=>a.emails||[]);
    if(!all.length)return;
    navigator.clipboard.writeText(all.join('\n')).then(()=>{
        const b=gid('cpa');b.textContent='Copied!';b.classList.add('ok');
        setTimeout(()=>{b.textContent='Copy All';b.classList.remove('ok')},2000);
    });
}
async function startAll(){
    for(let i=0;i<S.accounts.length;i++){
        const a=S.accounts[i];
        if(['idle','done','error'].includes(a.status)){
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

// Polling
async function poll(){
    try{
        const r=await fetch('/api/status'); S=await r.json();
        if(!init&&S.accounts.length>0){
            const c=gid('ac'); c.innerHTML='';
            S.accounts.forEach((a,i)=>c.appendChild(mk(a,i)));
            init=true;
        }
        // Summary
        const p=S.total_target>0?(S.total_completed/S.total_target*100):0;
        st('sn', S.total_completed+' / '+S.total_target);
        sw('sb', p);
        const ac=S.accounts.length;
        const g=S.accounts.filter(a=>RUNNING.includes(a.status)).length;
        const cl=S.accounts.filter(a=>a.status==='long_cooldown').length;
        const dn=S.accounts.filter(a=>a.status==='done').length;
        const sp=S.accounts.filter(a=>a.status==='stopped').length;
        let ps=[]; if(g)ps.push(g+' active'); if(cl)ps.push(cl+' cooling');
        if(dn)ps.push(dn+' done'); if(sp)ps.push(sp+' stopped');
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


async def handle_index(request):
    return web.Response(text=DASHBOARD_HTML, content_type="text/html")


async def handle_status(request):
    manager = request.app["manager"]
    return web.json_response(manager.to_dict())


async def handle_start(request):
    account = request.match_info["account"]
    data = await request.json()
    count = int(data.get("count", 5))
    manager = request.app["manager"]
    ok = await manager.start_account(account, count)
    return web.json_response({"ok": ok})


async def handle_stop(request):
    account = request.match_info["account"]
    manager = request.app["manager"]
    ok = await manager.stop_account(account)
    return web.json_response({"ok": ok})


async def handle_resume(request):
    account = request.match_info["account"]
    manager = request.app["manager"]
    ok = await manager.resume_account(account)
    return web.json_response({"ok": ok})


async def start_server(manager, port: int):
    app = web.Application()
    app["manager"] = manager
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/status", handle_status)
    app.router.add_post("/api/accounts/{account}/start", handle_start)
    app.router.add_post("/api/accounts/{account}/stop", handle_stop)
    app.router.add_post("/api/accounts/{account}/resume", handle_resume)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    return runner
