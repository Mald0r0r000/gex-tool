import streamlit as st
import requests
import pandas as pd
import altair as alt
import numpy as np
from scipy.stats import norm
from datetime import datetime

# --- CONFIGURATION DE LA PAGE ---
st.set_page_config(
    page_title="GEX Master Pro",
    page_icon="⏳",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# --- STYLING ---
st.markdown("""
<style>
    .stApp {background-color: #0E1117;}
    div.stButton > button {
        width: 100%;
        background-color: #2962FF;
        color: white;
        border-radius: 8px;
        height: 3em;
        font-weight: bold;
        border: none;
    }
    div.stButton > button:hover {background-color: #0039CB;}
    /* Style pour les metrics personnalisées */
    [data-testid="stMetricValue"] {
        font-size: 1.2rem;
    }
</style>
""", unsafe_allow_html=True)

# --- CALCULATEUR BLACK-SCHOLES ---
class GreeksCalculator:
    def __init__(self, risk_free_rate=0.0):
        self.r = risk_free_rate

    def calculate(self, contract_data):
        try:
            parts = contract_data['instrument_name'].split('-')
            if len(parts) < 4: return contract_data
            
            date_str = parts[1]
            strike = float(parts[2])
            option_type = 'call' if parts[3] == 'C' else 'put'
            expiry = datetime.strptime(date_str, "%d%b%y")
        except:
            return contract_data 

        S = contract_data.get('underlying_price', 0)
        K = strike
        sigma = contract_data.get('mark_iv', 0) / 100.0
        
        if S == 0 or sigma == 0: return contract_data

        now = datetime.now()
        T = (expiry - now).total_seconds() / (365 * 24 * 3600)
        
        # Métadonnées Temporelles
        days_to_expiry = (expiry - now).days
        weekday = expiry.weekday() # 0=Lundi, 4=Vendredi
        month = expiry.month
        day = expiry.day
        
        # Identification des types d'expiration
        is_monthly = (day > 21 and weekday == 4)
        is_quarterly = is_monthly and (month in [3, 6, 9, 12])

        if T <= 0: return contract_data

        # Black-Scholes
        d1 = (np.log(S / K) + (self.r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)

        gamma = norm.pdf(d1) / (S * sigma * np.sqrt(T))
        
        # Injection
        contract_data['greeks'] = {"gamma": round(gamma, 5)}
        contract_data['dte_days'] = days_to_expiry 
        contract_data['weekday'] = weekday 
        contract_data['is_quarterly'] = is_quarterly
        contract_data['is_monthly'] = is_monthly
        contract_data['expiry_date'] = expiry # Stockage de l'objet date pour le tri
        
        return contract_data

# --- API DERIBIT ---
def get_deribit_data(currency='BTC'):
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        url_spot = f"https://www.deribit.com/api/v2/public/get_index_price?index_name={currency.lower()}_usd"
        spot_res = requests.get(url_spot, headers=headers).json()
        spot = spot_res['result']['index_price']
        
        url_book = "https://www.deribit.com/api/v2/public/get_book_summary_by_currency"
        params = {'currency': currency, 'kind': 'option'}
        book_res = requests.get(url_book, params=params, headers=headers).json()
        data = book_res['result']
        return spot, data
    except Exception as e:
        st.error(f"Erreur API: {e}")
        return None, None

# --- ANALYSEUR DE DATES (NOUVEAU) ---
def analyze_upcoming_expirations(data):
    # On scanne rapidement les données brutes pour trouver les dates uniques
    expirations = {}
    now = datetime.now()
    
    for entry in data:
        try:
            parts = entry['instrument_name'].split('-')
            date_str = parts[1]
            expiry = datetime.strptime(date_str, "%d%b%y")
            days_left = (expiry - now).days
            
            if days_left < 0: continue
            
            date_key = expiry.strftime("%d %b %Y")
            
            # Logique Quarterly (simplifiée pour l'affichage rapide)
            weekday = expiry.weekday()
            day = expiry.day
            month = expiry.month
            is_monthly = (day > 21 and weekday == 4)
            is_quart = is_monthly and (month in [3, 6, 9, 12])
            
            if is_quart and days_left not in expirations:
                expirations[days_left] = {"date": date_key, "type": "👑 Quarterly"}
            elif is_monthly and days_left not in expirations:
                expirations[days_left] = {"date": date_key, "type": "🏆 Monthly"}
                
        except:
            continue
            
    # On trie par jours restants
    sorted_days = sorted(expirations.keys())
    return sorted_days, expirations

# --- LOGIQUE PRINCIPALE ---
def process_gex(spot, data, dte_limit, only_fridays, use_weighting, w_quart, w_month, w_week):
    calculator = GreeksCalculator() 
    strikes = {}
    
    # Suivi des expirations manquées (DTE)
    missed_quarterly_dtes = []
    
    for entry in data:
        contract = calculator.calculate(entry)
        instr = contract.get('instrument_name', 'UNKNOWN')
        
        dte = contract.get('dte_days', 9999)
        is_quart = contract.get('is_quarterly', False)
        is_month = contract.get('is_monthly', False)
        weekday = contract.get('weekday', -1)
        oi = contract.get('open_interest', 0)
        greeks = contract.get('greeks')
        
        # --- FILTRE INTELLIGENT ---
        if dte > dte_limit:
            # Si on filtre, on note juste le DTE de la quarterly manquée
            if is_quart: missed_quarterly_dtes.append(dte)
            continue 
        
        if only_fridays and weekday != 4: continue
        if oi == 0: continue
        if not greeks: continue
            
        # Calcul GEX
        try:
            parts = instr.split('-')
            if len(parts) < 4: continue
            strike = float(parts[2])
            opt_type = parts[3] 
            gamma = greeks.get('gamma', 0) or 0
            
            weight = 1.0 
            if use_weighting:
                if is_quart: weight = w_quart
                elif is_month: weight = w_month
                else: weight = w_week 

            gex_val = ((gamma * oi * (spot ** 2) / 100) / 1_000_000) * weight
            
            if strike not in strikes: strikes[strike] = {'total_gex': 0}
            if opt_type == 'C': strikes[strike]['total_gex'] += gex_val
            else: strikes[strike]['total_gex'] -= gex_val
        except: continue

    # ALERTE INTELLIGENTE :
    # On ne crie que si la Quarterly manquée la plus PROCHE est ignorée
    warnings = []
    if missed_quarterly_dtes:
        next_missed_q = min(missed_quarterly_dtes)
        # Si la prochaine quarterly manquée est "proche" (ex: moins de 100j au dela du filtre)
        # Cela évite de crier pour une quarterly dans 300 jours
        if next_missed_q < (dte_limit + 90):
             warnings.append(f"⚠️ ATTENTION : Vous coupez la prochaine Trimestrielle (dans {next_missed_q} jours). Augmentez l'horizon !")

    if not strikes:
        return pd.DataFrame(), spot, spot, spot, warnings

    df = pd.DataFrame.from_dict(strikes, orient='index')
    df.index.name = 'Strike'
    df = df.sort_index()
    
    call_wall = df['total_gex'].idxmax()
    put_wall = df['total_gex'].idxmin()
    
    # Zero Gamma Logic
    subset = df[(df.index > spot * 0.85) & (df.index < spot * 1.15)]
    neg_gex = subset[subset['total_gex'] < 0]
    pos_gex = subset[subset['total_gex'] > 0]
    zero_gamma = spot 
    
    if not neg_gex.empty and not pos_gex.empty:
        idx_neg = neg_gex.index.max()
        val_neg = neg_gex.loc[idx_neg, 'total_gex']
        candidates_pos = pos_gex[pos_gex.index > idx_neg]
        if not candidates_pos.empty:
            idx_pos = candidates_pos.index.min()
            val_pos = candidates_pos.loc[idx_pos, 'total_gex']
            ratio = abs(val_neg) / (abs(val_neg) + val_pos)
            zero_gamma = idx_neg + (idx_pos - idx_neg) * ratio
        else: zero_gamma = subset['total_gex'].abs().idxmin()
    else:
        if not subset.empty: zero_gamma = subset['total_gex'].abs().idxmin()
        else: zero_gamma = spot

    return df, call_wall, put_wall, zero_gamma, warnings

# --- INTERFACE ---

st.title("⏳ GEX Time Master")

# On charge les données D'ABORD pour afficher le calendrier
if 'raw_data' not in st.session_state:
    with st.spinner("Connexion à Deribit..."):
        s, d = get_deribit_data('BTC')
        st.session_state['spot'] = s
        st.session_state['raw_data'] = d

if st.session_state.get('raw_data'):
    spot = st.session_state['spot']
    data = st.session_state['raw_data']
    
    # --- DASHBOARD DES PROCHAINES EXPIRATIONS ---
    st.markdown("### 📅 Calendrier des Baleines")
    sorted_days, exp_details = analyze_upcoming_expirations(data)
    
    # On affiche les 3 prochaines majeures
    cols = st.columns(3)
    for i in range(min(3, len(sorted_days))):
        days = sorted_days[i]
        info = exp_details[days]
        cols[i].metric(label=info['type'], value=f"{days} Jours", delta=info['date'], delta_color="off")
    
    st.divider()

    # --- REGLAGES ---
    c1, c2 = st.columns(2)
    # Le slider s'adapte maintenant à l'info qu'on a vue au dessus
    with c1:
        dte_limit = st.slider("Horizon d'Analyse (Jours)", 1, 365, 65)
    with c2:
        only_fridays = st.checkbox("Focus Vendredis", value=True)
        use_weighting = st.checkbox("Smart Weighting", value=True)

    # --- LANCEMENT ---
    if st.button("CALCULER LE GEX"):
        df, cw, pw, zg, warns = process_gex(spot, data, dte_limit, only_fridays, use_weighting, 3.0, 2.0, 1.0)
        
        # Affichage Warnings intelligents
        if warns:
            for w in warns:
                st.warning(w)

        if not df.empty:
            st.markdown(f"### Spot: **${spot:,.0f}**")
            
            m1, m2, m3 = st.columns(3)
            m1.metric("🔴 Call Wall", f"${cw:,.0f}")
            m2.metric("🟢 Put Wall", f"${pw:,.0f}")
            m3.metric("⚖️ Zero Gamma", f"${zg:,.0f}")
            
            # Graphique
            df_chart = df[(df.index > spot * 0.7) & (df.index < spot * 1.3)].reset_index()
            chart = alt.Chart(df_chart).mark_bar().encode(
                x=alt.X('Strike', axis=alt.Axis(format='$,f')),
                y='total_gex',
                color=alt.condition(alt.datum.total_gex > 0, alt.value('#00C853'), alt.value('#D50000')),
                tooltip=['Strike', 'total_gex']
            ).interactive()
            st.altair_chart(chart, use_container_width=True)
            
            # Code Pine
            st.code(f"""float call_wall = {cw}\nfloat put_wall = {pw}\nfloat zero_gamma = {zg}""", language='pine')
        else:
            st.error("Aucune donnée.")

else:
    if st.button("Réessayer la connexion"):
        st.session_state.clear()
        st.rerun()
