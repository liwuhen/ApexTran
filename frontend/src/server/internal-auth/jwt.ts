import { createHmac, randomUUID } from "node:crypto";

const DEFAULT_ISSUER = "apextran-bff";
const DEFAULT_AUDIENCE = "apextran-app";
const DEFAULT_TTL_SECONDS = 300;

function base64url(value: Buffer | string) {
  return Buffer.from(value).toString("base64url");
}

export function signInternalJwt({
  userId,
  scopes,
  audience = process.env.APEXTRAN_INTERNAL_JWT_AUDIENCE ?? DEFAULT_AUDIENCE,
}: {
  userId: string;
  scopes: string[];
  audience?: string;
}) {
  const issuer = process.env.APEXTRAN_INTERNAL_JWT_ISSUER ?? DEFAULT_ISSUER;
  const secret = process.env.APEXTRAN_INTERNAL_JWT_SECRET;
  if (!secret) {
    throw new Error("APEXTRAN_INTERNAL_JWT_SECRET is not configured");
  }
  const now = Math.floor(Date.now() / 1000);
  const header = {
    alg: "HS256",
    typ: "JWT",
    kid: process.env.APEXTRAN_INTERNAL_JWT_KEY_ID ?? "dev",
  };
  const payload = {
    iss: issuer,
    aud: audience,
    sub: userId,
    scope: scopes,
    iat: now,
    exp: now + DEFAULT_TTL_SECONDS,
    jti: randomUUID(),
  };
  const encodedHeader = base64url(JSON.stringify(header));
  const encodedPayload = base64url(JSON.stringify(payload));
  const signingInput = `${encodedHeader}.${encodedPayload}`;
  const signature = createHmac("sha256", secret)
    .update(signingInput)
    .digest("base64url");
  return `${signingInput}.${signature}`;
}
