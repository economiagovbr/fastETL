# Thanks to Jedi Wash! *.*
"""
Módulo cópia de dados entre Postgres e MsSql.

last update: 20/06/2020
guilty: Vitor Bellini, Nitai Bezerra
"""

import time
from datetime import datetime
import warnings
import urllib
from typing import List, Union
import pyodbc
from sqlalchemy import create_engine
import ctds
import ctds.pool
import pandas as pd

from airflow.hooks.postgres_hook import PostgresHook
from airflow.hooks.mssql_hook import MsSqlHook
from airflow.hooks.mysql_hook import MySqlHook
from airflow.hooks.base_hook import BaseHook


class DbConnection():
    """
    Gera as conexões origem e destino dependendo do tipo de provider.
    Providers disponíveis: 'MSSQL', 'PG' e 'MYSQL'
    """

    def __init__(self, conn_id: str, provider: str):
        # Valida providers suportados
        providers = ['MSSQL', 'PG', 'MYSQL']
        assert provider.upper() in providers, 'Provider não suportado '\
                                              '(utilize MSSQL, PG ou MYSQL) :P'

        if provider.upper() == 'MSSQL':
            conn_values = BaseHook.get_connection(conn_id)
            driver = '{ODBC Driver 17 for SQL Server}'
            server = conn_values.host
            port = conn_values.port
            database = conn_values.schema
            user = conn_values.login
            password = conn_values.password
            self.mssql_conn_string = f"""Driver={driver};\
                Server={server}, {port};\
                Database={database};\
                Uid={user};\
                Pwd={password};"""
        elif provider.upper() == 'PG':
            self.pg_hook = PostgresHook(postgres_conn_id=conn_id)
        elif provider.upper() == 'MYSQL':
            self.msql_hook = MySqlHook(mysql_conn_id=conn_id)
        self.provider = provider

    def __enter__(self):
        if self.provider == 'MSSQL':
            try:
                self.conn = pyodbc.connect(self.mssql_conn_string)
            except:
                raise Exception('MsSql connection failed.')
        elif self.provider == 'PG':
            try:
                self.conn = self.pg_hook.get_conn()
            except:
                raise Exception('PG connection failed.')
        elif self.provider == 'MYSQL':
            try:
                self.conn = self.msql_hook.get_conn()
            except:
                raise Exception('MYSQL connection failed.')
        return self.conn

    def __exit__(self, exc_type, exc_value, traceback):
        self.conn.close()

def build_select_sql(source_table: str,
                     column_list: str) -> str:
    """
    Monta a string do select da origem
    """

    columns = ', '.join(col for col in column_list)

    return f'SELECT {columns} FROM {source_table}'

def build_dest_sqls(destination_table: str, column_list: str,
                    wildcard_symbol: str) -> Union[str, str, str]:
    """
    Monta a string do insert do destino
    Monta a string de truncate do destino
    """

    columns = ', '.join(col for col in column_list)

    values = ", ".join([wildcard_symbol for i in range(len(column_list))])
    insert = f'INSERT INTO {destination_table} ({columns}) ' \
             f'VALUES ({values})'

    truncate = f'TRUNCATE TABLE {destination_table}'

    return insert, truncate

def get_cols_name(cur,
                  destination_provider: str,
                  destination_table: str,
                  columns_to_ignore: list=[]) -> List[str]:
    """
    Obtem as colunas da tabela de destino
    """

    if destination_provider.upper() == 'MSSQL':
        colnames = []
        cur.execute(f'SELECT * FROM {destination_table} WHERE 1 = 2')
        for col in cur.columns(schema=destination_table.split('.')[0], \
            table=destination_table.split('.')[1]):
            colnames.append(col.column_name)
    elif destination_provider.upper() == 'PG':
        cur.execute(f'SELECT * FROM {destination_table} WHERE 1 = 2')
        colnames = [desc[0] for desc in cur.description]

    colnames = [n for n in colnames
                    if n not in columns_to_ignore]

    return [f'"{n}"' for n in colnames]

def get_table_cols_name(conn_id: str, schema: str, table: str):
    """
    Obtem a lista de colunas de uma tabela.
    """
    conn_values = BaseHook.get_connection(conn_id)

    if conn_values.conn_type == 'mssql':
        db_hook = MsSqlHook(mssql_conn_id=conn_id)
    elif conn_values.conn_type == 'postgres':
        db_hook = PostgresHook(postgres_conn_id=conn_id)
    else:
        raise Exception('Conn_type not implemented.')

    with db_hook.get_conn() as db_conn:
        with db_conn.cursor() as db_cur:
            db_cur.execute(f'SELECT * FROM {schema}.{table} WHERE 1=2')
            column_names = [tup[0] for tup in db_cur.description]

    return column_names

def get_mssql_odbc_conn_str(conn_id: str):
    """
    Cria uma string de conexão com banco SQL Server usando driver pyodbc.
    """
    conn_values = BaseHook.get_connection(conn_id)
    driver = '{ODBC Driver 17 for SQL Server}'
    server = conn_values.host
    port = conn_values.port
    database = conn_values.schema
    user = conn_values.login
    password = conn_values.password

    mssql_conn = f"""Driver={driver};Server={server}, {port}; \
                    Database={database};Uid={user};Pwd={password};"""

    quoted_conn_str = urllib.parse.quote_plus(mssql_conn)

    return f'mssql+pyodbc:///?odbc_connect={quoted_conn_str}'

def get_mssql_odbc_engine(conn_id: str):
    """
    Cria uma engine de conexão com banco SQL Server usando driver pyodbc.
    """
    return create_engine(get_mssql_odbc_conn_str(conn_id))

def insert_df_to_db(df: pd.DataFrame, conn_id: str, schema: str,
                    table: str, reflect_col_table: bool = True):
    """
    Insere os registros do DataFrame df na tabela especificada. Insere
    apenas as colunas que existem na tabela.

    TODO: Implementar aqui o registro no LOG CONTROLE
    """
    if reflect_col_table:
        # Filter existing table columns
        cols = get_table_cols_name(conn_id=conn_id,
                                   schema=schema,
                                   table=table)
        cols = [col.lower() for col in cols]
        df.columns = df.columns.str.lower()
        df = df[cols]

    df.to_sql(name=table,
              schema=schema,
              con=get_mssql_odbc_engine(conn_id),
              if_exists='append',
              index=False)

def validate_db_string(source_table: str, destination_table: str,
                       select_sql: str) -> None:
    """
    Valida se string do banco está no formato schema.table e se tabelas de
    origem e destino possuem o mesmo nome. Se possui select_sql não valida a
    source_table
    """

    assert destination_table.count('.') == 1, 'Estrutura tabela destino ' \
                                              'deve ser str: schema.table'

    if not select_sql:
        assert source_table.count('.') == 1, 'Estrutura tabela origem deve ' \
                                            'ser str: schema.table'

        if source_table.split('.')[1] != destination_table.split('.')[1]:
            warnings.warn('Tabelas de origem e destino com nomes diferentes')

def compare_source_dest_rows(source_cur,
                             destination_cur,
                             source_table: str,
                             destination_table: str) -> None:
    """
    Compara quantidade de linhas na tabela origem e destino após o ETL.
    Caso diferente, imprime warning. Quando a tabela de origem está
    diretamente ligada ao sistema transacional justifica-se a diferença.
    """

    source_cur.execute(f'SELECT COUNT(*) FROM {source_table}')
    destination_cur.execute(f'SELECT COUNT(*) FROM {destination_table}')

    source_row_count = source_cur.fetchone()[0]
    destination_row_count = destination_cur.fetchone()[0]

    if source_row_count != destination_row_count:
        warnings.warn('Quantidade de linhas diferentes na origem e destino. ' \
                      f'Origem: {source_row_count} linhas. ' \
                      f'Destino: {destination_row_count} linhas')

def copy_db_to_db(destination_table: str,
                  source_conn_id: str,
                  source_provider: str,
                  destination_conn_id: str,
                  destination_provider: str,
                  source_table: str = None,
                  select_sql: str = None,
                  columns_to_ignore: list = [],
                  destination_truncate: bool = True,
                  chunksize: int = 1000) -> None:
    """
    Carrega dado do Postgres/MSSQL/MySQL para Postgres/MSSQL com psycopg2 e pyodbc
    copiando todas as colunas e linhas já existentes na tabela de destino.
    Tabela de destino deve ter a mesma estrutura e nome de tabela e colunas
    que a tabela de origem, ou passar um select_sql que tenha as colunas de
    destino.

    Alguns tipos de dados utilizados na tabela destino podem gerar
    problemas na cópia. Esta lista consolida os casos conhecidos:
    * **float**: mude para **numeric(x,y)** ou **decimal(x,y)**
    * **text**: mude para **varchar(max)** ou **nvarchar**
    * para datas: utilize **date** para apenas datas, **datetime** para
    data com hora, e **datetime2** para timestamp

    Exemplo:
        copy_db_to_db('Siorg_VBL.contato_email',
                      'SIORG_ESTATISTICAS.contato_email',
                      'POSTG_CONN_ID',
                      'PG',
                      'MSSQL_CONN_ID',
                      'MSSQL')

    Args:
        destination_table (str): tabela de destino no formato schema.table
        source_conn_id (str): connection origem do Airflow
        source_provider (str): provider do banco origem (MSSQL ou PG)
        destination_conn_id (str): connection destino do Airflow
        destination_provider (str): provider do banco destino (MSSQL ou PG)
        source_table (str): tabela de origem no formato schema.table
        select_sql (str): query sql para consulta na origem. Se utilizado o
            source_table será ignorado
        columns_to_ignore (list): list of columns to be ignored in the copy
        destination_truncate (bool): booleano para truncar tabela de destino
            antes do load. Default = True
        chunksize (int): tamanho do bloco de leitura na origem.
            Default = 1000 linhas

    Return:
        None

    Todo:
        * Transformar em Classe ou em Airflow Operator
        * Criar tabela no destino quando não existente
        * Alterar conexão do Postgres para pyodbc
        * Possibilitar inserir data da carga na tabela de destino
        * Criar testes
    """

    # validate db string
    validate_db_string(source_table, destination_table, select_sql)

    # create connections
    with DbConnection(source_conn_id, source_provider) as source_conn:
        with DbConnection(destination_conn_id, destination_provider) \
            as destination_conn:
            with source_conn.cursor() as source_cur:
                with destination_conn.cursor() as destination_cur:
                    # Fast etl
                    if destination_provider == 'MSSQL':
                        destination_conn.autocommit = False
                        destination_cur.fast_executemany = True
                        wildcard_symbol = '?'
                    else:
                        wildcard_symbol = '%s'

                    # gera queries
                    col_list = get_cols_name(destination_cur,
                                             destination_provider,
                                             destination_table,
                                             columns_to_ignore)

                    insert, truncate = build_dest_sqls(destination_table,
                                                       col_list, wildcard_symbol)
                    if not select_sql:
                        select_sql = build_select_sql(source_table, col_list)

                    # truncate stg
                    if destination_truncate:
                        destination_cur.execute(truncate)
                        if destination_provider == 'MSSQL':
                            destination_cur.commit()

                    # download data
                    start_time = time.perf_counter()
                    source_cur.execute(select_sql)
                    rows = source_cur.fetchmany(chunksize)
                    rows_inserted = 0

                    print(f'Inserindo linhas na tabela [{destination_table}].')
                    while rows:
                        destination_cur.executemany(insert, rows)
                        rows_inserted += len(rows)
                        rows = source_cur.fetchmany(chunksize)
                        print(f'{rows_inserted} linhas inseridas!!')

                    destination_conn.commit()

                    delta_time = time.perf_counter() - start_time

                    # validate total lines downloaded
                    # compare_source_dest_rows(source_cur,
                    #                           destination_cur,
                    #                           source_table,
                    #                           destination_table)

                    print('Tempo load: {:.4f} segundos'.format(delta_time))
                    print('Linhas inseridas: {}'.format(rows_inserted))
                    print('linhas/segundo: {}'.format(rows_inserted / delta_time))

def _table_rows_count(db_hook,
                     table: str,
                     where_condition: str = None):
    """ Calcula a quantidade de linhas na tabela (table) e utiliza a
    condição (where_condition) caso seja passada como parâmetro.
    """
    sql = f"SELECT COUNT(*) FROM {table}"
    sql += f" WHERE {where_condition};" if where_condition is not None else ";"
    return db_hook.get_first(sql)[0]

# TODO: Propor ao Wash de passarmos a definir explicitamente a coluna
# 'dataalteracao' na variável airflow de configurações sempre que for o
# caso, e assim pararmos de checar se a coluna 'dataalteracao' está na
# lista de colunas. Consultá-lo sobre drawbacks.

def _table_column_max_string(db_hook: MsSqlHook, table: str, column: str):
    """ Calcula o valor máximo da coluna (column) na tabela (table). Se
    a coluna for 'dataalteracao' a string retornada é formatada.
    """
    sql = f"SELECT MAX({column}) FROM {table};"
    max_value = db_hook.get_first(sql)[0]
    # TODO: Descobrir se é data pelo tipo do BD
    if column == 'dataalteracao':
        return max_value.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    else:
        return str(max_value)


def _build_increm_filter(col_list: list, dest_hook: MsSqlHook,
                table: str, key_column: str) -> str:
    """ Constrói a condição where (where_condition) a ser utilizada para
    calcular e identificar as linhas da tabela no BD origem (Quartzo/Serpro)
    que devem ser sincronizadas com aquela tabela no BD destino. Se a
    tabela não possuir a coluna 'dataalteracao' será utilizada a coluna
    (key_column).
    """
    col_list = [col.lower() for col in col_list]
    if 'dataalteracao' in col_list:
        key = "dataalteracao"
    else:
        key = key_column
    max_value = _table_column_max_string(dest_hook, table, key)
    where_condition = f"{key} > '{max_value}'"

    return where_condition


# New func: Distingue se a coluna para obtenção do max() e montagem do
#           filtro (where) é uma "data/hora alteração" ou é um número
#           sequencial (id, pk, etc): 'date_column' ou 'key_column'.
def _build_filter_condition(dest_hook: MsSqlHook,
                table: str, date_column: str, key_column: str):

    if date_column:
        sql = f"SELECT MAX({date_column}) FROM {table}"
    else:
        sql = f"SELECT MAX({key_column}) FROM {table}"

    max_value = dest_hook.get_first(sql)[0]

    if date_column:
        max_value = max_value.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        where_condition = f"{date_column} > '{max_value}'"
    else:
        max_value = str(max_value)
        where_condition = f"{key_column} > '{max_value}'"

    return max_value, where_condition


def _build_incremental_sqls(dest_table: str, source_table: str,
                           key_column: str, column_list: str):
    """ Constrói as queries SQLs que realizam os Updates dos registros
    atualizados desde a última sincronização e os Inserts das novas
    linhas.
    """
    cols = ", ".join(f"{col} = orig.{col}" for col in column_list)
    updates_sql = f"""
            UPDATE {dest_table} SET {cols}
            FROM {source_table} orig
            WHERE orig.{key_column} = {dest_table}.{key_column}
            """
    cols = ", ".join(column_list)
    inserts_sql = f"""INSERT INTO {dest_table} ({cols})
            SELECT {cols}
            FROM {source_table} AS inc
            WHERE NOT EXISTS
            (SELECT 1 FROM {dest_table} AS atual
                WHERE atual.{key_column} = inc.{key_column})
            """
    return updates_sql, inserts_sql

def sync_db_2_db(source_conn_id: str,
                 destination_conn_id: str,
                 table: str,
                 date_column: str,
                 key_column: str,
                 source_schema: str,
                 destination_schema: str,
                 increment_schema: str,
                 sync_exclusions: bool = False,
                 source_exc_schema: str = None,
                 source_exc_table: str = None,
                 source_exc_column: str = None,
                 chunksize: int = 1000) -> None:
    """ Realiza a atualização incremental de uma tabela. A sincronização
    é realizada em 3 etapas. 1-Envia s alterações necessárias para uma
    tabela intermediária localizada no esquema `increment_schema`.
    2-Realiza os Updates. 3-Realiza os Insertes. Apenas as colunas que
    existam na tabela no BD destino serão sincronizadas. Funciona com
    Postgres na origem e MsSql no destino. O algoritmo também realiza
    sincronização de exclusões.

    Exemplo:
        sync_db_2_db(source_conn_id=SOURCE_CONN_ID,
                     destination_conn_id=DEST_CONN_ID,
                     table=table,
                     date_column=date_column,
                     key_column=key_column,
                     source_schema=SOURCE_SCHEMA,
                     destination_schema=STG_SCHEMA,
                     chunksize=CHUNK_SIZE)

    Args:
        source_conn_id (str): string de conexão airflow do DB origem
        destination_conn_id (str): string de conexão airflow do DB destino
        table (str): tabela a ser sincronizada
        date_column (str): nome da coluna a ser utilizado para
        identificação dos registros atualizados na origem.
        key_column (str): nome da coluna a ser utilizado como chave na
        etapa de atualização dos registros antigos que sofreram
        atualizações na origem.
        source_eschema (str): esquema do BD na origem
        destination_schema (str): esquema do BD no destino
        increment_schema (str): Esquema no banco utilizado para tabelas
        temporárias. Caso esta variável seja None, esta tabela será
        criada no mesmo schema com sufixo '_alteracoes'
        sync_exclusions (bool): opção de sincronizar exclusões.
        Default = False.
        source_exc_schema (str): esquema da tabela na origem onde estão
        registradas exclusões
        source_exc_table (str): tabela na origem onde estão registradas
        exclusões
        source_exc_column (str): coluna na tabela na origem onde estão
        registradas exclusões
        chunksize (int): tamanho do bloco de leitura na origem.
        Default = 1000 linhas

    Return:
        None

    Todo:
        * Automatizar a criação da tabela gêmea e remoção ao final
        * Transformar em Airflow Operator
        * Possibilitar ler de MsSql e escrever em Postgres
        * Possibilitar inserir data da carga na tabela de destino
        * Criar testes
    """
    source_table_name = f"{source_schema}.{table}"
    dest_table_name = f"{destination_schema}.{table}"
    if increment_schema:
        inc_table_name = f"{increment_schema}.{table}"
    else:
        inc_table_name = f"{destination_schema}.{table}_alteracoes"

    source_hook = PostgresHook(postgres_conn_id=source_conn_id, autocommit=True)

    conn_values = BaseHook.get_connection(destination_conn_id)
    if conn_values.conn_type == 'mssql':
        dest_hook = MsSqlHook(mssql_conn_id=destination_conn_id)
        destination_provider = 'MSSQL'
    elif conn_values.conn_type == 'postgres':
        dest_hook = PostgresHook(postgres_conn_id=destination_conn_id)
        destination_provider = 'PG'

    col_list = get_table_cols_name(destination_conn_id,
                                   destination_schema,
                                   table)

    dest_rows_count = _table_rows_count(dest_hook, dest_table_name)
    print(f"Total de linhas atualmente na tabela destino: {dest_rows_count}.")
    # If de tabela vazia separado para evitar erro na _build_filter_condition()
    if dest_rows_count == 0:
        raise Exception("Tabela destino vazia! Utilize carga full!")

    ref_value, where_condition = _build_filter_condition(dest_hook,
                                                         dest_table_name,
                                                         date_column,
                                                         key_column)
    new_rows_count = _table_rows_count(source_hook,
                                       source_table_name,
                                       where_condition)
    print(f"Total de linhas novas ou modificadas: {new_rows_count}.")

    # Guarda as alterações e inclusões necessárias
    select_sql = build_select_sql(f"{source_table_name}", col_list)
    select_diff = f"{select_sql} WHERE {where_condition}"
    print(f"SELECT para espelhamento: {select_diff}")
    copy_db_to_db(destination_table=f"{inc_table_name}",
                  source_conn_id=source_conn_id,
                  source_provider='PG',
                  destination_conn_id=destination_conn_id,
                  destination_provider=destination_provider,
                  source_table=None,
                  select_sql=select_diff,
                  destination_truncate=True,
                  chunksize=chunksize)

    # Reconstrói índices
    if conn_values.conn_type == 'mssql':
        sql = f"ALTER INDEX ALL ON {inc_table_name} REBUILD"
    elif conn_values.conn_type == 'postgres':
        sql = f"REINDEX TABLE {inc_table_name}"

    dest_hook.run(sql)

    print(f"Iniciando carga incremental na tabela {dest_table_name}.")
    updates_sql, inserts_sql = _build_incremental_sqls(
        dest_table=f"{dest_table_name}",
        source_table=f"{inc_table_name}",
        key_column=key_column,
        column_list=col_list)
    # Realiza updates
    dest_hook.run(updates_sql)
    # Realiza inserts de novas linhas
    dest_hook.run(inserts_sql)

    # Se precisar aplicar as exclusões da origem no destino:
    if sync_exclusions:
        source_exc_sql = f"""SELECT {key_column}
                             FROM {source_exc_schema}.{source_exc_table}
                             WHERE {source_exc_column} > '{ref_value}'
                          """
        rows = source_hook.get_records(source_exc_sql)
        ids_to_del = [row[0] for row in rows]
        if ids_to_del:
            ids = ", ".join(str(id) for id in ids_to_del)
            sql = f"""
                DELETE FROM {dest_table_name}
                WHERE {key_column} IN ({ids})
            """
            dest_hook.run(sql)
        print("Quantidade de linhas possivelmente excluídas:", len(ids_to_del))



def write_ctds(table, rows, conn_id):
    """
    Escreve em banco MsSql Server utilizando biblioteca ctds com driver
    FreeTds.
    """

    conn_values = BaseHook.get_connection(conn_id)

    dbconfig = {
        "server": conn_values.host,
        "port": int(conn_values.port),
        "database": conn_values.schema,
        "autocommit": True,
        "enable_bcp": True,
        "ntlmv2": True,
        "user": conn_values.login,
        "password": conn_values.password,
        "timeout": 300
    }

    pool = ctds.pool.ConnectionPool(ctds, dbconfig)

    with pool.connection() as conn:
        itime = time.perf_counter()
        linhas = conn.bulk_insert(
            table=table,
            rows=rows,
            # batch_size=300000,
        )
        ftime = time.perf_counter()
        print(f"{linhas} linhas inseridas em {ftime - itime} segundos.")

def copy_by_key_interval(
                    source_provider: str,
                    source_conn_id: str,
                    source_table: str,
                    destination_provider: str,
                    destination_conn_id: str,
                    destination_table: str,
                    key_column: str,
                    key_start: int = 0,
                    key_interval: int = 10000,
                    destination_truncate: bool = True):
    """
    Carrega dado do Postgres/MSSQL para Postgres/MSSQL com psycopg2 e pyodbc
    copiando todas as colunas já existentes na tabela de destino usando
    intervalos de valores da chave da tabela na consulta à origem.
    Tabela de destino deve ter as mesmas colunas ou subconjunto das colunas
    da tabela de origem, e com data types iguais ou compatíveis.

    Exemplo:
        copy_by_key_interval(
                            source_provider='PG',
                            source_conn_id='quartzo_scdp',
                            source_table='novoScdp_VBL.trecho',
                            destination_provider='MSSQL',
                            destination_conn_id='mssql_srv_30_stg_scdp',
                            destination_table='dbo.trecho',
                            key_column='id',
                            key_start=2565,
                            key_interval=1000,
                            destination_truncate=False)

    Args:
        source_provider (str): provider do banco origem (MSSQL ou PG)
        source_conn_id (str): connection origem do Airflow
        source_table (str): tabela de origem no formato schema.table
        destination_provider (str): provider do banco destino (MSSQL ou PG)
        destination_conn_id (str): connection destino do Airflow
        destination_table (str): tabela de destino no formato schema.table
        key_column (str): nome da coluna chave da tabela origem
        key_start (int): id da chave a partir do qual a cópia é iniciada
        key_interval (int): intervalo de id's para ler da origem a cada vez
        destination_truncate (bool): booleano para truncar tabela de destino
            antes do load. Default = True

    Return:
        Tupla (status: bool, next_key: int):
            status: True (sucesso) ou False (falha)
            next_key: id da próxima chave a carregar, quando status = False
                      None: quando status = True, ou outras situações

    TODO:
        * try/except nas aberturas das conexões; se erro: return False, key_start
        * comparar performance do prepared statement no source: psycopg2 x pyodbc
    """

    # validate db string
    validate_db_string(source_table, destination_table, None)

    # create connections
    with DbConnection(source_conn_id, source_provider) as source_conn:
        with DbConnection(destination_conn_id, destination_provider) \
            as destination_conn:
            with source_conn.cursor() as source_cur:
                with destination_conn.cursor() as destination_cur:

                    # Fast etl
                    if destination_provider == 'MSSQL':
                        destination_conn.autocommit = False
                        destination_cur.fast_executemany = True
                        wildcard_symbol = '?'
                    else:
                        wildcard_symbol = '%s'

                    # gera queries
                    col_list = get_cols_name(destination_cur,
                                             destination_provider,
                                             destination_table)
                    insert, truncate = build_dest_sqls(destination_table,
                                                       col_list, wildcard_symbol)
                    select_sql = build_select_sql(source_table, col_list)
                    # pyodbc: select_sql = f"{select_sql} WHERE {key_column} BETWEEN ? AND ?"
                    select_sql = f"{select_sql} WHERE {key_column} BETWEEN %s AND %s"

                    # truncate stg
                    if destination_truncate:
                        destination_cur.execute(truncate)
                        destination_cur.commit()

                    # copy by key interval
                    start_time = time.perf_counter()
                    key_begin = key_start
                    key_end = key_begin + key_interval - 1
                    rows_inserted = 0

                    # Tenta LER na origem
                    try:
                        # pyodbc: rows = source_cur.execute(select_sql, key_begin, key_end).fetchall()
                        source_cur.execute(select_sql, (key_begin, key_end))
                        rows = source_cur.fetchall()    # psycopg2
                    except Exception as e:
                        print("Erro origem: ", str(e), "Key interval: ", key_begin, "-", key_end)
                        return False, key_begin

                    last_sleep = datetime.now()
                    run_step = 60 * 30 # 30 minutos

                    # Consulta max id na origem
                    db_hook = PostgresHook( postgres_conn_id=source_conn_id)
                    max_id_sql = f"""select COALESCE(max({key_column}),0)
                                        FROM {source_table}"""
                    max_id = int(db_hook.get_first(max_id_sql)[0])

                    # while rows:
                    while key_begin <= max_id and max_id > 0:
                        if (datetime.now() - last_sleep).seconds > run_step:
                            print(f"Roda por {run_step} segundos e dorme por"
                                   " 20 segundos para evitar o erro"
                                   " Negsignal.SIGKILL do Airflow!")
                            time.sleep(20)
                            last_sleep = datetime.now()

                        # Tenta ESCREVER no destino
                        if rows:
                            try:
                                destination_cur.executemany(insert, rows)
                                destination_conn.commit()
                            except Exception as e:
                                print("Erro destino: ", str(e), "Key interval: ", key_begin, "-", key_end)
                                return False, key_begin

                        rows_inserted += len(rows)
                        key_begin = key_end + 1
                        key_end = key_begin + key_interval - 1
                        # Tenta LER na origem
                        try:
                            # pyodbc: rows = source_cur.execute(select_sql, key_begin, key_end).fetchall()
                            source_cur.execute(select_sql, (key_begin, key_end))
                            rows = source_cur.fetchall()    # psycopg2
                        except Exception as e:
                            print("Erro origem: ", str(e), "Key interval: ", key_begin, "-", key_end)
                            return False, key_begin

                    destination_conn.commit()

                    delta_time = time.perf_counter() - start_time
                    print('Tempo load: {:.4f} segundos'.format(delta_time))
                    print('Linhas inseridas: {}'.format(rows_inserted))
                    print('linhas/segundo: {}'.format(rows_inserted / delta_time))

                    return True, None

def copy_by_key_with_retry(
                    source_provider: str,
                    source_conn_id: str,
                    source_table: str,
                    destination_provider: str,
                    destination_conn_id: str,
                    destination_table: str,
                    key_column: str,
                    key_start: int = 0,
                    key_interval: int = 10000,
                    destination_truncate: bool = True,
                    retries: int = 0,
                    retry_delay: int = 600):
    """
    Copia tabela entre dois bancos de dados chamando a function
    copy_by_key_interval(), mas permitindo retries quando ocorre falha.
    Uso: cópia de tabelas grandes do Quartzo em que se verifica frequentes
    falhas durante os fetchs, por exemplo, no vdb Siasg.
    A vantagem dos retries da function é não precisar fazer count na tabela
    destino a cada nova tentativa de restart. Em tabelas grandes, o count
    demora para retornar.

    Exemplo:
        copy_by_key_with_retry(
                            source_provider='PG',
                            source_conn_id='quartzo_scdp',
                            source_table='novoScdp_VBL.trecho',
                            destination_provider='MSSQL',
                            destination_conn_id='mssql_srv_30_stg_scdp',
                            destination_table='dbo.trecho',
                            key_column='id',
                            key_start=8150500,
                            key_interval=10000,
                            destination_truncate=False,
                            retries=10,
                            retry_delay=300)

    Args:
        source_provider (str): provider do banco origem (MSSQL ou PG)
        source_conn_id (str): connection origem do Airflow
        source_table (str): tabela de origem no formato schema.table
        destination_provider (str): provider do banco destino (MSSQL ou PG)
        destination_conn_id (str): connection destino do Airflow
        destination_table (str): tabela de destino no formato schema.table
        key_column (str): nome da coluna chave da tabela origem
        key_start (int): id da chave a partir do qual a cópia é iniciada
        key_interval (int): intervalo de id's para ler da origem a cada vez
        destination_truncate (bool): booleano para truncar tabela de destino
            antes do load. Default = True
        retries (int): número máximo de tentativas de reprocessamento
        retry_delay (int): quantos segundos aguardar antes da nova tentativa
    """

    retry = 0
    succeeded, next_key = copy_by_key_interval(
                        source_provider=source_provider,
                        source_conn_id=source_conn_id,
                        source_table=source_table,
                        destination_provider=destination_provider,
                        destination_conn_id=destination_conn_id,
                        destination_table=destination_table,
                        key_column=key_column,
                        key_start=key_start,
                        key_interval=key_interval,
                        destination_truncate=destination_truncate)

    while not succeeded and (retry <= retries):
        print("Falha na function copy_by_key_interval !!!")
        retry += 1
        print("Tentando retry", retry, "em", retry_delay, "segundos...")
        time.sleep(retry_delay)
        succeeded, next_key = copy_by_key_interval(
                        source_provider=source_provider,
                        source_conn_id=source_conn_id,
                        source_table=source_table,
                        destination_provider=destination_provider,
                        destination_conn_id=destination_conn_id,
                        destination_table=destination_table,
                        key_column=key_column,
                        key_start=next_key,
                        key_interval=key_interval,
                        destination_truncate=False)


    if succeeded:
        print("Término com sucesso!")
    else:
        print("Término com erro após", retries, "tentativas!")

def copy_by_limit_offset(
                    source_provider: str,
                    source_conn_id: str,
                    source_table: str,
                    destination_provider: str,
                    destination_conn_id: str,
                    destination_table: str,
                    limit: int = 1000,
                    destination_truncate: bool = True):
    """
    Carrega dado do Postgres/MSSQL para Postgres/MSSQL com psycopg2 e pyodbc
    copiando todas as colunas já existentes na tabela de destino, usando
    blocagem de linhas limit/offset na consulta à origem.
    Tabela de destino deve ter as mesmas colunas ou subconjunto das colunas
    da tabela de origem, e com data types iguais ou compatíveis.

    Exemplo:
        copy_by_limit_offset(
                            source_provider='PG',
                            source_conn_id='quartzo_scdp',
                            source_table='novoScdp_VBL.trecho',
                            destination_provider='MSSQL',
                            destination_conn_id='mssql_srv_30_stg_scdp',
                            destination_table='dbo.trecho',
                            limit=1000,
                            destination_truncate=True)

    Args:
        source_provider (str): provider do banco origem (MSSQL ou PG)
        source_conn_id (str): connection origem do Airflow
        source_table (str): tabela de origem no formato schema.table
        destination_provider (str): provider do banco destino (MSSQL ou PG)
        destination_conn_id (str): connection destino do Airflow
        destination_table (str): tabela de destino no formato schema.table
        limit (int): quantidade de linhas para ler da origem a cada vez
        destination_truncate (bool): booleano para truncar tabela de destino
            antes do load. Default = True
    """

    # validate db string
    validate_db_string(source_table, destination_table, None)

    # create connections
    with DbConnection(source_conn_id, source_provider) as source_conn:
        with DbConnection(destination_conn_id, destination_provider) \
            as destination_conn:
            with source_conn.cursor() as source_cur:
                with destination_conn.cursor() as destination_cur:

                    # Fast etl
                    destination_conn.autocommit = False
                    destination_cur.fast_executemany = True

                    # gera queries com limit e offset
                    col_list = get_cols_name(destination_cur,
                                             destination_provider,
                                             destination_table)
                    insert, truncate = build_dest_sqls(destination_table,
                                                       col_list, '?')
                    select_sql = build_select_sql(source_table, col_list)
                    # pyodbc: select_sql = f"{select_sql} limit ?, ?"
                    select_sql = f"{select_sql} limit %s, %s"

                    # truncate stg
                    if destination_truncate:
                        destination_cur.execute(truncate)
                        destination_cur.commit()

                    # copy by limit offset
                    start_time = time.perf_counter()
                    next_offset = 0
                    rows_inserted = 0
                    # pyodbc: rows = source_cur.execute(select_sql, next_offset, limit).fetchall()
                    source_cur.execute(select_sql, (next_offset, limit))
                    rows = source_cur.fetchall()    # psycopg2

                    while rows:
                        destination_cur.executemany(insert, rows)
                        destination_conn.commit()
                        rows_inserted += len(rows)
                        next_offset = next_offset + limit
                        # pyodbc: rows = source_cur.execute(select_sql, next_offset, limit).fetchall()
                        source_cur.execute(select_sql, (next_offset, limit))
                        rows = source_cur.fetchall()    # psycopg2

                    destination_conn.commit()

                    delta_time = time.perf_counter() - start_time
                    print('Tempo load: {:.4f} segundos'.format(delta_time))
                    print('Linhas inseridas: {}'.format(rows_inserted))
                    print('linhas/segundo: {}'.format(rows_inserted / delta_time))

def search_key_gaps(
                    source_provider: str,
                    source_conn_id: str,
                    source_table: str,
                    destination_provider: str,
                    destination_conn_id: str,
                    destination_table: str,
                    key_column: str,
                    key_start: int = 0,
                    key_interval: int = 100):
    """
    Verifica se existem lacunas de linhas entre intervalos de chaves,
    comparando tabela origem x tabela destino. Para cada intervalo, deve
    existir a mesma quantidade distinta de id's.

    Exemplo:
        search_key_gaps(
                        source_provider='PG',
                        source_conn_id='quartzo_comprasnet',
                        source_table='Comprasnet_VBL.tbl_pregao',
                        destination_provider='MSSQL',
                        destination_conn_id='mssql_srv_32_stg_comprasnet',
                        destination_table='dbo.tbl_pregao',
                        key_column='prgCod',
                        key_start=0,
                        key_interval=100000)

    Args:
        source_provider (str): provider do banco origem (MSSQL ou PG)
        source_conn_id (str): connection origem do Airflow
        source_table (str): tabela de origem no formato schema.table
        destination_provider (str): provider do banco destino (MSSQL ou PG)
        destination_conn_id (str): connection destino do Airflow
        destination_table (str): tabela de destino no formato schema.table
        key_column (str): nome da coluna chave da tabela origem
        key_start (int): id da chave a partir do qual a comparação é feita
        key_interval (int): intervalo de id's para ler da origem a cada vez
    """
    # validate db string
    validate_db_string(source_table, destination_table, None)

    # create connections
    with DbConnection(source_conn_id, source_provider) as source_conn:
        with DbConnection(destination_conn_id, destination_provider) \
            as destination_conn:
            with source_conn.cursor() as source_cur:
                with destination_conn.cursor() as destination_cur:

                    # gera queries
                    select_sql = f"""
                        SELECT COUNT(DISTINCT {key_column}) AS count_source
                        FROM {source_table}"""
                    # pyodbc: select_sql = f"{select_sql} WHERE {key_column} BETWEEN ? AND ?"
                    select_sql = f"{select_sql} WHERE {key_column} BETWEEN %s AND %s"
                    compare_sql = f"""
                        SELECT COUNT(DISTINCT {key_column}) AS count_dest
                        FROM {destination_table}"""
                    compare_sql = f"{compare_sql} WHERE {key_column} BETWEEN ? AND ?"
                    # psycopg2: compare_sql = f"{compare_sql} WHERE {key_column} BETWEEN %s AND %s"
                    lastkey_sql = f"""
                        SELECT MAX({key_column}) AS last_key
                        FROM {destination_table}"""

                    # compare by key interval
                    start_time = time.perf_counter()

                    rowlast = destination_cur.execute(lastkey_sql).fetchone()
                    # psycopg2: destination_cur.execute(lastkey_sql)
                    # psycopg2: rowlast = destination_cur.fetchone()
                    last_key = rowlast.last_key

                    gaps = totdif = 0
                    key_begin = key_start
                    key_end = key_begin + key_interval - 1
                    # pyodbc: rows = source_cur.execute(select_sql, key_begin, key_end).fetchone()
                    source_cur.execute(select_sql, (key_begin, key_end))
                    rows = source_cur.fetchone()

                    while rows:
                        rowsdest = destination_cur.execute(compare_sql, key_begin, key_end).fetchone()
                        # psycopg2: destination_cur.execute(compare_sql, (key_begin, key_end))
                        # psycopg2: rowsdest = destination_cur.fetchone()
                        print("Key interval:", key_begin, " to ", key_end,
                                time.strftime('%H:%M:%S', time.localtime()))
                        # pyodbc: count_source = rows.count_source
                        count_source = rows[0]  # psycopg2
                        if count_source != rowsdest.count_dest:
                            dif = count_source - rowsdest.count_dest
                            print("Gap!!! Source keys:", count_source,
                                    "Dest keys:", rowsdest.count_dest,
                                    "Difference:", dif)
                            gaps += 1
                            totdif += dif
                        key_begin = key_end + 1
                        key_end = key_begin + key_interval - 1
                        if key_begin > last_key:
                            break
                        # pyodbc: rows = source_cur.execute(select_sql, key_begin, key_end).fetchone()
                        source_cur.execute(select_sql, (key_begin, key_end))
                        rows = source_cur.fetchone()

                    delta_time = time.perf_counter() - start_time
                    print('Tempo do compare: {:.4f} segundos'.format(delta_time))
                    print("Resumo: ", gaps, "gaps, ", totdif, "rows faltam no destino!")
