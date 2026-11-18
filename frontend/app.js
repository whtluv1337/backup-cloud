let token = '';
let timer;
const labels = {backup:'Резервное копирование',restore:'Восстановление',check:'Проверка целостности',refresh:'Обновление списка',queued:'В очереди',running:'Выполняется',done:'Завершено',error:'Ошибка'};
const el = id => document.getElementById(id);
async function api(path, options={}) {
  const r = await fetch('/api/'+path,{...options,headers:{'Authorization':'Bearer '+token,'Content-Type':'application/json'}});
  if(!r.ok) {let b=await r.json().catch(()=>({}));throw new Error(b.error||('HTTP '+r.status));}
  return r;
}
function message(s){el('message').textContent=s;}
async function submit(action,snapshot){
  try{const r=await (await api('jobs',{method:'POST',body:JSON.stringify({action,snapshot})})).json();message('Задание принято: '+r.id.slice(0,8));await refresh();}catch(e){message(e.message);}
}
function cell(row,text,cls){const td=document.createElement('td');td.textContent=text;if(cls)td.className=cls;row.append(td);return td;}
async function refresh(){
  const data=await (await api('status')).json();
  const age=Date.now()/1000-Number(data.worker_heartbeat||0);
  el('worker').textContent=age<3700?'Исполнитель: последний ответ '+Math.max(0,Math.round(age))+' с назад':'Исполнитель: ожидается ответ';
  el('snapshots').replaceChildren();
  for(const s of data.snapshots){const c=document.createElement('article');c.className='card';const title=document.createElement('code');title.textContent=s.id.slice(0,12);const p=document.createElement('p');p.textContent=new Date(s.time).toLocaleString('ru-RU')+' · '+(s.hostname||'');const b=document.createElement('button');b.textContent='Восстановить';b.onclick=()=>submit('restore',s.id);c.append(title,p,b);el('snapshots').append(c);}
  if(!data.snapshots.length)el('snapshots').textContent='Снимков пока нет. Создайте первую резервную копию.';
  el('jobs').replaceChildren();
  for(const j of data.jobs){const row=document.createElement('tr');cell(row,labels[j.action]||j.action);cell(row,new Date(j.created*1000).toLocaleString('ru-RU'));cell(row,labels[j.status]||j.status,j.status);const td=cell(row,j.error||j.summary?.snapshot_id?.slice(0,12)||'');if(j.status==='done'&&j.action==='restore'){const b=document.createElement('button');b.textContent='Скачать ZIP';b.onclick=async()=>{try{const blob=await (await api('download/'+j.id)).blob();const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='restore-'+j.id+'.zip';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e){message(e.message);}};td.append(b);}el('jobs').append(row);}
}
el('connect').onclick=async()=>{token=el('token').value.trim();try{await refresh();message('Подключение установлено');clearInterval(timer);timer=setInterval(()=>refresh().catch(e=>message(e.message)),5000);}catch(e){message(e.message);}};
document.querySelectorAll('[data-action]').forEach(b=>b.onclick=()=>submit(b.dataset.action));
