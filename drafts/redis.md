---
title: "Redis — 캐시 그 이상, 어떻게 쓰는가"
description: "인메모리 Key-Value 저장소 Redis를 캐시와 BullMQ 잡 저장소로 쓸 때 알아야 할 TTL, TLS, 키 충돌 함정"
date: "2026-10-27"
tags: ["데이터베이스"]
qa_done: true
rewritten: true
---

Redis는 RAM에 데이터를 두는 인메모리 Key-Value 저장소야
디스크를 거치는 DB보다 응답이 훨씬 빠르고, 키마다 TTL(자동 만료 시간)을 걸 수 있어서 캐시에 딱 맞아
여기에 List, Hash, Set, Sorted Set 같은 자료구조까지 있어서 캐시를 넘어 큐 저장소로도 쓰여

## 왜 캐시로 쓰는가

비용이 큰 작업의 결과를 잠깐 들고 있다가 같은 요청이 오면 그대로 돌려주는 게 캐시의 전부야
JARVIS 서버에서는 브리핑 생성이 그런 작업이야
AI API 호출과 DB 쿼리가 함께 들어가니까 같은 유저가 같은 날 다시 요청하면 매번 만들 이유가 없어

```typescript
const cacheKey = `briefing:${userId}:${dateKey}`;
const cached = await this.cacheService.get(cacheKey);

if (cached) {
  return JSON.parse(cached);  // 캐시 히트: 생성 없이 바로 반환
}

const briefing = await this.generateBriefing(userId);
await this.cacheService.set(cacheKey, JSON.stringify(briefing), 60 * 60 * 24);  // 24시간 TTL
```

캐시에서 찾으면 히트, 없으면 미스야
미스일 때만 실제로 생성하고 결과를 저장해
TTL을 24시간으로 잡아두면 다음 날엔 알아서 만료돼서 별도로 지울 필요가 없어

## CacheService로 감싸기

JARVIS 서버는 ioredis 클라이언트를 CacheService 하나로 감싸서 get, set, del만 노출해

```typescript
@Injectable()
export class CacheService {
  constructor(@Inject('REDIS_CLIENT') private readonly redis: Redis) {}

  async get(key: string): Promise<string | null> {
    return this.redis.get(key);
  }

  async set(key: string, value: string, ttlSeconds: number): Promise<void> {
    await this.redis.set(key, value, 'EX', ttlSeconds);
  }

  async del(key: string): Promise<void> {
    await this.redis.del(key);
  }
}
```

`'EX'`는 초 단위 TTL이고 `'PX'`는 밀리초야
단위를 헷갈리면 캐시가 1000배 오래 살거나 순식간에 사라지니까 조심해야 해

Redis는 값을 string으로만 저장해서 객체는 이렇게 다뤄

```typescript
// ✅ 저장할 땐 stringify, 읽을 땐 null 체크 후 parse
await redis.set('user:1', JSON.stringify({ name: 'Jungho' }), 'EX', 3600);
const value = await redis.get('user:1');
const user = value ? JSON.parse(value) : null;

// ❌ 객체를 그대로 넣거나, null인데 바로 parse
await redis.set('user:1', { name: 'Jungho' });   // "[object Object]"가 저장됨
JSON.parse(await redis.get('user:2'));            // 없는 키면 null을 parse하게 됨
```

## BullMQ가 Redis를 쓰는 방식

BullMQ는 잡 상태를 Redis 자료구조로 관리해
대기 중인 잡은 List, 지연 잡은 Sorted Set(스코어가 실행 시각), 잡 상태 정보는 Hash에 들어가

```typescript
// 로컬 Redis
BullModule.forRoot({
  connection: { host: 'localhost', port: 6379 },
})

// Upstash Redis (TLS 필수)
BullModule.forRoot({
  connection: {
    host: REDIS_HOST,
    port: REDIS_PORT,
    password: REDIS_PASSWORD,
    tls: {},
  },
})
```

캐시와 큐가 같은 Redis를 쓰게 되는 순간 키 충돌을 신경 써야 해
BullMQ는 `bull:*` 패턴의 키를 쓰니까 앱 캐시 키는 `briefing:` 같은 prefix로 확실히 구분해둬야 해
그리고 BullMQ는 자기 ioredis 연결을 따로 쓰기 때문에 NestJS 쪽 Redis 클라이언트와 설정을 각각 관리해야 해

## Upstash Redis와 TLS

Upstash 같은 관리형 Redis는 URL 스킴부터 달라

```
REDIS_URL=rediss://default:password@my-redis.upstash.io:6380
```

`redis://`는 평문이고 `rediss://`는 TLS야 's' 하나 차이지만 연결 방식이 완전히 달라
URL을 host, port로 쪼개서 옵션 객체로 넘기면 `rediss://` 스킴 정보가 사라져서 `tls` 옵션이 없을 때 TLS 없이 붙으려다 연결이 실패해
빈 객체 `{}`라도 넣어야 활성화돼

```typescript
function parseRedis(url: string) {
  const parsed = new URL(url);
  return {
    host: parsed.hostname,
    port: parseInt(parsed.port),
    password: decodeURIComponent(parsed.password),
    tls: url.startsWith('rediss://') ? {} : undefined,  // 스킴으로 TLS 여부 자동 감지
  };
}
```

URL을 직접 파싱해서 스킴으로 TLS를 결정하면 로컬은 평문, 배포 환경은 TLS로 같은 코드가 돌아가

## 정리 대신 체크할 것

- 저장 전 `JSON.stringify`, 읽은 뒤 `null` 체크 후 `JSON.parse`
- TTL 단위는 `'EX'`가 초, `'PX'`가 밀리초
- `rediss://`면 `tls: {}` 필수
- 캐시 키와 BullMQ 키는 prefix로 분리
- 원본이 바뀌면 캐시를 지워야 하는 캐시 무효화는 TTL만으로 해결 안 되는 경우가 있으니 처음부터 염두에 둘 것

Redis는 데이터를 RAM에 두는 만큼 영속성은 설정에 따라 달라져서, 유실되면 안 되는 데이터의 원본은 PostgreSQL 같은 DB에 두고 Redis는 캐시와 큐 용도로 쓰는 게 안전해
