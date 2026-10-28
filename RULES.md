# Humanizing-draft 설계 규칙 (v0.1)

AI 보조로 작성한 **영어 공학 논문 원고**(OLED · PeLED · QLED · 광학 · 디스플레이 분야)를 대상으로,
2020년 이전에 사람이 쓴 논문의 문체를 기준으로 "AI가 쓴 것처럼 읽히는" 문장을 찾아 위험도를 매기고
교정안을 제안하는 도구의 규칙 문서다. 코드의 `rule_id`는 이 문서의 ID와 일치한다.

---

## 0. 범위와 원칙

| 항목 | 결정 |
|---|---|
| 언어 | 영어 논문만 |
| 분야 | 공학 — OLED, PeLED(perovskite LED), QLED, 광학/광자학, 디스플레이 |
| 입력 | `.docx`, `.pdf` |
| 출력 | 주석 달린 원본(`.docx` 형광펜+메모 / `.pdf` 하이라이트+노트), 별도 리포트(`.docx`, `.pdf`, `.json`) |
| 교정 제안 | 외부 API(Claude) 사용 가능. API 없이도 규칙 기반 탐지와 대체어 제안은 동작해야 함 |
| 학습 데이터 | Open Access 공학 논문 원문(2019년 이하 출판) |

**P1. 제안만 하고 자동 치환하지 않는다.** 최종 선택은 항상 저자가 한다.
**P2. 모든 판정에는 근거가 붙는다.** 어떤 규칙이 몇 점을 줬는지 보여 준다.
**P3. 의미·수치·인용을 바꾸지 않는다.** (§4 보호 토큰)
**P4. 이 도구는 문체 개선 도구다.** 저널의 AI 사용 공개 의무(ICMJE, Elsevier, Nature, ACS, Wiley, Optica 등)를 대체하지 않으며, README와 리포트에 이를 명시한다.

---

## 1. 코퍼스 규칙 (C)

### C1. 수집 대상
- **출판 연도 ≤ 2019** (`publication_year < 2020`).
- **Open Access** 이며 원문(전문)을 합법적으로 받을 수 있는 것만. 라이선스(`cc-by` 등)를 메타데이터에 기록한다.
- 유형: 연구 논문(`article`). 리뷰, 사설, 정정 공지는 제외(리뷰는 옵션으로 별도 수집).
- 언어: 영어.

### C2. 주제 필터
제목·초록에 다음 키워드군 중 하나 이상 포함 (`humanizer/config.py`의 `DOMAIN_QUERIES`):
- OLED: organic light-emitting diode/device, OLED, phosphorescent, TADF(thermally activated delayed fluorescence), exciplex, outcoupling
- PeLED: perovskite light-emitting, perovskite LED, PeLED, CsPbBr3/CsPbI3 nanocrystal electroluminescence
- QLED: quantum dot light-emitting, QLED, QD-LED, colloidal quantum dot electroluminescence
- 광학/디스플레이: microcavity, light extraction, liquid crystal display, micro-LED, color conversion, waveguide, photonic crystal, metasurface(디스플레이·발광 관련)

### C3. 우선순위 점수 (높을수록 먼저 수집·학습)
`priority = 0.40·인용 + 0.20·연차 + 0.25·소속 + 0.10·저널 + 0.05·주제일치`
- **인용**: `log(1+cited_by_count)`를 후보군 최대값으로 정규화.
- **연차**: 오래될수록 가산(2019→0, 1999 이전→1). 단 OA 원문이 적은 2000년 이전 논문은 수가 적으므로 가중치를 과도하게 두지 않는다.
- **소속**: 미국·유럽(EU/EEA + 영국 + 스위스) 소속 저자 비율. **교신(마지막) 저자**가 미국/유럽이면 +보너스. 원어민 영어 문체를 우선 학습하기 위함.
- **저널**: 분야 대표 저널 가산 (Nature/Science 계열, Nature Photonics, Advanced Materials, Applied Physics Letters, Optics Express, Organic Electronics, J. Appl. Phys., Phys. Rev. B, ACS Nano, Nano Letters, Light: Sci. & Appl., J. SID 등).
- 가중치는 `config.py`에서 조정 가능.

### C4. 원문 확보 순서
1. PMC ID가 있으면 **Europe PMC JATS XML** (섹션 구조가 가장 깨끗함)
2. arXiv 버전이 있으면 arXiv PDF
3. OpenAlex `best_oa_location.pdf_url`
4. 실패 시 건너뛰고 로그에 남김 (봇 차단 우회 금지)

### C5. 전처리
- 제거: 참고문헌, 감사의 글, 저자 정보, 각주, 수식 행, 표 본문, 페이지 머리말/꼬리말, 줄 번호.
- 인용 표기 `[12]`, `[3–5]`, 위첨자 숫자, `(Kim et al., 2018)` → `<CIT>` 로 정규화.
- 줄바꿈 하이픈 복원(`elec-\ntroluminescence` → `electroluminescence`).
- 그림 캡션은 `caption` 섹션으로 분리 보관(본문 통계와 섞지 않음).
- 섹션 정규화: `abstract / introduction / methods / results / discussion / conclusion / caption / other`
  (`Results and Discussion`은 `results`, `Experimental`·`Device fabrication`은 `methods`).

### C6. 저작권
- 원문은 `data/raw/`에만 저장하고 **git에 커밋하지 않는다** (`.gitignore`).
- 학습 결과는 빈도·통계·짧은 n-gram(≤ 5어절)만 저장한다. **원문 문장을 그대로 교정안으로 내보내지 않는다.**

### C7. 대조 코퍼스 (AI 텍스트)
- 사람 코퍼스 문단을 LLM으로 다시 쓰게 한 **쌍(pair) 데이터**를 만든다 (`synth-ai`).
  같은 기술 내용이라 기술 용어 효과가 상쇄되고 "문체 차이"만 남는다.
- 두 가지 모드: `rewrite`(문단 재작성), `generate`(제목·섹션만 주고 작성).
- 사용자가 실제로 쓰는 다른 LLM(ChatGPT, Gemini 등)의 출력도 `data/corpus/ai_docs.jsonl`에 추가하는 것을 권장한다. 모델이 다양할수록 일반화가 좋아진다.

---

## 2. 스타일 프로파일 (P)

사람 코퍼스에서 섹션별로 다음을 학습해 `data/profile/profile.json`에 저장한다.

| ID | 항목 | 용도 |
|---|---|---|
| P1 | 단어·2-gram·3-gram 빈도(백만 단어당) | 위험 단어의 "사람 기준 빈도" 근거 제시, 대체어 순위 |
| P2 | 문장 길이 평균·표준편차·변동계수(CV) | 리듬(burstiness) 판정 기준 |
| P3 | 문장 시작어 분포 | 접속부사 남용 판정 |
| P4 | 1인칭(we) 비율, 수동태 비율 | 섹션 관례 비교 |
| P5 | em dash, 세미콜론, 콜론 사용률 | 구두점 판정 |
| P6 | 문단 길이(문장 수) | 문단 구조 비교 |

---

## 3. 탐지 규칙 (D)

각 문장에 대해 규칙별 가중치를 합산한 점수로 위험도를 매긴다.
기본 임계값(`detector.yaml`에서 조정): **High ≥ 2.5, Medium ≥ 1.2, Low ≥ 0.5**.

### 3.1 어휘 (LEX)
| ID | 내용 | 예 |
|---|---|---|
| LEX_WORD | AI 과다 사용 단어 (시드 목록 + 학습 목록) | delve, pivotal, underscore, showcase, intricate, multifaceted, meticulous, tapestry, realm, foster, leverage, seamless, groundbreaking, testament |
| LEX_PHRASE | AI 상투 구문 | plays a crucial role, it is worth noting, shed light on, pave the way, in the realm of, holds great promise, has garnered significant attention, offering valuable insights, unlock the full potential |
| LEX_LEARNED | 대조 코퍼스에서 학습한 AI 편향 단어/구 (log-odds z-score) | 데이터로 자동 생성 |
| LEX_OVERUSE | 같은 위험 표현이 문서 안에서 3회 이상 반복 | |

공학 분야에서 정당하게 쓰이는 단어(robust, state-of-the-art, enhance, elucidate, significantly 등)는 가중치를 낮게 두거나 0으로 둔다. 사용자 허용 목록(`allowlist`)으로 끌 수 있다.

### 3.2 문장 구조 (STR)
| ID | 내용 |
|---|---|
| STR_TRAILING_PARTICIPLE | 문장 끝 분사구: `…, highlighting/underscoring/showcasing/paving …` (indicating/suggesting은 낮은 가중치) |
| STR_TRANSITION_START | Moreover / Furthermore / Additionally / Notably / Importantly / Crucially / Overall 등으로 시작 |
| STR_EM_DASH | em dash(—) 사용. 2020년 이전 공학 논문에서는 드묾 |
| STR_NOT_ONLY | not only … but also |
| STR_TRIAD | 형용사·추상명사 3개 나열 (efficient, stable, and scalable) |
| STR_THIS_SUMMARY | `This/These … highlights/underscores/showcases …` 형태의 자기 요약 |
| STR_RHETORICAL_Q | 수사 의문문 |
| STR_HEDGE_STACK | could potentially, may potentially 등 중복 hedging |
| STR_UNSUPPORTED_INTENSIFIER | remarkable/exceptional/unprecedented/significantly 등을 수치·인용 없이 사용 |
| STR_LONG_SENTENCE | 섹션 평균보다 2.5σ 이상 긴 문장 (프로파일 있을 때) |

### 3.3 문단·담화 (PAR)
| ID | 내용 |
|---|---|
| PAR_LOW_BURSTINESS | 4문장 이상 문단에서 문장 길이 CV가 사람 기준보다 현저히 낮음(기본 < 0.25) |
| PAR_TRANSITION_DENSITY | 문단 내 접속부사 시작 문장 비율 ≥ 40% |
| PAR_SUMMARY_END | Conclusion이 아닌 섹션에서 문단 끝마다 Overall/In summary/These results highlight… 식의 요약 |

### 3.4 섹션 보정
- `methods`, `caption`: 어휘 규칙 가중치 × 0.8 (정형화된 서술이 많음)
- `abstract`, `introduction`, `conclusion`: × 1.0 (AI 상투 표현이 가장 많이 나오는 구간)

### 3.5 참고문헌 검증 (REF)
| ID | 내용 |
|---|---|
| REF_DOI_NOT_FOUND | 참고문헌의 DOI가 CrossRef에 존재하지 않음 → **High** (AI 환각 인용 의심) |
| REF_TITLE_MISMATCH | DOI는 있으나 제목이 실제 메타데이터와 크게 다름 |
| REF_NO_MATCH | DOI 없이 서지 검색했을 때 유사 문헌이 없음 |

---

## 4. 교정 규칙 (R)

| ID | 규칙 |
|---|---|
| R1 | **보호 토큰 불변**: 숫자, 단위, ±, %, 인용 표기, 화학식(CsPbBr3, Ir(ppy)3), 약어(EQE, ITO, HTL, PEDOT:PSS), 그림/식 참조(Fig. 2a, Eq. (3)) 는 교정 전후 동일해야 한다. 위반한 제안은 폐기한다. |
| R2 | 문장당 교정안 2~3개 + 짧은 근거(한국어)를 제시한다. |
| R3 | 기준 문체는 **2019년 이전 미국·유럽 공학 논문**: 직접적, 구체적, 수치 중심, 짧은 문장과 긴 문장의 혼합. |
| R4 | 과교정 금지: 구어체, 일부러 넣는 오류, 의미 축소/확대 금지. |
| R5 | 섹션 관례 유지: Methods 과거형·수동태 허용, Results 과거형, Discussion은 적절한 hedging(may, suggest). |
| R6 | 용어 일관성: 같은 개념은 같은 용어로 쓴다(AI식 동의어 돌려쓰기 금지). |
| R7 | **재검사**: 모든 교정안은 탐지기를 다시 통과해야 하며, 원문보다 위험 등급이 낮아야 한다(High 원문 → Medium 이하). |
| R8 | API를 쓸 수 없으면 `alternatives.yaml`의 대체어 사전(사람 코퍼스 빈도로 정렬)으로 단어 단위 제안만 한다. |

---

## 5. 출력 규칙 (O)

- `*.annotated.docx`: 위험 문장 형광펜(High=빨강, Medium=노랑, Low=하늘색) + Word 메모(규칙, 근거, 교정안).
- `*.annotated.pdf`: 하이라이트 주석 + 팝업 노트.
- `*.report.docx` / `*.report.pdf`: 요약(문서 위험 점수, 섹션별 분포, 상위 규칙), 문장별 상세 표.
- `*.report.json`: 기계 판독용 전체 결과.

---

## 6. 검증과 운영 규칙 (E)

| ID | 규칙 |
|---|---|
| E1 | 사람 코퍼스 일부(기본 10%)를 학습에서 떼어 **테스트셋**으로 둔다. |
| E2 | 출시 기준: 사람 테스트셋 문장 중 **High 판정 ≤ 2%**, Medium 이상 ≤ 10%. |
| E3 | AI 테스트셋 문장 중 Medium 이상 판정률(재현율)을 함께 보고한다. |
| E4 | 비영어권 저자 문체가 과도하게 플래그되는지 별도 점검한다(소속 국가별 오탐률). |
| E5 | 규칙 가중치를 바꿀 때마다 `evaluate`를 다시 실행하고 결과를 기록한다. |
| E6 | 원고 원문은 교정 제안에 필요한 문단만 API로 보낸다. 전송 여부는 `--suggest` 플래그로 명시적으로 켠다. |
