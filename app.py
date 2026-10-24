import sqlite3
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(
    page_title="MLB 選手キャリア＆チーム補強ダッシュボード", layout="wide"
)

DB_PATH = "mlb_player_stats.db"

# 1 WARあたりの市場価値設定 (ドル)
WAR_MARKET_VALUE = 8_000_000  # $8M / 1 WAR
MLB_MINIMUM_SALARY = 780_000  # データ未登録時の推定年俸 ($780k)


# --- 簡易 WAR 計算 ＆ ポジション補正ユーティリティ ---
def process_war_and_position(df, is_pitcher=False):
    """DBにWARやposが無い場合にスタッツから動的計算・割り当てを行う関数"""
    if df.empty:
        return df

    df = df.copy()

    # 1. WAR の補正・簡易算定
    if "war" not in df.columns or df["war"].isnull().all():
        if is_pitcher:
            # 投手WAR: ( league_era(4.30) - era ) * IP / 9 + 投球回貢献
            ip = pd.to_numeric(df.get("inningsPitched", 0), errors="coerce").fillna(0)
            era = pd.to_numeric(df.get("era", 4.30), errors="coerce").fillna(4.30)
            df["war"] = ((4.30 - era) * (ip / 9.0) * 1.2) + (ip / 60.0)
            df["war"] = df["war"].round(1)
        else:
            # 打者WAR: ( ops - league_ops(0.710) ) * PA / 補正 + 出場貢献
            ops = pd.to_numeric(df.get("ops", 0.710), errors="coerce").fillna(0.710)
            pa = pd.to_numeric(df.get("plateAppearances", 0), errors="coerce").fillna(0)
            df["war"] = ((ops - 0.710) * (pa / 12.0)) + (pa / 300.0)
            df["war"] = df["war"].round(1)
    else:
        df["war"] = pd.to_numeric(df["war"], errors="coerce").fillna(0.0)

    # 2. ポジション (pos) の補正・自動判別
    if "pos" not in df.columns or df["pos"].isnull().all():
        if is_pitcher:
            df["pos"] = df.apply(
                lambda r: (
                    "SP"
                    if pd.to_numeric(r.get("gamesStarted", 0), errors="coerce") > 3
                    or (
                        pd.to_numeric(r.get("gamesStarted", 0), errors="coerce")
                        / max(
                            pd.to_numeric(r.get("gamesPlayed", 1), errors="coerce"), 1
                        )
                    )
                    > 0.4
                    else "RP"
                ),
                axis=1,
            )
        else:
            df["pos"] = "DH"
    else:
        if is_pitcher:
            df["pos"] = df.apply(
                lambda r: (
                    "SP"
                    if pd.to_numeric(r.get("gamesStarted", 0), errors="coerce") > 3
                    else "RP"
                ),
                axis=1,
            )
        else:
            df["pos"] = df["pos"].fillna("DH").replace(["", "P", "TWP"], "DH")

    return df


# --- データベース取得用関数 ---


@st.cache_data
def get_seasons():
    """DB内に存在するシーズン一覧を取得"""
    conn = sqlite3.connect(DB_PATH)
    try:
        q = "SELECT DISTINCT season FROM batting_stats UNION SELECT DISTINCT season FROM pitching_stats ORDER BY season DESC"
        seasons = pd.read_sql_query(q, conn)["season"].dropna().astype(int).tolist()
    except Exception:
        seasons = [2026, 2025, 2024, 2023, 2022, 2021, 2020, 2019, 2018, 2017]
    conn.close()
    return seasons


@st.cache_data
def get_all_players():
    """全シーズンを通じた選手マスターリストを取得（コンパレーター用）"""
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


@st.cache_data
def get_teams_by_season(season):
    """指定シーズンのチーム一覧を取得"""
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


@st.cache_data
def get_roster_by_season(team_name, season):
    """選択されたチーム・シーズンの所属選手リストを取得"""
    conn = sqlite3.connect(DB_PATH)
    query_b = "SELECT DISTINCT player_id, player_name FROM batting_stats WHERE season = ? AND team_name = ?"
    query_p = "SELECT DISTINCT player_id, player_name FROM pitching_stats WHERE season = ? AND team_name = ?"

    df_b = pd.read_sql_query(query_b, conn, params=(season, team_name))
    df_p = pd.read_sql_query(query_p, conn, params=(season, team_name))
    conn.close()

    df_combined = pd.concat([df_b, df_p]).drop_duplicates(subset=["player_id"])
    return df_combined.sort_values(by="player_name")


def get_roster_depth_data(team_name, season):
    """チームのポジション別WAR集計および選手別内訳の抽出"""
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


@st.cache_data
def get_all_teams_positional_war(season):
    """全30球団のポジション別合計WARを集計（ヒートマップ用）"""
    conn = sqlite3.connect(DB_PATH)
    q_b = "SELECT * FROM batting_stats WHERE season = ? AND team_name IS NOT NULL"
    try:
        df_b = pd.read_sql_query(q_b, conn, params=(season,))
    except Exception:
        df_b = pd.DataFrame()
    conn.close()

    if df_b.empty:
        return pd.DataFrame()

    df_b = process_war_and_position(df_b, is_pitcher=False)

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
    }
    df_b["norm_pos"] = df_b["pos"].map(pos_map).fillna("DH")

    pos_war = df_b.groupby(["team_name", "norm_pos"])["war"].sum().reset_index()
    return pos_war


def get_player_history(player_id):
    """選手の過去の成績推移を取得（打者・投手の両方を全キャリア表示）"""
    conn = sqlite3.connect(DB_PATH)
    query_b = "SELECT * FROM batting_stats WHERE CAST(player_id AS TEXT) = ? ORDER BY season DESC"
    query_p = "SELECT * FROM pitching_stats WHERE CAST(player_id AS TEXT) = ? ORDER BY season DESC"

    df_b = pd.read_sql_query(query_b, conn, params=(str(player_id),))
    df_p = pd.read_sql_query(query_p, conn, params=(str(player_id),))
    conn.close()

    df_b = process_war_and_position(df_b, is_pitcher=False)
    df_p = process_war_and_position(df_p, is_pitcher=True)

    return df_b, df_p


def get_player_transactions(player_id):
    """選手個人の公示・移籍履歴を取得"""
    conn = sqlite3.connect(DB_PATH)
    query = "SELECT date, type, description, from_team, to_team FROM transactions WHERE CAST(player_id AS TEXT) = ? ORDER BY date DESC"
    try:
        df_trans = pd.read_sql_query(query, conn, params=(str(player_id),))
    except Exception:
        df_trans = pd.DataFrame()
    conn.close()
    return df_trans


def get_player_contracts(player_id):
    """選手の全期間の年俸・契約情報・サービスタイムを取得（重複除去＋自動フォールバック機能付き）"""
    conn = sqlite3.connect(DB_PATH)
    query = """
        SELECT season, salary, aav, service_time, contract_years, free_agent_year 
        FROM contracts 
        WHERE CAST(player_id AS TEXT) = ? 
        ORDER BY season DESC
    """
    try:
        df_contract = pd.read_sql_query(query, conn, params=(str(player_id),))
        if not df_contract.empty:
            # 同一シーズンの重複行が存在する場合は年俸が高い正データ(非ダミー)を優先して残す
            df_contract = df_contract.sort_values(
                by=["season", "salary"], ascending=[False, False]
            )
            df_contract = df_contract.drop_duplicates(subset=["season"], keep="first")
    except Exception:
        df_contract = pd.DataFrame()
    conn.close()
    return df_contract


def save_player_contracts(player_id, player_name, edited_df):
    """st.data_editor で編集された契約データを SQLite に保存"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute(
        "DELETE FROM contracts WHERE CAST(player_id AS TEXT) = ?",
        (str(player_id),),
    )

    for _, row in edited_df.iterrows():
        season_val = row.get("season")
        if pd.notnull(season_val):
            cursor.execute(
                """
                INSERT INTO contracts (player_id, player_name, season, salary, aav, service_time, contract_years, free_agent_year)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    int(player_id),
                    player_name,
                    int(season_val),
                    row.get("salary"),
                    row.get("aav"),
                    (
                        str(row.get("service_time"))
                        if pd.notnull(row.get("service_time"))
                        else "-"
                    ),
                    row.get("contract_years"),
                    row.get("free_agent_year"),
                ),
            )

    conn.commit()
    conn.close()


def get_team_reinforcements(team_name, season):
    """指定チーム・年度の補強(IN)および放出(OUT)を抽出"""
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

    # シーズン終了後のFA退団検知
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


# --- UI アプリメインレイアウト ---

st.title("⚾ MLB 選手キャリア＆チーム補強ダッシュボード")

mode = st.sidebar.radio(
    "📌 表示モード切替",
    [
        "🧩 チーム別Depth Chart・ポジショナル分析",
        "👤 選手検索（個人キャリア）",
        "🏢 チーム補強・放出・公示一覧",
        "⚔️ シミュレーション & 比較ツール ( interactive GUI )",
    ],
)

seasons_list = get_seasons()
selected_season = st.sidebar.selectbox("① 対象シーズンを選択", seasons_list)
teams = get_teams_by_season(selected_season)

if not teams and mode != "⚔️ シミュレーション & 比較ツール ( interactive GUI )":
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
        st.header(
            f"🧩 {selected_team} Depth Chart & ロースター穴埋め分析 ({selected_season}年)"
        )

        tab_depth, tab_heatmap, tab_age = st.tabs(
            [
                "🛡️ チーム別 Depth Chart & 補強ポイント",
                "🌐 全30球団 ポジショナルWARマップ",
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
                pos_summary = (
                    df_depth.groupby("norm_pos")["war"]
                    .sum()
                    .reindex(target_positions)
                    .fillna(0.0)
                    .reset_index()
                )
                pos_summary.columns = ["Position", "Total_WAR"]

                total_war = pos_summary["Total_WAR"].sum()
                avg_age = (
                    df_depth["age"].dropna().mean()
                    if "age" in df_depth.columns
                    else None
                )

                if avg_age and avg_age >= 28.5 and total_war >= 15.0:
                    team_status = "🏆 Win-Now (全盛期・勝利至上期)"
                    status_color = "green"
                elif avg_age and avg_age < 27.0 and total_war < 10.0:
                    team_status = "🌱 Rebuild (若手育成・再建期)"
                    status_color = "orange"
                else:
                    team_status = "⚖️ Contender / Transition (競合・端境期)"
                    status_color = "blue"

                col_m1, col_m2, col_m3 = st.columns(3)
                with col_m1:
                    st.metric(label="チーム総 WAR", value=f"{total_war:.1f} WAR")
                with col_m2:
                    st.metric(
                        label="所属選手平均年齢",
                        value=f"{avg_age:.1f} 歳" if pd.notnull(avg_age) else "N/A",
                    )
                with col_m3:
                    st.subheader(f":{status_color}[{team_status}]")

                st.divider()

                st.subheader("📊 ポジション別 WAR 分布 (強度・補強穴マップ)")
                st.caption(
                    "※ WARが低いポジション（赤色領域）がチームの最大の補強ポイント（穴）です。"
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

                st.subheader("🔍 ポジション別 Depth Chart (選手内訳)")

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
                        cols_show = [
                            c
                            for c in ["player_name", "war", "games", "age"]
                            if c in df_pos_players.columns
                        ]
                        st.dataframe(
                            df_pos_players[cols_show].rename(
                                columns={
                                    "player_name": "選手名",
                                    "war": "WAR",
                                    "games": "出場試合数",
                                    "age": "年齢",
                                }
                            ),
                            use_container_width=True,
                            hide_index=True,
                        )
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
                            color_discrete_sequence=["#2b5c8f"],
                        )
                        fig_age.update_layout(height=280)
                        st.plotly_chart(fig_age, use_container_width=True)

        # --- タブ 2: 全30球団 ポジショナルWARマップ ---
        with tab_heatmap:
            st.markdown("### 🗺️ 全30球団 ポジショナルWARヒートマップ")
            st.caption(
                "全30球団の野手ポジション別合計WARを視覚化します。赤〜薄い色のセルが補強ポイント（穴）です。"
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
                    height=750,
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
                            f"⚠️ **{selected_team} 最優先補強ポイント (穴):** **`{weakest_p}`** （合計WAR: `{weakest_w:.1f}`）"
                        )
                    with col_h2:
                        st.success(
                            f"強みポジション: **`{strongest_p}`** （合計WAR: `{strongest_w:.1f}`）"
                        )
            else:
                st.info("※ポジショナルWARデータが取得できませんでした。")

        # --- タブ 3: 年齢・世代構成グラフ (Win-Now / Rebuild) ---
        with tab_age:
            st.markdown("### ⏳ 年齢・世代構成 & チームフェーズ分析")
            st.caption(
                "チーム主力選手の年齢分布とWAR貢献度から、勝負期（Win-Now）か再建期（Rebuild）かを視覚的に分析します。"
            )

            if not df_depth.empty and "age" in df_depth.columns:
                df_valid_age = df_depth.dropna(subset=["age"]).copy()

                if not df_valid_age.empty:
                    raw_avg_age = df_valid_age["age"].mean()

                    # WARがプラスの主力選手によるWAR加重平均年齢
                    main_contrib = df_valid_age[df_valid_age["war"] > 0]
                    if not main_contrib.empty and main_contrib["war"].sum() > 0:
                        weighted_age = (
                            main_contrib["age"] * main_contrib["war"]
                        ).sum() / main_contrib["war"].sum()
                    else:
                        weighted_age = raw_avg_age

                    col_a1, col_a2, col_a3 = st.columns(3)
                    col_a1.metric("チーム全体の平均年齢", f"{raw_avg_age:.1f} 歳")
                    col_a2.metric("主力 (WAR加重) 平均年齢", f"{weighted_age:.1f} 歳")

                    if weighted_age >= 29.0:
                        phase_label = "🔥 Win-Now (即戦力・全盛期中心)"
                        phase_color = "red"
                    elif weighted_age <= 26.5:
                        phase_label = "🌱 Rebuild / Young Core (再建・若手中心)"
                        phase_color = "green"
                    else:
                        phase_label = "⚖️ Balanced (全盛期と若手のバランス型)"
                        phase_color = "blue"

                    col_a3.markdown("**チームフェーズ判定:**")
                    col_a3.markdown(f":{phase_color}[**{phase_label}**]")

                    st.divider()

                    # 年齢 vs WAR 散布図
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

                    # プライムゾーン（26〜30歳）の強調表示
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
# モード 2: 👤 選手検索（個人キャリア）
# ------------------------------------------------------------------
elif mode == "👤 選手検索（個人キャリア）":
    selected_team = st.sidebar.selectbox("② チームを選択してください", teams)

    if selected_team:
        st.header(f"🏢 {selected_team} ({selected_season}年所属選手)")

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

            st.divider()

            if selected_player_id is not None:
                st.subheader(f"👤 {selected_player_name} 選手のキャリア・契約情報")

                tab_stats, tab_contract, tab_edit, tab_trans = st.tabs(
                    [
                        "📊 成績推移 (キャリア全期間)",
                        "💰 契約・年俸 & Surplus Value",
                        "✏️ 契約・サービスタイム管理 (DB編集)",
                        "📜 移籍・公示履歴 (Transactions)",
                    ]
                )

                df_b_hist, df_p_hist = get_player_history(selected_player_id)

                # 1. 成績推移（二刀流選手完全対応）
                with tab_stats:
                    is_two_way = not df_b_hist.empty and not df_p_hist.empty
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
                        c1.metric("通算 打者WAR", f"{b_war_total:.1f}")
                        c2.metric("通算 投手WAR", f"{p_war_total:.1f}")
                        c3.metric(
                            "🔥 通算 合計WAR (投打合算)", f"{total_career_war:.1f}"
                        )
                        st.divider()

                    if not df_b_hist.empty:
                        st.write("### 🏏 打撃成績 (全期間)")
                        cols_to_drop = [
                            c
                            for c in ["player_id", "team_id"]
                            if c in df_b_hist.columns
                        ]
                        df_b_display = df_b_hist.drop(columns=cols_to_drop)
                        first_cols = [
                            c
                            for c in ["season", "team_name", "player_name"]
                            if c in df_b_display.columns
                        ]
                        other_cols = [
                            c for c in df_b_display.columns if c not in first_cols
                        ]
                        st.dataframe(
                            df_b_display[first_cols + other_cols],
                            use_container_width=True,
                            hide_index=True,
                        )

                    if not df_p_hist.empty:
                        st.write("### ⚾ 投手成績 (全期間)")
                        cols_to_drop = [
                            c
                            for c in ["player_id", "team_id"]
                            if c in df_p_hist.columns
                        ]
                        df_p_display = df_p_hist.drop(columns=cols_to_drop)
                        first_cols = [
                            c
                            for c in ["season", "team_name", "player_name"]
                            if c in df_p_display.columns
                        ]
                        other_cols = [
                            c for c in df_p_display.columns if c not in first_cols
                        ]
                        st.dataframe(
                            df_p_display[first_cols + other_cols],
                            use_container_width=True,
                            hide_index=True,
                        )

                # 2. 契約・年俸 & Surplus Value（全キャリア期間対応）
                with tab_contract:
                    st.write("### 💰 契約情報・サービスタイム (MLS) & 過剰価値評価")

                    df_contracts = get_player_contracts(selected_player_id)

                    if not df_contracts.empty:
                        # 投打合算WARのシーズン別集計
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
                        df_c_disp["bat_war"] = (
                            df_c_disp["season"].map(b_war_by_season).fillna(0.0)
                        )
                        df_c_disp["pitch_war"] = (
                            df_c_disp["season"].map(p_war_by_season).fillna(0.0)
                        )
                        df_c_disp["total_war"] = (
                            df_c_disp["bat_war"] + df_c_disp["pitch_war"]
                        )

                        # 市場価値 Dollars ($8M / WAR) と Surplus Value
                        df_c_disp["market_value"] = (
                            df_c_disp["total_war"] * WAR_MARKET_VALUE
                        )
                        df_c_disp["surplus_value"] = df_c_disp[
                            "market_value"
                        ] - df_c_disp["salary"].fillna(MLB_MINIMUM_SALARY)

                        df_c_disp["年俸 ($)"] = df_c_disp["salary"].apply(
                            lambda x: f"${x:,.0f}" if pd.notnull(x) else "-"
                        )
                        df_c_disp["AAV (平均年俸)"] = df_c_disp["aav"].apply(
                            lambda x: f"${x:,.0f}" if pd.notnull(x) else "-"
                        )
                        df_c_disp["サービスタイム"] = df_c_disp["service_time"].fillna(
                            "-"
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
                                    "サービスタイム",
                                    "contract_years",
                                    "free_agent_year",
                                ]
                            ].rename(
                                columns={
                                    "season": "シーズン",
                                    "total_war": "合計WAR",
                                    "contract_years": "契約年数",
                                    "free_agent_year": "FA獲得予定年",
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
                        st.metric(
                            label="1 WAR あたりの標準市場価格", value="$8,000,000"
                        )
                    with col_sv2:
                        sample_war = 3.0
                        est_market_val = sample_war * WAR_MARKET_VALUE
                        st.metric(
                            label=f"参考: WAR {sample_war} 達成時の金銭価値",
                            value=f"${est_market_val:,.0f}",
                        )

                # 3. DB直接編集機能
                with tab_edit:
                    st.write(
                        f"### ✏️ {selected_player_name} 選手の契約・サービスタイム編集"
                    )
                    st.caption(
                        "表の数値を直接クリックして変更し、「💾 データベースに保存」ボタンを押すと即座にDBへ反映されます。"
                    )

                    df_contracts_edit = get_player_contracts(selected_player_id)

                    if df_contracts_edit.empty:
                        df_contracts_edit = pd.DataFrame(
                            [
                                {
                                    "season": selected_season,
                                    "salary": 780000.0,
                                    "aav": 780000.0,
                                    "service_time": "1.000",
                                    "contract_years": 1,
                                    "free_agent_year": selected_season + 4,
                                }
                            ]
                        )

                    edited_df = st.data_editor(
                        df_contracts_edit,
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
                            "service_time": st.column_config.TextColumn(
                                "サービスタイム (MLS)", help="例: 6.172, 3.045"
                            ),
                            "contract_years": st.column_config.NumberColumn(
                                "契約年数", format="%d"
                            ),
                            "free_agent_year": st.column_config.NumberColumn(
                                "FA予定年", format="%d"
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
                            f"✅ {selected_player_name} 選手の契約・サービスタイムデータを更新しました！"
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
# モード 3: 🏢 チーム補強・放出・公示一覧
# ------------------------------------------------------------------
elif mode == "🏢 チーム補強・放出・公示一覧":
    st.header("🏢 チーム別 カテゴリ補強・放出動向")

    selected_team = st.sidebar.selectbox("② チームを選択", teams)

    if selected_team and selected_season:
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
# モード 4: ⚔️ シミュレーション & 比較ツール ( interactive GUI )
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
    # 4-1. 2選手対比コンパレーター
    # ------------------------------------------------------------------
    if sub_mode == "2選手対比コンパレーター":
        st.subheader("📊 2選手対比コンパレーター")
        st.caption(
            "2名の選手を選択し、単年スタッツのレーダーチャート比較や、全キャリアのWAR推移グラフを並べて視覚化します。"
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

        p1_b_hist, p1_p_hist = get_player_history(p1_id)
        p2_b_hist, p2_p_hist = get_player_history(p2_id)

        # 1. キャリアWAR推移比較 (折れ線グラフ)
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

        # 2. シーズン単年レーダーチャート対比
        st.markdown(
            f"### 🎯 シーズン別能力比較（レーダーチャート） - 【{selected_season}年】"
        )

        comp_type = st.radio(
            "比較対象指標の種類を選択:",
            ["打撃スタッツ (Batting)", "投手スタッツ (Pitching)"],
            horizontal=True,
        )

        def get_single_season_stat(df, season):
            if df.empty:
                return None
            sub = df[df["season"] == season]
            if sub.empty:
                return None
            return sub.iloc[0]

        if comp_type == "打撃スタッツ (Batting)":
            p1_stat = get_single_season_stat(p1_b_hist, selected_season)
            p2_stat = get_single_season_stat(p2_b_hist, selected_season)

            categories = [
                "AVG (打率)",
                "OBP (出塁率)",
                "SLG (長打率)",
                "OPS",
                "HR (本塁打)",
                "WAR",
            ]

            def build_batting_vector(stat):
                if stat is None:
                    return [0, 0, 0, 0, 0, 0]
                avg = float(pd.to_numeric(stat.get("avg", 0), errors="coerce") or 0)
                obp = float(pd.to_numeric(stat.get("obp", 0), errors="coerce") or 0)
                slg = float(pd.to_numeric(stat.get("slg", 0), errors="coerce") or 0)
                ops = float(pd.to_numeric(stat.get("ops", 0), errors="coerce") or 0)
                hr = float(pd.to_numeric(stat.get("homeRuns", 0), errors="coerce") or 0)
                war = float(pd.to_numeric(stat.get("war", 0), errors="coerce") or 0)

                # レーダーチャート用に正規化（0-100スケール近似）
                return [
                    min(avg / 0.350 * 100, 100),
                    min(obp / 0.450 * 100, 100),
                    min(slg / 0.650 * 100, 100),
                    min(ops / 1.100 * 100, 100),
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
                title=f"{selected_season}年 打撃能力レーダー比較 (相対評価)",
                height=450,
            )
            st.plotly_chart(fig_radar, use_container_width=True)

        else:
            p1_stat = get_single_season_stat(p1_p_hist, selected_season)
            p2_stat = get_single_season_stat(p2_p_hist, selected_season)

            categories = [
                "ERA (防御率逆算)",
                "WHIP (逆算)",
                "SO/9",
                "BB/9 (逆算)",
                "IP (投球回)",
                "WAR",
            ]

            def build_pitching_vector(stat):
                if stat is None:
                    return [0, 0, 0, 0, 0, 0]
                era = float(
                    pd.to_numeric(stat.get("era", 4.50), errors="coerce") or 4.50
                )
                whip = float(
                    pd.to_numeric(stat.get("whip", 1.30), errors="coerce") or 1.30
                )
                so9 = float(
                    pd.to_numeric(stat.get("strikeoutsPer9Inn", 0), errors="coerce")
                    or 0
                )
                bb9 = float(
                    pd.to_numeric(stat.get("walksPer9Inn", 3.0), errors="coerce") or 3.0
                )
                ip = float(
                    pd.to_numeric(stat.get("inningsPitched", 0), errors="coerce") or 0
                )
                war = float(pd.to_numeric(stat.get("war", 0), errors="coerce") or 0)

                return [
                    max(0, min((6.0 - era) / 4.0 * 100, 100)),
                    max(0, min((2.0 - whip) / 1.2 * 100, 100)),
                    min(so9 / 13.0 * 100, 100),
                    max(0, min((5.0 - bb9) / 4.0 * 100, 100)),
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
                title=f"{selected_season}年 投手能力レーダー比較 (相対評価)",
                height=450,
            )
            st.plotly_chart(fig_radar, use_container_width=True)

    # ------------------------------------------------------------------
    # 4-2. 仮想トレード・シミュレーター
    # ------------------------------------------------------------------
    elif sub_mode == "仮想トレード・シミュレーター":
        st.subheader("🔄 仮想トレード・シミュレーター")
        st.caption(
            f"選択した2チーム（【{selected_season}年】所属ロースター）間で交換トレードを行った場合、両球団の獲得総WARおよび金銭価値バランスが釣り合っているかを簡易チェックします。"
        )

        all_teams = teams

        if len(all_teams) < 2:
            st.warning("トレード比較に必要なチームデータが不足しています。")
        else:
            col_t1, col_t2 = st.columns(2)

            with col_t1:
                team_a = st.selectbox("チーム A を選択", all_teams, index=0)
                roster_a = get_roster_by_season(team_a, selected_season)
                players_a = (
                    roster_a["player_name"].tolist() if not roster_a.empty else []
                )
                selected_a_players = st.multiselect(
                    f"【{team_a}】から放出する選手を選択 (Team A -> Team B)",
                    players_a,
                )

            with col_t2:
                default_b_idx = 1 if len(all_teams) > 1 else 0
                team_b = st.selectbox("チーム B を選択", all_teams, index=default_b_idx)
                roster_b = get_roster_by_season(team_b, selected_season)
                players_b = (
                    roster_b["player_name"].tolist() if not roster_b.empty else []
                )
                selected_b_players = st.multiselect(
                    f"【{team_b}】から放出する選手を選択 (Team B -> Team A)",
                    players_b,
                )

            st.divider()

            # WAR計算関数
            def calc_trade_package_war(team_name, player_names, season):
                if not player_names:
                    return 0.0, []

                df_depth = get_roster_depth_data(team_name, season)
                if df_depth.empty:
                    return 0.0, []

                sub_df = df_depth[df_depth["player_name"].isin(player_names)]
                details = []
                total_war = 0.0

                for p in player_names:
                    p_sub = sub_df[sub_df["player_name"] == p]
                    p_war = p_sub["war"].sum() if not p_sub.empty else 0.0
                    details.append({"player_name": p, "war": p_war})
                    total_war += p_war

                return total_war, details

            war_a_out, details_a = calc_trade_package_war(
                team_a, selected_a_players, selected_season
            )
            war_b_out, details_b = calc_trade_package_war(
                team_b, selected_b_players, selected_season
            )

            val_a_out = war_a_out * WAR_MARKET_VALUE
            val_b_out = war_b_out * WAR_MARKET_VALUE

            col_res1, col_res2 = st.columns(2)

            with col_res1:
                st.write(f"### 📦 {team_a} が放出するアセット")
                if details_a:
                    st.dataframe(
                        pd.DataFrame(details_a).rename(
                            columns={"player_name": "選手名", "war": "WAR"}
                        ),
                        use_container_width=True,
                        hide_index=True,
                    )
                else:
                    st.info("選手が選択されていません。")
                st.metric(
                    "放出 WAR 合計",
                    f"{war_a_out:.1f} WAR",
                    delta=f"${val_a_out:,.0f} 相当",
                )

            with col_res2:
                st.write(f"### 📦 {team_b} が放出するアセット")
                if details_b:
                    st.dataframe(
                        pd.DataFrame(details_b).rename(
                            columns={"player_name": "選手名", "war": "WAR"}
                        ),
                        use_container_width=True,
                        hide_index=True,
                    )
                else:
                    st.info("選手が選択されていません。")
                st.metric(
                    "放出 WAR 合計",
                    f"{war_b_out:.1f} WAR",
                    delta=f"${val_b_out:,.0f} 相当",
                )

            st.divider()

            # トレードバランス判定
            st.markdown("### ⚖️ 仮想トレード・バランス評価結果")

            diff_war = war_b_out - war_a_out  # Team A の純増減 WAR
            diff_val = diff_war * WAR_MARKET_VALUE

            if not selected_a_players and not selected_b_players:
                st.info(
                    "両チームの選択ボックスから対象選手を指定するとトレード判定が表示されます。"
                )
            else:
                m1, m2, m3 = st.columns(3)

                m1.metric(f"【{team_a}】獲得純増 WAR", f"{diff_war:+.1f} WAR")
                m2.metric("純増金銭価値 (市場評価)", f"${diff_val:+,.0f}")

                if abs(diff_war) <= 1.0:
                    status_text = "✅ 非常に釣り合いの取れたトレードです (Fair Trade)"
                    st_color = "green"
                elif diff_war > 1.0:
                    status_text = f"🟩 【{team_a}】側に大幅なメリットがあるトレードです (Team A Win)"
                    st_color = "blue"
                else:
                    status_text = f"🟥 【{team_b}】側に大幅なメリットがあるトレードです (Team B Win)"
                    st_color = "orange"

                with m3:
                    st.markdown("**トレード成立判定:**")
                    st.markdown(f":{st_color}[**{status_text}**]")
