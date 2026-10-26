// The only way the UI talks to the server: one typed call per contract operation.
// Every outcome comes back as an Envelope — non-2xx and network failures included;
// call() never throws for a server answer.
import { OPERATIONS, type OpId, type Requests, type Responses } from "./generated";

export interface ApiError {
  code: string;
  message_key: string;
  params: Record<string, string>;
  field: string | null;
}

export interface Meta {
  partial: boolean;
  truncated: boolean;
  notes: string[];
}

export interface Envelope<T> {
  ok: boolean;
  data: T | null;
  error: ApiError | null;
  meta: Meta;
}

/** Fired when the server says the session is gone; the app returns to sign-in. */
export const AUTH_REQUIRED_EVENT = "illumio-ops:auth-required";

let csrfToken: string | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

function failure<T>(code: string, messageKey: string, params: Record<string, string> = {}): Envelope<T> {
  return {
    ok: false,
    data: null,
    error: { code, message_key: messageKey, params, field: null },
    meta: { partial: false, truncated: false, notes: [] },
  };
}

function networkFailure<T>(): Envelope<T> {
  return {
    ok: false,
    data: null,
    error: { code: "network_error", message_key: "err_network", params: {}, field: null },
    meta: { partial: false, truncated: false, notes: [] },
  };
}

async function parse<T>(res: Response): Promise<Envelope<T>> {
  try {
    const body: unknown = await res.json();
    if (body && typeof body === "object" && typeof (body as { ok?: unknown }).ok === "boolean") {
      return body as Envelope<T>;
    }
  } catch {
    // not JSON: fall through to a generic HTTP failure
  }
  return failure<T>("http_error", "err_http_error", { status: String(res.status) });
}

async function refreshCsrf(): Promise<string | null> {
  // A GET: needs no token itself, so this cannot recurse.
  const env = await call("auth.csrf");
  csrfToken = env.data?.csrf_token ?? null;
  return csrfToken;
}

function buildPath(template: string, params?: Record<string, string>): string {
  return template.replace(/<(?:\w+:)?(\w+)>/g, (_match, name: string) => {
    const value = params?.[name];
    if (value === undefined) throw new Error(`missing path parameter ${name}`);
    return encodeURIComponent(value);
  });
}

export async function call<Op extends OpId>(
  op: Op,
  body?: Requests[Op],
  params?: Record<string, string>,
  query?: Record<string, string>,
): Promise<Envelope<Responses[Op]>> {
  const { method, path } = OPERATIONS[op];
  const search = query ? new URLSearchParams(Object.entries(query).filter(([, v]) => v !== "")).toString() : "";
  const url = buildPath(path, params) + (search ? `?${search}` : "");

  const send = async (): Promise<Response> => {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (method !== "GET") {
      headers["Content-Type"] = "application/json";
      const token = csrfToken ?? (await refreshCsrf());
      if (token) headers["X-CSRFToken"] = token;
    }
    return fetch(url, {
      method,
      credentials: "same-origin",
      headers,
      body: method === "GET" ? undefined : JSON.stringify(body ?? {}),
    });
  };

  let res: Response;
  let env: Envelope<Responses[Op]>;
  try {
    res = await send();
    env = await parse<Responses[Op]>(res);
    if (!env.ok && env.error?.code === "csrf_error") {
      // The server hands a fresh token with the error; retry exactly once.
      const fresh = (env.data as { csrf_token?: string } | null)?.csrf_token;
      csrfToken = fresh ?? (await refreshCsrf());
      res = await send();
      env = await parse<Responses[Op]>(res);
    }
  } catch {
    return networkFailure<Responses[Op]>();
  }
  if (res.status === 401 && op !== "auth.login") {
    window.dispatchEvent(new Event(AUTH_REQUIRED_EVENT));
  }
  return env;
}
