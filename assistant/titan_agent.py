"""assistant/titan_agent.py — Agent LLM Titan avec routage intelligent.

Pipeline de traitement d'une requête :
  1. IntentClassifier (sklearn) → intent + confidence
  2. Plugin dispatch → réponse directe si intent connu et confiance haute
  3. Knowledge base → contexte additionnel injecté dans le LLM
  4. LLM (ollama Python client > aiohttp fallback) → réponse enrichie

Avantages :
  - Réponses instantanées (< 100ms) pour les requêtes trading courantes
  - Moins d'appels LLM → latence globale divisée par 3-5
  - Contexte enrichi pour les requêtes complexes → moins d'hallucinations
  - Client ollama Python utilisé si installé (API plus robuste)

Dépendances :
  pip install aiohttp          (déjà présent)
  pip install ollama           (client Python officiel — optionnel)
  pip install scikit-learn     (classificateur — optionnel)
"""
from __future__ import annotations
import asyncio
import logging
from typing import Any, Dict, List, Optional

import aiohttp

from assistant.config import (
    TITAN_LLM_MODEL, TITAN_LLM_URL, TITAN_LLM_TIMEOUT,
    TITAN_LLM_MAX_TOKENS, TITAN_SCORE_CONTEXT, TITAN_SYSTEM_PROMPT,
    TITAN_API_BASE,
)

logger = logging.getLogger(__name__)

# Historique de conversation (mémoire courte — 8 échanges)
_MAX_HISTORY  = 8
_conversation: List[Dict[str, str]] = []

# ── Détection du client Ollama Python ────────────────────────────────────────

def _has_ollama_client() -> bool:
    try:
        import ollama  # noqa
        return True
    except ImportError:
        return False


# ── Collecte contexte trading ─────────────────────────────────────────────────

async def _get_trading_context(session: aiohttp.ClientSession) -> str:
    """Récupère un résumé du contexte trading depuis l'API locale."""
    if not TITAN_SCORE_CONTEXT:
        return ""

    ctx: List[str] = []
    _to = aiohttp.ClientTimeout(total=3)

    try:
        async with session.get(f"{TITAN_API_BASE}/api/state", timeout=_to) as r:
            if r.status == 200:
                _format_state(await r.json(), ctx)
    except Exception as e:
        logger.debug("[AGENT] Contexte API: %s", e)

    try:
        async with session.get(f"{TITAN_API_BASE}/paper/stats", timeout=_to) as r:
            if r.status == 200:
                _format_stats(await r.json(), ctx)
    except Exception:
        pass

    return "\n\n[CONTEXTE TEMPS RÉEL]\n" + "\n".join(ctx) if ctx else ""


def _format_state(data: Dict[str, Any], parts: List[str]) -> None:
    signals = data.get("signals", {})
    active  = [
        (sym, s) for sym, s in signals.items()
        if s.get("active") and s.get("side") not in ("NEUTRE", None, "")
    ]
    if active:
        parts.append("Signaux actifs :")
        for sym, s in active:
            parts.append(
                f"  {sym} {s.get('side')} score={s.get('score',0)}/11 "
                f"prix={s.get('price',0):.4f}$ régime={s.get('regime','?')}"
            )
    else:
        parts.append("Aucun signal actif en ce moment.")

    paper = data.get("paper", {})
    if paper:
        parts.append(
            f"Compte paper: equity={paper.get('equity',0):.2f}$ "
            f"PnL={paper.get('total_pnl',0):+.2f}$"
        )
    parts.append(f"Mode trading: {data.get('trading_mode', '?')}")


def _format_stats(stats: Dict[str, Any], parts: List[str]) -> None:
    n   = stats.get("total_trades", 0)
    wr  = stats.get("winrate_pct", 0)
    sh  = stats.get("sharpe", 0)
    dd  = stats.get("max_drawdown_pct", 0)
    pnl = stats.get("total_pnl", 0)
    if n > 0:
        parts.append(
            f"Stats paper ({n} trades): winrate={wr:.1f}% "
            f"sharpe={sh:.2f} drawdown={dd:.1f}% PnL={pnl:+.2f}$"
        )


# ── Appel LLM via client ollama Python ────────────────────────────────────────

async def _call_ollama_client(messages: List[Dict[str, str]]) -> str:
    """Appelle Ollama via le client Python officiel — streaming pour éviter le timeout."""
    import ollama

    client = ollama.AsyncClient(host=TITAN_LLM_URL)
    chunks: List[str] = []

    # Streaming : on reçoit des tokens au fur et à mesure — pas de timeout global
    stream = await client.chat(
        model=TITAN_LLM_MODEL,
        messages=messages,
        stream=True,
        options={
            "num_predict": TITAN_LLM_MAX_TOKENS,
            "temperature": 0.7,
            "top_p":       0.9,
        },
    )
    async for chunk in stream:
        content = chunk.get("message", {}).get("content", "")
        if content:
            chunks.append(content)

    return "".join(chunks).strip()


async def ask_titan_stream(
    user_message: str,
    session: Optional[aiohttp.ClientSession] = None,
    on_sentence: Optional[Any] = None,
) -> str:
    """Version streaming de ask_titan — appelle on_sentence(phrase) pour chaque phrase.

    Permet de commencer à parler dès que la première phrase est prête,
    sans attendre la fin de la génération LLM complète.

    Args:
        user_message: Texte de l'utilisateur.
        session:      Session aiohttp (créée si None).
        on_sentence:  Coroutine appelée avec chaque phrase dès qu'elle est complète.

    Returns:
        Réponse complète concaténée.
    """
    global _conversation

    # Essayer plugin d'abord
    try:
        from assistant.intent_classifier import classify
        from assistant.plugins import dispatch as plugin_dispatch
        intent, confidence = classify(user_message)
        plugin_resp = await plugin_dispatch(user_message, intent, confidence)
        if plugin_resp:
            _store_exchange(user_message, plugin_resp)
            if on_sentence:
                await on_sentence(plugin_resp)
            return plugin_resp
    except Exception:
        pass

    if not _has_ollama_client():
        # Fallback non-streaming
        result = await ask_titan(user_message, session=session)
        if on_sentence:
            await on_sentence(result)
        return result

    _own_session = session is None
    if _own_session:
        session = aiohttp.ClientSession()

    try:
        import ollama as _ollama
        from assistant.knowledge import get_context_for_intent
        from assistant.intent_classifier import classify

        intent, _ = classify(user_message)
        trading_ctx  = await _get_trading_context(session)
        knowledge_ctx = get_context_for_intent(intent)
        memory_ctx = ""
        try:
            from assistant.memory_store import get_context_summary
            memory_ctx = get_context_summary()
            if memory_ctx:
                memory_ctx = "\n\n[Mémoire utilisateur]\n" + memory_ctx
        except Exception:
            pass
        system_msg = TITAN_SYSTEM_PROMPT + trading_ctx + knowledge_ctx + memory_ctx

        messages = [{"role": "system", "content": system_msg}]
        messages.extend(_conversation[-_MAX_HISTORY * 2:])
        messages.append({"role": "user", "content": user_message})

        client = _ollama.AsyncClient(host=TITAN_LLM_URL)
        stream = await client.chat(
            model=TITAN_LLM_MODEL,
            messages=messages,
            stream=True,
            options={"num_predict": TITAN_LLM_MAX_TOKENS, "temperature": 0.7},
        )

        buffer       = ""
        full_answer  = ""
        _SENTENCE_END = ".!?:;"

        async for chunk in stream:
            token = chunk.get("message", {}).get("content", "")
            if not token:
                continue
            buffer     += token
            full_answer += token

            # Découper en phrases dès qu'un séparateur est trouvé
            while any(c in buffer for c in _SENTENCE_END):
                for sep in _SENTENCE_END:
                    idx = buffer.find(sep)
                    if idx != -1:
                        phrase = buffer[:idx + 1].strip()
                        buffer = buffer[idx + 1:].lstrip()
                        if phrase and on_sentence:
                            await on_sentence(phrase)
                        break

        # Dernier fragment (sans ponctuation finale)
        if buffer.strip() and on_sentence:
            await on_sentence(buffer.strip())

        full_answer = full_answer.strip()
        _store_exchange(user_message, full_answer)
        return full_answer

    except Exception as e:
        logger.error("[AGENT] Stream erreur: %s", e)
        fallback = "Désolé, une erreur est survenue."
        if on_sentence:
            await on_sentence(fallback)
        return fallback
    finally:
        if _own_session:
            await session.close()


# ── Appel LLM via aiohttp (fallback) ─────────────────────────────────────────

async def _call_ollama_http(
    session: aiohttp.ClientSession,
    messages: List[Dict[str, str]],
) -> str:
    """Appelle Ollama via l'API REST directement."""
    payload = {
        "model":   TITAN_LLM_MODEL,
        "messages": messages,
        "stream":   False,
        "options": {
            "num_predict": TITAN_LLM_MAX_TOKENS,
            "temperature": 0.7,
            "top_p":       0.9,
        },
    }
    async with session.post(
        f"{TITAN_LLM_URL}/api/chat",
        json=payload,
        timeout=aiohttp.ClientTimeout(total=TITAN_LLM_TIMEOUT),
    ) as resp:
        if resp.status != 200:
            body = await resp.text()
            logger.error("[AGENT] Ollama %d: %s", resp.status, body[:200])
            return "Désolé, je ne peux pas accéder au modèle LLM en ce moment."
        result  = await resp.json()
        content = result.get("message", {}).get("content", "").strip()
        return content or "Je n'ai pas pu générer de réponse."


# ── Interface publique ─────────────────────────────────────────────────────────

async def ask_titan(
    user_message: str,
    session:       Optional[aiohttp.ClientSession] = None,
    extra_context: str = "",
    use_plugins:   bool = True,
) -> str:
    """Traite une requête utilisateur via le pipeline complet.

    Pipeline :
      1. Classification d'intention (sklearn)
      2. Plugin dispatch (réponse directe si haute confiance)
      3. Enrichissement contexte (trading + knowledge base)
      4. LLM (ollama client ou aiohttp)

    Args:
        user_message:  Texte de l'utilisateur.
        session:       Session aiohttp (créée en interne si None).
        extra_context: Contexte additionnel optionnel.
        use_plugins:   Activer le dispatch plugin (défaut True).

    Returns:
        Réponse textuelle de Titan.
    """
    global _conversation

    # ── 1. Classification d'intention ────────────────────────────────────────
    intent     = "general"
    confidence = 0.0
    try:
        from assistant.intent_classifier import classify
        intent, confidence = classify(user_message)
        logger.info("[AGENT] Intent: %s (%.2f) — '%s'", intent, confidence, user_message[:60])
    except Exception as e:
        logger.debug("[AGENT] Classify: %s", e)

    # ── 2. Plugin dispatch ────────────────────────────────────────────────────
    if use_plugins:
        try:
            from assistant.plugins import dispatch as plugin_dispatch
            plugin_resp = await plugin_dispatch(user_message, intent, confidence)
            if plugin_resp:
                # Mémoriser l'échange même pour les réponses plugin
                _store_exchange(user_message, plugin_resp)
                return plugin_resp
        except Exception as e:
            logger.debug("[AGENT] Plugin dispatch: %s", e)

    # ── 3. Contexte trading + knowledge base ──────────────────────────────────
    _own_session = session is None
    if _own_session:
        session = aiohttp.ClientSession()

    try:
        trading_ctx = await _get_trading_context(session)

        knowledge_ctx = ""
        try:
            from assistant.knowledge import get_context_for_intent
            knowledge_ctx = get_context_for_intent(intent)
        except Exception:
            pass

        memory_ctx = ""
        try:
            from assistant.memory_store import get_context_summary
            memory_ctx = get_context_summary()
            if memory_ctx:
                memory_ctx = "\n\n[Mémoire utilisateur]\n" + memory_ctx
        except Exception:
            pass
        system_msg = TITAN_SYSTEM_PROMPT + trading_ctx + knowledge_ctx + memory_ctx
        if extra_context:
            system_msg += "\n\n" + extra_context

        messages = [{"role": "system", "content": system_msg}]
        messages.extend(_conversation[-_MAX_HISTORY * 2:])
        messages.append({"role": "user", "content": user_message})

        # ── 4. Appel LLM ─────────────────────────────────────────────────────
        answer = ""
        if _has_ollama_client():
            try:
                answer = await _call_ollama_client(messages)
                logger.debug("[AGENT] Réponse via ollama client")
            except Exception as e:
                logger.warning("[AGENT] ollama client erreur, fallback aiohttp: %s", e)

        if not answer:
            answer = await _call_ollama_http(session, messages)
            logger.debug("[AGENT] Réponse via aiohttp")

        if not answer:
            return "Je n'ai pas pu générer de réponse."

        _store_exchange(user_message, answer)
        logger.info("[AGENT] Réponse (%d chars): %.80s…", len(answer), answer)
        return answer

    except asyncio.TimeoutError:
        return "Le modèle LLM a mis trop de temps à répondre."
    except Exception as e:
        logger.error("[AGENT] Erreur: %s", e)
        return f"Erreur lors de la génération : {e}"
    finally:
        if _own_session:
            await session.close()


def _store_exchange(user_msg: str, assistant_msg: str) -> None:
    """Mémorise un échange dans l'historique conversationnel."""
    global _conversation
    _conversation.append({"role": "user",      "content": user_msg})
    _conversation.append({"role": "assistant", "content": assistant_msg})
    if len(_conversation) > _MAX_HISTORY * 2:
        _conversation = _conversation[-_MAX_HISTORY * 2:]


def clear_history() -> None:
    """Efface l'historique de conversation."""
    global _conversation
    _conversation.clear()
    logger.info("[AGENT] Historique effacé")


def get_history() -> List[Dict[str, str]]:
    """Retourne une copie de l'historique de conversation."""
    return list(_conversation)
