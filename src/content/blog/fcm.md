---
title: "FCM 푸시 알림 — 서버에서 모바일까지 알림 보내기"
description: "iOS는 APNs 브릿지를 타고 Android는 직접 붙는 FCM 구조와 토큰 만료 처리 패턴"
date: "2026-09-05"
tags: ["BullMQ"]
qa_done: true
rewritten: true
---

## 왜 필요한가

서버에서 앱으로 직접 TCP 연결을 유지하는 방식은 배터리 소모가 크고 iOS에서는 애초에 막혀있다

그래서 백그라운드 푸시는 각 OS가 제공하는 공식 채널을 거쳐야 한다

Android는 FCM, iOS는 APNs

FCM(Firebase Cloud Messaging)은 이 둘을 하나의 인터페이스로 묶어주는 Google의 크로스 플랫폼 메시징 서비스다

Android는 FCM이 직접 처리하고 iOS는 FCM이 APNs로 다시 브릿지한다

용어 몇 개만 짚고 가면

- FCM: Google의 푸시 알림 인프라, Android 직접 처리 iOS는 APNs 브릿지
- APNs: Apple의 푸시 알림 인프라, iOS/macOS 전용
- Device Token: 기기마다 FCM이 발급하는 고유 식별자, 앱 설치 + 권한 허용 시 발급되고 재설치하면 바뀜
- firebase-admin: 서버 사이드 Firebase SDK, 서비스 계정 JSON으로 인증
- Silent Push: 화면에 안 보이는 푸시, 백그라운드 데이터 동기화용

## 어떻게 동작하나

흐름은 이렇다

앱이 실행되면 Device Token을 발급받아 서버에 등록한다 (`POST /devices`)

서버는 이 토큰을 platform 정보와 함께 DB에 저장해둔다

알림을 보낼 시점이 되면 (JARVIS에서는 BullMQ Delayed Job이 그 시점을 잡는다) 서버가 FCM에 `send(token, platform, payload)`를 호출한다

여기서 갈라진다

iOS 토큰이면 FCM이 APNs로 넘겨서 기기에 전달되고, Android/Web 토큰이면 FCM이 바로 기기로 보낸다

토큰이 만료됐으면 FCM이 `messaging/registration-token-not-registered` 에러를 돌려주고, 서버는 이걸 받아서 해당 기기를 비활성화한다

## JARVIS에서 실제로 어떻게 썼나

### send 메서드 하나로 플랫폼 분기 흡수하기

```typescript
@Injectable()
export class FirebaseService {
  constructor(
    @Inject(FIREBASE_APP_TOKEN) private readonly firebaseApp: App,
    private readonly deviceRepository: DeviceRepository,
  ) {}

  async send(token: string, platform: Platform, payload: FcmPayload): Promise<void> {
    const message = this.buildMessage(token, platform, payload);

    try {
      await getMessaging(this.firebaseApp).send(message);
    } catch (err: unknown) {
      if (this.isExpiredTokenError(err)) {
        // 만료된 토큰 → 기기 비활성화 (재발송 불필요)
        await this.deviceRepository.deactivateByToken(token);
        return;  // throw하지 않음 — 다른 기기에 계속 발송
      }
      throw err;  // 네트워크 에러 등 → BullMQ retry
    }
  }
}
```

코드에서 볼 건 두 가지다

`getMessaging().send()`가 던지는 에러 중 만료된 토큰 에러만 따로 걸러서 조용히 넘기고, 나머지는 그대로 throw해서 BullMQ가 재시도하게 둔다

한 기기 토큰이 죽었다고 다른 기기 발송까지 막을 이유는 없다

### iOS와 Android가 요구하는 payload 구조가 다르다

```typescript
private buildMessage(token: string, platform: Platform, payload: FcmPayload): Message {
  if (platform === Platform.IOS) {
    // iOS — APNs 네이티브 포맷
    return {
      token,
      apns: {
        payload: {
          aps: {
            alert: {
              title: payload.title,
              body: payload.body,
            },
            sound: payload.silent ? undefined : 'default',
            contentAvailable: payload.silent ? true : undefined,  // silent push
          },
        },
      },
    };
  }

  // Android / Web — FCM data payload
  return {
    token,
    notification: {
      title: payload.title,
      body: payload.body,
    },
    data: {
      title: payload.title,   // 앱에서 커스텀 처리용 data payload 추가
      body: payload.body,
    },
  };
}
```

주요 차이는 세 가지

| | iOS | Android |
|--|-----|---------|
| 구조 | `apns.payload.aps` | `notification` + `data` |
| Silent | `aps.contentAvailable: true` | FCM data-only message |
| 소리 | `aps.sound: 'default'` | FCM 자동 처리 |

같은 `send()`를 호출해도 내부에서 이 분기를 안 타면 iOS에서는 알림이 아예 안 뜬다

### 토큰 만료 감지하기

```typescript
private isExpiredTokenError(err: unknown): boolean {
  if (err && typeof err === 'object' && 'errorInfo' in err) {
    const firebaseErr = err as { errorInfo?: { code?: string } };
    return firebaseErr.errorInfo?.code === 'messaging/registration-token-not-registered';
  }
  return false;
}
```

에러 코드가 `errorInfo.code` 아래 있다는 걸 모르면 여기서 한 번 막힌다

```typescript
// ❌ Firebase Admin SDK v9 이후로는 이렇게 접근 안 됨
err.code === 'messaging/registration-token-not-registered'

// ✅ errorInfo 한 겹 더 들어가야 함
err.errorInfo?.code === 'messaging/registration-token-not-registered'
```

만료된 토큰이면 `deactivateByToken()`으로 DB에서 비활성화하고 return

throw하면 BullMQ가 같은 job을 재시도하고, 재시도해도 토큰은 똑같이 만료 상태라 무한 루프로 이어진다

### 여러 기기에 동시 발송하기

```typescript
// alert-dispatch.processor.ts — 여러 기기에 동시 발송
await Promise.all(
  devices.map((device) =>
    this.firebaseService.send(device.token, device.platform, {
      title: alert.title,
      body: alert.body,
    }),
  ),
);
```

`Promise.all`로 모든 기기에 병렬 발송하는데, 개별 기기의 토큰 만료는 이미 `send()` 내부에서 삼켜지기 때문에 한 기기가 실패해도 전체가 reject되지 않는다

fcm payload 인터페이스는 단순하다

```typescript
export interface FcmPayload {
  title: string;
  body: string;
  silent?: boolean;  // true면 화면에 안 뜨고 백그라운드 실행만
}
```

## 삽질한 것

`err.code`로 바로 접근하면 항상 undefined다

Firebase Admin SDK v9부터 에러 구조가 `errorInfo.code`로 한 겹 더 들어가서, 이 위치를 모르면 만료 토큰 감지 자체가 안 된다

`deactivateByToken()` 다음에 return을 빼먹으면 문제가 더 커진다

throw하면 BullMQ가 재시도하고, 재시도해도 토큰은 여전히 만료 상태니까 같은 실패가 반복된다

iOS 알림이 안 온다면 코드보다 먼저 Firebase 콘솔의 APNs 인증서(.p8 키) 등록부터 확인하는 게 낫다

`Promise.all`은 기기 하나가 진짜 예외를 던지면 나머지 발송까지 끊긴다

`send()` 내부에서 토큰 만료를 미리 삼켜서 이 위험을 줄였지만, 네트워크 에러처럼 진짜 예외가 섞이면 `allSettled`나 개별 try/catch가 더 안전하다

기기 등록 타이밍도 놓치기 쉬운 지점이다

앱 최초 실행 시 토큰을 발급받아 서버에 등록하는데, 이 등록이 끝나기 전에 알림을 보내려 하면 기기 목록이 비어있어서 아무 데도 안 간다
