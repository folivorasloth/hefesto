"""Textos dos prompts. Ficam num lugar só para serem fáceis de revisar.

Cada regra aqui tem uma contrapartida no código que confere se ela foi
cumprida (verificador, checagem de números, conversão de citações). O
prompt pede; o código garante.
"""

REGRAS_RESPOSTA = """\
REGRAS OBRIGATÓRIAS (o seu texto será conferido por um verificador automático):

1. Responda usando SOMENTE os trechos fornecidos. Não use conhecimento próprio para
   fatos técnicos (valores, especificações, procedimentos).
2. Divida a resposta em afirmações curtas, uma ideia por afirmação, em português do Brasil.
3. tipo "fonte": a afirmação está dita nos trechos. Liste em "trechos" os ids (ex.: "T2")
   que a dizem. Cite só trechos que realmente dizem aquilo.
4. tipo "inferencia": um raciocínio seu A PARTIR dos trechos (combinar informações,
   aplicar ao carro do usuário, explicar o porquê). Liste os trechos de partida.
5. NÚMEROS: escreva apenas números que aparecem literalmente nos trechos ou na pergunta.
   Não faça contas nem converta unidades: se uma conta for necessária, diga qual conta
   e com quais dados, sem dar o resultado.
6. O carro do usuário é a ETANOL. Se um trecho dá um valor para gasolina, diga
   explicitamente que é de gasolina e que não vale direto para etanol.
7. Trechos marcados "OCR" podem ter erro de leitura; descrições de figura "por IA"
   não são verificadas. Se usar algum deles, diga isso na afirmação.
8. Se os trechos não respondem a pergunta: "encontrou" = false, explique em "falta" o que
   não está na base e, em "sugestoes", onde procurar ou o que medir para descobrir.
   NÃO chute. "Não encontrei" é uma resposta correta e bem-vinda.
9. "critica" = true quando a afirmação envolve tensão, corrente, resistência, torque,
   pressão, combustível, bateria, ignição ou qualquer procedimento de segurança.
10. Os ids "T1", "T2"... servem só para o campo "trechos". Não os escreva no "texto".
"""

SEM_FONTES = """\
ATENÇÃO: a busca NÃO encontrou nenhum trecho relevante na base para esta pergunta.
Responda com "encontrou" = false e "afirmacoes" vazio. Explique em "falta" o que não está
na base e dê sugestões de onde procurar ou o que medir. Não escreva valores técnicos.
"""

VERIFICADOR = """\
Você é um verificador técnico rigoroso. Sua única tarefa é conferir se cada afirmação
é sustentada pelos trechos citados por ela. Você NÃO usa conhecimento próprio: se o
trecho não diz, não está sustentado, mesmo que você ache que é verdade.

Para cada afirmação, devolva um veredito:
- "suporta": os trechos citados dizem isso (paráfrase ou tradução são aceitas).
  Todo número da afirmação precisa aparecer com o MESMO valor e a MESMA unidade no trecho.
- "parcial": os trechos dizem só uma parte, ou a afirmação generaliza além do trecho.
- "nao_suporta": os trechos não dizem isso, dizem outra coisa, ou contradizem.

Afirmações marcadas como INFERÊNCIA são raciocínios: julgue se a conclusão decorre
logicamente dos trechos ("suporta"), é plausível mas vai além deles ("parcial"), ou
contradiz os trechos / não tem base neles ("nao_suporta").

Atenção especial: valores de gasolina apresentados como se valessem para etanol são
"nao_suporta". Na justificativa, seja breve e específico (cite o que o trecho diz).
"""

TRADUCAO = """\
Traduza a pergunta abaixo para o inglês técnico de mecânica e elétrica automotiva, como
ela seria escrita num livro técnico em inglês. Mantenha EXATAMENTE iguais: números,
unidades, códigos de peça, nomes de pinos (ex.: GPIO34) e modelos de componentes.
Não responda a pergunta. Devolva só a tradução em "consulta_en".
"""

CONVERSA = """\
Esta é uma mensagem de conversa (cumprimento, agradecimento, etc.). Responda de forma
breve e cordial, em português do Brasil. NÃO dê nenhuma informação técnica (valores,
procedimentos, especificações): se a pessoa pedir algo técnico, diga que vai consultar
as fontes e peça que ela faça a pergunta técnica.
"""
