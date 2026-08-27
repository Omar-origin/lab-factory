const Lab = (() => {
  const money = cents => new Intl.NumberFormat("zh-CN", {style: "currency", currency: "CNY"}).format(Number(cents || 0) / 100);
  const date = value => value ? new Intl.DateTimeFormat("zh-CN", {dateStyle: "medium", timeStyle: "short"}).format(new Date(value)) : "—";
  const escape = value => String(value ?? "").replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[char]);
  const toast = message => { const node = document.querySelector("#toast"); if (!node) return; node.textContent = message; node.classList.add("visible"); clearTimeout(node._timer); node._timer = setTimeout(() => node.classList.remove("visible"), 3000); };
  function modal({title="提示", message="", confirmLabel="知道了", cancelLabel="", danger=false}={}) {
    let dialog = document.querySelector("#labModal");
    if (!dialog) { dialog = document.createElement("dialog"); dialog.id = "labModal"; dialog.className = "lab-modal"; document.body.append(dialog); }
    dialog.innerHTML = `<div class="modal-signal ${danger?"danger":""}"></div><p class="eyebrow">LAB FACTORY / NOTICE</p><h2>${escape(title)}</h2><p class="modal-message">${escape(message)}</p><div class="modal-actions">${cancelLabel?`<button class="button ghost" value="cancel">${escape(cancelLabel)}</button>`:""}<button class="button ${danger?"danger":"primary"}" value="confirm">${escape(confirmLabel)}</button></div>`;
    return new Promise(resolve => { let settled=false; const finish=value=>{if(settled)return;settled=true;dialog.oncancel=null;dialog.close();resolve(value)}; dialog.querySelector('[value="confirm"]').addEventListener("click",()=>finish(true)); dialog.querySelector('[value="cancel"]')?.addEventListener("click",()=>finish(false)); dialog.oncancel=event=>{event.preventDefault();finish(false)}; dialog.showModal(); });
  }
  async function request(path, options = {}) {
    const response = await fetch(path, {credentials: "same-origin", ...options, headers: {"Content-Type":"application/json", ...(options.headers || {})}});
    let body = {}; try { body = await response.json(); } catch {}
    if (!response.ok) { const error = new Error(body?.error?.message || `请求失败（${response.status}）`); error.status = response.status; throw error; }
    return body;
  }
  async function mountShell(active) {
    document.querySelectorAll("[data-route]").forEach(node => node.classList.toggle("active", node.dataset.route === active));
    document.querySelector("#menuButton")?.addEventListener("click", () => document.querySelector("#mainNav")?.classList.toggle("open"));
    document.querySelector("#logoutButton")?.addEventListener("click", async () => { try { await request("/api/auth/logout", {method:"POST", body:"{}"}); location.href = "/login"; } catch (error) { toast(error.message); } });
    try {
      const body = await request("/api/me");
      const email = body.user.email;
      document.querySelectorAll("[data-user-email]").forEach(node => node.textContent = email);
      document.querySelectorAll("[data-user-initial]").forEach(node => node.textContent = email.slice(0,1).toUpperCase());
      if (body.admin_access && !document.querySelector("[data-control-link]")) { const link=document.createElement("a");link.href="/control/overview";link.dataset.controlLink="";link.className="nav-link control-link";link.innerHTML='<span class="nav-glyph">▦</span>管理中控';document.querySelector("#mainNav")?.append(link); }
      return body;
    } catch (error) {
      if (error.status === 401 && active !== "plans" && active !== "showcase" && active !== "docs") location.href = `/login?next=${encodeURIComponent(location.pathname + location.search)}`;
      return null;
    }
  }
  if (["/login","/register","/dashboard","/plans","/referrals","/showcase","/docs","/account","/orders"].includes(location.pathname.replace(/\/$/,""))) fetch("/api/metrics/view",{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json"},body:JSON.stringify({route:location.pathname.replace(/\/$/,"")}),keepalive:true}).catch(()=>{});
  return {money, date, escape, toast, modal, request, mountShell};
})();
if (document.body.dataset.shell) Lab.mountShell(document.body.dataset.shell);
