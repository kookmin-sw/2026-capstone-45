# Reference Review Guide

## 1. 목적

이 문서는 `reference parsing` 결과를 검토할 때 무엇을 확인해야 하는지 정리한 리뷰 가이드다.

리뷰의 목표는 단순히 "bbox가 잘 맞는가"를 보는 것이 아니다. 아래 세 가지를 함께 판단해야 한다.

1. 문서의 `형식 구조`를 제대로 추출했는가
2. 추출된 블록에 `의미 역할`이 적절하게 붙었는가
3. 이 결과가 이후 `generation/rendering`에 실제로 쓸 수 있는 수준인가

즉, 리뷰 질문은 "OCR이 맞나?"보다 "이 결과가 레퍼런스 템플릿으로 충분히 쓸 만한가?"에 가깝다.

## 2. 어떤 파일을 함께 봐야 하는가

리뷰는 아래 산출물을 같이 봐야 한다.

- `reference_visualization_on_original_pdf.html`
  - 원본 문서 위에 블록과 semantic 결과가 겹쳐 보이는 시각화
- `reference_template.json`
  - downstream 공식 계약 산출물
- `semantic_overlay.json`
  - semantic role만 따로 요약한 결과
- `parser_diagnostics.json`
  - 어떤 엔진 결과를 썼고, fusion 중 어떤 보정이 있었는지 보여주는 진단 정보
- 필요하면 `canonical_pages.json`
  - 블록 단위 상세 확인용

권장 순서는 아래와 같다.

1. `reference_visualization_on_original_pdf.html`
2. `reference_template.json`
3. `semantic_overlay.json`
4. `parser_diagnostics.json`

## 3. 가장 먼저 봐야 할 것

### 3.1 페이지 archetype이 맞는가

먼저 페이지가 어떤 성격으로 분류됐는지 본다.

주요 질문:

- 이 페이지가 실제로 `cover_summary`, `body_narrative`, `evidence_table`, `compliance` 중 어디에 가까운가
- 잘못 분류되면 후속 단계가 전체적으로 어긋나지 않는가

예:

- 좌측 패널 + 우측 본문이 같이 있으면 `cover_summary`가 자연스럽다
- 표와 주석이 대부분이면 `evidence_table`가 자연스럽다
- 면책/고지/컴플라이언스 문구가 중심이면 `compliance`가 자연스럽다

이 단계가 중요한 이유:

- `anchor_pages`
- `section_order`
- `style_tokens`

이 모두가 archetype 분류에 의존하기 때문이다.

### 3.2 메인 골격이 맞는가

그 다음 문서의 뼈대가 제대로 잡혔는지 본다.

주요 질문:

- 문서 제목이 `report_title`로 잘 잡혔는가
- 본문 핵심 문단이 `supporting_argument`로 모였는가
- 좌측 데이터 패널과 우측 본문이 섞이지 않았는가
- 하단 메타와 본문이 분리됐는가

여기서 틀리면 generation 단계에서 "형식은 비슷한데 읽는 흐름이 이상한 문서"가 나온다.

## 4. 블록 리뷰에서 확인해야 할 것

### 4.1 bbox 자체보다 관계를 본다

bbox 리뷰는 단일 박스 정밀도보다 아래 관계가 더 중요하다.

- 제목과 본문이 올바른 순서로 붙어 있는가
- 이미지와 캡션이 같은 영역으로 인식되는가
- 좌측 패널 정보가 본문 section으로 들어가지 않았는가
- header/footer/page number가 본문으로 들어오지 않았는가

즉 "박스가 맞는가"보다 "박스끼리의 기능적 관계가 맞는가"를 봐야 한다.

### 4.2 canonical_label이 타당한가

확인 항목:

- `document_title`
- `section_heading`
- `paragraph`
- `image`
- `table`
- `meta_candidate`

오탐이 특히 위험한 케이스:

- 본문을 `meta_candidate`로 잘못 보는 경우
- panel title을 일반 `paragraph`로 떨어뜨리는 경우
- table/chart를 본문 텍스트처럼 취급하는 경우

### 4.3 reading order가 자연스러운가

주요 질문:

- 사람이 읽는 순서와 비슷한가
- 좌측 패널을 먼저 읽고 그 다음 메인 본문으로 가는가
- multi-column 또는 mixed layout에서 순서가 뒤엉키지 않았는가

reading order가 틀리면 `section_order`와 semantic rule이 연쇄적으로 흔들린다.

## 5. semantic 리뷰에서 확인해야 할 것

### 5.1 generic role이 맞는가

generic role은 문서군이 달라도 유지되어야 하는 역할층이다.

확인 항목:

- `main_title`
- `section_heading`
- `summary`
- `body`
- `evidence`
- `metadata`
- `author_info`
- `disclaimer`

판단 기준:

- 사람이 읽을 때 느끼는 역할과 모델이 붙인 역할이 대체로 일치해야 한다.
- generic role은 너무 세밀하기보다 안정적이어야 한다.
- 역할이 애매하면 과도하게 특정 role로 몰지 말고 더 일반적인 role에 두는 편이 낫다.

### 5.2 domain role이 맞는가

domain role은 특정 문서군에서만 의미가 있는 역할층이다.

financial report에서는 특히 아래를 본다.

- `investment_opinion_box`
- `key_data_box`
- `consensus_box`
- `price_chart_block`
- `report_title`
- `thesis_heading`
- `supporting_argument`
- `analyst_info`
- `research_center_meta`
- `disclaimer_block`

판단 기준:

- 해당 블록이 실제로 그 도메인 역할을 수행하는지 봐야 한다.
- 제목만 비슷하다고 domain role을 붙이면 안 된다.
- 표나 패널이 generation 핵심이 아닌데도 과하게 중요한 role로 승격되지 않았는지 봐야 한다.

### 5.3 semantic은 과감하게 비워도 되는가

semantic 품질이 낮은 페이지는 `generic_role`까지만 붙이고 `domain_role`은 비워두는 것이 맞다.

즉 리뷰에서 확인할 것은 "왜 안 붙었지?"만이 아니다. 아래 질문도 해야 한다.

- 이 페이지는 원래 semantic을 강하게 붙이면 안 되는 페이지 아닌가
- OCR 품질이 너무 낮아서 domain role 추론이 오히려 위험하지 않은가
- compliance/evidence 페이지인데 narrative semantic을 억지로 붙인 것은 아닌가

## 6. template 결과에서 확인해야 할 것

### 6.1 section_order가 생성용 골격으로 적절한가

가장 중요한 확인 항목 중 하나다.

주요 질문:

- `section_order`에 실제 narrative 흐름만 남아 있는가
- 표, 차트, panel heading, footer, compliance list가 섞여 들어가지 않았는가
- generation이 이 순서를 그대로 따라도 자연스러운 문서가 나올 것 같은가

좋은 `section_order`의 특징:

- 문서 제목에서 시작한다
- 핵심 섹션 제목과 본문이 자연스럽게 이어진다
- evidence panel은 필요하면 참조 대상이지 본문 골격은 아니다

나쁜 `section_order`의 특징:

- `BUY`, `Key Data`, `Consensus Data` 같은 좌측 패널 heading이 본문 섹션처럼 들어간다
- footer, analyst info, page meta가 narrative 흐름 중간에 낀다
- 순서상 사람이 읽는 본문 구조와 다르다

### 6.2 anchor_pages가 적절한가

anchor page는 템플릿의 대표 페이지다.

확인 질문:

- 이 페이지가 정말 문서 스타일과 본문 구조를 대표하는가
- evidence/compliance 페이지가 anchor로 뽑히지 않았는가
- 첫 페이지만 강하게 반영되어 뒤 페이지의 본문 스타일을 놓치지 않았는가

### 6.3 style_tokens가 납득 가능한가

`style_tokens`는 시각적 스타일을 숫자로 요약한 값이다.

확인 질문:

- 제목, 본문, 섹션 간 상대 크기 관계가 자연스러운가
- 값이 이상치처럼 보이지 않는가
- 실제 문서에서 느껴지는 밀도와 시각적 무게가 반영되어 있는가

중요한 점:

- 이 값은 절대 정답보다 상대 일관성이 중요하다.
- 숫자 하나가 정확한가보다 제목 > 섹션 > 본문 관계가 유지되는지가 더 중요하다.

### 6.4 image_slots와 unsupported_blocks 처리

확인 질문:

- 실제 시각요소가 있는데 `image_slots`가 비어 있지는 않은가
- 반대로 너무 작은 장식 요소까지 이미지 슬롯으로 잡지는 않았는가
- `unsupported_blocks`에 남겨야 할 evidence/table/chart가 generation 본문에 섞이지 않았는가

## 7. diagnostics에서 확인해야 할 것

`parser_diagnostics.json`은 품질 경고를 읽는 파일이다.

주요 항목:

- `source_engines`
- `fusion_conflicts`
- `text_replacements`
- `review_required`
- `high_noise_pages`
- `warnings`

판단 방법:

- `fusion_conflicts`가 많으면 엔진 간 해석 차이가 큰 것이다.
- `text_replacements`가 많으면 텍스트 안정성이 낮을 수 있다.
- `review_required=true`이면 결과를 그대로 신뢰하지 말고 수동 검토가 필요하다.
- 특정 페이지가 `high_noise_pages`에 있으면 그 페이지의 semantic과 template 기여도를 낮게 봐야 한다.

중요한 해석:

- conflict가 많다고 항상 실패는 아니다.
- 다만 conflict가 많은데도 `section_order`나 semantic이 공격적으로 생성되면 위험 신호다.

## 8. 잘 생성됐는지 평가하는 기준

아래 세 층위로 평가하면 된다.

### 8.1 구조 정확도

- 큰 영역 분리가 맞는가
- 읽기 순서가 맞는가
- 본문과 메타가 분리되는가
- table/chart/compliance가 narrative와 분리되는가

### 8.2 의미 정확도

- 제목, 본문, 메타, disclaimer 역할이 맞는가
- financial 페이지라면 투자의견, key data, analyst info가 맞게 해석되는가
- 애매한 블록에 과한 의미를 부여하지 않았는가

### 8.3 활용 가능성

- 이 결과를 그대로 generation 입력으로 써도 되는가
- 사람이 조금만 손보면 바로 쓸 수 있는가
- 아니면 구조부터 다시 잡아야 하는가

최종적으로는 아래 세 등급으로 판단하면 실무적으로 편하다.

- `Ready`
  - 바로 downstream에 연결 가능
- `Usable with review`
  - 핵심 구조는 맞지만 몇 개 수정 포인트가 있음
- `Needs rework`
  - archetype, section_order, semantic 중 하나 이상이 크게 틀림

## 9. 추가적으로 해야 하는 판단과 생각

리뷰는 결과를 맞다/틀리다로 끝내면 아쉽다. 아래 생각까지 해야 다음 개선으로 이어진다.

### 9.1 이 오류는 규칙 문제인가 OCR 문제인가

예:

- 텍스트가 깨졌으면 OCR 품질 문제일 수 있다
- 본문이 패널로 잘못 들어갔으면 archetype 또는 semantic rule 문제일 수 있다
- 순서가 꼬였으면 reading order 또는 fusion 문제일 수 있다

즉 오류를 발견하면 반드시 원인을 분리해서 봐야 한다.

### 9.2 이 오류가 downstream에 얼마나 치명적인가

모든 오류가 같은 심각도는 아니다.

- spelling 몇 개가 깨진 것은 경미할 수 있다
- `section_order` 오염은 치명적일 수 있다
- disclaimer 누락은 규제 문서에서는 매우 치명적일 수 있다

그래서 리뷰 메모에는 "무엇이 틀렸는가"뿐 아니라 "왜 중요한가"도 적는 것이 좋다.

### 9.3 이 문서는 정말 template화할 가치가 있는가

어떤 페이지는 너무 특수해서 generic template에 넣는 것이 오히려 해롭다.

확인 질문:

- 이 페이지는 대표 레이아웃인가
- 너무 예외적인 페이지는 아닌가
- evidence/compliance 페이지를 굳이 generation template에 넣어야 하는가

### 9.4 보수적으로 버려야 하는 정보는 무엇인가

좋은 parser는 많이 뽑는 parser가 아니라, downstream을 망치지 않게 뽑는 parser다.

따라서 아래 판단이 필요하다.

- 잘 모르겠는 블록은 과감히 제외할 것인가
- 표/차트는 evidence로만 두고 generation에서는 뺄 것인가
- low-quality 페이지의 domain semantic은 생략할 것인가

## 10. 리뷰 결과를 기록할 때 권장 포맷

리뷰 메모는 아래 형식이 실용적이다.

```md
## Review Summary
- sample:
- page:
- overall:

## Good
- 

## Issues
- severity:
  - issue:
  - impact:
  - suspected cause:

## Decision
- ready / usable with review / needs rework

## Follow-up
- 
```

핵심은 문제를 발견했을 때 아래 네 가지를 같이 적는 것이다.

- 무엇이 틀렸는가
- 어디에 나타났는가
- downstream 영향이 무엇인가
- 원인이 OCR인지 rule인지 fusion인지

## 11. financial report 리뷰 시 특히 확인할 것

financial report는 일반 문서보다 아래 항목이 더 중요하다.

- 좌측 투자정보 패널과 우측 narrative 본문이 분리되는가
- `BUY/HOLD/SELL`, 목표주가, 현재주가가 `investment_opinion_box`로 안정적으로 잡히는가
- `Key Data`, `Consensus Data`, `Stock Price`가 evidence 성격으로 남는가
- 회사명과 종목코드가 `report_title`로 자연스럽게 잡히는가
- analyst/contact/disclaimer가 본문과 섞이지 않는가
- compliance 페이지가 `section_order`에 들어가지 않는가

특히 중요한 실수 패턴:

- evidence panel heading이 narrative heading으로 들어가는 경우
- analyst info가 본문 문단처럼 들어가는 경우
- disclaimer가 누락되거나 summary처럼 잘못 들어가는 경우

## 12. 최종 판단 기준

최종적으로는 아래 질문 하나로 정리할 수 있다.

`이 결과를 다음 생성 단계에 넣었을 때, 문서의 핵심 구조와 역할을 보존한 채 비슷한 문서를 안정적으로 만들 수 있는가`

이 질문에:

- 거의 그렇다고 답할 수 있으면 `Ready`
- 대체로 그렇지만 몇 가지 수동 검토가 필요하면 `Usable with review`
- 아직 그렇다고 보기 어렵다면 `Needs rework`

리뷰의 목적은 정답률 숫자 하나를 만드는 것이 아니라, 결과를 실제 시스템에 안전하게 연결할 수 있는지를 판단하는 것이다.
