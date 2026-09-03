---
title: "BullMQ — Node.js에서 백그라운드 잡 처리하는 법"
description: "HTTP 응답 후 비동기 작업을 안전하게 처리하는 BullMQ 큐 원리와 JARVIS 실전 패턴 정리"
date: "2026-09-04"
tags: ["BullMQ"]
qa_done: true
rewritten: true
---

## 왜 필요한가

HTTP 요청 처리 흐름에 AI 메모리 추출, FCM 발송, 브리핑 생성 같은 무거운 작업을 끼워 넣으면 응답 시간에 그대로 반영된다

타임아웃 위험도 커진다

`setTimeout`으로 비동기 처리를 흉내낼 수도 있지만 프로세스가 재시작되면 예약된 작업이 그대로 날아간다

신뢰할 수 없는 방식이다

BullMQ는 Redis 기반 잡 큐다

프로세스가 재시작돼도 잡이 살아남고, 재시도·지연 실행·cron까지 기본으로 지원한다

용어 정리

- Queue: 잡을 쌓아두는 저장소, Redis List/Sorted Set 위에 구현
- Worker: 잡을 소비하는 프로세스, `@Processor(큐명)` 데코레이터로 정의
- Processor: Worker가 실행하는 함수, `process(job)` 메서드
- Delayed Job: 특정 시간 후 실행되는 잡, `delay` 옵션(밀리초)
- Cron Job: 반복 실행 잡, `repeat.pattern`(cron 표현식) + `tz`(타임존)
- Backoff: 실패한 잡의 재시도 간격, exponential backoff은 재시도마다 간격이 2배씩 증가
- jobId: 중복 잡 방지용 고유 ID, 같은 jobId가 이미 있으면 추가되지 않음

## 어떻게 동작하나

잡의 상태는 이렇게 흘러간다

- `queue.add()`로 잡을 넣으면 waiting 상태로 대기
- Worker가 pickup하면 active로 전환
- `process()`가 성공하면 completed, 예외를 던지면 failed
- failed 상태에서 남은 attempts가 있으면 다시 waiting으로 돌아가 재시도
- delay 옵션이 있는 잡은 waiting 전에 delayed 상태를 거쳐 대기 시간이 지나야 waiting으로 넘어감

### Processor 정의

공식 예제는 이렇게 생겼다

```typescript
import { Processor, WorkerHost } from '@nestjs/bullmq'
import { Job } from 'bullmq'

@Processor('audio')
export class AudioConsumer extends WorkerHost {
  async process(job: Job<any>): Promise<void> {
    // 잡 처리 로직
  }
}
```

JARVIS에서는 메모리 추출 큐를 이 구조로 짰다

```typescript
// memory-extract.processor.ts
@Processor(MEMORY_EXTRACT_QUEUE)
export class MemoryExtractProcessor extends WorkerHost {
  constructor(
    private readonly messageRepository: MessageRepository,
    private readonly memoryRepository: MemoryRepository,
    private readonly inferenceClient: InferenceClient,
    @InjectQueue(MEMORY_INDEX_QUEUE) private readonly memoryIndexQueue: Queue,
  ) { super() }

  @Transactional()
  async process(job: Job<MemoryExtractJobData>): Promise<void> {
    const { userId, conversationId, messageIds } = job.data

    if (messageIds.length === 0) return

    const messages = await this.messageRepository.findManyByIds(messageIds)
    const extracted = await this.inferenceClient.extractMemories({ userId, messages })

    if (extracted.length === 0) return

    const saved = await Promise.all(
      extracted.map((m) => this.memoryRepository.create({ userId, content: m.content, category: m.category, conversationId }))
    )

    // 인덱싱 큐에 추가 (Qdrant 임베딩)
    await this.memoryIndexQueue.addBulk(
      saved.map((m) => ({ name: MEMORY_INDEX_JOB, data: { memoryId: m.id, userId } }))
    )
  }
}
```

메시지 처리가 끝나면 이렇게 큐에 잡을 넣는다

```typescript
// message.service.ts — 채팅 완료 후 메모리 추출 큐에 추가
await this.memoryQueue.add('extract', {
  userId: user.id,
  conversationId,
  messageIds: [userMessage.id, assistantMessage.id],
} satisfies MemoryExtractJobData)
```

### Delayed Job

할 일 리마인더처럼 N분 후에 실행돼야 하는 작업은 delay 옵션을 쓴다

```typescript
// task.service.ts — 할 일 리마인더: N분 후 실행
const delay = reminderAt.getTime() - Date.now()

await this.taskRemindQueue.add(
  TASK_REMIND_JOB,
  { taskId: task.id },
  {
    delay,                             // 밀리초, 이 시간 후 active로 전환
    jobId: `task-remind:${task.id}`,   // 같은 taskId의 중복 잡 방지
  }
)
```

### Cron Job

반복 실행은 `OnModuleInit`에서 cron을 한 번 등록해두는 방식으로 쓴다

```typescript
// BriefingScheduleProcessor — OnModuleInit에서 cron 등록
async onModuleInit(): Promise<void> {
  await this.briefingScheduleQueue.add(
    'daily-schedule',
    {},
    {
      repeat: { pattern: '0 0 * * *', tz: 'UTC' },  // 매일 UTC 00:00
      jobId: 'briefing-daily-cron',                  // 중복 등록 방지
    },
  )
}

async process(_job: Job): Promise<void> {
  const settings = await this.briefingRepository.findAll()
  const now = new Date()

  for (const setting of settings) {
    const delay = triggerAt.getTime() - now.getTime()
    const dateKey = localDateKey(tz)

    // 오늘 날짜 기반 jobId, 하루에 한 번만 실행
    await this.briefingDispatchQueue.add(
      'dispatch',
      { userId: setting.userId },
      { delay, jobId: `briefing-dispatch:${setting.userId}:${dateKey}` },
    )
  }
}
```

### 잡 취소

active 상태 잡은 `remove()`가 실패한다

try/catch 없이 호출하면 취소 요청 자체가 예외로 끝나버린다

```typescript
// task.service.ts — 할 일 취소 시 pending reminder 제거
async cancelTaskReminder(taskId: string): Promise<void> {
  const jobId = `task-remind:${taskId}`
  const jobs = await this.taskRemindQueue.getJobs(['waiting', 'delayed'])

  for (const job of jobs) {
    if (job.opts?.jobId === jobId) {
      try {
        await job.remove()  // active 상태의 잡은 remove() 불가, throw
      } catch {
        // 잡이 이미 active(실행 중)이면 무시, 실행 완료 후 자연 종료
      }
    }
  }
}
```

## JARVIS에서 실제로 어떻게 썼나

푸시 알림 발송도 같은 구조로 처리한다

```typescript
// task-remind.processor.ts
@Processor(TASK_REMIND_QUEUE)
export class TaskRemindProcessor extends WorkerHost {
  async process(job: Job<{ taskId: string }>): Promise<void> {
    const { taskId } = job.data
    const task = await this.taskRepository.findById(taskId)

    // 잡 실행 시점에 태스크 상태 재확인, 이미 완료됐으면 skip
    if (!task || task.status !== TaskStatus.PENDING) {
      this.logger.warn(`skipping remind for missing/non-pending task ${taskId}`)
      return  // 에러 없이 완료 처리
    }

    const devices = await this.deviceRepository.findActiveByUserId(task.userId)

    for (const device of devices) {
      try {
        await this.firebaseService.send(device.token, device.platform, {
          title: '할 일 알림',
          body: task.title,
          silent: task.silent,
        })
      } catch (err) {
        this.logger.error(`FCM send failed for device ${device.token}`, err)
      }
    }
  }
}
```

## 삽질한 것

`Queue.remove(id)`와 `Job.remove()`는 같은 "잡 제거"인데 실패 시 동작이 다르다

- `Queue.remove(id)`: active/locked job이면 0을 반환 (throw 안 함), 제거 성공 시 1 반환
- `Job.remove()`: active job이면 throw

❌
```typescript
await queue.remove(id)
```

✅
```typescript
const removed = await queue.remove(id)
if (removed === 0) {
  logger.warn(`failed to remove job ${id}, likely active`)
}
```

`Queue.remove()`는 반환값을 체크하지 않으면 실패를 조용히 삼킨다

JARVIS에서 이 반환값 미체크를 실제로 발견했고, 그게 WarnService의 `guard()` 패턴을 도입한 계기가 됐다

그 외 걸렸던 것들

- 큐명·잡명 문자열 리터럴을 반복 쓰면 나중에 바꿀 때 한 곳도 놓치기 쉽다, `TASK_REMIND_JOB` 같은 상수로 빼둔다
- cron 잡은 `jobId` 없이 등록하면 `onModuleInit`이 재실행될 때마다 새 cron이 쌓인다
- `delay` 값이 음수가 될 수 있다는 걸 놓치기 쉽다, `reminderAt`이 이미 지난 시각이면 delay가 음수가 되고 즉시 실행된다 (의도한 동작인지 확인 필요)
- Processor에서 throw하면 retry로 이어진다, `return`으로 정상 종료해야 completed 처리된다, 잡을 실패로 만들고 싶을 때만 throw
- `@Transactional()`은 BullMQ worker에도 그대로 붙는다, HTTP 미들웨어 없이도 자체적으로 CLS context를 만들어주기 때문에 `@UseCls()`가 따로 필요 없다
