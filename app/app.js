const $ = (s) => document.querySelector(s)
const canvas = $('#galaxy')
const ctx = canvas.getContext('2d', { alpha: false })
const search = $('#search')
const clusterBar = $('#clusters')
const inspector = $('#inspector')
const inspectorBody = $('#inspectorBody')
const tooltip = $('#tooltip')
const timeline = $('#timeline')
const playBtn = $('#play')

let data, items, clusters, idMap
let activeCluster = null, query = '', cutoff = 100, playing = false
let selected = null, hovered = null
let yaw = -0.32, pitch = 0.18, distance = 255
let target = {x:0,y:0,z:0}, targetGoal = {x:0,y:0,z:0}
let dragging = false, dragX = 0, dragY = 0, moved = 0
let width = 0, height = 0, dpr = 1, visibleCount = 0
let bounds = {min:0,max:1}, lastTime = performance.now()
let screenX, screenY, screenZ, vis
const stars = Array.from({length:420}, () => ({x:(Math.random()-.5)*700,y:(Math.random()-.5)*500,z:(Math.random()-.5)*700,r:Math.random()*1.2+.2}))
const TAU = Math.PI*2

function colorFor(cluster, alpha=1, light=62){
  const h=(cluster*222.492)%360
  return `hsla(${h} 72% ${light}% / ${alpha})`
}
function fmt(n){ return new Intl.NumberFormat().format(n) }
function safe(s){ return String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c])) }
function dateLabel(v){ if(!v)return'unknown'; const d=new Date(v); return isNaN(d)?v:d.toLocaleDateString(undefined,{year:'numeric',month:'short',day:'numeric'}) }
function year(v){ const d=new Date(v); return isNaN(d)?'':String(d.getFullYear()) }
function cutoffTs(){ return bounds.min+(bounds.max-bounds.min)*(cutoff/100) }

function resize(){
  dpr=Math.min(devicePixelRatio||1,2); width=innerWidth; height=innerHeight
  canvas.width=Math.round(width*dpr); canvas.height=Math.round(height*dpr); canvas.style.width=width+'px';canvas.style.height=height+'px';ctx.setTransform(dpr,0,0,dpr,0,0)
}
addEventListener('resize',resize); resize()

function project(x,y,z){
  x-=target.x; y-=target.y; z-=target.z
  const cy=Math.cos(yaw), sy=Math.sin(yaw), cp=Math.cos(pitch), sp=Math.sin(pitch)
  const x1=cy*x-sy*z, z1=sy*x+cy*z
  const y2=cp*y-sp*z1, z2=sp*y+cp*z1
  const dz=z2+distance
  const focal=Math.min(width,height)*.92
  return {x:width*.5+x1*focal/dz,y:height*.51-y2*focal/dz,z:dz,scale:focal/dz}
}

function recomputeVisibility(){
  if(!data)return
  const q=query.trim().toLowerCase(), cts=cutoffTs(); visibleCount=0
  for(let i=0;i<items.length;i++){
    const it=items[i]; let ok=true
    if(activeCluster!==null&&it.cluster!==activeCluster)ok=false
    const t=it._ts
    if(Number.isFinite(t)&&t>cts)ok=false
    if(q&&!(it._hay.includes(q)))ok=false
    vis[i]=ok?1:0; if(ok)visibleCount++
  }
  $('#countText').textContent=`${fmt(visibleCount)} / ${fmt(data.meta.videoCount)} videos`
  $('#visibleCount').textContent=`${fmt(visibleCount)} visible`
  updateClusterButtons()
}

function renderClusters(){
  clusterBar.innerHTML=''
  const all=document.createElement('button');all.className='cluster-chip active';all.textContent='All';all.dataset.id='all';all.onclick=()=>{activeCluster=null;recomputeVisibility()};clusterBar.append(all)
  ;[...clusters].sort((a,b)=>b.count-a.count).forEach(c=>{
    const b=document.createElement('button');b.className='cluster-chip';b.dataset.id=String(c.id)
    b.innerHTML=`<i style="--h:${(c.id*222.492)%360}"></i>${safe(c.label)}<span>${c.count}</span>`
    b.onclick=()=>{activeCluster=activeCluster===c.id?null:c.id;recomputeVisibility()};clusterBar.append(b)
  })
}
function updateClusterButtons(){ clusterBar.querySelectorAll('button').forEach(b=>b.classList.toggle('active',(b.dataset.id==='all'&&activeCluster===null)||Number(b.dataset.id)===activeCluster)) }

function drawBackground(){
  ctx.fillStyle='#060609';ctx.fillRect(0,0,width,height)
  const g=ctx.createRadialGradient(width*.5,height*.43,0,width*.5,height*.43,Math.max(width,height)*.65);g.addColorStop(0,'#12121b');g.addColorStop(.48,'#08080c');g.addColorStop(1,'#030305');ctx.fillStyle=g;ctx.fillRect(0,0,width,height)
  ctx.fillStyle='rgba(130,140,175,.23)'
  for(const s of stars){ const p=project(s.x,s.y,s.z); if(p.z>8&&p.x>-5&&p.x<width+5&&p.y>-5&&p.y<height+5){ctx.beginPath();ctx.arc(p.x,p.y,s.r,0,TAU);ctx.fill()} }
}

function drawGalaxy(){
  const buckets=new Map(); let hoverCandidate=null
  const sx=screenX, sy=screenY, sz=screenZ
  for(let i=0;i<items.length;i++){
    const it=items[i],p=project(it.x,it.y,it.z);sx[i]=p.x;sy[i]=p.y;sz[i]=p.z
    if(p.z<8||p.x<-20||p.x>width+20||p.y<-20||p.y>height+20)continue
    const visible=vis[i]===1, sel=selected?.id===it.id
    const alpha=visible?(selected&&!sel?.32:.84):.018
    const sizeBucket=Math.min(4,Math.floor(Math.log2(it.watchCount+1)))
    const k=`${it.cluster}|${sizeBucket}|${visible?1:0}|${sel?1:0}`
    if(!buckets.has(k))buckets.set(k,[]);buckets.get(k).push(i)
  }
  for(const [key,inds] of buckets){
    const [cl,sb,v,sel]=key.split('|').map(Number); const visible=v===1
    ctx.fillStyle=sel?`rgba(255,255,255,.98)`:colorFor(cl,visible?(selected?.38:.78):.025,sel?78:62)
    ctx.shadowColor=sel?'rgba(255,255,255,.75)':colorFor(cl,visible?.42:0,62);ctx.shadowBlur=sel?17:(visible?7:0)
    ctx.beginPath();const base=1.25+sb*.55+(sel?3.2:0)
    for(const i of inds){const r=base*Math.max(.72,Math.min(1.6,260/screenZ[i]));ctx.moveTo(screenX[i]+r,screenY[i]);ctx.arc(screenX[i],screenY[i],r,0,TAU)}ctx.fill()
  }
  ctx.shadowBlur=0
}

function drawEdges(){
  if(!selected)return;const a=idMap.get(selected.id);if(a==null)return
  ctx.strokeStyle='rgba(255,255,255,.18)';ctx.lineWidth=1;ctx.beginPath()
  for(const rid of selected.related||[]){const j=idMap.get(rid);if(j==null||screenZ[j]<8)continue;ctx.moveTo(screenX[a],screenY[a]);ctx.lineTo(screenX[j],screenY[j])}ctx.stroke()
}

function drawLabels(){
  ctx.font='600 11px ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif';ctx.textBaseline='middle'
  for(const c of clusters){
    if(activeCluster!==null&&activeCluster!==c.id)continue
    if(query){let any=false;for(let i=0;i<items.length;i++)if(vis[i]&&items[i].cluster===c.id){any=true;break}if(!any)continue}
    const p=project(c.center[0],c.center[1]+8,c.center[2]);if(p.z<15||p.x<0||p.x>width||p.y<90||p.y>height-70)continue
    const text=c.label.length>34?c.label.slice(0,32)+'…':c.label,w=ctx.measureText(text).width+20
    ctx.fillStyle='rgba(8,8,12,.68)';roundRect(ctx,p.x-w/2,p.y-13,w,26,10);ctx.fill();ctx.strokeStyle='rgba(255,255,255,.12)';ctx.stroke()
    ctx.fillStyle='rgba(255,255,255,.78)';ctx.fillText(text,p.x-w/2+10,p.y+.5)
  }
}
function roundRect(c,x,y,w,h,r){c.beginPath();c.roundRect?c.roundRect(x,y,w,h,r):(c.rect(x,y,w,h))}

function animate(now){
  const dt=Math.min(40,now-lastTime);lastTime=now
  target.x+=(targetGoal.x-target.x)*.07;target.y+=(targetGoal.y-target.y)*.07;target.z+=(targetGoal.z-target.z)*.07
  if(playing){cutoff+=dt*.008;if(cutoff>=100){cutoff=100;playing=false;playBtn.textContent='▶'}timeline.value=cutoff;updateTimeline();recomputeVisibility()}
  drawBackground();drawGalaxy();drawEdges();drawLabels();requestAnimationFrame(animate)
}

function nearestAt(x,y){
  let best=-1,bestD=12*12
  for(let i=0;i<items.length;i++){if(!vis[i]||screenZ[i]<8)continue;const dx=screenX[i]-x,dy=screenY[i]-y,d=dx*dx+dy*dy;if(d<bestD){bestD=d;best=i}}
  return best
}

canvas.addEventListener('pointerdown',e=>{dragging=true;dragX=e.clientX;dragY=e.clientY;moved=0;canvas.setPointerCapture(e.pointerId);canvas.style.cursor='grabbing'})
canvas.addEventListener('pointermove',e=>{
  if(dragging){const dx=e.clientX-dragX,dy=e.clientY-dragY;dragX=e.clientX;dragY=e.clientY;moved+=Math.abs(dx)+Math.abs(dy);yaw+=dx*.005;pitch=Math.max(-1.25,Math.min(1.25,pitch+dy*.004));tooltip.hidden=true;return}
  const i=nearestAt(e.clientX,e.clientY);hovered=i>=0?items[i]:null;canvas.style.cursor=hovered?'pointer':'grab'
  if(hovered){tooltip.hidden=false;tooltip.style.left=Math.min(width-330,e.clientX+16)+'px';tooltip.style.top=Math.min(height-100,e.clientY+16)+'px';tooltip.innerHTML=`<b>${safe(hovered.title)}</b><span>${safe(hovered.channel||hovered.clusterLabel)} · ${hovered.watchCount}×</span>`}else tooltip.hidden=true
})
canvas.addEventListener('pointerup',e=>{dragging=false;canvas.releasePointerCapture(e.pointerId);canvas.style.cursor=hovered?'pointer':'grab';if(moved<7){const i=nearestAt(e.clientX,e.clientY);selectItem(i>=0?items[i]:null)}})
canvas.addEventListener('wheel',e=>{e.preventDefault();distance=Math.max(45,Math.min(650,distance*Math.exp(e.deltaY*.0012)))},{passive:false})
canvas.addEventListener('dblclick',e=>{const i=nearestAt(e.clientX,e.clientY);if(i>=0){const it=items[i];targetGoal={x:it.x,y:it.y,z:it.z};distance=Math.max(70,distance*.58);selectItem(it)}})

function selectItem(it){selected=it;if(it){targetGoal={x:it.x,y:it.y,z:it.z};inspector.classList.add('open');renderInspector()}else{inspector.classList.remove('open');targetGoal={x:0,y:0,z:0}}}
function renderInspector(){
  const s=selected;if(!s)return
  const related=(s.related||[]).map(id=>items[idMap.get(id)]).filter(Boolean)
  inspectorBody.className='';inspectorBody.innerHTML=`<div class="eyebrow">${safe(s.clusterLabel)}</div><h2>${safe(s.title)}</h2>${s.channel?`<div class="channel">${safe(s.channel)}</div>`:''}<div class="stats-grid"><div><b>${s.watchCount}</b><span>watches</span></div><div><b>${safe(dateLabel(s.firstWatched))}</b><span>first seen</span></div><div><b>${safe(dateLabel(s.lastWatched))}</b><span>last seen</span></div></div>${s.url?`<a class="open-video" href="${safe(s.url)}" target="_blank" rel="noreferrer">Open on YouTube ↗</a>`:''}${related.length?`<div class="related"><h3>Semantic neighbors</h3>${related.map(r=>`<button data-id="${safe(r.id)}"><span>${safe(r.title)}</span><small>${safe(r.channel||'')}</small></button>`).join('')}</div>`:''}`
  inspectorBody.querySelectorAll('[data-id]').forEach(b=>b.onclick=()=>selectItem(items[idMap.get(b.dataset.id)]))
}
$('#closeInspector').onclick=()=>selectItem(null)

function updateTimeline(){const ts=cutoffTs(),d=new Date(ts);$('#timelineNow').textContent=cutoff<99.9?d.toLocaleDateString(undefined,{year:'numeric',month:'short'}):'All history'}
timeline.oninput=()=>{playing=false;playBtn.textContent='▶';cutoff=Number(timeline.value);updateTimeline();recomputeVisibility()}
playBtn.onclick=()=>{if(cutoff>=99.9){cutoff=0;timeline.value=0;recomputeVisibility()}playing=!playing;playBtn.textContent=playing?'Ⅱ':'▶'}
search.oninput=()=>{query=search.value;recomputeVisibility()}
addEventListener('keydown',e=>{if(e.key==='Escape'){selectItem(null);query='';search.value='';activeCluster=null;cutoff=100;timeline.value=100;recomputeVisibility();updateTimeline()}if(e.key==='/'&&document.activeElement!==search){e.preventDefault();search.focus()}})

async function load(){
  try{
    const r=await fetch('./data/galaxy.json',{cache:'no-store'});if(!r.ok)throw new Error(`${r.status} ${r.statusText}`);data=await r.json();items=data.items;clusters=data.clusters;idMap=new Map(items.map((x,i)=>[x.id,i]));screenX=new Float32Array(items.length);screenY=new Float32Array(items.length);screenZ=new Float32Array(items.length);vis=new Uint8Array(items.length)
    let times=[];for(const it of items){it._ts=it.lastWatched?new Date(it.lastWatched).getTime():NaN;it._hay=`${it.title} ${it.channel||''} ${it.clusterLabel}`.toLowerCase();if(Number.isFinite(it._ts))times.push(it._ts)}bounds={min:times.length?Math.min(...times):0,max:times.length?Math.max(...times):1}
    $('#timelineBounds').textContent=`${year(data.meta.minTime)} → ${year(data.meta.maxTime)}`;$('#engineMeta').textContent=`${String(data.meta.projection).toUpperCase()} · ${String(data.meta.embedder).split(':')[0]}`
    renderClusters();recomputeVisibility();updateTimeline();$('#loadState').remove();requestAnimationFrame(animate)
  }catch(e){const l=$('#loadState');l.classList.add('error');l.innerHTML=`<h1>Couldn’t load galaxy.json</h1><p>${safe(e)}</p><code>./galaxy demo && ./galaxy dev</code>`}
}
load()
