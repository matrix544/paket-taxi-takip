import os
import sqlite3
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).parent
DB_PATH = APP_DIR / "paket_taxi.db"

st.set_page_config(page_title="Paket Taxi | Kazanç Takibi", page_icon="🛵", layout="wide")

DEFAULTS = {
    "salary": 85000.0,
    "bonus_threshold": 25,
    "bonus_rate": 35.0,
    "motor_rent": 13500.0,
    "accounting": 1000.0,
    "default_fuel": 300.0,
}

def supabase_client():
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_KEY", "")
    try:
        url = st.secrets.get("SUPABASE_URL", url)
        key = st.secrets.get("SUPABASE_KEY", key)
    except Exception:
        pass
    if not url or not key:
        return None
    try:
        from supabase import create_client
        return create_client(url, key)
    except Exception:
        return None

def init_sqlite():
    with sqlite3.connect(DB_PATH) as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            work_date TEXT NOT NULL UNIQUE,
            packages INTEGER NOT NULL DEFAULT 0,
            hours REAL NOT NULL DEFAULT 0,
            extra_income REAL NOT NULL DEFAULT 0,
            fuel_cash REAL NOT NULL DEFAULT 0,
            fuel_card REAL NOT NULL DEFAULT 0,
            other_expenses REAL NOT NULL DEFAULT 0,
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )
        """)
        con.commit()

def get_records():
    client = supabase_client()
    if client:
        try:
            res = client.table("daily_records").select("*").order("work_date", desc=True).execute()
            return pd.DataFrame(res.data or [])
        except Exception as e:
            st.error("Çevrim içi veritabanına bağlanılamadı. Supabase tablosunu ve Secrets ayarlarını kontrol et.")
            st.caption(str(e))
            return pd.DataFrame()
    init_sqlite()
    with sqlite3.connect(DB_PATH) as con:
        return pd.read_sql_query("SELECT * FROM records ORDER BY work_date DESC", con)

def save_record(row):
    client = supabase_client()
    payload = {
        "work_date": row["work_date"],
        "packages": int(row["packages"]),
        "hours": float(row["hours"]),
        "extra_income": float(row["extra_income"]),
        "fuel_cash": float(row["fuel_cash"]),
        "fuel_card": float(row["fuel_card"]),
        "other_expenses": float(row["other_expenses"]),
        "note": row["note"],
    }
    if client:
        client.table("daily_records").upsert(payload, on_conflict="work_date").execute()
        return
    init_sqlite()
    with sqlite3.connect(DB_PATH) as con:
        con.execute("""
        INSERT INTO records(work_date, packages, hours, extra_income, fuel_cash, fuel_card, other_expenses, note, created_at)
        VALUES(?,?,?,?,?,?,?,?,?)
        ON CONFLICT(work_date) DO UPDATE SET
        packages=excluded.packages, hours=excluded.hours, extra_income=excluded.extra_income,
        fuel_cash=excluded.fuel_cash, fuel_card=excluded.fuel_card,
        other_expenses=excluded.other_expenses, note=excluded.note
        """, (*payload.values(), datetime.now().isoformat(timespec="seconds")))
        con.commit()

def delete_record(work_date):
    client = supabase_client()
    if client:
        client.table("daily_records").delete().eq("work_date", work_date).execute()
        return
    init_sqlite()
    with sqlite3.connect(DB_PATH) as con:
        con.execute("DELETE FROM records WHERE work_date=?", (work_date,))
        con.commit()

def money(v):
    return f"{float(v):,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")

def enrich(df):
    if df.empty:
        return df
    for c in ["packages", "hours", "extra_income", "fuel_cash", "fuel_card", "other_expenses"]:
        if c not in df:
            df[c] = 0
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    df["work_date"] = pd.to_datetime(df["work_date"], errors="coerce").dt.date.astype(str)
    df["bonus"] = (df["packages"] - DEFAULTS["bonus_threshold"]).clip(lower=0) * DEFAULTS["bonus_rate"]
    df["day_costs"] = df["fuel_cash"] + df["other_expenses"]
    df["daily_variable_net"] = df["bonus"] + df["extra_income"] - df["day_costs"]
    return df

st.markdown("""
<style>
.block-container {padding-top: 1.4rem; padding-bottom: 2rem; max-width: 1200px;}
[data-testid="stMetric"] {background: var(--secondary-background-color); padding: 14px 16px; border-radius: 14px; border: 1px solid rgba(128,128,128,.18);}
.stButton>button {border-radius: 10px; min-height: 2.7rem;}
</style>
""", unsafe_allow_html=True)

st.title("🛵 Paket Taxi")
st.caption("Günlük paket, çalışma süresi, prim ve masraf takibi")
client = supabase_client()
if client:
    st.success("Çevrim içi veri tabanı bağlı. Kayıtlar internet üzerinden saklanıyor.")
else:
    st.warning("Şu an yerel kayıt modu açık. Yayınladıktan sonra verilerin kalıcı olması için Supabase bağlantısı kurmalısın.")

with st.sidebar:
    st.header("Aylık sabit giderler")
    salary = st.number_input("Aylık maaş (TL)", min_value=0.0, value=DEFAULTS["salary"], step=1000.0)
    motor_rent = st.number_input("Motor kirası / ay (TL)", min_value=0.0, value=DEFAULTS["motor_rent"], step=500.0)
    accounting = st.number_input("Muhasebe / ay (TL)", min_value=0.0, value=DEFAULTS["accounting"], step=100.0)
    bonus_threshold = st.number_input("Prim başlangıç paketi", min_value=0, value=DEFAULTS["bonus_threshold"], step=1)
    bonus_rate = st.number_input("Paket başı prim (TL)", min_value=0.0, value=DEFAULTS["bonus_rate"], step=5.0)
    st.caption("Prim hesabı, eşik üzerindeki paketler için yapılır. İş yerinin kuralı farklıysa ayarlardan değiştirebilirsin.")

records = enrich(get_records())
today = date.today().isoformat()
month = date.today().strftime("%Y-%m")
month_df = records[records["work_date"].str.startswith(month)] if not records.empty else records
today_df = records[records["work_date"] == today] if not records.empty else records
today_packages = int(today_df["packages"].sum()) if not today_df.empty else 0
month_packages = int(month_df["packages"].sum()) if not month_df.empty else 0
month_bonus = max(0, month_packages - int(bonus_threshold) * len(month_df)) * float(bonus_rate) if not month_df.empty else 0
month_fuel = float(month_df["fuel_cash"].sum()) if not month_df.empty else 0
month_other = float(month_df["other_expenses"].sum()) if not month_df.empty else 0
days_worked = int((month_df["packages"] > 0).sum()) if not month_df.empty else 0
fixed_total = motor_rent + accounting
estimated_net = salary + month_bonus - fixed_total - month_fuel - month_other

c1, c2, c3, c4 = st.columns(4)
c1.metric("Bugünkü paket", f"{today_packages}")
c2.metric("Bu ay paket", f"{month_packages}")
c3.metric("Bu ay hesaplanan prim", money(month_bonus))
c4.metric("Tahmini aylık net", money(estimated_net), help="Maaş + tahmini prim − motor kirası − muhasebe − kendi cebinden yakıt − diğer masraflar. Vergi ve iş yeri kesintileri dahil olmayabilir.")

st.divider()
tab1, tab2, tab3 = st.tabs(["➕ Günlük kayıt", "📊 Raporlar", "🧾 Kayıt geçmişi"])

with tab1:
    st.subheader("Günlük çalışma kaydı")
    st.caption("Aynı tarihte yeniden kaydedersen o günün kaydı güncellenir.")
    with st.form("daily_form", clear_on_submit=False):
        col1, col2 = st.columns(2)
        with col1:
            work_date = st.date_input("Çalışma tarihi", value=date.today())
            packages = st.number_input("Atılan paket sayısı", min_value=0, max_value=1000, value=0, step=1)
            hours = st.number_input("Çalışılan saat", min_value=0.0, max_value=24.0, value=11.0, step=0.5)
            extra_income = st.number_input("Ek gelir / bahşiş (TL)", min_value=0.0, value=0.0, step=50.0)
        with col2:
            fuel_cash = st.number_input("Cebinden ödediğin yakıt (TL)", min_value=0.0, value=0.0, step=50.0, help="Sadece cebinden ödediğin tutarı yaz. Yakıt kartıyla karşılanan tutarı buraya ekleme.")
            fuel_card = st.number_input("Yakıt kartı kullanımı (TL) — bilgi amaçlı", min_value=0.0, value=0.0, step=50.0, help="Bu tutar raporda ayrıca görünür; net hesabından ikinci kez düşülmez.")
            other_expenses = st.number_input("Diğer masraflar (TL)", min_value=0.0, value=0.0, step=50.0)
            note = st.text_input("Not", placeholder="Örn. yağmurlu gün, ekstra vardiya")
        bonus_preview = max(0, int(packages) - int(bonus_threshold)) * float(bonus_rate)
        st.info(f"Bu günün tahmini paketi: **{int(packages)}** · Tahmini prim: **{money(bonus_preview)}**")
        submitted = st.form_submit_button("💾 Günlük kaydı kaydet", use_container_width=True)
        if submitted:
            try:
                save_record({
                    "work_date": work_date.isoformat(), "packages": packages, "hours": hours,
                    "extra_income": extra_income, "fuel_cash": fuel_cash, "fuel_card": fuel_card,
                    "other_expenses": other_expenses, "note": note.strip()
                })
                st.success("Günlük kayıt kaydedildi.")
                st.rerun()
            except Exception as e:
                st.error("Kayıt yapılamadı. Veri tabanı ayarlarını kontrol et.")
                st.caption(str(e))

with tab2:
    st.subheader("Aylık rapor")
    selected_month = st.selectbox("Ay seç", options=[date.today().strftime("%Y-%m")] + (sorted(records["work_date"].str[:7].dropna().unique().tolist(), reverse=True) if not records.empty else []))
    report = records[records["work_date"].str.startswith(selected_month)] if not records.empty else records
    if report.empty:
        st.info("Bu ay için kayıt bulunmuyor.")
    else:
        total_packages = int(report["packages"].sum())
        total_bonus = sum(max(0, int(p) - int(bonus_threshold)) * float(bonus_rate) for p in report["packages"])
        total_hours = float(report["hours"].sum())
        cash_fuel = float(report["fuel_cash"].sum())
        card_fuel = float(report["fuel_card"].sum())
        other = float(report["other_expenses"].sum())
        days = int((report["packages"] > 0).sum())
        monthly_net = salary + total_bonus + float(report["extra_income"].sum()) - motor_rent - accounting - cash_fuel - other
        a,b,c,d = st.columns(4)
        a.metric("Toplam paket", f"{total_packages}")
        b.metric("Çalışılan gün", f"{days}")
        c.metric("Toplam saat", f"{total_hours:g}")
        d.metric("Tahmini net", money(monthly_net))
        st.write(f"**Maaş:** {money(salary)} · **Prim:** {money(total_bonus)} · **Ek gelir:** {money(report['extra_income'].sum())}")
        st.write(f"**Motor + muhasebe:** {money(motor_rent + accounting)} · **Cebinden yakıt:** {money(cash_fuel)} · **Diğer masraf:** {money(other)}")
        st.write(f"**Yakıt kartı kullanımı (bilgi):** {money(card_fuel)} — netten ayrıca düşülmedi.")
        display = report[["work_date", "packages", "hours", "bonus", "fuel_cash", "fuel_card", "other_expenses", "note"]].copy()
        display.columns = ["Tarih", "Paket", "Saat", "Tahmini prim (TL)", "Cebinden yakıt", "Yakıt kartı (bilgi)", "Diğer masraf", "Not"]
        st.dataframe(display, use_container_width=True, hide_index=True)
        csv = report.to_csv(index=False).encode("utf-8-sig")
        st.download_button("⬇️ Raporu CSV indir", csv, file_name=f"paket_taxi_{selected_month}.csv", mime="text/csv")

with tab3:
    st.subheader("Kayıt geçmişi")
    if records.empty:
        st.info("Henüz kayıt yok. İlk kaydını Günlük kayıt sekmesinden ekleyebilirsin.")
    else:
        show = records[["work_date", "packages", "hours", "bonus", "fuel_cash", "fuel_card", "other_expenses", "note"]].copy()
        show.columns = ["Tarih", "Paket", "Saat", "Tahmini prim", "Cebinden yakıt", "Yakıt kartı", "Diğer masraf", "Not"]
        st.dataframe(show, use_container_width=True, hide_index=True)
        delete_date = st.selectbox("Silmek istediğin gün", options=records["work_date"].tolist())
        if st.button("Seçili günün kaydını sil", type="secondary"):
            try:
                delete_record(delete_date)
                st.success(f"{delete_date} kaydı silindi.")
                st.rerun()
            except Exception as e:
                st.error("Kayıt silinemedi.")
                st.caption(str(e))

st.divider()
st.caption("Not: Bu uygulama kişisel takip içindir; resmi bordro veya vergi hesabı değildir. İş yerinin prim ve kesinti kurallarını bordro/şef ile doğrula.")
