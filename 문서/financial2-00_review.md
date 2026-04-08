# financial2-00 Review

## Review Summary

- sample: `financial2-00`
- artifact_dir: `/root/Desktop/workspace/ja/allm/artifacts/demo-financial2/01_reference`
- overall: `Usable with review`

이번 결과는 `financial report` 첫 페이지의 구조를 전반적으로 잘 읽었다. 특히 좌측 투자정보 패널, 우측 메인 본문, 하단 analyst/meta 영역 분리는 성공적이다. 다만 생성용 템플릿 관점에서는 아직 몇 가지 중요한 보정이 필요하다. 대표적으로 `language` 오분류, `section_order` 오염, `thesis_heading` semantic 누락, `used_for_generation`과 `unsupported_blocks` 간 불일치가 있다.

## Reviewed Files

- [reference_visualization_on_original_pdf.html](/root/Desktop/workspace/ja/allm/artifacts/demo-financial2/01_reference/reference_visualization_on_original_pdf.html)
- [reference_template.json](/root/Desktop/workspace/ja/allm/artifacts/demo-financial2/01_reference/reference_template.json)
- [semantic_overlay.json](/root/Desktop/workspace/ja/allm/artifacts/demo-financial2/01_reference/semantic_overlay.json)
- [parser_diagnostics.json](/root/Desktop/workspace/ja/allm/artifacts/demo-financial2/01_reference/parser_diagnostics.json)
- [canonical_pages.json](/root/Desktop/workspace/ja/allm/artifacts/demo-financial2/01_reference/canonical_pages.json)
- [reference_review.md](/root/Desktop/workspace/ja/allm/reference_review.md)

## 1. 전체 해석

이 페이지는 실제 문서 구조상 `cover_summary`로 보는 것이 자연스럽다. 좌측에는 `BUY`, 목표주가/현재주가, `Key Data`, `Consensus Data`, `Stock Price`, `Financial Data`가 세로 패널로 정렬되어 있고, 우측에는 회사명과 종목코드가 포함된 메인 제목과 3개 서술 단락이 있다. 하단에는 analyst 연락처와 리서치센터 메타가 따로 놓여 있다.

현재 파이프라인은 이 큰 구조를 대부분 올바르게 복원했다.

- 문서군을 `financial_report`로 판정했다.
- 페이지 archetype을 `cover_summary`로 판정했다.
- 레이아웃을 `two_column`으로 판정했다.
- 우측 본문 3개 단락을 `supporting_argument`로 인식했다.
- analyst 정보와 리서치센터 메타를 하단 메타로 분리했다.

즉, "문서가 어떤 형식인가"에 대한 1차 인식은 성공이라고 볼 수 있다.

## 2. 리뷰 가이드 기준 상세 점검

### 2.1 페이지 archetype

판정: `Pass`

근거:

- [reference_template.json](/root/Desktop/workspace/ja/allm/artifacts/demo-financial2/01_reference/reference_template.json)에서 `page_archetype`은 `cover_summary`다.
- `column_count=2`, `dominant_layout_pattern=two_column`, `left_sidebar_ratio=0.1192`, `text_area_ratio=0.4009`로 잡혀 있다.
- 시각적으로도 좌측 요약 패널 + 우측 본문이라는 구성과 맞는다.

해석:

- 이 판정은 자연스럽다.
- 이후 `anchor_pages`, `section_order`, `style_tokens`를 계산할 때 기준 페이지로 쓰기에도 무리가 없다.

보는 포인트:

- `left_sidebar_ratio`가 아주 높지는 않지만, 페이지 성격을 바꾸는 수준은 아니다.
- `evidence_table`로 잘못 분류되지 않은 점이 중요하다.

### 2.2 메인 골격

판정: `Mostly pass`

좋은 점:

- 우측 큰 제목 블록 [canonical_pages.json](/root/Desktop/workspace/ja/allm/artifacts/demo-financial2/01_reference/canonical_pages.json) 의 `dolphin-financial2-00-15`가 `main_title + report_title`로 분류됐다.
- 본문 블록 `17`, `19`, `21`이 `body + supporting_argument`로 분류됐다.
- 좌측 하단의 `Analyst`, `RA` 정보는 `author_info + analyst_info`로 처리됐다.
- `하나중권 리서치센터`는 `metadata + research_center_meta`로 처리됐다.

아쉬운 점:

- 제목 블록 `15`에 `KMW (032500)`와 `실적 확인하고 매수하시면 늦습니다`가 한 블록으로 합쳐져 있다.
- 본문 중간 소제목인 블록 `16`, `18`, `20`은 `subheading`으로 남아 있지만 semantic role이 붙지 않았다.

해석:

- 구조는 맞지만, 제목과 서브 타이틀의 세분화가 충분하지 않다.
- 설계상 기대했던 `thesis_heading` 역할이 빠졌기 때문에 "메인 제목 아래 논지 제목" 계층이 약하다.

### 2.3 블록 관계와 bbox

판정: `Pass`

좋은 점:

- 좌측 투자 패널과 우측 본문이 섞이지 않았다.
- 상단 날짜/문서 메타는 본문 위쪽 메타로 따로 분리됐다.
- 하단 analyst/meta 영역도 본문과 분리돼 있다.
- `Key Data`, `Consensus Data`, `Stock Price`, `Financial Data` 아래 표/차트가 각각 같은 패널 내부에 위치한다.

해석:

- bbox 정밀도 자체보다 중요한 "기능적 관계"는 대부분 맞다.
- 좌측 패널 heading과 바로 아래 evidence가 같은 패널로 묶이는 점은 좋다.

주의점:

- 좌측 최상단 작은 이미지 블록과 하단 작은 이미지 블록은 구조 이해에 크게 기여하지 않는다.
- 시각화에서 눈으로 보기에는 맞더라도 generation 관점에서는 이런 장식 요소를 적극적으로 활용할 필요는 없다.

### 2.4 reading order

판정: `Pass with caveat`

읽기 순서는 대체로 자연스럽다.

- 좌측 패널을 위에서 아래로 읽은 뒤
- 우측 제목과 본문으로 넘어가고
- 마지막에 analyst/meta로 간다.

이 순서는 사람의 시선과 크게 다르지 않다.

다만 caveat는 있다.

- 현재 `section_order`는 reading order 영향을 강하게 받아 좌측 evidence panel heading까지 생성용 섹션으로 포함한다.
- 즉 블록 순서 자체는 맞지만, 그 순서를 그대로 생성 골격으로 승격한 판단은 과하다.

## 3. semantic 리뷰

### 3.1 generic role

판정: `Mostly pass`

잘 된 부분:

- `report_header_meta` 계열 블록은 `metadata`로 잘 들어갔다.
- 좌측 투자 의견 박스는 `summary`로 잡혔다.
- 본문 단락은 `body`로 잡혔다.
- 표/차트/작은 이미지들은 `evidence`로 분리됐다.
- analyst는 `author_info`, 리서치센터는 `metadata`로 분리됐다.

문제점:

- `Financial Data` heading인 블록 `dolphin-financial2-00-10`은 사실상 evidence heading인데 generic role이 비어 있다.
- 본문 소제목 블록 `16`, `18`, `20`도 generic role이 비어 있다.

의미:

- semantic layer의 일관성이 완전하지 않다.
- 어떤 블록은 섹션 제목으로 `section_order`에는 반영되는데 semantic role은 없는 상태다.

### 3.2 domain role

판정: `Partial pass`

잘 된 부분:

- `BUY (유지)`, 목표주가, 현재주가 관련 블록은 `investment_opinion_box`로 일관되게 묶였다.
- `Key Data`, `Consensus Data`, `Stock Price`는 각각 `key_data_box`, `consensus_box`, `price_chart_block`으로 분류됐다.
- 메인 제목은 `report_title`, 본문 문단은 `supporting_argument`, analyst는 `analyst_info`, 리서치센터는 `research_center_meta`로 분류됐다.

문제점:

- 설계상 기대한 `thesis_heading`이 전혀 부여되지 않았다.
- 세 개의 핵심 소제목은 존재하지만 semantic적으로는 해석되지 않고 있다.
- `Financial Data` heading도 별도 domain role 없이 남아 있다.

해석:

- 이 결과는 "무엇이 패널이고 무엇이 본문인가"까지는 잘 보지만, "본문 내부에서 어떤 소제목이 논지 헤딩인가"는 아직 놓치고 있다.
- 금융 리포트 생성에 바로 쓰려면 `thesis_heading` 복원이 필요하다.

### 3.3 semantic을 약하게 두는 것이 맞는가

판정: `No`

이 페이지는 semantic을 약하게 둬야 하는 저품질 페이지가 아니다.

- `quality_score=0.7567`로 심각한 저품질은 아니다.
- 본문 텍스트도 충분히 읽을 수 있다.
- 따라서 `thesis_heading`을 생략한 것은 보수적 판단의 장점이라기보다 semantic 규칙 미완성에 가깝다.

## 4. template 리뷰

### 4.1 section_order

판정: `Needs work`

현재 [reference_template.json](/root/Desktop/workspace/ja/allm/artifacts/demo-financial2/01_reference/reference_template.json)의 `section_order`는 아래 문제를 가진다.

- `BUY (유지)`가 하나의 section으로 들어가 있다.
- `Key Data`, `Consensus Data`, `Stock Price`, `Financial Data`가 모두 section으로 들어가 있다.
- 설계상 narrative에서 제외해야 하는 evidence panel heading이 본문 골격으로 승격되어 있다.

현재 평가:

- `section-006` 이후의 우측 메인 본문 섹션은 자연스럽다.
- 하지만 `section-001`부터 `section-005`까지는 생성용 narrative 골격으로 보기 어렵다.

이것이 중요한 이유:

- downstream generation이 `section_order`를 그대로 쓰면 좌측 정보 패널을 본문 목차처럼 따라가게 된다.
- 그러면 "보고서 본문"이 아니라 "패널 라벨 나열"에 가까운 문서가 생성될 수 있다.

권장 판단:

- `BUY`, `Key Data`, `Consensus Data`, `Stock Price`, `Financial Data`는 `blocks`에는 남기되 `section_order`에서는 제외하는 편이 맞다.

### 4.2 anchor_pages

판정: `Pass`

- `anchor_pages=[1]`이고, 이 문서는 1페이지 샘플이므로 자연스럽다.
- 첫 페이지가 실제로 레이아웃 대표성이 높다.

### 4.3 style_tokens

판정: `Usable but suspicious`

현재 값:

- `title_font_scale=0.4809`
- `subtitle_font_scale=0.1247`
- `body_font_scale=0.1417`
- `column_count=2`
- `body_width_ratio=0.5981`

좋은 점:

- `column_count=2`
- `body_width_ratio`가 우측 본문 영역 폭과 대체로 맞는다.
- `section_spacing=0.2155`도 본문 섹션 간 분리감을 어느 정도 반영한다.

문제점:

- `title_font_scale`이 상대적으로 너무 크고,
- `subtitle_font_scale`보다 `body_font_scale`이 더 큰 값으로 나와 직관과 맞지 않는다.

해석:

- 수치가 시각적 체감과 완전히 일치한다고 보기 어렵다.
- 현재 style token은 "대략적인 레이아웃 힌트"로는 쓸 수 있지만, 정밀한 스타일 복원 기준으로는 아직 불안하다.

### 4.4 image_slots와 unsupported_blocks

판정: `Mixed`

`image_slots=[]`에 대한 판단:

- 이 페이지에는 생성에 재사용할 만한 큰 서사형 이미지가 없다.
- 좌측 상단 및 하단의 작은 이미지들은 장식 또는 로고 성격에 가깝다.
- 따라서 `image_slots`가 비어 있는 것은 큰 문제는 아니다.

`unsupported_blocks`에 대한 판단:

- 표와 차트가 `unsupported_for_generation`으로 분리된 것은 맞다.
- `dolphin-financial2-00-3`, `5`, `7`, `9`, `11`이 분리돼 있다.

하지만 중요한 불일치가 있다.

- `dolphin-financial2-00-3`은 `unsupported_blocks`에 있으면서 동시에 `used_for_generation=true`다.
- evidence heading 블록들도 `used_for_generation=true`인 상태다.

의미:

- 생성 제외 정책과 실제 사용 플래그가 완전히 일치하지 않는다.
- 이 불일치는 downstream에서 혼란을 만들 수 있다.

## 5. diagnostics 리뷰

### 5.1 전반 상태

판정: `Needs review but not failure`

주요 수치:

- `document_family=financial_report`
- `language=en`
- `matched_pairs=20`
- `text_replacements=12`
- `added_secondary_blocks=2`
- `overall_score=0.7567`
- `review_required=true`
- `fusion_conflicts=12`

해석:

- 엔진 결합 자체는 꽤 활발하게 일어났다.
- 본문 텍스트와 메타 텍스트 다수가 `Paddle` 쪽으로 교체됐다.
- 결과적으로 텍스트 품질은 개선됐지만, 엔진 간 불일치가 적지 않다는 뜻이기도 하다.

### 5.2 진단상 좋은 점

- `matched_pairs=20`이면 양쪽 엔진이 같은 영역을 상당히 많이 공유하고 있다.
- 핵심 본문 블록과 메타 블록 다수가 `IoU` 기준으로 잘 매칭된 것으로 보인다.
- `added_secondary_blocks`가 2개뿐이라 누락 보정이 과도하진 않다.

### 5.3 진단상 문제점

- `language=en`은 실제 문서와 맞지 않는다. 문서는 한국어 중심이다.
- `review_required=true`는 과도한 실패 신호는 아니지만, 자동 결과를 그대로 쓰기에는 이견이 있다는 뜻이다.
- `fusion_conflicts=12`는 적지 않은 수치다.
- `template_warnings`에 `low_ocr_quality_repaired_via_secondary_engine`가 들어가 있는데, 실제로는 페이지 자체가 저품질이라기보다 엔진 교체가 많았다는 의미에 가깝다.

해석:

- 현재 경고 메시지는 "OCR이 매우 나쁘다"로 읽히기 쉽지만, 실제 상태는 "보정이 많이 들어갔다"에 더 가깝다.
- 이 경고 문구는 향후 더 정확하게 다듬는 편이 좋다.

## 6. 잘 된 점

- `financial_report` 판정이 맞다.
- `cover_summary` archetype 판정이 맞다.
- 좌측 투자정보 패널과 우측 메인 본문이 분리됐다.
- 메인 제목과 3개 본문 단락이 안정적으로 추출됐다.
- analyst/contact/research center 메타가 하단에서 따로 잡혔다.
- `investment_opinion_box`, `key_data_box`, `consensus_box`, `price_chart_block` 같은 금융 패널 역할을 잘 식별했다.
- 본문 텍스트는 `Paddle` 보정을 통해 상대적으로 읽기 좋은 상태가 됐다.

## 7. 주요 이슈

### High

- `section_order`가 evidence panel heading을 본문 섹션으로 포함한다.
- `thesis_heading` semantic이 누락돼 본문 계층이 충분히 복원되지 않았다.
- `used_for_generation`과 `unsupported_blocks` 정책이 일관되지 않다.

### Medium

- `language`가 `en`으로 잘못 판정됐다.
- `Financial Data` heading에 semantic role이 없다.
- 메인 타이틀 블록에 회사명과 카피가 함께 합쳐져 있다.

### Low

- `style_tokens` 일부 값이 체감과 맞지 않는다.
- warning 문구가 실제 품질 상태를 다소 과장해 보이게 한다.

## 8. 리뷰 가이드 기준 체크리스트

### 구조 정확도

- archetype이 맞는가: `Yes`
- 큰 영역 분리가 맞는가: `Yes`
- reading order가 자연스러운가: `Mostly yes`
- 본문과 메타가 분리되는가: `Yes`
- evidence가 narrative와 분리되는가: `Block level yes / template level no`

### 의미 정확도

- report_title이 맞는가: `Mostly yes`
- supporting_argument가 맞는가: `Yes`
- investment_opinion_box가 맞는가: `Yes`
- key_data/consensus/price_chart 패널이 맞는가: `Yes`
- thesis_heading이 복원됐는가: `No`
- disclaimer/compliance 이슈가 있는가: `This page does not require disclaimer judgement`

### 활용 가능성

- 결과를 그대로 generation에 넣어도 되는가: `No`
- 수동 검토 후 사용 가능한가: `Yes`
- 가장 먼저 손봐야 할 것은 무엇인가: `section_order`, `thesis_heading`, `used_for_generation policy`, `language`

## 9. 원인 추정

이슈별로 원인을 나누면 아래와 같다.

- `language=en`
  - 언어 판별 규칙 문제
- `section_order` 오염
  - archetype 문제보다는 template synthesis 규칙 문제
- `thesis_heading` 누락
  - financial semantic overlay 규칙 미완성
- `used_for_generation`과 `unsupported_blocks` 불일치
  - export contract 또는 template assembly 정책 문제
- `text_replacements=12`
  - OCR 품질 자체보다는 fusion 전략의 적극적 보정 결과

즉, 현재 가장 큰 문제는 OCR 실패보다 후처리 정책 정교화 부족이다.

## 10. 최종 판단

최종 등급은 `Usable with review`다.

이유:

- 핵심 구조와 주요 금융 semantic은 이미 상당 부분 맞는다.
- 따라서 이 결과를 기반으로 규칙을 다듬는 것은 충분히 가치가 있다.
- 다만 현재 상태로는 생성용 템플릿 계약으로 바로 신뢰하기엔 위험하다.

한 줄 판단:

`문서 구조와 금융 패널 인식은 성공했지만, 생성용 골격과 semantic 계층을 다듬지 않으면 downstream에서 evidence 패널과 narrative가 섞일 위험이 있다.`

## 11. 권장 후속 작업

1. `section_order`에서 `evidence_panel`과 `investment_summary`를 narrative section으로 승격하지 않도록 수정
2. `subheading` 블록 `16`, `18`, `20`에 `thesis_heading` 부여 규칙 추가
3. `unsupported_blocks`에 들어간 block은 `used_for_generation=false`가 되도록 정책 정합성 맞추기
4. `language` 판별을 한국어 문서에 맞게 보정
5. `Financial Data` heading의 generic/domain role 처리 여부를 명시적으로 결정
6. `style_tokens` 계산식에서 title/subtitle/body 상대값 재검토
