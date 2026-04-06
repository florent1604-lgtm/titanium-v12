"""assistant/alexa_connector.py — Stub webhook pour future intégration Alexa Skill.

Structure prête pour Amazon Alexa Skills Kit :
  POST /alexa/webhook  — reçoit les requêtes Alexa

Pour activer :
  1. Créer un Alexa Skill dans la console développeur Amazon
  2. Pointer l'endpoint vers https://votre-domaine.com/alexa/webhook
  3. Configurer la vérification de signature (voir commentaire ci-dessous)
  4. Implémenter les handlers d'intent selon vos besoins

Intents implémentés (à compléter) :
  LaunchRequest     → "Titan, ouvre le bot"
  StatusIntent      → "Donne-moi le statut du bot"
  SignalIntent      → "Quel est le signal pour bitcoin ?"
  ReportIntent      → "Génère le rapport"
  AMAZON.HelpIntent → aide contextuelle
  AMAZON.StopIntent → arrêt

Documentation :
  https://developer.amazon.com/en-US/docs/alexa/custom-skills/handle-requests-sent-by-alexa.html
"""
from __future__ import annotations
import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/alexa", tags=["alexa"])

# ── Helpers de réponse Alexa ──────────────────────────────────────────────────

def _alexa_response(
    speech_text: str,
    should_end: bool = False,
    reprompt: Optional[str] = None,
    card_title: str = "Titan",
    card_text: Optional[str] = None,
) -> Dict[str, Any]:
    """Construit une réponse compatible Alexa Skills Kit."""
    resp: Dict[str, Any] = {
        "version": "1.0",
        "response": {
            "outputSpeech": {
                "type": "PlainText",
                "text": speech_text,
            },
            "shouldEndSession": should_end,
        },
    }
    if reprompt:
        resp["response"]["reprompt"] = {
            "outputSpeech": {"type": "PlainText", "text": reprompt}
        }
    if card_text:
        resp["response"]["card"] = {
            "type":    "Simple",
            "title":   card_title,
            "content": card_text or speech_text,
        }
    return resp


def _alexa_error(msg: str) -> Dict[str, Any]:
    return _alexa_response(f"Désolé, une erreur est survenue. {msg}", should_end=True)


# ── Handlers d'intent ─────────────────────────────────────────────────────────

async def _handle_launch(request_body: Dict) -> Dict:
    return _alexa_response(
        "Bonjour, Titan est en ligne. Je surveille les marchés. "
        "Vous pouvez me demander le statut, les signaux ou un rapport.",
        should_end=False,
        reprompt="Que souhaitez-vous savoir ?",
    )


async def _handle_status_intent(request_body: Dict) -> Dict:
    """Résumé rapide du bot."""
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            from assistant.titan_agent import ask_titan
            response = await ask_titan("Donne-moi un résumé rapide du statut du bot en 2 phrases.", session=session)
            return _alexa_response(response, should_end=True, card_text=response)
    except Exception as e:
        return _alexa_error(str(e))


async def _handle_signal_intent(request_body: Dict) -> Dict:
    """Signal pour un symbole spécifique."""
    slots = request_body.get("request", {}).get("intent", {}).get("slots", {})
    symbol_slot = slots.get("Symbol", {}).get("value", "bitcoin").lower()

    symbol_map = {
        "bitcoin": "BTC/USDT", "btc": "BTC/USDT",
        "ethereum": "ETH/USDT", "eth": "ETH/USDT",
        "solana": "SOL/USDT", "sol": "SOL/USDT",
        "gold": "PAXG/USDT", "or": "PAXG/USDT", "paxg": "PAXG/USDT",
    }
    sym = symbol_map.get(symbol_slot, "BTC/USDT")

    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            from assistant.titan_agent import ask_titan
            response = await ask_titan(
                f"Quel est le signal actuel pour {sym} ? Score, direction et raison en 2 phrases.",
                session=session,
            )
            return _alexa_response(response, should_end=True, card_text=response)
    except Exception as e:
        return _alexa_error(str(e))


async def _handle_report_intent(request_body: Dict) -> Dict:
    """Déclenche le rapport et retourne un résumé."""
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            from assistant.daily_report import build_daily_report
            report = await build_daily_report(session)
            # Version courte pour Alexa (max 8000 chars SSML)
            short = ". ".join(report.split(". ")[:4]) + "."
            return _alexa_response(short, should_end=True, card_text=report)
    except Exception as e:
        return _alexa_error(str(e))


async def _handle_help() -> Dict:
    return _alexa_response(
        "Vous pouvez me demander : le statut du bot, le signal pour bitcoin, "
        "ethereum ou solana, ou le rapport quotidien.",
        should_end=False,
        reprompt="Que souhaitez-vous savoir ?",
    )


async def _handle_stop() -> Dict:
    return _alexa_response("Au revoir. Titan continue de surveiller les marchés.", should_end=True)


# ── Dispatcher principal ──────────────────────────────────────────────────────

_INTENT_HANDLERS = {
    "StatusIntent":        _handle_status_intent,
    "SignalIntent":        _handle_signal_intent,
    "ReportIntent":        _handle_report_intent,
    "AMAZON.HelpIntent":   lambda b: _handle_help(),
    "AMAZON.StopIntent":   lambda b: _handle_stop(),
    "AMAZON.CancelIntent": lambda b: _handle_stop(),
}


# ── Route webhook ─────────────────────────────────────────────────────────────

@router.post("/webhook")
async def alexa_webhook(request: Request):
    """Point d'entrée principal des requêtes Alexa Skills Kit.

    TODO: Ajouter la vérification de signature Amazon en production.
    Voir: https://developer.amazon.com/en-US/docs/alexa/custom-skills/host-a-custom-skill-as-a-web-service.html
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Payload JSON invalide")

    request_type = body.get("request", {}).get("type", "")
    logger.info("[ALEXA] Requête: %s", request_type)

    # Launch
    if request_type == "LaunchRequest":
        return JSONResponse(await _handle_launch(body))

    # Intent
    if request_type == "IntentRequest":
        intent_name = body.get("request", {}).get("intent", {}).get("name", "")
        handler     = _INTENT_HANDLERS.get(intent_name)
        if handler:
            return JSONResponse(await handler(body))
        else:
            return JSONResponse(_alexa_response(
                f"Je ne connais pas la commande {intent_name}.",
                should_end=True,
            ))

    # Session ended
    if request_type == "SessionEndedRequest":
        return JSONResponse({"version": "1.0", "response": {}})

    raise HTTPException(400, f"Type de requête inconnu: {request_type}")


@router.get("/status")
async def alexa_status():
    """Vérifie que le connector Alexa est opérationnel."""
    return JSONResponse({
        "status":  "ok",
        "webhook": "/alexa/webhook",
        "note":    "Configurer cet endpoint dans la console Alexa Developer",
        "ts":      datetime.now(timezone.utc).isoformat(),
    })
