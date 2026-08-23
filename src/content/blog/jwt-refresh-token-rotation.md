---
title: "JWT Refresh Token Rotation — 왜 필요하고 어떻게 구현하나"
description: "탈취된 Refresh Token이 재사용되는 순간을 감지해서 전체 세션을 무효화하는 구현 정리"
date: "2026-08-24"
tags: ["인증"]
qa_done: true
rewritten: true
---

Access Token은 stateless다

서버가 한 번 발급하면 그 뒤로는 상태를 저장하지 않아서, 탈취당해도 만료 전까지는 막을 방법이 없다

그래서 TTL을 15분처럼 짧게 잡아 탈취 피해를 줄이고, 만료되면 Refresh Token으로 재발급받는 구조를 쓴다

문제는 Refresh Token도 탈취될 수 있다는 것

Rotation은 이 문제에 대한 답이다

갱신할 때마다 새 Refresh Token을 발급하고 구 토큰은 즉시 무효화한다

이미 무효화된 토큰으로 재요청이 오면 그 자체가 탈취 신호고, 전체 세션을 무효화하는 근거가 된다

## 용어 정리

- Access Token: TTL 15분짜리 요청 인증용 토큰, stateless라 DB 조회 없이 서명만 검증
- Refresh Token: TTL 7일짜리 재발급용 토큰, DB에 저장하고 사용 즉시 삭제
- Rotation: 매 refresh마다 구 RT 삭제 + 새 RT 발급하는 일회용 토큰 패턴
- Reuse Detection: 이미 사용된 RT로 요청이 들어오면 탈취로 간주해 전체 세션 무효화
- httpOnly Cookie: JS에서 접근 불가능한 쿠키, XSS로는 RT를 훔칠 수 없음
- jti (JWT ID): 토큰 고유 식별자, UUID로 발급하고 재사용 감지에도 활용 가능

## 어떻게 동작하나

정상 흐름은 단순하다

클라이언트가 `/auth/refresh`를 호출하면 서버는 기존 RT(RT1)를 삭제하고 새 AT2/RT2를 발급한다

문제는 이미 사용된 RT1으로 다시 요청이 오는 경우

서버가 RT1을 삭제하려고 시도하면 이미 없는 레코드라 Prisma가 `P2025 Record Not Found`를 던진다

이 에러를 탈취 신호로 해석해서 `AUTH_INVALID_REFRESH_TOKEN` 예외로 변환하고, 해당 userId의 모든 RT를 삭제한다

### Token Pair 생성

```typescript
async generateTokenPair(userId: string): Promise<TokenPair> {
  const accessToken = this.jwtService.sign(
    { sub: userId, jti: randomUUID() as string },
    {
      secret: this.jwtConfig.accessSecret,
      expiresIn: this.jwtConfig.accessExpiresIn, // "15m"
    },
  )

  const refreshToken = this.jwtService.sign(
    { sub: userId, jti: randomUUID() as string },
    {
      secret: this.jwtConfig.refreshSecret,
      expiresIn: this.jwtConfig.refreshExpiresIn, // "7d"
    },
  )

  await this.refreshTokenRepository.create({
    userId,
    token: refreshToken,
    expiresAt: addDays(new Date(), 7),
  })

  return { accessToken, refreshToken }
}
```

### Rotation — delete-first로 TOCTOU 제거

```typescript
// delete + create 원자성 보장, 빠지면 delete 성공 후 create 실패 시 영구 로그아웃
// 세션 무효화는 tx 바깥에서 실행, tx rollback에 말려들면 보안 조치가 DB에 반영 안 됨
@Transactional()
private async rotate(oldToken: string): Promise<TokenPair> {
  let stored: { userId: string; expiresAt: Date }

  try {
    stored = await this.refreshTokenRepository.delete(oldToken)
    // delete부터 시도해서 findUnique 후 delete 사이의 경합을 제거
  } catch (e) {
    if (e instanceof Prisma.PrismaClientKnownRequestError && e.code === PRISMA_ERROR_CODES.RECORD_NOT_FOUND) {
      throw new DomainException(DOMAIN_ERRORS.AUTH_INVALID_REFRESH_TOKEN)
    }
    throw e
  }

  if (stored.expiresAt < new Date()) {
    throw new DomainException(DOMAIN_ERRORS.AUTH_REFRESH_TOKEN_EXPIRED)
  }

  return this.generateTokenPair(stored.userId)
}
```

findUnique로 먼저 확인하고 delete하는 방식은 그 사이에 다른 요청이 끼어들 여지가 있다

delete부터 시도하고 결과로 존재 여부를 판단하는 쪽이 이 경합을 없앤다

### 탈취 감지 후 세션 무효화는 트랜잭션 바깥에서

```typescript
async rotateRefreshToken(oldToken: string): Promise<TokenPair> {
  try {
    return await this.rotate(oldToken)
  } catch (e) {
    if (e instanceof DomainException) {
      if (e.code === DOMAIN_ERRORS.AUTH_INVALID_REFRESH_TOKEN.code) {
        await this.handleReuseDetected(oldToken)
      } else if (e.code === DOMAIN_ERRORS.AUTH_REFRESH_TOKEN_EXPIRED.code) {
        await this.handleExpiredToken(oldToken)
      }
    }
    throw e
  }
}

private async handleReuseDetected(oldToken: string): Promise<void> {
  // 이미 재사용 감지된 상황이라 토큰이 만료됐어도 userId는 추출해야 함
  await this.invalidateSessionsFromToken(oldToken, true)
}

private async invalidateSessionsFromToken(token: string, ignoreExpiration = false): Promise<void> {
  try {
    const payload = this.jwtService.verify<{ sub: string }>(token, {
      secret: this.jwtConfig.refreshSecret,
      ignoreExpiration,
    })
    await this.refreshTokenRepository.deleteByUserId(payload.sub)
  } catch {
    // 위조 토큰은 userId를 알 수 없어서 전체 무효화가 불가능
  }
}
```

`ignoreExpiration`이 필요한 이유는 재사용 감지 흐름에서는 만료된 토큰이 들어올 수도 있기 때문이다

서명만 검증해서 userId를 뽑아내야 세션을 무효화할 수 있으니, 이 경로에서만 만료 체크를 건너뛴다

`rotate()`는 `@Transactional()` 안에서 도는데, 세션 무효화(`invalidateSessionsFromToken`)는 그 트랜잭션 밖에서 실행한다

`rotate()` 안에서 예외가 던져지면 트랜잭션이 롤백되는데, 세션 무효화까지 같은 트랜잭션 안에 있으면 보안 조치 자체가 롤백되어 DB에 반영되지 않는다

### httpOnly Cookie로 Refresh Token 전달

```typescript
buildRefreshCookieOptions() {
  return {
    httpOnly: true, // JS 접근 차단
    secure: this.appConfig.nodeEnv === 'production', // HTTPS만 전송
    sameSite: 'none' as const, // Cross-site 허용
    maxAge: 7 * 24 * 60 * 60 * 1000,
    path: '/',
  }
}
```

`sameSite: 'none'`은 SPA가 다른 도메인 서버에 요청할 때 쿠키를 포함시키기 위해 필요하다

`strict`로 두면 쿠키 자체가 차단된다

대신 `none`을 쓰려면 `secure: true`가 반드시 같이 있어야 한다

## 클라이언트 토큰 저장 전략

Access Token을 브라우저 어디에 저장하느냐에 따라 공격 표면이 달라진다

| 저장소 | XSS 취약 | CSRF 취약 |
|--------|---------|---------|
| localStorage | 취약 (JS 직접 접근) | 안전 |
| sessionStorage | 취약 (JS 직접 접근) | 안전 |
| httpOnly Cookie | 안전 (JS 접근 불가) | 취약 |
| 메모리 변수 | 안전 (페이지 벗어나면 소멸) | 안전 |

JARVIS는 Access Token을 메모리 변수에, Refresh Token을 httpOnly Cookie에 나눠서 저장한다

Access Token은 XSS로 훔칠 수 없고 탭을 닫으면 사라진다

TTL이 15분이라 새로고침 시 `/auth/refresh`로 다시 받으면 되니까 메모리에 두는 쪽의 손해가 적다

Refresh Token은 JS 접근 자체가 막혀 있고 SameSite 설정으로 CSRF까지 방어한다

localStorage에 Access Token을 저장하면 XSS 한 번으로 장기간 탈취가 가능해서, JARVIS PR #52에서 이 저장 방식을 제거했다

## Gotcha

- `rotate()`에 `@Transactional()` 누락 시 delete 성공 후 create 실패로 영구 로그아웃
- 세션 무효화를 `rotate()` 트랜잭션 안에 두면, 롤백 시 보안 조치도 함께 취소
- `handleRefresh`의 clearCookie 조건은 `DomainException`뿐, 500급 에러에도 clearCookie하면 유효한 RT가 DB에 남았는데 사용자만 로그아웃
- `sameSite: 'none'`은 반드시 `secure: true`와 세트
- `findOrCreateUserFromGoogle`은 `@Transactional()` 없이 P2002 catch 후 재쿼리, 트랜잭션 안에서는 PostgreSQL이 aborted 상태라 재쿼리 자체가 불가능

Rotation 자체는 갱신할 때마다 토큰을 바꾸는 단순한 아이디어인데, 탈취 감지와 트랜잭션 경계를 같이 설계해야 실제로 안전해진다
