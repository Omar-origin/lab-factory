interface Env {
  DB: D1Database;
  ASSETS: Fetcher;
  ADMIN_TOKEN: string;
  KEY_PEPPER: string;
  TOKEN_SECRET: string;
  LEASE_PRIVATE_KEY_B64: string;
  PRODUCT_ID: string;
  PRICE_CENTS: string;
  PERMANENT_PRICE_CENTS?: string;
  TEAM_PRICE_CENTS?: string;
  MAJOR_UPGRADE_PRICE_CENTS?: string;
  CURRENT_MAJOR_VERSION?: string;
  REFUND_DAYS: string;
  SUPPORT_CONTACT: string;
  LEASE_KEY_ID: string;
  APP_ORIGIN?: string;
  BREVO_API_KEY?: string;
  BREVO_SENDER_EMAIL?: string;
  BREVO_SENDER_NAME?: string;
  TURNSTILE_SITE_KEY?: string;
  TURNSTILE_SECRET?: string;
  DEV_ALLOW_AUTH_BYPASS?: string;
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
const LICENSE_PLANS = new Set(["experience", "permanent", "team"]);
const SESSION_COOKIE = "lf_session";
const SESSION_DAYS = 30;
const COMMISSION_RATE_BPS = 2000;
// Cloudflare Workers caps PBKDF2 at 100,000 iterations. A server-side HMAC
// pepper is applied before PBKDF2 so a leaked D1 password table is insufficient.
const PASSWORD_ITERATIONS = 100_000;
const LOGIN_FAILURE_LIMIT = 5;
const LOGIN_LOCK_MINUTES = 15;
const ACCOUNT_ROLES = new Set(["user", "distributor_admin", "owner"]);
const ADMIN_ROLES = new Set(["distributor_admin", "owner"]);
const EXPERIENCE_UPGRADE_PROMOTION = "experience-upgrade-v1";
const EXPERIENCE_UPGRADE_DISCOUNT_CENTS = 990;

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

async function orderActivationKey(env: Env, orderId: string, seatIndex = 1): Promise<string> {
  return activationKeyFromBytes((await hmacBytes(env.KEY_PEPPER, `order-delivery:v2:${orderId}:seat:${seatIndex}`)).slice(0, 20));
}

async function orderLicenseKeyId(orderId: string, seatIndex = 1): Promise<string> {
  return `lfkey_${(await sha256(`order-license:v2:${orderId}:seat:${seatIndex}`)).slice(0, 32)}`;
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

function jsonWithHeaders(status: number, body: unknown, extraHeaders: Record<string, string>): Response {
  const response = json(status, body);
  for (const [name, value] of Object.entries(extraHeaders)) response.headers.set(name, value);
  return response;
}

function cookieValue(request: Request, name: string): string {
  const raw = request.headers.get("Cookie") || "";
  for (const item of raw.split(";")) {
    const [key, ...parts] = item.trim().split("=");
    if (key === name) return decodeURIComponent(parts.join("="));
  }
  return "";
}

function sessionCookie(token: string, maxAge: number): string {
  return `${SESSION_COOKIE}=${encodeURIComponent(token)}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${maxAge}`;
}

function normalizeEmail(value: unknown): string {
  const email = text(value, "email", 254, true).toLowerCase();
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) throw new HttpError(400, "INVALID_EMAIL", "请输入有效的邮箱地址");
  return email;
}

function passwordValue(value: unknown, email = ""): string {
  if (typeof value !== "string") throw new HttpError(400, "INVALID_PASSWORD", "请输入密码");
  const byteLength = encoder.encode(value).byteLength;
  if (value.length < 8 || value.length > 64 || byteLength > 128) throw new HttpError(400, "WEAK_PASSWORD", "密码需为 8–64 个字符");
  if (!/[A-Za-z]/.test(value) || !/\d/.test(value)) throw new HttpError(400, "WEAK_PASSWORD", "密码必须同时包含字母和数字");
  if (email && (value.toLowerCase() === email || value.toLowerCase() === email.split("@")[0])) throw new HttpError(400, "WEAK_PASSWORD", "密码不能与邮箱相同");
  return value;
}

async function passwordDigest(env: Env, password: string, salt: Uint8Array, iterations: number): Promise<string> {
  const pepperedPassword = await hmacBytes(env.TOKEN_SECRET, `password:v1:${password}`);
  const key = await crypto.subtle.importKey("raw", Uint8Array.from(pepperedPassword), "PBKDF2", false, ["deriveBits"]);
  const result = await crypto.subtle.deriveBits({name: "PBKDF2", hash: "SHA-256", salt: Uint8Array.from(salt), iterations}, key, 256);
  return b64url(new Uint8Array(result));
}

async function newPasswordRecord(env: Env, password: string): Promise<Row> {
  const salt = new Uint8Array(16);
  crypto.getRandomValues(salt);
  return {hash: await passwordDigest(env, password, salt, PASSWORD_ITERATIONS), salt: b64url(salt), iterations: PASSWORD_ITERATIONS};
}

async function createUserSession(env: Env, user: Row): Promise<Response> {
  const current = nowIso();
  const sessionToken = randomToken();
  await env.DB.prepare("INSERT INTO user_sessions(id,user_id,token_hash,expires_at,created_at,last_seen_at) VALUES(?,?,?,?,?,?)")
    .bind(randomId("lfsession_"), user.id, await sha256(sessionToken), addDays(new Date(), SESSION_DAYS), current, current).run();
  return jsonWithHeaders(200, {ok: true, user: {id: user.id, email: user.email, display_name: user.display_name, role: userRole(user)}}, {"Set-Cookie": sessionCookie(sessionToken, SESSION_DAYS * 86400)});
}

function planDefinition(env: Env, plan: string): Row {
  const major = Math.max(1, Number(env.CURRENT_MAJOR_VERSION || "1"));
  if (plan === "experience") return {id: plan, name: "9.9 体验版", amount_cents: Number(env.PRICE_CENTS || "990"), usage_limit: 3, skill_condensation: false, seat_count: 1, major_version: major, free_major_updates: false};
  if (plan === "permanent") return {id: plan, name: "当前大版本永久版", amount_cents: Number(env.PERMANENT_PRICE_CENTS || "4990"), usage_limit: null, skill_condensation: true, seat_count: 1, major_version: major, free_major_updates: false, major_upgrade_cents: Number(env.MAJOR_UPGRADE_PRICE_CENTS || "2000")};
  if (plan === "team") return {id: plan, name: "五人共享版", amount_cents: Number(env.TEAM_PRICE_CENTS || "19900"), usage_limit: null, skill_condensation: true, seat_count: 5, major_version: null, free_major_updates: true};
  throw new HttpError(400, "INVALID_PLAN", "unknown plan");
}

async function experienceUpgradeOffer(env: Env, userId: string): Promise<Row> {
  let reservation = await env.DB.prepare("SELECT * FROM promotion_reservations WHERE user_id=? AND promotion_code=?")
    .bind(userId, EXPERIENCE_UPGRADE_PROMOTION).first<Row>();
  if (reservation?.state === "reserved") {
    const reservedOrder = await env.DB.prepare("SELECT status,cancelled_at,expires_at FROM orders WHERE id=?")
      .bind(reservation.reserved_order_id).first<Row>();
    const released = !reservedOrder || Boolean(reservedOrder.cancelled_at)
      || (reservedOrder.expires_at && String(reservedOrder.expires_at) <= nowIso() && ["payment_pending", "payment_rejected"].includes(String(reservedOrder.status)));
    if (released) {
      await env.DB.prepare("DELETE FROM promotion_reservations WHERE user_id=? AND promotion_code=? AND state='reserved'")
        .bind(userId, EXPERIENCE_UPGRADE_PROMOTION).run();
      reservation = null;
    }
  }
  if (reservation) return {eligible: false, state: reservation.state, discount_cents: 0};
  const experience = await env.DB.prepare(`SELECT id FROM orders WHERE user_id=? AND plan='experience'
    AND status IN ('paid','key_issued','delivered','refund_requested') ORDER BY paid_at DESC LIMIT 1`).bind(userId).first<Row>();
  if (!experience) return {eligible: false, state: "not_earned", discount_cents: 0};
  const higherPlan = await env.DB.prepare(`SELECT id FROM orders WHERE user_id=? AND plan IN ('permanent','team')
    AND status IN ('paid','key_issued','delivered','refund_requested') LIMIT 1`).bind(userId).first<Row>();
  if (higherPlan) return {eligible: false, state: "already_upgraded", discount_cents: 0};
  return {eligible: true, state: "available", discount_cents: EXPERIENCE_UPGRADE_DISCOUNT_CENTS, source_order_id: experience.id};
}

async function assertExperienceUpgradeOrder(env: Env, order: Row): Promise<void> {
  if (order.promotion_code !== EXPERIENCE_UPGRADE_PROMOTION) return;
  const reservation = await env.DB.prepare(`SELECT * FROM promotion_reservations
    WHERE user_id=? AND promotion_code=? AND reserved_order_id=? AND state='reserved'`)
    .bind(order.user_id, EXPERIENCE_UPGRADE_PROMOTION, order.id).first<Row>();
  if (!reservation) throw new HttpError(409, "PROMOTION_NOT_RESERVED", "新用户升级优惠已失效，请重新创建订单");
  const source = await env.DB.prepare(`SELECT id FROM orders WHERE id=? AND user_id=? AND plan='experience'
    AND status IN ('paid','key_issued','delivered','refund_requested')`).bind(reservation.source_order_id, order.user_id).first<Row>();
  if (!source) throw new HttpError(409, "PROMOTION_SOURCE_INVALID", "体验版订单已失效，不能继续使用升级优惠");
  const otherUpgrade = await env.DB.prepare(`SELECT id FROM orders WHERE user_id=? AND id!=? AND plan IN ('permanent','team')
    AND status IN ('paid','key_issued','delivered','refund_requested') LIMIT 1`).bind(order.user_id, order.id).first<Row>();
  if (otherUpgrade) throw new HttpError(409, "PROMOTION_ALREADY_USED", "该账号已经有效购买过升级套餐，新用户优惠不可重复使用");
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

async function optionalUser(request: Request, env: Env): Promise<Row | null> {
  const token = cookieValue(request, SESSION_COOKIE);
  if (!token) return null;
  const current = nowIso();
  const row = await env.DB.prepare(`SELECT u.* FROM user_sessions s JOIN users u ON u.id=s.user_id
    WHERE s.token_hash=? AND s.expires_at>? AND u.status='active'`).bind(await sha256(token), current).first<Row>();
  if (row) await env.DB.prepare("UPDATE user_sessions SET last_seen_at=? WHERE token_hash=?").bind(current, await sha256(token)).run();
  return row || null;
}

async function requireUser(request: Request, env: Env): Promise<Row> {
  const user = await optionalUser(request, env);
  if (!user) throw new HttpError(401, "AUTH_REQUIRED", "请先登录账号");
  return user;
}

function userRole(user: Row): string {
  const role = String(user.role || "user");
  return ACCOUNT_ROLES.has(role) ? role : "user";
}

async function requireRole(request: Request, env: Env, roles: Set<string>): Promise<Row> {
  const user = await requireUser(request, env);
  if (!roles.has(userRole(user))) throw new HttpError(403, "ROLE_REQUIRED", "当前账号没有访问中控的权限");
  return user;
}

function adminAudit(env: Env, actor: Row | null, action: string, targetType: string, targetId: string, metadata: Row = {}): D1PreparedStatement {
  return env.DB.prepare("INSERT INTO admin_audit_events(id,actor_user_id,action,target_type,target_id,metadata_json,created_at) VALUES(?,?,?,?,?,?,?)")
    .bind(randomId("lfaaudit_"), actor?.id || null, action, targetType, targetId, JSON.stringify(metadata), nowIso());
}

function ensureSameOrigin(request: Request, env: Env): void {
  const origin = request.headers.get("Origin");
  if (!origin) return;
  const expected = env.APP_ORIGIN || new URL(request.url).origin;
  if (origin !== expected && origin !== new URL(request.url).origin) throw new HttpError(403, "ORIGIN_REJECTED", "request origin is not allowed");
}

async function verifyTurnstile(request: Request, env: Env, token: string, expectedAction: string): Promise<void> {
  if (env.DEV_ALLOW_AUTH_BYPASS === "1" && token === "dev-turnstile") return;
  if (!env.TURNSTILE_SECRET || !env.TURNSTILE_SITE_KEY) throw new HttpError(503, "TURNSTILE_NOT_CONFIGURED", "人机验证尚未配置");
  if (!token || token.length > 2048) throw new HttpError(400, "TURNSTILE_REQUIRED", "请完成人机验证");
  let result: Row;
  try {
    const response = await fetch("https://challenges.cloudflare.com/turnstile/v0/siteverify", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({secret: env.TURNSTILE_SECRET, response: token, remoteip: request.headers.get("CF-Connecting-IP") || undefined, idempotency_key: crypto.randomUUID()}),
    });
    result = await response.json() as Row;
  } catch {
    throw new HttpError(503, "TURNSTILE_UNAVAILABLE", "人机验证服务暂时不可用");
  }
  const allowedHost = new URL(env.APP_ORIGIN || request.url).hostname;
  if (!result.success || (result.action && result.action !== expectedAction) || (result.hostname && result.hostname !== allowedHost)) {
    throw new HttpError(403, "TURNSTILE_FAILED", "人机验证未通过，请重试");
  }
}

async function sendVerificationEmail(env: Env, email: string, code: string, challengeId: string): Promise<void> {
  if (env.DEV_ALLOW_AUTH_BYPASS === "1" && !env.BREVO_API_KEY) return;
  if (!env.BREVO_API_KEY || !env.BREVO_SENDER_EMAIL) throw new HttpError(503, "EMAIL_NOT_CONFIGURED", "登录邮件服务尚未配置");
  const response = await fetch("https://api.brevo.com/v3/smtp/email", {
    method: "POST",
    headers: {"Content-Type": "application/json", "api-key": env.BREVO_API_KEY},
    body: JSON.stringify({
      sender: {email: env.BREVO_SENDER_EMAIL, name: env.BREVO_SENDER_NAME || "Lab Factory"},
      to: [{email}],
      subject: `${code} · Lab Factory 注册验证码`,
      textContent: `你的 Lab Factory 注册验证码是 ${code}。验证码 10 分钟内有效，请勿转发给他人。`,
      htmlContent: `<div style="font-family:Arial,sans-serif;max-width:560px;margin:auto;padding:32px;background:#101411;color:#f4f7f4"><p style="color:#55d6bd;letter-spacing:.12em">LAB FACTORY / VERIFY</p><h1 style="font-size:38px;letter-spacing:.16em">${code}</h1><p>验证码 10 分钟内有效，请勿转发给他人。</p></div>`,
      headers: {"X-Mailin-custom": `challenge:${challengeId}`},
      tags: ["account-register"],
    }),
  });
  if (!response.ok) throw new HttpError(503, "EMAIL_DELIVERY_FAILED", "验证码邮件发送失败，请稍后重试");
}

function loginCode(): string {
  const bytes = new Uint32Array(1);
  crypto.getRandomValues(bytes);
  return String(bytes[0] % 1_000_000).padStart(6, "0");
}

async function startRegistration(request: Request, env: Env): Promise<Response> {
  ensureSameOrigin(request, env);
  const input = await body(request);
  const email = normalizeEmail(input.email);
  passwordValue(input.password, email);
  await verifyTurnstile(request, env, text(input.turnstile_token, "turnstile_token", 2048, true), "register");
  await resolveInviteCode(env, input.invite_code);
  const recent = await env.DB.prepare("SELECT COUNT(*) AS count FROM email_challenges WHERE email=? AND purpose='register' AND created_at>?")
    .bind(email, new Date(Date.now() - 15 * 60_000).toISOString()).first<Row>();
  if (Number(recent?.count || 0) >= 5) throw new HttpError(429, "EMAIL_RATE_LIMITED", "验证码发送过于频繁，请稍后再试");
  const code = loginCode();
  const id = randomId("lfchallenge_");
  const created = nowIso();
  await env.DB.prepare("INSERT INTO email_challenges(id,email,purpose,code_hash,expires_at,created_at) VALUES(?,?,'register',?,?,?)")
    .bind(id, email, await hmacHex(env.TOKEN_SECRET, `${id}:${code}`), addHours(new Date(), 1 / 6), created).run();
  try { await sendVerificationEmail(env, email, code, id); }
  catch (error) {
    await env.DB.prepare("UPDATE email_challenges SET consumed_at=? WHERE id=?").bind(nowIso(), id).run();
    throw error;
  }
  const payload: Row = {ok: true, challenge_id: id, expires_in: 600};
  if (env.DEV_ALLOW_AUTH_BYPASS === "1") payload.dev_code = code;
  return json(200, payload);
}

async function ensureReferralCode(env: Env, userId: string): Promise<string> {
  const existing = await env.DB.prepare("SELECT code FROM referral_codes WHERE user_id=?").bind(userId).first<Row>();
  if (existing) return String(existing.code);
  for (let attempt = 0; attempt < 5; attempt += 1) {
    const bytes = new Uint8Array(5); crypto.getRandomValues(bytes);
    const code = Array.from(bytes, byte => BASE32[byte & 31]).join("");
    try {
      await env.DB.prepare("INSERT INTO referral_codes(code,user_id,created_at) VALUES(?,?,?)").bind(code, userId, nowIso()).run();
      return code;
    } catch (error) { if (!String(error).toLowerCase().includes("unique")) throw error; }
  }
  throw new Error("could not allocate referral code");
}

async function resolveInviteCode(env: Env, rawCode: unknown): Promise<Row | null> {
  const code = text(rawCode, "invite_code", 64).toUpperCase();
  if (!code) return null;
  const referral = await env.DB.prepare(`SELECT r.code,u.id AS user_id FROM referral_codes r JOIN users u ON u.id=r.user_id
    WHERE r.code=? AND u.status='active'`).bind(code).first<Row>();
  if (referral) return {kind: "referral", code, user_id: referral.user_id};
  const hash = await hmacHex(env.TOKEN_SECRET, `admin-invite:v1:${code}`);
  const adminInvite = await env.DB.prepare("SELECT * FROM admin_invites WHERE code_hash=?").bind(hash).first<Row>();
  if (!adminInvite || adminInvite.status !== "active" || String(adminInvite.expires_at) <= nowIso() || Number(adminInvite.use_count) >= Number(adminInvite.max_uses)) {
    throw new HttpError(400, "INVALID_INVITE_CODE", "邀请码无效、已过期或已用完");
  }
  return {...adminInvite, kind: "admin", code};
}

async function verifyRegistration(request: Request, env: Env): Promise<Response> {
  ensureSameOrigin(request, env);
  const input = await body(request);
  const challengeId = text(input.challenge_id, "challenge_id", 96, true);
  const email = normalizeEmail(input.email);
  const password = passwordValue(input.password, email);
  const code = text(input.code, "code", 6, true);
  if (!/^\d{6}$/.test(code)) throw new HttpError(400, "INVALID_CODE", "验证码格式不正确");
  const challenge = await env.DB.prepare("SELECT * FROM email_challenges WHERE id=? AND email=? AND purpose='register'").bind(challengeId, email).first<Row>();
  if (!challenge || challenge.consumed_at || String(challenge.expires_at) <= nowIso()) throw new HttpError(400, "CODE_EXPIRED", "验证码已过期，请重新获取");
  if (Number(challenge.attempts || 0) >= 5) throw new HttpError(429, "CODE_LOCKED", "验证码尝试次数过多，请重新获取");
  const expected = await hmacHex(env.TOKEN_SECRET, `${challengeId}:${code}`);
  if (!(await secureEqual(expected, String(challenge.code_hash)))) {
    await env.DB.prepare("UPDATE email_challenges SET attempts=attempts+1 WHERE id=?").bind(challengeId).run();
    throw new HttpError(400, "CODE_INCORRECT", "验证码不正确");
  }
  const current = nowIso();
  let user = await env.DB.prepare("SELECT * FROM users WHERE email=?").bind(email).first<Row>();
  const invitation = await resolveInviteCode(env, input.invite_code ?? input.referral_code);
  const referralCode = invitation?.kind === "referral" ? String(invitation.code) : "";
  if (user?.password_hash) throw new HttpError(409, "ACCOUNT_EXISTS", "该邮箱已经注册，请直接登录");
  const passwordRecord = await newPasswordRecord(env, password);
  if (!user) {
    const userId = randomId("lfuser_");
    const inviterId = invitation?.kind === "referral" ? invitation.user_id : null;
    const role = invitation?.kind === "admin" ? String(invitation.role) : "user";
    const adminStatements = invitation?.kind === "admin" ? [
      env.DB.prepare("UPDATE admin_invites SET use_count=use_count+1,status=CASE WHEN use_count+1>=max_uses THEN 'exhausted' ELSE status END WHERE id=? AND status='active' AND use_count<max_uses").bind(invitation.id),
      env.DB.prepare("INSERT INTO admin_invite_redemptions(invite_id,user_id,redeemed_at) VALUES(?,?,?)").bind(invitation.id, userId, current),
      adminAudit(env, null, "admin_invite_redeemed", "user", userId, {role, invite_id: invitation.id}),
    ] : [];
    await env.DB.batch([
      env.DB.prepare(`INSERT INTO users(id,email,invited_by_user_id,verified_at,created_at,updated_at,password_hash,password_salt,password_iterations,password_set_at,role,role_updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)`).bind(userId, email, inviterId || null, current, current, current, passwordRecord.hash, passwordRecord.salt, passwordRecord.iterations, current, role, role === "user" ? null : current),
      env.DB.prepare("UPDATE email_challenges SET consumed_at=? WHERE id=?").bind(current, challengeId),
      ...(inviterId ? [env.DB.prepare("INSERT INTO referral_attributions(invited_user_id,referrer_user_id,code,created_at) VALUES(?,?,?,?)").bind(userId, inviterId, referralCode, current)] : []),
      ...adminStatements,
    ]);
    user = await env.DB.prepare("SELECT * FROM users WHERE id=?").bind(userId).first<Row>();
  } else {
    const role = invitation?.kind === "admin" ? String(invitation.role) : userRole(user);
    await env.DB.batch([
      env.DB.prepare(`UPDATE users SET password_hash=?,password_salt=?,password_iterations=?,password_set_at=?,failed_login_count=0,login_locked_until=NULL,updated_at=? WHERE id=? AND password_hash IS NULL`)
        .bind(passwordRecord.hash, passwordRecord.salt, passwordRecord.iterations, current, current, user.id),
      env.DB.prepare("UPDATE email_challenges SET consumed_at=? WHERE id=?").bind(current, challengeId),
      ...(invitation?.kind === "admin" ? [
        env.DB.prepare("UPDATE users SET role=?,role_updated_at=?,updated_at=? WHERE id=?").bind(role, current, current, user.id),
        env.DB.prepare("UPDATE admin_invites SET use_count=use_count+1,status=CASE WHEN use_count+1>=max_uses THEN 'exhausted' ELSE status END WHERE id=? AND status='active' AND use_count<max_uses").bind(invitation.id),
        env.DB.prepare("INSERT INTO admin_invite_redemptions(invite_id,user_id,redeemed_at) VALUES(?,?,?)").bind(invitation.id, user.id, current),
        adminAudit(env, null, "admin_invite_redeemed", "user", String(user.id), {role, invite_id: invitation.id}),
      ] : []),
    ]);
    user = await env.DB.prepare("SELECT * FROM users WHERE id=?").bind(user.id).first<Row>();
  }
  if (user!.status !== "active") throw new HttpError(403, "ACCOUNT_DISABLED", "账号已停用，请联系售后");
  await ensureReferralCode(env, String(user!.id));
  return createUserSession(env, user!);
}

async function passwordLogin(request: Request, env: Env): Promise<Response> {
  ensureSameOrigin(request, env);
  const input = await body(request);
  const email = normalizeEmail(input.email);
  const password = passwordValue(input.password);
  await verifyTurnstile(request, env, text(input.turnstile_token, "turnstile_token", 2048, true), "login");
  let user = await env.DB.prepare("SELECT * FROM users WHERE email=?").bind(email).first<Row>();
  if (user?.login_locked_until && String(user.login_locked_until) > nowIso()) throw new HttpError(429, "LOGIN_LOCKED", "登录尝试次数过多，请 15 分钟后再试");
  const fallbackSalt = (await hmacBytes(env.TOKEN_SECRET, "password-login-fallback")).slice(0, 16);
  const salt = user?.password_salt ? fromB64url(String(user.password_salt)) : fallbackSalt;
  const iterations = Number(user?.password_iterations || PASSWORD_ITERATIONS);
  const candidate = await passwordDigest(env, password, salt, iterations);
  const matched = Boolean(user?.password_hash) && await secureEqual(candidate, String(user!.password_hash));
  if (!matched) {
    if (user) {
      const failures = Number(user.failed_login_count || 0) + 1;
      const lockedUntil = failures >= LOGIN_FAILURE_LIMIT ? addHours(new Date(), LOGIN_LOCK_MINUTES / 60) : null;
      await env.DB.prepare("UPDATE users SET failed_login_count=?,login_locked_until=?,updated_at=? WHERE id=?")
        .bind(failures >= LOGIN_FAILURE_LIMIT ? 0 : failures, lockedUntil, nowIso(), user.id).run();
    }
    throw new HttpError(401, "INVALID_CREDENTIALS", "邮箱或密码不正确");
  }
  if (user!.status !== "active") throw new HttpError(403, "ACCOUNT_DISABLED", "账号已停用，请联系售后");
  await env.DB.prepare("UPDATE users SET failed_login_count=0,login_locked_until=NULL,updated_at=? WHERE id=?").bind(nowIso(), user!.id).run();
  user = await env.DB.prepare("SELECT * FROM users WHERE id=?").bind(user!.id).first<Row>();
  return createUserSession(env, user!);
}

async function logout(request: Request, env: Env): Promise<Response> {
  ensureSameOrigin(request, env);
  const token = cookieValue(request, SESSION_COOKIE);
  if (token) await env.DB.prepare("DELETE FROM user_sessions WHERE token_hash=?").bind(await sha256(token)).run();
  return jsonWithHeaders(200, {ok: true}, {"Set-Cookie": sessionCookie("", 0)});
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
  result.effective_status = row.cancelled_at ? "cancelled" : (row.expires_at && String(row.expires_at) <= nowIso() && ["payment_pending", "payment_rejected"].includes(String(row.status)) ? "expired" : row.status);
  if (row.license_key_id) {
    const key = await env.DB.prepare("SELECT status,key_suffix,refund_deadline,activated_at FROM license_keys WHERE id=?").bind(row.license_key_id).first<Row>();
    if (key) result.license = key;
  }
  if (publicView && row.status === "delivered" && row.delivery_key_version === "derived-v1") {
    result.activation_key = activationKeyFromBytes((await hmacBytes(env.KEY_PEPPER, `order-delivery:v1:${row.id}`)).slice(0, 20));
  }
  if (publicView && row.status === "delivered" && row.delivery_key_version === "derived-v2") {
    const seats = Math.max(1, Number((await env.DB.prepare("SELECT seat_count FROM entitlements WHERE order_id=?").bind(row.id).first<Row>())?.seat_count || 1));
    result.activation_keys = await Promise.all(Array.from({length: seats}, (_, index) => orderActivationKey(env, String(row.id), index + 1)));
    result.activation_key = (result.activation_keys as string[])[0];
  }
  return result;
}

async function checkoutConfig(request: Request, env: Env): Promise<Response> {
  const user = await optionalUser(request, env);
  const upgradeOffer = user ? await experienceUpgradeOffer(env, String(user.id)) : {eligible: false, state: "signed_out", discount_cents: 0};
  const plans = [planDefinition(env, "experience"), planDefinition(env, "permanent"), planDefinition(env, "team")].map(plan => {
    const discount = upgradeOffer.eligible && plan.id !== "experience" ? Number(upgradeOffer.discount_cents) : 0;
    return {...plan, checkout_amount_cents: Number(plan.amount_cents) - discount, promotion_discount_cents: discount};
  });
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
      entitlement: "体验版可生成 3 份报告，不包含 Skill 凝练",
    },
    plans,
    new_customer_upgrade_offer: upgradeOffer,
    commission_rate_percent: 20,
    current_major_version: Number(env.CURRENT_MAJOR_VERSION || "1"),
    major_upgrade_cents: Number(env.MAJOR_UPGRADE_PRICE_CENTS || "2000"),
    turnstile_site_key: env.TURNSTILE_SITE_KEY || "",
    payment_providers: [{
      id: "alipay",
      label: "支付宝经营码",
      payment_url: "",
      instructions: "使用支付宝扫描经营码，并按订单金额付款",
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
  const user = await optionalUser(request, env);
  const contact = user ? String(user.email) : text(input.contact, "contact", 160, true);
  const provider = text(input.payment_provider, "payment_provider", 40, true);
  const plan = text(input.plan ?? "experience", "plan", 32, true);
  if (!LICENSE_PLANS.has(plan)) throw new HttpError(400, "INVALID_PLAN", "plan must be experience, permanent or team");
  if (provider !== "alipay") throw new HttpError(400, "PAYMENT_PROVIDER_UNAVAILABLE", "selected payment provider is unavailable");
  const definition = planDefinition(env, plan);
  const gross = Number(definition.amount_cents);
  const upgradeOffer = user && plan !== "experience" ? await experienceUpgradeOffer(env, String(user.id)) : {eligible: false, discount_cents: 0};
  const promotionDiscount = upgradeOffer.eligible ? Math.min(gross, Number(upgradeOffer.discount_cents || 0)) : 0;
  const promotionCode = promotionDiscount > 0 ? EXPERIENCE_UPGRADE_PROMOTION : "";
  let creditApplied = 0;
  const afterPromotion = gross - promotionDiscount;
  if (user && input.use_credit === true) creditApplied = Math.min(afterPromotion, Math.max(0, Number(user.store_credit_cents || 0)));
  const amount = afterPromotion - creditApplied;
  const id = randomId("lforder_");
  const token = randomToken();
  const current = nowIso();
  const initialStatus = amount === 0 ? "payment_submitted" : "payment_pending";
  try {
    await env.DB.batch([
      env.DB.prepare(`INSERT INTO orders(id,status_token_hash,status,product_id,amount_cents,currency,payment_provider,contact,refund_days,created_at,updated_at,plan,user_id,gross_amount_cents,credit_applied_cents,major_version,expires_at,promotion_code,promotion_discount_cents)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`).bind(
        id, await sha256(token), initialStatus, env.PRODUCT_ID, amount, "CNY", provider, contact, Number(env.REFUND_DAYS), current, current, plan, user?.id || null, gross, creditApplied, definition.major_version, addHours(new Date(), 24), promotionCode, promotionDiscount,
      ),
      ...(promotionDiscount > 0 && user ? [env.DB.prepare(`INSERT INTO promotion_reservations(user_id,promotion_code,source_order_id,reserved_order_id,discount_cents,state,created_at)
        VALUES(?,?,?,?,?,'reserved',?)`).bind(user.id, promotionCode, upgradeOffer.source_order_id, id, promotionDiscount, current)] : []),
      ...(amount === 0 ? [env.DB.prepare("UPDATE orders SET payment_reference='store-credit',payment_claimed_at=? WHERE id=?").bind(current, id)] : []),
      ...(creditApplied > 0 && user ? [env.DB.prepare("UPDATE users SET store_credit_cents=store_credit_cents-?,updated_at=? WHERE id=? AND store_credit_cents>=?").bind(creditApplied, current, user.id, creditApplied)] : []),
      orderAudit(env, id, "order_created", "customer", "", {provider, plan, gross_amount_cents: gross, promotion_code: promotionCode, promotion_discount_cents: promotionDiscount, credit_applied_cents: creditApplied}),
    ]);
  } catch (error) {
    if (promotionDiscount > 0 && user) {
      const reservation = await env.DB.prepare("SELECT reserved_order_id FROM promotion_reservations WHERE user_id=? AND promotion_code=?")
        .bind(user.id, EXPERIENCE_UPGRADE_PROMOTION).first<Row>();
      if (reservation && reservation.reserved_order_id !== id) throw new HttpError(409, "PROMOTION_ALREADY_RESERVED", "新用户优惠已经用于另一笔订单，请先处理原订单");
    }
    throw error;
  }
  const row = await env.DB.prepare("SELECT * FROM orders WHERE id=?").bind(id).first<Row>();
  return json(201, {ok: true, status_token: token, status_url: `/orders#token=${encodeURIComponent(token)}`, order: await orderValue(env, row!, true)});
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
  if (row.cancelled_at) throw new HttpError(409, "ORDER_CANCELLED", "订单已取消，请重新下单");
  if (row.expires_at && String(row.expires_at) <= nowIso() && ["payment_pending", "payment_rejected"].includes(current)) throw new HttpError(409, "ORDER_EXPIRED", "订单已过期，请重新下单");
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

async function usageCount(env: Env, keyId: string): Promise<number> {
  const row = await env.DB.prepare("SELECT COUNT(*) AS count FROM usage_events WHERE license_key_id=?").bind(keyId).first<Row>();
  return Number(row?.count || 0);
}

async function issueLease(env: Env, keyId: string, installId: string, issued = new Date(), plan = "permanent", usageLimit: number | null = null, count = 0): Promise<Row> {
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
    plan,
    usage_limit: plan === "experience" ? usageLimit : null,
    usage_count: count,
    features: {skill_condensation: plan === "permanent" || plan === "team"},
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
    lease: await issueLease(env, String(row.id), installId, current, String(row.plan || "permanent"), row.usage_limit === null || row.usage_limit === undefined ? null : Number(row.usage_limit), await usageCount(env, String(row.id))),
    refund_deadline: row.refund_deadline,
    refund_days: row.refund_days,
  });
}

async function authenticatedProof(request: Request, env: Env, expectedAction: string, extraFields: string[] = []): Promise<{row: Row; proof: Row; nonce: string; now: Date}> {
  const input = await body(request);
  const token = text(input.activation_token, "activation_token", 128, true);
  const proof = input.proof;
  const signature = input.signature;
  if (!proof || Array.isArray(proof) || typeof proof !== "object" || typeof signature !== "string") throw new HttpError(400, "MISSING_PROOF", "signed installation proof is required");
  const message = proof as Row;
  const required = ["action", "activation_token", "install_id", "nonce", "timestamp", ...extraFields].sort();
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
  return json(200, {ok: true, status: "active", lease: await issueLease(
    env, String(verified.row.id), String(verified.row.install_id), verified.now,
    String(verified.row.plan || "permanent"), verified.row.usage_limit === null || verified.row.usage_limit === undefined ? null : Number(verified.row.usage_limit),
    await usageCount(env, String(verified.row.id)),
  )});
}

async function consumeUsage(request: Request, env: Env): Promise<Response> {
  const verified = await authenticatedProof(request, env, "consume_usage", ["usage_id"]);
  if (verified.row.status !== "active") throw new HttpError(403, "KEY_BLOCKED", `license key is ${verified.row.status}`);
  const usageId = text(verified.proof.usage_id, "usage_id", 128, true);
  const keyId = String(verified.row.id);
  const existing = await env.DB.prepare("SELECT id FROM usage_events WHERE license_key_id=? AND usage_id=?").bind(keyId, usageId).first<Row>();
  let charged = false;
  if (!existing) {
    const inserted = await env.DB.prepare(`INSERT INTO usage_events(id,license_key_id,usage_id,used_at)
      SELECT ?,?,?,? WHERE EXISTS (
        SELECT 1 FROM license_keys k WHERE k.id=? AND k.status='active'
        AND (k.usage_limit IS NULL OR (SELECT COUNT(*) FROM usage_events u WHERE u.license_key_id=k.id) < k.usage_limit)
      )`).bind(randomId("lfusage_"), keyId, usageId, nowIso(), keyId).run();
    charged = Number(inserted.meta.changes || 0) === 1;
    if (!charged) throw new HttpError(403, "USAGE_LIMIT_REACHED", "experience license has used all three reports");
  }
  const count = await usageCount(env, keyId);
  const limit = verified.row.usage_limit === null || verified.row.usage_limit === undefined ? null : Number(verified.row.usage_limit);
  await consumeNonce(env, verified.row, verified.nonce, verified.now, [
    env.DB.prepare("UPDATE license_keys SET last_seen_at=? WHERE id=?").bind(nowIso(), keyId),
    audit(env, keyId, "usage_consumed", "client", "", {usage_id: usageId, usage_count: count, charged}),
  ]);
  return json(200, {
    ok: true, status: "active", charged, usage_count: count,
    remaining_uses: limit === null ? null : Math.max(0, limit - count),
    lease: await issueLease(env, keyId, String(verified.row.install_id), verified.now, String(verified.row.plan || "permanent"), limit, count),
  });
}

async function requestClientRefund(request: Request, env: Env): Promise<Response> {
  await authenticatedProof(request, env, "refund_request");
  throw new HttpError(409, "SELF_SERVICE_REFUND_UNAVAILABLE", "数字化商品交付后不提供自助无理由退款。重复付款、无法激活或重大功能故障请联系售后QQ群 923937311 处理。");
}

async function publicConfig(env: Env): Promise<Response> {
  return json(200, {ok: true, turnstile_site_key: env.TURNSTILE_SITE_KEY || "", support_contact: env.SUPPORT_CONTACT, app_origin: env.APP_ORIGIN || "https://lab.elyther.top"});
}

async function accountSummary(request: Request, env: Env): Promise<Response> {
  const user = await requireUser(request, env);
  const code = await ensureReferralCode(env, String(user.id));
  return json(200, {ok: true, user: {id: user.id, email: user.email, display_name: user.display_name, store_credit_cents: user.store_credit_cents, created_at: user.created_at, role: userRole(user)}, referral_code: code, admin_access: ADMIN_ROLES.has(userRole(user))});
}

async function dashboard(request: Request, env: Env): Promise<Response> {
  const user = await requireUser(request, env);
  const orderRows = (await env.DB.prepare("SELECT * FROM orders WHERE user_id=? AND user_hidden_at IS NULL ORDER BY created_at DESC LIMIT 50").bind(user.id).all<Row>()).results;
  const orders = await Promise.all(orderRows.map(row => orderValue(env, row, true)));
  const entitlements = (await env.DB.prepare(`SELECT e.*,o.status AS order_status,o.amount_cents,o.gross_amount_cents
    FROM entitlements e JOIN orders o ON o.id=e.order_id WHERE e.user_id=? ORDER BY e.created_at DESC`).bind(user.id).all<Row>()).results;
  const keys = (await env.DB.prepare(`SELECT k.id,k.status,k.key_suffix,k.install_id,k.activated_at,k.last_seen_at,k.plan,k.seat_index,k.order_id
    FROM license_keys k JOIN orders o ON o.id=k.order_id WHERE o.user_id=? ORDER BY k.created_at DESC`).bind(user.id).all<Row>()).results;
  const notices = (await env.DB.prepare("SELECT * FROM notices WHERE expires_at IS NULL OR expires_at>? ORDER BY published_at DESC LIMIT 5").bind(nowIso()).all<Row>()).results;
  const balance = await env.DB.prepare(`SELECT
    COALESCE(SUM(CASE WHEN status='pending' AND available_at>? THEN amount_cents ELSE 0 END),0) AS pending_cents,
    COALESCE(SUM(CASE WHEN status='pending' AND available_at<=? THEN amount_cents ELSE 0 END),0) AS available_cents,
    COALESCE(SUM(CASE WHEN status IN ('withdrawal_pending','withdrawn','converted') THEN amount_cents ELSE 0 END),0) AS settled_cents
    FROM commission_entries WHERE referrer_user_id=?`).bind(nowIso(), nowIso(), user.id).first<Row>();
  return json(200, {ok: true, user: {email: user.email, display_name: user.display_name, store_credit_cents: user.store_credit_cents}, orders, entitlements, keys, notices, commission: balance});
}

async function referralSummary(request: Request, env: Env): Promise<Response> {
  const user = await requireUser(request, env);
  const code = await ensureReferralCode(env, String(user.id));
  const invited = (await env.DB.prepare(`SELECT u.email,u.created_at,
    COALESCE(SUM(CASE WHEN o.status IN ('paid','key_issued','delivered') THEN o.amount_cents ELSE 0 END),0) AS paid_cents
    FROM referral_attributions a JOIN users u ON u.id=a.invited_user_id
    LEFT JOIN orders o ON o.user_id=u.id WHERE a.referrer_user_id=? GROUP BY u.id ORDER BY u.created_at DESC LIMIT 100`).bind(user.id).all<Row>()).results;
  const entries = (await env.DB.prepare(`SELECT c.*,u.email AS invited_email,o.plan,o.status AS order_status
    FROM commission_entries c JOIN users u ON u.id=c.invited_user_id JOIN orders o ON o.id=c.order_id
    WHERE c.referrer_user_id=? ORDER BY c.created_at DESC LIMIT 100`).bind(user.id).all<Row>()).results;
  const withdrawals = (await env.DB.prepare("SELECT * FROM withdrawal_requests WHERE user_id=? ORDER BY created_at DESC LIMIT 50").bind(user.id).all<Row>()).results;
  const now = nowIso();
  const pending = entries.filter(item => item.status === "pending" && String(item.available_at) > now).reduce((sum, item) => sum + Number(item.amount_cents), 0);
  const available = entries.filter(item => item.status === "pending" && String(item.available_at) <= now).reduce((sum, item) => sum + Number(item.amount_cents), 0);
  const total = entries.filter(item => item.status !== "reversed").reduce((sum, item) => sum + Number(item.amount_cents), 0);
  const safeInvited = invited.map(item => ({...item, email: undefined, masked_email: maskedEmail(item.email)}));
  const safeEntries = entries.map(item => ({...item, invited_email: undefined, masked_email: maskedEmail(item.invited_email)}));
  return json(200, {ok: true, code, invite_url: `${env.APP_ORIGIN || new URL(request.url).origin}/register?ref=${code}`, rate_percent: 20, stats: {invite_count: invited.length, pending_cents: pending, available_cents: available, total_cents: total, store_credit_cents: Number(user.store_credit_cents || 0)}, invited: safeInvited, entries: safeEntries, withdrawals});
}

async function convertCommission(request: Request, env: Env): Promise<Response> {
  ensureSameOrigin(request, env);
  const user = await requireUser(request, env);
  const input = await body(request);
  const requested = Math.max(0, Math.floor(Number(input.amount_cents || 0)));
  const rows = (await env.DB.prepare("SELECT id,amount_cents FROM commission_entries WHERE referrer_user_id=? AND status='pending' AND available_at<=? ORDER BY available_at,id").bind(user.id, nowIso()).all<Row>()).results;
  const available = rows.reduce((sum, item) => sum + Number(item.amount_cents), 0);
  const amount = requested || available;
  if (amount <= 0 || amount > available) throw new HttpError(400, "INVALID_COMMISSION_AMOUNT", "可转换佣金余额不足");
  let remaining = amount;
  const statements: D1PreparedStatement[] = [];
  for (const row of rows) {
    if (remaining <= 0) break;
    const value = Number(row.amount_cents);
    if (value > remaining) throw new HttpError(400, "PARTIAL_ENTRY_UNSUPPORTED", "请选择不小于单笔佣金的转换金额，或直接全部转换");
    statements.push(env.DB.prepare("UPDATE commission_entries SET status='converted',updated_at=? WHERE id=? AND status='pending'").bind(nowIso(), row.id));
    remaining -= value;
  }
  if (remaining !== 0) throw new HttpError(400, "COMMISSION_AMOUNT_MISMATCH", "转换金额需要由完整佣金记录组成");
  statements.push(env.DB.prepare("UPDATE users SET store_credit_cents=store_credit_cents+?,updated_at=? WHERE id=?").bind(amount, nowIso(), user.id));
  await env.DB.batch(statements);
  return json(200, {ok: true, converted_cents: amount, store_credit_cents: Number(user.store_credit_cents || 0) + amount});
}

async function requestWithdrawal(request: Request, env: Env): Promise<Response> {
  ensureSameOrigin(request, env);
  const user = await requireUser(request, env);
  const input = await body(request);
  const payoutNote = text(input.payout_note, "payout_note", 240, true);
  const rows = (await env.DB.prepare("SELECT id,amount_cents FROM commission_entries WHERE referrer_user_id=? AND status='pending' AND available_at<=? ORDER BY available_at,id").bind(user.id, nowIso()).all<Row>()).results;
  const available = rows.reduce((sum, item) => sum + Number(item.amount_cents), 0);
  const amount = Math.floor(Number(input.amount_cents || available));
  if (amount <= 0 || amount > available) throw new HttpError(400, "INVALID_WITHDRAWAL_AMOUNT", "可提现佣金余额不足");
  let remaining = amount;
  const selected: Row[] = [];
  for (const row of rows) {
    if (remaining <= 0) break;
    const value = Number(row.amount_cents);
    if (value > remaining) throw new HttpError(400, "PARTIAL_ENTRY_UNSUPPORTED", "请选择不小于单笔佣金的提现金额，或直接全部提现");
    selected.push(row); remaining -= value;
  }
  if (remaining !== 0) throw new HttpError(400, "WITHDRAWAL_AMOUNT_MISMATCH", "提现金额需要由完整佣金记录组成");
  const id = randomId("lfwithdraw_");
  await env.DB.batch([
    ...selected.map(row => env.DB.prepare("UPDATE commission_entries SET status='withdrawal_pending',withdrawal_id=?,updated_at=? WHERE id=? AND status='pending'").bind(id, nowIso(), row.id)),
    env.DB.prepare("INSERT INTO withdrawal_requests(id,user_id,amount_cents,payout_note,created_at) VALUES(?,?,?,?,?)").bind(id, user.id, amount, payoutNote, nowIso()),
  ]);
  return json(201, {ok: true, withdrawal: {id, amount_cents: amount, status: "pending"}});
}

function maskedEmail(value: unknown): string {
  const [local, domain = ""] = String(value || "").split("@");
  if (!local) return "—";
  const visible = local.length <= 2 ? local.slice(0, 1) : `${local.slice(0, 2)}${"•".repeat(Math.min(6, Math.max(3, local.length - 4)))}${local.slice(-2)}`;
  return `${visible}@${domain}`;
}

function adminInviteCode(): string {
  const bytes = new Uint8Array(16); crypto.getRandomValues(bytes);
  const raw = Array.from(bytes, byte => BASE32[byte & 31]).join("");
  return `LFA-${raw.match(/.{1,4}/g)!.join("-")}`;
}

async function createAdminInvite(input: Row, env: Env, actor: Row | null): Promise<Row> {
  const role = text(input.role ?? "distributor_admin", "role", 32, true);
  if (!["owner", "distributor_admin"].includes(role)) throw new HttpError(400, "INVALID_ROLE", "管理员邀请码角色无效");
  const maxUses = Math.max(1, Math.min(100, Math.floor(Number(input.max_uses || 1))));
  const validDays = Math.max(1, Math.min(90, Math.floor(Number(input.valid_days || 7))));
  const code = adminInviteCode();
  const id = randomId("lfainvite_");
  const created = nowIso();
  await env.DB.batch([
    env.DB.prepare(`INSERT INTO admin_invites(id,code_hash,code_suffix,role,max_uses,expires_at,created_by_user_id,created_at)
      VALUES(?,?,?,?,?,?,?,?)`).bind(id, await hmacHex(env.TOKEN_SECRET, `admin-invite:v1:${code}`), code.slice(-4), role, maxUses, addDays(new Date(), validDays), actor?.id || null, created),
    adminAudit(env, actor, "admin_invite_created", "admin_invite", id, {role, max_uses: maxUses, valid_days: validDays}),
  ]);
  return {id, code, code_suffix: code.slice(-4), role, max_uses: maxUses, use_count: 0, status: "active", expires_at: addDays(new Date(), validDays), created_at: created};
}

async function redeemAdminInvite(request: Request, env: Env): Promise<Response> {
  ensureSameOrigin(request, env);
  const user = await requireUser(request, env);
  const input = await body(request);
  const invitation = await resolveInviteCode(env, input.invite_code);
  if (!invitation || invitation.kind !== "admin") throw new HttpError(400, "INVALID_ADMIN_INVITE", "这不是有效的管理员邀请码");
  const currentRole = userRole(user);
  const grantedRole = String(invitation.role);
  const nextRole = currentRole === "owner" ? "owner" : grantedRole;
  const current = nowIso();
  await env.DB.batch([
    env.DB.prepare("UPDATE admin_invites SET use_count=use_count+1,status=CASE WHEN use_count+1>=max_uses THEN 'exhausted' ELSE status END WHERE id=? AND status='active' AND use_count<max_uses").bind(invitation.id),
    env.DB.prepare("INSERT INTO admin_invite_redemptions(invite_id,user_id,redeemed_at) VALUES(?,?,?)").bind(invitation.id, user.id, current),
    env.DB.prepare("UPDATE users SET role=?,role_updated_at=?,updated_at=? WHERE id=?").bind(nextRole, current, current, user.id),
    adminAudit(env, user, "admin_invite_redeemed", "user", String(user.id), {role: nextRole, invite_id: invitation.id}),
  ]);
  return json(200, {ok: true, role: nextRole, control_url: "/control/overview"});
}

async function controlSession(request: Request, env: Env): Promise<Response> {
  const actor = await requireRole(request, env, ADMIN_ROLES);
  return json(200, {ok: true, user: {id: actor.id, email: actor.email, role: userRole(actor)}, permissions: {
    manage_roles: userRole(actor) === "owner", global_analytics: userRole(actor) === "owner", process_withdrawals: userRole(actor) === "owner",
  }});
}

async function listControlUsers(url: URL, env: Env, actor: Row): Promise<Response> {
  const role = url.searchParams.get("role") || "";
  const query = (url.searchParams.get("q") || "").trim().toLowerCase();
  let rows: Row[];
  if (userRole(actor) === "owner") {
    rows = (await env.DB.prepare(`SELECT u.id,u.email,u.role,u.status,u.created_at,u.role_updated_at,
      (SELECT COUNT(*) FROM orders o WHERE o.user_id=u.id) AS order_count FROM users u ORDER BY u.created_at DESC LIMIT 500`).all<Row>()).results;
  } else {
    rows = (await env.DB.prepare(`SELECT u.id,u.email,u.role,u.status,u.created_at,u.role_updated_at,
      (SELECT COUNT(*) FROM orders o WHERE o.user_id=u.id) AS order_count FROM users u
      JOIN referral_attributions a ON a.invited_user_id=u.id WHERE a.referrer_user_id=? ORDER BY u.created_at DESC LIMIT 500`).bind(actor.id).all<Row>()).results;
  }
  if (role) rows = rows.filter(row => userRole(row) === role);
  if (query) rows = rows.filter(row => String(row.email).toLowerCase().includes(query) || String(row.id).toLowerCase().includes(query));
  return json(200, {ok: true, users: rows.map(row => ({...row, email: userRole(actor) === "owner" ? row.email : maskedEmail(row.email)}))});
}

async function updateControlUserRole(request: Request, env: Env, actor: Row, id: string): Promise<Response> {
  if (userRole(actor) !== "owner") throw new HttpError(403, "OWNER_REQUIRED", "只有完全管理员可以修改管理员身份");
  ensureSameOrigin(request, env);
  const input = await body(request);
  const role = text(input.role, "role", 32, true);
  if (!ACCOUNT_ROLES.has(role)) throw new HttpError(400, "INVALID_ROLE", "账号角色无效");
  const target = await env.DB.prepare("SELECT * FROM users WHERE id=?").bind(id).first<Row>();
  if (!target) throw new HttpError(404, "USER_NOT_FOUND", "账号不存在");
  if (userRole(target) === "owner" && role !== "owner") {
    const owners = await env.DB.prepare("SELECT COUNT(*) AS count FROM users WHERE role='owner' AND status='active'").first<Row>();
    if (Number(owners?.count || 0) <= 1) throw new HttpError(409, "LAST_OWNER", "不能取消最后一个完全管理员");
  }
  const current = nowIso();
  await env.DB.batch([
    env.DB.prepare("UPDATE users SET role=?,role_updated_at=?,updated_at=? WHERE id=?").bind(role, current, current, id),
    adminAudit(env, actor, "user_role_changed", "user", id, {from: userRole(target), to: role}),
  ]);
  return json(200, {ok: true, user: {id, email: target.email, role}});
}

async function listControlInvites(env: Env, actor: Row): Promise<Response> {
  if (userRole(actor) !== "owner") throw new HttpError(403, "OWNER_REQUIRED", "只有完全管理员可以查看管理员邀请码");
  const rows = (await env.DB.prepare(`SELECT i.id,i.code_suffix,i.role,i.status,i.max_uses,i.use_count,i.expires_at,i.created_at,i.revoked_at,
    u.email AS created_by_email FROM admin_invites i LEFT JOIN users u ON u.id=i.created_by_user_id ORDER BY i.created_at DESC LIMIT 200`).all<Row>()).results;
  return json(200, {ok: true, invites: rows});
}

async function revokeControlInvite(env: Env, actor: Row, id: string): Promise<Response> {
  if (userRole(actor) !== "owner") throw new HttpError(403, "OWNER_REQUIRED", "只有完全管理员可以作废管理员邀请码");
  const current = nowIso();
  await env.DB.batch([
    env.DB.prepare("UPDATE admin_invites SET status='revoked',revoked_at=? WHERE id=? AND status='active'").bind(current, id),
    adminAudit(env, actor, "admin_invite_revoked", "admin_invite", id),
  ]);
  return json(200, {ok: true});
}

async function recordPageView(request: Request, env: Env): Promise<Response> {
  ensureSameOrigin(request, env);
  const input = await body(request);
  const routeName = text(input.route, "route", 80, true).split("?")[0];
  const allowed = new Set(["/login","/register","/dashboard","/plans","/referrals","/showcase","/download","/docs","/account","/orders"]);
  if (!allowed.has(routeName)) throw new HttpError(400, "INVALID_ROUTE", "unknown metric route");
  const date = nowIso().slice(0, 10);
  const identity = `${request.headers.get("CF-Connecting-IP") || "local"}:${request.headers.get("User-Agent") || "unknown"}`;
  const visitorHash = await hmacHex(env.TOKEN_SECRET, `visitor:v1:${date}:${identity}`);
  const inserted = await env.DB.prepare("INSERT OR IGNORE INTO visitor_days(metric_date,route,visitor_hash,created_at) VALUES(?,?,?,?)").bind(date, routeName, visitorHash, nowIso()).run();
  const unique = Number(inserted.meta.changes || 0);
  await env.DB.prepare(`INSERT INTO daily_site_metrics(metric_date,route,page_views,unique_visitors) VALUES(?,?,1,?)
    ON CONFLICT(metric_date,route) DO UPDATE SET page_views=page_views+1,unique_visitors=unique_visitors+excluded.unique_visitors`).bind(date, routeName, unique).run();
  await env.DB.prepare("DELETE FROM visitor_days WHERE metric_date<?").bind(new Date(Date.now() - 90 * 86400_000).toISOString().slice(0, 10)).run();
  return json(202, {ok: true});
}

async function controlOverview(url: URL, env: Env, actor: Row): Promise<Response> {
  const days = Math.max(7, Math.min(90, Number(url.searchParams.get("days") || 30)));
  const cutoff = new Date(Date.now() - (days - 1) * 86400_000).toISOString().slice(0, 10);
  const owner = userRole(actor) === "owner";
  const scope = owner ? "" : " AND o.user_id IN (SELECT invited_user_id FROM referral_attributions WHERE referrer_user_id=?)";
  const orderSql = `SELECT plan,COUNT(*) AS orders,COALESCE(SUM(CASE WHEN status IN ('paid','key_issued','delivered','refunded') THEN gross_amount_cents ELSE 0 END),0) AS gross_gmv_cents,
    COALESCE(SUM(CASE WHEN status IN ('paid','key_issued','delivered') THEN gross_amount_cents ELSE 0 END),0) AS net_gmv_cents,
    SUM(CASE WHEN status IN ('paid','key_issued','delivered','refunded') THEN 1 ELSE 0 END) AS paid_orders FROM orders o WHERE date(created_at)>=?${scope} GROUP BY plan`;
  const orderStatement = owner ? env.DB.prepare(orderSql).bind(cutoff) : env.DB.prepare(orderSql).bind(cutoff, actor.id);
  const planRows = (await orderStatement.all<Row>()).results;
  const registration = owner
    ? await env.DB.prepare("SELECT COUNT(*) AS count FROM users WHERE date(created_at)>=?").bind(cutoff).first<Row>()
    : await env.DB.prepare("SELECT COUNT(*) AS count FROM referral_attributions a JOIN users u ON u.id=a.invited_user_id WHERE a.referrer_user_id=? AND date(u.created_at)>=?").bind(actor.id, cutoff).first<Row>();
  const keys = owner
    ? await env.DB.prepare(`SELECT COUNT(*) AS total,SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) AS active,
        SUM(CASE WHEN usage_limit IS NOT NULL AND (SELECT COUNT(*) FROM usage_events ue WHERE ue.license_key_id=license_keys.id)>=usage_limit THEN 1 ELSE 0 END) AS exhausted FROM license_keys`).first<Row>()
    : await env.DB.prepare(`SELECT COUNT(*) AS total,SUM(CASE WHEN k.status='active' THEN 1 ELSE 0 END) AS active,
        SUM(CASE WHEN k.usage_limit IS NOT NULL AND (SELECT COUNT(*) FROM usage_events ue WHERE ue.license_key_id=k.id)>=k.usage_limit THEN 1 ELSE 0 END) AS exhausted
        FROM license_keys k JOIN orders o ON o.id=k.order_id WHERE o.user_id IN (SELECT invited_user_id FROM referral_attributions WHERE referrer_user_id=?)`).bind(actor.id).first<Row>();
  const traffic = owner ? (await env.DB.prepare("SELECT metric_date,SUM(page_views) AS page_views,SUM(unique_visitors) AS unique_visitors FROM daily_site_metrics WHERE metric_date>=? GROUP BY metric_date ORDER BY metric_date").bind(cutoff).all<Row>()).results : [];
  return json(200, {ok: true, days, registrations: Number(registration?.count || 0), plans: planRows, keys, traffic, traffic_available: owner});
}

async function listWithdrawals(url: URL, env: Env): Promise<Response> {
  const status = url.searchParams.get("status") || "";
  if (status && !["pending", "paid", "rejected"].includes(status)) throw new HttpError(400, "INVALID_STATUS", "unknown withdrawal status");
  const limit = Math.max(1, Math.min(Number(url.searchParams.get("limit") || 100), 500));
  const sql = `SELECT w.*,u.email FROM withdrawal_requests w JOIN users u ON u.id=w.user_id ${status ? "WHERE w.status=?" : ""} ORDER BY w.created_at DESC LIMIT ?`;
  const statement = status ? env.DB.prepare(sql).bind(status, limit) : env.DB.prepare(sql).bind(limit);
  return json(200, {ok: true, withdrawals: (await statement.all<Row>()).results});
}

async function adminWithdrawalAction(request: Request, env: Env, id: string, action: string): Promise<Response> {
  const input = await body(request);
  const note = text(input.note, "note", 500);
  const row = await env.DB.prepare("SELECT * FROM withdrawal_requests WHERE id=?").bind(id).first<Row>();
  if (!row) throw new HttpError(404, "WITHDRAWAL_NOT_FOUND", "withdrawal request not found");
  if (row.status !== "pending") throw new HttpError(409, "INVALID_STATE", `withdrawal is already ${row.status}`);
  const current = nowIso();
  if (action === "paid") {
    await env.DB.batch([
      env.DB.prepare("UPDATE withdrawal_requests SET status='paid',processed_at=?,admin_note=? WHERE id=? AND status='pending'").bind(current, note, id),
      env.DB.prepare("UPDATE commission_entries SET status='withdrawn',updated_at=? WHERE withdrawal_id=? AND status='withdrawal_pending'").bind(current, id),
    ]);
  } else if (action === "reject") {
    await env.DB.batch([
      env.DB.prepare("UPDATE withdrawal_requests SET status='rejected',processed_at=?,admin_note=? WHERE id=? AND status='pending'").bind(current, note, id),
      env.DB.prepare("UPDATE commission_entries SET status='pending',withdrawal_id=NULL,updated_at=? WHERE withdrawal_id=? AND status='withdrawal_pending'").bind(current, id),
    ]);
  } else throw new HttpError(404, "UNKNOWN_ACTION", "unknown withdrawal action");
  return json(200, {ok: true, withdrawal: await env.DB.prepare("SELECT * FROM withdrawal_requests WHERE id=?").bind(id).first<Row>()});
}

async function claimLegacyOrder(request: Request, env: Env): Promise<Response> {
  ensureSameOrigin(request, env);
  const user = await requireUser(request, env);
  const input = await body(request);
  const token = text(input.order_token, "order_token", 128, true);
  const row = await env.DB.prepare("SELECT * FROM orders WHERE status_token_hash=?").bind(await sha256(token)).first<Row>();
  if (!row) throw new HttpError(404, "ORDER_NOT_FOUND", "订单 Token 无效");
  if (row.user_id && row.user_id !== user.id) throw new HttpError(409, "ORDER_ALREADY_CLAIMED", "该订单已绑定其他账号");
  await env.DB.batch([
    env.DB.prepare("UPDATE orders SET user_id=?,contact=?,updated_at=? WHERE id=?").bind(user.id, user.email, nowIso(), row.id),
    env.DB.prepare("UPDATE entitlements SET user_id=? WHERE order_id=?").bind(user.id, row.id),
    orderAudit(env, String(row.id), "order_claimed", "customer", "", {user_id: user.id}),
  ]);
  return json(200, {ok: true, order_id: row.id});
}

async function userOrderAction(request: Request, env: Env, id: string, action: string): Promise<Response> {
  ensureSameOrigin(request, env);
  const user = await requireUser(request, env);
  const row = await env.DB.prepare("SELECT * FROM orders WHERE id=? AND user_id=?").bind(id, user.id).first<Row>();
  if (!row) throw new HttpError(404, "ORDER_NOT_FOUND", "订单不存在");
  const current = nowIso();
  if (action === "hide") {
    if (!row.user_hidden_at) await env.DB.batch([
      env.DB.prepare("UPDATE orders SET user_hidden_at=?,updated_at=? WHERE id=? AND user_id=?").bind(current, current, id, user.id),
      orderAudit(env, id, "order_hidden", "customer"),
    ]);
  } else if (action === "cancel") {
    if (row.cancelled_at) return json(200, {ok: true, status: "cancelled"});
    if (!["payment_pending", "payment_rejected"].includes(String(row.status))) throw new HttpError(409, "INVALID_STATE", "当前订单状态不能取消");
    const credit = Math.max(0, Number(row.credit_applied_cents || 0));
    const cancelled = await env.DB.prepare("UPDATE orders SET cancelled_at=?,updated_at=? WHERE id=? AND user_id=? AND cancelled_at IS NULL").bind(current, current, id, user.id).run();
    if (Number(cancelled.meta.changes || 0) === 1) await env.DB.batch([
      ...(credit ? [env.DB.prepare("UPDATE users SET store_credit_cents=store_credit_cents+?,updated_at=? WHERE id=?").bind(credit, current, user.id)] : []),
      ...(row.promotion_code ? [env.DB.prepare("DELETE FROM promotion_reservations WHERE user_id=? AND promotion_code=? AND reserved_order_id=? AND state='reserved'").bind(user.id, row.promotion_code, id)] : []),
      orderAudit(env, id, "order_cancelled", "customer", "customer cancelled before payment", {credit_restored_cents: credit}),
    ]);
  } else throw new HttpError(404, "UNKNOWN_ACTION", "unknown order action");
  const fresh = await env.DB.prepare("SELECT * FROM orders WHERE id=?").bind(id).first<Row>();
  return json(200, {ok: true, order: await orderValue(env, fresh!, true)});
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

async function commissionStatements(env: Env, order: Row, paidAt: string): Promise<D1PreparedStatement[]> {
  if (!order.user_id || Number(order.amount_cents || 0) <= 0) return [];
  const attribution = await env.DB.prepare("SELECT referrer_user_id FROM referral_attributions WHERE invited_user_id=?").bind(order.user_id).first<Row>();
  if (!attribution) return [];
  const basis = Number(order.amount_cents);
  const amount = Math.round(basis * COMMISSION_RATE_BPS / 10_000);
  if (amount <= 0) return [];
  return [env.DB.prepare(`INSERT OR IGNORE INTO commission_entries(id,referrer_user_id,invited_user_id,order_id,basis_cents,rate_bps,amount_cents,available_at,created_at,updated_at)
    VALUES(?,?,?,?,?,?,?,?,?,?)`).bind(randomId("lfcommission_"), attribution.referrer_user_id, order.user_id, order.id, basis, COMMISSION_RATE_BPS, amount, addDays(new Date(paidAt), Number(order.refund_days || 7)), paidAt, paidAt)];
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
      await assertExperienceUpgradeOrder(env, row);
      const definition = planDefinition(env, String(row.plan || "experience"));
      const seatCount = Number(definition.seat_count || 1);
      const orderPlan = String(row.plan || "experience");
      const orderRefundDays = Number(row.refund_days);
      const entitlementId = `lfent_${(await sha256(`order-entitlement:v1:${id}`)).slice(0, 32)}`;
      const keys = await Promise.all(Array.from({length: seatCount}, async (_, offset) => {
        const seat = offset + 1;
        const plain = await orderActivationKey(env, id, seat);
        return {seat, plain, keyHash: await hmacHex(env.KEY_PEPPER, plain), keyId: await orderLicenseKeyId(id, seat)};
      }));
      const commission = await commissionStatements(env, row, time);
      try {
        await env.DB.batch([
          env.DB.prepare(`INSERT INTO entitlements(id,user_id,order_id,plan,major_version,seat_count,free_major_updates,created_at)
            VALUES(?,?,?,?,?,?,?,?)`).bind(entitlementId, row.user_id || null, id, row.plan || "experience", definition.major_version, seatCount, definition.free_major_updates ? 1 : 0, time),
          ...keys.flatMap(key => [
            env.DB.prepare(`INSERT INTO license_keys(id,key_hash,key_suffix,status,label,customer_ref,refund_days,product_id,created_at,sent_at,plan,usage_limit,entitlement_id,order_id,seat_index)
              VALUES(?,?,?,'unused','购买页自动发货',?,?,?,?,?,?,?,?,?,?)`).bind(key.keyId, key.keyHash, key.plain.slice(-4), `${id}:seat:${key.seat}`, orderRefundDays, env.PRODUCT_ID, time, time, orderPlan, orderPlan === "experience" ? 3 : null, entitlementId, id, key.seat),
            audit(env, key.keyId, "key_created", "admin", "semi-automatic order delivery", {refund_days: orderRefundDays, plan: orderPlan, seat_index: key.seat}),
            audit(env, key.keyId, "key_sent", "system", "displayed on authenticated order page"),
          ]),
          env.DB.prepare(`UPDATE orders SET status='delivered',paid_at=?,delivered_at=?,updated_at=?,admin_reason='',license_key_id=?,delivery_key_version='derived-v2'
            WHERE id=? AND status='payment_submitted'`).bind(time, time, time, keys[0].keyId, id),
          ...(row.promotion_code ? [env.DB.prepare("UPDATE promotion_reservations SET state='redeemed',redeemed_at=? WHERE user_id=? AND promotion_code=? AND reserved_order_id=? AND state='reserved'").bind(time, row.user_id, row.promotion_code, id)] : []),
          ...commission,
          orderAudit(env, id, "payment_confirmed", "admin", reason),
          orderAudit(env, id, "key_issued", "system", "semi-automatic delivery", {license_key_ids: keys.map(key => key.keyId), seat_count: seatCount}),
          orderAudit(env, id, "order_delivered", "system", "activation keys available on authenticated order page"),
        ]);
      } catch (error) {
        const fresh = await env.DB.prepare("SELECT status,delivery_key_version FROM orders WHERE id=?").bind(id).first<Row>();
        if (fresh?.status !== "delivered" || fresh.delivery_key_version !== "derived-v2") throw error;
      }
    }
  } else if (action === "confirm-payment") {
    if (!["paid", "key_issued", "delivered", "refund_requested", "refunded"].includes(current)) {
      if (current !== "payment_submitted") throw new HttpError(409, "INVALID_STATE", `payment cannot be confirmed from ${current}`);
      await assertExperienceUpgradeOrder(env, row);
      await env.DB.batch([
        env.DB.prepare("UPDATE orders SET status='paid',paid_at=?,updated_at=?,admin_reason='' WHERE id=? AND status='payment_submitted'").bind(time, time, id),
        ...(row.promotion_code ? [env.DB.prepare("UPDATE promotion_reservations SET state='redeemed',redeemed_at=? WHERE user_id=? AND promotion_code=? AND reserved_order_id=? AND state='reserved'").bind(time, row.user_id, row.promotion_code, id)] : []),
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
          env.DB.prepare(`INSERT INTO license_keys(id,key_hash,key_suffix,status,label,customer_ref,refund_days,product_id,created_at,plan,usage_limit)
            VALUES(?,?,?,'unused','购买页订单',?,?,?,?,?,?)`).bind(keyId, await hmacHex(env.KEY_PEPPER, plaintext), plaintext.slice(-4), id, Number(row.refund_days), env.PRODUCT_ID, time, String(row.plan || "experience"), row.plan === "permanent" ? null : 3),
          env.DB.prepare("UPDATE orders SET status='key_issued',license_key_id=?,updated_at=? WHERE id=? AND status='paid'").bind(keyId, time, id),
          audit(env, keyId, "key_created", "admin", "", {refund_days: row.refund_days, plan: row.plan || "experience"}),
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
        env.DB.prepare("UPDATE license_keys SET status='refunded',revoked_at=?,revoke_reason=? WHERE order_id=?").bind(time, reason || "original-route refund completed", id),
        env.DB.prepare("UPDATE commission_entries SET status='reversed',updated_at=? WHERE order_id=? AND status IN ('pending','withdrawal_pending')").bind(time, id),
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

async function listControlKeys(url: URL, env: Env, actor: Row): Promise<Response> {
  const plan = url.searchParams.get("plan") || "";
  const status = url.searchParams.get("status") || "";
  const query = (url.searchParams.get("q") || "").trim();
  if (plan && !LICENSE_PLANS.has(plan)) throw new HttpError(400, "INVALID_PLAN", "unknown plan");
  if (status && !KEY_STATES.has(status) && status !== "exhausted") throw new HttpError(400, "INVALID_STATUS", "unknown key status");
  const params: unknown[] = [];
  let sql = `SELECT k.*,o.user_id,u.email AS user_email,
    (SELECT COUNT(*) FROM usage_events ue WHERE ue.license_key_id=k.id) AS usage_count
    FROM license_keys k LEFT JOIN orders o ON o.id=k.order_id LEFT JOIN users u ON u.id=o.user_id WHERE 1=1`;
  if (userRole(actor) !== "owner") { sql += " AND o.user_id IN (SELECT invited_user_id FROM referral_attributions WHERE referrer_user_id=?)"; params.push(actor.id); }
  if (plan) { sql += " AND k.plan=?"; params.push(plan); }
  if (status && status !== "exhausted") { sql += " AND k.status=?"; params.push(status); }
  if (query) {
    if (/^LF-/i.test(query)) { sql += " AND k.key_hash=?"; params.push(await hmacHex(env.KEY_PEPPER, query.toUpperCase())); }
    else { sql += " AND (k.id LIKE ? OR k.key_suffix LIKE ? OR k.label LIKE ? OR k.order_id LIKE ? OR u.email LIKE ?)"; const like = `%${query}%`; params.push(like, like, like, like, like); }
  }
  sql += " ORDER BY k.created_at DESC LIMIT 500";
  let rows = (await env.DB.prepare(sql).bind(...params).all<Row>()).results.map(row => {
    const usageCount = Number(row.usage_count || 0), usageLimit = row.usage_limit == null ? null : Number(row.usage_limit);
    return {...publicKey(row), usage_count: usageCount, remaining_uses: usageLimit == null ? null : Math.max(0, usageLimit - usageCount), effective_status: usageLimit != null && usageCount >= usageLimit ? "exhausted" : row.status};
  });
  if (status === "exhausted") rows = rows.filter(row => row.effective_status === "exhausted");
  return json(200, {ok: true, keys: rows});
}

async function assertControlOrder(env: Env, actor: Row, orderId: string): Promise<void> {
  if (userRole(actor) === "owner") return;
  const allowed = await env.DB.prepare(`SELECT 1 AS allowed FROM orders o JOIN referral_attributions a ON a.invited_user_id=o.user_id
    WHERE o.id=? AND a.referrer_user_id=?`).bind(orderId, actor.id).first<Row>();
  if (!allowed) throw new HttpError(403, "OUT_OF_SCOPE", "该订单不属于你的分销渠道");
}

async function assertControlKey(env: Env, actor: Row, keyId: string): Promise<void> {
  if (userRole(actor) === "owner") return;
  const allowed = await env.DB.prepare(`SELECT 1 AS allowed FROM license_keys k JOIN orders o ON o.id=k.order_id
    JOIN referral_attributions a ON a.invited_user_id=o.user_id WHERE k.id=? AND a.referrer_user_id=?`).bind(keyId, actor.id).first<Row>();
  if (!allowed) throw new HttpError(403, "OUT_OF_SCOPE", "该密钥不属于你的分销渠道");
}

async function listControlOrders(url: URL, env: Env, actor: Row): Promise<Response> {
  const status = url.searchParams.get("status") || "";
  const plan = url.searchParams.get("plan") || "";
  const query = (url.searchParams.get("q") || "").trim();
  const params: unknown[] = [];
  let sql = "SELECT o.* FROM orders o WHERE 1=1";
  if (userRole(actor) !== "owner") { sql += " AND o.user_id IN (SELECT invited_user_id FROM referral_attributions WHERE referrer_user_id=?)"; params.push(actor.id); }
  if (status && !["cancelled","expired"].includes(status)) { if (!ORDER_STATES.has(status)) throw new HttpError(400, "INVALID_STATUS", "unknown order status"); sql += " AND o.status=?"; params.push(status); }
  if (plan) { if (!LICENSE_PLANS.has(plan)) throw new HttpError(400, "INVALID_PLAN", "unknown plan"); sql += " AND o.plan=?"; params.push(plan); }
  if (query) { const like = `%${query}%`; sql += " AND (o.id LIKE ? OR o.contact LIKE ? OR o.payment_reference LIKE ?)"; params.push(like, like, like); }
  sql += " ORDER BY o.created_at DESC LIMIT 500";
  let rows = await Promise.all((await env.DB.prepare(sql).bind(...params).all<Row>()).results.map(row => orderValue(env, row, false)));
  if (status) rows = rows.filter(row => row.effective_status === status);
  return json(200, {ok: true, orders: rows});
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
  const current = nowIso();
  const plan = text(input.plan ?? "permanent", "plan", 32, true);
  if (!LICENSE_PLANS.has(plan)) throw new HttpError(400, "INVALID_PLAN", "plan must be experience, permanent or team");
  const label = text(input.label, "label", 120);
  const customerRef = text(input.customer_ref, "customer_ref", 120);
  const seatCount = plan === "team" ? 5 : 1;
  const batchId = randomId("lfmanual_");
  const keys = await Promise.all(Array.from({length: seatCount}, async (_, index) => {
    const seat = index + 1;
    const plain = activationKey();
    return {id: randomId("lfkey_"), plain, seat, keyHash: await hmacHex(env.KEY_PEPPER, plain)};
  }));
  await env.DB.batch(keys.flatMap(key => [
    env.DB.prepare(`INSERT INTO license_keys(id,key_hash,key_suffix,status,label,customer_ref,refund_days,product_id,created_at,plan,usage_limit,seat_index)
      VALUES(?,?,?,'unused',?,?,?,?,?,?,?,?)`).bind(
        key.id, key.keyHash, key.plain.slice(-4), label || `中控直接生成 · ${plan}`, customerRef ? `${customerRef}${seatCount > 1 ? `:seat:${key.seat}` : ""}` : batchId,
        refundDays, env.PRODUCT_ID, current, plan, plan === "experience" ? 3 : null, key.seat,
      ),
    audit(env, key.id, "key_created", "admin", "control-room direct issue", {refund_days: refundDays, plan, seat_index: key.seat, batch_id: batchId}),
  ]));
  const publicKeys = await Promise.all(keys.map(key => getAdminKey(key.id, env)));
  return json(201, {
    ok: true,
    activation_key: keys[0].plain,
    activation_keys: keys.map(key => key.plain),
    batch_id: batchId,
    warning: `明文密钥只返回这一次。${seatCount > 1 ? "五人版已生成 5 把独立密钥，" : ""}请立即通过私密渠道保存并发送。`,
    key: publicKeys[0],
    keys: publicKeys,
  });
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
  if (pathname === "/" || pathname === "/index.html") return Response.redirect(`${url.origin}/showcase`, 302);
  const portalRoutes = new Set(["login", "register", "dashboard", "plans", "referrals", "showcase", "download", "docs", "account", "orders"]);
  const portalName = pathname.replace(/^\//, "").replace(/\/$/, "");
  if (portalRoutes.has(portalName)) url.pathname = `/${portalName}/index.html`;
  if (pathname === "/buy" || pathname === "/buy/" || pathname === "/buy/index.html") return Response.redirect(`${url.origin}/plans`, 302);
  if (pathname === "/admin" || pathname === "/admin/") url.pathname = "/admin/index.html";
  const controlRoute = pathname.match(/^\/control\/(overview|keys|orders|users|invites|withdrawals)\/?$/);
  if (pathname === "/control" || pathname === "/control/") return Response.redirect(`${url.origin}/control/overview`, 302);
  if (controlRoute) url.pathname = `/control/${controlRoute[1]}/index.html`;
  const asset = await env.ASSETS.fetch(new Request(url.toString(), request));
  const headers = new Headers(asset.headers);
  headers.set("Content-Security-Policy", "default-src 'self'; connect-src 'self' https://challenges.cloudflare.com; frame-src https://challenges.cloudflare.com; img-src 'self' data:; script-src 'self' https://challenges.cloudflare.com; style-src 'self' 'unsafe-inline'; object-src 'none'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'");
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
  if (request.method === "GET" && (/^\/control\/?$/.test(path) || /^\/control\/(overview|keys|orders|users|invites|withdrawals)\/?$/.test(path))) {
    const actor = await optionalUser(request, env);
    if (!actor) return Response.redirect(`${url.origin}/login?next=${encodeURIComponent(path)}`, 302);
    if (!ADMIN_ROLES.has(userRole(actor))) return Response.redirect(`${url.origin}/account`, 302);
    if (["/control/invites", "/control/invites/", "/control/withdrawals", "/control/withdrawals/"].includes(path) && userRole(actor) !== "owner") return Response.redirect(`${url.origin}/control/overview`, 302);
    return staticAsset(request, env, path);
  }
  if (request.method === "GET" && path === "/health") return json(200, {ok: true, service: "lab-factory-commercial-worker", time: nowIso()});
  if (request.method === "GET" && path === "/api/public/config") return publicConfig(env);
  if (request.method === "POST" && path === "/api/auth/register/start") return startRegistration(request, env);
  if (request.method === "POST" && path === "/api/auth/register/verify") return verifyRegistration(request, env);
  if (request.method === "POST" && path === "/api/auth/login") return passwordLogin(request, env);
  if (request.method === "POST" && path === "/api/auth/logout") return logout(request, env);
  if (request.method === "POST" && path === "/api/admin-invite/redeem") return redeemAdminInvite(request, env);
  if (request.method === "POST" && path === "/api/metrics/view") return recordPageView(request, env);
  if (request.method === "GET" && path === "/api/me") return accountSummary(request, env);
  if (request.method === "GET" && path === "/api/dashboard") return dashboard(request, env);
  if (request.method === "GET" && path === "/api/referrals") return referralSummary(request, env);
  if (request.method === "POST" && path === "/api/referrals/convert") return convertCommission(request, env);
  if (request.method === "POST" && path === "/api/referrals/withdrawals") return requestWithdrawal(request, env);
  if (request.method === "POST" && path === "/api/orders/claim") return claimLegacyOrder(request, env);
  const customerOrderMatch = path.match(/^\/api\/orders\/(lforder_[a-f0-9]+)\/(cancel|hide)$/);
  if (request.method === "POST" && customerOrderMatch) return userOrderAction(request, env, customerOrderMatch[1], customerOrderMatch[2]);
  if (request.method === "GET" && path === "/api/checkout/config") return checkoutConfig(request, env);
  if (request.method === "GET" && path === "/api/order") return getOrder(request, env);
  if (request.method === "POST" && path === "/api/orders") return createOrder(request, env);
  if (request.method === "POST" && path === "/api/order/payment") return submitPayment(request, env);
  if (request.method === "POST" && path === "/api/order/refund") return requestOrderRefund(request, env);
  if (request.method === "POST" && path === "/api/activate") return activate(request, env);
  if (request.method === "POST" && path === "/api/lease/refresh") return refreshLease(request, env);
  if (request.method === "POST" && path === "/api/usage/consume") return consumeUsage(request, env);
  if (request.method === "POST" && path === "/api/refunds/request") return requestClientRefund(request, env);

  if (path.startsWith("/api/control/")) {
    if (request.method === "POST") ensureSameOrigin(request, env);
    const actor = await requireRole(request, env, ADMIN_ROLES);
    if (request.method === "GET" && path === "/api/control/session") return controlSession(request, env);
    if (request.method === "GET" && path === "/api/control/overview") return controlOverview(url, env, actor);
    if (request.method === "GET" && path === "/api/control/users") return listControlUsers(url, env, actor);
    const controlUserMatch = path.match(/^\/api\/control\/users\/(lfuser_[a-f0-9]+)\/role$/);
    if (request.method === "POST" && controlUserMatch) return updateControlUserRole(request, env, actor, controlUserMatch[1]);
    if (request.method === "GET" && path === "/api/control/invites") return listControlInvites(env, actor);
    if (request.method === "POST" && path === "/api/control/invites") {
      if (userRole(actor) !== "owner") throw new HttpError(403, "OWNER_REQUIRED", "只有完全管理员可以生成管理员邀请码");
      return json(201, {ok: true, invite: await createAdminInvite(await body(request), env, actor)});
    }
    const controlInviteMatch = path.match(/^\/api\/control\/invites\/(lfainvite_[a-f0-9]+)\/revoke$/);
    if (request.method === "POST" && controlInviteMatch) return revokeControlInvite(env, actor, controlInviteMatch[1]);
    if (request.method === "GET" && path === "/api/control/keys") return listControlKeys(url, env, actor);
    if (request.method === "POST" && path === "/api/control/keys") {
      if (userRole(actor) !== "owner") throw new HttpError(403, "OWNER_REQUIRED", "只有完全管理员可以手工生成密钥");
      const response = await createKey(request, env);
      await env.DB.prepare("INSERT INTO admin_audit_events(id,actor_user_id,action,target_type,target_id,metadata_json,created_at) VALUES(?,?,?,?,?,?,?)")
        .bind(randomId("lfaaudit_"), actor.id, "key_created", "license_key", "new", "{}", nowIso()).run();
      return response;
    }
    const controlKeyMatch = path.match(/^\/api\/control\/keys\/(lfkey_[a-f0-9]+)(?:\/([a-z-]+))?$/);
    if (controlKeyMatch) {
      await assertControlKey(env, actor, controlKeyMatch[1]);
      if (request.method === "GET" && !controlKeyMatch[2]) return json(200, {ok: true, key: await getAdminKey(controlKeyMatch[1], env)});
      if (request.method === "POST" && controlKeyMatch[2]) {
        const response = await adminKeyAction(request, env, controlKeyMatch[1], controlKeyMatch[2]);
        await env.DB.prepare("INSERT INTO admin_audit_events(id,actor_user_id,action,target_type,target_id,metadata_json,created_at) VALUES(?,?,?,?,?,?,?)")
          .bind(randomId("lfaaudit_"), actor.id, `key_${controlKeyMatch[2]}`, "license_key", controlKeyMatch[1], "{}", nowIso()).run();
        return response;
      }
    }
    if (request.method === "GET" && path === "/api/control/orders") return listControlOrders(url, env, actor);
    const controlOrderMatch = path.match(/^\/api\/control\/orders\/(lforder_[a-f0-9]+)(?:\/([a-z-]+))?$/);
    if (controlOrderMatch) {
      await assertControlOrder(env, actor, controlOrderMatch[1]);
      if (request.method === "GET" && !controlOrderMatch[2]) return json(200, {ok: true, order: await getAdminOrder(controlOrderMatch[1], env)});
      if (request.method === "POST" && controlOrderMatch[2]) {
        const response = await adminOrderAction(request, env, controlOrderMatch[1], controlOrderMatch[2]);
        await env.DB.prepare("INSERT INTO admin_audit_events(id,actor_user_id,action,target_type,target_id,metadata_json,created_at) VALUES(?,?,?,?,?,?,?)")
          .bind(randomId("lfaaudit_"), actor.id, `order_${controlOrderMatch[2]}`, "order", controlOrderMatch[1], "{}", nowIso()).run();
        return response;
      }
    }
    if (path.startsWith("/api/control/withdrawals")) {
      if (userRole(actor) !== "owner") throw new HttpError(403, "OWNER_REQUIRED", "只有完全管理员可以处理提现");
      if (request.method === "GET" && path === "/api/control/withdrawals") return listWithdrawals(url, env);
      const match = path.match(/^\/api\/control\/withdrawals\/(lfwithdraw_[a-f0-9]+)\/(paid|reject)$/);
      if (request.method === "POST" && match) return adminWithdrawalAction(request, env, match[1], match[2]);
    }
    throw new HttpError(404, "NOT_FOUND", "not found");
  }

  if (request.method === "GET" && (path === "/admin/control.js" || path === "/admin/control.css")) {
    return staticAsset(request, env, path);
  }

  if (path.startsWith("/admin/") && path !== "/admin/index.html") {
    await requireAdmin(request, env);
    if (request.method === "POST" && path === "/admin/bootstrap-invites") return json(201, {ok: true, invite: await createAdminInvite(await body(request), env, null)});
    if (request.method === "GET" && path === "/admin/orders") return listOrders(url, env);
    if (request.method === "GET" && path === "/admin/withdrawals") return listWithdrawals(url, env);
    const withdrawalMatch = path.match(/^\/admin\/withdrawals\/(lfwithdraw_[a-f0-9]+)\/(paid|reject)$/);
    if (request.method === "POST" && withdrawalMatch) return adminWithdrawalAction(request, env, withdrawalMatch[1], withdrawalMatch[2]);
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
