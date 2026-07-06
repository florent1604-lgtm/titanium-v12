# Titanium V12 — Analyse spectrale & cycles de prix
### North Star : 2D → 3D → 4D (épicycles / Fourier appliqués au signal de prix)

> **Statut : objectif sans condition.** On reste terre à terre dans l'exécution (incrémental,
> local, paper trading d'abord), mais cette perspective est la direction de fond de Titanium V12.
> Origine : visualisation Fourier (épicycles reconstruisant une onde carrée) — `physanim`, juin 2026.

---

## 1. L'idée en une phrase

Un **épicycle = un phaseur rotatif** (amplitude, fréquence, phase). Empiler des épicycles pour
reconstruire une onde, c'est exactement une **décomposition de Fourier**. Transposé au trading :
**décomposer une série de prix en cycles dominants**, mesurer lequel domine *maintenant*, et où
on se situe *dans* ce cycle (la phase). La phase est l'info la plus exploitable pour le timing.

---

## 2. La progression dimensionnelle (mappée à des livrables concrets)

| Dim | Représentation | Ce qu'on voit | Livrable Titanium |
|-----|----------------|---------------|-------------------|
| **2D** | Prix × temps | Le chart classique + SMC | État actuel de Titanium |
| **3D** | Temps × fréquence × amplitude | Quels cycles existent et comment ils naissent/meurent | **Périodogramme glissant** (cycle dominant + carte spectrale) |
| **4D** | + Phase instantanée *(ou)* + multi-actifs | Où on est dans le cycle (creux/montée/sommet) ; ou surface BTC/ETH/SOL × fréquence × temps | **Phase instantanée** comme déclencheur de timing ; puis surface de corrélation spectrale |

Le saut clé n'est pas le nombre de dimensions pour faire joli — c'est : **2D dit "le prix est ici",
3D dit "un cycle de N barres domine", 4D dit "et on est à 20° avant le creux".**

---

## 3. Méthodes — comparatif honnête

### ❌ FFT brute sur les prix — à éviter
La FFT suppose un signal **stationnaire et périodique**. Le prix ne l'est pas. Conséquences :
fuite spectrale, cycles fantômes, et le **spectral dilation** d'Ehlers (les swings longs ont une
amplitude plus grande, ce qui biaise le spectre vers les basses fréquences). C'est le piège n°1.

### ✅ Prétraitement obligatoire : Roofing Filter (Ehlers)
Passe-bande qui retire la dérive lente (composante "trend"/DC, ex. > 48 barres) **et** le bruit
haute fréquence (< 10 barres). On n'analyse jamais le prix brut — toujours le prix « roofé ».
Implémentable proprement avec un Butterworth bande-passante (scipy) ou les filtres récursifs
d'Ehlers (Super Smoother).

### ✅ Hilbert Transform + Homodyne Discriminator (Ehlers, S&C 2000–2001)
Le prix est traité comme une onde : on construit sa représentation **phaseur** (composantes
In-phase `I` et Quadrature `Q`). De là on tire **la période du cycle dominant** (homodyne
discriminator : on multiplie le signal par son conjugué à 1 barre, le taux de changement de phase
donne la période) **et la phase instantanée** (`arctan(Q/I)`). C'est exactement notre brique 4D.
Avantage : causal, bar-par-bar, temps réel. La période est typiquement bornée (~6 à 50 barres).

### ✅✅ Autocorrelation Periodogram (Ehlers, *Cycle Analytics for Traders* 2013 / S&C 2016) — méthode favorite
Théorème de **Wiener-Khinchin** : densité spectrale de puissance = transformée de Fourier de
l'**autocorrélation**. Donc : autocorréler le prix roofé, projeter sur une base de Fourier, lire le
pic. Avantages revendiqués sur la Hilbert : réponse rapide (estimation en ~½ cycle), **mesure de la
puissance relative du cycle** (donc on sait quand il n'y a *pas* de cycle = trend/range → précieux
comme filtre de régime), autocorrélation bornée [-1, +1] (insensible à l'amplitude), pas besoin de
compenser le spectral dilation. **C'est probablement le meilleur point d'entrée pour V12.**

### ⚙️ Ondelettes (wavelets) — pour plus tard
La vraie réponse mathématique à la non-stationnarité (résolution temps-fréquence adaptative).
Plus lourd, plus dur à régler. À garder en réserve pour la phase 3D avancée, pas un point de départ.

---

## 4. Pièges à garder en tête (terre à terre)

1. **Non-stationnarité** — les marchés ne sont pas des sinusoïdes stables. Les cycles persistent
   « un moment » puis disparaissent. Un cycle mesuré n'est exploitable que tant qu'il est présent.
2. **Spectral dilation** — biais basse-fréquence si on ne roofe pas / normalise pas.
3. **Aliasing** — bornes min/max de période obligatoires.
4. **Filtres non-causaux** — `scipy.signal.filtfilt` et `hilbert` (via FFT) utilisent des données
   futures et ont des effets de bord. **Parfaits pour le backtest/visu, interdits en live** sans
   version causale. En production : filtres récursifs causaux (style Ehlers) ou `lfilter`.
5. **Cycles fantômes / p-hacking** — toujours valider en **walk-forward** (70/30, comme V11), sinon
   on ajuste à du bruit.

---

## 5. Plan d'implémentation incrémental pour V12

Ordre pragmatique, chaque étape autonome et testable, **sans casser l'existant** :

- **Phase 0 — module `spectral.py` isolé.** Roofing filter + cycle dominant via autocorrelation
  periodogram. Sortie : `dominant_cycle` (en barres) + `cycle_power` (0–1). Validé hors-ligne sur
  historique BTC/ETH/SOL avant tout branchement.
- **Phase 1 — phase instantanée (Hilbert).** Sortie : `phase` (0–360°) + zone (creux/montée/sommet).
  C'est la brique « 4D » de timing.
- **Phase 2 — périodogramme glissant (3D).** Carte temps×fréquence pour le dashboard iPhone (visu
  + détection visuelle des transitions de régime).
- **Phase 3 — 4D multi-actifs.** Surface BTC/ETH/SOL × fréquence × temps ; corrélations de cycles.

### Intégration au scoring /11
Deux usages, non exclusifs :
- **Filtre de régime** (le plus sûr) : si `cycle_power` est faible → marché en trend/range → on
  pondère différemment les critères SMC (les outils de cycle ne servent à rien sans cycle).
- **Critère(s) additionnel(s)** : un point « phase favorable » (ex. acheter près d'un creux de cycle
  confirmé par SMC) — extension du /11 vers /12+ uniquement après validation walk-forward.

### Stack (rester léger, local)
`numpy`, `scipy.signal` (`butter`, `filtfilt`/`lfilter`, `hilbert`, `periodogram`, `spectrogram`).
Pas de dépendance lourde. Cohérent avec la contrainte : **Titanium reste local.**

---

## 6. Garde-fous (cohérence projet)

- Local-first : aucun flux de prix brut vers le cloud (déjà la règle JARVIS/Oracle).
- Paper trading + stop-loss obligatoires avant tout signal réel issu du spectral.
- Walk-forward 70/30 systématique sur tout nouveau critère.
- Causalité vérifiée avant passage live (pas de `filtfilt`/`hilbert` FFT en production).

---

## 7. Annexe — squelette Python (clean-room, à valider)

> Implémentation minimale et originale, basée sur la DSP publique (Wiener-Khinchin, Butterworth,
> signal analytique). **Backtest/recherche uniquement** — `filtfilt` et `hilbert` ne sont pas causaux.

```python
import numpy as np
from scipy.signal import butter, filtfilt, hilbert

def roofing_filter(price, low_period=10, high_period=48, fs=1.0):
    """Passe-bande : retire trend lent (>high_period) et bruit (<low_period)."""
    nyq = 0.5 * fs
    low  = (1.0 / high_period) / nyq   # coupe les basses fréquences (trend)
    high = (1.0 / low_period)  / nyq   # coupe les hautes fréquences (bruit)
    b, a = butter(2, [low, high], btype="band")
    return filtfilt(b, a, price)       # non-causal -> recherche only

def autocorr_periodogram(x, pmin=8, pmax=50):
    """Cycle dominant via autocorrelation periodogram (Wiener-Khinchin)."""
    x = x - x.mean()
    n = len(x)
    # autocorrelation normalisee
    ac = np.correlate(x, x, mode="full")[n-1:]
    ac = ac / ac[0]
    periods = np.arange(pmin, pmax + 1)
    power = np.zeros_like(periods, dtype=float)
    lags = np.arange(1, min(pmax * 3, len(ac)))
    for i, p in enumerate(periods):
        w = 2 * np.pi / p
        re = np.sum(ac[lags] * np.cos(w * lags))
        im = np.sum(ac[lags] * np.sin(w * lags))
        power[i] = re**2 + im**2
    power /= power.max() + 1e-12
    dominant = int(periods[power.argmax()])
    cycle_power = float(power.max())      # ~force du cycle ; faible => pas de cycle
    return dominant, cycle_power, periods, power

def instantaneous_phase(x):
    """Phase instantanee (0..360) via signal analytique. Non-causal -> recherche only."""
    analytic = hilbert(x)
    phase = np.degrees(np.angle(analytic)) % 360.0
    return phase

# Pipeline type :
#   roofed = roofing_filter(close)
#   period, power, _, _ = autocorr_periodogram(roofed)
#   phase = instantaneous_phase(roofed)
#   -> features : dominant_cycle=period, cycle_power=power, phase=phase[-1]
```

---

## 8. Références

- John Ehlers — *Rocket Science for Traders* (Hilbert transform, dominant cycle)
- John Ehlers — *Cycle Analytics for Traders* (2013) — autocorrelation periodogram, roofing filter
- John Ehlers — « Measuring Market Cycles », *Technical Analysis of Stocks & Commodities*, sept. 2016
- Théorème de Wiener-Khinchin (PSD = TF de l'autocorrélation)
- Robot Wealth — *Using Digital Signal Processing in Quantitative Trading* (non-stationnarité, spectre)
- `scipy.signal` (Hilbert, periodogram, spectrogram, Butterworth)
