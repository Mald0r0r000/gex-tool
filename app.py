import streamlit as st
import requests
import pandas as pd
import altair as alt

# --- CONFIGURATION DE LA PAGE ---
st.set_page_config(
    page_title="GEX Master",
    page_icon="⚡",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# --- STYLING CSS (Dark Mode & Clean Look) ---
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
    div.stButton > button:hover {
        background-color: #0039CB;
    }
    .metric-card {
        background-color: #262730;
        padding: 15px;
        border-radius: 10px;
        border: 1px solid #444;
        text-align: center;
    }
</style>
""", unsafe_allow_html=True)

# --- FONCTIONS ---

def get_deribit_data(currency='BTC'):
    try:
        # 1. Spot Price
        url_spot = f"https://www.deribit.com/api/v2/public/get_index_price?index_name={currency.lower()}_usd"
        spot = requests.get(url_spot).json()['result']['index_price']
        
        # 2. Options Data
        url_book = "https://www.deribit.com/api/v2/public/get_book_summary_by_currency"
        params = {'currency': currency, 'kind': 'option'}
        data = requests.get(url_book, params=params).json()['result']
        
        return spot, data
    except Exception as e:
        st.error(f"Erreur de connexion API: {e}")
        return None, None

def process_gex(spot, data):
    strikes = {}
    
    for entry in data:
        if entry['open_interest'] == 0: continue
        
        instr = entry['instrument_name']
        parts = instr.split('-')
        strike = float(parts[2])
        opt_type = parts[3]
        
        gamma = entry['greeks'].get('gamma', 0) or 0
        oi = entry['open_interest']
        
        # Formule GEX ($ exposure per 1% move)
        # On divise par 10^6 pour avoir des millions (plus lisible sur le chart)
        gex_val = (gamma * oi * (spot ** 2) / 100) / 1_000_000 
        
        if strike not in strikes:
            strikes[strike] = {'total_gex': 0, 'call_gex': 0, 'put_gex': 0}
            
        if opt_type == 'C':
            strikes[strike]['total_gex'] += gex_val
            strikes[strike]['call_gex'] += gex_val
        else:
def process_gex(spot, data):
    strikes = {}
    
    for entry in data:
        # Sécurité 1: Si pas d'Open Interest, on zappe
        if entry.get('open_interest', 0) == 0: continue
        
        # Sécurité 2: Si pas de données 'greeks' (la cause de ton erreur), on zappe
        greeks = entry.get('greeks')
        if not greeks: continue
        
        instr = entry['instrument_name']
        parts = instr.split('-')
        
        # Sécurité 3: Vérifier que le format du nom est bon (ex: BTC-29DEC23-40000-C)
        if len(parts) < 4: continue
            
        try:
            strike = float(parts[2])
            opt_type = parts[3]
            
            # Récupération sécurisée du Gamma
            gamma = greeks.get('gamma', 0) or 0
            oi = entry['open_interest']
            
            # Formule GEX ($ exposure per 1% move) / en Millions
            gex_val = (gamma * oi * (spot ** 2) / 100) / 1_000_000 
            
            if strike not in strikes:
                strikes[strike] = {'total_gex': 0, 'call_gex': 0, 'put_gex': 0}
                
            if opt_type == 'C':
                strikes[strike]['total_gex'] += gex_val
                strikes[strike]['call_gex'] += gex_val
            else:
                strikes[strike]['total_gex'] -= gex_val
                strikes[strike]['put_gex'] -= gex_val
                
        except (ValueError, IndexError):
            continue # Si une donnée est bizarre, on ignore la ligne

    # Si aucune donnée n'a été traitée (cas extrême), on renvoie des valeurs par défaut pour éviter le crash
    if not strikes:
        return pd.DataFrame(), spot, spot, spot

    # Conversion en DataFrame
    df = pd.DataFrame.from_dict(strikes, orient='index')
    df.index.name = 'Strike'
    df = df.sort_index()
    
    # --- FIND LEVELS ---
    # Call Wall = Max Positive GEX
    call_wall = df['total_gex'].idxmax()
    
    # Put Wall = Max Negative GEX
    put_wall = df['total_gex'].idxmin()
    
    # Zero Gamma (Flip)
    subset = df[(df.index > spot * 0.85) & (df.index < spot * 1.15)]
    # Sécurité si le subset est vide
    if not subset.empty:
        zero_gamma = subset['total_gex'].abs().idxmin()
    else:
        zero_gamma = spot # Fallback au prix actuel
    
    return df, call_wall, put_wall, zero_gamma

# --- INTERFACE MAIN ---

st.title("⚡ BTC Gamma Exposure")
st.caption("Données institutionnelles Deribit | Analyseur GEX")

col_control1, col_control2 = st.columns([3, 1])
with col_control1:
    st.info("Clique pour actualiser les données et recalculer les niveaux.")
with col_control2:
    scan_btn = st.button("SCANNER")

if scan_btn:
    with st.spinner("Analyse de la chaîne d'options en cours..."):
        spot_price, raw_data = get_deribit_data('BTC')
        
        if spot_price:
            df, cw, pw, zg = process_gex(spot_price, raw_data)
            
            # 1. AFFICHAGE DES MÉTRIQUES
            st.markdown("---")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Spot Price", f"${spot_price:,.0f}")
            c2.metric("Call Wall (Res)", f"${cw:,.0f}", delta="Résistance", delta_color="normal")
            c3.metric("Put Wall (Sup)", f"${pw:,.0f}", delta="Support", delta_color="inverse")
            c4.metric("Zero Gamma", f"${zg:,.0f}", delta="Pivot")
            
            # 2. GRAPHIQUE INTERACTIF
            st.subheader("Profil de Liquidité (GEX)")
            
            # Filtre pour zoomer autour du prix (+/- 20%)
            df_chart = df[(df.index > spot_price * 0.75) & (df.index < spot_price * 1.25)].reset_index()
            
            # Chart avec Altair
            base = alt.Chart(df_chart).encode(x=alt.X('Strike', axis=alt.Axis(format='$.0f')))
            
            bar_chart = base.mark_bar(opacity=0.7).encode(
                y=alt.Y('total_gex', title='Gamma Exposure ($M)'),
                color=alt.condition(
                    alt.datum.total_gex > 0,
                    alt.value('#00C853'),  # Vert pour positif
                    alt.value('#D50000')   # Rouge pour négatif
                ),
                tooltip=['Strike', alt.Tooltip('total_gex', format=',.2f')]
            )
            
            rule = alt.Chart(pd.DataFrame({'x': [spot_price]})).mark_rule(color='orange', strokeDash=[5, 5]).encode(x='x')
            
            st.altair_chart((bar_chart + rule).interactive(), use_container_width=True)

            # 3. GÉNÉRATION PINE SCRIPT
            st.subheader("Code TradingView")
            pine_code = f"""// --- DATA GENERATED AT ${spot_price:,.0f} ---
float call_wall = {cw}
float put_wall = {pw}
float zero_gamma = {zg}"""
            
            st.text_area("Copier-coller dans l'Input du Script:", value=pine_code, height=100)
            
        else:
            st.error("Impossible de récupérer les données.")

else:
    st.write("En attente du scan...")
