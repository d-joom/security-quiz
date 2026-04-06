#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
정보보안기사 실기 문제은행 파서
- 기출 TXT 파일 파싱 (18회~28회)
- 실기 단답형 151제 파싱
- 요약정리 PDF에서 추가 문제 생성
"""

import re
import json
from pathlib import Path

BASE_DIR = Path(r'C:\development\security-quiz')

# ─────────────────────────────────────────────
# 공통 유틸
# ─────────────────────────────────────────────

def clean_text(text):
    text = text.replace('　', ' ')
    text = text.replace('\u200b', '')
    text = text.replace('\u00a0', ' ')
    text = text.replace('\ufeff', '')
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def get_points(q_type):
    return {'단답형': 3, '서술형': 12, '실무형': 16}.get(q_type, 3)

def extract_keywords(answer, q_type):
    """답안에서 자동채점용 키워드 추출"""
    keywords = []
    if not answer:
        return keywords
    # 쉼표/슬래시로 구분된 항목들 추출
    raw = re.split(r'[,，/]', answer)
    for kw in raw:
        kw = re.sub(r'\(.*?\)', '', kw)   # 괄호 내용 제거
        kw = re.sub(r'\s+', ' ', kw).strip()
        if kw and 1 <= len(kw) <= 60:
            keywords.append(kw)
    return keywords

# ─────────────────────────────────────────────
# 기출 파일 파서
# ─────────────────────────────────────────────

def parse_gichu(filepath, exam_name):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    content = clean_text(content)

    # Q&A 섹션: (답)이 포함된 마지막 [단답형] 위치
    last_qa_pos = -1
    for m in re.finditer(r'\[단답형\]', content):
        chunk = content[m.start(): m.start() + 5000]
        if '(답)' in chunk:
            last_qa_pos = m.start()

    if last_qa_pos == -1:
        print(f"  ⚠ Q&A 섹션 없음: {filepath.name}")
        return []

    qa_content = content[last_qa_pos:]
    questions = []

    # 섹션 분리
    section_re = re.compile(r'\[(단답형|서술형|실무형)\]')
    parts = section_re.split(qa_content)

    current_type = None
    for part in parts:
        if part in ('단답형', '서술형', '실무형'):
            current_type = part
        elif current_type and part.strip():
            qs = _parse_section(part, current_type, exam_name)
            questions.extend(qs)

    return questions


def _parse_section(content, q_type, exam_name):
    questions = []

    # 문제 블록 분리: 줄 시작 "숫자. " 패턴
    blocks = re.split(r'\n(?=\d+\.\s)', '\n' + content)

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        m = re.match(r'^(\d+)\.\s+(.*)', block, re.DOTALL)
        if not m:
            continue

        q_num = int(m.group(1))
        body = m.group(2).strip()

        # (답) 기준으로 문제/답 분리
        ans_split = re.split(r'\n?\(답\)\s*', body, maxsplit=1)
        if len(ans_split) < 2:
            continue

        q_text = ans_split[0].strip()
        ans_body = ans_split[1]

        # 답 / 해설 분리 (* 로 시작하는 줄)
        ans_lines, comm_lines = [], []
        in_comm = False
        for line in ans_body.split('\n'):
            s = line.strip()
            if s.startswith('*'):
                in_comm = True
            if in_comm:
                if s.startswith('*'):
                    comm_lines.append(s[1:].strip())
            else:
                ans_lines.append(line)

        answer = '\n'.join(ans_lines).strip()
        commentary = '\n'.join(comm_lines).strip()

        keywords = extract_keywords(answer, q_type) if q_type == '단답형' else []

        # 해설에서 핵심 키워드 추출 (서술형/실무형)
        if q_type in ('서술형', '실무형') and commentary:
            kw_matches = re.findall(r'핵심\s*키워드[는은:]\s*(.+?)(?:\n|$)', commentary)
            for km in kw_matches:
                for kw in re.split(r'[,，]', km):
                    kw = kw.strip()
                    if kw and len(kw) <= 60:
                        keywords.append(kw)

        # 실무형/서술형 소문항 처리
        sub_questions = _parse_sub_questions(q_text, answer, q_type)

        # 난이도 태그 추출 (해설에서)
        difficulty = ''
        if '신규' in commentary:
            difficulty = '신규'
        elif '기출' in commentary:
            difficulty = '기출'
        elif '교재' in commentary:
            difficulty = '교재'

        questions.append({
            'id': f'{exam_name}_{q_num}',
            'source': '기출',
            'exam': exam_name,
            'number': q_num,
            'type': q_type,
            'points': get_points(q_type),
            'question': q_text,
            'answer': answer,
            'keywords': keywords,
            'commentary': commentary,
            'difficulty': difficulty,
            'sub_questions': sub_questions or None,
        })

    return questions


def _parse_sub_questions(q_text, answer, q_type):
    """소문항 파싱 (N) 형식)"""
    if q_type not in ('서술형', '실무형'):
        return []

    sub_q_re = re.compile(r'(?:^|\n)(\d+)\)\s+(.+?)(?=\n\d+\)|\n\(답\)|$)', re.DOTALL)

    subs = {}
    for m in sub_q_re.finditer(q_text):
        num = int(m.group(1))
        subs[num] = {'number': num, 'question': m.group(2).strip(), 'answer': ''}

    # 답 매칭
    if subs:
        sub_a_re = re.compile(r'(?:^|\n)(\d+)\)\s+(.+?)(?=\n\d+\)|\n\*|$)', re.DOTALL)
        for m in sub_a_re.finditer(answer):
            num = int(m.group(1))
            if num in subs:
                subs[num]['answer'] = m.group(2).strip()

    return list(subs.values()) if subs else []


# ─────────────────────────────────────────────
# 151제 파서
# ─────────────────────────────────────────────

def parse_151(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    content = clean_text(content)
    questions = []

    blocks = re.split(r'-{20,}', content)

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        m = re.match(r'^(\d+)\.\s+(.*)', block, re.DOTALL)
        if not m:
            continue

        q_num = int(m.group(1))
        body = m.group(2).strip()

        ans_split = re.split(r'\n?\(답\)\s*', body, maxsplit=1)
        if len(ans_split) < 2:
            continue

        q_text = ans_split[0].strip()
        answer = ans_split[1].strip()
        keywords = extract_keywords(answer, '단답형')

        questions.append({
            'id': f'151제_{q_num:03d}',
            'source': '151제',
            'exam': '단답형151제',
            'number': q_num,
            'type': '단답형',
            'points': 3,
            'question': q_text,
            'answer': answer,
            'keywords': keywords,
            'commentary': '',
            'difficulty': '',
            'sub_questions': None,
        })

    return questions


# ─────────────────────────────────────────────
# 요약정리 PDF 파서
# ─────────────────────────────────────────────

GENERIC_TERMS = {
    '일반', '정의', '개요', '특징', '목적', '종류', '방법', '원리', '개념', '기본',
    '요소', '구성', '활용', '기준', '원칙', '유형', '분류', '현황', '소개', '설명',
    '관련', '기타', '추가', '참고', '정리', '요약', '내용', '사항', '조치', '조건',
    '표준', '절차', '과정', '단계', '방안', '대응', '적용', '수행', '실시', '확인',
    'BIA', '일반적'
}

def parse_pdf_summary(filepath):
    try:
        import pdfplumber
    except ImportError:
        print("  ⚠ pdfplumber 미설치")
        return []

    questions = []
    q_num = 1

    with pdfplumber.open(str(filepath)) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue

            lines = text.split('\n')
            i = 0
            while i < len(lines):
                line = lines[i].strip()

                # "term ○ definition" 패턴
                m = re.match(r'^(.+?)\s*○\s*(.+)$', line)
                if m:
                    term = m.group(1).strip()
                    defn = m.group(2).strip()

                    # 연속 줄 추가 (다음 ○ 또는 빈 줄까지)
                    j = i + 1
                    while j < len(lines):
                        nl = lines[j].strip()
                        if not nl or '○' in nl or re.match(r'^.+\s*○', nl):
                            break
                        defn += ' ' + nl
                        j += 1

                    defn = defn.strip()
                    term_clean = re.sub(r'\s+', ' ', term).strip()

                    # 유효성 검사
                    valid = (
                        2 <= len(term_clean) <= 30
                        and len(defn) >= 15
                        and term_clean not in GENERIC_TERMS
                        and not term_clean.isdigit()
                        and not re.match(r'^[\[\]①②③④⑤]', term_clean)
                        and not re.match(r'^\d+\.', term_clean)
                        and not re.match(r'^페이지', term_clean)
                    )

                    if valid:
                        q_text = f"다음 설명에 해당하는 정보보안 용어를 쓰시오.\n\n{defn}"
                        questions.append({
                            'id': f'요약_{q_num:04d}',
                            'source': '요약정리',
                            'exam': '요약정리',
                            'number': q_num,
                            'type': '단답형',
                            'points': 3,
                            'question': q_text,
                            'answer': term_clean,
                            'keywords': [term_clean],
                            'commentary': '',
                            'difficulty': '',
                            'sub_questions': None,
                        })
                        q_num += 1

                i += 1

    return questions


# ─────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────

def main():
    all_questions = []
    seen_ids = set()

    def add_questions(qs):
        added = 0
        for q in qs:
            if q['id'] not in seen_ids:
                seen_ids.add(q['id'])
                all_questions.append(q)
                added += 1
        return added

    # 1. 기출 파일 (18~28회)
    exam_files = sorted(BASE_DIR.glob('[0-9]*회.txt'))
    for f in exam_files:
        exam_name = f.stem
        qs = parse_gichu(f, exam_name)
        n = add_questions(qs)
        print(f'기출 {exam_name}: {n}문제')

    # 2. 151제
    f151 = BASE_DIR / '실기단답형_151제.txt'
    if f151.exists():
        qs = parse_151(f151)
        n = add_questions(qs)
        print(f'단답형 151제: {n}문제')

    # 3. 요약정리 PDF
    pdf_path = BASE_DIR / '정보보안기사 요약 정리.pdf'
    if pdf_path.exists():
        qs = parse_pdf_summary(pdf_path)
        n = add_questions(qs)
        print(f'요약정리 PDF: {n}문제')

    # JSON 저장
    out_json = BASE_DIR / 'questions_bank.json'
    with open(out_json, 'w', encoding='utf-8') as f:
        json.dump(all_questions, f, ensure_ascii=False, indent=2)

    # data.js 저장 (브라우저 file:// 직접 열기용)
    out_js = BASE_DIR / 'data.js'
    json_str = json.dumps(all_questions, ensure_ascii=False)
    with open(out_js, 'w', encoding='utf-8') as f:
        f.write(f'window.QUESTIONS_DATA = {json_str};\n')

    # 통계
    by_source = {}
    by_type = {}
    for q in all_questions:
        by_source[q['source']] = by_source.get(q['source'], 0) + 1
        by_type[q['type']] = by_type.get(q['type'], 0) + 1

    print(f'\n총 {len(all_questions)}문제 → {out_json}')
    print(f'data.js 생성 → {out_js}')
    print('출처:', by_source)
    print('유형:', by_type)


if __name__ == '__main__':
    main()
