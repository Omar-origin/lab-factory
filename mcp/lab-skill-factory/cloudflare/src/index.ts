interface Env {
  DB: D1Database;
  ASSETS: Fetcher;
  ADMIN_TOKEN: string;
  KEY_PEPPER: string;
  TOKEN_SECRET: string;
  LEASE_PRIVATE_KEY_B64: string;
  PRODUCT_ID: string;
  PRICE_CENTS: string;
  REFUND_DAYS: string;
  SUPPORT_CONTACT: string;
  LEASE_KEY_ID: string;
}

type Row = Record<string, unknown>;

class HttpError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

const encoder = new TextEncoder();
const KEY_STATES = new Set(["unused", "active", "refund_requested", "refunded", "banned"]);
const ORDER_STATES = new Set(["payment_pending", "payment_submitted", "payment_rejected", "paid", "key_issued", "delivered", "refund_requested", "refunded"]);

function nowIso(): string {
  return new Date().toISOString().replace(/\.\d{3}Z$/, "+00:00");
}

function addHours(value: Date, hours: number): string {
  return new Date(value.getTime() + hours * 3600_000).toISOString().replace(/\.\d{3}Z$/, "+00:00");
}

function addDays(value: Date, days: number): string {
  return new Date(value.getTime() + days * 86400_000).toISOString().replace(/\.\d{3}Z$/, "+00:00");
}

function text(value: unknown, field: string, max: number, required = false): string {
  if (value === undefined || value === null) value = "";
  if (typeof value !== "string") throw new HttpError(400, "INVALID_FIELD", `${field} must be a string`);
  const result = value.trim();
  if (required && !result) throw new HttpError(400, "MISSING_FIELD", `${field} is required`);
  if (result.length > max) throw new HttpError(400, "INVALID_FIELD", `${field} is too long`);
  return result;
}

function b64url(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function fromB64url(value: string): Uint8Array<ArrayBuffer> {
  const padded = value.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - value.length % 4) % 4);
  const binary = atob(padded);
  const result = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) result[index] = binary.charCodeAt(index);
  return result;
}

function hex(bytes: ArrayBuffer): string {
  return Array.from(new Uint8Array(bytes), value => value.toString(16).padStart(2, "0")).join("");
}

async function sha256(value: string): Promise<string> {
  return hex(await crypto.subtle.digest("SHA-256", encoder.encode(value)));
}

async function hmacBytes(secret: string, value: string): Promise<Uint8Array> {
  const key = await crypto.subtle.importKey("raw", encoder.encode(secret), {name: "HMAC", hash: "SHA-256"}, false, ["sign"]);
  return new Uint8Array(await crypto.subtle.sign("HMAC", key, encoder.encode(value)));
}

async function hmacHex(secret: string, value: string): Promise<string> {
  const bytes = await hmacBytes(secret, value);
  return Array.from(bytes, byte => byte.toString(16).padStart(2, "0")).join("");
}

async function secureEqual(left: string, right: string): Promise<boolean> {
  const a = new Uint8Array(await crypto.subtle.digest("SHA-256", encoder.encode(left)));
  const b = new Uint8Array(await crypto.subtle.digest("SHA-256", encoder.encode(right)));
  let difference = 0;
  for (let index = 0; index < a.length; index += 1) difference |= a[index] ^ b[index];
  return difference === 0;
}

function canonical(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  const record = value as Record<string, unknown>;
  return `{${Object.keys(record).sort().map(key => `${JSON.stringify(key)}:${canonical(record[key])}`).join(",")}}`;
}

function randomId(prefix: string): string {
  return prefix + crypto.randomUUID().replace(/-/g, "");
}

function randomToken(): string {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return b64url(bytes);
}

const BASE32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
function activationKeyFromBytes(bytes: Uint8Array): string {
  let bits = 0, value = 0, encoded = "";
  for (const byte of bytes) {
    value = (value << 8) | byte;
    bits += 8;
    while (bits >= 5) {
      encoded += BASE32[(value >>> (bits - 5)) & 31];
      bits -= 5;
    }
  }
  if (bits) encoded += BASE32[(value << (5 - bits)) & 31];
  return `LF-${encoded.match(/.{1,4}/g)!.join("-")}`;
}

function activationKey(): string {
  const bytes = new Uint8Array(20);
  crypto.getRandomValues(bytes);
  return activationKeyFromBytes(bytes);
}

async function orderActivationKey(env: Env, orderId: string): Promise<string> {
  return activationKeyFromBytes((await hmacBytes(env.KEY_PEPPER, `order-delivery:v1:${orderId}`)).slice(0, 20));
}

async function orderLicenseKeyId(orderId: string): Promise<string> {
  return `lfkey_${(await sha256(`order-license:v1:${orderId}`)).slice(0, 32)}`;
}

function normalizeKey(value: string): string {
  return value.trim().toUpperCase().replace(/ /g, "");
}

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
      "Referrer-Policy": "no-referrer",
    },
  });
}

async function body(request: Request): Promise<Row> {
  const raw = await request.text();
  if (encoder.encode(raw).byteLength > 32 * 1024) throw new HttpError(413, "BODY_TOO_LARGE", "request body is too large");
  try {
    const parsed = raw ? JSON.parse(raw) : {};
    if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") throw new Error();
    return parsed as Row;
  } catch {
    throw new HttpError(400, "INVALID_JSON", "request body must be a JSON object");
  }
}

async function requireAdmin(request: Request, env: Env): Promise<void> {
  const supplied = (request.headers.get("Authorization") || "").replace(/^Bearer\s+/i, "").trim();
  if (!env.ADMIN_TOKEN || !(await secureEqual(supplied, env.ADMIN_TOKEN))) throw new HttpError(401, "ADMIN_AUTH_REQUIRED", "valid administrator token required");
}

function orderToken(request: Request): string {
  return text(request.headers.get("X-Order-Token"), "status_token", 128, true);
}

function audit(env: Env, keyId: string | null, event: string, actor: string, reason = "", metadata: Row = {}): D1PreparedStatement {
  return env.DB.prepare("INSERT INTO audit_events(id,license_key_id,event,actor,reason,metadata_json,created_at) VALUES(?,?,?,?,?,?,?)")
    .bind(randomId("lfaudit_"), keyId, event, actor, reason.slice(0, 500), JSON.stringify(metadata), nowIso());
}

function orderAudit(env: Env, orderId: string, event: string, actor: string, reason = "", metadata: Row = {}): D1PreparedStatement {
  return env.DB.prepare("INSERT INTO order_audit_events(id,order_id,event,actor,reason,metadata_json,created_at) VALUES(?,?,?,?,?,?,?)")
    .bind(randomId("lfoaudit_"), orderId, event, actor, reason.slice(0, 500), JSON.stringify(metadata), nowIso());
}

function publicKey(row: Row): Row {
  const result: Row = {};
  for (const [key, value] of Object.entries(row)) {
    if (!["key_hash", "activation_token_hash", "device_public_key"].includes(key)) result[key] = value;
  }
  result.used = row.status !== "unused" || Boolean(row.activated_at);
  result.bound = Boolean(row.install_id);
  return result;
}

function maskContact(value: string): string {
  if (!value) return "";
  if (value.length <= 4) return "••••";
  return `${value.slice(0, 2)}••••${value.slice(-2)}`;
}

async function orderValue(env: Env, row: Row, publicView: boolean): Promise<Row> {
  const result: Row = {};
  for (const [key, value] of Object.entries(row)) {
    if (key !== "status_token_hash" && (!publicView || key !== "admin_reason")) result[key] = value;
  }
  if (publicView) result.contact = maskContact(String(row.contact || ""));
  if (row.license_key_id) {
    const key = await env.DB.prepare("SELECT status,key_suffix,refund_deadline,activated_at FROM license_keys WHERE id=?").bind(row.license_key_id).first<Row>();
    if (key) result.license = key;
  }
  if (publicView && row.status === "delivered" && row.delivery_key_version === "derived-v1") {
    result.activation_key = await orderActivationKey(env, String(row.id));
  }
  return result;
}

async function checkoutConfig(env: Env): Promise<Response> {
  return json(200, {
    ok: true,
    product: {
      id: env.PRODUCT_ID,
      name: "Lab Factory 抢先体验",
      amount_cents: Number(env.PRICE_CENTS),
      currency: "CNY",
      refund_days: Number(env.REFUND_DAYS),
      self_service_refunds: false,
      refund_policy: "数字化商品密钥交付后原则上不支持无理由退款；重复付款、无法激活且无法修复、重大功能缺陷或法律另有规定的情形，请联系售后人工处理。",
      entitlement: "当前 beta 永久使用，30 天内可更新，升级正式创始版抵扣 9.9 元",
    },
    payment_providers: [{
      id: "alipay",
      label: "支付宝经营码",
      payment_url: "",
      instructions: "使用支付宝扫描经营码并支付 9.9 元",
      qr_image_url: "/payment-assets/alipay.png",
      verification: "manual",
      available: true,
    }],
    support_contact: env.SUPPORT_CONTACT,
    delivery_commitment: "人工核款确认后，订单页自动显示激活密钥",
  });
}

async function createOrder(request: Request, env: Env): Promise<Response> {
  const input = await body(request);
  const contact = text(input.contact, "contact", 160, true);
  const provider = text(input.payment_provider, "payment_provider", 40, true);
  if (provider !== "alipay") throw new HttpError(400, "PAYMENT_PROVIDER_UNAVAILABLE", "selected payment provider is unavailable");
  const id = randomId("lforder_");
  const token = randomToken();
  const current = nowIso();
  await env.DB.batch([
    env.DB.prepare(`INSERT INTO orders(id,status_token_hash,status,product_id,amount_cents,currency,payment_provider,contact,refund_days,created_at,updated_at)
      VALUES(?,?,'payment_pending',?,?,?,?,?,?,?,?)`).bind(
      id, await sha256(token), env.PRODUCT_ID, Number(env.PRICE_CENTS), "CNY", provider, contact, Number(env.REFUND_DAYS), current, current,
    ),
    orderAudit(env, id, "order_created", "customer", "", {provider}),
  ]);
  const row = await env.DB.prepare("SELECT * FROM orders WHERE id=?").bind(id).first<Row>();
  return json(201, {ok: true, status_token: token, status_url: `/buy#order=${token}`, order: await orderValue(env, row!, true)});
}

async function orderByToken(request: Request, env: Env): Promise<Row> {
  const token = orderToken(request);
  const row = await env.DB.prepare("SELECT * FROM orders WHERE status_token_hash=?").bind(await sha256(token)).first<Row>();
  if (!row) throw new HttpError(404, "ORDER_NOT_FOUND", "order token is invalid");
  return row;
}

async function getOrder(request: Request, env: Env): Promise<Response> {
  return json(200, {ok: true, order: await orderValue(env, await orderByToken(request, env), true)});
}

async function submitPayment(request: Request, env: Env): Promise<Response> {
  const input = await body(request);
  const reference = text(input.payment_reference, "payment_reference", 120, true);
  const claimedAt = text(input.paid_at, "paid_at", 64, true);
  const row = await orderByToken(request, env);
  const current = String(row.status);
  if (current === "payment_submitted") {
    if (row.payment_reference !== reference || row.payment_claimed_at !== claimedAt) throw new HttpError(409, "PAYMENT_ALREADY_SUBMITTED", "payment details were already submitted");
  } else if (!["payment_pending", "payment_rejected"].includes(current)) {
    throw new HttpError(409, "INVALID_STATE", `payment cannot be submitted from ${current}`);
  } else {
    const updated = nowIso();
    await env.DB.batch([
      env.DB.prepare("UPDATE orders SET status='payment_submitted',payment_reference=?,payment_claimed_at=?,updated_at=?,admin_reason='' WHERE id=?")
        .bind(reference, claimedAt, updated, row.id),
      orderAudit(env, String(row.id), "payment_submitted", "customer", "", {paid_at: claimedAt}),
    ]);
  }
  const fresh = await env.DB.prepare("SELECT * FROM orders WHERE id=?").bind(row.id).first<Row>();
  return json(200, {ok: true, order: await orderValue(env, fresh!, true)});
}

async function requestOrderRefund(request: Request, env: Env): Promise<Response> {
  await orderByToken(request, env);
  throw new HttpError(409, "SELF_SERVICE_REFUND_UNAVAILABLE", "数字化商品交付后不提供自助无理由退款。重复付款、无法激活或重大功能故障请联系售后QQ群 923937311 处理。");
}

async function importLeasePrivate(env: Env): Promise<CryptoKey> {
  const raw = fromB64url(env.LEASE_PRIVATE_KEY_B64);
  if (raw.length !== 32) throw new Error("online lease private key secret is invalid");
  const prefix = Uint8Array.from([0x30,0x2e,0x02,0x01,0x00,0x30,0x05,0x06,0x03,0x2b,0x65,0x70,0x04,0x22,0x04,0x20]);
  const pkcs8 = new Uint8Array(prefix.length + raw.length);
  pkcs8.set(prefix); pkcs8.set(raw, prefix.length);
  return crypto.subtle.importKey("pkcs8", pkcs8, {name: "Ed25519"}, false, ["sign"]);
}

async function issueLease(env: Env, keyId: string, installId: string, issued = new Date()): Promise<Row> {
  const payload: Row = {
    format: "lab-factory-online-lease",
    version: 1,
    lease_id: randomId("lflease_"),
    license_key_id: keyId,
    install_id: installId,
    product_id: env.PRODUCT_ID,
    status: "active",
    issued_at: issued.toISOString().replace(/\.\d{3}Z$/, "+00:00"),
    refresh_after: addHours(issued, 6),
    expires_at: addHours(issued, 24),
    issuer_key_id: env.LEASE_KEY_ID,
  };
  const signature = await crypto.subtle.sign({name: "Ed25519"}, await importLeasePrivate(env), encoder.encode(canonical(payload)));
  return {payload, signature: b64url(new Uint8Array(signature))};
}

async function activate(request: Request, env: Env): Promise<Response> {
  const input = await body(request);
  const supplied = text(input.activation_key, "activation_key", 128, true);
  const installId = text(input.install_id, "install_id", 96, true);
  const publicKey = text(input.device_public_key, "device_public_key", 128, true);
  let publicRaw: Uint8Array;
  try { publicRaw = fromB64url(publicKey); } catch { throw new HttpError(400, "INVALID_DEVICE_KEY", "installation public key is invalid"); }
  if (publicRaw.length !== 32) throw new HttpError(400, "INVALID_DEVICE_KEY", "installation public key is invalid");
  const keyHash = await hmacHex(env.KEY_PEPPER, normalizeKey(supplied));
  let row = await env.DB.prepare("SELECT * FROM license_keys WHERE key_hash=?").bind(keyHash).first<Row>();
  if (!row) throw new HttpError(404, "INVALID_KEY", "activation key is invalid");
  if (["banned", "refunded", "refund_requested"].includes(String(row.status))) throw new HttpError(403, "KEY_BLOCKED", `activation key is ${row.status}`);
  const current = new Date();
  const currentTime = current.toISOString().replace(/\.\d{3}Z$/, "+00:00");
  if (row.status === "active") {
    if (row.install_id !== installId || row.device_public_key !== publicKey) throw new HttpError(409, "KEY_ALREADY_USED", "activation key is already bound to another installation");
  } else if (row.status === "unused") {
    const deadline = addDays(current, Number(row.refund_days));
    const result = await env.DB.prepare(`UPDATE license_keys SET status='active',activated_at=?,refund_deadline=?,install_id=?,device_public_key=?,last_seen_at=?,revoked_at=NULL,revoke_reason=''
      WHERE id=? AND status='unused'`).bind(currentTime, deadline, installId, publicKey, currentTime, row.id).run();
    if (Number(result.meta.changes || 0) !== 1) throw new HttpError(409, "ACTIVATION_RACE", "activation was claimed by another request");
    await audit(env, String(row.id), "key_activated", "client", "", {install_id: installId}).run();
    row = (await env.DB.prepare("SELECT * FROM license_keys WHERE id=?").bind(row.id).first<Row>())!;
  }
  const token = b64url(await hmacBytes(env.TOKEN_SECRET, `${row.id}\n${installId}\n${publicKey}`));
  await env.DB.prepare("UPDATE license_keys SET activation_token_hash=?,last_seen_at=? WHERE id=?").bind(await sha256(token), currentTime, row.id).run();
  return json(200, {
    ok: true,
    status: "active",
    activation_token: token,
    lease: await issueLease(env, String(row.id), installId, current),
    refund_deadline: row.refund_deadline,
    refund_days: row.refund_days,
  });
}

async function authenticatedProof(request: Request, env: Env, expectedAction: string): Promise<{row: Row; proof: Row; nonce: string; now: Date}> {
  const input = await body(request);
  const token = text(input.activation_token, "activation_token", 128, true);
  const proof = input.proof;
  const signature = input.signature;
  if (!proof || Array.isArray(proof) || typeof proof !== "object" || typeof signature !== "string") throw new HttpError(400, "MISSING_PROOF", "signed installation proof is required");
  const message = proof as Row;
  const required = ["action", "activation_token", "install_id", "nonce", "timestamp"];
  if (Object.keys(message).sort().join(",") !== required.join(",") || message.action !== expectedAction || message.activation_token !== token) throw new HttpError(400, "INVALID_PROOF", "installation proof does not match request");
  const installId = text(message.install_id, "install_id", 96, true);
  const nonce = text(message.nonce, "nonce", 128, true);
  const timestamp = Date.parse(text(message.timestamp, "timestamp", 64, true));
  if (!Number.isFinite(timestamp)) throw new HttpError(400, "INVALID_TIMESTAMP", "proof timestamp is invalid");
  const current = new Date();
  if (Math.abs(current.getTime() - timestamp) > 300_000) throw new HttpError(401, "STALE_PROOF", "installation proof is outside the five-minute window");
  const row = await env.DB.prepare("SELECT * FROM license_keys WHERE activation_token_hash=?").bind(await sha256(token)).first<Row>();
  if (!row || row.install_id !== installId) throw new HttpError(401, "INVALID_TOKEN", "activation token or installation does not match");
  try {
    const key = await crypto.subtle.importKey("raw", fromB64url(String(row.device_public_key)), {name: "Ed25519"}, false, ["verify"]);
    const valid = await crypto.subtle.verify({name: "Ed25519"}, key, fromB64url(signature), encoder.encode(canonical(message)));
    if (!valid) throw new Error();
  } catch {
    throw new HttpError(401, "INVALID_SIGNATURE", "installation signature is invalid");
  }
  return {row, proof: message, nonce, now: current};
}

async function consumeNonce(env: Env, row: Row, nonce: string, current: Date, statements: D1PreparedStatement[]): Promise<void> {
  const used = current.toISOString().replace(/\.\d{3}Z$/, "+00:00");
  statements.unshift(env.DB.prepare("DELETE FROM request_nonces WHERE expires_at<=?").bind(used));
  statements.push(env.DB.prepare("INSERT INTO request_nonces(nonce,license_key_id,used_at,expires_at) VALUES(?,?,?,?)")
    .bind(nonce, row.id, used, addHours(current, 1 / 6)));
  try { await env.DB.batch(statements); }
  catch (error) {
    if (String(error).toLowerCase().includes("unique")) throw new HttpError(409, "REPLAYED_PROOF", "installation proof nonce was already used");
    throw error;
  }
}

async function refreshLease(request: Request, env: Env): Promise<Response> {
  const verified = await authenticatedProof(request, env, "refresh");
  if (verified.row.status !== "active") throw new HttpError(403, "KEY_BLOCKED", `license key is ${verified.row.status}`);
  const current = verified.now.toISOString().replace(/\.\d{3}Z$/, "+00:00");
  await consumeNonce(env, verified.row, verified.nonce, verified.now, [
    env.DB.prepare("UPDATE license_keys SET last_seen_at=? WHERE id=?").bind(current, verified.row.id),
    audit(env, String(verified.row.id), "lease_refreshed", "client"),
  ]);
  return json(200, {ok: true, status: "active", lease: await issueLease(env, String(verified.row.id), String(verified.row.install_id), verified.now)});
}

async function requestClientRefund(request: Request, env: Env): Promise<Response> {
  await authenticatedProof(request, env, "refund_request");
  throw new HttpError(409, "SELF_SERVICE_REFUND_UNAVAILABLE", "数字化商品交付后不提供自助无理由退款。重复付款、无法激活或重大功能故障请联系售后QQ群 923937311 处理。");
}

async function listOrders(url: URL, env: Env): Promise<Response> {
  const status = url.searchParams.get("status") || "";
  if (status && !ORDER_STATES.has(status)) throw new HttpError(400, "INVALID_STATUS", "unknown order status");
  const limit = Math.max(1, Math.min(Number(url.searchParams.get("limit") || 100), 500));
  const statement = status ? env.DB.prepare("SELECT * FROM orders WHERE status=? ORDER BY created_at DESC LIMIT ?").bind(status, limit)
    : env.DB.prepare("SELECT * FROM orders ORDER BY created_at DESC LIMIT ?").bind(limit);
  const rows = (await statement.all<Row>()).results;
  return json(200, {ok: true, orders: await Promise.all(rows.map(row => orderValue(env, row, false)))});
}

async function getAdminOrder(id: string, env: Env): Promise<Row> {
  const row = await env.DB.prepare("SELECT * FROM orders WHERE id=?").bind(id).first<Row>();
  if (!row) throw new HttpError(404, "ORDER_NOT_FOUND", "order not found");
  const result = await orderValue(env, row, false);
  const events = (await env.DB.prepare("SELECT id,event,actor,reason,metadata_json,created_at FROM order_audit_events WHERE order_id=? ORDER BY created_at DESC LIMIT 100").bind(id).all<Row>()).results;
  result.audit_events = events.map(event => ({...event, metadata: JSON.parse(String(event.metadata_json || "{}")), metadata_json: undefined}));
  return result;
}

async function adminOrderAction(request: Request, env: Env, id: string, action: string): Promise<Response> {
  const input = await body(request);
  const reason = text(input.reason, "reason", 500);
  let row = await env.DB.prepare("SELECT * FROM orders WHERE id=?").bind(id).first<Row>();
  if (!row) throw new HttpError(404, "ORDER_NOT_FOUND", "order not found");
  const current = String(row.status);
  const time = nowIso();
  let plaintext = "";
  if (action === "confirm-and-deliver") {
    if (current !== "delivered") {
      if (current !== "payment_submitted") throw new HttpError(409, "INVALID_STATE", `order cannot be auto-delivered from ${current}`);
      plaintext = await orderActivationKey(env, id);
      const keyId = await orderLicenseKeyId(id);
      try {
        await env.DB.batch([
          env.DB.prepare(`INSERT INTO license_keys(id,key_hash,key_suffix,status,label,customer_ref,refund_days,product_id,created_at,sent_at)
            VALUES(?,?,?,'unused','购买页自动发货',?,?,?,?,?)`).bind(keyId, await hmacHex(env.KEY_PEPPER, plaintext), plaintext.slice(-4), id, Number(row.refund_days), env.PRODUCT_ID, time, time),
          env.DB.prepare(`UPDATE orders SET status='delivered',paid_at=?,delivered_at=?,updated_at=?,admin_reason='',license_key_id=?,delivery_key_version='derived-v1'
            WHERE id=? AND status='payment_submitted'`).bind(time, time, time, keyId, id),
          audit(env, keyId, "key_created", "admin", "semi-automatic order delivery", {refund_days: row.refund_days}),
          audit(env, keyId, "key_sent", "system", "displayed on authenticated order page"),
          orderAudit(env, id, "payment_confirmed", "admin", reason),
          orderAudit(env, id, "key_issued", "system", "semi-automatic delivery", {license_key_id: keyId}),
          orderAudit(env, id, "order_delivered", "system", "activation key available on authenticated order page"),
        ]);
      } catch (error) {
        const fresh = await env.DB.prepare("SELECT status,delivery_key_version FROM orders WHERE id=?").bind(id).first<Row>();
        if (fresh?.status !== "delivered" || fresh.delivery_key_version !== "derived-v1") throw error;
      }
    }
  } else if (action === "confirm-payment") {
    if (!["paid", "key_issued", "delivered", "refund_requested", "refunded"].includes(current)) {
      if (current !== "payment_submitted") throw new HttpError(409, "INVALID_STATE", `payment cannot be confirmed from ${current}`);
      await env.DB.batch([
        env.DB.prepare("UPDATE orders SET status='paid',paid_at=?,updated_at=?,admin_reason='' WHERE id=? AND status='payment_submitted'").bind(time, time, id),
        orderAudit(env, id, "payment_confirmed", "admin", reason),
      ]);
    }
  } else if (action === "reject-payment") {
    if (current !== "payment_rejected") {
      if (current !== "payment_submitted") throw new HttpError(409, "INVALID_STATE", `payment cannot be rejected from ${current}`);
      await env.DB.batch([
        env.DB.prepare("UPDATE orders SET status='payment_rejected',updated_at=?,admin_reason=? WHERE id=? AND status='payment_submitted'").bind(time, reason || "payment could not be verified", id),
        orderAudit(env, id, "payment_rejected", "admin", reason || "payment could not be verified"),
      ]);
    }
  } else if (action === "issue") {
    if (!["key_issued", "delivered", "refund_requested", "refunded"].includes(current)) {
      if (current !== "paid") throw new HttpError(409, "INVALID_STATE", `key cannot be issued from ${current}`);
      plaintext = activationKey();
      const keyId = randomId("lfkey_");
      try {
        await env.DB.batch([
          env.DB.prepare(`INSERT INTO license_keys(id,key_hash,key_suffix,status,label,customer_ref,refund_days,product_id,created_at)
            VALUES(?,?,?,'unused','购买页订单',?,?,?,?)`).bind(keyId, await hmacHex(env.KEY_PEPPER, plaintext), plaintext.slice(-4), id, Number(row.refund_days), env.PRODUCT_ID, time),
          env.DB.prepare("UPDATE orders SET status='key_issued',license_key_id=?,updated_at=? WHERE id=? AND status='paid'").bind(keyId, time, id),
          audit(env, keyId, "key_created", "admin", "", {refund_days: row.refund_days}),
          orderAudit(env, id, "key_issued", "admin", "", {license_key_id: keyId}),
        ]);
      } catch (error) {
        const fresh = await env.DB.prepare("SELECT status FROM orders WHERE id=?").bind(id).first<Row>();
        if (fresh?.status === "key_issued") plaintext = "";
        else throw error;
      }
    }
  } else if (action === "deliver") {
    if (current !== "delivered") {
      if (current !== "key_issued") throw new HttpError(409, "INVALID_STATE", `order cannot be delivered from ${current}`);
      const statements = [
        env.DB.prepare("UPDATE orders SET status='delivered',delivered_at=?,updated_at=? WHERE id=? AND status='key_issued'").bind(time, time, id),
        orderAudit(env, id, "order_delivered", "admin", reason),
      ];
      if (row.license_key_id) statements.push(
        env.DB.prepare("UPDATE license_keys SET sent_at=COALESCE(sent_at,?) WHERE id=?").bind(time, row.license_key_id),
        audit(env, String(row.license_key_id), "key_sent", "admin", "via order delivery"),
      );
      await env.DB.batch(statements);
    }
  } else if (action === "refund") {
    if (current !== "refunded") {
      if (!["paid", "key_issued", "delivered", "refund_requested"].includes(current)) throw new HttpError(409, "INVALID_STATE", `refund cannot be completed from ${current}`);
      const statements = [
        env.DB.prepare("UPDATE orders SET status='refunded',refunded_at=?,updated_at=?,admin_reason=? WHERE id=?").bind(time, time, reason || "original-route refund completed", id),
        orderAudit(env, id, "refund_completed", "admin", reason || "original-route refund completed"),
      ];
      if (row.license_key_id) statements.push(
        env.DB.prepare("UPDATE license_keys SET status='refunded',revoked_at=?,revoke_reason=? WHERE id=?").bind(time, reason || "original-route refund completed", row.license_key_id),
        audit(env, String(row.license_key_id), "refund_completed", "admin", reason || "original-route refund completed"),
      );
      await env.DB.batch(statements);
    }
  } else throw new HttpError(404, "UNKNOWN_ACTION", "unknown order action");
  row = (await env.DB.prepare("SELECT * FROM orders WHERE id=?").bind(id).first<Row>())!;
  const response: Row = {ok: true, order: await getAdminOrder(id, env)};
  if (plaintext && action !== "confirm-and-deliver") {
    response.activation_key = plaintext;
    response.warning = "明文密钥只返回这一次，请发送后立即标记订单已交付。";
  }
  return json(200, response);
}

async function listKeys(url: URL, env: Env): Promise<Response> {
  const status = url.searchParams.get("status") || "";
  if (status && !KEY_STATES.has(status)) throw new HttpError(400, "INVALID_STATUS", "unknown license-key status");
  const limit = Math.max(1, Math.min(Number(url.searchParams.get("limit") || 100), 500));
  const statement = status ? env.DB.prepare("SELECT * FROM license_keys WHERE status=? ORDER BY created_at DESC LIMIT ?").bind(status, limit)
    : env.DB.prepare("SELECT * FROM license_keys ORDER BY created_at DESC LIMIT ?").bind(limit);
  return json(200, {ok: true, keys: (await statement.all<Row>()).results.map(publicKey)});
}

async function getAdminKey(id: string, env: Env): Promise<Row> {
  const row = await env.DB.prepare("SELECT * FROM license_keys WHERE id=?").bind(id).first<Row>();
  if (!row) throw new HttpError(404, "KEY_NOT_FOUND", "license key not found");
  const result = publicKey(row);
  const events = (await env.DB.prepare("SELECT id,event,actor,reason,metadata_json,created_at FROM audit_events WHERE license_key_id=? ORDER BY created_at DESC LIMIT 100").bind(id).all<Row>()).results;
  result.audit_events = events.map(event => ({...event, metadata: JSON.parse(String(event.metadata_json || "{}")), metadata_json: undefined}));
  return result;
}

async function createKey(request: Request, env: Env): Promise<Response> {
  const input = await body(request);
  const refundDays = Number(input.refund_days ?? 7);
  if (![3, 7].includes(refundDays)) throw new HttpError(400, "INVALID_REFUND_DAYS", "refund_days must be 3 or 7");
  const plain = activationKey();
  const id = randomId("lfkey_");
  const current = nowIso();
  await env.DB.batch([
    env.DB.prepare(`INSERT INTO license_keys(id,key_hash,key_suffix,status,label,customer_ref,refund_days,product_id,created_at)
      VALUES(?,?,?,'unused',?,?,?,?,?)`).bind(id, await hmacHex(env.KEY_PEPPER, plain), plain.slice(-4), text(input.label, "label", 120), text(input.customer_ref, "customer_ref", 120), refundDays, env.PRODUCT_ID, current),
    audit(env, id, "key_created", "admin", "", {refund_days: refundDays}),
  ]);
  return json(201, {ok: true, activation_key: plain, warning: "明文密钥只返回这一次，请立即通过你的私密渠道发送给用户。", key: await getAdminKey(id, env)});
}

async function adminKeyAction(request: Request, env: Env, id: string, action: string): Promise<Response> {
  const input = await body(request);
  const reason = text(input.reason, "reason", 500);
  const row = await env.DB.prepare("SELECT * FROM license_keys WHERE id=?").bind(id).first<Row>();
  if (!row) throw new HttpError(404, "KEY_NOT_FOUND", "license key not found");
  const current = String(row.status);
  const time = nowIso();
  if (action === "mark-sent") {
    if (!row.sent_at) await env.DB.batch([
      env.DB.prepare("UPDATE license_keys SET sent_at=? WHERE id=?").bind(time, id), audit(env, id, "key_sent", "admin"),
    ]);
  } else if (action === "ban") {
    if (current !== "banned") await env.DB.batch([
      env.DB.prepare("UPDATE license_keys SET status='banned',revoked_at=?,revoke_reason=? WHERE id=?").bind(time, reason || "policy violation", id),
      audit(env, id, "key_banned", "admin", reason || "policy violation"),
    ]);
  } else if (action === "refund") {
    if (current !== "refunded") {
      if (!["unused", "active", "refund_requested", "banned"].includes(current)) throw new HttpError(409, "INVALID_STATE", `refund cannot be completed from ${current}`);
      await env.DB.batch([
        env.DB.prepare("UPDATE license_keys SET status='refunded',revoked_at=?,revoke_reason=? WHERE id=?").bind(time, reason || "refund completed", id),
        env.DB.prepare("UPDATE orders SET status='refunded',refunded_at=?,updated_at=?,admin_reason=? WHERE license_key_id=? AND status!='refunded'").bind(time, time, reason || "refund completed", id),
        audit(env, id, "refund_completed", "admin", reason || "refund completed"),
      ]);
    }
  } else if (action === "restore") {
    if (!["banned", "refund_requested"].includes(current)) throw new HttpError(409, "INVALID_STATE", `key cannot be restored from ${current}`);
    const target = row.install_id ? "active" : "unused";
    await env.DB.batch([
      env.DB.prepare("UPDATE license_keys SET status=?,revoked_at=NULL,revoke_reason='' WHERE id=?").bind(target, id),
      audit(env, id, "key_restored", "admin", reason, {status: target}),
    ]);
  } else if (action === "reset-binding") {
    if (!["active", "banned"].includes(current)) throw new HttpError(409, "INVALID_STATE", `binding cannot be reset from ${current}`);
    await env.DB.batch([
      env.DB.prepare(`UPDATE license_keys SET status='unused',activated_at=NULL,refund_deadline=NULL,install_id=NULL,device_public_key=NULL,
        activation_token_hash=NULL,last_seen_at=NULL,revoked_at=NULL,revoke_reason='' WHERE id=?`).bind(id),
      audit(env, id, "binding_reset", "admin", reason || "installation replacement"),
    ]);
  } else throw new HttpError(404, "UNKNOWN_ACTION", "unknown admin action");
  return json(200, {ok: true, key: await getAdminKey(id, env)});
}

async function purgePersonalData(request: Request, env: Env): Promise<Response> {
  const input = await body(request);
  const days = Number(input.retention_days ?? 90);
  if (days < 30 || days > 365) throw new HttpError(400, "INVALID_RETENTION", "retention_days must be between 30 and 365");
  const cutoff = new Date(Date.now() - days * 86400_000).toISOString().replace(/\.\d{3}Z$/, "+00:00");
  const rows = (await env.DB.prepare(`SELECT id FROM orders WHERE (contact!='' OR payment_reference!='' OR payment_claimed_at IS NOT NULL)
    AND ((status IN ('delivered','refunded') AND COALESCE(refunded_at,delivered_at,updated_at)<=?)
    OR (status IN ('payment_pending','payment_rejected') AND created_at<=?))`).bind(cutoff, cutoff).all<Row>()).results;
  if (rows.length) await env.DB.batch(rows.flatMap(row => [
    env.DB.prepare("UPDATE orders SET contact='',payment_reference='',payment_claimed_at=NULL,updated_at=? WHERE id=?").bind(nowIso(), row.id),
    orderAudit(env, String(row.id), "personal_data_purged", "admin", "", {retention_days: days}),
  ]));
  return json(200, {ok: true, purged_orders: rows.length, cutoff});
}

async function staticAsset(request: Request, env: Env, pathname: string): Promise<Response> {
  const url = new URL(request.url);
  if (pathname === "/") return Response.redirect(`${url.origin}/buy`, 302);
  if (pathname === "/buy" || pathname === "/buy/") url.pathname = "/buy/index.html";
  if (pathname === "/admin" || pathname === "/admin/") url.pathname = "/admin/index.html";
  const asset = await env.ASSETS.fetch(new Request(url.toString(), request));
  const headers = new Headers(asset.headers);
  headers.set("Content-Security-Policy", "default-src 'self'; connect-src 'self'; img-src 'self' data:; script-src 'self'; style-src 'self'; object-src 'none'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'");
  headers.set("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
  headers.set("Referrer-Policy", "no-referrer");
  headers.set("X-Content-Type-Options", "nosniff");
  headers.set("X-Frame-Options", "DENY");
  if (url.pathname.endsWith(".html")) headers.set("Cache-Control", "no-cache");
  return new Response(asset.body, {status: asset.status, statusText: asset.statusText, headers});
}

async function route(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);
  const path = url.pathname;
  if (request.method === "GET" && path === "/health") return json(200, {ok: true, service: "lab-factory-commercial-worker", time: nowIso()});
  if (request.method === "GET" && path === "/api/checkout/config") return checkoutConfig(env);
  if (request.method === "GET" && path === "/api/order") return getOrder(request, env);
  if (request.method === "POST" && path === "/api/orders") return createOrder(request, env);
  if (request.method === "POST" && path === "/api/order/payment") return submitPayment(request, env);
  if (request.method === "POST" && path === "/api/order/refund") return requestOrderRefund(request, env);
  if (request.method === "POST" && path === "/api/activate") return activate(request, env);
  if (request.method === "POST" && path === "/api/lease/refresh") return refreshLease(request, env);
  if (request.method === "POST" && path === "/api/refunds/request") return requestClientRefund(request, env);

  if (request.method === "GET" && (path === "/admin/control.js" || path === "/admin/control.css")) {
    return staticAsset(request, env, path);
  }

  if (path.startsWith("/admin/") && path !== "/admin/index.html") {
    await requireAdmin(request, env);
    if (request.method === "GET" && path === "/admin/orders") return listOrders(url, env);
    if (request.method === "POST" && path === "/admin/orders/purge-personal-data") return purgePersonalData(request, env);
    const orderMatch = path.match(/^\/admin\/orders\/(lforder_[a-f0-9]+)(?:\/([a-z-]+))?$/);
    if (orderMatch) {
      if (request.method === "GET" && !orderMatch[2]) return json(200, {ok: true, order: await getAdminOrder(orderMatch[1], env)});
      if (request.method === "POST" && orderMatch[2]) return adminOrderAction(request, env, orderMatch[1], orderMatch[2]);
    }
    if (request.method === "GET" && path === "/admin/keys") return listKeys(url, env);
    if (request.method === "POST" && path === "/admin/keys") return createKey(request, env);
    const keyMatch = path.match(/^\/admin\/keys\/(lfkey_[a-f0-9]+)(?:\/([a-z-]+))?$/);
    if (keyMatch) {
      if (request.method === "GET" && !keyMatch[2]) return json(200, {ok: true, key: await getAdminKey(keyMatch[1], env)});
      if (request.method === "POST" && keyMatch[2]) return adminKeyAction(request, env, keyMatch[1], keyMatch[2]);
    }
    throw new HttpError(404, "NOT_FOUND", "not found");
  }
  if (request.method === "GET") return staticAsset(request, env, path);
  throw new HttpError(404, "NOT_FOUND", "not found");
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    try {
      return await route(request, env);
    } catch (error) {
      if (error instanceof HttpError) return json(error.status, {ok: false, error: {code: error.code, message: error.message}});
      console.error(error);
      return json(500, {ok: false, error: {code: "INTERNAL_ERROR", message: "internal server error"}});
    }
  },
};
