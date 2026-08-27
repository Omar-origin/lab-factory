(function () {
  let sdkPromise;
  function loadSdk() {
    if (typeof window.turnstile?.render === "function") return Promise.resolve(window.turnstile);
    if (sdkPromise) return sdkPromise;
    sdkPromise = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
      script.async = true;
      script.defer = true;
      script.onload = () => typeof window.turnstile?.render === "function" ? resolve(window.turnstile) : reject(new Error("人机验证组件初始化失败，请刷新页面重试。"));
      script.onerror = () => reject(new Error("无法加载人机验证组件，请检查网络或浏览器拦截设置。"));
      document.head.append(script);
    });
    return sdkPromise;
  }
  window.LabTurnstile = {
    async mount({container, action, message, onToken}) {
      const config = await Lab.request("/api/public/config");
      if (!config.turnstile_site_key) throw new Error("管理员尚未配置人机验证。");
      const sdk = await loadSdk();
      const widgetId = sdk.render(container, {
        sitekey: config.turnstile_site_key, action, theme: "dark",
        callback: token => { message.textContent = "人机验证已完成"; message.dataset.state = "success"; onToken(token); },
        "expired-callback": () => { message.textContent = "人机验证已过期，请重新完成"; message.dataset.state = "error"; onToken(""); },
        "error-callback": () => { message.textContent = "人机验证加载失败，请刷新页面或关闭拦截插件后重试"; message.dataset.state = "error"; onToken(""); },
      });
      return {reset() { sdk.reset(widgetId); onToken(""); message.textContent = "请完成人机验证"; message.dataset.state = "pending"; }};
    },
  };
})();
