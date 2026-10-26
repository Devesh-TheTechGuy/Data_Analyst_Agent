const $ = (id) => document.getElementById(id);
const state = { chatId: null, chats: [], datasets: [], memories: [], busy: false, modal: null, editingMemory: null, thinkingOpen: localStorage.getItem('thinkingOpen') === 'true', personalKey: sessionStorage.getItem('byteApiKey')||'', keyMode: sessionStorage.getItem('byteKeyMode')||'server', serverKeyReady: false, currentUsage: null, quota: null };
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const icon = (name) => `<svg class="ui-icon" aria-hidden="true"><use href="#icon-${name}"></use></svg>`;

async function api(path, options = {}) {
  const response = await fetch(path, { credentials: 'same-origin', ...options });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
  return data;
}
function json(method, body) { return { method, headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) }; }
function toast(message) { const node = $('toast'); node.textContent = message; node.classList.remove('hidden'); clearTimeout(toast.timer); toast.timer = setTimeout(() => node.classList.add('hidden'), 3600); }
function scrollBottom() { const el = $('conversation'); el.scrollTop = el.scrollHeight; }
function closeSidebar() { $('sidebar').classList.remove('open'); $('mobile-backdrop').classList.remove('open'); }
function emptyUsage(){return {model:'gpt-4.1',input_tokens:0,output_tokens:0,cached_tokens:0,context_tokens:0,context_window:1047576,calls:0};}
function combineUsage(a,b){const x=a||emptyUsage(),y=b||emptyUsage();return {model:'gpt-4.1',input_tokens:x.input_tokens+y.input_tokens,output_tokens:x.output_tokens+y.output_tokens,cached_tokens:x.cached_tokens+y.cached_tokens,context_tokens:y.context_tokens||x.context_tokens,context_window:1047576,calls:x.calls+y.calls};}
function showUsage(usage){const u=usage||emptyUsage(), fmt=n=>Number(n||0).toLocaleString();$('usage-tokens').textContent=u.input_tokens||u.output_tokens?`${fmt(u.input_tokens)} in · ${fmt(u.output_tokens)} out`:'Tokens —';$('usage-context').textContent=u.context_tokens?`Context ${fmt(u.context_tokens)} / 1.05M`:'Context —';$('usage-cache').textContent=u.input_tokens?`Cache ${Math.round(100*u.cached_tokens/u.input_tokens)}%`:'Cache —';}
function usageFromMessages(messages){state.currentUsage=messages.filter(m=>m.role==='assistant'&&m.usage).reduce((sum,m)=>combineUsage(sum,m.usage),emptyUsage());showUsage(state.currentUsage);}
function updateKeyUI(){const personal=state.keyMode==='personal'&&!!state.personalKey;$('key-source').textContent=personal?'Your key':state.serverKeyReady?`${state.quota?.remaining??10} left`:'Add key';$('use-server-key').classList.toggle('selected',!personal);$('use-personal-key').classList.toggle('selected',personal);$('personal-key').placeholder=state.personalKey?'Key saved for this tab · enter a new key to replace':'sk-...';$('workspace-quota-note').textContent=state.serverKeyReady?`${state.quota?.remaining??10} of 10 workspace prompts left for this browser. Your own key does not use this allowance.`:'No workspace key is configured. Add your own key to chat.';}

function safeUrl(url) { const raw = String(url).replace(/&amp;/g, '&'); return /^https?:\/\//i.test(raw) || /^\/api\/charts\/[a-f0-9]+$/.test(raw) ? raw : '#'; }
function inline(text) {
  let value = esc(text);
  value = value.replace(/`([^`]+)`/g, '<code>$1</code>');
  value = value.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_, label, url) => `<img src="${esc(/^\/api\/charts\/[a-f0-9]+$/.test(url)?url:'#')}" alt="${label}">`);
  value = value.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, label, url) => `<a href="${esc(safeUrl(url))}" target="_blank" rel="noopener noreferrer">${label}</a>`);
  value = value.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>').replace(/\*([^*]+)\*/g, '<em>$1</em>');
  return value;
}
function markdown(source) {
  const lines = String(source || '').replace(/\r/g,'').split('\n');
  let out = '', list = '', code = false, codeLines = [];
  const endList = () => { if (list) { out += `</${list}>`; list = ''; } };
  for (let i=0;i<lines.length;i++) { const line=lines[i];
    if (line.startsWith('```')) { endList(); if (code) { out += `<pre><code>${esc(codeLines.join('\n'))}</code></pre>`; codeLines=[]; } code=!code; continue; }
    if (code) { codeLines.push(line); continue; }
    if (!line.trim()) { endList(); continue; }
    const separator=lines[i+1]?.trim();
    if (line.includes('|') && separator?.includes('-') && /^[|:\-\s]+$/.test(separator)) {
      endList();
      const cells=row=>row.trim().replace(/^\|/,'').replace(/\|$/,'').split('|').map(x=>inline(x.trim()));
      out+='<table><thead><tr>'+cells(line).map(x=>`<th>${x}</th>`).join('')+'</tr></thead><tbody>';
      i++;
      while (i+1<lines.length && lines[i+1].includes('|') && lines[i+1].trim()) {i++;out+='<tr>'+cells(lines[i]).map(x=>`<td>${x}</td>`).join('')+'</tr>';}
      out+='</tbody></table>';
      continue;
    }
    const heading = line.match(/^(#{1,3})\s+(.+)/);
    if (heading) { endList(); const n = heading[1].length; out += `<h${n}>${inline(heading[2])}</h${n}>`; continue; }
    const bullet = line.match(/^\s*[-*]\s+(.+)/), numbered = line.match(/^\s*\d+\.\s+(.+)/);
    if (bullet || numbered) { const type=bullet?'ul':'ol'; if (list!==type) { endList(); out+=`<${type}>`; list=type; } out+=`<li>${inline((bullet||numbered)[1])}</li>`; continue; }
    endList(); out += `<p>${inline(line)}</p>`;
  }
  endList(); if (codeLines.length) out += `<pre><code>${esc(codeLines.join('\n'))}</code></pre>`;
  return out;
}

function renderChats() {
  const query = $('chat-search').value.trim().toLowerCase();
  $('chat-list').innerHTML = state.chats.filter(c => c.title.toLowerCase().includes(query)).map(c => `<div class="chat-item ${c.id===state.chatId?'active':''}"><button class="chat-open" data-id="${esc(c.id)}" aria-label="Open ${esc(c.title)}" ${c.id===state.chatId?'aria-current="page"':''}><span class="chat-icon">${icon('chart')}</span><span class="chat-name">${esc(c.title)}</span></button><button class="chat-more" data-more="${esc(c.id)}" aria-label="Options for ${esc(c.title)}">•••</button></div>`).join('') || '<div class="empty-note">No conversations yet</div>';
  $('chat-list').querySelectorAll('.chat-open').forEach(el => el.addEventListener('click', () => openChat(el.dataset.id)));
  $('chat-list').querySelectorAll('.chat-more').forEach(el => el.addEventListener('click', e => { e.stopPropagation(); chatMenu(el.dataset.more, el); }));
}
function actionDialog({title,description,confirmText,inputValue,destructive=false}) {
  const dialog=$('action-dialog'), input=$('action-input'), hasInput=inputValue!==undefined;
  $('action-title').textContent=title;
  $('action-description').textContent=description;
  $('action-confirm').textContent=confirmText;
  $('action-confirm').classList.toggle('destructive',destructive);
  input.classList.toggle('hidden',!hasInput);
  input.required=hasInput;
  input.value=hasInput?inputValue:'';
  dialog.returnValue='';
  return new Promise(resolve=>{
    dialog.addEventListener('close',()=>resolve(dialog.returnValue==='confirm'?(hasInput?input.value.trim()||null:true):null),{once:true});
    dialog.showModal();
    if(hasInput){input.focus();input.select();}
    else $('action-confirm').focus();
  });
}
function chatMenu(id, anchor) {
  document.querySelector('.context-menu')?.remove();
  const menu = document.createElement('div'); menu.className = 'context-menu glass';
  menu.innerHTML = '<button data-action="rename">✎ Rename</button><button data-action="delete">⌫ Delete</button>';
  const rect = anchor.getBoundingClientRect(); menu.style.left = `${Math.max(8,Math.min(rect.right-130, innerWidth-145))}px`; menu.style.top = `${rect.bottom+5}px`;
  document.body.append(menu);
  menu.addEventListener('click', async e => {
    const action=e.target.dataset.action; menu.remove(); if (!action) return;
    if (action==='rename') {
      const chat=state.chats.find(c=>c.id===id), title=await actionDialog({title:'Rename chat',description:'Choose a name you can find later.',confirmText:'Save name',inputValue:chat.title});
      if (title?.trim()) { try { await api(`/api/chats/${id}`, json('PATCH',{title:title.trim()})); await refreshChats(); if (id===state.chatId) $('current-title').textContent=title.trim(); } catch(err){toast(err.message);} }
    } else if (await actionDialog({title:'Delete chat?',description:'This will remove the conversation and its messages.',confirmText:'Delete chat',destructive:true})) {
      try { await api(`/api/chats/${id}`,{method:'DELETE'}); if(id===state.chatId) newChat(); await refreshChats(); toast('Conversation deleted'); } catch(err){toast(err.message);}
    }
  });
  setTimeout(()=>document.addEventListener('click',e=>{if(!menu.contains(e.target))menu.remove();},{once:true}),0);
}
async function refreshChats() { state.chats = await api('/api/chats'); renderChats(); }
function newChat() { state.chatId=null; $('current-title').textContent='New analysis'; $('conversation').innerHTML=welcome(); state.currentUsage=emptyUsage();showUsage(state.currentUsage);renderChats(); closeSidebar(); $('prompt').focus(); }
async function openChat(id) {
  try { const chat=await api(`/api/chats/${id}`); state.chatId=id; $('current-title').textContent=chat.title; $('conversation').innerHTML='';
    if (!chat.messages.length) $('conversation').innerHTML=welcome(); else chat.messages.forEach(renderMessage);
    usageFromMessages(chat.messages);
    renderChats(); closeSidebar(); scrollBottom();
  } catch(err) { toast(err.message); }
}
function welcome() {
  const first=state.datasets[0];
  const chips=state.datasets.slice(0,3).map(d=>`<span class="dataset-chip" title="${esc(d.name)}">${esc(d.filename)} · ${Number(d.rows).toLocaleString()} rows</span>`).join('');
  const prompts=first?[
    {icon:'database',title:'Get an overview',detail:'Columns, rows, and missing values',prompt:`Inspect ${first.name} and give me a concise overview`},
    {icon:'shield',title:'Check data quality',detail:'Find gaps and inconsistencies',prompt:`Check ${first.name} for missing values and data quality issues`},
    {icon:'chart',title:'Find a pattern',detail:'Explore useful relationships',prompt:`Find an interesting pattern in ${first.name} and support it with calculations`},
    {icon:'spark',title:'Make a chart',detail:'See the shape of the data',prompt:`Create a useful chart for ${first.name} and explain what it shows`}
  ]:[];
  const cards=prompts.map(item=>`<button class="suggestion" data-prompt="${esc(item.prompt)}"><span class="suggest-icon">${icon(item.icon)}</span><span><strong>${item.title}</strong><small>${item.detail}</small></span></button>`).join('');
  return `<div class="welcome"><div class="welcome-mark">${icon('logo')}</div><h1>Ask your data <em>anything.</em></h1><p>Upload a file, ask a question, and follow the analysis behind the answer.</p>${first?`<div class="suggestions">${cards}</div><div class="loaded-strip">IN YOUR WORKSPACE ${chips}</div>`:`<button class="welcome-upload" data-upload="true">${icon('plus')} Upload your first dataset</button><div class="loaded-strip">CSV · EXCEL · JSON · PARQUET AND MORE</div>`}</div>`;
}
function renderMessage(message) {
  if ($('conversation').querySelector('.welcome')) $('conversation').innerHTML='';
  const article=document.createElement('article'); article.className=`message ${message.role}`; article.dataset.id=message.id||'';
  if (message.role==='user') article.innerHTML=`<div class="user-bubble">${esc(message.content)}</div>`;
  else {
    article.innerHTML=`<div class="assistant-heading"><span class="assistant-symbol">${icon('logo')}</span><span>BYTE into Data</span></div><div class="thinking-slot"></div><div class="answer">${markdown(message.content)}</div><div class="message-actions"><button class="copy-answer">${icon('copy')} Copy answer</button></div>`;
    renderThinking(article, message.activity||[]);
    article.querySelector('.copy-answer').addEventListener('click',async()=>{await navigator.clipboard.writeText(message.content);toast('Copied answer');});
  }
  $('conversation').append(article); return article;
}
function renderThinking(article, activity) {
  const slot=article.querySelector('.thinking-slot'); if (!slot) return;
  if (!activity.length) {slot.innerHTML='';return;}
  const describe=step=>step.tool==='sql_query'?step.arguments?.query:(step.arguments?.name||step.arguments?.expression||'');
  slot.innerHTML=`<details class="thinking" ${state.thinkingOpen?'open':''}><summary>${icon('spark')} Thinking <span>· ${activity.length} step${activity.length===1?'':'s'}</span></summary><div class="thinking-list">${activity.map(step=>`<div class="thinking-step ${step.error?'error':''}"><span class="thinking-dot">${icon('spark')}</span><div><strong>${esc(step.label)}</strong>${describe(step)?`<span class="step-arguments">${esc(describe(step))}</span>`:''}<span>${esc(step.result||'')}</span></div></div>`).join('')}</div></details>`;
  slot.querySelector('details').addEventListener('toggle',e=>{state.thinkingOpen=e.target.open;localStorage.setItem('thinkingOpen',String(state.thinkingOpen));updateThinkingToggle();});
}
function updateThinkingToggle(){$('thinking-toggle').classList.toggle('active',state.thinkingOpen);$('thinking-toggle').setAttribute('aria-pressed',String(state.thinkingOpen));}
function setBusy(value){state.busy=value;$('send').disabled=value;$('prompt').disabled=value;$('upload-trigger').disabled=value;$('send').innerHTML=value?'···':icon('arrow');}

async function sendMessage(text) {
  const question=text.trim(); if(!question||state.busy)return;
  setBusy(true); $('prompt').value=''; resizePrompt();
  try {
    if(!state.chatId){const chat=await api('/api/chats',json('POST',{title:'New analysis'}));state.chatId=chat.id;}
    renderMessage({role:'user',content:question});
    const pending=renderMessage({role:'assistant',content:'',activity:[]});
    pending.querySelector('.answer').innerHTML='<span class="loading-dots"><i></i><i></i><i></i></span>';
    scrollBottom(); let activity=[], gotFinal=false;const baseUsage=state.currentUsage||emptyUsage();
    const options=json('POST',{content:question});if(state.keyMode==='personal'&&state.personalKey)options.headers['X-OpenAI-API-Key']=state.personalKey;
    const response=await fetch(`/api/chats/${state.chatId}/messages`,{...options,credentials:'same-origin'});
    if(!response.ok){const data=await response.json().catch(()=>({}));if(response.status===429){state.quota={limit:10,used:10,remaining:0};updateKeyUI();}throw new Error(data.detail||'Could not send message');}
    const remaining=response.headers.get('X-Workspace-Prompts-Remaining');if(remaining!==null){state.quota={limit:10,used:10-Number(remaining),remaining:Number(remaining)};updateKeyUI();}
    const reader=response.body.getReader(), decoder=new TextDecoder(); let buffer='';
    const handle=block=>{const lines=block.split('\n');const kind=lines.find(x=>x.startsWith('event: '))?.slice(7);const raw=lines.filter(x=>x.startsWith('data: ')).map(x=>x.slice(6)).join('\n');if(!kind||!raw)return;
      const data=JSON.parse(raw);
      if(kind==='activity'){activity.push(data);renderThinking(pending,activity);scrollBottom();}
      if(kind==='usage'){state.currentUsage=combineUsage(baseUsage,data);showUsage(state.currentUsage);}
      if(kind==='final'){gotFinal=true;pending.dataset.id=data.id;pending.querySelector('.answer').innerHTML=markdown(data.content);renderThinking(pending,data.activity||activity);pending.querySelector('.copy-answer').onclick=async()=>{await navigator.clipboard.writeText(data.content);toast('Copied answer');};scrollBottom();}
      if(kind==='memory'){toast(`${data.count} useful ${data.count===1?'memory':'memories'} saved`);refreshMemories();}
      if(kind==='error'){pending.querySelector('.answer').innerHTML=`<div class="error-banner">${esc(data.message)}</div>`;}
    };
    while(true){const {value,done}=await reader.read();if(done)break;buffer+=decoder.decode(value,{stream:true}).replace(/\r\n/g,'\n');let index;while((index=buffer.indexOf('\n\n'))>=0){handle(buffer.slice(0,index));buffer=buffer.slice(index+2);}}
    if(buffer.trim())handle(buffer);
    if(!gotFinal && pending.querySelector('.loading-dots'))pending.querySelector('.answer').innerHTML='<div class="error-banner">The response ended before an answer arrived. Try again.</div>';
    await refreshChats(); $('current-title').textContent=state.chats.find(c=>c.id===state.chatId)?.title||'Analysis';
    const stored=await api(`/api/chats/${state.chatId}`);usageFromMessages(stored.messages);
  } catch(err){toast(err.message);const pending=$('conversation').querySelector('.message.assistant:last-child');if(pending)pending.querySelector('.answer').innerHTML=`<div class="error-banner">${esc(err.message)}</div>`;}
  finally{setBusy(false);$('prompt').focus();}
}
function resizePrompt(){const el=$('prompt');el.style.height='auto';el.style.height=Math.min(el.scrollHeight,150)+'px';}

async function refreshDatasets() {
  try {const data=await api('/api/datasets');state.datasets=data.datasets;$('dataset-count').textContent=state.datasets.length;$('top-dataset-count').textContent=`${state.datasets.length} dataset${state.datasets.length===1?'':'s'}`;$('dataset-summary').textContent=`${state.datasets.length} dataset${state.datasets.length===1?'':'s'}`;
    $('dataset-list').innerHTML=state.datasets.map(d=>`<div class="list-card"><span class="card-symbol">${icon('database')}</span><div class="card-content"><strong>${esc(d.filename)}</strong><p>Use <code>${esc(d.name)}</code> in a question</p><small>${Number(d.rows).toLocaleString()} rows · ${d.columns} columns · ${d.source==='folder'?'Data folder':'Uploaded'}</small></div>${d.source==='upload'?`<div class="card-actions"><button data-delete-dataset="${esc(d.id.slice(7))}" title="Remove dataset">✕</button></div>`:''}</div>`).join('')||'<div class="empty-note">No datasets yet. Upload one or add a file to data/.</div>';
    $('dataset-list').querySelectorAll('[data-delete-dataset]').forEach(button=>button.addEventListener('click',async()=>{if(!await actionDialog({title:'Remove dataset?',description:'This uploaded file will no longer be available in the workspace.',confirmText:'Remove dataset',destructive:true}))return;try{await api(`/api/datasets/${button.dataset.deleteDataset}`,{method:'DELETE'});await refreshDatasets();toast('Dataset removed');}catch(err){toast(err.message);}}));
    if(data.errors && Object.keys(data.errors).length)toast('Some files in data/ could not be loaded. Check their format.');
    if(!state.chatId)$('conversation').innerHTML=welcome();
  }catch(err){toast(err.message);}
}
async function pollDatasets() {
  if (document.hidden || state.modal || state.busy || !$('login-screen').classList.contains('hidden')) return;
  try {
    const data = await api('/api/datasets');
    const signature = items => items.map(d => `${d.id}:${d.name}:${d.rows}:${d.columns}`).join('|');
    if (signature(data.datasets) !== signature(state.datasets)) await refreshDatasets();
  } catch { /* The next manual refresh or poll can retry. */ }
}
setInterval(pollDatasets, 15000);
async function uploadFile(file) {
  if(!file)return; $('attachment-hint').classList.remove('hidden');$('attachment-hint').textContent=`Uploading ${file.name}...`;
  try{let data;
    if(file.size > 3 * 1024 * 1024){
      const session=await api('/api/uploads/start',json('POST',{filename:file.name,size_bytes:file.size}));
      const chunkSize=3*1024*1024;let seq=0;
      for(let offset=0;offset<file.size;offset+=chunkSize){
        const chunk=file.slice(offset,offset+chunkSize);
        const response=await fetch(`/api/uploads/${session.id}/chunks/${seq++}`,{method:'PUT',body:chunk,credentials:'same-origin'});
        if(!response.ok){const problem=await response.json().catch(()=>({}));throw new Error(problem.detail||'Upload failed');}
        $('attachment-hint').textContent=`Uploading ${file.name} · ${Math.min(100,Math.round((offset+chunk.size)/file.size*100))}%`;
      }
      data=await api(`/api/uploads/${session.id}/complete`,{method:'POST'});
    } else {const form=new FormData();form.append('file',file);data=await api('/api/datasets',{method:'POST',body:form});}
    await refreshDatasets();toast(`Loaded ${data.name} · ${Number(data.rows).toLocaleString()} rows`);$('attachment-hint').textContent=`▤ ${data.name} is ready. Ask a question about it.`;setTimeout(()=>$('attachment-hint').classList.add('hidden'),6000);}
  catch(err){$('attachment-hint').classList.add('hidden');toast(err.message);}
  finally{$('file-input').value='';}
}

async function refreshMemories(){try{state.memories=await api('/api/memories');$('memory-count').textContent=state.memories.length;$('memory-summary').textContent=`${state.memories.length} saved ${state.memories.length===1?'memory':'memories'}`;renderMemories();}catch(err){toast(err.message);}}
function renderMemories(){
  $('memory-list').innerHTML=state.memories.map(m=>`<div class="list-card"><span class="card-symbol">✧</span><div class="card-content"><strong>${esc(m.key)}</strong><p>${esc(m.value)}</p><small>${esc(m.category)}${m.scope?' · '+esc(m.scope):''}</small></div><div class="card-actions"><button data-edit="${esc(m.id)}" title="Edit memory">✎</button><button data-delete="${esc(m.id)}" title="Forget memory">✕</button></div></div>`).join('')||'<div class="empty-note">No memories yet. The analyst will save useful details from your conversations.</div>';
  $('memory-list').querySelectorAll('[data-edit]').forEach(b=>b.onclick=()=>openMemoryEditor(state.memories.find(m=>m.id===b.dataset.edit)));
  $('memory-list').querySelectorAll('[data-delete]').forEach(b=>b.onclick=async()=>{if(!await actionDialog({title:'Forget this memory?',description:'The analyst will stop using this saved detail.',confirmText:'Forget memory',destructive:true}))return;try{await api(`/api/memories/${b.dataset.delete}`,{method:'DELETE'});await refreshMemories();toast('Memory forgotten');}catch(err){toast(err.message);}});
}
function openModal(id){const returnFocus=state.modalReturnFocus||document.activeElement;closeModal(false);state.modalReturnFocus=returnFocus;state.modal=id;$('modal-backdrop').classList.remove('hidden');$(id).classList.remove('hidden');if(id==='memory-modal')refreshMemories();if(id==='datasets-modal')refreshDatasets();if(id==='key-modal')updateKeyUI();(id==='memory-editor'?$('memory-key'):$(id).querySelector('button'))?.focus();}
function closeModal(restoreFocus=true){['memory-modal','datasets-modal','memory-editor','key-modal'].forEach(id=>$(id).classList.add('hidden'));$('modal-backdrop').classList.add('hidden');state.modal=null;if(restoreFocus){state.modalReturnFocus?.focus();state.modalReturnFocus=null;}}
function openMemoryEditor(item=null){state.editingMemory=item?.id||null;$('editor-heading').textContent=item?'Edit memory':'Add memory';$('memory-category').value=item?.category||'definition';$('memory-key').value=item?.key||'';$('memory-value').value=item?.value||'';$('memory-scope').innerHTML='<option value="">All datasets</option>'+state.datasets.map(d=>`<option value="${esc(d.name)}">${esc(d.name)}</option>`).join('');$('memory-scope').value=item?.scope||'';openModal('memory-editor');}

async function initialize(){
  try{const status=await api('/api/status');if(!status.ready){$('login-screen').classList.remove('hidden');$('login-screen').querySelector('p').textContent=`Server setup required: ${status.missing.join(', ')}`;return;}
    if(!status.authenticated){$('login-screen').classList.remove('hidden');return;}
    $('login-screen').classList.add('hidden');state.serverKeyReady=status.chat_ready;state.quota=status.workspace_quota;updateKeyUI();await Promise.all([refreshChats(),refreshDatasets(),refreshMemories()]);newChat();
    if(!status.chat_ready&&!state.personalKey)toast('Add your OpenAI API key in API key settings to enable chat.');
  }catch(err){toast(err.message);}
}

$('composer').addEventListener('submit',e=>{e.preventDefault();sendMessage($('prompt').value);});
$('prompt').addEventListener('input',resizePrompt);
$('prompt').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMessage(e.target.value);}});
$('new-chat').onclick=newChat;$('chat-search').oninput=renderChats;
$('upload-trigger').onclick=()=>$('file-input').click();$('modal-upload').onclick=()=>$('file-input').click();$('file-input').onchange=e=>uploadFile(e.target.files[0]);
const dropSurface=document.querySelector('.main');
let dragDepth=0;
dropSurface.addEventListener('dragenter',e=>{if(!e.dataTransfer?.types?.includes('Files'))return;e.preventDefault();dragDepth++;dropSurface.classList.add('file-drag');});
dropSurface.addEventListener('dragover',e=>{if(e.dataTransfer?.types?.includes('Files'))e.preventDefault();});
dropSurface.addEventListener('dragleave',e=>{if(!e.dataTransfer?.types?.includes('Files'))return;dragDepth=Math.max(0,dragDepth-1);if(!dragDepth)dropSurface.classList.remove('file-drag');});
dropSurface.addEventListener('drop',e=>{if(!e.dataTransfer?.files?.length)return;e.preventDefault();dragDepth=0;dropSurface.classList.remove('file-drag');uploadFile(e.dataTransfer.files[0]);});
$('datasets-nav').onclick=() => openModal('datasets-modal');$('top-datasets').onclick=() => openModal('datasets-modal');$('memory-nav').onclick=() => openModal('memory-modal');$('top-memory').onclick=() => openModal('memory-modal');
$('key-nav').onclick=() => openModal('key-modal');$('top-key').onclick=() => openModal('key-modal');
$('refresh-datasets').onclick=refreshDatasets;$('add-memory').onclick=()=>openMemoryEditor();
$('modal-backdrop').onclick=closeModal;document.querySelectorAll('.modal-close').forEach(b=>b.onclick=()=>{if(state.modal==='memory-editor')openModal('memory-modal');else closeModal();});
$('memory-form').onsubmit=async e=>{e.preventDefault();const body={category:$('memory-category').value,key:$('memory-key').value.trim(),value:$('memory-value').value.trim(),scope:$('memory-scope').value};try{await api(state.editingMemory?`/api/memories/${state.editingMemory}`:'/api/memories',json(state.editingMemory?'PUT':'POST',body));openModal('memory-modal');toast('Memory saved');}catch(err){toast(err.message);}};
$('login-form').onsubmit=async e=>{e.preventDefault();try{await api('/api/auth/login',json('POST',{password:$('password').value}));$('password').value='';$('login-error').textContent='';initialize();}catch(err){$('login-error').textContent=err.message;}};
$('key-form').onsubmit=e=>{e.preventDefault();const key=$('personal-key').value.trim();if(!key){toast('Enter an OpenAI API key');return;}state.personalKey=key;state.keyMode='personal';sessionStorage.setItem('byteApiKey',key);sessionStorage.setItem('byteKeyMode','personal');$('personal-key').value='';updateKeyUI();closeModal();toast('Using your key for GPT-4.1');};
$('use-server-key').onclick=()=>{if(!state.serverKeyReady){toast('No workspace API key is configured');return;}state.keyMode='server';sessionStorage.setItem('byteKeyMode','server');updateKeyUI();toast('Using the workspace key');};
$('use-personal-key').onclick=()=>{if(state.personalKey){state.keyMode='personal';sessionStorage.setItem('byteKeyMode','personal');updateKeyUI();toast('Using your key');}else $('personal-key').focus();};
$('clear-key').onclick=()=>{state.personalKey='';state.keyMode='server';sessionStorage.removeItem('byteApiKey');sessionStorage.setItem('byteKeyMode','server');$('personal-key').value='';updateKeyUI();toast('Personal key removed');};
$('logout').onclick=async()=>{sessionStorage.removeItem('byteApiKey');sessionStorage.removeItem('byteKeyMode');await api('/api/auth/logout',{method:'POST'}).catch(()=>{});location.reload();};
$('thinking-toggle').onclick=()=>{state.thinkingOpen=!state.thinkingOpen;localStorage.setItem('thinkingOpen',String(state.thinkingOpen));document.querySelectorAll('.thinking').forEach(el=>el.open=state.thinkingOpen);updateThinkingToggle();toast(state.thinkingOpen?'Thinking steps shown':'Thinking steps hidden');};
$('menu-toggle').onclick=()=>{$('sidebar').classList.add('open');$('mobile-backdrop').classList.add('open');};$('mobile-backdrop').onclick=closeSidebar;
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('action-dialog').open){closeModal();closeSidebar();}if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){e.preventDefault();newChat();}if(e.key==='Tab'&&state.modal&&!$('action-dialog').open){const items=[...$(state.modal).querySelectorAll('button,input,textarea,select,[tabindex]')].filter(el=>!el.disabled&&el.getClientRects().length);if(items.length){const first=items[0],last=items[items.length-1];if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}}}});
$('conversation').addEventListener('click',e=>{const button=e.target.closest('[data-prompt]');if(button)sendMessage(button.dataset.prompt);if(e.target.closest('[data-upload]'))$('file-input').click();});
updateThinkingToggle();
initialize();
