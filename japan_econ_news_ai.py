"""
import sys
sys.argv = ["x", "--ai"]

"""
일본 경제 뉴스 키워드 · 분위기(트렌드) 분석 AI 프로그램  (v3: 3일치 비교 + 코랩 내장 AI)
-------------------------------------------------------
1) NHK · Yahoo!ニュース · 구글 뉴스 RSS에서 기사를 모아 발행일별(그저께·어제·오늘)로 나눔
   (실행할 때마다 articles_cache.json에 쌓아서, 매일 돌릴수록 지난 날 기사가 풍부해짐)
2) 형태소 분석(janome)으로 명사 키워드 추출 → 하루마다 순위 계산
3) 사전 기반 감성 분석으로 하루마다 분위기(긍정/부정) 판별
4) 한국어 분석 리포트 자동 작성
   - 기본: 규칙 기반 (정해진 멘트)
   - --ai : 구글 코랩에 내장된 AI(google.colab.ai)가 '경제 포인트'와 '3일 흐름 해석'을 직접 작성
            (API 키 필요 없음! 코랩에서만 작동)
5) 오늘의 차트 + 3일 비교 차트 저장 (--show 로 화면에도 띄우기)

설치:   pip install janome matplotlib

실행(터미널):  python japan_econ_news_ai.py
               python japan_econ_news_ai.py --sample
               python japan_econ_news_ai.py --ai        (코랩 내장 AI 사용)
               python japan_econ_news_ai.py --days 1
               python japan_econ_news_ai.py --label     (샘플 기사에 직접 정답 매기기 → 사전·AI 정확도 비교)

실행(코랩 셀):  import sys
                sys.argv = ["x", "--ai"]
                (그 아래에 이 코드 전체)
"""

import argparse
import csv
import glob
import json
import os
import re
import shutil
import time
import urllib.parse
import urllib.request
import warnings
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import matplotlib.pyplot as plt
from matplotlib import font_manager

try:
    from janome.tokenizer import Tokenizer
except ImportError:  # 코랩 등 janome이 없는 환경이면 자동으로 설치
    import subprocess
    import sys
    print("[안내] janome이 없어서 자동으로 설치합니다... (처음 한 번만, 약 10~30초)")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "janome"])
    from janome.tokenizer import Tokenizer

# ------------------------------------------------------------------
# 설정
# ------------------------------------------------------------------
JST = timezone(timedelta(hours=9))  # 일본 표준시 (한국과 같음)

FEEDS = {
    "NHK 経済": "https://www3.nhk.or.jp/rss/news/cat5.xml",
    "Yahoo!ニュース 経済": "https://news.yahoo.co.jp/rss/topics/business.xml",
}

GOOGLE_NEWS_QUERIES = ["経済", "株価", "為替 円", "日銀", "企業 決算", "物価"]
CACHE_ARTICLES = "articles_cache.json"
GOOGLE_NEWS_URL = "https://news.google.com/rss/search?q={q}&hl=ja&gl=JP&ceid=JP:ja"

STOPWORDS = {
    "こと", "もの", "ため", "よう", "これ", "それ", "ところ", "さん", "日本", "政府",
    "発表", "今回", "状況", "場合", "関係", "影響", "可能", "予定", "判断", "対応",
    "ニュース", "記事", "動画", "写真", "一部", "全体", "以上", "以下", "今年", "来年",
    "経済",
    "新聞", "注目", "支店", "ネットワーク", "フィスコ", "ウエルスアドバイザー", "トレーダーズ・ウェブ",
    "速報", "ロイター",  # 속보 표시·통신사 이름은 경제 내용이 아니라 잡음
}

COMPOUNDS = ["日経平均", "円安", "円高", "物価高", "利上げ", "利下げ", "賃上げ", "値上げ",
             "半導体", "最高値", "人手不足", "続伸", "続落", "急落", "急騰"]

POSITIVE = [
    "上昇", "高値", "最高", "増益", "好調", "回復", "拡大", "成長", "増加", "改善",
    "黒字", "上振れ", "堅調", "反発", "賃上げ", "最高値", "過去最高", "投資", "好転",
]
NEGATIVE = [
    "下落", "急落", "減益", "赤字", "悪化", "縮小", "減少", "不安", "懸念", "倒産",
    "下振れ", "低迷", "物価高", "値上げ", "円安", "リスク", "損失", "失速", "停滞",
]

KO_WORDS = {
    "円安": "엔저", "円高": "엔고", "為替": "환율", "金利": "금리", "利上げ": "금리 인상",
    "利下げ": "금리 인하", "日銀": "일본은행", "株価": "주가", "株式": "주식", "相場": "시세",
    "物価": "물가", "物価高": "물가 상승", "賃上げ": "임금 인상", "企業": "기업", "決算": "결산",
    "業績": "실적", "景気": "경기", "消費": "소비", "投資": "투자", "半導体": "반도체",
    "輸出": "수출", "輸入": "수입", "関税": "관세", "インフレ": "인플레이션", "金融": "금융",
    "市場": "시장", "経済": "경제", "日経平均": "닛케이 평균", "トヨタ": "도요타",
    "原油": "원유", "賃金": "임금", "雇用": "고용", "国債": "국채", "政策": "정책",
    "熊本": "구마모토", "アメリカ": "미국", "米国": "미국", "中国": "중국", "韓国": "한국",
    "東京": "도쿄", "大阪": "오사카", "台湾": "대만", "欧州": "유럽", "首相": "총리",
    "大統領": "대통령", "会社": "회사", "工場": "공장", "開発": "개발", "価格": "가격",
    "値上げ": "가격 인상", "人手不足": "인력 부족", "生産": "생산", "契約": "계약", "買収": "인수",
    "上場": "상장", "増税": "증세", "減税": "감세", "補助金": "보조금", "年金": "연금",
    "成長": "성장", "需要": "수요", "供給": "공급", "取引": "거래", "世界": "세계",
    "ドル": "달러", "ユーロ": "유로", "トランプ": "트럼프", "ソニー": "소니", "ソフトバンク": "소프트뱅크",
    "日経": "닛케이", "急落": "급락", "急騰": "급등", "上昇": "상승", "下落": "하락",
    "最高値": "사상 최고가", "更新": "경신", "見通し": "전망", "予想": "예상", "拡大": "확대",
    "不安": "불안", "懸念": "우려", "回復": "회복", "低迷": "침체", "赤字": "적자", "黒字": "흑자",
    "利益": "이익", "売上": "매출", "社長": "사장", "銀行": "은행", "保険": "보험", "不動産": "부동산",
    "自動車": "자동차", "電機": "전기·전자", "小売": "소매", "外国人": "외국인", "観光": "관광",
    "AI": "인공지능", "IPO": "기업공개", "FX": "외환거래", "PTS": "야간 사설거래", "ETF": "상장지수펀드",
    "情報": "정보", "夜間": "야간", "週刊": "주간지", "合併": "합병", "法人": "법인", "大手": "대기업",
    "平均": "평균", "調整": "조정", "東洋": "도요", "ホールディングス": "홀딩스",
    "アンソロピック": "앤트로픽", "エヌビディア": "엔비디아", "アップル": "애플", "テスラ": "테슬라",
    "フィスコ": "피스코", "会合": "회합", "長崎": "나가사키", "指数": "지수", "続伸": "연속 상승", "続落": "연속 하락",
    "日経平均": "닛케이 평균주가", "ウエルスアドバイザー": "웰스어드바이저",
    "寄り付き": "장 시작(개장)", "トレーダーズ・ウェブ": "트레이더스 웹(투자정보 매체)",
    "決算": "결산", "配当": "배당", "増配": "증배(배당 증가)", "新規": "신규", "最新": "최신",
    "ロイター": "로이터", "路線": "노선", "サービス": "서비스", "支持": "지지",
    "高騰": "급등", "速報": "속보", "修正": "수정", "関心": "관심", "目標": "목표",
}

_AUTO_KO = {}
CACHE_FILE = "translation_cache.json"

TOPIC_NOTES = {
    "円安": "엔저(엔화 약세)가 화제입니다. 수출 기업의 수익에는 유리하지만, 수입 물가가 올라 가계 부담이 커질 수 있습니다.",
    "円高": "엔고(엔화 강세)가 화제입니다. 수입 물가에는 유리하지만, 수출 기업의 실적에는 부담이 될 수 있습니다.",
    "金利": "금리 관련 소식이 많습니다. 금리가 오르면 대출 부담은 커지고 예금 이자는 늘어나, 기업 투자와 소비에 영향을 줍니다.",
    "日銀": "일본은행(BOJ)의 통화정책이 주목받고 있습니다. 일본은행의 결정은 환율과 주가에 직접 영향을 줍니다.",
    "株価": "주가 동향이 주요 이슈입니다. 주가는 기업 실적과 경기에 대한 투자자들의 기대를 보여주는 지표입니다.",
    "物価": "물가 소식이 많습니다. 물가 상승이 임금 상승을 앞지르면 실질 소득이 줄어 소비가 위축될 수 있습니다.",
    "賃上げ": "임금 인상이 화제입니다. 임금이 오르면 소비가 늘어 경기에 선순환을 만들 수 있다는 기대가 있습니다.",
    "半導体": "반도체 관련 소식이 많습니다. 반도체는 AI·자동차 등 여러 산업의 핵심 부품이라 경제 전반에 영향을 줍니다.",
    "AI": "AI 관련 소식이 눈에 띕니다. AI 투자가 기업 성장과 주식시장의 기대를 이끌고 있는지 살펴볼 만합니다.",
    "関税": "관세 문제가 언급됩니다. 관세는 수출입 가격과 기업의 무역 전략에 큰 영향을 줍니다.",
}

SAMPLE_BY_DAY = [
    [
        "日銀 利上げ観測が後退 円相場は小動き",
        "物価高が家計を圧迫 個人消費に懸念",
        "半導体株が下落 米国の関税引き上げ報道で不安拡大",
        "トヨタ 米国向け輸出が減少 円高が逆風に",
        "日経平均株価が続落 景気減速への警戒感",
    ],
    [
        "日経平均株価が反発 好調な米国市場を受け買い優勢",
        "円安が進行 輸出企業の業績改善に期待",
        "賃上げ率が高水準 個人消費の回復に期待",
        "日銀 金利政策を維持 市場は慎重に見守る",
        "物価高が続き値上げが相次ぐ 懸念も残る",
    ],
    [
        "日経平均株価が最高値を更新 好調な企業業績が相場を押し上げ",
        "円安が進行 輸入物価の上昇で家計への懸念が拡大",
        "日銀 金利政策を維持 市場は今後の利上げ時期に注目",
        "大手企業が賃上げを発表 過去最高の水準に",
        "半導体関連株が反発 AI投資の拡大で成長期待",
        "トヨタ 増益決算を発表 円安効果で業績は好調",
    ],
]

HISTORY_PATH = "history.csv"
OUT_DIR = "."  # 리포트·차트를 저장할 폴더 (코랩에서 드라이브를 연결하면 드라이브 폴더로 바뀜)
DRIVE_FOLDER = "/content/drive/MyDrive/japan_econ_news"


def setup_storage(use_drive=True):
    """코랩이면 구글 드라이브를 연결해서 기사 기록·번역 기록·결과 파일을 드라이브 폴더에 저장한다.
    → 런타임이 초기화돼도 어제·그저께 기사가 사라지지 않고 계속 쌓인다.
    코랩이 아니거나 연결에 실패하면 지금 폴더에 그대로 저장한다."""
    global CACHE_ARTICLES, CACHE_FILE, HISTORY_PATH, OUT_DIR
    if not use_drive:
        return
    try:
        from google.colab import drive  # 코랩이 아니면 ImportError
    except ImportError:
        return
    try:
        drive.mount("/content/drive")  # 처음 한 번 '권한 허용' 창이 뜸
        os.makedirs(DRIVE_FOLDER, exist_ok=True)
    except Exception as e:
        print(f"[경고] 구글 드라이브 연결 실패({e}) → 이 런타임 안에만 저장합니다.")
        return
    # 이미 이 런타임에 쌓아 둔 기록이 있고 드라이브에는 없으면 옮겨 준다
    for name in (CACHE_ARTICLES, CACHE_FILE, HISTORY_PATH):
        dst = os.path.join(DRIVE_FOLDER, os.path.basename(name))
        if os.path.exists(name) and not os.path.exists(dst):
            shutil.copy(name, dst)
    CACHE_ARTICLES = os.path.join(DRIVE_FOLDER, os.path.basename(CACHE_ARTICLES))
    CACHE_FILE = os.path.join(DRIVE_FOLDER, os.path.basename(CACHE_FILE))
    HISTORY_PATH = os.path.join(DRIVE_FOLDER, os.path.basename(HISTORY_PATH))
    OUT_DIR = DRIVE_FOLDER
    print(f"[안내] 구글 드라이브에 저장합니다 → {DRIVE_FOLDER}")


def day_label(day, today=None):
    """날짜 → '오늘/어제/그저께' (그 외엔 월/일)"""
    today = today or datetime.now(JST).date()
    return {0: "오늘", 1: "어제", 2: "그저께"}.get((today - day).days, f"{day:%m/%d}")


# ------------------------------------------------------------------
# 1. 뉴스 수집
# ------------------------------------------------------------------
def fetch_xml(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (school project)"})
    with urllib.request.urlopen(req, timeout=20) as res:
        return ET.fromstring(res.read())


def parse_pub(item):
    pub = item.findtext("pubDate")
    if not pub:
        return None
    try:
        return parsedate_to_datetime(pub).astimezone(JST)
    except Exception:
        return None


def fetch_feed_items(url, title_only=False):
    root = fetch_xml(url)
    out = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        if title_only:
            if " - " in title:
                title = title.rsplit(" - ", 1)[0]
            text = title
        else:
            desc = (item.findtext("description") or "").strip()
            text = f"{title} {desc}"
        if not text.strip():
            continue
        dt = parse_pub(item)
        out.append((dt.date() if dt else None, text))
    return out


def collect_articles():
    today = datetime.now(JST).date()
    sources = [(name, url, False) for name, url in FEEDS.items()]
    sources += [(f"구글뉴스 '{q}'", GOOGLE_NEWS_URL.format(q=urllib.parse.quote(q)), True)
                for q in GOOGLE_NEWS_QUERIES]
    articles = []
    for name, url, title_only in sources:
        try:
            got = fetch_feed_items(url, title_only)
            print(f"[수집] {name}: {len(got)}건")
            for day, text in got:
                if day is None:
                    if title_only:
                        continue
                    day = today
                articles.append((day, text))
        except Exception as e:
            print(f"[경고] {name} 수집 실패: {e}")
        time.sleep(0.3)
    return articles


def merge_cache(articles, keep_days=14):
    cache = {}
    if os.path.exists(CACHE_ARTICLES):
        try:
            with open(CACHE_ARTICLES, encoding="utf-8") as f:
                cache = json.load(f)
        except Exception:
            cache = {}
    for day, text in articles:
        bucket = cache.setdefault(str(day), [])
        if text not in bucket:
            bucket.append(text)
    limit = str(datetime.now(JST).date() - timedelta(days=keep_days))
    cache = {k: v for k, v in cache.items() if k >= limit}
    try:
        with open(CACHE_ARTICLES, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception:
        pass
    return cache


def collect_days(n_days, use_sample=False):
    today = datetime.now(JST).date()
    days = [today - timedelta(days=i) for i in range(n_days - 1, -1, -1)]

    if use_sample:
        samples = SAMPLE_BY_DAY[-n_days:]
        return [(d, list(t)) for d, t in zip(days, samples)]

    cache = merge_cache(collect_articles())
    result = []
    for d in days:
        texts = cache.get(str(d), [])
        print(f"[날짜별] {d} : {len(texts)}건")
        result.append((d, texts))
    return result


# ------------------------------------------------------------------
# 2. 키워드 추출 (자연어 처리)
# ------------------------------------------------------------------
_tokenizer = None


def extract_keywords(texts, top_n=15):
    global _tokenizer
    if _tokenizer is None:
        _tokenizer = Tokenizer()
    counter = Counter()
    for text in texts:
        for c in COMPOUNDS:
            n = text.count(c)
            if n:
                counter[c] += n
                text = text.replace(c, " ")
        for token in _tokenizer.tokenize(text):
            pos = token.part_of_speech.split(",")
            word = token.base_form if token.base_form != "*" else token.surface
            if pos[0] != "名詞" or pos[1] in ("代名詞", "数", "接尾", "非自立", "特殊"):
                continue
            if len(word) < 2 or word in STOPWORDS:
                continue
            if not re.search(r"[A-Za-z\u3040-\u30ff\u4e00-\u9fff\u3005]", word):
                continue
            counter[word] += 1
    return counter.most_common(top_n)


def auto_translate(words):
    """사전에 없는 일본어 단어를 자동 번역(구글 번역)해서 _AUTO_KO에 저장한다."""
    if not _AUTO_KO and os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, encoding="utf-8") as f:
                _AUTO_KO.update(json.load(f))
        except Exception:
            pass

    todo = [w for w in dict.fromkeys(words)
            if w not in KO_WORDS and not _AUTO_KO.get(w) and not w.isascii()]
    if not todo:
        return
    try:
        try:
            from deep_translator import GoogleTranslator
        except ImportError:
            import subprocess
            import sys
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "deep-translator"])
            from deep_translator import GoogleTranslator
        translator = GoogleTranslator(source="ja", target="ko")
    except Exception as e:
        print(f"[안내] 자동 번역을 쓸 수 없어요({e}). 일본어 단어는 그대로 표시합니다.")
        return

    last_err = None

    def translate_chunk(chunk):
        nonlocal last_err
        for attempt in range(3):
            try:
                out = translator.translate("\n".join(chunk))
                lines = [x.strip() for x in (out or "").split("\n")]
                return lines if len(lines) == len(chunk) else None
            except Exception as e:
                last_err = e
                time.sleep(2.0 * (attempt + 1))
        return None

    def translate_one(word):
        nonlocal last_err
        for attempt in range(3):
            try:
                r = (translator.translate(word) or "").strip()
                if r:
                    return r
            except Exception as e:
                last_err = e
            time.sleep(1.5 * (attempt + 1))
        return None

    for i in range(0, len(todo), 8):
        chunk = todo[i:i + 8]
        time.sleep(1.2)
        lines = translate_chunk(chunk)
        for j, w in enumerate(chunk):
            r = lines[j] if lines else translate_one(w)
            if r and r != w:
                _AUTO_KO[w] = r

    retry = [w for w in todo if not _AUTO_KO.get(w)]
    if retry:
        time.sleep(5)
        for w in retry:
            r = translate_one(w)
            if r and r != w:
                _AUTO_KO[w] = r
            time.sleep(0.5)

    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({k: v for k, v in _AUTO_KO.items() if v}, f, ensure_ascii=False, indent=1)
    except Exception:
        pass
    failed = [w for w in todo if not _AUTO_KO.get(w)]
    if failed:
        why = f" (원인: {last_err})" if last_err else ""
        print(f"[안내] 번역하지 못한 단어: {', '.join(failed)}{why}\n"
              "       → 코드 위쪽 KO_WORDS에 직접 추가하면 한국어로 나와요.")


def ko_label(word):
    ko = KO_WORDS.get(word) or _AUTO_KO.get(word)
    return f"{ko} ({word})" if ko and ko != word else word


# ------------------------------------------------------------------
# 3. 분위기 분석 (사전 기반 감성 분석)
# ------------------------------------------------------------------
def analyze_sentiment(texts):
    pos = sum(text.count(w) for text in texts for w in POSITIVE)
    neg = sum(text.count(w) for text in texts for w in NEGATIVE)
    total = pos + neg
    score = (pos - neg) / total if total else 0.0
    if score > 0.2:
        mood = "긍정적"
    elif score < -0.2:
        mood = "부정적"
    else:
        mood = "중립"
    return pos, neg, score, mood


def analyze_day(day, texts):
    kw_all = extract_keywords(texts, top_n=60)  # 3일 비교 차트용으로 넉넉하게 저장
    keywords = kw_all[:15]
    pos, neg, score, mood = analyze_sentiment(texts)
    return {"date": day, "texts": texts, "keywords": keywords, "kw_all": kw_all,
            "pos": pos, "neg": neg, "score": score, "mood": mood}


# ------------------------------------------------------------------
# 4. 한국어 분석 리포트 (+ 코랩 내장 AI)
# ------------------------------------------------------------------
def build_ai_prompt(daily):
    """AI에게 줄 질문(프롬프트): 분석 결과 숫자 + 오늘 기사 제목 일부"""
    today = daily[-1]
    top_words = [w for w, _ in today["keywords"][:10]]
    clean = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t)).strip() for t in today["texts"]]
    picked = sorted(clean, key=lambda t: -sum(w in t for w in top_words))[:25]
    headlines = "\n".join("- " + t[:90] for t in picked)
    days = "\n".join(
        f"{day_label(d['date'])}({d['date']}): 기사 {len(d['texts'])}건 / 분위기 점수 {d['score']:+.2f}"
        f" (긍정 {d['pos']}회, 부정 {d['neg']}회) / 상위 키워드: "
        + ", ".join(f"{ko_label(w)} {c}회" for w, c in d["keywords"][:6])
        for d in daily)
    return (
        "너는 일본 경제를 쉽게 설명해 주는 분석가야. 아래는 일본 경제 뉴스를 자동 분석한 결과야.\n"
        "고등학생이 이해할 수 있는 한국어로, 아래 형식을 정확히 지켜서 써 줘.\n\n"
        "[포인트]\n"
        "- (오늘의 경제 포인트 1: 2~3문장. 어떤 키워드/기사에 근거했는지 언급하고, 왜 중요한지 설명)\n"
        "- (포인트 2)\n"
        "- (포인트 3)\n"
        "[흐름]\n"
        "(최근 며칠간 분위기 점수와 키워드 변화를 해석하는 2~3문장)\n\n"
        "규칙: 아래 자료에 없는 사실은 지어내지 말 것 / 투자 조언은 하지 말 것 / "
        "**, # 같은 마크다운 기호는 쓰지 말 것 / 분위기 점수는 단어 목록 기반의 단순 지표라는 점을 감안할 것 / 날짜마다 기사 수가 크게 다르므로 기사 수가 늘었다는 사실 자체를 시장 변화로 해석하지 말 것.\n\n"
        f"[날짜별 분석 결과]\n{days}\n\n[오늘 기사 제목·요약 일부]\n{headlines}\n"
    )


def call_colab_ai(prompt):
    """구글 코랩에 내장된 AI 호출 (API 키 필요 없음, 코랩에서만 작동)"""
    from google.colab import ai  # 코랩이 아니면 ImportError
    last_err = None
    for attempt in range(3):
        try:
            return ai.generate_text(prompt)
        except Exception as e:
            last_err = e
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(last_err)


def ai_commentary(daily):
    """코랩 AI가 쓴 (경제 포인트, 3일 흐름 해석)을 돌려준다. 실패하면 (None, None) → 기본 해설로 대체"""
    try:
        text = call_colab_ai(build_ai_prompt(daily)).strip()
    except ImportError:
        print("[안내] 코랩이 아니라서 내장 AI를 쓸 수 없어요. 기본(규칙 기반) 해설을 사용합니다.")
        return None, None
    except Exception as e:
        print(f"[경고] 코랩 AI 호출 실패({e}) → 기본 해설로 대체합니다.")
        return None, None

    # 마크다운 기호 정리: '* 항목' → '- 항목', **굵게** 제거
    text = re.sub(r"(?m)^\s*[*•]\s+", "- ", text)
    text = text.replace("**", "").replace("##", "").replace("#", "")

    points, _, flow = text.partition("[흐름]")
    points = points.replace("[포인트]", "").strip()
    if not points:
        return None, None
    points = "\n".join("   " + line.strip() for line in points.splitlines() if line.strip())
    return points, flow.strip()


def rule_based_points(d):
    """규칙 기반 '경제 포인트' 줄 목록 (기사에 자주 나온 주제에 정해진 해설을 붙임)"""
    joined = " ".join(d["texts"])
    hits = sorted(((joined.count(k), k) for k in TOPIC_NOTES if joined.count(k) > 0), reverse=True)[:3]
    return [f"   - [{ko_label(k)} {cnt}회] {TOPIC_NOTES[k]}" for cnt, k in hits]


def make_report_rule_based(d, points=None):
    texts, keywords = d["texts"], d["keywords"]
    lines = [f"■ 일본 경제 뉴스 분석 리포트 ({d['date']})", ""]
    lines.append(f"1. 분석 규모: 경제 기사 {len(texts)}건의 제목·요약을 분석했습니다.")

    top = ", ".join(f"{ko_label(w)} {c}회" for w, c in keywords[:5])
    lines.append(f"2. 핵심 키워드: {top}")

    lines.append(f"3. 뉴스 분위기: '{d['mood']}' (긍정 표현 {d['pos']}회, 부정 표현 {d['neg']}회, 점수 {d['score']:+.2f})")
    if d["mood"] == "긍정적":
        lines.append("   → 주가 상승·실적 개선 등 밝은 소식의 비중이 더 큽니다.")
    elif d["mood"] == "부정적":
        lines.append("   → 물가 부담·경기 둔화 등 우려를 나타내는 소식의 비중이 더 큽니다.")
    else:
        lines.append("   → 긍정과 부정 소식이 비슷하게 섞여 있어 뚜렷한 방향성이 약합니다.")

    if points:  # AI가 쓴 경제 포인트
        lines.append("4. 오늘의 경제 포인트 (AI 분석):")
        lines.append(points)
        return "\n".join(lines)

    notes = rule_based_points(d)
    if notes:
        lines.append("4. 오늘의 경제 포인트:")
        lines.extend(notes)
    return "\n".join(lines)


def make_trend_report(daily, flow=None):
    if len(daily) < 2:
        return ""
    lines = ["", "■ 3일 변화 요약", ""]
    for d in daily:
        label = day_label(d["date"])
        sparse = " ⚠기사 적음" if len(d["texts"]) < 5 else ""
        top3 = ", ".join(ko_label(w) for w, _ in d["keywords"][:3])
        lines.append(f"- {label}({d['date']}): 기사 {len(d['texts'])}건{sparse} / 분위기 {d['mood']} ({d['score']:+.2f}) / 상위 키워드: {top3}")

    counts = [len(d["texts"]) for d in daily]
    if min(counts) and max(counts) / min(counts) >= 3:
        lines.append("")
        lines.append(f"⚠ 날짜별 기사 수 차이가 커서(최대 {max(counts) / min(counts):.1f}배) "
                     "키워드·표현 횟수 차트는 '기사 100건당' 기준으로 보정했어요.")

    first, last = daily[0], daily[-1]
    diff = last["score"] - first["score"]
    lines.append("")
    if diff > 0.15:
        lines.append(f"▶ 분위기 변화: {len(daily) - 1}일 사이 점수가 {first['score']:+.2f} → {last['score']:+.2f}로 올라, 뉴스 분위기가 개선되는 흐름입니다.")
    elif diff < -0.15:
        lines.append(f"▶ 분위기 변화: {len(daily) - 1}일 사이 점수가 {first['score']:+.2f} → {last['score']:+.2f}로 내려, 뉴스 분위기가 나빠지는 흐름입니다.")
    else:
        lines.append(f"▶ 분위기 변화: 점수가 {first['score']:+.2f} → {last['score']:+.2f}로 큰 변화 없이 비슷한 분위기가 이어졌습니다.")

    old = {w for w, _ in first["keywords"][:10]}
    new_words = [w for w, _ in last["keywords"][:10] if w not in old]
    if new_words:
        lines.append("▶ 오늘 새로 떠오른 키워드: " + ", ".join(ko_label(w) for w in new_words[:5]))
    if flow:
        lines.append("▶ AI 해석: " + flow)
    return "\n".join(lines)


# ------------------------------------------------------------------
# 4-2. 비교 기능: AI 감성 판단 vs 단어 사전 판단
# ------------------------------------------------------------------
def dict_label(text):
    """단어 사전으로 기사 1건의 분위기 판단 (긍정/부정/중립)"""
    p = sum(text.count(w) for w in POSITIVE)
    n = sum(text.count(w) for w in NEGATIVE)
    return "긍정" if p > n else "부정" if n > p else "중립"


def sample_path(day):
    return os.path.join(OUT_DIR, f"sentiment_sample_{day}.json")


def latest_sample_path():
    files = sorted(glob.glob(os.path.join(OUT_DIR, "sentiment_sample_*.json")))
    return files[-1] if files else None


def load_sample(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_sample(path, rows):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=1)
    except Exception as e:
        print(f"[경고] 샘플 저장 실패({e})")


def pick_samples(d, n):
    """감성 비교용 기사 n건을 고른다. 핵심 키워드가 들어간 '경제 기사'를 먼저, 부족하면 나머지에서 골고루."""
    clean = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t)).strip()[:80] for t in d["texts"]]
    clean = list(dict.fromkeys(t for t in clean if t))
    top_words = [w for w, _ in d["keywords"][:10]]
    relevant = [t for t in clean if any(w in t for w in top_words)]
    rel_set = set(relevant)
    rest = [t for t in clean if t not in rel_set]

    def spread(lst, k):  # 목록에서 골고루 k개
        if len(lst) <= k:
            return list(lst)
        step = len(lst) / k
        return [lst[int(i * step)] for i in range(k)]

    picked = spread(relevant, n)
    if len(picked) < n:
        picked += spread(rest, n - len(picked))
    return picked


def ai_sentiment_compare(d, n_samples=30):
    """(B) 기사 일부를 AI에게 긍정/부정/중립으로 판단시키고 단어 사전 판단과 비교할 자료를 만든다.
    샘플은 sentiment_sample_날짜.json 에 저장해서, 나중에 --label 로 직접 정답을 매길 수 있게 한다.
    성공하면 [{"text","dict","ai","human"}, ...] 를, 실패하면 None 을 돌려준다."""
    path = sample_path(d["date"])
    old = load_sample(path)
    if old and any(r.get("human") for r in old):
        print("[안내] 오늘은 직접 정답을 매긴 샘플이 있어서 같은 기사 그대로 사용합니다. "
              "(새로 뽑으려면 sentiment_sample 파일을 지우세요)")
        return old

    clean = pick_samples(d, n_samples)
    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(clean))
    prompt = (
        "아래는 일본 경제 뉴스 기사 제목·요약이야. 각 기사가 일본 경제·시장에 '긍정적인 소식'인지 "
        "'부정적인 소식'인지 '중립'인지, 단어 하나가 아니라 문맥과 의미를 보고 판단해 줘.\n"
        "출력 형식은 한 줄에 하나씩 '번호|라벨' 이고, 라벨은 긍정, 부정, 중립 중 하나만 써. "
        "다른 설명이나 기호는 절대 쓰지 마.\n"
        "예시:\n1|긍정\n2|부정\n\n"
        f"[기사]\n{numbered}\n"
    )
    try:
        text = call_colab_ai(prompt)
    except ImportError:
        print("[안내] 코랩이 아니라서 AI 감성 비교를 건너뜁니다.")
        return None
    except Exception as e:
        print(f"[경고] AI 감성 판단 실패({e}) → 비교를 건너뜁니다.")
        return None

    labels = {}
    for m in re.finditer(r"(\d+)\s*[|:.\-]\s*(긍정|부정|중립)", text):
        i = int(m.group(1)) - 1
        if 0 <= i < len(clean):
            labels.setdefault(i, m.group(2))
    if len(labels) < len(clean) * 0.6:
        print("[경고] AI 답변 형식을 제대로 읽지 못해 감성 비교를 건너뜁니다.")
        return None
    rows = [{"text": clean[i], "dict": dict_label(clean[i]), "ai": labels[i], "human": None}
            for i in sorted(labels)]
    save_sample(path, rows)
    return rows


def graded_rows(rows):
    """직접 정답(긍정/부정/중립)을 매긴 기사만"""
    return [r for r in rows if r.get("human") in ("긍정", "부정", "중립")]


def grade_lines(rows):
    """직접 매긴 정답 기준 정확도 비교 (정답이 5건 미만이면 빈 목록)"""
    g = graded_rows(rows)
    if len(g) < 5:
        return []
    n = len(g)
    dc = sum(1 for r in g if r["dict"] == r["human"])
    ac = sum(1 for r in g if r["ai"] == r["human"])
    lines = ["", f"■ 정확도 비교: 직접 매긴 정답 {n}건 기준", ""]
    lines.append(f"- 단어 사전: {dc}/{n}건 정답 ({dc / n:.0%})")
    lines.append(f"- AI      : {ac}/{n}건 정답 ({ac / n:.0%})")
    only_ai = [r for r in g if r["ai"] == r["human"] and r["dict"] != r["human"]]
    only_dict = [r for r in g if r["dict"] == r["human"] and r["ai"] != r["human"]]
    if only_ai:
        lines.append(f"- AI만 맞힌 기사 {len(only_ai)}건 (예시):")
        for r in only_ai[:3]:
            lines.append(f"   · {r['text'][:60]} → 정답 {r['human']} / 사전 {r['dict']} / AI {r['ai']}")
    if only_dict:
        lines.append(f"- 사전만 맞힌 기사 {len(only_dict)}건 (예시):")
        for r in only_dict[:3]:
            lines.append(f"   · {r['text'][:60]} → 정답 {r['human']} / 사전 {r['dict']} / AI {r['ai']}")
    lines.append("※ 정답은 직접 읽고 매긴 것이라 사람마다 다를 수 있고, 표본이 작아서 참고용으로 봐 주세요.")
    return lines


def make_sentiment_compare_report(rows):
    n = len(rows)

    def cnt(key, label):
        return sum(1 for r in rows if r[key] == label)

    def score(key):
        p, g = cnt(key, "긍정"), cnt(key, "부정")
        return (p - g) / (p + g) if p + g else 0.0

    same = sum(1 for r in rows if r["dict"] == r["ai"])
    lines = ["", f"■ 감성 분석 비교: 단어 사전 vs AI (같은 기사 {n}건 기준)", ""]
    lines.append(f"- 단어 사전: 긍정 {cnt('dict', '긍정')} / 중립 {cnt('dict', '중립')} / 부정 {cnt('dict', '부정')} (점수 {score('dict'):+.2f})")
    lines.append(f"- AI 판단 : 긍정 {cnt('ai', '긍정')} / 중립 {cnt('ai', '중립')} / 부정 {cnt('ai', '부정')} (점수 {score('ai'):+.2f})")
    lines.append(f"- 두 방식이 같은 판단을 한 기사: {same}/{n}건 ({same / n:.0%})")
    diffs = [r for r in rows if r["dict"] != r["ai"]][:5]
    if diffs:
        lines.append("- 판단이 달랐던 기사 예시:")
        for r in diffs:
            lines.append(f"   · {r['text'][:60]} → 사전 {r['dict']} / AI {r['ai']}")
    lines.append("※ 단어 사전은 단어만 보고, AI는 문맥을 보고 판단해요. 다만 AI가 항상 정답은 아니니 원문으로 확인해 보세요.")
    lines.extend(grade_lines(rows))
    return "\n".join(lines)


def draw_sentiment_compare_chart(rows, path, keep_open=False):
    set_font()
    labs = ["긍정", "중립", "부정"]
    dic = [sum(1 for r in rows if r["dict"] == lab) for lab in labs]
    ai = [sum(1 for r in rows if r["ai"] == lab) for lab in labs]
    x = list(range(len(labs)))
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.bar([i - 0.2 for i in x], dic, width=0.4, color="#9db8dd", label="단어 사전")
    ax.bar([i + 0.2 for i in x], ai, width=0.4, color="#1f4e99", label="AI")
    ax.set_xticks(x)
    ax.set_xticklabels(labs)
    ax.set_ylabel("기사 수")
    ax.set_title(f"감성 판단 비교 (같은 기사 {len(rows)}건)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    if not keep_open:
        plt.close(fig)


def draw_accuracy_chart(rows, path, keep_open=False):
    """직접 매긴 정답 대비 정확도: 단어 사전 vs AI"""
    set_font()
    g = graded_rows(rows)
    n = len(g)
    accs = [sum(1 for r in g if r[k] == r["human"]) / n * 100 for k in ("dict", "ai")]
    fig, ax = plt.subplots(figsize=(6, 5))
    bars = ax.bar(["단어 사전", "AI"], accs, color=["#9db8dd", "#1f4e99"])
    for b_, v in zip(bars, accs):
        ax.annotate(f"{v:.0f}%", (b_.get_x() + b_.get_width() / 2, v), textcoords="offset points",
                    xytext=(0, 5), ha="center")
    ax.set_ylim(0, 110)
    ax.set_ylabel("정답과 일치한 비율 (%)")
    ax.set_title(f"직접 매긴 정답 {n}건 기준 정확도")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    if not keep_open:
        plt.close(fig)


def label_mode():
    """--label : 저장된 기사 샘플을 하나씩 보여 주고 직접 정답(긍정/부정/중립)을 입력받는다.
    사전·AI의 판단은 숨기고 보여 주므로 정답이 휘둘리지 않는다. 입력 후 정확도를 비교한다."""
    path = latest_sample_path()
    rows = load_sample(path) if path else None
    if not rows:
        print("정답을 매길 샘플이 아직 없어요. 먼저 --ai 로 한 번 실행해서 기사 샘플을 만들어 주세요.")
        return
    key = {"1": "긍정", "2": "부정", "3": "중립"}
    todo = [i for i, r in enumerate(rows) if not r.get("human")]
    print(f"\n[정답 매기기] {os.path.basename(path)} · 남은 기사 {len(todo)}건 / 전체 {len(rows)}건")
    print("기준: 일본 경제·시장에 좋은 소식이면 1(긍정), 나쁜 소식이면 2(부정),")
    print("      단순 사실 전달이거나 경제와 상관이 약하면 3(중립), 판단이 어렵거나 경제 기사가 아니면 s(제외)")
    print("(중간에 q 를 누르면 저장하고 멈춰요. 다음에 --label 로 이어서 할 수 있어요.)")
    quit_now = False
    for i in todo:
        print(f"\n[{i + 1}/{len(rows)}] {rows[i]['text']}")
        while True:
            try:
                ans = input("정답? (1 긍정 / 2 부정 / 3 중립 / s 제외 / q 저장하고 그만): ").strip().lower()
            except EOFError:
                ans = "q"
            if ans in key:
                rows[i]["human"] = key[ans]
                break
            if ans == "s":
                rows[i]["human"] = "제외"
                break
            if ans == "q":
                quit_now = True
                break
            print("   1, 2, 3, s, q 중 하나를 입력하세요.")
        save_sample(path, rows)
        if quit_now:
            break

    lines = grade_lines(rows)
    if not lines:
        print(f"\n정답을 매긴 기사가 {len(graded_rows(rows))}건이라 아직 비교하기엔 적어요 (5건 이상 필요). "
              "--label 로 이어서 하면 돼요.")
        return
    print("\n".join(lines))
    day = os.path.basename(path)[len("sentiment_sample_"):-len(".json")]
    with open(os.path.join(OUT_DIR, f"accuracy_report_{day}.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    chart = os.path.join(OUT_DIR, f"accuracy_chart_{day}.png")
    draw_accuracy_chart(rows, chart)
    print(f"\n저장 완료 → {chart}")
    print("※ 이제 --ai 로 다시 실행하면 정확도 비교가 리포트에도 같이 들어가요.")


# ------------------------------------------------------------------
# 5. 시각화 + 기록
# ------------------------------------------------------------------
def set_font():
    preferred = ["Noto Sans CJK JP", "Noto Sans CJK KR", "Malgun Gothic", "Yu Gothic",
                 "Meiryo", "Hiragino Sans", "AppleGothic"]
    fallback = ["NanumGothic", "IPAexGothic", "IPAGothic"]

    def find(names):
        installed = {f.name for f in font_manager.fontManager.ttflist}
        return next((n for n in names if n in installed), None)

    name = find(preferred)
    if name is None and os.name == "posix":
        try:
            import subprocess
            print("[안내] 한글·일본어 폰트를 설치합니다... (처음 한 번만, 약 30초)")
            subprocess.run("apt-get -qq install -y fonts-noto-cjk > /dev/null 2>&1", shell=True)
            for path in glob.glob("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"):
                font_manager.fontManager.addfont(path)
            name = find(preferred)
        except Exception:
            pass
    name = name or find(fallback)
    if name:
        plt.rcParams["font.family"] = name
    else:
        print("[안내] 한글/일본어 폰트를 못 찾았어요. 글자가 □로 보이면 맑은 고딕(Malgun Gothic)을 설치하세요.")
    plt.rcParams["axes.unicode_minus"] = False
    warnings.filterwarnings("ignore", message=r"Glyph .* missing")


def draw_chart(d, path, keep_open=False):
    set_font()
    labels = [ko_label(w) for w, _ in d["keywords"]][::-1]
    counts = [c for _, c in d["keywords"]][::-1]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 6), gridspec_kw={"width_ratios": [3, 1]})
    ax1.barh(labels, counts, color="#3b6fb6")
    ax1.set_title(f"일본 경제 핵심 키워드 ({d['date']})")
    ax1.set_xlabel("등장 횟수")

    ax2.bar(["긍정", "부정"], [d["pos"], d["neg"]], color=["#4caf50", "#e53935"])
    ax2.set_title(f"분위기: {d['mood']} ({d['score']:+.2f})")
    ax2.set_ylabel("표현 횟수")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    if not keep_open:
        plt.close(fig)


def draw_three_day_chart(daily, path, keep_open=False):
    set_font()
    labels = [f"{day_label(d['date'])}\n{d['date']:%m/%d}\n({len(d['texts'])}건)" for d in daily]

    def per100(d, c):  # 기사 수가 날짜마다 다르므로 '기사 100건당' 횟수로 보정
        return c * 100 / max(len(d["texts"]), 1)

    total = Counter()
    for d in daily:
        for w, c in d["kw_all"]:
            total[w] += per100(d, c)
    top_words = [w for w, _ in total.most_common(8)]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6), gridspec_kw={"width_ratios": [3, 2]})
    width = 0.8 / len(daily)
    colors = ["#9db8dd", "#5b86c5", "#1f4e99"]
    ys = range(len(top_words))
    for i, d in enumerate(daily):
        cnt = dict(d["kw_all"])
        ax1.barh([y + i * width for y in ys], [per100(d, cnt.get(w, 0)) for w in top_words], height=width,
                 color=colors[-len(daily):][i], label=labels[i].replace("\n", " "))
    ax1.set_yticks([y + width * (len(daily) - 1) / 2 for y in ys])
    ax1.set_yticklabels([ko_label(w) for w in top_words])
    ax1.invert_yaxis()
    ax1.set_xlabel("기사 100건당 등장 횟수")
    ax1.set_title("3일간 핵심 키워드 비교 (기사 수 보정)")
    ax1.legend()

    x = range(len(daily))
    ax2.bar([i - 0.2 for i in x], [per100(d, d["pos"]) for d in daily], width=0.4, color="#4caf50", label="긍정 표현")
    ax2.bar([i + 0.2 for i in x], [per100(d, d["neg"]) for d in daily], width=0.4, color="#e53935", label="부정 표현")
    ax2.set_xticks(list(x))
    ax2.set_xticklabels(labels)
    ax2.set_ylabel("기사 100건당 표현 횟수")
    ax2.set_title("3일간 분위기 변화")
    ax3 = ax2.twinx()
    ax3.plot(list(x), [d["score"] for d in daily], marker="o", color="#333333", label="분위기 점수")
    for i, d in enumerate(daily):
        ax3.annotate(f"{d['score']:+.2f}", (i, d["score"]), textcoords="offset points", xytext=(0, 8), ha="center")
    ax3.axhline(0, color="gray", linestyle="--", linewidth=1)
    ax3.set_ylim(-1, 1)
    ax3.set_ylabel("분위기 점수 (-1 부정 ~ +1 긍정)")
    h1, l1 = ax2.get_legend_handles_labels()
    h2, l2 = ax3.get_legend_handles_labels()
    ax2.legend(h1 + h2, l1 + l2, loc="upper left")

    fig.tight_layout()
    fig.savefig(path, dpi=150)
    if not keep_open:
        plt.close(fig)


def save_history(daily, path=None):
    path = path or HISTORY_PATH
    rows = []
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig") as f:
            rows = [r for r in csv.reader(f)][1:]
    done = {str(d["date"]) for d in daily}
    rows = [r for r in rows if r and r[0] not in done]
    for d in daily:
        rows.append([str(d["date"]), f"{d['score']:.3f}", " / ".join(w for w, _ in d["keywords"][:5])])
    rows.sort(key=lambda r: r[0])
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "mood_score", "top5_keywords"])
        writer.writerows(rows)


# ------------------------------------------------------------------
# 메인
# ------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="일본 경제 뉴스 분석 프로그램")
    parser.add_argument("--sample", action="store_true", help="샘플 데이터로 실행")
    parser.add_argument("--show", action="store_true", help="차트를 화면 창으로 띄우기")
    parser.add_argument("--ai", action="store_true", help="코랩 내장 AI(API 키 불필요)가 경제 포인트를 직접 분석")
    parser.add_argument("--label", action="store_true", help="저장된 샘플 기사에 직접 정답을 매겨 사전·AI 정확도 비교")
    parser.add_argument("--no-drive", action="store_true", help="코랩에서도 구글 드라이브를 연결하지 않기")
    parser.add_argument("--days", type=int, default=3, choices=[1, 2, 3], help="분석할 일수 (기본 3일)")
    args, _ = parser.parse_known_args()
    setup_storage(use_drive=not args.no_drive)
    if args.label:
        label_mode()
        return

    collected = collect_days(args.days, use_sample=args.sample)
    collected = [(d, t) for d, t in collected if t]
    if not collected:
        print("기사를 가져오지 못했어요. 인터넷 연결을 확인하거나 --sample 로 먼저 시험해 보세요.")
        return
    if len(collected) < args.days:
        print(f"[안내] {args.days}일 중 {len(collected)}일치만 수집됐어요. 가져온 날짜만으로 비교합니다.")
    for d, t in collected:
        if len(t) < 5:
            print(f"[안내] {d} 기사가 {len(t)}건뿐이라 그날 분석은 참고용으로만 봐 주세요.")
    print(f"총 {sum(len(t) for _, t in collected)}건 분석 중...\n")

    daily = [analyze_day(d, t) for d, t in collected]
    auto_translate([w for d in daily for w, _ in d["keywords"]])
    today = daily[-1]

    points = flow = sent_rows = None
    if args.ai:
        print("[안내] 코랩 AI가 분석 중입니다... (수 초~수십 초)")
        points, flow = ai_commentary(daily)
        sent_rows = ai_sentiment_compare(today)
    report = make_report_rule_based(today, points)
    report += "\n" + make_trend_report(daily, flow)
    if sent_rows:
        report += "\n" + make_sentiment_compare_report(sent_rows)
    if points:
        report += "\n\n※ 경제 포인트와 흐름 해석은 AI가 작성했어요. AI도 틀릴 수 있으니 원문 기사와 함께 확인하세요."
    else:
        report += "\n\n※ 사전(단어 목록) 기반 분석이라 문맥을 완벽히 이해하지는 못합니다. 참고용 지표로 봐 주세요."
    print(report)

    report_path = os.path.join(OUT_DIR, f"report_{today['date']}.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    chart_path = os.path.join(OUT_DIR, f"result_{today['date']}.png")
    draw_chart(today, chart_path, keep_open=args.show)
    saved = [chart_path]
    if len(daily) >= 2:
        three_path = os.path.join(OUT_DIR, f"three_day_chart_{today['date']}.png")
        draw_three_day_chart(daily, three_path, keep_open=args.show)
        saved.append(three_path)
    if sent_rows:
        sent_path = os.path.join(OUT_DIR, f"sentiment_compare_{today['date']}.png")
        draw_sentiment_compare_chart(sent_rows, sent_path, keep_open=args.show)
        saved.append(sent_path)
        if len(graded_rows(sent_rows)) >= 5:
            acc_path = os.path.join(OUT_DIR, f"accuracy_chart_{today['date']}.png")
            draw_accuracy_chart(sent_rows, acc_path, keep_open=args.show)
            saved.append(acc_path)
    save_history(daily)

    print(f"\n저장 완료 → 차트: {' / '.join(saved)} / 리포트: {report_path} / 기록: {HISTORY_PATH}")
    if args.show:
        plt.show()


if __name__ == "__main__":
    main()
