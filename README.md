# gex-tool

Le prix du Bitcoin ne bouge pas au hasard. Il est massivement influencé par le marché des Options (Deribit), où les Market Makers doivent constamment couvrir leurs positions (Hedging).

Cet indicateur GEX (Gamma Exposure) vous permet de visualiser ces niveaux de liquidité cachés directement sur votre graphique TradingView. Il ne s'agit pas d'analyse technique classique, mais d'une analyse structurelle des flux financiers.

Ce que l'indicateur affiche :

Call Wall (Résistance Majeure) : Le niveau où les Market Makers sont massivement exposés à la vente. C'est souvent un plafond de verre difficile à percer du premier coup car la volatilité y est "écrasée".

Put Wall (Support Majeur) : Le niveau de protection ultime. À l'approche de ce prix, les Market Makers doivent acheter pour se couvrir, créant un "coussin" de rebond naturel.

Zero Gamma (Le "Flip") : Le niveau le plus important.

        Au-dessus : Zone de Gamma Positif. Le marché est stable, les corrections sont achetées. (Tendance haussière lente).

        En dessous : Zone de Gamma Négatif. La volatilité explose. Les baisses entraînent des ventes paniques. (Zone de danger).

La Technologie : Les données proviennent de Deribit (le plus gros exchange d'options crypto). Un algorithme Python (Black-Scholes) calcule l'exposition nette sur chaque strike pour déterminer ces niveaux avec précision.

🔗 Lien du Scanner (Données Brutes) : https://gex-tool-maldor0r.streamlit.app/


⚙️ La Routine de Mise à Jour (Méthode)

Cet indicateur fonctionne comme une "Carte Météo" : elle est valide tant que le paysage ne change pas radicalement. Voici comment garder vos niveaux à jour.
📅 1. La Mise à Jour Quotidienne (Le "Coffee Routine")

À faire chaque matin (idéalement après la clôture journalière de 02h00 UTC ou à votre réveil).

    Ouvrez l'outil de scan : https://gex-tool-maldor0r.streamlit.app/

    Cliquez sur le bouton "LANCER LE SCAN AVEC DEBUG".

    Attendez que les calculs (Black-Scholes) se terminent et que le graphique apparaisse.

    Tout en bas de la page, repérez le bloc de code gris. Copiez les 3 lignes :
    Pine Script

    float call_wall = 100000.0
    float put_wall = 85000.0
    float zero_gamma = 87833.5

    Allez sur TradingView > Ouvrez l'éditeur Pine (en bas) > Collez ces nouvelles valeurs dans la section "ZONE DE COLLAGE" de votre script > Sauvegardez (Ctrl+S).

🚨 2. Mise à Jour en cas de Mouvement Majeur

Le marché des options est vivant. Si le Bitcoin fait un mouvement violent (> 3% à 5%) en quelques heures, les positions des Market Makers changent.

    Pourquoi mettre à jour ? Si le prix traverse le "Zero Gamma", la dynamique change. Si le prix casse un "Wall", un nouveau Wall se forme ailleurs.

    Le signal : Si vous voyez le prix s'éloigner fortement de vos niveaux actuels ou traverser une zone rouge/verte, relancez un scan rapide pour obtenir la nouvelle "structure" du marché.

Disclaimer : Cet outil fournit une analyse de données de marché et ne constitue pas un conseil en investissement. Le trading d'options et de cryptomonnaies comporte des risques.


CODE PINESCRIPT

// This Pine Script® code is subject to the terms of the Mozilla Public License 2.0 at https://mozilla.org/MPL/2.0/
// © Mald0r0r

//Pour mettre à jour quotidiennement le script rendez-vous sur https://gex-tool-maldor0r.streamlit.app/
//En cas de gros mouvement de prix du BTC pensez à mettre à jour les valeurs Float dans la zone de collage

//@version=5
indicator("BTC GEX Overlay", overlay=true)

// --- ZONE DE COLLAGE ---
// C'est ici que tu colleras le code généré par ton site Streamlit
float call_wall = 100000.0
float put_wall = 85000.0
float zero_gamma = 87258.615
// -----------------------

// --- DESSIN DES LIGNES (Uniquement sur la dernière bougie) ---
var line l_cw = na
var line l_pw = na
var line l_zg = na
var label lb_cw = na
var label lb_pw = na
var label lb_zg = na

if barstate.islast
    line.delete(l_cw)
    line.delete(l_pw)
    line.delete(l_zg)
    label.delete(lb_cw)
    label.delete(lb_pw)
    label.delete(lb_zg)

    // CALL WALL (Résistance)
    l_cw := line.new(bar_index - 10, call_wall, bar_index + 10, call_wall, color=color.new(#9757df, 20), width=2)
    lb_cw := label.new(bar_index + 20, call_wall, "Call Wall\n" + str.tostring(call_wall), color=color.new(#9757df, 20), textcolor=color.new(#9757df, 20), style=label.style_none, size = size.tiny)
    
    // PUT WALL (Support)
    l_pw := line.new(bar_index - 10, put_wall, bar_index + 10, put_wall, color=color.new(#5bc4c2, 20), width=2)
    lb_pw := label.new(bar_index + 20, put_wall, "Put Wall\n" + str.tostring(put_wall), color=color.new(#5bc4c2, 20), textcolor=color.new(#5bc4c2, 20), style=label.style_none, size = size.tiny)

    // ZERO GAMMA (Pivot)
    l_zg := line.new(bar_index - 10, zero_gamma, bar_index + 10, zero_gamma, color=color.new(#dde0e3, 20), style=line.style_dashed)
    lb_zg := label.new(bar_index + 20, zero_gamma, "Zero Gamma\n" + str.tostring(zero_gamma), color=color.new(#dde0e3, 20), textcolor=color.new(#dde0e3, 20), style=label.style_none, size = size.tiny)

// --- COULEUR DE FOND (Scope Global) ---
// Si prix > zero gamma = Vert (Bullish/Stable)
// Si prix < zero gamma = Rouge (Volatile/Bearish)
bg_color = close > zero_gamma ? color.new(color.green, 95) : color.new(color.red, 95)
bgcolor(bg_color)
