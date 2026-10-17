import { createHash, pbkdf2Sync, randomBytes, timingSafeEqual } from 'node:crypto';
import { getDatabase } from '@netlify/database';

const db = getDatabase();
const SESSION_COOKIE = 'finova_session';
const SESSION_SECONDS = 60 * 60 * 24 * 7;
const JSON_HEADERS = {
  'Content-Type': 'application/json; charset=utf-8',
  'Cache-Control': 'no-store',
  'X-Content-Type-Options': 'nosniff',
};

function reply(payload, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { ...JSON_HEADERS, ...extraHeaders },
  });
}

function digestToken(token) {
  return createHash('sha256').update(token).digest('hex');
}

function passwordDigest(password, salt) {
  return pbkdf2Sync(password, salt, 310_000, 32, 'sha256').toString('hex');
}

function cookieValue(request, name) {
  const cookie = request.headers.get('cookie') || '';
  const entry = cookie.split(';').map(value => value.trim()).find(value => value.startsWith(`${name}=`));
  return entry ? decodeURIComponent(entry.slice(name.length + 1)) : '';
}

function setCookie(token) {
  return `${SESSION_COOKIE}=${encodeURIComponent(token)}; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=${SESSION_SECONDS}`;
}

function clearCookie() {
  return `${SESSION_COOKIE}=; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=0`;
}

async function requestData(request) {
  const length = Number(request.headers.get('content-length') || 0);
  if (length > 2_000_000) throw new Error('La solicitud es demasiado grande.');
  const body = await request.json();
  if (JSON.stringify(body).length > 2_000_000) throw new Error('La solicitud es demasiado grande.');
  return body;
}

async function sessionUser(request) {
  const token = cookieValue(request, SESSION_COOKIE);
  if (!token) return null;
  const tokenHash = digestToken(token);
  const rows = await db.sql`
    SELECT users.id, users.username
    FROM sessions JOIN users ON users.id = sessions.user_id
    WHERE sessions.token_hash = ${tokenHash} AND sessions.expires_at > NOW()
    LIMIT 1
  `;
  return rows[0] || null;
}

async function createSession(userId) {
  const token = randomBytes(32).toString('hex');
  const tokenHash = digestToken(token);
  await db.sql`
    INSERT INTO sessions (token_hash, user_id, expires_at)
    VALUES (${tokenHash}, ${userId}, NOW() + INTERVAL '7 days')
  `;
  return token;
}

async function getData(userId) {
  const [movements, loans, goals, events] = await Promise.all([
    db.sql`SELECT id, type, category, title, amount::float8 AS amount, occurred_at AS date FROM movements WHERE user_id = ${userId} ORDER BY occurred_at`,
    db.sql`SELECT id, name, entity, principal::float8 AS principal, paid::float8 AS paid, interest::float8 AS interest, interest_type AS "interestType", created_at AS created FROM loans WHERE user_id = ${userId}`,
    db.sql`SELECT id, name, target::float8 AS target, saved::float8 AS saved, due, emoji FROM goals WHERE user_id = ${userId}`,
    db.sql`SELECT id, kind, title, amount::float8 AS amount, occurred_at AS date, note FROM events WHERE user_id = ${userId} ORDER BY occurred_at`,
  ]);
  return { movements, loans, goals, events };
}

function positive(value, label, max = 1_000_000_000_000) {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0 || number > max) throw new Error(`${label} no es válido.`);
  return number;
}

function nonNegative(value, label, max = 1_000_000_000_000) {
  const number = Number(value || 0);
  if (!Number.isFinite(number) || number < 0 || number > max) throw new Error(`${label} no es válido.`);
  return number;
}

async function saveData(userId, payload) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) throw new Error('Formato de información inválido.');
  const keys = ['movements', 'loans', 'goals', 'events'];
  for (const key of keys) {
    if (!Array.isArray(payload[key]) || payload[key].length > 10_000) throw new Error(`La lista ${key} no es válida.`);
  }

  const client = await db.pool.connect();
  try {
    await client.query('BEGIN');
    for (const table of keys) await client.query(`DELETE FROM ${table} WHERE user_id = $1`, [userId]);
    for (const x of payload.movements) {
      if (!['income', 'expense'].includes(x.type)) throw new Error('Tipo de movimiento inválido.');
      await client.query('INSERT INTO movements (id,user_id,type,category,title,amount,occurred_at) VALUES ($1,$2,$3,$4,$5,$6,$7)',
        [String(x.id), userId, x.type, String(x.category), String(x.title), positive(x.amount, 'El monto'), String(x.date)]);
    }
    for (const x of payload.loans) {
      const principal = positive(x.principal, 'El valor del préstamo');
      const paid = Number(x.paid || 0);
      if (!Number.isFinite(paid) || paid < 0 || paid > principal) throw new Error('El total abonado no es válido.');
      await client.query('INSERT INTO loans (id,user_id,name,entity,principal,paid,interest,interest_type,created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)',
        [String(x.id), userId, String(x.name), String(x.entity || ''), principal, paid, Number(x.interest || 0), x.interestType === 'monthly' ? 'monthly' : 'annual', String(x.created)]);
    }
    for (const x of payload.goals) {
      const saved = nonNegative(x.saved, 'El ahorro acumulado');
      await client.query('INSERT INTO goals (id,user_id,name,target,saved,due,emoji) VALUES ($1,$2,$3,$4,$5,$6,$7)',
        [String(x.id), userId, String(x.name), positive(x.target, 'El objetivo'), saved, String(x.due || ''), String(x.emoji || '✳')]);
    }
    for (const x of payload.events) {
      if (!['loan', 'goal'].includes(x.kind)) throw new Error('Tipo de abono inválido.');
      await client.query('INSERT INTO events (id,user_id,kind,title,amount,occurred_at,note) VALUES ($1,$2,$3,$4,$5,$6,$7)',
        [String(x.id), userId, x.kind, String(x.title), positive(x.amount, 'El monto del abono'), String(x.date), String(x.note || '')]);
    }
    await client.query('COMMIT');
  } catch (error) {
    await client.query('ROLLBACK');
    throw error;
  } finally {
    client.release();
  }
}

async function handle(request) {
  const { pathname } = new URL(request.url);
  const action = pathname.split('/').filter(Boolean).at(-1);
  if (request.method === 'GET' && action === 'me') {
    const user = await sessionUser(request);
    return reply({ user: user?.username || null });
  }
  if (request.method === 'POST' && action === 'register') {
    const body = await requestData(request);
    const username = String(body.username || '').trim();
    const password = String(body.password || '');
    if (username.length < 3 || username.length > 40 || password.length < 8 || password.length > 256) {
      return reply({ error: 'Usa un usuario de 3 a 40 caracteres y una contraseña de 8 a 256 caracteres.' }, 400);
    }
    const salt = randomBytes(16).toString('hex');
    try {
      const rows = await db.sql`
        INSERT INTO users (username, username_key, password_salt, password_hash)
        VALUES (${username}, ${username.toLocaleLowerCase('en-US')}, ${salt}, ${passwordDigest(password, salt)})
        RETURNING id, username
      `;
      const token = await createSession(rows[0].id);
      return reply({ user: rows[0].username }, 201, { 'Set-Cookie': setCookie(token) });
    } catch (error) {
      if (error.code === '23505') return reply({ error: 'Ese usuario ya existe.' }, 409);
      throw error;
    }
  }
  if (request.method === 'POST' && action === 'login') {
    const body = await requestData(request);
    const username = String(body.username || '').trim();
    const password = String(body.password || '');
    const rows = await db.sql`SELECT id, username, password_salt, password_hash FROM users WHERE username_key = ${username.toLocaleLowerCase('en-US')} LIMIT 1`;
    if (!rows.length) return reply({ error: 'Usuario o contraseña incorrectos.' }, 401);
    const user = rows[0];
    const actual = Buffer.from(passwordDigest(password, user.password_salt), 'hex');
    const expected = Buffer.from(user.password_hash, 'hex');
    if (actual.length !== expected.length || !timingSafeEqual(actual, expected)) return reply({ error: 'Usuario o contraseña incorrectos.' }, 401);
    const token = await createSession(user.id);
    return reply({ user: user.username }, 200, { 'Set-Cookie': setCookie(token) });
  }
  if (request.method === 'POST' && action === 'logout') {
    const token = cookieValue(request, SESSION_COOKIE);
    if (token) await db.sql`DELETE FROM sessions WHERE token_hash = ${digestToken(token)}`;
    return reply({ ok: true }, 200, { 'Set-Cookie': clearCookie() });
  }
  if (request.method === 'GET' && action === 'data') {
    const user = await sessionUser(request);
    if (!user) return reply({ error: 'Inicia sesión para continuar.' }, 401);
    return reply(await getData(user.id));
  }
  if (request.method === 'POST' && action === 'data') {
    const user = await sessionUser(request);
    if (!user) return reply({ error: 'Inicia sesión para continuar.' }, 401);
    await saveData(user.id, await requestData(request));
    return reply({ ok: true });
  }
  return reply({ error: 'Ruta no encontrada.' }, 404);
}

export default async (request) => {
  try {
    return await handle(request);
  } catch (error) {
    console.error('FINOVA API error:', error);
    return reply({ error: 'No se pudo procesar la solicitud.' }, 500);
  }
};

export const config = { path: '/api/*' };
