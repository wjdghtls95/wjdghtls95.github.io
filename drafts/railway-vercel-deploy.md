---
title: "Railway + Vercel 배포 — NestJS + Next.js 실전 배포 가이드"
description: "NestJS는 Railway, Next.js는 Vercel로 나눠 배포할 때 만나는 502, 빌드 실패, Redis TLS 함정 정리"
date: "2026-10-19"
tags: ["데이터베이스"]
qa_done: true
rewritten: true
---

컨테이너가 떴고 health check도 통과했는데 모든 요청이 502로 떨어지는 경우가 있다
원인은 서버가 `127.0.0.1`에만 바인딩돼 있어서 로드밸런서가 컨테이너에 닿지 못하는 것이다

Railway + Vercel 조합은 설정을 최소화해서 프로덕션에 올릴 수 있다는 장점이 있다
AWS EC2는 VPC, 보안 그룹, 로드밸런서, IAM까지 직접 챙겨야 해서 설정 복잡도가 높다
대신 이 조합에도 플랫폼 특유의 규칙이 있고, 모르면 위 같은 증상으로 만난다

## 왜 둘로 나누나

- **Railway**: Docker 컨테이너 기반 PaaS, 서버리스가 아니라 항상 실행 중인 컨테이너
- **Vercel**: Next.js 특화 배포 플랫폼, Edge Network와 CDN, SSR/ISR 최적화

NestJS 서버에는 BullMQ Worker와 SSE가 있다
둘 다 프로세스가 계속 떠 있어야 하고 연결이 유지돼야 한다
Vercel 함수는 요청이 올 때만 실행되는 서버리스라 상시 메모리가 없고, Worker를 돌릴 수 없다

그래서 서버는 Railway, 웹은 Vercel로 분리한다

| | Railway | Vercel |
|--|---------|--------|
| 실행 방식 | 항상 실행 중인 컨테이너 | 요청 시 함수 실행 (서버리스) |
| 적합한 것 | NestJS, BullMQ, WebSocket, SSE | Next.js, 정적 사이트 |
| Cold Start | 없음 | 있음 |
| 비용 | 상시 과금 | 요청당 과금 |
| Dockerfile | 지원 | 미지원 (Next.js 자동 빌드) |

## 배포 흐름

두 플랫폼 모두 GitHub push가 트리거다

```
Railway: push → Dockerfile 빌드 → 컨테이너 실행 → PORT 환경 변수로 바인딩 → 로드밸런서 연결
Vercel:  push → next build → Edge Network 배포 → NEXT_PUBLIC_API_URL로 Railway 서버 호출
```

## 0.0.0.0 바인딩

```typescript
// ❌ 기본값은 localhost(127.0.0.1) 바인딩, Railway 로드밸런서가 접근 못 해서 502
await app.listen(3001);

// ✅ 모든 네트워크 인터페이스에서 수신
await app.listen(process.env.PORT ?? 3001, '0.0.0.0');
```

Docker 컨테이너 안에서 `127.0.0.1`은 컨테이너 자신만 접근할 수 있다
Railway 로드밸런서는 컨테이너 바깥에서 들어오기 때문에 `0.0.0.0`이어야 한다
두 번째 인자를 빠뜨리면 컨테이너는 정상으로 보이는데 요청만 전부 502가 된다

## EXPOSE는 지운다

```dockerfile
# ❌ EXPOSE가 있으면 Railway가 그 포트로 프록시를 고정한다
EXPOSE 3001

# ✅ EXPOSE 없음, PORT 환경 변수 기준으로 자동 라우팅
```

서버는 `PORT=4000`으로 떴는데 `EXPOSE 3001`이 남아 있으면 Railway는 3001로 프록시한다
결과는 또 502다
`EXPOSE`를 지우면 Railway가 `PORT`에 맞춰 알아서 라우팅한다

## 빌드 단계에는 시크릿이 없다

Railway는 빌드 단계와 실행 단계를 분리하고, 빌드 단계에는 `DATABASE_URL` 같은 시크릿을 주입하지 않는다
그런데 Prisma 설정 파일이 로드될 때 `DATABASE_URL`을 검증하면 `prisma generate`에서 빌드가 깨진다

```dockerfile
# ✅ 더미 URL로 형식 검증만 통과시킨다, 실제 DB 연결은 실행 단계에서 일어난다
RUN DATABASE_URL="postgresql://x:x@localhost:5432/x" pnpm --filter server exec prisma generate
```

## husky가 빌드를 막는다

```dockerfile
RUN pnpm install --frozen-lockfile --ignore-scripts
```

`package.json`의 `prepare` 스크립트가 `husky install`을 실행하는데, Docker 이미지에는 git이 없어서 설치가 실패하고 빌드 전체가 멈춘다
`--ignore-scripts`는 `prepare`, `postinstall` 같은 lifecycle 스크립트를 전부 건너뛴다

대신 자동으로 돌던 `prisma generate`도 같이 사라진다
그래서 위처럼 `prisma generate`를 Dockerfile에서 따로 실행해야 한다
`--frozen-lockfile`은 lockfile 변경을 막아서 CI/CD에서 의존성 버전을 고정해준다

## Vercel 환경 변수와 CORS

```
NEXT_PUBLIC_API_URL=https://your-app.railway.app
```

`NEXT_PUBLIC_*`는 브라우저 번들에 그대로 들어간다
시크릿은 절대 넣지 않는다

개발 중 CORS를 피하고 싶으면 `next.config.js`에서 rewrites로 프록시할 수 있다

```typescript
const nextConfig = {
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${process.env.NEXT_PUBLIC_API_URL}/:path*`,
      },
    ]
  },
}
```

배포 환경에서는 서버와 웹이 서로 다른 도메인이라 NestJS 쪽에서 웹 도메인을 허용해야 한다
`origin: [process.env.WEB_URL]` 같은 설정이 없으면 브라우저가 요청을 막는다

## Upstash Redis는 TLS로 붙는다

```
REDIS_URL=rediss://default:password@my-redis.upstash.io:6380
```

스킴이 `redis://`가 아니라 `rediss://`다, 끝의 `s`가 TLS를 뜻한다
URL 스킴으로 TLS 여부를 자동 감지하게 만들어두면 로컬과 배포 환경을 같은 코드로 다룰 수 있다

```typescript
function parseRedis(url: string) {
  const parsed = new URL(url);
  return {
    host: parsed.hostname,
    port: parseInt(parsed.port),
    password: decodeURIComponent(parsed.password),
    tls: url.startsWith('rediss://') ? {} : undefined,
  };
}
```

## 배포 전 체크할 것

- 서버는 `0.0.0.0`으로 listen하고 포트는 `PORT` 환경 변수를 따른다
- Dockerfile에 `EXPOSE`를 두지 않는다
- 빌드 단계에는 시크릿이 없으니 `prisma generate`에는 더미 `DATABASE_URL`을 준다
- `--ignore-scripts`를 쓰면 lifecycle로 돌던 작업은 직접 실행한다
- 상시 프로세스(BullMQ, SSE)는 Railway, Next.js는 Vercel
- 서버와 웹 도메인이 다르니 CORS 허용 도메인을 설정한다
