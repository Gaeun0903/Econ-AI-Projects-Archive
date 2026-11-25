"""
일본 경제 뉴스 키워드 · 분위기(트렌드) 분석 AI 프로그램
-------------------------------------------------------
1) NHK / Yahoo!ニュース 경제 RSS에서 오늘의 기사 수집
2) 형태소 분석(janome)으로 명사 키워드 추출 → 많이 나온 순위 계산
3) 사전 기반 감성 분석으로 오늘 일본 경제 뉴스의 분위기(긍정/부정) 판별
4) 결과를 그래프(PNG)와 기록 파일(history.csv)로 저장 → 날마다 쌓으면 트렌드 분석 가능

설치:   pip install janome matplotlib
실행:   python japan_econ_news_ai.py            (실제 뉴스 수집)
        python japan_econ_news_ai.py --sample   (인터넷 없이 샘플 데이터로 시험)
"""

import argparse
import csv
import os
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date

import matplotlib
matplotlib.use("Agg")  # 화면 없이 파일로 저장
import matplotlib.pyplot as plt
from matplotlib import font_manager
from janome.tokenizer import Tokenizer

# ------------------------------------------------------------------
# 설정
# ------------------------------------------------------------------
FEEDS = {
    "NHK 経済": "https://www3.nhk.or.jp/rss/news/cat5.xml",
    "Yahoo!ニュース 経済": "https://news.yahoo.co.jp/rss/topics/business.xml",
}

# 키워드로 세지 않을 단어 (너무 흔하거나 의미 없는 말)
STOPWORDS = {
    "こと", "もの", "ため", "よう", "これ", "それ", "ところ", "さん", "日本", "政府",
    "発表", "今回", "状況", "場合", "関係", "影響", "可能", "予定", "判断", "対応",
    "ニュース", "記事", "動画", "写真", "一部", "全体", "以上", "以下", "今年", "来年",
}

# 감성 분석용 단어 사전 (직접 단어를 추가하면 정확도가 올라감!)
POSITIVE = [
    "上昇", "高値", "最高", "増益", "好調", "回復", "拡大", "成長", "増加", "改善",
    "黒字", "上振れ", "堅調", "反発", "賃上げ", "最高値", "過去最高", "投資", "好転",
]
NEGATIVE = [
    "下落", "急落", "減益", "赤字", "悪化", "縮小", "減少", "不安", "懸念", "倒産",
    "下振れ", "低迷", "物価高", "値上げ", "円安", "リスク", "損失", "失速", "停滞",
]

SAMPLE_TEXTS = [
    "日経平均株価が最高値を更新 好調な企業業績が相場を押し上げ",
    "円安が進行 輸入物価の上昇で家計への懸念が拡大",
    "日銀 金利政策を維持 市場は今後の利上げ時期に注目",
    "大手企業が賃上げを発表 過去最高の水準に",
    "物価高が続き個人消費は低迷 景気回復の動きに停滞感",
    "半導体関連株が反発 AI投資の拡大で成長期待",
    "トヨタ 増益決算を発表 円安効果で業績は好調",
    "インフレ率が上昇 日銀は金融政策の判断を慎重に",
]

# ------------------------------------------------------------------
# 1. 뉴스 수집
# ------------------------------------------------------------------
def fetch_rss(url):
    """RSS 주소에서 (제목 + 요약) 문자열 리스트를 가져온다."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (school project)"})
    with urllib.request.urlopen(req, timeout=15) as res:
        root = ET.fromstring(res.read())
    texts = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        desc = (item.findtext("description") or "").strip()
        texts.append(f"{title} {desc}")
    return texts


def collect_news(use_sample=False):
    if use_sample:
        return list(SAMPLE_TEXTS)
    all_texts = []
    for name, url in FEEDS.items():
        try:
            got = fetch_rss(url)
            print(f"[수집] {name}: {len(got)}건")
            all_texts.extend(got)
        except Exception as e:  # 한 곳이 실패해도 나머지로 계속 진행
            print(f"[경고] {name} 수집 실패: {e}")
    return all_texts


# ------------------------------------------------------------------
# 2. 키워드 추출 (자연어 처리)
# ------------------------------------------------------------------
def extract_keywords(texts, top_n=15):
    tokenizer = Tokenizer()
    counter = Counter()
    for text in texts:
        for token in tokenizer.tokenize(text):
            pos = token.part_of_speech.split(",")
            word = token.base_form if token.base_form != "*" else token.surface
            # 명사만, 대명사/숫자/접미사 등은 제외
            if pos[0] != "名詞" or pos[1] in ("代名詞", "数", "接尾", "非自立", "特殊"):
                continue
            if len(word) < 2 or word in STOPWORDS:
                continue
            counter[word] += 1
    return counter.most_common(top_n)


# ------------------------------------------------------------------
# 3. 분위기 분석 (사전 기반 감성 분석)
# ------------------------------------------------------------------
def analyze_sentiment(texts):
    pos = sum(text.count(w) for text in texts for w in POSITIVE)
    neg = sum(text.count(w) for text in texts for w in NEGATIVE)
    total = pos + neg
    score = (pos - neg) / total if total else 0.0  # -1(매우 부정) ~ +1(매우 긍정)
    if score > 0.2:
        mood = "긍정적 😊"
    elif score < -0.2:
        mood = "부정적 😟"
    else:
        mood = "중립 😐"
    return pos, neg, score, mood


# ------------------------------------------------------------------
# 4. 시각화 + 기록
# ------------------------------------------------------------------
def set_japanese_font():
    candidates = ["Noto Sans CJK JP", "Yu Gothic", "Meiryo", "Hiragino Sans",
                  "Malgun Gothic", "AppleGothic", "IPAexGothic", "IPAGothic"]
    installed = {f.name for f in font_manager.fontManager.ttflist}
    for name in candidates:
        if name in installed:
            plt.rcParams["font.family"] = name
            return name
    print("[안내] 일본어 폰트를 못 찾았어요. 그래프 글자가 □로 보이면 Malgun Gothic/Meiryo를 설치하세요.")
    return None


def draw_chart(keywords, score, mood, pos, neg, path):
    set_japanese_font()
    plt.rcParams["axes.unicode_minus"] = False
    words = [w for w, _ in keywords][::-1]
    counts = [c for _, c in keywords][::-1]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 6), gridspec_kw={"width_ratios": [3, 1]})
    ax1.barh(words, counts, color="#3b6fb6")
    ax1.set_title(f"Today's Japan Economy Keywords ({date.today()})")
    ax1.set_xlabel("count")

    ax2.bar(["positive", "negative"], [pos, neg], color=["#4caf50", "#e53935"])
    ax2.set_title(f"Mood score {score:+.2f}")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def save_history(keywords, score, path="history.csv"):
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if new:
            writer.writerow(["date", "mood_score", "top5_keywords"])
        writer.writerow([date.today(), f"{score:.3f}", " / ".join(w for w, _ in keywords[:5])])


# ------------------------------------------------------------------
# 메인
# ------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", action="store_true", help="샘플 데이터로 실행")
    args = parser.parse_args()

    texts = collect_news(use_sample=args.sample)
    if not texts:
        print("기사를 가져오지 못했어요. 인터넷 연결을 확인하거나 --sample 로 먼저 시험해 보세요.")
        return
    print(f"총 {len(texts)}건 분석 중...\n")

    keywords = extract_keywords(texts)
    pos, neg, score, mood = analyze_sentiment(texts)

    print("=== 오늘의 일본 경제 핵심 키워드 TOP 10 ===")
    for i, (w, c) in enumerate(keywords[:10], 1):
        print(f"{i:2d}. {w}  ({c}회)")
    print(f"\n=== 오늘의 경제 뉴스 분위기: {mood} (긍정 {pos} / 부정 {neg} / 점수 {score:+.2f}) ===")

    out = f"result_{date.today()}.png"
    draw_chart(keywords, score, mood, pos, neg, out)
    save_history(keywords, score)
    print(f"\n그래프 저장: {out}   기록 저장: history.csv")


if __name__ == "__main__":
    main()
