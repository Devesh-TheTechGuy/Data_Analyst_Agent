const $ = (id) => document.getElementById(id);
const state = { chatId: null, chats: [], datasets: [], memories: [], busy: false, modal: null, editingMemory: null, thinkingOpen: localStorage.getItem('thinkingOpen') === 'true' };
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));

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
  $('chat-list').innerHTML = state.chats.filter(c => c.title.toLowerCase().includes(query)).map(c => `<div class="chat-item ${c.id===state.chatId?'active':''}" data-id="${esc(c.id)}"><span class="chat-icon">▢</span><span class="chat-name">${esc(c.title)}</span><button class="chat-more" data-more="${esc(c.id)}" aria-label="Conversation options">•••</button></div>`).join('') || '<div class="empty-note">No conversations yet</div>';
  $('chat-list').querySelectorAll('.chat-item').forEach(el => el.addEventListener('click', e => { if (!e.target.closest('.chat-more')) openChat(el.dataset.id); }));
  $('chat-list').querySelectorAll('.chat-more').forEach(el => el.addEventListener('click', e => { e.stopPropagation(); chatMenu(el.dataset.more, el); }));
}
function chatMenu(id, anchor) {
  document.querySelector('.context-menu')?.remove();
  const menu = document.createElement('div'); menu.className = 'context-menu glass';
  menu.innerHTML = '<button data-action="rename">✎ Rename</button><button data-action="delete">⌫ Delete</button>';
  const rect = anchor.getBoundingClientRect(); menu.style.left = `${Math.min(rect.left-120, innerWidth-150)}px`; menu.style.top = `${rect.bottom+5}px`;
  document.body.append(menu);
  menu.addEventListener('click', async e => {
    const action=e.target.dataset.action; menu.remove(); if (!action) return;
    if (action==='rename') {
      const chat=state.chats.find(c=>c.id===id), title=prompt('Name this conversation',chat.title);
      if (title?.trim()) { try { await api(`/api/chats/${id}`, json('PATCH',{title:title.trim()})); await refreshChats(); if (id===state.chatId) $('current-title').textContent=title.trim(); } catch(err){toast(err.message);} }
    } else if (confirm('Delete this conversation?')) {
      try { await api(`/api/chats/${id}`,{method:'DELETE'}); if(id===state.chatId) newChat(); await refreshChats(); toast('Conversation deleted'); } catch(err){toast(err.message);}
    }
  });
  setTimeout(()=>document.addEventListener('click',e=>{if(!menu.contains(e.target))menu.remove();},{once:true}),0);
}
async function refreshChats() { state.chats = await api('/api/chats'); renderChats(); }
function newChat() { state.chatId=null; $('current-title').textContent='New analysis'; $('conversation').innerHTML=welcome(); renderChats(); closeSidebar(); $('prompt').focus(); }
async function openChat(id) {
  try { const chat=await api(`/api/chats/${id}`); state.chatId=id; $('current-title').textContent=chat.title; $('conversation').innerHTML='';
    if (!chat.messages.length) $('conversation').innerHTML=welcome(); else chat.messages.forEach(renderMessage);
    renderChats(); closeSidebar(); scrollBottom();
  } catch(err) { toast(err.message); }
}
function welcome() {
  const samples = state.datasets.slice(0,3).map(d=>`<span class="dataset-chip">▤ ${esc(d.name)}</span>`).join('');
  return `<div class="welcome"><div class="welcome-mark">✧</div><h1>What can we <em>uncover?</em></h1><p>Ask a question, explore a pattern, or turn your data into clarity.</p><div class="suggestions"><button class="suggestion" data-prompt="Give me an overview of my datasets"><span class="suggest-icon">▤</span><span><strong>Explore my data</strong><small>Structure, columns and key patterns</small></span></button><button class="suggestion" data-prompt="Check my datasets for missing values and quality issues"><span class="suggest-icon">◇</span><span><strong>Check data quality</strong><small>Spot gaps and inconsistencies</small></span></button><button class="suggestion" data-prompt="Find the most interesting relationships in my data"><span class="suggest-icon">⌁</span><span><strong>Find insights</strong><small>Relationships worth a closer look</small></span></button><button class="suggestion" data-prompt="Create a useful chart from my data"><span class="suggest-icon">◫</span><span><strong>Visualize a trend</strong><small>Make the story easier to see</small></span></button></div><div class="loaded-strip">${state.datasets.length?'READY TO ANALYZE':'ADD A DATASET TO BEGIN'} ${samples}</div></div>`;
}
function renderMessage(message) {
  if ($('conversation').querySelector('.welcome')) $('conversation').innerHTML='';
  const article=document.createElement('article'); article.className=`message ${message.role}`; article.dataset.id=message.id||'';
  if (message.role==='user') article.innerHTML=`<div class="user-bubble">${esc(message.content)}</div>`;
  else {
    article.innerHTML=`<div class="assistant-heading"><span class="assistant-symbol">✧</span><span>Glassboard</span></div><div class="thinking-slot"></div><div class="answer">${markdown(message.content)}</div><div class="message-actions"><button class="copy-answer">▢ Copy</button></div>`;
    renderThinking(article, message.activity||[]);
    article.querySelector('.copy-answer').addEventListener('click',async()=>{await navigator.clipboard.writeText(message.content);toast('Copied answer');});
  }
  $('conversation').append(article); return article;
}
function renderThinking(article, activity) {
  const slot=article.querySelector('.thinking-slot'); if (!slot) return;
  if (!activity.length) {slot.innerHTML='';return;}
  const describe=step=>step.tool==='sql_query'?step.arguments?.query:(step.arguments?.name||step.arguments?.expression||'');
  slot.innerHTML=`<details class="thinking" ${state.thinkingOpen?'open':''}><summary>✦ Thinking <span>· ${activity.length} step${activity.length===1?'':'s'}</span></summary><div class="thinking-list">${activity.map(step=>`<div class="thinking-step ${step.error?'error':''}"><span class="thinking-dot">✧</span><div><strong>${esc(step.label)}</strong>${describe(step)?`<span class="step-arguments">${esc(describe(step))}</span>`:''}<span>${esc(step.result||'')}</span></div></div>`).join('')}</div></details>`;
  slot.querySelector('details').addEventListener('toggle',e=>{state.thinkingOpen=e.target.open;localStorage.setItem('thinkingOpen',String(state.thinkingOpen));});
}
function setBusy(value){state.busy=value;$('send').disabled=value;$('prompt').disabled=value;$('upload-trigger').disabled=value;$('send').textContent=value?'···':'↑';}

async function sendMessage(text) {
  const question=text.trim(); if(!question||state.busy)return;
  setBusy(true); $('prompt').value=''; resizePrompt();
  try {
    if(!state.chatId){const chat=await api('/api/chats',json('POST',{title:'New analysis'}));state.chatId=chat.id;}
    renderMessage({role:'user',content:question});
    const pending=renderMessage({role:'assistant',content:'',activity:[]});
    pending.querySelector('.answer').innerHTML='<span class="loading-dots"><i></i><i></i><i></i></span>';
    scrollBottom(); let activity=[], gotFinal=false;
    const response=await fetch(`/api/chats/${state.chatId}/messages`,{...json('POST',{content:question}),credentials:'same-origin'});
    if(!response.ok){const data=await response.json().catch(()=>({}));throw new Error(data.detail||'Could not send message');}
    const reader=response.body.getReader(), decoder=new TextDecoder(); let buffer='';
    const handle=block=>{const lines=block.split('\n');const kind=lines.find(x=>x.startsWith('event: '))?.slice(7);const raw=lines.filter(x=>x.startsWith('data: ')).map(x=>x.slice(6)).join('\n');if(!kind||!raw)return;
      const data=JSON.parse(raw);
      if(kind==='activity'){activity.push(data);renderThinking(pending,activity);scrollBottom();}
      if(kind==='final'){gotFinal=true;pending.dataset.id=data.id;pending.querySelector('.answer').innerHTML=markdown(data.content);renderThinking(pending,data.activity||activity);pending.querySelector('.copy-answer').onclick=async()=>{await navigator.clipboard.writeText(data.content);toast('Copied answer');};scrollBottom();}
      if(kind==='memory'){toast(`${data.count} useful ${data.count===1?'memory':'memories'} saved`);refreshMemories();}
      if(kind==='error'){pending.querySelector('.answer').innerHTML=`<div class="error-banner">${esc(data.message)}</div>`;}
    };
    while(true){const {value,done}=await reader.read();if(done)break;buffer+=decoder.decode(value,{stream:true}).replace(/\r\n/g,'\n');let index;while((index=buffer.indexOf('\n\n'))>=0){handle(buffer.slice(0,index));buffer=buffer.slice(index+2);}}
    if(buffer.trim())handle(buffer);
    if(!gotFinal && pending.querySelector('.loading-dots'))pending.querySelector('.answer').innerHTML='<div class="error-banner">The response ended before an answer arrived. Try again.</div>';
    await refreshChats(); $('current-title').textContent=state.chats.find(c=>c.id===state.chatId)?.title||'Analysis';
  } catch(err){toast(err.message);const pending=$('conversation').querySelector('.message.assistant:last-child');if(pending)pending.querySelector('.answer').innerHTML=`<div class="error-banner">${esc(err.message)}</div>`;}
  finally{setBusy(false);$('prompt').focus();}
}
function resizePrompt(){const el=$('prompt');el.style.height='auto';el.style.height=Math.min(el.scrollHeight,150)+'px';}

async function refreshDatasets() {
  try {const data=await api('/api/datasets');state.datasets=data.datasets;$('dataset-count').textContent=state.datasets.length;$('top-dataset-count').textContent=`${state.datasets.length} dataset${state.datasets.length===1?'':'s'}`;$('dataset-summary').textContent=`${state.datasets.length} dataset${state.datasets.length===1?'':'s'}`;
    $('dataset-list').innerHTML=state.datasets.map(d=>`<div class="list-card"><span class="card-symbol">▤</span><div class="card-content"><strong>${esc(d.name)}</strong><p>${esc(d.filename)}</p><small>${Number(d.rows).toLocaleString()} rows · ${d.columns} columns · ${d.source==='folder'?'Data folder':'Uploaded'}</small></div>${d.source==='upload'?`<div class="card-actions"><button data-delete-dataset="${esc(d.id.slice(7))}" title="Remove dataset">✕</button></div>`:''}</div>`).join('')||'<div class="empty-note">No datasets yet. Upload one or add a file to data/.</div>';
    $('dataset-list').querySelectorAll('[data-delete-dataset]').forEach(button=>button.addEventListener('click',async()=>{if(!confirm('Remove this uploaded dataset?'))return;try{await api(`/api/datasets/${button.dataset.deleteDataset}`,{method:'DELETE'});await refreshDatasets();toast('Dataset removed');}catch(err){toast(err.message);}}));
    if(data.errors && Object.keys(data.errors).length)toast('Some files in data/ could not be loaded. Check their format.');
    if(!state.chatId)$('conversation').innerHTML=welcome();
  }catch(err){toast(err.message);}
}
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
  $('memory-list').querySelectorAll('[data-delete]').forEach(b=>b.onclick=async()=>{if(!confirm('Forget this memory?'))return;try{await api(`/api/memories/${b.dataset.delete}`,{method:'DELETE'});await refreshMemories();toast('Memory forgotten');}catch(err){toast(err.message);}});
}
function openModal(id){closeModal();state.modal=id;$('modal-backdrop').classList.remove('hidden');$(id).classList.remove('hidden');if(id==='memory-modal')refreshMemories();if(id==='datasets-modal')refreshDatasets();}
function closeModal(){['memory-modal','datasets-modal','memory-editor'].forEach(id=>$(id).classList.add('hidden'));$('modal-backdrop').classList.add('hidden');state.modal=null;}
function openMemoryEditor(item=null){state.editingMemory=item?.id||null;$('editor-heading').textContent=item?'Edit memory':'Add memory';$('memory-category').value=item?.category||'definition';$('memory-key').value=item?.key||'';$('memory-value').value=item?.value||'';$('memory-scope').innerHTML='<option value="">All datasets</option>'+state.datasets.map(d=>`<option value="${esc(d.name)}">${esc(d.name)}</option>`).join('');$('memory-scope').value=item?.scope||'';openModal('memory-editor');}

async function initialize(){
  try{const status=await api('/api/status');if(!status.ready){$('login-screen').classList.remove('hidden');$('login-screen').querySelector('p').textContent=`Server setup required: ${status.missing.join(', ')}`;return;}
    if(!status.authenticated){$('login-screen').classList.remove('hidden');return;}
    $('login-screen').classList.add('hidden');await Promise.all([refreshChats(),refreshDatasets(),refreshMemories()]);newChat();
    if(!status.chat_ready)toast('Set OPENAI_API_KEY on the server to enable chat.');
  }catch(err){toast(err.message);}
}

$('composer').addEventListener('submit',e=>{e.preventDefault();sendMessage($('prompt').value);});
$('prompt').addEventListener('input',resizePrompt);
$('prompt').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMessage(e.target.value);}});
$('new-chat').onclick=newChat;$('chat-search').oninput=renderChats;
$('upload-trigger').onclick=()=>$('file-input').click();$('modal-upload').onclick=()=>$('file-input').click();$('file-input').onchange=e=>uploadFile(e.target.files[0]);
$('datasets-nav').onclick=() => openModal('datasets-modal');$('top-datasets').onclick=() => openModal('datasets-modal');$('memory-nav').onclick=() => openModal('memory-modal');$('top-memory').onclick=() => openModal('memory-modal');
$('refresh-datasets').onclick=refreshDatasets;$('add-memory').onclick=()=>openMemoryEditor();
$('modal-backdrop').onclick=closeModal;document.querySelectorAll('.modal-close').forEach(b=>b.onclick=()=>{if(state.modal==='memory-editor')openModal('memory-modal');else closeModal();});
$('memory-form').onsubmit=async e=>{e.preventDefault();const body={category:$('memory-category').value,key:$('memory-key').value.trim(),value:$('memory-value').value.trim(),scope:$('memory-scope').value};try{await api(state.editingMemory?`/api/memories/${state.editingMemory}`:'/api/memories',json(state.editingMemory?'PUT':'POST',body));openModal('memory-modal');toast('Memory saved');}catch(err){toast(err.message);}};
$('login-form').onsubmit=async e=>{e.preventDefault();try{await api('/api/auth/login',json('POST',{password:$('password').value}));$('password').value='';$('login-error').textContent='';initialize();}catch(err){$('login-error').textContent=err.message;}};
$('logout').onclick=async()=>{await api('/api/auth/logout',{method:'POST'}).catch(()=>{});location.reload();};
$('thinking-toggle').onclick=()=>{state.thinkingOpen=!state.thinkingOpen;localStorage.setItem('thinkingOpen',String(state.thinkingOpen));document.querySelectorAll('.thinking').forEach(el=>el.open=state.thinkingOpen);toast(state.thinkingOpen?'Thinking steps shown':'Thinking steps hidden');};
$('menu-toggle').onclick=()=>{$('sidebar').classList.add('open');$('mobile-backdrop').classList.add('open');};$('mobile-backdrop').onclick=closeSidebar;
document.addEventListener('keydown',e=>{if(e.key==='Escape'){closeModal();closeSidebar();}if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){e.preventDefault();newChat();}});
$('conversation').addEventListener('click',e=>{const button=e.target.closest('[data-prompt]');if(button)sendMessage(button.dataset.prompt);});
initialize();
