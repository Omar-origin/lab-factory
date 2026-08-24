let adminToken = "";
let lastCreated = null;
let lastIssuedKey = "";
const $ = (selector) => document.querySelector(selector);
const stateLabels = {unused:"未使用",active:"使用中",refund_requested:"申请退款",refunded:"已退款",banned:"已封禁"};
const orderLabels = {payment_pending:"等待付款",payment_submitted:"等待核款",payment_rejected:"付款未通过",paid:"已付款",key_issued:"已签发",delivered:"已交付",refund_requested:"申请退款",refunded:"已退款"};

function toast(message){const node=$("#toast");node.textContent=message;node.classList.add("visible");setTimeout(()=>node.classList.remove("visible"),2600)}
async function api(path, options={}){
  const response=await fetch(path,{...options,headers:{"Authorization":`Bearer ${adminToken}`,"Content-Type":"application/json",...(options.headers||{})}});
  const body=await response.json();
  if(!response.ok)throw new Error(body?.error?.message||`HTTP ${response.status}`);
  return body;
}
function textCell(value){const td=document.createElement("td");td.textContent=value??"—";return td}
function actionButton(label,action,key){const button=document.createElement("button");button.type="button";button.textContent=label;button.addEventListener("click",()=>runAction(action,key));return button}

async function loadKeys(){
  const filter=$("#statusFilter").value;
  const body=await api("/admin/keys?limit=500");
  const allKeys=body.keys,keys=filter?allKeys.filter(key=>key.status===filter):allKeys;
  $("#metricTotal").textContent=allKeys.length;
  $("#metricUnused").textContent=allKeys.filter(k=>k.status==="unused").length;
  $("#metricActive").textContent=allKeys.filter(k=>k.status==="active").length;
  $("#metricBlocked").textContent=allKeys.filter(k=>["refund_requested","refunded","banned"].includes(k.status)).length;
  const rows=$("#keyRows");rows.replaceChildren();$("#emptyState").hidden=keys.length!==0;
  keys.forEach(key=>{
    const tr=document.createElement("tr");tr.append(textCell(`•••• ${key.key_suffix}`));
    const status=document.createElement("td"),badge=document.createElement("span");badge.className=`badge ${key.status}`;badge.textContent=stateLabels[key.status]||key.status;status.append(badge);tr.append(status);
    tr.append(textCell(key.bound?key.install_id:"未绑定"));tr.append(textCell(key.refund_deadline||`${key.refund_days} 天（异常售后参考）`));tr.append(textCell(key.last_seen_at||"—"));
    const actions=document.createElement("td"),group=document.createElement("div");group.className="row-actions";group.append(actionButton("详情","show",key));
    if(["unused","active","refund_requested"].includes(key.status))group.append(actionButton("封禁","ban",key));
    if(["active","refund_requested","banned"].includes(key.status))group.append(actionButton("退款","refund",key));
    if(["banned","refund_requested"].includes(key.status))group.append(actionButton("恢复","restore",key));
    if(["active","banned"].includes(key.status))group.append(actionButton("换机","reset-binding",key));
    actions.append(group);tr.append(actions);rows.append(tr);
  });
}

async function loadOrders(){
  const filter=$("#orderStatusFilter").value;
  const body=await api("/admin/orders?limit=500");
  const orders=filter?body.orders.filter(order=>order.status===filter):body.orders;
  const rows=$("#orderRows");rows.replaceChildren();$("#emptyOrders").hidden=orders.length!==0;
  orders.forEach(order=>{
    const tr=document.createElement("tr");tr.append(textCell(order.id.replace("lforder_","").slice(0,10)));
    const status=document.createElement("td"),badge=document.createElement("span");badge.className=`badge ${order.status}`;badge.textContent=orderLabels[order.status]||order.status;status.append(badge);tr.append(status);
    tr.append(textCell(`${order.payment_provider} / ¥${(order.amount_cents/100).toFixed(2)}`));
    tr.append(textCell(order.payment_reference?`${order.payment_reference} · ${order.payment_claimed_at||""}`:"—"));
    tr.append(textCell(order.contact));
    const actions=document.createElement("td"),group=document.createElement("div");group.className="row-actions";group.append(orderActionButton("详情","show",order));
    if(order.status==="payment_submitted"){group.append(orderActionButton("确认到账并自动发货","confirm-and-deliver",order),orderActionButton("驳回","reject-payment",order))}
    if(order.status==="paid")group.append(orderActionButton("签发密钥","issue",order));
    if(order.status==="key_issued")group.append(orderActionButton("标记交付","deliver",order));
    if(["paid","key_issued","delivered","refund_requested"].includes(order.status))group.append(orderActionButton("原路退款已完成","refund",order));
    actions.append(group);tr.append(actions);rows.append(tr);
  });
}
function orderActionButton(label,action,order){const button=document.createElement("button");button.type="button";button.textContent=label;button.addEventListener("click",()=>runOrderAction(action,order));return button}
async function runOrderAction(action,order){
  try{
    if(action==="show"){const body=await api(`/admin/orders/${order.id}`);showOrderDetail(body.order);return}
    const names={"confirm-and-deliver":"确认到账并自动发货","confirm-payment":"确认付款","reject-payment":"驳回付款",issue:"签发密钥",deliver:"标记交付",refund:"确认原路退款已完成"};
    if(!confirm(`确认${names[action]}订单 ${order.id.slice(-8)}？`))return;
    const reason=action==="issue"?"":prompt("填写操作原因（会进入审计记录）：","")??"";
    const body=await api(`/admin/orders/${order.id}/${action}`,{method:"POST",body:JSON.stringify({reason})});
    if(body.activation_key){lastIssuedKey=body.activation_key;$("#issuedKeyValue").textContent=lastIssuedKey;$("#issuedKeyDialog").showModal()}
    toast(`${names[action]}成功`);await Promise.all([loadOrders(),loadKeys()]);
  }catch(error){toast(error.message)}
}
function showOrderDetail(order){
  $("#detailTitle").textContent=`订单 ${order.id.slice(-10)}`;const fields=$("#detailFields");fields.replaceChildren();
  [["状态",orderLabels[order.status]||order.status],["订单 ID",order.id],["渠道",order.payment_provider],["金额",`¥${(order.amount_cents/100).toFixed(2)} ${order.currency}`],["联系方式",order.contact],["付款核验",order.payment_reference],["付款申报时间",order.payment_claimed_at],["密钥 ID",order.license_key_id],["创建时间",order.created_at],["交付时间",order.delivered_at]].forEach(([name,value])=>{const dt=document.createElement("dt"),dd=document.createElement("dd");dt.textContent=name;dd.textContent=value||"—";fields.append(dt,dd)});
  const audit=$("#auditList");audit.replaceChildren();(order.audit_events||[]).forEach(event=>{const li=document.createElement("li");li.textContent=`${event.event} · ${event.actor}${event.reason?` · ${event.reason}`:""}`;const time=document.createElement("time");time.textContent=event.created_at;li.append(time);audit.append(li)});$("#detailDialog").showModal();
}

async function runAction(action,key){
  try{
    if(action==="show"){const body=await api(`/admin/keys/${key.id}`);showDetail(body.key);return}
    const names={ban:"封禁",refund:"完成退款",restore:"恢复", "reset-binding":"重置安装绑定"};
    if(!confirm(`确认${names[action]}密钥 •••• ${key.key_suffix}？`))return;
    const reason=prompt("填写操作原因（会进入审计记录）：","")??"";
    await api(`/admin/keys/${key.id}/${action}`,{method:"POST",body:JSON.stringify({reason})});toast(`${names[action]}成功`);await loadKeys();
  }catch(error){toast(error.message)}
}
function showDetail(key){
  $("#detailTitle").textContent=`密钥 •••• ${key.key_suffix}`;const fields=$("#detailFields");fields.replaceChildren();
  [["状态",stateLabels[key.status]||key.status],["密钥 ID",key.id],["备注",key.label],["订单引用",key.customer_ref],["安装 ID",key.install_id],["激活时间",key.activated_at],["退款截止",key.refund_deadline],["最后活动",key.last_seen_at],["封禁原因",key.revoke_reason]].forEach(([name,value])=>{const dt=document.createElement("dt"),dd=document.createElement("dd");dt.textContent=name;dd.textContent=value||"—";fields.append(dt,dd)});
  const audit=$("#auditList");audit.replaceChildren();(key.audit_events||[]).forEach(event=>{const li=document.createElement("li");li.textContent=`${event.event} · ${event.actor}${event.reason?` · ${event.reason}`:""}`;const time=document.createElement("time");time.textContent=event.created_at;li.append(time);audit.append(li)});$("#detailDialog").showModal();
}

$("#loginForm").addEventListener("submit",async event=>{event.preventDefault();adminToken=$("#adminToken").value;try{await Promise.all([loadKeys(),loadOrders()]);$("#adminToken").value="";$("#loginPanel").hidden=true;$("#controlPanel").hidden=false;$(".signal").classList.add("online");$("#connectionState").textContent="已连接"}catch(error){adminToken="";toast(error.message)}});
$("#createForm").addEventListener("submit",async event=>{event.preventDefault();const data=new FormData(event.currentTarget);try{const body=await api("/admin/keys",{method:"POST",body:JSON.stringify({label:data.get("label"),customer_ref:data.get("customer_ref"),refund_days:Number(data.get("refund_days"))})});lastCreated=body;$("#newKeyValue").textContent=body.activation_key;$("#newKeyPanel").hidden=false;event.currentTarget.reset();await loadKeys()}catch(error){toast(error.message)}});
$("#copyKey").addEventListener("click",async()=>{if(!lastCreated)return;await navigator.clipboard.writeText(lastCreated.activation_key);toast("密钥已复制，请通过私密渠道发送")});
$("#markSent").addEventListener("click",async()=>{if(!lastCreated)return;try{await api(`/admin/keys/${lastCreated.key.id}/mark-sent`,{method:"POST",body:"{}"});toast("已记录发送时间");await loadKeys()}catch(error){toast(error.message)}});
$("#refreshList").addEventListener("click",()=>loadKeys().catch(error=>toast(error.message)));
$("#statusFilter").addEventListener("change",()=>loadKeys().catch(error=>toast(error.message)));
$("#refreshOrders").addEventListener("click",()=>loadOrders().catch(error=>toast(error.message)));
$("#orderStatusFilter").addEventListener("change",()=>loadOrders().catch(error=>toast(error.message)));
$("#copyIssuedKey").addEventListener("click",async()=>{if(!lastIssuedKey)return;try{await navigator.clipboard.writeText(lastIssuedKey);toast("密钥已复制")}catch{toast("复制失败，请手动复制")}});
