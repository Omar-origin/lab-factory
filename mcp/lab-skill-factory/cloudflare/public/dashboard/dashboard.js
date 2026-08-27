const planNames = {experience:"9.9 体验版", permanent:"当前大版本永久版", team:"五人共享版"};
const statusNames = {payment_pending:"待付款",payment_submitted:"待核款",payment_rejected:"核款未通过",paid:"已付款",key_issued:"已签发",delivered:"已交付",refunded:"已退款",cancelled:"已取消",expired:"已失效"};
function statusClass(status) { return ["delivered","paid","key_issued"].includes(status) ? "good" : ["refunded","cancelled","expired"].includes(status) ? "bad" : "warn"; }

async function load() {
  await Lab.mountShell("dashboard");
  try {
    const body = await Lab.request("/api/dashboard");
    const current = body.entitlements.find(item => item.order_status === "delivered");
    const keys = current ? body.keys.filter(key => key.order_id === current.order_id) : [];
    const bound = keys.filter(key => key.install_id).length;
    const planCard = document.querySelector("#planCard"); planCard.classList.remove("loading");
    if (current) {
      planCard.innerHTML = `<div class="hero-top"><div><p class="eyebrow">CURRENT ENTITLEMENT</p><h2>${Lab.escape(planNames[current.plan] || current.plan)}</h2><p class="sub">${current.free_major_updates ? "后续大版本免费更新" : current.plan === "permanent" ? "当前大版本永久，未来大版本升级 ¥20" : "3 次报告体验授权"}</p></div><span class="status good">授权有效</span></div><div class="plan-facts"><div><span>授权版本</span><strong>${current.major_version ? `V${current.major_version}` : "全大版本"}</strong></div><div><span>可用席位</span><strong>${current.seat_count} 个</strong></div><div><span>绑定设备</span><strong>${bound} / ${current.seat_count}</strong></div></div><a class="button ghost" href="/account">管理密钥与机器</a>`;
    } else {
      planCard.innerHTML = `<div class="hero-top"><div><p class="eyebrow">NO ACTIVE PLAN</p><h2>还没有有效套餐</h2><p class="sub">可以先用 ¥9.9 完成三次真实任务，再决定是否长期使用。</p></div><span class="status warn">未授权</span></div><div class="plan-facts"><div><span>授权版本</span><strong>—</strong></div><div><span>可用席位</span><strong>0</strong></div><div><span>绑定设备</span><strong>0</strong></div></div><a class="button primary" href="/plans">查看三个套餐</a>`;
    }
    document.querySelector("#notices").innerHTML = body.notices.length ? body.notices.map(item => `<article class="notice"><h3>${Lab.escape(item.title)}</h3><p>${Lab.escape(item.body)}</p></article>`).join("") : `<div class="empty">暂无通知</div>`;
    document.querySelector("#deviceSummary").textContent = `${body.keys.filter(key => key.install_id).length} 台机器已绑定，共有 ${body.keys.length} 把密钥。`;
    document.querySelector("#commissionSummary").textContent = `待确认 ${Lab.money(body.commission.pending_cents)}，可用 ${Lab.money(body.commission.available_cents)}。`;
    document.querySelector("#orders").innerHTML = body.orders.length ? body.orders.map(order => { const state=order.effective_status||order.status; return `<tr><td class="metric">${Lab.escape(String(order.id).slice(-10))}</td><td>${Lab.escape(planNames[order.plan] || order.plan)}</td><td class="metric">${Lab.money(order.amount_cents)}</td><td><span class="status ${statusClass(state)}">${Lab.escape(statusNames[state] || state)}</span></td><td>${Lab.date(order.created_at)}</td></tr>` }).join("") : `<tr><td colspan="5" class="empty">还没有订单</td></tr>`;
  } catch (error) { if (error.status !== 401) Lab.toast(error.message); }
}
load();
