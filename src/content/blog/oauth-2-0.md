---
title: "OAuth 2.0 — Google 소셜 로그인 흐름 완전 정복"
description: "비밀번호 없이 Google이 인증을 대신하고 JARVIS는 발급받은 코드로 토큰만 교환하는 흐름 정리"
date: "2026-08-25"
tags: ["인증"]
qa_done: true
rewritten: true
phase: "auth"
---

유저의 Google 비밀번호를 JARVIS가 직접 받는 건 애초에 불가능한 선택지다

비밀번호가 유출되면 JARVIS 하나가 아니라 Google 계정 전체가 위험해진다

그렇다고 직접 회원가입을 구현하면 비밀번호 저장, 이메일 인증, 비밀번호 찾기까지 인증 인프라가 통째로 필요해진다

OAuth 2.0은 이 문제를 뒤집는다

Google이 대신 인증하고, JARVIS는 그 결과만 믿는다

비밀번호는 한 번도 JARVIS 서버를 거치지 않는다

## 용어 정리

- Authorization Code Flow: 브라우저 리다이렉트 기반 OAuth 흐름, 코드를 토큰으로 교환
- Authorization Code: 일회용 짧은 수명의 코드, Google 인증 후 callback URL로 전달
- scope: 요청하는 권한 범위 (`email`, `profile`, `calendar`)
- Sensitive Scope: Google 심사가 필요한 민감한 권한, calendar 읽기/쓰기 포함
- `accessType: 'offline'`: Refresh Token 포함 요청, Calendar 백그라운드 접근에 필요
- `prompt: 'consent'`: 매번 권한 동의 화면 표시, Refresh Token이 항상 포함되도록 강제

## 어떻게 동작하나

전체 흐름은 이렇다

1. 유저가 `/auth/google`에 접근하면 JARVIS가 scope, client_id, redirect_uri를 담아 Google로 리다이렉트
2. Google이 로그인 + 권한 동의 화면을 보여주고, 유저가 동의
3. Google이 `/auth/google/callback?code=AUTH_CODE`로 JARVIS를 다시 호출
4. JARVIS가 이 code와 client_secret으로 Google에 토큰을 요청 (Passport가 자동 처리)
5. Google이 access_token, refresh_token, profile을 반환
6. JARVIS가 profile로 유저를 찾거나 생성하고, 자체 JWT 토큰 페어를 발급
7. 브라우저는 발급받은 Access Token으로 `/auth/me`를 호출해 로그인을 완료

Google이 인증을 대신하고, JARVIS는 그 결과(profile)를 받아서 자기 시스템의 유저로 연결하는 게 핵심이다

## JARVIS에서 실제로 어떻게 썼나

### GoogleStrategy — scope + accessType 설정

Passport 공식 예제는 scope에 `email`, `profile`만 넣는다

```typescript
@Injectable()
export class GoogleStrategy extends PassportStrategy(Strategy, 'google') {
  constructor() {
    super({
      clientID: process.env.GOOGLE_CLIENT_ID,
      clientSecret: process.env.GOOGLE_CLIENT_SECRET,
      callbackURL: 'http://localhost:3000/auth/google/callback',
      scope: ['email', 'profile'],
    });
  }

  async validate(accessToken: string, refreshToken: string, profile: any, done: VerifyCallback) {
    done(null, profile);
  }
}
```

JARVIS는 Google Calendar 연동이 필요해서 여기에 두 가지를 더 얹는다

```typescript
@Injectable()
export class GoogleStrategy extends PassportStrategy(Strategy, 'google') {
  constructor(private readonly authService: AuthService, config: ConfigType<typeof googleConfig>) {
    super({
      clientID: config.clientId,
      clientSecret: config.clientSecret,
      callbackURL: config.callbackUrl,
      scope: ['email', 'profile', 'https://www.googleapis.com/auth/calendar'],
      // @types/passport-google-oauth20에 없는 파라미터라 as any로 우회
      accessType: 'offline',   // Refresh Token 포함
      prompt: 'consent',       // 매번 동의 화면 — RT 항상 받음
    } as any);
  }

  async validate(accessToken: string, refreshToken: string, profile: any, done: VerifyCallback) {
    const email = profile.emails?.[0]?.value;
    if (!email) throw new DomainException(DOMAIN_ERRORS.AUTH_GOOGLE_FAILED);

    const user = await this.authService.findOrCreateUserFromGoogle({
      providerId: profile.id,
      email,
      name: profile.displayName,
      accessToken,
      refreshToken,
    });
    done(null, user);
  }
}
```

`scope`에 calendar 권한을 추가했고, `accessType: 'offline'`으로 Google Refresh Token을 받는다

`prompt: 'consent'`가 없으면 재로그인 시 Refresh Token이 빠진다

### Controller — callback에서 토큰 전달

```typescript
@Get('google/callback')
@UseGuards(GoogleAuthGuard)
async handleGoogleCallback(@Req() req: Request, @Res() res: Response) {
  const user = req.user as User; // GoogleStrategy.validate()의 반환값
  const tokens = await this.authService.generateTokenPair(user.id);

  // Refresh Token → httpOnly 쿠키
  res.cookie(REFRESH_TOKEN_COOKIE, tokens.refreshToken, this.authService.buildRefreshCookieOptions());

  // Access Token → URL fragment — 서버 로그에 남지 않음
  res.redirect(`${this.appConfig.webUrl}/auth/callback#token=${tokens.accessToken}`);
}
```

Access Token을 쿼리스트링이 아니라 URL fragment(`#token=...`)로 보내는 이유가 있다

fragment는 브라우저가 서버로 전송하지 않는다

서버 접근 로그 어디에도 토큰이 남지 않고, Next.js `/auth/callback` 페이지가 `window.location.hash`로 직접 추출한다

### 클라이언트 callback 처리

```typescript
export default function CallbackPage() {
  const router = useRouter()
  const setUser = useAuthStore((s) => s.setUser)

  useEffect(() => {
    const hash = window.location.hash.slice(1) // '#token=...' → 'token=...'
    const token = new URLSearchParams(hash).get('token')

    if (!token) {
      router.replace('/login')
      return
    }

    apiFetch<MeResponse>('/auth/me', {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((res) => {
        setAccessToken(token)
        setUser(res.data)

        const isOnboarded = localStorage.getItem('jarvis_onboarded')
        router.replace(isOnboarded ? '/home' : '/onboarding')
      })
      .catch(() => {
        clearAccessToken()
        router.replace('/login')
      })
  }, [router, setUser])
}
```

### scope는 다 같은 scope가 아니다

| scope | 종류 | Google 심사 |
|-------|------|------------|
| `email`, `profile` | Basic | 불필요 |
| `https://www.googleapis.com/auth/calendar` | Sensitive | 공개 배포 전 심사 필요 (영업일 3~5일) |

JARVIS는 공개 배포 전에 이 Sensitive Scope 심사를 따로 신청해야 한다

## Gotcha

- `accessType: 'offline'` + `prompt: 'consent'`는 항상 쌍으로 써야 한다, 하나라도 빠지면 첫 로그인에만 RT가 오고 재로그인부터는 미포함되어 Calendar 백그라운드 접근이 끊긴다
- `@types/passport-google-oauth20`가 `accessType`, `prompt` 타입을 지원하지 않아서 `as any` 캐스팅으로 우회했다
- `profile.emails?.[0]?.value`는 optional chaining이 필수다, 일부 Google 계정은 이메일이 없을 수 있다
- 콜백 URL 도메인이 Google Cloud Console의 `Authorized redirect URIs`와 정확히 일치해야 한다, 다르면 `redirect_uri_mismatch` 에러가 난다
- 로컬 개발환경의 `http://localhost` 콜백 URL도 Google Console에 별도로 등록해야 동작한다

OAuth 자체는 인증을 Google에 위임하는 단순한 아이디어지만, scope 설계와 토큰 전달 방식까지 같이 맞춰야 실제로 안전하게 동작한다
