"""Monitor de lançamentos de veículos — Lucinei Automóveis.

Varre o estoque paginado de BuscadorVeiculo.aspx, compara os códigos dos
veículos com o estado salvo em estado/veiculos.json e envia notificação
push via ntfy.sh para cada veículo novo.
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://lucineiautomoveis.com.br"
LISTING_URL = f"{BASE_URL}/BuscadorVeiculo.aspx"
STATE_FILE = Path(__file__).resolve().parent / "estado" / "veiculos.json"
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
MAX_PAGES = 100          # trava de segurança contra loop infinito de paginação
RESUMO_THRESHOLD = 10    # acima disso, manda 1 resumo em vez de push individual

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )
}

RE_ID = re.compile(r"Veiculo\.aspx\?id=(\d+)")
RE_MARCA = re.compile(r"Marca:\s*(.+)")
RE_ANO = re.compile(r"Ano:\s*(.+?)\s*$", re.MULTILINE)


def fetch(url, params=None, tentativas=3):
    """GET com retry e backoff exponencial."""
    for i in range(tentativas):
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException:
            if i == tentativas - 1:
                raise
            time.sleep(2 ** (i + 1))


def parse_pagina(html):
    """Extrai os veículos dos cards de uma página de listagem."""
    soup = BeautifulSoup(html, "html.parser")
    veiculos = {}
    for card in soup.select("div.card"):
        link = card.find("a", href=RE_ID)
        if not link:
            continue
        vid = RE_ID.search(link["href"]).group(1)

        titulos = card.select("h5.card-text")
        modelo = titulos[0].get_text(strip=True) if titulos else "?"
        preco = titulos[-1].get_text(strip=True) if len(titulos) > 1 else "?"

        monta_el = card.select_one("p.btn")
        monta = monta_el.get_text(strip=True) if monta_el else ""

        texto = card.get_text("\n", strip=True)
        m_marca = RE_MARCA.search(texto)
        m_ano = RE_ANO.search(texto)

        img = card.select_one("img[src]")
        foto = f"{BASE_URL}/{img['src'].lstrip('/')}" if img else ""

        veiculos[vid] = {
            "modelo": modelo,
            "marca": m_marca.group(1).strip() if m_marca else "",
            "ano": m_ano.group(1).strip() if m_ano else "",
            "preco": preco,
            "monta": monta,
            "foto": foto,
            "link": f"{BASE_URL}/Veiculo.aspx?id={vid}",
        }
    return veiculos


def varrer_estoque():
    """Percorre todas as páginas da listagem e retorna dict id -> dados."""
    estoque = {}
    for pag in range(1, MAX_PAGES + 1):
        html = fetch(LISTING_URL, params={"pag": pag})
        veiculos = parse_pagina(html)
        # Para quando a página vem vazia ou só repete veículos já vistos
        # (a última página da paginação "trava" e devolve o mesmo conteúdo).
        if not veiculos or set(veiculos) <= set(estoque):
            break
        estoque.update(veiculos)
        time.sleep(1)
    return estoque


def carregar_estado():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return None


def salvar_estado(estado):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(estado, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def notificar(titulo, mensagem, link="", foto=""):
    """Publica notificação no ntfy.sh (vira push no celular)."""
    if not NTFY_TOPIC:
        print(f"[sem NTFY_TOPIC] {titulo} — {mensagem}")
        return
    payload = {
        "topic": NTFY_TOPIC,
        "title": titulo,
        "message": mensagem,
        "tags": ["red_car"],
    }
    if link:
        payload["click"] = link
    if foto:
        payload["attach"] = foto
    try:
        requests.post("https://ntfy.sh/", json=payload, timeout=30).raise_for_status()
    except requests.RequestException as exc:
        print(f"Falha ao notificar: {exc}", file=sys.stderr)


def main():
    estoque = varrer_estoque()
    if not estoque:
        print(
            "Nenhum veículo encontrado — site fora do ar ou layout mudou. "
            "Estado preservado.",
            file=sys.stderr,
        )
        return 1

    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    estado = carregar_estado()

    if estado is None:
        # Primeira execução: semeia o estado sem disparar um push por veículo.
        for dados in estoque.values():
            dados["visto_em"] = agora
        salvar_estado(estoque)
        notificar(
            "Monitor Lucinei ativo",
            f"{len(estoque)} veículos no estoque. Novos lançamentos serão avisados aqui.",
            link=LISTING_URL,
        )
        print(f"Estado inicial criado com {len(estoque)} veículos.")
        return 0

    novos = {vid: dados for vid, dados in estoque.items() if vid not in estado}

    if len(novos) > RESUMO_THRESHOLD:
        modelos = ", ".join(d["modelo"] for d in list(novos.values())[:5])
        notificar(
            f"{len(novos)} veículos novos na Lucinei",
            f"Entre eles: {modelos}…",
            link=LISTING_URL,
        )
    else:
        for dados in novos.values():
            notificar(
                f"Novo: {dados['marca']} {dados['modelo']}",
                f"Ano {dados['ano']} — {dados['preco']} ({dados['monta']})",
                link=dados["link"],
                foto=dados["foto"],
            )

    # Estado é cumulativo (guarda tudo que já passou pelo site): se um veículo
    # vendido voltar a ser anunciado com o mesmo código, não notifica de novo.
    for vid, dados in estoque.items():
        dados["visto_em"] = estado.get(vid, {}).get("visto_em", agora)
        estado[vid] = dados
    salvar_estado(estado)

    print(
        f"{len(estoque)} veículos no site, {len(novos)} novos, "
        f"estado com {len(estado)} registros."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
