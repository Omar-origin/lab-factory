const descriptions = {experience:"3 次报告体验，不包含 Skill 凝练。",permanent:"当前大版本永久使用，未来大版本升级只需 ¥20。",team:"5 个独立席位、5 把密钥，未来大版本免费更新。"};
const features = {experience:["3 次报告生成","同一安装包","适合先完成真实任务"],permanent:["无限报告","可凝练课程 Skill","当前大版本永久","未来大版本 ¥20 升级"],team:["5 把独立密钥","5 个设备席位","无限报告与 Skill 凝练","未来大版本免费更新"]};
let config, account, selected, orderToken = "";

function renderPlans() {
  document.querySelector("#planGrid").innerHTML = config.plans.map((plan,index) => {const discount=Number(plan.promotion_discount_cents||0);const price=Number(plan.checkout_amount_cents??plan.amount_cents);return `<article class="card plan-card ${index===1?"selected":""}" data-plan="${plan.id}" tabindex="0"><span class="plan-tag ${discount?"promo":""}">${discount?"新用户升级优惠":plan.id === "experience" ? "TRY FIRST" : plan.id === "permanent" ? "CURRENT VERSION" : "FIVE SEATS"}</span><h2>${Lab.escape(plan.name)}</h2><p class="muted">${Lab.escape(descriptions[plan.id])}</p><div class="plan-price">${discount?`<del>${Lab.money(plan.amount_cents)}</del>`:""}${Lab.money(price)} <small>/ 一次性</small></div>${discount?`<p class="promotion-note">已减 ${Lab.money(discount)} · 购买任一升级套餐后恢复原价</p>`:""}<ul class="feature-list">${features[plan.id].map(item=>`<li>${Lab.escape(item)}</li>`).join("")}</ul></article>`}).join("");
  document.querySelectorAll(".plan-card").forEach(card => { const choose = () => selectPlan(card.dataset.plan); card.addEventListener("click",choose); card.addEventListener("keydown",event=>{if(event.key==="Enter"||event.key===" ")choose()}); });
  const requested = new URL(location.href).searchParams.get("plan");
  selectPlan(config.plans.some(p=>p.id===requested) ? requested : config.plans[0].id);
  document.querySelector("#useCredit").checked = new URL(location.href).searchParams.get("credit") === "1"; updateReceipt();
}
function selectPlan(id) {
  const url = new URL(location.href); url.searchParams.set("plan",id); history.replaceState(null,"",url);
  selected = config.plans.find(plan=>plan.id===id); document.querySelectorAll(".plan-card").forEach(card=>card.classList.toggle("selected",card.dataset.plan===id));
  document.querySelector("#selectedName").textContent = selected.name; document.querySelector("#selectedDescription").textContent = descriptions[id]; updateReceipt(); document.querySelector("#createOrder").disabled = false;
  document.querySelector("#continueCheckout").textContent = selected.name + " · 查看账单";
}
function updateReceipt() {
  if (!selected) return; const available = account ? Number(account.user.store_credit_cents||0) : 0; const use = document.querySelector("#useCredit").checked;const promotion=Number(selected.promotion_discount_cents||0);const subtotal=Number(selected.checkout_amount_cents??selected.amount_cents);const credit = use ? Math.min(available,subtotal) : 0;
  document.querySelector("#grossPrice").textContent=Lab.money(selected.amount_cents);document.querySelector("#promotionRow").hidden=!promotion;document.querySelector("#promotionPrice").textContent=`− ${Lab.money(promotion)}`;document.querySelector("#upgradeOffer").hidden=!promotion;document.querySelector("#creditPrice").textContent=`− ${Lab.money(credit)}`; document.querySelector("#payPrice").textContent=Lab.money(subtotal-credit);
}
document.querySelector("#useCredit").addEventListener("change",updateReceipt);
document.querySelector("#createOrder").addEventListener("click",async()=>{
  if (!account) { location.href=`/login?next=${encodeURIComponent("/plans?plan="+selected.id+"&credit="+(document.querySelector("#useCredit").checked?"1":"0"))}`; return; }
  if (!document.querySelector("#agreement").checked) return Lab.toast("请先确认数字商品交付规则");
  const button=document.querySelector("#createOrder");button.disabled=true;
  try { const body=await Lab.request("/api/orders",{method:"POST",body:JSON.stringify({payment_provider:"alipay",plan:selected.id,use_credit:document.querySelector("#useCredit").checked})}); orderToken=body.status_token; sessionStorage.setItem("labFactoryOrderToken",orderToken); document.querySelector("#orderCreate").hidden=true; document.querySelector("#orderId").textContent=body.order.id; document.querySelector("#orderAmount").textContent=Lab.money(body.order.amount_cents);if(body.order.amount_cents===0){document.querySelector("#submittedPanel").hidden=false;document.querySelector("#orderToken").value=orderToken;document.querySelector("#openOrder").href=`/orders#token=${encodeURIComponent(orderToken)}`}else{document.querySelector("#paymentPanel").hidden=false} }
  catch(error){button.disabled=false;Lab.toast(error.message)}
});
document.querySelector("#paymentForm").addEventListener("submit",async event=>{event.preventDefault(); const data=new FormData(event.currentTarget); try{await Lab.request("/api/order/payment",{method:"POST",headers:{"X-Order-Token":orderToken},body:JSON.stringify({payment_reference:data.get("payment_reference"),paid_at:data.get("paid_at")})});document.querySelector("#paymentPanel").hidden=true;document.querySelector("#submittedPanel").hidden=false;document.querySelector("#orderToken").value=orderToken;document.querySelector("#openOrder").href=`/orders#token=${encodeURIComponent(orderToken)}`;}catch(error){Lab.toast(error.message)}});
document.querySelector("#copyToken").addEventListener("click",()=>navigator.clipboard.writeText(orderToken).then(()=>Lab.toast("Token 已复制")));
(async()=>{account=await Lab.mountShell("plans");try{config=await Lab.request("/api/checkout/config");renderPlans()}catch(error){Lab.toast(error.message)}})();
