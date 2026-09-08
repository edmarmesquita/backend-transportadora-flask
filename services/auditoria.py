import json
from copy import deepcopy

from extensions import db
from models.auditoria import LogAcao


def registrar_log(
    acao,
    detalhes="",
    modulo=None,
    entidade=None,
    entidade_id=None,
    antes=None,
    depois=None,
    usuario_id=None,
    usuario_nome=None,
    perfil=None,
    commit=False
):
    log = LogAcao(
        usuario_id=usuario_id,
        usuario_nome=usuario_nome,
        perfil=perfil,
        modulo=modulo,
        acao=acao,
        entidade=entidade,
        entidade_id=entidade_id,
        detalhes=detalhes,
        antes=json.dumps(
            antes,
            ensure_ascii=False,
            default=str
        ) if antes is not None else None,
        depois=json.dumps(
            depois,
            ensure_ascii=False,
            default=str
        ) if depois is not None else None
    )

    db.session.add(log)
    if commit:
        db.session.commit()

    return log


def snapshot_objeto(objeto, campos):
    """Serializa somente campos explicitamente aprovados para auditoria."""
    if objeto is None:
        return None

    return {
        campo: deepcopy(getattr(objeto, campo, None))
        for campo in campos
    }


def contexto_usuario(usuario):
    if not usuario:
        return {
            "usuario_id": None,
            "usuario_nome": None,
            "perfil": None,
        }

    return {
        "usuario_id": usuario.id,
        "usuario_nome": usuario.nome,
        "perfil": usuario.perfil,
    }
