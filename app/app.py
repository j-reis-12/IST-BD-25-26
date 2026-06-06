#!/usr/bin/python3
# Copyright (c) BDist Development Team
# Distributed under the terms of the Modified BSD License.
import os
from logging.config import dictConfig

from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from psycopg.rows import namedtuple_row, dict_row 
from psycopg_pool import ConnectionPool

dictConfig(
    {
        "version": 1,
        "formatters": {
            "default": {
                "format": "[%(asctime)s] %(levelname)s in %(module)s:%(lineno)s - %(funcName)20s(): %(message)s",
            }
        },
        "handlers": {
            "wsgi": {
                "class": "logging.StreamHandler",
                "stream": "ext://flask.logging.wsgi_errors_stream",
                "formatter": "default",
            }
        },
        "root": {"level": "INFO", "handlers": ["wsgi"]},
    }
)

RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")

app = Flask(__name__)
app.config.from_prefixed_env()
log = app.logger
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri=RATELIMIT_STORAGE_URI,
)

# Use the DATABASE_URL environment variable if it exists, otherwise use the default.
# Use the format postgres://username:password@hostname/database_name to connect to the database.
DATABASE_URL = os.environ.get("DATABASE_URL", "postgres://app:app@postgres/app")

pool = ConnectionPool(
    conninfo=DATABASE_URL,
    kwargs={
        "autocommit": True,  # If True don’t start transactions automatically.
        "row_factory": namedtuple_row,
    },
    min_size=4,
    max_size=10,
    open=True,
    # check=ConnectionPool.check_connection,
    name="postgres_pool",
    timeout=5,
)


def is_decimal(s):
    """Returns True if string is a parseable float number."""
    try:
        float(s)
        return True
    except ValueError:
        return False


@app.route("/zona/<int:id_zona>/", methods=("GET",))
@app.route("/zona/<int:id_zona>", methods=("GET",))
@limiter.limit("1 per second")
def zona_index(id_zona):
    """Retorna a lista de recintos e respetivas espécies de uma zona."""

    with pool.connection() as conn:
        # Usamos o dict_row para podermos aceder aos campos pelos nomes das colunas
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT 
                    r.id_recinto,
                    e.nome_cientifico,
                    e.nome_comum,
                    COUNT(a.id_animal) AS num_animais
                FROM recinto r
                LEFT JOIN animal a ON r.id_recinto = a.id_recinto
                LEFT JOIN especie e ON a.nome_cientifico = e.nome_cientifico
                WHERE r.id_zona = %(id_zona)s
                GROUP BY r.id_recinto, e.nome_cientifico, e.nome_comum
                ORDER BY r.id_recinto;
                """,
                {"id_zona": id_zona},
            )
            rows = cur.fetchall()

    # Se a zona não existir ou não tiver recintos associados
    if not rows:
        return jsonify({"message": "Zona não encontrada ou sem recintos.", "status": "error"}), 404

    # Dicionário auxiliar para agrupar os dados por recinto
    recintos_ajustados = {}

    for row in rows:
        id_recinto = row["id_recinto"]
        
        # Se é a primeira vez que vemos este recinto, inicializamos a sua estrutura
        if id_recinto not in recintos_ajustados:
            recintos_ajustados[id_recinto] = {
                "id_recinto": id_recinto,
                "especies": []
            }
        
        # Se o recinto tiver espécies (ou seja, se não estiver vazio devido ao LEFT JOIN)
        if row["nome_cientifico"] is not None:
            recintos_ajustados[id_recinto]["especies"].append({
                "nome_cientifico": row["nome_cientifico"],
                "nome_comum": row["nome_comum"],
                "num_animais": row["num_animais"]
            })

    # Convertemos o dicionário de suporte de volta para uma lista JSON limpa
    output_lista = list(recintos_ajustados.values())

    return jsonify(output_lista), 200



@app.route("/recinto/<int:id_recinto>/voto/<int:bid>/", methods=("POST", "PUT"))
@app.route("/recinto/<int:id_recinto>/voto/<int:bid>", methods=("POST", "PUT"))
@limiter.limit("1 per second")
def recinto_voto_save(id_recinto, bid):
    """Regista o voto de um bilhete num recinto específico."""

    with pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            
            # LEITURA E VALIDAÇÃO
            cur.execute(
                """
                SELECT 
                    b.votou,
                    EXISTS (
                        SELECT 1 
                        FROM acesso a
                        JOIN recinto r ON a.id_zona = r.id_zona
                        WHERE a.bid = b.bid AND r.id_recinto = %(id_recinto)s
                    ) AS tem_acesso
                FROM bilhete b
                WHERE b.bid = %(bid)s;
                """,
                {"bid": bid, "id_recinto": id_recinto}
            )
            
            resultado = cur.fetchone()

            # Validação
            if not resultado:
                return jsonify({"message": "Bilhete não encontrado.", "status": "error"}), 404
            
            if resultado["votou"] is True:
                return jsonify({"message": "Erro: Este bilhete já foi utilizado para votar.", "status": "error"}), 400
            if resultado["tem_acesso"] is False:
                return jsonify({"message": "Erro: Este bilhete não tem acesso à zona deste recinto.", "status": "error"}), 403

            # ESCRITA
            try:
                # Inicia a transação
                with conn.transaction():
                    
                    # Atualiza o bilhete
                    cur.execute(
                        """
                        UPDATE bilhete
                        SET votou = TRUE
                        WHERE bid = %(bid)s;
                        """,
                        {"bid": bid}
                    )
                    
                    # Atualiza os votos do recinto
                    cur.execute(
                        """
                        UPDATE recinto
                        SET votos = votos + 1
                        WHERE id_recinto = %(id_recinto)s;
                        """,
                        {"id_recinto": id_recinto}
                    )
                    
            except Exception as e:
                # Se falhar o ROLLBACK é automático.
                return jsonify({"message": f"Erro interno ao registar o voto: {str(e)}", "status": "error"}), 500
                
    return jsonify({"message": "Voto registado com sucesso!", "status": "success"}), 200

    

from datetime import datetime
@app.route("/venda/", methods=("POST",))
@app.route("/venda", methods=("POST",))
@limiter.limit("1 per second")
def venda_save():
    """Processa uma venda, gerando bilhetes e os seus acessos às zonas."""
    
    # 1. Obter o JSON enviado pelo cliente
    dados = request.get_json()
    
    if not dados or "bilhetes" not in dados or not dados["bilhetes"]:
        return jsonify({"message": "A venda tem de conter pelo menos um bilhete.", "status": "error"}), 400

    nif_cliente = dados.get("nif_cliente", None)
    
    # Estruturas para guardar o output final
    preco_total_venda = 0.0
    output_bilhetes = []

    try:
        with pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                with conn.transaction():
                    
                    # Criar a Venda
                    data_hora_atual = datetime.now()
                    
                    cur.execute(
                        """
                        INSERT INTO venda (data_hora, nif_cliente)
                        VALUES (%(data_hora)s, %(nif)s)
                        RETURNING no_venda;
                        """,
                        {"data_hora": data_hora_atual, "nif": nif_cliente}
                    )
                    no_venda = cur.fetchone()["no_venda"]
                    
                    # Processar cada bilhete
                    for req_bilhete in dados["bilhetes"]:
                        desconto = req_bilhete.get("desconto", 0.00)
                        zonas = req_bilhete.get("zonas", [])
                        
                        if not zonas:
                            raise ValueError("Um bilhete tem de ter acesso a pelo menos uma zona.")

                        # Criar o bilhete
                        cur.execute(
                            """
                            INSERT INTO bilhete (desconto, votou, no_venda)
                            VALUES (%(desconto)s, FALSE, %(no_venda)s)
                            RETURNING bid;
                            """,
                            {"desconto": desconto, "no_venda": no_venda}
                        )
                        bid = cur.fetchone()["bid"]
                        
                        preco_bilhete = 0.0
                        
                        # Adicionar os acessos e calcular o preço 
                        for id_zona in zonas:
                            # Ir buscar o preço da zona à base de dados
                            cur.execute(
                                "SELECT preco FROM zona WHERE id_zona = %(id_zona)s;",
                                {"id_zona": id_zona}
                            )
                            zona_info = cur.fetchone()
                            
                            if not zona_info:
                                raise ValueError(f"A zona com ID {id_zona} não existe.")
                                
                            # Associar o bilhete à zona
                            cur.execute(
                                """
                                INSERT INTO acesso (bid, id_zona)
                                VALUES (%(bid)s, %(id_zona)s);
                                """,
                                {"bid": bid, "id_zona": id_zona}
                            )
                            
                            # Somar o preço base
                            preco_bilhete += float(zona_info["preco"])
                        
                        # Aplicar o desconto (ex: se desconto for 0.50, corta 50% do preço)
                        preco_bilhete_final = preco_bilhete * (1 - float(desconto))
                        preco_total_venda += preco_bilhete_final
                        
                        # Guardar a info deste bilhete para a resposta final
                        output_bilhetes.append({
                            "bid": bid,
                            "preco_bilhete": round(preco_bilhete_final, 2)
                        })

    except ValueError as ve:
        # Erros de validação
        return jsonify({"message": str(ve), "status": "error"}), 400
    except Exception as e:
        # Se o trigger RI-4 disparar, a transação falha e faz rollback
        return jsonify({"message": f"Erro na base de dados: {str(e)}", "status": "error"}), 500

    # Se chegou aqui, o COMMIT foi feito com sucesso. Devolver a estrutura exigida.
    resposta = {
        "preco_total": round(preco_total_venda, 2),
        "bilhetes": output_bilhetes
    }
    
    return jsonify(resposta), 201


@app.route("/ping", methods=("GET",))
@limiter.exempt
def ping():
    log.debug("ping!")
    return jsonify({"message": "pong!", "status": "success"})


if __name__ == "__main__":
    app.run()
