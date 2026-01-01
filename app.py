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
    page_icon="🧠",
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

# --- CALCULATEUR BLACK-SCHOLES ---

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
            return contract_data 

        # 2. Variables
        S = contract_data.get('underlying_price', 0)
        K = strike
        sigma = contract_data.get('mark_iv', 0) / 100.0
        
        if S == 0 or sigma == 0: return contract_data

        now = datetime.now()
        T = (expiry - now).total_seconds() / (365 * 24 * 3600)
        
        # 3. Métadonnées Temporelles (Pour les filtres et pondérations)
        days_to_expiry = (expiry - now).days
        weekday = expiry.weekday() # 0=Lundi, 4=Vendredi
        month = expiry.month
        day = expiry.day
        
        # Logique simplifiée pour détecter les expirations majeures
        # Une Monthly est généralement le dernier vendredi du mois (donc > 21)
        is_monthly = (day > 21 and weekday == 4)
        # Une Quarterly est une Monthly qui tombe en Mars, Juin, Sept, Dec
        is_quarterly = is_monthly and (month in [3, 6, 9, 12])

        if T <= 0: return contract_data

        # 4. Calculs Mathématiques
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
        
        # 5. Injection des résultats
        contract_data['greeks'] = {
            "gamma": round(gamma, 5)
        }
        
        # On stocke les métadonnées pour le processeur
        contract_data['dte_days'] = days_to_expiry 
        contract_data['weekday'] = weekday 
        contract_data['is_quarterly'] = is_quarterly
        contract_data['is_monthly'] = is_monthly
        
        return contract_data
# --- FIN CALCULATEUR ---

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

# --- LOGIQUE PRINCIPALE ---
def process_gex(spot, data, dte_limit, only_fridays, use_weighting, w_quart, w_month, w_week):
    calculator = GreeksCalculator() 
    strikes = {}
    debug_log = [] 
    
    # Drapeaux pour l'alerte de sécurité
    missed_quarterly = False
    missed_monthly = False
    
    for i, entry in enumerate(data):
        contract = calculator.calculate(entry)
        instr = contract.get('instrument_name', 'UNKNOWN')
        
        # Récupération des infos
        dte = contract.get('dte_days', 9999)
        is_quart = contract.get('is_quarterly', False)
        is_month = contract.get('is_monthly', False)
        weekday = contract.get('weekday', -1)
        oi = contract.get('open_interest', 0)
        
        # --- FILTRE 1 : DTE (Avec Check de Sécurité) ---
        if dte > dte_limit:
            # Si on rejette, on vérifie si on est en train de rater une baleine
            if is_quart: missed_quarterly = True
            elif is_month: missed_monthly = True
            continue 
        
        # --- FILTRE 2 : VENDREDIS ---
        if only_fridays and weekday != 4: continue

        # --- FILTRE 3 : Open Interest ---
        if oi == 0: continue
        
        # --- FILTRE 4 : Validité ---
        greeks = contract.get('greeks')
        if not greeks: continue
            
        parts = instr.split('-')
        if len(parts) < 4: continue
            
        try:
            strike = float(parts[2])
            opt_type = parts[3] 
            gamma = greeks.get('gamma', 0) or 0
            
            # --- PONDÉRATION INTELLIGENTE ---
            weight = 1.0 
            if use_weighting:
                if is_quart: weight = w_quart
                elif is_month: weight = w_month
                else: weight = w_week 

            # Calcul du GEX Pondéré
            gex_val = ((gamma * oi * (spot ** 2) / 100) / 1_000_000) * weight
            
            if strike not in strikes: strikes[strike] = {'total_gex': 0}
            
            if opt_type == 'C':
                strikes[strike]['total_gex'] += gex_val
            else:
                strikes[strike]['total_gex'] -= gex_val
                
        except:
            continue

    # Génération des Warnings pour l'utilisateur
    warnings = []
    if missed_quarterly:
        warnings.append("⚠️ ATTENTION : Votre horizon est trop court ! Vous ignorez une expiration TRIMESTRIELLE majeure.")
    elif missed_monthly:
        warnings.append("⚠️ Note : Vous ignorez une expiration Mensuelle à venir.")

    # Fin de traitement
    if not strikes:
        return pd.DataFrame(), spot, spot, spot, debug_log, warnings

    df = pd.DataFrame.from_dict(strikes, orient='index')
    df.index.name = 'Strike'
    df = df.sort_index()
    
    call_wall = df['total_gex'].idxmax()
    put_wall = df['total_gex'].idxmin()
    
    # --- LOGIQUE ZERO GAMMA (Interpolation) ---
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
            numerator = abs(val_neg)
            denominator = abs(val_neg) + val_pos
            if denominator != 0:
                zero_gamma = idx_neg + (idx_pos - idx_neg) * (numerator / denominator)
            else:
                zero_gamma = (idx_neg + idx_pos) / 2
        else:
             zero_gamma = subset['total_gex'].abs().idxmin()
    else:
        if not subset.empty: zero_gamma = subset['total_gex'].abs().idxmin()
        else: zero_gamma = spot

    return df, call_wall, put_wall, zero_gamma, debug_log, warnings

# --- INTERFACE UTILISATEUR ---

st.title("🧠 GEX Master Pro")

# Section Filtres
col_f1, col_f2 = st.columns(2)
with col_f1:
    dte_limit = st.slider("📅 Horizon (Jours)", 1, 365, 60, help="Options expirant dans moins de X jours")
with col_f2:
    only_fridays = st.checkbox("🦅 Focus Vendredis", value=True, help="Ignore le bruit quotidien")

# Section Pondération
st.markdown("### ⚖️ Pondération Institutionnelle")
use_weighting = st.checkbox("⚡ Activer Smart Weighting", value=True, help="Donne plus de poids aux grosses expirations")

w_quart = 3.0
w_month = 2.0
w_week = 1.0

if use_weighting:
    cw1, cw2, cw3 = st.columns(3)
    w_quart = cw1.number_input("👑 Quarterly (x)", 1.0, 10.0, 3.0, 0.5)
    w_month = cw2.number_input("🏆 Monthly (x)", 1.0, 5.0, 2.0, 0.5)
    w_week = cw3.number_input("📅 Weekly (x)", 0.1, 2.0, 1.0, 0.1)

# Bouton de lancement
if st.button("LANCER L'ANALYSE AVANCÉE"):
    spot, raw_data = get_deribit_data('BTC')
    
    if spot and raw_data:
        st.success(f"Données reçues. Analyse en cours...")
        
        # Appel de la fonction principale
        df, cw, pw, zg, logs, warns = process_gex(spot, raw_data, dte_limit, only_fridays, use_weighting, w_quart, w_month, w_week)
        
        # Affichage des alertes de sécurité
        if warns:
            for w in warns:
                st.warning(w)
        
        if not df.empty:
            st.markdown("---")
            st.metric("Prix Actuel", f"${spot:,.0f}")
            
            m1, m2, m3 = st.columns(3)
            m1.metric("🔴 Call Wall (Résistance)", f"${cw:,.0f}")
            m2.metric("🟢 Put Wall (Support)", f"${pw:,.0f}")
            m3.metric("⚖️ Zero Gamma (Pivot)", f"${zg:,.0f}")
            
            # Graphique
            df_chart = df[(df.index > spot * 0.7) & (df.index < spot * 1.3)].reset_index()
            chart = alt.Chart(df_chart).mark_bar().encode(
                x=alt.X('Strike', axis=alt.Axis(format='$,f')),
                y='total_gex',
                color=alt.condition(alt.datum.total_gex > 0, alt.value('#00C853'), alt.value('#D50000')),
                tooltip=['Strike', 'total_gex']
            ).interactive()
            st.altair_chart(chart, use_container_width=True)
            
            # Génération Code Pine Clean
            code = f"""float call_wall = {cw}
float put_wall = {pw}
float zero_gamma = {zg}"""
            
            st.markdown("### 📋 Code pour PineScript")
            st.code(code, language='pine')
        else:
            st.error("Aucune donnée disponible avec ces filtres.")
    else:
        st.error("Erreur de connexion à Deribit.")
