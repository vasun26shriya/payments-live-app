const $ = id => document.getElementById(id);
let latestOrder = null;
const symbols = {INR:'₹',USD:'$',EUR:'€',GBP:'£'};
const money = (amount,currency) => new Intl.NumberFormat('en',{style:'currency',currency}).format(amount/100);
function message(id,text,error=false){ $(id).textContent=text; $(id).className='feedback '+(error?'error':'success'); }
async function api(path,options={}) {
  const response = await fetch('/api'+path,{credentials:'same-origin',...options,headers:{'Content-Type':'application/json',...options.headers}});
  const data = await response.json();
  if(!response.ok) throw Object.assign(new Error(data.error?.message || 'API unavailable. Please retry.'),{status:response.status,data});
  return data;
}
function showOrder(order,caption='Created and saved in MongoDB') {
  latestOrder=order; $('empty-result').hidden=true; $('result').hidden=false;
  $('result-caption').textContent=caption;
  $('result-status').textContent=order.status; $('result-status').className='badge '+order.status;
  $('result-amount').textContent=money(order.amount,order.currency);
  $('result-id').textContent=order.id; $('result-transaction').textContent=order.transaction_id || 'Awaiting payment result';
  $('result-json').textContent=JSON.stringify(order,null,2);
}
async function refreshOrders() {
  const {orders}=await api('/orders');
  $('count').textContent=orders.length;
  for(const status of ['paid','failed','pending']) $(status).textContent=orders.filter(o=>o.status===status).length;
  $('order-rows').replaceChildren();
  if(!orders.length){const row=document.createElement('tr'),cell=document.createElement('td');cell.colSpan=5;cell.className='table-empty';cell.textContent='No orders yet. Create one above to get started.';row.append(cell);$('order-rows').append(row);return;}
  for(const order of orders){
    const row=document.createElement('tr');
    const values=[order.id.slice(0,8)+'…',money(order.amount,order.currency),order.status,new Date(order.created_at).toLocaleString()];
    values.forEach((value,i)=>{const cell=document.createElement('td');if(i===2){const badge=document.createElement('span');badge.className='badge '+order.status;badge.textContent=value;cell.append(badge);}else{cell.textContent=value;if(i===0)cell.className='order-code';}row.append(cell);});
    const cell=document.createElement('td'),button=document.createElement('button');button.className='view-order';button.textContent='View ↗';button.addEventListener('click',async()=>{try{showOrder(await api('/orders/'+order.id),'Retrieved from MongoDB');$('result').scrollIntoView({behavior:'smooth',block:'center'});}catch(e){message('order-message',e.message,true);}});cell.append(button);row.append(cell);$('order-rows').append(row);
  }
}
$('currency').addEventListener('change',()=>{$('currency-symbol').textContent=symbols[$('currency').value];});
$('order-form').addEventListener('submit',async event=>{
  event.preventDefault(); $('create-button').disabled=true; message('order-message','Submitting order…');
  const raw=$('amount').value;
  if(!/^\d+(\.\d{1,2})?$/.test(raw)){message('order-message','Use a positive amount with at most two decimal places.',true);$('create-button').disabled=false;return;}
  const [whole,fraction='']=raw.split('.'); const amount=Number(whole)*100+Number(fraction.padEnd(2,'0'));
  try{const order=await api('/orders',{method:'POST',body:JSON.stringify({amount,currency:$('currency').value,outcome:new FormData(event.target).get('outcome')})});showOrder(order);message('order-message',order.status==='paid'?'Order paid. Saved with a transaction ID.':'Payment declined as requested. Order saved as failed.');await refreshOrders();}
  catch(e){message('order-message',e.message,true);}finally{$('create-button').disabled=false;}
});
$('retrieve-button').addEventListener('click',async()=>{if(!latestOrder)return;$('retrieve-button').disabled=true;try{const order=await api('/orders/'+latestOrder.id);showOrder(order,'Retrieved from MongoDB — same order and transaction');message('order-message','Saved order retrieved successfully.');await refreshOrders();}catch(e){message('order-message',e.message,true);}finally{$('retrieve-button').disabled=false;}});
$('refresh-button').addEventListener('click',async()=>{try{await refreshOrders();message('order-message','Order history refreshed.');}catch(e){message('order-message',e.message,true);}});
function experimentStep(title,detail,conflict=false){const step=document.createElement('div');step.className='experiment-step'+(conflict?' conflict':'');const heading=document.createElement('strong'),text=document.createElement('code');heading.textContent=title;text.textContent=detail;step.append(heading,text);$('retry-results').append(step);}
$('retry-button').addEventListener('click',async()=>{
  $('retry-button').disabled=true;$('retry-results').replaceChildren();message('retry-message','Sending three concurrent requests…');
  const key='lab:'+crypto.randomUUID(),payload={order_id:'retry:'+crypto.randomUUID(),amount:4200,currency:'INR',outcome:'success'};
  const send=body=>api('/payments',{method:'POST',headers:{'Idempotency-Key':key},body:JSON.stringify(body)});
  try{
    const results=await Promise.all([send(payload),send(payload),send(payload)]);
    results.forEach((r,i)=>experimentStep(`Request ${i+1} · 200 OK`,r.transaction_id));
    if(!results.every(r=>r.transaction_id===results[0].transaction_id)) throw new Error('Transaction IDs differ: retry verification failed.');
    experimentStep('✓ Same transaction for all three',key);
    let rejected=false;
    try{await send({...payload,amount:4300});}catch(e){if(e.status===409){rejected=true;experimentStep('Changed amount · 409 Conflict',e.message,true);}else throw e;}
    if(!rejected)throw new Error('Conflicting amount was unexpectedly accepted.');
    message('retry-message','Verified: retries are consistent; conflicting payloads are rejected.');
  }catch(e){message('retry-message',e.message,true);}finally{$('retry-button').disabled=false;}
});
async function boot(){try{const health=await api('/health');$('health-dot').style.background='#60a482';$('health-text').textContent='API connected';$('health-detail').textContent=health.storage+' · persistent storage';await refreshOrders();}catch(e){$('health-dot').style.background='#ce8674';$('health-text').textContent='Database unavailable';$('health-detail').textContent='Cloud connection needs setup';message('order-message',e.message,true);}}
boot();
