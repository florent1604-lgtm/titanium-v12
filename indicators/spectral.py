r"""
spectral.py — Titanium V12 / Module d'analyse spectrale (cycles de prix)
=======================================================================

North Star 2D -> 3D -> 4D :
    - dominant_cycle  : periode du cycle dominant (barres)            [3D]
    - cycle_power     : force du cycle [0..1] -> filtre de regime     [3D]
    - phase_deg       : phase instantanee (0..360)                    [4D]

Base : DSP publique (Wiener-Khinchin, Butterworth, signal analytique).
Implementation clean-room, a valider en walk-forward avant tout signal reel.

Deux APIs complementaires :
    - compute_spectral_features(close) -> SpectralFeatures (scipy)
      Consommee par core/signal_engine.py (Phase 1 : spectral_state -> scoring).
    - analyze(close_series) -> dict (numpy pur, 100% causal, style Ehlers)
      Consommee par l'instrumentation dashboard (ctx["spectral"]).

/!\ CAUSALITE
    filtfilt() et hilbert() (via FFT) utilisent des donnees FUTURES.
    -> OK pour backtest / recherche / dashboard.
    -> INTERDIT en live tel quel. Pour le live : version causale (lfilter)
      ou filtres recursifs causaux style Ehlers (cf. analyze() plus bas).

Dependances : numpy, scipy (scipy requis pour compute_spectral_features
uniquement — analyze() est en numpy pur).
"""

from __future__ import annotations
import math
from dataclasses import dataclass, asdict
from typing import Dict, Optional

import numpy as np

try:
    from scipy.signal import butter, filtfilt, lfilter, hilbert
    _SCIPY_OK = True
except ImportError:
    _SCIPY_OK = False


# ------------------------------------------------------------------------- #
# 1. Roofing filter (prétraitement obligatoire)
# ------------------------------------------------------------------------- #
def roofing_filter(
    price: np.ndarray,
    low_period: int = 10,
    high_period: int = 48,
    fs: float = 1.0,
    causal: bool = False,
) -> np.ndarray:
    """Passe-bande : retire la derive lente (>high_period) et le bruit (<low_period).

    On n'analyse JAMAIS le prix brut -> toujours le prix roofe.
    causal=False -> filtfilt (zero-phase, NON causal, recherche only)
    causal=True  -> lfilter  (causal, dephasage, utilisable en live)
    """
    price = np.asarray(price, dtype=float)
    nyq = 0.5 * fs
    low = (1.0 / high_period) / nyq     # coupe les basses freq (trend / DC)
    high = (1.0 / low_period) / nyq     # coupe les hautes freq (bruit)
    b, a = butter(2, [low, high], btype="band")
    if causal:
        return lfilter(b, a, price)
    return filtfilt(b, a, price)


# ------------------------------------------------------------------------- #
# 2. Cycle dominant — Autocorrelation Periodogram (Ehlers / Wiener-Khinchin)
# ------------------------------------------------------------------------- #
def autocorr_periodogram(
    x: np.ndarray,
    pmin: int = 8,
    pmax: int = 50,
):
    """Cycle dominant via projection de l'autocorrelation sur une base de Fourier.

    Wiener-Khinchin : PSD = TF de l'autocorrelation.
    Renvoie : (dominant_period, cycle_power[0..1], periods, power_spectrum)

    cycle_power faible  => pas de cycle exploitable (trend / range).
    cycle_power eleve   => cycle net.
    """
    x = np.asarray(x, dtype=float)
    x = x - x.mean()
    n = len(x)
    if n < pmax * 2:
        raise ValueError(f"Serie trop courte : n={n}, requis >= {pmax * 2}")

    ac = np.correlate(x, x, mode="full")[n - 1:]
    ac = ac / (ac[0] + 1e-12)                          # autocorr normalisee [-1, 1]

    periods = np.arange(pmin, pmax + 1)
    power = np.zeros_like(periods, dtype=float)
    max_lag = min(pmax * 3, len(ac) - 1)
    lags = np.arange(1, max_lag)

    for i, p in enumerate(periods):
        w = 2.0 * np.pi / p
        re = np.sum(ac[lags] * np.cos(w * lags))
        im = np.sum(ac[lags] * np.sin(w * lags))
        power[i] = re * re + im * im

    power = power / (power.max() + 1e-12)
    dominant = int(periods[power.argmax()])
    cycle_power = float(power.max() / (power.mean() + 1e-12))   # rapport pic/moyenne
    cycle_power = float(np.clip(cycle_power / 10.0, 0.0, 1.0))  # normalise ~[0,1]
    return dominant, cycle_power, periods, power


# ------------------------------------------------------------------------- #
# 3. Phase instantanee (brique 4D)
# ------------------------------------------------------------------------- #
def instantaneous_phase(x: np.ndarray) -> np.ndarray:
    r"""Phase instantanee (0..360) via signal analytique (Hilbert).

    /!\ NON causal (FFT) + effets de bord -> recherche / backtest only.
    Live -> Hilbert bar-par-bar (In-phase / Quadrature) a implementer. [TODO]
    """
    analytic = hilbert(np.asarray(x, dtype=float))
    return np.degrees(np.angle(analytic)) % 360.0


def phase_zone(phase_deg: float) -> str:
    r"""Classe la phase en zone. /!\ Le mapping exact (quelle phase = creux)
    DOIT etre calibre sur les donnees reelles (BTC/ETH/SOL) avant usage signal."""
    p = phase_deg % 360.0
    if p < 90:
        return "montee"
    elif p < 180:
        return "sommet"
    elif p < 270:
        return "descente"
    return "creux"


# ------------------------------------------------------------------------- #
# 4. API publique — features pretes pour le scoring /11
# ------------------------------------------------------------------------- #
@dataclass
class SpectralFeatures:
    dominant_cycle: int      # barres
    cycle_power: float       # 0..1  -> filtre de regime
    phase_deg: float         # 0..360
    phase_zone: str          # creux / montee / sommet / descente
    has_cycle: bool          # cycle_power > seuil

    def to_dict(self) -> dict:
        return asdict(self)


def compute_spectral_features(
    close: np.ndarray,
    low_period: int = 10,
    high_period: int = 48,
    pmin: int = 8,
    pmax: int = 50,
    power_threshold: float = 0.30,
    causal: bool = False,
) -> SpectralFeatures:
    """Pipeline complet : close -> features spectrales.

    Integration Titanium :
        - has_cycle == False -> regime trend/range : depondere les criteres cycle,
          laisse SMC piloter.
        - has_cycle == True  -> phase_zone exploitable pour le timing d'entree.
    """
    if not _SCIPY_OK:
        raise ImportError("scipy requis pour compute_spectral_features")
    roofed = roofing_filter(close, low_period, high_period, causal=causal)
    dominant, power, _, _ = autocorr_periodogram(roofed, pmin, pmax)
    phase = float(instantaneous_phase(roofed)[-1])
    return SpectralFeatures(
        dominant_cycle=dominant,
        cycle_power=power,
        phase_deg=phase,
        phase_zone=phase_zone(phase),
        has_cycle=power > power_threshold,
    )


# ------------------------------------------------------------------------- #
# 5. API causale — analyze() (numpy pur, style Ehlers, utilisable en live)
#    Consommee par l'instrumentation dashboard (ctx["spectral"]).
# ------------------------------------------------------------------------- #

def _roofing_causal(close: np.ndarray, hp_period: int = 48, ss_period: int = 10) -> np.ndarray:
    """Passe-bande causal : highpass 2 poles + SuperSmoother d'Ehlers.

    Isole les composantes cycliques entre ss_period et hp_period barres,
    supprime la tendance (basse frequence) et le bruit (haute frequence).
    IIR -> strictement causal, utilisable bar-par-bar en live.
    """
    n = len(close)
    if n < 5:
        return np.zeros(n)

    # Highpass 2 poles
    a = math.sqrt(0.5) * 2 * math.pi / hp_period
    alpha1 = (math.cos(a) + math.sin(a) - 1) / math.cos(a)
    hp = np.zeros(n)
    c1 = (1 - alpha1 / 2) ** 2
    for i in range(2, n):
        hp[i] = (c1 * (close[i] - 2 * close[i - 1] + close[i - 2])
                 + 2 * (1 - alpha1) * hp[i - 1]
                 - (1 - alpha1) ** 2 * hp[i - 2])

    # SuperSmoother 2 poles
    a2 = math.sqrt(2.0) * math.pi / ss_period
    b1 = 2 * math.exp(-a2 / math.sqrt(2.0)) * math.cos(a2)
    c3 = -math.exp(-2 * a2 / math.sqrt(2.0))
    c2 = b1
    c1s = 1 - c2 - c3
    out = np.zeros(n)
    for i in range(2, n):
        out[i] = c1s * (hp[i] + hp[i - 1]) / 2 + c2 * out[i - 1] + c3 * out[i - 2]
    return out


def _dft_power(sig: np.ndarray, period: int) -> float:
    """Puissance du signal a une periode donnee (DFT a frequence unique)."""
    n = len(sig)
    w = 2 * math.pi / period
    idx = np.arange(n)
    re = float(np.dot(sig, np.cos(w * idx)))
    im = float(np.dot(sig, np.sin(w * idx)))
    return re * re + im * im


def analyze(close_series) -> Optional[Dict[str, object]]:
    """Analyse spectrale causale complete sur les dernieres barres.

    Fenetre = 3*pmax barres (assez pour resoudre le cycle le plus lent
    sans trainer des regimes morts). Retourne None si donnees insuffisantes.
    """
    from utils.config import SPECTRAL_PMIN, SPECTRAL_PMAX, SPECTRAL_POWER_THRESHOLD

    if close_series is None or len(close_series) < SPECTRAL_PMAX * 2:
        return None

    window = int(SPECTRAL_PMAX * 3)
    close = close_series.values.astype(float)[-window:]
    filt = _roofing_causal(close, hp_period=SPECTRAL_PMAX, ss_period=max(SPECTRAL_PMIN, 8))

    # Warm-up du filtre IIR : on jette le premier tiers
    sig = filt[len(filt) // 3:]
    if len(sig) < SPECTRAL_PMAX:
        return None
    sig = sig - sig.mean()
    if float(np.abs(sig).max()) < 1e-12:
        return None

    # Periodogramme : puissance par periode candidate
    periods = range(SPECTRAL_PMIN, SPECTRAL_PMAX + 1)
    powers = {p: _dft_power(sig, p) for p in periods}
    total = sum(powers.values()) or 1e-12
    dom_p, dom_pow = max(powers.items(), key=lambda kv: kv[1])
    # Puissance relative : part du cycle dominant et de ses voisins immediats
    neighborhood = sum(powers.get(p, 0.0) for p in (dom_p - 1, dom_p, dom_p + 1))
    cycle_power = round(neighborhood / total, 3)
    has_cycle = cycle_power >= SPECTRAL_POWER_THRESHOLD

    # Phase instantanee : correlation des dernieres `dom_p` barres avec
    # sin/cos a la periode dominante (causal — fenetre passee uniquement)
    tail = sig[-dom_p:]
    idx = np.arange(dom_p)
    w = 2 * math.pi / dom_p
    re = float(np.dot(tail, np.cos(w * idx)))
    im = float(np.dot(tail, np.sin(w * idx)))
    phase = (math.degrees(math.atan2(im, re)) + 360.0) % 360.0

    if phase < 90:
        zone = "creux"        # bas de cycle — zone d'achat potentielle
    elif phase < 180:
        zone = "montee"
    elif phase < 270:
        zone = "sommet"       # haut de cycle — zone de vente potentielle
    else:
        zone = "descente"

    return {
        "dominant_cycle": int(dom_p) if has_cycle else 0,
        "cycle_power":    cycle_power,
        "has_cycle":      has_cycle,
        "phase_deg":      round(phase, 1),
        "phase_zone":     zone if has_cycle else "aucun",
    }


if __name__ == "__main__":
    # Test rapide sur un signal synthetique (cycle 20 barres + bruit + trend)
    t = np.arange(600)
    synth = (
        np.sin(2 * np.pi * t / 20)          # cycle dominant = 20
        + 0.3 * np.sin(2 * np.pi * t / 7)   # bruit HF
        + 0.002 * t                          # trend lent
        + 0.2 * np.random.randn(len(t))
    )
    feats = compute_spectral_features(synth)
    print("Attendu dominant_cycle ~= 20")
    print(feats.to_dict())
