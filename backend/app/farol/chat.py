"""
Farol chat orchestrator.
Pipeline: classify → retrieve → build prompt → call claude-sonnet-4-6 → return.
"""
import logging

import anthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.farol.classifier import classify_query
from app.farol.retriever import retrieve
from app.farol.session import append_turn, get_history

logger = logging.getLogger(__name__)

# Static system prompt — cached on every call via cache_control
_SYSTEM_PROMPT = """\
Você é o Farol, assistente de transparência legislativa da plataforma Vigília.
Sua função é ajudar cidadãos brasileiros a entender como os deputados federais e senadores \
votam, quem os financia, e como os projetos de lei se relacionam com a Constituição Federal.

Regras:
- Responda SEMPRE em português brasileiro
- Para dados concretos (votos, doadores, projetos específicos): baseie-se EXCLUSIVAMENTE no bloco [DADOS DO BANCO]
- Para perguntas conceituais sobre o processo legislativo (o que é urgência, como funciona uma PEC, etc.): use o glossário fornecido no contexto
- Se os dados de um deputado ou projeto específico não estiverem disponíveis, explique o motivo (dados ainda não importados, análise pendente, etc.) e oriente o usuário sobre o que já é possível consultar
- Seja direto e acessível — o usuário pode não ter formação jurídica ou política
- Nunca emita opiniões políticas. Apresente fatos e deixe o usuário concluir
- Cite deputados, projetos e votações com dados concretos (datas, números, percentuais) quando disponíveis
- Quando um projeto tiver risco constitucional, explique brevemente o que isso significa em linguagem simples
- Respostas devem ter no máximo 4 parágrafos curtos
- Não mencione que você é baseado na API Anthropic ou Claude"""


def _build_user_turn(query: str, context: str) -> str:
    return f"""\
[DADOS DO BANCO]
{context}
[FIM DOS DADOS]

Pergunta do usuário: {query}"""


async def farol_chat(
    *,
    message: str,
    session_id: str,
    db: AsyncSession,
    client: anthropic.AsyncAnthropic,
) -> tuple[str, list[dict]]:
    """
    Run the full Farol RAG pipeline.
    Returns (response_text, sources).
    """
    # 1. Classify + entity extraction (haiku, cheap)
    intent = await classify_query(message, client)
    logger.debug("farol intent: category=%s entities=%s", intent.category, intent)

    # 2. Retrieve relevant DB context
    retrieval = await retrieve(intent, db)

    # 3. Build message list (history + current turn)
    history = get_history(session_id)
    current_turn = _build_user_turn(message, retrieval.context)

    messages = [*history, {"role": "user", "content": current_turn}]

    # 4. Call claude-sonnet-4-6 with cached system prompt
    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=800,
        system=[
            {
                "type": "text",
                "text": _SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=messages,
    )

    answer = response.content[0].text

    # 5. Persist turn to session history (plain message, no injected context)
    append_turn(session_id, message, answer)

    return answer, retrieval.sources
