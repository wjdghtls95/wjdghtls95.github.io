---
title: "FastAPI 기초 — NestJS 개발자가 Python으로 넘어갈 때"
description: "lifespan, Depends, StreamingResponse로 보는 FastAPI의 핵심 구조와 NestJS 개념 대응, 실전에서 걸리는 함정"
date: "2026-11-11"
tags: ["Python"]
qa_done: true
rewritten: true
---

AI 추론 서버는 대부분의 시간을 외부 모델 응답을 기다리며 보낸다
그래서 요청 하나가 worker를 붙잡고 있는 동기 방식은 잘 맞지 않는다

Flask는 동기 기반이라 이런 I/O 위주 작업에서 worker thread를 block한다
Django는 풀스택이라 ML 서빙에 필요 없는 기능이 너무 많다
FastAPI는 async/await 네이티브에 Pydantic 자동 검증, 자동 OpenAPI 문서까지 붙어 있어서 추론 서버에 가장 잘 맞는다

NestJS를 쓰던 사람 기준으로, JARVIS 추론 서버 코드를 따라가며 정리한다

## 요청이 지나가는 길

```
HTTP 요청
  → Uvicorn (ASGI 서버)
  → FastAPI app
  → Middleware
  → Router 매칭
  → Depends 해결 (verify_internal_token)
  → Request Body Pydantic 검증
  → Handler 실행
  → JSONResponse 또는 StreamingResponse
```

Uvicorn이 ASGI 서버로 앱을 실제로 띄우고, FastAPI는 그 위에서 라우팅과 검증을 맡는다
NestJS의 요청 생명주기와 순서가 거의 같아서 머릿속 지도를 그대로 옮겨 쓸 수 있다

## 앱 생성과 Router 등록

공식 예제는 이렇게 단순하다

```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/items/{item_id}")
async def read_item(item_id: int):
    return {"item_id": item_id}
```

JARVIS에서는 시작·종료 처리를 `lifespan`으로 하고, 기능별로 Router를 나눠서 등록한다

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_settings()
    configure_logging(log_level=cfg.log_level, json_logs=cfg.log_json)
    await ensure_collection()  # Qdrant 컬렉션 초기화
    yield                      # 앱 실행 구간

app = FastAPI(title="jarvis-ai-inference", lifespan=lifespan)

app.include_router(chat_router)
app.include_router(memory_router)
app.include_router(routine_router)
```

```python
# ❌ deprecated
@app.on_event("startup")
async def startup(): ...

# ✅ lifespan context manager (위 코드)
```

`yield` 앞이 시작 로직, 뒤가 종료 로직이다
`include_router()`로 모듈을 나누는 건 NestJS에서 `imports: [ChatModule]`로 모듈을 붙이는 것과 비슷한 역할이다

## APIRouter와 Depends

공식 예제의 `Depends`는 값을 만들어서 핸들러에 넘겨주는 용도다

```python
async def common_parameters(q: str | None = None):
    return {"q": q}

@router.get("/items/")
async def read_items(commons: dict = Depends(common_parameters)):
    return commons
```

JARVIS는 값이 필요 없고 검증만 하면 되니까 `dependencies=[...]`로 붙인다

```python
router = APIRouter(prefix="/chat", tags=["chat"])

@router.post("/stream", dependencies=[Depends(verify_internal_token)])
async def chat_stream(body: ChatStreamRequest) -> StreamingResponse:
    return StreamingResponse(stream_chat(body), media_type="text/event-stream")
```

이 방식은 NestJS의 Guard와 같은 자리에 있다
반환값을 핸들러에서 쓰고 싶으면 파라미터로 받고, 통과 여부만 필요하면 `dependencies=[]`에 넣는다

## Depends로 만드는 JWT 검증

NestJS 서버가 `JwtService`로 서명한 토큰을 추론 서버가 같은 secret으로 검증한다

```python
JWT_ALGORITHM = "HS256"
bearer = HTTPBearer()

def verify_internal_token(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
) -> None:
    try:
        jwt.decode(
            credentials.credentials,
            get_settings().inference_secret,
            algorithms=[JWT_ALGORITHM],
        )
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
```

`HTTPBearer()`가 `Authorization: Bearer <token>` 헤더를 알아서 파싱해준다
검증에 실패하면 `HTTPException(401)`을 던지고, FastAPI가 JSON 에러 응답으로 바꿔준다
`HTTPBearer()` 인스턴스는 모듈 레벨에서 한 번만 만들어서 재사용한다

## StreamingResponse로 SSE 보내기

```python
from fastapi.responses import StreamingResponse

async def fake_streamer():
    for i in range(10):
        yield f"data: chunk {i}\n\n"

@app.get("/stream")
async def stream():
    return StreamingResponse(fake_streamer(), media_type="text/event-stream")
```

JARVIS의 `stream_chat(body)`도 `AsyncGenerator[str, None]`을 반환한다
FastAPI가 이 generator를 소비하면서 청크를 클라이언트로 흘려보내고, `media_type="text/event-stream"`이 SSE로 동작하게 만든다

## Exception Handler와 SSE의 함정

```python
@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"error": {"code": "INTERNAL_ERROR"}})
```

글로벌 핸들러를 등록해뒀다고 안심하면 안 된다
`StreamingResponse`의 이터레이션은 HTTP 헤더가 이미 전송된 뒤에 시작된다
그래서 스트림 도중에 터진 에러는 이 핸들러에 도달하지 않는다
generator를 만드는 service 안에서 try/except로 직접 처리해야 한다

```python
# ❌ 예외를 그냥 흘려보내는 generator (글로벌 핸들러가 못 잡음)
async def stream_chat(body):
    async for chunk in provider.stream(body):
        yield chunk

# ✅ generator 안쪽에서 try/except (개념 예시)
async def stream_chat(body):
    try:
        async for chunk in provider.stream(body):
            yield chunk
    except Exception:
        yield "data: error\n\n"
```

## 그 밖에 걸리는 것들

- `@lru_cache`를 붙인 `get_settings()`는 설정을 매 요청마다 파싱하지 않게 해주지만, 테스트에서 settings를 오버라이드할 때는 캐시를 무효화해야 한다
- `include_router` 순서가 곧 경로 매칭 순서라서, `/chat/stream`보다 `/chat/{id}`가 먼저 등록되면 `stream`이 id로 매칭된다

## NestJS와 대응해서 보면

- `include_router()`는 `imports: [Module]`
- `APIRouter`는 Controller
- `Depends()` / `dependencies=[...]`는 Guard나 Interceptor
- 요청 Body 검증은 Pydantic이 맡는다

개념은 거의 1:1로 옮겨지는데, 에러가 어느 시점에 어디로 가는지만 직접 확인해야 한다
특히 스트리밍 응답은 글로벌 핸들러가 지켜주지 않는다
