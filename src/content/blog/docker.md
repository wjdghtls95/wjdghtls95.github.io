---
title: "Docker — 개발 환경을 코드로 관리하는 법"
description: "Dockerfile 한 장으로 환경을 고정하는 방법과 pnpm 모노레포, Prisma, Railway 배포에서 만나는 함정 정리"
date: "2026-10-08"
tags: ["데이터베이스"]
qa_done: true
rewritten: true
---

"내 컴퓨터에서는 되는데" 문제는 대부분 환경 차이에서 나온다
Node.js 버전, 시스템 라이브러리, 설치된 패키지가 개발 머신과 서버에서 조금씩 다르기 때문이다

Docker는 이 환경 자체를 코드로 정의해서 해결한다
어디서 실행해도 같은 환경이 나오고, 의존성까지 한 덩어리로 패키징된다
Railway 같은 플랫폼은 소스를 직접 빌드하거나 Docker 이미지를 받아서 배포하기 때문에 Dockerfile 한 장이 곧 배포 설명서가 된다

## 용어부터 정리

- **이미지**: 실행 가능한 파일시스템 스냅샷, 레이어가 쌓인 읽기 전용 템플릿
- **컨테이너**: 이미지를 실행한 인스턴스, 프로세스처럼 시작하고 종료된다
- **레이어**: `RUN`, `COPY` 같은 명령어 하나마다 생기는 단위, 변경이 없으면 캐시를 재사용한다
- **Multi-stage Build**: 빌드용 이미지와 실행용 이미지를 나눠서 빌드 도구가 최종 이미지에 안 남게 하는 방식
- **`.dockerignore`**: 빌드 컨텍스트에서 제외할 파일 목록

## JARVIS AI의 Dockerfile

```dockerfile
FROM node:22-alpine
WORKDIR /app

RUN corepack enable && corepack prepare pnpm@latest --activate

COPY . .

RUN pnpm install --frozen-lockfile --ignore-scripts
RUN DATABASE_URL="postgresql://x:x@localhost:5432/x" pnpm --filter server exec prisma generate
RUN pnpm --filter server build

CMD ["sh", "-c", "pnpm --filter server exec prisma migrate deploy && node apps/server/dist/src/main"]
```

짧아 보여도 줄마다 이유가 있다
하나씩 풀어보면 이렇다

### `--ignore-scripts`

```dockerfile
RUN pnpm install --frozen-lockfile --ignore-scripts
```

`package.json`의 `prepare` 스크립트가 `husky install`을 실행하는데, Docker 안에는 git hooks가 필요 없다
게다가 husky는 devDependency라 환경에 따라 아예 없을 수도 있다

`--ignore-scripts`를 주면 `prepare`, `postinstall` 같은 lifecycle 스크립트가 전부 건너뛰어진다
대신 `prisma generate`도 자동 실행이 안 되니까 다음 줄에서 따로 돌려야 한다

`--frozen-lockfile`은 lockfile과 `package.json`이 어긋나면 에러를 내서 CI/CD에서 의존성 일관성을 지켜준다

### 더미 `DATABASE_URL`

```dockerfile
RUN DATABASE_URL="postgresql://x:x@localhost:5432/x" pnpm --filter server exec prisma generate
```

`prisma.config.ts`가 로드될 때 `DATABASE_URL` 환경 변수를 검증한다
그런데 빌드 단계에는 실제 DB가 없다

`prisma generate`는 DB에 연결하지 않고 Prisma Client의 타입 코드만 만든다
그래서 형식만 올바른 가짜 URL을 넣어주면 통과한다

### CMD에서 migrate 먼저

```dockerfile
CMD ["sh", "-c", "pnpm --filter server exec prisma migrate deploy && node apps/server/dist/src/main"]
```

컨테이너가 시작될 때마다 아직 적용 안 된 마이그레이션을 자동으로 적용한다
`&&`로 이어놨기 때문에 migrate가 실패하면 서버는 아예 뜨지 않는다
스키마가 안 맞는 상태로 서버가 돌아가는 것보다 시작 단계에서 멈추는 게 낫다

`sh -c`를 쓴 이유는 `&&` 같은 쉘 체이닝을 CMD 하나로 실행하기 위해서다

### EXPOSE를 일부러 안 쓴다

```dockerfile
# EXPOSE {port} 없음 (의도적)
```

Railway는 `EXPOSE`가 있으면 그 포트로 프록시를 고정한다
서버가 `PORT` 환경 변수 기준으로 다른 포트에서 뜨면 연결이 안 맞아서 502가 난다
`EXPOSE`를 빼면 Railway가 `PORT` 환경 변수를 보고 알아서 라우팅한다

### `.dockerignore`

```
node_modules/
.env
.git/
*.log
dist/
```

`COPY . .`을 할 때 이 목록은 빠진다
`node_modules/`는 로컬에서 설치한 걸 가져오는 대신 Docker 안에서 새로 설치하게 만들고, `.env`는 시크릿이 이미지에 박히는 걸 막는다
이게 없으면 `node_modules/`까지 빌드 컨텍스트에 실려서 빌드 시간이 크게 늘어난다

## Single-stage vs Multi-stage

위 Dockerfile은 단일 스테이지다
표준 패턴인 Multi-stage는 이렇게 생겼다

```dockerfile
# Stage 1: 빌드
FROM node:22-alpine AS builder
WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

# Stage 2: 실행 (빌드 도구 없이 dist만 복사)
FROM node:22-alpine
WORKDIR /app
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
CMD ["node", "dist/main"]
```

실행 이미지에는 빌드 결과물만 들어가니까 devDependency와 빌드 도구가 빠져서 이미지가 훨씬 가벼워진다

그런데도 JARVIS는 단일 스테이지를 쓴다
모노레포라서 workspace 패키지들 사이의 의존성이 얽혀 있고, Multi-stage로 쪼개면 어떤 걸 복사해야 하는지 관리가 복잡해지기 때문이다

| | Single-stage | Multi-stage |
|---|---|---|
| 이미지 크기 | 큼 (devDeps, 빌드 도구 포함) | 작음 |
| Dockerfile 복잡도 | 낮음 | 모노레포에서는 높음 |
| 적합한 상황 | 모노레포, 빠른 초기 배포 | 단일 패키지, 이미지 크기가 중요할 때 |

단일 스테이지는 쉽고 디버깅하기 편한 대신 이미지가 무겁다
이미지 크기나 pull 시간이 문제가 되는 시점이 오면 그때 Multi-stage로 옮기는 게 현실적인 순서다

## 함정 모음

- **`EXPOSE` + Railway**: 포트가 고정돼서 `PORT` 환경 변수가 무시되고 502가 난다
- **`--ignore-scripts` 뒤 `prisma generate`**: lifecycle이 스킵되니 별도로 실행하지 않으면 Prisma Client가 없다
- **alpine 호환성**: 일부 native addon은 alpine의 musl libc 환경에서 빌드가 실패한다, 그럴 땐 debian 기반인 `node:22`를 쓴다
- **`.dockerignore` 누락**: `node_modules/`가 빌드 컨텍스트에 들어가서 빌드 시간이 급증한다
