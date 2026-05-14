# 📡 정부지원사업 자동 수집 시스템

> 대학 산학협력단을 위한 보안 적용 정부지원사업 공고 자동화 툴

---

## 📁 파일 구조

```
gov_crawler/
├── crawler.py                          # 메인 크롤러 스크립트
├── requirements.txt                    # 패키지 목록
├── .env.example                        # 환경변수 템플릿 (복사해서 .env로 사용)
├── .gitignore                          # GitHub 업로드 제외 목록
└── .github/
    └── workflows/
        └── daily_crawler.yml           # GitHub Actions 자동화
```

---

## ⚡ 빠른 시작 (5분 설치)

### Step 1. 패키지 설치

```bash
pip install -r requirements.txt
```

### Step 2. API 키 설정

```bash
# .env.example을 복사해서 .env 파일 생성
cp .env.example .env

# .env 파일을 텍스트 편집기로 열어 API 키 입력
# Windows: notepad .env
# Mac/Linux: nano .env
```

`.env` 파일 내용:
```
BIZINFO_API_KEY=발급받은_기업마당_API_키
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
```

### Step 3. 실행

```bash
python crawler.py
```

---

## 🔐 보안 가이드 (API 키 안전 보관)

### 핵심 원칙

| ✅ 해야 할 것 | ❌ 하면 안 되는 것 |
|---|---|
| `.env` 파일에 키 저장 | 코드(`crawler.py`)에 직접 입력 |
| `.gitignore`에 `.env` 추가 | `.env` 파일을 GitHub에 push |
| GitHub Secrets 활용 | Slack/카톡 등에 키 전송 |
| 키 노출 시 즉시 재발급 | 키를 여러 사람과 공유 |

### 환경변수 3가지 설정 방법

#### 방법 A. `.env` 파일 (로컬 실행, 가장 간단)
```bash
# .env 파일 생성 후 입력
BIZINFO_API_KEY=your_key_here
SLACK_WEBHOOK_URL=https://hooks.slack.com/...
```

#### 방법 B. 시스템 환경변수 (터미널에서 직접)
```bash
# Windows (PowerShell)
$env:BIZINFO_API_KEY = "your_key_here"

# Mac/Linux (bash/zsh)
export BIZINFO_API_KEY="your_key_here"
echo 'export BIZINFO_API_KEY="your_key_here"' >> ~/.zshrc
```

#### 방법 C. GitHub Secrets (자동화, 가장 안전)
```
저장소 → Settings → Secrets and variables
→ Actions → New repository secret
→ BIZINFO_API_KEY 입력
```

---

## 🤖 자동화 파이프라인 옵션 2가지

---

### 옵션 1. GitHub Actions (무료, 추천)

```
장점: 완전 무료 / 서버 불필요 / API 키 안전 보관 / 로그 자동 기록
단점: GitHub 계정 필요 / 코드를 저장소에 올려야 함
```

**설정 순서:**

```
1. GitHub 계정 생성 (github.com)
2. 새 저장소(Repository) 생성 — Private으로 설정 ← 중요!
3. 파일 업로드: crawler.py, requirements.txt, .github/workflows/daily_crawler.yml
   (.env는 절대 올리지 않기!)
4. Settings > Secrets and variables > Actions
   → BIZINFO_API_KEY, SLACK_WEBHOOK_URL 등록
5. Actions 탭에서 워크플로우 확인
   → 매일 오전 9시 자동 실행됨
```

**수동으로 즉시 실행하려면:**
```
Actions 탭 → "정부지원사업 공고 자동 수집" 클릭
→ [Run workflow] 버튼 클릭
```

---

### 옵션 2. Make(구 Integromat) 노코드 파이프라인

```
장점: 코딩 없음 / 시각적 설정 / 구글시트·슬랙 연동 쉬움
단점: 월 1,000 operations 제한 (무료) / 복잡한 필터링 한계
```

**Make 워크플로우 구성:**

```
[Schedule: 매일 09:00]
    ↓
[HTTP: GET 기업마당 API]
    ↓
[JSON Parse: 응답 파싱]
    ↓
[Iterator: 공고 항목 순회]
    ↓
[Filter: "대학" OR "산학협력" 포함]
    ↓
[Google Sheets: 행 추가]
    ↓
[Slack: 요약 메시지 전송]
```

**설정 방법:**
```
1. make.com 무료 가입
2. [Create a new scenario] 클릭
3. 첫 모듈: "Schedule" 선택 → Every Day, 09:00
4. + 버튼 → "HTTP" → Make a request
   URL: 기업마당 API 엔드포인트
   Headers: serviceKey=환경변수 또는 직접 입력
5. + 버튼 → "JSON" → Parse JSON
6. + 버튼 → "Tools" → Iterator (배열 순회)
7. + 버튼 → "Filter" 추가
   조건: title CONTAINS "대학" OR "산학협력"
8. + 버튼 → "Google Sheets" → Add a Row
9. + 버튼 → "Slack" → Create a Message
10. [Save] → [Run once]로 테스트 → [Schedule ON]
```

---

## 📊 출력 결과 형식

수집 결과는 `output/` 폴더에 저장됩니다.

| 컬럼 | 설명 | 예시 |
|------|------|------|
| 소스 | 데이터 출처 | 기업마당, 교육부 |
| 사업명 | 공고 제목 | 2025년 산학연협력 기술개발사업 |
| 주관부처 | 담당 부처 | 중소벤처기업부 |
| 마감일 | 신청 마감일 | 20250731 |
| 상세링크 | 원본 공고 URL | https://... |
| 수집일시 | 자동 수집 시각 | 2025-07-01 09:00 |

---

## 🔑 기업마당 API 키 발급 방법

```
1. https://www.data.go.kr 접속
2. 상단 메뉴 [데이터찾기] → 검색창에 입력:
   "중소벤처기업부 중소기업 지원사업 공고 조회"
3. 검색결과에서 "오픈API" 탭 선택
4. 해당 API 클릭 → [활용신청] 버튼
5. 활용목적 입력 후 신청 (보통 1~2일 내 승인)
6. 마이페이지 > 데이터활용 > 오픈API → 인증키 확인
7. 일반 인증키(Decoding) 복사해서 .env에 입력
```

---

## ❓ 자주 묻는 문제

**Q. API 호출이 안 돼요**
- `.env` 파일에 키가 정확히 입력됐는지 확인
- `python -c "import os; from dotenv import load_dotenv; load_dotenv(); print(os.environ.get('BIZINFO_API_KEY','❌ 키 없음')[:10])"`

**Q. 교육부 크롤링이 빈 결과예요**
- 교육부 사이트 구조가 변경됐을 수 있음
- `crawler.py`의 `_parse_moe_page` 함수의 CSS 셀렉터 확인

**Q. GitHub Actions 실행이 안 돼요**
- Secrets에 키가 등록됐는지 확인
- Actions 탭에서 워크플로우가 enabled 상태인지 확인
