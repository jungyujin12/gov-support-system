"""
================================================================
 정부지원사업 자동 수집 시스템 v3
 Gov Grant Radar — Structured Data Edition
================================================================
 v3 변경사항:
   - sources.json 기반 소스 ON/OFF 관리
   - /data/latest.json + /data/latest.csv 저장
   - /archive/YYYY-MM-DD.json 날짜별 누적
   - 크로스데이 중복 제거 (archive 기반)
   - 확장 가능한 소스 핸들러 구조

 디렉토리 구조:
   /data
     latest.json   ← 대시보드 fetch()용 최신 공고
     latest.csv    ← CSV 다운로드용
   /archive
     2026-05-14.json
     2026-05-15.json   ← 날짜별 누적 보관

 설치:
   pip install requests beautifulsoup4 pandas python-dotenv openpyxl
================================================================
"""

import os
import sys
import json
import time
import logging
import requests
import pandas as pd
from datetime import datetime
from typing import Optional
from bs4 import BeautifulSoup
from pathlib import Path

# ──────────────────────────────────────────────
# [1] 환경변수 로드
# ──────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ──────────────────────────────────────────────
# [2] 로깅
# ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("crawler.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# [3] 경로 설정
# ──────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent
DATA_DIR    = BASE_DIR / "data"
ARCHIVE_DIR = BASE_DIR / "archive"
SOURCES_FILE = BASE_DIR / "sources.json"

DATA_DIR.mkdir(exist_ok=True)
ARCHIVE_DIR.mkdir(exist_ok=True)


# ──────────────────────────────────────────────
# [4] 설정 (Config)
# ──────────────────────────────────────────────
class Config:
    BIZINFO_API_KEY:  str = os.environ.get("BIZINFO_API_KEY", "")
    SLACK_WEBHOOK_URL: str = os.environ.get("SLACK_WEBHOOK_URL", "")

    BIZINFO_URL: str = (
        "https://apis.data.go.kr/B552735/kisedbizentrprssupport/getAnnoList"
    )
    BIZINFO_ROWS: int = 100

    # HTTP
    TIMEOUT:     int   = 20
    RETRY:       int   = 3
    RETRY_DELAY: int   = 2
    PAGE_DELAY:  float = 0.8

    # 중복 제거용 archive 참조 일수
    DEDUP_ARCHIVE_DAYS: int = 7


# ──────────────────────────────────────────────
# [5] sources.json 로드
# ──────────────────────────────────────────────
def load_sources() -> list[dict]:
    """
    sources.json에서 활성화된 소스 목록 반환.
    파일 없으면 기본값(기업마당+교육부)으로 동작.
    """
    if not SOURCES_FILE.exists():
        logger.warning("⚠️  sources.json 없음 → 기본 소스로 실행")
        return [
            {"source": "기업마당",      "enabled": True,  "type": "api",   "pages": 5},
            {"source": "교육부_사업공고","enabled": True,  "type": "crawl", "pages": 5, "board_id": "72761"},
        ]

    with open(SOURCES_FILE, encoding="utf-8") as f:
        all_sources = json.load(f)

    enabled = [s for s in all_sources if s.get("enabled", False)]
    disabled = [s["source"] for s in all_sources if not s.get("enabled", False)]

    logger.info(f"📋 활성 소스: {[s['source'] for s in enabled]}")
    if disabled:
        logger.info(f"   비활성 소스: {disabled}")

    return enabled


# ──────────────────────────────────────────────
# [6] HTTP 유틸
# ──────────────────────────────────────────────
def safe_get(url: str, params: dict = None) -> Optional[requests.Response]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
        ),
        "Accept-Language": "ko-KR,ko;q=0.9",
    }
    for attempt in range(1, Config.RETRY + 1):
        try:
            res = requests.get(url, params=params, headers=headers, timeout=Config.TIMEOUT)
            res.raise_for_status()
            return res
        except requests.exceptions.Timeout:
            logger.warning(f"⏱️  타임아웃 {attempt}/{Config.RETRY}: {url[:55]}")
        except requests.exceptions.HTTPError as e:
            logger.error(f"❌ HTTP {e.response.status_code}: {url[:55]}")
            return None
        except requests.exceptions.ConnectionError:
            logger.warning(f"🔌 연결 실패 {attempt}/{Config.RETRY}")
        except Exception as e:
            logger.error(f"❌ 요청 오류: {e}")
            return None
        if attempt < Config.RETRY:
            time.sleep(Config.RETRY_DELAY)
    return None


# ──────────────────────────────────────────────
# [7] 날짜 정규화
# ──────────────────────────────────────────────
def normalize_date(raw: str) -> str:
    """
    다양한 형식 → YYYY-MM-DD 변환.
    파싱 불가 시 빈 문자열 반환.
    """
    import re
    if not raw:
        return ""
    raw = str(raw).strip()

    # 이미 YYYY-MM-DD
    if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        return raw

    # 8자리 숫자: 20251231
    if re.match(r"^\d{8}$", raw):
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"

    # 구분자 치환 후 재시도
    cleaned = re.sub(r"[./]", "-", raw)
    if re.match(r"^\d{4}-\d{2}-\d{2}$", cleaned):
        return cleaned

    # 날짜 패턴 추출
    match = re.search(r"(\d{4})[.\-/](\d{2})[.\-/](\d{2})", raw)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"

    logger.debug(f"날짜 파싱 실패: '{raw}'")
    return ""


# ──────────────────────────────────────────────
# [8] 소스 핸들러 — 기업마당 API
# ──────────────────────────────────────────────
def handler_bizinfo(source_cfg: dict) -> list[dict]:
    """기업마당 API 다중 페이지 수집"""
    if not Config.BIZINFO_API_KEY:
        logger.warning("⚠️  BIZINFO_API_KEY 없음 → 기업마당 건너뜀")
        return []

    pages = source_cfg.get("pages", 5)
    logger.info(f"📡 기업마당 API ({pages}페이지 × {Config.BIZINFO_ROWS}건)")
    results = []

    for page in range(1, pages + 1):
        params = {
            "serviceKey": Config.BIZINFO_API_KEY,
            "pageNo": page,
            "numOfRows": Config.BIZINFO_ROWS,
            "type": "json",
        }
        res = safe_get(Config.BIZINFO_URL, params=params)
        if not res:
            continue

        try:
            body   = res.json().get("response", {}).get("body", {})
            total  = int(body.get("totalCount", 0))
            items  = body.get("items", [])
            if isinstance(items, dict):
                items = [items]
            if not items:
                break

            for item in items:
                title = str(item.get("pblancNm", "")).strip()
                if not title:
                    continue
                pid = str(item.get("pblancId", "")).strip()
                url = (
                    f"https://www.bizinfo.go.kr/web/lay1/bbs/S1T122C128/AS/74/"
                    f"view.do?pblancId={pid}" if pid else "https://www.bizinfo.go.kr"
                )
                results.append({
                    "소스":     "기업마당",
                    "사업명":   title,
                    "주관부처": str(item.get("jrsdInsttNm", "")).strip(),
                    "마감일":   normalize_date(str(item.get("rcptEndDd", ""))),
                    "상세링크": url,
                })

            logger.info(f"   └ {page}페이지: {len(items)}건 (전체 {total}건)")
            if page * Config.BIZINFO_ROWS >= total:
                break

        except Exception as e:
            logger.error(f"   └ {page}페이지 파싱 오류: {e}")

        time.sleep(Config.PAGE_DELAY)

    logger.info(f"   ✅ 기업마당 합계: {len(results)}건")
    return results


# ──────────────────────────────────────────────
# [9] 소스 핸들러 — 교육부 게시판
# ──────────────────────────────────────────────
def handler_moe(source_cfg: dict) -> list[dict]:
    """교육부 게시판 다중 페이지 크롤링"""
    board_id   = source_cfg.get("board_id", "72761")
    pages      = source_cfg.get("pages", 5)
    src_name   = source_cfg.get("source", "교육부")
    BASE       = "https://www.moe.go.kr"

    logger.info(f"🏫 {src_name} (board={board_id}, {pages}페이지)")
    results = []

    for page in range(1, pages + 1):
        time.sleep(Config.PAGE_DELAY)
        url = f"{BASE}/boardCnts/listRenew.do?boardID={board_id}&page={page}"
        res = safe_get(url)
        if not res:
            continue

        soup = BeautifulSoup(res.text, "html.parser")
        rows = []
        for sel in ["table.board_list tbody tr", "table.bbs_list tbody tr", "tbody tr"]:
            rows = soup.select(sel)
            if rows:
                break

        page_items = []
        for row in rows:
            try:
                a = (
                    row.select_one("td.subject a")
                    or row.select_one("td.title a")
                    or row.select_one("td a[href*='boardCnts']")
                    or row.select_one("td a")
                )
                if not a:
                    continue
                title = a.get_text(strip=True)
                if not title or title in ("공지", "[공지]"):
                    continue

                href = a.get("href", "")
                if href and not href.startswith("http"):
                    href = BASE + href
                if not href or href.rstrip("/").endswith("#"):
                    href = BASE

                date_raw = _extract_date(row)

                page_items.append({
                    "소스":     src_name,
                    "사업명":   title,
                    "주관부처": "교육부",
                    "마감일":   normalize_date(date_raw),
                    "상세링크": href,
                })
            except Exception as e:
                logger.debug(f"행 파싱 오류: {e}")

        results.extend(page_items)
        logger.info(f"   └ {page}페이지: {len(page_items)}건")

        if not page_items:
            break  # 빈 페이지 = 마지막 페이지

    logger.info(f"   ✅ {src_name} 합계: {len(results)}건")
    return results


def _extract_date(row) -> str:
    """테이블 행에서 날짜 텍스트 추출"""
    import re
    pattern = re.compile(r"\d{4}[.\-/]\d{2}[.\-/]\d{2}|\d{8}")

    # 날짜 클래스 우선
    for cls in ["date", "regDate", "reg_date", "td_date"]:
        cell = row.select_one(f"td.{cls}")
        if cell:
            t = cell.get_text(strip=True)
            m = pattern.search(t)
            return m.group() if m else t

    # 전체 셀에서 패턴 탐색
    for td in row.select("td"):
        t = td.get_text(strip=True)
        m = pattern.search(t)
        if m:
            return m.group()

    # 마지막 셀
    tds = row.select("td")
    return tds[-1].get_text(strip=True) if tds else ""


# ──────────────────────────────────────────────
# [10] 향후 소스 핸들러 플레이스홀더
#      sources.json에서 enabled:true로 바꾸고
#      아래 함수를 구현하면 자동으로 수집됨
# ──────────────────────────────────────────────
def handler_iris(source_cfg: dict) -> list[dict]:
    logger.info("ℹ️  IRIS 핸들러 미구현")
    return []

def handler_nrf(source_cfg: dict) -> list[dict]:
    logger.info("ℹ️  NRF 핸들러 미구현")
    return []

def handler_kstartup(source_cfg: dict) -> list[dict]:
    logger.info("ℹ️  K-Startup 핸들러 미구현")
    return []

def handler_daejeon_tp(source_cfg: dict) -> list[dict]:
    logger.info("ℹ️  대전TP 핸들러 미구현")
    return []

def handler_generic_crawl(source_cfg: dict) -> list[dict]:
    """
    범용 크롤링 핸들러 (미구현 소스 기본 처리).
    source_cfg에 url, pages 있으면 기본 크롤링 시도.
    """
    logger.info(f"ℹ️  {source_cfg.get('source')} 핸들러 미구현 → 건너뜀")
    return []


# 소스명 → 핸들러 함수 매핑 테이블
HANDLER_MAP = {
    "기업마당":       handler_bizinfo,
    "교육부_사업공고": handler_moe,
    "교육부_공지사항": handler_moe,
    "IRIS":           handler_iris,
    "NRF":            handler_nrf,
    "K-Startup":      handler_kstartup,
    "대전TP":         handler_daejeon_tp,
    "충남경제진흥원":  handler_generic_crawl,
}


# ──────────────────────────────────────────────
# [11] 크로스데이 중복 제거
# ──────────────────────────────────────────────
def load_recent_seen_names(days: int = 7) -> set:
    """
    최근 N일간 archive에서 수집된 사업명 set 반환.
    오늘 수집분과 중복 제거용으로 사용.
    """
    seen = set()
    for archive_file in sorted(ARCHIVE_DIR.glob("*.json"), reverse=True)[:days]:
        try:
            with open(archive_file, encoding="utf-8") as f:
                data = json.load(f)
            for item in data.get("items", []):
                name = item.get("사업명", "").strip()
                if name:
                    seen.add(name)
        except Exception as e:
            logger.debug(f"archive 로드 오류 ({archive_file.name}): {e}")
    return seen


# ──────────────────────────────────────────────
# [12] 데이터 정제
# ──────────────────────────────────────────────
def build_dataframe(all_items: list[dict]) -> pd.DataFrame:
    COLS = ["소스", "사업명", "주관부처", "마감일", "상세링크"]

    if not all_items:
        logger.warning("⚠️  수집 결과 없음")
        return pd.DataFrame(columns=COLS + ["수집일시"])

    df = pd.DataFrame(all_items).reindex(columns=COLS)

    # 빈 사업명 제거
    df = df[df["사업명"].str.strip().astype(bool)]

    # 동일 실행 내 중복 제거 (사업명+링크 기준)
    before = len(df)
    df["_key"] = df["사업명"].str.strip() + "|" + df["상세링크"].fillna("").str.strip()
    df = df.drop_duplicates(subset=["_key"]).drop(columns=["_key"])
    logger.info(f"🔄 중복 제거: {before - len(df)}건 제거 → {len(df)}건")

    # 마감일 정렬 (빈 값 뒤로)
    df["_sort"] = df["마감일"].replace("", "9999-99-99")
    df = df.sort_values("_sort").drop(columns=["_sort"]).reset_index(drop=True)

    df["수집일시"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    logger.info(f"✅ 최종: {len(df)}건")
    return df


# ──────────────────────────────────────────────
# [13] 저장 — /data + /archive
# ──────────────────────────────────────────────
def save_all(df: pd.DataFrame) -> dict:
    """
    저장 구조:
      /data/latest.json   ← 대시보드 fetch()용
      /data/latest.csv    ← CSV 다운로드용
      /archive/YYYY-MM-DD.json  ← 날짜별 누적
    """
    today = datetime.now().strftime("%Y-%m-%d")
    records = df.to_dict(orient="records") if not df.empty else []
    paths = {}

    # ── 공통 JSON 구조 ──
    json_body = {
        "generated_at": datetime.now().isoformat(),
        "date": today,
        "total": len(records),
        "sources": df["소스"].value_counts().to_dict() if not df.empty else {},
        "items": records,
    }

    # ── /data/latest.json ──
    latest_json = DATA_DIR / "latest.json"
    with open(latest_json, "w", encoding="utf-8") as f:
        json.dump(json_body, f, ensure_ascii=False, indent=2)
    paths["latest_json"] = str(latest_json)
    logger.info(f"💾 latest.json: {len(records)}건")

    # ── /data/latest.csv ──
    latest_csv = DATA_DIR / "latest.csv"
    df.to_csv(latest_csv, index=False, encoding="utf-8-sig")
    paths["latest_csv"] = str(latest_csv)
    logger.info(f"💾 latest.csv")

    # ── /archive/YYYY-MM-DD.json ──
    archive_file = ARCHIVE_DIR / f"{today}.json"
    if archive_file.exists():
        # 기존 archive와 병합 (같은 날 여러 번 실행 시)
        try:
            with open(archive_file, encoding="utf-8") as f:
                existing = json.load(f)
            existing_names = {i["사업명"] for i in existing.get("items", [])}
            new_items = [r for r in records if r["사업명"] not in existing_names]
            merged = existing.get("items", []) + new_items
            json_body["items"] = merged
            json_body["total"] = len(merged)
            logger.info(f"📁 archive 병합: 기존 {len(existing.get('items',[]))}건 + 신규 {len(new_items)}건")
        except Exception:
            pass

    with open(archive_file, "w", encoding="utf-8") as f:
        json.dump(json_body, f, ensure_ascii=False, indent=2)
    paths["archive"] = str(archive_file)
    logger.info(f"📁 archive/{today}.json: {json_body['total']}건")

    # ── archive 목록 메타 업데이트 ──
    _update_archive_index()

    return paths


def _update_archive_index():
    """
    /data/archive_index.json 업데이트.
    대시보드에서 과거 날짜 목록을 fetch()할 때 사용.
    """
    files = sorted(ARCHIVE_DIR.glob("*.json"), reverse=True)
    index = []
    for f in files:
        try:
            with open(f, encoding="utf-8") as fp:
                d = json.load(fp)
            index.append({
                "date": d.get("date", f.stem),
                "total": d.get("total", 0),
                "sources": d.get("sources", {}),
                "file": f"archive/{f.name}",
            })
        except Exception:
            pass

    index_path = DATA_DIR / "archive_index.json"
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump({"updated_at": datetime.now().isoformat(), "archives": index}, f,
                  ensure_ascii=False, indent=2)
    logger.info(f"📋 archive_index.json: {len(index)}개 날짜")


# ──────────────────────────────────────────────
# [14] 슬랙 알림
# ──────────────────────────────────────────────
def send_slack(df: pd.DataFrame):
    if not Config.SLACK_WEBHOOK_URL:
        return
    today = datetime.now().strftime("%Y년 %m월 %d일")
    sources_txt = " · ".join(
        f"{k}: {v}건" for k, v in df["소스"].value_counts().items()
    ) if not df.empty else "없음"

    try:
        requests.post(Config.SLACK_WEBHOOK_URL, json={
            "blocks": [
                {"type": "header",
                 "text": {"type": "plain_text", "text": f"📡 공고 수집 완료 — {today}"}},
                {"type": "section",
                 "text": {"type": "mrkdwn",
                          "text": f"*전체 {len(df)}건*\n{sources_txt}"}},
            ]
        }, timeout=10)
        logger.info("💬 슬랙 알림 전송")
    except Exception as e:
        logger.warning(f"슬랙 오류 (무시): {e}")


# ──────────────────────────────────────────────
# [15] 메인
# ──────────────────────────────────────────────
def main():
    logger.info("=" * 60)
    logger.info("  정부지원사업 자동 수집 v3")
    logger.info(f"  실행: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    # ── 활성 소스 로드 ──
    sources = load_sources()
    if not sources:
        logger.error("❌ 활성 소스 없음. sources.json 확인")
        sys.exit(1)

    # ── 소스별 수집 ──
    all_items = []
    for src_cfg in sources:
        src_name = src_cfg.get("source", "")
        handler = HANDLER_MAP.get(src_name, handler_generic_crawl)
        try:
            items = handler(src_cfg)
            all_items.extend(items)
        except Exception as e:
            logger.error(f"❌ {src_name} 수집 중 오류: {e}")

    # ── 정제 ──
    df = build_dataframe(all_items)

    # ── 저장 ──
    paths = save_all(df)

    # ── 결과 요약 ──
    logger.info("\n📊 소스별 수집 현황:")
    if not df.empty:
        for src, cnt in df["소스"].value_counts().items():
            logger.info(f"   {src:20s}: {cnt:4d}건")
    logger.info(f"\n   저장 경로: {list(paths.keys())}")

    # ── 슬랙 ──
    send_slack(df)

    logger.info("\n" + "=" * 60)
    logger.info(f"  완료! 총 {len(df)}건")
    logger.info("=" * 60)
    return df


if __name__ == "__main__":
    main()
