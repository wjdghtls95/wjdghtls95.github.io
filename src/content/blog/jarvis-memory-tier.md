---
title: "JARVIS 메모리 티어: AI가 기억을 3단계로 관리하는 법"
description: "RAG만으로는 부족했다. CORE, SEARCHABLE, ARCHIVED 3티어로 메모리를 분리해 AI 응답 품질을 높인 구현 과정"
date: "2026-08-14"
tags: ["Project"]
project: "jarvis"
phase: "memory"
qa_done: true
---

JARVIS를 쓰다 보면 이런 상황이 생긴다.

"내가 좋아하는 커피가 아메리카노라고 몇 번 말했는데 왜 또 물어봐?"

메모리가 많아질수록 RAG 검색 품질이 떨어지기 때문이다. 100개의 메모리 중에서 유사도로 찾다 보면, 정작 중요한 기본 정보가 순위에서 밀린다.

이걸 해결하려고 메모리를 3개 티어로 나눴다.

## 3티어 구조

**CORE**: 사용자가 직접 핀한 핵심 사실. 최대 10개. 항상 Claude에게 전달된다. RAG 검색을 거치지 않는다.

**SEARCHABLE**: 일반 장기 메모리. 대화에서 자동 추출된다. RAG로 관련 있는 것만 골라서 전달.

**ARCHIVED**: 30일 이상 접근 없는 메모리. 검색과 RAG 양쪽에서 완전히 제외된다.

## 왜 CORE를 RAG로 안 보내나

처음엔 CORE도 RAG로 검색하면 되지 않을까 생각했다. 하지만 문제가 있다.

유사도 기반 검색은 "관련성"으로 순위를 매긴다. "오늘 점심 뭐 먹을까?"라는 질문에 "사용자 이름: 정호"가 높은 점수를 받을 이유가 없다.

그래서 CORE는 검색을 건너뛰고 system prompt 상단에 직접 박는다.

```python
def build_messages(request):
    # CORE는 RAG 점수 무관하게 항상 맨 앞에
    if request.core_memories:
        system = "핵심 기억:\n" + format_cores(request.core_memories) + "\n\n" + system
    # SEARCHABLE은 RAG 결과
    if request.memories:
        system += "\n관련 기억:\n" + format_memories(request.memories)
```

핵심 기억이 먼저, RAG 결과가 뒤에. Claude는 항상 CORE를 알고 있다.

## ARCHIVED는 왜 완전히 격리하나

30일간 한 번도 안 쓴 메모리가 검색에 나오면 뭐가 문제일까?

"예전에 살던 집 주소"가 지금 질문의 답으로 올라온다. 사용자 입장에서는 AI가 엉뚱한 걸 기억하는 것처럼 보인다.

Qdrant 쿼리에 `must_not` 필터를 달아서 ARCHIVED를 탐색 대상에서 뺐다.

```python
must_not = [FieldCondition(key="tier", match=MatchValue(value="ARCHIVED"))]
```

검색할 때도, RAG로 주입할 때도 같은 필터가 들어간다.

## 구현 순서

7개 Step을 순서대로 쌓았다. 각 Step이 다음 Step의 선행 조건이었다.

1. 검색 점수 개선: relevance 0.6 + recency 0.2 + importance 0.2
2. DB 스키마: `MemoryTier` enum + `tier` 컬럼 + composite index
3. 핀/언핀 API: CORE 최대 10개 제한 포함
4. CORE 주입: `streamMessage()`에서 `findCoreByUserId()` 호출
5. Qdrant 동기화: tier를 벡터 payload에 저장
6. UI: 메모리 목록에 CORE 섹션 + 핀 버튼
7. 자동 아카이브: BullMQ로 매일 자정 30일 초과 메모리 아카이브

## 삽질 포인트

두 레포 동기화를 놓치면 필터가 무의미해진다.

NestJS에서 `tier: ARCHIVED`로 업데이트해도 Qdrant payload에 반영이 안 되면, 다음 검색에서 ARCHIVED가 그대로 나온다. Step 5가 빠진 채로 Step 7을 만들었으면 아카이브 자체가 작동 안 하는 상황이 됐을 것이다.

또 하나: `MemoryArchiveProcessor`에서 처음에 `skip/take` 방식으로 페이지네이션을 짰다가 코드리뷰에서 `cursor` 방식으로 바꿨다. skip/take는 배치 중간에 새 데이터가 추가되면 같은 항목을 두 번 처리할 수 있다.

---

레퍼런스: MemGPT (Packer et al., 2023). working memory와 long-term storage를 분리한 아이디어에서 시작했다.
