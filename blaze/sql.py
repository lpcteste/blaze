from __future__ import absolute_import, division, print_function

from datashape.predicates import isscalar
import sqlalchemy
from sqlalchemy import Table, MetaData
from sqlalchemy.engine import Engine
from toolz import first, keyfilter

from .compute.sql import select
from .data.sql import dispatch, dshape_to_table
from .expr import Expr, Projection, Field, UnaryOp, BinOp, Join
from .compatibility import basestring, _strtypes
from .resource import resource
from .utils import keywords


import sqlalchemy as sa

__all__ = ()


def engine_of(x):
    if isinstance(x, Engine):
        return x
    if isinstance(x, MetaData):
        return x.bind
    if isinstance(x, Table):
        return x.metadata.bind
    raise NotImplementedError("Can't deterimine engine of %s" % x)


@dispatch(Expr, sa.sql.ClauseElement)
def post_compute(expr, query, scope=None):
    """ Execute SQLAlchemy query against SQLAlchemy engines

    If the result of compute is a SQLAlchemy query then it is likely that the
    data elements are themselves SQL objects which contain SQLAlchemy engines.
    We find these engines and, if they are all the same, run the query against
    these engines and return the result.
    """
    if not all(isinstance(val, (Engine, Table)) for val in scope.values()):
        return query

    engines = set(filter(None, map(engine_of, scope.values())))

    if not engines:
        return query

    if len(set(map(str, engines))) != 1:
        raise NotImplementedError("Expected single SQLAlchemy engine")

    engine = first(engines)

    with engine.connect() as conn:  # Perform query
        result = conn.execute(select(query)).fetchall()

    if isscalar(expr.dshape):
        return result[0][0]
    if isscalar(expr.dshape.measure):
        return [x[0] for x in result]
    return result


@dispatch(sqlalchemy.Table)
def drop(table):
    table.drop(table.bind)


@dispatch(sqlalchemy.Table, basestring)
def create_index(s, column, name=None, unique=False):
    if name is None:
        raise ValueError('SQL indexes must have a name')
    sa.Index(name, getattr(s.c, column), unique=unique).create(s.bind)


@dispatch(sqlalchemy.Table, list)
def create_index(s, columns, name=None, unique=False):
    if name is None:
        raise ValueError('SQL indexes must have a name')
    args = name,
    args += tuple(getattr(s.c, column) for column in columns)
    sa.Index(*args, unique=unique).create(s.bind)


@resource.register('(sqlite|postgresql|mysql|mysql\+pymysql)://.+')
def resource_sql(uri, *args, **kwargs):
    kwargs2 = keyfilter(keywords(sqlalchemy.create_engine).__contains__,
                       kwargs)
    engine = sqlalchemy.create_engine(uri, **kwargs2)
    if args and isinstance(args[0], _strtypes):
        table_name, args = args[0], args[1:]
        metadata = sqlalchemy.MetaData(engine)
        metadata.reflect()
        if table_name not in metadata.tables:
            if 'dshape' in kwargs:
                t = dshape_to_table(table_name, kwargs['dshape'], metadata)
                t.create()
                return t
            else:
                raise ValueError("Table does not exist and no dshape provided")
        return metadata.tables[table_name]
    else:
        return engine


@resource.register('impala://.+')
def resource_impala(uri, *args, **kwargs):
    try:
        import impala.sqlalchemy
    except ImportError:
        raise ImportError("Please install or update `impyla` library")
    return resource_sql(uri, *args, **kwargs)


from .compute.pyfunc import broadcast_collect
@dispatch(Expr, sa.sql.elements.ClauseElement)
def optimize(expr, _):
    return broadcast_collect(expr)
