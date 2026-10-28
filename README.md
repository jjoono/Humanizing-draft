# Humanizing-draft

AI 보조로 작성한 **영어 공학 논문 원고**(OLED · PeLED · QLED · 광학 · 디스플레이)에서
"AI가 쓴 것처럼 읽히는" 문장을 찾아 위험도(High / Medium / Low)를 매기고, 근거와 교정안을 보여 주는 도구입니다.
기준 문체는 **2020년 이전 미국·유럽 연구진의 Open Access 공학 논문**에서 학습합니다.

전체 규칙은 [RULES.md](RULES.md)에 있습니다. 리포트에 나오는 `rule_id`(예: `LEX_PHRASE`, `STR_TRAILING_PARTICIPLE`)는 이 문서의 ID와 같습니다.

> 이 도구는 문체를 다듬기 위한 것입니다. 원고 작성에 AI를 썼다면 투고 저널의 AI 사용 공개 규정은 따로 지켜야 합니다.

## 설치

```bash
pip install -e ".[llm,dev]"
```

`llm`은 Claude 교정 제안(`--suggest`)과 AI 대조 코퍼스 생성(`synth-ai`)에 필요합니다. API 키는 `ANTHROPIC_API_KEY` 환경 변수로 넘깁니다.

## 1. 원고 분석 (코퍼스 없이도 바로 사용 가능)

```bash
humanizer analyze draft.docx --out out/
```

```bash
humanizer analyze draft.pdf --out out/ --suggest --refcheck
```

| 출력 파일 | 내용 |
|---|---|
| `*.annotated.docx` / `*.annotated.pdf` | 위험 문장에 형광펜(빨강=High, 노랑=Medium, 하늘색=Low) + 메모(근거, 교정안) |
| `*.report.docx` / `*.report.pdf` | 요약, 섹션별 분포, 자주 걸린 규칙, 문장별 상세 |
| `*.report.json` | 전체 결과 |

주요 옵션은 다음과 같습니다.
- `--min-risk low|medium|high`: 주석을 달고 교정안을 요청할 최소 위험도 (기본 `medium`)
- `--suggest`: 위험 문장이 있는 문단만 Claude API로 보내 교정안 2~3개를 받습니다. 숫자·인용·화학식이 바뀐 교정안, 재검사에서 위험 등급이 내려가지 않은 교정안은 자동으로 버립니다(R1, R7).
- `--refcheck`: 참고문헌 DOI를 CrossRef로 확인해 존재하지 않는 인용(AI 환각 의심)을 표시합니다.
- `--allow WORD`: 분야에서 정당하게 쓰는 단어를 제외합니다 (여러 번 사용 가능).

## 2. 기준 코퍼스 구축 (2019년 이하 OA 논문)

아래 단계는 OpenAlex · Europe PMC · arXiv · 출판사 사이트에 접속해야 합니다.

OpenAlex는 API 키가 없으면 같은 IP를 쓰는 모든 사용자가 하루 무료 한도를 나눠 씁니다. 무료 키를 받아 넣으세요(https://help.openalex.org/api/authentication/).

```bash
export OPENALEX_API_KEY=your-key
```

```bash
export HUMANIZER_MAILTO=you@example.com
```

```bash
humanizer collect
```

```bash
humanizer fetch --limit 500
```

```bash
humanizer extract
```

```bash
humanizer build-profile
```

1. `collect`: 분야별 검색 → 미국/유럽 소속 저자 포함 · OA · 2019년 이하로 거른 뒤, 인용 수 · 연차 · 소속 · 저널 점수로 정렬합니다 → `data/corpus/candidates.jsonl`
2. `fetch`: 우선순위 순으로 Europe PMC XML → arXiv PDF → OA PDF 순서로 내려받습니다 → `data/raw/`
3. `extract`: 섹션 분리, 인용 정규화, 수식·표·참고문헌 제거, 10%는 테스트셋으로 분리합니다 → `data/corpus/human_docs.jsonl`, `human_test.jsonl`
4. `build-profile`: 섹션별 문장 길이 · 시작어 · 수동태 · em dash 비율, n-gram 빈도를 학습합니다 → `data/profile/profile.json`

`data/`는 저작권 때문에 git에 올리지 않습니다(`.gitignore`).

## 3. AI 대조 코퍼스와 학습 마커

```bash
humanizer synth-ai --limit 200
```

```bash
humanizer learn-markers
```

`synth-ai`는 사람 문단을 Claude로 다시 쓰게 해서 같은 내용의 쌍(pair) 데이터를 만듭니다.
ChatGPT 등 실제로 쓰는 다른 LLM의 출력도 같은 형식으로 `data/corpus/ai_docs.jsonl`에 추가하면 탐지 범위가 넓어집니다.
`learn-markers`는 두 코퍼스의 log-odds 비율로 AI 쪽에 치우친 단어와 구를 뽑아 `LEX_LEARNED` 규칙으로 씁니다.

## 4. 오탐률 검증

```bash
humanizer evaluate --ai data/corpus/ai_docs.jsonl
```

사람 테스트셋에서 High ≤ 2%, Medium 이상 ≤ 10%이면 `release_gate_passed: true`가 됩니다(E2).
`humanizer/data/detector.yaml`의 가중치를 바꿀 때마다 다시 실행해서 결과를 비교하세요.

## 구조

```
humanizer/
  cli.py            명령어
  config.py         코퍼스 대상 분야·국가·저널·우선순위 가중치
  corpus/           OpenAlex 수집, 원문 다운로드, 텍스트 추출, AI 대조 코퍼스 생성
  profile.py        사람 스타일 프로파일, 대조 마커 학습
  detect.py         문장·문단 단위 탐지 규칙
  data/detector.yaml      시드 규칙과 가중치 (직접 수정 가능)
  data/alternatives.yaml  API 없이 쓰는 대체어 사전
  rewrite.py        Claude 교정 제안 + 보호 토큰/재검사 가드
  refcheck.py       CrossRef 참고문헌 검증
  io_docx.py, io_pdf.py   입력 파싱과 주석 달린 사본 생성
  report.py         docx / pdf / json 리포트
tests/
```

```bash
pytest
```
