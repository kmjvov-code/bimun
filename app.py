"""
비문 신청서 시스템 (Flask)
- PC 상담/작업용 2페이지 구조
- 저장 데이터 중심
- 저장 파일: saved_data/*.json, saved_data/_index.json
"""

import os
import json
import uuid
import re
import base64
from datetime import datetime
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 저장 위치
# - 윈도우/NAS 사용 시: 기본값은 Z:\CS\claude_code\bimun_data
# - 다른 경로를 쓰려면 환경변수 BIMUN_SAVE_ROOT를 설정하거나 아래 기본 경로를 바꾸면 됩니다.
DEFAULT_SAVE_ROOT = r"Z:\CS\claude_code\bimun_data" if os.name == "nt" else os.path.join(BASE_DIR, "saved_data")
SAVE_ROOT = os.environ.get("BIMUN_SAVE_ROOT", DEFAULT_SAVE_ROOT)
DATA_DIR = os.path.join(SAVE_ROOT, "data")
PREVIEW_DIR = os.path.join(SAVE_ROOT, "preview")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(PREVIEW_DIR, exist_ok=True)
INDEX_FILE = os.path.join(DATA_DIR, "_index.json")
# 구버전 호환용 이름
SAVE_DIR = DATA_DIR

CATALOG = {
    "매장묘": ["단장", "쌍분"],
    "단납/평장1기": ["기본"],
    "쌍납/평장부부A": ["기본"],
    "송수재": ["개인", "부부"],
    "부부A": ["기본"],
    "납골정": ["기본"],
    "평장부부B": ["기본", "1번", "2번", "3번", "4번"],
    "평장1기P": ["기본"],
    "4기": ["A", "B", "C", "P", "R"],
    "평장부부P": ["기본"],
    "평장4기": ["기본"],
    "평장4기P": ["기본"],
    "8기": ["기본"],
    "다기형": ["12A", "20기", "30기"],
    "12기B": ["기본"],
    "24기": ["기본"],
}

PRICE_GROUPS = {
    "A": {"big_korean": 8000, "big_chinese": 12000, "small_korean": 4000, "small_chinese": 6000, "stone_photo_price": 120000},
    "B": {"big_korean": 10000, "big_chinese": 15000, "small_korean": 5000, "small_chinese": 7500, "stone_photo_price": 120000},
    "C": {"big_korean": 16000, "big_chinese": 24000, "small_korean": 8000, "small_chinese": 12000, "stone_photo_price": 120000},
}

STONE_PHOTO_CATEGORIES = ["단납/평장1기", "송수재", "평장부부B", "평장부부P", "평장4기"]
STONE_PHOTO_COMBOS = {
    ("단납/평장1기", "기본"), ("송수재", "부부"),
    ("평장부부B", "기본"), ("평장부부P", "기본"), ("평장4기", "기본"),
}
STAFF_LIST = ["", "이성규", "이재민", "진승현", "우승협", "윤은영", "김애진", "김경란", "김민재", "김현", "임병현", "김동현", "박동석", "강세범", "배건호"]
STATUS_LIST = ["접수됨", "시안문자발송", "고객확인완료", "완료"]

# 기존 가격군 기준 유지용 간단 룰
RULES = {}
for c, subs in CATALOG.items():
    for s in subs:
        # 글자당 금액 그룹
        # A: 대부분 상품 (大 한글 8,000 / 한자 12,000, 小 한글 4,000 / 한자 6,000)
        # B: 매장묘, 평장부부B 1/2/3/4 (大 10,000/15,000, 小 5,000/7,500)
        # C: 4기P, 8기, 다기형, 12기B, 24기 (大 16,000/24,000, 小 8,000/12,000)
        group = "A"
        if c == "매장묘" or (c == "평장부부B" and s in ["1번", "2번", "3번", "4번"]):
            group = "B"
        if c in ["8기", "다기형", "12기B", "24기"] or (c == "4기" and s == "P"):
            group = "C"
        slots = 1
        if c in ["쌍납/평장부부A", "송수재", "부부A", "납골정", "평장부부B", "평장부부P"] or (c == "매장묘" and s == "쌍분"):
            slots = 2
        if c in ["4기", "평장4기", "평장4기P"]:
            slots = 4
        if c in ["8기", "다기형", "12기B", "24기"]:
            slots = 5
        front_only_hanja = c in ["단납/평장1기", "쌍납/평장부부A", "송수재", "평장1기P"]
        RULES[f"{c}||{s}"] = {
            "price_group": group,
            "slots": slots,
            "has_side": (c == "매장묘") or (c == "평장부부B" and s == "2번"),
            "stone_photo": c in STONE_PHOTO_CATEGORIES,
            "front_style": "maejang" if (c == "매장묘" or (c == "평장부부B" and s == "2번")) else "standard",
            # 한자 표현 가능 범위: 계산용이 아니라 시안 표현 방식 제어용
            "front_hanja": True,
            "side_hanja": (not front_only_hanja) and ((c == "매장묘") or (c == "평장부부B" and s == "2번")),
            "back_hanja": not front_only_hanja,
            "needs_orientation": (c == "4기" and s == "B"),
            "family_phrase": c in ["8기", "12기B", "24기", "다기형"],
        }


def safe_filename_text(text):
    """Windows/NAS 파일명에 쓸 수 없는 문자 제거."""
    return re.sub(r'[\\/:*?"<>|]', '', str(text or '').strip())


def get_religion_name(data):
    """종교마크가 없으면 무교로 저장명 표시."""
    raw = str(data.get("religion_mark") or "").strip()
    if not raw:
        return "무교"
    mapping = {
        "buddhism": "불교", "불교": "불교",
        "christian": "기독교", "기독교": "기독교",
        "catholic": "천주교", "천주교": "천주교",
        "故": "무교",
        "none": "무교", "없음": "무교", "무교": "무교",
    }
    return mapping.get(raw, raw)


def make_storage_basename(data):
    """#계약번호계약자명(대분류_소분류_종교) 형태."""
    contract_no = safe_filename_text(data.get("contract_no") or "00000")
    contractor = safe_filename_text(data.get("contractor") or "이름없음")
    category = safe_filename_text(data.get("category") or "대분류")
    subcategory = safe_filename_text(data.get("subcategory") or "소분류")
    religion = safe_filename_text(get_religion_name(data))
    return f"#{contract_no}{contractor}({category}_{subcategory}_{religion})"


def unique_path(directory, basename, ext, current_filename=None):
    """같은 이름이 있으면 _HHMMSS를 붙여 덮어쓰기 방지. 현재 파일은 덮어쓰기 허용."""
    filename = f"{basename}{ext}"
    path = os.path.join(directory, filename)
    if current_filename and filename == current_filename:
        return path, filename
    if not os.path.exists(path):
        return path, filename
    stamp = datetime.now().strftime("_%H%M%S")
    filename = f"{basename}{stamp}{ext}"
    return os.path.join(directory, filename), filename


def _read_index():
    if not os.path.exists(INDEX_FILE):
        return []
    try:
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _write_index(items):
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def count_chars(text):
    return len(str(text or "").replace(" ", "").replace("\n", "").replace("\r", ""))


def _is_hanja(ch):
    cp = ord(ch)
    return (0x4E00 <= cp <= 0x9FFF) or (0x3400 <= cp <= 0x4DBF) or (0xF900 <= cp <= 0xFAFF)


def count_chars_split(text):
    """Returns (hanja_count, other_count) for non-whitespace chars."""
    t = str(text or "").replace(" ", "").replace("\n", "").replace("\r", "")
    hanja = sum(1 for c in t if _is_hanja(c))
    return hanja, len(t) - hanja


def _bongwan_suffix(bongwan, hanja_suf, kor_suf):
    """Returns suffix count (0 if already appended)."""
    t = str(bongwan or "").strip()
    if not t:
        return 0
    if t.endswith(hanja_suf) or t.endswith(kor_suf):
        return 0
    return 1  # always 1 char suffix


def get_rule(category, subcategory):
    return RULES.get(f"{category}||{subcategory}") or RULES["매장묘||단장"]


def calc_summary(form):
    category = form.get("category", "매장묘")
    subcategory = form.get("subcategory", "단장")
    rule = get_rule(category, subcategory)
    pg = PRICE_GROUPS[rule["price_group"]]

    # ===== 24기 전용 가격 로직 =====
    # 요청 기준:
    # - 大: 가족지묘 문구(~지묘) = 16,000원
    # - 中: 망자명 + 세례명 + 고인별 종교마크 = 8,000원
    # - 小: 망일 = 4,000원
    # 다른 상품 계산 로직에 영향 없도록 24기에서만 조기 return 한다.
    if category == "24기":
        big_unit = 16000
        mid_unit = 8000
        small_unit = 4000

        big_cnt = 0
        mid_cnt = 0
        small_cnt = 0

        def add_count(group, text, extra=0):
            nonlocal big_cnt, mid_cnt, small_cnt
            cnt = count_chars(text) + int(extra or 0)
            if group == "big":
                big_cnt += cnt
            elif group == "mid":
                mid_cnt += cnt
            else:
                small_cnt += cnt

        # 大: "김해김씨 가족지묘" 계열. 본관 뒤 씨/氏가 없으면 1자 추가, 가족지묘 4자 추가.
        fb = str(form.get("family_bongwan") or "").strip()
        if fb:
            add_count("big", fb)
            if not (fb.endswith("씨") or fb.endswith("氏")):
                add_count("big", "", extra=1)
            add_count("big", "가족지묘")

        try:
            slot_count_24 = int(form.get("slot_count") or rule.get("slots") or 5)
        except Exception:
            slot_count_24 = 5
        slot_count_24 = max(1, min(slot_count_24, 10))

        for i in range(1, slot_count_24 + 1):
            # 中: 망자명 + 세례명 + 고인별 종교마크
            add_count("mid", form.get(f"f{i}_name"))
            add_count("mid", form.get(f"f{i}_baptism"))
            rel = str(
                form.get(f"f{i}_religion_mark")
                or form.get(f"f{i}_religion")
                or form.get(f"religion_mark_{i}")
                or ""
            ).strip()
            if rel not in ("", "없음", "none", "무교"):
                add_count("mid", "", extra=1)

            # 小: 망일. 사망 표현(졸/선종/소천)은 날짜가 있을 때만 함께 계산.
            death = form.get(f"f{i}_death")
            dtype = form.get(f"f{i}_death_type", "졸")
            if death:
                add_count("small", death)
                if (dtype or "졸") != "없음":
                    add_count("small", dtype or "졸")

        big_amt = big_cnt * big_unit
        mid_amt = mid_cnt * mid_unit
        small_amt = small_cnt * small_unit
        total = big_amt + mid_amt + small_amt

        return {
            "big_cnt": big_cnt, "big_amt": big_amt,
            "big_korean_cnt": big_cnt, "big_korean_unit": big_unit, "big_korean_amt": big_amt,
            "big_hanja_cnt": 0, "big_hanja_unit": big_unit, "big_hanja_amt": 0,

            "mid_cnt": mid_cnt, "mid_amt": mid_amt,
            "mid_korean_cnt": mid_cnt, "mid_korean_unit": mid_unit, "mid_korean_amt": mid_amt,
            "mid_hanja_cnt": 0, "mid_hanja_unit": mid_unit, "mid_hanja_amt": 0,

            "small_cnt": small_cnt, "small_amt": small_amt,
            "small_korean_cnt": small_cnt, "small_korean_unit": small_unit, "small_korean_amt": small_amt,
            "small_hanja_cnt": 0, "small_hanja_unit": small_unit, "small_hanja_amt": 0,

            "side_cnt": 0, "side_amt": 0,
            "back_cnt": 0, "back_amt": 0,
            "stone_enabled": False,
            "stone_added": False,
            "stone_count": 0,
            "stone_unit": 0,
            "stone_amt": 0,
            "total": total,
            "price_group": "24_CUSTOM",
            "has_side": False,
        }

    # ===== 4기P 전용 가격 로직 =====
    # 가격 기준:
    # - 1,2 고인 이름/세례명/종교마크 = 大 (한글 16,000 / 한자 24,000)
    # - 1,2 망일 및 자손 = 中 (한글 8,000 / 한자 12,000)
    # - 3,4 고인 이름/세례명/종교마크 = 中 (한글 8,000 / 한자 12,000)
    # - 3,4 망일 = 小 (한글 4,000 / 한자 6,000)
    if category == "4기" and subcategory == "P":
        big_k_unit, big_h_unit = 16000, 24000
        mid_k_unit, mid_h_unit = 8000, 12000
        small_k_unit, small_h_unit = 4000, 6000

        big_k = big_h = 0
        mid_k = mid_h = 0
        small_k = small_h = 0

        def add_to_group(group, text, extra_other=0):
            nonlocal big_k, big_h, mid_k, mid_h, small_k, small_h
            h, o = count_chars_split(text)
            o += extra_other
            if group == "big":
                big_h += h
                big_k += o
            elif group == "mid":
                mid_h += h
                mid_k += o
            else:
                small_h += h
                small_k += o

        def date_text_for(i):
            parts = []
            # 4기P 가격 설명은 '망일' 기준이지만, 생년월일을 입력한 경우 누락 방지를 위해 날짜 계열로 함께 계산
            birth = form.get(f"f{i}_birth")
            death = form.get(f"f{i}_death")
            btype = form.get(f"f{i}_birth_type", "생")
            dtype = form.get(f"f{i}_death_type", "졸")
            if birth:
                parts.append(str(birth))
                if btype != "없음":
                    parts.append(str(btype))
            if death:
                parts.append(str(death))
                if (dtype or "졸") != "없음":
                    parts.append(str(dtype or "졸"))
            return "".join(parts)

        def has_religion_for(i):
            # 고인별 종교마크가 있으면 우선 사용하고, 없으면 전체 종교마크 사용
            val = str(form.get(f"f{i}_religion_mark") or form.get(f"f{i}_religion") or "").strip()
            if not val:
                val = str(form.get("religion_mark") or "").strip()
            return val not in ("", "없음", "none", "무교")

        # 1,2 고인: 이름/세례명/종교마크 = 大, 날짜 = 中
        for i in [1, 2]:
            add_to_group("big", form.get(f"f{i}_name"))
            add_to_group("big", form.get(f"f{i}_baptism"))
            add_to_group("mid", date_text_for(i))

        # 3,4 고인: 이름/세례명/종교마크 = 中, 날짜 = 小
        for i in [3, 4]:
            add_to_group("mid", form.get(f"f{i}_name"))
            add_to_group("mid", form.get(f"f{i}_baptism"))
            add_to_group("small", date_text_for(i))

        # 고인별 종교마크는 위치와 관계없이 전부 大 1자로 계산
        # 고인별 선택값이 없고 전체 종교마크만 있는 경우도 기존처럼 고인별 표시되는 구조면 각 고인 1자씩 계산
        for i in [1, 2, 3, 4]:
            if has_religion_for(i):
                add_to_group("big", "", extra_other=1)

        # 자손 = 中
        for key, prefix_len in [
            ("son_text", 1), ("daughter_in_law_text", 2), ("grandson_text", 1),
            ("daughter_text", 1), ("son_in_law_text", 2), ("maternal_grandchild_text", 2),
        ]:
            if form.get(key):
                add_to_group("mid", form.get(key), extra_other=prefix_len)
        add_to_group("mid", form.get("etc_text"))

        big_k_amt = big_k * big_k_unit
        big_h_amt = big_h * big_h_unit
        mid_k_amt = mid_k * mid_k_unit
        mid_h_amt = mid_h * mid_h_unit
        small_k_amt = small_k * small_k_unit
        small_h_amt = small_h * small_h_unit

        big_cnt = big_k + big_h
        mid_cnt = mid_k + mid_h
        small_cnt = small_k + small_h

        big_amt = big_k_amt + big_h_amt
        mid_amt = mid_k_amt + mid_h_amt
        small_amt = small_k_amt + small_h_amt
        total = big_amt + mid_amt + small_amt

        return {
            "big_cnt": big_cnt, "big_amt": big_amt,
            "big_korean_cnt": big_k, "big_korean_unit": big_k_unit, "big_korean_amt": big_k_amt,
            "big_hanja_cnt": big_h, "big_hanja_unit": big_h_unit, "big_hanja_amt": big_h_amt,

            "mid_cnt": mid_cnt, "mid_amt": mid_amt,
            "mid_korean_cnt": mid_k, "mid_korean_unit": mid_k_unit, "mid_korean_amt": mid_k_amt,
            "mid_hanja_cnt": mid_h, "mid_hanja_unit": mid_h_unit, "mid_hanja_amt": mid_h_amt,

            "small_cnt": small_cnt, "small_amt": small_amt,
            "small_korean_cnt": small_k, "small_korean_unit": small_k_unit, "small_korean_amt": small_k_amt,
            "small_hanja_cnt": small_h, "small_hanja_unit": small_h_unit, "small_hanja_amt": small_h_amt,

            "side_cnt": 0, "side_amt": 0,
            "back_cnt": 0, "back_amt": 0,
            "stone_enabled": False,
            "stone_added": False,
            "stone_count": 0,
            "stone_unit": 0,
            "stone_amt": 0,
            "total": total,
            "price_group": "4기P_CUSTOM",
            "has_side": False,
        }


    bk_u = pg["big_korean"]
    bh_u = pg["big_chinese"]
    sk_u = pg["small_korean"]
    sh_u = pg["small_chinese"]

    # Separate hanja vs other (Korean/numbers) counts
    big_h, big_o = 0, 0
    small_h, small_o = 0, 0
    side_h, side_o = 0, 0
    back_h, back_o = 0, 0

    def _add_big(text, extra_other=0):
        nonlocal big_h, big_o
        h, o = count_chars_split(text)
        big_h += h; big_o += o + extra_other

    def _add_small(text, extra_other=0):
        nonlocal small_h, small_o
        h, o = count_chars_split(text)
        small_h += h; small_o += o + extra_other

    def _add_side(text, extra_other=0):
        nonlocal side_h, side_o
        h, o = count_chars_split(text)
        side_h += h; side_o += o + extra_other

    def _add_back(text, extra_other=0):
        nonlocal back_h, back_o
        h, o = count_chars_split(text)
        back_h += h; back_o += o + extra_other

    try:
        slot_count = int(form.get("slot_count") or 1)
    except Exception:
        slot_count = 1
    slot_count = max(1, min(slot_count, 10))

    if rule.get("front_style") == "maejang":
        # 문자별 자동감지 (탭 기준 강제 없음)
        if form.get("religion_mark"):
            big_o += 1

        jidmyo_val = str(form.get("jidmyo", "") or "")
        if jidmyo_val == "있음":        # 구형 데이터 호환
            big_o += 2
        elif jidmyo_val not in ("없음", ""):
            _add_big(jidmyo_val)

        male_title = str(form.get("male_title", "") or "")
        female_title = str(form.get("female_title", "") or "")
        m_bon = str(form.get("male_bongwan") or "")
        f_bon = str(form.get("female_bongwan") or "")

        if male_title and male_title != "없음":
            _add_big(male_title)
            _add_big(m_bon)
            ms = m_bon.strip()
            if ms and not ms.endswith("公") and not ms.endswith("공"):
                if _is_hanja(ms[-1]): big_h += 1
                else: big_o += 1
            _add_big(form.get("male_name"))
        if female_title and female_title != "없음":
            _add_big(female_title)
            _add_big(f_bon)
            fs = f_bon.strip()
            if fs and not fs.endswith("氏") and not fs.endswith("씨"):
                if _is_hanja(fs[-1]): big_h += 1
                else: big_o += 1
            _add_big(form.get("female_name"))
    else:
        # 전체 종교마크 + 고인별 종교마크 모두 큰글자 1자로 계산
        counted_religion = False
        if form.get("religion_mark") and str(form.get("religion_mark")).strip() not in ["", "없음", "none", "무교"]:
            big_o += 1
            counted_religion = True

        # 고인 이름 앞에 개별 종교마크가 들어가는 경우도 전부 大 1자로 계산
        try:
            _slot_count_for_rel = int(form.get("slot_count") or rule.get("slots") or 1)
        except Exception:
            _slot_count_for_rel = int(rule.get("slots") or 1)

        for _ri in range(1, _slot_count_for_rel + 1):
            _rel = (
                form.get(f"f{_ri}_religion_mark")
                or form.get(f"f{_ri}_religion")
                or form.get(f"religion_mark_{_ri}")
                or ""
            )
            if str(_rel).strip() not in ["", "없음", "none", "무교"]:
                big_o += 1

        _add_big(form.get("front_extra"))
        if rule.get("family_phrase") and form.get("family_bongwan"):
            h, o = count_chars_split(form.get("family_bongwan"))
            big_h += h; big_o += o + 5  # 고정 5자

        for i in range(1, slot_count + 1):
            # 가족지묘 계열(8기/다기형/12기B/24기)은 '가족지묘' 문구만 大,
            # 고인명/세례명/날짜는 小로 계산한다.
            if rule.get("family_phrase"):
                _add_small(form.get(f"f{i}_name"))
                _add_small(form.get(f"f{i}_baptism"))
            else:
                _add_big(form.get(f"f{i}_name"))
                _add_big(form.get(f"f{i}_baptism"))
            birth = form.get(f"f{i}_birth")
            death = form.get(f"f{i}_death")
            btype = form.get(f"f{i}_birth_type", "생")
            dtype = form.get(f"f{i}_death_type", "졸")
            if birth:
                _add_small(birth)
                if btype != "없음":
                    _add_small(btype)
            if death:
                _add_small(death)
                if (dtype or "졸") != "없음":
                    _add_small(dtype or "졸")

    if rule.get("has_side"):
        for prefix in ["s1", "s2"]:
            birth = form.get(f"{prefix}_birth")
            death = form.get(f"{prefix}_death")
            btype = form.get(f"{prefix}_birth_type", "생")
            dtype = form.get(f"{prefix}_death_type", "졸")
            if birth:
                _add_side(birth)
                if btype != "없음":
                    _add_side(btype)
            if death:
                _add_side(death)
                if (dtype or "졸") != "없음":
                    _add_side(dtype or "졸")

    for key, prefix_len in [
        ("son_text", 1), ("daughter_in_law_text", 2), ("grandson_text", 1),
        ("daughter_text", 1), ("son_in_law_text", 2), ("maternal_grandchild_text", 2),
    ]:
        if form.get(key):
            _add_back(form.get(key), extra_other=prefix_len)
    _add_back(form.get("etc_text"))

    stone_enabled = (category, subcategory) in STONE_PHOTO_COMBOS

    # 스톤포토는 고인별 선택 개수로 계산한다.
    # 예: 고인 2명 선택 → 120,000원 × 2 = 240,000원
    stone_count = 0
    if stone_enabled:
        try:
            stone_count = int(form.get("stone_photo_count") or 0)
        except Exception:
            stone_count = 0
        if stone_count <= 0:
            # 프론트에서 f1_stone_photo, f2_stone_photo ... 로 넘어오는 값 집계
            for i in range(1, slot_count + 1):
                if str(form.get(f"f{i}_stone_photo") or "") in ["yes", "추가", "있음", "on", "true", "1"]:
                    stone_count += 1
        # 구형 저장 데이터/구형 체크박스 호환
        if stone_count <= 0 and form.get("stone_photo") in ["yes", "추가", "있음"]:
            stone_count = 1
    stone_added = stone_enabled and stone_count > 0

    big_k_amt = big_o * bk_u;  big_h_amt = big_h * bh_u
    small_k_amt = small_o * sk_u; small_h_amt = small_h * sh_u
    side_k_amt = side_o * sk_u;  side_h_amt = side_h * sh_u
    back_k_amt = back_o * sk_u;  back_h_amt = back_h * sh_u

    big_cnt = big_o + big_h;    big_amt = big_k_amt + big_h_amt
    small_cnt = small_o + small_h; small_amt = small_k_amt + small_h_amt
    side_cnt = side_o + side_h;  side_amt = side_k_amt + side_h_amt
    back_cnt = back_o + back_h;  back_amt = back_k_amt + back_h_amt

    # 작은글자 통합 (전면소+측면+후면)
    all_small_k = small_o + side_o + back_o
    all_small_h = small_h + side_h + back_h
    all_small_k_amt = all_small_k * sk_u
    all_small_h_amt = all_small_h * sh_u

    stone_amt = pg["stone_photo_price"] * stone_count if stone_added else 0
    total = big_amt + small_amt + side_amt + back_amt + stone_amt

    return {
        "big_cnt": big_cnt, "big_amt": big_amt,
        "big_korean_cnt": big_o, "big_korean_unit": bk_u, "big_korean_amt": big_k_amt,
        "big_hanja_cnt": big_h, "big_hanja_unit": bh_u, "big_hanja_amt": big_h_amt,
        "small_cnt": small_cnt, "small_amt": small_amt,
        "small_korean_cnt": all_small_k, "small_korean_unit": sk_u, "small_korean_amt": all_small_k_amt,
        "small_hanja_cnt": all_small_h, "small_hanja_unit": sh_u, "small_hanja_amt": all_small_h_amt,
        "side_cnt": side_cnt, "side_amt": side_amt,
        "back_cnt": back_cnt, "back_amt": back_amt,
        "stone_enabled": stone_enabled,
        "stone_added": stone_added,
        "stone_count": stone_count,
        "stone_unit": pg["stone_photo_price"],
        "stone_amt": stone_amt,
        "total": total,
        "price_group": rule["price_group"],
        "has_side": rule["has_side"],
    }


def make_summary_item(data, item_id=None, created_at=None):
    summary = calc_summary(data)
    category = data.get("category", "")
    subcategory = data.get("subcategory", "")
    now = created_at or datetime.now().strftime("%Y-%m-%d %H:%M")
    return {
        "id": item_id or str(uuid.uuid4()),
        "created_at": now,
        "contract_no": data.get("contract_no", ""),
        "contractor": data.get("contractor", ""),
        "phone": data.get("phone", ""),
        "type_label": f"{category} / {subcategory}" if subcategory else category,
        "category": category,
        "subcategory": subcategory,
        "status": data.get("status", "접수됨"),
        "writer": data.get("writer", ""),
        "designer": data.get("designer", ""),
        "checker": data.get("checker", ""),
        "big_amt": summary["big_amt"],
        "small_amt": summary["small_amt"] + summary["side_amt"] + summary["back_amt"],
        "stone_photo": f"추가 {summary.get('stone_count', 1)}개" if summary["stone_added"] else "없음",
        "total": summary["total"],
        "data_file": data.get("data_file", ""),
        "preview_file": data.get("preview_file", ""),
    }


@app.route("/")
def index():
    return render_template(
        "index.html",
        catalog=CATALOG,
        rules=RULES,
        staff_list=STAFF_LIST,
        status_list=STATUS_LIST,
        stone_categories=STONE_PHOTO_CATEGORIES,
        saved_list=_read_index(),
    )


@app.route("/api/calc", methods=["POST"])
def api_calc():
    data = request.get_json(force=True) or {}
    return jsonify(calc_summary(data))


@app.route("/api/save", methods=["POST"])
def api_save():
    data = request.get_json(force=True) or {}
    item_id = data.get("id") or str(uuid.uuid4())
    created_at = data.get("created_at") or datetime.now().strftime("%Y-%m-%d %H:%M")
    data["id"] = item_id
    data["created_at"] = created_at
    data["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 저장 파일명: #계약번호계약자명(대분류_소분류_종교).json
    base_name = make_storage_basename(data)
    current_data_file = data.get("data_file")
    data_path, data_file = unique_path(DATA_DIR, base_name, ".json", current_data_file)
    data["data_file"] = data_file
    # PNG는 프론트에서 이어서 /api/save-preview로 저장됨. 파일명만 미리 알려준다.
    data["preview_file"] = os.path.splitext(data_file)[0] + ".png"

    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    items = _read_index()
    summary_item = make_summary_item(data, item_id=item_id, created_at=created_at)
    items = [x for x in items if x.get("id") != item_id]
    items.insert(0, summary_item)
    _write_index(items)
    return jsonify({
        "ok": True, "id": item_id, "item": summary_item,
        "data_file": data_file, "preview_file": data["preview_file"],
        "save_root": SAVE_ROOT,
    })


@app.route("/api/save-preview", methods=["POST"])
def api_save_preview():
    payload = request.get_json(force=True) or {}
    filename = safe_filename_text(payload.get("filename") or "preview.png")
    if not filename.lower().endswith(".png"):
        filename += ".png"
    data_url = payload.get("image") or ""
    if "," in data_url:
        data_url = data_url.split(",", 1)[1]
    try:
        image_bytes = base64.b64decode(data_url)
    except Exception:
        return jsonify({"ok": False, "error": "invalid image"}), 400
    path = os.path.join(PREVIEW_DIR, filename)
    with open(path, "wb") as f:
        f.write(image_bytes)
    return jsonify({"ok": True, "preview_file": filename, "preview_dir": PREVIEW_DIR})


@app.route("/api/list")
def api_list():
    return jsonify(_read_index())


def _find_item(item_id):
    for item in _read_index():
        if item.get("id") == item_id:
            return item
    return None


@app.route("/api/load/<item_id>")
def api_load(item_id):
    item = _find_item(item_id)
    filename = item.get("data_file") if item else f"{item_id}.json"
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        # 구버전 uuid 파일 호환
        legacy = os.path.join(DATA_DIR, f"{item_id}.json")
        if os.path.exists(legacy):
            path = legacy
        else:
            return jsonify({"ok": False, "error": "not found"}), 404
    with open(path, "r", encoding="utf-8") as f:
        return jsonify({"ok": True, "data": json.load(f)})


@app.route("/api/delete/<item_id>", methods=["POST"])
def api_delete(item_id):
    item = _find_item(item_id)
    if item:
        for directory, key in [(DATA_DIR, "data_file"), (PREVIEW_DIR, "preview_file")]:
            filename = item.get(key)
            if filename:
                path = os.path.join(directory, filename)
                if os.path.exists(path):
                    os.remove(path)
    else:
        legacy = os.path.join(DATA_DIR, f"{item_id}.json")
        if os.path.exists(legacy):
            os.remove(legacy)
    items = [x for x in _read_index() if x.get("id") != item_id]
    _write_index(items)
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
