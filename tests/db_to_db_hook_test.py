from datetime import datetime, date
import logging
import subprocess
import pytest

from airflow.hooks.dbapi import DbApiHook
from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.providers.odbc.hooks.odbc import OdbcHook

import pandas as pd
from pandas._testing import assert_frame_equal
from sqlalchemy import Table, Column, Integer, String, Date, Float, Boolean, MetaData
from pyodbc import ProgrammingError
from psycopg2.errors import UndefinedTable

from plugins.FastETL.hooks.db_to_db_hook import DbToDbHook


def _try_drop_table(table_name: str, hook: DbApiHook) -> None:
    logging.info('Tentando apagar a tabela %s.', table_name)
    try:
        hook.run(f'DROP TABLE {table_name};')
    except (UndefinedTable, ProgrammingError) as e:
        logging.info(e)


def _create_initial_table(table_name: str, hook: DbApiHook,
                          db_provider: str) -> None:
    filename = f'create_table_{db_provider.lower()}.sql'
    sql_stmt = open(f'/opt/airflow/tests/sql/init/{filename}').read()
    hook.run(sql_stmt.format(table_name=table_name))


def _insert_initial_source_table_n_data(table_name: str, hook: DbApiHook,
                                        db_provider: str) -> None:
    _create_initial_table(table_name, hook, db_provider)
    data = {'Name':['hendrix', 'nitai', 'krishna', 'jesus'],
            'Description':[
                "É um fato conhecido de todos que um leitor se distrairá com o conteúdo de texto legível de uma página quando estiver examinando sua diagramação. A vantagem de usar Lorem Ipsum é que ele tem uma distribuição normal de letras, ao contrário de Conteúdo aqui, conteúdo aqui, fazendo com que ele tenha uma aparência similar a de um texto legível.",
                "Muitos softwares de publicação e editores de páginas na internet agora usam Lorem Ipsum como texto-modelo padrão, e uma rápida busca por 'lorem ipsum' mostra vários websites ainda em sua fase de construção. Várias versões novas surgiram ao longo dos anos, eventualmente por acidente, e às vezes de propósito",
                "Existem muitas variações disponíveis de passagens de Lorem Ipsum, mas a maioria sofreu algum tipo de alteração, seja por inserção de passagens com humor, ou palavras aleatórias que não parecem nem um pouco convincentes. Se você pretende usar uma passagem de Lorem Ipsum, precisa ter certeza de que não há algo embaraçoso escrito ",
                "Ao contrário do que se acredita, Lorem Ipsum não é simplesmente um texto randômico. Com mais de 2000 anos, suas raízes podem ser encontradas em uma obra de literatura latina clássica datada de 45 AC. Richard McClintock, um professor de latim do Hampden-Sydney College na Virginia, pesquisou uma das mais obscuras palavras em latim, consectetur, oriunda de uma passagem de Lorem Ipsum, e, procurando por entre citações da palavra na literatura clássica, descobriu a sua"],
            'Description2':[
                "É um fato conhecido de todos que um leitor se distrairá com o conteúdo de texto legível de uma página quando estiver examinando sua diagramação. A vantagem de usar Lorem Ipsum é que ele tem uma distribuição normal de letras, ao contrário de Conteúdo aqui, conteúdo aqui, fazendo com que ele tenha uma aparência similar a de um texto legível.",
                "Muitos softwares de publicação e editores de páginas na internet agora usam Lorem Ipsum como texto-modelo padrão, e uma rápida busca por 'lorem ipsum' mostra vários websites ainda em sua fase de construção. Várias versões novas surgiram ao longo dos anos, eventualmente por acidente, e às vezes de propósito",
                "Existem muitas variações disponíveis de passagens de Lorem Ipsum, mas a maioria sofreu algum tipo de alteração, seja por inserção de passagens com humor, ou palavras aleatórias que não parecem nem um pouco convincentes. Se você pretende usar uma passagem de Lorem Ipsum, precisa ter certeza de que não há algo embaraçoso escrito ",
                "Ao contrário do que se acredita, Lorem Ipsum não é simplesmente um texto randômico. Com mais de 2000 anos, suas raízes podem ser encontradas em uma obra de literatura latina clássica datada de 45 AC. Richard McClintock, um professor de latim do Hampden-Sydney College na Virginia, pesquisou uma das mais obscuras palavras em latim, consectetur, oriunda de uma passagem de Lorem Ipsum, e, procurando por entre citações da palavra na literatura clássica, descobriu a sua"],
            'Age':[27, 38, 1000, 33],
            'Weight':[1000.0111111111111, 75.33, 333.33, 12345.54320091],
            'Birth':[
                date(1942, 11, 27),
                date(1983, 6, 2),
                date(3227, 6, 23),
                date(1, 12, 27)],
            'Active':[False, True, True, True],
            'date_time':[
                datetime(1942, 11, 27, 1, 2, 3),
                datetime(1983, 6, 2, 1, 2, 3),
                datetime(3227, 6, 23, 1, 2, 3),
                datetime(1, 12, 27, 1, 2, 3)],
            }

    pd.DataFrame(data).to_sql(name=table_name,
                              con=hook.get_sqlalchemy_engine(),
                              if_exists='append',
                              index=False)


@pytest.mark.parametrize(
    'source_conn_id, source_hook_cls, source_provider, dest_conn_id, dest_hook_cls, destination_provider, has_dest_table',
    [
        ('pg-source-conn', PostgresHook, 'PG', 'pg-destination-conn', PostgresHook, 'PG', True),
        ('mssql-source-conn', OdbcHook, 'MSSQL', 'mssql-destination-conn', OdbcHook, 'MSSQL', True),
        ('pg-source-conn', PostgresHook, 'PG', 'mssql-destination-conn', OdbcHook, 'MSSQL', True),
        ('mssql-source-conn', OdbcHook, 'MSSQL', 'pg-destination-conn', PostgresHook, 'PG', True),
        ('pg-source-conn', PostgresHook, 'PG', 'pg-destination-conn', PostgresHook, 'PG', False),
        ('mssql-source-conn', OdbcHook, 'MSSQL', 'mssql-destination-conn', OdbcHook, 'MSSQL', False),
        ('pg-source-conn', PostgresHook, 'PG', 'mssql-destination-conn', OdbcHook, 'MSSQL', False),
        ('mssql-source-conn', OdbcHook, 'MSSQL', 'pg-destination-conn', PostgresHook, 'PG', False),
    ])
def test_full_table_replication_various_db_types(
        source_conn_id: str,
        source_hook_cls: DbApiHook,
        source_provider: str,
        dest_conn_id: str,
        dest_hook_cls: DbApiHook,
        destination_provider: str,
        has_dest_table: bool):
    source_table_name = 'origin_table'
    dest_table_name = 'destination_table'
    source_hook = source_hook_cls(source_conn_id)
    dest_hook = dest_hook_cls(dest_conn_id)

    # Setup
    _try_drop_table(source_table_name, source_hook)
    _insert_initial_source_table_n_data(source_table_name,
                                        source_hook,
                                        source_provider)

    _try_drop_table(dest_table_name, dest_hook)
    if has_dest_table:
        _create_initial_table(dest_table_name,
                              dest_hook,
                              destination_provider)

    # source_schema = 'public' if source_provider == 'PG' else 'dbo'
    # destination_schema = 'public' if destination_provider == 'PG' else 'dbo'

    # # Run
    # DbToDbHook(
    #     source_conn_id=source_conn_id,
    #     destination_conn_id=dest_conn_id,
    #     source_provider=source_provider,
    #     destination_provider=destination_provider
    #     ).full_copy(
    #         source_table=f'{source_schema}.{source_table_name}',
    #         destination_table=f'{destination_schema}.{dest_table_name}',
    #     )
    task_id = f'test_from_{source_provider}_to_{destination_provider}'.lower()
    subprocess.run(['airflow', 'tasks', 'test', 'test_dag', task_id, '2021-01-01'])

    # Assert
    source_data = source_hook.get_pandas_df(f'select * from {source_table_name}')
    dest_data = dest_hook.get_pandas_df(f'select * from {dest_table_name}')

    assert_frame_equal(source_data, dest_data)
