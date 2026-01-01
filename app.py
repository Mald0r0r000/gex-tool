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
    # --- CORRECTION 1 : Initialiser le calculateur ici ---
    calculator = GreeksCalculator() 
    
    strikes = {}
    debug_log = [] 
    
    # On itère sur 'entry' (l'entrée brute de l'API)
    for i, entry in enumerate(data):
        is_debug_sample = i < 5

        # --- CORRECTION 2 : Passer 'entry' au calculateur ---
        # On transforme la donnée brute 'entry' en donnée enrichie 'contract'
        contract = calculator.calculate(entry)
        
        # Ensuite on utilise 'contract' (qui contient maintenant les greeks)
        instr = contract.get('instrument_name', 'UNKNOWN')
        
        # Check 1: Open Interest
        oi = contract.get('open_interest', 0)
        if oi == 0:
            if is_debug_sample: debug_log.append(f"{instr}: Rejeté (OI=0)")
            continue
        
        # Check 2: Greeks (Maintenant ça va passer !)
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
            opt_type = parts[3] # 'C' ou 'P' (attention Deribit met 'C' ou 'P' dans le nom, mais verifiez votre parsing)
            
            # Note: Dans le nom c'est souvent "C" ou "P", mais vérifions
            # Le parser a déjà extrait le type en 'call'/'put' dans l'objet, 
            # mais ici vous re-parsez le nom manuellement. Gardons votre logique :
            type_char = parts[3] 

            gamma = greeks.get('gamma', 0) or 0
            
            # GEX Calc
            gex_val = (gamma * oi * (spot ** 2) / 100) / 1_000_000 
            
            if strike not in strikes:
                strikes[strike] = {'total_gex': 0}
            
            if type_char == 'C':
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
    
    subset = df[(df.index > spot * 0.85) & (df.index < spot * 1.15)]
    # Petit fix de sécurité si subset vide
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
        
        # AFFICHER LA DONNÉE BRUTE (C'est ça qui nous intéresse)
        with st.expander("🔍 VOIR LA DONNÉE BRUTE (Premier contrat)"):
            st.json(raw_data[0])
            
        df, cw, pw, zg, logs = process_gex(spot, raw_data)
        
        with st.expander("⚠️ LOGS DE FILTRAGE"):
            st.write(logs)
            
        if not df.empty:
            st.metric("Spot", f"${spot:,.0f}")
            st.metric("Call Wall", f"${cw:,.0f}")
            st.metric("Put Wall", f"${pw:,.0f}")
            
            # Chart
            df_chart = df[(df.index > spot * 0.8) & (df.index < spot * 1.2)].reset_index()
            chart = alt.Chart(df_chart).mark_bar().encode(
                x='Strike',
                y='total_gex',
                color=alt.condition(alt.datum.total_gex > 0, alt.value('green'), alt.value('red'))
            )
            st.altair_chart(chart, use_container_width=True)
            
            # Code
            code = f"""float call_wall = {cw}\nfloat put_wall = {pw}\nfloat zero_gamma = {zg}"""
            st.code(code)
        else:
            st.error("Aucune donnée après filtrage.")
    else:
        st.error("Impossible de joindre Deribit.")
