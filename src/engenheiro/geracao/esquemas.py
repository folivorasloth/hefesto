"""Esquemas JSON passados ao Ollama em `format` (structured outputs).

Com o esquema, o modelo é obrigado a devolver cada afirmação separada, com
tipo (fonte/inferência) e a lista de trechos que a sustentam. O texto final
é montado pelo código a partir disso: é assim que garantimos que nenhuma
afirmação "fonte" aparece sem citação.
"""

RESPOSTA = {
    "type": "object",
    "properties": {
        "encontrou": {
            "type": "boolean",
            "description": "true se os trechos respondem a pergunta (mesmo que parcialmente)",
        },
        "afirmacoes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "texto": {"type": "string"},
                    "tipo": {"type": "string", "enum": ["fonte", "inferencia"]},
                    "trechos": {"type": "array", "items": {"type": "string"}},
                    "critica": {"type": "boolean"},
                },
                "required": ["texto", "tipo", "trechos", "critica"],
            },
        },
        "falta": {"type": "string", "description": "o que a pergunta pede e os trechos não trazem"},
        "sugestoes": {
            "type": "array",
            "items": {"type": "string"},
            "description": "onde procurar ou o que medir para descobrir o que falta",
        },
    },
    "required": ["encontrou", "afirmacoes", "falta", "sugestoes"],
}

VERIFICACAO = {
    "type": "object",
    "properties": {
        "avaliacoes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "veredito": {"type": "string", "enum": ["suporta", "parcial", "nao_suporta"]},
                    "justificativa": {"type": "string"},
                },
                "required": ["id", "veredito", "justificativa"],
            },
        }
    },
    "required": ["avaliacoes"],
}

TRADUCAO = {
    "type": "object",
    "properties": {"consulta_en": {"type": "string"}},
    "required": ["consulta_en"],
}
