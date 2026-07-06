r"""
spectral.py — Titanium V12 / Module d'analyse spectrale (cycles de prix)
=======================================================================

North Star 2D -> 3D -> 4D :
    - dominant_cycle  : periode du cycle dominant (barres)            [3D]
    - cycle_power     : force du cycle [0..1] -> filtre de regime     [3D]
    - phase_deg       : phase instantanee (0..360)                    [4D]

Base : DSP publique (Wiener-Khinchin, Butterworth, signal analytique).
Implementation clean-room, a valider en walk-forward avant tout signal reel.

/!\ CAUSALITE
    filtfilt() et hilbert() (via FFT) utilisent des donnees FUTURES.
    -> OK pour backtest / recherche / dashboard.
    -> INTERDIT en live tel quel. Pour le live : version causale (lfilter)
       ou filtres recursifs causaux style Ehlers. Toggle `causal=True` fourni
       pour le roofing ; la phase live exige une Hilbert bar-par-bar (TODO).

Dependances : numpy, scipy
"""

from __future__ import annotations
from dataclasses import dataclass, asdict
import numpy as np
from scipy.signal import butter, filtfilt, lfilter, hilbert


# --------------------------------------------------------------------------- #
# 1. Roofing filter (prétraitement obligatoire)
# --------------------------------------------------------------------------- #
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
    low = (1.0 / high_period) / nyq    # coupe les basses freq (trend / DC)
    high = (1.0 / low_period) / nyq    # coupe les hautes freq (bruit)
    b, a = butter(2, [low, high], btype="band")
    if causal:
        return lfilter(b, a, price)
    return filtfilt(b, a, price)


# --------------------------------------------------------------------------- #
# 2. Cycle dominant — Autocorrelation Periodogram (Ehlers / Wiener-Khinchin)
# --------------------------------------------------------------------------- #
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
    ac = ac / (ac[0] + 1e-12)                         # autocorr normalisee [-1, 1]

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


# --------------------------------------------------------------------------- #
# 3. Phase instantanee (brique 4D)
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# 4. API publique — features pretes pour le scoring /11
# --------------------------------------------------------------------------- #
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


if __name__ == "__main__":
    # Test rapide sur un signal synthetique (cycle 20 barres + bruit + trend)
    t = np.arange(600)
    synth = (
        np.sin(2 * np.pi * t / 20)        # cycle dominant = 20
        + 0.3 * np.sin(2 * np.pi * t / 7)  # bruit HF
        + 0.002 * t                        # trend lent
        + 0.2 * np.random.randn(len(t))
    )
    feats = compute_spectral_features(synth)
    print("Attendu dominant_cycle ~= 20")
    print(feats.to_dict())
