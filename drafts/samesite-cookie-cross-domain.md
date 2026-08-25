---
title: "SameSite 쿠키와 크로스 도메인 — 배포하면 왜 로그인이 깨지나"
description: "프론트와 서버가 다른 도메인일 때 쿠키가 안 실리는 이유와 SameSite 분기 처리법"
date: "2026-08-26"
tags: ["인증"]
qa_done: true
phase: "auth"
rewritten: true
---

로컬에서는 멀쩡하던 로그인이 배포하면 깨지는 경우가 있다

개발자 도구로 확인해보면 응답에 `Set-Cookie`는 찍히는데 다음 요청에 쿠키가 안 실려있다

프론트엔드(Vercel)와 서버(Railway)가 서로 다른 도메인에 있어서 생기는 문제다

## 왜 필요한가

- `SameSite` 기본값은 브라우저마다 다르고, 최근 브라우저는 기본값을 `Lax`로 강화
- 명시 안 하면 예상치 못한 동작 발생
- 프론트와 서버가 다른 도메인이면 쿠키가 요청에 포함되지 않아 인증이 깨짐
- 로컬(localhost)과 프로덕션(크로스 도메인)에서 요구사항이 다름
- 환경별 분기 필수

## 어떻게 동작하나

`SameSite`는 브라우저가 쿠키를 다른 도메인 요청에 포함할지 결정하는 속성

값에 따라 동작이 다르다

| 값 | 크로스 사이트 GET | 크로스 사이트 POST | 최상위 탐색 | 비고 |
|---|---|---|---|---|
| `Strict` | ❌ | ❌ | ❌ | CSRF 완전 차단, 최고 보안 |
| `Lax` | ✅ (GET만) | ❌ | ✅ | 현대 브라우저 기본값 |
| `None` | ✅ | ✅ | ✅ | 반드시 `Secure: true` 동반 필수 |

`SameSite=None`을 쓰려면 조건이 붙는다

- `Secure` 속성 필수 동반
- `Secure` 없으면 브라우저가 쿠키 설정 자체를 거부
- `Secure`는 HTTPS에서만 쿠키 전송

로컬 개발(`http://localhost`)은 HTTPS가 아니라서 `Secure: false`로 완화해야 한다

같은 사이트 여부는 스킴 + eTLD+1 기준으로 판단한다

- `vercel.app` vs `railway.app` → 다른 사이트, 크로스 사이트
- `app.jarvis.com` vs `api.jarvis.com` → 같은 eTLD+1(`jarvis.com`), 서브도메인은 같은 사이트

## JARVIS에서 실제로 어떻게 썼나

Railway(서버)와 Vercel(웹)은 완전히 다른 도메인이라 모든 요청이 크로스 사이트 요청이다

환경별로 분기해서 처리했다

```typescript
// apps/server/src/auth/auth.service.ts
buildRefreshCookieOptions() {
  const isProd = this.appConfig.nodeEnv === 'production';
  return {
    httpOnly: true,
    secure: isProd,
    sameSite: isProd ? ('none' as const) : ('lax' as const),
    maxAge: 7 * 24 * 60 * 60 * 1000,
    path: '/',
  };
}
```

- 프로덕션은 `none` + `Secure: true`, Vercel에서 Railway로 크로스 도메인 쿠키 전송 허용
- 로컬은 `lax` + `Secure: false`, localhost는 같은 사이트 취급이라 HTTPS 불필요

## 삽질한 것

`clearCookie` 옵션을 set과 다르게 주면 로그아웃이 안 먹는다

```typescript
// ❌ set 시와 다른 옵션으로 clearCookie → 브라우저가 다른 쿠키로 인식, 삭제 안 됨
res.clearCookie(REFRESH_TOKEN_COOKIE, { httpOnly: true, path: '/' });

// ✅ set 시와 동일한 sameSite/secure 옵션 맞춰야 함
res.clearCookie(REFRESH_TOKEN_COOKIE, this.authService.buildClearCookieOptions());
```

브라우저는 쿠키를 `name + domain + path + samesite` 조합으로 식별한다

하나라도 다르면 완전히 다른 쿠키로 취급해서, `clearCookie`를 호출해도 지워지지 않고 그대로 남는다

set과 clear가 같은 옵션 빌더를 공유하도록 만들어야 이 문제를 피할 수 있다
