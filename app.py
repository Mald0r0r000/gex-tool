import streamlit as st
import requests
import pandas as pd
import altair as alt
import numpy as np
from scipy.stats import norm
from datetime import datetime

# --- CONFIGURATION DE LA PAGE ---
st.set_page_config(
    page_title="GEX Master Debug",
    page_icon="🛠️",
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
</style>
""", unsafe_allow_html=True)

# --- FONCTIONS ---

class GreeksCalculator:
    def __init__(self, risk_free_rate=0.0):
        self.r = risk_free_rate

    def calculate(self, contract_data):
        # 1. Parsing du nom (ex: BTC-27MAR26-80000-C)
        try:
            parts = contract_data['instrument_name'].split('-')
            if len(parts) < 4: return contract_data
            
            date_str = parts[1]
            strike = float(parts[2])
            option_type = 'call' if parts[3] == 'C' else 'put'
            expiry = datetime.strptime(date_str, "%d%b%y")
        except:
            return contract_data # On ignore si format bizarre

        # 2. Variables Black-Scholes
        S = contract_data.get('underlying_price', 0)
        K = strike
        sigma = contract_data.get('mark_iv', 0) / 100.0
        
        if S == 0 or sigma == 0: return contract_data

        now = datetime.now()
        T = (expiry - now).total_seconds() / (365 * 24 * 3600)
        
        if T <= 0: return contract_data

        # 3. Calculs Mathématiques
        d1 = (np.log(S / K) + (self.r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)

        if option_type == 'call':
            delta = norm.cdf(d1)
            theta_part = - (S * norm.pdf(d1) * sigma) / (2 * np.sqrt(T))
            theta = theta_part - self.r * K * np.exp(-self.r * T) * norm.cdf(d2)
        else:
            delta = norm.cdf(d1) - 1
            theta_part = - (S * norm.pdf(d1) * sigma) / (2 * np.sqrt(T))
            theta = theta_part + self.r * K * np.exp(-self.r * T) * norm.cdf(-d2)

        gamma = norm.pdf(d1) / (S * sigma * np.sqrt(T))
        
        # 4. Insertion des résultats
        contract_data['greeks'] = {
            "delta": round(delta, 5),
            "gamma": round(gamma, 5),
            "theta": round(theta / 365, 5) # Theta par jour
        }
        contract_data['delta'] = round(delta, 5) # Copie pour compatibilité
        
        return contract_data
# --- FIN DU BLOC CALCULATEUR ---

def get_deribit_data(currency='BTC'):
    # On ajoute un User-Agent pour éviter de se faire bloquer par Deribit
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        # 1. Spot Price
        url_spot = f"https://www.deribit.com/api/v2/public/get_index_price?index_name={currency.lower()}_usd"
        spot_res = requests.get(url_spot, headers=headers).json()
        spot = spot_res['result']['index_price']
        
        # 2. Options Data
        url_book = "https://www.deribit.com/api/v2/public/get_book_summary_by_currency"
        params = {'currency': currency, 'kind': 'option'}
        book_res = requests.get(url_book, params=params, headers=headers).json()
        data = book_res['result']
        
        return spot, data
    except Exception as e:
        st.error(f"Erreur technique API: {e}")
        return None, None

def process_gex(spot, data):
    # Initialiser le calculateur ici
    calculator = GreeksCalculator() 
    
    strikes = {}
    debug_log = [] 
    
    # On itère sur 'entry' (l'entrée brute de l'API)
    for i, entry in enumerate(data):
        is_debug_sample = i < 5

        # On transforme la donnée brute 'entry' en donnée enrichie 'contract'
        contract = calculator.calculate(entry)
        
        # Ensuite on utilise 'contract' (qui contient maintenant les greeks)
        instr = contract.get('instrument_name', 'UNKNOWN')
        
        # Check 1: Open Interest
        oi = contract.get('open_interest', 0)
        if oi == 0:
            if is_debug_sample: debug_log.append(f"{instr}: Rejeté (OI=0)")
            continue
        
        # Check 2: Greeks
        greeks = contract.get('greeks')
        if not greeks:
            if is_debug_sample: debug_log.append(f"{instr}: Rejeté (Pas de Greeks)")
            continue
            
        # Check 3: Format Nom
        parts = instr.split('-')
        if len(parts) < 4: 
            continue
            
        try:
            strike = float(parts[2])
            opt_type = parts[3] # 'C' ou 'P'
            
            gamma = greeks.get('gamma', 0) or 0
            
            # GEX Calc
            gex_val = (gamma * oi * (spot ** 2) / 100) / 1_000_000 
            
            if strike not in strikes:
                strikes[strike] = {'total_gex': 0}
            
            if opt_type == 'C':
                strikes[strike]['total_gex'] += gex_val
            else:
                strikes[strike]['total_gex'] -= gex_val
                
        except Exception as e:
            if is_debug_sample: debug_log.append(f"{instr}: Erreur Calcul ({e})")
            continue

    # Conversion DataFrame
    if not strikes:
        return pd.DataFrame(), spot, spot, spot, debug_log

    df = pd.DataFrame.from_dict(strikes, orient='index')
    df.index.name = 'Strike'
    df = df.sort_index()
    
    # Levels logic
    call_wall = df['total_gex'].idxmax()
    put_wall = df['total_gex'].idxmin()
    
    # --- LOGIQUE INTELLIGENTE POUR LE ZERO GAMMA (INTERPOLATION) ---
    subset = df[(df.index > spot * 0.85) & (df.index < spot * 1.15)]
    neg_gex = subset[subset['total_gex'] < 0]
    pos_gex = subset[subset['total_gex'] > 0]
    
    zero_gamma = spot # Valeur par défaut
    
    # On cherche le vrai point de bascule entre le rouge et le vert
    if not neg_gex.empty and not pos_gex.empty:
        idx_neg = neg_gex.index.max()
        val_neg = neg_gex.loc[idx_neg, 'total_gex']
        
        candidates_pos = pos_gex[pos_gex.index > idx_neg]
        if not candidates_pos.empty:
            idx_pos = candidates_pos.index.min()
            val_pos = candidates_pos.loc[idx_pos, 'total_gex']
            
            # Interpolation
            numerator = abs(val_neg)
            denominator = abs(val_neg) + val_pos
            if denominator != 0:
                ratio = numerator / denominator
                zero_gamma = idx_neg + (idx_pos - idx_neg) * ratio
            else:
                zero_gamma = (idx_neg + idx_pos) / 2
        else:
             zero_gamma = subset['total_gex'].abs().idxmin()
    else:
        # Fallback si pas de transition nette
        if not subset.empty:
            zero_gamma = subset['total_gex'].abs().idxmin()
        else:
            zero_gamma = spot

    return df, call_wall, put_wall, zero_gamma, debug_log

# --- INTERFACE ---

st.title("🛠️ GEX Debugger")

if st.button("LANCER LE SCAN AVEC DEBUG"):
    spot, raw_data = get_deribit_data('BTC')
    
    if spot and raw_data:
        st.success(f"Connexion réussie ! {len(raw_data)} contrats récupérés.")
        
        # AFFICHER LA DONNÉE BRUTE
        with st.expander("🔍 VOIR LA DONNÉE BRUTE (Premier contrat)"):
            st.json(raw_data[0])
            
        df, cw, pw, zg, logs = process_gex(spot, raw_data)
        
        with st.expander("⚠️ LOGS DE FILTRAGE"):
            st.write(logs)
            
        if not df.empty:
            st.metric("Spot", f"${spot:,.0f}")
            col1, col2, col3 = st.columns(3)
            col1.metric("Call Wall", f"${cw:,.0f}")
            col2.metric("Put Wall", f"${pw:,.0f}")
            col3.metric("Zero Gamma (Flip)", f"${zg:,.0f}")
            
            # Chart
            df_chart = df[(df.index > spot * 0.8) & (df.index < spot * 1.2)].reset_index()
            chart = alt.Chart(df_chart).mark_bar().encode(
                x='Strike',
                y='total_gex',
                color=alt.condition(alt.datum.total_gex > 0, alt.value('green'), alt.value('red')),
                tooltip=['Strike', 'total_gex']
            ).interactive()
            st.altair_chart(chart, use_container_width=True)
            
            # --- MODIFICATION ICI : Code propre sans point-virgule ---
            code = f"""float call_wall = {cw}
float put_wall = {pw}
float zero_gamma = {zg}"""
            st.code(code, language='pine')
        else:
            st.error("Aucune donnée après filtrage.")
    else:
        st.error("Impossible de joindre Deribit.")
