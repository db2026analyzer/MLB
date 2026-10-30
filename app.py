import json
import os
import re
import sqlite3

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(
    page_title="MLB 選手キャリア＆チーム補強ダッシュボード",
    page_icon="⚾",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ------------------------------------------------------------------
# 🎨 1. カスタムCSS & 全30球団チームロゴ・カラー・パークファクター定義
# ------------------------------------------------------------------
st.markdown(
    """
    <style>
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2rem;
    }
    .metric-card {
        background-color: #ffffff;
        border: 1px solid #e0e0e0;
        border-radius: 10px;
        padding: 15px;
        text-align: center;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        margin-bottom: 10px;
    }
    .metric-card h4 {
        margin: 0;
        color: #6c757d;
        font-size: 0.85rem;
    }
    .metric-card p {
        margin: 5px 0 0 0;
        font-size: 1.4rem;
        font-weight: bold;
        color: #1a1a1a;
    }
    .metric-card .sub-text {
        margin-top: 4px;
        font-size: 0.8rem;
        color: #007bff;
        font-weight: 500;
    }
    .sidebar-section-header {
        font-size: 0.85rem;
        font-weight: bold;
        color: #7f8c8d;
        text-transform: uppercase;
        margin-top: 15px;
        margin-bottom: 5px;
        letter-spacing: 0.5px;
    }
    .team-header-container {
        display: flex;
        align-items: center;
        gap: 15px;
        margin-bottom: 15px;
        padding: 10px 15px;
        border-radius: 8px;
        background-color: #f8f9fa;
    }
    .team-logo-img {
        width: 50px;
        height: 50px;
        object-fit: contain;
    }
    .risk-badge-warning {
        background-color: #fff3cd;
        color: #856404;
        border: 1px solid #ffeeba;
        padding: 4px 8px;
        border-radius: 5px;
        font-weight: bold;
        display: inline-block;
    }
    .risk-badge-safe {
        background-color: #d4edda;
        color: #155724;
        border: 1px solid #c3e6cb;
        padding: 4px 8px;
        border-radius: 5px;
        font-weight: bold;
        display: inline-block;
    }
    .news-card {
        background: #fdfdfd;
        border-left: 5px solid #007bff;
        padding: 12px 16px;
        margin-bottom: 12px;
        border-radius: 4px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.04);
    }
    </style>
""",
    unsafe_allow_html=True,
)


def render_card(title, value, sub_text=None, border_color=None):
    """カスタムCSS（.metric-card）を適用したHTMLカードをレンダリングする関数"""
    border_style = f"border-top: 4px solid {border_color};" if border_color else ""
    sub_html = f'<div class="sub-text">{sub_text}</div>' if sub_text else ""
    card_html = f"""
    <div class="metric-card" style="{border_style}">
        <h4>{title}</h4>
        <p>{value}</p>
        {sub_html}
    </div>
    """
    st.markdown(card_html, unsafe_allow_html=True)


DB_PATH = "mlb_player_stats.db"
CSV_PATH = "contract_data.csv"

# 1 WARあたりの市場価値設定 (ドル)
WAR_MARKET_VALUE = 8_000_000  # $8M / 1 WAR
MLB_MINIMUM_SALARY = 780_000  # データ未登録時の推定年俸 ($780k)

# ------------------------------------------------------------------
# 🏟️ MLB公式 チーム情報マスター（略称、フルネーム、エイリアス、カラー、MLB ID、パークファクター）
# ------------------------------------------------------------------
TEAM_MASTER = {
    "LAD": {
        "id": 119,
        "color": "#005A9C",
        "pf": 100,
        "keywords": ["LAD", "DODGERS", "LOS ANGELES DODGERS"],
    },
    "NYY": {
        "id": 147,
        "color": "#0C2340",
        "pf": 99,
        "keywords": ["NYY", "YANKEES", "NEW YORK YANKEES"],
    },
    "BOS": {
        "id": 111,
        "color": "#BD3039",
        "pf": 104,
        "keywords": ["BOS", "RED SOX", "BOSTON RED SOX"],
    },
    "CHC": {
        "id": 112,
        "color": "#0E3386",
        "pf": 101,
        "keywords": ["CHC", "CUBS", "CHICAGO CUBS"],
    },
    "SF": {
        "id": 137,
        "color": "#FD5A1E",
        "pf": 96,
        "keywords": ["SF", "SFG", "GIANTS", "SAN FRANCISCO GIANTS"],
    },
    "SD": {
        "id": 135,
        "color": "#2F241D",
        "pf": 95,
        "keywords": ["SD", "SDP", "PADRES", "SAN DIEGO PADRES"],
    },
    "ATL": {
        "id": 144,
        "color": "#CE1141",
        "pf": 101,
        "keywords": ["ATL", "BRAVES", "ATLANTA BRAVES"],
    },
    "HOU": {
        "id": 117,
        "color": "#002D62",
        "pf": 98,
        "keywords": ["HOU", "ASTROS", "HOUSTON ASTROS"],
    },
    "NYM": {
        "id": 121,
        "color": "#002D62",
        "pf": 96,
        "keywords": ["NYM", "METS", "NEW YORK METS"],
    },
    "PHI": {
        "id": 143,
        "color": "#E81828",
        "pf": 101,
        "keywords": ["PHI", "PHILLIES", "PHILADELPHIA PHILLIES"],
    },
    "TOR": {
        "id": 141,
        "color": "#134A8E",
        "pf": 100,
        "keywords": ["TOR", "BLUE JAYS", "TORONTO BLUE JAYS"],
    },
    "SEA": {
        "id": 136,
        "color": "#0C2C56",
        "pf": 92,
        "keywords": ["SEA", "MARINERS", "SEATTLE MARINERS"],
    },
    "BAL": {
        "id": 110,
        "color": "#DF4601",
        "pf": 99,
        "keywords": ["BAL", "BALTIMORE", "ORIOLES"],
    },
    "TEX": {
        "id": 140,
        "color": "#003278",
        "pf": 102,
        "keywords": ["TEX", "RANGERS", "TEXAS RANGERS"],
    },
    "MIN": {
        "id": 142,
        "color": "#002B5C",
        "pf": 100,
        "keywords": ["MIN", "TWINS", "MINNESOTA TWINS"],
    },
    "CWS": {
        "id": 145,
        "color": "#27251F",
        "pf": 101,
        "keywords": ["CWS", "WHITE SOX", "CHICAGO WHITE SOX"],
    },
    "CLE": {
        "id": 114,
        "color": "#0C2340",
        "pf": 98,
        "keywords": ["CLE", "GUARDIANS", "INDIANS", "CLEVELAND"],
    },
    "DET": {
        "id": 116,
        "color": "#0C2340",
        "pf": 97,
        "keywords": ["DET", "TIGERS", "DETROIT TIGERS"],
    },
    "KC": {
        "id": 118,
        "color": "#004687",
        "pf": 103,
        "keywords": ["KC", "KCR", "ROYALS", "KANSAS CITY ROYALS"],
    },
    "LAA": {
        "id": 108,
        "color": "#BA0021",
        "pf": 100,
        "keywords": ["LAA", "ANGELS", "LOS ANGELES ANGELS"],
    },
    "OAK": {
        "id": 133,
        "color": "#003831",
        "pf": 95,
        "keywords": ["OAK", "ATHLETICS", "A'S", "OAKLAND ATHLETICS"],
    },
    "TB": {
        "id": 139,
        "color": "#092C5C",
        "pf": 97,
        "keywords": ["TB", "TBR", "RAYS", "TAMPA BAY RAYS"],
    },
    "AZ": {
        "id": 109,
        "color": "#A71930",
        "pf": 99,
        "keywords": ["AZ", "ARI", "DIAMONDBACKS", "D-BACKS", "ARIZONA"],
    },
    "COL": {
        "id": 115,
        "color": "#333366",
        "pf": 112,
        "keywords": ["COL", "ROCKIES", "COLORADO ROCKIES"],
    },
    "MIA": {
        "id": 146,
        "color": "#00A3E0",
        "pf": 96,
        "keywords": ["MIA", "MARLINS", "MIAMI MARLINS"],
    },
    "MIL": {
        "id": 158,
        "color": "#12284C",
        "pf": 101,
        "keywords": ["MIL", "BREWERS", "MILWAUKEE BREWERS"],
    },
    "CIN": {
        "id": 113,
        "color": "#C6011F",
        "pf": 105,
        "keywords": ["CIN", "REDS", "CINCINNATI REDS"],
    },
    "PIT": {
        "id": 134,
        "color": "#FDB827",
        "pf": 98,
        "keywords": ["PIT", "PIRATES", "PITTSBURGH PIRATES"],
    },
    "STL": {
        "id": 138,
        "color": "#C41E3A",
        "pf": 98,
        "keywords": ["STL", "CARDINALS", "ST. LOUIS CARDINALS"],
    },
    "WSH": {
        "id": 120,
        "color": "#AB0003",
        "pf": 100,
        "keywords": ["WSH", "WAS", "NATIONALS", "WASHINGTON NATIONALS"],
    },
}
DEFAULT_COLOR = "#2E86C1"


def get_team_info(team_name):
    """球団名（フルネーム・略称・エイリアス）からマスター情報を正確に取得"""
    if not team_name:
        return {"id": 1, "color": DEFAULT_COLOR, "pf": 100}
    t_clean = str(team_name).upper().strip()
    for code, info in TEAM_MASTER.items():
        for kw in info["keywords"]:
            if kw == t_clean or kw in t_clean:
                return info
    return {"id": 1, "color": DEFAULT_COLOR, "pf": 100}


def get_team_color(team_name):
    return get_team_info(team_name)["color"]


def get_team_pf(team_name):
    return get_team_info(team_name).get("pf", 100)


def get_team_logo_url(team_name):
    info = get_team_info(team_name)
    t_id = info["id"]
    if t_id == 1:
        return "https://www.mlbstatic.com/team-logos/league-on-dark/1.svg"
    return f"https://www.mlbstatic.com/team-logos/team-cap-on-light/{t_id}.svg"


def render_team_header(team_name, title_text):
    logo_url = get_team_logo_url(team_name)
    color = get_team_color(team_name)
    st.markdown(
        f"""
        <div class="team-header-container" style="border-left: 6px solid {color};">
            <img src="{logo_url}" class="team-logo-img"/>
            <h2 style="margin:0; color: #1a1a1a;">{title_text}</h2>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ------------------------------------------------------------------
# 🌱 プロスペクト・アセット枠の標準価値マッピング
# ------------------------------------------------------------------
PROSPECT_ASSETS = {
    "🏆 ランク1: 超有望株 / Top 10 (+4.5 WAR相当 / 約$36M価値)": 4.5,
    "🌟 ランク2: 有望株 / Top 50 (+3.0 WAR相当 / 約$24M価値)": 3.0,
    "💫 ランク3: 有望株 / Top 100 (+2.0 WAR相当 / 約$16M価値)": 2.0,
    "🌱 ランク4: 組織上位プロスペクト (+1.0 WAR相当 / 約$8M価値)": 1.0,
    "⚾ ランク5: ローカル注目株 (+0.5 WAR相当 / 約$4M価値)": 0.5,
}


def parse_salary_str(val):
    if pd.isna(val):
        return None
    val_str = str(val).strip()
    if "FA" in val_str or "Option" in val_str or val_str == "-" or val_str == "":
        return None

    m_m = re.search(r"\$(\d+(?:\.\d+)?)M", val_str, re.IGNORECASE)
    if m_m:
        return float(m_m.group(1)) * 1_000_000

    m_k = re.search(r"\$(\d+(?:\.\d+)?)k", val_str, re.IGNORECASE)
    if m_k:
        return float(m_k.group(1)) * 1_000

    clean_str = re.sub(r"[^\d.]", "", val_str)
    if clean_str:
        try:
            return float(clean_str)
        except Exception:
            return None
    return None


def clean_player_id(player_id, player_name=None):
    try:
        if pd.notnull(player_id):
            p_str = str(player_id).strip()
            if p_str.replace(".", "", 1).isdigit():
                val = int(float(p_str))
                if val > 0:
                    return val
    except Exception:
        pass

    if player_name:
        conn = sqlite3.connect(DB_PATH)
        query = "SELECT player_id FROM batting_stats WHERE player_name = ? UNION SELECT player_id FROM pitching_stats WHERE player_name = ?"
        try:
            df = pd.read_sql_query(query, conn, params=(player_name, player_name))
            conn.close()
            if not df.empty and pd.notnull(df.iloc[0]["player_id"]):
                return int(df.iloc[0]["player_id"])
        except Exception:
            conn.close()
    return None


# ------------------------------------------------------------------
# 🤖 本番仕様 LLM AI ニュース感情・トレンド分析エンジン
# ------------------------------------------------------------------
@st.cache_data(ttl=3600)
def analyze_news_with_llm(news_text, api_key=None, provider="openai"):
    """LLM API (OpenAI / Gemini) を呼び出してニューステキストから感情スコア・タグ・要約をJSON出力"""
    if not news_text or len(news_text.strip()) < 5:
        return {
            "sentiment_score": 0,
            "sentiment_label": "Neutral 😐",
            "tags": ["📋 一般情報"],
            "impact": "Low",
            "summary": "ニューステキストが指定されていません。",
        }

    if not api_key:
        api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("GEMINI_API_KEY")

    if not api_key:
        text_lower = news_text.lower()
        score = 0
        tags = []
        if any(
            k in text_lower
            for k in [
                "injury",
                "injured",
                "il",
                "surgery",
                "out",
                "怪我",
                "離脱",
                "手術",
            ]
        ):
            score -= 60
            tags.append("⚠️ 故障・IL")
        if any(
            k in text_lower
            for k in [
                "trade",
                "rumor",
                "interest",
                "deal",
                "トレード",
                "移籍",
                "獲得噂",
            ]
        ):
            score += 20
            tags.append("🔥 トレード噂")
        if any(
            k in text_lower
            for k in [
                "sign",
                "extension",
                "contract",
                "dollar",
                "契約",
                "延長",
                "年俸",
            ]
        ):
            score += 40
            tags.append("💰 大型契約")
        if any(
            k in text_lower
            for k in [
                "mvp",
                "hr",
                "win",
                "great",
                "lead",
                "活躍",
                "本塁打",
                "勝利",
            ]
        ):
            score += 50
            tags.append("🏆 絶好調")

        if not tags:
            tags.append("📰 一般トピックス")

        label = (
            "Positive 🔥"
            if score >= 30
            else ("Negative ⚠️" if score <= -30 else "Neutral ⚖️")
        )
        impact = (
            "High" if abs(score) >= 50 else ("Medium" if abs(score) >= 20 else "Low")
        )

        return {
            "sentiment_score": score,
            "sentiment_label": label,
            "tags": tags,
            "impact": impact,
            "summary": (news_text[:120] + "..." if len(news_text) > 120 else news_text),
        }

    try:
        prompt = f"""
        あなたはMLBのゼネラルマネージャー（GM）専門AIアナリストです。
        以下のMLBニュース記事テキストを分析し、厳密なJSON形式のみで出力してください。

        【ニュース本文】
        {news_text}

        【出力フォーマット (JSON strictly)】
        {{
            "sentiment_score": -100から+100の整数 (ポジティブなら正, ネガティブなら負),
            "sentiment_label": "Positive", "Negative", "Neutral" のいずれか,
            "tags": ["⚠️故障・IL", "🔥トレード噂", "💰契約・FA", "🏆大活躍", "🔄編成変更"] から該当するものを最大3つ選択,
            "impact": "Low", "Medium", "High", "Critical" のいずれか,
            "summary": "ニュースの要点を日本語で2~3行で簡潔にまとめ"
        }}
        """

        if provider == "openai":
            import openai

            client = openai.OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.2,
            )
            res_content = response.choices[0].message.content
            return json.loads(res_content)
        else:
            from google import genai

            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )
            clean_json = re.sub(r"```json|```", "", response.text).strip()
            return json.loads(clean_json)

    except Exception as e:
        return {
            "sentiment_score": 0,
            "sentiment_label": "Neutral ⚖️",
            "tags": ["📰 AI解析完了"],
            "impact": "Low",
            "summary": f"ニューステキスト解析完了 (API応答: {str(e)[:50]})",
        }


# ------------------------------------------------------------------
# ⚡ wRC+, FIP, BABIP, K/BB, 指標計算関数
# ------------------------------------------------------------------
def process_war_and_position(df, is_pitcher=False):
    if df.empty:
        return df

    df = df.copy()

    def get_series(col_name, default_val=0):
        if col_name in df.columns:
            return df[col_name]
        return pd.Series(default_val, index=df.index)

    if is_pitcher:
        ip = pd.to_numeric(get_series("inningsPitched", 0.0), errors="coerce").fillna(
            0.0
        )
        era = pd.to_numeric(get_series("era", 4.30), errors="coerce").fillna(4.30)
        hr = pd.to_numeric(get_series("homeRuns", 0), errors="coerce").fillna(0.0)
        bb = pd.to_numeric(
            get_series("baseOnBalls", get_series("walks", 0)), errors="coerce"
        ).fillna(0.0)
        so = pd.to_numeric(get_series("strikeouts", 0), errors="coerce").fillna(0.0)
        h = pd.to_numeric(get_series("hits", 0), errors="coerce").fillna(0.0)
        gs = pd.to_numeric(get_series("gamesStarted", 0), errors="coerce").fillna(0.0)
        gp = pd.to_numeric(
            get_series("gamesPlayed", get_series("games", 1)), errors="coerce"
        ).fillna(1.0)

        fip_val = np.where(
            ip > 0,
            ((13.0 * hr + 3.0 * bb - 2.0 * so) / np.maximum(ip, 0.1)) + 3.10,
            era,
        )
        df["fip"] = np.round(fip_val, 2)
        df["era"] = era

        denom = ip * 2.8 + h - so
        babip_val = np.where(denom > 0, (h - hr) / denom, 0.300)
        df["babip"] = np.round(np.clip(babip_val, 0.200, 0.400), 3)

        df["k_bb"] = np.where(bb > 0, np.round(so / bb, 2), np.round(so, 2))
        df["k_9"] = np.where(ip > 0, np.round((so * 9.0) / ip, 2), 0.0)
        df["bb_9"] = np.where(ip > 0, np.round((bb * 9.0) / ip, 2), 0.0)

        era_num = pd.to_numeric(df["era"], errors="coerce").fillna(4.30)
        fip_num = pd.to_numeric(df["fip"], errors="coerce").fillna(4.30)
        fip_diff = era_num - fip_num

        df["luck_flag"] = np.where(
            fip_diff >= 0.5,
            "不運/補強の狙い目💡",
            np.where(fip_diff <= -0.5, "運が良い/守備に感謝", "標準的"),
        )

        if "war" not in df.columns or df["war"].isnull().all():
            is_sp = ((gs / np.maximum(gp, 1)) >= 0.5) | (gs > 3)
            runs_saved = (4.30 - era) * (ip / 9.0)
            rep_runs_sp = (ip / 180.0) * 9.0
            rep_runs_rp = (ip / 220.0) * 9.0
            war_sp = (runs_saved + rep_runs_sp) / 8.5
            war_rp = (runs_saved + rep_runs_rp) / 10.0
            df["war"] = np.where(is_sp, war_sp, war_rp).round(1)
        else:
            df["war"] = pd.to_numeric(df["war"], errors="coerce").fillna(0.0)

        is_sp = ((gs / np.maximum(gp, 1)) >= 0.5) | (gs > 3)
        df["pos"] = np.where(is_sp, "SP", "RP")

    else:
        ops = pd.to_numeric(get_series("ops", 0.710), errors="coerce").fillna(0.710)
        obp = pd.to_numeric(get_series("obp", 0.315), errors="coerce").fillna(0.315)
        slg = pd.to_numeric(get_series("slg", 0.395), errors="coerce").fillna(0.395)
        pa = pd.to_numeric(get_series("plateAppearances", 0), errors="coerce").fillna(0)
        games = pd.to_numeric(
            get_series("gamesPlayed", get_series("games", 0)), errors="coerce"
        ).fillna(0)

        team_pfs = (
            df["team_name"].apply(get_team_pf) if "team_name" in df.columns else 100
        )
        df["park_factor"] = team_pfs

        woba_val = (obp * 0.7) + (slg * 0.4)
        df["woba"] = np.round(woba_val, 3)

        wrc_raw = (((woba_val - 0.315) / 1.15) + 0.12) / 0.12 * 100
        wrc_plus = wrc_raw * (100.0 / team_pfs)
        df["wrc_plus"] = np.round(np.clip(wrc_plus, 20, 250), 0).astype(int)

        if "war" not in df.columns or df["war"].isnull().all():
            batting_war = (ops - 0.710) * (pa / 12.0)
            rep_war = pa / 600.0
            pos_adj_map = {
                "C": 12.5,
                "SS": 7.5,
                "2B": 2.5,
                "3B": 2.5,
                "CF": 2.5,
                "RF": -7.5,
                "LF": -7.5,
                "1B": -12.5,
                "DH": -17.5,
            }
            pos_val = (
                str(df.get("pos", "DH").iloc[0] if len(df) > 0 else "DH")
                .split(",")[0]
                .strip()
            )
            adj_runs_per_game = pos_adj_map.get(pos_val, -5.0) / 162.0
            pos_war = (games * adj_runs_per_game) / 10.0
            df["war"] = (batting_war + rep_war + pos_war).round(1)
        else:
            df["war"] = pd.to_numeric(df["war"], errors="coerce").fillna(0.0)

        if "pos" not in df.columns:
            df["pos"] = "DH"
        else:
            df["pos"] = df["pos"].fillna("DH")

    return df


# ------------------------------------------------------------------
# ⚡ 修正: 故障リスク判定（10年選手などの長期キャリアとIL精度の適正化）
# ------------------------------------------------------------------
def calculate_durability_metrics(player_id, player_name=None):
    clean_id = clean_player_id(player_id, player_name)
    df_b, df_p = get_player_history(clean_id, player_name)
    seasons_3yr = [2026, 2025, 2024]

    games_list = []
    ip_list = []

    if not df_b.empty:
        sub_b = df_b[df_b["season"].isin(seasons_3yr)]
        for _, r in sub_b.iterrows():
            games_list.append(
                pd.to_numeric(r.get("gamesPlayed", r.get("games", 0)), errors="coerce")
                or 0
            )

    if not df_p.empty:
        sub_p = df_p[df_p["season"].isin(seasons_3yr)]
        for _, r in sub_p.iterrows():
            ip_list.append(
                pd.to_numeric(r.get("inningsPitched", 0), errors="coerce") or 0.0
            )

    avg_games = np.mean(games_list) if games_list else 0.0
    avg_ip = np.mean(ip_list) if ip_list else 0.0

    # キャリア通算シーズン数のカウント
    career_seasons = len(
        set(df_b["season"].tolist() if not df_b.empty else []).union(
            set(df_p["season"].tolist() if not df_p.empty else [])
        )
    )
    career_seasons = max(career_seasons, 1)

    # 1. 公示データからの純粋なIL登録数の高精度抽出
    # (オプション/マイナー降格、忌引・出産休暇・ウェーバー等を除外し、純粋な故障者リスト表記のみを限定検知)
    df_trans = get_player_transactions(clean_id)
    il_count = 0
    if not df_trans.empty:
        combined_text = (
            df_trans.astype(str).apply(lambda x: " ".join(x), axis=1).str.upper()
        )
        # 厳密なIL登録・IL追加のキーワード表記のみを検出
        il_mask = combined_text.str.contains(
            r"\bPLACED\s+ON\s+(THE\s+)?(\d+-DAY|\d+\s+DAY)?\s*(INJURED|DISABLED)\s+LIST\b|\bINJURED\s+LIST\b|\bDISABLED\s+LIST\b|\b\d+-DAY\s+IL\b|\b60-DAY\s+IL\b|\b15-DAY\s+IL\b|\b10-DAY\s+IL\b|\b7-DAY\s+IL\b",
            regex=True,
        )
        il_count = il_mask.sum()

    # 2. 通算プレイ年数を考慮した1シーズンあたり平均IL回数算定 (10年で5〜6回程度は低〜標準リスク領域へ)
    il_per_season = il_count / career_seasons
    is_pitcher_main = (avg_ip > 0 and not ip_list) or (avg_ip > avg_games)

    # 判定の最適化: 長期キャリア（10年等）の選手が通算5-6回程度のILであればリスク低に分類
    if il_count >= 5 and il_per_season >= 0.8:
        risk_flag = f"⚠️ 故障リスク高 (通算IL {il_count}回)"
        is_high_risk = True
    elif il_count >= 2 or (il_count >= 1 and career_seasons <= 2):
        risk_flag = f"🟡 故障歴あり (通算IL {il_count}回)"
        is_high_risk = False
    elif (is_pitcher_main and avg_ip < 60.0 and avg_ip > 0) or (
        not is_pitcher_main and avg_games < 80.0 and avg_games > 0
    ):
        risk_flag = "⚠️ 稼働数不足 (故障懸念)"
        is_high_risk = True
    else:
        risk_flag = f"✅ 故障リスク低 (健全/通算IL {il_count}回)"
        is_high_risk = False

    # 3. 安定度スコア (0~100)
    if is_pitcher_main:
        stability_score = min(int((avg_ip / 180.0) * 100), 100)
    else:
        stability_score = min(int((avg_games / 140.0) * 100), 100)

    return {
        "score": stability_score,
        "avg_games": round(avg_games, 1),
        "avg_ip": round(avg_ip, 1),
        "risk_flag": risk_flag,
        "is_high_risk": is_high_risk,
        "il_count": il_count,
    }


def get_player_primary_positions(player_id, df_b_all, df_p_all):
    p_id_clean = clean_player_id(player_id)
    p_sub = (
        df_p_all[df_p_all["player_id"] == p_id_clean]
        if not df_p_all.empty and p_id_clean
        else pd.DataFrame()
    )
    b_sub = (
        df_b_all[df_b_all["player_id"] == p_id_clean]
        if not df_b_all.empty and p_id_clean
        else pd.DataFrame()
    )

    b_games = (
        pd.to_numeric(b_sub.get("gamesPlayed", b_sub.get("games", 0)), errors="coerce")
        .fillna(0)
        .sum()
        if not b_sub.empty
        else 0
    )
    p_games = (
        pd.to_numeric(p_sub.get("gamesPlayed", p_sub.get("games", 0)), errors="coerce")
        .fillna(0)
        .sum()
        if not p_sub.empty
        else 0
    )

    player_name = ""
    if not b_sub.empty and "player_name" in b_sub.columns:
        player_name = str(b_sub.iloc[0]["player_name"])
    elif not p_sub.empty and "player_name" in p_sub.columns:
        player_name = str(p_sub.iloc[0]["player_name"])

    def judge_sp_or_rp(p_df):
        tot_gs = (
            pd.to_numeric(p_df.get("gamesStarted", 0), errors="coerce").fillna(0).sum()
        )
        tot_gp = (
            pd.to_numeric(
                p_df.get("gamesPlayed", p_df.get("games", 1)), errors="coerce"
            )
            .fillna(0)
            .sum()
        )
        tot_ip = (
            pd.to_numeric(p_df.get("inningsPitched", 0), errors="coerce")
            .fillna(0)
            .sum()
        )
        if (tot_gp > 0 and (tot_gs / tot_gp) >= 0.5) or (
            tot_gs >= 5 and (tot_gp > 0 and tot_ip / tot_gp >= 3.0)
        ):
            return "SP"
        return "RP"

    def extract_field_positions(b_df):
        if b_df.empty:
            return "DH"
        pos_counts = {}
        for _, row in b_df.iterrows():
            p_val = row.get("pos")
            if pd.isna(p_val):
                continue
            p_str = str(p_val).strip()
            gp = (
                pd.to_numeric(
                    row.get("gamesPlayed", row.get("games", 1)), errors="coerce"
                )
                or 1
            )
            for pos_item in p_str.split(","):
                clean_item = pos_item.strip()
                if clean_item and clean_item not in [
                    "P",
                    "TWP",
                    "DH",
                    "None",
                    "nan",
                    "",
                ]:
                    pos_counts[clean_item] = pos_counts.get(clean_item, 0) + gp

        if not pos_counts:
            return "DH"
        sorted_positions = [
            k
            for k, v in sorted(
                pos_counts.items(), key=lambda item: item[1], reverse=True
            )
        ]
        return ", ".join(sorted_positions)

    if "Shohei Ohtani" in player_name or "Ohtani" in player_name:
        return "P/DH"
    if p_games > b_games:
        return judge_sp_or_rp(p_sub)
    if b_games > 0:
        return extract_field_positions(b_sub)

    return "DH"


# ------------------------------------------------------------------
# ⚡ キャッシュ最適化処理（st.cache_data）
# ------------------------------------------------------------------
@st.cache_data(ttl=3600)
def get_seasons():
    conn = sqlite3.connect(DB_PATH)
    try:
        q = "SELECT DISTINCT season FROM batting_stats UNION SELECT DISTINCT season FROM pitching_stats ORDER BY season DESC"
        seasons = pd.read_sql_query(q, conn)["season"].dropna().astype(int).tolist()
    except Exception:
        seasons = [2026, 2025, 2024, 2023, 2022, 2021, 2020, 2019, 2018, 2017]
    conn.close()
    return seasons


@st.cache_data(ttl=3600)
def get_all_players():
    conn = sqlite3.connect(DB_PATH)
    query = """
        SELECT DISTINCT player_id, player_name FROM batting_stats WHERE player_name IS NOT NULL
        UNION
        SELECT DISTINCT player_id, player_name FROM pitching_stats WHERE player_name IS NOT NULL
        ORDER BY player_name
    """
    try:
        df_p = pd.read_sql_query(query, conn)
    except Exception:
        df_p = pd.DataFrame(columns=["player_id", "player_name"])
    conn.close()
    return df_p


@st.cache_data(ttl=3600)
def get_teams_by_season(season):
    conn = sqlite3.connect(DB_PATH)
    query = """
        SELECT DISTINCT team_name FROM batting_stats WHERE season = ? AND team_name IS NOT NULL
        UNION
        SELECT DISTINCT team_name FROM pitching_stats WHERE season = ? AND team_name IS NOT NULL
        ORDER BY 1
    """
    try:
        df_teams = pd.read_sql_query(query, conn, params=(season, season))
        teams = df_teams.iloc[:, 0].dropna().tolist()
    except Exception:
        teams = []
    conn.close()
    return teams


@st.cache_data(ttl=3600)
def get_roster_by_season(team_name, season):
    conn = sqlite3.connect(DB_PATH)
    query_b = "SELECT DISTINCT player_id, player_name FROM batting_stats WHERE season = ? AND team_name = ?"
    query_p = "SELECT DISTINCT player_id, player_name FROM pitching_stats WHERE season = ? AND team_name = ?"

    df_b = pd.read_sql_query(query_b, conn, params=(season, team_name))
    df_p = pd.read_sql_query(query_p, conn, params=(season, team_name))
    conn.close()

    df_combined = pd.concat([df_b, df_p]).drop_duplicates(subset=["player_id"])
    return df_combined.sort_values(by="player_name")


@st.cache_data(ttl=1800)
def get_roster_depth_data(team_name, season):
    conn = sqlite3.connect(DB_PATH)

    q_b = "SELECT * FROM batting_stats WHERE team_name = ? AND season = ?"
    q_p = "SELECT * FROM pitching_stats WHERE team_name = ? AND season = ?"

    df_b = pd.read_sql_query(q_b, conn, params=(team_name, season))
    df_p = pd.read_sql_query(q_p, conn, params=(team_name, season))
    conn.close()

    df_b = process_war_and_position(df_b, is_pitcher=False)
    df_p = process_war_and_position(df_p, is_pitcher=True)

    if not df_b.empty:
        df_b["games"] = (
            df_b["gamesPlayed"]
            if "gamesPlayed" in df_b.columns
            else df_b.get("games", 0)
        )

    if not df_p.empty:
        df_p["games"] = (
            df_p["gamesPlayed"]
            if "gamesPlayed" in df_p.columns
            else df_p.get("games", 0)
        )

    df_all = pd.concat([df_b, df_p], ignore_index=True)
    return df_all


# ------------------------------------------------------------------
# ⚡ チームのポジション別合計スタッツからWARを算定する専用関数
# ------------------------------------------------------------------
def calc_positional_war_from_team_stats(df_b, df_p):
    """
    ポジションごとの単純な個人の足し算ではなく、
    チーム・ポジションごとの合計スタッツからセイバーメトリクスで正確にWARを計算する
    """
    pos_map_b = {
        "C": "C",
        "1B": "1B",
        "2B": "2B",
        "3B": "3B",
        "SS": "SS",
        "LF": "LF",
        "CF": "CF",
        "RF": "RF",
        "OF": "CF",
        "DH": "DH",
    }
    pos_map_p = {"SP": "SP", "RP": "RP", "P": "RP"}

    pos_rows = []

    if not df_b.empty:
        df_b_work = df_b.copy()
        df_b_work["norm_pos"] = df_b_work["pos"].map(pos_map_b).fillna("DH")
        for (t_name, norm_pos), group in df_b_work.groupby(["team_name", "norm_pos"]):
            pa_tot = pd.to_numeric(
                group.get("plateAppearances", 0), errors="coerce"
            ).sum()
            games_tot = pd.to_numeric(
                group.get("gamesPlayed", group.get("games", 0)), errors="coerce"
            ).sum()

            if pa_tot > 0:
                ops_avg = (
                    pd.to_numeric(group.get("ops", 0.710), errors="coerce")
                    * pd.to_numeric(group.get("plateAppearances", 1), errors="coerce")
                ).sum() / pa_tot
            else:
                ops_avg = 0.710

            batting_war = (ops_avg - 0.710) * (pa_tot / 12.0)
            rep_war = pa_tot / 600.0

            pos_adj_map = {
                "C": 12.5,
                "SS": 7.5,
                "2B": 2.5,
                "3B": 2.5,
                "CF": 2.5,
                "RF": -7.5,
                "LF": -7.5,
                "1B": -12.5,
                "DH": -17.5,
            }
            adj_runs = pos_adj_map.get(norm_pos, -5.0) / 162.0
            pos_war = (games_tot * adj_runs) / 10.0
            calc_war = round(batting_war + rep_war + pos_war, 1)

            pos_rows.append(
                {"team_name": t_name, "norm_pos": norm_pos, "war": calc_war}
            )

    if not df_p.empty:
        df_p_work = df_p.copy()
        df_p_work["norm_pos"] = df_p_work["pos"].map(pos_map_p).fillna("RP")
        for (t_name, norm_pos), group in df_p_work.groupby(["team_name", "norm_pos"]):
            ip_tot = pd.to_numeric(
                group.get("inningsPitched", 0), errors="coerce"
            ).sum()
            if ip_tot > 0:
                er_tot = pd.to_numeric(
                    group.get("earnedRuns", 0), errors="coerce"
                ).sum()
                era_avg = (
                    (er_tot * 9.0) / ip_tot
                    if er_tot > 0
                    else pd.to_numeric(group.get("era", 4.30), errors="coerce").mean()
                )
            else:
                era_avg = 4.30

            runs_saved = (4.30 - era_avg) * (ip_tot / 9.0)
            rep_runs = (
                (ip_tot / 180.0) * 9.0 if norm_pos == "SP" else (ip_tot / 220.0) * 9.0
            )
            div_val = 8.5 if norm_pos == "SP" else 10.0
            calc_war = round((runs_saved + rep_runs) / div_val, 1)

            pos_rows.append(
                {"team_name": t_name, "norm_pos": norm_pos, "war": calc_war}
            )

    if not pos_rows:
        return pd.DataFrame()

    df_res = pd.DataFrame(pos_rows)
    return df_res.groupby(["team_name", "norm_pos"])["war"].sum().reset_index()


@st.cache_data(ttl=3600)
def get_all_teams_positional_war(season):
    conn = sqlite3.connect(DB_PATH)
    q_b = "SELECT * FROM batting_stats WHERE season = ? AND team_name IS NOT NULL"
    q_p = "SELECT * FROM pitching_stats WHERE season = ? AND team_name IS NOT NULL"
    try:
        df_b = pd.read_sql_query(q_b, conn, params=(season,))
        df_p = pd.read_sql_query(q_p, conn, params=(season,))
    except Exception:
        df_b = pd.DataFrame()
        df_p = pd.DataFrame()
    conn.close()

    if df_b.empty and df_p.empty:
        return pd.DataFrame()

    df_b = process_war_and_position(df_b, is_pitcher=False)
    df_p = process_war_and_position(df_p, is_pitcher=True)

    return calc_positional_war_from_team_stats(df_b, df_p)


@st.cache_data(ttl=1800)
def get_player_history(player_id, player_name=None):
    p_id_clean = clean_player_id(player_id, player_name)
    conn = sqlite3.connect(DB_PATH)

    if p_id_clean:
        query_b = "SELECT * FROM batting_stats WHERE CAST(player_id AS TEXT) = ? ORDER BY season DESC"
        query_p = "SELECT * FROM pitching_stats WHERE CAST(player_id AS TEXT) = ? ORDER BY season DESC"
        df_b = pd.read_sql_query(query_b, conn, params=(str(p_id_clean),))
        df_p = pd.read_sql_query(query_p, conn, params=(str(p_id_clean),))
    elif player_name:
        query_b = (
            "SELECT * FROM batting_stats WHERE player_name = ? ORDER BY season DESC"
        )
        query_p = (
            "SELECT * FROM pitching_stats WHERE player_name = ? ORDER BY season DESC"
        )
        df_b = pd.read_sql_query(query_b, conn, params=(player_name,))
        df_p = pd.read_sql_query(query_p, conn, params=(player_name,))
    else:
        df_b, df_p = pd.DataFrame(), pd.DataFrame()

    conn.close()

    df_b = process_war_and_position(df_b, is_pitcher=False)
    df_p = process_war_and_position(df_p, is_pitcher=True)

    return df_b, df_p


def get_player_transactions(player_id):
    p_id_clean = clean_player_id(player_id)
    if not p_id_clean:
        return pd.DataFrame()

    conn = sqlite3.connect(DB_PATH)
    query = "SELECT date, type, description, from_team, to_team FROM transactions WHERE CAST(player_id AS TEXT) = ? ORDER BY date DESC"
    try:
        df_trans = pd.read_sql_query(query, conn, params=(str(p_id_clean),))
    except Exception:
        df_trans = pd.DataFrame()
    conn.close()
    return df_trans


# ------------------------------------------------------------------
# ⚡ データベースクエリ関数の正規化DB対応アップデート
# ------------------------------------------------------------------
def get_player_contracts(player_id, player_name=None):
    p_id_clean = clean_player_id(player_id, player_name)
    conn = sqlite3.connect(DB_PATH)

    # 後方互換ビュー V_contracts_legacy または 旧contractsテーブルからの柔軟フォールバック
    if p_id_clean:
        query = "SELECT season, salary, aav, service_time, contract_years, free_agent_year, contract_status, option_type, buyout FROM V_contracts_legacy WHERE CAST(player_id AS TEXT) = ? ORDER BY season DESC"
        params = (str(p_id_clean),)
    elif player_name:
        query = "SELECT season, salary, aav, service_time, contract_years, free_agent_year, contract_status, option_type, buyout FROM V_contracts_legacy WHERE player_name = ? ORDER BY season DESC"
        params = (player_name,)
    else:
        conn.close()
        return pd.DataFrame()

    try:
        df_contract = pd.read_sql_query(query, conn, params=params)
    except Exception:
        # 新ビューが未作成の場合は旧テーブルから取得
        try:
            query_old = "SELECT season, salary, aav, service_time, contract_years, free_agent_year, contract_status FROM contracts WHERE CAST(player_id AS TEXT) = ? ORDER BY season DESC"
            df_contract = pd.read_sql_query(query_old, conn, params=params)
        except Exception:
            df_contract = pd.DataFrame()

    if not df_contract.empty:
        df_contract = df_contract.sort_values(
            by=["season", "salary"], ascending=[False, False]
        )
        df_contract = df_contract.drop_duplicates(subset=["season"], keep="first")

    conn.close()
    return df_contract


def save_player_contracts(player_id, player_name, edited_df):
    """新・正規化テーブル (contracts_master & contract_details) への保存対応"""
    p_id_clean = clean_player_id(player_id, player_name)
    if not p_id_clean:
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 旧契約テーブルのクリーンアップ
    try:
        cursor.execute(
            "DELETE FROM contracts WHERE CAST(player_id AS TEXT) = ? OR player_name = ?",
            (str(p_id_clean), player_name),
        )
    except Exception:
        pass

    # 新契約マスターの取得または作成
    cursor.execute(
        "SELECT contract_id FROM contracts_master WHERE player_id = ?",
        (int(p_id_clean),),
    )
    row = cursor.fetchone()
    if row:
        contract_id = row[0]
    else:
        cursor.execute(
            "INSERT INTO contracts_master (player_id, contract_status, service_time, free_agent_year) VALUES (?, ?, ?, ?)",
            (int(p_id_clean), "1 yr", "0.000", 2027),
        )
        contract_id = cursor.lastrowid

    # 年別詳細の保存
    for _, row_item in edited_df.iterrows():
        season_val = row_item.get("season")
        if pd.notnull(season_val):
            sal_val = row_item.get("salary", MLB_MINIMUM_SALARY)
            aav_val = row_item.get("aav", sal_val)
            opt_val = row_item.get("option_type", "None")

            cursor.execute(
                """
                INSERT OR REPLACE INTO contract_details 
                (contract_id, season, salary, aav, option_type, buyout, incentive)
                VALUES (?, ?, ?, ?, ?, 0.0, 0.0)
            """,
                (
                    int(contract_id),
                    int(season_val),
                    float(sal_val) if pd.notnull(sal_val) else 780000.0,
                    float(aav_val) if pd.notnull(aav_val) else 780000.0,
                    str(opt_val),
                ),
            )

    conn.commit()
    conn.close()


def get_team_reinforcements(team_name, season):
    conn = sqlite3.connect(DB_PATH)

    query = """
        SELECT date as 日付, type as 種別, player_name as 選手名, from_team as 旧所属, to_team as 新所属, description as 詳細
        FROM team_transactions 
        WHERE (from_team = ? OR to_team = ?) AND season = ?
        ORDER BY date DESC
    """
    try:
        df = pd.read_sql_query(query, conn, params=(team_name, team_name, season))
    except Exception:
        df = pd.DataFrame()

    def classify_transaction(row):
        t_type = str(row["種別"]).lower()

        if "assigned" in t_type:
            return "OTHER", "OTHER"

        is_to_me = row["新所属"] == team_name
        is_from_me = row["旧所属"] == team_name

        direction = "OTHER"
        if is_to_me and any(
            k in t_type for k in ["signed", "claimed", "trade", "traded"]
        ):
            direction = "IN"
        elif is_from_me and any(
            k in t_type
            for k in ["claimed", "trade", "traded", "released", "designated"]
        ):
            direction = "OUT"

        category = "OTHER"
        if "trade" in t_type or "traded" in t_type:
            category = "Trade"
        elif "signed" in t_type or "free agent" in t_type or "fa" in t_type:
            category = "FA"
        elif "claimed" in t_type or "released" in t_type or "designated" in t_type:
            category = "OTHER"

        return direction, category

    if not df.empty:
        results = df.apply(classify_transaction, axis=1)
        df["区分"] = [r[0] for r in results]
        df["カテゴリ"] = [r[1] for r in results]
    else:
        df = pd.DataFrame(
            columns=[
                "日付",
                "種別",
                "選手名",
                "旧所属",
                "新所属",
                "詳細",
                "区分",
                "カテゴリ",
            ]
        )

    fa_departures = []
    try:
        q_current = f"""
            SELECT DISTINCT player_id, player_name FROM batting_stats WHERE season = {season} AND team_name = '{team_name}'
            UNION
            SELECT DISTINCT player_id, player_name FROM pitching_stats WHERE season = {season} AND team_name = '{team_name}'
        """
        q_next = f"""
            SELECT DISTINCT player_id, team_name FROM batting_stats WHERE season = {season + 1}
            UNION
            SELECT DISTINCT player_id, team_name FROM pitching_stats WHERE season = {season + 1}
        """

        df_curr = pd.read_sql_query(q_current, conn)
        df_next = pd.read_sql_query(q_next, conn)

        if not df_curr.empty:
            for _, p in df_curr.iterrows():
                p_id = p["player_id"]
                p_name = p["player_name"]

                next_teams = df_next[df_next["player_id"] == p_id]["team_name"].tolist()

                if team_name not in next_teams:
                    already_logged = not df[
                        (df["選手名"] == p_name) & (df["区分"] == "OUT")
                    ].empty

                    if not already_logged:
                        fa_departures.append(
                            {
                                "日付": f"{season}-11-01 (オフシーズン)",
                                "種別": "FA Departure",
                                "選手名": p_name,
                                "旧所属": team_name,
                                "新所属": (
                                    next_teams[0] if next_teams else "FA / 未所属"
                                ),
                                "詳細": f"{season}年シーズン終了に伴うFA権行使・退団",
                                "区分": "OUT",
                                "カテゴリ": "FA",
                            }
                        )
    except Exception:
        pass

    conn.close()

    if fa_departures:
        df_fa = pd.DataFrame(fa_departures)
        df = pd.concat([df, df_fa], ignore_index=True)

    return df


@st.cache_data(ttl=3600)
def get_fa_players_by_year(target_year=2027):
    conn = sqlite3.connect(DB_PATH)

    try:
        df_contracts = pd.read_sql_query(
            "SELECT DISTINCT player_id, player_name, free_agent_year FROM contracts WHERE CAST(free_agent_year AS INTEGER) = ?",
            conn,
            params=(target_year,),
        )
    except Exception:
        df_contracts = pd.DataFrame()

    df_b = pd.read_sql_query("SELECT * FROM batting_stats", conn)
    df_p = pd.read_sql_query("SELECT * FROM pitching_stats", conn)

    conn.close()

    if df_contracts.empty:
        return pd.DataFrame(
            columns=[
                "player_id",
                "所属チーム",
                "ポジション",
                "選手名",
                "通算WAR",
                "故障リスク",
                "安定度スコア",
            ]
        )

    df_b_proc = process_war_and_position(df_b, is_pitcher=False)
    df_p_proc = process_war_and_position(df_p, is_pitcher=True)

    b_war_tot = (
        df_b_proc.groupby("player_id")["war"].sum()
        if not df_b_proc.empty
        else pd.Series()
    )
    p_war_tot = (
        df_p_proc.groupby("player_id")["war"].sum()
        if not df_p_proc.empty
        else pd.Series()
    )

    fa_list = []
    for _, row in df_contracts.iterrows():
        p_name = row["player_name"]
        p_id = clean_player_id(row.get("player_id"), p_name)

        tot_war = round(
            float(b_war_tot.get(p_id, 0.0)) + float(p_war_tot.get(p_id, 0.0)), 1
        )

        b_sub = (
            df_b_proc[df_b_proc["player_id"] == p_id].sort_values(
                "season", ascending=False
            )
            if not df_b_proc.empty and p_id
            else pd.DataFrame()
        )
        p_sub = (
            df_p_proc[df_p_proc["player_id"] == p_id].sort_values(
                "season", ascending=False
            )
            if not df_p_proc.empty and p_id
            else pd.DataFrame()
        )

        latest_team = "FA / 未所属"
        if not b_sub.empty and not p_sub.empty:
            latest_team = (
                b_sub.iloc[0]["team_name"]
                if b_sub.iloc[0]["season"] >= p_sub.iloc[0]["season"]
                else p_sub.iloc[0]["team_name"]
            )
        elif not b_sub.empty:
            latest_team = b_sub.iloc[0]["team_name"]
        elif not p_sub.empty:
            latest_team = p_sub.iloc[0]["team_name"]

        correct_pos = get_player_primary_positions(p_id, df_b, df_p)
        dur_metrics = calculate_durability_metrics(p_id, p_name)

        fa_list.append(
            {
                "player_id": p_id,
                "所属チーム": latest_team,
                "ポジション": correct_pos,
                "選手名": p_name,
                "通算WAR": tot_war,
                "故障リスク": dur_metrics["risk_flag"],
                "安定度スコア": f"{dur_metrics['score']} / 100",
            }
        )

    df_res = pd.DataFrame(fa_list).sort_values(by="通算WAR", ascending=False)
    return df_res


@st.cache_data(ttl=3600)
def get_team_future_payrolls():
    conn = sqlite3.connect(DB_PATH)

    query = """
        WITH latest_team AS (
            SELECT player_id, player_name, team_name FROM batting_stats WHERE season = 2026 AND team_name IS NOT NULL
            UNION
            SELECT player_id, player_name, team_name FROM pitching_stats WHERE season = 2026 AND team_name IS NOT NULL
        )
        SELECT 
            lt.team_name,
            c.player_id,
            c.player_name,
            c.salary,
            c.aav,
            c.free_agent_year
        FROM contracts c
        JOIN latest_team lt ON c.player_id = lt.player_id
        WHERE c.season = 2026
    """
    try:
        df_db_2026 = pd.read_sql_query(query, conn)
    except Exception:
        df_db_2026 = pd.DataFrame()
    conn.close()

    try:
        df_csv = pd.read_csv(CSV_PATH)
    except Exception:
        df_csv = pd.DataFrame()

    if df_db_2026.empty:
        return pd.DataFrame()

    csv_salary_map = {}
    if not df_csv.empty and "Name" in df_csv.columns:
        year_cols = [str(y) for y in range(2026, 2031) if str(y) in df_csv.columns]
        for _, row in df_csv.iterrows():
            p_name = str(row["Name"]).strip()
            csv_salary_map[p_name] = {}
            for y_col in year_cols:
                parsed_val = parse_salary_str(row[y_col])
                if parsed_val is not None:
                    csv_salary_map[p_name][int(y_col)] = parsed_val

    future_rows = []
    for yr in range(2026, 2031):
        for _, row in df_db_2026.iterrows():
            p_name = row["player_name"]
            team_name = row["team_name"]
            p_id = clean_player_id(row.get("player_id"), p_name)
            fa_yr = row.get("free_agent_year")

            sal = None
            if p_name in csv_salary_map and yr in csv_salary_map[p_name]:
                sal = csv_salary_map[p_name][yr]
            elif pd.notnull(fa_yr) and yr < float(fa_yr):
                sal = (
                    row["aav"]
                    if pd.notnull(row.get("aav")) and row["aav"] > 0
                    else row.get("salary", MLB_MINIMUM_SALARY)
                )

            if sal is not None and sal > 0:
                future_rows.append(
                    {
                        "team_name": team_name,
                        "player_id": p_id,
                        "player_name": p_name,
                        "season": yr,
                        "salary": sal,
                    }
                )

    df_future = pd.DataFrame(future_rows)
    if df_future.empty:
        return pd.DataFrame()

    df_summary = (
        df_future.groupby(["team_name", "season"])
        .agg(
            total_payroll=("salary", "sum"),
            contracted_players=("player_id", "nunique"),
        )
        .reset_index()
    )

    return df_summary


# ------------------------------------------------------------------
# 📱 3. モーダルダイアログ機能 (st.dialog)
# ------------------------------------------------------------------
@st.dialog("👤 選手プロフィール・詳細カード")
def show_player_modal(player_id, player_name):
    """選手詳細情報をモーダル表示するダイアログ関数"""
    clean_id = clean_player_id(player_id, player_name)
    df_b_hist, df_p_hist = get_player_history(clean_id, player_name)
    df_contracts = get_player_contracts(clean_id, player_name)
    pos_summary = get_player_primary_positions(clean_id, df_b_hist, df_p_hist)
    dur_metrics = calculate_durability_metrics(clean_id, player_name)

    img_id_str = str(clean_id) if clean_id else "generic"
    img_url = f"https://img.mlbstatic.com/mlb-photos/image/upload/d_people:generic:headshot:silo:current.png/w_400,q_auto:best/v1/people/{img_id_str}/headshot/silo/current"

    col_img, col_info = st.columns([1, 2])
    with col_img:
        st.image(img_url, use_container_width=True, caption=player_name)
    with col_info:
        st.subheader(player_name)
        st.caption(
            f"主要ポジション: **{pos_summary}** | MLB ID: {clean_id if clean_id else 'N/A'}"
        )

        st.markdown(
            f"**🏃 安定度スコア:** `{dur_metrics['score']}/100` （直近3年平均: `{dur_metrics['avg_games']}試合` / `{dur_metrics['avg_ip']} IP`）"
        )
        st.markdown(f"**🏥 故障リスク判定:** {dur_metrics['risk_flag']}")

        st.markdown("---")

        if not df_contracts.empty:
            c_row = df_contracts.iloc[0]
            sal = c_row.get("salary", MLB_MINIMUM_SALARY)
            fa = c_row.get("free_agent_year", "-")
            status = c_row.get("contract_status", "1 yr")
            st.markdown(f"**契約状況:** {status}")
            st.markdown(
                f"**今期年俸:** ${sal:,.0f}" if pd.notnull(sal) else "**今期年俸:** -"
            )
            st.markdown(f"**FA予定:** {fa} 年" if pd.notnull(fa) else "**FA予定:** -")
        else:
            st.markdown(f"**推定年俸:** ${MLB_MINIMUM_SALARY:,.0f} (最低保証)")

    st.divider()

    b_war = df_b_hist["war"].sum() if not df_b_hist.empty else 0.0
    p_war = df_p_hist["war"].sum() if not df_p_hist.empty else 0.0
    tot_war = b_war + p_war

    m1, m2, m3 = st.columns(3)
    with m1:
        render_card("打撃通算 WAR", f"{b_war:.1f}")
    with m2:
        render_card("投手通算 WAR", f"{p_war:.1f}")
    with m3:
        render_card("合計通算 WAR", f"{tot_war:.1f}", border_color="#ffc107")

    st.write("#### 📊 セイバーメトリクス & 直近成績 (最新シーズン)")
    if not df_b_hist.empty:
        latest_b = df_b_hist.iloc[0]
        st.caption("【最新 打撃高度指標 (wRC+ & 球場補正)】")
        b_cols = [
            c
            for c in [
                "season",
                "team_name",
                "avg",
                "obp",
                "slg",
                "ops",
                "wrc_plus",
                "woba",
                "park_factor",
                "homeRuns",
                "war",
            ]
            if c in df_b_hist.columns
        ]
        st.dataframe(
            pd.DataFrame([latest_b[b_cols]]).rename(
                columns={"wrc_plus": "wRC+", "park_factor": "PF"}
            ),
            hide_index=True,
            use_container_width=True,
        )

    if not df_p_hist.empty:
        latest_p = df_p_hist.iloc[0]
        st.caption("【最新 投手高度指標 (FIP & 運・守備評価)】")
        p_cols = [
            c
            for c in [
                "season",
                "team_name",
                "era",
                "fip",
                "babip",
                "luck_flag",
                "k_bb",
                "inningsPitched",
                "strikeouts",
                "war",
            ]
            if c in df_p_hist.columns
        ]
        st.dataframe(
            pd.DataFrame([latest_p[p_cols]]).rename(
                columns={
                    "era": "ERA",
                    "fip": "FIP",
                    "babip": "BABIP",
                    "luck_flag": "運/守備評価",
                    "k_bb": "K/BB",
                }
            ),
            hide_index=True,
            use_container_width=True,
        )


# --- チーム比較ダッシュボード描画用関数 ---
def render_team_comparison_dashboard(selected_season):
    st.header("📊 チーム分析・比較ダッシュボード")

    conn = sqlite3.connect(DB_PATH)

    q_b = f"SELECT * FROM batting_stats WHERE season = {selected_season} AND team_name IS NOT NULL"
    q_p = f"SELECT * FROM pitching_stats WHERE season = {selected_season} AND team_name IS NOT NULL"

    try:
        df_b = pd.read_sql_query(q_b, conn)
    except Exception:
        df_b = pd.DataFrame()

    try:
        df_p = pd.read_sql_query(q_p, conn)
    except Exception:
        df_p = pd.DataFrame()

    conn.close()

    if df_b.empty and df_p.empty:
        st.warning(f"{selected_season}年のチームスタッツデータが見つかりませんでした。")
        return

    teams_b = df_b["team_name"].unique().tolist() if not df_b.empty else []
    teams_p = df_p["team_name"].unique().tolist() if not df_p.empty else []
    all_teams = sorted(list(set(teams_b + teams_p)))

    tab1, tab2 = st.tabs(["⚔️ 2チーム直接比較", "📈 チーム構造・年齢層分析"])

    # ---------------------------------------------------------
    # Tab 1: 2チーム直接比較（レーダーチャート）
    # ---------------------------------------------------------
    with tab1:
        st.subheader(f"⚔️ 2チーム能力レーダーチャート比較 ({selected_season}年)")

        col1, col2 = st.columns(2)
        with col1:
            team_a = st.selectbox(
                "チームAを選択", all_teams, index=0, key="comp_team_a"
            )
        with col2:
            default_b_idx = 1 if len(all_teams) > 1 else 0
            team_b = st.selectbox(
                "チームBを選択", all_teams, index=default_b_idx, key="comp_team_b"
            )

        if team_a and team_b:
            color_a = get_team_color(team_a)
            color_b = get_team_color(team_b)

            def get_team_summary(t_name):
                b_sub = (
                    df_b[df_b["team_name"] == t_name]
                    if not df_b.empty
                    else pd.DataFrame()
                )
                p_sub = (
                    df_p[df_p["team_name"] == t_name]
                    if not df_p.empty
                    else pd.DataFrame()
                )

                if not b_sub.empty:
                    tot_hits = pd.to_numeric(
                        b_sub.get("hits", 0), errors="coerce"
                    ).sum()
                    tot_ab = pd.to_numeric(
                        b_sub.get("atBats", 0), errors="coerce"
                    ).sum()
                    avg = (
                        (tot_hits / tot_ab)
                        if tot_ab > 0
                        else (
                            pd.to_numeric(
                                b_sub.get("avg", 0.250), errors="coerce"
                            ).mean()
                        )
                    )
                else:
                    avg = 0.250

                hr = (
                    pd.to_numeric(b_sub.get("homeRuns", 0), errors="coerce").sum()
                    if not b_sub.empty
                    else 0
                )
                runs = (
                    pd.to_numeric(b_sub.get("runs", 0), errors="coerce").sum()
                    if not b_sub.empty
                    else 0
                )
                sb = (
                    pd.to_numeric(b_sub.get("stolenBases", 0), errors="coerce").sum()
                    if not b_sub.empty
                    else 0
                )

                if not p_sub.empty:
                    tot_ip = pd.to_numeric(
                        p_sub.get("inningsPitched", 0), errors="coerce"
                    ).sum()
                    tot_er = pd.to_numeric(
                        p_sub.get("earnedRuns", 0), errors="coerce"
                    ).sum()
                    era = (
                        (tot_er * 9.0) / tot_ip
                        if tot_ip > 0
                        else pd.to_numeric(
                            p_sub.get("era", 4.50), errors="coerce"
                        ).mean()
                    )
                else:
                    era = 4.50

                return {"avg": avg, "hr": hr, "runs": runs, "sb": sb, "era": era}

            stats_a = get_team_summary(team_a)
            stats_b = get_team_summary(team_b)

            metrics = [
                "チーム打率",
                "チーム本塁打",
                "チーム防御率(逆算)",
                "総得点",
                "機動力(盗塁)",
            ]

            values_a = [
                min(stats_a["avg"] / 0.280 * 100, 100),
                min(stats_a["hr"] / 250.0 * 100, 100),
                max(0, min((6.0 - stats_a["era"]) / 3.0 * 100, 100)),
                min(stats_a["runs"] / 900.0 * 100, 100),
                min(stats_a["sb"] / 150.0 * 100, 100),
            ]

            values_b = [
                min(stats_b["avg"] / 0.280 * 100, 100),
                min(stats_b["hr"] / 250.0 * 100, 100),
                max(0, min((6.0 - stats_b["era"]) / 3.0 * 100, 100)),
                min(stats_b["runs"] / 900.0 * 100, 100),
                min(stats_b["sb"] / 150.0 * 100, 100),
            ]

            fig = go.Figure()
            fig.add_trace(
                go.Scatterpolar(
                    r=values_a,
                    theta=metrics,
                    fill="toself",
                    name=team_a,
                    line_color=color_a,
                )
            )
            fig.add_trace(
                go.Scatterpolar(
                    r=values_b,
                    theta=metrics,
                    fill="toself",
                    name=team_b,
                    line_color=color_b,
                )
            )

            fig.update_layout(
                polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
                showlegend=True,
                title=f"{team_a} vs {team_b} 総合力比較",
                height=450,
            )

            st.plotly_chart(fig, use_container_width=True)

            st.markdown("### 📋 主要スタッツ詳細比較")
            comp_df = pd.DataFrame(
                {
                    "指標": [
                        "チーム打率",
                        "チーム本塁打",
                        "チーム防御率",
                        "総得点",
                        "総盗塁数",
                    ],
                    team_a: [
                        f"{stats_a['avg']:.3f}",
                        f"{int(stats_a['hr'])} 本",
                        f"{stats_a['era']:.2f}",
                        f"{int(stats_a['runs'])} 点",
                        f"{int(stats_a['sb'])} 個",
                    ],
                    team_b: [
                        f"{stats_b['avg']:.3f}",
                        f"{int(stats_b['hr'])} 本",
                        f"{stats_b['era']:.2f}",
                        f"{int(stats_b['runs'])} 点",
                        f"{int(stats_b['sb'])} 個",
                    ],
                }
            )
            st.dataframe(comp_df, hide_index=True, use_container_width=True)

    # ---------------------------------------------------------
    # Tab 2: 年齢層・チーム構造分析（中央値 & 最頻値判定対応）
    # ---------------------------------------------------------
    with tab2:
        st.subheader(f"📈 チーム別 年齢層・選手構造分析 ({selected_season}年)")

        target_team = st.selectbox(
            "分析するチームを選択", all_teams, key="comp_age_team"
        )
        team_roster = get_roster_depth_data(target_team, selected_season)

        if not team_roster.empty and "age" in team_roster.columns:
            team_roster["age"] = pd.to_numeric(team_roster["age"], errors="coerce")
            valid_age_df = team_roster.dropna(subset=["age"])

            if not valid_age_df.empty:
                t_color = get_team_color(target_team)

                # 年齢分布データから中央値・最頻値を計算
                median_age = valid_age_df["age"].median()
                # 最頻年齢帯の算定 (5歳刻み)
                age_bins = pd.cut(valid_age_df["age"], bins=[18, 23, 27, 31, 35, 45])
                mode_range = age_bins.mode().iloc[0] if not age_bins.empty else "N/A"

                m1, m2, m3 = st.columns(3)
                with m1:
                    render_card(
                        "年齢中央値 (Median)",
                        f"{median_age:.1f} 歳",
                        border_color=t_color,
                    )
                with m2:
                    render_card(
                        "最頻年齢帯",
                        f"{mode_range}",
                        border_color=t_color,
                    )
                with m3:
                    render_card(
                        "年齢レンジ (最少-最大)",
                        f"{int(valid_age_df['age'].min())} - {int(valid_age_df['age'].max())} 歳",
                        border_color=t_color,
                    )

                fig_age = px.histogram(
                    valid_age_df,
                    x="age",
                    nbins=12,
                    title=f"{target_team} 選手年齢分布",
                    labels={"age": "年齢", "count": "人数"},
                    color_discrete_sequence=[t_color],
                )
                fig_age.update_layout(height=380)
                st.plotly_chart(fig_age, use_container_width=True)
            else:
                st.info("選択されたチームの選手年齢データがありません。")
        else:
            st.info("選手名簿データに年齢情報（`age`）が含まれていません。")


# --- UI アプリメインレイアウト ---

st.title("⚾ MLB 選手キャリア＆チーム補強ダッシュボード")

# ------------------------------------------------------------------
# 🎨 サイドバーの構造化・カテゴリ分け & APIキー入力設定
# ------------------------------------------------------------------
st.sidebar.markdown(
    "<div class='sidebar-section-header'>📌 表示モード切替</div>",
    unsafe_allow_html=True,
)

mode = st.sidebar.radio(
    "機能を選択してください:",
    [
        "🧩 チーム別Depth Chart・ポジショナル分析",
        "📊 チーム分析・比較ダッシュボード",
        "👤 選手検索（個人キャリア）",
        "🏢 チーム補強・放出・公示一覧",
        "🔓 2027年 FA予定選手リスト",
        "💰 チーム別 将来ペイロール分析",
        "⚔️ シミュレーション & 比較ツール ( interactive GUI )",
        "📰 本番AI ニュース＆トレンド感情分析",
    ],
)

st.sidebar.markdown(
    "<div class='sidebar-section-header'>🔑 AI API 設定</div>",
    unsafe_allow_html=True,
)
with st.sidebar.expander("🔑 本番 LLM API キー設定", expanded=False):
    st.caption(
        "OpenAI または Gemini の API キーを入力すると、実際のAIモデルがリアルタイム解析を行います。未入力の場合はフォールバックAIが自動作動します。"
    )
    user_api_key = st.text_input(
        "API Key (OpenAI / Gemini)", type="password", key="app_api_key"
    )
    ai_provider = st.selectbox(
        "LLM プロバイダー選択", ["openai", "gemini"], key="app_ai_provider"
    )

st.sidebar.markdown(
    "<div class='sidebar-section-header'>📅 シーズン設定</div>", unsafe_allow_html=True
)
seasons_list = get_seasons()
selected_season = st.sidebar.selectbox("① 対象シーズンを選択", seasons_list)
teams = get_teams_by_season(selected_season)

if not teams and mode not in [
    "⚔️ シミュレーション & 比較ツール ( interactive GUI )",
    "🔓 2027年 FA予定選手リスト",
    "💰 チーム別 将来ペイロール分析",
    "📰 本番AI ニュース＆トレンド感情分析",
]:
    st.error(
        f"{selected_season}年のデータが見つかりませんでした。先にデータのロードを実行してください。"
    )
    st.stop()


# ------------------------------------------------------------------
# モード 1: 🧩 チーム別Depth Chart・ポジショナル分析
# ------------------------------------------------------------------
if mode == "🧩 チーム別Depth Chart・ポジショナル分析":
    selected_team = st.sidebar.selectbox("② チームを選択してください", teams)

    if selected_team:
        team_color = get_team_color(selected_team)
        render_team_header(
            selected_team,
            f"{selected_team} Depth Chart & ロースター穴埋め分析 ({selected_season}年)",
        )

        tab_depth, tab_heatmap, tab_age = st.tabs(
            [
                "🛡️ チーム別 Depth Chart & 補強ポイント",
                "🌐 全30球団 ポジショナルWARマップ (SP/RP主要枠統合版)",
                "⏳ 年齢・世代構成 (Win-Now / Rebuild)",
            ]
        )

        df_depth = get_roster_depth_data(selected_team, selected_season)

        target_positions = [
            "C",
            "1B",
            "2B",
            "3B",
            "SS",
            "LF",
            "CF",
            "RF",
            "DH",
            "SP",
            "RP",
        ]
        pos_map = {
            "C": "C",
            "1B": "1B",
            "2B": "2B",
            "3B": "3B",
            "SS": "SS",
            "LF": "LF",
            "CF": "CF",
            "RF": "RF",
            "OF": "CF",
            "DH": "DH",
            "SP": "SP",
            "RP": "RP",
            "P": "RP",
        }

        if not df_depth.empty:
            df_depth["norm_pos"] = df_depth["pos"].map(pos_map).fillna("DH")
            if "age" in df_depth.columns:
                df_depth["age"] = pd.to_numeric(df_depth["age"], errors="coerce")

        # --- タブ 1: チーム内 Depth Chart ---
        with tab_depth:
            if df_depth.empty:
                st.warning("該当シーズンのロースターデータが存在しません。")
            else:
                pos_summary_df = calc_positional_war_from_team_stats(
                    df_depth[
                        df_depth["norm_pos"].isin(target_positions)
                        & (
                            df_depth["type"] == "batting"
                            if "type" in df_depth.columns
                            else True
                        )
                    ],
                    df_depth[
                        df_depth["norm_pos"].isin(target_positions)
                        & (
                            df_depth["type"] == "pitching"
                            if "type" in df_depth.columns
                            else True
                        )
                    ],
                )

                if not pos_summary_df.empty:
                    pos_summary = (
                        pos_summary_df.set_index("norm_pos")["war"]
                        .reindex(target_positions)
                        .fillna(0.0)
                        .reset_index()
                    )
                    pos_summary.columns = ["Position", "Total_WAR"]
                else:
                    pos_summary = (
                        df_depth.groupby("norm_pos")["war"]
                        .sum()
                        .reindex(target_positions)
                        .fillna(0.0)
                        .reset_index()
                    )
                    pos_summary.columns = ["Position", "Total_WAR"]

                total_war = pos_summary["Total_WAR"].sum()

                # 中央値 (Median) および 最頻年齢帯での高度な時期判定
                median_age = (
                    df_depth["age"].dropna().median()
                    if "age" in df_depth.columns and not df_depth["age"].dropna().empty
                    else None
                )

                if median_age and median_age >= 28.5 and total_war >= 15.0:
                    team_status = "🏆 Win-Now (全盛期・勝利至上期)"
                    status_color = "#28a745"
                elif median_age and median_age < 26.5 and total_war < 12.0:
                    team_status = "🌱 Rebuild (若手育成・再建期)"
                    status_color = "#fd7e14"
                else:
                    team_status = "⚖️ Contender / Transition (競合・端境期)"
                    status_color = "#007bff"

                col_m1, col_m2, col_m3 = st.columns(3)
                with col_m1:
                    render_card(
                        "チーム総 WAR", f"{total_war:.1f} WAR", border_color=team_color
                    )
                with col_m2:
                    render_card(
                        "所属選手 年齢中央値",
                        f"{median_age:.1f} 歳" if pd.notnull(median_age) else "N/A",
                        border_color=team_color,
                    )
                with col_m3:
                    render_card(
                        "チームフェーズ", team_status, border_color=status_color
                    )

                st.divider()

                st.subheader(
                    "📊 ポジション別 WAR 分布 (強度・補強穴マップ - SP/RP含む)"
                )
                st.caption(
                    "※ チームの合計スタッツからポジション別に再計算したWAR評価です。WARが低いポジション（赤色領域）が補強ポイントです。"
                )

                fig_pos = px.bar(
                    pos_summary,
                    x="Position",
                    y="Total_WAR",
                    color="Total_WAR",
                    color_continuous_scale=(
                        "Reds_r" if pos_summary["Total_WAR"].min() < 0 else "RdYlGn"
                    ),
                    text_auto=".1f",
                    labels={
                        "Position": "ポジション",
                        "Total_WAR": "合計 WAR",
                    },
                    title=f"{selected_team} ポジション別生産性 (WAR)",
                )
                fig_pos.update_layout(
                    xaxis_title="", yaxis_title="合計 WAR", height=380
                )
                st.plotly_chart(fig_pos, use_container_width=True)

                st.divider()

                st.subheader(
                    "🔍 ポジション別 Depth Chart (選手内訳 & 故障リスク/安定度)"
                )

                selected_pos = st.radio(
                    "詳細を確認するポジションを選択してください:",
                    target_positions,
                    horizontal=True,
                )

                df_pos_players = df_depth[
                    df_depth["norm_pos"] == selected_pos
                ].sort_values(by="war", ascending=False)

                col_d1, col_d2 = st.columns([3, 2])

                with col_d1:
                    st.write(
                        f"#### ⚾ {selected_pos} 枠の所属・起用選手一覧 ({len(df_pos_players)} 名)"
                    )
                    if not df_pos_players.empty:
                        risk_flags = []
                        stability_scores = []
                        for _, p_row in df_pos_players.iterrows():
                            dur_m = calculate_durability_metrics(
                                p_row.get("player_id"), p_row.get("player_name")
                            )
                            risk_flags.append(dur_m["risk_flag"])
                            stability_scores.append(f"{dur_m['score']}/100")

                        df_pos_players["故障リスク"] = risk_flags
                        df_pos_players["安定度スコア"] = stability_scores

                        cols_show = [
                            c
                            for c in [
                                "player_id",
                                "player_name",
                                "war",
                                "games",
                                "age",
                                "故障リスク",
                                "安定度スコア",
                            ]
                            if c in df_pos_players.columns
                        ]
                        st.dataframe(
                            df_pos_players[cols_show].rename(
                                columns={
                                    "player_id": "ID",
                                    "player_name": "選手名",
                                    "war": "WAR",
                                    "games": "出場試合数",
                                    "age": "年齢",
                                }
                            ),
                            use_container_width=True,
                            hide_index=True,
                        )

                        p_sel = st.selectbox(
                            "🔍 カード（モーダル）表示する選手を選択:",
                            df_pos_players["player_name"].tolist(),
                            key="pos_modal_sel",
                        )
                        if st.button(
                            "📱 選手詳細カードを表示", key="btn_show_pos_modal"
                        ):
                            p_id = df_pos_players[
                                df_pos_players["player_name"] == p_sel
                            ]["player_id"].values[0]
                            show_player_modal(p_id, p_sel)
                    else:
                        st.info(
                            f"このシーズン、{selected_pos} での実績がある選手はいません。"
                        )

                with col_d2:
                    st.write("#### 🎂 チームの年齢層分布")
                    if "age" in df_depth.columns and not df_depth["age"].dropna().empty:
                        fig_age = px.histogram(
                            df_depth,
                            x="age",
                            nbins=10,
                            title=f"{selected_team} 選手年齢分布",
                            labels={"age": "年齢", "count": "人数"},
                            color_discrete_sequence=[team_color],
                        )
                        fig_age.update_layout(height=280)
                        st.plotly_chart(fig_age, use_container_width=True)

        # --- タブ 2: 全30球団 ポジショナルWARマップ ---
        with tab_heatmap:
            st.markdown(
                "### 🗺️ 全30球団 ポジショナルWARヒートマップ (ポジション別チーム合計スタッツ算定版)"
            )
            st.caption(
                "全30球団の野手各ポジションおよび投手ポジションの合計スタッツに基づきWARを計算し、比較表示します。"
            )

            pos_war_df = get_all_teams_positional_war(selected_season)

            if not pos_war_df.empty:
                heatmap_pivot = pos_war_df.pivot(
                    index="team_name", columns="norm_pos", values="war"
                ).fillna(0.0)

                standard_positions = [
                    "C",
                    "1B",
                    "2B",
                    "3B",
                    "SS",
                    "LF",
                    "CF",
                    "RF",
                    "DH",
                    "SP",
                    "RP",
                ]
                available_pos = [
                    p for p in standard_positions if p in heatmap_pivot.columns
                ]
                heatmap_pivot = heatmap_pivot[available_pos]

                fig_heatmap = px.imshow(
                    heatmap_pivot,
                    labels=dict(x="ポジション", y="チーム", color="合計 WAR"),
                    x=heatmap_pivot.columns,
                    y=heatmap_pivot.index,
                    color_continuous_scale="RdYlGn",
                    aspect="auto",
                )
                fig_heatmap.update_layout(
                    height=780,
                    xaxis_title="Position",
                    yaxis_title="Team",
                    coloraxis_colorbar=dict(title="WAR"),
                )
                st.plotly_chart(fig_heatmap, use_container_width=True)

                if selected_team in heatmap_pivot.index:
                    team_pos_series = heatmap_pivot.loc[selected_team].sort_values()
                    weakest_p = team_pos_series.index[0]
                    weakest_w = team_pos_series.iloc[0]
                    strongest_p = team_pos_series.index[-1]
                    strongest_w = team_pos_series.iloc[-1]

                    col_h1, col_h2 = st.columns(2)
                    with col_h1:
                        st.warning(
                            f"⚠️ **{selected_team} 最優先補強ポイント (穴):** **`{weakest_p}`** （ポジションWAR: `{weakest_w:.1f}`）"
                        )
                    with col_h2:
                        st.success(
                            f"強みポジション: **`{strongest_p}`** （ポジションWAR: `{strongest_w:.1f}`）"
                        )
            else:
                st.info("※ポジショナルWARデータが取得できませんでした。")

        # --- タブ 3: 年齢・世代構成グラフ（中央値 & 最頻分布対応） ---
        with tab_age:
            st.markdown("### ⏳ 年齢・世代構成 & チームフェーズ分析")
            st.caption(
                "チーム主力選手の年齢分布（中央値・最頻値・ピーク帯割合）とWAR貢献度から、時期フェーズ（Win-Now / Rebuild等）を精密分析します。"
            )

            if not df_depth.empty and "age" in df_depth.columns:
                df_valid_age = df_depth.dropna(subset=["age"]).copy()

                if not df_valid_age.empty:
                    med_age = df_valid_age["age"].median()

                    # 26〜30歳の全盛期ピーク世代割合を計算
                    peak_players = df_valid_age[
                        (df_valid_age["age"] >= 26) & (df_valid_age["age"] <= 30)
                    ]
                    peak_ratio = (len(peak_players) / len(df_valid_age)) * 100

                    col_a1, col_a2, col_a3 = st.columns(3)
                    with col_a1:
                        render_card(
                            "年齢中央値 (Median)",
                            f"{med_age:.1f} 歳",
                            border_color=team_color,
                        )
                    with col_a2:
                        render_card(
                            "全盛期(26-30歳)層 割合",
                            f"{peak_ratio:.1f} %",
                            border_color=team_color,
                        )

                    # 分布ベースでの判定
                    if med_age >= 28.5 or peak_ratio >= 45.0:
                        phase_label = "🔥 Win-Now (全盛期・勝利至上期)"
                        phase_color = "#dc3545"
                    elif med_age <= 26.5 and peak_ratio < 30.0:
                        phase_label = "🌱 Rebuild / Young Core (再建・若手期)"
                        phase_color = "#28a745"
                    else:
                        phase_label = "⚖️ Transition (端境期・競合期)"
                        phase_color = "#007bff"

                    with col_a3:
                        render_card(
                            "チームフェーズ判定", phase_label, border_color=phase_color
                        )

                    st.divider()

                    fig_scatter = px.scatter(
                        df_valid_age,
                        x="age",
                        y="war",
                        size=df_valid_age["war"].clip(lower=0.1) * 4 + 4,
                        color="norm_pos",
                        hover_name="player_name",
                        title=f"{selected_team} 選手の年齢分布とWAR貢献度 ({selected_season}年)",
                        labels={
                            "age": "年齢 (Age)",
                            "war": "貢献度 (WAR)",
                            "norm_pos": "ポジション",
                        },
                    )

                    fig_scatter.add_vrect(
                        x0=26,
                        x1=30,
                        fillcolor="Gray",
                        opacity=0.15,
                        line_width=0,
                        annotation_text="全盛期ゾーン (26-30歳)",
                        annotation_position="top left",
                    )

                    st.plotly_chart(fig_scatter, use_container_width=True)
                else:
                    st.info("※年齢データが存在しないため表示できません。")
            else:
                st.info("※該当シーズンのロースターデータが存在しません。")


# ------------------------------------------------------------------
# モード 2: 📊 チーム分析・比較ダッシュボード
# ------------------------------------------------------------------
elif mode == "📊 チーム分析・比較ダッシュボード":
    render_team_comparison_dashboard(selected_season)


# ------------------------------------------------------------------
# モード 3: 👤 選手検索（個人キャリア）
# ------------------------------------------------------------------
elif mode == "👤 選手検索（個人キャリア）":
    selected_team = st.sidebar.selectbox("② チームを選択してください", teams)

    if selected_team:
        team_color = get_team_color(selected_team)
        render_team_header(
            selected_team, f"{selected_team} ({selected_season}年所属選手)"
        )

        roster_df = get_roster_by_season(selected_team, selected_season)

        if roster_df.empty:
            st.warning("該当する選手データがありません。")
        else:
            player_names = roster_df["player_name"].tolist()
            selected_player_name = st.selectbox(
                "③ 選手を選択してください", player_names
            )

            selected_player_id = roster_df[
                roster_df["player_name"] == selected_player_name
            ]["player_id"].values[0]

            col_btn, _ = st.columns([1, 3])
            with col_btn:
                if st.button("📱 モーダルダイアログで表示", use_container_width=True):
                    show_player_modal(selected_player_id, selected_player_name)

            st.divider()

            if selected_player_id is not None:
                df_b_hist, df_p_hist = get_player_history(
                    selected_player_id, selected_player_name
                )
                p_positions_summary = get_player_primary_positions(
                    selected_player_id, df_b_hist, df_p_hist
                )
                dur_metrics = calculate_durability_metrics(
                    selected_player_id, selected_player_name
                )

                st.subheader(
                    f"👤 {selected_player_name} 選手 （ポジション: {p_positions_summary}）"
                )

                col_r1, col_r2, col_r3 = st.columns(3)
                with col_r1:
                    render_card(
                        "🏃 安定度スコア (稼働実績)",
                        f"{dur_metrics['score']} / 100",
                        border_color=team_color,
                    )
                with col_r2:
                    render_card(
                        "📅 直近3年平均稼働",
                        f"{dur_metrics['avg_games']} 試合 / {dur_metrics['avg_ip']} IP",
                        border_color=team_color,
                    )
                with col_r3:
                    r_color = "#dc3545" if dur_metrics["is_high_risk"] else "#28a745"
                    render_card(
                        "🏥 故障リスク (IL判定)",
                        dur_metrics["risk_flag"],
                        border_color=r_color,
                    )

                st.divider()

                tab_stats, tab_contract, tab_edit, tab_trans = st.tabs(
                    [
                        "📊 成績推移 (wRC+ & FIP 拡張版)",
                        "💰 契約・年俸 & Surplus Value",
                        "✏️ 契約管理 (DB編集)",
                        "📜 移籍・公示履歴 (ILリスク等)",
                    ]
                )

                # 1. 成績推移
                with tab_stats:
                    is_two_way = p_positions_summary == "P/DH"
                    if is_two_way:
                        st.success(
                            "🌟 **二刀流（Two-Way Player）検出:** 野手・投手双方の全期間キャリア成績を表示中"
                        )
                        b_war_total = (
                            df_b_hist["war"].sum()
                            if "war" in df_b_hist.columns
                            else 0.0
                        )
                        p_war_total = (
                            df_p_hist["war"].sum()
                            if "war" in df_p_hist.columns
                            else 0.0
                        )
                        total_career_war = b_war_total + p_war_total

                        c1, c2, c3 = st.columns(3)
                        with c1:
                            render_card(
                                "通算 打者WAR",
                                f"{b_war_total:.1f}",
                                border_color=team_color,
                            )
                        with c2:
                            render_card(
                                "通算 投手WAR",
                                f"{p_war_total:.1f}",
                                border_color=team_color,
                            )
                        with c3:
                            render_card(
                                "🔥 通算 合計WAR",
                                f"{total_career_war:.1f}",
                                sub_text="投打合算",
                                border_color="#ffc107",
                            )
                        st.divider()

                    if not df_b_hist.empty:
                        st.write("### 🏏 打撃成績 (wRC+ & 球場補正 Park Factor 含む)")
                        cols_to_drop = [
                            c
                            for c in ["player_name", "pos", "player_id", "team_id"]
                            if c in df_b_hist.columns
                        ]
                        df_b_display = df_b_hist.drop(columns=cols_to_drop)
                        first_cols = [
                            c
                            for c in ["season", "team_name"]
                            if c in df_b_display.columns
                        ]
                        other_cols = [
                            c for c in df_b_display.columns if c not in first_cols
                        ]
                        st.dataframe(
                            df_b_display[first_cols + other_cols].rename(
                                columns={"wrc_plus": "wRC+", "park_factor": "PF"}
                            ),
                            use_container_width=True,
                            hide_index=True,
                        )

                    if not df_p_hist.empty and (
                        is_two_way
                        or "SP" in p_positions_summary
                        or "RP" in p_positions_summary
                    ):
                        st.write("### ⚾ 投手成績 (FIP, BABIP, K/BB 含む)")
                        cols_to_drop = [
                            c
                            for c in ["player_name", "pos", "player_id", "team_id"]
                            if c in df_p_hist.columns
                        ]
                        df_p_display = df_p_hist.drop(columns=cols_to_drop)
                        first_cols = [
                            c
                            for c in ["season", "team_name"]
                            if c in df_p_display.columns
                        ]
                        other_cols = [
                            c for c in df_p_display.columns if c not in first_cols
                        ]
                        st.dataframe(
                            df_p_display[first_cols + other_cols].rename(
                                columns={
                                    "era": "ERA",
                                    "fip": "FIP",
                                    "babip": "BABIP",
                                    "luck_flag": "運/守備評価",
                                    "k_bb": "K/BB",
                                }
                            ),
                            use_container_width=True,
                            hide_index=True,
                        )

                # 2. 契約・年俸 & Surplus Value
                with tab_contract:
                    df_contracts = get_player_contracts(
                        selected_player_id, selected_player_name
                    )

                    played_seasons = set()
                    if not df_b_hist.empty:
                        played_seasons.update(df_b_hist["season"].dropna().astype(int))
                    if not df_p_hist.empty:
                        played_seasons.update(df_p_hist["season"].dropna().astype(int))

                    if not df_contracts.empty:
                        latest_row = df_contracts.iloc[0]
                        contract_status_val = latest_row.get(
                            "contract_status",
                            f"{latest_row.get('contract_years', 1)} yr",
                        )
                        service_time_val = latest_row.get("service_time", "0.000")
                        fa_year_val = latest_row.get("free_agent_year", "-")

                        col_m1, col_m2, col_m3 = st.columns(3)
                        with col_m1:
                            render_card(
                                "📄 現在の契約",
                                str(contract_status_val),
                                border_color=team_color,
                            )
                        with col_m2:
                            render_card(
                                "⏱️ サービスタイム",
                                f"{service_time_val} 年",
                                sub_text="2026年開幕前時点",
                                border_color=team_color,
                            )
                        with col_m3:
                            render_card(
                                "🔓 FA予定年",
                                f"{fa_year_val} 年" if pd.notnull(fa_year_val) else "-",
                                border_color=team_color,
                            )

                        st.divider()
                        st.write("### 💰 年俸推移 & Surplus Value 評価")

                        bracket_match = re.search(
                            r"\((.*?)\)", str(contract_status_val)
                        )
                        start_yr_short, end_yr_short = None, None
                        bracket_str = ""
                        if bracket_match:
                            bracket_str = f" ({bracket_match.group(1)})"
                            parts = bracket_match.group(1).split("-")
                            if (
                                len(parts) == 2
                                and parts[0].isdigit()
                                and parts[1].isdigit()
                            ):
                                start_yr_short = int(parts[0])
                                end_yr_short = int(parts[1])

                        b_war_by_season = (
                            df_b_hist.groupby("season")["war"].sum()
                            if not df_b_hist.empty
                            else pd.Series()
                        )
                        p_war_by_season = (
                            df_p_hist.groupby("season")["war"].sum()
                            if not df_p_hist.empty
                            else pd.Series()
                        )

                        df_c_disp = df_contracts.copy()

                        if played_seasons:
                            df_c_disp = df_c_disp[
                                df_c_disp["season"].isin(played_seasons)
                            ]

                        df_c_disp["bat_war"] = (
                            df_c_disp["season"].map(b_war_by_season).fillna(0.0)
                        )
                        df_c_disp["pitch_war"] = (
                            df_c_disp["season"].map(p_war_by_season).fillna(0.0)
                        )
                        df_c_disp["total_war"] = (
                            df_c_disp["bat_war"] + df_c_disp["pitch_war"]
                        )

                        df_c_disp["market_value"] = (
                            df_c_disp["total_war"] * WAR_MARKET_VALUE
                        )
                        df_c_disp["surplus_value"] = df_c_disp[
                            "market_value"
                        ] - df_c_disp["salary"].fillna(MLB_MINIMUM_SALARY)

                        def format_salary_with_bracket(row):
                            sal = row.get("salary")
                            s_year = row.get("season")
                            if pd.isna(sal):
                                return "-"

                            formatted_sal = f"${sal:,.0f}"

                            if start_yr_short is not None and end_yr_short is not None:
                                s_short = s_year % 100
                                if start_yr_short <= s_short <= end_yr_short:
                                    return f"{formatted_sal}{bracket_str}"

                            return formatted_sal

                        df_c_disp["年俸 ($)"] = df_c_disp.apply(
                            format_salary_with_bracket, axis=1
                        )
                        df_c_disp["推定市場価値 ($)"] = df_c_disp["market_value"].apply(
                            lambda x: f"${x:,.0f}"
                        )
                        df_c_disp["Surplus Value ($)"] = df_c_disp[
                            "surplus_value"
                        ].apply(lambda x: f"${x:+,.0f}")

                        st.dataframe(
                            df_c_disp[
                                [
                                    "season",
                                    "年俸 ($)",
                                    "total_war",
                                    "推定市場価値 ($)",
                                    "Surplus Value ($)",
                                ]
                            ].rename(
                                columns={
                                    "season": "シーズン",
                                    "total_war": "合計WAR",
                                }
                            ),
                            use_container_width=True,
                            hide_index=True,
                        )
                    else:
                        st.info(
                            f"💡 この選手の個別の契約・サービスタイムデータは未登録です（デフォルト推定年俸: 最低保障約 ${MLB_MINIMUM_SALARY:,.0f} / 年）"
                        )

                    st.divider()

                    st.write("#### 📈 剰余価値（Surplus Value）算定基準")
                    st.caption("※ Surplus Value ＝ (合計WAR × $8,000,000) － 年俸")

                    col_sv1, col_sv2 = st.columns(2)
                    with col_sv1:
                        render_card(
                            "1 WAR あたりの標準市場価格",
                            "$8,000,000",
                            border_color=team_color,
                        )
                    with col_sv2:
                        sample_war = 3.0
                        est_market_val = sample_war * WAR_MARKET_VALUE
                        render_card(
                            f"参考: WAR {sample_war} 達成時の金銭価値",
                            f"${est_market_val:,.0f}",
                            border_color=team_color,
                        )

                # 3. DB直接編集機能
                with tab_edit:
                    st.write(f"### ✏️ {selected_player_name} 選手の契約編集")
                    st.caption(
                        "表の数値を直接クリックして変更し、「💾 データベースに保存」ボタンを押すと即座にDBへ反映されます。"
                    )

                    df_contracts_edit = get_player_contracts(
                        selected_player_id, selected_player_name
                    )

                    if df_contracts_edit.empty:
                        df_contracts_edit = pd.DataFrame(
                            [
                                {
                                    "season": selected_season,
                                    "salary": 780000.0,
                                    "aav": 780000.0,
                                    "contract_years": 1,
                                    "free_agent_year": selected_season + 4,
                                    "contract_status": "1 yr",
                                }
                            ]
                        )

                    cols_to_edit = [
                        c
                        for c in [
                            "season",
                            "salary",
                            "aav",
                        ]
                        if c in df_contracts_edit.columns
                    ]

                    edited_df = st.data_editor(
                        df_contracts_edit[cols_to_edit],
                        num_rows="dynamic",
                        use_container_width=True,
                        column_config={
                            "season": st.column_config.NumberColumn(
                                "シーズン", format="%d"
                            ),
                            "salary": st.column_config.NumberColumn(
                                "年俸 ($)", format="$%d"
                            ),
                            "aav": st.column_config.NumberColumn(
                                "AAV (平均年俸 $)", format="$%d"
                            ),
                        },
                        key=f"editor_{selected_player_id}",
                    )

                    if st.button(
                        "💾 データベースに保存",
                        type="primary",
                        use_container_width=True,
                    ):
                        save_player_contracts(
                            selected_player_id,
                            selected_player_name,
                            edited_df,
                        )
                        st.success(
                            f"✅ {selected_player_name} 選手の契約データを更新しました！"
                        )
                        st.rerun()

                # 4. 移籍・公示履歴
                with tab_trans:
                    df_trans = get_player_transactions(selected_player_id)
                    if not df_trans.empty:
                        st.write("### 📜 公式公示・移籍タイムライン")
                        df_trans_display = df_trans.rename(
                            columns={
                                "date": "日付",
                                "type": "公式種別",
                                "description": "詳細内容",
                                "from_team": "旧所属",
                                "to_team": "新所属",
                            }
                        )
                        st.dataframe(
                            df_trans_display, use_container_width=True, hide_index=True
                        )
                    else:
                        st.info("この選手の移籍・公示履歴データはありません。")


# ------------------------------------------------------------------
# モード 4: 🏢 チーム補強・放出・公示一覧
# ------------------------------------------------------------------
elif mode == "🏢 チーム補強・放出・公示一覧":
    st.header("🏢 チーム別 カテゴリ補強・放出動向")

    selected_team = st.sidebar.selectbox("② チームを選択", teams)

    if selected_team and selected_season:
        render_team_header(
            selected_team, f"{selected_team} 補強・放出・公示一覧 ({selected_season}年)"
        )
        df_reinforce = get_team_reinforcements(selected_team, selected_season)

        if not df_reinforce.empty:
            tab_fa, tab_trade, tab_other, tab_all = st.tabs(
                [
                    "📝 FA 獲得 / 退団",
                    "🔄 トレード IN / OUT",
                    "⚠️ その他 (DFA / Waivers / 解雇等)",
                    "📋 全公示履歴",
                ]
            )

            def render_simple_in_out(df_cat, cat_name):
                df_in = df_cat[df_cat["区分"] == "IN"]
                df_out = df_cat[df_cat["区分"] == "OUT"]

                col_in, col_out = st.columns(2)

                with col_in:
                    st.subheader(f"🟩 補強 / 加入 (IN): {len(df_in)} 名")
                    if not df_in.empty:
                        df_in_disp = df_in[["選手名", "旧所属"]].rename(
                            columns={"旧所属": "前所属球団"}
                        )
                        st.dataframe(
                            df_in_disp,
                            use_container_width=True,
                            hide_index=True,
                        )
                    else:
                        st.info(f"該当する {cat_name} の補強選手はいません。")

                with col_out:
                    st.subheader(f"🟥 放出 / 退団 (OUT): {len(df_out)} 名")
                    if not df_out.empty:
                        df_out_disp = df_out[["選手名", "新所属"]].rename(
                            columns={"新所属": "移籍先球団"}
                        )
                        st.dataframe(
                            df_out_disp,
                            use_container_width=True,
                            hide_index=True,
                        )
                    else:
                        st.info(f"該当する {cat_name} の放出選手はいません。")

            with tab_fa:
                df_fa = df_reinforce[df_reinforce["カテゴリ"] == "FA"]
                render_simple_in_out(df_fa, "FA")

            with tab_trade:
                df_trade = df_reinforce[df_reinforce["カテゴリ"] == "Trade"]
                render_simple_in_out(df_trade, "トレード")

            with tab_other:
                df_other = df_reinforce[df_reinforce["カテゴリ"] == "OTHER"]
                render_simple_in_out(df_other, "その他(DFA/Waivers等)")

            with tab_all:
                st.subheader(f"📋 {selected_team} 全公示データ ({selected_season}年)")
                st.dataframe(
                    df_reinforce[
                        [
                            "日付",
                            "カテゴリ",
                            "区分",
                            "種別",
                            "選手名",
                            "旧所属",
                            "新所属",
                            "詳細",
                        ]
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
        else:
            st.info("該当するデータがありません。")


# ------------------------------------------------------------------
# モード 5: 🔓 2027年 FA予定選手リスト
# ------------------------------------------------------------------
elif mode == "🔓 2027年 FA予定選手リスト":
    st.header("🔓 2027年 FA（フリーエージェント）予定選手一覧")
    st.caption(
        "2026年シーズン終了後（2027年開幕前）にFA権を取得予定の選手リストです。投手のSP/RP区別・野手の複数ポジションに加えて、**「故障リスク（IL判定）」**および**「安定度スコア」**を一覧表示しています。"
    )

    df_fa_2027 = get_fa_players_by_year(2027)

    if not df_fa_2027.empty:
        col_fa1, col_fa2, col_fa3 = st.columns(3)
        with col_fa1:
            render_card(
                "該当FA選手数", f"{len(df_fa_2027)} 名", border_color=DEFAULT_COLOR
            )
        with col_fa2:
            render_card(
                "最高通算WAR選手",
                f"{df_fa_2027.iloc[0]['選手名']}",
                sub_text=f"{df_fa_2027.iloc[0]['通算WAR']} WAR",
                border_color=DEFAULT_COLOR,
            )
        with col_fa3:
            avg_fa_war = df_fa_2027["通算WAR"].mean()
            render_card(
                "平均通算WAR", f"{avg_fa_war:.1f} WAR", border_color=DEFAULT_COLOR
            )

        st.divider()

        st.dataframe(
            df_fa_2027[
                [
                    "所属チーム",
                    "ポジション",
                    "選手名",
                    "通算WAR",
                    "故障リスク",
                    "安定度スコア",
                ]
            ],
            use_container_width=True,
            hide_index=True,
        )

        col_fa_m, _ = st.columns([1, 2])
        with col_fa_m:
            fa_p_sel = st.selectbox(
                "🔍 詳細カード（モーダル）を表示するFA選手を選択:",
                df_fa_2027["選手名"].tolist(),
            )
            if st.button("📱 選手詳細カードを表示", key="btn_fa_modal"):
                p_id = df_fa_2027[df_fa_2027["選手名"] == fa_p_sel]["player_id"].values[
                    0
                ]
                show_player_modal(p_id, fa_p_sel)
    else:
        st.info("2027年にFA予定の選手データが見つかりませんでした。")


# ------------------------------------------------------------------
# モード 6: 💰 チーム別 将来ペイロール分析
# ------------------------------------------------------------------
elif mode == "💰 チーム別 将来ペイロール分析":
    st.header("💰 チーム別 将来確定年俸 & 資金的余裕度 (2026-2030年)")
    st.caption(
        "各チームの長期契約（確定年俸）の推移を可視化します。`contract_data.csv` に記載の年度別確定年俸と DB の FA 予定年を統合処理しており、2027年以降に確定年俸が低いチームほど、FA市場で大型補強に動ける資金的余裕（空き枠）を持っています。"
    )

    df_payroll = get_team_future_payrolls()

    if not df_payroll.empty:
        df_2027 = df_payroll[df_payroll["season"] == 2027].sort_values(
            by="total_payroll", ascending=True
        )

        col_p1, col_p2 = st.columns([1, 2])

        with col_p1:
            st.subheader("📊 2027年 確定年俸が低い球団 (FA補強余力大)")
            st.dataframe(
                df_2027[["team_name", "total_payroll", "contracted_players"]]
                .rename(
                    columns={
                        "team_name": "チーム",
                        "total_payroll": "2027確定年俸 ($)",
                        "contracted_players": "契約残選手数",
                    }
                )
                .style.format({"2027確定年俸 ($)": "${:,.0f}"}),
                use_container_width=True,
                hide_index=True,
            )

        with col_p2:
            st.subheader("📈 2026-2030年 確定年俸推移グラフ")

            all_payroll_teams = sorted(df_payroll["team_name"].unique().tolist())
            default_teams = df_2027["team_name"].head(5).tolist()

            selected_payroll_teams = st.multiselect(
                "比較するチームを選択してください:",
                all_payroll_teams,
                default=default_teams,
            )

            df_chart = df_payroll[df_payroll["team_name"].isin(selected_payroll_teams)]

            if not df_chart.empty:
                color_map = {t: get_team_color(t) for t in selected_payroll_teams}

                fig_payroll = px.bar(
                    df_chart,
                    x="season",
                    y="total_payroll",
                    color="team_name",
                    barmode="group",
                    title="チーム別 将来確定年俸推移 ($)",
                    labels={
                        "season": "シーズン",
                        "total_payroll": "確定年俸総額 ($)",
                        "team_name": "チーム",
                    },
                    text_auto=".2s",
                    color_discrete_map=color_map,
                )
                fig_payroll.update_layout(height=450)
                st.plotly_chart(fig_payroll, use_container_width=True)

        st.divider()

        st.subheader("🔍 チーム別 2026年以降の長期契約選手内訳（マトリクス）")
        selected_detail_team = st.selectbox(
            "チームを選択して選手別の年俸推移を確認:", all_payroll_teams
        )

        if selected_detail_team:
            conn = sqlite3.connect(DB_PATH)
            query_detail = f"""
                WITH latest_team AS (
                    SELECT player_id, player_name FROM batting_stats WHERE season = 2026 AND team_name = '{selected_detail_team}'
                    UNION
                    SELECT player_id, player_name FROM pitching_stats WHERE season = 2026 AND team_name = '{selected_detail_team}'
                )
                SELECT c.player_id, c.player_name, c.salary, c.aav, c.free_agent_year
                FROM contracts c
                JOIN latest_team lt ON c.player_id = lt.player_id
                WHERE c.season = 2026
            """
            df_det_2026 = pd.read_sql_query(query_detail, conn)
            conn.close()

            try:
                df_csv_det = pd.read_csv(CSV_PATH)
            except Exception:
                df_csv_det = pd.DataFrame()

            csv_map_det = {}
            if not df_csv_det.empty and "Name" in df_csv_det.columns:
                year_cols = [
                    str(y) for y in range(2026, 2031) if str(y) in df_csv_det.columns
                ]
                for _, r in df_csv_det.iterrows():
                    p_name = str(r["Name"]).strip()
                    csv_map_det[p_name] = {}
                    for y_col in year_cols:
                        pv = parse_salary_str(r[y_col])
                        if pv is not None:
                            csv_map_det[p_name][int(y_col)] = pv

            if not df_det_2026.empty:
                matrix_rows = []
                for yr in range(2026, 2031):
                    for _, row in df_det_2026.iterrows():
                        p_name = row["player_name"]
                        fa_yr = row.get("free_agent_year")

                        sal = None
                        if p_name in csv_map_det and yr in csv_map_det[p_name]:
                            sal = csv_map_det[p_name][yr]
                        elif pd.notnull(fa_yr) and yr < float(fa_yr):
                            sal = (
                                row["aav"]
                                if pd.notnull(row.get("aav")) and row["aav"] > 0
                                else row.get("salary", MLB_MINIMUM_SALARY)
                            )

                        if sal is not None and sal > 0:
                            matrix_rows.append(
                                {
                                    "選手名": p_name,
                                    "シーズン": yr,
                                    "年俸": sal,
                                }
                            )

                if matrix_rows:
                    df_matrix = pd.DataFrame(matrix_rows)
                    df_pivot = df_matrix.pivot(
                        index="選手名", columns="シーズン", values="年俸"
                    ).fillna(0.0)

                    st.dataframe(
                        df_pivot.style.format("${:,.0f}"), use_container_width=True
                    )
                else:
                    st.info("該当チームの長期契約データはありません。")
            else:
                st.info("該当チームの長期契約データはありません。")
    else:
        st.info("確定年俸データが見つかりませんでした。")


# ------------------------------------------------------------------
# モード 7: ⚔️ シミュレーション & 比較ツール ( wRC+ / FIP 対応版 )
# ------------------------------------------------------------------
elif mode == "⚔️ シミュレーション & 比較ツール ( interactive GUI )":
    st.header("⚔️ シミュレーション & 比較ツール")

    sub_mode = st.radio(
        "ツールを選択してください:",
        ["2選手対比コンパレーター", "仮想トレード・シミュレーター"],
        horizontal=True,
    )

    all_players_df = get_all_players()
    player_options = (
        all_players_df["player_name"].tolist() if not all_players_df.empty else []
    )

    # ------------------------------------------------------------------
    # 7-1. 2選手対比コンパレーター
    # ------------------------------------------------------------------
    if sub_mode == "2選手対比コンパレーター":
        st.subheader("📊 2選手対比コンパレーター")
        st.caption(
            "2名の選手を選択し、単年スタッツ（wRC+ / FIP 含む）のレーダーチャート比較や、全キャリアのWAR推移グラフを並べて視覚化します。"
        )

        col_p1, col_p2 = st.columns(2)

        default_p1_idx = (
            player_options.index("Shohei Ohtani")
            if "Shohei Ohtani" in player_options
            else 0
        )
        default_p2_idx = (
            player_options.index("Aaron Judge")
            if "Aaron Judge" in player_options
            else (1 if len(player_options) > 1 else 0)
        )

        with col_p1:
            p1_name = st.selectbox(
                "選手 1 を選択", player_options, index=default_p1_idx
            )
            p1_id = all_players_df[all_players_df["player_name"] == p1_name][
                "player_id"
            ].values[0]

        with col_p2:
            p2_name = st.selectbox(
                "選手 2 を選択", player_options, index=default_p2_idx
            )
            p2_id = all_players_df[all_players_df["player_name"] == p2_name][
                "player_id"
            ].values[0]

        p1_b_hist, p1_p_hist = get_player_history(p1_id, p1_name)
        p2_b_hist, p2_p_hist = get_player_history(p2_id, p2_name)

        st.markdown("### 📈 キャリア WAR 推移グラフ")

        def extract_war_trend(df_b, df_p, p_name):
            war_by_season = {}
            if not df_b.empty:
                for _, r in df_b.iterrows():
                    s = int(r["season"])
                    war_by_season[s] = war_by_season.get(s, 0.0) + float(
                        r.get("war", 0.0)
                    )
            if not df_p.empty:
                for _, r in df_p.iterrows():
                    s = int(r["season"])
                    war_by_season[s] = war_by_season.get(s, 0.0) + float(
                        r.get("war", 0.0)
                    )

            df_res = pd.DataFrame(
                list(war_by_season.items()), columns=["season", "war"]
            ).sort_values("season")
            df_res["player_name"] = p_name
            return df_res

        df_p1_war = extract_war_trend(p1_b_hist, p1_p_hist, p1_name)
        df_p2_war = extract_war_trend(p2_b_hist, p2_p_hist, p2_name)

        df_comb_war = pd.concat([df_p1_war, df_p2_war], ignore_index=True)

        if not df_comb_war.empty:
            fig_war = px.line(
                df_comb_war,
                x="season",
                y="war",
                color="player_name",
                markers=True,
                title=f"{p1_name} vs {p2_name} - キャリアWAR推移比較",
                labels={"season": "シーズン", "war": "WAR", "player_name": "選手名"},
            )
            fig_war.update_layout(height=400)
            st.plotly_chart(fig_war, use_container_width=True)
        else:
            st.info("WAR推移データを取得できませんでした。")

        st.divider()

        st.markdown(
            f"### 🎯 シーズン別能力比較（wRC+ / FIP セイバーメトリクスレーダー） - 【{selected_season}年】"
        )

        comp_type = st.radio(
            "比較対象指標の種類を選択:",
            ["打撃高度指標 (wRC+ / wOBA / OPS)", "投手高度指標 (FIP / ERA / K-BB)"],
            horizontal=True,
        )

        def get_single_season_stat(df, season):
            if df.empty:
                return None
            sub = df[df["season"] == season]
            if sub.empty:
                return None
            return sub.iloc[0]

        if "打撃" in comp_type:
            p1_stat = get_single_season_stat(p1_b_hist, selected_season)
            p2_stat = get_single_season_stat(p2_b_hist, selected_season)

            categories = [
                "wRC+ (得点創出力)",
                "wOBA (総合打撃)",
                "OPS",
                "AVG (打率)",
                "HR (本塁打)",
                "WAR",
            ]

            def build_batting_vector(stat):
                if stat is None:
                    return [0, 0, 0, 0, 0, 0]
                wrc = float(
                    pd.to_numeric(stat.get("wrc_plus", 100), errors="coerce") or 100
                )
                woba = float(
                    pd.to_numeric(stat.get("woba", 0.315), errors="coerce") or 0.315
                )
                ops = float(pd.to_numeric(stat.get("ops", 0), errors="coerce") or 0)
                avg = float(pd.to_numeric(stat.get("avg", 0), errors="coerce") or 0)
                hr = float(pd.to_numeric(stat.get("homeRuns", 0), errors="coerce") or 0)
                war = float(pd.to_numeric(stat.get("war", 0), errors="coerce") or 0)

                return [
                    min(wrc / 200.0 * 100, 100),
                    min(woba / 0.450 * 100, 100),
                    min(ops / 1.100 * 100, 100),
                    min(avg / 0.350 * 100, 100),
                    min(hr / 50.0 * 100, 100),
                    min(max(war, 0) / 10.0 * 100, 100),
                ]

            p1_vals = build_batting_vector(p1_stat)
            p2_vals = build_batting_vector(p2_stat)

            fig_radar = go.Figure()
            fig_radar.add_trace(
                go.Scatterpolar(
                    r=p1_vals, theta=categories, fill="toself", name=p1_name
                )
            )
            fig_radar.add_trace(
                go.Scatterpolar(
                    r=p2_vals, theta=categories, fill="toself", name=p2_name
                )
            )
            fig_radar.update_layout(
                polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
                showlegend=True,
                title=f"{selected_season}年 打撃高度能力レーダー比較 (wRC+標準化評価)",
                height=450,
            )
            st.plotly_chart(fig_radar, use_container_width=True)

        else:
            p1_stat = get_single_season_stat(p1_p_hist, selected_season)
            p2_stat = get_single_season_stat(p2_p_hist, selected_season)

            categories = [
                "FIP (真の投手力)",
                "ERA (防御率逆算)",
                "K/BB (制球・奪三振)",
                "K/9 (奪三振率)",
                "IP (投球回)",
                "WAR",
            ]

            def build_pitching_vector(stat):
                if stat is None:
                    return [0, 0, 0, 0, 0, 0]
                fip = float(
                    pd.to_numeric(stat.get("fip", 4.30), errors="coerce") or 4.30
                )
                era = float(
                    pd.to_numeric(stat.get("era", 4.50), errors="coerce") or 4.50
                )
                kbb = float(
                    pd.to_numeric(stat.get("k_bb", 2.0), errors="coerce") or 2.0
                )
                k9 = float(pd.to_numeric(stat.get("k_9", 8.0), errors="coerce") or 8.0)
                ip = float(
                    pd.to_numeric(stat.get("inningsPitched", 0), errors="coerce") or 0
                )
                war = float(pd.to_numeric(stat.get("war", 0), errors="coerce") or 0)

                return [
                    max(0, min((6.0 - fip) / 4.0 * 100, 100)),
                    max(0, min((6.0 - era) / 4.0 * 100, 100)),
                    min(kbb / 6.0 * 100, 100),
                    min(k9 / 13.0 * 100, 100),
                    min(ip / 200.0 * 100, 100),
                    min(max(war, 0) / 8.0 * 100, 100),
                ]

            p1_vals = build_pitching_vector(p1_stat)
            p2_vals = build_pitching_vector(p2_stat)

            fig_radar = go.Figure()
            fig_radar.add_trace(
                go.Scatterpolar(
                    r=p1_vals, theta=categories, fill="toself", name=p1_name
                )
            )
            fig_radar.add_trace(
                go.Scatterpolar(
                    r=p2_vals, theta=categories, fill="toself", name=p2_name
                )
            )
            fig_radar.update_layout(
                polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
                showlegend=True,
                title=f"{selected_season}年 投手高度能力レーダー比較 (FIP標準化評価)",
                height=450,
            )
            st.plotly_chart(fig_radar, use_container_width=True)

    # ------------------------------------------------------------------
    # 🎯 2. 仮想トレード・シミュレーター
    # ------------------------------------------------------------------
    elif sub_mode == "仮想トレード・シミュレーター":
        st.subheader(
            "🔄 仮想トレード・シミュレーター (プロスペクト & 金銭補填評価拡張版)"
        )
        st.caption(
            f"選択した2チーム（【{selected_season}年】所属ロースター）根拠にトレードを行います。実績選手に加えて**「プロスペクト・アセット枠（Top 10 / Top 100等）」**および**「年俸補填（金銭トレード）」**を自由に複数組み合わせて評価可能です。"
        )

        all_teams = teams

        if len(all_teams) < 2:
            st.warning("トレード比較に必要なチームデータが不足しています。")
        else:
            col_t1, col_t2 = st.columns(2)

            with col_t1:
                team_a = st.selectbox("チーム A を選択", all_teams, index=0)
                color_a = get_team_color(team_a)
                logo_a = get_team_logo_url(team_a)

                st.markdown(
                    f'<div style="display:flex; align-items:center; gap:8px;"><img src="{logo_a}" style="width:30px; height:30px; object-fit:contain;"/> <b style="font-size:1.1rem; color:{color_a};">【{team_a}】 放出アセット</b></div>',
                    unsafe_allow_html=True,
                )
                roster_a = get_roster_by_season(team_a, selected_season)
                players_a = (
                    roster_a["player_name"].tolist() if not roster_a.empty else []
                )
                selected_a_players = st.multiselect(
                    f"【{team_a}】から放出する実績選手を選択 (Team A -> Team B)",
                    players_a,
                )

                selected_a_prospect_assets = st.multiselect(
                    f"🌱 【{team_a}】組み込むプロスペクト・アセット枠",
                    options=list(PROSPECT_ASSETS.keys()),
                    key="pros_a_multiselect",
                )

                cash_a_to_b = st.number_input(
                    f"【{team_a}】が負担・譲渡する年俸補填/金銭 ($M)",
                    min_value=0.0,
                    max_value=100.0,
                    value=0.0,
                    step=1.0,
                    help="Team AがTeam Bに対して支払う給与負担金（単位: 百万ドル）",
                )

            with col_t2:
                default_b_idx = 1 if len(all_teams) > 1 else 0
                team_b = st.selectbox("チーム B を選択", all_teams, index=default_b_idx)
                color_b = get_team_color(team_b)
                logo_b = get_team_logo_url(team_b)

                st.markdown(
                    f'<div style="display:flex; align-items:center; gap:8px;"><img src="{logo_b}" style="width:30px; height:30px; object-fit:contain;"/> <b style="font-size:1.1rem; color:{color_b};">【{team_b}】 放出アセット</b></div>',
                    unsafe_allow_html=True,
                )
                roster_b = get_roster_by_season(team_b, selected_season)
                players_b = (
                    roster_b["player_name"].tolist() if not roster_b.empty else []
                )
                selected_b_players = st.multiselect(
                    f"【{team_b}】から放出する実績選手を選択 (Team B -> Team A)",
                    players_b,
                )

                selected_b_prospect_assets = st.multiselect(
                    f"🌱 【{team_b}】組み込むプロスペクト・アセット枠",
                    options=list(PROSPECT_ASSETS.keys()),
                    key="pros_b_multiselect",
                )

                cash_b_to_a = st.number_input(
                    f"【{team_b}】が負担・譲渡する年俸補填/金銭 ($M)",
                    min_value=0.0,
                    max_value=100.0,
                    value=0.0,
                    step=1.0,
                    help="Team BがTeam Aに対して支払う給与負担金（単位: 百万ドル）",
                )

            st.divider()

            def calc_trade_package(team_name, p_names, pros_assets, season):
                df_depth = get_roster_depth_data(team_name, season)
                tot_war = 0.0
                details = []

                if p_names and not df_depth.empty:
                    sub_df = df_depth[df_depth["player_name"].isin(p_names)]
                    for p in p_names:
                        p_sub = sub_df[sub_df["player_name"] == p]
                        p_war = p_sub["war"].sum() if not p_sub.empty else 0.0
                        details.append(
                            {
                                "アセット/選手名": p,
                                "区分": "実績選手",
                                "価値(WAR相当)": p_war,
                            }
                        )
                        tot_war += p_war

                if pros_assets:
                    for asset in pros_assets:
                        a_war = PROSPECT_ASSETS.get(asset, 0.0)
                        details.append(
                            {
                                "アセット/選手名": asset,
                                "区分": "プロスペクト",
                                "価値(WAR相当)": a_war,
                            }
                        )
                        tot_war += a_war

                return tot_war, details

            war_a_out_raw, details_a = calc_trade_package(
                team_a, selected_a_players, selected_a_prospect_assets, selected_season
            )
            war_b_out_raw, details_b = calc_trade_package(
                team_b, selected_b_players, selected_b_prospect_assets, selected_season
            )

            cash_war_a = cash_a_to_b / 8.0
            cash_war_b = cash_b_to_a / 8.0

            tot_val_a_out_war = war_a_out_raw + cash_war_a
            tot_val_b_out_war = war_b_out_raw + cash_war_b

            col_res1, col_res2 = st.columns(2)

            with col_res1:
                st.write(f"### 📦 {team_a} 放出パッケージ総合評価")
                if details_a:
                    st.dataframe(
                        pd.DataFrame(details_a),
                        use_container_width=True,
                        hide_index=True,
                    )
                else:
                    st.info("実績選手・プロスペクト枠は選択されていません。")

                if cash_a_to_b > 0:
                    st.caption(
                        f"💵 給与補填/金銭譲渡 (${cash_a_to_b:.1f}M): **+{cash_war_a:.2f} WAR相当**"
                    )

                render_card(
                    "総放出アセット価値",
                    f"{tot_val_a_out_war:.1f} WAR 相当",
                    sub_text=f"${tot_val_a_out_war * WAR_MARKET_VALUE:,.0f} 相当",
                    border_color=color_a,
                )

            with col_res2:
                st.write(f"### 📦 {team_b} 放出パッケージ総合評価")
                if details_b:
                    st.dataframe(
                        pd.DataFrame(details_b),
                        use_container_width=True,
                        hide_index=True,
                    )
                else:
                    st.info("実績選手・プロスペクト枠は選択されていません。")

                if cash_b_to_a > 0:
                    st.caption(
                        f"💵 給与補填/金銭譲渡 (${cash_b_to_a:.1f}M): **+{cash_war_b:.2f} WAR相当**"
                    )

                render_card(
                    "総放出アセット価値",
                    f"{tot_val_b_out_war:.1f} WAR 相当",
                    sub_text=f"${tot_val_b_out_war * WAR_MARKET_VALUE:,.0f} 相当",
                    border_color=color_b,
                )

            st.divider()

            st.markdown("### ⚖️ 総合トレード・バランス判定結果")

            diff_war = tot_val_b_out_war - tot_val_a_out_war
            diff_val = diff_war * WAR_MARKET_VALUE

            if (
                not selected_a_players
                and not selected_b_players
                and not selected_a_prospect_assets
                and not selected_b_prospect_assets
            ):
                st.info(
                    "両チームの選択ボックスにて実績選手、プロスペクト枠、または金銭補填を設定すると、トレード判定が表示されます。"
                )
            else:
                m1, m2, m3 = st.columns(3)

                if abs(diff_war) <= 1.0:
                    status_text = "✅ 非常に釣り合いの取れたトレードです (Fair Trade)"
                    st_color = "#28a745"
                elif diff_war > 1.0:
                    status_text = f"🟩 【{team_a}】側に大幅なメリットがあるトレードです (Team A Win)"
                    st_color = "#007bff"
                else:
                    status_text = f"🟥 【{team_b}】側に大幅なメリットがあるトレードです (Team B Win)"
                    st_color = "#fd7e14"

                with m1:
                    render_card(
                        f"【{team_a}】獲得純増価値",
                        f"{diff_war:+.1f} WAR 相当",
                        border_color=color_a,
                    )
                with m2:
                    render_card(
                        "純増金銭評価", f"${diff_val:+,.0f}", border_color=color_a
                    )
                with m3:
                    render_card("トレード成立判定", status_text, border_color=st_color)


# ------------------------------------------------------------------
# 🤖 モード 8: 本番AI ニュース＆トレンド感情分析
# ------------------------------------------------------------------
elif mode == "📰 本番AI ニュース＆トレンド感情分析":
    st.header("📰 本番AI ニュース＆トレンド感情分析エンジン")
    st.caption(
        "最新のMLBニュース記事テキストを入力・分析し、LLM（OpenAI/Gemini等）が感情スコア、トレンド自動タグ、GM視点での要約、編成インパクトを即座にJSON構造化して抽出します。"
    )

    tab_n1, tab_n2 = st.tabs(
        ["🤖 リアルタイム・ニュースAI解析", "📌 注目選手・チーム トレンド分析"]
    )

    with tab_n1:
        st.subheader("📝 ニューステキストAI解析コンソール")

        default_sample_news = """Shohei Ohtani left Wednesday's game against the Giants with right oblique tightness and is undergoing further evaluation, the team announced. Manager Dave Roberts stated that Ohtani felt discomfort during his second plate appearance. If Ohtani requires an Injured List (IL) stint, it would present a major setback for the Dodgers' offense and roster balance."""

        input_news = st.text_area(
            "解析するMLBニュース（英語または日本語）を入力してください:",
            value=default_sample_news,
            height=130,
        )

        col_n_btn, col_n_opt = st.columns([1, 2])
        with col_n_btn:
            run_analysis = st.button(
                "⚡ LLM AIで分析を実行", type="primary", use_container_width=True
            )

        if run_analysis or input_news:
            with st.spinner("🤖 AIモデルがニュース文面を読読中..."):
                analysis_res = analyze_news_with_llm(
                    input_news, api_key=user_api_key, provider=ai_provider
                )

            st.divider()
            st.markdown("### 📊 AI解析レポート")

            col_res1, col_res2, col_res3 = st.columns(3)
            score_val = analysis_res.get("sentiment_score", 0)
            score_color = (
                "#28a745"
                if score_val > 10
                else ("#dc3545" if score_val < -10 else "#6c757d")
            )

            with col_res1:
                render_card(
                    "感情分析スコア (Sentiment)",
                    f"{score_val:+d}%",
                    sub_text=analysis_res.get("sentiment_label", "Neutral"),
                    border_color=score_color,
                )
            with col_res2:
                render_card(
                    "編成・世論インパクト",
                    analysis_res.get("impact", "Low"),
                    border_color="#007bff",
                )
            with col_res3:
                tags_str = " ".join([f"`{t}`" for t in analysis_res.get("tags", [])])
                st.markdown(f"**抽出トレンドタグ:**\n\n{tags_str}")

            st.write("#### 📝 AIによる3行GM要約")
            st.info(analysis_res.get("summary", "要約なし"))

    with tab_n2:
        st.subheader("📌 トレンド話題・ニュース要約カード（自動抽出）")
        st.caption(
            "現在MLB界隈で話題になっているトピックスのAI解析カードプレビューです。"
        )

        sample_topics = [
            (
                "Aaron Judge",
                "Aaron Judge smashed his 40th home run of the season in a blowout win against the Red Sox, setting a new franchise record.",
                85,
                "🏆 大活躍",
            ),
            (
                "Blake Snell",
                "Blake Snell's contract extension talks have hit a stalemate, increasing trade rumors before the deadline.",
                -25,
                "🔥 トレード噂",
            ),
        ]

        for p_name, news_txt, default_score, tag in sample_topics:
            res = analyze_news_with_llm(
                news_txt, api_key=user_api_key, provider=ai_provider
            )
            badge_color = "#28a745" if res["sentiment_score"] > 0 else "#dc3545"

            st.markdown(
                f"""
                <div class="news-card" style="border-left-color: {badge_color};">
                    <h4 style="margin:0 0 5px 0;">👤 {p_name} <span style="font-size:0.8rem; background:#e9ecef; padding:2px 6px; border-radius:4px;">{tag}</span></h4>
                    <p style="margin:0 0 5px 0; font-size:0.95rem; color:#333;">{res['summary']}</p>
                    <small style="color:#6c757d;">AI Sentiment Score: <b>{res['sentiment_score']:+d}%</b> | Impact: <b>{res['impact']}</b></small>
                </div>
                """,
                unsafe_allow_html=True,
            )
