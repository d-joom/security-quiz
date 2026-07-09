"""
Google Sheets에서 문제 데이터를 가져와 questions_bank.json에 병합하는 스크립트
시트 구조: 열1=답, 열2=문제
사용법: python fetch_sheets.py
"""

import csv
import hashlib
import io
import json
import re
import urllib.request
import urllib.parse

SPREADSHEET_ID = "1Af8diBgdAGmSDN4nc2uHrlEPjx2j5W5hcOh8o7iEqvY"
SOURCE_LABEL = "요약시트"

SUBJECT_MAP = {
    1: "시스템보안",
    2: "네트워크보안",
    3: "어플리케이션보안",
    4: "정보보안일반",
    5: "보안관리및법규",
}

# (시트명, 과목번호, 유형)
SHEET_NAMES = [
    ("단답형(1)", 1, "단답형"),
    ("단답형(2)", 2, "단답형"),
    ("단답형(3)", 3, "단답형"),
    ("단답형(4)", 4, "단답형"),
    ("단답형(5)", 5, "단답형"),
    ("서술형(1)", 1, "서술형"),
    ("서술형(2)", 2, "서술형"),
    ("서술형(3)", 3, "서술형"),
    ("서술형(4)", 4, "서술형"),
    ("서술형(5)", 5, "서술형"),
]

OUTPUT_FILE = "questions_bank.json"


def fetch_csv(sheet_name: str) -> str:
    encoded = urllib.parse.quote(sheet_name, safe="", encoding="utf-8")
    url = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv&sheet={encoded}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8")


def content_hash(raw: str) -> str:
    return hashlib.md5(raw.strip().encode()).hexdigest()


def parse_csv(raw_csv: str, sheet_name: str, subject_num: int, q_type: str) -> list[dict]:
    subject = SUBJECT_MAP[subject_num]
    reader = csv.reader(io.StringIO(raw_csv))
    rows = list(reader)

    # 첫 행이 헤더인 경우 건너뜀
    start = 1 if rows and rows[0] and rows[0][0].strip() in ("답", "answer", "Answer") else 0

    questions = []
    for i, row in enumerate(rows[start:], start=1):
        if len(row) < 2:
            continue
        answer = row[0].strip()
        question = row[1].strip()
        if not answer or not question:
            continue

        q_id = f"sheet_{q_type[0]}_{subject_num}_{i:03d}"

        keywords = [kw.strip() for kw in re.split(r"\n|\(\d+\)\s*", answer) if kw.strip()]
        keywords = [k for k in keywords if k and len(k) < 60][:5]

        questions.append({
            "id": q_id,
            "source": SOURCE_LABEL,
            "exam": subject,
            "subject_num": subject_num,
            "number": i,
            "type": q_type,
            "points": 5 if q_type == "서술형" else 3,
            "question": question,
            "answer": answer,
            "keywords": keywords,
            "commentary": "",
            "difficulty": "",
            "sub_questions": None,
        })
    return questions


def load_existing() -> list[dict]:
    try:
        with open(OUTPUT_FILE, "rb") as f:
            return json.loads(f.read().decode("utf-8"))
    except FileNotFoundError:
        return []


def save(data: list[dict]):
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    with open("data.js", "w", encoding="utf-8") as f:
        f.write("window.QUESTIONS_DATA = ")
        json.dump(data, f, ensure_ascii=False)
        f.write(";")


def main():
    existing = load_existing()

    # 기존 요약시트 항목 제거 후 재수집 (업데이트 반영)
    base = [q for q in existing if q.get("source") != SOURCE_LABEL and not q.get("id", "").startswith("sheet_")]
    base_questions = {q["question"].strip() for q in base}

    seen_hashes: set[str] = set()
    new_questions: list[dict] = []

    for sheet_name, subject_num, q_type in SHEET_NAMES:
        print(f"  [{sheet_name}] 가져오는 중...", end=" ", flush=True)
        try:
            raw = fetch_csv(sheet_name)
            h = content_hash(raw)

            if h in seen_hashes:
                print("스킵 (미작성 시트)")
                continue
            seen_hashes.add(h)

            parsed = parse_csv(raw, sheet_name, subject_num, q_type)

            added = []
            seen_in_batch = {q["question"].strip() for q in new_questions}
            for q in parsed:
                key = q["question"].strip()
                if key in base_questions or key in seen_in_batch:
                    continue
                added.append(q)

            new_questions.extend(added)
            print(f"{len(parsed)}개 파싱, {len(added)}개 추가")

        except Exception as e:
            print(f"실패 ({e})")

    merged = base + new_questions
    save(merged)
    print(f"\n완료: 요약시트 {len(new_questions)}개 -> 총 {len(merged)}개")


if __name__ == "__main__":
    main()
