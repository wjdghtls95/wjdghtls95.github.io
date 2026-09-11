---
title: "NestJS Config Pattern — 환경변수를 타입 안전하게 관리하는 법"
description: "registerAs와 @Inject로 환경변수에 타입을 입혀서 오타를 컴파일 타임에 잡는 방법"
date: "2026-09-11"
tags: ["NestJS"]
qa_done: true
rewritten: true
---

`ConfigService.get<string>('jwt.accessSecret')` 같은 코드는 문자열 키에 의존한다

키를 오타 내도 컴파일은 통과하고, 런타임에 `undefined`가 나서야 문제를 알게 된다

`@nestjs/config`의 `registerAs`를 쓰면 이 문자열 키 접근을 인터페이스 기반 주입으로 바꿀 수 있다

## 어떻게 동작하나

전체 흐름은 이렇다

```
.env 파일
  → ConfigModule.forRoot (validate 실행)
  → 실패 시 앱 즉시 종료
  → 성공 시 registerAs factory 실행
  → jwtConfig / appConfig / googleConfig 객체 생성
  → DI 컨테이너 등록
  → @Inject(jwtConfig.KEY)로 각 서비스에 주입
```

`registerAs('jwt', factory)`가 하는 일:

- `'jwt'` 네임스페이스 아래 config 객체 등록
- `.KEY` 프로퍼티로 DI 토큰 노출 (`jwtConfig.KEY === 'jwt'`)
- factory 반환 타입을 TypeScript가 그대로 추론

```ts
export interface JwtConfig {
  accessSecret: string;
  refreshSecret: string;
  accessExpiresIn: string;
  refreshExpiresIn: string;
}

export default registerAs(
  'jwt',
  (): JwtConfig => ({
    accessSecret: process.env.JWT_ACCESS_SECRET!,
    refreshSecret: process.env.JWT_REFRESH_SECRET!,
    accessExpiresIn: process.env.JWT_ACCESS_EXPIRES_IN ?? '15m',
    refreshExpiresIn: process.env.JWT_REFRESH_EXPIRES_IN ?? '7d',
  }),
);
```

`!` 단언이 안전한 이유는 앱 시작 시점에 `validate()`가 이미 검증을 끝내기 때문

```ts
export function validate(config: Record<string, unknown>) {
  const validated = plainToInstance(EnvironmentVariables, config, {
    enableImplicitConversion: true,
  });
  const errors = validateSync(validated, { skipMissingProperties: false });

  if (errors.length > 0) {
    throw new Error(`Env validation failed:\n${errors.join('\n')}`);
  }

  return validated;
}
```

`.env`를 읽고, class-validator로 검증하고, 실패하면 그 자리에서 앱을 죽인다

런타임 중간에 터지는 대신 시작 시점에 바로 잡힌다는 게 핵심

## JARVIS에서 실제로 어떻게 썼나

config를 도메인별로 쪼갰다

```
config/
  app.config.ts     ← 서버 일반 (port, nodeEnv, webUrl, redis 등)
  jwt.config.ts     ← JWT 전용 (secret, expiresIn)
  google.config.ts  ← Google OAuth 전용 (clientId, clientSecret, callbackUrl)
```

이유는 세 가지

- 관심사 분리, jwt 설정이 바뀌어도 app.config는 안 건드림
- 주입 단위 최소화, AuthService는 jwtConfig만, GoogleStrategy는 googleConfig만 받음
- 테스트 편의, 특정 config만 mock 가능

Redis 연결 정보처럼 값이 여러 소스에서 올 수 있는 경우는 factory 안에서 분기 처리한다

```ts
function parseRedis(): Pick<AppConfig, 'redisHost' | 'redisPort' | 'redisPassword' | 'redisTls'> {
  const redisUrl = process.env.REDIS_URL;

  if (redisUrl) {
    const url = new URL(redisUrl);
    return {
      redisHost: url.hostname,
      redisPort: parseInt(url.port, 10),
      redisPassword: url.password || undefined,
      redisTls: url.protocol === 'rediss:',
    };
  }

  return {
    redisHost: process.env.REDIS_HOST ?? 'localhost',
    redisPort: parseInt(process.env.REDIS_PORT ?? '6379', 10),
    redisPassword: process.env.REDIS_PASSWORD,
    redisTls: false,
  };
}
```

`REDIS_URL`이 있으면 파싱해서 쓰고, 없으면 개별 환경변수를 조합한다

Upstash처럼 URL 하나로 Redis를 주는 서비스와 로컬 개발 환경을 같은 코드로 커버하려고 이렇게 나눴다

주입하는 위치별로 문법이 조금씩 다르다

```ts
// Injectable class
@Injectable()
export class AuthService {
  constructor(
    @Inject(jwtConfig.KEY) private readonly jwtConfig: JwtConfig,
    @Inject(appConfig.KEY) private readonly appConfig: AppConfig,
  ) {}
}
```

```ts
// forRootAsync factory (BullMQ 등)
BullModule.forRootAsync({
  inject: [appConfig.KEY],
  useFactory: (config: AppConfig) => ({
    connection: { host: config.redisHost, port: config.redisPort },
  }),
}),
```

```ts
// DI 컨테이너 밖에서 직접 꺼낼 때
this.appConfig = app.get(ConfigService).get<AppConfig>('app')!;
```

## 삽질한 것

**필드명 충돌**

```ts
// ❌ import한 jwtConfig와 필드명 jwtConfig가 겹쳐서 순환 참조 에러
@Inject(jwtConfig.KEY) private readonly jwtConfig: JwtConfig
```

인터페이스(`JwtConfig`)를 타입으로 직접 import해서 쓰면 피할 수 있다

**`isGlobal` 빼먹기**

`ConfigModule.forRoot`에 `isGlobal: true`를 안 넣으면 모듈마다 `ConfigModule`을 따로 import해야 한다

거의 항상 global로 켜두는 게 맞다

**문자열 키 재사용**

```ts
// ❌ 같은 config를 여러 번 get
const host = this.config.get<AppConfig>('app')!.redisHost;
const port = this.config.get<AppConfig>('app')!.redisPort;
```

```ts
// ✅ 한 번에 구조분해
const { redisHost, redisPort } = this.config.get<AppConfig>('app')!;
```

작은 습관이지만 문자열 키로 `get`을 반복 호출할 때마다 오타 위험이 다시 열린다는 걸 기억해두면 좋다
